---
id: PHASE-3
title: Hook and instruction wiring for the other six adapters
build_state: done
epic: harness-port
depends_on: [PHASE-2]
blocks: [PHASE-4]
---

# PHASE-3 — The other six adapters

## Why

PHASE-2 wired the harness for `claude-code` only. Six adapters remained
harness-blind: cursor, opencode, cline, copilot, codex, antigravity. Each has a
different (or no) hook mechanism, so each needed a distinct wiring strategy
rather than one copy-pasted across all seven.

## Scope delivered

| Adapter | Mechanism | Output | Native events used |
|---|---|---|---|
| opencode | JS plugin, shells out to the shared `check-file.sh` | `.opencode/plugin/harness.js` | `tool.execute.after` (edit only — **no session-end event exists** in opencode's plugin API) |
| antigravity | native hooks | `.agents/hooks.json` | `Stop` **only** — its edit-tool payload carries no file path, so a per-file hook would fire, find nothing to lint, and exit 0, indistinguishable from a passing gate |
| cursor, cline, copilot, codex | instruction layer only, no hook mechanism available | shared `AGENTS-HARNESS.md` + ~1 KB pointer in the root file | none |

- **`adapter.yaml` additions**: `opencode` gets `plugin_dir`/`harness_plugin`
  output paths, `capabilities.hooks: true`, `capabilities.hook_events.file_edit`
  → native `tool.execute.after`, and a `hook_wiring` artifact entry pointed at
  new template `harness-plugin.js.j2`. `antigravity` gets `agents_root`/
  `hooks_json` output paths, `capabilities.hooks: true`,
  `capabilities.hook_events.session_stop` → native `Stop`, and a `hook_wiring`
  entry pointed at new template `hooks.json.j2`.
- **`adapters/opencode/templates/harness-plugin.js.j2`** — the plugin shells out
  to `scripts/harness/check-file.sh` via `child_process.spawn`, rather than
  reimplementing lint logic in JS (two implementations of "is this file clean"
  would drift within a month). Includes a timeout guard (kills the child,
  reports the timeout rather than silently reporting clean), and an `on
  "error"` handler so a missing interpreter doesn't break the editing session —
  the harness is a safety net, not a dependency of being able to type.
- **`adapters/antigravity/templates/hooks.json.j2`** — minimal JSON: one
  `Stop` entry invoking `bash scripts/harness/hook-stop.sh`.
- **Shared partials** (`adapters/_shared/templates/`):
  - `harness-pointer.md.j2` — ~1 KB, included in every root instruction file
    (cline, codex, antigravity, copilot, claude-code, cursor, opencode). Models
    the existing `ticketing-pointer.md.j2` pattern exactly: trigger + path, not
    the body — root files are read every turn and compete with the actual task
    for context.
  - `harness-and-gates.md.j2` — the full contract, rendered by all seven
    adapters as `AGENTS-HARNESS.md` at target root. Renders the actual **gate
    table for that specific target** (reads `profile`/`target` context passed
    into every aggregate render — see below), including which commands are
    still `UNVERIFIED`.
  - New `harness_doc` artifact entry added to all 7 `adapter.yaml`s.
- **`render()` aggregate context extended**: every aggregate render (not just
  the harness doc) now receives `target={name, stack_profile, primary_site}`
  and `profile=harness.profile(target.stack_profile)` (or `None` if no harness
  exists), plus `policies=[...]` (added here, ahead of need, because PHASE-4's
  operating-manual/ticketing templates need it and it's free once the
  aggregate loop already loads `load_policies()`). `harness` itself is now
  loaded **unconditionally** in `render()` (not gated behind "is this the
  owning adapter") — every adapter needs the gate table to render its own
  `AGENTS-HARNESS.md`, even the six that don't write the scripts.
- **`forge validate` gained a dependency check**: adapters that *wire* hooks
  (`hook_wiring`) don't *write* the scripts (`harness_scripts`) — if no enabled
  adapter in a target declares `harness_scripts`, every hook in that target
  references a script that will never exist and fails at run time. Verified by
  temporarily removing `claude-code` from `self`'s `enabled_tools` and
  confirming the check fires.

## Files touched

New: `adapters/_shared/templates/harness-pointer.md.j2`,
`harness-and-gates.md.j2`, `adapters/opencode/templates/harness-plugin.js.j2`,
`adapters/antigravity/templates/hooks.json.j2`

Modified: all 7 `adapters/*/adapter.yaml`, all 7 root instruction templates
(`claude-md-root.j2`, `forge-main.mdc.j2`, `AGENTS.md.j2`,
`00-forge-main.md.j2`, `copilot-instructions.md.j2`, `AGENTS.codex.md.j2`,
`system.md.j2`), `forge/src/forge/render.py`, `commands/validate.py`,
`forge.config.yaml` (`targets.self.renders` gains `harness_doc`)

## Verification performed

- **Char budget re-check** (the binding constraint — antigravity's 15,000-char
  cap): before this ticket, antigravity's `system.md` was 6,315 chars; after
  adding the ~1 KB pointer, 7,185 chars, 7,815 headroom remaining. All 5
  budgeted adapters (cursor 40k/13,891 used, cline 35k/8,632, copilot
  30k/9,302, codex 20k/8,810, antigravity 15k/7,185) stayed within budget —
  measured directly against real staged output, not estimated.
- New tests (`forge/tests/test_harness.py`, extended) assert: every one of the
  7 adapters ships `AGENTS-HARNESS.md`; every root instruction file references
  it; every aggregate stays under its adapter's char budget; exactly one
  adapter (`claude-code`) writes the scripts; the opencode plugin's rendered
  content actually contains `check-file.sh` and `tool.execute.after`;
  antigravity's rendered `hooks.json` contains only a `Stop` event; the 4
  instruction-only adapters (cursor/cline/copilot/codex) emit no
  `settings-fragment` / `hook-wiring` artifact kind.
- Generated `.agents/hooks.json` validated as parseable JSON
  (`json.load(...)`); generated `harness.js` validated with `node --check`
- `pytest forge/tests -q` → 299 passed, 2 skipped (opencode/claude-code have no
  char budget, so the budget-check test parametrization skips them by design)
- Fixed 6 pre-existing hardcoded aggregate-count assertions in
  `forge/tests/test_adapters.py` that broke when the new `harness_doc`
  aggregate was added (e.g. `assert summary.get("aggregate") == 2` →
  `== 3`) — these were legitimate count changes, not incorrect tests.
- Self target re-synced after enabling `harness_doc` for it → confirmed
  `AGENTS-HARNESS.md` in the forge repo root correctly shows the `python_cli`
  gate table (`ruff`, `mypy`, `pytest`, `forge-score`), not the bench's
  `frappe` table.

## Deviations from the original plan

None of substance — the plan's per-adapter table (claude-code=native,
opencode=plugin, antigravity=Stop-only, others=instruction-layer) was followed
as written. The two "honest gaps" (opencode has no session-end event,
antigravity's edit payload has no file path) were identified during
implementation, not anticipated in the plan, and resolved by wiring only what
actually works rather than emitting an inert hook.

## Known follow-ups

None specific to this ticket.
