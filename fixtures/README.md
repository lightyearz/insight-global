# Replay fixtures

Replay mode runs the whole pipeline with no credentials and no network:

| Setting | Replay behaviour |
|---|---|
| `DATA_MODE=replay` | Sources come from `sources.json`. |
| `LLM_PROVIDER=replay` | Every LLM step returns the recorded structured output. |

Without any credentials, replay is the default for both settings.

Replay is keyed by **step + item**, never by a prompt hash. You can therefore change a prompt without invalidating the fixtures.

> **Illustrative demo data.** The sources are real public records, but in the committed fixtures the LLM outputs
> (`llm/*.json`: extracted options, conflicts, relevance suggestions and report text) were hand-authored from those
> abstracts for replay and demos. They are not a reviewed clinical summary and not medical advice.

## Layout

```
fixtures/replay/<condition-slug>/
  manifest.json
  condition.json
  sources.json
  llm/
    extract_treatments/
      <source_id_to_filename(source.id)>.json   # one per entry in sources.json
    consolidate_options.json
    detect_conflicts.json
    suggest_relevance.json
    write_report.json
```

- **`<condition-slug>`:** lowercase kebab case, for example `type-2-diabetes`. It must equal `manifest.slug`.
- **File names:** `source_id_to_filename` lives in `api/app/agent/llm_outputs.py`. It replaces every character outside `[A-Za-z0-9._-]` with `_`:
  - `pubmed:38078589` becomes `pubmed_38078589.json`.
  - `medlineplus:diabetestype2` becomes `medlineplus_diabetestype2.json`.

## Files and their exact shapes

The ids, quotes and dates in the examples below are illustrative placeholders, not real records.

The Pydantic models are the source of truth. Every file must validate against its model.

| File | Model | Module |
|---|---|---|
| `manifest.json` | `ReplayManifest` | `app/schemas.py` |
| `condition.json` | `Condition` | `app/schemas.py` |
| `sources.json` | `list[Source]` | `app/schemas.py` |
| `llm/extract_treatments/<id>.json` | `ExtractTreatmentsOutput` | `app/agent/llm_outputs.py` |
| `llm/consolidate_options.json` | `ConsolidateOptionsOutput` | `app/agent/llm_outputs.py` |
| `llm/detect_conflicts.json` | `DetectConflictsOutput` | `app/agent/llm_outputs.py` |
| `llm/suggest_relevance.json` | `SuggestRelevanceOutput` | `app/agent/llm_outputs.py` |
| `llm/write_report.json` | `WriteReportOutput` | `app/agent/llm_outputs.py` |

All LLM files are exactly what Gemini returns for that step. Any value the agent derives deterministically is not stored in them. That includes source dates and tiers, grounding flags, confidence caps, suggested resolutions, the timeline and the report assembly. Replaying the recorded outputs therefore exercises the real post-processing code.

### manifest.json

```json
{
  "slug": "type-2-diabetes",
  "label": "Type 2 diabetes",
  "aliases": ["type 2 diabetes mellitus", "t2d", "t2dm", "diabetes type 2"],
  "recorded_at": "2026-10-03T14:00:00Z",
  "recorded_with": "hand-authored",
  "notes": "Sources fetched live from PubMed/MedlinePlus on recorded_at; LLM outputs hand-authored from the abstracts."
}
```

`recorded_with` is either `"hand-authored"` or the model id that produced the LLM files, for example `"gemini-3.8-flash"`.

### condition.json

```json
{ "input": "type 2 diabetes", "label": "Diabetes Mellitus, Type 2", "mesh_id": "D003924", "synonyms": ["Type 2 Diabetes", "NIDDM"] }
```

At run time, `input` is overwritten with what the user typed.

### sources.json

This file holds `Source` objects with **real** metadata copied from the live record: title, journal, authors, PMID, DOI, URL, `published_at` and `updated_at`. Follow these rules:

- `excerpt` is the real abstract or summary text, exactly as the connector would build it (see docs/CONTRACT.md, section 8).
  In this public copy, PubMed excerpts are truncated to the quoted sentences; see [Excerpts in this public copy](#excerpts-in-this-public-copy).
- `retrieved_at` is the real fetch time and stays fixed. The report shows it as the research snapshot.
- `reliability_tier`, `source_type` and `tier_rationale` follow the tier table in docs/CONTRACT.md, section 7.2.
- Never invent a PMID, a DOI or a date. If a date is unknown, use `null`.

### llm/extract_treatments/pubmed_38078589.json

```json
{
  "is_relevant": true,
  "issuing_body": "American Diabetes Association",
  "region": "US",
  "treatments": [
    {
      "name": "Metformin",
      "category": "pharmacologic",
      "drug_class": "Biguanide",
      "line_of_therapy": "first_line",
      "population": "Adults with type 2 diabetes without specific comorbidity indications",
      "summary": "Remains a preferred initial glucose-lowering agent for most adults.",
      "evidence": [
        {
          "quote": "<verbatim span from this source's excerpt>",
          "statement": "Metformin is recommended as initial therapy for most adults.",
          "recommendation_strength": null,
          "evidence_level": "A",
          "stance": "recommended"
        }
      ],
      "milestones": []
    }
  ],
  "notes": null
}
```

- `stance` is one of `recommended`, `recommended_against`, `conditional`, `insufficient_evidence`, `described` (contract 1.1).
- Every `quote` must be a verbatim span of that source's `excerpt`, of at least 5 words or 30 characters. The check is `is_grounded(quote, excerpt)`. Hand-authored fixtures must pass it. Keep exactly one deliberately ungrounded item in one fixture only if a test needs it, and say so in `notes`.
- A non-relevant source returns `{"is_relevant": false, "issuing_body": null, "region": null, "treatments": [], "notes": "..."}`.

### llm/consolidate_options.json

```json
{
  "options": [
    {
      "id": "opt-metformin",
      "name": "Metformin",
      "category": "pharmacologic",
      "drug_class": "Biguanide",
      "line_of_therapy": "first_line",
      "population": "Most adults with type 2 diabetes",
      "summary": "...",
      "member_refs": ["pubmed:38078589#0", "medlineplus:diabetestype2#1"],
      "confidence": "high"
    }
  ]
}
```

A ref has the form `"<source_id>#<index>"`, where the index points into that source's `treatments` array.

### llm/detect_conflicts.json

`side` groups positions that give the same answer (contract 1.1). The suggested resolution compares the best
source of each side, so sources that agree are never compared with each other.

```json
{
  "conflicts": [
    {
      "id": "conf-first-line-agent-with-ascvd",
      "topic": "Preferred first agent for adults with established cardiovascular disease",
      "conflict_type": "outdated_guidance",
      "treatment_option_ids": ["opt-metformin", "opt-sglt2-inhibitors"],
      "positions": [
        { "source_id": "pubmed:38078589", "side": 1, "statement": "...", "quote": "<verbatim>" },
        { "source_id": "pubmed:31234567", "side": 2, "statement": "...", "quote": "<verbatim>" }
      ],
      "ai_assessment": "The 2024 guideline post-dates the 2019 review and incorporates newer outcome trials..."
    }
  ]
}
```

`{"conflicts": []}` is valid. Each fixture **should** include at least one real, quotable conflict so the HITL path can be demonstrated. Typical sources of conflict are an older review against a newer guideline, or a US body against a UK or EU body.

### llm/suggest_relevance.json

```json
{ "suggestions": [ { "option_id": "opt-metformin", "suggested": true, "reason": "Core first-line therapy; drives most prescribing volume." } ] }
```

### llm/write_report.json

```json
{
  "title": "Standard of care: Type 2 diabetes (US)",
  "top_level_description": "120-200 words ...",
  "key_takeaways": ["...", "...", "..."]
}
```

The replay provider returns this file whatever the user selected. Write it for the **suggested** selection, which is the default path. The report's options, conflict log, sources, timeline and audit log are still assembled deterministically from the user's actual choices.

## Replay provider rules

- **Lookup path:**
  - `extract_treatments`: `FIXTURES_DIR/<fixture_slug>/llm/extract_treatments/<source_id_to_filename(item_key)>.json`.
  - All other steps: `FIXTURES_DIR/<fixture_slug>/llm/<step>.json`.
- **Validation:** each file is validated with its output model. A missing file raises `ReplayFixtureMissing`, which fails the step and names the expected path.
- **Usage and cost:** `model="replay"`, `tokens_in=0`, `tokens_out=0`, cost 0.
- **Condition matching:** `POST /api/briefings` matches the typed condition against `slug`, `label` and `aliases`. The match is case-insensitive and whitespace-normalised.
- **Pacing:** `REPLAY_STEP_DELAY_MS` adds a delay per node so the UI progress is visible.

## Adding a fixture

1. Fetch the real records. Live mode is easiest: run once with `DATA_MODE=live` and copy the briefing's `sources` and `condition` from `GET /api/briefings/{id}`. Alternatively, call E-utilities and MedlinePlus by hand.
2. Write the `llm/*.json` files. Hand-author them from the excerpts, or copy them from a real Gemini run. To record them automatically, see [Recording a fixture from a live run](#recording-a-fixture-from-a-live-run); a recorded fixture's `recorded_with` names the provider and model ids.
3. Run the fixture validation test (`uv run pytest -k fixtures`). It validates every file against its model and checks that every quote is grounded.

## Recording a fixture from a live run

Set `RECORD_FIXTURES=1` with `DATA_MODE=live` and a Gemini provider. The run records into
`api/data/recordings/<slug>.<briefing id>/`; after the report is written it is moved to `fixtures/replay/<slug>/`
unless that folder already exists (`RECORD_OVERWRITE=1` replaces it). The committed hand-authored fixtures are
therefore never overwritten by accident, and failed runs leave nothing behind in `fixtures/`.

Fixture staleness: schema drift is caught by the fixture test (every model forbids unknown fields and requires
every field). Prompt changes do not invalidate fixtures by design (replay is keyed by step + item).

## Excerpts in this public copy

The recorded fixtures (and the web mocks in `web/src/mocks/`) contain real public records. To respect publishers'
copyright, the published repository does **not** ship full journal abstracts:

- **Kept in full:** text that is public domain or openly licensed, such as MedlinePlus / National Library of Medicine
  health-topic summaries (US government work). ClinicalTrials.gov and openFDA records, when added, fall in the same group.
- **Truncated:** abstracts from other publishers (PubMed records from journals such as Annals of Internal Medicine,
  BMJ, CMAJ or the Cochrane Library). Each such `excerpt` holds only the sentences that contain a quote used as evidence,
  as a milestone, or in a conflict position for that source. Non-adjacent sentences are joined with ` … `. A source with
  no quoted sentence gets a short placeholder. Titles, authors, journal, PMID, DOI, dates and the PubMed URL are unchanged,
  so every source can be read in full at its link.
- Every quote remains a verbatim span of its (truncated) excerpt, so `uv run pytest -k fixtures` still passes.
- The `Source` schema rejects unknown fields, so there is no `excerpt_truncated` flag. Every PubMed excerpt in
  `fixtures/replay/` and `web/src/mocks/` should be treated as truncated. The synthetic test fixture in
  `api/tests/fixtures/` is invented text and is unaffected.

Live mode (`DATA_MODE=live`) always fetches the full abstract from PubMed at run time. Replay runs that call a real
model (`LLM_PROVIDER=vertex|gemini_api` with `DATA_MODE=replay`) therefore see shorter excerpts than a live run would.

### Retention cap

A truncated excerpt may keep at most 60% of the original abstract (`max_retained_ratio` in the export rules). One
exception is documented: PMID 39589443 (Herz, a short summary of the 2024 ESC guideline) keeps about 95%, because
each of its seven recommendations is quoted as evidence. The publisher and licence status of every record are
listed in [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md#pubmed-ncbi-e-utilities).
