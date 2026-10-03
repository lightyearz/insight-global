# SQLAlchemy 2.0 async + Alembic on Cloud SQL

## Contents

- Engine, sessions, and transactions
- Connecting to Cloud SQL from Cloud Run
- Connection pool sizing
- Models and naming conventions
- Async pitfalls
- Alembic setup (env.py)
- Day-to-day migration workflow
- Autogenerate blind spots and review checklist
- Zero-downtime changes (expand/contract)
- Running migrations in CI/CD
- pgvector

## Engine, sessions, and transactions

```python
# app/infrastructure/db.py
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

engine = create_async_engine(
    get_settings().database_url.get_secret_value(),
    pool_size=5,
    max_overflow=2,
    pool_timeout=10,
    pool_pre_ping=True,     # survive idle connections dropped while CPU was throttled
    pool_recycle=1800,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
```

- One session per request, injected with `Depends(get_session)`.
- The application layer owns the transaction boundary
  (`async with session.begin(): ...` inside the use case), so a use case
  commits or rolls back as one unit regardless of how many repositories it
  touches.
- `expire_on_commit=False` keeps returned objects readable after commit
  without an implicit (and in async, failing) refresh.

## Connecting to Cloud SQL from Cloud Run

| Option | How | Notes |
|---|---|---|
| Unix socket | Deploy with `--add-cloudsql-instances=<PROJECT_ID>:<REGION>:<INSTANCE>`; URL `postgresql+asyncpg://<USER>:<PASSWORD>@/<DB>?host=/cloudsql/<PROJECT_ID>:<REGION>:<INSTANCE>` | Simplest; password lives in Secret Manager |
| Cloud SQL Python Connector | `create_async_engine("postgresql+asyncpg://", async_creator=getconn)` with `connector.connect_async(..., "asyncpg", enable_iam_auth=True)` | Supports IAM database auth, which removes the DB password secret; the IAM DB user is the service account email without `.gserviceaccount.com` |
| Private IP | Direct VPC egress to the instance's private IP | Needs VPC setup; useful when also reaching other private resources |

Whichever you choose, give each service its own runtime service account with
`roles/cloudsql.client` (and `roles/cloudsql.instanceUser` for IAM DB auth),
and its own database role with grants limited to the tables it owns.

## Connection pool sizing

Cloud Run scales instances horizontally, and every instance has its own pool:

```
services x max_instances x (pool_size + max_overflow) + admin/migration headroom  <  max_connections
```

- Cap `max_instances` per service deliberately; it is a database-protection
  setting as much as a cost setting.
- With request concurrency of, say, 80 and a pool of 5, requests wait on the
  pool rather than opening connections. Set `pool_timeout` so they fail fast.
- `NullPool` (a new connection per checkout) keeps idle connections at zero
  but adds connection latency to every request; use it for jobs and scripts,
  rarely for request-serving services.

## Models and naming conventions

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

Deterministic constraint names are what let `downgrade()` drop the right
constraint. Set the convention before the first migration; retrofitting it
later means renaming existing constraints.

Use typed `Mapped[...]` / `mapped_column(...)` declarations, timezone-aware
timestamps (`DateTime(timezone=True)`, `server_default=func.now()`), and UUID
or bigint primary keys consistently across services.

## Async pitfalls

- **Lazy loading raises in async** (`MissingGreenlet`). Load relationships
  explicitly with `selectinload` / `joinedload`; set `lazy="raise"` on
  relationships so a missed eager load fails in tests, not production.
- **Never share one `AsyncSession` across concurrent tasks** (for example
  inside `asyncio.gather`). Give each task its own session.
- **Keep blocking calls off the event loop.** Sync SDK calls (some Google
  client libraries, token minting) go through `asyncio.to_thread`.
- **Parameterise everything.** `text()` queries use bound parameters
  (`text("... WHERE id = :id").bindparams(id=item_id)`), never f-strings.

## Alembic setup (env.py)

```python
# alembic/env.py (essentials)
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.infrastructure.db_base import Base
import app.infrastructure.models  # noqa: F401  imports EVERY model module

config = context.config
target_metadata = Base.metadata

# Migrations use a sync driver; the app uses asyncpg.
url = os.environ["MIGRATIONS_DATABASE_URL"]
config.set_main_option("sqlalchemy.url", url)


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()
```

Rules:

- **Import every model module.** A model that is not imported is invisible
  to autogenerate, which then proposes `drop_table` for it. Keep a single
  `models/__init__.py` that imports them all.
- Use a dedicated `MIGRATIONS_DATABASE_URL` (sync driver, for example
  `postgresql+psycopg://...`) instead of string-rewriting the app URL. In CI it
  points at the Auth Proxy on `localhost`.
- Do not put fallback credentials or keys in `env.py` to make imports work.
  If importing models drags in settings that require secrets, decouple the
  models module from settings, or supply real values from CI.
- Alembic also ships an async template (`alembic init -t async`) that runs
  migrations through an async engine with `run_sync`; either approach is fine.
- **Shared database, per-service Alembic:** give each service its own
  `version_table` (`alembic_version_<service>`) and an `include_object` filter
  limited to its own tables, so autogenerate never touches another service's
  tables.

## Day-to-day migration workflow

```bash
# after changing a model in the owning service
alembic revision --autogenerate -m "add_status_to_orders"
# READ the generated file in alembic/versions/ and fix it, then:
alembic upgrade head

alembic downgrade -1        # verify the downgrade works locally
alembic upgrade head
alembic current             # where the DB is
alembic history --verbose   # the chain
alembic check               # fails if models and migrations disagree
```

- Messages are imperative and specific; one logical change per revision.
- Keep history linear. If a merge produces two heads, rebase your revision's
  `down_revision` onto the new head rather than adding a merge revision,
  unless both branches already shipped.
- Data migrations do not import application ORM models (they change over
  time). Use `sa.table()` / `sa.column()` lightweight constructs or bound
  `op.execute(sa.text(...))`.
- Long-running statements on large tables: set
  `op.execute("SET lock_timeout = '5s'")` at the top so a migration waiting
  on a lock fails instead of blocking live traffic behind it.
- Indexes on large live tables: create them concurrently, outside the
  migration transaction:

```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_orders_customer_id", "orders", ["customer_id"],
            postgresql_concurrently=True,
        )
```

## Autogenerate blind spots and review checklist

Autogenerate does not reliably detect:

- table or column **renames** (it emits drop + add, which loses data)
- changes to Postgres ENUM values
- free-standing CHECK constraints and some primary-key changes
- anonymously named constraints (hence the naming convention)
- server default changes unless `compare_server_default=True`

Custom column types (pgvector, citext, ...) render with their module path; add
the import to the migration file or to `script.py.mako`.

Review checklist for every migration:

- [ ] Only tables owned by this service are touched
- [ ] No drop + add pairs that should be a rename
- [ ] `downgrade()` reverses `upgrade()` and has been run locally
- [ ] Additive and backward-compatible with the currently deployed code
- [ ] New NOT NULL columns have a server default or follow expand/contract
- [ ] Large-table operations use `lock_timeout`, batching, or `CONCURRENTLY`
- [ ] Exactly one head after the change

## Zero-downtime changes (expand/contract)

During a Cloud Run rollout old and new revisions serve traffic at the same
time, and a rollback simply routes traffic back to the old revision. So the
schema must work with **both** the current and the previous code.

1. **Expand** (migration, deployed before code): add nullable columns, new
   tables, new indexes. Nothing the old code depends on changes.
2. **Migrate code**: deploy code that writes both old and new shapes and reads
   the new shape with a fallback.
3. **Backfill**: batched, idempotent, resumable; run as a job, not inside a
   request.
4. **Enforce**: add constraints once data is clean. For NOT NULL on a big
   table: add `CHECK (col IS NOT NULL) NOT VALID`, then `VALIDATE CONSTRAINT`,
   then `SET NOT NULL` (Postgres can use the validated check to skip a full
   scan), then drop the check.
5. **Contract** (a later release): drop the old column or table once no
   deployed revision reads it.

Renames follow the same path: add new, dual-write, backfill, switch reads,
drop old. Never rename a live column in place.

## Running migrations in CI/CD

**On pull requests**, against a disposable Postgres service container (use a
pgvector-enabled image if you use vectors):

```bash
test "$(alembic heads | wc -l)" -eq 1          # single head
alembic upgrade head && alembic downgrade base && alembic upgrade head
alembic check                                   # models match migrations
```

**On deploy**, before the new revision takes traffic. Two good patterns:

- *GitHub Actions job*: authenticate with Workload Identity Federation
  (`google-github-actions/auth` with `workload_identity_provider` and
  `service_account`), start Cloud SQL Auth Proxy v2
  (`cloud-sql-proxy <PROJECT_ID>:<REGION>:<INSTANCE> --port 5432 &`), wait
  with `pg_isready`, read credentials from Secret Manager and mask them with
  `::add-mask::`, then run `alembic upgrade head`. The deploy job `needs:` this
  job. Do not set `continue-on-error`; `upgrade head` is already a no-op when
  the database is current, so a failure is a real failure.
- *Cloud Run job*: build the migration entrypoint into the service image and
  run it as a job (`gcloud run jobs deploy <SERVICE>-migrate --image <IMAGE>
  --command alembic --args upgrade,head --set-cloudsql-instances ...
  --set-secrets ...`, then `gcloud run jobs execute <SERVICE>-migrate --wait`).
  Database credentials never leave Google Cloud.

Migrations run from one place only. Never also run `alembic upgrade` from
service startup: concurrent instances race each other.

## pgvector

```python
# migration
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
    )
    op.create_index(
        "ix_documents_embedding_hnsw", "documents", ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
```

```python
# query
from sqlalchemy import select

stmt = (
    select(Document)
    .order_by(Document.embedding.cosine_distance(query_embedding))
    .limit(10)
)
```

- On Cloud SQL, `CREATE EXTENSION` needs a role with `cloudsqlsuperuser`;
  run it in a migration, not by hand.
- The column dimension must equal the embedding model's output dimension.
  HNSW and IVFFlat indexes on `vector` support up to 2,000 dimensions
  (`halfvec` up to 4,000). If the embedding model's default output is larger,
  request a smaller output dimensionality or store `halfvec`.
- The index operator class must match the query's distance function
  (`vector_cosine_ops` with `cosine_distance` / `<=>`), or the planner ignores
  the index.
- Tune recall per query with `SET LOCAL hnsw.ef_search = <n>`.
- Store the embedding model name and version alongside vectors; changing
  models means re-embedding, which is a backfill (see expand/contract).
