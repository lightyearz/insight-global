#!/usr/bin/env python3
"""End-to-end API smoke test (stdlib only).

Runs the full briefing flow against a running API for each condition given:
create -> follow SSE until awaiting_review -> submit a review that overrides the
AI (deselects a suggested option, selects a non-suggested one, overrides one
conflict suggestion and records a custom decision with a note) -> follow SSE
until run/completed -> verify the report.

Usage: python3 scripts/smoke_api.py [--base http://localhost:8080] [condition ...]
Exit code 0 when every check passes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_CONDITIONS = ["type 2 diabetes", "hypertension"]


class Check:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def __call__(self, ok: bool, msg: str) -> None:
        print(f"  [{'ok' if ok else 'FAIL'}] {msg}")
        if not ok:
            self.failures.append(msg)


def request(base: str, method: str, path: str, body: dict | None = None, user: str = "admin"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("X-User-Id", user)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


def follow_events(base: str, briefing_id: str, after_seq: int, timeout_s: float = 120) -> list[dict]:
    """Read the SSE stream until the server closes it. Returns the events received."""
    req = urllib.request.Request(f"{base}/api/briefings/{briefing_id}/events?after_seq={after_seq}")
    req.add_header("Accept", "text/event-stream")
    events: list[dict] = []
    deadline = time.monotonic() + timeout_s
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        for raw_line in resp:
            line = raw_line.decode().rstrip("\n")
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
            if time.monotonic() > deadline:
                raise TimeoutError("SSE stream did not close in time")
    return events


def run_flow(base: str, condition: str) -> list[str]:
    check = Check()
    print(f"\n=== {condition} ===")
    status, b = request(base, "POST", "/api/briefings", {"condition": condition, "region": "US"})
    check(status == 202 and b["status"] == "researching", f"create -> 202 researching ({status})")
    bid = b["id"]

    events = follow_events(base, bid, 0)
    seqs = [e["seq"] for e in events]
    check(seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "SSE seq strictly increasing")
    last = events[-1]
    check(
        (last["step"], last["status"]) == ("human_review", "awaiting_review"),
        f"SSE closes at human_review/awaiting_review (got {last['step']}/{last['status']})",
    )
    steps_seen = {e["step"] for e in events}
    for node in ("normalize_condition", "retrieve_sources", "extract_treatments",
                 "consolidate_options", "detect_conflicts", "suggest_relevance"):
        check(node in steps_seen, f"event stream includes {node}")

    _, b = request(base, "GET", f"/api/briefings/{bid}")
    check(b["status"] == "awaiting_review", "briefing is awaiting_review")
    opts, conflicts, sources = b["treatment_options"], b["conflicts"], b["sources"]
    print(f"  sources={len(sources)} options={len(opts)} conflicts={len(conflicts)}")
    check(len(conflicts) >= 2, "at least two conflicts to review")
    for s in sources:
        check(bool(s["retrieved_at"]), f"source {s['id']} has retrieved_at")
        check(bool(s["published_at"]), f"source {s['id']} has published_at")

    # Negative paths: unresolved conflicts -> 400, other analyst -> 403.
    suggested = [o["id"] for o in opts if o["suggested"]]
    not_suggested = [o["id"] for o in opts if not o["suggested"]]
    st, _ = request(base, "POST", f"/api/briefings/{bid}/review", {"selected_option_ids": suggested})
    check(st == 400 if conflicts else st == 202, f"review without conflict resolutions -> 400 ({st})")
    st, _ = request(base, "POST", f"/api/briefings/{bid}/review",
                    {"selected_option_ids": suggested, "conflict_resolutions": []}, user="analyst")
    check(st == 403, f"analyst reviewing admin's briefing -> 403 ({st})")

    # Human decisions that differ from the AI.
    selected = suggested[1:] + not_suggested[:1]  # drop one suggested, add one not suggested
    resolutions = []
    for i, c in enumerate(conflicts):
        sug = c["suggested_resolution"]
        if i == 0:
            # Override: accept a different source than the AI suggested.
            other = next(p["source_id"] for p in c["positions"] if p["source_id"] != sug["accepted_source_id"])
            resolutions.append({"conflict_id": c["id"], "decision": "accept_source",
                                "accepted_source_id": other, "note": "Smoke test: reviewer override"})
        elif i == 1:
            resolutions.append({"conflict_id": c["id"], "decision": "custom", "accepted_source_id": None,
                                "note": "Smoke test: present both and flag for clinical lead"})
        else:
            resolutions.append({"conflict_id": c["id"], "decision": sug["decision"],
                                "accepted_source_id": sug["accepted_source_id"], "note": ""})
    if resolutions:
        silent = [dict(resolutions[0], note="")] + resolutions[1:]
        st, _ = request(base, "POST", f"/api/briefings/{bid}/review",
                        {"selected_option_ids": selected, "conflict_resolutions": silent})
        check(st == 400, f"overriding the suggestion without a note -> 400 ({st})")
    st, b = request(base, "POST", f"/api/briefings/{bid}/review",
                    {"selected_option_ids": selected, "conflict_resolutions": resolutions})
    check(st == 202 and b["status"] == "generating_report", f"review -> 202 generating_report ({st})")
    st, _ = request(base, "POST", f"/api/briefings/{bid}/review",
                    {"selected_option_ids": selected, "conflict_resolutions": resolutions})
    check(st == 409, f"second review -> 409 ({st})")

    events2 = follow_events(base, bid, seqs[-1])
    last = events2[-1]
    check((last["step"], last["status"]) == ("run", "completed"),
          f"SSE closes at run/completed (got {last['step']}/{last['status']})")

    _, b = request(base, "GET", f"/api/briefings/{bid}")
    check(b["status"] == "completed", "briefing completed")
    r = b["report"]
    check(r is not None, "report present")
    if r is None:
        return check.failures
    check(sorted(o["id"] for o in r["treatment_options"]) == sorted(selected), "report has exactly the selected options")
    check(bool(r["top_level_description"].strip()), "top-level description present")
    tl = r["timeline"]
    research = [e for e in tl if e["kind"] == "research_conducted"]
    check(len(research) == 1 and tl[-1]["kind"] == "research_conducted", "one research_conducted event, last")
    dates = [e["date"] for e in tl[:-1]]
    check(dates == sorted(dates), "timeline sorted by date")
    check(len(r["conflict_log"]) == len(conflicts), "conflict_log has every conflict")
    by_id = {c["id"]: c for c in r["conflict_log"]}
    for res in resolutions:
        got = by_id[res["conflict_id"]]["resolution"]
        check(got is not None and got["decision"] == res["decision"]
              and got["accepted_source_id"] == res["accepted_source_id"] and got["note"] == res["note"]
              and got["resolved_by"] == "admin", f"conflict {res['conflict_id']} records human decision")
    actions = [a["action"] for a in r["audit_log"]]
    for action in ("briefing_created", "review_submitted", "conflict_resolved", "report_generated"):
        check(action in actions, f"audit_log has {action}")
    check(actions.count("conflict_resolved") == len(conflicts), "one conflict_resolved audit entry per conflict")
    for s in r["sources"]:
        check(bool(s["published_at"]) and bool(s["retrieved_at"]),
              f"report source {s['id']} has published_at + retrieved_at")
    check(bool(r["research_conducted_at"]) and bool(r["disclaimer"]), "research_conducted_at + disclaimer")
    check(bool(r["research_started_at"]) and bool(r["research_completed_at"]), "research run start + end")
    ss = r["search_strategy"]
    check(ss is not None and ss["pubmed_queries"] and len(ss["tier_rules"]) == 4, "search strategy (scope & method)")
    check(sorted(x["id"] for x in r["excluded_options"]) == sorted(o["id"] for o in opts if o["id"] not in selected),
          "excluded_options lists every deselected option")
    check(all(o["recommendation_direction"] for o in r["treatment_options"]), "options carry recommendation_direction")
    for c in r["conflict_log"]:
        sides = {p["side"] for p in c["positions"]}
        check(len(sides) >= 2, f"conflict {c['id']} has >= 2 sides")
        check(bool(c["suggested_resolution"]["rule"]), f"conflict {c['id']} suggestion names its rule")
    check(all(e["short_label"] for e in tl), "timeline events have short labels")
    if r["model"] == "replay":
        check(r["key_takeaways"][0].startswith("Replay note:"), "replay narrative flags the reviewer's changes")
    print(f"  report: {len(r['treatment_options'])} options, {len(r['sources'])} sources, "
          f"{len(tl)} timeline events, {len(r['audit_log'])} audit entries")
    request(base, "DELETE", f"/api/briefings/{bid}")
    return check.failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("conditions", nargs="*", default=DEFAULT_CONDITIONS)
    args = ap.parse_args()
    failures: list[str] = []
    for cond in args.conditions:
        failures += [f"{cond}: {f}" for f in run_flow(args.base.rstrip("/"), cond)]
    print(f"\n{'PASS' if not failures else 'FAIL'}: {len(failures)} failed checks")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
