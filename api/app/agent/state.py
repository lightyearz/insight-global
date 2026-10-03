"""LangGraph state: JSON-able dicts only (pydantic ``model_dump(mode="json")``), so checkpoints stay portable."""

from __future__ import annotations

from typing import Any, TypedDict


class BriefingState(TypedDict, total=False):
    briefing_id: str
    fixture_slug: str | None
    condition_input: str
    region: str
    condition: dict[str, Any]
    normalisation: str
    sources: list[dict[str, Any]]
    # source_id -> ExtractTreatmentsOutput dict (successful extractions only)
    extractions: dict[str, dict[str, Any]]
    options: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    review: dict[str, Any] | None
    report: dict[str, Any] | None
