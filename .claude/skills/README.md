# Claude Code harness: skills, agents, rules, and hooks

This directory holds the reusable knowledge Claude Code loads while working in this repo. The stack it targets: Python 3.12 + FastAPI services, a Next.js / React / TypeScript / Tailwind front end, and Google Cloud (Cloud Run, Cloud SQL with pgvector, Vertex AI Gemini through Application Default Credentials, Secret Manager), deployed from GitHub Actions with Workload Identity Federation.

At session start Claude sees only each skill's `name` and `description`. The body of `SKILL.md` loads when the skill is invoked, and files under `reference/` load only when read. That is why descriptions must say *when* to use a skill and why bodies stay under 500 lines.

## Layout

```
CLAUDE.md                     always-on instructions (short: pointers and non-negotiables)
.claude/
  settings.json               hook wiring + a small permission allowlist (shared)
  settings.local.json         personal overrides (not committed)
  hooks/
    guard-bash.sh             PreToolUse guard for Bash commands
    post-edit.sh              PostToolUse sensor for Edit/Write
  rules/<topic>.md            path-scoped rules, loaded when a matching file is touched
  skills/<name>/SKILL.md      on-demand knowledge and procedures
  skills/<name>/reference/    long tables and catalogues, one level deep
  agents/<name>.md            subagents: a role, a tool set, and preloaded skills
  scripts/
    harness_lint.py           lints skills, agents, rules, hooks, CLAUDE.md
    build_skills_index.py     regenerates the index at the bottom of this file
```

## How the layers load

| Layer | Where | Loaded | Use it for |
|---|---|---|---|
| Always-on instructions | `CLAUDE.md` | every session | what is true for every task |
| Path-scoped rules | `.claude/rules/*.md` with `paths:` | when a matching file is read or edited | conventions for one part of the tree, e.g. `harness-authoring.md` for `.claude/**` |
| Skills | `.claude/skills/<name>/` | description always; body on invocation | domain knowledge, procedures, reading lists |
| Subagents | `.claude/agents/<name>.md` | description always; body when spawned | isolated implementation or review work with a fresh context |
| Hooks | `.claude/settings.json` + `.claude/hooks/` | on the event, whatever the model decides | guards that must never be skipped, sensors that report after every edit |

The method behind this layout, the audit checklist, and the reading list are in the `harness-engineering` skill.

## Principles

- **Descriptions are the trigger.** Third person, what it does and when to use it, under 1,024 characters.
- **Progressive disclosure.** Overview and workflow in `SKILL.md`; tables, catalogues, and long references in `reference/<topic>.md`, linked one level deep, with a `## Contents` list when over 100 lines.
- **Agents carry the role, skills carry the knowledge.** An agent preloads the small skills it always needs with `skills:` in its frontmatter and reads the rest on demand.
- **Placeholders, never real identifiers.** This harness is public: use `<PROJECT_ID>`, `<REGION>`, `<SERVICE>`, `<AR_REPO>`; no keys, service URLs, personal names, or local paths. The lint enforces the obvious cases.
- **Guards over sentences.** If something must never happen, it is a hook rule, not a paragraph.
- **Retire, do not delete.** A retired skill keeps a notice at the top and is tagged in the index; knowledge about a removed integration still helps migrations and audits.

## Agents

| Agent | Use it for |
|---|---|
| `python-developer` | Writing, refactoring, and reviewing Python code to the house standards |
| `backend-developer` | Implementing FastAPI services: routes, schemas, persistence, migrations, tests |
| `frontend-developer` | Building Next.js / React / TypeScript / Tailwind pages and components |
| `ui-ux-designer` | Designing and reviewing UI: tokens, component states, accessibility, dashboards |
| `testing-qa` | Test strategy, writing tests, diagnosing failing or flaky suites |
| `ai-ml-engineering` | LLM features on Vertex AI Gemini: prompts, structured output, embeddings and retrieval |
| `devops-infrastructure` | Cloud Run, Cloud SQL, Secret Manager, IAM, and GitHub Actions CI/CD |
| `project-manager` | Plans, checklists, status reports, and keeping docs consistent |

## Hooks

- `guard-bash.sh` (PreToolUse, `Bash`) denies, with a reason and the safe alternative: making a Cloud Run service public (`--allow-unauthenticated`, `allUsers` bindings), force-pushing `main`/`master`, printing Secret Manager values into the transcript, reading `.env` files, private keys, or service-account key files, committing secret files, and force-adding `.claude/` or the whole tree past the ignore rules.
- `post-edit.sh` (PostToolUse, `Edit|Write`) runs ruff on Python files, eslint on `web/**/*.ts(x)`, and `harness_lint.py` on harness files. It never blocks; leftover findings are handed back to Claude.

## Maintaining the harness

```bash
python3 .claude/scripts/harness_lint.py              # exit 1 on errors
python3 .claude/scripts/harness_lint.py --strict     # warnings fail too; run before a harness PR
python3 .claude/scripts/build_skills_index.py        # regenerate the index below from frontmatter
python3 .claude/scripts/build_skills_index.py --check
```

Adding a skill: create `.claude/skills/<name>/SKILL.md` with `name` and `description` frontmatter, add the name to `CATEGORIES` and a one-line entry to `SUMMARIES` in `build_skills_index.py`, regenerate the index, and run the lint. Adding an agent: create `.claude/agents/<name>.md`, keep the description to one or two sentences, and preload only skills that exist here.

## Skill index

<!-- BEGIN GENERATED SKILL INDEX -->

_17 skills. Regenerate this block with `.claude/scripts/build_skills_index.py`; edit frontmatter, not this table._

### Application engineering

| Skill | Use it for |
|---|---|
| `python-developer` | Python 3.12 standards: typing, Pydantic v2, SOLID layering, async correctness, config and secrets, logging, Ruff |
| `backend-architect` | FastAPI service architecture on Cloud Run: boundaries, API conventions, SQLAlchemy and Alembic, service-to-service auth |
| `frontend-developer` | Next.js App Router, React, strict TypeScript, Tailwind; calling private Cloud Run backends; chat and streaming UI |
| `ui-ux-designer` | Token-based design system, component states, WCAG 2.2 AA accessibility, dashboard patterns |

### Testing and quality

| Skill | Use it for |
|---|---|
| `testing-qa` | Test strategy and quality gates across backend and front end, CI wiring, coverage targets |
| `backend-test-runner` | Running and writing pytest suites for FastAPI services: fixtures, async tests, isolation, mocking |
| `frontend-test-runner` | Type-check, ESLint, component tests, Playwright E2E, and accessibility scans |

### AI and LLM engineering

| Skill | Use it for |
|---|---|
| `ai-ml-engineering` | Gemini on Vertex AI via ADC, prompts, structured output, embeddings and pgvector retrieval |
| `llm-models-expert` | Comparing LLM providers and models on capability, context window, and price; choosing a model |
| `llm-guardrails` | Input and output safety for LLM features: prompt injection, PII, moderation, fail-closed pipelines |
| `llm-evaluation` | Evaluating LLM features: eval sets, LLM-as-judge, regression benchmarks |
| `agentic-ai-resources` | Theory and reading list on agents: the agent loop, design patterns, tool use, MCP, JSON-RPC |

### Cloud and operations

| Skill | Use it for |
|---|---|
| `devops-infrastructure` | GCP infrastructure reference: Cloud Run, Cloud SQL, Secret Manager, IAM, GitHub Actions with WIF |
| `cloud-run-deploy` | Deploying, verifying, and rolling back Cloud Run services |
| `cloud-costs-optimization` | Analysing GCP spend and right-sizing Cloud Run, builds, and storage |

### Harness and process

| Skill | Use it for |
|---|---|
| `harness-engineering` | Improving this harness: guides vs sensors, context budget, the audit checklist, the lint and hooks |
| `project-manager` | Organising docs, tracking progress, and writing status reports |

<!-- END GENERATED SKILL INDEX -->
