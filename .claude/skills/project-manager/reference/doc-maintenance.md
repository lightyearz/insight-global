# Documentation Maintenance

## Contents
- Documentation hierarchy
- Consolidating duplicate documents
- Moving or renaming files
- Cookbook: find, grep, replace, verify
- Keeping skills and agents in sync with the code

## Documentation hierarchy

A typical layout for this stack. Adapt to what exists; do not create empty directories for the sake of it.

```
README.md                         # Project overview, quick start, map of docs/
CLAUDE.md                         # Always-loaded agent instructions (short, pointers only)
docs/
  IMPLEMENTATION_CHECKLIST.md     # Master plan and progress (single source of truth)
  adr/
    README.md                     # Decision log index
    template.md                   # ADR template
    0001-record-architecture-decisions.md
  architecture/                   # System overview, diagrams, data flows
  runbooks/                       # Deploy, rollback, incident procedures
  status/                         # Weekly reports, risk register
services/<service>/README.md      # Per-service purpose, API, config names, run and test
web/README.md                     # Frontend structure, run and test
.claude/
  skills/<name>/SKILL.md          # Skills, with reference/ for long material
  agents/<name>.md                # Subagent definitions
  rules/*.md                      # Path-scoped rules
```

Each topic has exactly one home. The top-level README links to the checklist, the ADR index, the architecture overview and the runbooks so a newcomer can find everything from one page.

## Consolidating duplicate documents

1. **Identify duplicates.** Same file name in several places, or different files covering the same topic:
   ```bash
   git ls-files '*.md' | xargs -n1 basename | sort | uniq -d
   git grep -l -i "background jobs" -- '*.md'
   ```
2. **Compare.** For each candidate: last commit date (`git log -1 --format=%ad -- <file>`), completeness, accuracy against the code, and how many files link to it.
3. **Choose the canonical file.** Most accurate first, then most complete, then the conventional location (project-wide material in `docs/`, service-specific material in the service README).
4. **Merge unique content** from the others into the canonical file. Verify each merged claim against the code; do not carry over stale statements.
5. **Find every reference** to the files being removed (`git grep -n "<path or file name>"`), including `.claude/`, CI workflows, code comments and READMEs.
6. **Repoint references** to the canonical file.
7. **Delete the duplicates** with `git rm`.
8. **Verify:** re-grep for the old paths (expect zero hits) and run the link check below. Commit the merge, the reference updates and the deletions together, with a `docs:` commit that names the canonical file.

## Moving or renaming files

1. Note the old and new paths.
2. `git grep -n "old/path/file.md"` and also grep for the bare file name, since some links are relative.
3. `git mv old/path/file.md new/path/file.md` (keeps history visible to `git log --follow`).
4. Update every reference; relative links may need different `../` depth from each referring file.
5. Re-grep for the old path, run the link check, and commit everything together.

## Cookbook: find, grep, replace, verify

Prefer `git ls-files` and `git grep`: they skip ignored and generated directories (`node_modules`, `.venv`, build output) automatically.

```bash
# All tracked Markdown files
git ls-files '*.md'

# Markdown changed in the last 7 days
git log --since="7 days ago" --name-only --pretty=format: -- '*.md' | sort -u

# Every reference to a path, with line numbers
git grep -n "docs/old-name.md"

# Only in Markdown, or only in the harness
git grep -n "old-name" -- '*.md'
git grep -n "old-name" -- .claude/
```

In-place replacement differs between GNU sed (Linux) and BSD sed (macOS). Use one of these portable forms:

```bash
# Perl works the same everywhere
git grep -l "docs/old-name.md" | xargs perl -pi -e 's|docs/old-name\.md|docs/new-name.md|g'

# GNU sed (Linux, CI runners)
git grep -l "docs/old-name.md" | xargs sed -i 's|docs/old-name\.md|docs/new-name.md|g'

# BSD sed (macOS) needs an explicit empty backup suffix
git grep -l "docs/old-name.md" | xargs sed -i '' 's|docs/old-name\.md|docs/new-name.md|g'
```

Always review the result with `git diff` before committing; a broad pattern can rewrite code or URLs you did not mean to touch.

Relative-link check for Markdown (reports links whose target file does not exist):

```bash
git ls-files '*.md' | while read -r f; do
  grep -oE '\]\([^)#[:space:]]+' "$f" | sed 's/^](//' | grep -vE '^(https?:|mailto:)' |
  while read -r link; do
    [ -e "$(dirname "$f")/$link" ] || echo "$f -> $link"
  done
done
```

Counts for a metrics block:

```bash
git ls-files '*.md' | wc -l                                  # documentation files
git ls-files '*.py' '*.ts' '*.tsx' | xargs wc -l | tail -1   # source lines (rough)
```

## Keeping skills and agents in sync with the code

Skills and agents are documentation that agents execute, so stale guidance causes wrong code, not just confusion. After a change that alters how work is done (new service, renamed directory, changed test command, new deploy step):

1. `git grep -n "<old name or path>" -- .claude/ CLAUDE.md` and update every hit.
2. Update the skill that owns the topic rather than adding a note to an unrelated one; check the skill index (`.claude/skills/README.md`) to find the owner.
3. Run the harness checks the repo provides (frontmatter, line limits, dead links, unknown preloaded skills). The `harness-engineering` skill has the audit checklist and the conventions for skill and agent files.
4. If the skill set changed (added, renamed, removed), regenerate or update the skills index in the same commit.

Checklist for any skill or agent you touch:

- [ ] Frontmatter `name` matches the directory or file name; `description` says what it does and when to use it.
- [ ] Paths, commands and file names it mentions exist in the repo today.
- [ ] Cross-references point only to skills and agents that exist.
- [ ] No secrets, real project identifiers, personal names or machine-specific paths.
