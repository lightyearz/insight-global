---
name: llm-guardrails
description: Designs, implements and reviews guardrails for LLM features in Python 3.12 / FastAPI services on Google Cloud - layered input and output checks, prompt-injection defence for tool-using and RAG agents, PII detection and reversible redaction with Presidio (plus optional GLiNER), content-safety classifiers, output schema and semantic validation, groundedness and citation checks, fail-open versus fail-closed decisions with circuit breakers, latency budgets, guarded streaming, red-team testing, and Google Cloud Model Armor as a managed option. Use when adding or reviewing an LLM endpoint, agent tool or RAG pipeline, deciding what to filter and where, handling a guardrail outage or false-positive spike, choosing between self-hosted detectors and Model Armor, or turning a bypass or incident into a regression test.
---

# LLM Guardrails

Guardrails are the deterministic and model-based controls around an LLM call that decide what gets in, what comes out, and what the model is allowed to do. They complement, and never replace, authentication, authorisation, least-privilege tools and good prompt design. No single detector is reliable on its own; the protection comes from layers that fail safely and are measured.

## Companion skills

| Need | Load |
|------|------|
| LLM client, timeouts, structured output basics, delimiting untrusted text in prompts | `ai-ml-engineering` |
| Which model to use as a judge or classifier, and what it costs | `llm-models-expert` |
| Eval sets, precision/recall of detectors, LLM-as-judge, before/after numbers | `llm-evaluation` |
| Agent loops, tool calling, MCP | `agentic-ai-resources` |
| Service boundaries, service-to-service auth, where a check lives | `backend-architect` |
| Typing, Pydantic, error handling, logging standards | `python-developer` |
| pytest fakes for models and checks | `backend-test-runner`, `testing-qa` |
| Rendering model output safely in the browser | `frontend-developer` |
| Private Cloud Run services, IAM, deploy flags | `cloud-run-deploy`, `devops-infrastructure` |
| Cost of always-on guardrail services and managed scanning | `cloud-costs-optimization` |

## Reference files

Load only the file the task needs:

- [reference/pipeline.md](reference/pipeline.md) - verdict model, policy as data, the concurrent orchestrator with per-check timeouts, deadline, early exit and failure modes, circuit breaker, input normalisation, FastAPI wiring, health and logging, consumption limits, tests.
- [reference/prompt-injection.md](reference/prompt-injection.md) - direct and indirect injection, the lethal trifecta, agent design patterns (dual LLM, plan-then-execute, action selector, CaMeL), least-privilege tools and approval gates, RAG ingestion and retrieval controls, exfiltration channels, detection classifiers, canary tokens, reading list.
- [reference/pii.md](reference/pii.md) - Presidio setup, custom recognisers, per-entity thresholds, GLiNER as an extra recogniser, anonymisation strategies, reversible pseudonymisation for LLM calls, keyed hashing, Sensitive Data Protection as the managed alternative, logging and evaluation.
- [reference/output-validation.md](reference/output-validation.md) - output as untrusted input, schema plus semantic validation with bounded repair, Gemini safety settings and block handling, groundedness and citation checks, abstention, safe rendering, guarded streaming.
- [reference/model-armor.md](reference/model-armor.md) - Google Cloud Model Armor: filters, templates, IAM, calling the sanitize API from a service, interpreting results, the Vertex AI integration and its fail-open behaviour, enforcement modes, limitations.
- [reference/red-teaming.md](reference/red-teaming.md) - attack taxonomy, adversarial and benign suites, oracle-based scoring, attack success rate and false-positive rate, tools and benchmarks, CI gates, production canaries, the incident-to-test loop.

## Core rules

1. **Layers, not a filter.** Combine deterministic checks (size limits, normalisation, allowlists, schema), classifiers, architecture (least privilege, approval gates) and output validation. A sentence in the system prompt is not a control.
2. **Check every untrusted source where it enters.** User input, retrieved chunks, tool outputs, uploaded files and model output are all untrusted. Guarding only the user turn leaves indirect injection wide open.
3. **Architecture bounds risk; detection only reduces it.** Once a model has read untrusted content, it must not be able to take a high-impact action without a deterministic gate: scoped credentials, allowlisted tools and arguments, or human approval.
4. **Fail closed by default.** Fail open only through a written exception for non-gating enrichment, and only when the failure alerts. Responses and metrics distinguish "blocked by policy" from "blocked because a check was unavailable".
5. **Policy is data.** Categories, thresholds, actions and failure modes live in a versioned config file, not in `if` statements. Every verdict logs the policy version.
6. **Check what you send.** The model receives exactly the normalised, redacted text that the checks approved, never a different variant of it.
7. **Redact before text leaves the trust boundary.** PII is removed or pseudonymised before text goes to a third-party model, logs, traces, analytics or eval datasets. Decide, and write down, which services count as inside the boundary.
8. **Model output is untrusted input to whatever consumes it.** Validate the schema, check semantics, escape for the renderer, parameterise SQL and shell, and allowlist URLs.
9. **Every check has a timeout, and the pipeline has a deadline.** Run independent checks concurrently, put the cheapest and most decisive first, and stop as soon as the outcome is decided.
10. **Never log raw content in guardrail logs.** Log check, category, score, action, policy version, request ID and span offsets.
11. **Every failure is loud.** Log at ERROR with a traceback, increment a metric, flip a degraded flag on the inspect or readiness endpoint, and alert.
12. **No switch that removes the baseline.** Feature flags and debug modes may add checks or tighten thresholds; none may skip the baseline pipeline. A guardrail behind a default-off flag is off.
13. **Calibrate on data.** Thresholds come from per-category precision and recall on held-out adversarial and benign sets. Changes ship with before/after numbers (`llm-evaluation`).
14. **Every bypass becomes a test.** Add a minimal reproduction to the red-team suite before fixing it.

## Threat map

Categories follow the OWASP Top 10 for LLM Applications (2025 edition).

| Risk | Primary controls | Details |
|------|------------------|---------|
| LLM01 Prompt injection (direct and indirect) | least-privilege tools, approval gates, isolation patterns, classifiers on every untrusted source, delimiting | [prompt-injection.md](reference/prompt-injection.md) |
| LLM02 Sensitive information disclosure | PII redaction in and out, access-filtered retrieval, no secrets in context | [pii.md](reference/pii.md) |
| LLM03 Supply chain | pinned model revisions, offline model loading, dependency locks | `ai-ml-engineering` |
| LLM04 Data and model poisoning | ingestion scanning, provenance on every chunk, reviewed example banks | [prompt-injection.md](reference/prompt-injection.md) |
| LLM05 Improper output handling | schema + semantic validation, renderer escaping, parameterised sinks | [output-validation.md](reference/output-validation.md) |
| LLM06 Excessive agency | tool allowlists, identity from the session not the model, approval for side effects | [prompt-injection.md](reference/prompt-injection.md) |
| LLM07 System prompt leakage | assume the system prompt is public, no secrets in it, canary tokens | [prompt-injection.md](reference/prompt-injection.md) |
| LLM08 Vector and embedding weaknesses | authorisation filters in the retrieval query, tenant isolation | [prompt-injection.md](reference/prompt-injection.md) |
| LLM09 Misinformation | citations, groundedness checks, abstention | [output-validation.md](reference/output-validation.md) |
| LLM10 Unbounded consumption | input size caps, output token caps, rate limits, step limits for agents | [pipeline.md](reference/pipeline.md) |

## Pipeline shape

```
request (authenticated, schema-validated, rate-limited)
  -> size cap + normalisation (NFKC, strip invisible and tag characters)
  -> input checks, concurrent, each with a timeout and a failure mode:
       PII detection (Presidio [+ GLiNER])            -> redact or pseudonymise
       prompt-injection / jailbreak classifier         -> block or review
       content-safety / scope classifier               -> block, review or allow
  -> policy decision: strictest action wins; log verdict + policy version
  -> retrieval and tool results: same checks per chunk (source = retrieved / tool_output)
  -> generate (provider safety settings on; system prompt holds no secrets)
  -> output checks: schema + semantics, PII, content safety, groundedness, URL allowlist
  -> restore pseudonyms only if the output returns to the user who supplied them
  -> render safely (escape, sanitise markdown, no remote images)
  -> metrics per check; degraded flags; alerts
```

### Where checks run

| Option | Strengths | Costs |
|--------|-----------|-------|
| In-process library (Presidio, ONNX classifier) | no network hop, simplest failure handling | larger image and memory per API instance; model load time on every cold start |
| Separate private Cloud Run service | shared by many callers, scales and deploys independently | network hop, its own cold starts (keep min instances at 1 or more on the hot path), service-to-service auth |
| Managed API (Model Armor, Sensitive Data Protection) | no models to operate, Google maintains detectors | per-token cost, regional availability, less control over thresholds, its own failure behaviour |

Guardrail services are private (`--no-allow-unauthenticated`) and called with Google-signed ID tokens, with application-level authentication as a second layer (`backend-architect`, `cloud-run-deploy`).

## Choosing detectors

| Need | Self-hosted | Managed on Google Cloud | Notes |
|------|-------------|-------------------------|-------|
| PII | Presidio (regex, checksums, NER, context words), plus GLiNER for open-ended entities | Sensitive Data Protection inspect/de-identify; Model Armor SDP filter | Presidio is cheap and deterministic; GLiNER adds recall on names and handles at a CPU cost |
| Prompt injection and jailbreak | small fine-tuned classifiers (for example `protectai/deberta-v3-base-prompt-injection-v2`, Llama Prompt Guard 2), LLM Guard scanners | Model Armor prompt-injection and jailbreak filter | High false-positive rates on benign instruction-like text; long inputs need windowing |
| Harmful content categories | ShieldGemma, Llama Guard, LLM Guard toxicity and topic scanners | Gemini safety settings, Model Armor responsible-AI filters | Map vendor categories onto your own policy categories |
| Off-topic or out-of-scope | embedding few-shot similarity or zero-shot NLI (`ai-ml-engineering`) | - | Often the most useful filter for a narrow assistant |
| Output structure | Pydantic models | Gemini response schema | Use both |
| Groundedness | NLI cross-encoder per claim, LLM-as-judge | Vertex AI check-grounding API | Deterministic citation checks first |
| URLs in output | domain allowlist | Model Armor malicious-URI filter | Allowlist beats reputation lists for most apps |
| Secrets and credentials | regex plus entropy scanners | Sensitive Data Protection credential infoTypes | Scan both directions |

Check model licences (some safety models are gated or carry use restrictions), evaluate every detector on your own traffic, and record the model ID and revision with each verdict.

## Fail open or fail closed

Decide per component, write it in the policy file, and test both branches.

| Component | On error, timeout or open circuit | Why |
|-----------|-----------------------------------|-----|
| Injection check on a path with tools, private data or side effects | closed: block or hold | an unscreened input can trigger actions |
| PII redaction before a third-party model, logs or storage | closed: hold the request | leaked data cannot be recalled |
| Content-safety check on user-facing output | closed: return the safe template | the user sees the failure otherwise |
| Scope or topic classifier | most cautious route | a wrong "allowed" is costlier than a generic answer |
| Permission or entitlement lookup | minimum permissions | never widen access on failure |
| Groundedness check | closed for high-stakes answers (abstain, show sources only); open with a visible flag for low stakes | match the cost of a wrong answer |
| Enrichment (sentiment, analytics tags) | open, with ERROR log and alert | does not gate anything |

- A circuit breaker makes an outage fail fast instead of adding a full timeout to every request ([pipeline.md](reference/pipeline.md)).
- Return a distinct response when a check was unavailable (503 with `Retry-After`, "we could not check this message, try again") rather than the policy refusal; otherwise an outage looks like a spike in policy blocks.
- Managed integrations can fail open. The Model Armor integration with Vertex AI `generateContent` skips screening when Model Armor is unreachable or errors. If the path must fail closed, call the sanitize API yourself and apply your own failure mode ([model-armor.md](reference/model-armor.md)).

## Latency budget

Order-of-magnitude figures for short inputs on a small CPU instance; measure your own.

| Step | Typical cost |
|------|--------------|
| Size cap, normalisation, regex, allowlists | under 1 ms |
| Presidio with a spaCy model | single-digit to tens of ms |
| DeBERTa-base classifier (ONNX, CPU) per 512-token window | ~10-50 ms |
| GLiNER on CPU | tens to hundreds of ms, growing with text length and label count |
| Hop to a private Cloud Run service in the same region | a few ms to tens of ms, plus cold starts |
| Managed scanning API | tens to low hundreds of ms from the same region |
| LLM-as-judge | hundreds of ms to seconds |

- Set a p95 target for the whole input stage (for interactive chat, a few hundred ms at most) and a hard deadline above it.
- Run independent checks concurrently; exit early once any check blocks.
- Scan retrieved chunks at ingestion and cache the verdict keyed by chunk ID, content hash and policy version, so query-time checks only cover what changed.
- Keep LLM-as-judge and other slow checks off the synchronous path unless the stakes justify it; run them asynchronously on a sample for audit instead.
- Timeouts free the request, not the CPU: work handed to a thread keeps running. Bound CPU-bound detectors with a semaphore.

## Streaming output

| Strategy | Use when | Cost |
|----------|----------|------|
| Buffer the full response, check, then send | high-stakes or structured output | no streaming benefit |
| Hold-back window: check overlapping windows, release text only after it passed | interactive chat with output checks | a short delay; a later failure needs a retraction event |
| Check after the stream, retract on failure | low-stakes only | the user may already have read it |

Never execute streamed tool-call arguments before the complete call is validated. Code: [output-validation.md](reference/output-validation.md).

## When content is blocked

- Return templated responses owned by product and policy, never text generated by the model that was just attacked.
- Do not reveal which detector fired or its score; that hands attackers an oracle. Keep that detail in internal logs.
- Offer a way forward (rephrase, contact support) and a path to report a false positive into a review queue.
- Raw content for human review goes to an access-controlled store with a retention limit, redacted where possible, never to general logs.

## Lessons and pitfalls

1. **A silent fail-open hid a dead classifier for weeks.** A dependency upgrade broke model loading in a safety classifier; the endpoint caught the exception and fell back to a base model that returned the lowest-risk label, so high-risk input was allowed. Nobody noticed because a separate layer (the generating model's own behaviour) still answered sensibly. Make failures loud, expose per-check health, and run live end-to-end canaries that assert known-bad input is blocked ([red-teaming.md](reference/red-teaming.md)).
2. **Defence in depth is what limited the damage.** The independent second layer kept outcomes acceptable while the first was broken. Keep at least two independent layers on the highest-severity categories.
3. **Fix over-firing on the most severe category with data, not its threshold.** Add hard negatives and clearer positives; keep its recall floor. Over-blocking is the safe failure direction.
4. **Initialised is not invoked.** Assert in an integration test that each check is on the request path: a fake check that fires must change the response, and a blocked input must never reach the fake model.
5. **User-turn-only guardrails miss indirect injection.** Poisoned documents and tool outputs arrive without passing the input checks. Scan every untrusted source.
6. **Blocked responses look empty.** In `google-genai`, `response.text` is `None` when the prompt or the candidate was blocked. Code that coerces `None` to `""` silently returns empty answers; check `prompt_feedback.block_reason` and `finish_reason` explicitly.
7. **Models mangle placeholders.** Pseudonyms like `<PERSON_1>` get rewritten ("Person 1") or invented (`<PERSON_3>`). Validate placeholders in output before restoring, and strip unknown ones.
8. **Managed scanners have blind spots.** Model Armor checks each request on its own, without conversation history, and does not decode Base64 or hex. Multi-turn attacks and encoded payloads need your own normalisation and conversation-level checks.
9. **Debug logging leaks.** Logging the full prompt "temporarily" puts PII and secrets into Cloud Logging and every log sink. Log verdicts, not content.
10. **Truncation hides payloads.** Classifiers truncated at 512 tokens never see an injection placed at the end of a long document. Window long inputs and take the maximum score.

## Metrics

- Per check: latency p50/p95, error and timeout rate, circuit state, and block/redact/review rate by category and policy version.
- Share of requests served with any degraded check; a non-zero rate on a fail-closed check is an incident.
- Red-team attack success rate per category and benign false-positive rate, per release.
- Human-review overturn rate (false positives confirmed by reviewers).
- PII: entities detected per type (counts only), placeholder-restore failures.
- Groundedness: unsupported-claim rate, citation failures, abstention rate.

## Definition of done

- A short threat model for the feature: untrusted sources, tools and their blast radius, data the model can see, where output is rendered or executed.
- Every check has a timeout, a failure mode in the policy file, and tests for its error and timeout branches.
- Integration tests prove each check is on the path and that blocked input never reaches the model or a tool.
- Red-team and benign suite numbers (attack success rate, false-positive rate) before and after, in the PR description.
- Guardrail logs carry no raw content; every verdict carries the policy version and model revisions.
- Readiness or inspect endpoints expose per-check status; alerts exist for degraded checks and for canary failures.
- Ruff and the affected tests run; the report states what was run, the numbers, and follow-ups. If the project tracks work with the `project-manager` skill, update it.
