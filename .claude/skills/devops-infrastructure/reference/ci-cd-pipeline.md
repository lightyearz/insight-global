# CI/CD Pipeline (GitHub Actions + Cloud Run)

## Contents

- Branch protection and naming
- Quality gates
- Security scanning
- Dependency updates
- Build and deploy workflow
- Image tags: never deploy a tag that was not built
- WIF in workflows
- Cloud Build as a secondary path
- Config files
- Deploy order after large changes
- Ignore files

## Branch protection and naming

- Direct pushes to `main` are blocked; every change goes through a pull request with required checks.
- Branch prefixes follow Conventional Commits: `feat/`, `fix/`, `chore/`, `docs/`, `ci/`, `perf/`, `security/`, `build/`, `refactor/`, `test/`, `style/`.
- Security-sensitive paths (workflows, IaC, auth code, Dockerfiles) have required reviewers in `.github/CODEOWNERS`.

## Quality gates

| Gate | Tool | Blocks merge |
|------|------|--------------|
| Python lint and format | `ruff check`, `ruff format --check` | Yes |
| Python tests | `pytest` per service | Yes |
| Frontend types and lint | `npm run type-check`, `npm run lint` | Yes |
| Docker images build | `docker/build-push-action` | Yes |
| Secret scanning | gitleaks (full history) + GitHub push protection | Yes |
| Dockerfile lint | hadolint | Yes |
| IaC plan | `terraform plan` posted to the PR | Yes (must succeed) |
| No public services | grep / policy check for `--allow-unauthenticated` and `allUsers` invoker bindings | Yes |
| Python CVEs | pip-audit per service | Report only |
| Container CVEs | Trivy (CRITICAL / HIGH) | Report only |
| npm advisories | `npm audit --audit-level=high` | Report only |

Promote a report-only gate to blocking once its baseline is clean; a gate that is always red trains people to ignore it.

## Security scanning

A dedicated `security-scan.yml` runs on every PR, on pushes to `main`, and on a weekly schedule (new CVEs appear without code changes):

- **gitleaks**: whole git history, not only the diff.
- **pip-audit**: each service's pinned requirements against the OSV database.
- **Trivy**: each built image; upload SARIF to code scanning so findings are tracked.
- **hadolint**: every Dockerfile.
- **npm audit**: the web app.

## Dependency updates

Dependabot (`.github/dependabot.yml`) opens weekly PRs for each Python service (pip), the web app (npm), Docker base images, and GitHub Actions.

Triage rules:
- Patch and minor bumps with green CI: merge.
- A bump already superseded by `main`: close it with a comment.
- Pre-release versions: do not ship them to production services.
- Major runtime bumps (a new Python base image): hold until the ML wheel stack (torch, transformers, onnxruntime, and similar) is confirmed to install and import on the new version.

## Build and deploy workflow

Merging to `main` runs `deploy.yml`:

1. **detect changes**: which services changed (path filters), plus "deploy all" when a shared package or the workflow itself changed.
2. **build images**: Buildx with registry or GHA layer cache; push `<REGION>-docker.pkg.dev/<PROJECT_ID>/<AR_REPO>/<SERVICE>:<SHA>`. Third-party actions are pinned to a commit SHA.
3. **migrate**: `alembic upgrade head` against Cloud SQL through the Cloud SQL Auth Proxy, before any new code serves traffic. Migrations must be backward compatible with the running code (expand / contract, see `backend-architect`).
4. **deploy backends**: image-only update per changed service, in parallel (`gcloud run services update <SERVICE> --image=...`). Config (CPU, memory, env, secrets) belongs to Terraform.
5. **verify**: created revision equals ready revision for each service, then health checks through the real caller path.
6. **deploy web**: build and deploy the Next.js service last.
7. **cleanup**: Artifact Registry cleanup policies prune old images; avoid custom delete scripts.

Building in GitHub Actions and pushing to Artifact Registry avoids paying for a second build system; Cloud Build stays available for manual config deploys.

## Image tags: never deploy a tag that was not built

A "deploy all" trigger that redeploys an unchanged service with `:<SHA>` fails, because that service's image was not rebuilt in this run: the revision fails with `Image ...:<sha> not found` and the service is stuck on its previous revision. Resolve the tag per service:

```bash
resolve_image() {
  local svc="$1" base="<REGION>-docker.pkg.dev/<PROJECT_ID>/<AR_REPO>/$1"
  if gcloud artifacts docker images describe "$base:$SHA" >/dev/null 2>&1; then
    echo "$base:$SHA"
  elif gcloud artifacts docker images describe "$base:latest" >/dev/null 2>&1; then
    echo "$base:latest"   # last built image for an unchanged service
  else
    echo "WARNING: no image for $svc, skipping" >&2; return 1
  fi
}
```

Skip with a warning rather than failing the whole deploy for a service that did not change. A revision failing with "image not found" is a tagging or ordering problem, not a code crash.

## WIF in workflows

Every job that calls `google-github-actions/auth` needs:

```yaml
permissions:
  contents: read
  id-token: write   # lets the job request a GitHub OIDC token
```

This applies to every such job, including cleanup and migration jobs. Without it the auth step fails. Setup of the pool, provider and service account is in the "Secrets, OAuth, service accounts and WIF" reference linked from SKILL.md.

When a build needs to read a private bucket (model files), request an access token and pass it as a BuildKit secret:

```yaml
- id: auth
  uses: google-github-actions/auth@<PINNED_SHA>
  with:
    workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
    service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}
    token_format: access_token
- uses: docker/build-push-action@<PINNED_SHA>
  with:
    secrets: |
      gcs_token=${{ steps.auth.outputs.access_token }}
```

## Cloud Build as a secondary path

Use Cloud Build for a manual build-and-deploy from a laptop or when GitHub Actions is unavailable:

```bash
export SHORT_SHA=$(git rev-parse --short HEAD)
gcloud builds submit --config cloudbuild-<SERVICE>.yaml \
  --substitutions=_SHORT_SHA=${SHORT_SHA} --project <PROJECT_ID> .
```

Pick the machine type deliberately: the default small machine is cheap but slow; a high-CPU machine shortens ML image builds. See `cloud-costs-optimization`.

## Config files

| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | Lint, type-check and tests on every PR |
| `.github/workflows/deploy.yml` | Build, migrate, deploy and verify on merge to `main` |
| `.github/workflows/preview.yml` | Optional preview deploys per PR (tagged revisions with no traffic) |
| `.github/workflows/security-scan.yml` | gitleaks, pip-audit, Trivy, hadolint, npm audit |
| `.github/workflows/terraform.yml` | Plan on PR, apply on merge |
| `.github/dependabot.yml` | Dependency update PRs |
| `.github/CODEOWNERS` | Required reviewers for sensitive paths |
| `SECURITY.md` | Vulnerability disclosure policy |
| `cloudbuild-<SERVICE>.yaml` | Manual Cloud Build path |

## Deploy order after large changes

1. Database migrations (always first, always backward compatible).
2. Services that own data other services read.
3. Services that call them.
4. Model-serving services (longest builds; verify readiness before shifting traffic).
5. The web front end, last.

## Ignore files

1. `.gcloudignore` (root): controls what `gcloud builds submit` uploads. Must not exclude service folders or shared packages.
2. `.dockerignore` (per build context): controls what `COPY` can see. Exclude `.git`, `node_modules`, virtualenvs, caches, local data, and every `.env*` file.
