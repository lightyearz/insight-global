# Health Briefing (proof of concept)

Health Briefing turns a medical condition into a **structured, source-cited briefing** for a health-system
**strategy team**: service-line directors, planning analysts and strategy leads who need a defensible
picture of a clinical area before a planning decision.

An AI agent reads the public literature, a person reviews and decides, and the system writes the report.
Every statement links to a verbatim quote, every source carries its publication, update and retrieval dates
and a reliability tier, and every human decision is logged.

> **Not medical advice.** Health Briefing summarises public literature (clinical guidelines, systematic
> reviews and National Library of Medicine summaries) to support planning. It is not a clinical tool,
> it must not be used for individual patient decisions, and it handles **no patient data (no PHI)**.

| Briefing part | Status |
|---|---|
| **Standard of care now**: current treatment options, lines of therapy, where guidelines disagree | Working, end to end (this repo) |
| **Emerging treatments next**: late-stage trials, new approvals, what is likely to change practice | Planned |
| **Companies and institutions**: who is developing, sponsoring or leading in the area | Planned |

## Contents

- [Screenshots](#screenshots)
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Human in the loop](#human-in-the-loop)
- [Sources and licensing](#sources-and-licensing)
- [License](#license)
- [LLM modes](#llm-modes)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Testing](#testing)
- [Deploying](#deploying)
- [Repository layout](#repository-layout)
- [Claude Code harness](#claude-code-harness-claude)
- [Disclaimer](#disclaimer)

## Screenshots

To capture screenshots of every page from the built-in mock data, with no backend (the script uses
Playwright's Chromium: run `npx playwright install chromium` once in `web/`, or set `CHROMIUM_PATH`):

```bash
cd web && npm install && npm run dev:mock      # terminal 1: UI on http://localhost:3001
cd web && BASE_URL=http://localhost:3001 SCREENSHOT_DIR=../docs/screenshots npm run screenshots:mock   # terminal 2
```

The stakeholder deck in [`deck/`](deck/) (three animated slides plus a 60-second video, built with the
open-source HyperFrames framework) shows the same flow for a non-technical audience.

## How it works

1. **Research.** The condition is normalised with MeSH. The agent retrieves clinical guidelines and
   systematic reviews from PubMed plus the MedlinePlus summary. Gemini extracts the treatment options from each
   source with **verbatim quotes**, and a deterministic check verifies that every quote really occurs in its source.
2. **Human review.** The AI pre-suggests which options matter; the user decides which go into the report. When
   two sources disagree, both positions appear side by side with their dates and reliability tiers, together
   with an AI assessment and a rule-based suggested resolution. A person must settle every conflict.
3. **Report.** An executive summary and key takeaways, a timeline of when guidelines and evidence were published
   and when the research ran, the selected options with their evidence, a conflict log, an audit log, and every
   source with its publication date, last update and retrieval timestamp. The report page has a print stylesheet.

## Architecture

```
 Browser ──► Next.js 16 (React 19, TypeScript, Tailwind v4)
                │  server-side rewrite of /api/* (the browser only calls relative URLs)
                ▼
             FastAPI ──► LangGraph 1.x StateGraph ──► Gemini (google-genai: Vertex AI or Gemini API, structured JSON output)
                │              │
                │              └──► public NLM connectors: PubMed E-utilities, MedlinePlus, MeSH, Clinical Tables
                │
                ├── SQLite: briefings + event log (app.db)
                ├── SQLite: LangGraph checkpoints (checkpoints.db)
                └── Server-Sent Events: live step-by-step progress to the UI
```

The agent graph:

```
normalize_condition → retrieve_sources → extract_treatments → consolidate_options
  → detect_conflicts → suggest_relevance → human_review (interrupt) → write_report
```

Design choices worth knowing:

- **The LLM proposes; code decides.** Reliability tiers, grounding flags, confidence caps, suggested conflict
  resolutions, the timeline and the report assembly are deterministic (`api/app/agent/policy.py`,
  `api/app/agent/timeline.py`). Gemini only returns schema-validated JSON (Pydantic models in
  `api/app/agent/llm_outputs.py`), and invalid output is retried with the validation error.
- **Grounding.** Each quote must be a normalised, case-sensitive substring of its source excerpt. Ungrounded items
  are kept and shown with a warning (never silently dropped), and they lower the option's confidence.
- **Reliability tiers** come from the connector, never from the model: 1 = practice guideline, 2 = systematic review
  or meta-analysis, 3 = MedlinePlus (NLM-curated summary), 4 = other.
- **Durable pause.** The human-review step is a LangGraph `interrupt()` backed by a SQLite checkpointer, so a
  briefing can wait for review across API restarts and a failed report step can be retried from its checkpoint.
- **Prompt-injection hygiene.** Source text is wrapped in delimiters and labelled as untrusted data; source URLs
  are restricted to an allowlist of NLM hosts.
- **Single process by design.** The event bus, run tasks and both SQLite files live in one process; run one worker
  and one instance.

The full contract (API, data model, state machine, graph, policies, settings) is in
[`docs/CONTRACT.md`](docs/CONTRACT.md).

## Human in the loop

The review step is where the strategy team stays in control:

- **Selection.** Every extracted option arrives with its evidence, line of therapy, population and a capped
  confidence. The AI pre-selects the ones it considers relevant and says why; the reviewer keeps, adds or removes
  options. Only selected options reach the report.
- **Conflict resolution.** When sources disagree (a newer guideline against an older review, a US body against a
  European one, different populations), the UI shows both positions side by side with quote, publisher, dates,
  tier and grounding status. The suggested resolution follows a published rule (lower tier number wins, then the
  newer effective date; regional and population differences keep both with context). The reviewer must choose a
  decision for every conflict: accept one source, keep both with context, exclude the topic, or a custom decision
  with a note.
- **Audit.** Each selection, exclusion and conflict decision is written to the briefing's audit log with the
  reviewer and time, and the report carries the conflict log.

There is no authentication in this POC. Three demo users are seeded: `admin` (the default, can do everything) and
`analyst` / `analyst2`, who can create briefings but review, retry or delete only their own. The UI sends the
selected user as an `X-User-Id` header.

## Sources and licensing

- **Official public APIs only, no scraping.** NCBI E-utilities (PubMed), the MedlinePlus Health Topics web service,
  the MeSH lookup and NLM Clinical Tables. They need no keys; requests identify the app (`NCBI_TOOL`, optional
  `NCBI_EMAIL`), are rate-limited (3 requests per second to NCBI, 10 with an optional `NCBI_API_KEY`) and retried with
  backoff. Abstracts and summaries are used as published; the tool stores titles, dates, identifiers and links so
  every claim can be checked at the source.
- **Tiering and dates.** Each source records its reliability tier with a one-sentence rationale, plus three dates:
  published, last updated (when the publisher states it) and retrieved by this tool.
- **Fixtures and mocks.** `fixtures/replay/` and `web/src/mocks/` hold real public records so the app runs offline.
  MedlinePlus / NLM text is US-government public domain and is kept in full. **Journal abstracts from other
  publishers are truncated in this repository** to the sentences actually quoted as evidence (joined with ` … `),
  with title, journal, authors, PMID, DOI, dates and URL unchanged; see
  [`fixtures/README.md`](fixtures/README.md#excerpts-in-this-public-copy). Live mode always fetches the full abstract.
  The recorded LLM outputs (extracted options, conflicts, relevance suggestions and report text) and the web mocks
  are **illustrative demo data**, hand-authored from those abstracts: they are not a reviewed clinical summary.
- **ClinicalTrials.gov notice (planned "emerging treatments" agent).** That agent is designed to use the
  ClinicalTrials.gov API and openFDA. ClinicalTrials.gov data is provided by the U.S. National Library of Medicine;
  listing a study there does not mean it has been evaluated by the U.S. Federal Government, and the briefing will
  show the date each record was retrieved. openFDA data is public domain (CC0) and is not intended for clinical use.
- **Third-party code and fonts** used by the deck are vendored unmodified with their licences in
  [`deck/assets/licenses/`](deck/assets/licenses/) (HyperFrames runtime: Apache-2.0, plus the MIT/ISC packages it
  bundles; GSAP: Webflow's Standard "no charge" licence, **not** MIT; Lucide icons: ISC; Atkinson Hyperlegible Next:
  SIL OFL 1.1).
- **Attribution.** Source: PubMed and MedlinePlus, U.S. National Library of Medicine; MeSH and Clinical Tables courtesy
  of NLM. NLM does not endorse this project. NCBI's disclaimer and copyright notice:
  <https://www.ncbi.nlm.nih.gov/home/about/policies/>. Per-source licences, retrieval dates and modifications are
  listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md#3-data-sources-and-attribution).

## License

The code and documentation written for this repository are released under the [MIT licence](LICENSE)
(© The Health Briefing POC authors). Vendored libraries, the font and the public records in the fixtures and mocks
remain under their owners' terms; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## LLM modes

| `LLM_PROVIDER` | `DATA_MODE` | What happens | Credentials |
|---|---|---|---|
| `replay` | `replay` | Fully offline demo from recorded fixtures (default when nothing is configured) | none |
| `vertex` | `replay` or `live` | Gemini on Vertex AI | **Application Default Credentials**, no keys: `gcloud auth application-default login` locally, the runtime service account on Cloud Run. Set `GOOGLE_CLOUD_PROJECT`. |
| `gemini_api` | `replay` or `live` | Gemini Developer API | `GEMINI_API_KEY` from the environment only; it is never logged, echoed or returned |

- `auto` (the default for both settings) picks `vertex` if `GOOGLE_CLOUD_PROJECT` is set, else `gemini_api` if
  `GEMINI_API_KEY` is set, else `replay`; `DATA_MODE=auto` follows the provider (`replay` with replay, `live` otherwise).
- `DATA_MODE=replay` with a real model re-runs Gemini on the recorded sources, which keeps runs reproducible.
- Replay is keyed by step and item, never by a prompt hash, so prompts can change without invalidating fixtures.
- Models: `GEMINI_MODEL` (consolidation, conflicts, report) and `GEMINI_MODEL_LITE` (per-source extraction and
  relevance). Token use and an estimated cost are recorded per run.

## Quickstart

Prerequisites: Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node 20.9+ (Node 22 for the deck), and `curl`.
All commands run from the repository root.

```bash
scripts/dev.sh            # API on :8080 + web on :3000, replay mode by default (WEB_MODE=prod for a production build)
scripts/dev.sh status     # or: stop | restart | logs
```

`scripts/dev.sh` uses `bash` and `setsid` (Linux, WSL, or macOS with util-linux installed); otherwise run each
half by hand as shown below.

Open <http://localhost:3000>, choose a recorded condition (type 2 diabetes or hypertension), watch the research
steps stream in, review the options and conflicts, and read the report. `GET /api/replay/conditions` lists the
recorded conditions.

Or run each half by hand, each in its own terminal from the repository root:

```bash
# API (http://localhost:8080); replay mode when no credentials are configured
cd api && uv sync && uv run uvicorn app.main:app --port 8080 --reload

# Web (http://localhost:3000)
cd web && npm install && npm run dev
```

For a UI-only demo with no backend at all: `cd web && npm install && npm run dev:mock` (port 3001).

To use a real model, create `api/.env` (it is git-ignored) and restart:

```bash
# Gemini Developer API
printf 'LLM_PROVIDER=gemini_api\nGEMINI_API_KEY=<your-key>\nDATA_MODE=live\n' > api/.env

# or Vertex AI with Application Default Credentials (no keys; the identity needs roles/aiplatform.user)
gcloud auth application-default login
printf 'LLM_PROVIDER=vertex\nGOOGLE_CLOUD_PROJECT=<your-project>\nDATA_MODE=live\n' > api/.env

scripts/dev.sh restart && curl -s localhost:8080/api/health    # shows the active llm_provider and data_mode
```

`DATA_MODE=live` searches PubMed, MedlinePlus and MeSH live; `DATA_MODE=replay` runs Gemini on the recorded sources
of the two recorded conditions.

## Configuration

Copy [`.env.example`](.env.example) to `api/.env` (and the web part to `web/.env.local`) and fill in only what you
need. **Never commit `.env` files**; only `.env.example` is tracked.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `auto`, `vertex`, `gemini_api` or `replay` |
| `DATA_MODE` | `auto` | `auto`, `live` or `replay` |
| `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` | (none) / `global` | Vertex AI project and location (ADC) |
| `GEMINI_API_KEY` | (none) | Gemini Developer API key. Secret. |
| `GEMINI_MODEL` / `GEMINI_MODEL_LITE` | see `.env.example` | Main and lite model ids |
| `NCBI_TOOL` / `NCBI_EMAIL` / `NCBI_API_KEY` | `health-briefing-poc` / (none) / (none) | NCBI identification and optional higher rate limit (the key is secret) |
| `DATA_DIR` | `./data` | SQLite files (git-ignored) |
| `FIXTURES_DIR` | `../fixtures/replay` | Replay fixtures |
| `CORS_ORIGINS` | `http://localhost:3000` | Origins allowed to call the API |
| `API_BASE_URL` (web) | `http://localhost:8080` | Where the Next.js server proxies `/api/*` (read at build / dev start) |
| `NEXT_PUBLIC_API_MODE` (web) | `api` | `mock` runs the UI on built-in mock data |

Timeouts, retries, concurrency, PubMed limits, abuse limits and replay pacing are listed in
[`docs/CONTRACT.md` §11](docs/CONTRACT.md).

## Testing

From the repository root:

```bash
# API: unit, policy, connector (mocked HTTP), grounding, fixture-validation and end-to-end API tests
(cd api && uv run pytest)
(cd api && uv run pytest -k fixtures)          # every fixture validates and every quote is grounded
(cd api && RUN_LIVE_LLM=1 GOOGLE_CLOUD_PROJECT=<your-project> uv run pytest -m live)   # opt-in: real Gemini via ADC
(cd api && uv run ruff check . && uv run ruff format --check .)

# Web: lint, type-check, production build
(cd web && npm run lint && npm run type-check && npm run build)

# Whole stack: API smoke flow + Playwright UI flow for every recorded condition (starts the stack if needed).
# Needs a Playwright Chromium: run `npx playwright install chromium` once in web/, or set CHROMIUM_PATH.
scripts/e2e.sh
```

## Deploying

The API and web app each ship a Dockerfile (non-root, no keys baked in):

```bash
docker build -f api/Dockerfile -t health-briefing-api .                                  # from the repo root
docker build -t health-briefing-web --build-arg API_BASE_URL=http://api:8080 web/
```

Notes for **Google Cloud Run**:

- **No secrets in the repository.** On Cloud Run, Vertex AI is reached through the service's runtime service
  account (ADC); grant it only the Vertex AI user role. If you use the Gemini API instead, put the key in Secret
  Manager and mount it as `GEMINI_API_KEY`.
- **CI/CD without keys.** The repository ships no CI/CD workflows. If you add one (for example GitHub Actions),
  authenticate with **Workload Identity Federation** (OIDC) so that no service-account key file ever exists, and
  keep project ids, regions and service names in repository/environment variables, not in code.
- The API is single-process: deploy it with `--max-instances=1` and one worker, and set `FORWARDED_ALLOW_IPS='*'`
  behind Cloud Run's front end. SQLite on the container filesystem is fine for a demo but not durable; use a
  managed database and a shared checkpointer before running more than one instance.
- There is no authentication in the POC. Keep the services private (`--no-allow-unauthenticated`, with the web
  server calling the API using an identity token) or put them behind an identity-aware proxy before sharing a URL.

## Repository layout

```
api/        FastAPI + LangGraph agent (Python, uv): app/ (routers, agent graph and nodes, connectors, LLM providers), tests/
web/        Next.js UI: briefings list, new briefing, research / review / report views; mock mode and Playwright e2e
fixtures/   Recorded replay fixtures for offline runs (see fixtures/README.md)
deck/       Stakeholder deck and 60-second video (HyperFrames); see deck/README.md and deck/SPEAKER_NOTES.md
docs/       CONTRACT.md (API, data model, agent graph, policies, settings), DECISIONS.md (why, and what was rejected)
scripts/    dev.sh (start/stop the stack), e2e.sh (end-to-end checks), smoke_api.py (stdlib API flow check)
.claude/    Claude Code harness used to build this project (see below)
```

## Claude Code harness (`.claude/`)

This project was built with [Claude Code](https://docs.claude.com/en/docs/claude-code/overview), and the reusable
harness is included so others can work on it the same way. It targets the same stack (Python / FastAPI, Next.js /
TypeScript, Google Cloud and Gemini):

- **Skills** (`.claude/skills/<name>/SKILL.md`): on-demand knowledge and procedures, for example
  `ai-ml-engineering`, `llm-evaluation`, `llm-guardrails`, `llm-models-expert`, `backend-architect`,
  `backend-test-runner`, `frontend-developer`, `frontend-test-runner`, `cloud-run-deploy`, `devops-infrastructure`,
  `harness-engineering`, `project-manager` and `ui-ux-designer`. Only each skill's description is always loaded;
  bodies and `reference/` files load when needed. See [`.claude/skills/README.md`](.claude/skills/README.md).
- **Subagents** (`.claude/agents/`): focused roles with their own tools and preloaded skills, such as
  backend, frontend, Python, AI/ML, DevOps, testing/QA, UI/UX and project management.
- **Rules** (`.claude/rules/`): path-scoped conventions loaded when matching files are touched
  (`python-services.md`, `web-frontend.md`, `harness-authoring.md`).
- **Hooks** (`.claude/settings.json`, `.claude/hooks/`): a `PreToolUse` guard on shell commands
  (`guard-bash.sh`) and a `PostToolUse` sensor that formats and lints after every edit (`post-edit.sh`).
- **Scripts** (`.claude/scripts/`): `harness_lint.py` lints skills, agents, rules and hooks;
  `build_skills_index.py` regenerates the skills index.

## Disclaimer

Health Briefing is a proof of concept for **planning and research support**. It is **not medical advice** and not a
medical device. It summarises public literature only, may be incomplete or out of date, and every output must be
checked against the cited sources by a qualified person. It processes **no patient data (no PHI)**; do not enter
patient information. Trademarks and journal names belong to their owners, and the linked sources remain the
authoritative versions.
