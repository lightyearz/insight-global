---
name: llm-evaluation
description: Designs and runs evaluations for LLM features in Python / FastAPI services on Google Cloud - golden datasets (JSONL cases, slices, held-out splits, versioning), deterministic checks, LLM-as-judge with rubrics and calibration against human labels, RAG metrics (retrieval recall@k, faithfulness, context precision and recall, citation precision), agent trajectory evaluation, end-to-end benchmarks against a live endpoint with a results report, regression evals as a CI gate with thresholds, and cost and latency tracking. Covers the Vertex AI Gen AI evaluation service, Ragas, DeepEval and promptfoo. Use when building or extending an eval set, comparing prompts, models or retrieval settings, writing or calibrating an LLM judge, gating a pull request on eval results, or investigating a quality, latency or cost regression.
---

# LLM Evaluation

How to tell whether an LLM feature is good enough, whether a change made it better or worse, and how to stop regressions from merging. The stack default is Gemini on Vertex AI called through Application Default Credentials (ADC) from Python 3.12 services; the methods are provider-neutral.

Unit tests prove the code paths work with a fake model. Evals measure what the real model does with real-looking inputs. Keep them separate: unit tests run on every commit and never call a model; evals call real models, cost money, and run on a schedule or a label.

## Companion skills

| Need | Load |
|------|------|
| Calling Gemini, structured output, prompts, classifiers, embeddings | `ai-ml-engineering` |
| Which model to evaluate, current prices for cost estimates | `llm-models-expert` |
| Input and output filtering, prompt injection, PII redaction of sampled logs | `llm-guardrails` |
| Agent loops, tool calling, MCP | `agentic-ai-resources` |
| pytest structure and fakes for deterministic tests | `backend-test-runner`, `testing-qa` |
| Playwright for UI-side behaviour an API benchmark cannot see | `frontend-test-runner` |
| CI workflows, Workload Identity Federation, Secret Manager | `devops-infrastructure` |
| Budgets and billing alerts for eval spend | `cloud-costs-optimization` |

## Reference files

Load only the file the task needs:

- [reference/datasets.md](reference/datasets.md) - case schema, sources (production samples, synthetic, adversarial, hard negatives), size per slice, deterministic splits, labelling and inter-annotator agreement, versioning and manifests, multi-turn cases, threshold calibration for classifiers.
- [reference/llm-as-judge.md](reference/llm-as-judge.md) - pointwise, pairwise and reference-based judges, rubric design, a judge on Gemini with a Pydantic verdict schema, calibration against human labels (agreement, Cohen's kappa, judge recall on failures), known biases and mitigations, judge versioning.
- [reference/rag-and-agent-metrics.md](reference/rag-and-agent-metrics.md) - retrieval metrics with code, faithfulness, answer relevance, context precision and recall, citation precision and recall, agent outcome and trajectory metrics, forbidden-action checks, step and cost efficiency.
- [reference/ci-gate.md](reference/ci-gate.md) - end-to-end benchmark runner and results file, report dashboard, absolute floors and regression deltas, non-determinism and confidence intervals, PR versus nightly tiers, a GitHub Actions job with WIF, cost and latency tracking.
- [reference/tools.md](reference/tools.md) - Vertex AI Gen AI evaluation service, Ragas, DeepEval and promptfoo: what each is good at, ADC setup, minimal examples, and how to choose. Versions there are marked "verify".

## Core rules

1. **Define "good" before you measure.** Write the success criteria per feature as checks a script or a judge can apply: required content, forbidden content, format, routing, grounding, tone. Vague goals produce vague evals.
2. **Deterministic checks first.** Exact match, regex, JSON-schema validation, required and forbidden strings, routing labels and tool-call names are cheap, fast and repeatable. Use an LLM judge only for what code cannot check.
3. **An uncalibrated judge is a guess.** Before a judge gates anything, measure its agreement with human labels on at least ~100 cases, and re-measure whenever the judge model, prompt or rubric changes.
4. **Version everything that affects a score.** Dataset version, prompt version, model ID, judge model and judge prompt version, retrieval config, thresholds. Store them in every results file; a score without them cannot be compared.
5. **Hold out a test split.** Tune prompts, thresholds and few-shot examples on a dev split. Report on the held-out split. Tuning on the set you report on is overfitting.
6. **Report per slice, not just overall.** An average hides a broken category. Track the most costly failure class (unsafe output, leaked instructions, wrong tool with side effects) on its own line with its own threshold.
7. **Zero-tolerance checks are separate from pass rates.** Some failures, such as system-prompt leakage or a forbidden tool call, block a release on a single occurrence. Never let them be averaged away.
8. **Quality, latency and cost together.** Every run records tokens, estimated cost and latency percentiles next to quality. A change that wins on quality and doubles p95 latency or cost is a trade-off, not a win.
9. **A degraded run is not a result.** If an upstream dependency (classifier, retriever, guardrail) was unreachable or fell back during the run, flag the run as degraded and do not compare it with healthy runs.
10. **Every failure is evidence.** Store the input, output, retrieved context, tool calls and the reason each check failed, including the matched text for content checks. A red number without evidence wastes a triage session.
11. **Real user data stays protected.** Sampled production cases go through the same PII redaction as logs (`llm-guardrails`), live in access-controlled storage, and never go to a free-tier model whose terms allow training on inputs.

## The evaluation loop

```
define success criteria and slices
  -> build or extend the dataset (dev + held-out test)
  -> choose graders: deterministic checks, then calibrated judges, then human review
  -> run the baseline (current prompt, model, retrieval config); store results
  -> make one change
  -> rerun on the same dataset version; compare per slice with confidence intervals
  -> gate: zero-tolerance checks, absolute floors, max regression vs baseline
  -> ship behind a flag; monitor online metrics and sampled human review
  -> add every production failure to the dataset as a new case
```

Change one thing at a time. When a prompt, a model and a retrieval setting change together, the eval tells you the sum, not which change helped.

## Choosing graders

| Grader | Cost | Good for | Weak at |
|--------|------|----------|---------|
| Exact match, normalised match | free | labels, short answers, extracted fields | free text |
| Regex, required and forbidden strings | free | mandatory disclosures, leaked secrets or instructions, banned phrases | paraphrase |
| Schema validation (Pydantic) | free | structured output, tool arguments | semantic correctness |
| Routing and tool-call checks | free | router decisions, tool names and order | whether the answer was good |
| Embedding similarity to a reference | low | paraphrase-tolerant correctness | factual detail, negation |
| Reference-based LLM judge | medium | correctness against a gold answer | needs gold answers |
| Reference-free rubric judge | medium | helpfulness, tone, instruction following, groundedness | bias, drift; must be calibrated |
| Pairwise LLM judge | medium | comparing two prompts or models | position bias; only gives relative results |
| Human review | high | calibrating judges, ambiguous or high-stakes slices | scale, consistency |

Combine them per case: a case can require valid JSON, a correct label, no forbidden strings and a judge score of at least 4 out of 5.

## Golden datasets in brief

One JSONL row per case, validated with Pydantic on load:

```json
{"id": "refund-policy-014", "slice": "billing", "tags": ["multi-intent"], "split": "test",
 "input": "Can I get a refund after 40 days and also change my plan?",
 "expected_route": "billing", "reference": "Refunds are available within 30 days...",
 "must_include": ["30 days"], "must_not_include": ["guaranteed"], "source": "prod-sample-2026-09"}
```

- Size: roughly 50 or more cases per slice you report on; 100 or more for slices that gate releases. Fewer than that and a single case moves the score by several points.
- Sources: redacted production samples (most valuable), hand-written cases for known requirements, adversarial and injection attempts, hard negatives near decision boundaries, and synthetic cases that a human has reviewed.
- Splits: assign `dev` or `test` by a stable hash of the case ID so a case never changes split.
- Version the dataset with a manifest (version, case count per slice, content hash). Bump the version on any edit.

Details, code and labelling guidance: [reference/datasets.md](reference/datasets.md).

## LLM-as-judge in brief

- One criterion per judge call, a 1-5 or pass/fail scale with written anchors for each score, and a short reason generated before the score.
- Structured output: the judge returns a Pydantic-validated verdict; a malformed verdict is an error, not a pass.
- Temperature 0. Use a model at least as capable as the one judged, ideally from a different family, to reduce self-preference.
- Pairwise comparisons run twice with the order swapped; a verdict that flips with order counts as a tie.
- Calibrate: label 100-200 cases by hand, run the judge, and report agreement, Cohen's kappa and the judge's recall on human-labelled failures. A judge that misses real failures must not gate a release.
- Pin the judge model ID and version the judge prompt. A judge change requires recalibration and a new baseline.

Full method and code: [reference/llm-as-judge.md](reference/llm-as-judge.md).

## RAG metrics

| Metric | Question it answers | How |
|--------|--------------------|-----|
| Retrieval recall@k, hit rate@k | Did the relevant chunks make it into the top k? | Labelled relevant chunk or document IDs per case; pure code |
| Precision@k, MRR, nDCG | Are relevant chunks ranked high? | Same labels; pure code |
| Context precision | How much of the retrieved context is relevant? | Judge per chunk, or labelled IDs |
| Context recall | Does the context contain everything the reference answer needs? | Judge: reference claims supported by context |
| Faithfulness (groundedness) | Is every claim in the answer supported by the context? | Judge: split answer into claims, verify each |
| Answer relevance | Does the answer address the question? | Judge or embedding similarity |
| Citation precision | Do the cited sources support the sentences that cite them? | Judge per (sentence, cited chunk) pair |
| Citation recall | Are factual sentences cited at all? | Code plus judge |
| Refusal correctness | Does it say "I don't know" when the context lacks the answer? | Cases with deliberately missing context |

Evaluate retrieval and generation separately. If recall@k is low, prompt changes cannot fix the answer. Code and judge prompts: [reference/rag-and-agent-metrics.md](reference/rag-and-agent-metrics.md).

## Agent evaluation

Grade the **outcome** and the **trajectory**:

| Dimension | Metric |
|-----------|--------|
| Outcome | Task success from the final state (database rows, files, API calls made), not from the agent's own claim of success |
| Tool selection | Precision and recall of tool calls against the expected set; exact, in-order or any-order match as the task requires |
| Arguments | Schema-valid and semantically correct arguments for each call |
| Safety | Zero forbidden tool calls; irreversible actions only after approval |
| Efficiency | Steps, tokens, cost and wall-clock time per task; loops and repeated identical calls |
| Robustness | Behaviour when a tool errors, times out or returns injected instructions |

An agent that succeeds in forty steps when five would do is a regression. Run agent tasks several times; report success rate with a confidence interval, not one lucky run.

## End-to-end benchmarks

A benchmark script sends every case through the real endpoint (for example the deployed chat API) and grades the response, so it catches routing, prompt assembly and guardrail problems that component evals miss.

Typical per-case checks:

- **Routing**: the request reached the expected route, persona or handler.
- **Required structure**: a mandated block, field or format is present when the case expects it.
- **Required content**: high-stakes categories include the mandated information (for example escalation instructions or a disclosure).
- **Leakage**: the output contains no system-prompt fragments, secrets or internal identifiers. Zero tolerance; surface the matched substring.

The runner writes one results file per run: run metadata (time, git SHA, dataset version, model, prompt version), totals per check, latency p50/p95/mean, dependency health, error count, a short `failing_cases` list for triage and a full `results` list with every input, output and check outcome. A small report app (for example Streamlit) shows a card per check with pass/warn/fail colouring, a latency histogram, a per-slice breakdown, a filterable case browser, a failing-case drill-down and a comparison against a second results file.

An API benchmark only grades response text. Behaviour that lives in the UI (rendering of structured blocks, expansion controls, math rendering, streaming progress) needs a Playwright spec (`frontend-test-runner`). Use the benchmark for pass rates and trends, and recorded E2E runs for proof that a fix works in the browser.

Runner, results schema and report layout: [reference/ci-gate.md](reference/ci-gate.md).

## Regression gate in CI

- **On pull requests that touch prompts, model config, retrieval or guardrails**: run a fast smoke subset (tens of cases, deterministic checks plus calibrated judges) and fail on any zero-tolerance hit or a breach of absolute floors.
- **Nightly or before release**: run the full held-out set, several repeats for non-deterministic slices, and compare with the stored baseline of the default branch.
- **Thresholds**: zero-tolerance checks (count must be 0), absolute floors per slice (for example routing accuracy at least 0.95), and maximum regression versus baseline (for example no slice drops more than 3 points beyond its confidence interval). Latency p95 and cost per case get ceilings too.
- **Authentication**: CI reaches Vertex AI through Workload Identity Federation, never a key file.
- **Budget**: cap cases, repeats and judge calls per run; print the estimated cost in the job summary.
- **Baseline updates** happen deliberately on the default branch after review, never automatically from a PR.

Workflow, threshold config and statistics: [reference/ci-gate.md](reference/ci-gate.md).

## Cost and latency tracking

Record per case: input, output, cached and thinking tokens from `usage_metadata`, model ID, estimated cost at the dated price list (`llm-models-expert`), time to first token for streams, total latency, retries and fallbacks. Aggregate per slice and per run: p50 and p95 latency, mean and p95 cost per case, total run cost including judge calls. Track the judge's own cost separately; it can exceed the cost of the system under test.

## Tool options

| Tool | Strength | Notes |
|------|----------|-------|
| Own pytest or script harness | Full control, deterministic checks, no new dependency | Start here; add a library when you need its judges or reports |
| Vertex AI Gen AI evaluation service | Managed judges with adaptive rubrics, computation metrics, agent metrics, ADC and IAM, data stays in the project | Python SDK in `google-cloud-aiplatform`; API surface changes often (verify) |
| Ragas | RAG metrics (faithfulness, context precision and recall), test-set generation | Metric import paths changed between releases (verify) |
| DeepEval | pytest-style `assert_test`, G-Eval, RAG and agent metrics, Gemini on Vertex AI via ADC | Parameter enums renamed in recent majors (verify) |
| promptfoo | YAML test matrices across prompts and providers, many assertion types, CI exit codes, web viewer | Node CLI; Vertex provider uses ADC (verify) |

Library metrics are LLM judges with someone else's prompt. Calibrate them against your human labels exactly as you would your own judge. Setup and examples: [reference/tools.md](reference/tools.md).

## Hard-won lessons

1. **Tiny test sets lie.** A classifier reported at a respectable accuracy on about a dozen hand-picked messages fell apart on a realistic set. Use at least ~50 cases per reported slice and show confidence intervals.
2. **A check that is red by design trains people to ignore red.** A check expected a structured block on the first turn while the product deliberately withheld it until a later turn, so the check failed on every run and the dashboard was ignored. Fix the check or make the case multi-turn; never leave a permanently failing check.
3. **Show the evidence.** A leakage check reported only pass or fail, so every failure needed a manual search through the output. Record the matched substring, the rule that matched and the case ID in the failing-case view.
4. **Degraded dependencies poison comparisons.** A run where an upstream classifier was unreachable silently fell back to defaults and looked like a quality regression. Probe dependencies at the start of a run, record their health in the results file, and show a banner on degraded runs.
5. **Model aliases move.** An auto-updating model alias changed underneath a stable baseline. Pin model IDs for both the system and the judge, and record them in every results file.
6. **Judges drift with their prompts.** A small wording change to a judge prompt shifted scores across the board with no change to the system. Version judge prompts and rerun calibration and baseline together.
7. **Library defaults are not your rubric.** An off-the-shelf "answer relevance" metric rewarded long answers that the product wanted short. Check that each metric measures what your success criteria say before adopting it.
8. **Calibrate thresholds on data, then leave them alone.** When the most costly class over-fires, add hard negatives and clearer positives rather than moving its threshold below the agreed recall floor; verify offline that true positives stay above it.

## Definition of done

- Success criteria, slices and graders written down next to the dataset.
- Dataset versioned, with a held-out split, at least ~50 cases per reported slice, and redacted sources documented.
- Every LLM judge calibrated against human labels, with the agreement numbers stored next to the judge prompt.
- Results file includes dataset, prompt, model, judge and retrieval versions, dependency health, cost and latency.
- PR description shows before and after numbers per slice for quality, latency and cost, plus any zero-tolerance hits.
- CI gate configured with zero-tolerance checks, absolute floors and regression limits; baseline stored for the default branch.
- New production failures are added as cases. If the project tracks work with the `project-manager` skill, update it.
