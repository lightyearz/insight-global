"""A briefing paused for review survives a server restart (SQLite checkpointer); running ones fail."""

from __future__ import annotations

import httpx

from app.main import create_app
from app.schemas import Briefing
from tests.conftest import wait_for_status


async def test_awaiting_review_survives_restart_and_resumes(settings):
    app1 = create_app(settings)
    async with (
        app1.router.lifespan_context(app1),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app1), base_url="http://t") as c,
    ):
        bid = (await c.post("/api/briefings", json={"condition": "Test condition"})).json()["id"]
        b = await wait_for_status(c, bid, {"awaiting_review", "failed"})
        assert b["status"] == "awaiting_review"
        conflict_id = b["conflicts"][0]["id"]
        # Simulate a run that was mid-flight when the server died.
        store = app1.state.store
        stuck = Briefing.model_validate(b)
        stuck.id = "brf_aaaaaaaaaaaa"
        stuck.status = "researching"
        await store.insert_briefing(stuck)

    app2 = create_app(settings)
    async with (
        app2.router.lifespan_context(app2),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t") as c,
    ):
        stuck = (await c.get("/api/briefings/brf_aaaaaaaaaaaa")).json()
        assert stuck["status"] == "failed" and stuck["error"].startswith("Interrupted by server restart")
        events = (await c.get("/api/briefings/brf_aaaaaaaaaaaa/events")).text
        assert '"status":"failed"' in events  # recovery emits a terminal event
        assert await app2.state.runner.is_paused_for_review(bid)
        r = await c.post(
            f"/api/briefings/{bid}/review",
            json={
                "selected_option_ids": ["opt-alphamab"],
                "conflict_resolutions": [
                    {"conflict_id": conflict_id, "decision": "accept_both_with_context", "note": "Keep both."}
                ],
            },
        )
        assert r.status_code == 202, r.text
        done = await wait_for_status(c, bid, {"completed", "failed"})
        assert done["status"] == "completed", done["error"]
        assert [o["id"] for o in done["report"]["treatment_options"]] == ["opt-alphamab"]
        # event seq continues after restart
        seqs = [e for e in (await c.get(f"/api/briefings/{bid}/events")).text.split("\n") if e.startswith("id: ")]
        nums = [int(s[4:]) for s in seqs]
        assert nums == list(range(1, len(nums) + 1))
