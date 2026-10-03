"""End-to-end API flow in replay mode: research -> HITL review -> report."""

from __future__ import annotations

import json

from tests.conftest import wait_for_status

ADMIN = {"X-User-Id": "admin"}


def parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = [line[6:] for line in block.split("\n") if line.startswith("data: ")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


async def test_full_briefing_flow(app_client):
    _, client = app_client

    health = (await client.get("/api/health")).json()
    assert (health["llm_provider"], health["data_mode"], health["status"]) == ("replay", "replay", "ok")
    assert [m["slug"] for m in (await client.get("/api/replay/conditions")).json()] == ["test-condition"]

    resp = await client.post("/api/briefings", json={"condition": "Test condition", "region": "US"})
    assert resp.status_code == 202, resp.text
    created = resp.json()
    bid = created["id"]
    assert resp.headers["location"] == f"/api/briefings/{bid}"
    assert created["status"] == "researching" and created["created_by"] == "admin"
    assert created["run"]["steps"][0]["name"] == "normalize_condition"
    assert created["audit_log"][0]["action"] == "briefing_created"

    b = await wait_for_status(client, bid, {"awaiting_review", "failed"})
    assert b["status"] == "awaiting_review", b["error"]
    assert b["condition"]["label"] == "Test Condition" and b["condition"]["input"] == "Test condition"
    assert b["research_started_at"] and b["research_completed_at"]
    assert len(b["sources"]) == 3
    src = {s["id"]: s for s in b["sources"]}
    assert src["pubmed:1000001"]["issuing_body"] == "Test Society"  # filled from extraction
    assert src["pubmed:1000001"]["region"] == "US"
    assert all(s["retrieved_at"] for s in b["sources"])
    options = {o["id"]: o for o in b["treatment_options"]}
    assert set(options) == {"opt-alphamab", "opt-betacillin", "opt-structured-exercise"}
    assert options["opt-alphamab"]["suggested"] and options["opt-alphamab"]["selected"]
    assert not options["opt-structured-exercise"]["suggested"]
    [conflict] = b["conflicts"]
    assert conflict["resolution"] is None
    assert conflict["suggested_resolution"]["accepted_source_id"] == "pubmed:1000001"
    steps = {s["name"]: s["status"] for s in b["run"]["steps"]}
    assert steps["suggest_relevance"] == "completed" and steps["human_review"] == "running"
    assert steps["write_report"] == "pending"

    # SSE: history replay then close at awaiting_review
    sse = await client.get(f"/api/briefings/{bid}/events")
    assert sse.status_code == 200 and sse.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(sse.text)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert (events[0]["step"], events[0]["status"]) == ("run", "started")
    assert (events[-1]["step"], events[-1]["status"]) == ("human_review", "awaiting_review")
    assert any(e["step"] == "extract_treatments" and e["status"] == "progress" for e in events)
    last_seq = events[-1]["seq"]

    # HITL validation: unresolved conflict -> 400
    selected = ["opt-alphamab", "opt-structured-exercise"]
    r = await client.post(f"/api/briefings/{bid}/review", json={"selected_option_ids": selected})
    assert r.status_code == 400 and "unresolved" in r.json()["detail"]
    # empty selection -> 400
    r = await client.post(f"/api/briefings/{bid}/review", json={"selected_option_ids": []})
    assert r.status_code == 400
    # unknown option -> 400
    r = await client.post(f"/api/briefings/{bid}/review", json={"selected_option_ids": ["opt-nope"]})
    assert r.status_code == 400
    # accepted source not among positions -> 400
    bad = {
        "conflict_id": conflict["id"],
        "decision": "accept_source",
        "accepted_source_id": "medlineplus:testcondition",
    }
    r = await client.post(
        f"/api/briefings/{bid}/review", json={"selected_option_ids": selected, "conflict_resolutions": [bad]}
    )
    assert r.status_code == 400
    # custom without note -> 422 (model validator)
    r = await client.post(
        f"/api/briefings/{bid}/review",
        json={
            "selected_option_ids": selected,
            "conflict_resolutions": [{"conflict_id": conflict["id"], "decision": "custom"}],
        },
    )
    assert r.status_code == 422
    # analyst cannot review admin's briefing -> 403
    r = await client.post(
        f"/api/briefings/{bid}/review", headers={"X-User-Id": "analyst"}, json={"selected_option_ids": selected}
    )
    assert r.status_code == 403

    # Valid review: the human overrides the AI suggestion (selection + conflict)
    resolution = {
        "conflict_id": conflict["id"],
        "decision": "accept_source",
        "accepted_source_id": "pubmed:1000002",
        "note": "Local formulary prefers Betacillin",
    }
    r = await client.post(
        f"/api/briefings/{bid}/review",
        headers=ADMIN,
        json={"selected_option_ids": selected, "conflict_resolutions": [resolution]},
    )
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "generating_report"
    # second submission -> 409
    r2 = await client.post(
        f"/api/briefings/{bid}/review", json={"selected_option_ids": selected, "conflict_resolutions": [resolution]}
    )
    assert r2.status_code == 409

    done = await wait_for_status(client, bid, {"completed", "failed"})
    assert done["status"] == "completed", done["error"]
    assert done["reviewed_by"] == "admin" and done["reviewed_at"]
    report = done["report"]
    assert report is not None
    assert {o["id"] for o in report["treatment_options"]} == set(selected)
    assert all(o["selected"] for o in report["treatment_options"])
    assert report["timeline"][-1]["kind"] == "research_conducted"
    assert sum(1 for e in report["timeline"] if e["kind"] == "research_conducted") == 1
    assert report["research_conducted_at"].startswith("2026-09-30T11:58:12")
    [logged] = report["conflict_log"]
    assert logged["resolution"]["decision"] == "accept_source"
    assert logged["resolution"]["accepted_source_id"] == "pubmed:1000002"
    assert logged["resolution"]["resolved_by"] == "admin"
    assert logged["resolution"]["note"] == "Local formulary prefers Betacillin"
    actions = [a["action"] for a in report["audit_log"]]
    for action in (
        "briefing_created",
        "review_submitted",
        "option_selected",
        "option_excluded",
        "conflict_resolved",
        "report_generated",
    ):
        assert action in actions
    assert report["generated_by"] == "admin" and report["model"] == "replay"
    assert report["disclaimer"].startswith("This briefing is an AI-assisted summary")
    assert {s["id"] for s in report["sources"]} == {"pubmed:1000001", "pubmed:1000002", "medlineplus:testcondition"}
    assert all(s["published_at"] and s["retrieved_at"] for s in report["sources"])
    assert {s["name"]: s["status"] for s in done["run"]["steps"]} == {
        n: "completed"
        for n in (
            "normalize_condition",
            "retrieve_sources",
            "extract_treatments",
            "consolidate_options",
            "detect_conflicts",
            "suggest_relevance",
            "human_review",
            "write_report",
        )
    }

    # SSE after review: follows report generation and closes at run/completed
    tail = parse_sse((await client.get(f"/api/briefings/{bid}/events", params={"after_seq": last_seq})).text)
    assert [(e["step"], e["status"]) for e in tail] == [
        ("human_review", "completed"),
        ("write_report", "started"),
        ("write_report", "completed"),
        ("run", "completed"),
    ]

    # list + summary
    summaries = (await client.get("/api/briefings")).json()
    assert summaries[0]["id"] == bid and summaries[0]["has_report"] and summaries[0]["open_conflict_count"] == 0
    assert summaries[0]["selected_option_count"] == 2
    assert (await client.get("/api/briefings", params={"created_by": "analyst"})).json() == []

    # review after completion -> 409
    r = await client.post(
        f"/api/briefings/{bid}/review", json={"selected_option_ids": selected, "conflict_resolutions": [resolution]}
    )
    assert r.status_code == 409

    # delete: analyst forbidden, admin ok
    assert (await client.delete(f"/api/briefings/{bid}", headers={"X-User-Id": "analyst"})).status_code == 403
    assert (await client.delete(f"/api/briefings/{bid}")).status_code == 204
    assert (await client.get(f"/api/briefings/{bid}")).status_code == 404
    assert (await client.get(f"/api/briefings/{bid}/events")).status_code == 404


async def test_users_and_identity(app_client):
    _, client = app_client
    users = (await client.get("/api/users")).json()
    assert {u["id"] for u in users} >= {"admin", "analyst"}
    assert (await client.get("/api/me")).json()["id"] == "admin"
    assert (await client.get("/api/me", headers={"X-User-Id": "analyst"})).json()["role"] == "analyst"
    r = await client.get("/api/me", headers={"X-User-Id": "mallory"})
    assert r.status_code == 401 and r.json() == {"detail": "Unknown user 'mallory'"}


async def test_replay_unknown_condition_is_400(app_client):
    _, client = app_client
    r = await client.post("/api/briefings", json={"condition": "Unknown disease"})
    assert r.status_code == 400 and "Test condition" in r.json()["detail"]
    r = await client.post("/api/briefings", json={"condition": "x"})
    assert r.status_code == 422


async def test_condition_suggest_in_replay(app_client):
    _, client = app_client
    assert (await client.get("/api/conditions/suggest", params={"q": "t"})).json() == []
    out = (await client.get("/api/conditions/suggest", params={"q": "test"})).json()
    assert out == [{"label": "Test condition", "code": None, "source": "replay"}]


async def test_analyst_can_review_own_briefing_and_404s(app_client):
    _, client = app_client
    analyst = {"X-User-Id": "analyst"}
    r = await client.post("/api/briefings", headers=analyst, json={"condition": "tc", "region": "UK"})
    bid = r.json()["id"]
    b = await wait_for_status(client, bid, {"awaiting_review", "failed"})
    conflict_id = b["conflicts"][0]["id"]
    r = await client.post(
        f"/api/briefings/{bid}/review",
        headers=analyst,
        json={
            "selected_option_ids": ["opt-betacillin"],
            "conflict_resolutions": [{"conflict_id": conflict_id, "decision": "exclude_topic"}],
        },
    )
    # Overriding the AI suggestion needs a reason.
    assert r.status_code == 400 and "note is required" in r.json()["detail"]
    r = await client.post(
        f"/api/briefings/{bid}/review",
        headers=analyst,
        json={
            "selected_option_ids": ["opt-betacillin"],
            "conflict_resolutions": [
                {"conflict_id": conflict_id, "decision": "exclude_topic", "note": "Out of scope for this plan."}
            ],
        },
    )
    assert r.status_code == 202, r.text
    done = await wait_for_status(client, bid, {"completed", "failed"})
    assert done["status"] == "completed"
    assert done["report"]["region"] == "UK"
    assert done["report"]["conflict_log"][0]["resolution"]["decision"] == "exclude_topic"
    assert (await client.get("/api/briefings/brf_000000000000")).status_code == 404
    r = await client.post("/api/briefings/brf_000000000000/review", json={"selected_option_ids": ["opt-a"]})
    assert r.status_code == 404


async def test_failure_marks_briefing_failed(app_client, tmp_path):
    app, client = app_client
    # Point the replay LLM at an empty folder so extract_treatments fails for every source.
    app.state.runner.deps.llm.fixtures_dir = tmp_path
    r = await client.post("/api/briefings", json={"condition": "Test condition"})
    bid = r.json()["id"]
    b = await wait_for_status(client, bid, {"failed", "awaiting_review"})
    assert b["status"] == "failed"
    assert b["error"] == "Treatment extraction failed for every source"
    steps = {s["name"]: s["status"] for s in b["run"]["steps"]}
    assert steps["extract_treatments"] == "failed"
    events = parse_sse((await client.get(f"/api/briefings/{bid}/events")).text)
    assert (events[-1]["step"], events[-1]["status"]) == ("run", "failed")
