---
id: PHASE-1
title: Sync targets — forge repo as a first-class target
build_state: done
epic: harness-port
depends_on: [PHASE-0]
blocks: [PHASE-2]
---

# PHASE-1 — Sync targets

## Why

The user's explicit instruction (overriding the original plan, which had
proposed a hand-authored, unrendered harness for the forge repo): **the forge
repo must receive its own harness through `forge sync`, exactly like the bench
does** — not hand-authored separately. One canonical source, two destinations.
The reasoning: the forge repo is where harness bugs get hit first (it's where
agents work daily), and a hand-authored copy guarantees drift from whatever gets
fixed there.

The original plan's objection to this — "a sync would rewrite the hooks
currently executing them" — was checked against the actual code and found
false: `sync.py::_swap_into_bench` does `tmp.write_text(...); tmp.replace(target)`,
an atomic rename that installs a **new inode**; a running script holds an fd to
the old inode and finishes reading it unharmed. Corruption only comes from
truncate-in-place, which this pipeline never does.

## Scope delivered

- **`Target` dataclass** (`forge/src/forge/models.py`, frozen): `name`, `root`,
  `stack_profile`, `enabled_tools`, `primary_site`, `owned_remotes`,
  `managed_apps`, `renders: frozenset[str] | None` (artifact-group scoping, see
  below), `self_target: bool`.

- **`load_targets()` / `load_target()`** (`forge/src/forge/loader.py`): `bench:`
  in `forge.config.yaml` stays authoritative and is synthesized into a target
  named `bench` with `stack_profile: frappe` if not otherwise overridden.
  `targets:` is **additive on top**, not a replacement — verified by a test that
  a config with only `bench:` produces an identical target to before this
  ticket. Root resolution: `{{ env.VAR }}` expansion via
  `resolve_config_str()`; a relative `root:` (e.g. `"."` for `self`) resolves
  against the **forge repo root**, not `cwd` — tested explicitly, since `cwd`
  varies by how the command was invoked.

- **`forge.config.yaml`**: new `targets: {self: {root: ".", stack_profile:
  python_cli, self_target: true, enabled_tools: [claude-code, opencode, codex],
  renders: [...]}}` block (the `renders:` list starts empty in this ticket and
  is filled in incrementally by PHASE-2/3/4 as content becomes available for
  it — see those tickets for the exact list as of last verification).

- **`render()` and `sync_tool()`/`sync_all()`/`run_sync()` accept a `target`**
  (`forge/src/forge/render.py`, `forge/src/forge/sync.py`). `--target
  bench|self` and `--all-targets` added to `forge sync` and `forge diff` CLI
  commands.

- **`_target_wants(target, group)` / artifact-group scoping** — a target with
  `renders: [...]` set receives *only* those adapter.yaml artifact groups
  (`agents`, `skills`, `tools`, `per_app_claude_md`, etc.); `renders: None`
  (unset) means everything, so the bench target's behavior is completely
  unaffected. Wired into every render branch: `agents`, `commands`, `skills`,
  `tools`, `root_claude_md`, `per_app_claude_md`, and the generic aggregate
  loop.

- **`_managed_apps_for(target)`** replaces the old
  `_managed_apps(forge_cfg)` — reads from the target, not the raw config dict.

- **Ownership guard is target-aware**: `foreign_app_targets(...,
  target=...)` returns `{}` immediately when `target.self_target` is true (we
  are inside the repo we'd be asking about) but still honors
  `owned_remotes`/`is_foreign()` for every other target — hand-edit detection
  and the security gate are **not** bypassed for self, only the "is this repo
  ours" prompt.

- **Staging root bug found and fixed**: `_stage_artifacts` used to infer the
  bench root via `_bench_root_from()` (looks for an `apps/` dir or an existing
  `.claude/`) — this heuristic fails on a repo's *first* sync, since neither
  marker exists yet. First real test of `--target self` produced staging paths
  like `.forge-staging/claude-code/Work/Projects/...` (walked all the way up
  the real filesystem looking for a marker it would never find). Fixed by
  threading the target's `root:` through explicitly as an authoritative
  `target_root` parameter; the heuristic is now only a fallback for legacy call
  sites that don't pass one.

- **Ruff + mypy wired into CI and pre-commit** (were configured in
  `forge/pyproject.toml`, run nowhere): `.github/workflows/ci.yml` gained
  `ruff check src/`, `mypy src/forge` steps (run with `working-directory:
  forge`, which matters — run from the repo root, mypy silently ran
  **non-strict** because it never found `forge/pyproject.toml`; this was caught
  mid-ticket after an initial false "mypy passes" report). `.pre-commit-config.yaml`
  gained a `ruff-pre-commit` hook (`ruff --fix`) and a local `mypy` hook, both
  scoped to `^forge/(src|tests)/`.
  - `ruff format --check` was **deliberately not added** — 23 of 29 files in
    `forge/src` differ from the formatter's output (~425 changed lines), which
    predates this epic. Adding the check now would either fail immediately or
    require reformatting the whole codebase inside this feature branch, burying
    the actual diff. Both CI and pre-commit carry a comment explaining this and
    recommending the reformat land as its own dedicated commit first.
  - 8 real mypy-strict errors found and fixed as part of wiring this in (all
    pre-existing, unrelated to this epic's own new code): untyped
    `post.metadata` in `loader.py` (root cause of 4 of them, via `fm.get()`
    returning `object`), `**updates` missing a type annotation in
    `deprecate.py`, bare `dict` in two `sync.py` signatures, one `str`/`Path`
    variable-reuse bug in `render.py::render()`'s per-app aggregate branch
    (renamed the local, not a logic change). `types-PyYAML` added as a dev
    dependency to resolve a `Library stubs not installed for "yaml"` error.

## Files touched

New: `forge/tests/test_targets.py`

Modified: `forge/src/forge/models.py`, `loader.py`, `render.py`, `sync.py`,
`cli.py`, `commands/sync.py`, `commands/diff.py`, `deprecate.py`,
`commands/commit.py`, `commands/test.py`, `audit.py`, `stats.py` (last several:
mypy-strict fixes only, no behavior change), `forge.config.yaml`,
`.github/workflows/ci.yml`, `.pre-commit-config.yaml`, `forge/pyproject.toml`,
`forge/uv.lock`, `.gitignore` (`.ci-fake-bench/` explicitly ignored — it holds
only the already-ignored staging dir today, so git happened not to see it; that
stops being true the moment a real file lands there).

## Verification performed

- `pytest forge/tests -q` → 249 passed (+18 target tests over PHASE-0's 231)
- `ruff check src/` (from `forge/`) → clean
- `mypy src/forge` (from `forge/`, strict) → clean, 29 files
- `forge sync --target self --dry-run` then `--target self` (real, not dry-run)
  against a bare/no-`.claude` forge repo → succeeded, produced correct
  `scripts/harness/...` staging layout (this ticket has no harness content yet
  to actually populate it with — that's PHASE-2 — so this run legitimately
  wrote 0 files at the time)
- Confirmed self-sync is a genuine no-op on the working tree when nothing to
  render: captured `git status --porcelain` before/after, identical
- `forge sync --all-targets --all --dry-run` → both targets iterate, each with
  its own `enabled_tools` list, 10 total tool×target dry-runs succeed

## Deviations from the original plan

**This is the ticket where the user's explicit correction was applied.** The
original approved plan (before this correction) proposed:
> "The forge repo's own harness (hand-authored, NOT rendered) ... Rendering the
> forge repo's harness from its own canonical layer creates a sync that rewrites
> the hooks currently executing it. Keep them separate; share only the *shape*."

This was overridden per direct user instruction ("make sure that we use harness
for both erpnext-ai-forge and erpnext projects like we use sync commands"). The
atomic-rename safety argument above is why the override is safe, not just
requested.

## Known follow-ups

- None specific to this ticket; `renders:` scoping for `self` starts empty here
  and is filled in by PHASE-2 (`harness_scripts`, `hook_wiring`), PHASE-3
  (`harness_doc`), PHASE-4 (`operating_manual_doc`).
