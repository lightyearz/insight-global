#!/usr/bin/env bash
# End-to-end checks against the running stack (replay mode by default):
#   1. API smoke flow (scripts/smoke_api.py) for every condition: create -> SSE -> review -> report checks.
#   2. Playwright UI flow (web/e2e/flow.spec.ts) for every condition, through the web proxy.
#
# If the stack is not running it is started with scripts/dev.sh and stopped again afterwards
# (set KEEP_RUNNING=1 to leave it up).
#
# Env:
#   E2E_CONDITIONS  semicolon-separated (default "type 2 diabetes;hypertension")
#   API_PORT (8080) WEB_PORT (3000)
#   PLAYWRIGHT_BROWSERS_PATH  optional: folder of preinstalled Playwright browsers (never downloads browsers)
#   SKIP_API=1 / SKIP_UI=1    run only one half
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${API_PORT:-8080}"
WEB_PORT="${WEB_PORT:-3000}"
IFS=';' read -r -a CONDITIONS <<<"${E2E_CONDITIONS:-type 2 diabetes;hypertension}"

started=0
if ! curl -sf -o /dev/null "http://localhost:$API_PORT/api/health" || ! curl -sf -o /dev/null "http://localhost:$WEB_PORT/"; then
  API_PORT="$API_PORT" WEB_PORT="$WEB_PORT" "$ROOT/scripts/dev.sh" start
  started=1
fi
cleanup() { if [[ "$started" == 1 && "${KEEP_RUNNING:-0}" != 1 ]]; then "$ROOT/scripts/dev.sh" stop; fi; }
trap cleanup EXIT

fail=0
if [[ "${SKIP_API:-0}" != 1 ]]; then
  echo "== API smoke flow =="
  python3 "$ROOT/scripts/smoke_api.py" --base "http://localhost:$API_PORT" "${CONDITIONS[@]}" | grep -v '\[ok\]' || fail=1
fi

if [[ "${SKIP_UI:-0}" != 1 ]]; then
  for cond in "${CONDITIONS[@]}"; do
    echo "== Playwright UI flow: $cond =="
    (cd "$ROOT/web" && E2E_CONDITION="$cond" E2E_BASE_URL="http://localhost:$WEB_PORT" \
      npx playwright test --reporter=list) || fail=1
  done
fi

if [[ "$fail" == 0 ]]; then echo "E2E: PASS"; else echo "E2E: FAIL" >&2; fi
exit "$fail"
