---
name: testing-qa
description: Defines the test strategy and quality gates for a Python 3.12 / FastAPI backend and a Next.js / TypeScript frontend deployed on Cloud Run - the test pyramid, test layout, fixtures and mocking boundaries, security and LLM-guardrail tests, performance tests, CI wiring, coverage targets, and how to test private Cloud Run services with an identity token. Use when planning what to test, setting up test infrastructure or CI test jobs, reviewing test quality, diagnosing flaky or silently skipped suites, or verifying a deployed service.
---

# Testing & QA

Strategy and quality gates for the whole repository. The mechanics live in two runner skills:

- **`backend-test-runner`**: pytest commands, async fixtures, database isolation, mocking HTTP and LLM clients.
- **`frontend-test-runner`**: type-check, lint, Playwright E2E, accessibility checks.

Reference files (one level deep):

- [reference/test-examples.md](reference/test-examples.md) - worked examples per pyramid layer, security and guardrail tests, data-rights tests.
- [reference/cloud-run-endpoint-testing.md](reference/cloud-run-endpoint-testing.md) - local vs deployed testing, identity tokens, impersonation, smoke tests in CI, load tests.
- [reference/ci-and-lessons.md](reference/ci-and-lessons.md) - GitHub Actions test workflow, pre-commit, and hard-won lessons about suites that look green but never ran.

## Test pyramid

| Layer | Share | Scope | Speed budget (whole layer) |
|---|---|---|---|
| Unit | ~70% | Pure domain logic, use cases with in-memory fakes, React hooks and utilities | < 5 s per service |
| Integration | ~20% | API routes through the ASGI app, real PostgreSQL (with pgvector where used), HTTP clients against mocked transports | < 30 s per service |
| E2E | ~10% | Full user journeys in a browser (Playwright) against a local stack or a preview deployment | < 5 min |

Push every check as far down the pyramid as it can go. An E2E test that fails tells you *that* something broke; a unit test tells you *what*.

## Layout

### Backend (one directory per service)

```
services/<service>/
  app/
    domain/          # entities, value objects, pure rules
    application/     # use cases, ports (Protocols)
    infrastructure/  # repositories, HTTP and LLM clients
    api/             # FastAPI routers
  tests/
    conftest.py      # env vars, engine, session, client fixtures
    unit/
    integration/
    e2e/             # optional, cross-service flows
  pyproject.toml     # [tool.pytest.ini_options], markers, coverage config
```

### Frontend

```
web/
  app/ components/ lib/
  __tests__/ or *.test.ts(x) next to the code   # unit/component (Vitest or Jest + Testing Library)
  e2e/
    playwright.config.ts
    auth.setup.ts
    specs/ helpers/
```

## What to test

### Backend

- **Domain**: every rule and invariant, including boundaries and invalid input.
- **Use cases**: orchestration with fakes for repositories and external clients; assert on outcomes and emitted events, not on call order.
- **API**: status codes, response schema, error envelope, validation errors (422), auth failures (401 vs 403), pagination.
- **Persistence**: migrations apply and roll back; queries return what the use case expects; constraints actually reject bad rows.

### Frontend

- **Units and components**: rendering per state (default, loading, error, empty), user interactions via Testing Library queries by role and label.
- **E2E**: critical journeys only (sign-in, the core workflow, payments or exports if present), plus a smoke suite over public pages and a broken-link check.
- **Accessibility**: automated axe scans on every page in the smoke suite, plus manual keyboard checks for new interactive UI.

### Security and safety (non-negotiable before shipping changes in these areas)

- **Authentication**: missing, expired, malformed and wrongly-signed tokens; pinned algorithms; `exp` / `iss` / `aud` checks.
- **Authorization**: each role against each protected route, and object-level checks (user A cannot read user B's record by changing an ID).
- **Input validation**: SQL injection and XSS payloads are rejected or safely encoded; oversized payloads are refused.
- **PII handling**: redaction or masking catches each supported entity type; logs and error responses never contain raw PII or secrets.
- **LLM guardrails**: prompt-injection attempts, disallowed-output cases and fallback behaviour when the model or guardrail times out. Design of the guardrails lives in `llm-guardrails`; quality evaluation of model output lives in `llm-evaluation`.
- **Data rights**: export returns everything the user owns; deletion removes or anonymises it across every table and store; consent records are written and honoured.

Examples for each: [reference/test-examples.md](reference/test-examples.md).

### Performance

- **Load and stress**: Locust or k6 against a staging deployment, never production. Track p50/p95/p99 latency and error rate, and watch Cloud Run instance count and cold starts while the test runs.
- **Query performance**: assert query counts on hot endpoints to catch N+1 regressions; run `EXPLAIN ANALYZE` on new queries over realistic row counts.
- **Caching**: test hit and miss paths and invalidation, not just that a cache exists.

## Fixtures and mocking boundaries

| Dependency | In unit tests | In integration tests |
|---|---|---|
| Database | In-memory fake repository | Real PostgreSQL (container) with per-test transaction rollback |
| Other internal services | Fake behind a `Protocol` | Mocked HTTP transport (`respx`) |
| LLM / Vertex AI | Fake client returning scripted replies | Same fake; real model only in opt-in, marked evaluation runs |
| Cache (Redis) | Fake | Real container when the cache behaviour is under test |
| Time | `freezegun` / `time-machine` | Same |

Rules: small focused fixtures, factory fixtures instead of shared mutable objects, no fixture that "sets up the world". Concrete fixture code is in `backend-test-runner`.

## Coverage targets

| Area | Target |
|---|---|
| Auth, authorization, PII handling, guardrails | > 90% |
| Domain and application layers | > 80% (aim for 95% on core business rules) |
| API routes | > 70% |
| UI components | > 60% |
| Config, startup, generated code | Excluded |

Coverage is a floor, not a goal. A covered line with no meaningful assertion is uncovered in practice; review assertions, not just percentages.

## Testing deployed services

Backend Cloud Run services should be private (`--no-allow-unauthenticated`). Two valid ways to exercise them:

1. **Locally (preferred during development)**: run the stack with docker-compose and call `http://localhost:<PORT>` directly, no IAM involved.
2. **Deployed (staging or production checks)**: call the service's own Cloud Run URL with a Google-signed identity token:

```bash
SERVICE_URL=$(gcloud run services describe <SERVICE> --region=<REGION> \
  --project=<PROJECT_ID> --format='value(status.url)')
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$SERVICE_URL/api/v1/health"
```

Do not test backend routes by curling the public web domain's `/api/*` paths: the frontend's server identity is the invoker there, and the extra hop hides which layer failed. Impersonation, `gcloud run services proxy`, CI smoke tests via Workload Identity Federation and load-test auth are covered in [reference/cloud-run-endpoint-testing.md](reference/cloud-run-endpoint-testing.md).

## CI integration (summary)

- Run unit and integration tests on every pull request; E2E smoke on every PR that touches `web/`; full E2E on merge or nightly.
- If jobs are path-filtered per service, add a scheduled full run so untouched suites cannot rot unseen.
- Treat "skipped" and "no tests collected" as failures for required jobs.
- Upload coverage and Playwright reports as artifacts.

Workflow template and pitfalls: [reference/ci-and-lessons.md](reference/ci-and-lessons.md).

## Best practices

1. Write the failing test first when fixing a bug; it proves the fix and prevents regression.
2. One behaviour per test, named `test_<what>_when_<condition>_should_<outcome>`.
3. Arrange-Act-Assert, with the three sections visibly separated.
4. Mock at the boundary you own (your `Protocol`), not deep inside third-party SDKs.
5. Test failure paths and edge cases, not only the happy path.
6. No sleeps; wait on conditions. No dependence on test order.
7. Keep tests fast enough to run on every save for the module you are editing.
8. Treat test code as production code: typed, linted, reviewed.
9. Re-run a new or fixed test several times (or with `pytest-randomly` / Playwright `--repeat-each`) before calling it stable.

## Diagnosing flaky tests

| Symptom | Usual cause | Fix |
|---|---|---|
| Passes alone, fails in the suite | Shared state, leaked DB rows, module-level singletons | Transaction rollback per test; reset singletons in a fixture |
| Fails only in CI | Timing, missing env var, different timezone or locale | Condition-based waits; set env in `conftest.py`; freeze time |
| `RuntimeError: ... event loop` | Mixed loop scopes or `asyncio.get_event_loop()` in sync helpers | See [reference/ci-and-lessons.md](reference/ci-and-lessons.md) |
| Playwright timeout on click | Overlay (cookie banner, toast) intercepts pointer events | Seed the dismissal state in `addInitScript`; wait for the overlay to detach |
| Different results each run against staging | Data created by other runs | Unique per-run identifiers; clean up in teardown |

## After completing a feature

1. Run the affected suites plus lint and type checks (commands in the runner skills) and report what ran and the result.
2. Note any tests skipped and why.
3. Use the `project-manager` skill to update the project's progress tracker and any feature documentation.
