# Health Briefing POC: contract (v1.1.0)

This document is the contract every builder codes against. The sources of truth are:

| What | File |
|---|---|
| API and persisted models | `api/app/schemas.py` |
| TypeScript mirror (same names, snake_case) | `web/src/lib/types.ts` |
| LLM structured outputs, LLM client interface, grounding helpers | `api/app/agent/llm_outputs.py` |
| Replay fixture format | `fixtures/README.md` |

Why each design choice was made (and what was rejected) is in [DECISIONS.md](DECISIONS.md).

### Changes in v1.1.0 (review fixes; every new field has a default, so v1.0.0 documents still load)

| Area | Change |
|---|---|
| `Source` | `url` must be `https` on `pubmed.ncbi.nlm.nih.gov`, `medlineplus.gov` or `www.nlm.nih.gov`. New `region_inferred` (true when the AI inferred the region). |
| `Evidence` | New `stance`: `recommended`, `recommended_against`, `conditional`, `insufficient_evidence`, `described`. |
| `TreatmentOption` | New `recommendation_direction`: `for`, `against`, `conditional`, `mixed`, `not_stated` (derived from stances). |
| `ConflictPosition` | New `side`: positions with the same side give the same answer. |
| `SuggestedResolution` | New `rule`: which deterministic rule produced it. |
| `TimelineEvent` | New `short_label` (chart label, e.g. `ACP 2024`). |
| `Report` | New `excluded_options`, `research_started_at`, `research_completed_at`, `search_strategy`. |
| `Briefing` | New `search_strategy`. `RunInfo.model_versions`. `BriefingSummary.research_conducted_at` and `data_mode`. |
| `ReviewSubmission` | At most 200 option ids and 50 resolutions. A note is required whenever a decision differs from the suggestion. |
| API | `POST /api/briefings/{id}/retry`; 429 run limits; 409 when a review's checkpoint is lost. |
| LLM outputs | `ExtractedEvidence.stance`, `DetectedConflictPosition.side`. |

Scope of this slice: one agent, **standard of care** (current treatment options) for one condition. The pipeline is: retrieve public sources, extract treatments with Gemini, have a human select options and resolve conflicts, then generate the report. It uses public literature only and no PHI. **This is not medical advice**: `DISCLAIMER` appears in the UI and in every report.

---

## 1. Layout

```
./                          repository root
  api/                      FastAPI + LangGraph (uv, Python >= 3.11)
    pyproject.toml
    app/
      main.py               FastAPI app, CORS, lifespan (store + checkpointer + startup recovery)
      config.py             pydantic-settings Settings (section 9)
      schemas.py            CONTRACT
      store.py              SQLite persistence of Briefing JSON + JobEvents
      events.py             in-process event bus (per-briefing asyncio fan-out) + seq allocation
      users.py              seeded users + X-User-Id dependency
      routers/              health.py, users.py, conditions.py, briefings.py
      llm/                  base.py (factory), vertex.py, gemini_api.py, replay.py, pricing.py
      connectors/           http.py (shared client, rate limit, retries), pubmed.py, medlineplus.py,
                            mesh.py, clinical_tables.py, replay.py
      agent/
        llm_outputs.py      CONTRACT
        graph.py            StateGraph build + runner (start / resume)
        nodes/              one module per node
        prompts.py          system and user prompt builders
        policy.py           tiering, confidence caps, conflict resolution policy
        timeline.py         deterministic timeline assembly
    tests/
  web/                      Next.js 16, React 19, TS strict, Tailwind v4, lucide-react
    src/lib/types.ts        CONTRACT
    src/lib/api.ts          typed fetch client + SSE helper
  fixtures/replay/<slug>/   recorded runs (see fixtures/README.md)
  docs/CONTRACT.md          this file
```

Nothing in this repository imports code from outside it. Keep secrets out of the repo and out of logs.

---

## 2. Wire format

- JSON, UTF-8. Field names are snake_case, identical in Python and TypeScript.
- **Every field is always present** in responses. Optional values are `null`, never omitted, so never use `exclude_none` or `exclude_unset` on responses.
- Datetimes are timezone-aware UTC ISO 8601 (`2026-10-03T15:17:59.192907Z`). Python uses `datetime.now(timezone.utc)`.
- `PartialDate`: `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. Use `schemas.date_precision_of()` to get the precision. Lexicographic order of partial dates is chronological order.
- IDs:
  - Briefing: `brf_` + 12 lowercase hex characters.
  - Source: `pubmed:<pmid>` or `medlineplus:<page slug>` (for example `medlineplus:diabetestype2`).
  - Option: `opt-<kebab>`.
  - Conflict: `conf-<kebab>`.
  - Timeline event: `tl-<kebab>`.
  - User: `[a-z0-9_-]{1,64}`.
- Errors:
  - Most errors are `{"detail": "<human readable string>"}` (`ErrorResponse`).
  - 422 request-validation errors keep FastAPI's default shape, `{"detail": [{loc, msg, type}, ...]}`.
  - Error messages never contain secrets, API keys or raw upstream payloads.

---

## 3. Users and identity (no auth)

- Seeded users, read-only in this POC:
  - `{"id":"admin","name":"Admin","email":"admin@example.org","role":"admin"}`
  - `{"id":"analyst","name":"Demo Analyst","email":"analyst@example.org","role":"analyst"}`
- Every request may send the `X-User-Id` header. If it is absent, the acting user is `admin` (`DEFAULT_USER_ID`). An unknown id returns `401 {"detail":"Unknown user '<id>'"}`.
- Permissions:
  - `admin` can do everything.
  - `analyst` can list and read all briefings and create briefings, but can only **review** or **delete** briefings where `created_by == self`. Otherwise the API returns 403.
- The web app keeps the chosen user in `localStorage` and sends it as `X-User-Id`. A user switcher sits in the header.

---

## 4. REST API

Base URL: `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8080`). CORS allows `CORS_ORIGINS`.

| Method and path | Request | Success | Errors |
|---|---|---|---|
| `GET /api/health` | none | 200 `HealthResponse` | none |
| `GET /api/users` | none | 200 `User[]` | none |
| `GET /api/me` | `X-User-Id?` | 200 `User` | 401 |
| `GET /api/conditions/suggest?q=` | `q` (any length; under 2 characters returns `[]`) | 200 `ConditionSuggestion[]` (at most 10) | none (upstream failures return `[]`) |
| `GET /api/replay/conditions` | none | 200 `ReplayManifest[]` (sorted by label; `[]` if there are no fixtures) | none |
| `POST /api/briefings` | `CreateBriefingRequest` | **202** `Briefing` (`status="researching"`), header `Location: /api/briefings/{id}` | 400 (replay mode with no matching fixture), 401, 422, 429 (run limits, with `Retry-After`) |
| `GET /api/briefings?created_by=&status=` | optional filters | 200 `BriefingSummary[]`, newest first | 401 |
| `GET /api/briefings/{id}` | none | 200 `Briefing` | 404 |
| `GET /api/briefings/{id}/events` | `Last-Event-ID?` header or `?after_seq=` | 200 `text/event-stream` of `JobEvent` (section 5) | 404 |
| `POST /api/briefings/{id}/review` | `ReviewSubmission` | **202** `Briefing` (`status="generating_report"`) | 400, 401, 403, 404, 409, 422 |
| `POST /api/briefings/{id}/retry` | none | **202** `Briefing` (`researching` or `generating_report`), or 202 `awaiting_review` if the checkpoint is paused at review | 401, 403, 404, 409 (not failed, already running, or no checkpoint), 429 |
| `DELETE /api/briefings/{id}` | none | **204** | 401, 403, 404 |

Endpoint details:

- **`GET /api/conditions/suggest`**:
  - `DATA_MODE=live`: uses the NLM Clinical Tables conditions API (`source="clinical_tables"`, `code` = first ICD-10-CM code).
  - `DATA_MODE=replay`: matches `q` against manifest labels and aliases (`source="replay"`, `code=null`).
- **`POST /api/briefings`**:
  1. Creates the Briefing. `run.steps` holds every `NodeName` with status `pending`. `audit_log` gets `briefing_created`.
  2. Persists it and emits JobEvent `run/started`.
  3. Starts the graph as a background `asyncio` task and returns immediately.
  4. In replay mode, `condition` must match a fixture: case-insensitive and whitespace-normalised against `slug`, `label` or any `aliases` entry. Otherwise the API returns 400 with the available labels.
- **`POST /api/briefings/{id}/review`** checks run in this order:
  1. 404 if the briefing does not exist.
  2. 403 if the acting user lacks permission.
  3. 409 if `status != "awaiting_review"`.
  4. 400 for any of the following:
     - `selected_option_ids` is empty.
     - An option id is unknown.
     - A conflict has no resolution, has duplicate resolutions, or is unknown.
     - `accepted_source_id` is not one of that conflict's `positions[].source_id`.
     - A decision differs from `suggested_resolution` and `note` is blank (overrides need a reason).
  4b. 409 if the LangGraph checkpoint is not paused at `human_review` ("checkpoint lost"). Resuming an empty
     thread would silently re-run the graph from START with empty state.
  5. The API builds `ReviewDecision` with `resolved_by` and `reviewed_by` set to the acting user, and `resolved_at` and `reviewed_at` set to now.
  6. It sets `status="generating_report"`, persists, and emits `human_review/completed`.
  7. It resumes the graph in the background with `Command(resume=decision.model_dump(mode="json"))` and returns 202.
- **Run limits (no auth, so cost guards):** 429 when `MAX_ACTIVE_RUNS` runs are active, when the user already has
  `MAX_ACTIVE_RUNS_PER_USER`, or when the per-user token bucket (`CREATE_RATE_PER_MINUTE`, burst `CREATE_BURST`) is empty.
- **`POST /api/briefings/{id}/retry`:** resumes a `failed` run with `ainvoke(None)` from its last checkpoint (the node
  that failed or was interrupted). The review is never repeated: a failure in `write_report` resumes at `write_report`.
- **`DELETE /api/briefings/{id}`**:
  - Cancels a running task if there is one, and emits `run/failed` ("Briefing deleted") so open streams close.
  - Deletes the briefing, its events and its checkpoint thread (`await checkpointer.adelete_thread(id)`).

---

## 5. Server-Sent Events: `GET /api/briefings/{id}/events`

- Each message has the format `id: <seq>\ndata: <JobEvent JSON>\n\n` and uses the default event type, so `EventSource.onmessage` receives it. The server sends a `: ping` comment every 15 seconds.
- The server first **replays the stored history**: all events with `seq > after_seq`, where `after_seq` comes from `Last-Event-ID` or the query parameter and defaults to 0. It then streams live events.
- **Close rule:**
  - If the briefing status is `awaiting_review`, `completed` or `failed` once the history has been sent, the server closes the stream.
  - Otherwise it stays live until it sends an event with status `awaiting_review` or `failed`, or the event `step="run", status="completed"`.
  - After the user submits a review, the client opens a new stream with `?after_seq=<last seen>` to follow report generation.
- `seq` starts at 1 and strictly increases per briefing. Events are persisted before they are published.

Expected event sequence. `progress` events are optional, and `data` is free-form:

```
run/started
normalize_condition/started  -> completed   (data: {label, mesh_id})
retrieve_sources/started -> progress (data: {connector, count}) ... -> completed (data: {count})
extract_treatments/started -> progress (data: {source_id, treatments}) ... -> completed
consolidate_options/started -> completed (data: {options})
detect_conflicts/started -> completed (data: {conflicts})
suggest_relevance/started -> completed (data: {suggested})
human_review/awaiting_review              <- stream closes here
--- POST /review ---
human_review/completed (message: "Review submitted by <user>")
write_report/started -> completed
run/completed                             <- stream closes here
```

On error, the failing node emits `<node>/failed`, then the runner emits `run/failed` with `message = briefing.error`.

---

## 6. Briefing status state machine

```
           POST /briefings
                 |
            researching ----------------------------> failed
                 | graph pauses at human_review interrupt   ^
                 v                                          |
          awaiting_review  (survives restarts: checkpoint)  |
                 | POST /review (valid)                     |
                 v                                          |
         generating_report -------------------------------->|
                 |
                 v
             completed
```

- `research_started_at` is set when `normalize_condition` starts.
- `research_completed_at` is set when `suggest_relevance` completes.
- `reviewed_by` and `reviewed_at` are set on review.
- `updated_at` is set on every persist.
- **Startup recovery:** for briefings left in `researching` or `generating_report`:
  - if the checkpoint is paused at `human_review` (crash between the interrupt and the status change), the briefing
    goes back to `awaiting_review` with the matching event;
  - otherwise it changes to `failed` through the event bus (so the stream history ends with `run/failed`) with
    `error="Interrupted by server restart; use Retry to resume from the last checkpoint"`.
  Briefings in `awaiting_review` stay resumable, because the LangGraph checkpoint is in SQLite.
- `AgentStep` mirrors node progress:
  - `pending` → `running` → `completed`, `failed` or `skipped`.
  - `human_review` is `running` while the briefing awaits review and `completed` once the review is submitted.
  - `detail` holds a short human summary, such as `"9 sources (8 PubMed, 1 MedlinePlus)"`.

---

## 7. Agent graph (LangGraph 1.x)

```
START -> normalize_condition -> retrieve_sources -> extract_treatments -> consolidate_options
      -> detect_conflicts -> suggest_relevance -> human_review (interrupt) -> write_report -> END
```

**Graph mechanics:**

- `StateGraph` with a `TypedDict` state that holds JSON-able dicts (pydantic `model_dump(mode="json")`), for example `briefing_id`, `fixture_slug`, `condition`, `region`, `sources`, `extractions`, `options`, `conflicts`, `review` and `report`.
- Checkpointer: `AsyncSqliteSaver` (`langgraph-checkpoint-sqlite`) at `DATA_DIR/checkpoints.db`. `thread_id` = briefing id.
- After each node the runner (or the node) persists the updated `Briefing` and emits events. Nodes receive an injected context with the store, the event emitter, the LLM client, connectors and settings. Use a closure or `functools.partial`, not global state.
- Pause detection: after `await graph.ainvoke(...)`, call `snap = await graph.aget_state(config)`. If `snap.next == ("human_review",)`, set `status="awaiting_review"` and emit `human_review/awaiting_review`. The **runner** does this, not the node, because a node re-executes from its start when resumed.
- Resume: `await graph.ainvoke(Command(resume=review_decision_dict), config)`.
- Concurrency inside a node uses `asyncio.gather`, bounded by `asyncio.Semaphore(LLM_MAX_CONCURRENCY)`.

### 7.1 Nodes

| Node | LLM? | Does |
|---|---|---|
| `normalize_condition` | no | **Live** (`connectors/mesh.py`): 1. MeSH lookup `match=exact` (case-insensitive). 2. NCBI `esearch db=mesh`: the first `"<heading>"[MeSH Terms]` of the query translation (maps synonyms such as "type 2 diabetes" or "COPD"), resolved with an exact lookup. 3. `startswith`, then `contains`, preferring labels that start with the query, then the shortest. `label` = MeSH label, `mesh_id` = descriptor UI. If nothing is found, `label = input` (title-cased if all lowercase) and `mesh_id=null`, and PubMed searches `[Title/Abstract]`. The method used is reported in `search_strategy.normalisation`. **Replay:** load `condition.json`, and set `input` to what the user typed. |
| `retrieve_sources` | no | Run the connectors in parallel (section 8). Dedupe by id and keep at most `MAX_SOURCES`. Fails if 0 sources are found. If one connector fails, emit a `progress` warning (error class and HTTP status only, never a URL) and continue. Sets `Briefing.search_strategy`. **Replay:** load `sources.json` unchanged, including `retrieved_at`. |
| `extract_treatments` | yes, lite, one call per source (`item_key = source.id`) | Produces `ExtractTreatmentsOutput`. If `Source.issuing_body` is null it is filled only when the name appears in the source's title or excerpt; a null `region` is filled with `region_inferred=true`. If a source fails, emit `progress` (`skipped`) and continue. The node fails only if every source fails. |
| `consolidate_options` | yes, main | The input lists every extracted treatment with ref `"<source_id>#<index>"` → `ConsolidateOptionsOutput`. Deterministic post-processing is in section 7.2. |
| `detect_conflicts` | yes, main | The input is the options plus their evidence, with source dates and tiers → `DetectConflictsOutput`. Deterministic validation and `suggested_resolution` are in section 7.3. Zero conflicts is valid. |
| `suggest_relevance` | yes, lite | The input is condition, region and options → `SuggestRelevanceOutput`. Sets `suggested`, `suggestion_reason`, and `selected = suggested`. An option missing from the output gets `suggested=false` with reason `"No suggestion returned by model"`. Unknown ids are ignored. |
| `human_review` | no | `decision = interrupt({"kind": "human_review", "briefing_id": id}, response_schema=ReviewDecision)` (validated on resume). Applies `ReviewDecision`: sets `option.selected`, `conflict.resolution`, and `briefing.reviewed_by` / `reviewed_at`. Appends audit entries: one `review_submitted`, one `option_selected` or `option_excluded` per option, and one `conflict_resolved` per conflict. |
| `write_report` | yes, main | Section 7.4. Sets `status="completed"`, appends `report_generated` to the audit log, and emits `run/completed`. |

Failure rules:

- If a node raises, the briefing changes to `status="failed"`, the step changes to `failed`, and `error` gets a one-line message.
- If consolidation yields 0 options, the run fails with `"No treatment options could be extracted from the retrieved sources"`.

### 7.2 Reliability tiers, grounding and confidence (deterministic, in `policy.py`)

**Reliability tiers** are assigned by the connector, never by the LLM. 1 is the most reliable.

| Tier | When | `source_type` |
|---|---|---|
| 1 | PubMed publication type `Practice Guideline` or `Guideline`; or (when not SR/MA) a title naming a guidance document (guideline, guidance / consensus / position / scientific statement, standards of care) or a known guideline body together with recommendations / statement / update | `clinical_guideline` |
| 2 | PubMed `Systematic Review` or `Meta-Analysis` (and not tier 1 by publication type) | `systematic_review` |
| 3 | MedlinePlus health topic (NLM-curated consumer summary) | `consumer_health_summary` |
| 4 | Anything else | `other` |

`tier_rationale` names the rule that applied, for example `"Rule: PubMed publication type 'Practice Guideline'"` or `"Rule: title identifies a guidance document ('Guidance Statement'); PubMed indexes it as 'Journal Article, Review'"`. Known limitation: tiers come from publication metadata, not an appraisal of quality.

**Grounding** uses `llm_outputs.is_grounded(quote, source.excerpt)`:

- It applies NFKC normalisation, removes Unicode format characters (soft hyphen, zero-width space), unifies quotes, dashes, spaces and `≥`/`≤`, and collapses whitespace.
- It is a case-sensitive substring check, and the quote must have at least 5 words or 30 characters.
- Grounding proves where a quote came from. It does not prove that the paraphrased `statement` follows from it (no entailment check).
- It sets `Evidence.grounded`, `TreatmentMilestone.grounded` and `ConflictPosition.grounded`.
- Ungrounded items are **kept and shown with a warning**. They are never silently dropped.

**Building options from `ConsolidateOptionsOutput`:**

- Evidence is the concatenation of `ExtractedEvidence` from each valid `member_refs` entry, with `source_id` taken from the ref. Milestones are built the same way. A milestone with an invalid date is dropped.
- Invalid refs are ignored. An option with no valid refs is dropped.
- Any extracted treatment referenced by no option becomes its own option, so nothing is silently lost:
  - `id` = `opt-` + slug of its name.
  - `confidence` = `low` before capping.
- Duplicate ids get `-2`, `-3` and so on.

**Confidence:**

- Start from the LLM's proposed confidence, then apply a cap:
  - The cap is `high` if grounded evidence comes from at least two distinct tier 1-2 sources ("multiple higher-tier sources agree").
  - It is `medium` if there is any other grounded evidence.
  - It is `low` if there is no grounded evidence.
- `confidence = min(proposed, cap)`.
- Then, if any evidence item is ungrounded and the confidence is above `low`, lower it by one more level.
- A ref is used by at most one option (the first that lists it), so evidence is never duplicated across options.

**Recommendation direction** (`recommendation_direction`, from the stances of grounded evidence, or all evidence if none is grounded): `against` and (`recommended` or `conditional`) → `mixed`; only `recommended_against` → `against`; any `recommended` → `for`; only `conditional` → `conditional`; else `not_stated`.

### 7.3 Conflicts and suggested-resolution policy

**Validation:**

- Drop positions whose `source_id` is unknown; keep one position per source.
- Drop the conflict if fewer than 2 distinct sources remain.
- Renumber `side` 1..n. If the model put every position on one side, each source gets its own side.
- Drop unknown option ids.
- Dedupe conflict ids.
- Fill `published_at` and `reliability_tier` from the Source.
- Compute `grounded` for each position.

**`suggested_resolution`** is computed deterministically in `policy.py`, never by the LLM. The *effective date* of a position is the source's `updated_at`, or its `published_at` if there is no update date. A null date counts as the oldest.

1. `regional_variation`: if exactly one position's source `region` equals the briefing `region`, the decision is `accept_source` for that source. Otherwise it is `accept_both_with_context`.
2. `population_difference`: the decision is `accept_both_with_context`.
3. `contradiction` or `outdated_guidance`: sources on the same side are never compared with each other. The best source of each side (lowest tier, then latest effective date) represents the side, and the two best sides are compared:
   - The lower tier wins (`rule="higher_tier"`).
   - On a tier tie, the later date wins (`more_recent_same_tier`). Dates compare at their common precision, so `2020-06` vs `2020-06-15` is a tie.
   - On a full tie, the source matching the briefing region wins (`region_tiebreak`); otherwise `accept_both_with_context` (`tie`).
   - `regional_variation` uses `regional_match` / `regional_context`; `population_difference` uses `population_context`.

`rationale` is a templated sentence that cites the rule, for example `"Rule (higher tier): position 1: tier 1 clinical guideline (2025-05-25), with 1 more source(s) agreeing outranks position 2: tier 2 systematic review (2020-12-17)."`. The UI labels it as a rule, not an AI judgement.

**HITL:**

- The UI shows the positions side by side with their quote, source title, publisher, `published_at`, `updated_at` ("Not stated" if absent), `retrieved_at`, tier badge, tier rule and grounded flag, plus a "Newer" badge on the most recent position. It also shows `ai_assessment` (AI) and the suggestion with its rule (code).
- **Nothing is preselected.** The human must choose and confirm a decision for **every** conflict before submitting ("Use the suggestion" fills the choice but still needs Confirm).
- `custom` requires a note, and so does any decision that differs from the suggestion (enforced by the API too). `exclude_topic` means the report narrative must not discuss that topic. The topic still appears in `conflict_log`.

### 7.4 `write_report` (Gemini plus deterministic assembly)

**LLM input** (`WriteReportOutput`):

- Condition label and region.
- **Only selected options**: name, category, line, population, summary, and grounded evidence statements tagged with source short name, tier and date.
- **Only resolved conflicts**, with their decision and note. `exclude_topic` conflicts are listed as "do not discuss".
- The research date.

The system prompt forbids advice to individuals and any content that is not supported by the inputs.

**Deterministic assembly of `Report`:**

- `treatment_options`: the selected options, ordered by `line_of_therapy` (first_line, second_line, add_on, alternative, unspecified), then by confidence (high to low), then by name.
- `sources`: every source referenced by:
  - the selected options' evidence and milestones,
  - every `conflict_log` position, and
  - every timeline event.

  They are ordered by tier ascending, then `published_at` descending.
- `conflict_log`: all conflicts, each with its resolution.
- `audit_log`: the briefing audit log, including `report_generated`.
- `research_conducted_at` = `max(source.retrieved_at)` over all briefing sources, which is the evidence snapshot time. In replay mode this is the recording time, which is the honest value; the UI labels it "Evidence snapshot recorded".
- `research_started_at` / `research_completed_at`: when this briefing's run started and finished its research steps.
- `search_strategy`: copied from the briefing ("Scope & method").
- `excluded_options`: every option the reviewer left out, with the AI suggestion and who excluded it.
- `generated_by` = the reviewer.
- `model` = the model id used by `write_report` (`"replay"` under the replay provider).
- `llm_provider`, `data_mode` and `disclaimer = DISCLAIMER`.

**Timeline** (`timeline.py`, deterministic):

- **Source events:** for each report source with `published_at`, one event:
  - `kind` is `guideline_published` if `source_type == "clinical_guideline"`, otherwise `evidence_published`.
  - `id` = `tl-src-<slug(source.id)>`.
  - `label` = `"<issuing_body or publisher>: <title truncated to 80 chars>"`.
  - `source_ids=[id]`.
  - `treatment_option_ids` = the selected options that cite this source.
- **Update events:** if `updated_at` is set and differs from `published_at`, a second event with the same kind, `id` = `tl-upd-<slug>`, and a label ending in `"(updated)"`.
- **Treatment milestones:** each grounded milestone of a selected option becomes a `treatment_milestone` event with `id` = `tl-ms-<option slug>-<n>`.
- **Short labels:** each event has `short_label` (`"<acronym or short body> <year>"`, `"... upd. <year>"`, the option name for milestones, `"Research"`).
- **Research event:** exactly one `research_conducted` event (label "Evidence snapshot recorded (...)" in replay):
  - `id="tl-research"`.
  - `date` = the `research_conducted_at` date (`YYYY-MM-DD`), with `date_precision="day"`.
  - `description` = `"<N> sources retrieved (<data_mode>) between <min retrieved_at> and <max>"`.
- **Sorting:** ascending by `date` string, then by kind order (guideline, evidence, milestone). `research_conducted` is always last.

---

## 8. Connectors (`DATA_MODE=live`)

Shared rules:

- Use one `httpx.AsyncClient`, with the timeout set by `HTTP_TIMEOUT_S`.
- **Outbound allowlist:** every request, including each redirect hop, must be `https` to a known NLM host (`connectors/http.py: ALLOWED_HOSTS`); anything else raises before it is sent (SSRF guard).
- Retry up to 3 times with exponential backoff and jitter on 429, 5xx and transport errors; `Retry-After` (seconds, capped at 30) is honoured on 429/503.
- Per-host rate limits: NCBI 3/s (10 with `NCBI_API_KEY`, shared by PubMed and the MeSH entry-term search), MedlinePlus 1.2/s (85/min/IP), MeSH lookup and Clinical Tables 5/s. Autocomplete results are cached for 10 minutes.
- Response bodies are streamed with an 8 MB cap.
- Always send `User-Agent: health-briefing-poc`.
- Never log API keys: httpx/httpcore request logging is set to WARNING, our own log lines are redacted, and failures are re-raised as `UpstreamError("HTTP <code> from <host><path>")` without the query string.

### PubMed (NCBI E-utilities)

**Search:**

- `esearch.fcgi?db=pubmed&retmode=json&sort=relevance&retmax=N&term=...&tool=$NCBI_TOOL&email=$NCBI_EMAIL[&api_key=...]`.
- Run two searches:
  - **Guidelines:** `(<C>) AND (Practice Guideline[pt] OR Guideline[pt]) AND ("<Y-PUBMED_YEARS>"[dp] : "3000"[dp]) AND English[la] AND hasabstract`, with `N = PUBMED_GUIDELINE_MAX`.
  - **Reviews:** `(<C>) AND (Systematic Review[pt] OR Meta-Analysis[pt]) AND (therapy OR treatment OR management) AND (same date, language and abstract filters)`, with `N = PUBMED_REVIEW_MAX`.
- `<C>` is `"<mesh label>"[MeSH Major Topic]` when `mesh_id` is set, otherwise `"<label>"[Title/Abstract]`. Quotes and square brackets are stripped from the label first.

**Fetch:** `efetch.fcgi?db=pubmed&retmode=xml&id=<comma ids>`, parsed with `xml.etree` (or `defusedxml`).

**Field mapping:**

- `title`: `ArticleTitle`, with inner tags stripped.
- `publisher`: `Journal/Title`.
- `authors`: `"LastName Initials"`, or `CollectiveName`.
- `doi`: `ArticleId[@IdType="doi"]`.
- `url`: `https://pubmed.ncbi.nlm.nih.gov/<pmid>/`.
- `published_at`: `ArticleDate[@DateType="Electronic"]` if present, otherwise `JournalIssue/PubDate`. Month names map to numbers. For `MedlineDate`, take the year and the first month.
- `updated_at`: null. PubMed's `DateRevised` is a record-maintenance date, not a content revision.
- `excerpt`: the `AbstractText` sections joined by `"\n\n"`, each prefixed with `"<Label>: "` when it has a label.
- `region`: null. Extraction may fill it.
- Tier: from the `PublicationType` list (section 7.2).

### MedlinePlus

**Search:** `https://wsearch.nlm.nih.gov/ws/query?db=healthTopics&term=<label>&retmax=1`, parsed as XML.

**Field mapping:**

- `title`: the `title` content with HTML stripped.
- `url`: the document `url`. Documents whose URL fails the source-URL allowlist are skipped (the URL is fetched later for dates).
- `id`: `medlineplus:<url path stem>`, for example `diabetestype2`.
- `publisher`: `organizationName`, which is "National Library of Medicine".
- `excerpt`: `FullSummary` with HTML tags stripped, entities unescaped, and `<p>` boundaries turned into `"\n\n"`.
- `region`: `"US"`.
- Tier: 3.

**Dates:** the web service has none. GET the topic `url` and read `<meta name="DC.Date.Created">` into `published_at` and `<meta name="DC.Date.Modified">` into `updated_at`. If that fails, `published_at` is null.

### MeSH and Clinical Tables

- **MeSH:** see `normalize_condition`.
- **Clinical Tables:** `https://clinicaltables.nlm.nih.gov/api/conditions/v3/search?terms=<q>&maxList=10&df=primary_name,icd10cm_codes`. The response is `[total, codes, null, [[name, icd10], ...]]`.

All sources get `retrieved_at = now(UTC)` at fetch time.

---

## 9. LLM layer

**Provider selection.** Provider is `Settings.llm_provider`, resolved at startup:

- `LLM_PROVIDER=auto` (the default) resolves to:
  - `vertex` if `GOOGLE_CLOUD_PROJECT` is set,
  - otherwise `gemini_api` if `GEMINI_API_KEY` is set,
  - otherwise `replay`.
- `DATA_MODE=auto` resolves to `replay` when the provider is `replay`, and to `live` otherwise.
- `LLM_PROVIDER=replay` combined with `DATA_MODE=live` is **rejected at startup**: live sources have no recorded LLM outputs.

**Providers:**

| Provider | Client | Credentials |
|---|---|---|
| `vertex` | `genai.Client(enterprise=True, project=GOOGLE_CLOUD_PROJECT, location=GOOGLE_CLOUD_LOCATION or "global")` | ADC only, no keys (google-genai >= 2.28; `vertexai=True` is the legacy alias) |
| `gemini_api` | `genai.Client(api_key=GEMINI_API_KEY)` | The key is read from env at runtime and never logged, echoed or returned |
| `replay` | Reads `fixtures/replay/<slug>/llm/...` | none |

**Call shape** (verified against the google-genai 2.28 source):

```python
from google.genai import types
resp = await client.aio.models.generate_content(
    model=model_id,
    contents=request.prompt,
    config=types.GenerateContentConfig(
        system_instruction=request.system,
        response_mime_type="application/json",
        response_json_schema=gemini_json_schema(OutputModel),   # not response_schema
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),  # main model only
    ),
)
parsed = OutputModel.model_validate_json(resp.text)
usage = resp.usage_metadata  # prompt_token_count, candidates_token_count, thoughts_token_count
```

- Do not set `temperature`. Gemini 3.x guidance is to keep the default, and Flash-Lite ignores it.
- `gemini-3.8-flash` rejects `MINIMAL`, so use `LOW`. For the lite model, omit `thinking_config`.
- The per-call timeout is `LLM_TIMEOUT_S`.
- Retry `LLM_MAX_RETRIES` times on 429, 5xx, timeouts and JSON or pydantic validation failures. A validation retry appends the validation error to the prompt.
- `finish_reason` is checked: `SAFETY`, `BLOCKLIST`, `PROHIBITED_CONTENT`, `SPII`, `LANGUAGE` and a blocked prompt fail at once (repeating the same request cannot help); `RECITATION` retries with an instruction to keep quotes short; `MAX_TOKENS` retries with double `max_output_tokens` (`LLM_MAX_OUTPUT_TOKENS`, default 16384).
- Then raise `LLMError`, which carries the tokens of the failed attempts so they are still counted in `RunInfo`.
- `resp.model_version` is recorded in `RunInfo.model_versions`.
- Thinking level is configurable: `GEMINI_THINKING_LEVEL` (main-model steps) and `GEMINI_THINKING_LEVEL_CONFLICTS` (detect_conflicts), default `low`.
- `tokens_in = prompt_token_count`.
- `tokens_out = candidates_token_count + thoughts_token_count`.

**Models per step:** `MODEL_TIER_BY_STEP`:

- `extract_treatments` and `suggest_relevance` use `GEMINI_MODEL_LITE` (default `gemini-3.5-flash-lite`).
- The other steps use `GEMINI_MODEL` (default `gemini-3.8-flash`).

**Cost** (`llm/pricing.py`, USD per 1M tokens, checked 2026-10-03):

| Model | Input | Output | Note |
|---|---|---|---|
| `gemini-3.8-flash` | 0.75 | 3.75 | Introductory price through 2026-12-31, then 1.50 / 7.50 |
| `gemini-3.5-flash-lite` | 0.30 | 2.50 | |

Prices match by model-id prefix (so `gemini-3.8-flash-001` or `-preview` variants are priced) and by date (the introductory price switches on 2027-01-01). An unknown model costs 0 and logs a warning. The replay provider reports 0 tokens and 0 cost. `RunInfo` totals accumulate after every call.

**Prompt rules** (`prompts.py`):

- Prompts include only public source text.
- Source text is wrapped in `<source>` blocks and derived data (LLM outputs, reviewer notes) in `<data>` blocks; both are declared untrusted data, never instructions (system rule 1).
- Delimiters inside untrusted text are neutralised case-insensitively (`</SOURCE >` → `‹/SOURCE >`), and `<` is escaped as `\u003c` inside JSON payloads, so no value can close a block.
- `detect_conflicts` sees each source's issuing body and region, and code-found "stance disagreements" (same option, opposite stances) as hints.
- Prompts ask for verbatim quotes and say "use null when not stated".

---

## 10. Persistence

- `DATA_DIR/app.db` (SQLite) has two tables:
  - `briefings(id PK, created_by, status, created_at, updated_at, json)`, where `json` is `Briefing.model_dump_json()`.
  - `events(briefing_id, seq, json, PK(briefing_id, seq))`.
- `DATA_DIR/checkpoints.db` is the LangGraph checkpointer.
- Both are created on startup and are git-ignored.

---

## 11. Settings (env; `api/app/config.py`, pydantic-settings, reads `api/.env` if present)

| Var | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `auto`, `vertex`, `gemini_api` or `replay` |
| `DATA_MODE` | `auto` | `auto`, `live` or `replay` |
| `GOOGLE_CLOUD_PROJECT` | empty | Vertex project (ADC) |
| `GOOGLE_CLOUD_LOCATION` | `global` | |
| `GEMINI_API_KEY` | empty | Secret. Gemini Developer API only |
| `GEMINI_MODEL` | `gemini-3.8-flash` | |
| `GEMINI_MODEL_LITE` | `gemini-3.5-flash-lite` | |
| `LLM_TIMEOUT_S` | `90` | |
| `LLM_MAX_RETRIES` | `2` | |
| `LLM_MAX_CONCURRENCY` | `4` | |
| `LLM_MAX_OUTPUT_TOKENS` | `16384` | Doubled once on a `MAX_TOKENS` finish |
| `GEMINI_THINKING_LEVEL` | `low` | `low`, `medium` or `high` (main model) |
| `GEMINI_THINKING_LEVEL_CONFLICTS` | `low` | For `detect_conflicts` |
| `NCBI_TOOL` | `health-briefing-poc` | |
| `NCBI_EMAIL` | empty | Recommended by NCBI |
| `NCBI_API_KEY` | empty | Secret, optional. Raises the limit to 10 requests per second |
| `PUBMED_GUIDELINE_MAX` | `6` | |
| `PUBMED_REVIEW_MAX` | `6` | |
| `PUBMED_YEARS` | `6` | |
| `MAX_SOURCES` | `12` | |
| `HTTP_TIMEOUT_S` | `20` | |
| `DATA_DIR` | `./data` | Relative to `api/` |
| `FIXTURES_DIR` | `../fixtures/replay` | Relative to `api/` |
| `REPLAY_STEP_DELAY_MS` | `400` | Artificial delay per node in replay, so progress is visible |
| `RECORD_FIXTURES` | `false` | Live data only; see section 12 |
| `RECORD_OVERWRITE` | `false` | Allow a promoted recording to replace an existing fixture |
| `MAX_ACTIVE_RUNS` | `4` | 429 above this |
| `MAX_ACTIVE_RUNS_PER_USER` | `2` | 429 above this |
| `CREATE_RATE_PER_MINUTE` / `CREATE_BURST` | `6` / `3` | Per-user token bucket on `POST /api/briefings` |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated |
| `API_BASE_URL` (web) | `http://localhost:8080` | Where the Next.js server proxies `/api/*` (`NEXT_PUBLIC_API_BASE_URL` is a fallback) |

---

## 12. Implementation notes

- **`RECORD_FIXTURES`** (default `false`, `DATA_MODE=live` only): every structured output, plus `manifest.json`, `condition.json` and `sources.json`, is written to a per-briefing folder `DATA_DIR/recordings/<slug>.<briefing id>/`, never to the committed fixtures. After the run completes (report written), the folder is moved to `FIXTURES_DIR/<slug>/` only if no fixture exists there (or `RECORD_OVERWRITE=1`). Failed or concurrent runs never touch the fixtures. `recorded_with` names the provider and both model ids.
- **Single process:** the event bus, run tasks and both SQLite files live in one process. Run one worker and one instance (Cloud Run `--max-instances=1`).
- **SQLite:** `app.db` uses WAL and a 15 s busy timeout; writes are shielded from task cancellation so a cancelled run cannot leave the database locked.
- **Seeded users:** `analyst2` ("Second Analyst", role `analyst`) is seeded in addition to `admin` and `analyst`, to demonstrate the own-briefings-only rule.
- **Source dedupe:** besides id, `retrieve_sources` dedupes by normalised title, because guidelines are often co-published in several journals under different PMIDs. MedlinePlus summaries are always kept; PubMed fills the rest of `MAX_SOURCES`.
- **MeSH fallback label:** the typed text is title-cased only if it is all lowercase (so `COPD` stays `COPD`).
- **Persistence layer:** `app/db.py` (SQLAlchemy 2 async + aiosqlite, tables `users`, `briefings`, `events`) backs `app/store.py`.
- **Paths:** relative `DATA_DIR` / `FIXTURES_DIR` resolve against `api/`, not the working directory.
- **Web API URL:** the browser only calls relative `/api/*` URLs; the Next.js server proxies them to `API_BASE_URL` (default `http://localhost:8080`; a trailing `/api` is accepted). `NEXT_PUBLIC_API_BASE_URL` is honoured as a fallback. The value is baked in at `next build`, so the web Dockerfile takes it as a build argument.
- **Replay narrative caveat:** under the replay provider, `write_report.json` was recorded for the AI-suggested selection and resolutions. When the review departs from them, `write_report` prepends a "Replay note: ..." entry to `key_takeaways` saying so (the options table and conflict log always reflect the review).
