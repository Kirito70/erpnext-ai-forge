---
id: gap-ticket
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-07-31
triggers_agents: [novizna-architect]
---

# /gap-ticket

File an out-of-scope finding discovered during
[`/ticket-review`](ticket-review.md) (or any other review/build activity) as
its own tracked ticket — **never** as an expansion of the ticket currently
under review.

## Usage

```text
/gap-ticket "<subject>" --origin <PARENT-KEY>
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<subject>` | yes | One-line description of the finding |
| `--origin` | yes | The ticket/review that surfaced this finding |

## Examples

```text
/gap-ticket "Payment Entry rounding drifts on split settlement" --origin NPOS-D5
```

## Pipeline

This is a thin, review-context wrapper around
[`/write-ticket`](write-ticket.md) — it does not duplicate that command's
logic, it constrains how it's invoked:

1. **Architect:** call `/write-ticket "<subject>" --gap-of <PARENT-KEY>`.
   `/write-ticket` handles `--gap-of` by setting `labels: [gap]`, an `origin:`
   field naming the parent ticket and today's date, and adding a
   `build_state: gap` row to `LEDGER-proposed.md` — see
   [`write-ticket`'s pipeline](write-ticket.md#pipeline) for the exact
   mechanics, not repeated here.
2. **Architect:** back-reference the new gap ticket's key from the parent's
   `docs/harness/journal/<PARENT-KEY>.md` — either in the `## REVIEW` entry
   being written for the parent (the common case, called from
   `/ticket-review`), or as a standalone journal note if called outside a
   review.
3. **Architect:** report the new ticket's key back to whoever is running the
   review, so it can be cited in the reviewer's findings table.

## The one rule

**A finding that is real but out of scope for the ticket under review does not
expand that ticket.** It becomes its own ticket, with its own acceptance
criteria, its own review, its own build. Folding it in instead means the
original ticket's scope silently grew past what was reviewed and approved for
it.

## Ownership guard

Applies exactly as documented in
[`/write-ticket`'s ownership guard](write-ticket.md#ownership-guard) — a
finding about code in an upstream or foreign-remote app still gets a ticket,
written to the vault and the owning target's ledger, naming the foreign app as
the subject. Nothing is ever written into the foreign app's own directory.

## Tools Touched

None directly — delegates entirely to `/write-ticket`.
