# Manual deploy without the normal CI path

Three options, from least to most control. Any persistent config change made here must be back-ported to Terraform.

## Option A: re-run the deploy workflow (easiest)

```bash
gh workflow run deploy.yml --ref main          # uses the workflow's workflow_dispatch trigger
gh run list --workflow=deploy.yml --limit 1
gh run watch
```

Requires `on: workflow_dispatch` in the workflow. Add an input (for example `services: "api-users,api-billing"` or `all`) so one service can be redeployed without rebuilding everything.

## Option B: Cloud Build (build and deploy inside Google Cloud)

Useful when GitHub Actions is unavailable, or from a laptop with a slow uplink (the build runs in Google Cloud, not locally).

```bash
export SHORT_SHA=$(git rev-parse --short HEAD)
gcloud builds submit --config cloudbuild-<SERVICE>.yaml \
  --substitutions=_SHORT_SHA=${SHORT_SHA} --project <PROJECT_ID> .
```

A minimal `cloudbuild-<SERVICE>.yaml`:

```yaml
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-t", "${_IMAGE}:${_SHORT_SHA}", "-f", "services/<SERVICE>/Dockerfile", "."]
  - name: gcr.io/cloud-builders/docker
    args: ["push", "${_IMAGE}:${_SHORT_SHA}"]
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk:slim
    entrypoint: gcloud
    args: ["run", "services", "update", "<SERVICE>", "--image", "${_IMAGE}:${_SHORT_SHA}",
           "--region", "<REGION>"]
substitutions:
  _IMAGE: <REGION>-docker.pkg.dev/<PROJECT_ID>/<AR_REPO>/<SERVICE>
options:
  machineType: E2_HIGHCPU_8   # only for heavy builds; omit for the cheaper default
images: ["${_IMAGE}:${_SHORT_SHA}"]
```

The Cloud Build service account needs `artifactregistry.writer`, `run.developer`, and `iam.serviceAccountUser` on the service's runtime account.

## Option C: direct `gcloud run deploy` (full flags, no rebuild)

For a first deploy, or to recreate a service's config by hand in an emergency:

```bash
gcloud run deploy <SERVICE> \
  --image=<REGION>-docker.pkg.dev/<PROJECT_ID>/<AR_REPO>/<SERVICE>:<SHA> \
  --region=<REGION> --project=<PROJECT_ID> \
  --service-account=<SERVICE>-run@<PROJECT_ID>.iam.gserviceaccount.com \
  --no-allow-unauthenticated \
  --memory=1Gi --cpu=1 --min-instances=0 --max-instances=10 --cpu-boost \
  --concurrency=40 --timeout=300 \
  --set-env-vars=ENVIRONMENT=production,LOG_LEVEL=info \
  --set-secrets=DATABASE_URL=DATABASE_URL:latest,JWT_SECRET_KEY=JWT_SECRET_KEY:latest \
  --add-cloudsql-instances=<PROJECT_ID>:<REGION>:<INSTANCE> \
  --labels=env=prod,service=<SERVICE>
```

Notes:
- `--set-env-vars` and `--set-secrets` replace the whole list; `--update-env-vars` and `--update-secrets` merge. Use the `update` forms for a one-value change.
- Add `--network=<VPC> --subnet=<SUBNET> --vpc-egress=private-ranges-only` (Direct VPC egress) when the service must reach Memorystore or a private-IP database.
- Add `--no-traffic --tag candidate` to stage the revision without serving it (see section 3 of SKILL.md).

## Where config lives

| File | Purpose | Used by |
|------|---------|---------|
| `infra/terraform/services.tf` | Source of truth for every service's config | Terraform workflow |
| `.github/workflows/deploy.yml` | Builds images and swaps them on merge | Automatic |
| `.github/workflows/preview.yml` | Optional tagged no-traffic revisions per PR | Automatic on PR |
| `cloudbuild-<SERVICE>.yaml` | Manual build and deploy in Cloud Build | Option B |
