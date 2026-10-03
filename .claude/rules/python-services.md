---
paths:
  - "**/*.py"
---

# Python rules (FastAPI services and supporting code)

Full standards: the `python-developer` skill.

- PEP 8. Type hints on every function signature; no `Any` without a stated reason.
- `async def` for every route handler and every database or network call; no blocking calls inside coroutines.
- After editing a `.py` file run `ruff check --fix` and `ruff format` (or let the post-edit hook do it, if one is configured); fix any reported error before moving on.
- Schema changes go through Alembic only: `alembic revision --autogenerate -m "<description>"` in the owning service, then review the generated migration. Never `Base.metadata.create_all()`, never raw `CREATE TABLE`.
- Each service owns its tables; cross-service reads go through the owning service's API, not shared ORM models (see the `backend-architect` skill).
- Cloud Run services are deployed with `--no-allow-unauthenticated` and called with an OIDC ID token (for example from the Next.js server side). Keep an application-level auth check (Bearer token middleware or dependency) as the second boundary.
- Configuration comes from a `pydantic-settings` class; secrets come from Secret Manager; Google clients use Application Default Credentials. No hardcoded secrets, no key files.
- Tests: from the service directory run `python3 -m pytest -v --tb=short`. Name tests `test_<behavior>_when_<condition>_should_<expected>` and keep Arrange / Act / Assert visibly separated.
- Coverage targets: security-critical code (authentication, authorization, input validation, guardrails) over 90 percent; business logic over 80 percent; routes over 70 percent.
- Guardrail pipelines fail closed: if a scanner (prompt-injection detector, PII detector, content classifier) errors or times out, treat the content as blocked, never as clean (see the `llm-guardrails` skill).
