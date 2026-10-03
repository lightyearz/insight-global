---
name: devops-infrastructure
description: Reference for hosting Python 3.12 FastAPI services and a Next.js front end on Google Cloud - reference architecture, Cloud Run sizing and flags, Artifact Registry, Cloud SQL and Memorystore networking, Secret Manager, runtime service accounts, Workload Identity Federation for GitHub Actions, Terraform as the source of truth for service config, CI quality gates and security scanning, Docker builds (including build secrets for model files), logging and health checks, and troubleshooting failed revisions, IAM 403s and out-of-memory kills while loading ONNX or transformer models. Use when designing or changing infrastructure, wiring CI/CD or WIF, managing secrets or service accounts, sizing a service, debugging a deploy or a crashing container, or explaining how the platform is hosted. For copy-paste deploy, rollout and rollback commands use cloud-run-deploy.
---

# DevOps and Infrastructure (Google Cloud)

How the platform is hosted, why it is set up that way, and how to debug it. Commands use placeholders; set them once per shell:

```bash
export PROJECT_ID=<PROJECT_ID> REGION=<REGION> SERVICE=<SERVICE> AR_REPO=<AR_REPO>
```

Never paste real project numbers, service-account emails, `*.run.app` URLs, bucket names or secret values into code, docs or this harness.

## Related skills

| Need | Skill |
|------|-------|
| Deploy, verify, roll out gradually, roll back | `cloud-run-deploy` |
| Spend analysis, right-sizing, build and storage costs | `cloud-costs-optimization` |
| Service boundaries, ID-token auth between services, Alembic | `backend-architect` |
| Model memory, background loading, ONNX export | `ai-ml-engineering` |
| Calling private backends from Next.js | `frontend-developer` |
| Test commands that CI runs | `backend-test-runner`, `frontend-test-runner` |

## Reference files (load on demand)

- [CI/CD pipeline](reference/ci-cd-pipeline.md): branch rules, quality gates, security scanning, Dependabot, the build-and-deploy workflow, image tags, Cloud Build as a secondary path, deploy order.
- [Secrets, OAuth, service accounts and WIF](reference/secrets-oauth-identity.md): Secret Manager layout and commands, GitHub secrets, env-var escaping, OAuth client setup, service-account roles, Workload Identity Federation from scratch.
- [Terraform](reference/terraform.md): module layout, plan-on-PR / apply-on-merge, what Terraform owns versus what CI deploys.
- [ONNX / model OOM troubleshooting](reference/onnx-oom-troubleshooting.md): exit code 137, sizing formula, startup probes, background loading.

## Reference architecture

```
<DOMAIN>
└── web: Next.js on Cloud Run (the only public entry point)
    └── route handlers / server-side proxy ──(ID token)──> private backends

Cloud Run (<REGION>)
├── api-*      FastAPI, private, min=0 + startup CPU boost unless on the hot path
├── model-*    model serving, private, sized by the memory formula, min=1 if user-facing
├── worker-*   continuous background loop, private, instance-based billing, min=1
└── jobs       Cloud Run Jobs for scheduled or batch work

Cloud SQL for PostgreSQL (+ pgvector)   Cloud SQL connector or private IP
Memorystore for Redis (optional)       Direct VPC egress or a Serverless VPC Access connector
Secret Manager                         runtime secrets, referenced by name from each service
Artifact Registry (<AR_REPO>)          images tagged with the commit SHA
Vertex AI (Gemini)                     called with ADC through the runtime service account
GitHub Actions                         builds images and deploys through WIF (no JSON keys)
Terraform                              service config, IAM, secret containers
```

## Non-negotiables

- **Backends are private.** Deploy with `--no-allow-unauthenticated`; grant `roles/run.invoker` to each caller's service account, never to `allUsers`. Callers send a Google-signed ID token; the app keeps its own auth check as a second layer. The web front end is the one public service, and its exposure is set in reviewed Terraform, not from a shell.
- **One runtime service account per service**, least privilege. Do not run on the default compute service account.
- **No service-account key files anywhere.** Locally: `gcloud auth application-default login`. CI: WIF. Cloud Run: the attached service account. Google clients pick all three up through ADC.
- **Secrets live in Secret Manager** and are referenced by the service (`--set-secrets=ENV=SECRET:latest`). Never in the image, build args, plain env vars, or logs.
- **Images go to Artifact Registry, tagged with the commit SHA.** Deploy by SHA or digest; `:latest` is a convenience tag, not a deploy reference.
- **Terraform owns persistent config** (CPU, memory, scaling, env, secrets, IAM). A manual `gcloud run deploy` is for emergencies and is back-ported to Terraform the same day.
- **Containers** are multi-stage, run as non-root, pin their base image, and listen on `0.0.0.0:$PORT`.
- **CORS** lists known origins only; no wildcards.

## Service sizing

| Role | Memory | vCPU | Min / max | Flags | Notes |
|------|--------|------|-----------|-------|-------|
| CRUD / auth API | 512Mi-1Gi | 1 | 0 / 10 | `--cpu-boost` | min 1 only if it sits on the latency-critical path |
| Model serving | formula below | 2 | 1 / 5 | `--cpu-boost` | load in the background, gate traffic on a startup probe |
| Continuous worker | 512Mi-4Gi | 1-2 | 1 / 2 | `--no-cpu-throttling` | instance-based billing: the CPU runs between requests |
| WebSocket / SSE | 512Mi-1Gi | 1-2 | 1 / N | `--session-affinity`, `--timeout=3600` | clients must reconnect; affinity is best effort |
| Next.js web | 512Mi-1Gi | 1 | 0-1 / 10 | `--cpu-boost` | `output: 'standalone'` keeps the image small |

- **Model memory starting point:** `limit ~= 2.5 x model files on disk + 0.5 GiB`, then measure peak RSS during load. Details: [onnx-oom-troubleshooting](reference/onnx-oom-troubleshooting.md) and the `ai-ml-engineering` skill.
- Larger memory limits require more vCPUs on Cloud Run; check the current limits table before sizing.
- Cloud Run's writable filesystem is in memory: anything written to `/tmp` counts against the limit.
- An API and its worker can share one image and differ only in command, flags and scaling. Model them as two Terraform resources.
- `min-instances` costs money while idle; cold starts cost latency. Decide per service, see `cloud-costs-optimization`.

## Docker builds

- One `Dockerfile` per service. When services share an internal Python package, build from the repo root so the package can be copied in, and keep a per-service `.dockerignore` (exclude `.git`, `node_modules`, virtualenvs, test data).
- `.gcloudignore` at the root controls what `gcloud builds submit` uploads. It must not exclude service folders.
- **Model files**, two patterns:
  1. **Bake at build time** from a private bucket. In GitHub Actions request a short-lived access token (`token_format: access_token` on `google-github-actions/auth`) and pass it as a BuildKit secret; it never enters build args or layer history. Do not hand the WIF credentials file to the build: it points at a token file on the runner that does not exist inside the build container, and parsing it fails.
  2. **Mount at runtime** with a Cloud Storage volume (`--add-volume=name=models,type=cloud-storage,bucket=<BUCKET>,readonly=true` plus `--add-volume-mount=volume=models,mount-path=/mnt/models`). The mount is read-only: anything the service must write goes to a local path.

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=gcs_token \
    GCS_TOKEN="$(cat /run/secrets/gcs_token)" python scripts/download_models.py --dest /models
```

```bash
# local build with your own credentials
GCS_TOKEN="$(gcloud auth print-access-token)" \
  docker build --secret id=gcs_token,env=GCS_TOKEN -t "$SERVICE:dev" -f services/$SERVICE/Dockerfile .
```

The download script builds `google.oauth2.credentials.Credentials(token=...)` and passes it to `storage.Client`. Version model folders in the bucket and never overwrite one in place.

## Local development

```bash
docker compose up -d                 # whole stack
docker compose logs -f <service>
docker compose down
```

- Make optional infrastructure optional in code: an unset `REDIS_URL` should disable caching, not crash startup (`redis_url: str | None = None` in settings).
- Point local services at a local PostgreSQL with pgvector, or at Cloud SQL through `cloud-sql-proxy`.

### Reaching a private Cloud Run service from a laptop (HTTP only)

```bash
# grant yourself invoker on that one service (prefer this over opening it up)
gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" --project "$PROJECT_ID" \
  --member="user:<YOUR_EMAIL>" --role="roles/run.invoker"

# tunnel: requests to localhost get your ID token attached
gcloud run services proxy "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --port 8080
curl -s http://127.0.0.1:8080/health

# remove the binding when done
gcloud run services remove-iam-policy-binding "$SERVICE" --region "$REGION" --project "$PROJECT_ID" \
  --member="user:<YOUR_EMAIL>" --role="roles/run.invoker"
```

`gcloud run services proxy` does not reliably forward WebSocket upgrades (the frontend answers 503 or "upstream connect error"). For a WebSocket service, run the server locally instead, and remember any Origin allow-list it enforces.

## Monitoring and health

```bash
# recent logs for a service
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE" \
  --project "$PROJECT_ID" --limit 50 --format='value(timestamp,severity,textPayload)'

# errors only
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE AND severity>=ERROR" \
  --project "$PROJECT_ID" --limit 20

# one revision, oldest first (startup failures)
gcloud logging read "resource.labels.service_name=$SERVICE AND resource.labels.revision_name=<REVISION>" \
  --project "$PROJECT_ID" --limit 100 --order=asc --format='value(textPayload)'

# what is serving right now
gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" \
  --format="value(status.latestCreatedRevisionName,status.latestReadyRevisionName,status.traffic)"
```

- Health endpoints: a cheap `/health` that never calls downstreams (liveness), plus readiness that reports model or dependency state. Cloud Run reserves some paths ending in `z` (such as `/healthz`) at its frontend; use `/health` for endpoints you call from outside. Container probes are not affected.
- Log as structured JSON to stdout so `severity` and fields are queryable; never log secrets, tokens or full request bodies with user data.
- Alert on: 5xx rate, p95 latency, instance count at `max-instances`, memory utilisation above 85 percent, and failed revisions.
- A public 200 is not proof of a successful deploy: Cloud Run keeps the last good revision serving when a new one fails. Use the silent-failure check in `cloud-run-deploy`.

## Post-deploy checklist

- Created revision equals ready revision for every deployed service.
- No startup errors or tracebacks in the new revision's logs.
- Model-serving services report ready within their startup-probe budget; memory stays below 85 percent of the limit.
- Health endpoints answer through the real caller path (the web app's proxy), not only directly.
- No rise in 5xx or latency for 30 minutes.

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| Revision fails with `Image ...:<sha> not found` | A deploy step referenced a tag that was never built (an unchanged service redeployed by a "deploy all" trigger). Resolve the tag first: use `:<sha>` if it exists, else the service's last built tag, else skip with a warning. Not a code bug. |
| New revision never becomes ready, old one keeps serving | Startup crash. Read the revision's logs oldest-first and `gcloud run revisions describe <REVISION> --format="value(status.conditions[].message)"`. Usual causes: missing import from a half-merged PR, a dependency incompatible with the Python version, a shared package not copied into the image. |
| `Container failed to start and listen on the port` | Bind `0.0.0.0:$PORT`; move slow initialisation off the startup path; lengthen the startup probe. |
| Exit code 137, `Memory limit exceeded`, logs stop mid model load | OOM. See [onnx-oom-troubleshooting](reference/onnx-oom-troubleshooting.md). |
| `403 Forbidden` from a private service | Caller's service account lacks `roles/run.invoker`, or the ID token audience is not the service's base URL. |
| `401` on a user endpoint although IAM passed | The ID token was sent in `Authorization` and replaced the user token. Send it in `X-Serverless-Authorization`. |
| WIF auth step fails in GitHub Actions | The job is missing `permissions: id-token: write`, or the provider's attribute condition does not match the repository. |
| `denied: Permission ... artifactregistry` on push | CI service account needs `roles/artifactregistry.writer`; run `gcloud auth configure-docker <REGION>-docker.pkg.dev`. |
| Cloud SQL `connection refused` | Runtime or CI service account needs `roles/cloudsql.client`; check the instance connection name and connector or proxy config. |
| CORS errors | Origin missing from the allow-list. `gcloud` splits `--set-env-vars` on commas: use `--set-env-vars='^@^CORS_ORIGINS=https://a.example,https://b.example'` (see `gcloud topic escaping`) or set it in Terraform. |
| `redirect_uri_mismatch` | The exact redirect URI is missing from the OAuth client. See [secrets-oauth-identity](reference/secrets-oauth-identity.md#oauth-client-configuration). |
| Foreign key to a table in another service's database | Cross-service foreign keys are not allowed; keep the ID column, drop the constraint, validate through the owning service's API. |
| GitHub jobs "not started because recent account payments have failed" | Account billing problem, not a workflow problem. |

## Data protection baseline

- Encryption in transit (Cloud Run TLS, Cloud SQL connector) and at rest are on by default; add CMEK only if a policy requires it.
- Cloud SQL automated backups and point-in-time recovery enabled; restore tested.
- Secret Manager and IAM changes are visible in Cloud Audit Logs; enable Data Access logs for Secret Manager in production.
- Retention and deletion of user data are implemented in the owning service, not by ad-hoc SQL.

## Lessons learned

- The live behaviour of a real request is the ground truth for whether a fix is deployed; a confusing image tag on a revision does not matter if the request shows the fix working.
- A read-only bucket mount cannot hold anything rebuilt at startup. Rebuild derived artefacts (indexes, lookup databases) from data baked into the image into a local writable path.
- When several people or sessions share one working tree, commit your files by explicit path and build the PR branch in a separate `git worktree` with `git cherry-pick`. Never `git stash -u` a tree holding someone else's work.
