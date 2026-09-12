---
id: ticket-authoring-guide
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-07-31
trigger: "Authoring a new vault ticket via /write-ticket, or refining one via /refine-ticket"
scope: [agent:novizna-architect, agent:ticket-refiner]
foundational: false
domain: meta
security_score: 100
supersedes: []
---

# Ticket Authoring Guide

How to write a ticket a **weaker implementer than you** can build from without
guessing. Five passes, in order. Skipping a pass is how a ticket ships that
looks complete and isn't. Loaded by `/write-ticket` and `/refine-ticket`
(directly, and via the `ticket-refiner` agent).

The ticket *schema* (frontmatter fields, vault paths, `depends_on` semantics) is
[`ticketing-contract`](../../policies/ticketing-contract.md) — read that first if
you haven't. This skill is about *how to think* while filling that schema in,
not the schema itself.

## When to Load

- `/write-ticket` is invoked for a new proposed or gap ticket
- `/refine-ticket` is invoked on an existing proposed/gap ticket
- The `ticket-refiner` agent is delegated a ticket to pressure-test

## The Five Passes

### 1. VERIFY

Ground every claim the ticket will make against the bench **before** writing
anything. A ticket that cites a DocType field, app, or hook that doesn't exist
sends a weaker implementer down a dead end they have no way to detect.

- Check `discovery/data/*.json` first — `doctype-index.json` for DocTypes and
  their fields, `apps-index.json` for which app owns what, `hooks-index.json`
  for existing hook wiring, `api-surface.json` for existing whitelist
  endpoints, `override-map.json` for what's already overridden.
- This is the **same pre-flight** the architect already runs (see
  [architect §0](../../agents/novizna-architect.md)) — do not invent a second
  verification mechanism. If a reference is missing from discovery, trigger a
  targeted re-scan before assuming it doesn't exist; only treat it as absent
  after the re-scan still misses.
- If you cannot verify a claim against real bench state, the ticket says so
  explicitly ("assumed: ...", "not yet confirmed: ...") rather than stating it
  as fact.

### 2. PLACE

Decide where this ticket lives before writing its body.

- **Collision-check the key** across three places, in this order: the vault
  project's `tickets/` directory, the vault `INDEX.md`, and **all three ledger
  files** (`LEDGER-proposed.md`, `LEDGER-pending.md`, `LEDGER-done.md` — see
  [`definition-of-done`](../../policies/definition-of-done.md)). A key that
  exists in any of the three is taken.
- Confirm which vault project (`jira_project`) and which epic the ticket
  belongs under. If no epic fits, that's a decision for the human, not a new
  epic invented on the spot.
- If the ticket is a **gap ticket** (raised during `/ticket-review` on other
  work), it goes to `LEDGER-proposed.md` with `labels: [gap]` and an `origin:`
  field naming the parent ticket — never expands the parent.

### 3. DECIDE

Lock the design decisions that a weaker implementer must not be left to make
themselves — because they'll make them differently than the reviewer expects,
and the disagreement surfaces at review time instead of before build starts.

Forbidden without escalation (see
[escalation-rules](../../policies/escalation-rules.md)):

- Any edit under an upstream app (`frappe`, `erpnext`, `crm`, `hrms`, `lending`,
  `lms`, `education`, `helpdesk`, `gameplan`, `drive`, `press` — see
  `upstream_apps` in `forge.config.yaml`)
- A new DocType, without explicit human approval
- Choosing **fixture vs. Custom Field vs. Property Setter** for a schema
  change — decide it in the ticket; do not leave it to the implementer
- A migration patch whose idempotency is not yet argued (see SPECIFY below)

Other decisions to lock now rather than defer:

- Which app owns the change, and whether it's a new file or an extension of an
  existing one
- Whether the change needs a permission model update (and if so, sketch the
  permission matrix now — SPECIFY writes it down formally)

### 4. SPECIFY

Write the ticket so a weaker implementer needs no follow-up questions. Required
sections, present or explicitly marked not-applicable:

- **DocType/field table** — for any schema touch: field name, fieldtype,
  `reqd`, `options`, and which DocType it lands on.
- **Whitelist endpoint signature** — for any new/changed API: full signature,
  `allow_guest` posture (and if `true`, the rate-limit stance — see
  [`whitelist-api-patterns`](../frappe-core/whitelist-api-patterns.md)), and the
  permission check it performs.
- **Permission matrix** — role × operation, for anything touching permissions.
- **Patch position** — for a migration patch: exact position in `patches.txt`,
  and an explicit idempotency argument (what happens if this patch runs twice
  — a patch that silently corrupts on re-run is a Tier-3 review trigger per
  [review-protocol](../../policies/review-protocol.md)).
- **Frontend file destinations** — for any UI ticket: the exact folder each new
  page/component lands in, as `<area>/<category>/<entity>/`, plus the nav-config
  entry and route path that must agree with it (see
  [`spa-file-structure`](../frontend/spa-file-structure.md)). "Add a Coupon Codes
  page" is not a destination; `pages/pos/manage/pricing/coupon-codes/` is. A
  ticket that leaves this to the implementer gets a file dropped wherever the
  neighbours already are, which is how flat page directories grow.
- **Fixture filter scope** — for a fixture export: the exact filter, and
  confirmation it does not sweep in another app's records.
- **Negative acceptance criteria** — not just "returns the right data" but
  "returns 403 for the wrong role", "permission query condition isolates
  correctly across two orgs", "re-running the patch is a no-op". These are the
  criteria a weak implementer is most likely to skip because nothing prompts
  them.

### 5. DEFEND

Before handing the ticket off, attack it the way `/refine-ticket` will:

- What's the cheapest way an implementer could satisfy the letter of this
  ticket while missing its point?
- Which acceptance criterion is actually unverifiable as written (no concrete
  command, no concrete expected value)?
- Is anything in DECIDE contradicted by anything in SPECIFY?

If you can't answer these, the ticket isn't ready — send it through
`/refine-ticket` rather than shipping it as-is.

## Common Pitfalls

- Citing a DocType field that exists on a *different* DocType than the one
  named — always confirmed against `doctype-index.json`, never against memory.
- Writing acceptance criteria that describe behavior but give no way to check
  it mechanically (no command, no expected exit code, no expected row count).
- Deciding fixture-vs-Custom-Field implicitly by which one is mentioned first,
  rather than explicitly in DECIDE.
- Forgetting the negative case: "handles X" without "and rejects not-X".
- Naming a UI surface without naming its folder — the implementer then places it
  by imitation, and every ticket after inherits the wrong tree.

## References

- [`ticketing-contract`](../../policies/ticketing-contract.md) — the schema this guide fills in
- [`definition-of-done`](../../policies/definition-of-done.md) — the ledger this ticket's key must collision-check against
- [`review-protocol`](../../policies/review-protocol.md) — the tiering that SPECIFY's negative-AC requirement feeds
- [`novizna-architect`](../../agents/novizna-architect.md) — the §0 pre-flight this guide's VERIFY pass reuses
- [`write-ticket`](../../commands/write-ticket.md), [`refine-ticket`](../../commands/refine-ticket.md) — the commands that load this skill
