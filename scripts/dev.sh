#!/usr/bin/env bash
# Start / stop the Health Briefing stack locally: FastAPI on :8080 and the Next.js web app on :3000.
#
#   scripts/dev.sh [start|stop|restart|status|logs]
#
# Defaults to fully offline REPLAY mode (LLM_PROVIDER=replay, DATA_MODE=replay) unless you set
# LLM_PROVIDER / DATA_MODE yourself or have an api/.env (then the API's own settings apply).
#
# Env:
#   API_PORT (8080)  WEB_PORT (3000)
#   WEB_MODE  dev (next dev, hot reload; default) | prod (next build + next start)
#   RUN_DIR   where PID files and logs go (default: <repo>/.run)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${RUN_DIR:-$ROOT/.run}"
API_PORT="${API_PORT:-8080}"
WEB_PORT="${WEB_PORT:-3000}"
WEB_MODE="${WEB_MODE:-dev}"
API_LOG="$RUN_DIR/api.log"
WEB_LOG="$RUN_DIR/web.log"
mkdir -p "$RUN_DIR"

# Run a command detached in its own session (so stop can kill the whole process group); the PID
# file holds the session leader's pid, which is also the process-group id.
launch() { # pidfile logfile cmd...
  local pidfile="$1" logfile="$2"; shift 2
  setsid bash -c 'echo $$ >"$0"; exec "$@"' "$pidfile" "$@" >>"$logfile" 2>&1 </dev/null &
  for _ in $(seq 1 20); do [[ -s "$pidfile" ]] && return 0; sleep 0.1; done
}

is_running() { [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null; }

wait_for() { # url seconds
  local url="$1" secs="$2" i
  for ((i = 0; i < secs * 2; i++)); do
    curl -sf -o /dev/null "$url" && return 0
    sleep 0.5
  done
  return 1
}

start_api() {
  if is_running "$RUN_DIR/api.pid"; then echo "api: already running (pid $(cat "$RUN_DIR/api.pid"))"; return; fi
  command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
  if [[ -z "${LLM_PROVIDER:-}" && -z "${DATA_MODE:-}" && ! -f "$ROOT/api/.env" ]]; then
    export LLM_PROVIDER=replay DATA_MODE=replay
  fi
  export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:$WEB_PORT}"
  (cd "$ROOT/api" && uv sync --quiet)
  : >"$API_LOG"
  echo "api: starting on :$API_PORT (LLM_PROVIDER=${LLM_PROVIDER:-<api/.env>}, DATA_MODE=${DATA_MODE:-<api/.env>})"
  (cd "$ROOT/api" && launch "$RUN_DIR/api.pid" "$API_LOG" uv run uvicorn app.main:app --port "$API_PORT")
  wait_for "http://localhost:$API_PORT/api/health" 60 || { echo "api: did not start, see $API_LOG" >&2; exit 1; }
  echo "api: $(curl -s "http://localhost:$API_PORT/api/health")"
}

start_web() {
  if is_running "$RUN_DIR/web.pid"; then echo "web: already running (pid $(cat "$RUN_DIR/web.pid"))"; return; fi
  export NEXT_PUBLIC_API_MODE="${NEXT_PUBLIC_API_MODE:-api}"
  export API_BASE_URL="${API_BASE_URL:-http://localhost:$API_PORT}"
  [[ -d "$ROOT/web/node_modules" ]] || (cd "$ROOT/web" && npm install --no-audit --no-fund)
  local cmd
  if [[ "$WEB_MODE" == "prod" ]]; then
    echo "web: building (API_BASE_URL=$API_BASE_URL is baked into the proxy rewrite)"
    (cd "$ROOT/web" && npm run build >"$WEB_LOG" 2>&1) || { echo "web: build failed, see $WEB_LOG" >&2; exit 1; }
    cmd=(npx next start -p "$WEB_PORT")
  else
    cmd=(npx next dev -p "$WEB_PORT")
  fi
  echo "web: starting on :$WEB_PORT ($WEB_MODE, NEXT_PUBLIC_API_MODE=$NEXT_PUBLIC_API_MODE)"
  (cd "$ROOT/web" && launch "$RUN_DIR/web.pid" "$WEB_LOG" "${cmd[@]}")
  wait_for "http://localhost:$WEB_PORT/" 120 || { echo "web: did not start, see $WEB_LOG" >&2; exit 1; }
  echo "web: http://localhost:$WEB_PORT"
}

stop_one() { # name
  local pidfile="$RUN_DIR/$1.pid"
  if is_running "$pidfile"; then
    local pid; pid="$(cat "$pidfile")"
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -9 -- "-$pid" 2>/dev/null || true
    echo "$1: stopped"
  else
    echo "$1: not running"
  fi
  rm -f "$pidfile"
}

status() {
  for name in api web; do
    if is_running "$RUN_DIR/$name.pid"; then echo "$name: running (pid $(cat "$RUN_DIR/$name.pid"))"; else echo "$name: stopped"; fi
  done
  curl -s "http://localhost:$API_PORT/api/health" && echo || true
}

case "${1:-start}" in
  start) start_api; start_web ;;
  stop) stop_one web; stop_one api ;;
  restart) stop_one web; stop_one api; start_api; start_web ;;
  status) status ;;
  logs) tail -n 50 -f "$API_LOG" "$WEB_LOG" ;;
  *) echo "usage: $0 [start|stop|restart|status|logs]" >&2; exit 2 ;;
esac
