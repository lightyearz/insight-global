"""Fixture validation (fixtures/README.md): every file validates and every quote is grounded.

Runs over the synthetic test fixture and over any real fixtures in ../fixtures/replay.
Select with ``uv run pytest -k fixtures``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.agent.llm_outputs import LLM_OUTPUT_MODELS, ExtractTreatmentsOutput, is_grounded, source_id_to_filename
from app.config import PROJECT_DIR
from app.schemas import Condition, ReplayManifest, Source
from tests.conftest import TEST_FIXTURES

REAL_FIXTURES = PROJECT_DIR / "fixtures" / "replay"


def fixture_dirs() -> list[Path]:
    dirs = sorted(p.parent for p in TEST_FIXTURES.glob("*/manifest.json"))
    if REAL_FIXTURES.is_dir():
        dirs += sorted(p.parent for p in REAL_FIXTURES.glob("*/manifest.json"))
    return dirs


@pytest.mark.parametrize("folder", fixture_dirs(), ids=lambda p: f"{p.parent.parent.parent.name}/{p.name}")
def test_replay_fixtures_valid_and_grounded(folder: Path) -> None:
    manifest = ReplayManifest.model_validate_json((folder / "manifest.json").read_text())
    assert manifest.slug == folder.name
    Condition.model_validate_json((folder / "condition.json").read_text())
    sources = TypeAdapter(list[Source]).validate_json((folder / "sources.json").read_text())
    assert sources, "sources.json is empty"
    by_id = {s.id: s for s in sources}
    assert len(by_id) == len(sources), "duplicate source ids"

    llm = folder / "llm"
    ungrounded: list[str] = []
    for s in sources:
        path = llm / "extract_treatments" / f"{source_id_to_filename(s.id)}.json"
        assert path.is_file(), f"missing {path.relative_to(folder)}"
        out = ExtractTreatmentsOutput.model_validate_json(path.read_text())
        if out.notes and "ungrounded" in out.notes.lower():
            continue  # deliberately ungrounded item, declared in notes (fixtures/README.md)
        for t in out.treatments:
            for e in t.evidence:
                if not is_grounded(e.quote, s.excerpt):
                    ungrounded.append(f"{s.id} / {t.name}: {e.quote[:60]}")
            for m in t.milestones:
                if not is_grounded(m.quote, s.excerpt):
                    ungrounded.append(f"{s.id} / {t.name} milestone: {m.quote[:60]}")
    for step, model in LLM_OUTPUT_MODELS.items():
        if step == "extract_treatments":
            continue
        parsed = model.model_validate_json((llm / f"{step}.json").read_text())
        if step == "detect_conflicts":
            for c in parsed.conflicts:  # type: ignore[attr-defined]
                for p in c.positions:
                    assert p.source_id in by_id, f"{c.id}: unknown source {p.source_id}"
                    if not is_grounded(p.quote, by_id[p.source_id].excerpt):
                        ungrounded.append(f"{c.id} / {p.source_id}: {p.quote[:60]}")
    assert not ungrounded, "ungrounded quotes:\n" + "\n".join(ungrounded)
