---
name: cloud-run-deploy
description: Runbook for deploying Python FastAPI and Next.js services to Google Cloud Run - the pull-request release flow through GitHub Actions, manual image and config deploys, safe rollouts with no-traffic tagged revisions and gradual traffic splits, fast rollback, post-deploy checks that catch revisions which never became ready, health checks against private IAM-protected services, invoker grants between services, secret rotation, database migrations in CI, and adding a new service. Use when deploying, rolling out or rolling back a service, checking whether a deploy actually took effect, rotating a secret, granting one service access to another, or setting up a new Cloud Run service. For architecture, CI design, Workload Identity Federation and deeper troubleshooting use devops-infrastructure.
---

# Cloud Run Deploy Runbook

Copy-paste commands for shipping, verifying and undoing changes on Cloud Run. Background and design live in `devops-infrastructure`; spend questions in `cloud-costs-optimization`.

Set the placeholders once per shell:

```bash
export PROJECT_ID=<PROJECT_ID> REGION=<REGION> SERVICE=<SERVICE> AR_REPO=<AR_REPO>
export SHA=$(git rev-parse --short HEAD)
export IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPO/$SERVICE:$SHA"
```

> Terraform owns service config (CPU, memory, scaling, env, secrets, IAM). Use the `gcloud` config flags below only in an emergency and back-port the change to Terraform the same day, or the next apply reverts it.

## Reference files (load on demand)

- [Manual deploy without CI](reference/manual-deploy.md): re-run the workflow, Cloud Build, or a direct `gcloud run deploy` with full flags.
- [Secret rotation](reference/secrets-rotation.md): hidden-input updates, rolling services onto the new version, disabling old versions, GitHub secrets.
- [Database migrations in CI](reference/alembic-migrations.md): Alembic through the Cloud SQL Auth Proxy, common failures and fixes.
- [New service setup](reference/new-service-setup.md): checklist from Dockerfile to first verified deploy.

## 1. Normal release: pull request, merge, CI deploys

Direct pushes to `main` are blocked; the merge triggers the deploy workflow.

```bash
git checkout -b feat/<short-name>          # fix/, chore/, docs/, ci/, perf/, security/, build/, refactor/, test/, style/
git add <files>                             # explicit paths, never the whole tree
git commit -m "feat(<scope>): <summary>"
git push -u origin feat/<short-name>
gh pr create --title "feat(<scope>): <summary>" --body "## Summary
- ...

## Test plan
- [ ] ..."
gh pr checks <PR_NUMBER> --watch
gh pr merge <PR_NUMBER> --squash --delete-branch

# follow the deploy
gh run list --workflow=deploy.yml --limit 1
gh run watch
```

After the run finishes, do section 5. A green workflow is not proof that new code is serving.

## 2. Deploy one image by hand

```bash
# image only, keep the current config
gcloud run services update "$SERVICE" --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID"
```

For a first deploy or a full-flag deploy, see [manual-deploy](reference/manual-deploy.md). Backends always carry `--no-allow-unauthenticated`.

## 3. Safe rollout: no-traffic revision, smoke test, shift gradually

```bash
# 1. deploy without traffic, reachable only through a tag URL
gcloud run deploy "$SERVICE" --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" \
  --no-traffic --tag candidate

# 2. smoke-test the candidate directly (your account needs roles/run.invoker)
TAG_URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --format=json \
  | jq -r '.status.traffic[] | select(.tag=="candidate") | .url')
curl -sf -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$TAG_URL/health"

# 3. shift traffic in steps, watching errors and latency between steps
gcloud run services update-traffic "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --to-tags candidate=10
gcloud run services update-traffic "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --to-tags candidate=50

# 4. finish: send everything to the latest revision and resume "follow latest"
gcloud run services update-traffic "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --to-latest
gcloud run services update-traffic "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --remove-tags candidate
```

Errors for one revision while traffic is split:

```bash
gcloud logging read "resource.labels.service_name=$SERVICE AND resource.labels.revision_name=<REVISION> AND severity>=ERROR" \
  --project "$PROJECT_ID" --limit 20 --freshness=15m
```

- Use this flow for model changes, risky dependency bumps and anything touching auth.
- Tag URLs are still private: they need an ID token like the main URL.
- If Terraform manages the service's `traffic` block, the next apply resets a manual split. Finish the rollout before applying, or manage traffic in Terraform.

## 4. Rollback

```bash
gcloud run revisions list --service "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --limit 5
gcloud run services update-traffic "$SERVICE" --region "$REGION" --project "$PROJECT_ID" \
  --to-revisions <PREVIOUS_REVISION>=100
```

- Rollback is a traffic change: seconds, no rebuild.
- While traffic is pinned to a revision, check where the next deploy's traffic goes (`gcloud run services describe "$SERVICE" --format="value(status.traffic)"`) and return to `--to-latest` once the fix is out.
- Code rollback does not undo migrations. Migrations are written to be backward compatible (expand, then contract) so the previous revision keeps working against the new schema.
- Roll back the web front end the same way; it is just another service.

## 5. Verify the deploy actually took effect

Cloud Run keeps the last healthy revision serving when a new revision fails its startup probe: the deploy "succeeded", public health checks return 200, and no new code is running.

```bash
for svc in <SERVICE_A> <SERVICE_B> <SERVICE_C>; do
  read -r created ready < <(gcloud run services describe "$svc" --region "$REGION" --project "$PROJECT_ID" \
    --format="value(status.latestCreatedRevisionName,status.latestReadyRevisionName)")
  [ "$created" = "$ready" ] && echo "OK      $svc -> $ready" || echo "BROKEN  $svc created=$created serving=$ready"
done
```

Run it after every deploy and every Terraform apply (a config-only change can surface an unrelated startup bug). When a revision is broken:

```bash
gcloud run revisions describe <CREATED_REVISION> --region "$REGION" --project "$PROJECT_ID" \
  --format="value(status.conditions[].message)"

gcloud logging read "resource.labels.service_name=$SERVICE AND resource.labels.revision_name=<CREATED_REVISION>" \
  --project "$PROJECT_ID" --limit 100 --order=asc --format='value(textPayload)' \
  | grep -iE "error|exception|modulenotfound|importerror|traceback|memory limit" | head -20

# which image is actually serving
gcloud run revisions describe <READY_REVISION> --region "$REGION" --project "$PROJECT_ID" --format=json \
  | jq -r '.spec.containers[0].image'
```

Usual root causes: an import of a module that was never committed (half-merged PR); a pinned dependency that does not support the image's Python version; a shared internal package not copied or installed in the image; a missing secret or missing `secretAccessor` grant; the app not listening on `0.0.0.0:$PORT`; an out-of-memory kill during model load; `Image ...:<sha> not found` (a tagging problem, see `devops-infrastructure`).

## 6. Health checks against private services

```bash
# directly, with your identity token (you need roles/run.invoker on the service)
URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')
curl -sf -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL/health"

# or through a local authenticated tunnel
gcloud run services proxy "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --port 8080

# best signal: through the real caller path (the web app's server-side proxy route)
curl -sf "https://<DOMAIN>/api/<SERVICE>/health"
```

The caller-path check proves the caller's service account still has `roles/run.invoker` and that its proxy route works. Do not open a service to `allUsers` to test it; a `PreToolUse` Bash hook that rejects `allUsers` invoker grants is a cheap way to make that impossible.

## 7. Let one service call another

```bash
gcloud run services add-iam-policy-binding <TARGET_SERVICE> --region "$REGION" --project "$PROJECT_ID" \
  --member="serviceAccount:<CALLER_SA>@$PROJECT_ID.iam.gserviceaccount.com" --role="roles/run.invoker"
```

Then add the binding to Terraform. The caller mints an ID token with the target's base URL as audience (`backend-architect`, `frontend-developer`).

## 8. Emergency config change

```bash
gcloud run services update "$SERVICE" --region "$REGION" --project "$PROJECT_ID" \
  --memory 2Gi --cpu 2 --min-instances 1 --max-instances 5 --cpu-boost

gcloud run services update "$SERVICE" --region "$REGION" --project "$PROJECT_ID" \
  --update-env-vars LOG_LEVEL=debug --update-secrets JWT_SECRET_KEY=JWT_SECRET_KEY:latest
```

Values that contain commas need the `^@^` delimiter syntax (`gcloud topic escaping`). Back-port to Terraform.

## 9. WebSocket and streaming services

- Deploy with `--session-affinity` and `--timeout` up to 3600 seconds; connections still end at the timeout, so clients reconnect with backoff.
- Tune `--concurrency` to what one instance can hold open; keep `min-instances` at 1 or more if reconnect storms after scale-to-zero hurt.
- `gcloud run services proxy` does not reliably forward WebSocket upgrades. Test WebSocket servers by running them locally.

## Post-deploy checklist

- [ ] PR checks green and the deploy run finished.
- [ ] Section 5 reports `OK` for every deployed service.
- [ ] No errors or tracebacks in the new revisions' startup logs.
- [ ] Health checks pass through the real caller path.
- [ ] Model-serving services ready within their probe budget; memory below about 85 percent of the limit.
- [ ] No rise in 5xx rate or p95 latency for 30 minutes.
- [ ] The web front end loads and the changed feature works end to end.

## Pull-request mechanics that save time

- When one PR has become a superset of several overlapping PRs, retitle it to the combined scope and merge it with a merge commit (`gh pr merge <N> --merge --delete-branch`) so each commit stays traceable; close the subset PRs with "superseded by #N".
- `gh pr merge --delete-branch` fails its local cleanup step when the working tree has uncommitted changes, but the remote merge still succeeds. Confirm with `gh pr view <N> --json state,mergedAt`.
- To cut a clean PR out of a shared or messy working tree without touching it: `git worktree add ../clean <BASE_SHA>`, then in that worktree `git checkout -b <branch> && git cherry-pick <SHAS> && git push -u origin <branch>`, and `gh pr create --head <branch>`.
- If a service rebuilds derived data (indexes, lookup databases) at startup from files baked into its image, a normal deploy refreshes it; no manual rebuild-and-upload step.
