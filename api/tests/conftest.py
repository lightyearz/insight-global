from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app

TEST_FIXTURES = Path(__file__).parent / "fixtures" / "replay"


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "LLM_PROVIDER": "replay",
        "DATA_MODE": "replay",
        "google_cloud_project": "",
        "gemini_api_key": "",
        "ncbi_api_key": "",
        "data_dir": str(tmp_path / "data"),
        "fixtures_dir": str(TEST_FIXTURES),
        "replay_step_delay_ms": 0,
        "record_fixtures": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
async def app_client(settings: Settings) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


async def wait_for_status(
    client: httpx.AsyncClient, briefing_id: str, statuses: set[str], timeout: float = 15.0
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        resp = await client.get(f"/api/briefings/{briefing_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in statuses:
            return body
        if loop.time() > deadline:
            raise AssertionError(f"timed out waiting for {statuses}; status={body['status']} error={body['error']}")
        await asyncio.sleep(0.05)
