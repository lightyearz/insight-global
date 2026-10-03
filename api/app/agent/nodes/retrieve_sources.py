"""retrieve_sources: PubMed + MedlinePlus in parallel (live) or sources.json (replay)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from app.agent.deps import AgentDeps, NodeResult
from app.agent.policy import TIER_RULES
from app.agent.state import BriefingState
from app.connectors.http import UpstreamError
from app.connectors.pubmed import build_queries
from app.schemas import Briefing, Condition, NormalisationMethod, ReplayManifest, SearchStrategy, Source
from app.store import utcnow

logger = logging.getLogger(__name__)

PUBLICATION_TYPES = [
    "Practice Guideline",
    "Guideline",
    "Systematic Review",
    "Meta-Analysis",
]


def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def select_sources(found: list[Source], max_sources: int) -> list[Source]:
    """Dedupe by id and by normalised title (guidelines are often co-published in several journals);
    keep every MedlinePlus summary and fill the rest with PubMed in search order."""
    seen: set[str] = set()
    unique: list[Source] = []
    for s in found:
        keys = {s.id, f"title:{_title_key(s.title)}"}
        if not keys & seen:
            seen.update(keys)
            unique.append(s)
    consumer = [s for s in unique if s.connector == "medlineplus"][:max_sources]
    pubmed = [s for s in unique if s.connector == "pubmed"][: max(0, max_sources - len(consumer))]
    return pubmed + consumer


def describe(sources: list[Source]) -> str:
    n_pm = sum(1 for s in sources if s.connector == "pubmed")
    n_mp = sum(1 for s in sources if s.connector == "medlineplus")
    return f"{len(sources)} sources ({n_pm} PubMed, {n_mp} MedlinePlus)"


def failure_summary(exc: BaseException) -> str:
    """Safe, short description of a connector failure for events (never a URL or query string)."""
    code = getattr(exc, "status_code", None)
    return f"{type(exc).__name__}{f' (HTTP {code})' if code else ''}"


def search_strategy(
    deps: AgentDeps,
    condition: Condition,
    method: NormalisationMethod,
    found: int,
    selected: list[Source],
) -> SearchStrategy:
    settings = deps.settings
    replay = settings.data_mode == "replay"
    as_of = max((s.retrieved_at for s in selected), default=utcnow())
    queries = [q for q, _ in build_queries(condition, settings, now=as_of)]
    return SearchStrategy(
        condition_input=condition.input,
        normalised_label=condition.label,
        mesh_id=condition.mesh_id,
        normalisation=method,
        connectors=[
            f"PubMed (NCBI E-utilities): up to {settings.pubmed_guideline_max} guidelines and "
            f"{settings.pubmed_review_max} systematic reviews / meta-analyses, by relevance",
            "MedlinePlus Health Topics (NLM consumer summary), with page created/modified dates",
        ],
        pubmed_queries=queries,
        publication_types=PUBLICATION_TYPES,
        date_window=f"{as_of.year - settings.pubmed_years} to present (PubMed publication date), English, "
        "with abstract",
        max_sources=settings.max_sources,
        sources_found=found,
        sources_selected=len(selected),
        tier_rules=list(TIER_RULES),
        data_mode=settings.data_mode,
        note=(
            "Replay: these sources were recorded earlier (see 'Retrieved' dates); the queries are the ones a live "
            "run issues."
            if replay
            else ""
        ),
    )


async def run(deps: AgentDeps, state: BriefingState) -> NodeResult:
    bid = state["briefing_id"]
    condition = Condition.model_validate(state["condition"])
    method: NormalisationMethod = state.get("normalisation", "none")  # type: ignore[assignment]
    if deps.settings.data_mode == "replay":
        slug = state.get("fixture_slug")
        assert slug
        sources = deps.replay.sources(slug)
        found = len(sources)
        for connector in ("pubmed", "medlineplus"):
            count = sum(1 for s in sources if s.connector == connector)
            await deps.events.emit(
                bid,
                "retrieve_sources",
                "progress",
                f"{connector}: {count} sources (replay)",
                {"connector": connector, "count": count},
            )
    else:
        assert deps.pubmed is not None and deps.medlineplus is not None
        names = ("pubmed", "medlineplus")
        results = await asyncio.gather(
            deps.pubmed.search(condition), deps.medlineplus.search(condition), return_exceptions=True
        )
        found_list: list[Source] = []
        for name, res in zip(names, results, strict=True):
            if isinstance(res, BaseException):
                if not isinstance(res, UpstreamError | ValueError):
                    logger.warning("Connector %s failed unexpectedly: %s", name, type(res).__name__)
                summary = failure_summary(res)
                await deps.events.emit(
                    bid,
                    "retrieve_sources",
                    "progress",
                    f"{name}: failed ({summary}); continuing",
                    {"connector": name, "count": 0, "warning": True},
                )
                continue
            found_list.extend(res)
            await deps.events.emit(
                bid,
                "retrieve_sources",
                "progress",
                f"{name}: {len(res)} sources",
                {"connector": name, "count": len(res)},
            )
        found = len(found_list)
        sources = select_sources(found_list, deps.settings.max_sources)
        if deps.settings.record_fixtures and state.get("fixture_slug"):
            record_sources(deps, state["fixture_slug"] or "", condition, sources)

    if not sources:
        raise RuntimeError(f"No sources found for '{condition.label}'")
    strategy = search_strategy(deps, condition, method, found, sources)

    def patch(b: Briefing) -> None:
        b.sources = sources
        b.search_strategy = strategy

    return NodeResult(
        update={"sources": [s.model_dump(mode="json") for s in sources]},
        message=f"Retrieved {describe(sources)}",
        detail=describe(sources),
        data={"count": len(sources), "found": found},
        patch=patch,
    )


# ---------------------------------------------------------------------------
# Fixture recording (RECORD_FIXTURES=1, live data only)
# ---------------------------------------------------------------------------


def recording_dir(deps: AgentDeps, recording_key: str) -> Path:
    """Per-briefing recording folder: <DATA_DIR>/recordings/<slug>.<briefing id>/ (never the fixtures folder)."""
    return deps.settings.recordings_path / recording_key


def record_sources(deps: AgentDeps, recording_key: str, condition: Condition, sources: list[Source]) -> None:
    """Write manifest/condition/sources next to the recorded LLM outputs. Promoted by the runner on success."""
    slug = recording_key.split(".", 1)[0]
    folder = recording_dir(deps, recording_key)
    folder.mkdir(parents=True, exist_ok=True)
    s = deps.settings
    manifest = ReplayManifest(
        slug=slug,
        label=condition.label,
        aliases=sorted({condition.input.lower().strip()} - {condition.label.lower()}),
        recorded_at=utcnow(),
        recorded_with=f"{s.llm_provider}: {s.gemini_model} + {s.gemini_model_lite}",
        notes="Recorded from a live run (RECORD_FIXTURES=1). write_report.json reflects that run's review.",
    )
    (folder / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (folder / "condition.json").write_text(condition.model_dump_json(indent=2) + "\n", encoding="utf-8")
    payload = [src.model_dump(mode="json") for src in sources]
    (folder / "sources.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
