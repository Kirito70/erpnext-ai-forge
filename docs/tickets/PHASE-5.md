---
id: PHASE-5
title: Ticket authoring and refinement — /write-ticket, /refine-ticket, ticket-refiner
build_state: done
epic: harness-port
depends_on: [PHASE-4]
blocks: [PHASE-6]
---

# PHASE-5 — Ticket authoring and refinement

## Why

`AGENTS-TICKETING.md` (now sourced from `canonical/policies/ticketing-contract.md`,
PHASE-4) defines the vault ticket schema and rules well, but no tooling
actually *uses* it — there is no `/write-ticket`, no `/refine-ticket`, no
`ticket-refiner` agent. The reference implementation this harness is ported
from has a five-pass authoring framework (Verify → Place → Decide → Specify →
Defend) plus a nine-step adversarial refinement pass; both need adapting to
Frappe conventions rather than copied verbatim (the reference is FastAPI/Vue).

## As-built record

All four planned artifacts were built as scoped, with both open questions
resolved before writing content:

- **Open question 1 resolved**: `discovery/data/anti-pattern-findings.json`
  exists and has real, current data. Confirmed the `sql_fstring` finding cited
  in the plan is real: `noviznaerp_payroll/custom/loan_custom.py:137`, 15
  occurrences. Also found and cited: `ignore_permissions` is the most common
  finding (present in 8 of 9 scanned custom apps), `allow_guest` findings in
  `cargo_management`/`novizna_pos`/`noviznaerp_payroll`, and
  `db_commit_non_test` in 6 of 9 apps. `ticket-refiner.md` cites these by exact
  file:line rather than inventing hypothetical examples.
- **Open question 2 resolved**: `/write-ticket` documents the vault-write flow
  (resolving `$NOVIZNA_VAULT`, writing to `wiki/<project>/tickets/<KEY>.md`)
  but does **not** implement live I/O against a real vault — this ticket
  scoped the authoring *logic* (the five-pass framework, collision-checking,
  ownership guard, gap-loop wiring) as prose/pipeline steps an agent follows,
  consistent with how every other canonical command in this repo works (they
  are agent instructions, not executable code). No vault sandbox/test-double
  was needed as a result.

### Files created

- `canonical/skills/meta/ticket-authoring-guide.md` — the five-pass framework
  (VERIFY/PLACE/DECIDE/SPECIFY/DEFEND), each pass adapted to Frappe per the
  plan: VERIFY reuses the architect's existing §0 pre-flight rather than a new
  mechanism; PLACE collision-checks across vault tickets + `INDEX.md` + all
  three ledger files; DECIDE adds the forbidden-path list (upstream apps, new
  DocTypes, fixture-vs-Custom-Field-vs-Property-Setter, patch idempotency);
  SPECIFY requires DocType/field tables, whitelist signatures with
  `allow_guest` posture, permission matrices, patch position + idempotency
  argument, and negative ACs.
- `canonical/commands/write-ticket.md` — `/write-ticket "<subject>" [--epic]
  [--type] [--gap-of <PARENT-KEY>]`. Documents the ownership guard explicitly
  (reusing `forge/src/forge/repo.py::owner_of_app`/`is_foreign` by name, not a
  parallel rule) and the gap-ticket flow (`--gap-of` sets `labels: [gap]` +
  `origin:`, writes a `build_state: gap` row to `LEDGER-proposed.md`,
  back-references the parent's journal).
- `canonical/commands/refine-ticket.md` — `/refine-ticket <KEY> [--focus]`.
  Delegates to `ticket-refiner`; the nine-step pipeline maps each of the five
  authoring passes to a "re-check" (state may have moved) and, for DECIDE, an
  explicit "attack" step citing the concrete anti-pattern classes above.
  Explicitly never touches `status:`.
- `canonical/agents/ticket-refiner.md` — new agent, `scope:
  [agent:novizna-architect]`, `foundational: false`. No `tools:` frontmatter added
  (consistent with the current repo-wide convention that no canonical agent
  sets one yet — fixing that is explicitly PHASE-6 scope, not this ticket's).

## Original planned scope (for reference — see "As-built record" above for
## what actually happened)

1. **`canonical/skills/meta/ticket-authoring-guide.md`** — the five-pass
   framework, as a **skill** (not a doc), so it is scored, versioned, and
   rendered to all seven tools automatically like every other skill. Frappe
   adaptations to each pass:
   - **VERIFY**: ground against `discovery/data/*.json` first — reuse the
     architect agent's existing §0 stale-reference pre-flight rather than
     inventing a parallel verification mechanism.
   - **PLACE**: collision-check the proposed ticket key across vault tickets,
     the vault `INDEX.md`, **and** all three ledger files (PHASE-4) before
     assigning it.
   - **DECIDE**: add a Frappe-specific forbidden-path list — never edit an
     upstream app (`canonical/`'s `upstream_apps` list), no new DocType
     without explicit human approval, fixture-vs-Custom-Field-vs-Property-
     Setter must be decided *in the ticket* (not left to the implementer), and
     any migration patch must state its idempotency argument explicitly.
   - **SPECIFY**: require a DocType/field table (fieldtype, `reqd`, `options`),
     a whitelist endpoint signature including its `allow_guest` posture and
     rate-limit stance, a permission matrix, the patch's position in
     `patches.txt`, and negative acceptance criteria (403 for the wrong role,
     permission-query-condition isolation, `on_submit` idempotency).
2. **`canonical/commands/write-ticket.md`** — reads the skill above +
   `ticketing-contract.md`; routes gap findings specifically to
   `LEDGER-proposed.md` with a `gap` state (this half connects to PHASE-6's
   gap loop, so implementation order matters if both are picked up together).
3. **`canonical/commands/refine-ticket.md`** — the adversarial nine-step
   refinement pass; verifies claims made in a proposed ticket against live
   code, pressure-tests the design, resolves cheap open questions itself,
   hardens the spec for a weaker implementer than the one refining it.
4. **`canonical/agents/ticket-refiner.md`** — new agent, `scope:
   [agent:novizna-architect]`, `foundational: false`. Cites Frappe-specific fact
   classes that have actually been wrong on this bench as its "classes of
   things to check" (the plan named `discovery/data/anti-pattern-findings.json`
   — known SQL-injection sites in `noviznaerp_payroll`, `src_override/` files —
   as the source for these; confirm this file still exists and still has that
   content before citing it, since discovery data can go stale).

## Budget/scope note carried over from planning

Adding one new agent (`ticket-refiner`) costs ≈+150 chars on every aggregate
render across 5 budgeted adapters (cursor/cline/copilot/codex/antigravity).
Judged acceptable at plan time given the headroom measured in PHASE-3/4
(antigravity: 7,133 chars free as of PHASE-4's last verification) — **re-check
actual headroom before landing**, since PHASE-4 already consumed some of it and
a new agent + new skill + two new commands is a bigger increment than any single
prior phase added.

## Acceptance criteria — verified

- [x] `canonical/skills/meta/ticket-authoring-guide.md` exists, scores 100 via
      `forge score`, and is rendered by all 7 adapters (confirmed via
      `render()` for `claude-code`; identical pipeline for the other six)
- [x] `canonical/commands/write-ticket.md` and `refine-ticket.md` exist with
      correct frontmatter matching `audit-skills.md`'s pattern
- [x] `canonical/agents/ticket-refiner.md` exists with correct frontmatter
      matching `qa-test-engineer.md`'s pattern
- [x] `forge validate --no-check-drift` → `✓ schema valid`, no new issues
- [x] Char budget re-measured on all 5 budgeted adapters: antigravity (the
      binding constraint) moved 7,867 → 7,975 chars (+108), still 7,025 under
      its 15,000 cap. No adapter exceeded budget.
- [x] `forge score --path canonical/ --fail-below 80` → lowest 100
- [x] New test file `forge/tests/test_ticket_authoring.py` (19 tests): asserts
      frontmatter correctness, ≥95 score on all 4 new files, cross-references
      in the skill actually resolve to real files, the ownership guard and
      gap-loop mechanics are named explicitly in `write-ticket.md`'s body (not
      just implied), `refine-ticket.md` states it never touches `status:`,
      `ticket-refiner.md` cites the real `loan_custom.py` finding by name (not
      a hypothetical), and char budgets hold — all 19 passed on first run
      after one lint fix (see Bugs below)
- [x] Full test suite: 331 passed, 2 skipped (+19 over PHASE-4's 312)
- [x] `ruff check src/` (scope per PHASE-1's CI decision), `mypy src/forge`
      (strict) → both clean
- [x] Live self-harness re-confirmed green after landing:
      `./scripts/harness/gates.sh quick` → `RESULT: GREEN`

## Bugs found during this ticket

- The live `hook-posttooluse.sh` (built in PHASE-2, now actually running
  against this repo per PHASE-1) **blocked its own edit**: an unused local
  variable (`F841`) in the first draft of `test_ticket_authoring.py`. Fixed by
  removing the dead assignment. Notable as the first time in this epic the
  harness enforced something on itself in real time rather than in a test.

## Deviations from the original plan

None of substance. Both "known open questions" from the original draft were
resolved before implementation (see "As-built record" above) rather than
deferred.

## Known follow-ups

- Reviewer-agent `tools:` restriction (read-only tool lists) is explicitly
  PHASE-6 scope, not touched here — `ticket-refiner` has no `tools:`
  frontmatter, consistent with every other current canonical agent.
- No live vault I/O exists yet for `/write-ticket` to actually execute against
  — it documents the flow; nothing in this repo currently *runs* a command
  against a real Obsidian vault. If that's wanted, it's a new, separate
  ticket, not an extension of this one.
