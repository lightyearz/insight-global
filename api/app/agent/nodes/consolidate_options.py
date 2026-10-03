"""consolidate_options: LLM merge + deterministic post-processing (docs/CONTRACT.md section 7.2)."""

from __future__ import annotations

import re
from typing import Any

from app.agent import prompts
from app.agent.deps import AgentDeps, NodeResult
from app.agent.llm_outputs import (
    ConsolidatedOption,
    ConsolidateOptionsOutput,
    ExtractedTreatment,
    ExtractTreatmentsOutput,
    LLMRequest,
    is_grounded,
)
from app.agent.policy import cap_confidence, recommendation_direction, slugify, unique_id
from app.agent.state import BriefingState
from app.schemas import (
    OPTION_ID_PATTERN,
    PARTIAL_DATE_PATTERN,
    Briefing,
    Condition,
    Evidence,
    Source,
    TreatmentMilestone,
    TreatmentOption,
    date_precision_of,
)

NO_OPTIONS_MESSAGE = "No treatment options could be extracted from the retrieved sources"


def treatments_by_ref(extractions: dict[str, ExtractTreatmentsOutput]) -> dict[str, tuple[str, ExtractedTreatment]]:
    refs: dict[str, tuple[str, ExtractedTreatment]] = {}
    for sid, ext in extractions.items():
        for i, t in enumerate(ext.treatments):
            refs[f"{sid}#{i}"] = (sid, t)
    return refs


def llm_items(refs: dict[str, tuple[str, ExtractedTreatment]], sources: dict[str, Source]) -> list[dict[str, Any]]:
    items = []
    for ref, (sid, t) in refs.items():
        s = sources[sid]
        items.append(
            {
                "ref": ref,
                "source_tier": s.reliability_tier,
                "source_date": s.updated_at or s.published_at,
                "name": t.name,
                "category": t.category,
                "drug_class": t.drug_class,
                "line_of_therapy": t.line_of_therapy,
                "population": t.population,
                "summary": t.summary,
                "evidence": [
                    {
                        "statement": e.statement,
                        "stance": e.stance,
                        "strength": e.recommendation_strength,
                        "level": e.evidence_level,
                    }
                    for e in t.evidence
                ],
            }
        )
    return items


def build_options(
    output: ConsolidateOptionsOutput,
    extractions: dict[str, ExtractTreatmentsOutput],
    sources: dict[str, Source],
) -> list[TreatmentOption]:
    refs = treatments_by_ref(extractions)
    used: set[str] = set()
    taken: set[str] = set()
    options: list[TreatmentOption] = []

    proposals: list[tuple[ConsolidatedOption, list[str]]] = []
    for opt in output.options:
        # A ref belongs to exactly one option: later options cannot re-use a ref (no duplicated evidence).
        valid = [r for r in dict.fromkeys(opt.member_refs) if r in refs and r not in used]
        if valid:
            proposals.append((opt, valid))
            used.update(valid)
    # Anything the model did not place becomes its own option, so nothing is silently lost.
    for ref, (_sid, t) in refs.items():
        if ref not in used:
            orphan = ConsolidatedOption(
                id=f"opt-{slugify(t.name)}",
                name=t.name,
                category=t.category,
                drug_class=t.drug_class,
                line_of_therapy=t.line_of_therapy,
                population=t.population,
                summary=t.summary,
                member_refs=[ref],
                confidence="low",
            )
            proposals.append((orphan, [ref]))

    for opt, member_refs in proposals:
        evidence: list[Evidence] = []
        milestones: list[TreatmentMilestone] = []
        for ref in member_refs:
            sid, t = refs[ref]
            excerpt = sources[sid].excerpt
            for e in t.evidence:
                evidence.append(
                    Evidence(
                        source_id=sid,
                        quote=e.quote,
                        statement=e.statement,
                        recommendation_strength=e.recommendation_strength,
                        evidence_level=e.evidence_level,
                        stance=e.stance,
                        grounded=is_grounded(e.quote, excerpt),
                    )
                )
            for m in t.milestones:
                date = m.date.strip()
                if not re.fullmatch(PARTIAL_DATE_PATTERN, date):
                    continue
                milestones.append(
                    TreatmentMilestone(
                        date=date,
                        date_precision=date_precision_of(date),
                        label=m.label,
                        source_id=sid,
                        quote=m.quote,
                        grounded=is_grounded(m.quote, excerpt),
                    )
                )
        if not evidence:
            continue
        candidate = opt.id.strip().lower()
        if not re.fullmatch(OPTION_ID_PATTERN, candidate):
            candidate = f"opt-{slugify(opt.name)}"
        options.append(
            TreatmentOption(
                id=unique_id(candidate, taken),
                name=opt.name,
                category=opt.category,
                drug_class=opt.drug_class,
                line_of_therapy=opt.line_of_therapy,
                population=opt.population,
                summary=opt.summary,
                evidence=evidence,
                milestones=milestones,
                recommendation_direction=recommendation_direction(evidence),
                confidence=cap_confidence(opt.confidence, evidence, sources),
                suggested=False,
                suggestion_reason="",
                selected=False,
            )
        )
    return options


async def run(deps: AgentDeps, state: BriefingState) -> NodeResult:
    bid = state["briefing_id"]
    condition = Condition.model_validate(state["condition"])
    sources = {s["id"]: Source.model_validate(s) for s in state["sources"]}
    extractions = {sid: ExtractTreatmentsOutput.model_validate(e) for sid, e in state["extractions"].items()}
    refs = treatments_by_ref(extractions)
    if not refs:
        raise RuntimeError(NO_OPTIONS_MESSAGE)

    request = LLMRequest(
        step="consolidate_options",
        system=prompts.CONSOLIDATE_SYSTEM,
        prompt=prompts.consolidate_prompt(condition.label, state["region"], llm_items(refs, sources)),
        fixture_slug=state.get("fixture_slug"),
    )
    result = await deps.call_llm(bid, request, ConsolidateOptionsOutput)
    options = build_options(result.parsed, extractions, sources)
    if not options:
        raise RuntimeError(NO_OPTIONS_MESSAGE)

    def patch(b: Briefing) -> None:
        b.treatment_options = options

    ungrounded = sum(1 for o in options for e in o.evidence if not e.grounded)
    detail = f"{len(options)} options from {len(refs)} extracted treatments"
    if ungrounded:
        detail += f"; {ungrounded} evidence quote(s) failed the grounding check"
    return NodeResult(
        update={"options": [o.model_dump(mode="json") for o in options]},
        message=f"Consolidated into {len(options)} treatment options",
        detail=detail,
        data={"options": len(options), "ungrounded_evidence": ungrounded},
        patch=patch,
    )
