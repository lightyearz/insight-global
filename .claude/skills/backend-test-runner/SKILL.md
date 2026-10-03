---
name: backend-test-runner
description: Runs and writes pytest suites for Python 3.12 FastAPI services - commands, pytest-asyncio configuration, typed fixtures, Arrange-Act-Assert, naming, test isolation with transaction rollback on PostgreSQL, dependency overrides, mocking HTTP and LLM (Vertex AI Gemini) clients, coverage targets, and Ruff checks afterwards. Use when running backend tests, writing or reviewing pytest code, adding fixtures or conftest.py, or fixing failing and flaky backend tests.
---

# Backend Test Runner

How to run and write pytest suites for the FastAPI services under `services/<service>/`. Overall strategy, coverage policy and CI wiring are in `testing-qa`; general Python standards are in `python-developer`.

Worked fixture code (async engine, rollback session, client with overrides, factories, `respx`, fake LLM, testcontainers) is in [reference/fixtures.md](reference/fixtures.md).

## Commands

```bash
# one service
cd services/<service> && python3 -m pytest -v --tb=short

# every service that has tests (each in its own subshell, so no cd back is needed)
for svc in services/*/; do
  [ -d "$svc/tests" ] && (cd "$svc" && python3 -m pytest -q --tb=short) || echo "FAILED: $svc"
done

# coverage with missing lines
python3 -m pytest --cov=app --cov-report=term-missing

# one file, one test, last failures first
python3 -m pytest tests/unit/test_billing.py -k "renewal" -v
python3 -m pytest --lf -x

# the default CI selection: skip heavy model, live-LLM and deployed smoke tests
python3 -m pytest -m "not model_loaded and not live_llm and not smoke"

# lint and format what you touched (run from the repo root so CI's config applies)
python3 -m ruff check --fix <paths> && python3 -m ruff format <paths>
```

## Configuration

```toml
# services/<service>/pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"                          # async tests and fixtures need no decorator
asyncio_default_fixture_loop_scope = "function"
addopts = "--strict-markers -ra"
markers = [
  "integration: needs a real database or container",
  "model_loaded: loads real ML model weights (slow, skipped in CI)",
  "live_llm: calls a real model endpoint (opt-in, costs money)",
  "smoke: runs against a deployed service",
]

[tool.coverage.run]
source = ["app"]
omit = ["app/main.py", "app/config.py"]
```

With `asyncio_mode = "strict"` instead, async fixtures need `@pytest_asyncio.fixture` and tests need `@pytest.mark.asyncio`. Pick one mode per repository.

Set environment variables at the top of `tests/conftest.py`, before anything imports the app, because settings objects are usually built at import time:

```python
import os

os.environ.setdefault("ENV", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
os.environ.setdefault("LLM_PROVIDER", "fake")   # never reach a real model by accident
```

## Writing tests

### Type hints on everything, no `Any`

Every test, fixture and helper has full annotations, including `-> None` on tests. Use `Protocol`, `TypeVar` / PEP 695 generics, `TypedDict` or `Callable[..., Awaitable[T]]` instead of `Any`.

```python
UserFactory = Callable[..., Awaitable[User]]

@pytest.fixture
def make_user(db_session: AsyncSession) -> UserFactory:
    async def _make(email: str | None = None, role: Role = Role.MEMBER) -> User:
        ...
    return _make
```

### Naming: `test_<what>_when_<condition>_should_<outcome>`

```
test_login_when_password_invalid_should_return_401
test_invoice_when_payment_fails_should_stay_unpaid
test_session_when_token_expired_should_require_reauth
test_search_when_query_empty_should_return_422
```

### Arrange-Act-Assert

```python
async def test_create_document_when_payload_valid_should_return_201(
    client: AsyncClient, member_headers: dict[str, str]
) -> None:
    # Arrange
    payload = {"title": DOC_TITLE, "body": DOC_BODY}

    # Act
    response = await client.post("/api/v1/documents", json=payload, headers=member_headers)

    # Assert
    assert response.status_code == 201
    assert response.json()["title"] == DOC_TITLE
```

### No magic values

Name the values the test depends on (`MAX_UPLOAD_MB = 10`, `TRIAL_DAYS = 14`, `DOC_TITLE = "Quarterly plan"`) or import the production constant. A bare `assert body["limit"] == 180` says nothing about why 180.

### SOLID applied to tests

| Principle | In test code |
|---|---|
| Single responsibility | One behaviour per test; several asserts are fine if they describe that one behaviour |
| Open/closed | Add a new fixture rather than adding flags to a shared one |
| Liskov | Shared contract tests (parametrised over implementations) must pass for every implementation of a port |
| Interface segregation | Small fixtures composed together; no fixture that builds the whole world |
| Dependency inversion | Inject fakes via fixtures and `app.dependency_overrides`; do not patch module globals |

### Isolation

- Each test runs inside a transaction that is rolled back afterwards (pattern in the reference file).
- Factories create fresh, unique data (`uuid4()` in emails and names); no shared mutable module-level objects.
- Never rely on execution order; `pytest-randomly` will expose it.
- Reset `app.dependency_overrides` in fixture teardown.
- `httpx.ASGITransport` does not run the app's lifespan; if startup state matters, wrap the app in `asgi_lifespan.LifespanManager`.

## Mocking strategy

| Dependency | Approach | Why |
|---|---|---|
| LLM APIs (Vertex AI Gemini, others) | Fake implementing your `LLMClient` protocol | Deterministic, free, no network |
| Database | Real PostgreSQL (pgvector image if you use vectors) with rollback | Mocks hide SQL and constraint bugs |
| Other internal services | `respx` (or `pytest-httpx`) on the `httpx` client | Tests the real request building and error handling |
| Google Cloud clients (Secret Manager, Storage) | Fake behind a protocol; never real ADC in unit tests | Tests must pass on a laptop with no credentials |
| Redis | Fake for unit tests, container for integration | |
| Time | `freezegun` or `time-machine` | No `time.sleep()`, no wall-clock flakiness |

Mock at the boundary you own. Patching deep inside an SDK couples the test to SDK internals and breaks on upgrades.

## Critical paths (tests required before shipping a change)

- Authentication and token validation, role-based and object-level authorization.
- PII redaction and anything that writes user content to logs.
- LLM guardrails: input and output filters, fail-closed behaviour on timeout (see `llm-guardrails`).
- Data export and deletion completeness, consent recording.
- Money movement, if any: idempotency and failure rollback.

Examples for each are in the `testing-qa` skill's reference.

## Anti-patterns

- Testing implementation details (private methods, call order) instead of behaviour.
- Mocking everything, including the database, so no real query ever runs.
- Tests without assertions, or asserting only `status_code == 200`.
- `time.sleep()` or polling loops without a deadline.
- God fixtures, `autouse` fixtures that do expensive work for every test.
- `asyncio.get_event_loop()` in sync helpers (see `testing-qa` reference `ci-and-lessons.md`).
- Catching broad exceptions in tests, or `pytest.raises(Exception)`.

## After running tests

1. All selected tests pass; note anything skipped and why.
2. `ruff check` and `ruff format` are clean for the files you touched.
3. No new `Any` annotations.
4. Coverage on critical paths did not drop.
5. New or fixed tests pass on repeated runs in random order (`pytest-randomly` installed, or `pytest --count=5` with `pytest-repeat`).
