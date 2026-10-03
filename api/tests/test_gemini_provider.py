"""GeminiLLMClient against a stub google-genai client (no network, no credentials)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors
from google.genai import types

from app.agent.llm_outputs import LLMError, LLMRequest, SuggestRelevanceOutput, WriteReportOutput
from app.llm.gemini import GeminiLLMClient
from app.llm.pricing import estimate_cost_usd
from tests.conftest import make_settings

GOOD = '{"title": "T", "top_level_description": "D", "key_takeaways": ["a", "b", "c"]}'


class StubModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        usage = SimpleNamespace(prompt_token_count=100, candidates_token_count=20, thoughts_token_count=5)
        return SimpleNamespace(text=r, usage_metadata=usage)


def make_client(tmp_path, responses):
    settings = make_settings(tmp_path, LLM_PROVIDER="gemini_api", gemini_api_key="unit-test-key", llm_max_retries=2)
    models = StubModels(responses)
    stub = SimpleNamespace(aio=SimpleNamespace(models=models))
    client = GeminiLLMClient("gemini_api", stub, settings)  # type: ignore[arg-type]
    return client, models


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _sleep(_s):
        return None

    monkeypatch.setattr("app.llm.gemini.asyncio.sleep", _sleep)


async def test_main_model_call_shape_and_usage(tmp_path):
    client, models = make_client(tmp_path, [GOOD])
    req = LLMRequest(step="write_report", system="SYS", prompt="PROMPT")
    res = await client.generate(req, WriteReportOutput)
    assert res.parsed.title == "T" and res.model == "gemini-3.8-flash"
    assert (res.tokens_in, res.tokens_out) == (100, 25)
    call = models.calls[0]
    cfg: types.GenerateContentConfig = call["config"]
    assert call["model"] == "gemini-3.8-flash" and call["contents"] == "PROMPT"
    assert cfg.system_instruction == "SYS" and cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema["properties"]["key_takeaways"]["minItems"] == 3
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert cfg.response_schema is None


async def test_lite_model_has_no_thinking_config(tmp_path):
    client, models = make_client(tmp_path, ['{"suggestions": []}'])
    req = LLMRequest(step="suggest_relevance", system="s", prompt="p")
    res = await client.generate(req, SuggestRelevanceOutput)
    assert res.model == "gemini-3.5-flash-lite"
    assert models.calls[0]["config"].thinking_config is None


async def test_validation_failure_is_retried_with_error_in_prompt(tmp_path):
    client, models = make_client(tmp_path, ['{"title": "T"}', GOOD])
    res = await client.generate(LLMRequest(step="write_report", system="s", prompt="P"), WriteReportOutput)
    assert res.parsed.title == "T"
    assert len(models.calls) == 2
    assert "did not validate" in models.calls[1]["contents"]
    assert (res.tokens_in, res.tokens_out) == (200, 50)  # both attempts are billed


async def test_retryable_api_error_then_success(tmp_path):
    err = genai_errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})
    client, models = make_client(tmp_path, [err, GOOD])
    res = await client.generate(LLMRequest(step="write_report", system="s", prompt="P"), WriteReportOutput)
    assert res.parsed.title == "T" and len(models.calls) == 2


async def test_non_retryable_error_raises_llm_error(tmp_path):
    err = genai_errors.ClientError(400, {"error": {"code": 400, "message": "bad schema", "status": "INVALID"}})
    client, models = make_client(tmp_path, [err, GOOD])
    with pytest.raises(LLMError, match="400"):
        await client.generate(LLMRequest(step="write_report", system="s", prompt="P"), WriteReportOutput)
    assert len(models.calls) == 1


async def test_gives_up_after_retries(tmp_path):
    client, models = make_client(tmp_path, ["", "", ""])
    with pytest.raises(LLMError, match="empty response"):
        await client.generate(LLMRequest(step="write_report", system="s", prompt="P"), WriteReportOutput)
    assert len(models.calls) == 3


def test_pricing():
    assert estimate_cost_usd("gemini-3.8-flash", 1_000_000, 1_000_000) == pytest.approx(4.5)
    assert estimate_cost_usd("gemini-3.5-flash-lite", 1_000_000, 0) == pytest.approx(0.30)
    assert estimate_cost_usd("replay", 10, 10) == 0.0
    assert estimate_cost_usd("unknown-model", 10, 10) == 0.0


def _resp(text, finish="STOP", block=None, version="gemini-3.8-flash-001"):
    usage = SimpleNamespace(prompt_token_count=10, candidates_token_count=2, thoughts_token_count=0)
    cand = SimpleNamespace(finish_reason=SimpleNamespace(name=finish))
    feedback = SimpleNamespace(block_reason=SimpleNamespace(name=block)) if block else None
    return SimpleNamespace(
        text=text, usage_metadata=usage, candidates=[cand], prompt_feedback=feedback, model_version=version
    )


class RawStub(StubModels):
    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make_raw_client(tmp_path, responses):
    settings = make_settings(tmp_path, LLM_PROVIDER="gemini_api", gemini_api_key="unit-test-key", llm_max_retries=2)
    models = RawStub(responses)
    return GeminiLLMClient("gemini_api", SimpleNamespace(aio=SimpleNamespace(models=models)), settings), models


async def test_safety_block_is_not_retried_and_usage_is_reported(tmp_path):
    client, models = make_raw_client(tmp_path, [_resp("", finish="SAFETY"), _resp(GOOD)])
    with pytest.raises(LLMError, match="SAFETY") as info:
        await client.generate(LLMRequest(step="write_report", system="s", prompt="P"), WriteReportOutput)
    assert len(models.calls) == 1
    assert (info.value.tokens_in, info.value.tokens_out, info.value.model) == (10, 2, "gemini-3.8-flash")


async def test_prompt_block_is_not_retried(tmp_path):
    client, models = make_raw_client(tmp_path, [_resp("", block="JAILBREAK"), _resp(GOOD)])
    with pytest.raises(LLMError, match="prompt blocked"):
        await client.generate(LLMRequest(step="write_report", system="s", prompt="P"), WriteReportOutput)
    assert len(models.calls) == 1


async def test_recitation_retries_with_shorter_quote_instruction(tmp_path):
    client, models = make_raw_client(tmp_path, [_resp("", finish="RECITATION"), _resp(GOOD)])
    res = await client.generate(LLMRequest(step="write_report", system="s", prompt="P"), WriteReportOutput)
    assert res.parsed.title == "T" and res.model_version == "gemini-3.8-flash-001"
    assert "recitation filter" in models.calls[1]["contents"]


async def test_max_tokens_retries_with_a_higher_limit(tmp_path):
    client, models = make_raw_client(tmp_path, [_resp('{"title": "T"', finish="MAX_TOKENS"), _resp(GOOD)])
    await client.generate(LLMRequest(step="write_report", system="s", prompt="P"), WriteReportOutput)
    first, second = (c["config"].max_output_tokens for c in models.calls)
    assert second == first * 2


async def test_thinking_level_is_configurable_per_step(tmp_path):
    settings = make_settings(
        tmp_path,
        LLM_PROVIDER="gemini_api",
        gemini_api_key="k",
        gemini_thinking_level="medium",
        gemini_thinking_level_conflicts="high",
    )
    client = GeminiLLMClient("gemini_api", SimpleNamespace(), settings)  # type: ignore[arg-type]
    cfg = client._config(LLMRequest(step="detect_conflicts", system="s", prompt="p"), WriteReportOutput, 1024)
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.HIGH
    cfg = client._config(LLMRequest(step="write_report", system="s", prompt="p"), WriteReportOutput, 1024)
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM


def test_pricing_prefix_and_date():
    from datetime import date

    assert estimate_cost_usd("gemini-3.8-flash-001", 1_000_000, 0, on=date(2026, 10, 3)) == pytest.approx(0.75)
    assert estimate_cost_usd("gemini-3.8-flash", 1_000_000, 0, on=date(2027, 1, 1)) == pytest.approx(1.50)
    assert estimate_cost_usd("gemini-3.8-flash-lite-x", 1_000_000, 0) >= 0  # unknown variants never crash
