# Benchmarks, Reports and the CI Gate

## Contents
- Suggested layout
- End-to-end benchmark runner
- Per-case checks
- Results file
- Report dashboard
- Thresholds
- Non-determinism and statistics
- Gate script
- GitHub Actions job
- Cost and latency tracking
- Operating the gate

## Suggested layout

One layout that works; adapt names to the repo:

```
evals/
  datasets/<feature>/cases.jsonl        # versioned cases (see datasets.md)
  datasets/<feature>/manifest.json
  judges/<criterion>.v<N>.md            # judge prompts (see llm-as-judge.md)
  checks.py                             # deterministic graders
  run.py                                # runner: cases -> system -> graders -> results file
  gate.py                               # results + thresholds + baseline -> pass/fail + summary
  report.py                             # dashboard over one or two results files
  thresholds.yaml
  baselines/<feature>.json              # results of the default branch, updated deliberately
```

Eval dependencies (judges, pandas, a dashboard library) go in a separate dependency group so they never reach the production image.

## End-to-end benchmark runner

The runner calls the system through the same entry point real users hit, so routing, prompt assembly, guardrails and streaming are all exercised. For a private Cloud Run service, send a Google-signed ID token (see `testing-qa` for the token patterns); test-user credentials, when the entry point needs a user session, come from Secret Manager at run time, never from the repo.

```python
import asyncio
import os
import time

import httpx

from evals.checks import grade_case            # deterministic checks, below
from evals.datasets import EvalCase


async def call_system(client: httpx.AsyncClient, case: EvalCase) -> dict[str, object]:
    started = time.perf_counter()
    try:
        response = await client.post(
            "/api/chat",                         # example path
            json={"message": case.input, "history": [t.model_dump() for t in case.history]},
            timeout=60.0,
        )
        response.raise_for_status()
        body = response.json()
        return {
            "output": body["text"],
            "route": response.headers.get("x-route"),           # expose route/model metadata for evals
            "model": response.headers.get("x-model-id"),
            "usage": body.get("usage", {}),
            "latency_ms": (time.perf_counter() - started) * 1000,
            "error": None,
        }
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        return {"output": "", "route": None, "model": None, "usage": {},
                "latency_ms": (time.perf_counter() - started) * 1000, "error": repr(exc)}


async def run_cases(cases: list[EvalCase], base_url: str, concurrency: int = 4) -> list[dict[str, object]]:
    headers = {"Authorization": f"Bearer {os.environ['ID_TOKEN']}"}
    semaphore = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(base_url=base_url, headers=headers) as client:

        async def one(case: EvalCase) -> dict[str, object]:
            async with semaphore:
                result = await call_system(client, case)
            return {"id": case.id, "slice": case.slice, "tags": list(case.tags),
                    "input": case.input, **result, "checks": grade_case(case, result)}

        return await asyncio.gather(*(one(c) for c in cases))
```

- Expose routing and model metadata in a response header, a trailing SSE event, or a debug field available only to eval callers, so routing can be graded without parsing prose.
- For streamed endpoints, record time to first token as well as total latency.
- Keep concurrency low enough to stay inside quota; a run that trips rate limits measures the limiter, not the system.
- Probe dependencies (classifiers, retrievers, guardrail services) at the start of the run and record their health; see "Results file".
- Cache system outputs keyed by (model, prompt version, retrieval config, case ID). When only graders change, rerun graders on cached outputs instead of paying for generation again.

## Per-case checks

Deterministic checks return a structured outcome with evidence, not just a boolean:

```python
import re

from pydantic import BaseModel


class CheckResult(BaseModel):
    name: str
    applicable: bool
    passed: bool | None = None
    evidence: str | None = None               # matched substring, actual route, missing phrase


def check_route(case: EvalCase, result: dict[str, object]) -> CheckResult:
    if case.expected_route is None:
        return CheckResult(name="routing", applicable=False)
    actual = result.get("route")
    return CheckResult(name="routing", applicable=True, passed=actual == case.expected_route,
                       evidence=f"expected={case.expected_route} actual={actual}")


def check_required_content(case: EvalCase, output: str) -> CheckResult:
    if not case.must_include:
        return CheckResult(name="required_content", applicable=False)
    missing = [p for p in case.must_include if p.lower() not in output.lower()]
    return CheckResult(name="required_content", applicable=True, passed=not missing,
                       evidence=f"missing: {missing}" if missing else None)


def check_leakage(output: str, fragments: list[str], min_len: int = 30) -> CheckResult:
    """Zero tolerance: no system-prompt fragment, secret or internal identifier in the output."""
    normalised = re.sub(r"\s+", " ", output.lower())
    for fragment in fragments:
        probe = re.sub(r"\s+", " ", fragment.lower())
        if len(probe) >= min_len and probe in normalised:
            return CheckResult(name="leakage", applicable=True, passed=False, evidence=fragment[:120])
    return CheckResult(name="leakage", applicable=True, passed=True)
```

- Build leakage fragments from the actual system prompt (sentences or distinctive lines long enough not to occur naturally), plus canary strings planted in the prompt purely for detection, plus internal identifiers. Rebuild the list whenever the prompt changes.
- A required-structure check (a mandated block, tag or JSON field) is the same pattern with a regex or a parser.
- Mark checks not applicable rather than passed when a case does not exercise them; otherwise pass rates inflate.
- Judge-based checks (see `llm-as-judge.md`) return the same `CheckResult` shape, with the judge's reason as evidence.

## Results file

One JSON file per run. Everything needed to reproduce, compare and triage:

```json
{
  "run": {"started_at": "...", "git_sha": "...", "branch": "...", "tier": "full",
          "dataset": "support-chat", "dataset_version": "...", "dataset_fingerprint": "...",
          "system_model": "...", "prompt_version": "...", "retrieval_config": "...",
          "judges": {"instruction_following": {"model": "...", "prompt_version": "v3"}}},
  "health": {"degraded": false, "dependencies": {"classifier": "ok", "retriever": "ok"}, "errors": 0},
  "checks": {"routing": {"applicable": 160, "passed": 155, "rate": 0.969},
             "leakage": {"applicable": 168, "passed": 168, "rate": 1.0}},
  "by_slice": {"billing": {"routing": {"applicable": 60, "passed": 59, "rate": 0.983}}},
  "latency_ms": {"p50": 1450, "p95": 3900, "mean": 1710, "ttft_p95": 900},
  "cost_usd": {"system_total": 0.41, "judge_total": 0.88, "per_case_mean": 0.0077},
  "failing_cases": [{"id": "...", "slice": "...", "failed": ["routing"], "evidence": {"routing": "expected=billing actual=general"}}],
  "results": [{"id": "...", "input": "...", "output": "...", "route": "...", "latency_ms": 1320,
               "usage": {"input_tokens": 812, "output_tokens": 164}, "checks": {}}]
}
```

- `failing_cases` is a reduced view for triage; `results` has everything.
- `health.degraded` is true when any dependency probe failed or any fallback fired during the run. The gate refuses to compare degraded runs.
- Store results files as CI artifacts; keep the latest default-branch file as the baseline.
- Results contain model outputs; if inputs came from production samples, store artifacts with the same access controls as the dataset.

## Report dashboard

A small report app (Streamlit works well; any notebook or static HTML does too) turns results files into something technical and non-technical reviewers can read:

1. **Header**: run metadata (dataset, versions, model, git SHA, time). A warning banner when the run is degraded; an error banner when `errors > 0`.
2. **Card per check**: pass rate with status from the thresholds file (pass / warn / fail). Any zero-tolerance failure shows a prominent alert above everything else. Use the design system's status colours and pair colour with an icon or text label.
3. **Latency panel**: p50, p95, mean, time to first token, and a histogram of per-case latency with p50 and p95 markers.
4. **Per-slice breakdown**: each check split by slice, so a broken category is visible even when the overall rate is fine.
5. **Case browser**: filterable table (slice, tags, route, pass/fail, text search); selecting a row shows the full input, output, retrieved context or tool calls, and each check with its evidence.
6. **Failing cases**: the triage list, grouped by check, with evidence inline.
7. **Comparison**: load a second results file (usually the baseline) and show per-check and per-slice deltas, cases that flipped pass to fail and fail to pass, and latency and cost deltas.

The report reads results files only; it never calls models. It is a development tool and should not be deployed publicly.

## Thresholds

```yaml
# evals/thresholds.yaml
dataset: support-chat
min_cases_per_slice: 50
zero_tolerance: [leakage, forbidden_tool, fabricated_citation]
floors:                       # absolute minimum pass rate per check, overall
  routing: 0.95
  required_content: 0.98
  schema_valid: 0.99
judge_floors:                 # minimum mean score per judge criterion
  instruction_following: 4.2
slice_floors:                 # stricter floors for specific slices
  adversarial:
    refusal_correct: 0.97
regression:
  max_drop_points: 3.0        # per check and slice, versus baseline
  significance: 0.05          # paired test on flipped cases
latency_ms:
  p95: 6000
  ttft_p95: 1500
cost_usd:
  per_case_mean: 0.01
  run_total: 10.0
```

- Floors encode "good enough to ship". Regression limits encode "no worse than what is already shipped". Use both: floors alone let quality erode slowly above the floor; regression limits alone let a bad baseline persist.
- Colour bands in the report come from the same file (for example warn within 2 points above a floor), so the dashboard and the gate never disagree.
- Raise floors deliberately after improvements land; do not leave them far below current performance.

## Non-determinism and statistics

- Temperature 0 reduces variation but does not remove it; providers do not guarantee identical outputs. Set a seed where the API supports one, and still expect some churn.
- Same cases in both runs means a **paired** comparison: count cases that flipped pass to fail (`b`) and fail to pass (`c`). With an exact binomial (McNemar) test on `b` versus `c`, a handful of flips on a large set is noise; many flips in one direction is a real change.
- For mean judge scores, bootstrap a confidence interval by resampling cases.
- For slices with high run-to-run variation (agents, long generations), run 3-5 repeats in nightly runs and compare mean pass rates.

```python
import random
from statistics import mean

from scipy.stats import binomtest


def paired_regression(baseline: dict[str, bool], current: dict[str, bool], alpha: float = 0.05) -> dict[str, float | bool]:
    shared = baseline.keys() & current.keys()
    b = sum(baseline[i] and not current[i] for i in shared)    # pass -> fail
    c = sum(not baseline[i] and current[i] for i in shared)    # fail -> pass
    p_value = binomtest(b, b + c, 0.5).pvalue if b + c else 1.0
    return {"pass_to_fail": b, "fail_to_pass": c, "p_value": p_value, "significant_regression": b > c and p_value < alpha}


def bootstrap_ci(scores: list[float], iterations: int = 2000, level: float = 0.95, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(mean(rng.choices(scores, k=len(scores))) for _ in range(iterations))
    lo = means[int((1 - level) / 2 * iterations)]
    hi = means[int((1 + level) / 2 * iterations) - 1]
    return lo, hi
```

## Gate script

The gate reads the results file, the thresholds and the baseline, prints a Markdown summary (for `$GITHUB_STEP_SUMMARY` and a PR comment), and exits non-zero on failure. Order of evaluation:

1. Refuse if the run is degraded, the dataset fingerprint does not match the manifest, or a gated slice has fewer than `min_cases_per_slice` cases. Exit with a distinct code so "could not evaluate" is never mistaken for "passed".
2. Fail on any zero-tolerance hit; list the case IDs and evidence.
3. Fail on any floor breach (overall, per slice, per judge criterion).
4. Fail on a regression larger than `max_drop_points` that is also significant in the paired test.
5. Fail on latency or cost ceilings.
6. Otherwise pass, still printing deltas so reviewers see small movements.

The summary leads with the verdict and the failing items, then a compact per-check and per-slice table with baseline, current and delta, then latency and cost. Link the full results artifact.

## GitHub Actions job

```yaml
name: llm-eval
on:
  pull_request:
    paths: ["app/llm/**", "prompts/**", "evals/**", "config/models.yaml"]   # whatever affects model behaviour
  schedule:
    - cron: "23 3 * * *"         # nightly full run
  workflow_dispatch:

permissions:
  contents: read
  id-token: write                # Workload Identity Federation

concurrency:
  group: llm-eval-${{ github.ref }}
  cancel-in-progress: true

jobs:
  eval:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@v4                       # pin current majors (verify)
      - id: auth
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.WIF_PROVIDER }}   # projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/<POOL>/providers/<PROVIDER>
          service_account: ${{ vars.EVAL_SA }}                    # <SA_NAME>@<PROJECT_ID>.iam.gserviceaccount.com
          token_format: id_token
          id_token_audience: ${{ vars.SERVICE_URL }}
          id_token_include_email: true
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen --group eval
      - name: Run evals
        env:
          GOOGLE_CLOUD_PROJECT: ${{ vars.GCP_PROJECT }}
          GOOGLE_CLOUD_LOCATION: ${{ vars.GCP_REGION }}
          ID_TOKEN: ${{ steps.auth.outputs.id_token }}
          EVAL_TIER: ${{ github.event_name == 'pull_request' && 'smoke' || 'full' }}
        run: uv run python -m evals.run --tier "$EVAL_TIER" --base-url "${{ vars.SERVICE_URL }}" --out results/run.json
      - name: Gate
        run: uv run python -m evals.gate results/run.json --thresholds evals/thresholds.yaml --baseline evals/baselines/support-chat.json --summary "$GITHUB_STEP_SUMMARY"
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: eval-results-${{ github.run_id }}
          path: results/
          retention-days: 30
```

- The eval service account needs `roles/aiplatform.user` for judge and model calls and `roles/run.invoker` on the service under test; nothing else. The auth step also writes ADC credentials, so the Vertex AI client picks them up without keys.
- PRs from forks do not get `id-token: write`; run evals for them only after a maintainer applies a label or via `workflow_dispatch`.
- For a PR, evaluate a preview deployment of the PR's code (for example a tagged Cloud Run revision with no traffic) or start the service inside the job; evaluating the shared environment measures the default branch, not the PR.
- Make the smoke tier fast (a few minutes) so people do not learn to skip it.

## Cost and latency tracking

Per case, record from `usage_metadata`: prompt, candidate (output), cached and thinking token counts; the model ID; latency, time to first token, retries and whether a fallback fired. Then:

- estimate cost with the dated price table maintained per `llm-models-expert` (store the table version in the results file);
- aggregate p50 and p95 latency and mean and p95 cost per slice; long-tail cases often dominate both;
- report judge cost separately from system cost;
- plot trends from nightly results (a BigQuery table loaded from the results files works well), so slow drift in tokens per answer or latency is visible before it breaches a ceiling;
- set a hard per-run budget in the runner (maximum cases times maximum repeats times maximum judge calls) and abort before exceeding it.

## Operating the gate

- **Baselines**: update by a dedicated commit on the default branch after a reviewed improvement, with the results file attached. Never auto-update from PR runs.
- **Flaky cases**: if a case flips without changes, quarantine it in a `flaky` tag (reported but not gated), investigate, and fix the case or the grader within a set time. Do not raise thresholds to absorb flakiness.
- **Overrides**: a release that must ship despite a failing gate needs a written reason in the PR and a follow-up issue; do not delete or weaken cases to turn the gate green.
- **Headless versus UI**: the benchmark grades API responses. Rendering of structured blocks, expand/collapse controls, math, progress indicators and streaming UI need Playwright specs (`frontend-test-runner`); recorded runs of those specs are the proof that a fix works for users.
- **Online signals**: after release, watch user feedback, guardrail block rates, fallback rates and sampled human review. Disagreement between online signals and offline evals means the dataset no longer matches real traffic; refresh it.
