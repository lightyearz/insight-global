# Claude Code harness surface (2.1.x): fields, events, limits

Distilled from the official docs on 2026-09-25. Re-check after a major release.

## Contents
- Skill frontmatter
- Subagent frontmatter
- Rules
- Hook events and control
- Settings files
- Limits and load order

## Skill frontmatter (`.claude/skills/<name>/SKILL.md`)

| Field | Meaning |
|---|---|
| `name` | Defaults to the directory name; lowercase, digits, hyphens; max 64 chars; no "anthropic"/"claude". |
| `description` | What it does and when to use it; loaded into every session. Platform max 1,024 chars. |
| `when_to_use` | Extra trigger phrases appended to the description; together truncated at 1,536 chars in the listing. |
| `paths` | Globs that limit automatic activation to when matching files are in play. |
| `user-invocable: false` | Hide from the `/` menu; Claude can still load it. |
| `disable-model-invocation: true` | Only the user can run it (side-effect workflows). |
| `allowed-tools` / `disallowed-tools` | Tool grants or removals for the turn the skill runs. |
| `model`, `effort` | Overrides while the skill is active. |
| `context: fork` + `agent:` | Run the skill in an isolated subagent (`Explore`, `Plan`, `general-purpose`, or a custom agent). |
| `hooks` | Hooks registered when the skill is invoked, for the rest of the session. |
| `argument-hint`, `arguments` | Autocomplete hint and named `$args`. |
| `metadata`, `license`, `compatibility` | Accepted, ignored by Claude Code. |

Dynamic context: a line starting with `` !`command` `` runs before Claude sees the skill and is replaced with its output. Substitutions: `$ARGUMENTS`, `${CLAUDE_SKILL_DIR}`, `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_EFFORT}`.

## Subagent frontmatter (`.claude/agents/<name>.md`)

| Field | Meaning |
|---|---|
| `name`, `description` | Required. Description is loaded every session; keep it short and add "Use proactively when ...". |
| `tools` / `disallowedTools` | Allowlist or denylist (`mcp__*` patterns work). |
| `model` | A model alias (`sonnet`, `opus`, `haiku`, ...), a full model id, or `inherit`. |
| `skills` | Skills whose full content is preloaded at spawn. |
| `memory` | `user`, `project` (`.claude/agent-memory/<name>/`), or `local`. Claude Code injects the memory instructions; do not paste them into the body. |
| `maxTurns`, `effort`, `permissionMode`, `background`, `isolation: worktree`, `omitClaudeMd`, `hooks`, `mcpServers`, `color` | Behavioural controls. |

A non-fork subagent receives: its body as system prompt, the delegation message, all CLAUDE.md files (unless `omitClaudeMd`), a git status snapshot, preloaded skills. It does not receive conversation history, previously read files, or previously invoked skills.

## Rules (`.claude/rules/*.md`)

Only one frontmatter field is read: `paths` (YAML list or comma-separated globs; brace expansion allowed). Rules without `paths` load every session with CLAUDE.md priority. Path-scoped rules load when Claude reads or edits a matching file. Subdirectories are discovered recursively; symlinks are allowed.

## Hook events and control (`.claude/settings.json`)

Events that matter for a user harness: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PostCompact`, `SessionEnd`, `Notification`, `FileChanged`, `InstructionsLoaded`.

Matchers: tool name for tool events (`Bash`, `Edit|Write`, regex like `mcp__.*`); `if: "Bash(git *)"` narrows further with permission-rule syntax.

Input: a command hook receives JSON on stdin with `session_id`, `cwd`, `hook_event_name`, and for tool events `tool_name` and `tool_input` (`tool_input.command` for Bash, `tool_input.file_path` for Edit/Write).

Control: exit code 2 blocks (PreToolUse, UserPromptSubmit, PreModelSwitch) and feeds stderr to Claude; exit 0 with JSON `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny|allow|ask|defer", "permissionDecisionReason": "...", "additionalContext": "...", "updatedInput": {...}}}` for structured decisions. A PostToolUse hook can return `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}` to hand findings to Claude without blocking. A Stop hook returning exit 2 keeps the turn going (up to 8 consecutive blocks).

Hook types: `command` (JSON on stdin), `http`, `mcp_tool`, `prompt` (a fast model judges), `agent` (a subagent with Read/Grep/Glob judges). Env: `CLAUDE_PROJECT_DIR`, `CLAUDE_EFFORT`; `${CLAUDE_PROJECT_DIR}` resolves inside `command`. Quote it (`"${CLAUDE_PROJECT_DIR}"/.claude/hooks/x.sh`) so paths with spaces work.

## Settings files

| File | Scope | In git |
|---|---|---|
| `.claude/settings.json` | project, shared with the team | yes |
| `.claude/settings.local.json` | project, personal overrides | no (gitignore it) |
| `~/.claude/settings.json` | user, all projects | n/a |
| managed policy | organisation | n/a |

Permission rules use `Tool(specifier)` syntax, for example `Bash(pytest:*)` or `Bash(python3 .claude/scripts/*)`. Keep the shared allowlist small: every entry is a command Claude may run without asking.

## Limits and load order

- CLAUDE.md: target under 200 lines; files up to 4 MiB load, larger are skipped. `@path` imports load at launch (depth 4). Block HTML comments are stripped before injection.
- MEMORY.md (auto memory and agent memory): first 200 lines or 25 KB.
- Skills: description always; body on invocation; after compaction each re-attached skill keeps its first 5,000 tokens, 25,000 combined.
- Subagents: combined descriptions over 15,000 tokens warn at startup; nesting depth 3; 20 concurrent by default.
- Load order of instructions: managed policy, user `~/.claude/CLAUDE.md` and `~/.claude/rules/`, project `CLAUDE.md` and `.claude/rules/`, nested CLAUDE.md files on traversal, path-scoped rules on file match.
