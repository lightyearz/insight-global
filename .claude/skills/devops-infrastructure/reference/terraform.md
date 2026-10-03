# Terraform for Cloud Run infrastructure

Terraform is the single source of truth for persistent infrastructure config. CI deploys new images; Terraform owns everything else.

## Layout

```
infra/terraform/
  main.tf            provider, GCS backend, shared locals (project, region, labels)
  services.tf        google_cloud_run_v2_service per service: CPU, memory, scaling, env, secrets, probes, volumes
  jobs.tf            google_cloud_run_v2_job for batch and scheduled work
  secrets.tf         google_secret_manager_secret containers (values are added out of band)
  iam.tf             runtime service accounts, invoker bindings, secret accessor bindings, WIF
  registry.tf        Artifact Registry repository and cleanup policies
  variables.tf       project, region, per-service image tags
  outputs.tf         service URLs (consumed by other services' env vars)
  terraform.tfvars   non-secret overrides
```

- State lives in a versioned GCS bucket (`backend "gcs"`) with uniform bucket-level access; never commit state or plan files.
- Mark irreplaceable resources (`google_secret_manager_secret`, Cloud SQL instances) with `lifecycle { prevent_destroy = true }`.
- Set `deletion_protection` on Cloud SQL and on Cloud Run v2 services as appropriate.
- Label every resource (`env`, `service`, `team`, `cost-center`) through a shared `locals` map; labels flow into the billing export.

## Workflow

`.github/workflows/terraform.yml`:
- **On PR**: `terraform fmt -check`, `terraform validate`, `terraform plan`; post the plan as a PR comment.
- **On merge to main**: `terraform apply` of the reviewed plan (or `-auto-approve` for a small team that reviews the PR plan).
- Authenticates through WIF with its own service account (broader than the image deployer because it manages IAM).

Rules:
- To change CPU, memory, scaling, env vars, secrets or probes: edit `services.tf`, open a PR, read the plan.
- To add a secret: add the `google_secret_manager_secret` and its accessor bindings, merge, then add the value with `gcloud secrets versions add` (hidden input). Values never enter Terraform state.
- To add a service: add the service, its runtime service account, its secret bindings, and an invoker binding for each caller. Never an `allUsers` invoker on a backend; CI should reject one.
- An emergency `gcloud run deploy` with config flags is overwritten by the next apply unless back-ported. Back-port the same day.

## CI deploys images, Terraform owns config

Two writers on one service will fight unless the split is explicit:

```hcl
resource "google_cloud_run_v2_service" "api" {
  name     = "<SERVICE>"
  location = var.region

  template {
    service_account = google_service_account.api.email
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/<AR_REPO>/<SERVICE>:${var.image_tags["<SERVICE>"]}"
      resources {
        limits            = { cpu = "1", memory = "1Gi" }
        startup_cpu_boost = true
      }
      env {
        name = "JWT_SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt.secret_id
            version = "latest"
          }
        }
      }
      startup_probe {
        http_get { path = "/health" }
        period_seconds    = 5
        failure_threshold = 24
      }
    }
  }

  lifecycle {
    # CI swaps images; Terraform must not roll them back on the next apply
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
}
```

Either ignore the image as above, or have CI pass the new tag into `terraform apply` (`var.image_tags`). Pick one model per repository and document it.

- Mount secrets with `version = "latest"` so a rotation plus a new revision picks up the value; a pinned version needs a Terraform change on every rotation.
- If you split traffic manually (canary), Terraform's `traffic` block will reset it on the next apply. Either manage traffic in Terraform or leave the `traffic` block out and ignore it.
