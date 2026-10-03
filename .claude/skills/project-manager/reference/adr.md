# Architecture Decision Records

## Contents
- What an ADR is for
- When to write one (and when not to)
- Location, numbering and naming
- Statuses and lifecycle
- The template
- Writing guidance
- The index file
- Worked example

## What an ADR is for

An Architecture Decision Record captures one architecturally significant decision together with its context and consequences. It is short (one to two pages), written at the time of the decision, and kept in the repository next to the code so that it is versioned, reviewed in PRs, and discoverable by agents. The collection of ADRs is the project's decision log; reading them in order explains how the system got its shape.

ADRs record **why**, not **how**. Implementation detail belongs in code, READMEs and runbooks; the ADR links to them.

## When to write one (and when not to)

Write an ADR when a decision:

- is hard or expensive to reverse (datastore, queue, framework, hosting model, public API shape);
- crosses service or team boundaries (who owns a table, which service calls which, sync vs async integration);
- adds a dependency, managed service or vendor, or removes one;
- changes the data model, data ownership, retention, or the authentication and authorisation model;
- trades one quality attribute for another (cost vs latency, consistency vs availability, simplicity vs flexibility);
- departs from an existing standard or an earlier ADR.

Do not write one when the choice is local to one module and cheap to change, is already dictated by an accepted ADR or a team standard, or is a pure implementation detail (naming, file layout inside a package). When in doubt, a two-paragraph ADR costs little; an unrecorded reversal of a major decision costs a lot.

## Location, numbering and naming

- Directory: `docs/adr/`.
- File name: `NNNN-short-kebab-title.md`, for example `0004-use-cloud-tasks-for-background-jobs.md`.
- `NNNN` is four digits, zero-padded, sequential, assigned at creation, and never reused (a rejected ADR keeps its number).
- Title: the decision as a short noun or verb phrase ("Use Cloud Tasks for background jobs"), not the question.
- `0001-record-architecture-decisions.md` conventionally records the decision to keep ADRs at all.
- `docs/adr/template.md` holds a copy of the template below.

Next number (bash; handles an empty directory and leading zeros):

```bash
last=$(ls docs/adr 2>/dev/null | grep -Eo '^[0-9]{4}' | sort -n | tail -1)
printf '%04d\n' $((10#${last:-0} + 1))
```

If two branches create the same number concurrently, the second to merge renumbers its file and updates references before merging.

## Statuses and lifecycle

| Status | Meaning |
|--------|---------|
| `Proposed` | Written and open for review; not yet binding. |
| `Accepted` | Agreed; the team builds to it. |
| `Rejected` | Considered and declined; kept so the discussion is not repeated. |
| `Deprecated` | No longer relevant (the component was removed) but not replaced. |
| `Superseded by NNNN` | Replaced by a later ADR, which links back with `Supersedes NNNN`. |

Accepted ADRs are immutable. To change a decision, write a new ADR and edit only the status line of the old one. Typos and broken links may be fixed at any time.

## The template

```markdown
# NNNN. <Decision title>

- **Status:** Proposed | Accepted | Rejected | Deprecated | Superseded by [NNNN](NNNN-title.md)
- **Date:** YYYY-MM-DD
- **Deciders:** <roles or handles of the people who agreed>
- **Related:** <issues, PRs, checklist IDs, other ADRs; "Supersedes NNNN" if applicable>

## Context

<The problem and the forces at play: requirements, constraints (budget, latency,
team skills, compliance, deadlines), the current state of the system, and why a
decision is needed now. Neutral language; no option is favoured here.>

## Decision drivers

- <Driver 1, e.g. p95 latency under 300 ms at expected load>
- <Driver 2, e.g. no new stateful infrastructure for a small team to operate>
- <Driver 3, e.g. monthly cost under a stated budget at current volume>

## Options considered

### Option A: <name>
<One-paragraph description.>
- Pros: <...>
- Cons: <...>

### Option B: <name>
- Pros: <...>
- Cons: <...>

### Option C: Do nothing / keep the status quo
- Pros: <...>
- Cons: <...>

## Decision

We will <chosen option>, because <the decisive drivers>. <Scope: where it
applies and where it does not.>

## Consequences

- **Positive:** <what gets easier or better>
- **Negative:** <what gets harder, new costs, risks accepted>
- **Neutral / follow-ups:** <migrations, new checklist items with IDs, docs to
  update, monitoring to add>

## Evidence

- <Benchmark or spike: what was measured, how, result, link to the script or PR>
- <Cost estimate: inputs, formula, result; mark estimates as estimates>
- <Documentation consulted: title, URL, date read>
- <Prior incidents or metrics that motivated the decision>

## Revisit when

<Conditions that should trigger a new ADR, e.g. "volume exceeds 10x current"
or "the managed service adds feature X".>
```

`Decision drivers` and `Revisit when` are optional; the other sections are required. The do-nothing option is worth listing whenever it is a real option: it forces the context section to justify the change.

## Writing guidance

- **Keep it short.** One decision per ADR. If the context section grows past a page, the decision is probably several decisions.
- **Show the losing options fairly.** Future readers need to know what was rejected and why, so they do not re-propose it without new information.
- **Make evidence checkable.** Link to the benchmark script, the spike branch or PR, the cost spreadsheet, the documentation page with the date it was read. Mark illustrative or projected numbers as such.
- **State consequences honestly.** Every real decision has a cost. An ADR with no negative consequences has not been thought through.
- **Link both ways.** The ADR lists the checklist IDs and PRs it affects; those items and PR descriptions cite the ADR number.
- **Review it like code.** Open the ADR in a PR with status `Proposed`; merge it as `Accepted` once agreed, or as `Rejected` if declined.

## The index file

`docs/adr/README.md` lists every ADR so readers and agents can scan the decision log without opening each file:

```markdown
# Architecture Decision Records

New ADRs: copy template.md to NNNN-title.md (next free number) and open a PR.

| # | Title | Status | Date |
|---|-------|--------|------|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | 2026-07-01 |
| [0002](0002-postgres-on-cloud-sql.md) | Use PostgreSQL on Cloud SQL as the primary datastore | Accepted | 2026-07-03 |
| [0003](0003-pgvector-for-semantic-search.md) | Use pgvector for semantic search | Accepted | 2026-08-20 |
| [0004](0004-use-cloud-tasks-for-background-jobs.md) | Use Cloud Tasks for background jobs | Proposed | 2026-09-28 |
```

Update the index in the same commit that adds or changes an ADR's status.

## Worked example

Numbers below are illustrative; a real ADR cites its own measurements.

```markdown
# 0003. Use pgvector for semantic search

- **Status:** Accepted
- **Date:** 2026-08-20
- **Deciders:** backend lead, platform lead
- **Related:** checklist P2.3, P2.4; PR #88 (spike); ADR 0002

## Context

P2 adds semantic search over roughly 200k documents, growing about 5k a month.
Queries need p95 under 300 ms end to end. The team is three engineers and
already operates PostgreSQL on Cloud SQL (ADR 0002). Embeddings come from a
Vertex AI embedding model (768 dimensions).

## Decision drivers

- Latency target at current and 5x volume
- No new stateful service to operate, back up and secure
- Filter by tenant and document type in the same query as the similarity search

## Options considered

### Option A: pgvector in the existing Cloud SQL instance
- Pros: one datastore, transactional consistency with the documents table,
  SQL filters and joins, existing backups and IAM.
- Cons: competes with OLTP load for CPU and memory; index build time grows with
  volume; fewer ANN tuning options than a dedicated engine.

### Option B: Vertex AI Vector Search
- Pros: managed, scales far beyond our volume, low query latency.
- Cons: separate index to keep in sync with PostgreSQL; filtering model differs
  from SQL; always-on endpoint cost is high relative to our volume.

### Option C: Self-hosted vector database on Cloud Run or GKE
- Pros: rich feature set.
- Cons: new stateful service for a small team; persistence on Cloud Run is a
  poor fit; operational load outweighs benefits at this scale.

## Decision

We will store embeddings in a pgvector column with an HNSW index in the
existing Cloud SQL instance, because it meets the latency target at 5x
volume in the spike, keeps one datastore, and supports tenant filters in SQL.
This applies to document search only; it does not cover future image search.

## Consequences

- **Positive:** no new infrastructure; search and metadata updates are
  transactional; backups and access control unchanged.
- **Negative:** search load shares the primary instance; we accept a possible
  tier upgrade sooner. HNSW index builds lengthen migrations on large tables.
- **Follow-ups:** P2.5 add a read replica if search CPU exceeds 40 percent
  sustained; P2.6 add search latency to the service dashboard; build the index
  in a separate migration run off-peak.

## Evidence

- Spike (PR #88): 1M synthetic 768-d vectors, HNSW (m=16, ef_construction=64),
  ef_search=40; p95 query 41 ms in-database, recall@10 0.96 against exact search.
- Cost estimate: one tier upgrade vs an always-on managed vector endpoint;
  estimate in the PR description, prices read from the provider pages on
  2026-08-18.
- pgvector README and Cloud SQL documentation for supported extension versions,
  read 2026-08-18.

## Revisit when

Document count exceeds 5M, p95 search latency exceeds 150 ms in-database, or
search load forces an instance tier above budget.
```
