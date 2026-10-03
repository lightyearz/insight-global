# LLM Cost Estimation

## Contents
- The formula
- What counts as input and output
- Multi-turn growth
- Worked example (illustrative prices)
- Estimator in Python
- Measure real usage
- Billing export, attribution and alerts
- Pre-launch checklist

## The formula

```
cost per call  = (uncached_input x P_in + cached_input x P_cached + (output + thinking) x P_out) / 1,000,000
monthly cost   = sum over call types of (calls per month x cost per call) x (1 + retry and fallback overhead)
               + explicit cache storage + any per-request fees (for example search grounding)
```

`P_in`, `P_cached` and `P_out` are USD per million tokens from the provider's pricing page for the exact model, endpoint location (global or regional) and service tier (standard, batch or flex, priority) you will use. Record the date you read them.

Pricing details to check every time:
- **Output vs input:** output is usually several times the input price.
- **Thinking:** thinking or reasoning tokens are billed at the output rate.
- **Long-context threshold:** some models bill every token of a request at a higher rate once the prompt exceeds a threshold (for example 200K tokens).
- **Caching:** cached reads are billed at a fraction of the input price. Explicit caches add a storage charge per token-hour. Some providers add a premium on cache writes, and caching only applies above a minimum prefix size.
- **Tiers:** batch and flex tiers are typically around half the standard price, with delayed or best-effort completion. Priority tiers cost more.
- **Location:** global and regional endpoints may be priced differently.
- **Modalities:** images, audio and video convert to tokens at model-specific rates. Some outputs (images, audio) have their own prices.

## What counts as input and output

Input, re-sent on every call:
- system prompt and persona instructions
- tool or function declarations (their JSON schemas count as input)
- retrieved documents and other injected context
- conversation history
- the new user message, including attachments

Output:
- visible response tokens
- thinking tokens, whether or not they are shown
- tool-call arguments the model emits

Previous turns' thinking is usually not re-sent as input, but check how your SDK handles thought signatures or reasoning items in multi-turn calls.

Rule of thumb for English prose: about 4 characters per token. Code, JSON, non-English text and unusual vocabulary use more tokens. Tokenisers differ between providers, so the same text costs a different number of tokens on each. Use the provider's token-counting endpoint for anything that matters.

## Multi-turn growth

With a static prefix of `s` tokens (system prompt, tools, fixed context), `u` new user tokens and `a` reply tokens per turn, and the full history resent, the input for a conversation of `n` turns is:

```
input(n) = n*s + n*u + (u + a) * n*(n - 1)/2
```

The last term grows with the square of the conversation length. For long chats it dominates. Two controls:

- **Window the history:** keep the last `w` turns verbatim.
- **Summarise older turns** with a small model, re-summarising when the window overflows. The summary call is cheap but not free; count it.

Windowing barely matters for short chats and matters a great deal for long ones (example values `s=1,500`, `u=60`, `a=250`, `w=4`):

| Turns | Full-history input | 4-turn window input | Saving |
|------:|-------------------:|--------------------:|-------:|
| 8 | 21,160 | 19,300 | ~9% |
| 40 | 304,200 | 108,900 | ~64% |

Caching interacts with windowing. A sliding window changes the prefix after the static part, so only the static prefix stays cacheable. Full history keeps a growing prefix that implicit caching can reuse turn to turn. Measure both if caching is a large share of the bill.

## Worked example (illustrative prices)

**The prices below are invented round numbers to show the arithmetic. They are not current prices for any model.** Illustrative prices: `P_in = 0.50`, `P_cached = 0.05`, `P_out = 3.00` USD per 1M tokens.

Load: 1,000 daily active users x 3 conversations per day x 30 days = 90,000 conversations per month. Each conversation has 8 turns with `s=1,500`, `u=60`, `a=250`.

Per conversation: input = 12,000 (static) + 9,160 (history and new messages) = 21,160 tokens; output = 2,000 tokens.

| Scenario | Monthly input cost | Monthly output cost | Total |
|----------|-------------------:|--------------------:|------:|
| Baseline | $952.20 | $540.00 | **$1,492.20** |
| Static prefix cached | $466.20 | $540.00 | **$1,006.20** |
| Baseline + 500 thinking tokens per turn | $952.20 | $1,620.00 | **$2,572.20** |

Lessons that generalise:
- A static prefix that is large relative to each message makes caching worth a third of the bill here.
- An unbounded thinking budget can cost more than everything else combined. Set it explicitly.
- Output caps and concise formats pay off quickly because output is the expensive side.
- Estimate with p95 conversation length and p95 output length as well as averages. Averages hide the long tail that drives cost.

## Estimator in Python

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Prices:
    """USD per 1M tokens, copied from the provider page on a recorded date."""

    input: float
    output: float                       # also applies to thinking tokens
    cached_input: float | None = None


@dataclass(frozen=True, slots=True)
class ChatShape:
    turns: int                          # turns per conversation
    system_tokens: int                  # system prompt + tool declarations + static context
    user_tokens: int                    # new user tokens per turn
    reply_tokens: int                   # visible output tokens per turn
    thinking_tokens: int = 0            # thinking tokens per turn
    history_window: int | None = None   # earlier turns kept verbatim; None keeps all


def conversation_tokens(shape: ChatShape) -> tuple[int, int, int]:
    """Return (static_input, variable_input, output) tokens for one conversation."""
    static = variable = 0
    for earlier in range(shape.turns):
        kept = earlier if shape.history_window is None else min(earlier, shape.history_window)
        static += shape.system_tokens
        variable += kept * (shape.user_tokens + shape.reply_tokens) + shape.user_tokens
    output = shape.turns * (shape.reply_tokens + shape.thinking_tokens)
    return static, variable, output


def monthly_cost(
    shape: ChatShape,
    conversations_per_month: int,
    prices: Prices,
    *,
    cache_static_prefix: bool = False,
    retry_overhead: float = 0.0,        # 0.05 = 5% extra calls from retries and fallbacks
) -> float:
    static, variable, output = conversation_tokens(shape)
    static_price = (
        prices.cached_input
        if cache_static_prefix and prices.cached_input is not None
        else prices.input
    )
    per_conversation = (
        static * static_price + variable * prices.input + output * prices.output
    ) / 1_000_000
    return per_conversation * conversations_per_month * (1 + retry_overhead)


# Reproduces the worked example (illustrative prices only):
shape = ChatShape(turns=8, system_tokens=1_500, user_tokens=60, reply_tokens=250)
prices = Prices(input=0.50, output=3.00, cached_input=0.05)
assert round(monthly_cost(shape, 90_000, prices), 2) == 1492.20
assert round(monthly_cost(shape, 90_000, prices, cache_static_prefix=True), 2) == 1006.20
```

Simplifications: no cache-write premium, no minimum cacheable prefix, no summary calls and no long-context surcharge. Add whichever applies to your model.

## Measure real usage

Estimates are for planning. Once traffic flows, log the provider's usage numbers on every call and compare them with the estimate weekly.

Gemini (`google-genai` SDK) reports usage on `response.usage_metadata`:

```python
usage = response.usage_metadata
logger.info(
    "llm usage",
    extra={
        "model": model,
        "prompt_version": request.prompt_version,
        "input_tokens": (usage.prompt_token_count or 0) if usage else 0,          # includes cached part
        "cached_tokens": (usage.cached_content_token_count or 0) if usage else 0,
        "output_tokens": (usage.candidates_token_count or 0) if usage else 0,
        "thinking_tokens": (usage.thoughts_token_count or 0) if usage else 0,
        "tool_prompt_tokens": (usage.tool_use_prompt_token_count or 0) if usage else 0,
    },
)
```

- Other providers report the same quantities under different names, and they do not all add up the same way. For example, Anthropic's `input_tokens` excludes cache reads and cache writes, which are reported separately. Check the definitions before you sum them in a dashboard.
- To check a large input against a budget before sending it, use the token-counting endpoint (`client.aio.models.count_tokens(...)` in `google-genai`). Do not call it on every request just for accounting; the response usage is free.
- Aggregate by model, prompt version and feature so a cost spike can be traced to one change.

## Billing export, attribution and alerts

- Export Cloud Billing data to BigQuery (https://cloud.google.com/billing/docs/how-to/export-data-bigquery) and group generative AI spend by service and SKU.
- Vertex AI generation requests accept user-defined labels (the `labels` field of the request config in `google-genai`), which appear in the billing export. Label by feature or environment to attribute spend. Confirm support for the model and SDK version you use.
- Set budgets and alert thresholds per project, and separate projects or labels for dev, staging and prod (`cloud-costs-optimization`).
- Add an application-level guard as well: per-user or per-tenant daily token caps, enforced before the call, stop runaway loops and abuse faster than a billing alert.

## Pre-launch checklist

- [ ] Prices read from the provider page for the exact model, location and tier, with the date recorded
- [ ] Token estimate uses p95 as well as average conversation and output lengths
- [ ] Thinking budget and `max_output_tokens` set explicitly per call type
- [ ] History windowing or summarisation in place for chat
- [ ] Stable content placed first so caching can apply; cache hit rate logged
- [ ] Retry, fallback and cascade overhead included
- [ ] Usage logged per call with model and prompt version
- [ ] Budget alerts and per-user caps configured
