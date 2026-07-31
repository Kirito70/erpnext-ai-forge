# Harness Port — Ticket Index

Epic: **port the estimation-ops verification harness into erpnext-ai-forge**, adapted to
Frappe/ERPNext, delivered through `forge sync` to both the Novizna bench and the
forge repo itself (see the approved plan at
`/home/tayyab/.claude/plans/we-have-a-good-witty-volcano.md` for the original design
rationale — these tickets are the as-built and as-planned record, kept in the repo
so they survive a context reset).

Ledger convention borrowed from the very system this epic builds: each ticket below
carries a `build_state`, not a `status` — there is no separate human-owned intent
store yet for this meta-work, so `build_state` here is the single source of truth.

| Key | Title | build_state | Depends on |
|-----|-------|-------------|------------|
| [PHASE-0](PHASE-0.md) | Pipeline enablers (file modes, manifest merge, shell scoring, `forge diff`) | **done** | — |
| [PHASE-1](PHASE-1.md) | Sync targets — forge repo as a first-class target | **done** | PHASE-0 |
| [PHASE-2](PHASE-2.md) | Hooks in the adapter contract (`canonical/harness/`, settings.json merge) | **done** | PHASE-1 |
| [PHASE-3](PHASE-3.md) | Hook/instruction wiring for the other six adapters | **done** | PHASE-2 |
| [PHASE-4](PHASE-4.md) | Operating manual, ticketing contract → canonical, three-file ledger, Jira seam | **done** | PHASE-2 |
| [PHASE-5](PHASE-5.md) | Ticket authoring and refinement (`/write-ticket`, `/refine-ticket`, `ticket-refiner`) | **done** | PHASE-4 |
| [PHASE-6](PHASE-6.md) | `/ticket-review` DoD gate, risk-tiered lanes, gap loop, ownership guard | **done** | PHASE-4, PHASE-5 |
| [PHASE-7](PHASE-7.md) | Skills provenance lockfile (`skills-lock.json`, `forge skills verify`) | **done** | PHASE-0 |

**All seven phases are done.** The epic's implementation is complete; nothing
remains in the original plan's scope. See "Known follow-ups" in each ticket for
work explicitly deferred (not forgotten) during that phase.

## Current repo state (as of last verification, after PHASE-7)

- **Tests:** 367 passed, 2 skipped (`forge/tests/`)
- **Lint:** `ruff check src/` clean, `mypy src/forge` (strict) clean
- **Security score:** `forge score --path canonical/ --fail-below 80` → lowest 100
- **Schema:** `forge validate --no-check-drift` → `✓ schema valid`
- **Canonical content:** 11 agents, 21 commands, 31 skills, 6 policies, 14 tools
- **Char budget headroom (binding constraint, antigravity, 15,000 cap):** 6,809
  chars free
- **Live self-harness:** `./scripts/harness/gates.sh quick` → `RESULT: GREEN`
- **Working tree:** NOT committed. 85 changed paths as of this writing. Run
  `git status --porcelain | wc -l` for the current count. See each phase
  ticket's "Files touched"/"Files created"/"Files modified" section for the
  specific files that phase is responsible for.

## Self-target side effects on disk

`forge sync --target self` has been run for real against this repo repeatedly
during verification (Phases 1 through 7), so `.claude/`, `.opencode/`,
`scripts/harness/`, `AGENTS-HARNESS.md`, `AGENTS-OPERATING-MANUAL.md`, and
`.forge-manifest.json` at the repo root are genuinely on disk and untracked.
These are the intended generated output of the `self` target, not stray files
— see PHASE-1/PHASE-2 for why the forge repo renders its own harness. They
should be committed (or explicitly `.gitignore`d, if the decision is to only
ever generate them in CI) before or alongside this epic's commit.

## Recommended commit boundary(s)

The whole epic is one working tree right now (85 changed paths across 7
phases). Two reasonable ways to split it into commits, in order:

1. **Phases 0–4** — pipeline safety, targets, hooks, adapter rollout,
   policy/ledger. Changes to `forge/src/forge/*.py` plumbing plus the harness
   and policy content everything downstream depends on.
2. **Phases 5–7** — new canonical *content* built on top of that plumbing
   (ticket authoring/review commands and agents, the skills lockfile). Lower
   risk to leave split from (1) since it doesn't touch pipeline internals
   beyond `validate.py` and the `scoring.py`/`skills_lock.py` refactor from
   PHASE-7.

Whichever split is used, commit the self-target generated output (see above)
in the same commit as the phase that changed what it renders, not separately —
otherwise `forge validate`'s self-target drift check (added in PHASE-1's CI
step) will show the working tree as out of sync with what's committed.

## Known follow-ups across the whole epic (not phase-specific)

- No live end-to-end smoke test of `/write-ticket` → `/refine-ticket` →
  `/ticket-review` → `/gap-ticket` against a real vault ticket exists yet
  (noted in PHASE-5 and PHASE-6). All four commands are documented and their
  individual mechanics are unit-tested, but nobody has run the full chain for
  real. Natural next step once there's a real ticket to try it on.
- Per-app ledger mirroring (`apps/<app>/docs/harness/LEDGER-*.md`) was never
  built (noted in PHASE-4, referenced again in PHASE-6). The ownership-guard
  check added in PHASE-6 is forward-compatible with it but has nothing real to
  protect today.
- 3 Frappe gate commands remain `UNVERIFIED` against a real bench (PHASE-2):
  `python-lint`, `frontend-lint`, `python-lint-all`. No linter convention
  exists anywhere in this repo currently — confirm one before trusting these.
- No `forge ledger sync` command exists to reconcile vault and repo ledger
  copies (PHASE-4) — documented as an agent duty for now.
- `ruff format --check` is intentionally not enforced yet (PHASE-1) — 23 of 29
  `forge/src` files predate the formatter. Land as its own commit before
  adding the check.
