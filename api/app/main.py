"""FastAPI app factory: CORS, routers, lifespan (store + checkpointer + startup recovery)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agent.deps import AgentDeps
from app.agent.graph import AgentRunner
from app.config import Settings, get_settings
from app.connectors.http import HttpClient
from app.connectors.medlineplus import MedlinePlusConnector
from app.connectors.pubmed import PubMedConnector
from app.connectors.replay import ReplayConnector
from app.db import create_engine_for, init_db
from app.events import EventBus
from app.llm.base import build_llm_client
from app.ratelimit import TokenBucket
from app.routers import briefings, conditions, health, users
from app.schemas import Briefing
from app.store import Store

logger = logging.getLogger("app")


RESTART_ERROR = "Interrupted by server restart; use Retry to resume from the last checkpoint"


async def recover_interrupted(store: Store, events: EventBus, runner: AgentRunner) -> int:
    """Runs that were in flight when the process died.

    - Checkpoint paused at ``human_review`` (crash between the interrupt and the status change, or before a
      submitted review was applied): back to ``awaiting_review`` with the matching event.
    - Anything else: ``failed`` through the event bus (so the history ends with a terminal event). The
      checkpoint is kept, so ``POST /api/briefings/{id}/retry`` resumes from the node that was running.
    ``awaiting_review`` briefings need nothing: they are resumable from the checkpoint as they are.
    """
    n = 0
    for status in ("researching", "generating_report"):
        for b in await store.list_briefings(status=status):
            n += 1
            if await runner.is_paused_for_review(b.id):
                await runner.mark_awaiting_review(b.id, " (restored after a server restart)")
                continue

            def fail(x: Briefing) -> None:
                x.status = "failed"
                x.error = RESTART_ERROR
                for s in x.run.steps:
                    if s.status == "running":
                        s.status = "failed"
                        s.detail = "Interrupted by server restart"

            await events.transition(b.id, fail, "run", "failed", RESTART_ERROR)
    return n


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        data_path = settings.data_path
        engine = create_engine_for(data_path)
        await init_db(engine)
        store = Store(engine)
        bus = EventBus(store)
        http = HttpClient(settings.http_timeout_s)
        replay = ReplayConnector(settings.fixtures_path)
        live = settings.data_mode == "live"
        deps = AgentDeps(
            settings=settings,
            store=store,
            events=bus,
            llm=build_llm_client(settings),
            replay=replay,
            http=http,
            pubmed=PubMedConnector(http, settings) if live else None,
            medlineplus=MedlinePlusConnector(http) if live else None,
            llm_semaphore=asyncio.Semaphore(max(1, settings.llm_max_concurrency)),
        )
        conn = await aiosqlite.connect(str(data_path / "checkpoints.db"))
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()
        runner = AgentRunner(deps, checkpointer)

        recovered = await recover_interrupted(store, bus, runner)
        if recovered:
            logger.warning("Recovered %d briefing(s) interrupted by a restart", recovered)
        logger.info(
            "Health Briefing API ready: llm_provider=%s data_mode=%s fixtures=%s",
            settings.llm_provider,
            settings.data_mode,
            settings.fixtures_path,
        )

        app.state.settings = settings
        app.state.store = store
        app.state.events = bus
        app.state.http = http
        app.state.replay = replay
        app.state.runner = runner
        app.state.create_bucket = TokenBucket(settings.create_rate_per_minute, settings.create_burst)
        try:
            yield
        finally:
            for bid in list(runner.tasks):
                await runner.cancel(bid)
            await conn.close()
            await http.aclose()
            await engine.dispose()

    app = FastAPI(
        title="Health Briefing API",
        version="0.1.0",
        description="Standard-of-care briefing agent (POC). Public literature only; not medical advice.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-User-Id", "Last-Event-ID"],
        expose_headers=["Location"],
    )

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    for r in (health.router, users.router, conditions.router, briefings.router):
        app.include_router(r)
    return app


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx/httpcore log full request URLs at INFO, which would include NCBI api_key values.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


_configure_logging()
app = create_app()
