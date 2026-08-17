---
id: PHASE-0
title: Pipeline enablers — file modes, manifest merge, shell scoring, forge diff
build_state: done
epic: harness-port
depends_on: []
blocks: [PHASE-1, PHASE-2, PHASE-7]
---

# PHASE-0 — Pipeline enablers

## Why

Before any hook script could be added, four latent defects in the render/sync
pipeline had to be fixed — none of them hypothetical, all found by reading the
actual code, not by guessing:

1. `forge/src/forge/scoring.py::score_path` globbed `*.md,*.yaml,*.yml,*.py,*.j2`
   — **no `*.sh`** — and every deduction rule capable of catching dangerous shell
   (`D-CURL-SHELL`, `D-DANGEROUS-SKIP-PERMS`) carried an *unanchored*
   `skip_if_path_matches: (canonical|docs)` regex that matched the substring
   "canonical" or "docs" anywhere in a path, not just at path components meant to
   be exempt. A shell script placed under `canonical/` would have been invisible
   to `forge score`, the sync security gate, and the pre-commit hook, all three
   at once.
2. Nothing in `RenderedArtifact` / `_stage_artifacts` / `_swap_into_bench` carried
   a POSIX file mode. Every artifact so far had been Markdown/JSON/YAML that
   nothing executes; a rendered `gates.sh` would have landed `0644` and silently
   never run.
3. `merge_settings_json` and `write_settings_with_backup`
   (`forge/src/forge/settings_merge.py`) were fully implemented, imported into
   `sync.py` at the top of the file, and **never called** — only referenced in a
   stale comment at the old line 551. `forge.config.yaml`'s
   `sync.backup_claude_settings: true` was therefore a promise the code did not
   keep.
4. Every `sync_tool` call overwrote the bench-root `.forge-manifest.json` with
   only its own adapter's rows (`build_manifest` → `write_manifest`, no read-merge
   step). All seven adapters legitimately write `AGENTS-TICKETING.md` at bench
   root; whichever synced last silently erased the other six adapters' hand-edit
   protection for every file in that directory.

`forge diff` was also a stub (`console.print("not yet implemented")` in
`cli.py`) — needed as the reviewable "what would this sync do" step before later
phases start merging into `settings.json` and installing executable scripts.

## Scope delivered

- **File modes end to end**
  - `RenderedArtifact.mode: int | None = None` (`forge/src/forge/render.py`)
  - `_stage_artifacts` chmods the staged file when `mode` is set
  - `_swap_into_bench` chmods the **temp file before `tmp.replace(target)`**, so
    the swap stays atomic (no window where the file exists but isn't yet
    executable)
  - `ManifestEntry.mode: int | None = None`, **`MANIFEST_SCHEMA_VERSION` kept at
    `2`** deliberately — bumping it would make `read_manifest` return `None` on
    every existing manifest, and `detect_hand_edits` treats "no manifest record"
    as "adopt it", silently discarding one full round of hand-edit protection
    bench-wide.

- **Manifest merge** — `merge_manifest()` in `forge/src/forge/manifest.py`: unions
  `source_files`/`outputs` by path; rows belonging to `incoming.adapter_name` are
  replaced wholesale (so a file that adapter no longer renders correctly drops
  out), rows belonging to any *other* adapter are preserved untouched. Added
  `ManifestEntry.adapter: str | None` so ownership is recorded per row. Legacy
  rows with no `adapter` are attributed to whichever adapter is currently
  syncing (pre-merge manifests only ever held one adapter's rows anyway).

- **Scorer sees shell, with precise exemptions**
  - `score_path` glob extended to `*.sh`, `*.bash`
  - New anchored `_PROSE_DIRS` regex:
    `^(canonical/(agents|skills|commands|apps|policies)/|docs/)` — replaces the
    old unanchored `(canonical|docs)` substring match
  - `D-EDIT-UPSTREAM` and `D-READ-SITE-CONFIG` kept a **broader**, also-anchored
    exemption (`^(canonical/|discovery/|adapters/|docs/)`) rather than narrowing
    to prose dirs — narrowing them broke `discovery/data/override-map.json` and
    `canonical/tools/override-checker.yaml`, which legitimately reference
    upstream app paths as *data*. Verified empirically before landing (see
    "Deviations" below).
  - Five new shell deduction rules added to both `scoring.py` and
    `canonical/policies/security-scoring.yaml`:
    `D-SHELL-RM-RF` (50, CRITICAL), `D-SHELL-SUDO` (40, HIGH),
    `D-SHELL-CHMOD-WORLD` (30, HIGH), `D-SHELL-EVAL-SUBSHELL` (30, HIGH),
    `D-SHELL-NO-STRICT-MODE` (10, MEDIUM — an *absence* check for `set -e`,
    which the scoring engine did not support until this ticket added
    `match_absence` handling)
  - `exempt_paths` mechanism added: exact repo-relative paths, checked verbatim,
    for the one case (the `curl|bash` string appearing literally in the deny-list
    that *blocks* it — see PHASE-2) where a targeted exemption is needed rather
    than a directory-wide one
  - `.pre-commit-config.yaml` `forge-score-staged` filter widened from
    `^canonical/.*\.(md|yaml|yml)$` to `^canonical/.*\.(md|ya?ml|sh|bash|j2)$`;
    `commands/score.py::_staged_files` suffix set widened to match

- **`forge diff` implemented** — `forge/src/forge/commands/diff.py` (new file).
  Renders in memory, classifies each artifact against what's on disk as `new`,
  `modified`, `mode` (content identical, permission bit wrong — the case a
  content-only diff misses), `hand-edited`, `merged` (settings fragments — added
  in PHASE-2, not this phase), or `unchanged`. Writes nothing. `forge new` was
  left stubbed — out of scope, no user need identified.
  - `--target`/`--tool` CLI flags: `forge diff --tool <t> [--target <t>]
    [--no-content] [--unchanged]`

- **Config** — `forge.config.yaml`: added commit scopes `harness`, `hooks`,
  `ticketing`, `policies` (else `forge commit --check` rejects every commit this
  epic makes); added a `harness:` block (`enabled`, `owner_adapter:
  claude-code`, `scripts_dir: scripts/harness`).

## Files touched

New:

- `forge/src/forge/commands/diff.py`
- `forge/tests/test_diff.py`, `forge/tests/test_file_modes.py`,
  `forge/tests/test_scoring_shell.py`

Modified:

- `forge/src/forge/render.py` (mode field)
- `forge/src/forge/sync.py` (chmod-before-rename, manifest merge call site)
- `forge/src/forge/manifest.py` (merge_manifest, adapter field)
- `forge/src/forge/scoring.py` (glob, anchored exemptions, 5 new rules,
  `match_absence` support)
- `forge/src/forge/commands/score.py` (`_staged_files` suffix set)
- `forge/src/forge/cli.py` (`diff` command wired to real implementation)
- `canonical/policies/security-scoring.yaml` (5 new deduction entries)
- `.pre-commit-config.yaml` (score-staged filter)
- `.gitignore` (`.ci-fake-bench/` added — see PHASE-1)
- `forge.config.yaml` (commit scopes, `harness:` block)
- `forge/tests/test_manifest.py` (extended with merge tests)

## Bugs found while building this (not pre-existing — introduced and caught

## within this ticket's own work)

- First `D-SHELL-RM-RF` regex missed the quoted form `rm -rf "$BENCH"/x` — the
  actually-dangerous spelling, since an unset `$BENCH` collapses it to
  `rm -rf /x`. Caught by testing the rule against real shell before shipping it,
  not by review. Fixed by adding an optional `["']?` before the path anchor.

## Verification performed

- `pytest forge/tests -q` → 231 passed (baseline was 189; +42 from this ticket's
  own new tests)
- `forge score --path canonical/ --fail-below 80` → lowest 100, incl.
  `canonical/skills/security/review-checklist.md` (the file that legitimately
  names `curl | sh` in prose — regression-tested explicitly)
- `forge validate --no-check-drift` → schema valid
- **Byte-identical staging proof**: ran `forge sync --all --dry-run` against
  `.ci-fake-bench` on the pre-change tree and the post-change tree, diffed the
  172 staged files with render timestamps normalized out — **zero differences**.
  Confirms this ticket changed pipeline internals with no behavior change for
  any existing artifact.
- ruff/mypy were **not** yet wired into CI at this point (that's PHASE-1); ran
  manually and confirmed this ticket's new files were clean, pre-existing 18
  ruff errors / mypy strict errors in the repo were left as baseline (fixed in
  PHASE-1).

## Deviations from the original plan

1. Did **not** narrow `D-EDIT-UPSTREAM`'s exemption to prose-only dirs as
   initially planned — empirical check first showed it would newly fire
   CRITICAL/50 on two legitimate data files. Kept it broad instead and only
   narrowed the two rules that actually needed narrowing
   (`D-CURL-SHELL`, `D-DANGEROUS-SKIP-PERMS`).
2. Replaced the planned `D-SHELL-UNQUOTED-PATH-VAR` rule (regex-detecting
   unquoted shell variables in paths — judged unreliable and untestable with no
   harness scripts yet to validate against) with `D-SHELL-NO-STRICT-MODE`, an
   absence check for `set -e`. Required adding `match_absence` support to the
   scoring engine, which did not exist before.

## Known follow-ups (not blocking, not yet actioned)

- Every rendered artifact embeds a `rendered_at` timestamp, so every sync
  rewrites every file even when content is otherwise identical (`forge diff`
  against the real bench showed "76 modified" where the only change was that
  line). Flagged, not fixed — would reduce diff noise and manifest churn but is
  outside this epic's scope.
- Pre-existing baseline debt at the time of this ticket (fixed in PHASE-1, not
  here): 18 ruff errors and mypy-strict errors in `forge/src`, never run in CI.
