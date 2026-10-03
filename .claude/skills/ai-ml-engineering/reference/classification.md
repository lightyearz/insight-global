# Text Classification: Zero-Shot, Ensembles, and Choosing an Approach

## Contents
- Zero-shot NLI classification
- Label design
- Per-class thresholds
- Multi-stage pipelines with early exit
- Merging an extra detector into an existing classifier
- Speed and caching
- When to use what
- Measuring accuracy

The running example is support-ticket triage: map a message to labels, and labels to a severity of `LOW`, `NORMAL`, `HIGH` or `CRITICAL`. The mechanics apply to any routing or moderation problem where some classes are much costlier to miss than others.

## Zero-shot NLI classification

A zero-shot NLI model turns every candidate label into a hypothesis ("This message is about {label}.") and scores entailment against the input. Cost is one forward pass per (text, label) pair, so **latency grows linearly with the number of labels**.

```python
import time
from dataclasses import dataclass
from enum import IntEnum

from transformers import pipeline


class Severity(IntEnum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


LABELS_BY_SEVERITY: dict[Severity, tuple[str, ...]] = {
    Severity.CRITICAL: ("service outage", "security breach", "data loss"),
    Severity.HIGH: ("cannot log in", "billing error", "bug blocking work"),
    Severity.NORMAL: ("how-to question", "feature request", "account settings change"),
    Severity.LOW: ("general feedback", "thank-you message", "small talk"),
}
SEVERITY_BY_LABEL: dict[str, Severity] = {
    label: severity for severity, labels in LABELS_BY_SEVERITY.items() for label in labels
}
ALL_LABELS: list[str] = list(SEVERITY_BY_LABEL)

# Lower threshold where a miss is expensive (recall-biased); higher where false alarms are.
THRESHOLDS: dict[Severity, float] = {
    Severity.CRITICAL: 0.25,
    Severity.HIGH: 0.35,
    Severity.NORMAL: 0.40,
    Severity.LOW: 0.40,
}
DEFAULT_SEVERITY = Severity.NORMAL


@dataclass(frozen=True, slots=True)
class LabelScore:
    label: str
    score: float


@dataclass(frozen=True, slots=True)
class Classification:
    severity: Severity
    labels: tuple[LabelScore, ...]
    inference_ms: float


class ZeroShotClassifier:
    def __init__(self, model_id: str = "facebook/bart-large-mnli", device: int = -1) -> None:
        # device=-1 is CPU; 0 is the first GPU.
        self._pipe = pipeline("zero-shot-classification", model=model_id, device=device)

    def classify(self, text: str) -> Classification:
        start = time.perf_counter()
        result = self._pipe(
            text,
            ALL_LABELS,
            multi_label=True,
            hypothesis_template="This message is about {}.",
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        detected = tuple(
            LabelScore(label, score)
            for label, score in zip(result["labels"], result["scores"], strict=True)
            if score >= THRESHOLDS[SEVERITY_BY_LABEL[label]]
        )
        severity = max((SEVERITY_BY_LABEL[d.label] for d in detected), default=DEFAULT_SEVERITY)
        return Classification(severity=severity, labels=detected, inference_ms=elapsed_ms)
```

- `multi_label=True` scores each label independently (entailment versus contradiction), so scores do not sum to 1 and several labels can pass. `multi_label=False` applies a softmax across labels so they compete; use it only when classes are mutually exclusive.
- The pipeline is synchronous and CPU-bound. Call it with `await asyncio.to_thread(clf.classify, text)` from async code.
- Alternatives to BART-MNLI: the `MoritzLaurer/deberta-v3-*-zeroshot-*` family is often more accurate at similar or smaller size; `facebook/bart-base`-sized NLI checkpoints are faster but weaker. Benchmark on your data.
- Expect a mediocre baseline on domain-specific labels. Label wording and thresholds usually matter more than the model.

## Label design

Do:
- Use short natural-language phrases (2-4 words): "cannot log in", not `ACCESS_01`.
- Make labels for costly classes specific: "active security breach" rather than "problem".
- Add contrast labels that separate severity: "cosmetic display glitch" versus "data loss", "question about an invoice" versus "charged twice".
- Group labels by outcome so assignment logic stays a lookup.
- Test with real, messy production-like text (typos, fragments, mixed topics).

Do not:
- Use abstract IDs or overly generic labels ("issue", "other").
- Mix entity extraction ("which product?") into a classification label set.
- Grow past ~30-40 labels on CPU without measuring latency; every label is another forward pass.

## Per-class thresholds

- Thresholds are per class, never one global number.
- Decide per class which error is costlier. Missed critical events: lower threshold, accept more false positives. Expensive actions on a positive (paging someone, blocking a user): higher threshold or a second confirmation.
- Confidence hierarchy for expensive actions: if the top class triggers an expensive action but its score is below a confirmation level, either run a second-stage check (stronger model or LLM) or downgrade to the next class and flag for review.

```python
CONFIRM_CRITICAL_AT = 0.5

if result.severity is Severity.CRITICAL:
    top = max(s.score for s in result.labels if SEVERITY_BY_LABEL[s.label] is Severity.CRITICAL)
    if top < CONFIRM_CRITICAL_AT:
        result = await confirm_with_llm(text, result)  # second stage decides, logs both scores
```

- Calibrate thresholds on a held-out set; the protocol is under "Threshold calibration protocol" in the `semantic-similarity.md` reference.

## Multi-stage pipelines with early exit

One generic model rarely serves every class well. Use specialised detectors per high-cost class, ordered from most to least severe, with early exit:

```python
import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Detection:
    detector: str
    label: str
    score: float


Detector = Callable[[str], Awaitable[Detection | None]]


@dataclass(frozen=True, slots=True)
class Stage:
    name: str
    severity: Severity
    detectors: Sequence[Detector]
    decide: Callable[[list[Detection]], bool]   # e.g. any() for recall-critical stages


async def _guarded(detector: Detector, text: str, health: "ComponentHealth") -> Detection | None:
    try:
        return await detector(text)
    except Exception as exc:  # one broken detector must not cancel the stage
        health.record_failure(exc)  # ERROR log + traceback + degraded flag (model-serving.md)
        return None


async def run_pipeline(text: str, stages: Sequence[Stage], health: "ComponentHealth") -> tuple[Severity, list[Detection], str]:
    for stage in stages:  # most severe first
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_guarded(d, text, health)) for d in stage.detectors]
        hits = [r for t in tasks if (r := t.result()) is not None]
        if stage.decide(hits):
            return stage.severity, hits, stage.name
    return DEFAULT_SEVERITY, [], "default"
```

- Detectors inside a stage run concurrently; a stage that decides stops the pipeline, so common, benign inputs pay for every stage while rare severe inputs exit early. If most traffic is benign, consider a cheap "clearly benign" stage first.
- Use `any()` for stages where a miss is unacceptable and a majority or weighted vote where false positives are costly.
- `asyncio.TaskGroup` cancels siblings when one task raises; the `_guarded` wrapper prevents that and records the failure. Decide per stage whether a failed detector should fail open or closed.
- Off-the-shelf task-specific models (sentiment, emotion, toxicity, language identification) on the Hugging Face Hub are good building blocks. Before adopting one, check its licence, training-data domain versus yours, label set, size and latency, and evaluate it on your data rather than trusting the model card.
- Load every model once at startup and keep it in memory; see the `model-serving.md` reference.

## Merging an extra detector into an existing classifier

When an additional detector (for example the embedding scanner in the `semantic-similarity.md` reference) runs alongside a base classifier:

1. Run the base classifier, then the detector (or both concurrently).
2. Final severity is `max(base, detector)`: upgrade-only, the detector never lowers a result.
3. Merge labels, de-duplicated by label ID.
4. Cache the **merged** result, never the base result alone.
5. Detector failure follows the component's documented fail mode and is recorded in health.

Guard against the "registered but never called" failure with an integration test:

```python
async def test_classify_when_detector_fires_should_raise_severity() -> None:
    # Arrange
    base = FakeBaseClassifier(severity=Severity.NORMAL)
    detector = FakeDetector(hit=Detection(detector="intent-bank", label="cancel_account", score=0.21))
    classifier = TicketClassifier(base=base, detectors=[detector])

    # Act
    result = await classifier.classify("please close my account and delete everything")

    # Assert
    assert detector.calls == 1
    assert result.severity is Severity.HIGH
```

## Speed and caching

- Smaller checkpoint: base or distilled models are 2-3x faster than large ones with some accuracy loss.
- Fewer labels: cost is linear in label count.
- Batching: pass a list of texts and `batch_size=8..32`; throughput improves several-fold.
- ONNX export plus INT8 dynamic quantization: commonly 2-3x faster on CPU; see the `model-serving.md` reference.
- GPU: much faster per call, but on Cloud Run GPUs add cost and region constraints; encoder models usually meet budgets on CPU with ONNX.
- Cache results:

```python
import hashlib


def classification_cache_key(text: str, *, model_version: str, labels_version: str, thresholds_version: str) -> str:
    normalised = " ".join(text.lower().split())
    digest = hashlib.sha256(normalised.encode()).hexdigest()
    return f"clf:{model_version}:{labels_version}:{thresholds_version}:{digest}"
```

The key must include the model, label-set and threshold versions; otherwise a label or threshold change keeps serving stale answers until the TTL expires. Use an in-process LRU for per-instance hot keys and Redis (Memorystore) when instances should share results. Set a TTL (for example 24 hours) and never cache inputs containing PII unless the cache is covered by the same retention rules as the source data.

## When to use what

Zero-shot NLI when:
- You have no labelled data yet, or classes change often.
- Data must stay in your environment and per-call cost must be zero.
- Moderate accuracy is acceptable and you can spend time tuning labels and thresholds.

An LLM with a response schema when:
- You need strong accuracy immediately and volume is moderate.
- Sending the text to the model provider is acceptable.
- Classes need judgement or context (multi-sentence, sarcasm, mixed intents).
- You want to bootstrap labelled data for a cheaper model (review a sample of its labels by hand).

A fine-tuned small encoder (or SetFit) when:
- You have a few hundred to a few thousand labelled examples.
- You need high accuracy, low latency (tens of ms) and zero per-call cost.

Embedding few-shot similarity when:
- Each class is defined well by examples rather than a name.
- You want non-engineers to extend classes by adding reviewed examples.

## Measuring accuracy

- Build a held-out eval set that is never used to tune labels, thresholds or few-shot examples. Aim for at least ~50 examples per class, drawn from realistic inputs.
- Report per-class precision, recall and F1 plus a confusion matrix; report recall of the costliest class on its own line.
- Re-run the same set before and after every change (model, labels, thresholds, examples) and keep the results with the change.
- Treat accuracy figures from a handful of examples, or from a model card, as anecdotes.
- Eval-set construction, judges and regression tracking are covered in `llm-evaluation`.
