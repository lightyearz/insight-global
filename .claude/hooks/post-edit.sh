#!/usr/bin/env bash
# PostToolUse hook for Edit|Write (a harness "sensor": observes, never blocks).
#
# Formats and lints the file that was just changed:
#   *.py                    ruff check --fix + ruff format (when ruff is installed)
#   web/**/*.ts, *.tsx      eslint --fix (when web/ has an ESLint config and a local install)
#   .claude/**, CLAUDE.md   .claude/scripts/harness_lint.py on that path
# Anything the tools could not fix is handed back to Claude as
# additionalContext so it can self-correct. Always exits 0.
#
# Input: hook JSON on stdin, e.g. {"tool_input":{"file_path":"/abs/path.py"}}
# Needs: bash, jq. Without jq it does nothing.

command -v jq >/dev/null 2>&1 || exit 0
f=$(jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0
[ -n "$f" ] || exit 0
root="${CLAUDE_PROJECT_DIR:-$PWD}"
root="${root%/}"
case "$f" in /*) ;; *) f="$root/$f" ;; esac
[ -f "$f" ] || exit 0

# Only touch files inside this project.
case "$f" in "$root"/*) ;; *) exit 0 ;; esac

notes=""
add_note() { notes+="$1"$'\n\n'; }

case "$f" in
  *.py)
    if command -v ruff >/dev/null 2>&1; then
      ruff=(ruff)
    elif python3 -m ruff --version >/dev/null 2>&1; then
      ruff=(python3 -m ruff)
    else
      ruff=()
    fi
    if [ "${#ruff[@]}" -gt 0 ]; then
      out=$(cd "$root" && "${ruff[@]}" check --fix --quiet "$f" 2>&1 | tail -n 20)
      (cd "$root" && "${ruff[@]}" format --quiet "$f" >/dev/null 2>&1)
      [ -n "$out" ] && add_note "ruff could not auto-fix these in $f; fix them before moving on:"$'\n'"$out"
    fi
    ;;
  */web/*.ts | */web/*.tsx)
    web="${f%%/web/*}/web"
    eslint="$web/node_modules/.bin/eslint"
    has_config=0
    for c in "$web"/eslint.config.js "$web"/eslint.config.mjs "$web"/eslint.config.cjs \
      "$web"/eslint.config.ts "$web"/eslint.config.mts "$web"/.eslintrc \
      "$web"/.eslintrc.js "$web"/.eslintrc.cjs "$web"/.eslintrc.json "$web"/.eslintrc.yml; do
      [ -f "$c" ] && has_config=1 && break
    done
    if [ "$has_config" = 1 ] && [ -x "$eslint" ]; then
      out=$(cd "$web" && "$eslint" --fix "$f" 2>&1 | tail -n 30)
      [ -n "$out" ] && add_note "eslint could not auto-fix these in $f (also run the type-check script in web/ before finishing):"$'\n'"$out"
    fi
    ;;
esac

case "$f" in
  */.claude/* | */CLAUDE.md)
    lint="$root/.claude/scripts/harness_lint.py"
    if [ -f "$lint" ] && command -v python3 >/dev/null 2>&1; then
      out=$(python3 "$lint" --root "$root" --paths "$f" 2>&1)
      if printf '%s\n' "$out" | grep -Eq '^(ERROR|WARNING) '; then
        add_note "harness_lint findings after editing $f:"$'\n'"$(printf '%s\n' "$out" | tail -n 25)"
      fi
    fi
    ;;
esac

if [ -n "$notes" ]; then
  jq -n --arg ctx "$notes" '{
    hookSpecificOutput: {
      hookEventName: "PostToolUse",
      additionalContext: $ctx
    }
  }'
fi
exit 0
