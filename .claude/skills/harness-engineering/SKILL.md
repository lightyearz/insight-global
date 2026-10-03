---
name: harness-engineering
description: "Theory primer, audit method and verified reading list for harness engineering and context engineering in coding agents: what a harness is (model + loop + tools + context management + guardrails + memory + orchestration), feedforward guides vs feedback sensors, the attention budget, progressive disclosure, compaction and memory, subagent isolation, and the mistake-to-guardrail loop. Maps every Claude Code lever (CLAUDE.md, .claude/rules, skills, agents, hooks, memory, workflows) to the files in this repo and gives the checklist for auditing or extending them. Use when creating or improving skills, agents, rules, hooks or CLAUDE.md, when an agent keeps repeating a mistake, when choosing between a skill, subagent, hook or rule, when asked about token or context cost (including whether output-compression tools help), or when someone wants papers on harness or context engineering."
---

# Harness Engineering: Theory, Method, and This Repo's Harness

**Domain:** the runtime around the model. In a coding agent the harness is everything except the weights: the loop, tools, context management, safety controls, memory, orchestration, and the extension surfaces (instruction files, skills, hooks, subagents). The discipline was named in early 2026 (Lopopolo at OpenAI, Fowler/Bockeler, Hashimoto) as the third layer after prompt engineering and context engineering.
**Audience:** anyone editing `.claude/` or `CLAUDE.md`, and any agent asked to improve its own instructions.
**Freshness:** links in `reference/reading-list.md` were fetched and content-checked on 2026-09-25; version-specific limits come from the Claude Code 2.1.x docs. Re-verify before quoting after a major release.
**Companions:** the `agentic-ai-resources` skill (the agent loop and protocols), `.claude/rules/harness-authoring.md` (rules that load when you edit the harness), `.claude/scripts/harness_lint.py` (the sensor).

## When to use

- "Why does the agent keep doing X?" / "make the agent never do that again"
- Deciding between CLAUDE.md, a rule, a skill, a subagent, a hook, or a workflow
- Auditing or restructuring skills and agents (size, descriptions, progressive disclosure)
- Questions about token cost, context rot, compaction, or tools that promise savings
- Someone wants the research: papers, first-party guides, a NotebookLM source list

## How to use this skill

1. Answer from Part 1 and Part 2 (self-contained theory). Cite `reference/reading-list.md` for depth.
2. For a concrete audit, run the checklist in Part 4 and the sensors in Part 6.
3. For "which lever is which file here", use Part 3.
4. For exact frontmatter fields, hook events and limits, read `reference/claude-code-surface.md`.

---

# PART 1 - What a harness is

**Agent = model + harness.** Every production coding agent (Claude Code, Codex CLI, Gemini CLI, OpenHands, Aider, and others) is a hand-rolled loop around an LLM with the same seven subsystems: the loop itself, tool execution, context management, safety and permissions, memory, orchestration of subagents, and extension surfaces. A source-code study of eleven systems (Barbaste et al. 2026) found none of them imports an agent framework, none uses vector retrieval for code, and that SKILL.md-style skills are adopted more widely than MCP.

**Two layers.** The builder's harness is the tool (Claude Code itself). The user's harness is what you add on top: CLAUDE.md, rules, skills, agents, hooks, tests, linters, CI. This skill is about the user's layer.

**Guides and sensors (Fowler / Bockeler 2026).**
- *Feedforward guides* steer the agent before it acts: instructions, examples, skills, preloaded context, type systems. They raise the chance of a good first attempt.
- *Feedback sensors* observe after it acts and push a correction back: tests, linters, type checkers, hooks that print findings, reviewer subagents. Sensors written for the model (clear error text, a remediation hint) let it self-correct without a human.
- Feedback-only harnesses repeat mistakes; feedforward-only harnesses never learn whether the rule worked. You need both.

**Computational vs inferential.** A linter is deterministic, fast, and reliable; a reviewer subagent is slow, expensive, and probabilistic but can judge semantics. Put deterministic checks in scripts and hooks; spend inference only on what scripts cannot judge.

**The mistake-to-guardrail loop (Hashimoto's rule).** "Anytime you find an agent makes a mistake, take the time to engineer a solution so the agent never makes that mistake again." In practice an incident becomes a hook rule, a lint check, a test, or one precise sentence in the right rule file. OpenAI's Codex team shipped a million-line application this way with zero hand-written code; they report spending about 20 percent of their time on manual cleanup until they encoded taste into custom linters whose error messages carry remediation text.

**A map, not a manual.** The same team found a single large AGENTS.md fails because context is scarce. Keep the always-loaded file short (about 100 lines of pointers) and make the `docs/` or skills tree the system of record. Anthropic's Claude Code guidance agrees: target under 200 lines, and for each line ask "would removing this cause a mistake?"

**Harness coherence.** Guides and sensors drift apart as they multiply. A sensor that never fires means either quality is high or detection is inadequate. There is no "coverage" metric for harnesses yet; the substitute is a lint script over the harness itself plus periodic review of which skills are read and which are ignored.

# PART 2 - Context engineering (the resource the harness manages)

**Attention budget.** Context is finite and its marginal value falls with every token. The goal is "the smallest possible set of high-signal tokens that maximise the likelihood of the desired outcome" (Anthropic 2025). Empirically, 18 frontier models degrade non-uniformly as input grows even on trivial tasks; distractors hurt more as length grows; low similarity between the question and the needle accelerates the decay (Chroma "Context Rot", 2025). Multi-turn conversations lose about 39 percent of performance versus a single well-specified turn (Laban et al. 2025). Long context is a cost you pay with reliability, not just money.

**Altitude.** Instructions should be specific enough to guide and general enough to let the model generalise. Hard-coded brittle logic on one side, vague platitudes on the other. State the rule, then the reason, so the model can extend it to cases you did not list.

**Just-in-time over pre-loading.** Give the agent lightweight identifiers (paths, names, links) and let it load what it needs. This is why skills expose only name and description until invoked, why rules can be path-scoped, and why reference files cost nothing until read. Anthropic's runtime numbers: a subagent that explores widely should return a 1,000 to 2,000 token summary; a re-attached skill after compaction keeps only its first 5,000 tokens.

**Progressive disclosure for skills.** Metadata always, SKILL.md on invocation, reference files on demand. Keep SKILL.md under 500 lines, references one level deep, a table of contents in any reference over 100 lines. SkillsBench (2026) found curated skills raise pass rates by 16 points on average, that focused skills of two or three modules beat comprehensive documentation, and that self-generated skills give no benefit on average, so the human-curated, evaluated skill is the unit that works.

**Compaction and memory.** Rule-based elision of old tool output before LLM summarisation is the most efficient strategy measured (Fan et al. 2026), and making elided content recoverable did not help accuracy. Structured notes outside the window (progress files, MEMORY.md, git history) beat relying on compaction; the long-running-agent pattern is: read the progress file and git log, run a smoke test, work on one feature, verify end to end, write the progress file. Recite the current goal near the end of context to fight lost-in-the-middle (Manus's todo.md trick).

**Cache discipline.** Cached input is roughly a tenth of the price of uncached input. Keep prompt prefixes stable (no timestamps at the top), append rather than rewrite, and mask tools instead of removing them mid-task. Removing a skill or tool definition halfway through a session invalidates the cache and confuses references in earlier turns.

**Subagents.** Use them for context isolation and parallel exploration, not by default. Each spawn carries fixed overhead (roughly 20k tokens of system context) and multi-agent sessions cost three to four times a single thread. The right shape: a lead with the plan, workers with clean windows returning distilled results, and an adversarial reviewer that did not write the code.

**Planning and action space.** Explicit planning is an accuracy scaffold for weaker models and mostly a cost saver for stronger ones. Strong models do as well with a bash-only interface as with many bespoke tools, at lower cost (Fan et al. 2026). Keep tool sets small and unambiguous: "if a human engineer can't say which tool applies, the agent can't either."

# PART 3 - The harness map in this repo (which lever is which file)

| Lever | Where | Loaded | Use it for |
|---|---|---|---|
| Always-on instructions | `CLAUDE.md` (root) | every session | commands the model cannot guess, repo etiquette, non-negotiables, pointers |
| Path-scoped rules | `.claude/rules/*.md` with `paths:` | when a matching file is read or edited | language rules for backend and frontend code, authoring rules for `.claude/**` |
| Skills | `.claude/skills/<name>/SKILL.md` + `reference/` | description always; body on invocation | domain knowledge, procedures, reading lists; one skill per domain |
| Subagents | `.claude/agents/<name>.md` | description always; body when spawned | isolated implementation work, review with fresh context, research fan-out |
| Agent memory | `.claude/agent-memory/<agent>/MEMORY.md` (first 200 lines) | when that agent runs (`memory: project`) | what the agent learned about this repo |
| Auto memory | the user's Claude Code project memory folder | every session (index) | personal preferences and facts that do not belong in the repo |
| Hooks | `.claude/settings.json` -> `.claude/hooks/*.sh` | on the event | `guard-bash.sh` (PreToolUse Bash guard), `post-edit.sh` (PostToolUse Edit/Write: ruff, eslint, harness lint) |
| Harness lint | `.claude/scripts/harness_lint.py` | on demand and from the post-edit hook | frontmatter, size, dead links, index coverage, hook wiring, secrets, non-portable paths |
| Skills index | `.claude/scripts/build_skills_index.py` | on demand | regenerates the index block of `.claude/skills/README.md` from frontmatter |
| Workflows | Workflow tool scripts | on demand | deterministic fan-out with verification stages; keep fan-outs small |
| CI quality gates | `.github/workflows/` | on PR | the outermost sensor: build, tests, type-check, secret scanning, Dockerfile lint, CODEOWNERS |

**Choosing the lever.** Always true and short: CLAUDE.md. True only for some files: a rule. A procedure or body of knowledge used sometimes: a skill. Work that should not pollute the main context, or needs different tools or a fresh reviewer: a subagent. Must happen regardless of what the model decides: a hook. Many items with the same shape and a verify step: a workflow.

**Skill and agent pairing.** Agents carry the role and tools; skills carry the knowledge. An agent that always needs a small skill preloads it with `skills:` in its frontmatter; larger skills stay on demand. The published sets are listed in `.claude/skills/README.md`.

**Structural facts worth knowing.** Skill descriptions are truncated at 1,536 characters in the listing and the platform limit is 1,024; SKILL.md bodies over 500 lines lose effectiveness; combined subagent descriptions over 15,000 tokens trigger a startup warning; CLAUDE.md should stay under 200 lines; MEMORY.md loads only its first 200 lines or 25 KB. Rules take only a `paths:` field. The full field reference is in `reference/claude-code-surface.md`.

**Public-repo hygiene.** This harness is published. Skills, agents, rules and hooks carry placeholders (`<PROJECT_ID>`, `<REGION>`, `<SERVICE>`, `<AR_REPO>`, `<SA_NAME>@<PROJECT_ID>.iam.gserviceaccount.com`), never real project ids, service URLs, bucket names, keys, personal names, or machine-specific paths. Personal settings go in `.claude/settings.local.json`, which stays out of git. The lint flags credential shapes as errors and real service-account emails, `*.run.app` URLs and home-directory paths as warnings.

# PART 4 - Audit checklist (run this when touching the harness)

Copy and tick:

```
Harness audit
- [ ] CLAUDE.md under 200 lines; every line would cause a mistake if removed
- [ ] Nothing in CLAUDE.md that only applies to some paths (move to .claude/rules/) or some tasks (move to a skill)
- [ ] Every skill has frontmatter: name == directory, description says what AND when, third person, under 1,024 chars
- [ ] Every SKILL.md body under 500 lines; overflow in reference/<topic>.md, linked one level deep, TOC if over 100 lines
- [ ] No stale facts (retired services, renamed components, dead vendors, old model names); superseded material under "Old patterns"
- [ ] Cross-references point only to skills, agents and files that exist in this repo
- [ ] Every agent description is one or two sentences plus "Use proactively when ..."; detail lives in the body
- [ ] Agents that always need one small skill preload it with skills:; no pasted memory boilerplate
- [ ] Every incident in the last month has a matching guard (hook rule, lint check, test) or a one-line rule where a guard is impossible
- [ ] Sensors speak to the model: error output says what to do next
- [ ] No secrets, real project ids, service URLs, personal names or local paths anywhere under .claude/
- [ ] Skills index regenerated; harness_lint.py reports zero errors
- [ ] Token levers reviewed: always-loaded text (CLAUDE.md + descriptions + memory index) is the smallest it can be
```

**The improvement loop (evaluation first).** Do the task once without the skill and note what you had to explain. Write the minimum skill that closes those gaps. Test it in a fresh session, with a smaller model tier if smaller models will use it. Watch which files the agent reads, which it ignores, and where it re-reads: move re-read content into SKILL.md, delete ignored content, make missed links explicit. Repeat when a real task exposes a gap.

**Worked examples of the mistake-to-guardrail loop.** Each row is a mistake agents really make on this stack and the cheapest guard that stops it for good.

| Mistake | Guard | Kind |
|---|---|---|
| Deploys a Cloud Run service with `--allow-unauthenticated` | `guard-bash.sh` denies it and says to keep the service private and grant `roles/run.invoker` | PreToolUse hook |
| Prints a Secret Manager value into the transcript | `guard-bash.sh` denies `gcloud secrets versions access` unless the value goes to a file or a variable | PreToolUse hook |
| `cat` of a `.env` file or a service-account key | `guard-bash.sh` denies and points to the `.example` file and to ADC | PreToolUse hook |
| Force-pushes `main` | `guard-bash.sh` denies; branch protection is the backstop | hook + repo setting |
| Force-adds ignored files (`git add -f .claude`, `.env`) | `guard-bash.sh` denies and says to fix the ignore rules instead | PreToolUse hook |
| Creates tables with `create_all()` instead of a migration | one line in the Python rule file + a CI check that models and migrations agree | rule + test |
| Leaves unformatted Python or lint errors behind | `post-edit.sh` runs ruff / eslint and feeds remaining findings back | PostToolUse hook |
| Writes a skill whose description never says when to use it | `harness_lint.py` W105 | lint |
| Links a skill to a doc that was later deleted | `harness_lint.py` W108 | lint |
| Pastes a key or a home-directory path into a skill | `harness_lint.py` E901 / `local-path` marker | lint |

# PART 5 - Token cost: what actually moves the bill

Cost is dominated by re-read (cached) input, then by what loads at session start, then by tool output. In order of leverage:

1. **Always-loaded text.** CLAUDE.md, every skill description, every agent description, the auto-memory index. Trimming these pays on every turn of every session.
2. **Fan-out width.** Each subagent restarts with the system context. Prefer few, well-scoped agents; design verify stages so a dead pool reports "unverified" rather than "confirmed".
3. **Session hygiene.** Clear between unrelated tasks, keep exploration in subagents, avoid repeated corrections in one thread.
4. **Skill size.** A 1,400-line skill costs about 15,000 tokens the moment it is invoked; the same knowledge split into a 300-line overview plus references costs a fifth of that on most tasks.
5. **Exploration.** A repo map or code index (symbol index, dependency graph) answers "where is X / what calls Y" from an explicit structure instead of many file reads. This is "a map, not a manual" applied to code; measure it on your own repo before trusting a vendor's multiplier.
6. **Tool output.** Claude Code already truncates pathological output. Filtering tools have little left to win.

**Output-compression proxies, a case study (RTK, Rust Token Killer).** RTK is an MIT CLI proxy that installs a PreToolUse hook rewriting Bash commands (`git status` -> `rtk git status`) to compress output, and advertises 60 to 90 percent savings. JetBrains ran a paired A/B benchmark (Claude Code 2.1.201, Sonnet, 86 SkillsBench tasks, 425 billable trials): at low effort RTK made sessions 7.6 percent *more* expensive (p = 0.004) and at high effort the difference was zero. The hook only sees about a third of Bash calls and a fifth of tool-result characters; `Read`, `Grep`, and `Glob` bypass it; cached re-reads dominate the bill; and its scoreboard measured its own diff, not the customer's invoice, reporting 96 million tokens "saved" while bills rose. Quality was unchanged, with one broken rewrite of compound `find` predicates. Verdict: do not adopt. The general lesson: a tool's self-reported savings describe its counterfactual, not your bill. Spend the effort on levers 1 to 4.

# PART 6 - Running the sensors

```bash
python3 .claude/scripts/harness_lint.py            # skills, agents, rules, hooks, CLAUDE.md; exit 1 on errors
python3 .claude/scripts/harness_lint.py --strict   # warnings fail too (use before a harness PR)
python3 .claude/scripts/harness_lint.py --paths .claude/skills/<name>   # one skill
python3 .claude/scripts/build_skills_index.py      # regenerate the README index block
python3 .claude/scripts/build_skills_index.py --check
```

**Lint codes.** `E0xx`/`W1xx` skills, `E2xx`/`W2xx` agents, `W3xx` rules and CLAUDE.md, `E4xx` settings and hooks, `E901` credential found. Marker warnings (`local-path`, `sa-email`, `run-url`, plus any project-specific ones) can be suppressed in a file that legitimately discusses them with `<!-- harness-lint: allow <marker-id> -->`. Add a marker to `MARKERS` in the script the day a name is renamed or retired.

**Hooks.**
- `.claude/hooks/guard-bash.sh` (PreToolUse, matcher `Bash`) denies: Cloud Run deploys or IAM bindings that make a service public; force-push to `main`/`master`; `gcloud secrets versions access` whose output is not sent to a file, a variable, or a stdin consumer; reading `.env`, `*.pem`, `*.key`, or service-account key files with `cat`/`less`/`head`/`tail`; `git add` of secret files; and `git add -f` on `.claude/` or the whole tree. Each denial carries the reason and the alternative.
- `.claude/hooks/post-edit.sh` (PostToolUse, matcher `Edit|Write`) runs `ruff check --fix` and `ruff format` on `.py`, `eslint --fix` on `web/**/*.ts(x)` when an ESLint config and local install exist, and `harness_lint.py` on `.claude/**` and `CLAUDE.md`. It never blocks; remaining findings come back to the model as `additionalContext`.

Test a rule by piping sample hook JSON into the script, once with a case it must deny and once with a near miss it must allow. The guard only inspects words in command position, so a sample string inside a `printf` argument is not itself blocked; for a table of many cases, keep them in a small test script.

```bash
printf '%s' '{"tool_input":{"command":"git push --force origin main"},"cwd":"."}' | .claude/hooks/guard-bash.sh   # deny JSON
printf '%s' '{"tool_input":{"command":"git push origin feat/x"},"cwd":"."}' | .claude/hooks/guard-bash.sh        # no output = allow
printf '%s' '{"tool_input":{"file_path":"'"$PWD"'/app/main.py"}}' | .claude/hooks/post-edit.sh
```

# PART 7 - Reading

- `reference/reading-list.md`: every source, grouped by topic, with one line on why it matters, plus a comma-separated list for NotebookLM.
- `reference/claude-code-surface.md`: the exact frontmatter fields, hook events, limits, and syntax for skills, agents, rules, and hooks in Claude Code 2.1.x.

---

*Distilled from primary sources fetched 2026-09-25. Re-verify links and version-specific limits before quoting them after a major Claude Code release.*
