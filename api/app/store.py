"""Persistence of Briefing JSON documents, JobEvents and users (docs/CONTRACT.md section 10)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import Executable, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import briefings_table, events_table, users_table
from app.schemas import Briefing, JobEvent, User


def utcnow() -> datetime:
    return datetime.now(UTC)


class BriefingNotFound(KeyError):
    pass


class Store:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ------------------------------------------------------------------ users

    async def list_users(self) -> list[User]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(select(users_table).order_by(users_table.c.id))).mappings().all()
        return [User.model_validate(dict(r)) for r in rows]

    async def get_user(self, user_id: str) -> User | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(users_table).where(users_table.c.id == user_id))).mappings().first()
        return User.model_validate(dict(row)) if row else None

    # ------------------------------------------------------------------ briefings

    async def _write(self, *statements: Executable) -> None:
        """Run writes in one transaction, shielded from task cancellation.

        Runs are cancelled (delete, shutdown) at arbitrary awaits; a write cancelled half-way could leave the
        SQLite connection inside a transaction and lock the database for every other writer.
        """

        async def run() -> None:
            async with self.engine.begin() as conn:
                for st in statements:
                    await conn.execute(st)

        await asyncio.shield(run())

    async def insert_briefing(self, briefing: Briefing) -> None:
        await self._write(insert(briefings_table).values(**self._row(briefing)))

    async def get_briefing(self, briefing_id: str) -> Briefing | None:
        async with self.engine.connect() as conn:
            raw = (
                await conn.execute(select(briefings_table.c.json).where(briefings_table.c.id == briefing_id))
            ).scalar_one_or_none()
        return Briefing.model_validate_json(raw) if raw else None

    async def require_briefing(self, briefing_id: str) -> Briefing:
        b = await self.get_briefing(briefing_id)
        if b is None:
            raise BriefingNotFound(briefing_id)
        return b

    async def save_briefing(self, briefing: Briefing) -> Briefing:
        briefing.updated_at = utcnow()
        row = self._row(briefing)
        await self._write(update(briefings_table).where(briefings_table.c.id == briefing.id).values(**row))
        return briefing

    async def mutate(self, briefing_id: str, fn: Callable[[Briefing], Awaitable[None] | None]) -> Briefing:
        """Load, apply ``fn`` in place, persist. Serialised per briefing (safe under asyncio.gather)."""
        async with self._locks[briefing_id]:
            b = await self.require_briefing(briefing_id)
            result = fn(b)
            if asyncio.iscoroutine(result):
                await result
            # Re-validate so a bad mutation fails loudly instead of persisting invalid JSON.
            b = Briefing.model_validate(b.model_dump())
            return await self.save_briefing(b)

    async def list_briefings(self, created_by: str | None = None, status: str | None = None) -> list[Briefing]:
        q = select(briefings_table.c.json).order_by(briefings_table.c.created_at.desc())
        if created_by:
            q = q.where(briefings_table.c.created_by == created_by)
        if status:
            q = q.where(briefings_table.c.status == status)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(q)).scalars().all()
        return [Briefing.model_validate_json(r) for r in rows]

    async def delete_briefing(self, briefing_id: str) -> None:
        await self._write(
            delete(events_table).where(events_table.c.briefing_id == briefing_id),
            delete(briefings_table).where(briefings_table.c.id == briefing_id),
        )
        self._locks.pop(briefing_id, None)

    @staticmethod
    def _row(b: Briefing) -> dict[str, str]:
        return {
            "id": b.id,
            "created_by": b.created_by,
            "status": b.status,
            "created_at": b.created_at.isoformat(),
            "updated_at": b.updated_at.isoformat(),
            "json": b.model_dump_json(),
        }

    # ------------------------------------------------------------------ events

    async def insert_event(self, event: JobEvent) -> None:
        await self._write(
            insert(events_table).values(briefing_id=event.briefing_id, seq=event.seq, json=event.model_dump_json())
        )

    async def list_events(self, briefing_id: str, after_seq: int = 0) -> list[JobEvent]:
        q = (
            select(events_table.c.json)
            .where(events_table.c.briefing_id == briefing_id, events_table.c.seq > after_seq)
            .order_by(events_table.c.seq)
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(q)).scalars().all()
        return [JobEvent.model_validate_json(r) for r in rows]

    async def max_event_seq(self, briefing_id: str) -> int:
        async with self.engine.connect() as conn:
            value = (
                await conn.execute(
                    select(func.max(events_table.c.seq)).where(events_table.c.briefing_id == briefing_id)
                )
            ).scalar_one_or_none()
        return int(value or 0)
