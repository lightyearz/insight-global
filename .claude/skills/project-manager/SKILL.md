---
name: project-manager
description: Keeps a software project organised and its progress visible - maintains the implementation checklist (docs/IMPLEMENTATION_CHECKLIST.md) with stable IDs, evidence and progress percentages, writes Architecture Decision Records in docs/adr/NNNN-title.md (context, options, decision, consequences, evidence), produces session summaries, weekly status reports, plans and risk registers, consolidates duplicate documentation and repairs cross-references, and writes Conventional Commits with safe staging in shared working trees. Use when a feature lands, a significant technical decision is made, documentation is duplicated or moved, a plan or status report is needed, or the user confirms finished work and wants it committed.
---

# Project Manager

Keeps the project's written record honest: what is planned, what is done (with evidence), why the architecture looks the way it does, and what changed in each commit. The goal is that a new contributor, human or agent, can answer "where are we and why?" from the repository alone.

**Companions:** `harness-engineering` (editing skills, agents, rules or CLAUDE.md), `backend-architect` and `devops-infrastructure` (technical input for ADRs), `testing-qa` (what "verified" means before an item is marked done).

## When to use

- A feature, service or phase milestone has landed: update the checklist and docs.
- A decision is hard to reverse or affects more than one component: write an ADR.
- The user asks for a plan, a status report, a session summary or a risk register.
- Documentation is duplicated, contradictory, stale, or files have moved.
- The user confirms a piece of work is finished and wants it committed.

## Reference files (load on demand)

- [reference/adr.md](reference/adr.md) - when to write an ADR, numbering and file naming, the full template (context, options, decision, consequences, evidence), statuses and supersession, the index file, a worked example.
- [reference/status-and-planning.md](reference/status-and-planning.md) - session summary, weekly status report, phase completion criteria, metrics block, risk register, estimation sizes and buffers, git commands that gather report data.
- [reference/doc-maintenance.md](reference/doc-maintenance.md) - the documentation hierarchy, the duplicate-consolidation workflow, moving files and updating references, a portable find / grep / sed cookbook, keeping skills and agents in sync with the code.
- [reference/git-workflow.md](reference/git-workflow.md) - Conventional Commits in full, commit-on-confirmation, safe staging in a shared working tree, extracting a clean PR with a worktree, merging overlapping PRs, path-filtered CI caveats.

## Ground rules

1. **One source of truth per topic.** Link to it; never copy its content into a second file. When two files disagree, consolidate (see `reference/doc-maintenance.md`).
2. **Done means verified.** Do not tick a checklist item because code exists. Tick it when the change is merged (or committed on the working branch, if that is the team's rule) and its tests pass. Record the evidence next to the tick.
3. **Read before you write.** Check `git log`, open PRs and the current checklist before updating anything; someone may have moved on since the last session.
4. **Repository-relative paths only.** Write `docs/adr/0003-...md`, never an absolute path from one machine. Absolute paths break for every other contributor and leak local details.
5. **Dates are absolute.** Write `2026-09-30`, not "yesterday" or "last week".
6. **Small, reviewable changes.** Documentation updates ride in the same PR as the code they describe when possible, so they cannot drift.

## The implementation checklist

`docs/IMPLEMENTATION_CHECKLIST.md` is the master list of planned and completed work. Agents and humans both read it to decide what to do next, so it must match reality.

### Structure

```markdown
# Implementation Checklist

Last updated: 2026-09-30

## Progress summary
| Phase | Status | Done / total | Notes |
|-------|--------|--------------|-------|
| P0 Foundations | Done (2026-08-14) | 9/9 | |
| P1 Core services | In progress | 8/10 (80%) | P1.7 blocked on ADR 0004 |
| P2 Search and AI features | Not started | 0/12 | depends on P1 |

## P0: Foundations - Done (2026-08-14)
- [x] **P0.1 Repository, branch protection and CI** - PR #3
- [x] **P0.2 Dev, staging and production projects** - PR #5, ADR 0001

## P1: Core services - In progress (8/10, 80%)
- [x] **P1.1 Users API: create, read, update** - PR #21, tests in services/api/tests/test_users.py
- [ ] **P1.7 Background job runner** - Blocked: waiting on ADR 0004 (queue choice)
  - [x] P1.7.1 Job table and migration - PR #40
  - [ ] P1.7.2 Worker service on Cloud Run
```

Rules for items:

- **Stable IDs** (`P1.7`, `P1.7.2`). IDs never change once assigned and are never reused; reference them in commit bodies, PR titles and ADRs so work is traceable in both directions.
- **One outcome per item**, phrased as a verifiable result ("Users API returns 404 for unknown IDs"), not an activity ("work on users").
- **Evidence on every ticked item**: a PR number, commit SHA, test file, or ADR. An unticked item that is blocked states the blocker and links it.
- **Status vocabulary** for phases: `Not started`, `In progress`, `Blocked - <reason>`, `Done (YYYY-MM-DD)`. Use these words consistently so the file can be grepped and parsed.
- **Progress** = completed leaf items / total leaf items, rounded down. Recompute it whenever you tick an item; never estimate it by feel.

### When to update it

Update after: completing a feature or sub-task, adding or removing a service or component, finishing a phase milestone, accepting an ADR that adds or removes work, discovering a blocker, or changing the plan (re-scoped, deferred or cancelled items stay listed with a short reason rather than being deleted silently).

### Before ticking an item

1. Find the change: `git log --oneline --grep "P1.7"` or the merged PR.
2. Confirm it does what the item says: read the code path, or grep for the endpoint, migration or component.
3. Confirm tests exist and pass for it (load `backend-test-runner` or `frontend-test-runner` for the commands).
4. Tick, add the evidence, recompute the phase percentage and the summary table, bump `Last updated`.

## Architecture Decision Records

An ADR is a short, immutable note recording one significant decision: the forces at play, the options weighed, what was chosen, what it costs, and the evidence behind it. ADRs answer "why is it like this?" months later, when the people and the chat logs are gone.

- **Location and naming:** `docs/adr/NNNN-short-kebab-title.md`, four-digit zero-padded, numbered sequentially, never reused. Index in `docs/adr/README.md`.
- **Write one when** a decision is hard or costly to reverse, crosses service boundaries, adds a dependency or managed service, changes the data model, data ownership or the auth model, or trades one quality attribute for another (cost vs latency, simplicity vs flexibility).
- **Do not write one** for choices that are local, cheap to reverse, or already dictated by an existing ADR or standard.
- **Sections:** Context, Options considered, Decision, Consequences, Evidence (plus status, date, deciders, related links).
- **Lifecycle:** `Proposed` -> `Accepted` (or `Rejected`). Accepted ADRs are not rewritten; a later decision creates a new ADR that marks the old one `Superseded by NNNN`.
- **Evidence is required.** Benchmarks, spike results, cost estimates, load tests, documentation consulted (with the date). Label illustrative or estimated numbers as such.

Full template, a numbering one-liner and a worked example: [reference/adr.md](reference/adr.md).

## Status reporting

Pick the smallest format that answers the reader's question:

| Need | Format | Where |
|------|--------|-------|
| What happened this session and what is next | Session summary | Reply to the user; optionally `docs/status/YYYY-MM-DD-session.md` |
| Weekly progress for the team | Weekly status report | `docs/status/YYYY-MM-DD-weekly.md` |
| What could go wrong and who owns it | Risk register | Section in the weekly report or `docs/status/risks.md` |
| How the work breaks down and in what order | Plan | New phase section in the checklist, plus an ADR if it encodes a decision |

Every report leads with health (`Green` / `Amber` / `Red` and one sentence why), then completed work with evidence, in-progress work with percentages taken from the checklist, blockers with owners, and next priorities. Build reports from `git log`, merged PRs and the checklist, not from memory. Templates and data-gathering commands: [reference/status-and-planning.md](reference/status-and-planning.md).

## Commits: Conventional Commits

```
<type>(<scope>): <imperative summary, lower case, no trailing period, <= 72 chars>

<body: what changed and why, wrapped at 72; bullets are fine>

<footers: Refs: #123 | Closes #123 | BREAKING CHANGE: ... | attribution trailers>
```

- **Types:** `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `style`, `revert`.
- **Scope:** the service, package or area touched (`api`, `web`, `worker`, `infra`, `adr`, `checklist`). Omit it rather than invent a vague one.
- **Breaking changes:** `!` after the type or scope (`feat(api)!: ...`) and a `BREAKING CHANGE:` footer that says what consumers must do.
- **Traceability:** mention checklist IDs and ADR numbers in the body (`Implements P1.7.1. See ADR 0004.`).
- **Attribution:** add exactly the trailer lines the session or CLAUDE.md specifies; do not invent your own.

### Commit on confirmation

When the user confirms a piece of work is finished and asks for it to be committed (some teams use a single trigger word, for example "worked"):

1. `git branch --show-current` and `git status`. If on the default branch, stop and create or ask for a feature branch; protected branches take changes only through PRs.
2. Stage **by explicit path**, only files that belong to the finished work. Never `git add -A` or `git add .` in a tree that may hold someone else's work in progress.
3. `git diff --cached --stat` to confirm the staged set, then commit with a Conventional Commit message that matches what was actually done.
4. Report the SHA and the one-line summary. If nothing changed, say so instead of making an empty commit.
5. **Do not push** unless the user asked for it.

Shared-tree hygiene, clean-PR extraction with a worktree and merging overlapping PRs: [reference/git-workflow.md](reference/git-workflow.md).

## Documentation hygiene

- **Naming:** kebab-case file names (`deploy-runbook.md`); `README.md` for directory entry points; ADRs follow `NNNN-title.md`. Match the existing convention in a directory before introducing a new one.
- **Headings:** one `#` title per file, then `##` sections; a table of contents in any file over about 100 lines.
- **Freshness:** put `Last updated: YYYY-MM-DD` near the top of living documents (checklist, runbooks, indexes). Git records who changed what; the document does not need to.
- **Moving or renaming a file:** use `git mv`, find every reference first (`git grep -n "old/path"`), update them in the same commit, then re-grep to confirm zero hits.
- **Broken links:** after any reorganisation, check that every relative link in `docs/` and `.claude/` resolves (the cookbook in `reference/doc-maintenance.md` has a one-liner).
- **Stale content:** delete or archive superseded documents; a wrong document is worse than a missing one because agents will follow it.

## Common scenarios

### A feature has landed
1. Verify it (code path, tests, merged PR).
2. Tick the checklist items with evidence; recompute percentages and the summary table.
3. Update or create the feature's documentation (service README, API notes) in the same PR if possible.
4. If the feature changed how a skill or agent should behave, update that skill (load `harness-engineering`).
5. Give the user a session summary.

### A significant technical decision was made
1. Write `docs/adr/NNNN-title.md` with status `Proposed` (or `Accepted` if already agreed), including the options that lost and the evidence.
2. Add it to `docs/adr/README.md`.
3. Add, remove or re-scope checklist items the decision implies, linking the ADR.
4. If it replaces an earlier decision, mark the old ADR `Superseded by NNNN` (the only edit allowed to an accepted ADR).

### Files moved or the structure changed
1. Record old and new paths.
2. `git grep -n` for every old path, including in `.claude/`, CI workflows and READMEs.
3. `git mv`, update every reference, re-grep for zero hits, check links.
4. Update the documentation hierarchy in the top-level README if it shows one.
5. Commit the move and the reference updates together.

### A new service was added
1. Service `README.md`: purpose, owner, endpoints, configuration (names of settings and secrets, never values), how to run and test it.
2. Checklist items for the service with IDs.
3. An ADR if the service introduces a new boundary, datastore or dependency.
4. Architecture overview or diagram updated.
5. Relevant skills updated (`backend-architect`, `devops-infrastructure`, `cloud-run-deploy`) if their guidance changes.

### Documentation is duplicated or contradictory
Follow the consolidation workflow in [reference/doc-maintenance.md](reference/doc-maintenance.md): pick the canonical file, merge unique content into it, repoint every reference, delete the duplicate, verify.

## Cadence

- **End of session:** session summary; checklist updated; documentation changes committed with the code; next priorities noted.
- **Weekly:** status report; phase percentages and estimates refreshed; risks and blockers reviewed; open ADRs in `Proposed` either decided or given an owner and date.
- **Monthly:** documentation review for stale or duplicate files; skills and agents checked against the current code; completed phases archived or collapsed in the checklist.

## Success criteria

- No two files claim to be the source of truth for the same topic; no references point at missing files.
- Every ticked checklist item carries evidence, and the percentages match a recount.
- Every hard-to-reverse decision of the last quarter has an ADR with options and evidence.
- Commit history reads as a changelog: typed, scoped, and traceable to checklist IDs and ADRs.
- A newcomer can find the plan, the decisions and the current status within a few minutes, starting from the top-level README.
