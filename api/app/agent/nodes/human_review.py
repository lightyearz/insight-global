"""human_review: LangGraph ``interrupt()``; resumed with a ReviewDecision dict.

Not wrapped by ``instrument``: the node re-executes from its start on resume, so the
pause itself is detected and announced by the runner (docs/CONTRACT.md section 7).
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.agent.deps import AgentDeps, set_step
from app.agent.state import BriefingState
from app.schemas import AuditEntry, Briefing, Conflict, ReviewDecision, Source, TreatmentOption

_DECISION_LABEL = {
    "accept_source": "accepted",
    "accept_both_with_context": "kept both positions with context",
    "exclude_topic": "excluded topic from the report narrative",
    "custom": "custom resolution",
}


def source_label(source: Source | None, source_id: str) -> str:
    """Readable source reference for audit text, e.g. 'American College of Physicians, 2024 (pubmed:38639546)'."""
    if source is None:
        return source_id
    year = (source.updated_at or source.published_at or "undated")[:4]
    return f"{source.issuing_body or source.publisher}, {year} ({source_id})"


def apply_decision(
    options: list[TreatmentOption],
    conflicts: list[Conflict],
    decision: ReviewDecision,
    sources: dict[str, Source] | None = None,
) -> tuple[list[TreatmentOption], list[Conflict], list[AuditEntry]]:
    sources = sources or {}
    actor, at = decision.reviewed_by, decision.reviewed_at
    selected = set(decision.selected_option_ids)
    audit = [
        AuditEntry(
            at=at,
            actor=actor,
            action="review_submitted",
            target_id=None,
            detail=f"Selected {len(selected & {o.id for o in options})} of {len(options)} options; "
            f"resolved {len(decision.conflict_resolutions)} conflict(s).",
        )
    ]
    for o in options:
        o.selected = o.id in selected
        agreed = "matches" if o.selected == o.suggested else "overrides"
        audit.append(
            AuditEntry(
                at=at,
                actor=actor,
                action="option_selected" if o.selected else "option_excluded",
                target_id=o.id,
                detail=f"{o.name}: {'included' if o.selected else 'excluded'} ({agreed} AI suggestion).",
            )
        )
    for c in conflicts:
        res = decision.conflict_resolutions.get(c.id)
        if res is None:
            continue
        c.resolution = res
        what = _DECISION_LABEL[res.decision]
        if res.accepted_source_id:
            what += f" {source_label(sources.get(res.accepted_source_id), res.accepted_source_id)}"
        follows = (
            res.decision == c.suggested_resolution.decision
            and res.accepted_source_id == c.suggested_resolution.accepted_source_id
        )
        detail = f"{c.topic}: {what} ({'follows' if follows else 'differs from'} suggested resolution)."
        if res.note:
            detail += f" Note: {res.note}"
        audit.append(AuditEntry(at=at, actor=actor, action="conflict_resolved", target_id=c.id, detail=detail))
    return options, conflicts, audit


def make_node(deps: AgentDeps):
    async def human_review(state: BriefingState) -> dict[str, Any]:
        bid = state["briefing_id"]
        # response_schema documents the resume value and validates it (pydantic) before we use it.
        decision = interrupt({"kind": "human_review", "briefing_id": bid}, response_schema=ReviewDecision)
        if not isinstance(decision, ReviewDecision):  # pragma: no cover - defensive
            decision = ReviewDecision.model_validate(decision)
        options = [TreatmentOption.model_validate(o) for o in state["options"]]
        conflicts = [Conflict.model_validate(c) for c in state.get("conflicts", [])]
        sources = {s["id"]: Source.model_validate(s) for s in state.get("sources", [])}
        options, conflicts, audit = apply_decision(options, conflicts, decision, sources)

        def patch(b: Briefing) -> None:
            b.treatment_options = options
            b.conflicts = conflicts
            b.reviewed_by = decision.reviewed_by
            b.reviewed_at = decision.reviewed_at
            b.audit_log.extend(audit)
            set_step(b, "human_review", "completed", f"Reviewed by {decision.reviewed_by}")

        await deps.store.mutate(bid, patch)
        return {
            "options": [o.model_dump(mode="json") for o in options],
            "conflicts": [c.model_dump(mode="json") for c in conflicts],
            "review": decision.model_dump(mode="json"),
        }

    return human_review
