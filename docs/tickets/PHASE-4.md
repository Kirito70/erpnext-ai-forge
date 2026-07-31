---
id: PHASE-4
title: Operating manual, ticketing contract → canonical, three-file ledger, Jira seam
build_state: done
epic: harness-port
depends_on: [PHASE-2]
blocks: [PHASE-5, PHASE-6]
---

# PHASE-4 — Operating manual, ticketing contract, ledger

## Why

Pre-existing defect, found during original planning and fixed here:
`adapters/_shared/templates/ticketing-and-memory.md.j2` held ~4,500 characters
of **normative rules** (vault layout, ticket frontmatter schema, the binding
force of `depends_on`, who owns `status:`) directly in the adapter template
layer — no `version:`, no `owners:`, no `last_reviewed:`, invisible to
`forge score --path canonical/`, invisible to `forge validate`, impossible to
`forge deprecate`. That is a second, unversioned source of truth for normative
content, inside the one repo built specifically to prevent that pattern.

Also needed: a stack-neutral reasoning protocol (ported and adapted from a
sibling repo's `OPERATING_MANUAL.md`), and a ledger design that lets build
state live in-repo (per explicit user instruction) *alongside* the existing
Obsidian-vault ticket source of truth, without creating the same kind of
double-truth problem the ticketing-contract move was fixing.

## Scope delivered

### Ticketing contract extracted to canonical (content-neutral, proven)

- New `canonical/policies/ticketing-contract.md` — the moved contract, with
  proper frontmatter (`id`, `version: 1.0.0`, `owners`, `last_reviewed`,
  `scope`).
- `adapters/_shared/templates/ticketing-and-memory.md.j2` shrunk to a template:
  `{{ policies | selectattr("id", "eq", "ticketing-contract") | map(attribute="body") | first }}`
  plus the provenance footer.
- **Proven content-neutral**: rendered `AGENTS-TICKETING.md` before and after
  the move, diffed with the embedded timestamp normalized out — the *only*
  difference across all 103 lines is the provenance footer now naming the exact
  source file (`canonical/policies/ticketing-contract.md` vs. the old
  `canonical/`). All contract text byte-identical.

### New canonical policy: `operating-manual.md`

Adapted (not copied) from a sibling repo's stack-neutral 8-section reasoning
protocol. §3 ("decide where the real risk lives") is re-grounded on Frappe-
specific risk: `ignore_permissions=True` in submit/API paths, permission query
conditions, GL Entry/Payment Entry/invoice rounding, migration patch
idempotency, fixture export scope, `doc_events` committing mid-transaction,
`allow_guest=True`, anything under `src_override/`. Includes a closing 5-question
self-test.

### New canonical policy: `definition-of-done.md`

Formalizes the **vault-owns-intent / repo-owns-evidence** split with
deliberately different field names so the two cannot be confused: vault
`status:` (human-owned, in `wiki/<project>/tickets/<KEY>.md`) vs. repo
`build_state:` (agent-owned, in `docs/harness/LEDGER-*.md`). "Neither field is
derived from the other" is stated explicitly. Defines the journal
(`docs/harness/journal/<KEY>.md` — checkpoints + **pasted real gate output** +
a `## REVIEW` entry; "no REVIEW entry means the review did not happen means the
ticket is not done"), the 6-step Definition of Done, "what done is not", and
stop-and-ask triggers (new DocType, upstream app edits, non-idempotent
patches, permission/money-path changes, a wrong-looking gate command).

### The ledger: three files, not one

`LEDGER-proposed.md` (`proposed`/`gap` states — triage), `LEDGER-pending.md`
(`todo`/`claimed`/`in_progress`/`blocked`/`gates_green`/`reviewed` — **read on
every build session**, kept small on purpose), `LEDGER-done.md`
(`done`/`abandoned` — terminal, append-only). Split rationale: a single file
would put finished-work rows in the way of the dozen that matter on every
single ticket, a cost paid forever. `LEDGER-blocked.md` can be added later with
no migration if `blocked` rows crowd out pending.

- **Invariant**: a key appears in exactly one ledger file at a time; a
  `build_state` transition is a *move* (delete + append), never a copy. This is
  machine-checked: new `forge validate` rule parses every `LEDGER-*.md` under
  each target's `docs/harness/`, and fails if any ticket key appears in more
  than one file. Verified by deliberately duplicating a row across
  `LEDGER-pending.md` and `LEDGER-done.md` and confirming the check fires.
- **`LEDGER_PHASES`** constant in `render.py` drives both the render loop and a
  test (`test_every_build_state_belongs_to_exactly_one_ledger`) asserting no
  `build_state` value is claimed by two phases.
- **Render strategy**: new `ledger.md.j2` shared template, rendered with
  `artifact_kind="scaffold"`. Only `claude-code` (the harness-owning adapter)
  renders it — seven adapters seeding the same three tool-neutral paths would
  race.
- **Scaffold semantics added to `sync.py`**: any rendered artifact with
  `artifact_kind == "scaffold"` whose output path **already exists on disk** is
  added to the `protected` set before the swap — written once, then owned by
  whatever writes rows into it afterward. Verified live: seeded the ledger,
  hand-wrote a row via a real `forge sync` cycle, appended a ticket row
  manually, re-ran `forge sync`, confirmed the row survived.

### Jira seam (design only, not built)

Added to `ticketing-contract.md`: `jira_key: null` / `jira_synced_at: null`
frontmatter fields (never hand-populated — a fabricated key is worse than an
absent one, since a future sync would trust it), a full field-mapping table
(`id`→issue key as the **stable correlation key, never reused/renumbered** —
called out as the one decision here that is genuinely irreversible if gotten
wrong; `title`→Summary; `type`→Issue Type; `epic`→Parent; `priority`→Priority;
`story_points`→custom field; `labels`→Labels; `depends_on`/`blocks`→issue
links; `jira_project`→Project), and an explicit rule that **`status` never
syncs in either direction** — two human-owned fields (vault `status`, Jira
transitions) syncing bidirectionally has no non-arbitrary conflict-resolution
rule. No `forge jira` command, no client, no credentials were built — this is
deliberately just the seam.

### Review protocol gap closed

`canonical/policies/review-protocol.md` §2 acceptance criteria gained a new
row: **"Gates covering the change | run and observed to pass — real output
quoted, not inferred"**. Every other criterion in that table (findings count,
score, pairing sign-off, TASK BRIEF criteria) can be satisfied by *reading*;
none of them proves anything was actually *executed*. This closes that gap.

### Pointer to the operating manual

A document claiming to apply "before and above every other rule" that nothing
references would never get read. Added `operating-manual-pointer.md.j2`
(~700 chars) to all 7 root instruction templates, alongside the existing
harness and ticketing pointers.

## Files touched

New: `canonical/policies/operating-manual.md`, `definition-of-done.md`,
`adapters/_shared/templates/operating-manual.md.j2`, `ledger.md.j2`,
`operating-manual-pointer.md.j2`, `forge/tests/test_policies_and_ledger.py`

Modified: `canonical/policies/ticketing-contract.md` (new — extracted),
`adapters/_shared/templates/ticketing-and-memory.md.j2` (shrunk),
`canonical/policies/review-protocol.md`, `forge/src/forge/render.py`
(`LEDGER_PHASES`, ledger render loop, `policies`/`target`/`profile` context),
`forge/src/forge/sync.py` (scaffold protection), `commands/validate.py`
(ledger-key invariant), all 7 `adapters/*/adapter.yaml` (+
`operating_manual_doc` artifact entry), all 7 root instruction templates (+
manual pointer), `adapters/claude-code/adapter.yaml` (+ `ledger` artifact
entry), `forge.config.yaml` (`targets.self.renders` gains
`operating_manual_doc`), `forge/tests/test_loader.py`,
`forge/tests/test_adapters.py`, `forge/tests/test_targets.py` (updated
expected counts/sets for the new artifacts)

## Verification performed

- **Content-neutrality proof** for the ticketing move (described above,
  diff-based, not asserted)
- `forge score --path canonical/policies --fail-below 80` → lowest 100 across
  all 6 policy files including the 3 new ones
- New ledger-invariant test: duplicate a ticket key across two ledger files →
  `forge validate` reports it; single occurrence → clean
- New re-sync-survival test: render ledgers, stage, swap, hand-write a row,
  re-stage with the now-existing file in the `protected` set, swap again,
  assert the row is still present
- Char budget re-check after adding the operating-manual pointer: antigravity
  went from 7,185 → 7,867 chars (still well under 15,000; 7,133 headroom)
- `pytest forge/tests -q` → 312 passed, 2 skipped (+13 over PHASE-3's 299)
- `ruff check src/`, `mypy src/forge` (strict) → clean
- `forge validate --no-check-drift` → schema valid
- Real self-sync (`forge sync --target self --all`) re-run after enabling the
  new artifact groups for `self` → succeeded; `./scripts/harness/gates.sh
  quick` on the live repo still reports `RESULT: GREEN`

## Deviations from the original plan

None of substance for the policy/ledger content. The plan's exact three-file
split, `build_state` naming, and one-way non-`status` Jira push were all
followed as specified (these were themselves the result of an earlier explicit
user correction to the initial plan draft — see the plan-mode transcript for
that back-and-forth, not repeated here).

## Known follow-ups

- No `forge ledger sync --target ...` command exists yet to reconcile the
  vault and repo ledger copies — noted in the policy text as "a documented
  agent duty now; a command is the natural later addition," matching the Jira
  posture. Not scoped for this epic unless requested.
- The per-app ledger mirror (`apps/<app>/docs/harness/LEDGER-*.md`, gated on
  `managed_apps` + non-foreign + not-upstream) described in the original plan
  was **not implemented** in this ticket — only the target-root ledger
  (`<target_root>/docs/harness/LEDGER-*.md`) was built. If per-app mirroring is
  still wanted, it needs its own follow-up ticket (would reuse the same
  `artifact_kind="scaffold"` mechanism, gated the same way `per_app_claude_md`
  is gated on `managed_apps`).
