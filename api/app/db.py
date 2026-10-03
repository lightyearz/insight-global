"""SQLite via SQLAlchemy 2.0 async (aiosqlite). See docs/CONTRACT.md section 10.

Tables:
- ``users``: seeded, read-only in this POC.
- ``briefings``: one row per briefing; ``json`` holds ``Briefing.model_dump_json()``.
- ``events``: persisted ``JobEvent`` history, keyed by (briefing_id, seq).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, event, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

metadata = MetaData()

users_table = Table(
    "users",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("email", String(320), nullable=False),
    Column("role", String(16), nullable=False),
)

briefings_table = Table(
    "briefings",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("created_by", String(64), nullable=False, index=True),
    Column("status", String(32), nullable=False, index=True),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("json", Text, nullable=False),
)

events_table = Table(
    "events",
    metadata,
    Column("briefing_id", String(32), primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("json", Text, nullable=False),
)

SEED_USERS: list[dict[str, str]] = [
    {"id": "admin", "name": "Admin", "email": "admin@example.org", "role": "admin"},
    {"id": "analyst", "name": "Demo Analyst", "email": "analyst@example.org", "role": "analyst"},
    # Additive to CONTRACT v1.0.0 section 3: a second analyst to demonstrate per-user permissions.
    {"id": "analyst2", "name": "Second Analyst", "email": "analyst2@example.org", "role": "analyst"},
]


def create_engine_for(data_dir: Path) -> AsyncEngine:
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{data_dir / 'app.db'}", connect_args={"timeout": 15})

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
        # WAL: readers never block the single writer (SSE readers vs. the agent's writes).
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

    return engine


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        existing = set((await conn.execute(select(users_table.c.id))).scalars())
        missing = [u for u in SEED_USERS if u["id"] not in existing]
        if missing:
            await conn.execute(insert(users_table), missing)
