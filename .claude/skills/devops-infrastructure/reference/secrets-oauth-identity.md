# Secrets, OAuth, Service Accounts and Workload Identity Federation

## Contents

- Secret Manager
- GitHub secrets
- Non-sensitive configuration
- OAuth client configuration
- Service accounts
- Workload Identity Federation

## Secret Manager

Runtime secrets live in Secret Manager and are referenced by Cloud Run services by name. Typical set (names are conventions, not requirements):

| Secret | Purpose |
|--------|---------|
| `DATABASE_URL` | PostgreSQL connection string (or separate `DB_USER` / `DB_PASSWORD`) |
| `JWT_SECRET_KEY` | Signing key for application JWTs |
| `ENCRYPTION_KEY` | Field-level encryption key (for example a Fernet key) |
| `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` | Google OAuth client for user sign-in |
| `<PROVIDER>_API_KEY` | Third-party APIs that cannot use ADC (Vertex AI does not need a key) |
| `<PROVIDER>_WEBHOOK_SECRET` | Webhook signature verification |
| `INTERNAL_API_KEY` | Optional application-level secret between services, on top of IAM |
| `REDIS_URL` | Only if it embeds credentials |

Rules:
- Grant `roles/secretmanager.secretAccessor` per secret to the service accounts that need it, not project-wide.
- Mount as env vars by reference: `--set-secrets=JWT_SECRET_KEY=JWT_SECRET_KEY:latest`. A running instance caches the value from boot; rotation needs a new revision (see `cloud-run-deploy`).
- Applications fail fast at startup when a required secret is missing. No default fallback values.
- Never print a secret value into a terminal an agent or a recorder can see. Capture into a variable, write to a gitignored file, or pipe into the consumer. A `PreToolUse` Bash hook that rejects commands echoing secret values is a cheap way to enforce this.

```bash
gcloud secrets list --project <PROJECT_ID>
gcloud secrets versions list <SECRET> --project <PROJECT_ID> --limit 3     # confirms a version exists

# create the container once, then add versions with hidden input
gcloud secrets create <SECRET> --project <PROJECT_ID> --replication-policy=automatic
read -s -p "Value for <SECRET>: " V && printf '%s' "$V" | \
  gcloud secrets versions add <SECRET> --project <PROJECT_ID> --data-file=- && unset V

# grant one service account access to one secret
gcloud secrets add-iam-policy-binding <SECRET> --project <PROJECT_ID> \
  --member="serviceAccount:<SA_NAME>@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

When Terraform manages secrets, it owns the secret container and IAM; values are added out of band with `versions add` so they never enter Terraform state.

## GitHub secrets

GitHub Actions secrets are a separate store from Secret Manager. Keep them minimal: with WIF, CI needs only the provider resource name and the service-account email (neither is a secret, but storing them as secrets or variables keeps workflows generic).

```bash
gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --repo <OWNER>/<REPO>
gh secret set GCP_SERVICE_ACCOUNT --repo <OWNER>/<REPO>
gh secret list --repo <OWNER>/<REPO>

# organisation-wide, shared with selected or all repos
gh secret set <NAME> --org <ORG> --visibility selected --repos <REPO>
```

Anything CI needs at runtime beyond that (for example the database URL for migrations) should be read from Secret Manager inside the job through WIF, not duplicated into GitHub.

## Non-sensitive configuration

Plain env vars, set in Terraform: `ENVIRONMENT`, `LOG_LEVEL`, `FRONTEND_URL`, `CORS_ORIGINS`, downstream service URLs, model IDs.

`gcloud` splits `--set-env-vars` on commas. For a value that contains commas, switch the delimiter with the `^DELIM^` prefix (`gcloud topic escaping`):

```bash
gcloud run services update <SERVICE> --region <REGION> \
  --update-env-vars='^@^CORS_ORIGINS=https://app.example.com,http://localhost:3000@ENVIRONMENT=production'
```

Terraform needs no escaping, which is one more reason to keep config there.

## OAuth client configuration

The OAuth client ID and secret are created in the Google Cloud console (APIs and Services, Credentials) and stored in Secret Manager.

- **Authorized JavaScript origins**: every origin that starts the sign-in flow, for example `https://<DOMAIN>`, `https://www.<DOMAIN>`, `http://localhost:3000` (development only).
- **Authorized redirect URIs**: the exact callback URLs, including scheme, host, path and trailing slash, for example `https://<DOMAIN>/api/auth/callback/google`.
- Prefer routing callbacks through your own domain rather than a backend's `*.run.app` URL, so the URL does not change when a service is recreated.
- `redirect_uri_mismatch` always means the URI sent by the app is not in the list character for character. Copy the one from the error and compare.
- Keep separate OAuth clients for development and production.

## Service accounts

| Account | Purpose | Typical roles |
|---------|---------|---------------|
| `<SERVICE>-run@<PROJECT_ID>.iam.gserviceaccount.com` | Runtime identity of one Cloud Run service | `cloudsql.client`, `secretmanager.secretAccessor` (per secret), `aiplatform.user` if it calls Vertex AI, `run.invoker` on the services it calls |
| `web-run@<PROJECT_ID>.iam.gserviceaccount.com` | Runtime identity of the web front end | `run.invoker` on each backend it calls |
| `ci-deployer@<PROJECT_ID>.iam.gserviceaccount.com` | Impersonated by GitHub Actions through WIF | see below |

### CI deployer roles

| Role | Why |
|------|-----|
| `roles/artifactregistry.writer` | Push images (storage roles alone are not enough for Artifact Registry) |
| `roles/run.developer` (or `run.admin` if it manages IAM on services) | Deploy revisions |
| `roles/iam.serviceAccountUser` on each runtime service account | Deploy a service that runs as that account |
| `roles/cloudsql.client` | Run migrations through the Cloud SQL Auth Proxy |
| `roles/secretmanager.secretAccessor` on the secrets migrations need | Read the database URL during migrations |

Grant `iam.serviceAccountUser` on the specific runtime accounts rather than project-wide. Terraform's deployer usually needs broader roles (it manages IAM); keep it a separate service account from the image deployer.

## Workload Identity Federation

Keyless auth from GitHub Actions: GitHub issues an OIDC token, Google exchanges it for short-lived credentials of a service account. No JSON keys exist to leak.

| Resource | Example |
|----------|---------|
| Pool | `github-actions-pool` |
| Provider | `github-actions-provider` (issuer `https://token.actions.githubusercontent.com`) |
| Attribute mapping | `google.subject=assertion.sub`, `attribute.repository=assertion.repository`, `attribute.ref=assertion.ref` |
| Attribute condition | `attribute.repository == "<OWNER>/<REPO>"` (required; without it any repository could federate) |
| Service account | `ci-deployer@<PROJECT_ID>.iam.gserviceaccount.com` |

### Set up from scratch

```bash
PROJECT_ID=<PROJECT_ID>
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
SA_EMAIL="ci-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
REPO="<OWNER>/<REPO>"

gcloud iam service-accounts create ci-deployer --display-name="GitHub Actions deployer" --project "$PROJECT_ID"

for ROLE in roles/artifactregistry.writer roles/run.developer roles/cloudsql.client; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" --role="$ROLE" --condition=None
done

gcloud iam workload-identity-pools create github-actions-pool \
  --location=global --display-name="GitHub Actions" --project "$PROJECT_ID"

gcloud iam workload-identity-pools providers create-oidc github-actions-provider \
  --location=global --workload-identity-pool=github-actions-pool \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="attribute.repository==\"${REPO}\"" \
  --project "$PROJECT_ID"

gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" --project "$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository/${REPO}"
```

Then grant `roles/iam.serviceAccountUser` on each runtime service account and `secretAccessor` on the specific secrets, and store the provider resource name (`projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider`) and `SA_EMAIL` as GitHub secrets. Better still, create all of this in Terraform.

To restrict production deploys to `main`, tighten the condition (`attribute.repository == "<OWNER>/<REPO>" && attribute.ref == "refs/heads/main"`) or bind a separate production service account to a principal set filtered on the ref.

### Workflow usage

```yaml
permissions:
  contents: read
  id-token: write

steps:
  - uses: google-github-actions/auth@<PINNED_SHA>
    with:
      workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
      service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}
  - uses: google-github-actions/setup-gcloud@<PINNED_SHA>
```

Some third-party deploy actions expect a raw JSON key and do not work with WIF. Use the provider's own CLI after the auth step instead; CLIs built on Google client libraries pick up the federated credentials through ADC.
