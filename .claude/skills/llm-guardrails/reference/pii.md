# PII Detection and Redaction

## Contents

- [Decide what counts](#decide-what-counts)
- [Presidio setup](#presidio-setup)
- [Custom recognisers](#custom-recognisers)
- [Per-entity thresholds and allow lists](#per-entity-thresholds-and-allow-lists)
- [Adding GLiNER](#adding-gliner)
- [Anonymisation strategies](#anonymisation-strategies)
- [Reversible pseudonymisation for LLM calls](#reversible-pseudonymisation-for-llm-calls)
- [Keyed hashing for joins](#keyed-hashing-for-joins)
- [Output-side checks](#output-side-checks)
- [Managed alternative: Sensitive Data Protection](#managed-alternative-sensitive-data-protection)
- [Logging and audit](#logging-and-audit)
- [Performance and deployment](#performance-and-deployment)
- [Evaluating detection](#evaluating-detection)
- [Pitfalls](#pitfalls)

The Presidio code below was run against `presidio-analyzer` / `presidio-anonymizer` 2.2.x; check signatures when upgrading.

## Decide what counts

Agree the entity list with whoever owns data governance, and keep it in the policy file:

- Direct identifiers: names, email addresses, phone numbers, postal addresses, government IDs, payment card and bank numbers.
- Indirect identifiers that matter in your domain: customer or account IDs, usernames and social handles, employer or organisation names, IP addresses, precise locations, dates of birth.
- Secrets that are not PII but must never reach a model or a log: API keys, tokens, passwords, private keys.

For each entity decide: detect at all, action (redact, pseudonymise, block), threshold, and whether it may be restored in the output.

## Presidio setup

```python
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

NLP_CONFIG = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
}


def build_analyzer() -> AnalyzerEngine:
    nlp_engine = NlpEngineProvider(nlp_configuration=NLP_CONFIG).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
    for recognizer in custom_recognizers():
        analyzer.registry.add_recognizer(recognizer)
    return analyzer
```

- Build the analyzer once at startup (FastAPI `lifespan`) and share it; model load takes seconds.
- `en_core_web_lg` gives better person and location recall than `en_core_web_sm` at several hundred MB more memory. A transformers NER engine is more accurate again and much slower on CPU. Measure on your data.
- Each language needs its own NLP model and recognisers. Detect the language first; route unsupported languages to the fail-closed path or a managed detector rather than scanning them with the English model.
- Install the spaCy model in the image build (pinned version), not at runtime.

## Custom recognisers

```python
from presidio_analyzer import Pattern, PatternRecognizer


def custom_recognizers() -> list[PatternRecognizer]:
    return [
        PatternRecognizer(
            supported_entity="CUSTOMER_ID",
            name="customer_id_recognizer",
            patterns=[Pattern(name="customer_id", regex=r"\bCUST-\d{8}\b", score=0.6)],
            context=["customer", "account"],  # nearby words raise the score
        ),
        PatternRecognizer(
            supported_entity="INTERNAL_HOSTNAME",
            name="internal_host_recognizer",
            patterns=[Pattern(name="internal_host", regex=r"\b[a-z0-9-]+\.internal\.example\b", score=0.8)],
        ),
    ]
```

- Start pattern scores low when the pattern is ambiguous and let context words raise them.
- Deny lists (`deny_list=[...]`) suit closed vocabularies such as internal project code names.
- Every custom recogniser gets positive and negative unit tests.

## Per-entity thresholds and allow lists

Default scores differ widely by recogniser (a phone number with no context words can score 0.4 while an email scores 1.0), so a single global threshold is wrong for someone.

```python
from presidio_analyzer import RecognizerResult

ENTITY_THRESHOLDS: dict[str, float] = {
    "PERSON": 0.6,
    "LOCATION": 0.6,
    "EMAIL_ADDRESS": 0.5,
    "PHONE_NUMBER": 0.4,
    "CREDIT_CARD": 0.5,
    "CUSTOMER_ID": 0.5,
}
DEFAULT_THRESHOLD = 0.5


def detect(analyzer: AnalyzerEngine, text: str, allow_list: list[str]) -> list[RecognizerResult]:
    results = analyzer.analyze(
        text=text, language="en", entities=list(ENTITY_THRESHOLDS), allow_list=allow_list,
    )
    return [r for r in results if r.score >= ENTITY_THRESHOLDS.get(r.entity_type, DEFAULT_THRESHOLD)]
```

- `allow_list` suppresses known false positives such as your product and feature names.
- Load thresholds and allow lists from the policy file, and record their calibration results next to them.

## Adding GLiNER

GLiNER is a small zero-shot NER model: you pass entity labels as text at inference time, which helps with entities that regexes and spaCy miss (names in lowercase, usernames, organisation names, domain-specific identifiers). It is for span extraction only; do not use it for topic or intent classification.

Presidio ships a `GLiNERRecognizer` that plugs into the same registry, so its results merge with the others:

```python
from presidio_analyzer.predefined_recognizers import GLiNERRecognizer

GLINER_LABELS = {  # GLiNER label -> Presidio entity
    "person": "PERSON",
    "email": "EMAIL_ADDRESS",
    "phone number": "PHONE_NUMBER",
    "street address": "LOCATION",
    "organization": "ORGANIZATION",
    "username": "USERNAME",
}


def add_gliner(analyzer: AnalyzerEngine) -> None:
    analyzer.registry.add_recognizer(
        GLiNERRecognizer(
            model_name="urchade/gliner_multi_pii-v1",
            entity_mapping=GLINER_LABELS,
            flat_ner=False,
            multi_label=True,
            threshold=0.5,
            map_location="cpu",
        )
    )
    analyzer.registry.remove_recognizer("SpacyRecognizer")  # optional: avoid duplicate PERSON/LOCATION spans
```

- Recent Presidio releases chunk long text for GLiNER automatically (character chunks with overlap); older releases do not, so check before relying on it.
- Cost grows with text length and with the number of labels. Keep the label list short and measure p95 on realistic inputs; GLiNER is often the slowest PII component.
- Pin the model revision, bake it into the image and load offline. Check the licence of the GLiNER checkpoint you choose.
- Evaluate the combined pipeline, not GLiNER alone: the point is the recall it adds on top of Presidio, against the false positives it adds.

### Merging and overlaps

When recognisers disagree, resolve overlaps before replacing text: keep the higher score, then the longer span.

```python
def resolve_overlaps(results: list[RecognizerResult]) -> list[RecognizerResult]:
    ordered = sorted(results, key=lambda r: (-r.score, -(r.end - r.start)))
    kept: list[RecognizerResult] = []
    for r in ordered:
        if all(r.end <= k.start or r.start >= k.end for k in kept):
            kept.append(r)
    return sorted(kept, key=lambda r: r.start)
```

`AnonymizerEngine.anonymize` applies its own conflict resolution; the helper above is for custom replacement such as pseudonymisation.

## Anonymisation strategies

| Strategy | Presidio operator | Reversible | Use for |
|----------|-------------------|------------|---------|
| Typed placeholder | `replace` with `<ENTITY>` | no | logs, analytics, eval datasets |
| Numbered pseudonym | custom (below) | yes, within the request | LLM calls whose answer must refer back to the entities |
| Mask | `mask` (`masking_char`, `chars_to_mask`, `from_end`) | no | showing partial values ("****0187") |
| Redact | `redact` | no | removing entirely when the model does not need to know something was there |
| Hash | `hash` (`hash_type`, optional fixed `salt`) | no | joining records without storing the value; prefer keyed HMAC (below) |
| Encrypt | `encrypt` (AES `key`), `DeanonymizeEngine` + `decrypt` | yes, with the key | stored records that authorised staff must later read |

```python
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

anonymizer = AnonymizerEngine()

redacted = anonymizer.anonymize(
    text=text,
    analyzer_results=results,
    operators={
        "DEFAULT": OperatorConfig("replace", {"new_value": "<PII>"}),
        "PHONE_NUMBER": OperatorConfig("mask", {"masking_char": "*", "chars_to_mask": 8, "from_end": False}),
    },
).text
```

Encryption keys come from Secret Manager (or Cloud KMS), never from code or config files.

## Reversible pseudonymisation for LLM calls

Numbered, consistent placeholders let the model reason about who did what ("`<PERSON_1>` emailed `<PERSON_2>`") without seeing the values. The mapping lives only in request scope.

```python
import re
from collections import defaultdict
from dataclasses import dataclass

_PLACEHOLDER = re.compile(r"<([A-Z][A-Z_]*)_(\d+)>")


@dataclass(frozen=True)
class Pseudonymised:
    text: str
    mapping: dict[str, str]  # placeholder -> original; request scope only, never logged


def neutralise_placeholder_lookalikes(text: str) -> str:
    """Stop user text that already looks like a placeholder from being 'restored'."""
    return _PLACEHOLDER.sub(lambda m: m.group(0).replace("<", "‹").replace(">", "›"), text)


def pseudonymise(text: str, results: list[RecognizerResult]) -> Pseudonymised:
    mapping: dict[str, str] = {}
    seen: dict[tuple[str, str], str] = {}
    counters: defaultdict[str, int] = defaultdict(int)
    parts: list[str] = []
    cursor = 0
    for r in resolve_overlaps(results):
        original = text[r.start : r.end]
        key = (r.entity_type, original.casefold())
        placeholder = seen.get(key)
        if placeholder is None:
            counters[r.entity_type] += 1
            placeholder = f"<{r.entity_type}_{counters[r.entity_type]}>"
            seen[key] = placeholder
            mapping[placeholder] = original
        parts.append(text[cursor : r.start])
        parts.append(placeholder)
        cursor = r.end
    parts.append(text[cursor:])
    return Pseudonymised("".join(parts), mapping)


def restore(text: str, mapping: dict[str, str]) -> str:
    """Put originals back; unknown placeholders (invented by the model) are removed."""
    return _PLACEHOLDER.sub(lambda m: mapping.get(m.group(0), "[redacted]"), text)
```

Order of operations: normalise, then `neutralise_placeholder_lookalikes`, then detect, then `pseudonymise`, then generate, then output checks on the pseudonymised output, then `restore`.

- Tell the model in the system prompt that placeholders must be kept verbatim and that it must not guess the real values.
- Restore only when the output goes back to the same user who supplied the values. Never restore into logs, stored transcripts shared with others, or tool arguments the user has not approved.
- Count placeholder-restore failures (unknown or mangled placeholders) as a metric; a rising rate means the prompt or model changed behaviour.
- Same name, same placeholder within a conversation: keep the mapping in server-side session state if pseudonyms must stay stable across turns, with the same retention as the conversation.

## Keyed hashing for joins

When analytics needs to count or join by a person without storing who they are, use an HMAC with a key from Secret Manager rather than a plain or fixed-salt hash (plain hashes of emails and phone numbers are trivially reversed by brute force).

```python
import hashlib
import hmac


def pseudonymous_id(value: str, key: bytes) -> str:
    return hmac.new(key, value.casefold().encode(), hashlib.sha256).hexdigest()[:32]
```

Store the key version alongside each ID; rotating the key breaks joins across versions by design.

## Output-side checks

- Run the same detector on model output before restoring pseudonyms. Any PII that is not a known placeholder came from the model (memorised data, retrieved documents, other users' records via a leaky tool) and is redacted or blocked per policy.
- Scan tool outputs and retrieved chunks for PII before they enter the context when the user is not entitled to see that data.
- Scan for secrets in both directions with regex and entropy scanners.

## Managed alternative: Sensitive Data Protection

Google Cloud Sensitive Data Protection (the DLP API) provides a large catalogue of built-in infoTypes, custom infoTypes, and de-identification transforms. It suits teams that prefer not to operate NER models, need many country-specific identifiers, or already use it for storage scanning. It is also what the Model Armor SDP filter uses.

```python
from google.cloud import dlp_v2

dlp = dlp_v2.DlpServiceClient()  # ADC; the runtime service account needs a DLP user role


def deidentify(text: str, project_id: str, location: str) -> str:
    response = dlp.deidentify_content(
        request=dlp_v2.DeidentifyContentRequest(
            parent=f"projects/{project_id}/locations/{location}",
            inspect_config=dlp_v2.InspectConfig(
                info_types=[dlp_v2.InfoType(name=n) for n in ("EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON_NAME")],
                min_likelihood=dlp_v2.Likelihood.LIKELY,
            ),
            deidentify_config=dlp_v2.DeidentifyConfig(
                info_type_transformations=dlp_v2.InfoTypeTransformations(
                    transformations=[
                        dlp_v2.InfoTypeTransformations.InfoTypeTransformation(
                            primitive_transformation=dlp_v2.PrimitiveTransformation(
                                replace_with_info_type_config=dlp_v2.ReplaceWithInfoTypeConfig()
                            )
                        )
                    ]
                )
            ),
            item=dlp_v2.ContentItem(value=text),
        ),
        timeout=2.0,
    )
    return response.item.value
```

- Keep inspect and de-identify configuration in templates managed as infrastructure, and reference them by name.
- Choose the processing location to match data-residency requirements.
- It is a network call with per-request cost and its own quotas: apply a timeout, the circuit breaker, and the fail-closed mode like any other check. Prices change; check them with `cloud-costs-optimization`.
- A hybrid is common: Presidio in-process for the hot path, Sensitive Data Protection for batch scanning of stored data.

## Logging and audit

- Log entity types, counts, offsets, scores, recogniser names, model revisions and the policy version. Never the matched values.
- Keep an audit record of detection and redaction decisions where regulation or customer contracts require it, with a defined retention.
- After detection, PII is not stored in plain text unless the feature needs it and the store is access-controlled. Store the minimum required.

## Performance and deployment

- In-process Presidio is usually fastest; a dedicated private PII service makes sense when several services share it or GLiNER's memory would bloat every API instance.
- Run analysis through `asyncio.to_thread` behind a semaphore; spaCy and GLiNER are CPU-bound.
- Batch when scanning many chunks (`BatchAnalyzerEngine`, or one GLiNER call over several texts).
- Size memory for the spaCy model plus GLiNER plus headroom, and gate readiness on both being loaded (`ai-ml-engineering`, model-serving reference).

## Evaluating detection

- Build a labelled set with realistic formats for your users: international phone numbers, names from many cultures, lowercase names, obfuscated emails ("jane at example dot com"), IDs inside URLs, PII split across lines.
- Generate synthetic records with Faker-style generators so test data contains no real people; never copy production text into the repo.
- Report recall and precision per entity type. Track recall on the highest-risk types (payment cards, government IDs) separately with a floor.
- Include benign hard negatives: product names, common words that are also names, version numbers that look like phone numbers.
- Re-run the evaluation for every recogniser, threshold, model or library upgrade (`llm-evaluation`).

## Pitfalls

- Regex-only PII detection misses most names and addresses; NER-only misses structured IDs. Use both.
- Detecting on one string and sending another (for example detection before normalisation, generation after) produces offsets that point at the wrong characters.
- NER spans vary between mentions (the full name once, only the first name the next time), so one person can receive two placeholders, and a partial span leaves the surname in clear text. Larger NER models and GLiNER reduce this; test repeated mentions explicitly and do not promise exact coreference.
- A PII step that fails open sends raw PII to the model whenever it is slow. Fail closed.
- Debug logging of prompts undoes all of this.
