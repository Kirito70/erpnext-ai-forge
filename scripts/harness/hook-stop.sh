#!/usr/bin/env bash
# AUTO-GENERATED FROM erpnext-ai-forge 0.1.0 — DO NOT EDIT
# Source: canonical/harness/scripts/hook-stop.sh.j2
# Target: self (python_cli)
#
# Refuses to let a session end on red gates. Exit 2 = blocking.
#
# Runs `quick` only — never `full`. On a Frappe bench the full suite is minutes,
# and a Stop hook that takes minutes is a Stop hook someone disables. Full gates
# belong to /ticket-review, run once by the orchestrator.

set -euo pipefail
# shellcheck source=/dev/null
. "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

INPUT="$(cat || true)"

# Loop guard. When we block, the agent stops again, which fires this hook again.
# Without honouring the tool's own re-entry flag that is an infinite loop.
case "$INPUT" in
  *'"stop_hook_active": true'*|*'"stop_hook_active":true'*)
    exit 0
    ;;
esac

# Session id, so the dirty marker matches the one the edit hook wrote.
PY=""
for candidate in python3 python py; do
  if command -v "$candidate" >/dev/null 2>&1 \
     && "$candidate" -c 'print(1)' >/dev/null 2>&1; then
    PY="$candidate"; break
  fi
done

SESSION=""
if [ -n "$PY" ] && [ -n "$INPUT" ]; then
  SESSION="$(printf '%s' "$INPUT" | "$PY" -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(); raise SystemExit(0)
print(d.get("session_id") or d.get("sessionId") or "")
' 2>/dev/null || printf '')"
fi
export FORGE_SESSION_ID="${SESSION:-nosession}"

# Fast path: nothing was edited, so there is nothing to verify. A read-only or
# docs-only session must cost nothing to end, or the hook becomes a tax on
# every conversation and gets removed.
if ! is_dirty; then
  exit 0
fi

HARNESS="$(dirname -- "${BASH_SOURCE[0]}")"
unset FORGE_HARNESS_ACTIVE

status=0
"$HARNESS/gates.sh" quick || status=$?

if [ "$status" -ne 0 ]; then
  fail_block "gates are RED — this session cannot end in a 'done' state."
  note "Run: scripts/harness/gates.sh quick"
  exit 2
fi

# Green: clear the marker so a follow-up session with no edits ends instantly.
clear_dirty
exit 0
