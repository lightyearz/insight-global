# Decision log (standard-of-care slice)

This log records the significant decisions in the Health Briefing POC, ADR style. For each one it gives the
choice, the alternatives considered, why the choice won, and the evidence in this repository (code, tests, measured
results). [CONTRACT.md](CONTRACT.md) says *what* the system does. This file says *why*.

Status of every entry: **accepted** for the POC, as of 2026-10-03 (contract v1.1.0). Versions in use: LangGraph 1.2.12,
langgraph-checkpoint-sqlite 3.1.1, google-genai 2.28.0, FastAPI 0.142, Pydantic 2.13, Next.js 16.3, React 19.3.

Each entry uses this layout:

> **Choice** · **Alternatives** · **Why** · **Evidence** · **Revisit when**

---

## D1. Agent framework: LangGraph `StateGraph`

- **Choice:** a linear LangGraph 1.x `StateGraph` with eight nodes (`normalize_condition` → … → `write_report`). It
  runs as one background `asyncio` task per briefing, with `thread_id` = briefing id
  (`api/app/agent/graph.py`).
- **Alternatives:**
  - A hand-written async pipeline plus our own state machine and persistence.
  - A "tool-calling agent" loop, where the LLM decides which tool to call next.
  - Google ADK or another multi-agent framework.
- **Why:**
  - The work is a fixed sequence with exactly one human pause. A graph makes that sequence explicit and testable.
  - LangGraph gives three things we would otherwise build ourselves: checkpointing, `interrupt()` /
    `Command(resume=…)`, and resume after a crash.
  - An LLM-driven loop would let the model decide when research is "done". That is the wrong place for
    non-determinism in an evidence product.
  - LangGraph keeps nodes as plain async functions, so policy code stays ordinary Python that we can unit-test.
- **Evidence:**
  - `build_graph()` is about 15 lines.
  - Nodes get their dependencies through a closure (`AgentDeps`), with no globals.
  - `tests/test_restart.py` and `tests/test_lifecycle.py` exercise checkpoint resume across a simulated process
    restart, and retry of a failed step.
- **Revisit when:** later agents (epidemiology, pipeline, cost) run in parallel. Then use subgraphs or `Send` fan-out
  per agent, under one parent graph.

## D2. Human-in-the-loop with `interrupt()`, detected by the runner

- **Choice:**
  - The `human_review` node calls `interrupt({...}, response_schema=ReviewDecision)`.
  - After each `ainvoke`, the **runner** checks `aget_state().next == ("human_review",)`, sets the briefing to
    `awaiting_review` and emits the event.
  - `POST /review` validates the decision, then resumes with `Command(resume=decision)`.
- **Alternatives:**
  - End the graph at review and start a second graph for the report.
  - Have the node announce the pause itself.
  - Poll a database flag inside a node.
- **Why:**
  - `interrupt()` persists the paused state in the checkpoint. An `awaiting_review` briefing therefore survives
    restarts with no extra code.
  - On resume, the node re-executes from its start. If the node announced the pause, the announcement would be sent
    twice, so the runner does it instead.
  - `response_schema` makes LangGraph validate the resume value with Pydantic.
  - The API validates everything before resuming: unknown ids, unresolved conflicts, the source not being one of the
    positions, and an override with no note. It also checks that the checkpoint still exists. The review findings
    showed why: resuming an empty thread silently re-runs the graph from START.
- **Evidence:**
  - `app/agent/nodes/human_review.py` and `app/routers/briefings.py::submit_review`.
  - Tests:
    - `test_review_with_lost_checkpoint_is_409_not_a_silent_restart`
    - `test_restart_recovery_restores_a_paused_run_to_awaiting_review`
    - `test_awaiting_review_survives_restart_and_resumes`
  - A locked status transition turns a concurrent second submission into a 409, which the smoke flow checks.
- **Revisit when:** reviews need several reviewers or partial saves on the server. A `PATCH …/review-draft` endpoint
  would replace today's per-browser `sessionStorage` drafts.

## D3. HITL design: the human decides, the system suggests, nothing is preselected

- **Choice:**
  - **Options:** the AI pre-suggests which options to include, and the human ticks or unticks them.
  - **Conflicts:** each starts with **no decision selected**. The UI shows:
    - the positions side by side, with publication, update and retrieval dates, tier and tier rule;
    - an AI assessment of *why* the sources differ;
    - a suggestion computed by code, labelled with the rule that produced it.
  - "Use the suggestion" fills in the choice, but the human must still press Confirm.
  - Any override needs a note. The API enforces this too.
  - Every decision lands in the conflict log and the audit log, with who decided, when, and whether it followed the
    suggestion.
- **Alternatives:**
  - Preselect the suggestion, which is what the first build did.
  - Have the LLM decide and the human only approve.
  - Require a note on every decision.
- **Why:**
  - Preselection turned review into one click per conflict. In the first build's demo, 3 of 3 conflicts and 15 of 15
    options "matched the AI", submitted 3 seconds after creation. That is rubber-stamping.
  - A note on overrides keeps friction where judgement departs from the rule. Accepting the rule stays cheap.
  - The audit trail then explains every departure.
- **Evidence:**
  - `web/src/components/ConflictCard.tsx` (`emptyDraft`, `draftError`, `overridesSuggestion`).
  - The API rule in `submit_review`.
  - `web/e2e/flow.spec.ts` asserts that no radio is checked initially and that an override is blocked until a note
    is given.
- **Revisit when:** reviewers are trusted users with a formal sign-off workflow. Then require notes on all decisions,
  plus a second reviewer for overrides.

## D4. Policy in code, not in the LLM

- **Choice:** the LLM extracts, merges, detects and writes. Code decides everything that has to be auditable:
  - source tiers;
  - grounding;
  - confidence caps;
  - recommendation direction;
  - suggested conflict resolutions;
  - the timeline;
  - report assembly.

  The code lives in `app/agent/policy.py`, `timeline.py` and `nodes/write_report.py`.
- **Alternatives:** ask Gemini for tiers, confidence and the "winning" position.
- **Why:**
  - These values must be reproducible and explainable to a strategy reader.
  - A templated rule ("same tier, newer wins") can be defended in a review. A model's opinion cannot.
  - The LLM output schemas carry no field for these values, so the model cannot set them.
- **Evidence:**
  - `llm_outputs.py` has no tier, date, grounding or resolution fields.
  - `tests/test_policy.py` holds 29 rule tests, including a regression on a real fixture.
- **Revisit when:** there is an evaluated, calibrated model for evidence grading. Even then, keep the rule as the
  default and show the model's view next to it.

## D5. LLM provider abstraction; keyless Vertex AI by default

- **Choice:** one small `LLMClient` protocol (`generate(request, output_model) -> LLMResult`) with three providers:
  - `vertex`: google-genai `Client(enterprise=True, project, location)` with Application Default Credentials, so
    **no keys**.
  - `gemini_api`: the `GEMINI_API_KEY` key is a `SecretStr`, read at runtime and never logged.
  - `replay`: recorded fixtures.

  `LLM_PROVIDER=auto` chooses Vertex when `GOOGLE_CLOUD_PROJECT` is set, the API key when `GEMINI_API_KEY` is set,
  and replay otherwise.
- **Alternatives:**
  - LangChain chat-model wrappers.
  - Calling google-genai directly from the nodes.
  - Only supporting API keys.
- **Why:**
  - Health-system clients run on GCP with service accounts. Keyless ADC is the deployable path, and a key is the
    laptop path.
  - Our own interface stays tiny and makes replay a first-class provider.
  - The call shape was checked against the installed SDK source, not taken from memory:
    - `response_json_schema`, not `response_schema`;
    - `ThinkingLevel.LOW`;
    - `HttpOptions.timeout` in milliseconds;
    - the SDK does no retries by default, so ours do not double up.
- **Model split:**
  - `gemini-3.5-flash-lite` handles the cheap, parallel, per-source extraction and the relevance suggestion.
  - `gemini-3.8-flash` (thinking `LOW`) handles consolidation, conflict detection and the report.
  - Both are configurable, including the thinking level for conflict detection.
  - Prices are matched by model-id prefix and by date, because the introductory price ends 2026-12-31.
- **Robustness:**
  - `finish_reason` is handled. `SAFETY` and other blocks fail fast. `RECITATION` retries with a "short quotes"
    instruction. `MAX_TOKENS` retries with double the limit.
  - Tokens from failed attempts are still billed to the run.
- **Evidence:**
  - `app/llm/gemini.py`, `vertex.py`, `gemini_api.py` and `pricing.py`.
  - `tests/test_gemini_provider.py` uses a stub client with no network.
  - `tests/test_live_smoke.py` (`RUN_LIVE_LLM=1 pytest -m live`) sends every output schema to the real provider once.
    It has not been run here because it needs real cloud credentials.
- **Revisit when:** a second LLM vendor is needed. Add a provider; nodes do not change.

## D6. Replay fixtures keyed by step and item

- **Choice:**
  - `DATA_MODE=replay` loads `sources.json`.
  - `LLM_PROVIDER=replay` returns `llm/<step>.json`, or `llm/extract_treatments/<source>.json` for extraction.
  - It is the default when no credentials are set.
  - Two conditions are committed: type 2 diabetes and hypertension.
- **Alternatives:**
  - Cache responses by a hash of the prompt.
  - Mock the HTTP layer (VCR-style cassettes).
  - Offer no offline mode.
- **Why:**
  - The demo, CI and evaluations must run with no credentials and no network.
  - Keying by step and item, not by prompt hash, lets us change prompts without invalidating fixtures.
  - Every fixture runs through the **real** post-processing: grounding, tiers, policy, timeline and assembly. Replay
    therefore tests the deterministic half of the system end to end.
- **Recording safety** (review fix):
  - `RECORD_FIXTURES` works in live mode only.
  - It writes to `DATA_DIR/recordings/<slug>.<briefing id>/`.
  - A recording is promoted to `fixtures/replay/<slug>/` only after the report is written, and never over an
    existing fixture unless `RECORD_OVERWRITE=1`.
- **Honesty:**
  - The committed LLM outputs are hand-authored from real abstracts, and each manifest says so.
  - When a reviewer departs from the suggestions, the replay narrative gains a "Replay note".
- **Evidence:**
  - `fixtures/README.md` and `tests/test_fixtures.py`. Every fixture validates, and every quote is grounded: 101
    extraction quotes and 6 conflict positions.
  - `test_recordings_are_promoted_only_when_complete_and_never_overwrite`.
- **Revisit when:** live runs are routine. Then record real Gemini outputs and use them as regression goldens (see the
  eval plan below).

## D7. Grounding check: verbatim quotes, verified by code

- **Choice:**
  - Every evidence item, milestone and conflict position carries a verbatim `quote`.
  - `is_grounded()` normalises both the quote and the source excerpt:
    - Unicode NFKC;
    - format characters (soft hyphen, zero-width space) removed;
    - quotes, dashes, spaces and `≥`/`≤` unified;
    - whitespace collapsed.
  - It then does a case-sensitive substring check.
  - A quote needs at least 5 words or 30 characters.
  - Ungrounded items are **kept and flagged**, and they lower confidence.
- **Alternatives:**
  - Trust the model's citations.
  - Fuzzy matching or embeddings.
  - An LLM-as-judge entailment check.
  - Drop ungrounded items.
- **Why:**
  - A substring check is cheap, deterministic and explainable: "this sentence is in the abstract".
  - Fuzzy matching invites near-miss hallucinations.
  - Dropping items silently would hide model errors. Flagging them shows the errors to the reviewer.
- **Known limit:**
  - Grounding proves *where* a quote came from. It does **not** prove that the paraphrased `statement` follows from
    the quote, which would need an entailment check.
  - Asking for long verbatim spans can trigger Gemini's recitation filter. That is handled by retrying with short
    quotes (D5).
  - The structural fix is numbered sentences (`[S1]…`), where the model returns sentence ids. It is deferred because
    it changes every fixture.
- **Evidence:** `llm_outputs.is_grounded` and `tests/test_grounding.py`.

## D8. Reliability tiers from publication metadata, with the rule shown

- **Choice:**
  - **T1** is a PubMed `Practice Guideline` / `Guideline` publication type, *or* a title that identifies a guidance
    document or a known guideline body's recommendations.
  - **T2** is `Systematic Review` / `Meta-Analysis`.
  - **T3** is a MedlinePlus summary.
  - **T4** is anything else.
  - Each source stores the rule that applied (`tier_rationale`, "Rule: …"), and the UI shows it.
- **Alternatives:**
  - An LLM quality grade.
  - GRADE appraisal.
  - Journal impact factor.
- **Why:**
  - It is deterministic and transparent.
  - It needs no licensed data.
  - It is good enough to rank a guideline above a narrative review for a strategy reader.
  - The title rule exists because of a real miss: the ACP 2018 HbA1c *Guidance Statement* is indexed as "Review", so it
    sat at T4, and the conflict suggestion rested on "T1 outranks T4".
- **Known limit:** tiers say what *kind* of document a source is, not how good it is.
- **Evidence:** `policy.pubmed_tier` and `tests/test_policy.py::test_guidance_titles_are_tier_1_and_reviews_stay_tier_2`.

## D9. Conflict policy: compare *sides*, not sources

- **Choice:**
  - `detect_conflicts` (LLM) returns one position per source. Positions that give the same answer share a `side`.
  - Code then computes the suggestion. The best source of each side (lowest tier, then latest effective date)
    represents that side, and the two best sides are compared, in this order:
    1. The lower tier wins.
    2. Otherwise the later date wins, compared at the precision both dates share.
    3. Otherwise the source matching the briefing region wins.
    4. Otherwise keep both with context.
  - Regional and population conflicts have their own rules.
  - The UI labels the result as a rule, separate from the AI assessment.
- **Alternatives:**
  - Compare the top two sources overall (the first build).
  - Let the LLM pick a winner.
- **Why:**
  - Comparing the top two sources overall gave a wrong suggestion on a real fixture. In the hypertension
    "general systolic target" conflict, Hypertension Canada 2025 and ESC 2024 *agree* (both below 130 mm Hg), yet the
    rationale said one "supersedes" the other. The opposing Cochrane review was never mentioned.
  - Grouping by side fixes that by construction.
  - Comparing dates by precision stops "2020-06" losing to "2020-06-15" on string order alone.
- **Evidence:**
  - `policy.suggest_resolution` and `sides_of`.
  - Tests:
    - `test_sources_on_the_same_side_are_never_compared_with_each_other`
    - `test_hypertension_fixture_suggestions_compare_opposing_sides`
    - `test_month_only_vs_day_date_is_a_tie_not_a_win`
- **Revisit when:** conflicts span more than two answers often. Then show a ranked list of sides instead of a pairwise
  rationale.

## D10. Timeline built deterministically

- **Choice:** `app/agent/timeline.py` builds the timeline from source dates and grounded milestones:
  - guideline and evidence publication events;
  - update events;
  - treatment milestones;
  - exactly one "research conducted / evidence snapshot" event, always last.

  Each event has a short chart label (for example "ACP 2024"). The UI draws swim lanes (Guidelines, Evidence,
  Milestones) over a six-year window, with an "earlier" count, and always shows the full list below the chart.
- **Alternatives:**
  - Let the LLM write a timeline.
  - Use a charting library.
- **Why:**
  - Dates are facts from metadata. An LLM adds nothing and can invent dates.
  - Milestones come only from grounded quotes.
  - A dependency-free chart keeps the bundle small and prints cleanly.
  - The always-visible list makes the chart accessible without hover.
- **Evidence:** `tests/test_pipeline_logic.py::test_report_assembly_and_timeline` and `web/src/components/Timeline.tsx`.

## D11. Dates: three different "when"s, all shown

- **Choice:** every source records three dates:
  - `published_at`, when the source was created (partial dates allowed);
  - `updated_at`, when it was last revised, if the publisher states it;
  - `retrieved_at`, when the research fetched it.

  The report shows the evidence snapshot (`max(retrieved_at)`) and the research run start and end separately. In
  replay mode the snapshot is labelled "Evidence snapshot recorded".
- **Why:**
  - It shows when each source was created and when the research was conducted.
  - Keeping the snapshot and the run separate avoids a confusing "snapshot older than the briefing" in replay.
  - PubMed's `DateRevised` is record maintenance, not a content revision, so it is not used as `updated_at`.
- **Evidence:** `Source` in `app/schemas.py`, the MedlinePlus `DC.Date.*` parsing, and the report meta block.

## D12. Condition normalisation through MeSH, in several steps

- **Choice:** the lookup tries, in order:
  1. MeSH `match=exact`.
  2. An NCBI `esearch db=mesh` query translation, which maps entry terms and synonyms.
  3. `startswith` / `contains`, preferring labels that start with the query, then the shortest.
  4. If nothing matches, the typed text, searched in titles and abstracts.

  The method used is shown in "Scope & method".
- **Why:** the first build took the first `contains` hit, and MeSH returns hits alphabetically. Live calls showed the
  result:
  - "stroke" became "Embolic Stroke";
  - "pneumonia" became "Chlamydial Pneumonia";
  - "type 2 diabetes" and "COPD" matched nothing.
- **Evidence:** `app/connectors/mesh.py` and `tests/test_connectors.py::test_mesh_normalisation_exact_entry_term_partial_and_none`.
  The PubMed condition clause now uses `[MeSH Major Topic]`, because plain `[MeSH Terms]` pulled in unrelated
  guidelines.

## D13. Storage: SQLite (app and checkpoints) for the POC

- **Choice:**
  - `DATA_DIR/app.db`, using SQLAlchemy 2 async with aiosqlite in WAL mode, holds Briefing JSON documents and events.
  - `checkpoints.db` holds LangGraph's `AsyncSqliteSaver` checkpoints.
  - One process runs one worker.
- **Alternatives:**
  - Postgres or Cloud SQL, with the Postgres checkpointer.
  - Firestore.
  - Keeping everything in memory.
- **Why:**
  - It needs zero infrastructure for a demo and runs offline.
  - The Briefing aggregate is read and written whole, which suits document-per-row.
  - The SQLAlchemy layer and the checkpointer interface make Postgres a configuration change, not a redesign.
- **Consequences (documented):**
  - The event bus, run tasks and databases are single-process. Cloud Run must run with `--max-instances=1`.
  - Writes are shielded from task cancellation. A cancelled run used to be able to leave SQLite locked, which a
    delete-while-running test exposed.
- **Evidence:** `app/store.py::_write`, `app/db.py`, `api/Dockerfile`, and
  `tests/test_lifecycle.py::test_deleting_a_running_briefing_emits_a_terminal_event`.
- **Revisit when:** there is more than one instance or real users. Then move to Cloud SQL Postgres with the Postgres
  checkpointer, and Redis or Postgres `LISTEN` for events.

## D14. Web to API: Next.js rewrites as a same-origin proxy

- **Choice:** the browser only calls relative `/api/*` URLs. `next.config.ts` rewrites them to `API_BASE_URL`, and
  gzip is off so SSE streams are not buffered.
- **Alternatives:**
  - Browser calls to the API origin, with CORS.
  - A custom route-handler proxy.
  - A Backend-for-Frontend with auth.
- **Why:**
  - There is no CORS in the normal path.
  - SSE via `EventSource` works same-origin.
  - The API URL is a build-time setting.
  - When auth arrives, the same seam becomes a server-side proxy that attaches identity tokens (Cloud Run IAM).
- **Evidence:** `web/next.config.ts`, and `web/src/lib/api.ts`, which has an HTTP adapter and a mock adapter.
- **Revisit when:** auth is added. Then use a route handler that injects ID tokens, or a BFF.

## D15. Security posture for a public-literature POC

- **Choice:**
  - No authentication. `X-User-Id` selects a seeded user, and `admin` is the default.
  - Permissions are checked server-side: an analyst can modify only their own briefings.
  - Cost and abuse guards: 429 on active-run caps, a per-user cap, and a token bucket on create.
  - Outbound requests are restricted to an `https` allowlist of NLM hosts, checked on every redirect hop.
  - Source URLs are validated, and the UI only renders `http(s)` links (`safeHref`).
  - API keys never reach logs. httpx request logging is off, and errors carry `host + path` only.
  - Untrusted text cannot close prompt delimiters (case-insensitive neutralising, `<` escaped in JSON).
  - An AI-extracted region is marked "inferred". An issuing body is kept only if it appears in the source text.
  - No HIPAA or GDPR scope: public literature only, no PHI. A "not medical advice" disclaimer appears in the UI, the
    review step and the report, including print.
- **Evidence:** `app/connectors/http.py` and `tests/test_connectors.py`, which covers blocked hosts and schemes, a
  redirect to a metadata IP, the key never appearing in logs or errors, `Retry-After` and the body cap. Also
  `tests/test_lifecycle.py` for the 429s.

---

## Known limitations

- **Tiers** reflect document type, not quality (D8).
- **Grounding** proves provenance, not entailment (D7).
- **Live Gemini behaviour** is unverified here: recitation, schema acceptance across both backends, and token costs.
  Run `pytest -m live` with credentials.
- **Fixtures** are hand-authored from real abstracts, not recorded model output (D6).
- **Region** has no "Canada" value, so Hypertension Canada shows no region.
- **Drafts:** review drafts are stored per browser (`sessionStorage`), not shared between reviewers.

## Evaluation plan (next step)

Use the hand-authored fixtures as gold labels and run live Gemini on the same recorded sources
(`LLM_PROVIDER=vertex DATA_MODE=replay`). Measure:

- **Option recall:** the share of gold options found, matched by drug or class.
- **Grounding rate:** the share of quotes that pass `is_grounded`, per step and model.
- **Conflict precision and recall** against the gold conflicts, plus side assignment accuracy.
- **Stance accuracy** per evidence item.
- **Cost and latency** per briefing, from `RunInfo`.

Gate prompt and model changes on these numbers (a regression eval in CI against recorded live outputs).
