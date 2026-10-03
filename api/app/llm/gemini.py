"""Gemini provider (google-genai >= 2.28) shared by the ``vertex`` and ``gemini_api`` modes.

Call shape verified against the installed google-genai source (docs/CONTRACT.md section 9):
``client.aio.models.generate_content(..., config=GenerateContentConfig(response_json_schema=...))``.
Secrets are never logged: only the step, model, attempt and error class/code are.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import TypeVar

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.agent.llm_outputs import MODEL_TIER_BY_STEP, LLMError, LLMRequest, LLMResult, gemini_json_schema
from app.config import Settings
from app.schemas import LLMProviderName

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}


class _RetryableError(Exception):
    pass


# Finish reasons where repeating the identical request is pointless.
_BLOCKED_FINISH = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "LANGUAGE"}
_THINKING = {"low": types.ThinkingLevel.LOW, "medium": types.ThinkingLevel.MEDIUM, "high": types.ThinkingLevel.HIGH}

RECITATION_HINT = (
    "\n\nYour previous answer was stopped by the recitation filter. Keep every quote to the shortest span "
    "(one sentence or clause, at most about 30 words) that states the point; do not copy longer passages."
)
MAX_TOKENS_HINT = "\n\nYour previous answer was cut off at the output limit. Be more concise: shorter summaries."


def _enum_name(value: object) -> str:
    return str(getattr(value, "name", value) or "")


class GeminiLLMClient:
    def __init__(self, provider: LLMProviderName, client: genai.Client, settings: Settings) -> None:
        self.provider = provider
        self._client = client
        self._settings = settings

    def model_for(self, request: LLMRequest) -> str:
        tier = MODEL_TIER_BY_STEP[request.step]
        return self._settings.gemini_model_lite if tier == "lite" else self._settings.gemini_model

    def _config(
        self, request: LLMRequest, output_model: type[BaseModel], max_output_tokens: int
    ) -> types.GenerateContentConfig:
        kwargs: dict[str, object] = {}
        if MODEL_TIER_BY_STEP[request.step] == "main":
            # gemini-3.8-flash rejects MINIMAL; LOW is the cheapest accepted level.
            level = (
                self._settings.gemini_thinking_level_conflicts
                if request.step == "detect_conflicts"
                else self._settings.gemini_thinking_level
            )
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=_THINKING[level])
        return types.GenerateContentConfig(
            system_instruction=request.system,
            response_mime_type="application/json",
            response_json_schema=gemini_json_schema(output_model),
            max_output_tokens=max_output_tokens,
            http_options=types.HttpOptions(timeout=int(self._settings.llm_timeout_s * 1000)),
            **kwargs,  # type: ignore[arg-type]
        )

    async def generate(self, request: LLMRequest, output_model: type[T]) -> LLMResult[T]:
        model = self.model_for(request)
        max_tokens = max(1024, self._settings.llm_max_output_tokens)
        prompt = request.prompt
        attempts = max(1, self._settings.llm_max_retries + 1)
        tokens_in = tokens_out = 0
        version: str | None = None
        last_error = "unknown error"
        for attempt in range(1, attempts + 1):
            config = self._config(request, output_model, max_tokens)
            try:
                resp = await asyncio.wait_for(
                    self._client.aio.models.generate_content(model=model, contents=prompt, config=config),
                    timeout=self._settings.llm_timeout_s + 5,
                )
                usage = resp.usage_metadata
                if usage is not None:
                    tokens_in += usage.prompt_token_count or 0
                    tokens_out += (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                version = getattr(resp, "model_version", None) or version
                feedback = getattr(resp, "prompt_feedback", None)
                block = _enum_name(getattr(feedback, "block_reason", None))
                if block and block != "BLOCKED_REASON_UNSPECIFIED":
                    last_error = f"prompt blocked ({block})"
                    break  # same prompt, same block: do not retry
                candidates = getattr(resp, "candidates", None) or []
                finish = _enum_name(getattr(candidates[0], "finish_reason", None)) if candidates else ""
                if finish in _BLOCKED_FINISH:
                    last_error = f"response blocked (finish_reason={finish})"
                    break
                if finish == "RECITATION":
                    prompt = request.prompt + RECITATION_HINT
                    raise _RetryableError("response stopped by the recitation filter")
                if finish == "MAX_TOKENS":
                    max_tokens = min(max_tokens * 2, 65536)
                    prompt = request.prompt + MAX_TOKENS_HINT
                    raise _RetryableError(f"output cut off at max_output_tokens (retrying with {max_tokens})")
                text = resp.text
                if not text:
                    raise _RetryableError(f"empty response (finish_reason={finish or 'unknown'})")
                try:
                    parsed = output_model.model_validate_json(text)
                except (ValidationError, json.JSONDecodeError) as exc:
                    summary = _validation_summary(exc)
                    prompt = (
                        f"{request.prompt}\n\nYour previous answer did not validate against the JSON schema: "
                        f"{summary}. Return corrected JSON only."
                    )
                    raise _RetryableError(f"invalid structured output: {summary}") from exc
                return LLMResult(
                    parsed=parsed, model=model, tokens_in=tokens_in, tokens_out=tokens_out, model_version=version
                )
            except genai_errors.APIError as exc:
                last_error = f"{type(exc).__name__} {exc.code}"
                if exc.code not in _RETRYABLE_HTTP:
                    break
            except (TimeoutError, httpx.TransportError) as exc:  # TransportError includes httpx timeouts
                last_error = type(exc).__name__
            except _RetryableError as exc:
                last_error = str(exc)
            logger.warning("LLM %s attempt %d/%d failed: %s", request.step, attempt, attempts, last_error[:200])
            if attempt < attempts:
                await asyncio.sleep(min(20.0, 1.5 * 2 ** (attempt - 1)) + random.uniform(0, 0.5))  # noqa: S311
        raise LLMError(
            f"{request.step}: Gemini call failed ({last_error[:200]})",
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


def _validation_summary(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]]
        return "; ".join(parts)
    return str(exc)[:300]
