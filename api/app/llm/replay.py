"""Replay provider: returns recorded structured outputs (fixtures/README.md)."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.agent.llm_outputs import LLMError, LLMRequest, LLMResult, ReplayFixtureMissing, source_id_to_filename
from app.schemas import LLMProviderName

T = TypeVar("T", bound=BaseModel)


def fixture_path(fixtures_dir: Path, request: LLMRequest) -> Path:
    if not request.fixture_slug:
        raise ReplayFixtureMissing(f"{request.step}: no replay fixture slug for this briefing")
    base = fixtures_dir / request.fixture_slug / "llm"
    if request.step == "extract_treatments":
        if not request.item_key:
            raise ReplayFixtureMissing("extract_treatments: item_key (source id) is required in replay")
        return base / "extract_treatments" / f"{source_id_to_filename(request.item_key)}.json"
    return base / f"{request.step}.json"


class ReplayLLMClient:
    provider: LLMProviderName = "replay"

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    async def generate(self, request: LLMRequest, output_model: type[T]) -> LLMResult[T]:
        path = fixture_path(self.fixtures_dir, request)
        if not path.is_file():
            rel = path.relative_to(self.fixtures_dir) if path.is_relative_to(self.fixtures_dir) else path
            raise ReplayFixtureMissing(f"{request.step}: replay fixture not found: {rel}")
        try:
            parsed = output_model.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            n = exc.error_count()
            raise LLMError(f"{request.step}: replay fixture {path.name} is invalid ({n} errors)") from exc
        return LLMResult(parsed=parsed, model="replay", tokens_in=0, tokens_out=0)
