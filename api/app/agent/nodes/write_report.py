"""write_report: Gemini writes the narrative; everything else is assembled deterministically (7.4)."""

from __future__ import annotations

from datetime import datetime

from app.agent import prompts
from app.agent.deps import AgentDeps, NodeResult
from app.agent.llm_outputs import LLMRequest, WriteReportOutput
from app.agent.policy import confidence_rank
from app.agent.state import BriefingState
from app.agent.timeline import build_timeline
from app.schemas import (
    DISCLAIMER,
    AuditEntry,
    Briefing,
    Condition,
    Conflict,
    DataMode,
    ExcludedOption,
    LLMProviderName,
    Region,
    Report,
    ReviewDecision,
    SearchStrategy,
    Source,
    TreatmentOption,
)
from app.store import utcnow

_LINE_ORDER = {"first_line": 0, "second_line": 1, "add_on": 2, "alternative": 3, "unspecified": 4}


def order_options(options: list[TreatmentOption]) -> list[TreatmentOption]:
    return sorted(
        options, key=lambda o: (_LINE_ORDER[o.line_of_therapy], -confidence_rank(o.confidence), o.name.lower())
    )


def report_sources(
    selected: list[TreatmentOption], conflicts: list[Conflict], sources: dict[str, Source]
) -> list[Source]:
    ids: set[str] = set()
    for o in selected:
        ids.update(e.source_id for e in o.evidence)
        ids.update(m.source_id for m in o.milestones)
    for c in conflicts:
        ids.update(p.source_id for p in c.positions)
    chosen = [sources[i] for i in ids if i in sources]
    # tier ascending, then published_at descending (undated last): stable two-pass sort
    chosen.sort(key=lambda s: s.published_at or "", reverse=True)
    chosen.sort(key=lambda s: s.reliability_tier)
    return chosen


def replay_deviation_note(options: list[TreatmentOption], conflicts: list[Conflict]) -> str | None:
    """Replay narratives are recorded for the AI-suggested path; flag a review that departed from it."""
    changed_options = sum(1 for o in options if o.selected != o.suggested)
    changed_conflicts = 0
    for c in conflicts:
        r, s = c.resolution, c.suggested_resolution
        if r is None or r.decision != s.decision or r.accepted_source_id != s.accepted_source_id:
            changed_conflicts += 1
    if not changed_options and not changed_conflicts:
        return None
    return (
        "Replay note: this narrative was recorded for the AI-suggested selection and conflict resolutions. "
        f"The reviewer changed {changed_options} option selection(s) and {changed_conflicts} conflict decision(s), "
        "so the treatment options table and conflict log below, not this text, reflect the review."
    )


def excluded_options(options: list[TreatmentOption], decision: ReviewDecision) -> list[ExcludedOption]:
    return [
        ExcludedOption(
            id=o.id,
            name=o.name,
            category=o.category,
            line_of_therapy=o.line_of_therapy,
            recommendation_direction=o.recommendation_direction,
            suggested=o.suggested,
            suggestion_reason=o.suggestion_reason,
            excluded_by=decision.reviewed_by,
            excluded_at=decision.reviewed_at,
        )
        for o in order_options([o for o in options if not o.selected])
    ]


def assemble_report(
    *,
    narrative: WriteReportOutput,
    model: str,
    condition: Condition,
    region: Region,
    options: list[TreatmentOption],
    conflicts: list[Conflict],
    all_sources: list[Source],
    audit_log: list[AuditEntry],
    decision: ReviewDecision,
    llm_provider: LLMProviderName,
    data_mode: DataMode,
    generated_at: datetime,
    research_started_at: datetime | None = None,
    research_completed_at: datetime | None = None,
    search_strategy: SearchStrategy | None = None,
) -> Report:
    by_id = {s.id: s for s in all_sources}
    selected = order_options([o for o in options if o.selected])
    srcs = report_sources(selected, conflicts, by_id)
    research_at = max((s.retrieved_at for s in all_sources), default=generated_at)
    timeline = build_timeline(srcs, selected, all_sources, data_mode, research_at)
    return Report(
        title=narrative.title,
        condition=condition,
        region=region,
        top_level_description=narrative.top_level_description,
        key_takeaways=narrative.key_takeaways,
        treatment_options=selected,
        excluded_options=excluded_options(options, decision),
        timeline=timeline,
        conflict_log=conflicts,
        audit_log=audit_log,
        sources=srcs,
        research_conducted_at=research_at,
        research_started_at=research_started_at,
        research_completed_at=research_completed_at,
        search_strategy=search_strategy,
        reviewed_by=decision.reviewed_by,
        reviewed_at=decision.reviewed_at,
        generated_at=generated_at,
        generated_by=decision.reviewed_by,
        model=model,
        llm_provider=llm_provider,
        data_mode=data_mode,
        disclaimer=DISCLAIMER,
    )


async def run(deps: AgentDeps, state: BriefingState) -> NodeResult:
    bid = state["briefing_id"]
    condition = Condition.model_validate(state["condition"])
    region: Region = state["region"]  # type: ignore[assignment]
    sources = [Source.model_validate(s) for s in state["sources"]]
    options = [TreatmentOption.model_validate(o) for o in state["options"]]
    conflicts = [Conflict.model_validate(c) for c in state.get("conflicts", [])]
    decision = ReviewDecision.model_validate(state["review"])
    research_at = max((s.retrieved_at for s in sources), default=utcnow())

    request = LLMRequest(
        step="write_report",
        system=prompts.REPORT_SYSTEM,
        prompt=prompts.report_prompt(
            condition.label,
            region,
            order_options([o for o in options if o.selected]),
            conflicts,
            {s.id: s for s in sources},
            research_at.date().isoformat(),
        ),
        fixture_slug=state.get("fixture_slug"),
    )
    result = await deps.call_llm(bid, request, WriteReportOutput)
    narrative = result.parsed
    if result.model == "replay" and (note := replay_deviation_note(options, conflicts)):
        narrative = narrative.model_copy(update={"key_takeaways": [note, *narrative.key_takeaways]})

    briefing = await deps.store.require_briefing(bid)
    now = utcnow()
    generated = AuditEntry(
        at=now,
        actor="system",
        action="report_generated",
        target_id=None,
        detail=f"Report generated with {result.model} for {decision.reviewed_by} "
        f"({sum(1 for o in options if o.selected)} options, {len(conflicts)} conflict(s)).",
    )
    report = assemble_report(
        narrative=narrative,
        model=result.model,
        condition=condition,
        region=region,
        options=options,
        conflicts=conflicts,
        all_sources=sources,
        audit_log=[*briefing.audit_log, generated],
        decision=decision,
        llm_provider=deps.settings.llm_provider,
        data_mode=deps.settings.data_mode,
        generated_at=now,
        research_started_at=briefing.research_started_at,
        research_completed_at=briefing.research_completed_at,
        search_strategy=briefing.search_strategy,
    )

    def patch(b: Briefing) -> None:
        b.audit_log.append(generated)
        b.report = report
        # status -> "completed" is set by the runner together with the run/completed event.

    return NodeResult(
        update={"report": report.model_dump(mode="json")},
        message=f"Report generated: {len(report.treatment_options)} options, {len(report.sources)} sources",
        detail=f"{len(report.treatment_options)} options, {len(report.timeline)} timeline events",
        data={"options": len(report.treatment_options), "sources": len(report.sources)},
        patch=patch,
    )
