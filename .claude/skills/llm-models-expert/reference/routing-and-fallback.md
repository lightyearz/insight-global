# Model Routing, Cascades, Fallback and Migration

## Contents
- Patterns at a glance
- Never fall back on these
- Route configuration
- Availability fallback (Python sketch)
- Cascades: cheap first, escalate when needed
- Circuit breaking and hedging
- Model migration checklist

The code builds on the provider-neutral `TextGenerator`, `GenerationRequest` and `GenerationResult` types from the `ai-ml-engineering` skill (LLM integration reference). Retries for a single target live there. This file covers choosing and switching between targets. **Model IDs are illustrative: verify current IDs before use.**

## Patterns at a glance

| Pattern | What it does | Use when | Cost and latency effect |
|---------|--------------|----------|-------------------------|
| Static routing | Each call type has a configured model | Always; this is the baseline | None |
| Cascade | Try a cheap model, escalate to a stronger one on a failure signal | Most requests are easy and a reliable escalation signal exists | Cheaper on average; escalated requests pay both latencies |
| Availability fallback | On 429, 5xx or timeout, try another location, then a sibling model, then another provider | User-facing paths that must answer | Small, unless the primary is degraded for a long time |
| Hedged request | Send a second request after a delay, keep the first answer, cancel the other | Strict latency SLOs on short calls | Pays twice for the hedged fraction |
| Shadow | Run a candidate model on copies of traffic without serving its output | Evaluating a migration on real input | Pays for both while shadowing |
| Canary or A/B | Serve a percentage of traffic from the candidate behind a flag | Final step of a migration | Proportional to the percentage |

## Never fall back on these

- **Safety blocks and content-policy refusals.** A blocked response is a guardrail decision, not an outage. Retrying on a model with laxer filters is a guardrail bypass. Handle it as a refusal (`llm-guardrails`).
- **Your own guardrail rejecting the output.** Same reasoning: treat it as blocked, not as an error to route around.
- **4xx validation, authentication or permission errors.** They are bugs or misconfiguration and will fail the same way everywhere. Raise and alert.
- **An exhausted caller deadline.** Do not start another long call; return a degraded response instead.

## Route configuration

Keep routes in a versioned config file loaded at startup, with the file path set through `pydantic-settings`. Every call type names its route, so changing a model is a config change reviewed like code.

```yaml
# config/llm_routes.yaml
# Model IDs are illustrative; verify current IDs and locations before use.
routes:
  classify_intent:
    targets:
      - {model: "gemini-2.5-flash-lite", location: "<REGION>"}
    max_output_tokens: 64
  chat_reply:
    targets:
      - {model: "gemini-2.5-flash", location: "global"}
      - {model: "gemini-2.5-flash", location: "<REGION>"}         # same model, other location
      - {model: "gemini-2.5-flash-lite", location: "global"}      # sibling model, degraded quality
    max_output_tokens: 1024
    thinking_budget: 0
```

```python
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Target(BaseModel):
    model: str
    location: str


class Route(BaseModel):
    targets: list[Target] = Field(min_length=1)
    max_output_tokens: int
    thinking_budget: int | None = None


class RouteTable(BaseModel):
    routes: dict[str, Route]


def load_routes(path: Path) -> RouteTable:
    return RouteTable.model_validate(yaml.safe_load(path.read_text()))
```

Rules:
- Every fallback target must pass the same eval as the primary, or carry an explicit, documented "degraded" quality bar.
- Prompts do not always transfer between models. If a fallback needs a different prompt, version it separately and log which prompt version was used.
- Fallback to another provider sends user data to another processor. That needs the same data-terms review as a primary model.

## Availability fallback (Python sketch)

One generator per target (per model and location). The outer deadline bounds the whole chain. Fallback happens only on availability errors.

```python
import asyncio
import logging
from dataclasses import replace

from google.genai import errors

logger = logging.getLogger(__name__)

FALLBACK_STATUS = frozenset({429, 500, 502, 503, 504})


class AllTargetsFailedError(RuntimeError):
    """Every configured target failed with an availability error."""


def _is_availability_error(exc: Exception) -> bool:
    if isinstance(exc, errors.APIError):
        return exc.code in FALLBACK_STATUS
    return isinstance(exc, (TimeoutError, ConnectionError))


class FallbackGenerator:
    """Tries each (generator, model) target in order and falls back only on availability errors."""

    def __init__(self, targets: list[tuple[TextGenerator, str]], deadline_s: float) -> None:
        self._targets = targets
        self._deadline_s = deadline_s

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        last_error: Exception | None = None
        async with asyncio.timeout(self._deadline_s):
            for position, (generator, model) in enumerate(self._targets):
                try:
                    result = await generator.generate(replace(request, model=model))
                except Exception as exc:
                    if not _is_availability_error(exc):
                        raise  # safety blocks, bad requests and output errors are not outages
                    last_error = exc
                    logger.warning(
                        "llm target failed",
                        extra={"model": model, "position": position, "error": type(exc).__name__},
                    )
                    continue
                if position > 0:
                    logger.info("llm served by fallback", extra={"model": model, "position": position})
                return result
        raise AllTargetsFailedError("all model targets failed") from last_error
```

- Give each target a per-attempt deadline shorter than the chain deadline, or the first slow target consumes the whole budget.
- Log and count fallbacks. A sustained fallback rate is an incident, not a success.
- Test it with fakes that raise each error class, including one that must not fall back (`backend-test-runner`).

## Cascades: cheap first, escalate when needed

A cascade pays off only when escalation is rare enough:

```
expected cost = c_cheap + p_escalate x c_strong
cascade is cheaper than always-strong when  p_escalate < 1 - c_cheap / c_strong
```

If the cheap model costs a tenth of the strong one, the cascade saves money while fewer than 90% of requests escalate. Latency still matters: every escalated request pays both calls. Measure `p_escalate` on the eval set before shipping.

Escalation signals, best first:
1. **Deterministic checks:** output fails schema validation, a required field is missing, a citation does not match a retrieved source, code fails to compile or tests.
2. **An independent verifier:** a classifier or small judge model scoring the answer, calibrated against labelled data.
3. **Agreement:** two cheap samples disagree.
4. **Token log-probabilities**, where the provider exposes them.
5. **Self-reported confidence:** cheapest but poorly calibrated. Use only after checking it against the eval set.

```python
from pydantic import BaseModel, ValidationError


class Answer(BaseModel):
    answer: str
    confidence: float


class CascadeError(RuntimeError):
    """No tier produced valid output."""


async def answer_with_cascade(
    tiers: list[tuple[str, TextGenerator]],   # ordered cheap -> strong
    request: GenerationRequest,
    min_confidence: float,                    # calibrated on the eval set
) -> tuple[Answer, str]:
    for index, (tier, generator) in enumerate(tiers):
        is_last = index == len(tiers) - 1
        result = await generator.generate(request)
        try:
            parsed = Answer.model_validate_json(result.text)
        except ValidationError:
            logger.info("cascade escalation", extra={"tier": tier, "reason": "invalid_output"})
            continue
        if parsed.confidence >= min_confidence or is_last:
            return parsed, result.model
        logger.info("cascade escalation", extra={"tier": tier, "reason": "low_confidence"})
    raise CascadeError("no tier produced valid output")
```

Log the tier that answered and the reason for each escalation. The escalation rate per call type is a key cost metric.

## Circuit breaking and hedging

- **Circuit breaker:** after N consecutive availability failures on a target, skip it for a cool-down period and go straight to the next target. Without one, every request pays the primary's timeout during an outage. Keep breaker state per instance; that is good enough on Cloud Run.
- **Hedging:** only for short, latency-critical calls. Start the second request after roughly the p95 latency of the first, take the first success and cancel the other. Track the hedge rate; it is extra spend.

## Model migration checklist

Use it when a model is deprecated, a new generation ships, or cost or quality drifts.

1. **Read the release notes** for behaviour changes: default thinking settings, temperature range, safety filter defaults, output limits, tokenizer, structured-output and tool-calling differences.
2. **Run the eval set** on the candidate. Compare quality, schema-valid rate, refusal rate, p50 and p95 latency, and input, output and thinking tokens per call (the cost delta).
3. **Revisit prompts.** Remove workarounds for the old model, re-check few-shot examples, and version any prompt changes.
4. **Shadow** the candidate on a sample of live or replayed traffic without serving its output. Replaying stored user input must respect your data-retention rules and the candidate provider's terms.
5. **Canary** behind a flag at a small percentage. Watch error rate, finish reasons, guardrail triggers, user feedback and cost per request.
6. **Roll forward,** keeping the old model as a fallback target until its retirement date, then remove it from config.
7. **Update the decision record** with the new ID, location, prices, the date checked and the eval results.
