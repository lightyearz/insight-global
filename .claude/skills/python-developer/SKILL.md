---
name: python-developer
description: Applies Python 3.12 coding standards for typing, Pydantic v2 models, SOLID and clean-architecture layering, error handling, async correctness, configuration and secrets, structured logging, Ruff and security tooling, dependency pinning, and container hygiene. Use when writing, refactoring, or reviewing Python code (FastAPI services, workers, scripts, libraries) for quality, testability, and maintainability.
---

# Python Developer

Standards for Python 3.12 code in this repository. Service boundaries, API design and database ownership live in the `backend-architect` skill; pytest mechanics live in `backend-test-runner` and `testing-qa`. Worked code for the patterns below is in [reference/patterns.md](reference/patterns.md).

## Style and layout

- PEP 8, 4-space indent. Ruff formats; line length 88 (formatter-enforced, not hand-wrapped).
- Imports: standard library, third party, local, separated by blank lines (Ruff `I` sorts them). Prefer absolute imports (`from app.services.billing import ...`) over deep relative ones.
- Declare the public API with `__all__` directly after the imports in modules that other packages import from.
- Google-style docstrings on public modules, classes and functions. Document *why* and the contract (raises, side effects), not a restatement of the signature.
- Functions over about 50 lines, or classes with several unrelated reasons to change, are a refactoring signal.

## Typing

- Type hints on every parameter and return value, including `-> None`.
- Use 3.12 syntax natively: `list[str]`, `dict[str, int]`, `X | None`, `type Alias = ...`, PEP 695 generics (`def first[T](items: Sequence[T]) -> T`). `from __future__ import annotations` is unnecessary on 3.12 and can break FastAPI/Pydantic resolution of types defined in local scopes, so do not add it to route or model modules.
- No `Any` unless it is truly unavoidable (and then say why). Reach for `Protocol`, `TypeVar`/PEP 695 generics, `TypedDict`, or `object` first.
- Accept the most general type you need (`Sequence`, `Mapping`, `Iterable`), return the most specific one.
- Use `Annotated[..., Depends(...)]` for FastAPI dependencies rather than default-value `Depends`.
- If the project configures mypy or pyright, keep it clean. A `# type: ignore` needs an error code and a reason.

## Data modelling (Pydantic v2)

- Validate data at boundaries with Pydantic models, not raw `dict`s. Separate request, response and persistence shapes (`UserCreate`, `UserOut`, ORM `UserRow`); never return ORM objects directly from routes.
- v2 API only: `model_validate`, `model_dump`, `model_config = ConfigDict(...)`, `field_validator`/`model_validator`. Not `parse_obj`, `.dict()`, `class Config`, or `@validator`.
- `ConfigDict(from_attributes=True)` on models built from ORM rows; `ConfigDict(extra="forbid")` on inbound request models so typos fail loudly; `frozen=True` for value objects.
- Use constrained types (`Field(min_length=1, max_length=200)`, `PositiveInt`, `EmailStr`, `HttpUrl`) instead of hand-written checks.
- Use `SecretStr` for anything secret so it does not leak through `repr` or logs.
- Plain `@dataclass(slots=True)` is fine for internal structures that never cross a trust boundary.

## Architecture (SOLID + layers)

- **SRP**: one reason to change per class or function.
- **OCP**: extend through new strategy/implementation classes, not growing `if/elif` chains over a type field.
- **LSP**: subclasses and implementations honour the base contract (same exceptions, no narrowed inputs).
- **ISP**: small `Protocol`s describing what a caller actually uses, not one large service interface.
- **DIP**: domain and application code depend on `Protocol`s; infrastructure implements them; FastAPI `Depends` wires them together.

Layers, with dependencies pointing inward only:

| Layer | Contains | May import |
|-------|----------|------------|
| Domain | Entities, value objects, domain errors, pure rules | Standard library, Pydantic |
| Application | Use cases, orchestration, repository/client `Protocol`s | Domain |
| Infrastructure | SQLAlchemy repositories, HTTP clients, cloud SDK adapters | Domain, Application |
| API | FastAPI routers, request/response schemas, dependency wiring | All of the above |

Domain and application code never import `fastapi`, `sqlalchemy`, or a cloud SDK, and never raise `HTTPException`.

## Errors

- One base class (for example `AppError`) with specific subclasses (`NotFoundError`, `ConflictError`, `UpstreamUnavailableError`).
- Catch specific exceptions; never a bare `except:`, and `except Exception` only at a process boundary (request middleware, worker loop) where it is logged and re-raised or converted.
- Wrap infrastructure failures in domain errors with `raise ... from exc` so the cause chain survives.
- Map domain errors to HTTP status codes in one place (registered exception handlers), not scattered through routes.
- Use `ExceptionGroup` / `except*` when handling failures from `asyncio.TaskGroup`.
- Guardrail and validation code fails closed: if a check errors or times out, treat the input as rejected. See `llm-guardrails`.

## Async and I/O

- `async def` for route handlers and anything awaiting I/O. Inside `async def`, never call blocking code: `requests`, `time.sleep`, synchronous DB drivers, large file reads, CPU-heavy work such as local model inference.
- Use async clients (`httpx.AsyncClient`, `asyncpg`/SQLAlchemy async) and offload unavoidable blocking calls with `await asyncio.to_thread(...)`. CPU-bound work belongs in a process pool, a job, or a separate service.
- Create long-lived clients (HTTP, DB engine, SDK clients) once in the FastAPI `lifespan` and close them on shutdown; do not open a client per request.
- Every outbound call has an explicit timeout. Retry only idempotent operations, with backoff and a cap.
- Fan out with `asyncio.TaskGroup` (structured cancellation) rather than bare `gather` or fire-and-forget `create_task`.
- On Cloud Run with request-based billing, CPU is throttled outside requests, so work started after the response is returned can stall. Use Cloud Tasks, Pub/Sub, or a Cloud Run job for background work.

## Configuration and secrets

- Read configuration through one `pydantic-settings` `Settings` class, cached with `functools.lru_cache`; inject it, do not read `os.environ` throughout the code.
- Secrets come from Secret Manager (exposed to Cloud Run as environment variables or mounted files). Never hardcode them, never commit `.env` files, never log them.
- Google Cloud clients (Vertex AI, Cloud SQL connector, Secret Manager, Storage) authenticate with Application Default Credentials. No service-account key files in code, images, or CI.

## Logging and observability

- Emit structured JSON to stdout (`structlog` or `python-json-logger`); Cloud Logging parses it. Map the level onto a `severity` field so filtering works.
- Bind context (request ID, trace ID, user/tenant ID) once per request via context variables, not by formatting it into every message.
- `INFO` for notable business events, `WARNING` for handled problems, `ERROR` for failures needing attention (with `exc_info`). No `print`.
- Never log secrets, tokens, raw personal data, or full LLM prompts/responses; log identifiers, sizes, hashes, and outcomes.

## Tooling

- Ruff for lint and format (replaces Black, isort, Flake8). Run `ruff check --fix` and `ruff format` after editing, and enforce both in pre-commit and CI. Baseline config is in [reference/patterns.md](reference/patterns.md#ruff-configuration).
- Security: Ruff `S` rules (Bandit) in lint, plus `pip-audit` (or `trivy fs .`) on dependencies in CI.
- Lint and type-check failures block a change; do not silence a rule without a short comment explaining why.

## Testing

- `pytest` + `pytest-asyncio` + `pytest-cov`; shared fixtures in `conftest.py`, data-driven cases with `pytest.mark.parametrize`.
- Depend on `Protocol`s so unit tests use small in-memory fakes instead of deep `mock.patch` chains.
- Prefer a real test database (for example a disposable Postgres container) over mocking the ORM for repository and query tests.
- Aim for at least 80 percent branch coverage overall and more on security-critical paths. Conventions and commands: `backend-test-runner`.

## Dependencies

- Pin direct dependencies (`pyproject.toml` with a lock file, or `requirements.txt` with exact versions; hashes where practical). Keep dev/test tools in a separate group.
- Work inside a virtual environment (`.venv`, or `uv`).
- Review updates regularly and run `pip-audit` in CI; upgrade deliberately, one dependency family at a time, with tests.

## Containers

- Base image `python:3.12-slim-bookworm` (or the current stable slim); multi-stage build so compilers and caches stay out of the runtime image.
- Run as a non-root user; set `PYTHONUNBUFFERED=1`; listen on `$PORT` (Cloud Run sets it).
- Keep the build context small with `.dockerignore` (exclude `.venv`, `.git`, tests, `.env*`, local data).
- Example Dockerfile: [reference/patterns.md](reference/patterns.md#dockerfile). Deployment: `cloud-run-deploy`.

## Review checklist

1. **Types**: complete hints, no unexplained `Any`, Pydantic at boundaries, v2 API only.
2. **Errors**: specific exceptions, `from exc` chaining, no bare `except`, guardrails fail closed.
3. **Security**: parameterised SQL (no f-string queries), input validation, no secrets or personal data in logs, no `eval`/`pickle` on untrusted data, `subprocess` without `shell=True`.
4. **Async**: no blocking calls in `async def`, timeouts on every outbound call, shared clients, no orphaned tasks.
5. **Data access**: no N+1 queries (use `selectinload`/joins), transactions scoped to the use case, schema changes through migrations.
6. **Design**: single responsibility, dependencies injected, no hidden module-level state, layers respected.
7. **Tests**: new behaviour covered, failure paths tested, fakes over deep mocks.
8. **Naming and docs**: descriptive names consistent with the codebase; docstrings explain contracts.

When reporting a review, list findings by severity with `file:line`, the concrete failure scenario, and the suggested fix.
