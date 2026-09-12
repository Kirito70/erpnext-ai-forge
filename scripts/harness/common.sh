#!/usr/bin/env bash
# AUTO-GENERATED FROM erpnext-ai-forge 0.1.0 — DO NOT EDIT
# Source: canonical/harness/scripts/common.sh.j2
# Target: self (python_cli)
#
# Sourced, not executed. Every function here is stack-agnostic; the commands
# they run are inlined into the calling script at render time.

set -euo pipefail

# The repo this harness governs. Resolved from the script's own location so it
# is correct no matter where the agent's cwd happens to be — hooks fire with an
# unpredictable cwd, and a relative guess silently lints the wrong tree.
HARNESS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$HARNESS_DIR/../.." && pwd)"
export REPO_ROOT

# Re-entrancy guard. `check-file` runs a formatter that WRITES to the file it
# was called about, which in some tools re-triggers the same edit hook. Without
# this the second invocation edits again and the loop does not terminate.
# Also read by `forge sync --target self`, which refuses to rewrite scripts
# while one of them is executing.
if [ -n "${FORGE_HARNESS_ACTIVE:-}" ]; then
  exit 0
fi
export FORGE_HARNESS_ACTIVE=1

# Cap on echoed output. A hook's stdout goes into the model's context; an
# unbounded lint dump costs more than the failure it reports.
HARNESS_MAX_LINES="${HARNESS_MAX_LINES:-40}"

cap() {
  local n="${1:-$HARNESS_MAX_LINES}"
  awk -v max="$n" '
    { lines[NR] = $0 }
    END {
      start = (NR > max) ? NR - max + 1 : 1
      if (start > 1) print "… " (start - 1) " earlier line(s) omitted"
      for (i = start; i <= NR; i++) print lines[i]
    }'
}

# Timeout wrapper. A hook that hangs is worse than one that fails: the agent
# waits forever with no signal. Falls back to running bare where no timeout
# binary exists (macOS without coreutils) rather than refusing to run.
run_to() {
  local secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$secs" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$secs" "$@"
  else
    "$@"
  fi
}

# --- session dirty marker --------------------------------------------------
# The Stop gate is the expensive one. A session that only read files, or only
# touched docs, should pay nothing to end. So an edit hook marks the session
# dirty and the Stop hook exits immediately when the marker is absent.
#
# Keyed by repo path AND session id: two agents in two checkouts must not share
# a marker, or one clearing it lets the other end on red.
_marker_path() {
  local key
  key="$(printf '%s' "$REPO_ROOT" | cksum | tr -d ' \t' )"
  printf '%s/forge-harness-%s-%s.dirty' \
    "${TMPDIR:-/tmp}" "$key" "${FORGE_SESSION_ID:-nosession}"
}

mark_dirty()  { : > "$(_marker_path)"; }
is_dirty()    { [ -f "$(_marker_path)" ]; }
clear_dirty() { rm -f "$(_marker_path)"; }

# --- path helpers ----------------------------------------------------------
# `apps/<app>/…` -> the app directory. Frontend tooling has to run from inside
# the app that owns the file; running `yarn lint` from the bench root either
# fails or, worse, lints a different app.
# Prints nothing when the path is not under apps/, which callers treat as
# "no app context".
_app_dir_of() {
  local path="$1" rel
  case "$path" in
    /*) rel="${path#"$REPO_ROOT"/}" ;;
    *)  rel="$path" ;;
  esac
  case "$rel" in
    # `apps/<app>/…` — a file inside an app.
    apps/*/*) printf '%s/apps/%s' "$REPO_ROOT" "$(printf '%s' "${rel#apps/}" | cut -d/ -f1)" ;;
    # `apps/<app>` — the app directory itself, with no trailing path. This is
    # what _subject_path produces from a bare app name, and it is a legitimate
    # subject in its own right; matching only `apps/*/*` left it resolving to
    # nothing, which was the second half of HARNESS-005. `apps/` alone (empty
    # app) must still resolve to nothing, hence `?*` rather than `*`.
    apps/?*)  printf '%s/apps/%s' "$REPO_ROOT" "${rel#apps/}" ;;
    *)        printf '' ;;
  esac
}

# A gate subject may arrive as a path (`apps/<app>/…`) or as a bare app name
# (`gates.sh full novizna_pos`) — the form AGENTS-HARNESS.md documents and the
# form every ticket Test Plan uses. _app_dir_of matches only `apps/*/*`, so a
# bare name resolved to the empty string, `bench run-tests --app ""` then ran
# EVERY app, and the run died on unrelated site fixture state — which reads to
# the operator as "my code broke the tests" (HARNESS-005).
#
# Normalising once, here, keeps _app_dir_of and _js_dir_of unchanged: they go on
# taking a path and only ever see a path. A bare token becomes an app only when
# apps/<token> really is a directory — never guessed. Anything else is returned
# untouched, so a non-app subject still resolves to no app and the caller skips
# loudly rather than silently widening its scope.
_subject_path() {
  local s="$1"
  case "$s" in
    ""|*/*) printf '%s' "$s"; return ;;
  esac
  if [ -d "$REPO_ROOT/apps/$s" ]; then printf 'apps/%s' "$s"; else printf '%s' "$s"; fi
}

# `apps/<app>/…` -> the app name, for gates that take --app.
_app_of() {
  local d
  d="$(_app_dir_of "$1")"
  [ -n "$d" ] && basename "$d" || printf ''
}

# `apps/<app>/…` -> the JS workspace that owns the file: the nearest ancestor
# directory containing a package.json, bounded by the app.
#
# NOT the same as _app_dir_of, and the difference is the whole point. A Frappe
# app's JS workspace is not required to sit at the app root:
#
#   apps/novizna_pos/novizna-pos-ui/package.json   <- nested; app root has none
#   apps/novizna_crm/package.json                  <- at the app root
#   apps/novizna_crm/crm_build/package.json        <- and a second one below it
#
# Feeding _app_dir_of to `yarn --cwd` therefore fails outright for novizna_pos
# ("Couldn't find a package.json file in …/apps/novizna_pos") on EVERY frontend
# edit, and for novizna_crm picks the root workspace even when the edited file
# belongs to a nested one. Walking up from the file resolves both, and is the
# only direction that stays unambiguous when an app has several workspaces.
#
# _app_dir_of keeps its meaning — `bench run-tests --app` needs the Frappe app
# name, which is the directory under apps/, never the JS workspace.
#
# Prints nothing when no package.json exists at or above the file within the
# app; callers treat that as "no JS context" and skip rather than fail.
_js_dir_of() {
  local app_dir dir
  app_dir="$(_app_dir_of "$1")"
  [ -n "$app_dir" ] || { printf ''; return; }
  case "$1" in
    /*) dir="$(dirname -- "$1")" ;;
    *)  dir="$REPO_ROOT/$(dirname -- "$1")" ;;
  esac
  while [ "$dir" != "$app_dir" ] && [ "$dir" != "/" ] && [ -n "$dir" ]; do
    if [ -f "$dir/package.json" ]; then printf '%s' "$dir"; return; fi
    dir="$(dirname -- "$dir")"
  done
  [ -f "$app_dir/package.json" ] && printf '%s' "$app_dir" || printf ''
}

# Absolute form of a path that may be given relative to the bench root.
#
# Gates that change directory need this. `yarn --cwd <js_dir> lint <file>` runs
# eslint with cwd inside the JS workspace, so a bench-relative
# `apps/novizna_pos/novizna-pos-ui/src/App.vue` resolves to nothing there and
# eslint exits 2 with "No files matching the pattern". Passing every gate an
# absolute path costs nothing — ruff and eslint both accept it — and removes a
# whole class of cwd-dependent breakage.
_abs_of() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *)  printf '%s/%s' "$REPO_ROOT" "$1" ;;
  esac
}

# A path under apps/ representing what this session actually changed.
#
# The whole-target gates are per-app — `bench run-tests --app X`, `yarn build`
# in X's workspace — so they need a subject. gates.sh has no $FILE of its own
# (it is not per-file), and referencing one under `set -u` aborted the run
# before any gate executed. Deriving it from the working tree is what "the
# definition of done for the work in progress" actually means.
#
# Asked PER APP, not at the bench root: a Frappe bench is not itself a git
# repository — each app under apps/ is its own checkout (often a worktree). A
# single `git -C "$REPO_ROOT" diff` returns nothing here, silently, which reads
# as "no changes" rather than "wrong question".
#
# First app with a dirty tree wins. Empty when nothing under apps/ changed,
# which callers must treat as "cannot run per-app gates" rather than guessing.
# Apps this harness may act on. Set by the CALLER (gates.sh) rather than
# rendered here: common.sh is shared verbatim by every target, and baking a
# target's app list into it would leak target data into the shared plumbing —
# the thing `test_plumbing_scripts_are_identical_across_targets` exists to stop.
#
# Empty means "no restriction". On a bench that matters: the first dirty app
# alphabetically is `drive`, an upstream fork, and an unrestricted full gate
# would run `bench run-tests --app drive`.
_OWNED_APPS="${_OWNED_APPS:-}"

_is_owned_app() {
  [ -z "$_OWNED_APPS" ] && return 0
  case " $_OWNED_APPS " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

_changed_app_path() {
  local app_dir app rel manifest p
  local -a excludes
  for app_dir in "$REPO_ROOT"/apps/*/; do
    [ -d "$app_dir/.git" ] || [ -f "$app_dir/.git" ] || continue
    app="$(basename "$app_dir")"
    _is_owned_app "$app" || continue

    # Forge's own output does not count as work. It writes CLAUDE.md and the
    # manifest into every managed app on every sync, so without this every
    # owned app is permanently dirty and the loop always returns the first one
    # alphabetically — an answer that looks plausible and is never right.
    #
    # The exclusion list is read from the manifest rather than hard-coded, so
    # it stays correct when forge starts writing something new.
    excludes=(':(exclude).forge-manifest.json')
    manifest="$app_dir/.forge-manifest.json"
    if [ -f "$manifest" ]; then
      while IFS= read -r p; do
        [ -n "$p" ] && excludes+=(":(exclude)$p")
      done < <(grep -o '"path"[[:space:]]*:[[:space:]]*"[^"]*"' "$manifest" 2>/dev/null \
               | sed 's/.*"\(.*\)"$/\1/')
    fi

    rel="$(git -C "$app_dir" status --porcelain --untracked-files=no \
           -- . "${excludes[@]}" 2>/dev/null | head -n1 | awk '{print $NF}')"
    if [ -n "$rel" ]; then
      printf 'apps/%s/%s' "$app" "$rel"
      return
    fi
  done
  printf ''
}

# --- reporting -------------------------------------------------------------
# Hook stdout is read by a model, not a person. State the file, the command,
# and what to do — never just "failed".
fail_block() {
  local what="$1"
  printf '\n[harness] %s\n' "$what" >&2
  printf '[harness] Fix this before continuing. The edit is not accepted yet.\n' >&2
}

note() { printf '[harness] %s\n' "$1" >&2; }
