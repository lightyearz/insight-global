"""Run lifecycle guards: abuse limits, lost checkpoints, retry from checkpoint, restart recovery, recording."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.main import create_app
from app.schemas import Briefing
from tests.conftest import make_settings, wait_for_status

REVIEW_NOTE = "Keep both, reviewed."


def review_body(b: dict) -> dict:
    return {
        "selected_option_ids": [o["id"] for o in b["treatment_options"] if o["suggested"]],
        "conflict_resolutions": [
            {"conflict_id": c["id"], "decision": "accept_both_with_context", "note": REVIEW_NOTE}
            for c in b["conflicts"]
        ],
    }


async def test_report_carries_method_run_times_and_excluded_options(app_client):
    _, client = app_client
    bid = (await client.post("/api/briefings", json={"condition": "Test condition"})).json()["id"]
    b = await wait_for_status(client, bid, {"awaiting_review", "failed"})
    strategy = b["search_strategy"]
    assert strategy["normalisation"] == "replay_fixture" and strategy["sources_selected"] == 3
    assert any("[Title/Abstract]" in q or "[MeSH Major Topic]" in q for q in strategy["pubmed_queries"])
    assert len(strategy["tier_rules"]) == 4
    src = {s["id"]: s for s in b["sources"]}
    assert src["pubmed:1000001"]["region_inferred"] is True
    summary = (await client.get("/api/briefings")).json()[0]
    assert summary["research_conducted_at"] and summary["data_mode"] == "replay"

    r = await client.post(f"/api/briefings/{bid}/review", json=review_body(b))
    assert r.status_code == 202, r.text
    done = await wait_for_status(client, bid, {"completed", "failed"})
    report = done["report"]
    assert report["research_started_at"] == done["research_started_at"]
    assert report["research_completed_at"] == done["research_completed_at"]
    assert report["search_strategy"]["normalised_label"] == "Test Condition"
    assert [x["id"] for x in report["excluded_options"]] == ["opt-structured-exercise"]
    assert report["excluded_options"][0]["excluded_by"] == "admin"
    assert all(e["short_label"] for e in report["timeline"])
    assert all(o["recommendation_direction"] for o in report["treatment_options"])
    assert report["conflict_log"][0]["suggested_resolution"]["rule"] == "higher_tier"
    detail = next(a["detail"] for a in report["audit_log"] if a["action"] == "conflict_resolved")
    assert "differs from suggested" in detail and REVIEW_NOTE in detail


async def test_run_limits_return_429(tmp_path):
    settings = make_settings(tmp_path, max_active_runs_per_user=1, replay_step_delay_ms=300)
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        assert (await c.post("/api/briefings", json={"condition": "tc"})).status_code == 202
        r = await c.post("/api/briefings", json={"condition": "tc"})
        assert r.status_code == 429 and "already have 1" in r.json()["detail"]
        assert r.headers["retry-after"]
        # another user is not affected by the per-user cap
        assert (
            await c.post("/api/briefings", headers={"X-User-Id": "analyst"}, json={"condition": "tc"})
        ).status_code == 202


async def test_create_rate_limit(tmp_path):
    settings = make_settings(tmp_path, create_burst=2, create_rate_per_minute=1, max_active_runs_per_user=10)
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        codes = [(await c.post("/api/briefings", json={"condition": "tc"})).status_code for _ in range(3)]
        assert codes == [202, 202, 429]


async def test_review_with_lost_checkpoint_is_409_not_a_silent_restart(app_client):
    app, client = app_client
    bid = (await client.post("/api/briefings", json={"condition": "tc"})).json()["id"]
    b = await wait_for_status(client, bid, {"awaiting_review", "failed"})
    await app.state.runner.delete_thread(bid)  # e.g. a fresh volume or a different instance
    r = await client.post(f"/api/briefings/{bid}/review", json=review_body(b))
    assert r.status_code == 409 and "checkpoint lost" in r.json()["detail"]
    assert (await client.get(f"/api/briefings/{bid}")).json()["status"] == "awaiting_review"


async def test_review_list_sizes_are_bounded(app_client):
    _, client = app_client
    r = await client.post(
        "/api/briefings/brf_000000000000/review", json={"selected_option_ids": [f"opt-{i}" for i in range(201)]}
    )
    assert r.status_code == 422


async def test_failed_report_step_can_be_retried_from_checkpoint(app_client, tmp_path):
    app, client = app_client
    bid = (await client.post("/api/briefings", json={"condition": "tc"})).json()["id"]
    b = await wait_for_status(client, bid, {"awaiting_review", "failed"})
    llm = app.state.runner.deps.llm
    real_dir = llm.fixtures_dir
    llm.fixtures_dir = tmp_path  # write_report fixture "missing" -> the report step fails
    assert (await client.post(f"/api/briefings/{bid}/review", json=review_body(b))).status_code == 202
    failed = await wait_for_status(client, bid, {"failed", "completed"})
    assert failed["status"] == "failed"
    assert await app.state.runner.next_nodes(bid) == ("write_report",)

    llm.fixtures_dir = real_dir
    r = await client.post(f"/api/briefings/{bid}/retry", headers={"X-User-Id": "analyst"})
    assert r.status_code == 403
    r = await client.post(f"/api/briefings/{bid}/retry")
    assert r.status_code == 202 and r.json()["status"] == "generating_report" and r.json()["error"] is None
    done = await wait_for_status(client, bid, {"completed", "failed"})
    assert done["status"] == "completed", done["error"]
    # the review is not repeated: one review_submitted entry
    assert [a["action"] for a in done["report"]["audit_log"]].count("review_submitted") == 1
    r = await client.post(f"/api/briefings/{bid}/retry")
    assert r.status_code == 409


async def test_restart_recovery_restores_a_paused_run_to_awaiting_review(settings):
    app1 = create_app(settings)
    async with (
        app1.router.lifespan_context(app1),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app1), base_url="http://t") as c,
    ):
        bid = (await c.post("/api/briefings", json={"condition": "tc"})).json()["id"]
        await wait_for_status(c, bid, {"awaiting_review", "failed"})

        # Simulate a crash between the interrupt checkpoint and the awaiting_review transition.
        def rewind(b: Briefing) -> None:
            b.status = "researching"

        await app1.state.store.mutate(bid, rewind)

    app2 = create_app(settings)
    async with (
        app2.router.lifespan_context(app2),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t") as c,
    ):
        b = (await c.get(f"/api/briefings/{bid}")).json()
        assert b["status"] == "awaiting_review"
        events = (await c.get(f"/api/briefings/{bid}/events")).text
        assert "restored after a server restart" in events


async def test_deleting_a_running_briefing_emits_a_terminal_event(tmp_path):
    settings = make_settings(tmp_path, replay_step_delay_ms=500)
    app = create_app(settings)
    seen: list = []
    async with app.router.lifespan_context(app):
        bus = app.state.events
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            bid = (await c.post("/api/briefings", json={"condition": "tc"})).json()["id"]
            async with bus.subscribe(bid) as queue:
                assert (await c.delete(f"/api/briefings/{bid}")).status_code == 204
                while not queue.empty():
                    seen.append(queue.get_nowait())
    assert seen and (seen[-1].step, seen[-1].status) == ("run", "failed") and "deleted" in seen[-1].message


def _write_recording(root: Path, key: str) -> None:
    folder = root / key
    (folder / "llm").mkdir(parents=True)
    (folder / "manifest.json").write_text("{}")
    (folder / "llm" / "write_report.json").write_text("{}")


def test_recordings_are_promoted_only_when_complete_and_never_overwrite(tmp_path):
    from app.llm.recorder import promote_recording

    recordings, fixtures = tmp_path / "rec", tmp_path / "fx"
    _write_recording(recordings, "asthma.brf_1")
    assert promote_recording(recordings, "asthma.brf_1", fixtures, overwrite=False) == fixtures / "asthma"
    _write_recording(recordings, "asthma.brf_2")
    assert promote_recording(recordings, "asthma.brf_2", fixtures, overwrite=False) is None  # existing fixture
    assert (recordings / "asthma.brf_2").is_dir()
    assert promote_recording(recordings, "asthma.brf_2", fixtures, overwrite=True) == fixtures / "asthma"
    (recordings / "copd.brf_3").mkdir(parents=True)
    assert promote_recording(recordings, "copd.brf_3", fixtures, overwrite=True) is None  # incomplete


def test_recorder_wraps_live_runs_only(tmp_path):
    from app.llm.base import build_llm_client
    from app.llm.recorder import RecordingLLMClient

    replay_data = make_settings(tmp_path, LLM_PROVIDER="gemini_api", gemini_api_key="k", record_fixtures=True)
    assert not isinstance(build_llm_client(replay_data), RecordingLLMClient)
    live = make_settings(
        tmp_path, LLM_PROVIDER="gemini_api", DATA_MODE="live", gemini_api_key="k", record_fixtures=True
    )
    client = build_llm_client(live)
    assert isinstance(client, RecordingLLMClient)
    assert client.fixtures_dir == live.recordings_path
    assert json.dumps(str(live.recordings_path)).count("recordings") == 1
