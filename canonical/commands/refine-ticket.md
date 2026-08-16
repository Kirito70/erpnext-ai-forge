---
id: refine-ticket
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-07-31
triggers_agents: [novizna-architect, ticket-refiner]
---

# /refine-ticket

Adversarially pressure-test an existing proposed or gap ticket before it is
picked up for build — verify its claims against live code, attack its design,
resolve the cheap open questions itself, and harden it for an implementer
weaker than whoever wrote it.

## Usage

```
/refine-ticket <KEY> [--focus verify|decide|specify|all]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<KEY>` | yes | The ticket key, e.g. `NPOS-D5` |
| `--focus` | no | Restrict refinement to one pass from [`ticket-authoring-guide`](../skills/meta/ticket-authoring-guide.md). Default: all five. |

## Examples

```
/refine-ticket NPOS-D5
/refine-ticket NPOS-D11 --focus specify
```

## Pipeline

1. **Architect:** delegate to [`ticket-refiner`](../agents/ticket-refiner.md).
2. **Ticket Refiner:** re-run **VERIFY** against current bench state — a claim
   that was true when the ticket was written may not be true now. Re-check
   `discovery/data/*.json`; if it's stale for anything the ticket cites,
   trigger a targeted re-scan before trusting either the ticket or the
   discovery cache.
3. **Ticket Refiner:** re-run **PLACE** — confirm the key still doesn't collide
   (another ticket may have claimed it since), confirm `depends_on` entries
   still point at real, unresolved tickets.
4. **Ticket Refiner:** attack **DECIDE** — for each locked decision, ask "what
   would make this wrong?" Frappe-specific classes worth checking every time:
   permission-query-condition isolation across orgs, `ignore_permissions`
   creeping into a path that didn't need it, non-idempotent patches, fixture
   filters wide enough to sweep another app's rows, `doc_events` committing
   mid-transaction. Cite [`anti-pattern-findings.json`](../../discovery/data/anti-pattern-findings.json)
   where a standing finding of the same class already exists on this bench —
   it means the mistake is not hypothetical here.
5. **Ticket Refiner:** verify **SPECIFY** is actually checkable — every
   acceptance criterion needs a concrete command or a concrete expected value,
   not a description of desired behavior. Reject vague ACs; rewrite them
   concrete.
6. **Ticket Refiner:** resolve what's cheap to resolve itself (a DocType field
   name, an existing endpoint's exact signature) rather than leaving it as an
   open question for the implementer.
7. **Ticket Refiner:** report PASS (ticket is ready to build) or a list of
   required edits, each tagged to the pass that found it (VERIFY/PLACE/DECIDE/
   SPECIFY/DEFEND).
8. **Architect:** apply the required edits to the ticket file, or escalate per
   [escalation-rules](../policies/escalation-rules.md) if a required edit
   itself needs human approval (e.g., the refiner determined a new DocType is
   actually required).
9. **Architect:** on a PASS verdict, move the ledger row from `LEDGER-proposed.md`
   to `LEDGER-pending.md` as `build_state: todo` — `brain ticket start <KEY> --state todo`
   performs the move. This is the **only** writer of that transition: without it a refined
   ticket never reaches the queue a build session reads, and `/ticket-review` is later told
   to move a row out of `LEDGER-pending.md` that nothing ever put there.
   On a FAIL verdict the row stays in `LEDGER-proposed.md`.

## Notes

- This command **never changes `status:`** — refinement is not approval to
  build; that's a separate, human-gated step. Moving `build_state` to `todo` is
  not approval either: it records that the ticket is well-formed enough to be
  worked, which is evidence, not intent.
- If refinement surfaces a finding that's genuinely a *different* piece of
  work than the ticket describes, that's a job for `/write-ticket --gap-of
  <KEY>`, not an expansion of this ticket's scope.
- The nine-step structure above maps to the five authoring passes with VERIFY,
  PLACE and DECIDE each split into a "re-check" and an "attack" sub-step where
  the distinction matters (state may have moved since the ticket was written;
  design may look locked but be wrong).

## Tools Touched

None directly — reads discovery data, the vault ticket, and ledger files.
