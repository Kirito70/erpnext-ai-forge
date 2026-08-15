---
id: ticket-review
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-07-31
triggers_agents: [architect, security-reviewer, qa-test-engineer, code-reviewer, frappe-framework-reviewer, frontend-frappe-ui-specialist, frontend-quasar-specialist]
---

# /ticket-review

The mandatory Definition-of-Done gate. Runs before a ticket's `build_state`
moves to `done` — see
[`definition-of-done`](../policies/definition-of-done.md). Not enforced by any
hook; the proof it ran is the journal `## REVIEW` entry.

## Usage

```
/ticket-review <KEY>
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<KEY>` | yes | The ticket key whose implementation is under review |

## Examples

```
/ticket-review NPOS-D5
```

## Pipeline

1. **Architect:** classify the change into a risk tier per
   [review-protocol §7](../policies/review-protocol.md#7-risk-tiered-lane-selection)
   — take the **highest** trigger that applies, never average across several
   smaller ones.
2. **Architect:** **run the gates once**, yourself — `scripts/harness/gates.sh
   full` for the change's stack. Paste the real output into every reviewer
   lane's prompt as authoritative context; a lane may run targeted read-only
   probes to verify a specific claim, but must not re-run the full gate suite
   itself. On a Frappe bench a test run costs real time — re-running it once
   per lane multiplies that cost for no additional signal.
3. **Architect:** delegate to the lanes the tier selects (§7's table):
   - **project-pattern** — [`code-reviewer`](../agents/code-reviewer.md) for
     backend/integrations/devops artifacts; the *other* frontend specialist in
     [review mode](../agents/frontend-frappe-ui-specialist.md#review-mode) for
     frontend artifacts.
   - **framework** — [`frappe-framework-reviewer`](../agents/frappe-framework-reviewer.md).
   - **security** — [`security-reviewer`](../agents/security-reviewer.md), per
     §4's existing mandatory pairing; **holds veto on any CRITICAL finding**.
   - **tests** — `qa-test-engineer`, confirming the AC↔test mapping and the
     80% coverage floor on changed code.
4. **Architect:** each lane emits a review per
   [review-protocol §1](../policies/review-protocol.md#1-review-output-format).
5. **Architect:** compute acceptance per
   [review-protocol §2](../policies/review-protocol.md#2-acceptance-criteria-v02)
   — including the **"gates run and observed to pass"** row. A lane that
   reports based on inferred rather than observed gate output fails this
   criterion regardless of what else it found.
6. **Architect:** CRITICAL/HIGH findings **in scope** of the ticket are fixed
   in-ticket and re-reviewed (loop cap per
   [review-protocol §3](../policies/review-protocol.md#3-loop-cap-tightened--v02-part-b-item-2)).
   Findings **out of scope** of the ticket are filed via
   [`/gap-ticket`](gap-ticket.md) — **never** absorbed into this ticket's
   scope, no matter how small the fix looks.
7. **Architect:** on acceptance, append a `## REVIEW` entry to
   `docs/harness/journal/<KEY>.md` — reviewer verdicts, the pasted gate output,
   any gap tickets filed — **creating `docs/harness/journal/` if it is absent**;
   then move the ledger row from `LEDGER-pending.md` to `LEDGER-done.md`
   (`build_state: done`). `brain ticket done <KEY>` does both: it moves the row
   and appends the journal entry, creating the directory. The vault ticket's
   `status:` is left untouched for the human.

   The directory's absence is not hypothetical — it did not exist in the Novizna
   bench at all, which by §3 of
   [definition-of-done](../policies/definition-of-done.md) ("No REVIEW entry
   means the review did not happen") meant no ticket there had ever been
   formally completed. Silently skipping the write is indistinguishable from a
   review that never ran.

## Risk tiering quick reference

See [review-protocol §7](../policies/review-protocol.md#7-risk-tiered-lane-selection)
for the full table. Escalate, never de-escalate: a CRITICAL/HIGH finding at
tier 1 or 2 forces a tier-3 re-run of the fix.

## Notes

- This command is **not** wired to any Stop hook. The mechanical harness
  (`scripts/harness/gates.sh`) verifies gates pass; it has no reliable way to
  know which ticket is in flight, and a false block there would be worse than
  an occasionally-missed review. The DoD ceremony is enforced by this command
  and proven by the journal entry, not by automation.
- A pre-existing red gate is named and ticket-linked in the review, never
  silently left out.

## Tools Touched

None directly — invokes `scripts/harness/gates.sh` once, then delegates to
review agents.
