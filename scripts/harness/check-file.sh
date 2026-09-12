#!/usr/bin/env bash
# AUTO-GENERATED FROM erpnext-ai-forge 0.1.0 — DO NOT EDIT
# Source: canonical/harness/scripts/check-file.sh.j2
# Target: self (python_cli)
#
# Lint one file and fail if anything remains. Called by the file-edit hook, and
# usable by hand: scripts/harness/check-file.sh path/to/file [more…]

set -euo pipefail
# shellcheck source=/dev/null
. "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

[ "$#" -gt 0 ] || { note "check-file: no paths given; nothing to do."; exit 0; }

rc=0

for FILE in "$@"; do
  [ -f "$FILE" ] || continue

  # Generated and vendored trees are not ours to lint, and failures there are
  # not actionable by whoever triggered the hook.
  case "$FILE" in
    */node_modules/*|*/.venv/*|*/dist/*|*/build/*|*/__pycache__/*|*.generated.*)
      continue
      ;;
  esac

  # --- python-lint [VERIFIED] ---
  case "$FILE" in
    *.py)
      if ! run_to 120 \
           uv run --project forge ruff check --fix "$(_abs_of "$FILE")" 2>&1 | cap; then
        fail_block "python-lint failed on $FILE"
        rc=1
      fi
      ;;
  esac

done

exit "$rc"
