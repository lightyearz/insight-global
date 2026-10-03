# Fixture patterns for FastAPI services

## Contents

- conftest.py layout
- Test database: external URL or a pgvector container
- Migrations once per session
- Engine and per-test rollback session
- HTTP client with dependency overrides
- Auth tokens and headers
- Factory fixtures
- Mocking downstream services with respx
- Fake LLM client (Vertex AI Gemini behind a protocol)
- Keeping tests off the network and off real credentials
- Freezing time

Assumes `asyncio_mode = "auto"` (see SKILL.md), SQLAlchemy 2.0 async with `asyncpg`, Alembic, `httpx`, `respx`, and optionally `testcontainers[postgres]`.

## conftest.py layout

```
tests/
  conftest.py            # env vars first, then database, client, auth, fakes
  factories.py           # optional: factory helpers imported by conftest
  unit/
  integration/
  smoke/                 # deployed checks, marked `smoke`
```

Put fixtures used by one directory in that directory's own `conftest.py`. Keep the root `conftest.py` to fixtures most tests need.

## Test database: external URL or a pgvector container

```python
import os
from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """CI provides a Postgres service container; locally, start one on demand."""
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
        yield pg.get_connection_url()
```

Use the same major PostgreSQL version as Cloud SQL, and the `pgvector` image if any migration runs `CREATE EXTENSION vector`.

## Migrations once per session

Run the real Alembic migrations rather than `metadata.create_all()`, so the tests also prove the migrations work:

```python
from alembic import command
from alembic.config import Config


@pytest.fixture(scope="session")
def migrated_url(database_url: str) -> str:
    cfg = Config("alembic.ini")                       # tests run from the service directory
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")
    return database_url
```

`env.py` must use the URL set on the config (`config.get_main_option("sqlalchemy.url")`) when present, instead of always reading application settings. The async `env.py` template calls `asyncio.run()`, which is fine here because this fixture is synchronous and runs outside any event loop.

## Engine and per-test rollback session

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool


@pytest.fixture(scope="session")
def engine(migrated_url: str) -> AsyncEngine:
    # NullPool: no connection outlives the event loop that opened it, so a
    # session-scoped engine is safe with function-scoped test loops.
    return create_async_engine(migrated_url, poolclass=NullPool)


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn,
            join_transaction_mode="create_savepoint",  # app-level commit() releases a savepoint only
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()                     # nothing the test wrote survives
```

Symptoms that point here: `got Future attached to a different loop` (pooled connection reused across loops; use `NullPool`), or rows leaking between tests (code under test opened its own session instead of using the injected one).

## HTTP client with dependency overrides

```python
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_llm_client, get_session
from app.main import app


@pytest.fixture
async def client(db_session: AsyncSession, fake_llm: "FakeLLM") -> AsyncIterator[AsyncClient]:
    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
```

`ASGITransport` does not run the lifespan. If startup builds state the routes need, wrap the app: `async with LifespanManager(app) as manager: transport = ASGITransport(app=manager.app)` (from `asgi-lifespan`). Prefer an app factory (`create_app(settings)`) over the module-level `app` when tests need different settings.

## Auth tokens and headers

```python
import time
from collections.abc import Callable

import jwt

TEST_JWT_SECRET = os.environ["JWT_SECRET"]
TokenFactory = Callable[..., str]


@pytest.fixture
def make_token() -> TokenFactory:
    def _make(
        sub: str, role: str = "member", *, expires_in: int = 300, key: str = TEST_JWT_SECRET
    ) -> str:
        now = int(time.time())
        claims = {"sub": sub, "role": role, "iat": now, "exp": now + expires_in,
                  "iss": "test-issuer", "aud": "test-audience"}
        return jwt.encode(claims, key, algorithm="HS256")
    return _make


@pytest.fixture
def auth_headers(make_token: TokenFactory) -> Callable[["UserRow"], dict[str, str]]:
    return lambda user: {"Authorization": f"Bearer {make_token(str(user.id), user.role)}"}
```

Use `expires_in=-1` for expired-token tests and a different `key` for forged-signature tests. Match `iss` / `aud` to what the test settings expect.

## Factory fixtures

```python
from collections.abc import Awaitable
from uuid import uuid4

from app.infrastructure.models import UserRow

UserFactory = Callable[..., Awaitable[UserRow]]


@pytest.fixture
def make_user(db_session: AsyncSession) -> UserFactory:
    async def _make(*, email: str | None = None, role: str = "member") -> UserRow:
        user = UserRow(
            email=email or f"user-{uuid4().hex[:8]}@example.com",
            role=role,
            password_hash="not-a-real-hash",
        )
        db_session.add(user)
        await db_session.flush()          # assigns the primary key without committing
        return user
    return _make
```

Factories take keyword overrides with sensible defaults and generate unique values, so tests stay independent and order-free.

## Mocking downstream services with respx

```python
import httpx
import respx

BILLING_URL = "http://billing.test"   # set via env in conftest so the app uses it


async def test_profile_when_billing_unavailable_should_return_partial_profile(
    client: AsyncClient, member_headers: dict[str, str], respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(f"{BILLING_URL}/api/v1/accounts/me").mock(
        return_value=httpx.Response(503)
    )

    response = await client.get("/api/v1/profile", headers=member_headers)

    assert route.called
    assert response.status_code == 200
    assert response.json()["billing"] is None
```

`respx_mock` fails the test on any unmocked outbound request and on routes that were never called. The test client's own `ASGITransport` is not intercepted. Disable service-to-service ID-token minting in tests (for example a `TokenProvider(enabled=False)` or a fake), otherwise the client tries to reach the metadata server.

## Fake LLM client (Vertex AI Gemini behind a protocol)

Production code depends on a small protocol; the Vertex AI adapter is one implementation and the fake is another.

```python
# app/application/ports.py
from typing import Protocol


class LLMClient(Protocol):
    async def generate(self, prompt: str, *, system: str | None = None) -> str: ...
```

```python
# app/infrastructure/gemini.py  (credentials come from ADC; no API key)
from google import genai
from google.genai import types


class GeminiClient:
    def __init__(self, project: str, location: str, model: str) -> None:
        self._client = genai.Client(vertexai=True, project=project, location=location)
        self._model = model

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system),
        )
        return response.text or ""
```

```python
# tests/conftest.py
from dataclasses import dataclass, field


@dataclass
class FakeLLM:
    replies: list[str] = field(default_factory=lambda: ["ok"])
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append(prompt)
        if self.error is not None:
            raise self.error
        return self.replies[min(len(self.calls), len(self.replies)) - 1]


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
```

Script replies per test (`fake_llm.replies = ["{\"label\": \"billing\"}"]`), simulate failures (`fake_llm.error = TimeoutError()`), and assert on `fake_llm.calls` (for example that a blocked input never reached the model). Keep one small contract test of the real adapter marked `live_llm`, run on demand; model quality belongs in `llm-evaluation`, not in unit tests.

## Keeping tests off the network and off real credentials

- Block sockets with `pytest-socket`: `addopts = "--disable-socket --allow-unix-socket --allow-hosts=127.0.0.1,::1"` (allows the local database and the Docker socket). Mark live tests with `@pytest.mark.enable_socket`.
- Make the LLM and Google Cloud client factories fail loudly in tests unless overridden:

```python
@pytest.fixture(autouse=True)
def _no_real_cloud_clients(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live_llm"):
        return

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("real Vertex AI client constructed in a test; inject FakeLLM")
    monkeypatch.setattr("app.infrastructure.gemini.genai.Client", _refuse)
```

- Unset `GOOGLE_APPLICATION_CREDENTIALS` in the test environment so nothing silently uses a developer's credentials.

## Freezing time

Prefer injecting a clock (`Clock` protocol with `now() -> datetime`) into code that depends on time. When that is not practical:

```python
from freezegun import freeze_time


@freeze_time("2026-01-15T12:00:00Z", real_asyncio=True)
async def test_token_when_past_expiry_should_be_rejected(...) -> None:
    ...
```

`real_asyncio=True` keeps the event loop's monotonic clock real; without it, a frozen clock can stall `asyncio.sleep` and timeouts. `time-machine` is an alternative with lower overhead.
