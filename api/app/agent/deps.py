"""Dependencies injected into graph nodes (closure, no globals) and the node instrumentation wrapper."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from app.agent.llm_outputs import LLMClient, LLMError, LLMRequest, LLMResult
from app.agent.state import BriefingState
from app.config import Settings
from app.connectors.http import HttpClient
from app.connectors.medlineplus import MedlinePlusConnector
from app.connectors.pubmed import PubMedConnector
from app.connectors.replay import ReplayConnector
from app.events import EventBus
from app.llm.pricing import estimate_cost_usd
from app.schemas import AgentStep, Briefing, NodeName, StepStatus
from app.store import Store, utcnow

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class AgentDeps:
    settings: Settings
    store: Store
    events: EventBus
    llm: LLMClient
    replay: ReplayConnector
    http: HttpClient | None = None
    pubmed: PubMedConnector | None = None
    medlineplus: MedlinePlusConnector | None = None
    llm_semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(4))

    async def call_llm(self, briefing_id: str, request: LLMRequest, output_model: type[T]) -> LLMResult[T]:
        """Bounded-concurrency LLM call; accumulates tokens and cost on ``briefing.run``, including the
        usage of attempts that ultimately failed (billed all the same)."""
        model, tokens_in, tokens_out, version = "", 0, 0, None
        try:
            async with self.llm_semaphore:
                result = await self.llm.generate(request, output_model)
            model, tokens_in, tokens_out, version = (
                result.model,
                result.tokens_in,
                result.tokens_out,
                result.model_version,
            )
            return result
        except LLMError as exc:
            model, tokens_in, tokens_out = exc.model, exc.tokens_in, exc.tokens_out
            raise
        finally:
            if tokens_in or tokens_out or version:
                await self._add_usage(briefing_id, model, tokens_in, tokens_out, version)

    async def _add_usage(
        self, briefing_id: str, model: str, tokens_in: int, tokens_out: int, version: str | None
    ) -> None:
        cost = estimate_cost_usd(model, tokens_in, tokens_out)

        def add_usage(b: Briefing) -> None:
            b.run.tokens_in += tokens_in
            b.run.tokens_out += tokens_out
            b.run.est_cost_usd = round(b.run.est_cost_usd + cost, 6)
            if version and version not in b.run.model_versions:
                b.run.model_versions.append(version)

        with contextlib.suppress(KeyError):  # briefing deleted meanwhile
            await self.store.mutate(briefing_id, add_usage)


@dataclass
class NodeResult:
    update: dict[str, Any]
    message: str
    detail: str | None = None
    data: dict[str, Any] | None = None
    patch: Callable[[Briefing], None] | None = None
    """Applied to the persisted Briefing together with the step completion."""


NodeFn = Callable[[AgentDeps, BriefingState], Awaitable[NodeResult]]


def set_step(b: Briefing, name: NodeName, status: StepStatus, detail: str | None = None) -> None:
    step: AgentStep = next(s for s in b.run.steps if s.name == name)
    step.status = status
    now = utcnow()
    if status == "running":
        step.started_at = now
        step.ended_at = None
    elif status in ("completed", "failed", "skipped"):
        step.ended_at = now
        if step.started_at is None:
            step.started_at = now
    if detail is not None:
        step.detail = detail


def one_line(exc: BaseException, limit: int = 300) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:limit]


STARTED_MESSAGES: dict[str, str] = {
    "normalize_condition": "Normalising condition",
    "retrieve_sources": "Retrieving sources",
    "extract_treatments": "Extracting treatment options from each source",
    "consolidate_options": "Consolidating treatment options",
    "detect_conflicts": "Checking sources for conflicting statements",
    "suggest_relevance": "Suggesting relevant options",
    "write_report": "Writing the report",
}


def instrument(deps: AgentDeps, name: NodeName, fn: NodeFn) -> Callable[[BriefingState], Awaitable[dict[str, Any]]]:
    """Wrap a node: step running/completed/failed on the Briefing + started/completed/failed events."""

    async def node(state: BriefingState) -> dict[str, Any]:
        bid = state["briefing_id"]

        def start(b: Briefing) -> None:
            set_step(b, name, "running")
            if name == "normalize_condition" and b.research_started_at is None:
                b.research_started_at = utcnow()

        await deps.store.mutate(bid, start)
        await deps.events.emit(bid, name, "started", STARTED_MESSAGES.get(name, name))
        try:
            result = await fn(deps, state)
            if deps.settings.data_mode == "replay" and deps.settings.replay_step_delay_ms > 0:
                await asyncio.sleep(deps.settings.replay_step_delay_ms / 1000)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            msg = one_line(exc)
            logger.exception("Node %s failed for %s", name, bid)

            def fail(b: Briefing) -> None:
                set_step(b, name, "failed", msg)

            await deps.store.mutate(bid, fail)
            await deps.events.emit(bid, name, "failed", msg)
            raise

        def complete(b: Briefing) -> None:
            if result.patch is not None:
                result.patch(b)
            set_step(b, name, "completed", result.detail)

        await deps.store.mutate(bid, complete)
        await deps.events.emit(bid, name, "completed", result.message, result.data)
        return result.update

    node.__name__ = name
    return node
