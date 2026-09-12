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
| [PHASE-8](PHASE-8.md) | `forge ledger sync` — reconcile vault tickets against the repo ledger (post-epic follow-up) | **done** | PHASE-4 |

**All eight tickets are done.** PHASE-0 through PHASE-7 were the original
seven-phase plan; PHASE-8 closed the one follow-up item asked for afterward.

## Current repo state (as of last verification, after PHASE-8)

- **Tests:** 386 passed, 2 skipped (`forge/tests/`)
- **Lint:** `ruff check src/` clean, `mypy src/forge` (strict) clean, 33 source files
- **Security score:** `forge score --path canonical/ --fail-below 80` → lowest 100
- **Schema:** `forge validate --no-check-drift` → `✓ schema valid`
- **Canonical content:** 11 agents, 21 commands, 31 skills, 6 policies, 14 tools
- **Char budget headroom (binding constraint, antigravity, 15,000 cap):** 6,809
  chars free
- **Live self-harness:** `./scripts/harness/gates.sh quick` → `RESULT: GREEN`
- **Working tree:** PHASE-0 through PHASE-7 are committed (6 atomic commits —
  see `git log --oneline` for `feat(forge)`, `feat(harness)`,
  `chore(harness)`, `feat(ticketing)`, `feat(skills)`, `docs`). PHASE-8's
  `forge ledger sync` work is the only thing not yet committed as of this
  writing.

## A known inaccuracy in the committed history

The `feat(ticketing)` commit's message says "forge validate gains two checks:
every review_only agent must declare read-only tools, and no ledger/ticket
scaffold may be written under an upstream or foreign-remote app directory" —
that `validate.py` code actually landed in the earlier `feat(forge)` commit,
which bundled the engine file's full final state rather than being split
phase-by-phase (see "Commit history and its limits" below). Not fixed via
amend since it wasn't asked for; flagging here so it isn't mistaken for
current, undocumented behavior.

## Commit history and its limits

Six commits landed PHASE-0 through PHASE-7, grouped by **concern** rather than
by exact phase number: `feat(forge)` (engine: targets, scoring, diff, skills
lockfile core), `feat(harness)` (canonical/harness/ + policy rollout to all 7
adapters), `chore(harness)` (self-target rendered output, regenerated fresh
immediately before committing), `feat(ticketing)` (ticket authoring/review
content), `feat(skills)` (the lockfile data), `docs` (this ticket record).

True per-phase bisectability wasn't achievable without risky hunk-level
surgery — `render.py`, `sync.py`, `validate.py`, `models.py`, `loader.py`,
`cli.py`, and `forge.config.yaml` each accumulated changes from 3–5 phases
with no intermediate commits along the way. Each of the six commits touches a
disjoint file set (verified programmatically against the full changed-path
list before each commit) and is independently reviewable; they are not,
however, each independently phase-accurate in their messages for the handful
of shared engine files (see "known inaccuracy" above).

## Known follow-ups across the whole epic (not phase-specific)

- No live end-to-end smoke test of `/write-ticket` → `/refine-ticket` →
  `/ticket-review` → `/gap-ticket` (and now `forge ledger sync`) against a
  real vault ticket exists yet (noted in PHASE-5, PHASE-6, PHASE-8). All five
  are documented and unit-tested individually against fixtures, but nobody
  has run the full chain against a real Obsidian vault. Natural next step
  once there's a real ticket to try it on.
- Per-app ledger mirroring (`apps/<app>/docs/harness/LEDGER-*.md`) was never
  built (noted in PHASE-4, referenced again in PHASE-6). The ownership-guard
  check added in PHASE-6 is forward-compatible with it but has nothing real to
  protect today. `forge ledger sync` (PHASE-8) only reconciles a target's
  root ledger, for the same reason.
- 3 Frappe gate commands remain `UNVERIFIED` against a real bench (PHASE-2):
  `python-lint`, `frontend-lint`, `python-lint-all`. No linter convention
  exists anywhere in this repo currently — confirm one before trusting these.
- `ruff format --check` is intentionally not enforced yet (PHASE-1) — 23 of 29
  `forge/src` files predate the formatter. Land as its own commit before
  adding the check.
