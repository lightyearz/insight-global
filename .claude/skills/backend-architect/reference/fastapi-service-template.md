# FastAPI service template

## Contents

- Settings with pydantic-settings
- Error hierarchy and handlers
- Shared HTTP client and outbound calls
- App factory, lifespan, middleware
- Health endpoints
- Structured logging for Cloud Logging
- Review checklist

Python 3.12, FastAPI, Pydantic v2, pydantic-settings 2.7+, SQLAlchemy 2.0
async, httpx. Adapt names to the project; keep the shapes.

## Settings with pydantic-settings

```python
# app/config.py
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",            # local dev only; never committed
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "example-service"
    environment: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    api_path_prefix: str = ""

    # Required secrets: no defaults, so startup fails fast if they are missing.
    database_url: SecretStr
    jwt_secret: SecretStr
    internal_api_key: SecretStr

    # Dependency URLs: safe local defaults, real values injected per environment.
    downstream_service_url: str = "http://localhost:8081"

    # NoDecode stops pydantic-settings from JSON-decoding the env value,
    # so a plain comma-separated string works.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("internal_api_key")
    @classmethod
    def reject_empty_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("internal_api_key must not be empty")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Notes:

- Use `get_settings()` as a FastAPI dependency; tests override it with
  `app.dependency_overrides[get_settings] = lambda: Settings(...)`.
- `SecretStr` keeps values out of reprs and logs. Call `.get_secret_value()`
  only at the point of use.
- On older pydantic-settings without `NoDecode`, declare the field as `str`
  and expose a parsed `list[str]` property.
- Never log `database_url`. If you must log the target, log host and database
  name only.

## Error hierarchy and handlers

```python
# app/domain/errors.py  (no FastAPI imports here)
class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class DependencyUnavailableError(AppError):
    status_code = 503
    code = "dependency_unavailable"
```

```python
# app/api/errors.py
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.errors import AppError

logger = logging.getLogger(__name__)


def _envelope(code: str, message: str, request: Request, details: object = None) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, request, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope("validation_error", "Invalid request", request, exc.errors()),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=_envelope("internal_error", "Internal server error", request),
        )
```

Rules:

- Messages in `AppError` are written for clients; never interpolate SQL,
  stack traces, tokens, or personal data into them.
- `exc.errors()` from validation can echo input values. If request bodies may
  contain sensitive data, strip the `input` key before returning.
- Auth dependencies may raise `HTTPException(401, headers={"WWW-Authenticate": "Bearer"})`;
  keep the 401 message generic ("Could not validate credentials").
- If you prefer RFC 9457 `application/problem+json`, adopt it everywhere at
  once; mixed envelopes across services are worse than either choice.

## Shared HTTP client and outbound calls

Create one `httpx.AsyncClient` per process in the lifespan (connection reuse),
not one per request.

```python
# app/infrastructure/clients/downstream.py
import logging

import httpx

from app.domain.errors import DependencyUnavailableError
from app.infrastructure.auth import TokenProvider

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=2.0)


class DownstreamClient:
    """Client for the downstream service.

    Failure policy: FAILS CLOSED. Callers need this answer to authorise the
    request, so any error raises DependencyUnavailableError (503).
    """

    def __init__(self, http: httpx.AsyncClient, base_url: str, token_provider: TokenProvider) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._tokens = token_provider

    async def get_item(self, item_id: str) -> dict[str, object]:
        token = await self._tokens.token_for(self._base_url)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            resp = await self._http.get(
                f"{self._base_url}/api/v1/items/{item_id}",
                headers=headers,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("downstream get_item failed: %s", type(exc).__name__)
            raise DependencyUnavailableError("Downstream service unavailable") from exc
        return resp.json()
```

`TokenProvider` (OIDC ID token minting and caching) is covered in the
service-to-service auth reference linked from SKILL.md.
Retry only idempotent requests, with capped exponential backoff and jitter;
never retry a non-idempotent POST without an idempotency key.

## App factory, lifespan, middleware

```python
# app/main.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.routers import health, items
from app.config import get_settings
from app.infrastructure.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.http = httpx.AsyncClient()
    yield
    await app.state.http.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.service_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,   # explicit list, never "*" with credentials
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_error_handlers(app)

    router = APIRouter(prefix=settings.api_path_prefix)
    router.include_router(health.router, prefix="/api/v1")
    router.include_router(items.router, prefix="/api/v1")
    app.include_router(router)
    return app


app = create_app()
```

Notes:

- No `Base.metadata.create_all()` in the lifespan. Schema comes from Alembic.
- Behind Cloud Run, run uvicorn with `--proxy-headers --forwarded-allow-ips="*"`
  so the scheme and client IP come from the front end. Trusting all forwarders
  is acceptable only because the container is reachable solely through
  Google's front end; do not copy that setting to other hosting.
- Listen on `0.0.0.0:$PORT`; Cloud Run injects `PORT`.
- Add a request-ID middleware that reuses an incoming trace or request ID
  header when present and stores it on `request.state.request_id`.

## Health endpoints

```python
# app/api/routers/health.py
import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(session: AsyncSession = Depends(get_session)) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - report state, never the exception text
        checks["database"] = "unavailable"
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "degraded", "checks": checks},
    )
```

Liveness stays dependency-free. Readiness returns 503, not 200 with an
"unhealthy" body, so probes and smoke tests actually notice.

## Structured logging for Cloud Logging

Cloud Run ships stdout to Cloud Logging. One JSON object per line with
`severity` and `message` is parsed into structured fields. To correlate logs
with a request trace, add
`"logging.googleapis.com/trace": "projects/<PROJECT_ID>/traces/<TRACE_ID>"`,
taking the trace ID from the incoming `traceparent` or `X-Cloud-Trace-Context`
header.

```python
import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            payload["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
```

Never log tokens, secrets, full request bodies, or personal data. Log IDs.

## Review checklist

- [ ] Required secrets have no defaults; the service refuses to start without them
- [ ] No `create_all`, no raw DDL in app code
- [ ] Domain layer free of FastAPI, SQLAlchemy, httpx imports
- [ ] One error envelope; the catch-all handler hides internals
- [ ] Every outbound call has a timeout and a documented fail-open or fail-closed policy
- [ ] CORS origins are an explicit list
- [ ] `/api/v1/health` is dependency-free; `/api/v1/health/ready` returns 503 when not ready
- [ ] Logs are JSON with `severity`; no secrets or personal data in log lines
