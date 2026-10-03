"""Deterministic post-processing: option building, conflicts, relevance, timeline, report assembly."""

from datetime import UTC, datetime

from pydantic import TypeAdapter

from app.agent.llm_outputs import (
    ConsolidatedOption,
    ConsolidateOptionsOutput,
    DetectConflictsOutput,
    ExtractTreatmentsOutput,
    SuggestRelevanceOutput,
    WriteReportOutput,
)
from app.agent.nodes.consolidate_options import build_options
from app.agent.nodes.detect_conflicts import build_conflicts
from app.agent.nodes.human_review import apply_decision
from app.agent.nodes.suggest_relevance import apply_suggestions
from app.agent.nodes.write_report import assemble_report, replay_deviation_note
from app.schemas import ConflictResolution, ReviewDecision, Source
from tests.conftest import TEST_FIXTURES

FX = TEST_FIXTURES / "test-condition"


def load():
    sources = {s.id: s for s in TypeAdapter(list[Source]).validate_json((FX / "sources.json").read_text())}
    extractions = {
        sid: ExtractTreatmentsOutput.model_validate_json(
            (FX / "llm" / "extract_treatments" / f"{sid.replace(':', '_')}.json").read_text()
        )
        for sid in sources
    }
    consolidated = ConsolidateOptionsOutput.model_validate_json((FX / "llm" / "consolidate_options.json").read_text())
    return sources, extractions, consolidated


def test_build_options_grounding_milestones_and_confidence():
    sources, extractions, consolidated = load()
    options = build_options(consolidated, extractions, sources)
    by_id = {o.id: o for o in options}
    assert set(by_id) == {"opt-alphamab", "opt-betacillin", "opt-structured-exercise"}
    assert all(e.grounded for o in options for e in o.evidence)
    ex = by_id["opt-structured-exercise"]
    assert len(ex.milestones) == 1 and ex.milestones[0].date == "2022" and ex.milestones[0].grounded
    assert ex.milestones[0].date_precision == "year"
    # high needs >= 2 distinct grounded tier 1-2 sources: alphamab has tier 1 + tier 3 -> medium
    assert by_id["opt-alphamab"].confidence == "medium"
    assert by_id["opt-betacillin"].confidence == "medium"  # tier 1 + tier 2 -> cap high, proposed medium
    assert by_id["opt-alphamab"].recommendation_direction == "for"
    assert by_id["opt-betacillin"].recommendation_direction == "for"  # conditional + recommended


def test_build_options_orphans_invalid_refs_and_duplicate_ids():
    sources, extractions, _ = load()
    out = ConsolidateOptionsOutput(
        options=[
            ConsolidatedOption(
                id="opt-alphamab",
                name="Alphamab",
                category="pharmacologic",
                drug_class=None,
                line_of_therapy="first_line",
                population="p",
                summary="s",
                member_refs=["pubmed:1000001#0", "pubmed:9#0"],
                confidence="high",
            ),
            ConsolidatedOption(
                id="opt-alphamab",
                name="Alphamab dup",
                category="pharmacologic",
                drug_class=None,
                line_of_therapy="first_line",
                population="p",
                summary="s",
                member_refs=["medlineplus:testcondition#1"],
                confidence="high",
            ),
            ConsolidatedOption(
                id="BAD ID",
                name="Ghost",
                category="other",
                drug_class=None,
                line_of_therapy="unspecified",
                population="p",
                summary="s",
                member_refs=["nope#1"],
                confidence="high",
            ),
        ]
    )
    options = build_options(out, extractions, sources)
    ids = [o.id for o in options]
    assert ids[:2] == ["opt-alphamab", "opt-alphamab-2"]
    assert "opt-ghost" not in ids  # no valid refs -> dropped
    # every unreferenced extracted treatment became its own low-confidence option
    orphans = options[2:]
    assert {o.name for o in orphans} == {"Betacillin", "Structured exercise", "Regular exercise"}
    assert all(o.confidence == "low" for o in orphans)


def test_ungrounded_evidence_is_kept_and_lowers_confidence():
    sources, extractions, consolidated = load()
    ext = extractions["pubmed:1000001"]
    ext.treatments[0].evidence[0].quote = "Alphamab is the best drug ever invented for everyone."
    options = {o.id: o for o in build_options(consolidated, extractions, sources)}
    alpha = options["opt-alphamab"]
    assert [e.grounded for e in alpha.evidence] == [False, True]
    assert alpha.confidence == "low"  # cap medium (only tier-3 grounded), minus one for ungrounded


def full_flow():
    sources, extractions, consolidated = load()
    options = build_options(consolidated, extractions, sources)
    detected = DetectConflictsOutput.model_validate_json((FX / "llm" / "detect_conflicts.json").read_text())
    conflicts = build_conflicts(detected, sources, {o.id for o in options}, "US")
    rel = SuggestRelevanceOutput.model_validate_json((FX / "llm" / "suggest_relevance.json").read_text())
    options = apply_suggestions(options, rel)
    return sources, options, conflicts


def test_conflicts_validated_and_suggested():
    _, _, conflicts = full_flow()
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.treatment_option_ids == ["opt-alphamab", "opt-betacillin"]  # unknown id dropped
    assert [p.reliability_tier for p in c.positions] == [1, 2]
    assert all(p.grounded for p in c.positions)
    assert c.suggested_resolution.decision == "accept_source"
    assert c.suggested_resolution.accepted_source_id == "pubmed:1000001"


def test_conflict_with_unknown_source_is_dropped():
    sources, *_ = load()
    out = DetectConflictsOutput.model_validate(
        {
            "conflicts": [
                {
                    "id": "conf-x",
                    "topic": "t",
                    "conflict_type": "contradiction",
                    "treatment_option_ids": [],
                    "positions": [
                        {"source_id": "pubmed:1000001", "side": 1, "statement": "a", "quote": "q"},
                        {"source_id": "pubmed:42", "side": 2, "statement": "b", "quote": "q"},
                    ],
                    "ai_assessment": "x",
                }
            ]
        }
    )
    assert build_conflicts(out, sources, set(), "US") == []


def test_relevance_defaults_for_missing_options():
    _, options, _ = full_flow()
    by_id = {o.id: o for o in options}
    assert by_id["opt-alphamab"].suggested and by_id["opt-alphamab"].selected
    ex = by_id["opt-structured-exercise"]
    assert not ex.suggested and not ex.selected
    assert ex.suggestion_reason == "No suggestion returned by model"


def test_report_assembly_and_timeline():
    sources, options, conflicts = full_flow()
    now = datetime(2026, 10, 1, tzinfo=UTC)
    decision = ReviewDecision(
        selected_option_ids=["opt-structured-exercise", "opt-alphamab"],
        conflict_resolutions={
            conflicts[0].id: ConflictResolution(
                decision="custom", note="Use local formulary", resolved_by="admin", resolved_at=now
            )
        },
        reviewed_by="admin",
        reviewed_at=now,
    )
    options, conflicts, audit = apply_decision(options, conflicts, decision)
    assert [a.action for a in audit].count("conflict_resolved") == 1
    assert {a.action for a in audit} >= {"review_submitted", "option_selected", "option_excluded"}
    narrative = WriteReportOutput.model_validate_json((FX / "llm" / "write_report.json").read_text())
    report = assemble_report(
        narrative=narrative,
        model="replay",
        condition={"input": "tc", "label": "Test", "mesh_id": None, "synonyms": []},
        region="US",
        options=options,
        conflicts=conflicts,
        all_sources=list(sources.values()),
        audit_log=audit,
        decision=decision,
        llm_provider="replay",
        data_mode="replay",
        generated_at=now,
    )
    # selected only, ordered by line of therapy then confidence then name
    assert [o.id for o in report.treatment_options] == ["opt-alphamab", "opt-structured-exercise"]
    # sources: tier ascending; includes conflict-only source pubmed:1000002
    assert [s.id for s in report.sources] == ["pubmed:1000001", "pubmed:1000002", "medlineplus:testcondition"]
    assert report.research_conducted_at == max(s.retrieved_at for s in sources.values())
    kinds = [e.kind for e in report.timeline]
    assert kinds[-1] == "research_conducted" and kinds.count("research_conducted") == 1
    dates = [e.date for e in report.timeline[:-1]]
    assert dates == sorted(dates)
    ids = {e.id for e in report.timeline}
    assert {
        "tl-src-pubmed-1000001",
        "tl-src-pubmed-1000002",
        "tl-src-medlineplus-testcondition",
        "tl-upd-medlineplus-testcondition",
        "tl-ms-structured-exercise-1",
        "tl-research",
    } == ids
    research = report.timeline[-1]
    assert research.date == "2026-09-30" and "3 sources retrieved (replay)" in research.description
    guideline = next(e for e in report.timeline if e.id == "tl-src-pubmed-1000001")
    assert guideline.kind == "guideline_published"
    assert set(guideline.treatment_option_ids) == {"opt-alphamab", "opt-structured-exercise"}


def test_replay_deviation_note_only_when_review_departs_from_suggestions():
    _, options, conflicts = full_flow()
    now = datetime(2026, 10, 1, tzinfo=UTC)

    def decide(selected: list[str], decision: str, accepted: str | None):
        d = ReviewDecision(
            selected_option_ids=selected,
            conflict_resolutions={
                c.id: ConflictResolution(
                    decision=decision, accepted_source_id=accepted, note="n", resolved_by="admin", resolved_at=now
                )
                for c in conflicts
            },
            reviewed_by="admin",
            reviewed_at=now,
        )
        return apply_decision(options, conflicts, d)

    suggested = [o.id for o in options if o.suggested]
    sug = conflicts[0].suggested_resolution
    opts, confs, _ = decide(suggested, sug.decision, sug.accepted_source_id)
    assert replay_deviation_note(opts, confs) is None
    opts, confs, _ = decide([*suggested, "opt-structured-exercise"], "custom", None)
    note = replay_deviation_note(opts, confs)
    assert note is not None and "1 option selection(s) and 1 conflict decision(s)" in note
