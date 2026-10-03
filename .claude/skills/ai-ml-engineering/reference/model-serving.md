# Serving Self-Hosted Models on Cloud Run

## Contents
- Getting model files into the image
- Memory sizing and OOM diagnosis
- Startup: background loading, liveness and readiness
- Never fail silently
- Model manifest
- ONNX export, quantization and runtime tuning
- Concurrency and threading
- Batching
- Versioning and rollout
- Dependency hygiene
- Access control

Deploy commands, IAM and CI wiring live in `cloud-run-deploy` and `devops-infrastructure`; this file covers what is specific to ML workloads.

## Getting model files into the image

| Option | Pros | Cons |
|--------|------|------|
| Mirror models to a private GCS bucket, fetch during the Docker build with a short-lived token | Reproducible, auditable, no runtime network dependency | Larger image, one more build step |
| Download from the Hugging Face Hub during the build, pinned to a commit `revision` | Simple | Build depends on the Hub; still pin and check licences |
| Mount a bucket read-only with a Cloud Run Cloud Storage volume | Small image | Slower first load; objects can change under a running revision (drift) |
| Download at startup | none worth having | Slow cold starts, a new failure mode at boot, egress on every instance |

Recommended: the private bucket, fetched in a builder stage.

```dockerfile
# syntax=docker/dockerfile:1
FROM gcr.io/google.com/cloudsdktool/google-cloud-cli:slim AS model-fetcher
ARG MODELS_URI=gs://<MODELS_BUCKET>/<MODEL_SET_VERSION>
RUN --mount=type=secret,id=gcs_token \
    mkdir -p /models && \
    CLOUDSDK_AUTH_ACCESS_TOKEN_FILE=/run/secrets/gcs_token \
    gcloud storage cp --recursive "${MODELS_URI}/*" /models/

FROM python:3.12-slim AS runtime
# ... install the app ...
COPY --from=model-fetcher /models /models
ENV MODEL_DIR=/models \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
```

In GitHub Actions, mint the token with Workload Identity Federation and pass it as a BuildKit secret, never as a build argument (build arguments end up in image history):

```yaml
- id: auth
  uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ vars.WIF_PROVIDER }}
    service_account: ${{ vars.CI_SERVICE_ACCOUNT }}   # <SA_NAME>@<PROJECT_ID>.iam.gserviceaccount.com
    token_format: access_token
- uses: docker/build-push-action@v6
  with:
    context: .
    file: services/<SERVICE>/Dockerfile
    push: true
    tags: <REGION>-docker.pkg.dev/<PROJECT_ID>/<AR_REPO>/<SERVICE>:${{ github.sha }}
    secrets: |
      gcs_token=${{ steps.auth.outputs.access_token }}
```

Local build:

```bash
GCS_TOKEN="$(gcloud auth print-access-token)" \
  docker build --secret id=gcs_token,env=GCS_TOKEN -f services/<SERVICE>/Dockerfile .
```

To add or update a model: upload a new versioned folder to the bucket, bump `MODEL_SET_VERSION`, and deploy. Never overwrite a version in place.

## Memory sizing and OOM diagnosis

Starting point: `memory_limit ~= 2.5 x model files on disk + 0.5 GiB`, then measure.

| Model files on disk | Starting limit |
|---------------------|----------------|
| < 300 MB | 1 GiB |
| 300-700 MB | 2 GiB |
| 0.7-1.5 GB | 3-4 GiB |
| > 1.5 GB | 4-6 GiB or more |

Where the memory goes for a ~700 MB encoder served through `transformers` or `optimum`: the loaded weights (~0.8-0.9 GB), PyTorch (~0.4-0.5 GB, pulled in by `optimum`'s ORT model classes even though inference runs in ONNX Runtime), `transformers` (~0.1-0.2 GB), the app (~0.1-0.2 GB). Loading peaks above steady state.

- Measure peak RSS during load locally with `docker stats` and add headroom.
- Cloud Run's writable filesystem is in memory: files written to `/tmp` count against the limit.
- Larger memory limits require more vCPUs on Cloud Run; check current limits when sizing.

Symptoms of an out-of-memory kill:
- Locally: exit code 137 and `"OOMKilled": true` in `docker inspect <container>`.
- Logs stop in the middle of model loading with no Python traceback.
- On Cloud Run: a "memory limit exceeded" error in the service logs, instance restarts, and a new revision that never becomes ready.
- Callers see connection refused or JSON decode errors on empty responses.

Fixes, in order: raise the limit; quantize or switch to a smaller model; load models one at a time and drop intermediate copies; serve ONNX with plain `onnxruntime` so PyTorch is not imported at all.

## Startup: background loading, liveness and readiness

Model loading takes seconds to minutes; it must not block the event loop or the port binding.

```python
import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Generic, Literal, TypeVar

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
M = TypeVar("M")


class ModelNotReadyError(RuntimeError):
    pass


class ModelHolder(Generic[M]):
    def __init__(self, name: str, loader: Callable[[], M], warm_up: Callable[[M], None]) -> None:
        self.name = name
        self._loader = loader
        self._warm_up = warm_up
        self._model: M | None = None
        self.status: Literal["loading", "ready", "failed"] = "loading"
        self.error: str | None = None

    async def load(self) -> None:
        try:
            model = await asyncio.to_thread(self._loader)
            await asyncio.to_thread(self._warm_up, model)  # first inference allocates and optimises
            self._model = model
            self.status = "ready"
            logger.info("model ready", extra={"model": self.name})
        except Exception as exc:  # never re-raise from a background task: it dies silently
            self.status = "failed"
            self.error = f"{type(exc).__name__}: {exc}"
            logger.exception("model load failed", extra={"model": self.name})

    def get(self) -> M:
        if self._model is None:
            raise ModelNotReadyError(self.name)
        return self._model


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    holder = ModelHolder("triage-encoder", load_triage_model, warm_up_triage_model)
    app.state.model = holder
    load_task = asyncio.create_task(holder.load())  # keep a reference; unreferenced tasks can be collected
    yield
    load_task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/health")  # liveness: never touches the model
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")  # readiness: 503 until the model is loaded
async def ready(request: Request) -> JSONResponse:
    holder: ModelHolder[object] = request.app.state.model
    status_code = 200 if holder.status == "ready" else 503
    return JSONResponse({"model": holder.name, "status": holder.status, "error": holder.error},
                        status_code=status_code)
```

- Inference endpoints translate `ModelNotReadyError` into 503 with a `Retry-After` header.
- Point the Cloud Run startup probe at `/ready` so traffic is not routed until the model is loaded. If a required model fails to load, the probe keeps failing and the new revision never takes traffic: the deploy fails loudly instead of serving a broken service.

```yaml
# Cloud Run service spec, under the container
startupProbe:
  httpGet:
    path: /ready
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 24   # ~2 minutes for the model to load
```

- Startup CPU boost (`--cpu-boost`) shortens model load. Minimum instances avoid cold-start loads on latency-sensitive paths but cost money while idle; see `cloud-costs-optimization`.
- For local `docker compose`, give the container healthcheck a start period longer than the load time.
- Optional models should not gate readiness; report them as degraded instead.
- Use `lifespan`; `@app.on_event("startup")` is deprecated.

## Never fail silently

Every fallback path records itself:

```python
import logging
import threading
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class ComponentHealth:
    name: str
    status: Literal["ok", "degraded"] = "ok"
    failures: int = 0
    last_error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_failure(self, exc: BaseException) -> None:
        with self._lock:
            self.failures += 1
            self.status = "degraded"
            self.last_error = f"{type(exc).__name__}: {exc}"
        logger.error("component failed", extra={"component": self.name}, exc_info=exc)

    def snapshot(self) -> dict[str, object]:
        return {"status": self.status, "failures": self.failures, "last_error": self.last_error}
```

- Expose every component's `snapshot()` in an inspect or readiness payload, emit a counter metric, and alert on degraded status or a rising fallback rate (a log-based metric works).
- Decide and document each component's fail mode:

| Component kind | Fail mode |
|----------------|-----------|
| Optional enrichment (extra labels, suggestions) | Fail open: return the base result, record the failure |
| Detector guarding a costly or risky action | Explicit decision; if it fails open, alert immediately because the protection is off |
| Model producing the endpoint's core output | Fail closed: 503, never a fabricated default |

## Model manifest

Describe every model in one place and derive validation from it:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    version: str
    relative_path: str
    required_files: tuple[str, ...]
    optional: bool = False


MANIFEST: tuple[ModelSpec, ...] = (
    ModelSpec("triage-encoder", "1.3.0", "triage-encoder", ("model.onnx", "tokenizer.json", "config.json")),
    ModelSpec("embedder", "1.0.0", "all-MiniLM-L6-v2", ("model.safetensors", "tokenizer.json", "config.json")),
    ModelSpec("experimental-ner", "0.2.0", "experimental-ner", ("model.onnx",), optional=True),
)


def validate_models(root: Path) -> list[str]:
    """Raise if a required model is incomplete; return the names of missing optional models."""
    missing_optional: list[str] = []
    for spec in MANIFEST:
        base = root / spec.relative_path
        missing = [f for f in spec.required_files if not (base / f).is_file()]
        if not missing:
            continue
        if spec.optional:
            missing_optional.append(spec.name)
        else:
            raise RuntimeError(f"required model {spec.name} is missing {missing} under {base}")
    return missing_optional
```

- The required set comes from the `optional` flag, never from a separately hard-coded list.
- `required_files` must match the artifact actually published (`model.safetensors` versus `pytorch_model.bin`). Unit-test the expected names so a stale entry fails CI, not the deploy.
- Feature-flagged models are `optional=True`; log a warning when they are absent.

## ONNX export, quantization and runtime tuning

Export once, offline or in CI, and commit the result to the model bucket:

```bash
optimum-cli export onnx --model <hub-id-or-local-path> --task text-classification <out_dir>/
```

Dynamic INT8 quantization for CPU serving:

```python
from onnxruntime.quantization import QuantType, quantize_dynamic

quantize_dynamic("out/model.onnx", "out/model.int8.onnx", weight_type=QuantType.QInt8)
```

Re-run the eval set after quantizing; the accuracy delta is usually small for encoders but must be measured, not assumed.

Serve with `onnxruntime` and `tokenizers` only, so the runtime image needs no PyTorch:

```python
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import onnxruntime as ort
from numpy.typing import NDArray
from tokenizers import Tokenizer


class OnnxSequenceClassifier:
    def __init__(self, model_dir: Path, *, intra_op_threads: int, pad_token: str, max_length: int = 256) -> None:
        options = ort.SessionOptions()
        options.intra_op_num_threads = intra_op_threads      # = vCPUs available to this model
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            str(model_dir / "model.int8.onnx"), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=max_length)
        # pad_token: "[PAD]" for BERT-family, "<pad>" for RoBERTa/BART-family
        self._tokenizer.enable_padding(pad_id=self._tokenizer.token_to_id(pad_token), pad_token=pad_token)

    def predict_proba(self, texts: Sequence[str]) -> NDArray[np.float32]:
        encodings = self._tokenizer.encode_batch(list(texts))
        feeds = {
            "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
        }
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.array([e.type_ids for e in encodings], dtype=np.int64)
        (logits,) = self._session.run(["logits"], feeds)
        shifted = np.exp(logits - logits.max(axis=1, keepdims=True))
        return shifted / shifted.sum(axis=1, keepdims=True)
```

- For zero-shot NLI in ONNX, encode (text, hypothesis) pairs (`encode_batch([(text, hyp), ...])`) and read the entailment index from `config.json`'s `label2id`.
- Warm up with one representative batch at startup; the first run allocates buffers and is much slower.
- Fix `max_length` to what the task needs; sequence length dominates latency.
- When batching, group texts of similar length to reduce padding.

## Concurrency and threading

- Inference is CPU-bound. Run it with `asyncio.to_thread` (or a sync `def` endpoint) so the event loop keeps serving health checks.
- Concurrent requests each using `intra_op_threads` oversubscribe the CPU and inflate tail latency. Bound in-flight inferences with an `asyncio.Semaphore` sized to `vCPUs // intra_op_threads`, and set Cloud Run concurrency low for model-serving services.
- Keep heavy models in their own service when their CPU and memory profile differs sharply from the API that calls them; scale them independently.

## Batching

For high throughput, micro-batch: collect requests until N items (for example 32) or T milliseconds (for example 10 ms), whichever comes first, run one forward pass, and resolve each caller's future with its row. This trades a few milliseconds of latency for several-fold throughput. Benchmark realistic batch sizes (1, 8, 16, 32) before choosing N and T.

## Versioning and rollout

- Name models `{name}:{semver}`. Bump the major version for architecture or label-set changes, the middle number for retrained weights, the patch for packaging fixes.
- Pin Hub revisions to a commit; record model versions in the manifest and in every prediction log line.
- Include model versions in cache keys (see "Speed and caching" in the `classification.md` reference).
- Before merging a model change: p50/p95 latency at realistic batch sizes, peak memory, and per-class accuracy on the eval set, compared with the current model.
- Roll out as a new Cloud Run revision with no traffic, smoke-test it through a revision tag URL, then shift traffic gradually while watching metrics; rollback is shifting traffic back. Commands are in `cloud-run-deploy`.

## Dependency hygiene

- One requirements lock per service. Legacy variants drift: one old variant pinned a FastAPI release that passed the deprecated `on_startup` argument to a newer Starlette, and the service failed at import whenever that file was used.
- Install the CPU build of PyTorch when there is no GPU (`--index-url https://download.pytorch.org/whl/cpu`); the default wheel pulls in gigabytes of CUDA libraries.
- Major `transformers` and `sentence-transformers` upgrades change loading defaults (the meta-tensor failure). Keep a CI smoke test that loads each model from the manifest and runs one inference.
- Upgrade ML dependencies in their own PR with before/after eval numbers.

## Access control

- Model services are private: deploy with `--no-allow-unauthenticated` and call them with a Google-signed ID token whose audience is the service URL; grant callers `roles/run.invoker` on that service only.
- If the service also runs its own JWT middleware, a Google ID token will not satisfy it. Know which layer each endpoint expects, and smoke-test through the same path real callers use.
- Details: `backend-architect` (service-to-service auth) and `cloud-run-deploy` (IAM).
