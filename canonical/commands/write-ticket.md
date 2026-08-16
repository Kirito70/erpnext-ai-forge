---
id: write-ticket
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-07-31
triggers_agents: [novizna-architect]
---

# /write-ticket

Author a new vault ticket — or a gap ticket raised while working something
else — that a weaker implementer can build from without guessing.

## Usage

```
/write-ticket "<subject>" [--epic <EPIC-X>] [--type Story|Task|Bug|Spike] [--gap-of <PARENT-KEY>]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<subject>` | yes | One-line description of the work |
| `--epic` | no | Epic to file under. If omitted, ask rather than guess. |
| `--type` | no | `Story` \| `Task` \| `Bug` \| `Spike`. Default: `Story`. |
| `--gap-of` | no | Parent ticket key, if this is a gap ticket raised during `/ticket-review`. Sets `labels: [gap]` and `origin:` automatically. |

## Examples

```
/write-ticket "Add section metadata to the masters registry" --epic EPIC-D
/write-ticket "Payment Entry rounding drifts on split settlement" --type Bug --gap-of NPOS-D5
```

## Pipeline

1. **Architect:** load [`ticket-authoring-guide`](../skills/meta/ticket-authoring-guide.md) and [`ticketing-contract`](../policies/ticketing-contract.md).
2. **Architect:** run the five passes — **VERIFY** (ground every claim against `discovery/data/*.json`, reusing the [architect §0 pre-flight](../agents/novizna-architect.md)), **PLACE** (resolve `$NOVIZNA_VAULT` per the contract; collision-check the proposed key across the vault `tickets/` dir, the vault `INDEX.md`, and all three ledger files), **DECIDE** (lock schema/permission/patch decisions; escalate per [escalation-rules](../policies/escalation-rules.md) if a forbidden decision is required), **SPECIFY** (fill the mandatory sections — DocType/field table, whitelist signature, permission matrix, patch position + idempotency argument, negative ACs, whichever apply), **DEFEND** (self-check before handing off).
3. **Architect:** if `--gap-of` was given — set `labels: [gap]`, `origin: <PARENT-KEY> (<today's date>)`, and back-reference the new ticket from the parent's journal `## REVIEW` entry (create the entry if this is the first gap raised against that ticket).
4. **Architect:** write the ticket file to `$VAULT/wiki/<project>/tickets/<KEY>.md` with the frontmatter schema from `ticketing-contract`. Do not flip `status:` — a new ticket starts `To Do` and stays human-owned from that point on.
5. **Architect:** add a ledger row to `LEDGER-proposed.md` for **every** ticket, not only gaps — `build_state: gap` when `--gap-of` was given, otherwise `build_state: proposed`.

   A ticket with no ledger row is invisible to every build session, and `forge ledger sync` reports it as `missing-ledger-row` indefinitely — 70 of 136 novizna tickets are in exactly that state. Writing the row only for gaps also contradicted this command's own ownership guard below, which says a ticket is written "to the vault **and to the owning target's ledger**" unconditionally.
6. **Architect:** report the ticket key, its `depends_on`/`blocks` as written, and anything left as "assumed" or "not yet confirmed" from the VERIFY pass — do not silently drop these caveats from the handoff.

## Ownership guard

Every ticket is written to the vault, unconditionally, regardless of what code
it concerns. If the ticket's subject involves a repo forge does not own — an
upstream app (`upstream_apps` in `forge.config.yaml`) or an app whose git
remote fails `is_foreign()` — the ticket still gets written, to the vault and to
the owning target's ledger, and its body names the foreign app as the *subject*.
**Nothing is ever written into the foreign app's own directory.** This is the
same ownership check `forge sync` already applies to rendered artifacts
(`forge/src/forge/repo.py::owner_of_app` / `is_foreign`) — do not invent a
second rule that can drift from it.

## Notes

- `status:` is human-owned from the moment the ticket exists. This command sets
  it once, to `To Do`, and never touches it again.
- A ticket with unresolved "assumed" claims from VERIFY is not ready to build —
  say so in the handoff rather than letting it look finished.
- Prefer `/refine-ticket` on anything non-trivial before it's picked up for
  build; this command produces a first draft, not a guaranteed-adversarial one.

## Tools Touched

None directly — this command reads discovery data and vault/ledger files. It
does not run any `canonical/tools/*.yaml` wrapper.
