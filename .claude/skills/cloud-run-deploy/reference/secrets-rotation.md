# Secret rotation on Cloud Run

## Contents

- Rules
- Update a value with hidden input
- Roll services onto the new version
- Retire the old version
- A rotation script, in outline
- GitHub Actions secrets

## Rules

- Secret containers are defined in Terraform (`secrets.tf`, with `prevent_destroy`). Values are added out of band, never through Terraform, so they never land in state.
- Paste real values only through hidden input (`read -s`). `echo -n "value" | ...` puts the secret in shell history and in anything that records the terminal, including an agent transcript. Keep `echo` for non-secret placeholders.
- Use `printf '%s'`, not `echo -n`: some shells print the literal `-n`, and `printf '%s'` never adds a trailing newline.
- Never print a secret to check it. Check that a version exists (`versions list`) or compare a hash.

## Update a value with hidden input

```bash
read -s -p "Paste new value for <SECRET>: " V && echo "got ${#V} chars" && \
  printf '%s' "$V" | gcloud secrets versions add <SECRET> --project <PROJECT_ID> --data-file=- && \
  unset V && echo DONE

# one value into several secrets (when different services read different names)
read -s -p "Paste value: " V && \
  for S in <SECRET_A> <SECRET_B>; do
    printf '%s' "$V" | gcloud secrets versions add "$S" --project <PROJECT_ID> --data-file=- || break
  done && unset V && echo DONE

# confirm the new version is now latest
gcloud secrets versions list <SECRET> --project <PROJECT_ID> --limit 3
```

## Roll services onto the new version

Cloud Run resolves a secret when an instance starts and caches it. A service that mounts `<SECRET>:latest` keeps the old value until it gets a new revision.

```bash
# find every service that references the secret (env var or volume)
SECRET=<SECRET>
for svc in $(gcloud run services list --region <REGION> --project <PROJECT_ID> --format='value(metadata.name)'); do
  gcloud run services describe "$svc" --region <REGION> --project <PROJECT_ID> --format=json \
    | jq -e --arg s "$SECRET" '[.spec.template.spec.containers[].env[]?.valueFrom.secretKeyRef.name,
                                  .spec.template.spec.volumes[]?.secret.secretName] | index($s) != null' \
      >/dev/null && echo "$svc"
done

# create a new revision for each affected service
gcloud run services update <SERVICE> --region <REGION> --project <PROJECT_ID> \
  --update-env-vars=SECRETS_ROTATED_AT=$(date -u +%Y%m%dT%H%M%SZ)
```

Any config change creates a new revision; bumping a harmless env var is a reliable way to force one. Terraform drops that variable on its next apply, which creates one more revision and is harmless.

If a service pins a version (`<SECRET>:7`), a new revision does not pick up the rotation: update the pin in Terraform. Prefer `:latest` mounts so rotation is a value change plus a restart.

Also restart anything else that reads the secret: Cloud Run Jobs, workers, and CI jobs that fetch it.

## Retire the old version

`versions add` is non-destructive: the previous version stays enabled.

```bash
# once the new value has worked in production for about a day
gcloud secrets versions disable <OLD_VERSION> --secret=<SECRET> --project <PROJECT_ID>
# after a further grace period, if nothing broke
gcloud secrets versions destroy <OLD_VERSION> --secret=<SECRET> --project <PROJECT_ID>
```

Disabling first gives a one-command way back (`versions enable`). Destroy is permanent.

For a signing key (JWT), plan an overlap: verify with both old and new keys for one token lifetime, sign with the new one, then remove the old key.

## A rotation script, in outline

Worth having as `scripts/rotate-secret.sh <SECRET> [--project=..] [--region=..] [--yes]`:

1. Hidden-input paste; reject empty input; print the length only.
2. Confirm the secret exists.
3. Discover affected services (the loop above) and show them.
4. Ask for confirmation before adding a version, so an aborted run does not burn one.
5. Add the version.
6. Create a new revision for each affected service, in parallel.
7. Report per-service success or failure with the new revision name, then run the created-equals-ready check from SKILL.md.

It does not handle GitHub secrets or version-pinned mounts; say so in its help text.

## GitHub Actions secrets

A separate store, read by workflows. With Workload Identity Federation, CI should need very few.

```bash
gh secret set <NAME> --repo <OWNER>/<REPO>              # prompts for the value, hidden
gh secret set <NAME> --org <ORG> --visibility selected --repos <REPO>
gh secret list --repo <OWNER>/<REPO>
```

Workflows pick up a new value on their next run. When a value lives in both stores, update both in the same change window, or better, have CI read it from Secret Manager through WIF.
