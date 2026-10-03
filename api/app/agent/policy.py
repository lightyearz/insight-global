"""Deterministic policies (docs/CONTRACT.md sections 7.2 and 7.3). Never delegated to the LLM.

- Reliability tiers for sources.
- Confidence caps from grounding and tiers.
- Suggested resolution for conflicts.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from functools import cmp_to_key

from app.schemas import (
    Confidence,
    ConflictPosition,
    ConflictType,
    Evidence,
    RecommendationDirection,
    Region,
    ReliabilityTier,
    Source,
    SourceType,
    SuggestedResolution,
)

# ---------------------------------------------------------------------------
# Reliability tiers
# ---------------------------------------------------------------------------

GUIDELINE_PUBLICATION_TYPES = ("Practice Guideline", "Guideline")
REVIEW_PUBLICATION_TYPES = ("Systematic Review", "Meta-Analysis")

SOURCE_TYPE_LABEL: dict[SourceType, str] = {
    "clinical_guideline": "clinical guideline",
    "systematic_review": "systematic review",
    "consumer_health_summary": "consumer health summary",
    "other": "publication",
}

# Guidance documents that PubMed sometimes indexes only as "Review" (e.g. ACP "Guidance Statement").
_GUIDANCE_TITLE_RE = re.compile(
    r"\b(clinical practice guidelines?|guidelines?|guidance statement|consensus statement|position statement|"
    r"consensus report|standards of (medical )?care|scientific statement)\b",
    re.IGNORECASE,
)
# Well-known guideline bodies; matched as whole words in the title together with a guidance noun.
GUIDELINE_BODIES = (
    "ACP",
    "AAFP",
    "ADA",
    "AACE",
    "ACC",
    "AHA",
    "ATS",
    "EASD",
    "ERS",
    "ESC",
    "ESH",
    "GINA",
    "GOLD",
    "IDSA",
    "ISH",
    "KDIGO",
    "NICE",
    "SIGN",
    "USPSTF",
    "WHO",
    "American College of Physicians",
    "American Diabetes Association",
    "American Heart Association",
    "European Society of Cardiology",
    "National Institute for Health and Care Excellence",
)
_BODY_RE = re.compile(r"\b(" + "|".join(re.escape(b) for b in GUIDELINE_BODIES) + r")\b")
_BODY_NOUN_RE = re.compile(r"\b(recommendations?|statement|update|consensus|standards)\b", re.IGNORECASE)

TIER_RULES: tuple[str, ...] = (
    "Tier 1 (guideline): PubMed publication type Practice Guideline / Guideline, or a title that identifies a "
    "guidance document (guideline, guidance / consensus / position statement) or a known guideline body's "
    "recommendations.",
    "Tier 2 (systematic review): PubMed publication type Systematic Review / Meta-Analysis.",
    "Tier 3 (curated summary): MedlinePlus health topic (NLM-curated consumer summary).",
    "Tier 4 (other): any other publication.",
)


def pubmed_tier(publication_types: Iterable[str], title: str = "") -> tuple[ReliabilityTier, SourceType, str]:
    """Tier 1: guideline publication types, or a guidance title; tier 2: SR / MA; else tier 4.

    The returned rationale names the rule that applied, so reviewers can see why a source ranks where it does.
    """
    types_ = list(publication_types)
    for pt in GUIDELINE_PUBLICATION_TYPES:
        if pt in types_:
            return 1, "clinical_guideline", f"Rule: PubMed publication type '{pt}'"
    for pt in REVIEW_PUBLICATION_TYPES:
        if pt in types_:
            return 2, "systematic_review", f"Rule: PubMed publication type '{pt}'"
    shown = ", ".join(types_[:3]) or "none"
    m = _GUIDANCE_TITLE_RE.search(title)
    if m:
        return (
            1,
            "clinical_guideline",
            (f"Rule: title identifies a guidance document ('{m.group(0)}'); PubMed indexes it as '{shown}'"),
        )
    body = _BODY_RE.search(title)
    if body and _BODY_NOUN_RE.search(title):
        return (
            1,
            "clinical_guideline",
            (
                f"Rule: title names guideline body '{body.group(0)}' issuing recommendations; "
                f"PubMed indexes it as '{shown}'"
            ),
        )
    return 4, "other", f"Rule: PubMed publication type(s) '{shown}' are neither guideline nor systematic review"


def medlineplus_tier() -> tuple[ReliabilityTier, SourceType, str]:
    return 3, "consumer_health_summary", "Rule: MedlinePlus health topic (NLM-curated consumer health summary)"


# ---------------------------------------------------------------------------
# Confidence and recommendation direction
# ---------------------------------------------------------------------------

_CONF_RANK: dict[Confidence, int] = {"low": 0, "medium": 1, "high": 2}
_RANK_CONF: dict[int, Confidence] = {v: k for k, v in _CONF_RANK.items()}


def confidence_rank(c: Confidence) -> int:
    return _CONF_RANK[c]


def cap_confidence(proposed: Confidence, evidence: Sequence[Evidence], sources: dict[str, Source]) -> Confidence:
    """High needs grounded support from >= 2 distinct tier 1-2 sources ("multiple higher-tier sources agree");
    any grounded support caps at medium; nothing grounded caps at low. Any ungrounded quote lowers one level."""
    strong = {
        e.source_id
        for e in evidence
        if e.grounded and e.source_id in sources and sources[e.source_id].reliability_tier <= 2
    }
    any_grounded = any(e.grounded and e.source_id in sources for e in evidence)
    cap: Confidence = "high" if len(strong) >= 2 else "medium" if any_grounded else "low"
    rank = min(_CONF_RANK[proposed], _CONF_RANK[cap])
    if rank > 0 and any(not e.grounded for e in evidence):
        rank -= 1
    return _RANK_CONF[rank]


def recommendation_direction(evidence: Sequence[Evidence]) -> RecommendationDirection:
    """for / against / conditional / mixed from the stances of grounded evidence (all evidence if none grounded)."""
    pool = [e for e in evidence if e.grounded] or list(evidence)
    stances = {e.stance for e in pool}
    pro = "recommended" in stances
    con = "recommended_against" in stances
    cond = "conditional" in stances
    if con and (pro or cond):
        return "mixed"
    if con:
        return "against"
    if pro:
        return "for"
    if cond:
        return "conditional"
    return "not_stated"


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------


def effective_date(source: Source) -> str | None:
    """updated_at if stated, else published_at. None sorts as the oldest."""
    return source.updated_at or source.published_at


def compare_dates(a: str | None, b: str | None) -> int:
    """Precision-aware: 1 if a is later, -1 if earlier, 0 if equal or indistinguishable.

    "2020-06" vs "2020-06-15" is a tie (the month-only date could be either side); undated is oldest.
    """
    if a is None or b is None:
        return 0 if a == b else (1 if b is None else -1)
    n = min(len(a), len(b))
    return (a[:n] > b[:n]) - (a[:n] < b[:n])


def _describe(source: Source) -> str:
    date = effective_date(source) or "undated"
    return f"tier {source.reliability_tier} {SOURCE_TYPE_LABEL[source.source_type]} ({date})"


def _better(a: Source, b: Source) -> bool:
    """a ranks above b: lower tier, then later effective date."""
    if a.reliability_tier != b.reliability_tier:
        return a.reliability_tier < b.reliability_tier
    return compare_dates(effective_date(a), effective_date(b)) > 0


def _best(group: Sequence[Source]) -> Source:
    best = group[0]
    for s in group[1:]:
        if _better(s, best):
            best = s
    return best


def sides_of(positions: Sequence[ConflictPosition], sources: dict[str, Source]) -> list[list[Source]]:
    """Distinct sources grouped by position side, in order of first appearance."""
    groups: dict[int, list[Source]] = {}
    for p in positions:
        s = sources.get(p.source_id)
        if s is None:
            continue
        group = groups.setdefault(p.side, [])
        if all(s.id != g.id for g in group):
            group.append(s)
    return [g for g in groups.values() if g]


def _side_text(n: int, group: Sequence[Source], best: Source) -> str:
    agree = f", with {len(group) - 1} more source(s) agreeing" if len(group) > 1 else ""
    return f"position {n}: {_describe(best)}{agree}"


def suggest_resolution(
    conflict_type: ConflictType,
    positions: Sequence[ConflictPosition],
    sources: dict[str, Source],
    briefing_region: Region,
) -> SuggestedResolution:
    """Deterministic suggestion shown to the human reviewer (docs/CONTRACT.md section 7.3).

    Sources that give the same answer share a ``side``; the best source of each side (lowest tier, then
    most recent) represents it, and the two best sides are compared. A side is never compared with itself.
    """
    sides = sides_of(positions, sources)
    distinct = [s for g in sides for s in g]

    if conflict_type == "regional_variation":
        matching = [s for s in distinct if s.region == briefing_region]
        if len(matching) == 1:
            s = matching[0]
            inferred = " (region inferred by AI from the source text)" if s.region_inferred else ""
            return SuggestedResolution(
                decision="accept_source",
                accepted_source_id=s.id,
                rule="regional_match",
                rationale=(
                    f"Regional variation: only {s.issuing_body or s.publisher} ({_describe(s)}) targets the "
                    f"briefing region ({briefing_region}){inferred}."
                ),
            )
        return SuggestedResolution(
            decision="accept_both_with_context",
            accepted_source_id=None,
            rule="regional_context",
            rationale=(
                f"Regional variation: {'no' if not matching else 'more than one'} position matches the briefing "
                f"region ({briefing_region}), so the positions are kept with their regional context."
            ),
        )

    if conflict_type == "population_difference" or len(sides) < 2:
        return SuggestedResolution(
            decision="accept_both_with_context",
            accepted_source_id=None,
            rule="population_context",
            rationale="Population difference: the positions apply to different patient groups, so they are kept "
            "with the population stated.",
        )

    # contradiction / outdated_guidance: compare the best source of each side.
    ranked = sorted(
        ((i + 1, g, _best(g)) for i, g in enumerate(sides)),
        key=cmp_to_key(lambda a, b: -1 if _better(a[2], b[2]) else (1 if _better(b[2], a[2]) else 0)),
    )
    (n1, g1, best), (n2, g2, other) = ranked[0], ranked[1]
    if best.reliability_tier < other.reliability_tier:
        return SuggestedResolution(
            decision="accept_source",
            accepted_source_id=best.id,
            rule="higher_tier",
            rationale=f"Rule (higher tier): {_side_text(n1, g1, best)} outranks {_side_text(n2, g2, other)}.",
        )
    cmp = compare_dates(effective_date(best), effective_date(other))
    if cmp > 0:
        return SuggestedResolution(
            decision="accept_source",
            accepted_source_id=best.id,
            rule="more_recent_same_tier",
            rationale=(
                f"Rule (same tier, newer wins): {_side_text(n1, g1, best)} is more recent than "
                f"{_side_text(n2, g2, other)}. This is a recency rule, not a judgement of the evidence."
            ),
        )
    in_region = [s for s in (best, other) if s.region == briefing_region]
    if len(in_region) == 1:
        s = in_region[0]
        return SuggestedResolution(
            decision="accept_source",
            accepted_source_id=s.id,
            rule="region_tiebreak",
            rationale=(
                f"Rule (tie on tier and date, region breaks the tie): only {s.issuing_body or s.publisher} "
                f"targets the briefing region ({briefing_region})."
            ),
        )
    return SuggestedResolution(
        decision="accept_both_with_context",
        accepted_source_id=None,
        rule="tie",
        rationale=(
            f"Rule (tie): the best sources on each side tie on reliability tier ({best.reliability_tier}) and date "
            f"({effective_date(best) or 'undated'}), so the positions are kept with context."
        ),
    )


# ---------------------------------------------------------------------------
# Ids
# ---------------------------------------------------------------------------


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug[:max_len].strip("-") or "item"


def unique_id(candidate: str, taken: set[str]) -> str:
    if candidate not in taken:
        taken.add(candidate)
        return candidate
    n = 2
    while f"{candidate}-{n}" in taken:
        n += 1
    taken.add(f"{candidate}-{n}")
    return f"{candidate}-{n}"
