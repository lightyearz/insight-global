---
paths:
  - ".claude/**"
  - "CLAUDE.md"
---

# Editing the harness itself (skills, agents, rules, hooks, CLAUDE.md)

Method and rationale: the `harness-engineering` skill. Mechanical checks: `python3 .claude/scripts/harness_lint.py` (run it before you finish; the post-edit hook runs it on the file you touched).

## This harness is public
- No secrets, tokens, or key material. No real project ids or numbers, service-account emails, `*.run.app` URLs, bucket or registry names, domains, personal names, or machine-specific paths. Use placeholders: `<PROJECT_ID>`, `<REGION>`, `<SERVICE>`, `<AR_REPO>`, `<SA_NAME>@<PROJECT_ID>.iam.gserviceaccount.com`.
- Link only to skills, agents, and files that exist in this repo; the lint flags dead relative links and unknown preloaded skills.
- Personal settings go in `.claude/settings.local.json` (not committed), never in `.claude/settings.json`.

## Skills (`.claude/skills/<name>/SKILL.md`)
- Frontmatter is required: `name` (equals the directory name; lowercase, digits, hyphens) and `description` (third person, says what it does AND when to use it, under 1,024 characters).
- Keep the SKILL.md body under 500 lines. Move tables, long lists, and rarely-needed detail into `reference/<topic>.md` and link each file directly from SKILL.md (one level deep). Reference files over 100 lines start with a `## Contents` list.
- Write for a smart reader: only what Claude cannot infer. No tutorials on standard tooling.
- No time-sensitive phrasing ("before August use X"). Put superseded material under an "Old patterns" heading instead of deleting it.
- After adding or renaming a skill run `python3 .claude/scripts/build_skills_index.py` so `.claude/skills/README.md` matches; add the skill to `CATEGORIES` (for its section) and `SUMMARIES` (for its one-line index entry) in that script. Private, git-ignored skill dirs are left out of the index automatically.

## Agents (`.claude/agents/<name>.md`)
- `name` equals the filename. Keep `description` short (one or two sentences plus "Use proactively when ..."); it is loaded into every session. Put the detail in the body.
- Do not paste the "Persistent Agent Memory" section into the body; Claude Code injects it when `memory:` is set.
- Prefer `skills:` preloading over "always load skill X first" instructions for small skills; list only skills that exist here.

## Hooks (`.claude/hooks/*.sh`, wired in `.claude/settings.json`)
- Scripts are executable, read the hook JSON from stdin with `jq`, and are referenced as `"${CLAUDE_PROJECT_DIR}"/.claude/hooks/<name>.sh`.
- A guard denies with a reason that names the safe alternative. A sensor never blocks; it returns findings as `additionalContext`.
- Test every new rule by piping sample hook JSON into the script, for both a case it must deny and a near miss it must allow.

## Rules and CLAUDE.md
- CLAUDE.md stays under 200 lines and holds only what applies to every session. Anything path-specific belongs in `.claude/rules/<topic>.md` with a `paths:` scope; anything task-specific belongs in a skill.
- If an instruction must hold no matter what the model decides, make it a hook, not a sentence.
