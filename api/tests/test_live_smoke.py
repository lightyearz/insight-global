"""Opt-in live smoke test: sends every structured-output schema to the configured Gemini provider once.

Verifies what unit tests cannot: that the provider accepts our JSON Schema subset (``additionalProperties:
false``, ``$defs``/``$ref``, ``anyOf`` with null, enums, minItems/maxItems) and that each response validates.

    RUN_LIVE_LLM=1 GEMINI_API_KEY=... uv run pytest -m live          # Gemini Developer API
    RUN_LIVE_LLM=1 GOOGLE_CLOUD_PROJECT=... uv run pytest -m live    # Vertex AI via ADC

Skipped by default (no network or credentials in CI).
"""

from __future__ import annotations

import os

import pytest

from app.agent import prompts
from app.agent.llm_outputs import LLM_OUTPUT_MODELS, LLMRequest
from app.config import Settings
from app.llm.base import build_llm_client

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE_LLM") != "1", reason="set RUN_LIVE_LLM=1 to call Gemini"),
]

SOURCE_TEXT = (
    "RECOMMENDATIONS: Metformin is recommended as first-line pharmacotherapy for adults with type 2 diabetes "
    "(strong recommendation). In 2022, SGLT-2 inhibitors were added as first-line therapy for people with "
    "chronic kidney disease. DPP-4 inhibitors are not recommended as add-on therapy."
)

PROMPTS = {
    "extract_treatments": (prompts.EXTRACT_SYSTEM, f'<source id="pubmed:1">\n{SOURCE_TEXT}\n</source>'),
    "consolidate_options": (prompts.CONSOLIDATE_SYSTEM, '<data>[{"ref": "pubmed:1#0", "name": "Metformin"}]</data>'),
    "detect_conflicts": (prompts.CONFLICTS_SYSTEM, f'<source id="pubmed:1">\n{SOURCE_TEXT}\n</source>'),
    "suggest_relevance": (
        prompts.RELEVANCE_SYSTEM,
        '<data>[{"option_id": "opt-metformin", "name": "Metformin"}]</data>',
    ),
    "write_report": (prompts.REPORT_SYSTEM, '<data>[{"name": "Metformin", "summary": "First-line."}]</data>'),
}


@pytest.mark.parametrize("step", list(LLM_OUTPUT_MODELS))
async def test_provider_accepts_schema_and_returns_valid_output(step):
    settings = Settings()
    if settings.llm_provider == "replay":
        pytest.skip("no Gemini credentials configured")
    client = build_llm_client(settings)
    system, prompt = PROMPTS[step]
    result = await client.generate(LLMRequest(step=step, system=system, prompt=prompt), LLM_OUTPUT_MODELS[step])
    assert result.parsed is not None
    assert result.tokens_in > 0
