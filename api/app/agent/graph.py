"""StateGraph build + background runner (start / pause detection / resume). docs/CONTRACT.md section 7."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from itertools import pairwise
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.agent.deps import AgentDeps, instrument, one_line, set_step
from app.agent.nodes import (
    consolidate_options,
    detect_conflicts,
    extract_treatments,
    human_review,
    normalize_condition,
    retrieve_sources,
    suggest_relevance,
    write_report,
)
from app.agent.state import BriefingState
from app.llm.recorder import promote_recording
from app.schemas import NODE_ORDER, Briefing

logger = logging.getLogger(__name__)


def build_graph(deps: AgentDeps) -> StateGraph:
    g: StateGraph = StateGraph(BriefingState)
    g.add_node("normalize_condition", instrument(deps, "normalize_condition", normalize_condition.run))
    g.add_node("retrieve_sources", instrument(deps, "retrieve_sources", retrieve_sources.run))
    g.add_node("extract_treatments", instrument(deps, "extract_treatments", extract_treatments.run))
    g.add_node("consolidate_options", instrument(deps, "consolidate_options", consolidate_options.run))
    g.add_node("detect_conflicts", instrument(deps, "detect_conflicts", detect_conflicts.run))
    g.add_node("suggest_relevance", instrument(deps, "suggest_relevance", suggest_relevance.run))
    g.add_node("human_review", human_review.make_node(deps))
    g.add_node("write_report", instrument(deps, "write_report", write_report.run))
    g.add_edge(START, NODE_ORDER[0])
    for a, b in pairwise(NODE_ORDER):
        g.add_edge(a, b)
    g.add_edge(NODE_ORDER[-1], END)
    return g


class AgentRunner:
    """Runs the compiled graph as background asyncio tasks, one thread per briefing (thread_id = briefing id)."""

    def __init__(self, deps: AgentDeps, checkpointer: BaseCheckpointSaver) -> None:
        self.deps = deps
        self.checkpointer = checkpointer
        self.graph: CompiledStateGraph = build_graph(deps).compile(checkpointer=checkpointer)
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.owners: dict[str, str] = {}
        """briefing id -> user id of whoever started the active task (for per-user run caps)."""

    @staticmethod
    def config(briefing_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": briefing_id}}

    def active_runs(self, user_id: str | None = None) -> int:
        live = [b for b, t in self.tasks.items() if not t.done()]
        return len(live) if user_id is None else sum(1 for b in live if self.owners.get(b) == user_id)

    def start(
        self,
        briefing_id: str,
        *,
        condition_input: str,
        region: str,
        fixture_slug: str | None,
        owner: str = "",
    ) -> None:
        state: BriefingState = {
            "briefing_id": briefing_id,
            "fixture_slug": fixture_slug,
            "condition_input": condition_input,
            "region": region,
            "review": None,
            "report": None,
        }
        self._spawn(briefing_id, state, owner)

    def resume(self, briefing_id: str, decision: dict[str, Any], owner: str = "") -> None:
        self._spawn(briefing_id, Command(resume=decision), owner)

    def retry(self, briefing_id: str, owner: str = "") -> None:
        """Re-run from the last checkpoint (the node that failed or was interrupted)."""
        self._spawn(briefing_id, None, owner)

    def _spawn(self, briefing_id: str, payload: Any, owner: str = "") -> None:
        task = asyncio.create_task(self._drive(briefing_id, payload), name=f"briefing-{briefing_id}")
        self.tasks[briefing_id] = task
        self.owners[briefing_id] = owner

        def _forget(t: asyncio.Task[None]) -> None:
            if self.tasks.get(briefing_id) is t:
                self.tasks.pop(briefing_id, None)
                self.owners.pop(briefing_id, None)

        task.add_done_callback(_forget)

    async def wait(self, briefing_id: str) -> None:
        task = self.tasks.get(briefing_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def cancel(self, briefing_id: str) -> None:
        task = self.tasks.pop(briefing_id, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def delete_thread(self, briefing_id: str) -> None:
        await self.checkpointer.adelete_thread(briefing_id)

    async def next_nodes(self, briefing_id: str) -> tuple[str, ...]:
        """Nodes the checkpoint would run next; () if the thread is finished or has no checkpoint."""
        snap = await self.graph.aget_state(self.config(briefing_id))
        return tuple(snap.next)

    async def is_paused_for_review(self, briefing_id: str) -> bool:
        return await self.next_nodes(briefing_id) == ("human_review",)

    async def mark_awaiting_review(self, briefing_id: str, note: str = "") -> None:
        briefing = await self.deps.store.require_briefing(briefing_id)
        n_sel = sum(1 for o in briefing.treatment_options if o.suggested)
        await self.deps.events.transition(
            briefing_id,
            _mark_awaiting_review,
            "human_review",
            "awaiting_review",
            f"Awaiting human review: {len(briefing.treatment_options)} options ({n_sel} suggested), "
            f"{len(briefing.conflicts)} conflict(s) to resolve{note}",
            {
                "options": len(briefing.treatment_options),
                "suggested": n_sel,
                "conflicts": len(briefing.conflicts),
            },
        )

    async def _drive(self, briefing_id: str, payload: Any) -> None:
        deps = self.deps
        config = self.config(briefing_id)
        try:
            await self.graph.ainvoke(payload, config)
            snap = await self.graph.aget_state(config)
            if tuple(snap.next) == ("human_review",):
                await self.mark_awaiting_review(briefing_id)
            elif not snap.next:
                self._promote_recording(snap.values.get("fixture_slug"))
                await deps.events.transition(briefing_id, _mark_completed, "run", "completed", "Briefing completed")
            else:  # pragma: no cover - defensive
                raise RuntimeError(f"Graph stopped unexpectedly before {snap.next}")
        except asyncio.CancelledError:
            logger.info("Run for %s cancelled", briefing_id)
            raise
        except Exception as exc:
            msg = one_line(exc)
            logger.warning("Run for %s failed: %s", briefing_id, msg)

            def fail(b: Briefing) -> None:
                b.status = "failed"
                b.error = msg

            with contextlib.suppress(KeyError):  # deleted meanwhile
                await deps.events.transition(briefing_id, fail, "run", "failed", msg)

    def _promote_recording(self, recording_key: str | None) -> None:
        s = self.deps.settings
        if not (s.record_fixtures and s.data_mode == "live" and recording_key):
            return
        try:
            promote_recording(s.recordings_path, recording_key, s.fixtures_path, overwrite=s.record_overwrite)
        except OSError as exc:
            logger.warning("Could not promote recording %s: %s", recording_key, type(exc).__name__)


def _mark_completed(b: Briefing) -> None:
    b.status = "completed"


def _mark_awaiting_review(b: Briefing) -> None:
    b.status = "awaiting_review"
    set_step(b, "human_review", "running", "Waiting for a human to select options and resolve conflicts")
