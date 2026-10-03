#!/usr/bin/env bash
# PreToolUse guard for the Bash tool (a harness "guard": deterministic, says no).
#
# Denies a short list of commands that are never right in this repo and tells
# Claude what to do instead. When an agent makes a mistake you never want
# repeated, add a rule here (the mistake-to-guardrail loop in the
# harness-engineering skill), then test it with a case it must deny and a near
# miss it must allow.
#
# Input:  hook JSON on stdin, e.g. {"tool_input":{"command":"..."},"cwd":"..."}
# Output: a JSON deny decision on stdout, or nothing (normal permission flow).
# Needs:  bash, jq, awk. Without jq it allows everything (fails open).
# No `set -u` / `pipefail`: empty arrays break -u on older bash, and `grep -q`
# closing a pipe early must not turn a match into a failure.

command -v jq >/dev/null 2>&1 || exit 0
input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null) || exit 0
[ -z "$cmd" ] && exit 0
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null) || cwd=""
[ -n "$cwd" ] || cwd="${CLAUDE_PROJECT_DIR:-$PWD}"

deny() {
  jq -n --arg reason "Blocked by .claude/hooks/guard-bash.sh: $1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

# --- parsing helpers ---------------------------------------------------------

# Heredoc bodies are data written somewhere, not commands: drop them.
strip_heredocs() {
  awk '
    skip { line = $0; sub(/^[ \t]+/, "", line); if (line == delim) skip = 0; next }
    {
      print
      if (match($0, /(^|[^<])<<-?[ \t]*["\047]?[A-Za-z_][A-Za-z0-9_]*["\047]?/)) {
        d = substr($0, RSTART, RLENGTH)
        sub(/^[^<]*<<-?[ \t]*/, "", d)
        gsub(/["\047]/, "", d)
        delim = d; skip = 1
      }
    }'
}

# One line per list element: split on newlines, ;, &&, ||.
split_segments() { awk '{ gsub(/&&|\|\||;/, "\n"); print }'; }

# One line per simple command: also split pipes and command substitutions.
split_stages() { awk '{ gsub(/\||\$\(|`|\(|\)/, "\n"); print }'; }

# True when a path names a file that holds credentials.
is_secret_path() {
  local p="${1//[\"\']/}"
  p="${p%/}"
  local b="${p##*/}"
  case "$b" in
    *.example | *.template | *.sample | *.dist) return 1 ;;
    .env | .env.* | .env[*?]* | *.env | .envrc) return 0 ;;
    *.pem | *.p12 | *.pfx | *.key) return 0 ;;
    *sa-key*.json | *service-account*.json | *credentials*.json) return 0 ;;
  esac
  return 1
}

clean_cmd=$(printf '%s\n' "$cmd" | strip_heredocs)

# --- rule 1: Secret Manager values never land in the transcript --------------
# Allowed: --out-file, a stdout redirect to a file, capture into a variable,
# or a pipe into a stdin consumer (docker login --password-stdin, wc, sha256sum).
while IFS= read -r seg; do
  printf '%s' "$seg" | grep -Eq '(^|[|(`]|\$\()[[:space:]]*(sudo[[:space:]]+)?gcloud[[:space:]]+([^[:space:]]+[[:space:]]+)*secrets[[:space:]]+versions[[:space:]]+access' || continue
  printf '%s' "$seg" | grep -Eq -- '--out-file' && continue
  printf '%s' "$seg" | grep -Eq '(^|[^0-9&<>])>>?[[:space:]]*[^&[:space:]|]' && continue
  printf '%s' "$seg" | grep -Eq '[A-Za-z_][A-Za-z0-9_]*=["]?(\$\(|`)[[:space:]]*gcloud' && continue
  printf '%s' "$seg" | grep -Eq '\|[^|]*(--password-stdin|--data-file=-|--data-file=/dev/stdin|(^|[[:space:]|])(wc|sha256sum|shasum|md5sum)([[:space:]]|$))' && continue
  deny "'gcloud secrets versions access' would print a secret into the transcript, which may be logged or shared. Write it to a file instead (--out-file=<path> or > <path>, both gitignored), capture it in a variable (VAR=\$(gcloud secrets versions access ...)), or pipe it into the consumer (... | docker login --password-stdin). To check a secret exists, use 'gcloud secrets versions list <SECRET>'."
done < <(printf '%s\n' "$clean_cmd" | split_segments)

# --- per-command rules -------------------------------------------------------
while IFS= read -r stage; do
  [ -n "${stage//[[:space:]]/}" ] || continue
  read -r -a words <<<"$stage"
  for k in "${!words[@]}"; do words[$k]="${words[$k]//[\"\']/}"; done
  # Skip leading env assignments and wrappers.
  i=0
  while [ "$i" -lt "${#words[@]}" ]; do
    case "${words[$i]}" in
      sudo | env | command | time | nohup | exec | [A-Za-z_]*=*) i=$((i + 1)) ;;
      *) break ;;
    esac
  done
  w=("${words[@]:$i}")
  [ "${#w[@]}" -gt 0 ] || continue
  prog="${w[0]##*/}"
  args=("${w[@]:1}")

  case "$prog" in
    # --- rule 2: Cloud Run services stay private ------------------------------
    gcloud)
      joined=" ${args[*]} "
      case "$joined" in *" run "*) ;; *) continue ;; esac
      for a in "${args[@]}"; do
        if [ "$a" = "--allow-unauthenticated" ]; then
          deny "Cloud Run services stay private: deploy with --no-allow-unauthenticated. Callers authenticate with an OIDC identity token and need roles/run.invoker on the service (grant it to the caller's service account). If a service must be public, change that in reviewed infrastructure code or CI, not from an agent shell."
        fi
      done
      case "$joined" in
        *" add-iam-policy-binding "*)
          case "$joined" in
            *allUsers* | *allAuthenticatedUsers*)
              deny "Granting a Cloud Run service to allUsers/allAuthenticatedUsers makes it public. Grant roles/run.invoker to the specific caller service account instead (<SA_NAME>@<PROJECT_ID>.iam.gserviceaccount.com)."
              ;;
          esac
          ;;
      esac
      ;;

    # --- rule 3: credential files are never printed ---------------------------
    cat | less | more | head | tail | bat | batcat | nl | tac)
      for a in "${args[@]}"; do
        case "$a" in -*) continue ;; esac
        if is_secret_path "$a"; then
          deny "reading '$a' would print credentials into the transcript. For variable names read the matching .example/.template file; to check one variable is set use: grep -c '^NAME=' $a. Google credentials should not live on disk: use Application Default Credentials (gcloud auth application-default login) locally and Workload Identity Federation in CI."
        fi
      done
      ;;

    git)
      # Find the subcommand, skipping global options (-C <dir>, -c <k=v>, --x=y).
      j=0
      dir="$cwd"
      while [ "$j" -lt "${#args[@]}" ]; do
        case "${args[$j]}" in
          -C) dir="${args[$((j + 1))]:-$dir}"; case "$dir" in /*) ;; *) dir="$cwd/$dir" ;; esac; j=$((j + 2)) ;;
          -c | --git-dir | --work-tree | --namespace) j=$((j + 2)) ;;
          -*) j=$((j + 1)) ;;
          *) break ;;
        esac
      done
      sub="${args[$j]:-}"
      rest=("${args[@]:$((j + 1))}")

      case "$sub" in
        # --- rule 4: no force-push to main/master -----------------------------
        push)
          force=0
          positional=()
          for a in "${rest[@]}"; do
            case "$a" in
              --force* | --mirror) force=1 ;;
              --*) ;;
              -*f*) force=1 ;;
              -*) ;;
              *) positional+=("$a") ;;
            esac
          done
          refspecs=("${positional[@]:1}")
          hit=0
          for r in "${refspecs[@]}"; do
            plus=0
            case "$r" in +*) plus=1; r="${r#+}" ;; esac
            dst="${r##*:}"
            dst="${dst#refs/heads/}"
            [ "$dst" = HEAD ] && dst=$(git -C "$dir" symbolic-ref --short -q HEAD 2>/dev/null || true)
            if { [ "$force" = 1 ] || [ "$plus" = 1 ]; } && { [ "$dst" = main ] || [ "$dst" = master ]; }; then
              hit=1
            fi
          done
          if [ "$force" = 1 ] && [ "${#refspecs[@]}" -eq 0 ]; then
            branch=$(git -C "$dir" symbolic-ref --short -q HEAD 2>/dev/null || true)
            case "$branch" in main | master) hit=1 ;; esac
          fi
          if [ "$hit" = 1 ]; then
            deny "never force-push main/master. Push a feature branch (feat/..., fix/..., chore/...) and open a pull request. If main really must be rewritten, a human does it deliberately with branch protection temporarily lifted."
          fi
          ;;

        # --- rule 5: no committing secrets, no force-adding ignored files -----
        add)
          force=0
          paths=()
          for a in "${rest[@]}"; do
            case "$a" in
              --force) force=1 ;;
              --) ;;
              --*) ;;
              -*f*) force=1 ;;
              -*) ;;
              *) paths+=("$a") ;;
            esac
          done
          for p in "${paths[@]}"; do
            if is_secret_path "$p"; then
              deny "'$p' holds secrets and must never be committed. Commit a .example file with placeholder values instead; real values live in Secret Manager (or a local, gitignored file). If it is already staged, run: git restore --staged $p"
            fi
          done
          if [ "$force" = 1 ]; then
            for p in "${paths[@]}"; do
              p="${p//[\"\']/}"
              case "$p" in
                .claude | .claude/* | ./.claude | ./.claude/* | */.claude | */.claude/*)
                  deny "'git add -f' on .claude/ bypasses the ignore rules and can commit local-only files (settings.local.json, agent memory, credentials). Fix the ignore rules instead (remove the /.claude/ line from .git/info/exclude, or add a targeted negation to .gitignore), keep .claude/settings.local.json ignored, then 'git add' the specific files."
                  ;;
                . | ./ | '*' | :/ | :)
                  deny "'git add -f' on the whole tree stages every ignored file (.env, keys, build output). Add the specific paths you mean, and fix .gitignore if a wanted file is ignored."
                  ;;
              esac
            done
          fi
          ;;
      esac
      ;;
  esac
done < <(printf '%s\n' "$clean_cmd" | split_segments | split_stages)

exit 0
