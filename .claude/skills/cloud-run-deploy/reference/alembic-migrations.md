# Database migrations in CI (Alembic + Cloud SQL)

Migration authoring (models, autogenerate review, expand / contract) is in the `backend-architect` skill. This file covers running migrations during deploy and fixing the failures that block it.

## How the deploy job runs migrations

1. Installs the owning service's requirements plus any shared internal package its models import. Missing either one fails with `ModuleNotFoundError`.
2. Authenticates through WIF and reads `DATABASE_URL` (and any key the models need at import time) from Secret Manager into job-scoped env vars.
3. Starts the Cloud SQL Auth Proxy on `127.0.0.1:5432` and waits for it with a `pg_isready` loop (about 30 seconds maximum).
4. `alembic/env.py` turns the application's async URL (`postgresql+asyncpg://...`) into a sync one for the migration run.
5. Compares `alembic current` with `alembic heads` and skips `upgrade head` when already at head.
6. Runs `alembic upgrade head` before any new revision serves traffic.

The CI service account needs `roles/cloudsql.client` and `roles/secretmanager.secretAccessor` on the secrets it reads.

```bash
# adding a migration (from the directory that holds alembic.ini for the owning service)
alembic revision --autogenerate -m "<description>"
# read and fix the generated file, then
alembic upgrade head && alembic downgrade -1 && alembic upgrade head   # against a local database
```

## Connecting by hand

```bash
cloud-sql-proxy <PROJECT_ID>:<REGION>:<INSTANCE> --port 5433 &
PROXY=$!
until pg_isready -h 127.0.0.1 -p 5433 -q; do sleep 1; done
PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -p 5433 -U <DB_USER> -d <DB_NAME> \
  -c "SELECT version_num FROM alembic_version;"
kill $PROXY
```

Load `DB_PASSWORD` into a variable (`DB_PASSWORD=$(gcloud secrets versions access latest --secret=<SECRET> --project <PROJECT_ID>)`) rather than printing it.

## Failures and fixes

| Error | Cause and fix |
|-------|---------------|
| `Requested revision X overlaps with other requested revisions Y` | More than one row in `alembic_version`, usually because several Alembic configurations once shared one database. Find the true head with `alembic heads` in the canonical migrations directory, back up, then delete every other row: `DELETE FROM alembic_version WHERE version_num <> '<TRUE_HEAD>';`. Give each service its own `version_table` if they must share a database. |
| `ModuleNotFoundError: app.<...>.models.<name>` | A half-merged PR: an `__init__.py` or `env.py` imports a module that was never committed. Find it with `git log -S "from .<name>" -- <path>`; restore the file or remove the import. |
| `No module named <package>` | The migration job did not install a shared package the models import. Install it in the same step as the service requirements. |
| `Fernet key must be 32 url-safe base64-encoded bytes` | `ENCRYPTION_KEY` is not a valid Fernet key; generate one with `Fernet.generate_key()` and rotate it in properly. |
| `connection refused` on the proxy port | The CI service account lacks `roles/cloudsql.client`, the instance connection name is wrong, or the job did not wait for the proxy. |
| `Multiple head revisions are present` | Two branches each added a migration with the same parent. Create a merge revision (`alembic merge -m "merge heads" <REV_A> <REV_B>`) or renumber one, below. |

## Renumbering a migration safely

When a restored or rebased migration collides with one already on `main` (both claim the same parent):

1. Rename the file so its prefix sorts after the current head.
2. Set `revision` to the new ID and `down_revision` to the current head.
3. Run `alembic history` and confirm one straight chain to the new head.
4. Keep idempotency guards (check that a table or column exists before creating it) so the migration is safe if part of it was already applied out of band.
