#!/usr/bin/env bash
# AUTO-GENERATED FROM erpnext-ai-forge 0.1.0 — DO NOT EDIT
# Source: canonical/harness/scripts/gates.sh.j2
# Target: self (python_cli)
#
#   gates.sh quick   cheap checks — safe to run when a session ends
#   gates.sh full    the real Definition of Done; minutes, not seconds
#   gates.sh all     alias for full
#
# Prints one line per gate and a final RESULT. Never infer success from a quiet
# exit: read the RESULT line.

set -euo pipefail
# shellcheck source=/dev/null
. "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

MODE="${1:-quick}"
case "$MODE" in
  quick|full|all) ;;
  *) printf 'usage: gates.sh [quick|full|all]\n' >&2; exit 2 ;;
esac

# The `full` gates are per-app (`bench run-tests --app X`, a frontend build in
# X's workspace), so they need a subject. Unlike check-file.sh this script is
# not handed one — and the gate table's {app}/{app_dir}/{js_dir} placeholders
# all expand to helpers that read $FILE. Referencing it undefined under `set -u`
# aborted the whole run at the first full gate, which is why `gates.sh full`
# has never completed.
#
# Explicit second argument wins; otherwise infer from what the working tree has
# changed. Never guessed: an empty subject skips the per-app gates loudly.
FILE="$(_subject_path "${2:-}")"
if [ -z "$FILE" ] && [ "$MODE" != "quick" ]; then
  FILE="$(_changed_app_path)"
  [ -n "$FILE" ] && note "gates: subject inferred from working tree -> $FILE"
fi

failed=0
declare -a RESULTS=()

run_gate() {
  local id="$1" secs="$2"; shift 2
  local out status
  printf '\n[gate] %s\n' "$id" >&2
  set +e
  out="$(run_to "$secs" "$@" 2>&1)"; status=$?
  set -e
  if [ "$status" -eq 0 ]; then
    RESULTS+=("PASS  $id")
  else
    printf '%s\n' "$out" | cap >&2
    RESULTS+=("FAIL  $id (exit $status)")
    failed=1
  fi
}

printf '=== harness gates (%s) — target %s ===\n' "$MODE" "self" >&2

# ruff [VERIFIED]
run_gate "ruff" 300 uv run --project forge ruff check forge/src
# mypy [VERIFIED]
run_gate "mypy" 300 uv run --project forge mypy forge/src/forge
# forge-validate [VERIFIED]
# --no-check-drift matters: validate's default reads the BENCH, and a hook in this repo must not depend on a bench being present.
run_gate "forge-validate" 300 uv run --project forge forge validate --no-check-drift

if [ "$MODE" != "quick" ]; then
  # pytest [VERIFIED]
  run_gate "pytest" 600 uv run --project forge pytest forge/tests -q
  # forge-score [VERIFIED]
  run_gate "forge-score" 1800 uv run --project forge forge score --path canonical/ --fail-below 80
fi

printf '\n=== harness gates (%s) ===\n' "$MODE" >&2
for line in "${RESULTS[@]}"; do printf '  %s\n' "$line" >&2; done

if [ "$failed" -ne 0 ]; then
  printf '\nRESULT: RED — the task is NOT done until every gate above passes.\n' >&2
  exit 1
fi
printf '\nRESULT: GREEN\n' >&2
