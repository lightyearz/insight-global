# Git Workflow: Commits, Shared Trees and PRs

## Contents
- Conventional Commits in full
- Commit on confirmation
- Safe staging in a shared working tree
- Extracting a clean PR with a worktree
- Merging overlapping PRs
- Path-filtered CI: a green check can be a skip

## Conventional Commits in full

Format (Conventional Commits 1.0):

```
<type>[optional scope][!]: <description>

[optional body]

[optional footer(s)]
```

| Type | Use for |
|------|---------|
| `feat` | A new user- or API-visible capability |
| `fix` | A bug fix |
| `docs` | Documentation only (checklist, ADRs, READMEs, skills) |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf` | Performance improvement |
| `test` | Adding or correcting tests |
| `build` | Build system, dependencies, Dockerfiles |
| `ci` | CI configuration and workflows |
| `chore` | Maintenance that does not touch src or tests |
| `style` | Formatting only, no logic change |
| `revert` | Reverts a previous commit (body names the SHA) |

Guidelines:

- **Description:** imperative mood ("add", not "added"), lower case, no trailing period, the whole first line at most 72 characters.
- **Scope:** a stable area name (`api`, `web`, `worker`, `infra`, `ci`, `adr`, `checklist`). Agree the list once and reuse it so `git log --grep "(api)"` is useful.
- **Body:** why the change was made and anything a reviewer would not see from the diff. Bullets are fine. Wrap at 72.
- **Breaking changes:** `feat(api)!: remove v1 search endpoint` plus a footer `BREAKING CHANGE: clients must call /v2/search; v1 returns 410.`
- **Footers:** `Refs: #123`, `Closes #123`, and whatever attribution trailers the session or CLAUDE.md specifies. Footers go after one blank line, one per line.
- **One logical change per commit.** Documentation that describes a code change may travel in the same commit; unrelated cleanup may not.
- **Squash merges:** the PR title becomes the commit subject, so PR titles follow the same format.

Examples:

```
feat(worker): run background jobs from Cloud Tasks

- Add /tasks/run handler with OIDC token verification
- Add job table and migration (expand step only)
- Implements P1.7.2. See ADR 0004.

Refs: #44
```

```
docs(adr): accept 0004 use cloud tasks for background jobs
```

```
fix(api): return 404 instead of 500 for unknown user id

The repository raised NoResultFound, which the error middleware did not
map. Map it to NotFoundError and add a regression test.

Closes #52
```

## Commit on confirmation

Applies when the user confirms work is finished and wants it committed (a phrase such as "that worked, commit it", or a team trigger word such as "worked").

1. **Check where you are:** `git branch --show-current` and `git log --oneline -1`. On the default branch, stop and create or ask for a feature branch.
2. **See what changed:** `git status --short` and `git diff --stat`.
3. **Stage by explicit path** only the files that belong to the finished work: `git add path/one.py path/two.md`. Never `git add -A`, `git add .` or `git commit -a` in a tree that may contain other people's or other sessions' changes.
4. **Check the staged set:** `git diff --cached --stat`. Unstage anything unrelated with `git restore --staged <path>`.
5. **Never stage secrets:** `.env` files, key files, credentials, Terraform state. If one shows up as untracked, it belongs in `.gitignore`, not in the commit.
6. **Commit** with a Conventional Commit message describing what was actually done, citing checklist IDs and ADRs.
7. **Report** the short SHA and subject. If nothing changed, say so; do not create an empty commit.
8. **Do not push** unless the user asked. If a pre-commit hook fails, fix the cause and create a new commit; do not bypass hooks with `--no-verify`.

## Safe staging in a shared working tree

When several people or agent sessions share one checkout:

- **The checked-out branch can change under you.** Another session may switch branches mid-task, and your commit lands on whatever is checked out. Re-run `git branch --show-current` immediately before every commit.
- **Stage explicit paths only**, as above, so you never sweep another session's work in progress into your commit.
- **Do not stash someone else's work in progress.** `git stash push -u` in a tree with other sessions' untracked files can fail partway (for example on permission-protected paths) and leave untracked files removed from the working tree without being captured in the stash. Use a separate worktree instead.
- **Prefer one worktree per concurrent task** (`git worktree add ../<repo>-<task> -b <branch>`) so sessions never share a working directory in the first place.

## Extracting a clean PR with a worktree

To get your commits onto a clean PR branch without disturbing anyone's working tree:

```bash
git fetch origin
git worktree add ../clean-pr origin/main          # separate directory, detached at base
cd ../clean-pr
git switch -c feat/background-jobs
git cherry-pick <sha1> <sha2>                     # only your commits, oldest first
# run the affected tests here
git push -u origin feat/background-jobs
cd - && git worktree remove ../clean-pr
```

The worktree is a separate directory, so the shared checkout is never touched. Resolve cherry-pick conflicts in the worktree; abort with `git cherry-pick --abort` if the commits depend on work you did not intend to include.

## Merging overlapping PRs

When your commits end up tangled in a teammate's PR branch (or theirs in yours):

- **Keep them separate (default):** merge your clean PR first, then rebuild the teammate's PR by cherry-picking only their commits onto the updated default branch, and close the tangled PR as superseded with a link.
- **Combine them:** if one PR already contains everything from the other, retitle it to the combined scope, merge it with a **merge commit** rather than a squash so each commit stays individually traceable (useful when an audit trail matters, such as security-sensitive changes), and close the subset PR as superseded.
- Either way, update the checklist evidence to point at the PR that actually merged.

## Path-filtered CI: a green check can be a skip

Monorepo workflows often run a service's tests only when files under that service change. A green check on a PR can therefore mean "skipped", not "passed":

- Open the run and confirm the relevant jobs actually executed (`gh pr checks <number>`, then `gh run view <run-id>`).
- When a change affects a shared package or contract used by several services, run the dependent services' tests explicitly (locally or with a manual workflow dispatch) before calling it verified.
- Record in the PR description and the session summary which suites ran, not just that CI was green.
