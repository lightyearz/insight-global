"""Replay connector: manifests, condition and sources from ``FIXTURES_DIR/<slug>/`` (fixtures/README.md)."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from app.schemas import Condition, ConditionSuggestion, ReplayManifest, Source

logger = logging.getLogger(__name__)

_SOURCES = TypeAdapter(list[Source])


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


class ReplayConnector:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def manifests(self) -> list[ReplayManifest]:
        out: list[ReplayManifest] = []
        if not self.fixtures_dir.is_dir():
            return out
        for path in sorted(self.fixtures_dir.glob("*/manifest.json")):
            try:
                m = ReplayManifest.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError) as exc:
                logger.warning("Ignoring invalid replay manifest %s: %s", path, type(exc).__name__)
                continue
            if m.slug != path.parent.name:
                logger.warning("Ignoring replay manifest %s: slug %r != folder name", path, m.slug)
                continue
            out.append(m)
        return sorted(out, key=lambda m: m.label.lower())

    def match(self, condition: str) -> ReplayManifest | None:
        q = _norm(condition)
        for m in self.manifests():
            if q in {_norm(m.slug), _norm(m.slug.replace("-", " ")), _norm(m.label), *(_norm(a) for a in m.aliases)}:
                return m
        return None

    def suggest(self, q: str, limit: int = 10) -> list[ConditionSuggestion]:
        nq = _norm(q)
        out: list[ConditionSuggestion] = []
        for m in self.manifests():
            if any(nq in _norm(t) for t in (m.label, m.slug, *m.aliases)):
                out.append(ConditionSuggestion(label=m.label, code=None, source="replay"))
        return out[:limit]

    def condition(self, slug: str, typed: str) -> Condition:
        c = Condition.model_validate_json((self.fixtures_dir / slug / "condition.json").read_text(encoding="utf-8"))
        c.input = typed
        return c

    def sources(self, slug: str) -> list[Source]:
        return _SOURCES.validate_json((self.fixtures_dir / slug / "sources.json").read_text(encoding="utf-8"))
