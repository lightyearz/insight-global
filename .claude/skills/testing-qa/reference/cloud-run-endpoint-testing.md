# Testing Cloud Run endpoints

## Contents

- Rule: test the service, not the public site
- Local stack (no IAM)
- Deployed service with your own identity token
- Impersonating a service account
- Proxying a private service to localhost
- Smoke tests in pytest
- Smoke tests in GitHub Actions (Workload Identity Federation)
- Load tests against a private service
- Troubleshooting

Placeholders: `<PROJECT_ID>`, `<REGION>`, `<SERVICE>`, `<PORT>`, `<SA_EMAIL>`. The IAM model behind all of this (runtime service accounts, per-service `roles/run.invoker`, minting tokens in code) is in the `backend-architect` and `cloud-run-deploy` skills.

## Rule: test the service, not the public site

Backend services run with `--no-allow-unauthenticated`. The public web app's server (or a load balancer / hosting rewrite) is the only invoker, so curling the public domain's `/api/*` routes with your own token either returns 403 or tests three layers at once. Test the service URL directly, or the whole stack locally.

## Local stack (no IAM)

```bash
docker compose up -d
curl -fsS http://localhost:<PORT>/api/v1/health
```

Use this for development and for anything that writes data.

## Deployed service with your own identity token

Your user account needs `roles/run.invoker` on the service (grant it on staging, not as a standing production permission).

```bash
SERVICE_URL=$(gcloud run services describe <SERVICE> --region=<REGION> \
  --project=<PROJECT_ID> --format='value(status.url)')

TOKEN=$(gcloud auth print-identity-token)   # valid for about one hour
curl -fsS -H "Authorization: Bearer $TOKEN" "$SERVICE_URL/api/v1/health"

gcloud auth list                             # confirm which account is active
```

If the endpoint also requires an application-level user JWT, send the ID token in `X-Serverless-Authorization` (Cloud Run checks that header first) and the user JWT in `Authorization`:

```bash
curl -fsS -H "X-Serverless-Authorization: Bearer $TOKEN" \
  -H "Authorization: Bearer <USER_JWT>" "$SERVICE_URL/api/v1/me"
```

## Impersonating a service account

Reproduce exactly what a calling service sees by minting a token as its runtime service account (you need `roles/iam.serviceAccountTokenCreator` on that account):

```bash
TOKEN=$(gcloud auth print-identity-token \
  --impersonate-service-account=<SA_EMAIL> \
  --audiences="$SERVICE_URL" \
  --include-email)
curl -fsS -H "Authorization: Bearer $TOKEN" "$SERVICE_URL/api/v1/health"
```

A 403 here while your personal token works means the caller's invoker binding is missing: the bug is in IAM, not in the code.

## Proxying a private service to localhost

```bash
gcloud run services proxy <SERVICE> --region=<REGION> --project=<PROJECT_ID> --port=8080
curl -fsS http://localhost:8080/api/v1/health
```

The proxy attaches your credentials to every request, which is convenient for browser tools, Postman, or a local frontend pointed at a deployed backend.

## Smoke tests in pytest

```python
# tests/smoke/test_deployed_health.py
import os

import httpx
import pytest

SERVICE_URL = os.environ.get("SERVICE_URL", "")

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(not SERVICE_URL, reason="SERVICE_URL not set"),
]


def _id_token() -> str:
    """Prefer a token injected by CI; fall back to the metadata server or a SA key."""
    if token := os.environ.get("ID_TOKEN"):
        return token
    import google.auth.transport.requests
    import google.oauth2.id_token

    return google.oauth2.id_token.fetch_id_token(
        google.auth.transport.requests.Request(), SERVICE_URL
    )


def test_health_when_deployed_should_return_200() -> None:
    response = httpx.get(
        f"{SERVICE_URL}/api/v1/health",
        headers={"Authorization": f"Bearer {_id_token()}"},
        timeout=30.0,  # allow for a cold start
    )
    assert response.status_code == 200
```

`fetch_id_token` cannot mint a token from end-user ADC (`gcloud auth application-default login`). Locally, export `ID_TOKEN=$(gcloud auth print-identity-token)` instead. Register the `smoke` marker in `pyproject.toml` and exclude it from the default run (`-m "not smoke"`).

## Smoke tests in GitHub Actions (Workload Identity Federation)

```yaml
smoke:
  runs-on: ubuntu-latest
  needs: deploy
  permissions:
    contents: read
    id-token: write          # required for Workload Identity Federation
  steps:
    - uses: actions/checkout@v4
    - id: auth
      uses: google-github-actions/auth@v2
      with:
        workload_identity_provider: ${{ vars.WIF_PROVIDER }}   # projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/<POOL>/providers/<PROVIDER>
        service_account: ${{ vars.SMOKE_TEST_SA }}
        token_format: id_token
        id_token_audience: ${{ vars.SERVICE_URL }}
        id_token_include_email: true
    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"
    - run: pip install httpx pytest
    - run: pytest tests/smoke -m smoke -v
      env:
        SERVICE_URL: ${{ vars.SERVICE_URL }}
        ID_TOKEN: ${{ steps.auth.outputs.id_token }}
```

The smoke-test service account needs `roles/run.invoker` on the target service only, and the federated GitHub principal must be allowed to impersonate it (`roles/iam.workloadIdentityUser`, plus token-creator rights where your setup requires them). No JSON keys. In CI, set `SERVICE_URL` so the tests run rather than skip.

## Load tests against a private service

Run against staging. ID tokens last about an hour, so either keep runs shorter than that, refresh the token in the script, or point the tool at `gcloud run services proxy`.

```javascript
// k6: SERVICE_URL=... ID_TOKEN=$(gcloud auth print-identity-token) k6 run load.js
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  stages: [
    { duration: '1m', target: 20 },
    { duration: '3m', target: 20 },
    { duration: '1m', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
  },
};

export default function () {
  const res = http.get(`${__ENV.SERVICE_URL}/api/v1/items`, {
    headers: { Authorization: `Bearer ${__ENV.ID_TOKEN}` },
  });
  check(res, { 'status is 200': (r) => r.status === 200 });
}
```

While it runs, watch instance count, CPU, memory and request latency in Cloud Monitoring, and note cold-start latency separately from steady-state latency. Locust works the same way: put the token in the default headers of the `HttpUser` client.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| 403, no log line from the app | Caller lacks `roles/run.invoker`, or the token audience is not the service URL |
| 401 from Cloud Run | Missing or expired token, or an access token sent instead of an ID token |
| 401/403 with an app log line | IAM passed; the application's own auth rejected the request |
| Google-branded 404 on a health path | Path is reserved by Cloud Run; avoid paths ending in `z` (such as `/healthz`) and anything under `/_ah/` |
| First request slow or times out, later ones fast | Cold start; raise the client timeout or set minimum instances on staging |
| Works locally, 500 when deployed | Missing env var or secret, or the runtime service account lacks access to a dependency; check the service logs |
