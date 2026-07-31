#!/usr/bin/env bash
# AUTO-GENERATED FROM erpnext-ai-forge 0.1.0 — DO NOT EDIT
# Source: canonical/harness/scripts/typecheck.sh.j2
# Target: self (python_cli)
#
# ADVISORY. Always exits 0, on purpose.
#
# A type error is usually cross-file, and a multi-file refactor passes through
# genuinely broken intermediate states. Blocking each edit until the whole tree
# type-checks makes the hook impossible to work with, and the reliable outcome
# of an unworkable hook is that someone turns it off. So: report, do not block.

set -uo pipefail
# shellcheck source=/dev/null
. "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

# mypy [VERIFIED]
out="$(run_to 120 uv run --project forge mypy forge/src/forge 2>&1)" || true
if printf '%s' "$out" | grep -qE 'error:|error TS'; then
  note "typecheck (mypy) reported problems — advisory, not blocking:"
  printf '%s\n' "$out" | grep -E 'error:|error TS' | cap 20 >&2
fi

exit 0
