# New Cloud Run service checklist

From an empty folder to a first verified deploy. Infrastructure goes into Terraform; the commands are for checking the result.

1. **Code and image**: `services/<SERVICE>/` with a multi-stage `Dockerfile` (non-root user, pinned base image, listens on `0.0.0.0:$PORT`), `.dockerignore`, a cheap `/health`, and a readiness endpoint if it loads models. Layout: `backend-architect`.
2. **CI build**: add the service to the change-detection filters and the build matrix in `.github/workflows/deploy.yml`, and to the security scans (pip-audit, Trivy, hadolint).
3. **Terraform**, in one PR:
   - a runtime service account `<SERVICE>-run@<PROJECT_ID>.iam.gserviceaccount.com`;
   - `secretAccessor` on exactly the secrets it reads, `cloudsql.client` if it uses Cloud SQL, `aiplatform.user` if it calls Vertex AI;
   - the `google_cloud_run_v2_service` with CPU, memory, scaling, env, secrets, startup probe and labels;
   - `roles/run.invoker` for each caller's service account (the web app, other services). Never `allUsers` for a backend;
   - `iam.serviceAccountUser` on the runtime account for the CI deployer.
4. **First image**: merge, or build and push once by hand, so the first apply has an image to point at.
5. **Callers**: add the service's URL to each caller's config (a Terraform output feeding an env var), and for the web app a server-side proxy route that attaches an ID token (`frontend-developer`).
6. **Verify**:

```bash
gcloud run services describe <SERVICE> --region <REGION> --project <PROJECT_ID> \
  --format="value(status.url,status.latestReadyRevisionName)"

URL=$(gcloud run services describe <SERVICE> --region <REGION> --project <PROJECT_ID> --format='value(status.url)')
curl -sf -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL/health"

# unauthenticated must be refused
curl -s -o /dev/null -w '%{http_code}\n' "$URL/health"     # expect 401 or 403, never 200
```

7. **Operate**: add it to the created-equals-ready check, the dashboards and alerts, and the cost labels. Decide `min-instances` deliberately (`cloud-costs-optimization`).
