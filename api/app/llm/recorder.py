"""Optional fixture recorder (``RECORD_FIXTURES=1`` with ``DATA_MODE=live``).

Wraps a live LLM client and writes every structured output into the replay layout under a per-briefing
recording folder ``DATA_DIR/recordings/<slug>.<briefing id>/llm/...`` (never the committed fixtures).
Sources, condition and manifest are written by retrieve_sources; :func:`promote_recording` moves a
finished recording into ``FIXTURES_DIR/<slug>/`` only after the report was written, and never over an
existing fixture unless ``RECORD_OVERWRITE=1``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app.agent.llm_outputs import LLMClient, LLMRequest, LLMResult
from app.llm.replay import fixture_path

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class RecordingLLMClient:
    def __init__(self, inner: LLMClient, fixtures_dir: Path) -> None:
        self.inner = inner
        self.provider = inner.provider
        self.fixtures_dir = fixtures_dir

    async def generate(self, request: LLMRequest, output_model: type[T]) -> LLMResult[T]:
        result = await self.inner.generate(request, output_model)
        if request.fixture_slug:
            path = fixture_path(self.fixtures_dir, request)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(result.parsed.model_dump_json(indent=2) + "\n", encoding="utf-8")
            logger.info("Recorded fixture %s", path.relative_to(self.fixtures_dir))
        return result


def promote_recording(recordings_dir: Path, recording_key: str, fixtures_dir: Path, *, overwrite: bool) -> Path | None:
    """Move a completed recording into the fixtures folder. Returns the new fixture path, or None if kept."""
    src = recordings_dir / recording_key
    slug = recording_key.split(".", 1)[0]
    dest = fixtures_dir / slug
    if not (src / "manifest.json").is_file() or not (src / "llm" / "write_report.json").is_file():
        logger.warning("Recording %s is incomplete; not promoted", recording_key)
        return None
    if dest.exists():
        if not overwrite:
            logger.warning("Fixture %s exists; recording kept at %s (set RECORD_OVERWRITE=1 to replace)", slug, src)
            return None
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    logger.info("Promoted recording %s to fixture %s", recording_key, slug)
    return dest
