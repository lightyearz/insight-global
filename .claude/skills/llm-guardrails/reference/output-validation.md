# Output Validation, Groundedness and Safe Rendering

## Contents

- [Output is untrusted input](#output-is-untrusted-input)
- [Schema validation with bounded repair](#schema-validation-with-bounded-repair)
- [Semantic validation and citation checks](#semantic-validation-and-citation-checks)
- [Groundedness methods](#groundedness-methods)
- [Abstention](#abstention)
- [Provider safety settings and blocked responses](#provider-safety-settings-and-blocked-responses)
- [Content checks on output](#content-checks-on-output)
- [Tool calls are output too](#tool-calls-are-output-too)
- [Safe rendering](#safe-rendering)
- [Guarded streaming](#guarded-streaming)

Structured-output basics (response schemas, Pydantic parsing, retries) are in `ai-ml-engineering`. This file covers what to check beyond "it parsed".

## Output is untrusted input

Whatever consumes model output treats it like user input:

| Sink | Risk | Control |
|------|------|---------|
| Browser | XSS, remote image exfiltration | escape, sanitise markdown, no raw HTML, link and image allowlists |
| SQL | injection | parameterised queries only; the model never writes SQL that runs with broad privileges |
| Shell, `eval`, templates | code execution | never; if code execution is the feature, use an isolated sandbox |
| HTTP requests | SSRF, exfiltration | host allowlist, no metadata server or private ranges |
| Other services and agents | injection propagation | validate against a schema; the receiver treats it as untrusted |
| Emails, tickets, documents | phishing under your brand | templates, approval for external recipients |

## Schema validation with bounded repair

```python
import logging
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class OutputValidationError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems[:5]))
        self.problems = problems


async def generate_validated(
    generator: "TextGenerator",
    prompt: str,
    schema: type[T],
    validate: Callable[[T], list[str]],
    *,
    max_repairs: int = 1,
) -> T:
    problems: list[str] = []
    attempt_prompt = prompt
    for attempt in range(max_repairs + 1):
        raw = await generator.generate_json(attempt_prompt, schema)
        try:
            parsed = schema.model_validate_json(raw)
        except ValidationError as exc:
            problems = [f"{e['loc']}: {e['msg']}" for e in exc.errors(include_input=False)]
        else:
            problems = validate(parsed)
            if not problems:
                return parsed
        logger.warning("model output failed validation", extra={"attempt": attempt, "problems": problems[:5]})
        attempt_prompt = add_repair_note(prompt, problems)  # restate the rules and list the problems
    raise OutputValidationError(problems)
```

- One repair attempt is usually enough; more attempts add latency and cost for little gain. After that, return a templated fallback.
- `errors(include_input=False)` keeps model output (which may contain PII) out of logs and out of the repair prompt.
- Use `extra="forbid"`, enums, `max_length` and numeric bounds on every output model, so validation catches drift instead of passing it on.
- A `finish_reason` of `MAX_TOKENS` means truncated output. For JSON it fails validation; for prose, flag it rather than presenting a cut-off answer as complete.

## Semantic validation and citation checks

Schema validity says nothing about whether the values are allowed. Check IDs against the sets the model was given, numbers against ranges, URLs against allowlists, and quotes against sources.

```python
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str
    quote: str = Field(min_length=1, max_length=500)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(max_length=4000)
    citations: list[Citation] = Field(default_factory=list, max_length=10)
    abstained: bool = False


_WS = re.compile(r"\s+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _norm(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


def check_citations(answer: Answer, retrieved: dict[str, str]) -> list[str]:
    """retrieved maps chunk ID -> chunk text, exactly as given to the model."""
    problems: list[str] = []
    if not answer.abstained and not answer.citations:
        problems.append("answer has no citations")
    for c in answer.citations:
        source = retrieved.get(c.chunk_id)
        if source is None:
            problems.append(f"unknown chunk_id {c.chunk_id}")
        elif _norm(c.quote) not in _norm(source):
            problems.append(f"quote not found in {c.chunk_id}")
    cited = " ".join(_norm(retrieved[c.chunk_id]) for c in answer.citations if c.chunk_id in retrieved)
    for number in set(_NUMBER.findall(answer.answer)):
        if number not in cited:  # heuristic: flag, do not block, on this one
            problems.append(f"number {number} not found in cited sources")
    return problems
```

- Invented chunk IDs and fabricated quotes are cheap to catch and common. Always run these checks.
- The number check is a heuristic (substring matching, formatting differences); use it to flag or route to a stronger check, not as a hard block.
- Show citations in the UI so users can verify; an answer without visible sources gets less trust, and should.

## Groundedness methods

| Method | Cost | Catches | Misses |
|--------|------|---------|--------|
| Citation ID and verbatim-quote checks | negligible | invented sources and quotes | real sources cited for claims they do not support |
| Number and entity overlap with cited sources | negligible | invented figures and names | paraphrase, unit conversions |
| NLI cross-encoder per claim (premise = cited chunk, hypothesis = claim) | tens of ms per pair on CPU | unsupported or contradicted single claims | multi-hop reasoning, very long chunks (512-token windows) |
| LLM-as-judge groundedness | hundreds of ms to seconds | nuanced support, partial support | judge errors; needs calibration against human labels |
| Vertex AI check-grounding API | managed call | claim-level support score and citations against supplied facts | subject to input-size limits and cost; check current limits |

- Split the answer into claims (sentences are a reasonable first cut), check each, and aggregate: the share of supported claims, and whether any claim is contradicted.
- Calibrate thresholds on a labelled set (`llm-evaluation`) and record which judge model and prompt version produced each score.
- For high-stakes answers, an unsupported claim means: remove it, answer with sources only, or abstain. For low-stakes answers, show a visible "could not verify" note.

## Abstention

- If retrieval returns nothing above a similarity floor, do not ask the model to answer from its own knowledge. Return a templated "I could not find this in the available sources" or ask a clarifying question.
- Give the model an explicit way to abstain (`abstained: true`) and treat abstention as a valid, measured outcome, not a failure.
- Track abstention rate alongside groundedness; a drop in abstentions with flat retrieval quality often means the model started guessing.

## Provider safety settings and blocked responses

Gemini on Vertex AI applies safety filters to prompts and responses. Configure thresholds explicitly and handle blocks explicitly: in `google-genai`, `response.text` is `None` when the prompt or the candidate was blocked.

```python
from google.genai import types

SAFETY_SETTINGS = [
    types.SafetySetting(category=category, threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE)
    for category in (
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
    )
]
CONFIG = types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS, max_output_tokens=1024)

BLOCKING_FINISH_REASONS = frozenset({
    types.FinishReason.SAFETY,
    types.FinishReason.BLOCKLIST,
    types.FinishReason.PROHIBITED_CONTENT,
    types.FinishReason.SPII,
    types.FinishReason.RECITATION,
})


class ModelBlockedError(Exception):
    pass


class EmptyResponseError(Exception):
    pass


def extract_text(response: types.GenerateContentResponse) -> str:
    feedback = response.prompt_feedback
    if feedback is not None and feedback.block_reason is not None:
        raise ModelBlockedError(f"prompt blocked: {feedback.block_reason}")  # includes MODEL_ARMOR, JAILBREAK
    if not response.candidates:
        raise EmptyResponseError("no candidates")
    finish_reason = response.candidates[0].finish_reason
    if finish_reason in BLOCKING_FINISH_REASONS:
        raise ModelBlockedError(f"response blocked: {finish_reason}")
    text = response.text
    if not text:
        raise EmptyResponseError(f"empty text, finish_reason={finish_reason}")
    return text
```

- Map `ModelBlockedError` to the same templated response as your own content block, and count it as its own metric (`blocked_by_provider`), with the reason.
- Provider filters are one layer, tuned for general use; they do not know your policy categories, your scope, or your data. Keep your own checks.
- Some harm categories and thresholds are not configurable, and available categories change between model versions; check the current Vertex AI documentation when upgrading models.
- In streaming responses a chunk can carry a blocking `finish_reason` after text has already been sent; handle it like a guarded-stream failure (below).

## Content checks on output

Run the output pipeline with `source="model_output"`:

- PII: anything that is not a known placeholder came from the model; redact or block per policy (`pii.md`).
- Content-safety categories with output-specific thresholds; output can be stricter than input.
- Canary token and system-prompt leakage (`prompt-injection.md`).
- Secrets: regex and entropy scanners.
- URLs: allowlist or reputation check; strip query strings on non-allowlisted links.
- Scope: an answer far outside the product's scope is a sign of a successful hijack, even if nothing harmful was said.

## Tool calls are output too

- Validate every tool call's arguments against the tool's Pydantic model before execution; reject unknown tools.
- Execute only after the complete call is received; never act on partially streamed arguments.
- Cap tool calls per turn and per conversation; repeated identical calls are a loop, not progress.
- Treat a `MALFORMED_FUNCTION_CALL` or schema failure as a tool error returned to the model once, then stop.

## Safe rendering

The browser is a sink. In a Next.js frontend (`frontend-developer`):

```tsx
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";

const LINK_HOSTS = new Set(["docs.example.com"]);

function isAllowedLink(href?: string): boolean {
  if (!href) return false;
  try {
    const url = new URL(href);
    return url.protocol === "https:" && LINK_HOSTS.has(url.hostname);
  } catch {
    return false; // relative or malformed
  }
}

export function ModelMarkdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      rehypePlugins={[rehypeSanitize]}
      components={{
        img: () => null, // no remote images from model output
        a: ({ href, children }) =>
          isAllowedLink(href) ? (
            <a href={href} target="_blank" rel="noopener noreferrer nofollow">
              {children}
            </a>
          ) : (
            <span>{children}</span>
          ),
      }}
    >
      {text}
    </ReactMarkdown>
  );
}
```

- Never pass model output to `dangerouslySetInnerHTML`, and do not enable raw-HTML plugins for model content.
- Set a Content-Security-Policy with a tight `img-src` and `connect-src` as a second layer.
- Math and code rendering libraries have had injection bugs of their own; keep them updated and configured in their safe modes.

## Guarded streaming

Release text only after it has passed a check, keeping a hold-back tail so a term split across chunks is seen whole:

```python
from collections.abc import AsyncIterator, Awaitable, Callable


class OutputBlockedError(Exception):
    pass


async def guarded_stream(
    deltas: AsyncIterator[str],
    is_safe: Callable[[str], Awaitable[bool]],
    *,
    hold_back: int = 200,
    check_every: int = 400,
) -> AsyncIterator[str]:
    text, released, checked_at = "", 0, 0
    async for delta in deltas:
        text += delta
        if len(text) - checked_at < check_every:
            continue
        if not await is_safe(text[max(0, released - hold_back):]):  # unreleased text + overlap
            raise OutputBlockedError
        checked_at = len(text)
        safe_until = len(text) - hold_back
        if safe_until > released:
            yield text[released:safe_until]
            released = safe_until
    if not await is_safe(text[max(0, released - hold_back):]):
        raise OutputBlockedError
    if released < len(text):
        yield text[released:]
```

- Every character is checked before it is released, so a block only needs to retract text whose problem depends on later context. Send an SSE `retract` event and have the UI replace the partial message with the template.
- The window check sees local context only. Checks that need the whole answer (groundedness, schema) run at the end, on the full text, before the final chunk is released.
- Tune `check_every` against the latency of `is_safe`; checking every token multiplies cost. Time to first token grows by roughly `check_every + hold_back` characters of generation plus one check.
- Retries after text was sent duplicate output; follow the streaming rules in `ai-ml-engineering`.
