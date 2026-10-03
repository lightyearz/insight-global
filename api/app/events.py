"""In-process event bus: per-briefing seq allocation, persistence, then live fan-out.

Events are persisted before they are published (docs/CONTRACT.md section 5), so the
SSE endpoint can always replay history from the store and then follow live events.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from typing import Any

from app.schemas import Briefing, JobEvent, JobEventStatus, JobStep
from app.store import Store, utcnow


class EventBus:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._seq: dict[str, int] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._subscribers: defaultdict[str, set[asyncio.Queue[JobEvent]]] = defaultdict(set)

    async def emit(
        self,
        briefing_id: str,
        step: JobStep,
        status: JobEventStatus,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> JobEvent:
        return await self.transition(briefing_id, None, step, status, message, data)

    async def transition(
        self,
        briefing_id: str,
        mutate: Callable[[Briefing], None] | None,
        step: JobStep,
        status: JobEventStatus,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> JobEvent:
        """Apply a Briefing mutation (e.g. a status change) and persist its event atomically.

        SSE readers take their history + status snapshot under the same lock (:meth:`snapshot`),
        so they never see a terminal status without the matching terminal event, or vice versa.
        """
        async with self._locks[briefing_id]:
            if mutate is not None:
                await self.store.mutate(briefing_id, mutate)
            if briefing_id not in self._seq:
                self._seq[briefing_id] = await self.store.max_event_seq(briefing_id)
            self._seq[briefing_id] += 1
            event = JobEvent(
                briefing_id=briefing_id,
                seq=self._seq[briefing_id],
                ts=utcnow(),
                step=step,
                status=status,
                message=message,
                data=data,
            )
            await self.store.insert_event(event)
        for queue in list(self._subscribers.get(briefing_id, ())):
            queue.put_nowait(event)
        return event

    async def snapshot(self, briefing_id: str, after_seq: int) -> tuple[list[JobEvent], Briefing | None]:
        """Consistent (event history, current briefing) pair for the SSE close rule."""
        async with self._locks[briefing_id]:
            history = await self.store.list_events(briefing_id, after_seq=after_seq)
            return history, await self.store.get_briefing(briefing_id)

    @contextlib.asynccontextmanager
    async def subscribe(self, briefing_id: str) -> AsyncIterator[asyncio.Queue[JobEvent]]:
        queue: asyncio.Queue[JobEvent] = asyncio.Queue()
        self._subscribers[briefing_id].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[briefing_id].discard(queue)
            if not self._subscribers[briefing_id]:
                self._subscribers.pop(briefing_id, None)

    def forget(self, briefing_id: str) -> None:
        self._seq.pop(briefing_id, None)
        self._locks.pop(briefing_id, None)


def is_terminal_event(event: JobEvent) -> bool:
    """Close rule: awaiting_review, any failed event, or run/completed."""
    return event.status in ("awaiting_review", "failed") or (event.step == "run" and event.status == "completed")
