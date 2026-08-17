---
id: PHASE-6
title: "/ticket-review DoD gate, risk-tiered lanes, gap loop, ownership guard"
build_state: done
epic: harness-port
depends_on: [PHASE-4, PHASE-5]
blocks: []
---

# PHASE-6 — Ticket review as DoD gate + gap loop

## Why

`canonical/commands/audit-skills.md` only lints *canonical artifacts*
(agents/skills/commands/tools themselves) — nothing reviews *delivered bench
code*, and there is no mechanism that turns an out-of-scope finding into a
tracked gap ticket instead of silently expanding the ticket under review.
`canonical/policies/review-protocol.md` already has a solid producer/reviewer
pairing table and a 2-loop escalation cap (pre-existing, not built by this
epic) — this phase adds risk-tiering on top of it and the actual
`/ticket-review` command, it does not replace the existing protocol.

## As-built record

Both open questions from the original draft were resolved before writing, as
concrete design decisions (documented, not deferred):

1. **The "declared read-only review mode" mechanism for frontend specialists**
   is a documented invocation convention, not a frontmatter restriction: each
   frontend specialist agent file gained a new `## Review Mode` section stating
   that when invoked by `/ticket-review` as a reviewer (not as the producer of
   the artifact under review), it operates read-only (`Read`/`Grep`/`Glob`
   only) and emits a standard review, gated by *invocation context* rather than
   by a separate `tools:` frontmatter entry — because these agents are
   producers first (need `Write`/`Edit` in their normal role) and a frontmatter
   restriction can't apply conditionally within one file. Concretely:
   `frontend-frappe-ui-specialist` reviews `frontend-quasar-specialist`'s
   output and vice versa (different stack, shared Vue 3 conventions) — neither
   reviews its own producer output.
2. **Composition with `review-protocol.md` §4** was resolved by adding a new
   **§7 "Risk-Tiered Lane Selection"** to that policy (not duplicating the
   tier table only in `ticket-review.md`'s prose): §4's mandatory-pairing table
   stays authoritative for which agent reviews which producer by default; §7
   **adds** the new project-pattern/framework lanes on top of it for
   backend/integrations at tiers 2–3, and **selects among** §4's existing
   pairing for frontend at the lightest tier. Verified this doesn't break any
   existing anchor link (`#1-review-output-format`, `#3-loop-cap...`,
   `#4-mandatory-reviewer-pairings`, `#6-documentation-sub-phase...` are all
   referenced from other files) by appending §7 at the end rather than
   renumbering. Bumped `review-protocol.md` to `version: 1.1.0` (MINOR — new
   section, non-breaking) per `governance.md`'s versioning rule.

A third correction made mid-implementation, caught by actually checking the
agents rather than assuming from the plan text: the plan's phrasing implied
"reviewer agents" broadly should get restricted `tools:`. Checked
`qa-test-engineer.md`'s own role table first — its `Outputs` row is literally
"Test files + coverage report + ..." — it **writes files** as its primary
output and is not purely a reviewer. Restricting it to read-only tools would
have broken its actual job. Only agents whose *entire* output is a review
artifact (no code changes) got the restriction: the pre-existing
`security-reviewer` (confirmed its own body already states "you do not write
implementation code" — the restriction matches existing behavior exactly, adds
nothing new) plus the two new agents built in this ticket.

### Files created

- `canonical/commands/ticket-review.md` — `/ticket-review <KEY>`. Classifies
  risk tier, runs gates **once** via the architect and pastes real output into
  every lane prompt, delegates to the tier's lanes, computes acceptance per
  `review-protocol` §2 (including the "gates run and observed to pass" row
  already added in PHASE-4), routes in-scope CRITICAL/HIGH fixes through the
  existing loop cap, routes out-of-scope findings to `/gap-ticket`, and closes
  by appending a journal `## REVIEW` entry and moving the ledger row to
  `LEDGER-done.md`. Explicitly documents that it is **not** wired to any Stop
  hook and states why (the hook can't know which ticket is in flight; a false
  block is worse than an occasionally-missed review).
- `canonical/commands/gap-ticket.md` — `/gap-ticket "<subject>" --origin
  <PARENT-KEY>`. Deliberately a thin wrapper around `/write-ticket --gap-of`
  rather than duplicating its logic — states the one rule explicitly ("a
  finding that is real but out of scope... does not expand that ticket... it
  becomes its own ticket") and documents the same ownership guard as
  `/write-ticket` by reference, not by re-explaining it.
- `canonical/agents/code-reviewer.md` — project-pattern lane. `review_only:
  true`, `tools: [Read, Grep, Glob, Bash]`. Checks DRY against `frappe.utils`,
  override-system layering (cites `override-map.json` and the
  `override-checker` tool by name), per-app `CLAUDE.md` drift, docs-matches-
  code.
- `canonical/agents/frappe-framework-reviewer.md` — framework lane.
  `review_only: true`, `tools: [Read, Grep, Glob, Bash]`. Checks `hooks.py`
  ordering, `doc_events` atomicity, permission query conditions, patch
  idempotency, fixture scope, whitelist/CSRF — each check cites a real,
  currently-standing finding from `anti-pattern-findings.json` by exact
  file:line (e.g. the `db_commit_non_test` finding in
  `noviznaerp_payroll/custom/attendance_custom.py:41`, present in 6 of 9
  scanned apps; `ignore_permissions` present in 8 of 9), matching PHASE-5's
  precedent of citing concrete rather than hypothetical evidence.

### Files modified

- `canonical/policies/review-protocol.md` — new §7 (above); `scope:` extended
  to include the two new agents; version bumped to 1.1.0.
- `canonical/agents/security-reviewer.md` — added `tools: [Read, Grep, Glob,
  Bash]` + `review_only: true`.
- `canonical/agents/frontend-frappe-ui-specialist.md`,
  `frontend-quasar-specialist.md` — added `## Review Mode` sections (no
  frontmatter change).
- `forge/src/forge/commands/validate.py` — two new checks:
  1. Every `review_only: true` agent must declare `tools:`, and that list must
     not include `Write`/`Edit`/`MultiEdit`/`NotebookEdit`.
  2. **Ownership guard on scaffold outputs**: for every target, for every app
     under its `apps/` directory, if that app is in `upstream_apps` or fails
     `is_foreign()` against the target's `owned_remotes`, a `docs/harness/`
     directory under that app is flagged — reusing
     `forge/src/forge/repo.py::owner_of_app`/`is_foreign` directly (same
     function calls `sync.py`'s foreign-write guard already uses), not a
     parallel rule.
  - Scope note: the plan asked for "no ledger **or ticket** output path
    resolves inside an upstream/foreign app." Ticket files live in the vault,
    outside this repo's filesystem — no code path in this repo writes them, so
    there is nothing to mechanically check for tickets specifically. The
    ownership guard for tickets remains agent-instruction-level (documented in
    `write-ticket.md`/`gap-ticket.md`, reusing the same named functions in
    prose that the code enforces). The implemented check covers what's
    actually code-reachable today: per-app ledger scaffolds — and is
    forward-compatible with per-app mirroring if that's ever built (PHASE-4's
    noted follow-up).

## Original planned scope (for reference — see "As-built record" above for

## what actually happened)

### New commands

- **`canonical/commands/ticket-review.md`** — the mandatory DoD gate. Runs
  gates **once**, by the orchestrator, and pastes the real output into every
  reviewer-lane prompt (do not let each lane re-run `bench run-tests`
  independently — on a Frappe bench a test run is materially more expensive
  than in the reference repo this pattern is ported from, so this matters more
  here, not less).
- **`canonical/commands/gap-ticket.md`** — files an out-of-scope finding as a
  new ticket: `labels: [gap]`, `origin:` field naming the parent ticket + review
  date, collision-checks the new key against the vault `INDEX.md` **and all
  three ledger files** (PHASE-4), adds a `build_state: gap` row to
  `LEDGER-proposed.md` specifically, and back-references the new ticket from
  the parent's journal `## REVIEW` entry. **Never expands the ticket under
  review** — this is the core rule of the gap loop.

### New reviewer agents (two, not more — see budget note)

- **`canonical/agents/code-reviewer.md`** — project-pattern lane: conventions,
  DRY against `frappe.utils`, override-system layering, per-app `CLAUDE.md`
  drift, docs-matches-code.
- **`canonical/agents/frappe-framework-reviewer.md`** — framework-correctness
  lane: `hooks.py` ordering, `doc_events` atomicity / stray `db.commit()`,
  permission query conditions, patch idempotency + `patches.txt` position,
  fixture filter scope, whitelist/CSRF posture.
- Existing `security-reviewer` and `qa-test-engineer` agents are **reused as-
  is**, not modified by this ticket unless a real gap is found in them.
- The two existing frontend specialist agents
  (`frontend-frappe-ui-specialist`, `frontend-quasar-specialist`) are reused in
  a **declared read-only review mode** rather than creating two more dedicated
  reviewer agents — every additional agent is a direct, permanent char-budget
  cost on 5 adapters, and their bodies already contain the relevant review
  knowledge.

### Risk tiers (set lane *count*; the existing pairings table sets *which*

### lanes — these compose, tiering does not replace `review-protocol.md` §4)

| Tier | Trigger (highest applicable wins) | Lanes |
|---|---|---|
| **3 · full** | permissions / `ignore_permissions` / `allow_guest`; money paths (Payment Entry, GL Entry, Sales/Purchase Invoice, POS closing, payroll); migration patch or `patches.txt` change; fixture export; `hooks.py` change; raw `frappe.db.sql`; `site_config`/scheduler; any `src_override/` touch; >~400 changed lines | project + framework + security |
| **2 · standard** | new DocType / controller / report / whitelist API; Vue views/composables with real logic | backend: project + framework · frontend: frontend-specialist + project |
| **1 · light** | docs/comments/tests-only; pure rename/move; localized <50-line one-file fix | one lane matching the surface |

Rule: **escalate, never de-escalate** — any CRITICAL/HIGH finding at tier 1/2
forces a tier-3 re-run after the fix, not a downgrade.

### Ownership guard on ticket writes (applies to both `/gap-ticket` and, once

### built, `/write-ticket` from PHASE-5)

Resolution order, reusing **existing** ownership machinery
(`forge/src/forge/repo.py::owner_of_app()` + `is_foreign()`, which read live
from `git remote get-url` — deliberately not a second hand-kept list that can
drift):

1. **The vault** — always, unconditionally, regardless of what code the
   finding concerns.
2. **The owning target repo** — bench root or `self`, both owned by
   definition.
3. **A per-app mirror** — only if the app is in `managed_apps` **and**
   `is_foreign()` is false **and** the app is not in `upstream_apps`.

A finding about `apps/frappe` or another upstream/foreign app still produces a
ticket — written to the vault and the owned bench root, naming the foreign app
as the *subject* of the ticket body — but **nothing is ever written under the
foreign app's own directory**. This mirrors the existing
`_confirm_foreign_writes` behavior for rendered artifacts (built in an earlier,
pre-epic commit — `173011a feat(sync): confirm before creating files in a repo
we do not own`), so the rule agents follow and the rule the code enforces are
literally the same rule, not a parallel one that can drift from it.

New `forge validate` check: no ledger or ticket output path may resolve inside
an `upstream_apps` entry or a foreign-remote app.

### Review protocol acceptance criterion (ALREADY DONE in PHASE-4, listed here

### only because it's part of this ticket's original scope statement)

The "gates run and observed to pass" row in `review-protocol.md` §2 was
already added in PHASE-4 — do not re-add it. Reviewer agents still need an
explicit **read-only `tools:` list** in their frontmatter (currently: **no
canonical agent sets `tools:` at all**, confirmed by inspection — every
rendered Claude subagent today gets unrestricted tools). Add a `forge validate`
check enforcing that reviewer agents declare a read-only tool list.

### Explicit non-goal (already decided, do not revisit without new information)

**Do not enforce `/ticket-review` from the Stop hook.** The hook has no
reliable way to know which ticket is in flight, and a false block there is
worse than an occasionally-missed review. The mechanical layer (hooks/gates)
stays objective and cheap; the DoD ceremony is enforced by protocol — the
journal `## REVIEW` entry is the proof, per `definition-of-done.md` (PHASE-4).

## Acceptance criteria — verified

- [x] `canonical/commands/ticket-review.md` and `gap-ticket.md` exist with
      correct frontmatter
- [x] `canonical/agents/code-reviewer.md` and `frappe-framework-reviewer.md`
      exist with correct frontmatter and a read-only `tools:` list
      (`[Read, Grep, Glob, Bash]`)
- [x] New `forge validate` rule: any agent with `review_only: true` must
      declare `tools:` excluding write capabilities — verified with two
      deliberate-failure probes (no `tools:` at all; `tools:` including
      `Write`) plus two automated regression tests
      (`test_validate_fails_when_review_only_has_no_tools`,
      `test_validate_fails_when_review_only_has_write`)
- [x] New `forge validate` rule: no scaffold directory resolves under an
      `upstream_apps` entry or a foreign-remote app — verified live by creating
      `.ci-fake-bench/apps/frappe/docs/harness/` and confirming the check
      fires, then confirming it's silent once removed; both directions also
      covered by automated tests
- [x] Risk-tier table is documented in `review-protocol.md` §7 (the
      authoritative policy, not only in `ticket-review.md`'s prose) and
      referenced from `ticket-review.md`
- [x] Char budget re-measured after 2 new agents + 2 new commands: antigravity
      (binding constraint) moved 7,975 → 8,191 chars (+216), still 6,809 under
      its 15,000 cap
- [x] `forge score --path canonical/ --fail-below 80` → lowest 100;
      `forge validate --no-check-drift` → schema valid; full suite → 357
      passed, 2 skipped (+26 over PHASE-5's 331)
- [x] `ruff check src/`, `mypy src/forge` (strict) → both clean (one new mypy
      error surfaced and fixed during this ticket — see Bugs below)
- [x] Live self-harness re-confirmed: `./scripts/harness/gates.sh quick` →
      `RESULT: GREEN`

The plan's suggested "end-to-end smoke: a real review producing an
out-of-scope finding" was **not** run as a live smoke test — there is no real
ticket in flight to review yet (PHASE-5's commands are unexecuted against a
real vault, per that ticket's own noted follow-up). Instead, the gap-loop
mechanics were verified by static assertion: `gap-ticket.md` correctly
documents delegating to `/write-ticket --gap-of` (verified in PHASE-5's tests
already), states the never-expand rule explicitly, and states the ownership
guard. A live smoke test is a fair follow-up once PHASE-5's commands are
exercised against a real ticket.

## Bugs found during this ticket

- `is_foreign()` in `forge/src/forge/repo.py` types its second argument as
  `set[str]`; the new validate check passed `target.owned_remotes`, which is a
  `frozenset[str]` (per the `Target` dataclass, `PHASE-1`). mypy strict caught
  this immediately (`Argument 2 to "is_foreign" has incompatible type
  "frozenset[str]"; expected "set[str]"`). Fixed by wrapping with `set(...)` at
  the call site rather than loosening `is_foreign`'s signature — no other
  caller passes a frozenset.
- A test assertion (`"includes a write capability" in out`) failed against
  real output because Rich's console word-wrapping inserted a line break
  mid-phrase. Fixed by normalizing whitespace before asserting
  (`" ".join(output.split())`) rather than asserting on raw wrapped text.

## Deviations from the original plan

None of substance — both noted open questions were resolved as concrete,
documented design decisions (see "As-built record") rather than deferred or
left ambiguous.

## Known follow-ups

- No live end-to-end smoke test of the full gap-loop against a real ticket
  (see above) — natural to run once PHASE-5's `/write-ticket` is exercised for
  real.
- Per-app ledger mirroring (noted as a PHASE-4 follow-up) still doesn't exist;
  the ownership-guard check built here is forward-compatible with it but has
  nothing real to protect yet beyond the target-root ledgers, which are never
  placed under an app directory in the first place.
