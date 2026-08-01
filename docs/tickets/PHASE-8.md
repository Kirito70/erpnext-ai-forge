---
id: PHASE-8
title: "forge ledger sync — reconcile vault tickets against the repo ledger"
build_state: done
epic: harness-port
depends_on: [PHASE-4]
blocks: []
---

# PHASE-8 — `forge ledger sync` (post-epic follow-up)

Not part of the original seven-phase plan. Closes follow-up #4 logged in
`INDEX.md` after PHASE-7 landed: "No `forge ledger sync` command exists to
reconcile vault and repo ledger copies — documented as an agent duty for now."

## Why

`definition-of-done.md` (PHASE-4) established that the vault owns intent
(`status:`) and the repo ledger owns evidence (`build_state:`), and that
neither field is derived from the other. That split is correct, but it leaves
a real gap open: nothing checks that the two stores agree on which *tickets
exist and have been worked*. A ticket marked `In Progress` in the vault with
no ledger row anywhere defeats the entire point of `LEDGER-pending.md` being
the one file a build session needs to read.

## What this does — and deliberately does not do

**Does:** checks ticket-key *coverage* across the two stores.
- A ledger row whose key has no matching vault ticket → `orphan-ledger-row`.
- A vault ticket marked `In Progress` or `Done` with no ledger row in any of
  the three files → `missing-ledger-row`.
- A vault ticket still `To Do` with no ledger row is **not** a finding — most
  of a backlog is untouched at any time, and flagging all of it would bury
  the two or three findings that actually matter under hundreds that don't.

**Does not:** sync `status:` and `build_state:` to each other, or compare
their values at all. A ticket marked `Done` in the vault with `build_state:
todo` in the ledger is not flagged — comparing those two fields is exactly
the coupling PHASE-4 split them to prevent. Pinned by a dedicated test
(`test_status_and_build_state_are_never_compared_to_each_other`).

**`--fix` does exactly one thing:** appends a conservative `todo` row to
`LEDGER-pending.md` for each `missing-ledger-row` finding. It never touches
the vault, never edits an existing row, and never removes an orphan row —
confirmed by `test_fix_never_touches_orphans`. The seeded `build_state` is
deliberately the honest minimum ("todo"), not a guess at the ticket's real
progress; whoever picks the ticket up next corrects it through the normal
build flow.

## Files created

- `forge/src/forge/ledger_sync.py` — `resolve_vault_path` (mirrors the exact
  discovery order in `ticketing-contract.md`: `--vault-path` explicit override
  → `$NOVIZNA_VAULT` → `~/.config/brain/brains.toml` default vault → `None`,
  never a guessed path), `parse_vault_tickets`, `parse_ledger_rows`,
  `reconcile`, `seed_missing_rows`.
- `forge/src/forge/commands/ledger.py` + `forge ledger sync --project <name>
  [--target bench|self] [--vault-path <path>] [--fix]` CLI command (new
  `ledger_app` sub-typer in `cli.py`, matching the `skills_app`/`apps_app`
  pattern).
- `forge/tests/test_ledger_sync.py` (19 tests).

## Explicitly not wired into CI or `forge validate`

Unlike every other check added in this epic, this one **requires a real
vault** — `$NOVIZNA_VAULT` or a `brains.toml` default, neither of which exists
on a CI runner or in a fresh checkout. Wiring it into the automated gate chain
would make every CI run either fail on an unresolvable vault or silently skip
the check, both worse than making it a manually-invoked command. This mirrors
the same reasoning that kept `/write-ticket`'s vault I/O undocumented-as-code
in PHASE-5 — vault access is real, but it is not automatable from this repo.

## Verification performed

- Manual end-to-end run against a throwaway fixture vault (`/tmp/fake-vault`,
  removed after): created a ticket `In Progress` with no ledger row, confirmed
  the finding; ran `--fix`, confirmed the exact row landed in
  `LEDGER-pending.md`; re-ran with no `--fix`, confirmed clean (idempotent);
  added a ledger row with no matching ticket, confirmed the `orphan-ledger-row`
  finding; ran `--fix` again, confirmed the orphan was left completely
  untouched (byte-count check before/after); confirmed vault-path resolution
  fails closed (`Could not resolve the vault path... Not guessing`) rather
  than falling back to a plausible-looking default.
- `pytest forge/tests -q` → 386 passed, 2 skipped (+19 over PHASE-7's 367)
- `ruff check src/`, `mypy src/forge` (strict) → both clean, 33 source files
- No `canonical/` or policy content changed, so `forge score`/`forge validate`
  are unaffected — confirmed unchanged (still 100 / schema valid)
- Live self-harness re-confirmed: `./scripts/harness/gates.sh quick` →
  `RESULT: GREEN`

## Known follow-ups

- No real vault exists yet to run this against for real (same gap noted for
  `/write-ticket` in PHASE-5/6) — the fixture-based tests and manual
  throwaway-vault probe are the only verification possible right now.
- `--project` is required per invocation; there is no config-level mapping
  from a target to "the vault project(s) it builds tickets for". Deliberately
  not added — a single bench could plausibly host tickets from more than one
  vault project, and guessing which one narrows the tool's use unnecessarily.
