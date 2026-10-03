# Python patterns (worked examples)

Reference code for the standards in [SKILL.md](../SKILL.md). Names such as `User`, `UserRow` and `GetUser` are illustrative.

## Contents

- [Dependency inversion with Protocols and FastAPI](#dependency-inversion-with-protocols-and-fastapi)
- [Exception hierarchy and HTTP mapping](#exception-hierarchy-and-http-mapping)
- [Settings and secrets](#settings-and-secrets)
- [Lifespan-managed clients and async I/O](#lifespan-managed-clients-and-async-io)
- [Structured logging for Cloud Logging](#structured-logging-for-cloud-logging)
- [Testing with fakes](#testing-with-fakes)
- [Ruff configuration](#ruff-configuration)
- [Dockerfile](#dockerfile)

## Dependency inversion with Protocols and FastAPI

```python
# application/users.py: depends only on the domain and a Protocol
from typing import Protocol
from uuid import UUID

from app.domain.errors import NotFoundError
from app.domain.users import User


class UserRepository(Protocol):
    async def get(self, user_id: UUID) -> User | None: ...


class GetUser:
    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    async def __call__(self, user_id: UUID) -> User:
        user = await self._repo.get(user_id)
        if user is None:
            raise NotFoundError("user", str(user_id))
        return user
```

```python
# infrastructure/sql_users.py: implements the Protocol structurally (no inheritance needed)
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.users import User
from app.infrastructure.models import UserRow


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> User | None:
        row = await self._session.get(UserRow, user_id)
        return User.model_validate(row) if row else None  # User has from_attributes=True
```

```python
# api/users.py: the only layer that knows about FastAPI
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def get_user_use_case(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GetUser:
    return GetUser(SqlUserRepository(session))


@router.get("/users/{user_id}", response_model=UserOut)
async def read_user(
    user_id: UUID,
    get_user: Annotated[GetUser, Depends(get_user_use_case)],
) -> UserOut:
    return UserOut.model_validate(await get_user(user_id))
```

## Exception hierarchy and HTTP mapping

```python
# domain/errors.py
class AppError(Exception):
    """Base class for all application errors."""


class NotFoundError(AppError):
    def __init__(self, resource: str, key: str) -> None:
        super().__init__(f"{resource} {key!r} not found")
        self.resource = resource
        self.key = key


class ConflictError(AppError): ...


class UpstreamUnavailableError(AppError): ...
```

Wrap infrastructure failures at the edge, keeping the cause:

```python
try:
    response = await client.post(url, json=payload, timeout=10.0)
    response.raise_for_status()
except httpx.HTTPError as exc:
    raise UpstreamUnavailableError("scoring service unavailable") from exc
```

Map to HTTP once, in the API layer:

```python
_STATUS: dict[type[AppError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    UpstreamUnavailableError: 503,
}


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    status = next((code for cls, code in _STATUS.items() if isinstance(exc, cls)), 500)
    if status >= 500:
        logger.error("request_failed", error=type(exc).__name__, exc_info=exc)
    detail = str(exc) if status < 500 else "internal error"  # do not leak internals
    return JSONResponse(status_code=status, content={"detail": detail})
```

## Settings and secrets

```python
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")  # .env is local-only and git-ignored

    database_url: SecretStr
    gcp_project: str
    gcp_region: str
    log_level: str = "INFO"
    request_timeout_s: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- On Cloud Run the same fields arrive as environment variables, with secret values sourced from Secret Manager (`--set-secrets`). Commit a `.env.example` with placeholder values only.
- Read the secret with `settings.database_url.get_secret_value()` at the point of use; never log the `Settings` object after unwrapping.
- Google SDK clients pick up Application Default Credentials automatically (the runtime service account on Cloud Run, `gcloud auth application-default login` locally). Do not pass key files.

## Lifespan-managed clients and async I/O

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(settings.request_timeout_s))
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(lifespan=lifespan)
```

Offloading and fan-out:

```python
import asyncio

# A blocking library call inside async code
text = await asyncio.to_thread(extract_text, pdf_bytes)

# Structured concurrency: if one task fails, the others are cancelled
async with asyncio.TaskGroup() as tg:
    profile = tg.create_task(fetch_profile(user_id))
    history = tg.create_task(fetch_history(user_id))
result = merge(profile.result(), history.result())
```

Handle failures from a `TaskGroup` with `except* SomeError as group:`; every failed task's exception is in `group.exceptions`.

## Structured logging for Cloud Logging

```python
import logging

import structlog
from structlog.typing import EventDict, WrappedLogger


def _to_severity(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    event_dict["severity"] = str(event_dict.pop("level", "info")).upper()
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            _to_severity,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
    )
```

Bind request context once in middleware:

```python
@app.middleware("http")
async def bind_request_context(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request.headers.get("x-request-id") or uuid4().hex,
        path=request.url.path,
    )
    return await call_next(request)
```

Then `logger.info("invoice_issued", invoice_id=str(invoice.id), amount_cents=invoice.amount_cents)`: identifiers and numbers, never secrets or raw personal data.

## Testing with fakes

Because `GetUser` depends on a `Protocol`, a few lines of fake replace a mock chain:

```python
from uuid import UUID, uuid4

import pytest


class FakeUserRepository:
    def __init__(self, users: dict[UUID, User] | None = None) -> None:
        self._users = users or {}

    async def get(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)


async def test_get_user_when_missing_should_raise_not_found() -> None:
    # Arrange
    use_case = GetUser(FakeUserRepository())

    # Act / Assert
    with pytest.raises(NotFoundError):
        await use_case(uuid4())


@pytest.mark.parametrize("name", ["a", "x" * 200])
def test_user_create_when_name_at_bounds_should_validate(name: str) -> None:
    assert UserCreate(name=name).name == name
```

The async test above assumes `asyncio_mode = "auto"` under `[tool.pytest.ini_options]`; otherwise mark it with `@pytest.mark.asyncio`.

## Ruff configuration

```toml
[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "ARG", "PTH", "ASYNC", "S", "ANN"]
ignore = ["E501"]  # the formatter owns line length

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "ANN"]  # assert is fine in tests

[tool.pytest.ini_options]
asyncio_mode = "auto"
addopts = "--strict-markers"
```

`ASYNC` catches blocking calls inside `async def`; `S` is the Bandit rule set; `UP` keeps syntax current for the target version.

## Dockerfile

```dockerfile
FROM python:3.12-slim-bookworm AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /install /usr/local
COPY --chown=app:app app ./app
USER app
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

Pair it with a `.dockerignore` that excludes `.venv/`, `.git/`, `tests/`, `.env*`, `__pycache__/` and local data.
