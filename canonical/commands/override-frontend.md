---
id: override-frontend
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, frontend-frappe-ui-specialist]
---

# /override-frontend

Create a correctly-pathed `src_override/` pair for an upstream CRM file.

## Usage

```
/override-frontend <upstream-path>
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<upstream-path>` | yes | Path under `apps/crm/frontend/src/` (relative or absolute) |

## Example

```
/override-frontend apps/crm/frontend/src/components/Leads/LeadsListHeader.vue
```

## Pipeline

1. **Architect:** validate upstream file exists
2. **Frontend Specialist (Frappe-UI):**
   - Copy upstream content to `apps/novizna_crm/frontend/src_override/<same-relative-path>`
   - Add `// AUTO-COPIED FROM apps/crm/frontend/src/... — modify below this line` header (informational; not strictly required by the build)
   - Open the new file for the developer to edit
3. **Frontend Specialist:** run [`override-checker`](../tools/override-checker.yaml) to verify the pair
4. **Architect:** synthesize + remind developer that net-new helper components should live in `src/`, not `src_override/`

## Notes

- Per [Decision 16](../../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md): `src_override/` is strictly one-for-one with `apps/crm/frontend/src/`
- The 10 currently overridden files are in [`override-map.json`](../../discovery/data/override-map.json) — this command will refuse to override the same file twice
- If the upstream file is renamed in a future CRM release, `override-checker` will surface it

## Tools Touched

- [`override-checker`](../tools/override-checker.yaml)
- [`diff-upstream`](./diff-upstream.md) (sibling command — useful for understanding what's already different)
