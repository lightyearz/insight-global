# Troubleshooting out-of-memory kills when loading ONNX or transformer models

## Contents

- Symptom
- Detection (Docker and Cloud Run)
- Where the memory goes
- Fix: size the container
- Fix: load in the background, gate on readiness
- Common mistakes
- Verification
- Related symptoms

Model-side techniques (quantization, plain `onnxruntime` instead of `optimum`, model manifests) are in the `ai-ml-engineering` skill. This file covers diagnosis and the container and Cloud Run side.

## Symptom

The container starts, the server logs that it is listening, model loading begins, and then the logs stop with no traceback. The process was killed by the kernel's OOM killer (SIGKILL, exit code 137). Callers see connection refused or a JSON decode error on an empty response.

## Detection (Docker and Cloud Run)

```bash
# Docker: was it the OOM killer?
docker inspect <container> --format '{{.State.OOMKilled}} {{.State.ExitCode}}'   # true 137

# watch memory while the model loads
docker stats <container>

# the last log lines before the kill
docker logs --tail 50 <container>
```

On Cloud Run:

```bash
gcloud logging read "resource.labels.service_name=<SERVICE> AND textPayload:\"Memory limit\"" \
  --project <PROJECT_ID> --limit 20
gcloud run revisions describe <REVISION> --region <REGION> --project <PROJECT_ID> \
  --format="value(status.conditions[].message)"
```

Look for "Memory limit of ... exceeded", repeated instance restarts, and a revision that never becomes ready while the previous one keeps serving.

## Where the memory goes

For a ~700 MB zero-shot ONNX encoder served through `optimum` + `transformers`:

| Component | Approximate memory |
|-----------|--------------------|
| Model weights loaded | 0.8-0.9 GB |
| PyTorch (imported by `optimum`'s ORT classes even though inference runs in ONNX Runtime) | 0.4-0.5 GB |
| `transformers` | 0.1-0.2 GB |
| FastAPI app and dependencies | 0.1-0.2 GB |
| **Steady state** | **1.5-2.0 GB** |

Loading peaks above steady state (file read plus session construction), and on Cloud Run any file written to `/tmp` is memory too.

## Fix: size the container

Starting point: `memory_limit ~= model files on disk x 2.5 + 0.5 GiB`, then measure peak RSS during load and add headroom.

| Model files on disk | Starting limit |
|---------------------|----------------|
| < 300 MB | 1 GiB |
| 300-700 MB | 2 GiB |
| 0.7-1.5 GB | 3-4 GiB |
| > 1.5 GB | 4-6 GiB or more |

```yaml
# docker-compose.yml
services:
  model-api:
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 512M
```

```bash
# Cloud Run (back-port to Terraform afterwards)
gcloud run services update <SERVICE> --region <REGION> --memory 2Gi --cpu 2
```

If the limit cannot grow: quantize (INT8), switch to a smaller model, load models one at a time and release intermediates, or run plain `onnxruntime` with a tokenizer so PyTorch is never imported.

## Fix: load in the background, gate on readiness

Load the model off the event loop so the server answers health checks while it loads, record failure instead of raising, and report readiness separately from liveness.

```python
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

logger = logging.getLogger(__name__)


class ModelState:
    def __init__(self) -> None:
        self.ready = asyncio.Event()
        self.model: object | None = None
        self.error: str | None = None


state = ModelState()


async def load_model() -> None:
    try:
        state.model = await asyncio.to_thread(build_model)  # blocking load in a worker thread
    except Exception as exc:  # record, never re-raise from a background task
        state.error = repr(exc)
        logger.exception("model load failed")
    finally:
        state.ready.set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(load_model())  # keep a reference so it is not garbage-collected
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}  # liveness: never waits for the model


@app.get("/ready")
async def ready(response: Response) -> dict[str, str]:
    if not state.ready.is_set():
        response.status_code = 503
        return {"model": "loading"}
    if state.error:
        response.status_code = 503
        return {"model": "failed"}
    return {"model": "ready"}
```

Then let the platform wait for readiness:
- **Cloud Run**: a startup probe on `/ready` with a budget longer than the slowest load (for example `period_seconds = 5`, `failure_threshold = 24` for two minutes). Traffic is not routed to the instance until it passes; startup CPU boost (`--cpu-boost`) shortens the load.
- **Docker**: `HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ready')"`. The `--start-period` keeps failures during loading from counting.

Inference endpoints return 503 with a clear body while the model is loading or failed, never a silent default answer. For guardrail or safety classifiers that means fail closed (see `llm-guardrails`).

## Common mistakes

- Loading the model synchronously in startup: the server cannot answer probes for 30-60 seconds and the platform may kill it.
- Re-raising inside a background task: the exception disappears or takes the process down without a useful log line.
- Fire-and-forget `asyncio.create_task(...)` without keeping a reference: the task can be garbage-collected.
- A health check that waits for the model: liveness fails during a normal load and the instance is restarted in a loop.
- Sizing the limit to the model file size: the runtime, libraries and load peak need 2-3 times that.

## Verification

```bash
docker compose up -d model-api
docker inspect model-api --format '{{.State.OOMKilled}}'     # false
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/ready   # 503 while loading, 200 once ready
curl -s localhost:8080/health                                   # 200 throughout
```

On Cloud Run, after deploy: created revision equals ready revision, memory utilisation stays below about 85 percent of the limit under load, and the first request after a cold start succeeds.

## Related symptoms

| Symptom | Usual meaning |
|---------|---------------|
| Exit code 137 | SIGKILL, almost always the OOM killer |
| `Expecting value: line 1 column 1` in a caller | Empty response: the service was down or restarting |
| Container exits silently | OOM kill, or an uncaught exception in a background task |
| Health check timing out | Event loop blocked by a synchronous load, or the instance is being OOM-killed during load |
| First request takes 30-60 s, later ones fast | Model loaded lazily on first request; move it to startup with a readiness gate |
