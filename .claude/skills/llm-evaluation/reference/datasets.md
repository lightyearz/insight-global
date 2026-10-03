# Golden Datasets

## Contents
- Case schema
- Loading and validating
- Where cases come from
- How many cases
- Deterministic splits
- Labelling and agreement
- Versioning and manifests
- Multi-turn cases
- Calibrating classifier thresholds
- Maintenance

## Case schema

Keep cases in JSONL under version control (for example `evals/datasets/<feature>/cases.jsonl`), one case per line, so diffs are reviewable. Every field a grader needs lives in the case; graders never look anything up elsewhere.

```python
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Split(StrEnum):
    DEV = "dev"
    TEST = "test"


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    slice: str                                   # reporting group, e.g. "billing"
    tags: tuple[str, ...] = ()                   # cross-cutting: "adversarial", "multi-intent", "non-english"
    split: Split
    input: str | None = None                     # single-turn input
    history: tuple[Turn, ...] = ()               # prior turns for multi-turn cases
    expected_route: str | None = None            # router, persona or handler the request should reach
    expected_label: str | None = None            # classification tasks
    reference: str | None = None                 # gold answer for reference-based grading
    relevant_doc_ids: tuple[str, ...] = ()       # RAG: chunks or documents that answer the question
    expected_tools: tuple[str, ...] = ()         # agents: tool names in the expected order
    forbidden_tools: tuple[str, ...] = ()        # agents: must never be called
    must_include: tuple[str, ...] = ()           # required substrings (case-insensitive)
    must_not_include: tuple[str, ...] = ()       # forbidden substrings
    rubric: str | None = None                    # case-specific judge criteria, if any
    source: str                                  # provenance: "prod-sample-<date>", "handwritten", "synthetic-reviewed"
    notes: str | None = None
```

- `extra="forbid"` catches typos in field names, which otherwise silently disable a check.
- Prefer several narrow fields over one free-form `expected` blob; each grader reads only its own fields.
- Store the reason a case exists in `notes` (the bug or requirement it covers). Cases without a reason get deleted in clean-ups.

## Loading and validating

```python
import hashlib
import json
from pathlib import Path


class DatasetError(ValueError):
    pass


def load_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = EvalCase.model_validate_json(line)
        except ValueError as exc:
            raise DatasetError(f"{path}:{line_no}: {exc}") from exc
        if case.id in seen:
            raise DatasetError(f"{path}:{line_no}: duplicate id {case.id!r}")
        if case.input is None and not case.history:
            raise DatasetError(f"{path}:{line_no}: case has neither input nor history")
        seen.add(case.id)
        cases.append(case)
    return cases


def dataset_fingerprint(path: Path) -> str:
    """Content hash recorded in every results file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
```

Run `load_cases` in a unit test so a malformed dataset fails the normal test suite, not the expensive eval job.

## Where cases come from

| Source | Value | Caveats |
|--------|-------|---------|
| Redacted production samples | Real distribution, real phrasing | Redact PII first (`llm-guardrails`); sample across time, slices and outcome (not only complaints) |
| Production failures and incidents | Highest-value regression cases | Add the case in the same PR as the fix |
| Hand-written requirement cases | Cover every written requirement and rule | Authors write too-clean inputs; vary phrasing, length and typos |
| Hard negatives | Inputs that look like a class but are not | Essential for classifiers and routers; most false positives live here |
| Adversarial cases | Prompt injection, instruction override, attempts to extract the system prompt, off-topic steering | Keep them in their own slice with zero-tolerance checks |
| Edge cases | Empty, very long, non-English, mixed language, code, emoji-only, multiple intents | Usually a small `edge` slice |
| Synthetic (LLM-generated) | Fast coverage of rare slices | Must be reviewed by a person; tag `synthetic-reviewed`; never the only source for a slice |

Generating synthetic cases: give the model the slice definition, a few real examples and a list of variation axes (tone, length, phrasing, language, level of detail), ask for structured output, then deduplicate by embedding similarity and review every case before it enters `test`.

## How many cases

- Report a slice only when it has roughly 50 or more cases; gate a release on a slice only with 100 or more.
- The 95% confidence interval of a pass rate p over n cases is roughly `p +/- 1.96 * sqrt(p * (1 - p) / n)`. At p = 0.9: n = 50 gives about +/-8 points, n = 200 about +/-4, n = 1000 about +/-2. A "2 point improvement" on 50 cases is noise.
- For rare but costly failures (leaks, unsafe output), absence in 100 cases does not prove the rate is low: zero failures in n cases bounds the rate at about `3 / n` with 95% confidence (the rule of three). Add targeted adversarial cases instead of waiting for random ones.
- Spend new cases where the intervals are widest or the failures most costly, not evenly.

## Deterministic splits

Assign the split once, by a stable hash, and store it in the case, so it never moves when the file is reordered or extended:

```python
def assign_split(case_id: str, test_fraction: float = 0.5) -> Split:
    bucket = int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % 10_000
    return Split.TEST if bucket < test_fraction * 10_000 else Split.DEV
```

- Prompt iteration, few-shot selection and threshold tuning use `dev` only.
- `test` is for reporting and gating. If someone tunes against `test`, retire those cases to `dev` and add fresh ones.
- Keep near-duplicates (same template, same source conversation) in the same split, for example by hashing a `group_id` instead of the case ID.

## Labelling and agreement

- Write a labelling guide with definitions, a decision procedure for ambiguous cases, and a worked example for every label or score.
- Have two people label an overlapping sample of 50-100 cases. Measure agreement (percent agreement and Cohen's kappa). If people disagree, a model cannot be graded against them; fix the guide first.
- Resolve disagreements by discussion and record the decision in the guide, not only in the label.
- Rough reading of kappa: below 0.4 means the task or guide is unclear; 0.6-0.8 is usable; above 0.8 is strong. These are conventions, not laws.

```python
from sklearn.metrics import cohen_kappa_score


def agreement(labels_a: list[str], labels_b: list[str]) -> dict[str, float]:
    matches = sum(a == b for a, b in zip(labels_a, labels_b, strict=True))
    return {
        "percent_agreement": matches / len(labels_a),
        "cohen_kappa": float(cohen_kappa_score(labels_a, labels_b)),
    }
```

## Versioning and manifests

Each dataset directory carries a manifest that the runner checks and copies into every results file:

```json
{
  "dataset": "support-chat",
  "version": "2026.10.1",
  "fingerprint": "3f9c0a1b2c4d5e6f",
  "cases": {"billing": 120, "account": 96, "adversarial": 80, "edge": 40},
  "splits": {"dev": 168, "test": 168},
  "labelling_guide": "labelling-guide.md",
  "changelog": "Added 12 multi-intent billing cases from incident review"
}
```

- Bump the version on any change, including a corrected label. Scores from different dataset versions are not comparable without rerunning the baseline.
- The runner refuses to start if the manifest fingerprint does not match the file, which catches unreviewed edits.
- Large or sensitive datasets (redacted production samples) can live in a private bucket or BigQuery table; keep the manifest and the loader in the repo and record the object generation or snapshot ID.

## Multi-turn cases

- Store prior turns in `history` and grade only the final assistant turn, unless the check is explicitly about the whole conversation.
- When a behaviour is designed to appear on a later turn (for example the system asks a clarifying question first), write the case with the history that leads to that turn. Grading the first turn against a later-turn expectation produces a permanently failing check.
- For conversation-level properties (stays on topic, keeps a persona, never reveals instructions under pressure), generate the user turns with a scripted or simulated user, cap the number of turns, and grade the full transcript.
- Freeze assistant turns in `history` (recorded, not regenerated) when you want to isolate the last turn; regenerate them when you want to measure compounding drift.

## Calibrating classifier thresholds

Classifiers and detectors inside an LLM pipeline (routers, embedding few-shot detectors, guardrail scores) need thresholds chosen on data:

1. Build a calibration set per class: at least 50 cases, roughly half true positives and half hard negatives, in the `dev` split.
2. Score every case and plot the positive and negative score distributions.
3. Choose the threshold by the cost of errors: maximise F1 when errors cost about the same; for classes where a miss is costly, fix a recall floor (for example 0.98) and take the highest threshold that still meets it; for classes that only trigger monitoring, favour precision.
4. Report precision, recall and F1 at the chosen threshold on the `test` split, not on the calibration data.
5. Record the threshold, set sizes, metrics and dataset version next to the configuration it applies to.
6. Recalibrate whenever the model, label set or example bank changes.

```python
import numpy as np
from sklearn.metrics import precision_recall_curve


def threshold_for_recall(y_true: np.ndarray, scores: np.ndarray, min_recall: float) -> float:
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    # thresholds has len(recall) - 1 entries; recall decreases as the threshold rises
    ok = np.where(recall[:-1] >= min_recall)[0]
    if ok.size == 0:
        raise ValueError("no threshold reaches the requested recall")
    return float(thresholds[ok[-1]])
```

Classifier design and score functions themselves are covered in `ai-ml-engineering`.

## Maintenance

- Review the dataset each quarter or after a major product change: remove cases whose requirement no longer exists, add cases for new features, rebalance slices.
- Feed production back in: route low-confidence predictions, user-reported failures and guardrail blocks to a review queue, and turn reviewed items into cases.
- Watch for saturation: when a slice passes at 100% for months, add harder cases or it stops telling you anything.
- Do not delete failing cases to make a number go up. Move a case only when its expectation was wrong, and record why in the changelog.
