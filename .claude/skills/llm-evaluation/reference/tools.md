# Evaluation Tools

## Contents
- Choosing a tool
- Common rules for any tool
- Own harness (pytest or a script)
- Vertex AI Gen AI evaluation service
- Ragas
- DeepEval
- promptfoo
- Old patterns

Package versions, import paths, metric names and flags below were checked at the time of writing and change often. Treat every snippet as **verify against the tool's current docs and changelog before use**, and pin the version you adopt in the lock file.

## Choosing a tool

| Need | Good fit |
|------|----------|
| Deterministic checks, custom results schema, CI gate, full control | Own harness; add libraries for individual metrics |
| Managed LLM judges with data kept in the Google Cloud project, IAM and ADC, agent metrics | Vertex AI Gen AI evaluation service |
| RAG metrics (faithfulness, context precision and recall) and test-set generation | Ragas |
| Evals written as pytest tests, G-Eval custom criteria, RAG and agent metrics | DeepEval |
| Comparing prompts and providers side by side from YAML, quick assertions, web viewer, red-team scans | promptfoo |

Most teams end up with an own harness for the gate (it owns the dataset format, thresholds and results file) and call one library for the judge-based metrics they do not want to write. Avoid running two libraries for the same metric; they will disagree and nobody will know which to trust.

## Common rules for any tool

- **Authentication**: use ADC everywhere (Vertex AI client with `vertexai=True`, WIF in CI). Do not paste API keys or service-account key files into tool configs; several tools accept them, none require them for Vertex AI.
- **Calibrate library judges**: every judge-based metric is a prompt someone else wrote. Run it on your human-labelled calibration set (`llm-as-judge.md`) before it gates anything, and recalibrate when you upgrade the library.
- **Pin judge models explicitly**: tools have default judge models, often from another provider. Set the judge model in code so a library default never silently changes what you measure or where your data goes.
- **Telemetry**: some libraries send anonymous usage telemetry by default. Turn it off in CI and anywhere evaluation data is sensitive (for example `DEEPEVAL_TELEMETRY_OPT_OUT=1`, `RAGAS_DO_NOT_TRACK=true`, `PROMPTFOO_DISABLE_TELEMETRY=1`; verify names).
- **Hosted dashboards**: some tools offer a hosted results platform. Sending outputs there is sending data to a third party; it needs the same review as any other processor.
- **Results**: whatever the tool, convert its output into your own results file (`ci-gate.md`) so the gate, baselines and trends do not depend on one library's format.

## Own harness (pytest or a script)

Use plain Python when checks are deterministic or the judge is your own (see `llm-as-judge.md`). Two shapes:

- **A runner script** (`ci-gate.md`) for full datasets, results files, reports and the gate.
- **Marked pytest tests** for a handful of must-never-regress behaviours that developers run locally:

```python
import pytest

from evals.checks import check_leakage
from evals.datasets import load_cases

CASES = [c for c in load_cases(DATASET_PATH) if "must-never-regress" in c.tags]


@pytest.mark.live_llm                       # excluded from the default run; needs ADC
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
async def test_no_prompt_leakage(case, system_client, leak_fragments):
    output = await system_client.answer(case.input)
    result = check_leakage(output, leak_fragments)
    assert result.passed, f"{case.id} leaked: {result.evidence}"
```

Keep live-model tests out of the default pytest run (register the marker and deselect it), so unit tests stay fast, free and deterministic (`backend-test-runner`).

## Vertex AI Gen AI evaluation service

Managed evaluation on Google Cloud: rubric-based judge metrics (including adaptive rubrics generated per prompt), computation-based metrics, custom judge and code metrics, multi-candidate comparison and agent metrics. Data and judge calls stay inside the project, under IAM, billed to it. The Python SDK ships in `google-cloud-aiplatform`; Google's docs may present it under newer platform naming, so search the current docs for "Gen AI evaluation service" (verify).

```bash
uv add "google-cloud-aiplatform[evaluation]"     # verify extra name and current version
```

```python
import pandas as pd
import vertexai
from vertexai import types

client = vertexai.Client(project="<PROJECT_ID>", location="<REGION>")   # ADC; no key

df = pd.DataFrame(
    {
        "prompt": ["Can I get a refund after 40 days?"],
        "response": ["Refunds are available within 30 days of purchase..."],
        "reference": ["Refunds are available within 30 days; after that, account credit may be offered."],
    }
)

result = client.evals.evaluate(
    dataset=df,
    metrics=[
        types.RubricMetric.GENERAL_QUALITY,           # adaptive rubric judge
        types.RubricMetric.INSTRUCTION_FOLLOWING,
        types.Metric(name="exact_match"),             # computation-based; also "bleu", "rouge_1", "rouge_l_sum"
    ],
)
for summary in result.summary_metrics or []:
    print(summary)
```

- **Generate and evaluate**: `client.evals.run_inference(model=..., src=df)` produces responses for a prompt column, which can then be passed to `evaluate`. To evaluate your deployed system instead, call it yourself and fill the `response` column.
- **Custom judge**: `types.LLMMetric(name=..., prompt_template=...)` with your rubric; set `judge_model` explicitly. Custom code metrics: `types.Metric(name=..., custom_function=fn)`.
- **Prebuilt metric names** (verify): `GENERAL_QUALITY`, `TEXT_QUALITY`, `INSTRUCTION_FOLLOWING`, `SAFETY`, `HALLUCINATION`, `QUESTION_ANSWERING_QUALITY`, `SUMMARIZATION_QUALITY`, agent metrics such as `TOOL_USE_QUALITY` and `FINAL_RESPONSE_QUALITY`, and multi-turn variants.
- **Comparing candidates**: pass a list of datasets (one per prompt or model) to get per-candidate scores and win rates.
- **Quota**: evaluation calls have their own rate limit (`evaluation_service_qps` in the config); large runs need batching or a quota increase.
- **IAM**: the caller needs Vertex AI user permissions in the project; in CI that is the WIF-impersonated eval service account.
- Convert `result.eval_case_results` and `summary_metrics` into your results file; keep the per-case explanations as evidence.

## Ragas

Focused on RAG: faithfulness, response relevancy, context precision and recall, noise sensitivity, plus agent and tool-call metrics and synthetic test-set generation.

```bash
uv add ragas            # verify current version; metric import paths changed between releases
```

```python
from google import genai
from ragas.llms import llm_factory
from ragas.metrics.collections import ContextPrecision, ContextRecall, Faithfulness

gemini = genai.Client(vertexai=True, project="<PROJECT_ID>", location="<REGION>")   # ADC
judge = llm_factory("gemini-2.5-pro", provider="google", client=gemini)              # example model ID; verify

faithfulness = Faithfulness(llm=judge)
context_precision = ContextPrecision(llm=judge)
context_recall = ContextRecall(llm=judge)


async def score_rag_case(question: str, answer: str, contexts: list[str], reference: str) -> dict[str, float]:
    return {
        "faithfulness": (await faithfulness.ascore(user_input=question, response=answer, retrieved_contexts=contexts)).value,
        "context_precision": (await context_precision.ascore(user_input=question, reference=reference, retrieved_contexts=contexts)).value,
        "context_recall": (await context_recall.ascore(user_input=question, retrieved_contexts=contexts, reference=reference)).value,
    }
```

- Metrics in `ragas.metrics.collections` take the judge (and for some, an embeddings model) in the constructor and score one sample with `ascore(...)`. Older top-level imports from `ragas.metrics` are deprecated (verify for your version).
- Gemini support goes through an adapter layer; if structured output from the judge fails, check the Ragas docs for the currently recommended Gemini or Vertex AI setup before writing workarounds.
- Some metrics (for example response relevancy) also need an embeddings model; use the same embedding model family as production retrieval or a documented alternative, and record which.
- Synthetic test-set generation from your documents is useful to bootstrap a RAG dataset; review generated questions before they enter `test`.

## DeepEval

Evals as pytest-style tests: `LLMTestCase` objects, metrics with thresholds, `assert_test`, and a CLI runner. Includes G-Eval (criteria-based judge), RAG metrics (faithfulness, answer relevancy, contextual precision and recall), and agent metrics (tool correctness, task completion).

```bash
uv add deepeval         # verify current major; parameter enum names changed in recent releases
```

```python
import pytest
from deepeval import assert_test
from deepeval.metrics import FaithfulnessMetric, GEval
from deepeval.models import GeminiModel
from deepeval.test_case import LLMTestCase, SingleTurnParams   # older releases: LLMTestCaseParams

judge = GeminiModel(model="gemini-2.5-pro", project="<PROJECT_ID>", location="<REGION>", use_vertexai=True)  # ADC when no key is passed

concise_and_correct = GEval(
    name="concise-correct",
    criteria="The answer is correct according to the expected output and contains no unnecessary detail.",
    evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
    model=judge,
    threshold=0.7,
)
faithful = FaithfulnessMetric(model=judge, threshold=0.9)


@pytest.mark.live_llm
def test_refund_answer() -> None:
    case = LLMTestCase(
        input="Can I get a refund after 40 days?",
        actual_output=answer_from_system("Can I get a refund after 40 days?"),
        expected_output="Refunds are available within 30 days; after that, account credit may be offered.",
        retrieval_context=["Refunds are available within 30 days of purchase..."],
    )
    assert_test(case, [concise_and_correct, faithful])
```

- Run with `deepeval test run <file>` or plain pytest; set `DEEPEVAL_TELEMETRY_OPT_OUT=1` in CI.
- Pass `model=` to every metric. Without it, metrics fall back to a default judge from another provider that needs its own API key.
- Do not pass a service-account key to `GeminiModel`; with `use_vertexai=True` and no key it uses ADC (verify for your version).
- G-Eval scores are judge outputs; calibrate the criteria wording and threshold against human labels.

## promptfoo

A Node CLI that runs a matrix of prompts x providers x test cases from YAML, with many assertion types (string, regex, JSON, JavaScript or Python functions, model-graded rubrics, RAG context checks, latency, cost), a local web viewer and CI-friendly exit codes. Useful for prompt iteration and provider comparison; also has red-team scanning.

```yaml
# promptfooconfig.yaml
description: support answer prompt comparison
prompts:
  - file://prompts/support_answer.v3.txt
  - file://prompts/support_answer.v4.txt
providers:
  - id: vertex:gemini-2.5-flash          # example model ID; Vertex provider uses ADC (verify)
    config:
      projectId: "{{ env.GOOGLE_CLOUD_PROJECT }}"
      region: "{{ env.GOOGLE_CLOUD_LOCATION }}"
      temperature: 0
defaultTest:
  options:
    provider: vertex:gemini-2.5-pro      # grader for model-graded assertions
  assert:
    - type: not-icontains
      value: "<CANARY_STRING>"           # planted in the system prompt to detect leakage
    - type: latency
      threshold: 6000
tests:
  - description: refund window
    vars:
      query: Can I get a refund after 40 days?
      context: file://evals/contexts/refund-policy.md
    assert:
      - type: icontains
        value: 30 days
      - type: llm-rubric
        value: States the refund window and does not promise exceptions.
      - type: context-faithfulness
        threshold: 0.9
```

```bash
npx promptfoo@<pinned-version> eval -c promptfooconfig.yaml -o results/promptfoo.json --no-cache
npx promptfoo@<pinned-version> view      # local viewer
```

- `promptfoo eval` exits with a non-zero code (100 by default) when tests fail; `PROMPTFOO_PASS_RATE_THRESHOLD` relaxes that to a minimum pass rate (verify). Prefer converting the JSON output into your results file and gating with your own thresholds.
- To evaluate the deployed system rather than a raw model, use the HTTP provider with the endpoint URL, an `Authorization: Bearer {{ env.ID_TOKEN }}` header and a response transform that extracts the answer text (verify the current config keys).
- RAG assertions (`context-faithfulness`, `context-recall`, `context-relevance`) need `query` and `context` vars, or a `contextTransform` that extracts context from the system's output.
- Pin the promptfoo version (`npx promptfoo@<version>` or a dev dependency) so CI does not change behaviour under you.

## Old patterns

- `vertexai.evaluation.EvalTask` (the earlier evaluation module in the same SDK) still ships but the GenAI client (`vertexai.Client().evals`) is the recommended interface for new work (verify).
- Ragas metric singletons imported from `ragas.metrics` and scored with `evaluate()` over an `EvaluationDataset` are the older API; prefer `ragas.metrics.collections` (verify).
- DeepEval's `LLMTestCaseParams` was renamed `SingleTurnParams` (verify which your pinned version uses).
