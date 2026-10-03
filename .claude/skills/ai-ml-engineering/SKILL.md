---
name: ai-ml-engineering
description: Guides LLM and ML engineering in Python 3.12 / FastAPI services on Google Cloud - calling Gemini on Vertex AI through Application Default Credentials (timeouts, retries, streaming, structured JSON output validated with Pydantic, token and context budgets, model routing), prompt engineering, text classification (rules, zero-shot NLI, embedding few-shot similarity, ensembles with early exit, threshold calibration), embeddings and semantic search (sentence-transformers, Vertex AI embeddings, pgvector on Cloud SQL), and serving transformer or ONNX models on Cloud Run (memory sizing, background loading, readiness, quantization). Use when adding or changing an LLM call, writing a prompt or output schema, building a classifier or embedding pipeline, calibrating thresholds, or deploying and debugging a self-hosted model.
---

# AI/ML Engineering

How to build LLM and ML features in this stack: FastAPI services on Cloud Run that call Gemini on Vertex AI through Application Default Credentials (ADC), self-hosted transformer and ONNX models for cheap, private, low-latency classification, and embeddings stored in-process or in Cloud SQL with pgvector.

## Companion skills

| Need | Load |
|------|------|
| Which model, context window, current prices | `llm-models-expert` (this skill never hard-codes prices) |
| Input/output filtering, prompt-injection defence, PII redaction before model calls | `llm-guardrails` |
| Eval sets, regression benchmarks, LLM-as-judge, comparing prompt or model versions | `llm-evaluation` |
| Agent loops, tool calling, MCP | `agentic-ai-resources` |
| Service layout, typing, Pydantic, migrations | `backend-architect`, `python-developer` |
| pytest, fakes for model clients | `backend-test-runner`, `testing-qa` |
| Deploy flags, probes, IAM, CI image builds | `cloud-run-deploy`, `devops-infrastructure` |
| Instance sizing, min instances, token spend | `cloud-costs-optimization` |

## Reference files

Load only the file the task needs:

- [reference/llm-integration.md](reference/llm-integration.md) - Vertex AI client via ADC, a provider-neutral interface, timeouts and retries, SSE streaming through FastAPI, structured output, token and context budgets, model routing, cheap side-task pattern, testing with fakes.
- [reference/prompt-engineering.md](reference/prompt-engineering.md) - system prompt structure, audience calibration, delimiting untrusted input, few-shot design, output format, reasoning controls, redirection instead of bare refusals, prompt versioning.
- [reference/classification.md](reference/classification.md) - zero-shot NLI classifier code, label design, per-class thresholds, multi-stage ensembles with early exit, merging detectors, speed and caching, choosing an approach, measuring accuracy.
- [reference/semantic-similarity.md](reference/semantic-similarity.md) - embedding model choice, safe loading, example-bank format, contrastive few-shot classifier, building indexes from versioned source, in-process vs DuckDB vs pgvector, Vertex AI embeddings, calibration protocol.
- [reference/model-serving.md](reference/model-serving.md) - getting model files into the image, memory sizing and OOM diagnosis, background loading with liveness and readiness, component health, model manifests, ONNX export / quantization / runtime tuning, concurrency, versioned rollout, dependency hygiene.

## Core rules

1. **ADC, never API keys.** Use `google-genai` with `vertexai=True`. On Cloud Run the runtime service account needs `roles/aiplatform.user`; locally use `gcloud auth application-default login`; in CI use Workload Identity Federation. No key files.
2. **Configuration, not literals.** Model IDs, temperatures, token limits, thresholds and label sets live in `pydantic-settings` config or versioned data files. Log the model ID and prompt version with every call.
3. **Every model call is bounded.** A timeout, a small number of retries with jittered backoff on 429 and 5xx only, an overall deadline that includes retries, and a defined fallback.
4. **Structured output is validated.** Use the provider's JSON-schema mode and still parse with Pydantic; a validation failure is an error path, not a crash and not a silent default.
5. **Untrusted text is data.** Delimit user and retrieved content, never splice it into instructions; apply `llm-guardrails` on the way in and out.
6. **Keep the event loop free.** CPU-bound inference runs through `asyncio.to_thread` (or a sync `def` endpoint) and is concurrency-limited.
7. **Every fallback is observable.** Log at ERROR with a traceback, increment a metric, and flip a degraded flag that health or inspect endpoints expose. Never `print()` and continue.
8. **Measure before and after.** Any change to a model, prompt, threshold, label set or example bank comes with numbers on a held-out set (`llm-evaluation`).
9. **Unit tests never call a real model.** Depend on a `Protocol`, inject a fake, override the FastAPI dependency.

## Request pipeline shape

```
request
  -> authenticate + validate (FastAPI, Pydantic)
  -> input guardrails (llm-guardrails)
  -> cheap deterministic checks: rules, exact-match cache        may short-circuit
  -> classify / route: rules -> embeddings -> zero-shot -> LLM   escalate only when uncertain
  -> retrieve context (pgvector) if the route needs it
  -> generate (Gemini on Vertex AI, streamed when user-facing)
  -> output validation: schema + guardrails
  -> respond; record latency per step, tokens, model ID, prompt version
```

Run independent checks concurrently (`asyncio.TaskGroup`) and stop as soon as a stage decides. Put the most decisive, cheapest checks first.

## Choosing a classification approach

| Approach | Data needed | Typical latency | Strength | Use when |
|----------|-------------|-----------------|----------|----------|
| Keywords / regex | none | microseconds | precise on exact phrases, blind to paraphrase | hard rules, fast path, guaranteed matches |
| Embedding few-shot similarity | 10-50 curated examples per class, with hard negatives | ~5-20 ms on CPU | nuanced phrasing, auditable, cheap to extend | intents whose wording varies a lot |
| Zero-shot NLI (BART-MNLI, DeBERTa zero-shot) | label names only | 50-300 ms on CPU, linear in label count | no training data | prototypes, broad topics |
| Fine-tuned small encoder (DistilBERT, DeBERTa, SetFit) | hundreds to thousands of labelled examples | 10-50 ms | best self-hosted accuracy | stable, high-volume classes |
| LLM with a response schema | label definitions + few-shot | 0.3-2 s | strong out of the box, handles judgement | low volume, complex cases, labelling data for the cheaper options |

Latencies are order-of-magnitude on a small CPU instance; measure your own. A common production shape is rules first, then a cheap self-hosted model, escalating to an LLM only for the uncertain band. Details and code: [reference/classification.md](reference/classification.md).

## Embeddings and semantic similarity

- Normalise embeddings once; cosine similarity is then a dot product.
- For few-shot classification, score each class as **mean(top-k similarity to positives) - mean(top-k similarity to hard negatives)** and compare against a per-class threshold. The negative term is what suppresses look-alike false positives.
- Record the embedding model ID (and revision) with every stored vector. Vectors from different models are not comparable; a model change means re-embedding everything.
- Build indexes from versioned source data (JSON in the repo) during the image build or at startup with a content fingerprint. Never ship a pre-built index to a mutable bucket; it drifts from the source.
- Storage: in-process NumPy for small read-only banks shipped with code; pgvector on Cloud SQL for data written at runtime, RAG corpora, or anything needing filters and joins; DuckDB for offline analysis.

Full patterns: [reference/semantic-similarity.md](reference/semantic-similarity.md).

## Serving self-hosted models on Cloud Run

- Size memory at roughly `2.5 x model files on disk + 0.5 GiB` as a starting point, then measure peak RSS during load. Cloud Run's writable filesystem is in memory and counts against the limit.
- Load models in a background task started from the FastAPI `lifespan`; `/health` (liveness) never touches the model, `/ready` returns 503 until it is loaded; point the Cloud Run startup probe at `/ready`.
- Load sentence-transformers with `SentenceTransformer(name, device="cpu", model_kwargs={"low_cpu_mem_usage": False})`. Newer `transformers` releases initialise weights on the `meta` device by default, and moving them fails with `Cannot copy out of meta tensor`.
- Serve offline: models baked into the image, `HF_HUB_OFFLINE=1`, pinned revisions.
- For encoder models, export to ONNX once, quantize to INT8, and serve with `onnxruntime` + `tokenizers` so the runtime image does not need PyTorch.
- CPU-bound inference: keep Cloud Run concurrency low or guard inference with a semaphore; set ONNX intra-op threads to the instance vCPU count; warm up once at startup.
- Model services are private (`--no-allow-unauthenticated`) and called with Google-signed ID tokens.

Full patterns: [reference/model-serving.md](reference/model-serving.md).

## Prompt engineering in brief

- Stable rules go in the system instruction; variable content goes last. Stable-prefix-first also lets provider prompt caching apply.
- Write the prompt as role, goals, constraints, style, output format. State what to do instead of what not to do.
- Calibrate to the audience with explicit levers (vocabulary, depth, length, teach-versus-answer) selected in code, not a single prompt that tries to cover every reader.
- Few-shot: 3-8 examples covering every class, including hard negatives near the decision boundary, in exactly the production format.
- Temperature 0 for extraction and classification; set `max_output_tokens` per use case.
- Prompts are versioned files; every change is evaluated against the same eval set before rollout.

Details: [reference/prompt-engineering.md](reference/prompt-engineering.md).

## Hard-won lessons

1. **Initialised is not invoked.** A detector was registered as a singleton at startup and exposed through a getter, but the request handler never called it; every input that missed the keyword fast path skipped it entirely. Grep for callers of every detector, and keep an integration test that asserts the final result changes when a fake detector fires.
2. **Silent fallback hid a dead model for weeks.** A dependency upgrade broke model loading (the meta-tensor issue above); the caller caught the exception, printed it, and returned the base classifier's answer. Fallbacks must log at ERROR, count, and surface a degraded status that monitoring alerts on.
3. **Decide fail-open versus fail-closed per component, and write it down.** Optional enrichment fails open. A component guarding a costly or risky action may fail open only if that state alerts immediately. A model that produces the endpoint's core output fails closed (503).
4. **Ship source, not artifacts.** A vector index read from a mutable bucket stopped matching the example JSON in the repo, so edits had no effect until someone rebuilt and re-uploaded it by hand. Build from source in the image (or at startup with a fingerprint), and include the embedding model ID in the fingerprint.
5. **Tune the costliest class with data, not its threshold.** When the class whose misses are most expensive over-fires, add hard negatives and clearer positives to its examples; keep its threshold at the agreed recall floor. Verify offline that the offending input's score drops while true positives stay above threshold.
6. **Derive "required" from the manifest.** A startup validator with a hard-coded required-model list crashed when an optional model was absent, and a stale expected filename (`pytorch_model.bin` when the artifact shipped `model.safetensors`) blocked every deploy for months while the last good revision kept serving. Read the `optional` flag from the manifest and unit-test the expected file names.
7. **One dependency source of truth.** A legacy requirements variant pinned an old FastAPI that passed the deprecated `on_startup` argument to a newer Starlette, failing at import. Keep one lock per service and use `lifespan`.
8. **Callers drift from contracts silently.** A frontend posted to the wrong path with extra top-level fields; Pydantic dropped the unknown fields and the client treated the error as "no result". Use `extra="forbid"` on request models where unknown fields indicate a bug, and check callers against the live OpenAPI schema.
9. **Tiny test sets lie.** Accuracy measured on a dozen hand-picked messages is noise. Use at least ~50 examples per class from a held-out set and report per-class precision and recall, with the costliest class's recall tracked on its own.
10. **Know which auth layer you are testing.** A private Cloud Run service may sit behind IAM (Google ID token) and also run its own JWT middleware that rejects Google tokens. Smoke-test through the same path real callers use.

## Metrics to track

- Latency p50/p95 per pipeline step; time to first token for streams (target under ~2 s for interactive chat).
- Input and output tokens and estimated cost per request, by model and prompt version.
- Retries, timeouts, fallbacks, schema-validation failures, empty or truncated responses (finish reason not `STOP`).
- Classifier: predicted-class distribution over time (drift), per-class precision and recall on a reviewed sample, share of requests escalated to the LLM, cache hit rate.
- Model servers: load time, peak memory, restarts, readiness failures.

## Definition of done

- Before/after numbers on the eval set for quality, latency and cost, included in the PR description.
- Unit tests with fakes for every new branch (timeouts, retries, validation failure, fallback); an integration test proving each new detector is on the request path.
- Edge cases covered: empty, very long, non-English, adversarial or injection-style input, inputs on the class boundary.
- Thresholds and their calibration results recorded next to the data they apply to; model decisions documented next to the code that uses them.
- Health or inspect endpoints show the status of each model and detector.
- Ruff and the affected tests run; the report states what was run, the numbers, and any follow-ups. If the project tracks work with the `project-manager` skill, update it.
