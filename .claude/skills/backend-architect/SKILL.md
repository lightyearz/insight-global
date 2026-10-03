---
name: backend-architect
description: Backend architecture guidance for Python 3.12 + FastAPI microservices on Google Cloud Run. Covers service boundaries and data ownership, layered service layout, API conventions, SQLAlchemy 2.0 async with Alembic migrations, configuration with pydantic-settings and Secret Manager, error handling, service-to-service auth with Cloud Run IAM and OIDC identity tokens, health checks, and deploy consistency. Use when designing or refactoring a backend service, planning a schema change or migration rollout, adding a service-to-service call, reviewing backend changes that touch auth or sensitive data, or deciding where a piece of logic or a table belongs.
---

# Backend Architect

Use this skill for backend design, refactors, service decomposition, schema
planning, migration strategy, inter-service integration, and security-sensitive
backend work. For line-level Python quality use `python-developer`; for test
strategy use `testing-qa` and `backend-test-runner`; for pipelines and
infrastructure use `devops-infrastructure` and `cloud-run-deploy`.

## Role

Act as the backend architect, optimising for:

- clear service boundaries and one-way dependencies
- predictable, reversible schema evolution
- production-safe, zero-downtime deployments
- secure-by-default service edges (no public services, least privilege)
- privacy-aware design (minimise, protect, and audit personal data)

## Non-negotiable rules

1. **One table, one owner service.** Only the owner performs DDL on it.
2. **All schema changes go through Alembic.** Never `Base.metadata.create_all()`
   at startup, never raw `CREATE TABLE` in app code, never "startup patches".
   Grep for `create_all` in review; it tends to creep back in.
3. **Every migration has a working `upgrade()` and `downgrade()`**, and is
   backward-compatible with the previously deployed code (see expand/contract
   in [reference/sqlalchemy-alembic.md](reference/sqlalchemy-alembic.md)).
4. **No public backend services.** Deploy every Cloud Run service with
   `--no-allow-unauthenticated` and keep app-level auth as a second boundary.
   Enforce it with a CI policy check, not memory.
5. **Secrets live in Secret Manager.** Never in code, images, committed env
   files, or default values. Settings must fail fast when a required secret is
   missing.
6. **Identity comes from verified credentials only.** Derive the caller from
   the validated token, never from client-supplied `user_id` / `email` fields,
   especially on endpoints that pass identity to a third party (SSO, billing,
   support widgets).
7. **Safety- and security-critical components fail closed and fail loud.**
8. **Deploy config has one source of truth** (IaC or a declarative service
   config file). Manual `gcloud` changes are for emergencies and get reconciled.

## Service layout

Use a layered (hexagonal) structure so domain logic is testable without FastAPI
or a database:

```
services/<service>/
  app/
    main.py            # app factory: lifespan, middleware, routers, handlers
    config.py          # pydantic-settings Settings + get_settings()
    api/               # routers, request/response schemas, FastAPI dependencies
    application/       # use cases: orchestrate domain + infrastructure
    domain/            # entities, value objects, domain errors, repository Protocols
    infrastructure/    # SQLAlchemy models + repositories, HTTP clients, queues
  tests/
  Dockerfile
  pyproject.toml
```

Dependency rule: `api -> application -> domain`; `infrastructure` implements
interfaces declared in `domain`. The domain layer imports nothing from FastAPI,
SQLAlchemy, or httpx. Wire implementations with FastAPI `Depends` providers so
tests can override them with `app.dependency_overrides`.

A small shared package for cross-cutting concerns (token verification, error
base classes, logging setup) is fine. Keep domain models out of it, version it,
and remember a change to it must rebuild and redeploy every dependent service.

A worked template for `config.py`, `errors.py`, and `main.py` is in
[reference/fastapi-service-template.md](reference/fastapi-service-template.md).

## Service boundaries and data ownership

Pick one data model per repository, write it down, and do not mix them:

| Model | When it fits | Migration layout |
|---|---|---|
| Database per service | Independent teams or deploy cadences; strongest isolation | Each service owns its own Alembic directory and version table |
| Shared database, owned tables | Small team, one Cloud SQL instance to keep costs down | One Alembic stream; ownership enforced per table via model module paths and CODEOWNERS |

In both models:

- Cross-service **reads** go through an explicit contract: an HTTP API, an
  event, or a versioned read-only SQL view. Cross-service **DDL** never happens.
- Do not import another service's ORM models. Duplicate a small read DTO
  instead; coupling to someone else's table layout is the bigger cost.
- Prefer API or event integration over direct table coupling when feasible.
- Dependencies point one way. If an orchestrator or gateway calls domain
  services, domain services never call back into the gateway. Cycles between
  services are a design bug.
- When merging or splitting services, keep old route prefixes working (mount
  the moved routers under the old prefix) so callers only change a host.

## API conventions

- Version every route: `/api/v1/...`. Breaking changes get `/api/v2`, not an
  in-place edit.
- If services sit behind a shared proxy or load balancer that routes by path,
  make the outer prefix configurable (`API_PATH_PREFIX`) rather than hardcoded.
- Plural nouns for collections; `201` + `Location` on create, `204` on delete,
  `409` on conflicts, `422` for validation errors.
- Paginate every list endpoint (cursor-based for large or growing tables).
- One error envelope across all services (see below).
- Request and response bodies are Pydantic models with explicit types; never
  return ORM objects directly, and never accept `dict[str, Any]` bodies.
- Make write endpoints idempotent where a client may retry (idempotency key
  header stored with a unique constraint).

## Configuration (pydantic-settings)

- One `Settings(BaseSettings)` class per service, loaded once via a cached
  `get_settings()` dependency so tests can override it.
- Required secrets have **no default**; startup fails with a clear error if
  they are missing. Use `SecretStr` so they do not leak into logs or reprs.
- Non-secret config (log level, CORS origins, dependency URLs) has safe local
  defaults.
- On Cloud Run, map Secret Manager secrets to env vars with `--set-secrets`
  (or the IaC equivalent). Env-var secrets are resolved when an instance
  starts, so a rotation needs a new revision; pin versions for reproducibility.
- List-valued env vars (CORS origins) contain commas, which collide with
  `gcloud --set-env-vars`. Use gcloud's alternate delimiter syntax
  (`"^@^CORS_ORIGINS=https://a,https://b@LOG_LEVEL=INFO"`) or an env-vars YAML
  file, and parse comma-separated strings explicitly in the settings class.

## Error handling

- Define a small domain error hierarchy (`AppError` -> `NotFoundError`,
  `ConflictError`, `ForbiddenError`, ...) carrying a stable machine-readable
  `code`, an HTTP status, a safe message, and optional details.
- Domain and application layers raise domain errors, never `HTTPException`.
  Only the API layer and auth dependencies speak HTTP.
- Register one handler for `AppError` and one catch-all for `Exception`. The
  catch-all logs the traceback at ERROR and returns a generic 500 with a
  request ID; it never echoes exception text, SQL, or stack traces to clients.
- Health endpoints follow the same rule: report `ok` / `degraded` per
  dependency, not raw exception strings.
- Every outbound call has an explicit timeout. Decide per dependency whether a
  failure **fails open** (best-effort enrichment: log WARNING, continue) or
  **fails closed** (authorization, safety, consent, payment checks: reject).
  Write that decision in the client's docstring.

## Service-to-service auth on Cloud Run

Two layers, both required:

1. **Cloud Run IAM (outer).** Services are private. Each caller runs as its own
   runtime service account, holds `roles/run.invoker` on exactly the services
   it calls, and sends a Google-signed OIDC ID token whose audience is the
   target service URL.
2. **Application auth (inner).** FastAPI still validates the end-user JWT
   (signature, `exp`, issuer, audience, pinned algorithm) or, for internal-only
   endpoints, a caller check. Shared internal keys are compared with
   `hmac.compare_digest` and rejected outright if the configured key is empty.

When a proxy forwards an end-user request, put the OIDC token in
`X-Serverless-Authorization` so `Authorization` can keep carrying the user's
token to the app.

Token minting in Python and TypeScript, local-dev impersonation, testing
private services with `curl`, and the CI policy check are in
[reference/service-auth-cloud-run.md](reference/service-auth-cloud-run.md).

## Database and migrations (summary)

- SQLAlchemy 2.0 async (`asyncpg`) for the app; Alembic with a sync driver or
  the async template for migrations.
- One `AsyncSession` per request via a dependency; `expire_on_commit=False`;
  eager-load relationships explicitly (`selectinload`) because lazy loads fail
  in async code.
- Size connection pools against Postgres `max_connections`:
  `services x max_instances x (pool_size + max_overflow)` must leave headroom.
- Alembic's `env.py` must import **every** model module, or autogenerate will
  propose dropping the tables it cannot see. Always read the generated file.
- Keep history linear (exactly one head); CI fails on multiple heads.
- Run `alembic upgrade head` in CI before the new revision receives traffic,
  over the Cloud SQL Auth Proxy with Workload Identity Federation, or as a
  Cloud Run job using the service image. A failed migration fails the deploy.
- Use expand/contract for anything that is not purely additive.
- pgvector: enable the extension in a migration and keep indexed vector columns
  within the index dimension limit.

Full workflow, code, review checklist, and zero-downtime patterns:
[reference/sqlalchemy-alembic.md](reference/sqlalchemy-alembic.md).

## Health and operations

Every service exposes:

- `GET /api/v1/health`: liveness. Cheap and dependency-free, so a database
  blip does not restart every instance.
- `GET /api/v1/health/ready`: readiness. Checks the database and critical
  dependencies with short timeouts; returns **503** when not ready.

Use the readiness endpoint for post-deploy smoke tests and uptime checks.
Log JSON to stdout with a `severity` field so Cloud Logging parses it, and
attach the trace ID from the incoming trace header for correlation.

## Architecture lessons worth keeping

- **Build derived data from versioned source.** If a service reads a derived
  artifact (embedding index, lookup database, compiled rules), bake the source
  into the image and rebuild the artifact at build time, or at startup to a
  writable local path with a content-hash skip. Never hand-rebuild and upload
  it to a mutable bucket; the data silently drifts from the code.
- **Critical components fail loud.** A scanner or policy check that fails
  inside a bare `except` with a `print()` can silently downgrade results for
  weeks. Log at ERROR with traceback, expose a `degraded` flag on a diagnostic
  endpoint, prefer fail-closed, and keep an independent second layer.
- **Do not deploy an image that was not built in this run** without resolving
  it. When a shared-library change or deploy-all trigger redeploys an unchanged
  service, its `:<sha>` tag may not exist; fall back to the last good tag or
  skip with a warning. "Image not found" on a revision is a tagging or
  ordering bug, not a build failure.
- **Apply full service config on every deploy** (`gcloud run deploy` with all
  flags from a declarative file, or IaC), not incremental `services update`
  commands, so config cannot drift between environments.

## Standard workflow

1. Branch with a conventional prefix (`feat/`, `fix/`, `refactor/`, ...).
2. Decide ownership: which service owns the logic and each table touched.
3. Design or validate API and event contracts; version breaking changes.
4. Plan the migration in the owner service, including expand/contract steps
   and rollback.
5. Review security and privacy impact: authN/authZ, personal data handling,
   retention, audit logging, secrets.
6. Update deploy config (IaC or service config file) in the same PR.
7. Update architecture docs and diagrams.
8. Open a PR; quality gates (secret scan, Dockerfile lint, build, tests,
   migration round-trip) must pass. Require CODEOWNERS review for auth code,
   Dockerfiles, CI workflows, and IaC.

## Outputs this skill should produce

For an architecture task, deliver:

- an explicit ownership decision (service and tables)
- the migration strategy and rollout order
- API or event contract changes, with versioning
- auth model for any new service-to-service call
- deployment and config changes required
- docs and diagram updates
- concrete risks with mitigations

## References

- [reference/fastapi-service-template.md](reference/fastapi-service-template.md): settings, errors, app factory, health, logging
- [reference/sqlalchemy-alembic.md](reference/sqlalchemy-alembic.md): async sessions, Cloud SQL connections, Alembic workflow, zero-downtime migrations, pgvector
- [reference/service-auth-cloud-run.md](reference/service-auth-cloud-run.md): OIDC identity tokens, invoker IAM, internal keys, testing private services

Related skills: `python-developer`, `testing-qa`, `backend-test-runner`,
`devops-infrastructure`, `cloud-run-deploy`, `cloud-costs-optimization`,
`ai-ml-engineering` (Vertex AI integration), `llm-guardrails`.
