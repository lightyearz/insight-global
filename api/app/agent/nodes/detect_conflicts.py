"""detect_conflicts: LLM detection + deterministic validation and suggested resolution (section 7.3)."""

from __future__ import annotations

import re

from app.agent import prompts
from app.agent.deps import AgentDeps, NodeResult
from app.agent.llm_outputs import DetectConflictsOutput, LLMRequest, is_grounded
from app.agent.policy import slugify, suggest_resolution, unique_id
from app.agent.state import BriefingState
from app.schemas import (
    CONFLICT_ID_PATTERN,
    Briefing,
    Condition,
    Conflict,
    ConflictPosition,
    Region,
    Source,
    TreatmentOption,
)


def build_conflicts(
    output: DetectConflictsOutput,
    sources: dict[str, Source],
    option_ids: set[str],
    region: Region,
) -> list[Conflict]:
    taken: set[str] = set()
    conflicts: list[Conflict] = []
    for c in output.conflicts:
        detected = [p for p in c.positions if p.source_id in sources]
        # One position per source (the first one the model gave).
        detected = list({p.source_id: p for p in reversed(detected)}.values())[::-1]
        if len(detected) < 2:
            continue
        sides = [p.side if p.side >= 1 else 1 for p in detected]
        if len(set(sides)) < 2:
            # The model said these disagree but put every source on one side: treat each source as its own
            # side rather than silently comparing sources that may agree.
            sides = list(range(1, len(detected) + 1))
        # Renumber sides 1..n in order of first appearance.
        order: dict[int, int] = {}
        for sd in sides:
            order.setdefault(sd, len(order) + 1)
        positions = sorted(
            (
                ConflictPosition(
                    source_id=p.source_id,
                    side=order[sd],
                    statement=p.statement,
                    quote=p.quote,
                    published_at=sources[p.source_id].published_at,
                    reliability_tier=sources[p.source_id].reliability_tier,
                    grounded=is_grounded(p.quote, sources[p.source_id].excerpt),
                )
                for p, sd in zip(detected, sides, strict=True)
            ),
            key=lambda pos: pos.side,
        )
        candidate = c.id.strip().lower()
        if not re.fullmatch(CONFLICT_ID_PATTERN, candidate):
            candidate = f"conf-{slugify(c.topic)}"
        conflicts.append(
            Conflict(
                id=unique_id(candidate, taken),
                topic=c.topic,
                conflict_type=c.conflict_type,
                treatment_option_ids=[o for o in dict.fromkeys(c.treatment_option_ids) if o in option_ids],
                positions=positions,
                ai_assessment=c.ai_assessment,
                suggested_resolution=suggest_resolution(c.conflict_type, positions, sources, region),
                resolution=None,
            )
        )
    return conflicts


async def run(deps: AgentDeps, state: BriefingState) -> NodeResult:
    bid = state["briefing_id"]
    condition = Condition.model_validate(state["condition"])
    sources = {s["id"]: Source.model_validate(s) for s in state["sources"]}
    options = [TreatmentOption.model_validate(o) for o in state["options"]]
    cited = {e.source_id for o in options for e in o.evidence}
    cited_sources = [s for sid, s in sources.items() if sid in cited]

    request = LLMRequest(
        step="detect_conflicts",
        system=prompts.CONFLICTS_SYSTEM,
        prompt=prompts.conflicts_prompt(condition.label, state["region"], options, cited_sources),
        fixture_slug=state.get("fixture_slug"),
    )
    result = await deps.call_llm(bid, request, DetectConflictsOutput)
    conflicts = build_conflicts(result.parsed, sources, {o.id for o in options}, state["region"])  # type: ignore[arg-type]

    def patch(b: Briefing) -> None:
        b.conflicts = conflicts

    detail = f"{len(conflicts)} conflict(s) need a human decision" if conflicts else "No conflicts detected"
    return NodeResult(
        update={"conflicts": [c.model_dump(mode="json") for c in conflicts]},
        message=detail,
        detail=detail,
        data={"conflicts": len(conflicts)},
        patch=patch,
    )
