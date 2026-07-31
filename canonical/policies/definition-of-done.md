---
id: definition-of-done
kind: policy
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-07-30
scope: [agent:architect, agent:qa-test-engineer]
---

# Definition of Done — Ledger, Journal, Ceremony

The vault says what to build. This says how build state is recorded, and what
"done" means.

---

## 1. Vault owns intent; the repo owns evidence

Two stores, one rule each, and **different field names** so they cannot be
confused:

| Lives in | Owns | Field | Owned by |
|----------|------|-------|----------|
| Vault `wiki/<project>/tickets/<KEY>.md` | title, type, epic, priority, points, labels, `depends_on`/`blocks`, scope, acceptance criteria | `status:` | **Human** |
| Repo `docs/harness/LEDGER-*.md` | build state, agent, timestamps, last commit | `build_state:` | **Agent** |
| Repo `docs/harness/journal/<KEY>.md` | checkpoints, pasted real gate output, the REVIEW entry | — | Agent |

The naming is the whole mechanism. `status: To Do` in the vault alongside
`build_state: done` in the ledger is **not** a contradiction: the first means
"the human has not confirmed verification", the second means "the ceremony ran".
Give both the same name and they drift, every agent guesses which wins, and the
ledger becomes untrustworthy within a month.

Neither field is derived from the other. Never write the vault's `status:`.

---

## 2. The ledger is three files

`docs/harness/` holds:

| File | `build_state` values | Read by |
|------|---------------------|---------|
| `LEDGER-proposed.md` | `proposed`, `gap` | triage, `/refine-ticket` |
| `LEDGER-pending.md` | `todo`, `claimed`, `in_progress`, `blocked`, `gates_green`, `reviewed` | **every build session** |
| `LEDGER-done.md` | `done`, `abandoned` | audits, release notes |

Split by lifecycle because `LEDGER-pending.md` is read on every ticket, and a
single file would bury the twelve rows that matter under four hundred that do
not. That cost is paid on every session, forever.

Add `LEDGER-blocked.md` later if blocked rows crowd out pending. The format
supports it with no migration.

### The invariant

**A key appears in exactly one ledger file.**

A `build_state` transition is a **move**: delete the row from one file, append it
to another. Never copy. This is the one place the design rots, so it is
machine-checked — `forge validate` fails on a key present in two files, or absent
from all three while its vault ticket exists.

### Row format

```
| KEY | build_state | agent | started | finished | last commit | notes |
```

Header and column order are machine-parsed. Do not reformat them.

---

## 3. The journal

One file per ticket: `docs/harness/journal/<KEY>.md`.

- Checkpoints as you go, so an interrupted session can resume.
- **Pasted real gate output.** Not "tests passed" — the actual lines. A summary
  cannot be audited, and writing one from memory is how green-by-omission
  happens.
- A `## REVIEW` section, added by `/ticket-review`.

**No REVIEW entry means the review did not happen, which means the ticket is not
done.** That is the gate, and it is enforced by contract rather than by a hook:
the Stop hook has no reliable way to know which ticket is in flight, and a false
block there is far more damaging than a missed review.

---

## 4. What "done" requires

All of these, in order:

1. Every acceptance criterion in the vault ticket is met, or explicitly deferred
   with a reason.
2. `scripts/harness/gates.sh full` was **run and observed to pass** — output
   pasted into the journal. A gate that was already red before you started is
   named and ticket-linked, not silently skipped.
3. `/ticket-review` ran at the risk tier the change warrants, and the journal
   carries its `## REVIEW` entry.
4. Findings that were CRITICAL or HIGH are fixed in-ticket. Out-of-scope findings
   became gap tickets — the ticket is **not** expanded to absorb them.
5. `build_state` moved to `done` in the ledger (row moved to `LEDGER-done.md`).
6. The vault ticket's `status:` is left alone for the human.

## 5. What "done" is not

- Not "the code is written."
- Not "the tests I wrote pass" — the gates covering the change must pass.
- Not "it works locally" when the gate that would have caught it was skipped.
- Not "mostly done with a follow-up" — either it meets the criteria or it does
  not, and the remainder is a gap ticket with a key.

---

## 6. Stop-and-ask triggers

Halt, present options, and wait. Do not choose for the user:

- A new DocType is required.
- Any change under `apps/frappe`, `apps/erpnext`, or another upstream app.
- A migration patch that is not obviously idempotent.
- A permission model change, or anything touching `ignore_permissions` /
  `allow_guest`.
- Money paths: GL Entry, Payment Entry, invoices, POS closing, payroll.
- The ticket's stated approach turns out to be wrong.
- A gate command itself looks wrong (as opposed to the code failing it) — that is
  a finding about the harness; fix `canonical/harness/gates.yaml`, never the
  generated script.
