---
id: skill-authoring-guide
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Authoring a new skill for the canonical layer, or deciding whether to split / merge existing skills"
scope: [agent:architect]
foundational: true
domain: meta
security_score: 100
supersedes: []
---

# Skill Authoring Guide

How to write a new skill that passes review and integrates cleanly with the canonical layer. Loaded by Architect whenever the skill catalogue is extended.

## When to Load
- A new skill is being added under `canonical/skills/<domain>/`
- An existing skill has grown past 500 lines (governance cap) and needs splitting
- A skill is being deprecated or merged

## Frontmatter Schema (use exactly)

```yaml
---
id: <kebab-case-slug>            # MUST match the filename (without .md)
kind: skill
version: 1.0.0
status: stable                   # stable | draft | deprecated
owners: [m.tayyab9736@gmail.com]
last_reviewed: <YYYY-MM-DD>
trigger: "<the condition that causes a model to load this skill — 1 sentence>"
scope: [agent:<id>, agent:<id>]  # which agents may load this; use [global] only for cross-cutting
foundational: true|false         # F = always-loaded for in-scope agents; M = on-demand
domain: <frappe-core|frontend|data|reporting|integrations|security|testing|debugging|erpnext-domains|meta>
security_score: 100              # initial; security-reviewer recomputes
supersedes: []                   # IDs of skills this replaces, for the deprecation cycle
---
```

### Field meaning

- **`id`** — must match the filename. Renames must update both.
- **`trigger`** — one sentence answering "when does the model load this?" Avoid AND/OR conjunctions; prefer a single concrete situation.
- **`scope`** — list of `agent:<id>` entries from `canonical/agents/`. Use `[global]` only if every agent benefits.
- **`foundational`** — `true` means the skill is always loaded when the agent is invoked. `false` means model-invoked on demand. Foundational skills cost context budget; mark sparingly.
- **`domain`** — exactly one of the 10 directory names under `canonical/skills/`.

## Body Structure

```markdown
# <Skill Title>

<1–2 sentence purpose. State who loads it and when.>

## When to Load
- <Concrete trigger 1>
- <Concrete trigger 2>

## Key Concepts
<3–7 numbered one-line concepts>

## Patterns

### Pattern: <name>
**When:** <context>
**Do:**
```python
# bench-grounded example using REAL app paths/DocTypes from discovery
```
**Don't:**
```python
# anti-pattern, with AP-id link if applicable
```

### Pattern: <name>
... (3–6 patterns per skill)

## Common Pitfalls
- <Pitfall 1 with link to discovery AP-id if standing finding>
- <Pitfall 2>

## References
- <link to 2+ other skills/policies/tools/discovery files via relative paths>
```

## Length Budget

| Target | Max |
|--------|-----|
| 80–200 lines | 500 (governance cap) |

If a skill exceeds 500 lines, split along the patterns it carries. For example: `frappe-core/whitelist-api-patterns.md` covers auth, validation, pagination — if it ever grows beyond budget, split into `whitelist-auth-patterns.md` and `whitelist-pagination-patterns.md`.

## Quality Bar (must satisfy all)

1. **Every code example references a real custom app from this bench** — not `myapp`, not `example_app`. Pick from: `novizna_crm`, `novizna_core`, `novizna_pos`, `invoice_ninja_integration`, `noviznaerp_payroll`, `cargo_management`, `changemakers`, `erpnext_location`.
2. **Every `Don't` example links to a discovery AP-id** when a standing finding exists in [`anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json).
3. **At least 2 cross-references** in the References section — to other skills, policies, tools, or discovery JSON. Use relative paths.
4. **Voice matches existing agent specs** — direct, second-person where appropriate, no fluff. Read `canonical/agents/architect.md` for the cadence.
5. **A reader unfamiliar with this bench can identify which custom app each example came from** (Phase 1b exit criterion in v0.2 §10).

## F vs M Classification

| Bucket | Cost | When to use |
|--------|------|-------------|
| **Foundational (F)** | Always loaded for in-scope agents | The skill is referenced in 50%+ of that agent's tasks (e.g., `security/review-checklist` for Security Reviewer) |
| **Model-invoked (M)** | Loaded on demand | Domain-specific skills, vendor-specific connectors, less-common patterns |

Bias toward M. Foundational skills consume context budget on every task.

## Trigger Phrasing Guide

Good triggers are single-situation, present-tense, agent-readable:

- ✅ "Authoring or modifying a Script Report in any custom app"
- ✅ "Any code that touches site_config.json, frappe.conf, encryption_key, or any vendor secret"
- ❌ "Useful for reports and other things" (too vague)
- ❌ "When you might need SQL knowledge" (subjunctive — agent can't act on it)

## Cross-Referencing Pattern

Always link via relative path from the skill's location:

```markdown
- [`data/sql-best-practices`](../data/sql-best-practices.md)
- [`policies/security-scoring`](../../policies/security-scoring.yaml)
- [`discovery/data/anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json)
```

Verify links resolve before committing. `forge validate` checks this in Phase 2+.

## Deprecation Protocol

When a skill is superseded (per [`policies/governance`](../../policies/governance.md)):

1. New skill sets `supersedes: [<old-id>]`
2. Old skill sets `status: deprecated` and a deprecation note at the top of the body
3. Old skill moves to `canonical/_deprecated/skills/<domain>/<old-slug>.md`
4. Retained for one MINOR cycle, then removed
5. `CHANGELOG.md` records Deprecated and (one minor later) Removed

## Calibration Cadence

Per [`policies/governance`](../../policies/governance.md), after every 10 new skills the Architect runs `forge score canonical/skills/` and inspects scores for clusters in unexpected bands. If too lenient or too punitive, deductions in [`security-scoring.yaml`](../../policies/security-scoring.yaml) get tuned.

## Example Pre-Authoring Checklist

Before opening the editor:

- [ ] Confirmed the skill doesn't duplicate an existing one (`ls canonical/skills/*/`)
- [ ] Picked the right domain directory (only 10 are valid)
- [ ] Identified the scope (which agents)
- [ ] Drafted the trigger sentence
- [ ] Listed the 3–6 patterns the skill will carry
- [ ] Identified the discovery JSON files to cite
- [ ] Identified which standing AP-ids the `Don't` blocks will reference

## Common Pitfalls
- Generic Frappe content with no bench grounding — fails Phase 1b exit criterion.
- `Don't` blocks without AP-id linkage when a standing finding exists.
- Frontmatter `scope` referencing an agent ID that doesn't exist.
- Skill set `foundational: true` but only relevant to one rare task type.
- File path doesn't match `id` in frontmatter — sync tools mis-route.
- Skill exceeds 500 lines without a split plan.
- "Verify this URL exists" sections that cite hallucinated docs URLs — verify or omit.

## References
- [`policies/governance`](../../policies/governance.md) — versioning, deprecation, calibration
- [`policies/security-scoring`](../../policies/security-scoring.yaml) — initial scoring
- [`policies/review-protocol`](../../policies/review-protocol.md) — review output format
- [`discovery/INVENTORY.md`](../../../discovery/INVENTORY.md) — bench facts to draw from
- [`canonical/agents/architect.md`](../../agents/architect.md) — voice and structure reference
