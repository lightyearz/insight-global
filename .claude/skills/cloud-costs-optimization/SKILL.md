---
name: cloud-costs-optimization
description: Analyses and reduces Google Cloud spend for a Cloud Run based platform - billing export queries and labels, the Cloud Run billing model (request-based versus instance-based billing, minimum instances, concurrency, startup CPU boost), right-sizing memory and CPU for API, worker and model-serving services, build costs (Cloud Build machine types versus GitHub Actions, layer caching), Artifact Registry cleanup policies, Cloud SQL, Memorystore and VPC connector costs, logging ingestion, Cloud Run Jobs for batch work, and budgets and alerts. Use when reviewing a bill, deciding minimum instances or instance sizes, comparing build strategies, planning cost-efficient scaling, estimating the cost of a new service, or setting up budgets. For LLM token pricing and model choice use llm-models-expert.
---

# Cloud Costs and Optimization (Google Cloud)

Find where the money goes, then cut it without breaking latency or reliability. This skill holds methods and trade-offs, not prices: prices and free allotments change, so read the current pricing pages and your own billing export before quoting a number.

Placeholders: `<PROJECT_ID>`, `<REGION>`, `<AR_REPO>`, `<BILLING_ACCOUNT_ID>`, `<BILLING_DATASET>`.

> Service sizing and scaling live in Terraform. The `gcloud` commands below are for investigation and emergencies; make lasting changes in Terraform (`devops-infrastructure`).

## Related skills

| Need | Skill |
|------|-------|
| Token prices, model choice, routing to cheaper models | `llm-models-expert` |
| Service sizing, Terraform, CI design | `devops-infrastructure` |
| Applying a change safely and verifying it | `cloud-run-deploy` |
| Model memory, quantization, background loading | `ai-ml-engineering` |

## Cost review workflow

1. **Get facts, not estimates.** Enable the Cloud Billing export to BigQuery (detailed usage cost) and group by service, SKU and label (query below).
2. **Inventory** what is always on: Cloud Run services with `min-instances` above 0 or instance-based billing, Cloud SQL tier and HA, Memorystore size, VPC connectors, Artifact Registry size, log volume.
3. **Rank** by spend and pick the top three drivers. Ignore anything below a few percent of the bill.
4. **Change one thing at a time** through Terraform, with a note of the expected saving and the latency or reliability risk.
5. **Verify** in the next billing cycle and against latency and error dashboards. Revert if the user-facing cost was higher than the saving.

```sql
-- top services and SKUs for one invoice month, net of credits
SELECT
  service.description AS service,
  sku.description     AS sku,
  ROUND(SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS net_cost
FROM `<PROJECT_ID>.<BILLING_DATASET>.gcp_billing_export_v1_<BILLING_ACCOUNT_SUFFIX>`
WHERE invoice.month = '<YYYYMM>'
GROUP BY service, sku
ORDER BY net_cost DESC
LIMIT 25;

-- the same by service label (requires labels on resources)
SELECT l.value AS service_label, ROUND(SUM(cost), 2) AS cost
FROM `<PROJECT_ID>.<BILLING_DATASET>.gcp_billing_export_v1_<BILLING_ACCOUNT_SUFFIX>`, UNNEST(labels) l
WHERE l.key = 'service' AND invoice.month = '<YYYYMM>'
GROUP BY service_label ORDER BY cost DESC;
```

## The usual cost drivers

1. **Always-on instances.** `min-instances >= 1` on every service, including ones nobody calls on the hot path. With instance-based billing (`--no-cpu-throttling`) the CPU is billed for the whole instance lifetime, not only during requests.
2. **Large-memory model services.** An API and a worker built from the same image that both load the same models, each sized for them and both kept warm.
3. **Build compute.** Oversized Cloud Build machines, no layer cache (every build reinstalls every dependency), and pipelines that pay twice: a GitHub Actions runner that only calls `gcloud builds submit`.
4. **Unbounded image storage.** Every build pushes a new SHA tag and nothing deletes old ones; ML images are gigabytes each.
5. **Idle data services.** Cloud SQL with HA and a tier sized for future growth; Memorystore sized for a load that has not arrived; development and staging instances running around the clock.
6. **Networking.** Serverless VPC Access connectors run instances whether or not traffic flows; cross-region traffic between services and their database.
7. **Logging.** Every health check and request logged at INFO, plus verbose debug logs left on.
8. **LLM tokens.** At scale, usually the largest variable cost. See `llm-models-expert`.

## How Cloud Run bills (concepts)

- **Request-based billing (default):** CPU and memory are billed while an instance handles requests and during startup and shutdown. Idle minimum instances are billed at a lower idle rate. There is a monthly free allotment.
- **Instance-based billing (`--no-cpu-throttling`):** the whole instance lifetime is billed, at a lower unit rate. Required for work that runs outside a request (background loops, consumers). Cheaper than request-based billing only for consistently busy services.
- **Minimum instances** buy away cold starts and cost money every hour. Use them only on the latency-critical path, or for services whose cold start is long (model loading).
- **Startup CPU boost (`--cpu-boost`)** shortens cold starts for little cost; it is what makes `min-instances=0` acceptable for many APIs.
- **Concurrency** sets how many requests share an instance. I/O-bound FastAPI services can usually go well above the default; CPU-bound model inference usually needs a low value. Higher concurrency means fewer instances.
- **Maximum instances** caps runaway spend and protects database connection limits. Set it on every service.
- Memory and CPU are coupled: large memory limits require more vCPUs, so a memory-hungry model can force a CPU cost too.
- Committed use discounts are available for steady baseline usage once traffic is predictable.

## Playbook

### Quick wins (minutes, low risk)

**A. `min-instances=0` plus startup CPU boost off the hot path.** Services that tolerate a few seconds of cold start: admin tools, data export, webhooks, low-traffic CRUD.

```bash
gcloud run services update <SERVICE> --region <REGION> --project <PROJECT_ID> --min-instances 0 --cpu-boost
```

**B. Right-size from metrics, not guesses.** In Metrics Explorer, check `run.googleapis.com/container/cpu/utilizations` and `container/memory/utilizations` at p95 over two weeks. CPU below about 20 percent at p95: halve it. Memory below about 50 percent at peak: step down one size, keeping 15-20 percent headroom for model services.

**C. Artifact Registry cleanup policy.** Keep the last N versions per image and delete untagged or old ones. Always dry-run first.

```json
[
  {"name": "keep-recent", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 10}},
  {"name": "delete-old", "action": {"type": "Delete"}, "condition": {"tagState": "any", "olderThan": "30d"}}
]
```

```bash
gcloud artifacts repositories set-cleanup-policies <AR_REPO> --project <PROJECT_ID> --location <REGION> \
  --policy=cleanup-policy.json --dry-run
# dry-run mode evaluates the policies and records would-be deletions in Cloud Audit Logs without deleting;
# review those entries, then rerun with --no-dry-run to enforce
```

Keep policies win over delete policies, so the last N versions survive even when old.

**D. `max-instances` on every service**, sized to what the database and downstream quotas can take.

**E. Budgets and alerts** at several thresholds, including forecasted spend:

```bash
gcloud billing budgets create --billing-account=<BILLING_ACCOUNT_ID> --display-name="<PROJECT_ID> monthly" \
  --budget-amount=<AMOUNT><CURRENCY> --filter-projects=projects/<PROJECT_ID> \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0 --threshold-rule=percent=1.0,basis=forecasted-spend
```

**F. Drop noisy logs before ingestion.**

```bash
gcloud logging sinks update _Default --project <PROJECT_ID> \
  --add-exclusion=name=health-checks,filter='resource.type="cloud_run_revision" AND httpRequest.requestUrl:"/health"'
```

### Medium wins (hours to days)

**G. Build in GitHub Actions, deploy to Cloud Run.** Build and push images on the runner with Buildx, then `gcloud run services update --image`. Keep Cloud Build for manual deploys only.
Trade-offs: standard runners have fewer vCPUs than a large Cloud Build machine, so cold builds are slower; layer caching recovers most of it; builds do not need VPC access.

**H. Layer caching**, wherever builds run:

```yaml
- uses: docker/setup-buildx-action@<PINNED_SHA>
- uses: docker/build-push-action@<PINNED_SHA>
  with:
    cache-from: type=gha,scope=<SERVICE>
    cache-to: type=gha,mode=max,scope=<SERVICE>
```

Order the Dockerfile so dependency installation comes before copying source; otherwise every commit busts the cache.

**I. Cloud Build machine type.** Use the default machine for light builds; reserve high-CPU machines for heavy ML images where the time saved matters. Check which machine types the free build minutes cover.

**J. Direct VPC egress** instead of a Serverless VPC Access connector, for services that only need to reach private IPs (Memorystore, private Cloud SQL): no connector instances to pay for.

**K. Turn non-production off when idle.** `min-instances=0` everywhere outside production; stop development databases out of hours (`gcloud sql instances patch <INSTANCE> --activation-policy=NEVER`, and `ALWAYS` to start); no HA outside production.

### Big wins (architecture changes, plan carefully)

**L. Do not run two warm copies of the same models.** If an API service and a worker load the same models, either merge the worker into the API (background tasks in-process; needs memory headroom and careful testing) or move periodic work to **Cloud Run Jobs** triggered by Cloud Scheduler, which bill only while running.

```bash
gcloud run jobs create <JOB> --image=<REGION>-docker.pkg.dev/<PROJECT_ID>/<AR_REPO>/<SERVICE>:<SHA> \
  --region <REGION> --memory=1Gi --cpu=1 --task-timeout=600 --max-retries=1 \
  --command=python --args=-m,app.jobs.<JOB_MODULE>
```

**M. Smaller or quantized models.** INT8 ONNX, a distilled encoder, or plain `onnxruntime` without PyTorch can drop a service a whole memory tier (`ai-ml-engineering`).

**N. Model files: baked in the image or mounted from Cloud Storage.** Baking gives the fastest, most predictable cold start but slow builds and large images. A read-only Cloud Storage volume gives small images and fast builds; the first load reads over the network, so cold starts get longer. Bucket storage itself is cheap; the cost is in cold-start latency.

**O. LLM spend.** Route easy requests to a cheaper model, cap output tokens, cache repeated prompts and context, batch offline work. Estimate per-request token cost before launch (`llm-models-expert`).

## Decision matrix

| Change | Effort | Risk | Typical impact |
|--------|--------|------|----------------|
| `min-instances=0` + `--cpu-boost` off the hot path | Minutes | Low (cold starts) | High when many services idle |
| Right-size CPU and memory from metrics | Hours | Low | Medium |
| Artifact Registry cleanup policy | Minutes | None after dry run | Low, stops growth |
| `max-instances` everywhere | Minutes | Low | Caps worst case |
| Budgets and alerts | Minutes | None | Early warning |
| Health-check log exclusion | Minutes | Low | Low to medium |
| Builds in GitHub Actions with layer cache | Hours | Medium (pipeline change) | Medium |
| Direct VPC egress instead of a connector | Hours | Medium (networking) | Low to medium |
| Non-production off when idle | Hours | Low | Medium |
| Merge duplicate model services or move work to Jobs | Days | High (memory, behaviour) | High for ML-heavy stacks |
| Quantized or smaller models | Days | Medium (quality, needs evals) | High for ML-heavy stacks |

## Estimating cost before it happens

Work it out from unit prices on the pricing page for your region and billing mode; write the formula down next to the decision.

- **Baseline (idle) cost per service** = minimum instances x (vCPU x idle vCPU rate + GiB x idle memory rate) x seconds per month.
- **Per-request cost** = (vCPU x vCPU rate + GiB x memory rate) x busy seconds per request / effective concurrency + request fee + LLM tokens per request x token price.
- **Monthly** = baseline + per-request cost x monthly requests + data services (Cloud SQL tier, storage, HA) + networking + logging + builds and storage.
- Model growth in steps, not lines: the jumps come from a database tier or HA upgrade, a larger cache, extra regions, and the point where autoscaling adds instances for every service at once.
- Re-run the estimate at each traffic milestone and compare with the billing export.

## Investigation commands

```bash
# Cloud Run inventory: name, min, max, CPU throttling, CPU, memory
gcloud run services list --region <REGION> --project <PROJECT_ID> --format=json | jq -r '
  .[] | [.metadata.name,
         (.spec.template.metadata.annotations["autoscaling.knative.dev/minScale"] // "0"),
         (.spec.template.metadata.annotations["autoscaling.knative.dev/maxScale"] // "-"),
         (.spec.template.metadata.annotations["run.googleapis.com/cpu-throttling"] // "true"),
         .spec.template.spec.containers[0].resources.limits.cpu,
         .spec.template.spec.containers[0].resources.limits.memory] | @tsv'

# recent builds and their machine types
gcloud builds list --project <PROJECT_ID> --limit 20 \
  --format="table(id,status,createTime,finishTime,options.machineType)"

# Artifact Registry repository size and newest images
gcloud artifacts repositories list --project <PROJECT_ID> --location <REGION> --format="table(name,sizeBytes)"
gcloud artifacts docker images list <REGION>-docker.pkg.dev/<PROJECT_ID>/<AR_REPO> \
  --include-tags --sort-by=~createTime --limit 20

# Cloud SQL tiers and availability
gcloud sql instances list --project <PROJECT_ID> \
  --format="table(name,settings.tier,settings.availabilityType,settings.activationPolicy)"

# budgets already defined
gcloud billing budgets list --billing-account=<BILLING_ACCOUNT_ID>
```

Log ingestion by resource: Metrics Explorer, metric `logging.googleapis.com/billing/bytes_ingested`.

## Labels

Label every resource so the billing export can split cost by environment and service: `env`, `service`, `team`, `cost-center`. Set them in a shared Terraform `locals` map; for a one-off: `gcloud run services update <SERVICE> --region <REGION> --update-labels=env=prod,service=<SERVICE>`.

## Guardrails for an early-stage platform

1. `min-instances=0` everywhere except the latency-critical path and slow-loading model services.
2. Build in CI with layer caching; do not pay a second build system to sit in the middle.
3. Artifact Registry with cleanup policies from day one.
4. Budgets with actual and forecasted alerts from day one.
5. `max-instances` on every service.
6. Labels on everything, the billing export on, and a short monthly review against the dashboard.
7. Re-evaluate committed use discounts once the baseline is stable for a few months.
