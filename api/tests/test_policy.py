from datetime import UTC, datetime

import pytest

from app.agent.policy import (
    cap_confidence,
    compare_dates,
    medlineplus_tier,
    pubmed_tier,
    recommendation_direction,
    slugify,
    suggest_resolution,
    unique_id,
)
from app.schemas import ConflictPosition, Evidence, Source

NOW = datetime(2026, 9, 30, tzinfo=UTC)


def src(sid: str, tier: int, published: str | None, *, updated: str | None = None, region=None) -> Source:
    types = {1: "clinical_guideline", 2: "systematic_review", 3: "consumer_health_summary", 4: "other"}
    return Source(
        id=sid,
        connector="pubmed" if sid.startswith("pubmed") else "medlineplus",
        title=f"Title {sid}",
        publisher="Pub",
        url=f"https://pubmed.ncbi.nlm.nih.gov/{sid.split(':')[1]}/"
        if sid.startswith("pubmed")
        else "https://medlineplus.gov/x.html",
        source_type=types[tier],
        reliability_tier=tier,
        tier_rationale="test",
        region=region,
        published_at=published,
        updated_at=updated,
        retrieved_at=NOW,
        excerpt="Some excerpt text long enough.",
    )


def pos(s: Source, side: int) -> ConflictPosition:
    return ConflictPosition(
        source_id=s.id,
        side=side,
        statement="x",
        quote="q" * 12,
        published_at=s.published_at,
        reliability_tier=s.reliability_tier,
        grounded=True,
    )


# --- tiering -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("types", "tier", "stype"),
    [
        (["Journal Article", "Practice Guideline", "Review"], 1, "clinical_guideline"),
        (["Guideline"], 1, "clinical_guideline"),
        (["Systematic Review", "Practice Guideline"], 1, "clinical_guideline"),
        (["Journal Article", "Systematic Review"], 2, "systematic_review"),
        (["Meta-Analysis"], 2, "systematic_review"),
        (["Journal Article", "Review"], 4, "other"),
        ([], 4, "other"),
    ],
)
def test_pubmed_tier(types, tier, stype):
    t, st, rationale = pubmed_tier(types)
    assert (t, st) == (tier, stype)
    assert rationale


def test_medlineplus_tier():
    assert medlineplus_tier()[:2] == (3, "consumer_health_summary")


# --- confidence --------------------------------------------------------------


def ev(sid: str, grounded: bool = True) -> Evidence:
    return Evidence(source_id=sid, quote="q" * 30, statement="s", grounded=grounded)


def test_confidence_cap_rules():
    sources = {
        s.id: s for s in [src("pubmed:1", 1, "2024"), src("pubmed:2", 2, "2022"), src("medlineplus:a", 3, "2020")]
    }
    assert cap_confidence("high", [ev("pubmed:1"), ev("pubmed:2")], sources) == "high"
    assert cap_confidence("high", [ev("pubmed:1")], sources) == "medium"  # one strong source is not "multiple"
    assert cap_confidence("high", [ev("medlineplus:a")], sources) == "medium"
    assert cap_confidence("high", [ev("pubmed:1", grounded=False)], sources) == "low"
    # any ungrounded item lowers one more level
    assert (
        cap_confidence("high", [ev("pubmed:1"), ev("pubmed:2"), ev("medlineplus:a", grounded=False)], sources)
        == "medium"
    )
    assert cap_confidence("low", [ev("pubmed:1")], sources) == "low"


# --- conflict resolution policy ---------------------------------------------


def test_lower_tier_wins_contradiction():
    a, b = src("pubmed:1", 1, "2019"), src("pubmed:2", 2, "2024")
    r = suggest_resolution("contradiction", [pos(b, 1), pos(a, 2)], {a.id: a, b.id: b}, "US")
    assert r.decision == "accept_source" and r.accepted_source_id == "pubmed:1"
    assert "outranks" in r.rationale


def test_same_tier_most_recent_wins_using_updated_at():
    a = src("pubmed:1", 1, "2023-05")
    b = src("medlineplus:x", 1, "2015", updated="2025-01-01")
    r = suggest_resolution("outdated_guidance", [pos(a, 1), pos(b, 2)], {a.id: a, b.id: b}, "US")
    assert r.accepted_source_id == "medlineplus:x"


def test_undated_counts_as_oldest():
    a, b = src("pubmed:1", 2, None), src("pubmed:2", 2, "2001")
    r = suggest_resolution("contradiction", [pos(a, 1), pos(b, 2)], {a.id: a, b.id: b}, "US")
    assert r.accepted_source_id == "pubmed:2"


def test_full_tie_keeps_both():
    a, b = src("pubmed:1", 2, "2021"), src("pubmed:2", 2, "2021")
    r = suggest_resolution("contradiction", [pos(a, 1), pos(b, 2)], {a.id: a, b.id: b}, "US")
    assert r.decision == "accept_both_with_context" and r.accepted_source_id is None


def test_regional_variation_prefers_matching_region():
    us, uk = src("pubmed:1", 1, "2020", region="US"), src("pubmed:2", 1, "2024", region="UK")
    r = suggest_resolution("regional_variation", [pos(us, 1), pos(uk, 2)], {us.id: us, uk.id: uk}, "UK")
    assert r.decision == "accept_source" and r.accepted_source_id == "pubmed:2"
    r2 = suggest_resolution("regional_variation", [pos(us, 1), pos(uk, 2)], {us.id: us, uk.id: uk}, "EU")
    assert r2.decision == "accept_both_with_context"


def test_population_difference_keeps_both():
    a, b = src("pubmed:1", 1, "2020"), src("pubmed:2", 4, "2024")
    r = suggest_resolution("population_difference", [pos(a, 1), pos(b, 2)], {a.id: a, b.id: b}, "US")
    assert r.decision == "accept_both_with_context"


def test_slug_and_unique_ids():
    assert slugify("SGLT2 inhibitors (Empagliflozin)") == "sglt2-inhibitors-empagliflozin"
    taken: set[str] = set()
    assert [unique_id("opt-a", taken) for _ in range(3)] == ["opt-a", "opt-a-2", "opt-a-3"]


def test_guidance_titles_are_tier_1_and_reviews_stay_tier_2():
    t, st, why = pubmed_tier(
        ["Journal Article", "Research Support, Non-U.S. Gov't", "Review"],
        "Hemoglobin A1c Targets ...: A Guidance Statement Update From the American College of Physicians.",
    )
    assert (t, st) == (1, "clinical_guideline") and "Guidance Statement" in why and why.startswith("Rule:")
    # A systematic review *of* guidelines is still a review.
    assert pubmed_tier(["Systematic Review"], "A systematic review of clinical practice guidelines")[0] == 2
    assert pubmed_tier(["Review"], "KDIGO 2024 update: key recommendations")[0] == 1
    assert pubmed_tier(["Review"], "Narrative review of hypertension")[0] == 4


def test_compare_dates_is_precision_aware():
    assert compare_dates("2020-06", "2020-06-15") == 0
    assert compare_dates("2021", "2020-12-31") == 1
    assert compare_dates(None, "1999") == -1 and compare_dates(None, None) == 0


def test_month_only_vs_day_date_is_a_tie_not_a_win():
    a, b = src("pubmed:1", 2, "2020-06"), src("pubmed:2", 2, "2020-06-15")
    r = suggest_resolution("contradiction", [pos(a, 1), pos(b, 2)], {a.id: a, b.id: b}, "US")
    assert r.rule == "tie" and r.decision == "accept_both_with_context"


def test_region_breaks_a_tie():
    a, b = src("pubmed:1", 1, "2021", region="UK"), src("pubmed:2", 1, "2021", region="US")
    r = suggest_resolution("contradiction", [pos(a, 1), pos(b, 2)], {a.id: a, b.id: b}, "US")
    assert (r.rule, r.accepted_source_id) == ("region_tiebreak", "pubmed:2")


def test_sources_on_the_same_side_are_never_compared_with_each_other():
    """Regression (hypertension fixture): Canada 2025 and ESC 2024 agree (< 130), Cochrane 2020 disagrees.
    The old policy compared the two agreeing guidelines ("more recent supersedes")."""
    canada = src("pubmed:40419299", 1, "2025-05-25")
    esc = src("pubmed:39589443", 1, "2024-11-26")
    cochrane = src("pubmed:33332584", 2, "2020-12-17")
    sources = {s.id: s for s in (canada, esc, cochrane)}
    r = suggest_resolution("contradiction", [pos(canada, 1), pos(esc, 1), pos(cochrane, 2)], sources, "US")
    assert (r.rule, r.accepted_source_id) == ("higher_tier", "pubmed:40419299")
    assert "position 1" in r.rationale and "1 more source(s) agreeing" in r.rationale and "position 2" in r.rationale
    assert "tier 2 systematic review (2020-12-17)" in r.rationale


def test_hypertension_fixture_suggestions_compare_opposing_sides():
    import json

    from app.agent.llm_outputs import DetectConflictsOutput
    from app.agent.nodes.detect_conflicts import build_conflicts
    from app.config import PROJECT_DIR
    from app.connectors.replay import ReplayConnector

    replay = ReplayConnector(PROJECT_DIR / "fixtures" / "replay")
    sources = {s.id: s for s in replay.sources("hypertension")}
    raw = (PROJECT_DIR / "fixtures" / "replay" / "hypertension" / "llm" / "detect_conflicts.json").read_text()
    conflicts = {
        c.id: c for c in build_conflicts(DetectConflictsOutput.model_validate(json.loads(raw)), sources, set(), "US")
    }
    general = conflicts["conf-general-systolic-target"]
    assert [p.side for p in general.positions] == [1, 1, 2]
    assert general.suggested_resolution.rule == "higher_tier"
    assert "pubmed:33332584" in general.suggested_resolution.rationale or "systematic review" in (
        general.suggested_resolution.rationale
    )


def test_all_on_one_side_falls_back_to_one_side_per_source():
    from app.agent.llm_outputs import DetectConflictsOutput
    from app.agent.nodes.detect_conflicts import build_conflicts

    a, b = src("pubmed:1", 1, "2019"), src("pubmed:2", 2, "2024")
    out = DetectConflictsOutput.model_validate(
        {
            "conflicts": [
                {
                    "id": "conf-x",
                    "topic": "t",
                    "conflict_type": "contradiction",
                    "treatment_option_ids": [],
                    "positions": [
                        {"source_id": a.id, "side": 1, "statement": "a", "quote": "q"},
                        {"source_id": b.id, "side": 1, "statement": "b", "quote": "q"},
                    ],
                    "ai_assessment": "x",
                }
            ]
        }
    )
    [c] = build_conflicts(out, {a.id: a, b.id: b}, set(), "US")
    assert [p.side for p in c.positions] == [1, 2]


@pytest.mark.parametrize(
    ("stances", "expected"),
    [
        (["recommended", "described"], "for"),
        (["recommended_against"], "against"),
        (["recommended_against", "conditional"], "mixed"),
        (["conditional", "described"], "conditional"),
        (["described", "insufficient_evidence"], "not_stated"),
    ],
)
def test_recommendation_direction(stances, expected):
    evidence = [Evidence(source_id="pubmed:1", quote="q" * 30, statement="s", stance=s, grounded=True) for s in stances]
    assert recommendation_direction(evidence) == expected


def test_source_url_must_be_https_on_allowlisted_host():
    from pydantic import ValidationError

    for bad in (
        "javascript:alert(1)",
        "http://pubmed.ncbi.nlm.nih.gov/1/",
        "https://evil.example/",
        "data:text/html,x",
    ):
        with pytest.raises(ValidationError):
            src("pubmed:1", 1, "2020").model_copy(update={}).model_validate(
                {**src("pubmed:1", 1, "2020").model_dump(), "url": bad}
            )
