# Health Briefing API: FastAPI + LangGraph. Build from the repository root (fixtures are baked in):
#   docker build -f api/Dockerfile -t health-briefing-api .
#   docker run --rm -p 8080:8080 health-briefing-api            # replay mode, no credentials
# Cloud Run sets PORT; Vertex AI uses the service account via ADC (set GOOGLE_CLOUD_PROJECT). No keys baked in.
#
# SINGLE PROCESS BY DESIGN: the event bus, the run tasks and both SQLite files live in one process.
# Run exactly one worker and one instance (Cloud Run: --max-instances=1, --concurrency as needed);
# a second instance would not see the first one's runs, events or checkpoints.

FROM ghcr.io/astral-sh/uv:0.8.17 AS uv

FROM python:3.12-slim AS runtime
COPY --from=uv /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app/api

# Dependencies first (cached layer), from the lockfile only.
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY api/app ./app
COPY fixtures /app/fixtures

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown -R app:app /app/data

USER app

# SQLite lives on the container filesystem: fine for a POC demo, not durable across instances.
# Proxy headers are trusted only from FORWARDED_ALLOW_IPS (read by uvicorn). The default trusts only localhost;
# behind Cloud Run's front end set FORWARDED_ALLOW_IPS='*' at deploy time.
ENV PORT=8080 \
    FORWARDED_ALLOW_IPS=127.0.0.1 \
    DATA_DIR=/app/data \
    FIXTURES_DIR=/app/fixtures/replay \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --proxy-headers"]
