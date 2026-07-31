---
id: PHASE-2
title: Hooks in the adapter contract — canonical/harness/, settings.json merge
build_state: done
epic: harness-port
depends_on: [PHASE-1]
blocks: [PHASE-3, PHASE-4]
---

# PHASE-2 — Hooks in the adapter contract

## Why

Core design problem: `render()` dispatches artifact kinds by hardcoded branch
(`if "agents" in adapter_cfg...`), so a genuinely new artifact kind (shell
scripts, not Markdown/YAML) needs new render strategies, not just a new
`adapter.yaml` entry. Shell also cannot carry YAML frontmatter (a `---` block
before a `#!/usr/bin/env bash` shebang breaks the shebang), so harness sources
follow the `canonical/tools/*.yaml` pattern (a YAML spec pointing at files)
rather than the Markdown-frontmatter pattern everything else uses.

## Scope delivered

### `canonical/harness/` (new directory, new canonical artifact kind `"harness"`)

- `harness.yaml` — declares 6 scripts (`common`, `check-file`, `typecheck`,
  `gates`, `hook-posttooluse`, `hook-stop`) with id/file/mode/purpose, and 2
  hooks (`post-edit` → `file_edit` → `hook-posttooluse`, blocking, 240s;
  `session-end` → `session_stop` → `hook-stop`, blocking, 420s, args
  `["quick"]`, loop_guard `stop_hook_active`). Hook events use **forge-neutral**
  names (`file_edit`, `session_stop`) — never a tool's own vocabulary
  (`PostToolUse` etc.) — mapped per-adapter in `adapter.yaml`. Also documents
  (and PHASE-2's `forge validate` work enforces) 4 written-down invariants:
  no-sync-from-hook, strict-mode, no-eval-of-stdin, single-owner.
- `gates.yaml` — the gate command table **as data**, keyed by `stack_profile`
  (`frappe`, `python_cli`), each stack split into `file_lint` (per-edit),
  `typecheck` (advisory), `quick` (Stop hook), `full` (DoD, run once by a
  human/orchestrator). Every gate entry carries a `verify_status` of
  `VERIFIED`, `DOCUMENTED` (command is written down in canonical/ but not yet
  run against a live target by this ticket), or `UNVERIFIED`. As of this
  ticket: 3 `frappe` gates are `UNVERIFIED` (`python-lint`, `frontend-lint`,
  `python-lint-all` — **no linter convention exists anywhere in this repo**,
  confirmed by grep, zero hits for ruff/eslint/prettier outside `forge/`
  itself), 3 are `DOCUMENTED` (`frappe-tests`, `coverage-floor`,
  `frontend-build` — commands exist in `canonical/skills/testing/*.md` but
  weren't independently re-verified here), and all 6 `python_cli` gates are
  `VERIFIED` (they run against this very repo, in CI, right now).
- `permissions.yaml` — per-profile `allow` lists + a shared `deny_all` list.
  Contains the literal string `curl * | bash` in the deny list (needed to
  *block* it) — this exact string is what `D-CURL-SHELL` matches, so
  `permissions.yaml` is listed in that rule's new `exempt_paths` with a
  one-line comment explaining why, rather than widening the CRITICAL regex.
- `scripts/*.sh.j2` (6 files) — `common.sh.j2` (sourced helpers: `REPO_ROOT`
  resolution from the script's own location, `FORGE_HARNESS_ACTIVE` re-entrancy
  guard, `cap()` output limiter, `run_to()` timeout wrapper, dirty-marker
  functions, `_app_dir_of`/`_app_of` path helpers), `check-file.sh.j2`
  (blocking per-file lint), `typecheck.sh.j2` (advisory, always exits 0),
  `gates.sh.j2` (the DoD runner, `quick`/`full`/`all` modes), and the two hook
  adapters below.

### Hook adapters do NOT `eval` their stdin

`hook-posttooluse.sh.j2` and `hook-stop.sh.j2` parse hook JSON via a probed
Python interpreter (tries `python3`, `python`, `py`, testing each by actually
running it rather than just checking it resolves — defeats the Windows Store
`python3` stub, which exits 9009 without reading stdin), emit
**newline-separated values**, and read them with `IFS= read -r` from a
here-string. This is a deliberate deviation from the reference implementation
this harness is ported from, which used `eval "$(...)"` on the parsed output —
executing model-controlled hook stdin as shell. `D-SHELL-EVAL-SUBSHELL` was
added specifically to keep this from creeping back in.

### Two new render strategies (`forge/src/forge/render.py`)

- `harness_scripts` — single owning adapter renders the 6 scripts with `mode`
  set (`0755` executable, `0644` for the sourced `common.sh`) and `source_path`
  pointed at the real `.sh.j2` so the *existing, unmodified* `_security_gate`
  in `sync.py` scores them.
- `hook_wiring` — emits **nothing** (not an empty file — `_validate_staging`
  rejects zero-byte staged files) when an adapter has no hooks for the current
  target's available events.
- Third `FileSystemLoader` added to the Jinja `ChoiceLoader`, pointed at
  `canonical/harness/`, appended last (adapter-local and shared templates still
  win on name collision).
- New `render_gate_cmd()` Jinja filter: turns `gates.yaml`'s `{file}`/`{app}`/
  `{app_dir}` placeholders into shell expressions (`"$FILE"`,
  `"$(_app_of "$FILE")"`, etc.) at render time — one rendered script handles
  every file/app, rather than baking a value in per-render.
- `HarnessScript`/`HookSpec`/`HarnessSpec` dataclasses added to `models.py`;
  `load_harness()` added to `loader.py`; `"harness"` added to the
  `ArtifactKind` Literal.

### The real `settings.json` merge (this is the headline fix of this ticket)

`merge_settings_json()`/`write_settings_with_backup()` existed since before this
epic and were dead code (see PHASE-0). This ticket wires them in:
`settings.json` is rendered as `artifact_kind="settings-fragment"`, **excluded**
from `_swap_into_bench`'s normal atomic-swap path via the `protected` set, and
merged separately by new `_merge_settings_fragments()` in `sync.py` — deep-merge
into whatever's on disk, `.forge-backup` taken first if a prior file existed
(not on a genuinely first write — an empty backup there would look like data
loss). Manifest records **no `outputs` row** for settings fragments — their
bytes on disk are the *merge* of forge's fragment and the human's own keys, so a
fragment-hash comparison would report "hand-edited" on every single sync,
training people to ignore that warning. `forge diff` gained a `merged` status
distinct from `modified` for the same reason.

`adapters/claude-code/adapter.yaml`: `capabilities.hooks: true`,
`capabilities.hook_events` maps `file_edit`→`PostToolUse`
(matcher `Write|Edit|MultiEdit|NotebookEdit`) and `session_stop`→`Stop`
(matcher `""`); new `harness_dir` output path; new `harness_scripts` and
`hook_wiring` artifact entries (the latter tagged `artifact_kind:
settings-fragment`). New template `settings-hooks.json.j2`.

### `forge validate` gains harness checks

id↔filename match for harness scripts; every `hooks[].script` resolves to a
declared script and (new rule) **must start with `hook-`** — a hook pointed
directly at `check-file`/`gates` would receive JSON on stdin those scripts don't
expect, see no arguments, and exit 0 silently (verified this actually happens by
deliberately misconfiguring it, see Verification); exactly one enabled adapter
per target may declare `harness_scripts`; a grep over every harness script's
non-comment lines asserting none contains `forge sync`; a warn-list (not a
failure) of every gate with `verify_status: UNVERIFIED`, printed on every
`forge validate` run so the debt can't rot silently in a comment.

### `forge sync --prune-harness`

New `prune_harness()` in `sync.py`: deletes files under the harness dir that the
current render no longer produces. **Explicitly opt-in**, never automatic — the
swap never deletes on its own, so an orphaned script is inert (nothing invokes
it; the wiring file is the sole invocation point) rather than dangerous, and
silently deleting files in someone's repo because a render came out shorter is
exactly the kind of surprise that costs trust in the tool.

## Files touched

New: `canonical/harness/` (harness.yaml, gates.yaml, permissions.yaml,
scripts/*.sh.j2 ×6), `adapters/claude-code/templates/settings-hooks.json.j2`,
`forge/tests/test_harness.py`

Modified: `forge/src/forge/models.py`, `loader.py`, `render.py`, `sync.py`,
`commands/validate.py`, `commands/diff.py`, `scoring.py` (exempt_paths entry),
`adapters/claude-code/adapter.yaml`, `forge.config.yaml`
(`targets.self.renders: [harness_scripts, hook_wiring]`)

## Bugs found and fixed during this ticket (not pre-existing)

1. **Optional Jinja keys via attribute access under `StrictUndefined`** —
   `{%- if gate.note %}` raised `UndefinedError: 'dict object' has no attribute
   'note'` for gates without a `note` field. Fixed by switching every optional
   field access to `.get()`.
2. **`.get('timeout_seconds') | default(300)` silently rendered the literal
   string `None`** into every gate's timeout slot — Jinja's `default` filter
   only substitutes for *undefined*, and `dict.get()` returns `None`, which is
   defined. Every gate in the first working version died with `timeout:
   invalid time interval 'None'`. Found by actually **executing** the generated
   `gates.sh`, not by reading the template. Fixed by using `.get(key, fallback)`
   instead of `.get(key) | default(fallback)` throughout.
3. **`hook_wiring` context hardcoded `output_paths.harness_dir`**, which only
   `claude-code` (the owning adapter) defines — every other adapter's sync
   failed with `KeyError: 'harness_dir'`. Fixed with a fallback to
   `target.root / scripts_dir_rel` for non-owning adapters.

## Verification performed (execution, not just rendering)

- Generated `gates.sh quick` **actually run** against the live forge repo →
  `RESULT: GREEN`
- `check-file.sh` on a clean file → exit 0; on a file with an unfixable lint
  error (`F821 undefined name`) → exit 1 with the real ruff output printed
- `hook-posttooluse.sh` fed a real JSON payload on stdin → correctly extracted
  the file path with no `eval`, ran the check, exited 2 (blocking), set the
  session dirty marker (confirmed by `ls
  ${TMPDIR}/forge-harness-*-<session>.dirty`)
- `hook-stop.sh`: `stop_hook_active: true` → exits 0 without recursing; clean
  session, no dirty marker → exits 0 instantly (fast path); dirty session with
  green gates → runs `gates.sh quick`, prints `RESULT: GREEN`, clears the
  marker
- **Settings merge, live**: seeded `.claude/settings.json` with a custom
  permission, a custom `SessionStart` hook, and an arbitrary top-level key; ran
  a real (non-dry-run) `forge sync --target self --tool claude-code`; confirmed
  all three survived, forge's `PostToolUse`/`Stop` hooks were added alongside,
  and `.claude/settings.json.forge-backup` was created
- **Bootstrap from a bare repo**: deleted `.claude/`, `scripts/harness/`;
  re-ran `forge sync --target self --tool claude-code`; succeeded cleanly, no
  backup created on the first write (correct — nothing to back up yet)
- **`forge validate` invariant probes** (deliberately broken, then restored):
  pointed a hook directly at `check-file` instead of `hook-posttooluse` → caught
  (`hook 'post-edit' runs 'check-file' directly...`); appended `forge sync
  --all` to `gates.sh.j2` → caught (`harness script 'gates' invokes forge
  sync`)
- `pytest forge/tests -q` → 273 passed (+24 over PHASE-1's 249)
- `ruff check src/`, `mypy src/forge` (strict) → clean
- `forge score --path canonical/ --fail-below 80` → lowest 100 (including the
  new `canonical/harness/**` content, which is now genuinely scored rather than
  exempt)
- `forge sync --all-targets --all --dry-run` → 10/10 tool×target combos succeed

## Deviations from the original plan

- Replaced the plan's proposed `D-SHELL-UNQUOTED-PATH-VAR` rule with
  `D-SHELL-NO-STRICT-MODE` in PHASE-0 (documented there) — relevant here because
  it's this ticket's scripts that first exercise it.
- The plan's `forge diff --tool ... ` preview step before the settings merge was
  followed as specified and did catch the harness_dir bug above before it
  reached a real sync attempt.

## Known follow-ups

- 3 `frappe` gates remain `UNVERIFIED` (see gates.yaml summary above) — must be
  run against the real bench before Novizna agents rely on them. Requires
  access to a live bench + site.
- The bench has **four sites**; `FORGE_PRIMARY_SITE` needs confirming as the
  correct one for `bench --site <site> run-tests` before that gate is trusted.
