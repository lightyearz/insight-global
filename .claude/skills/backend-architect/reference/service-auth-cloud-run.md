# Service-to-service auth on Cloud Run

## Contents

- The two-layer model
- IAM setup: runtime service accounts and invoker bindings
- Minting ID tokens in Python (with caching)
- Minting ID tokens from a Next.js server
- Preserving the end-user token: X-Serverless-Authorization
- Local development and impersonation
- App-level checks: user JWTs and internal-only endpoints
- Testing private services
- Guardrails in CI
- Common failures

## The two-layer model

```
Browser --(user session)--> Next.js server --(OIDC ID token + user JWT)--> FastAPI service A
                                                                              |
                                                       (OIDC ID token) -------+--> FastAPI service B
```

1. **Cloud Run IAM** rejects any request without a valid Google-signed ID
   token from a principal holding `roles/run.invoker` on that service. This
   happens before your container sees the request.
2. **Application auth** inside FastAPI decides what the caller may do: end-user
   JWT validation and per-endpoint authorization, or an internal-only check.

The browser never calls backend services directly. Server-side code (Next.js
route handlers or server actions) is the only public entry point.

## IAM setup: runtime service accounts and invoker bindings

- Give every service its own runtime service account
  (`gcloud run deploy <SERVICE> --service-account=<SERVICE_SA_EMAIL> ...`).
  Do not run on the default compute service account; it is usually far more
  privileged than any one service needs.
- Grant `roles/run.invoker` **per target service** to exactly the callers that
  need it, never project-wide:

```bash
gcloud run services add-iam-policy-binding <TARGET_SERVICE> \
  --region=<REGION> \
  --member="serviceAccount:<CALLER_SA_EMAIL>" \
  --role="roles/run.invoker"
```

- Manage these bindings in IaC next to the service definition, so the call
  graph is reviewable in one place.
- Services called only from inside your VPC can additionally use
  `--ingress=internal` (callers must send their egress through the VPC), or
  `internal-and-cloud-load-balancing` when fronted by a load balancer.

## Minting ID tokens in Python (with caching)

On Cloud Run, `google.oauth2.id_token.fetch_id_token` gets a token for the
service's runtime account from the metadata server. Tokens last about an hour;
cache per audience and refresh early. The call is synchronous, so keep it off
the event loop.

```python
# app/infrastructure/auth.py
import asyncio
import time

import google.auth.transport.requests
import google.oauth2.id_token


class TokenProvider:
    """Mints and caches Google-signed OIDC ID tokens, one per audience."""

    _LIFETIME_S = 3600
    _REFRESH_MARGIN_S = 300

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled            # False for local docker-compose targets
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()
        self._request = google.auth.transport.requests.Request()

    async def token_for(self, audience: str) -> str | None:
        if not self._enabled:
            return None
        async with self._lock:
            now = time.monotonic()
            cached = self._cache.get(audience)
            if cached and cached[1] - now > self._REFRESH_MARGIN_S:
                return cached[0]
            token = await asyncio.to_thread(
                google.oauth2.id_token.fetch_id_token, self._request, audience
            )
            self._cache[audience] = (token, now + self._LIFETIME_S)
            return token
```

- **Audience** is the target service's URL origin
  (`https://<SERVICE_URL>`), with no path. If you call through a custom domain
  or load balancer, either mint the token for the service URL or register the
  other audience on the service with `--add-custom-audiences`.
- Callers only add the `Authorization` header when `token_for` returns a token,
  so the same client code works against `localhost` and Cloud Run.

## Minting ID tokens from a Next.js server

On Cloud Run the metadata server is the cheapest source:

```ts
// lib/server-fetch.ts (server-only)
const METADATA_IDENTITY_URL =
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity";

async function getIdentityToken(audience: string): Promise<string> {
  const res = await fetch(
    `${METADATA_IDENTITY_URL}?audience=${encodeURIComponent(audience)}&format=full`,
    { headers: { "Metadata-Flavor": "Google" }, cache: "no-store" },
  );
  if (!res.ok) throw new Error(`metadata server returned ${res.status}`);
  return res.text();
}

export async function serverFetch(url: string, init?: RequestInit): Promise<Response> {
  const onCloudRun = typeof process.env.K_SERVICE === "string";
  if (!onCloudRun) return fetch(url, init);            // local: plain fetch to localhost

  const token = await getIdentityToken(new URL(url).origin);
  const headers = new Headers(init?.headers);
  if (headers.has("Authorization")) {
    headers.set("X-Serverless-Authorization", `Bearer ${token}`);  // keep the user's token
  } else {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(url, { ...init, headers });
}
```

Cache tokens per audience here too if call volume is high. If token minting
fails, surface a clear 502/503 from the route handler rather than silently
sending an unauthenticated request.

## Preserving the end-user token: X-Serverless-Authorization

Cloud Run accepts the IAM token in either `Authorization` or
`X-Serverless-Authorization`. When a proxy forwards an end-user request, send
the IAM token in `X-Serverless-Authorization` and leave the user's JWT in
`Authorization` for FastAPI to validate. The app must never treat the presence
of the IAM token as proof of who the end user is.

## Local development and impersonation

- Default local setup: all services in docker compose on `localhost`, IAM
  disabled (`TokenProvider(enabled=False)`), app-level auth still on.
- User credentials from `gcloud auth application-default login` cannot mint
  audience-scoped ID tokens through `fetch_id_token`. To call a deployed
  service from a laptop, impersonate a service account that holds
  `roles/run.invoker` (the developer needs
  `roles/iam.serviceAccountTokenCreator` on it):

```bash
gcloud auth print-identity-token \
  --impersonate-service-account=<INVOKER_SA_EMAIL> \
  --audiences=https://<SERVICE_URL> \
  --include-email
```

```python
import google.auth
import google.auth.transport.requests
from google.auth import impersonated_credentials

source, _ = google.auth.default()
target = impersonated_credentials.Credentials(
    source_credentials=source,
    target_principal="<INVOKER_SA_EMAIL>",
    target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
    lifetime=900,
)
id_creds = impersonated_credentials.IDTokenCredentials(
    target, target_audience="https://<SERVICE_URL>", include_email=True
)
id_creds.refresh(google.auth.transport.requests.Request())
token = id_creds.token
```

Never download service account key files for this. Impersonation leaves an
audit trail and nothing to leak.

## App-level checks: user JWTs and internal-only endpoints

End-user JWTs (PyJWT):

```python
import jwt

payload = jwt.decode(
    token,
    key,                                   # public key (PEM, or resolved from JWKS)
    algorithms=["RS256"],                  # pin the algorithm; never read it from the token
    audience=settings.jwt_audience,
    issuer=settings.jwt_issuer,
    options={"require": ["exp", "iat", "sub", "iss", "aud"]},
)
```

- With an external identity provider, resolve keys via
  `jwt.PyJWKClient(<JWKS_URL>).get_signing_key_from_jwt(token).key` and cache
  the client.
- If you sign tokens yourself with a shared secret (`settings.jwt_secret`),
  pin `algorithms=["HS256"]` and pass `jwt_secret.get_secret_value()` as the
  key. Never allow both HMAC and RSA algorithms for the same token type.
- Return a generic 401 with `WWW-Authenticate: Bearer` on any failure.
- After decoding, load the user and check status or role in one shared
  dependency; routes depend on `get_current_user`, never on raw claims.

Internal-only endpoints (called by other services, never by users) add a
second check on top of IAM. A shared key works if it is handled correctly:

```python
import hmac

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


async def require_internal_caller(
    x_internal_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.internal_api_key.get_secret_value()
    if (
        not expected                       # empty config never means "open"
        or not x_internal_api_key
        or not hmac.compare_digest(x_internal_api_key.encode(), expected.encode())
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
```

- Compare bytes: `hmac.compare_digest` raises `TypeError` on non-ASCII `str`
  input, which a crafted header can trigger.
- Write this dependency once in the shared package. Copy-pasted checks drift,
  and one of them ends up using `!=`.
- Store the key in Secret Manager and rotate it by accepting two keys
  (current and next) during the changeover.

## Testing private services

```bash
# your user account needs roles/run.invoker on the service
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://<SERVICE_URL>/api/v1/health/ready

# or proxy the service to localhost with your credentials
gcloud run services proxy <SERVICE> --region=<REGION> --port=8080
curl http://localhost:8080/api/v1/health/ready
```

Do not test backend behaviour by curling the production web app's public API
routes; that path adds the proxy and real user sessions and hides which layer
failed. Test the service URL directly, or the full stack locally.

## Guardrails in CI

Make "no public services" a check, not a convention:

```bash
# fail the build if any deploy config makes a Cloud Run service public
if grep -rnE -- '--allow-unauthenticated' .github/ infra/ 2>/dev/null \
     | grep -v -- '--no-allow-unauthenticated'; then
  echo "Public Cloud Run service found"; exit 1
fi
# with Terraform, also reject allUsers / allAuthenticatedUsers invoker bindings
if grep -rnE 'allUsers|allAuthenticatedUsers' infra/ 2>/dev/null; then
  echo "Public IAM member found"; exit 1
fi
```

At the organisation level, the domain-restricted sharing policy
(`iam.allowedPolicyMemberDomains`) blocks `allUsers` bindings outright.

## Common failures

| Symptom | Likely cause |
|---|---|
| 403 from Cloud Run, no app log line | Caller lacks `roles/run.invoker` on the target, or token audience does not match the service URL |
| 401 from Cloud Run | Missing, expired, or non-ID (access) token |
| 401 from the app, IAM fine | IAM token sent in `Authorization`, overwriting the user's JWT; use `X-Serverless-Authorization` |
| Works locally, 403 in Cloud Run | Local run skipped IAM; the deployed caller's runtime SA was never granted invoker |
| `DefaultCredentialsError` / no ID token locally | User ADC cannot mint ID tokens; use impersonation or local services |
