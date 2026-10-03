# Status Templates, Metrics, Risks and Estimation

## Contents
- Gathering the data
- Session summary
- Weekly status report
- Phase completion criteria
- Metrics block
- Risk register
- Planning and estimation

## Gathering the data

Build every status update from the repository, not from memory. Useful commands:

```bash
# Commits on the current branch since a date, without merges
git log --since="2026-09-23" --no-merges --pretty='%h %ad %s' --date=short

# Commits that reference a checklist ID or ADR
git log --oneline --grep "P1.7"
git log --oneline --grep "ADR 0004"

# What changed in the working tree this session
git status --short
git diff --stat

# Merged and open PRs (GitHub CLI)
gh pr list --state merged --search "merged:>=2026-09-23" --limit 50
gh pr list --state open --limit 50

# Recent CI runs and their conclusions
gh run list --limit 20

# Checklist counts: done vs open leaf items
grep -c '^\s*- \[x\]' docs/IMPLEMENTATION_CHECKLIST.md
grep -c '^\s*- \[ \]' docs/IMPLEMENTATION_CHECKLIST.md
```

Cite PR numbers and short SHAs so every claim can be checked.

## Session summary

For the end of a working session. Usually a reply to the user; save it under `docs/status/` only if the team keeps session logs.

```markdown
# Session summary: <focus>

**Date:** YYYY-MM-DD
**Branch:** <branch>  **Commits:** <short SHAs>

## Done
1. <Outcome> - <evidence: PR, SHA, test>
2. <Outcome> - <evidence>

## Documentation and records
- Checklist: ticked P1.7.1, P1.7.2; P1 now 9/10 (90%)
- ADR: added 0004 (Proposed)
- Docs: services/worker/README.md created

## Verification
- <Commands run and their result, e.g. "pytest services/worker: 42 passed">
- <Anything not verified, stated plainly>

## Open issues and blockers
- <Issue> - <owner or next action>

## Next steps
1. <Next priority, with checklist ID>
2. <...>
```

State unverified work as unverified. A summary that overstates progress is worse than none.

## Weekly status report

Save as `docs/status/YYYY-MM-DD-weekly.md` (date the file by the start of the week or by the day it was written; pick one convention and keep it).

```markdown
# Weekly status: week of YYYY-MM-DD

**Health:** Green | Amber | Red - <one sentence: why>
**Date written:** YYYY-MM-DD

## Highlights
- <The one to three things a reader must know>

## Completed this week
- [x] P1.6 Users API pagination - PR #31
- [x] P1.7.1 Job table and migration - PR #40

## In progress
| Item | Progress | Expected | Notes |
|------|----------|----------|-------|
| P1.7 Background job runner | 1/2 sub-tasks | YYYY-MM-DD | waits on ADR 0004 |

## Phase progress
| Phase | Last week | This week |
|-------|-----------|-----------|
| P1 Core services | 6/10 (60%) | 8/10 (80%) |

## Decisions
- ADR 0004 Use Cloud Tasks for background jobs - Proposed, decision due YYYY-MM-DD

## Blockers and risks
- <Blocker> - <impact> - <owner> - <next action and date>
- See the risk register for the full list.

## Next week priorities
1. <Checklist ID and outcome>
2. <...>

## Notes
- <Context a reader needs: scope changes, staffing, dependencies on other teams>
```

Health guide: **Green** on track, no unowned blockers. **Amber** at risk; a blocker or slip that has a plan. **Red** a milestone will be missed or a blocker has no plan; name the decision needed and from whom.

## Phase completion criteria

A phase is `Done` only when all of these hold:

- [ ] Every leaf item ticked, each with evidence.
- [ ] Code merged to the default branch; nothing left only on a feature branch.
- [ ] Tests for the phase pass in CI (not skipped by path filters; see `git-workflow.md`).
- [ ] Deployed to the target environment if the phase includes deployment, with a smoke check recorded.
- [ ] Documentation updated: service READMEs, runbooks, the architecture overview.
- [ ] ADRs for the phase's significant decisions are `Accepted`.
- [ ] Known follow-ups moved into later phases as new items with IDs.

Then mark the heading `## P1: Core services - Done (YYYY-MM-DD)` and update the summary table.

## Metrics block

Optional section in the checklist or the weekly status. Track only metrics someone will act on; prefer numbers a command can regenerate.

```markdown
## Metrics (YYYY-MM-DD)

**Delivery**
- Checklist items done / total: 41 / 63 (65%)
- PRs merged this week: 9; median time to merge: 1.5 days
- Open ADRs in Proposed: 1

**Quality**
- Backend test coverage: 84% (target 80%)
- Frontend type-check and lint: clean
- Failing or quarantined tests: 0 / 2

**Operations** (if deployed)
- Error rate, p95 latency per service: from the monitoring dashboard
- Monthly cloud spend vs budget: from the billing export
```

Lines of code and page counts are poor progress measures; include them only if the reader asks.

## Risk register

```markdown
## Risks (updated YYYY-MM-DD)

| ID | Risk | Category | Impact | Likelihood | Mitigation | Owner | Status |
|----|------|----------|--------|------------|------------|-------|--------|
| R1 | LLM API quota exhausted at peak | Technical | High | Medium | Backoff with jitter, response cache, quota increase requested | backend | Open |
| R2 | Index build on large table locks writes during migration | Technical | High | Low | Build concurrently in a separate migration, off-peak | backend | Mitigated |
| R3 | Single engineer knows the deploy pipeline | Resource | Medium | High | Runbook in docs/, pair on next two deploys | platform | Open |
| R4 | Third-party API deprecates the endpoint we use | Schedule | Medium | Medium | Track provider changelog, wrap in an adapter | backend | Open |
```

Categories: **Technical** (architecture, performance, scalability, reliability), **Schedule** (dependencies, external deadlines), **Resource** (people, skills, budget, quotas), **Security and compliance** (data protection, access control, audit requirements), **Product** (adoption, fit, scope).

Rate impact and likelihood as High / Medium / Low. Every open High-impact risk needs an owner and a dated next action. Close risks explicitly (`Closed: <reason>`) rather than deleting rows.

## Planning and estimation

Every task in a plan carries: an ID, a verifiable outcome (acceptance criteria), a size, dependencies, and a priority (MoSCoW: Must / Should / Could / Won't, or RICE when comparing many candidates).

| Size | Typical scope | Base estimate | Buffer |
|------|---------------|---------------|--------|
| XS | config change, copy fix | under 1 hour | +25% |
| S | bug fix, small component | 1-4 hours | +25% |
| M | endpoint with tests, page, small service change | 1-2 days | +50% |
| L | new service, major feature | 3-5 days | +75% |
| XL | phase, cross-service change, migration | 1-2 weeks | +100% |

Rules of thumb:

- An XL item is a plan, not a task; break it into M and L items before estimating.
- Buffers grow with uncertainty, not just size: new technology, external dependencies and unclear requirements each justify moving up one buffer band.
- Map dependencies explicitly and identify the critical path; parallelise only what is truly independent.
- Record estimates in the checklist next to the phase (`Estimated: 2 weeks; depends on P1`) and compare with actuals at phase end. The comparison is the input for the next estimate.
- Organise plans around shippable increments: each milestone should leave the system deployable and demonstrable.
