# LLM Integration: Gemini on Vertex AI

## Contents
- Client setup with ADC
- A provider-neutral interface
- Generation with timeouts and retries
- Streaming to the browser (SSE)
- Structured output
- Token budgets and context-window management
- Model routing
- Cheap side tasks
- Testing LLM code

Model IDs below are examples. Confirm current IDs, regions and prices with the `llm-models-expert` skill before changing configuration.

## Client setup with ADC

```python
from functools import lru_cache

from google import genai
from google.genai import types
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_")

    gcp_project: str
    gcp_location: str                         # e.g. a region, or "global" for models served only there
    chat_model: str = "gemini-2.5-flash"      # example ID; verify with llm-models-expert
    fast_model: str = "gemini-2.5-flash-lite"
    request_timeout_s: float = 30.0           # per HTTP attempt
    deadline_s: float = 45.0                  # whole call, including retries
    max_output_tokens: int = 1024


@lru_cache(maxsize=1)
def get_llm_settings() -> LLMSettings:
    return LLMSettings()


@lru_cache(maxsize=1)
def get_genai_client() -> genai.Client:
    settings = get_llm_settings()
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_location,
        http_options=types.HttpOptions(timeout=int(settings.request_timeout_s * 1000)),  # milliseconds
    )
```

- Credentials come from ADC: the Cloud Run runtime service account (grant `roles/aiplatform.user`), `gcloud auth application-default login` locally, Workload Identity Federation in CI. Never create or mount service-account key files.
- One client per process; it pools connections. Avoid field names starting with `model_` in Pydantic models (reserved namespace), hence `chat_model`.
- The same client can be built from environment variables instead: `GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`.

## A provider-neutral interface

Business code depends on a `Protocol`, not on the SDK. This keeps tests fast and makes switching or mixing providers a local change.

```python
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    system_prompt: str
    contents: str
    prompt_version: str
    model: str | None = None          # None = the configured default
    temperature: float = 0.3
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    model: str
    finish_reason: str
    input_tokens: int
    output_tokens: int


class TextGenerator(Protocol):
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]: ...
```

## Generation with timeouts and retries

```python
import asyncio
import logging

from google.genai import errors
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_random_exponential

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class LLMOutputError(RuntimeError):
    """The model answered, but not with usable output."""


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, errors.APIError) and exc.code in RETRYABLE_STATUS


class GeminiGenerator:
    def __init__(self, client: genai.Client, settings: LLMSettings) -> None:
        self._client = client
        self._settings = settings

    def _config(self, request: GenerationRequest) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens or self._settings.max_output_tokens,
        )

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_random_exponential(multiplier=0.5, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _generate_once(self, model: str, request: GenerationRequest) -> types.GenerateContentResponse:
        return await self._client.aio.models.generate_content(
            model=model, contents=request.contents, config=self._config(request)
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        model = request.model or self._settings.chat_model
        async with asyncio.timeout(self._settings.deadline_s):  # bounds retries too
            response = await self._generate_once(model, request)

        candidate = response.candidates[0] if response.candidates else None
        finish = candidate.finish_reason.name if candidate and candidate.finish_reason else "UNKNOWN"
        text = response.text or ""
        if finish != "STOP" or not text:
            # MAX_TOKENS, SAFETY, RECITATION, ... are not successes; decide explicitly.
            logger.warning("llm non-stop finish", extra={"model": model, "finish": finish,
                                                         "prompt_version": request.prompt_version})
            if not text:
                raise LLMOutputError(f"empty response, finish_reason={finish}")

        usage = response.usage_metadata
        return GenerationResult(
            text=text,
            model=model,
            finish_reason=finish,
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(usage.candidates_token_count or 0) if usage else 0,
        )
```

Rules:
- Retry only transient failures (429, 5xx, connection resets). Never retry 400-class validation or permission errors; they will fail identically.
- Jittered exponential backoff, small attempt count. The outer `asyncio.timeout` keeps retries inside the caller's latency budget.
- Treat non-`STOP` finish reasons explicitly: `MAX_TOKENS` means truncated output, and a provider safety block returns no text.
- Log model, prompt version, tokens, latency and finish reason as structured fields on every call.

## Streaming to the browser (SSE)

```python
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

router = APIRouter()


# Inside GeminiGenerator:
async def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
    response_stream = await self._client.aio.models.generate_content_stream(
        model=request.model or self._settings.chat_model,
        contents=request.contents,
        config=self._config(request),
    )
    async for chunk in response_stream:
        if chunk.text:
            yield chunk.text


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    generator: Annotated[TextGenerator, Depends(get_text_generator)],
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        try:
            async for delta in generator.stream(to_generation_request(body)):
                yield f"data: {json.dumps({'delta': delta})}\n\n"
            yield "event: done\ndata: {}\n\n"
        except Exception:  # CancelledError is not an Exception: client disconnects still cancel
            logger.exception("chat stream failed")
            yield f"event: error\ndata: {json.dumps({'code': 'generation_failed'})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- Retry only before the first token. Once text has been sent, a silent retry duplicates output; send an error event and let the client offer "retry".
- When the client disconnects, Starlette cancels the generator. Do not swallow `CancelledError`, so the upstream model stream stops and you stop paying for tokens.
- Cloud Run supports streamed responses, but the service request timeout covers the whole stream; set it above the longest expected generation.
- Any proxy in between (for example a Next.js route handler) must pass the body through unbuffered; see the `frontend-developer` skill.
- Validate or filter streamed output per `llm-guardrails`; full-response checks need buffering or a post-stream retraction strategy.

## Structured output

```python
from enum import StrEnum

from pydantic import BaseModel, ValidationError


class Category(StrEnum):
    BILLING = "billing"
    BUG = "bug"
    ACCOUNT_ACCESS = "account_access"
    FEATURE_REQUEST = "feature_request"
    OTHER = "other"


class Severity(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TicketTriage(BaseModel):
    reason: str          # short justification, first so the model commits to it before deciding
    category: Category
    severity: Severity
    summary: str


async def triage(client: genai.Client, settings: LLMSettings, ticket_text: str) -> TicketTriage:
    response = await client.aio.models.generate_content(
        model=settings.fast_model,
        contents=wrap_untrusted("ticket", ticket_text),   # see prompt-engineering.md
        config=types.GenerateContentConfig(
            system_instruction=TRIAGE_SYSTEM_PROMPT,
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=TicketTriage,
            max_output_tokens=400,
        ),
    )
    try:
        return TicketTriage.model_validate_json(response.text or "")
    except ValidationError as exc:
        raise LLMOutputError("triage output failed schema validation") from exc
```

- Prefer the provider's schema mode over "please answer in JSON" in the prompt. Keep the schema simple: enums for categorical fields, flat objects, few optional fields. Exotic JSON Schema features may be unsupported.
- Always validate with Pydantic anyway. On failure, either retry once at temperature 0 with the validation error appended, or fail the request; never substitute a default label silently.
- Gemini schemas accept a property-ordering hint; check that the field you want generated first (here `reason`) comes first.
- Temperature 0 for extraction and classification. Keep `reason` short and internal; do not show it to end users as an explanation of record.

## Token budgets and context-window management

- Read `usage_metadata` after every call for accounting. Use `await client.aio.models.count_tokens(model=..., contents=...)` only when you must check a large input against a budget before sending it.
- Conversation history: keep the last N turns verbatim (start around 10) plus a rolling summary of older turns produced by the fast model. Re-summarise when the verbatim window overflows.
- Retrieved context: rank, deduplicate and cut to a token budget; include source IDs so answers can cite them.
- Order: stable system instruction and shared context first, the variable request last. This is also the order that lets provider prompt caching (implicit, or explicit context caches for large shared documents) apply; check current caching rules with `llm-models-expert`.
- Set `max_output_tokens` per use case. Models with built-in thinking spend output tokens on it; set the thinking budget or level explicitly for latency-sensitive calls (the parameter name varies by model generation).

## Model routing

Route each request to the cheapest option that meets its quality floor:

| Request class | Route |
|---------------|-------|
| Answerable deterministically (rule, FAQ match, cache hit) | no LLM call |
| Simple transform: reformat, short rewrite, extraction | fast / lite model |
| Default conversation or reasoning | standard model |
| Complex or high-stakes | strongest model plus strict output validation |

For a scored router:

```
score(m) = w_quality * quality(m, class) + w_cost * (1 / cost(m)) + w_latency * (1 / latency(m))
choose argmax score(m) over models with quality(m, class) >= min_quality(class)
```

The quality floor is a hard constraint, not a weight. Weights live in config; `quality(m, class)` comes from `llm-evaluation` runs, not intuition. Log the chosen route and why.

## Cheap side tasks

For auxiliary transforms such as tidying spelling or formatting of a short user message:

- Gate by size: only short inputs qualify.
- Run concurrently with the main pipeline (`asyncio.TaskGroup`); never block the primary response on it.
- On any error or timeout, return the original text unchanged; keep the original alongside the transformed version.
- Use the cheapest model, temperature 0, and a tight `max_output_tokens`. Batch APIs and cached system instructions cut cost further for offline work.
- Consider a non-LLM option first: dictionary spelling correction (for example SymSpell) runs in microseconds, offline, at zero cost, though it only fixes spelling.

## Testing LLM code

```python
from dataclasses import dataclass, field


@dataclass
class FakeGenerator:
    replies: list[str]
    calls: list[GenerationRequest] = field(default_factory=list)

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        return GenerationResult(text=self.replies.pop(0), model="fake", finish_reason="STOP",
                                input_tokens=0, output_tokens=0)

    async def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        self.calls.append(request)
        for word in self.replies.pop(0).split():
            yield word + " "


# app.dependency_overrides[get_text_generator] = lambda: FakeGenerator(replies=["hello there"])
```

- Unit-test retry, timeout and validation-failure branches with fakes that raise the SDK's error types or return malformed JSON.
- Assert on what was sent (system prompt version, delimiting of user input, model chosen by the router), not only on what came back.
- Quality regressions are measured with eval sets, not unit tests; see `llm-evaluation`. Fixture patterns are in `backend-test-runner`.
