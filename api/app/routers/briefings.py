"""Briefing lifecycle endpoints: create, list, read, events (SSE), review (HITL), retry, delete."""

from __future__ import annotations

import contextlib
import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from sse_starlette import EventSourceResponse, ServerSentEvent

from app.agent.deps import set_step
from app.agent.policy import slugify
from app.events import is_terminal_event
from app.schemas import (
    NODE_ORDER,
    AgentStep,
    AuditEntry,
    Briefing,
    BriefingStatus,
    BriefingSummary,
    Condition,
    ConflictResolution,
    CreateBriefingRequest,
    ReviewDecision,
    ReviewSubmission,
    RunInfo,
)
from app.store import utcnow
from app.users import CurrentUser, can_modify

router = APIRouter(prefix="/api/briefings", tags=["briefings"])


def _summary(b: Briefing) -> BriefingSummary:
    research_at = max((s.retrieved_at for s in b.sources), default=None)
    return BriefingSummary(
        id=b.id,
        condition_label=b.condition.label,
        region=b.region,
        status=b.status,
        created_by=b.created_by,
        created_at=b.created_at,
        updated_at=b.updated_at,
        source_count=len(b.sources),
        option_count=len(b.treatment_options),
        selected_option_count=sum(1 for o in b.treatment_options if o.selected),
        conflict_count=len(b.conflicts),
        open_conflict_count=sum(1 for c in b.conflicts if c.resolution is None),
        has_report=b.report is not None,
        research_conducted_at=research_at,
        data_mode=b.run.data_mode,
    )


async def _get_or_404(request: Request, briefing_id: str) -> Briefing:
    b = await request.app.state.store.get_briefing(briefing_id)
    if b is None:
        raise HTTPException(status_code=404, detail=f"Briefing '{briefing_id[:40]}' not found")
    return b


@router.post("", status_code=202, response_model=Briefing)
async def create_briefing(
    body: CreateBriefingRequest, request: Request, response: Response, user: CurrentUser
) -> Briefing:
    state = request.app.state
    settings = state.settings
    typed = " ".join(body.condition.split())
    _check_run_limits(request, user.id)
    briefing_id = f"brf_{secrets.token_hex(6)}"
    fixture_slug: str | None = None
    if settings.data_mode == "replay":
        manifest = state.replay.match(typed)
        if manifest is None:
            labels = ", ".join(m.label for m in state.replay.manifests()) or "none"
            raise HTTPException(
                status_code=400,
                detail=f"No replay fixture matches '{typed[:80]}'. Available conditions: {labels}",
            )
        fixture_slug = manifest.slug
    elif settings.record_fixtures:
        # Per-briefing recording folder under DATA_DIR/recordings (see app/llm/recorder.py).
        fixture_slug = f"{slugify(typed)}.{briefing_id}"

    now = utcnow()
    model, model_lite = settings.model_names
    briefing = Briefing(
        id=briefing_id,
        condition=Condition(input=typed, label=typed, mesh_id=None, synonyms=[]),
        region=body.region,
        status="researching",
        created_by=user.id,
        created_at=now,
        updated_at=now,
        audit_log=[
            AuditEntry(
                at=now,
                actor=user.id,
                action="briefing_created",
                target_id=None,
                detail=f"Briefing created for '{typed}' (region {body.region}, {settings.data_mode} data).",
            )
        ],
        run=RunInfo(
            llm_provider=settings.llm_provider,
            data_mode=settings.data_mode,
            model=model,
            model_lite=model_lite,
            steps=[AgentStep(name=n) for n in NODE_ORDER],
        ),
    )
    await state.store.insert_briefing(briefing)
    await state.events.emit(briefing.id, "run", "started", f"Research started for '{typed}' by {user.id}")
    state.runner.start(briefing.id, condition_input=typed, region=body.region, fixture_slug=fixture_slug, owner=user.id)
    response.headers["Location"] = f"/api/briefings/{briefing.id}"
    return briefing


def _check_run_limits(request: Request, user_id: str) -> None:
    """429 when too many runs are active (globally / per user) or the user creates briefings too fast.

    Each live run makes a dozen or more Gemini calls and there is no auth, so these are cost guards.
    """
    state = request.app.state
    settings = state.settings
    runner = state.runner
    if runner.active_runs() >= settings.max_active_runs:
        raise HTTPException(
            status_code=429,
            detail=f"{settings.max_active_runs} briefings are already running; try again when one finishes",
            headers={"Retry-After": "30"},
        )
    if runner.active_runs(user_id) >= settings.max_active_runs_per_user:
        raise HTTPException(
            status_code=429,
            detail=f"You already have {settings.max_active_runs_per_user} briefings running",
            headers={"Retry-After": "30"},
        )
    wait = state.create_bucket.take(user_id)
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail="Too many new briefings; please wait a moment",
            headers={"Retry-After": str(max(1, round(wait)))},
        )


@router.get("", response_model=list[BriefingSummary])
async def list_briefings(
    request: Request,
    _user: CurrentUser,
    created_by: str | None = None,
    status: BriefingStatus | None = None,
) -> list[BriefingSummary]:
    items = await request.app.state.store.list_briefings(created_by=created_by or None, status=status)
    return [_summary(b) for b in items]


@router.get("/{briefing_id}", response_model=Briefing)
async def get_briefing(briefing_id: str, request: Request) -> Briefing:
    return await _get_or_404(request, briefing_id)


@router.get("/{briefing_id}/events")
async def stream_events(
    briefing_id: str,
    request: Request,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    await _get_or_404(request, briefing_id)
    bus = request.app.state.events
    start = after_seq if after_seq is not None else (int(last_event_id) if (last_event_id or "").isdigit() else 0)

    async def gen() -> AsyncIterator[ServerSentEvent]:
        async with bus.subscribe(briefing_id) as queue:
            last = start
            history, current = await bus.snapshot(briefing_id, start)
            for ev in history:
                last = ev.seq
                yield ServerSentEvent(data=ev.model_dump_json(), id=str(ev.seq), sep="\n")
            if current is None or current.status in ("awaiting_review", "completed", "failed"):
                return
            while True:
                ev = await queue.get()
                if ev.seq <= last:
                    continue
                last = ev.seq
                yield ServerSentEvent(data=ev.model_dump_json(), id=str(ev.seq), sep="\n")
                if is_terminal_event(ev):
                    return

    return EventSourceResponse(
        gen(),
        ping=15,
        send_timeout=30,  # drop readers that stop reading instead of holding the stream forever
        sep="\n",
        ping_message_factory=lambda: ServerSentEvent(comment="ping", sep="\n"),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class _Conflict409(Exception):
    pass


@router.post("/{briefing_id}/review", status_code=202, response_model=Briefing)
async def submit_review(briefing_id: str, body: ReviewSubmission, request: Request, user: CurrentUser) -> Briefing:
    state = request.app.state
    briefing = await _get_or_404(request, briefing_id)
    if not can_modify(user, briefing):
        raise HTTPException(status_code=403, detail="Only the briefing's creator or an admin can review it")
    if briefing.status != "awaiting_review":
        raise HTTPException(status_code=409, detail=f"Briefing is '{briefing.status}', not awaiting review")

    # 400 checks
    selected = list(dict.fromkeys(body.selected_option_ids))
    if not selected:
        raise HTTPException(status_code=400, detail="Select at least one treatment option for the report")
    known_options = {o.id for o in briefing.treatment_options}
    unknown = [o for o in selected if o not in known_options]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown option id(s): {', '.join(unknown[:10])}")
    conflicts = {c.id: c for c in briefing.conflicts}
    seen: set[str] = set()
    for r in body.conflict_resolutions:
        if r.conflict_id not in conflicts:
            raise HTTPException(status_code=400, detail=f"Unknown conflict id: {r.conflict_id}")
        if r.conflict_id in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate resolution for conflict {r.conflict_id}")
        seen.add(r.conflict_id)
        if r.accepted_source_id is not None:
            allowed = {p.source_id for p in conflicts[r.conflict_id].positions}
            if r.accepted_source_id not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"accepted_source_id {r.accepted_source_id} is not a position of {r.conflict_id}",
                )
    missing = [cid for cid in conflicts if cid not in seen]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Every conflict needs a human decision; unresolved: {', '.join(missing[:10])}",
        )
    for r in body.conflict_resolutions:
        sugg = conflicts[r.conflict_id].suggested_resolution
        overrides = r.decision != sugg.decision or (
            r.decision == "accept_source" and r.accepted_source_id != sugg.accepted_source_id
        )
        if overrides and not r.note.strip():
            raise HTTPException(
                status_code=400,
                detail=f"A note is required when overriding the AI suggestion ({r.conflict_id})",
            )
    # The review resumes a LangGraph checkpoint. If it is gone (lost volume, DATA_DIR change, another
    # instance), resuming would silently re-run the graph from START with empty state.
    if not await state.runner.is_paused_for_review(briefing_id):
        raise HTTPException(
            status_code=409,
            detail="The saved research state for this briefing was not found (checkpoint lost); "
            "start a new briefing for this condition",
        )

    now = utcnow()
    decision = ReviewDecision(
        selected_option_ids=selected,
        conflict_resolutions={
            r.conflict_id: ConflictResolution(
                decision=r.decision,
                accepted_source_id=r.accepted_source_id,
                note=r.note.strip(),
                resolved_by=user.id,
                resolved_at=now,
            )
            for r in body.conflict_resolutions
        },
        reviewed_by=user.id,
        reviewed_at=now,
    )

    def start_generation(b: Briefing) -> None:
        if b.status != "awaiting_review":  # lost a race with a concurrent submission
            raise _Conflict409(b.status)
        b.status = "generating_report"
        b.reviewed_by = user.id
        b.reviewed_at = now
        set_step(b, "human_review", "completed", f"Reviewed by {user.id}")

    try:
        await state.events.transition(
            briefing_id, start_generation, "human_review", "completed", f"Review submitted by {user.id}"
        )
    except _Conflict409 as exc:
        raise HTTPException(status_code=409, detail=f"Briefing is '{exc}', not awaiting review") from exc
    updated = await state.store.require_briefing(briefing_id)
    state.runner.resume(briefing_id, decision.model_dump(mode="json"), owner=user.id)
    return updated


@router.post("/{briefing_id}/retry", status_code=202, response_model=Briefing)
async def retry_briefing(briefing_id: str, request: Request, user: CurrentUser) -> Briefing:
    """Resume a failed run from its last LangGraph checkpoint (the node that failed or was interrupted)."""
    state = request.app.state
    briefing = await _get_or_404(request, briefing_id)
    if not can_modify(user, briefing):
        raise HTTPException(status_code=403, detail="Only the briefing's creator or an admin can retry it")
    if briefing.status != "failed":
        raise HTTPException(status_code=409, detail=f"Briefing is '{briefing.status}'; only failed runs can be retried")
    if briefing_id in state.runner.tasks:
        raise HTTPException(status_code=409, detail="This briefing is already running")
    nxt = await state.runner.next_nodes(briefing_id)
    if not nxt:
        raise HTTPException(
            status_code=409,
            detail="No checkpoint to resume from for this briefing; start a new briefing instead",
        )
    if nxt == ("human_review",):
        await state.runner.mark_awaiting_review(briefing_id, f" (restored by {user.id})")
        return await state.store.require_briefing(briefing_id)
    _check_run_limits(request, user.id)
    reviewed = briefing.reviewed_at is not None

    def restart(b: Briefing) -> None:
        b.status = "generating_report" if reviewed else "researching"
        b.error = None

    await state.events.transition(
        briefing_id, restart, "run", "started", f"Retry by {user.id}: resuming at {', '.join(nxt)}"
    )
    state.runner.retry(briefing_id, owner=user.id)
    return await state.store.require_briefing(briefing_id)


@router.delete("/{briefing_id}", status_code=204)
async def delete_briefing(briefing_id: str, request: Request, user: CurrentUser) -> Response:
    state = request.app.state
    briefing = await _get_or_404(request, briefing_id)
    if not can_modify(user, briefing):
        raise HTTPException(status_code=403, detail="Only the briefing's creator or an admin can delete it")
    await state.runner.cancel(briefing_id)
    if briefing.status in ("researching", "generating_report"):
        # Close open SSE streams with a terminal event before the history disappears.
        with contextlib.suppress(KeyError):
            await state.events.emit(briefing_id, "run", "failed", f"Briefing deleted by {user.id}")
    await state.store.delete_briefing(briefing_id)
    await state.runner.delete_thread(briefing_id)
    state.events.forget(briefing_id)
    return Response(status_code=204)
