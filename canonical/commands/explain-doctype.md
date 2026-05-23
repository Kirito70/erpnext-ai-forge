---
id: explain-doctype
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, backend-specialist]
---

# /explain-doctype

Summarize a DocType's schema, hooks, permissions, and known callers.

## Usage

```
/explain-doctype <doctype-id>
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<doctype-id>` | yes | DocType ID (e.g. `crm_lead_industry`, `CRM Lead`) |

## Example

```
/explain-doctype crm_lead_industry
```

## Pipeline

1. **Architect:** look up the DocType in [`discovery/data/doctype-index.json`](../../discovery/data/doctype-index.json). If missing → trigger stale-reference re-scan (Decision 15).
2. **Backend Specialist:**
   - Read the JSON definition (fields, options, permissions block)
   - Read the controller (`validate`, lifecycle hooks defined)
   - Search [`hooks-index.json`](../../discovery/data/hooks-index.json) for `doc_events` entries referencing this DocType
   - Search for whitelist methods that read/write this DocType
   - Search frontend (novizna_crm or novizna_pos) for components that reference it
3. **Architect:** synthesize a structured doc

## Output

```markdown
## DocType: <id>

**App:** <app>
**Module:** <module>
**Submittable:** <yes/no>
**Naming:** <prefix or autoname rule>

### Fields
| Name | Type | Options | Required | Permlevel |
| ...  | ...  | ...     | ...      | ...       |

### Permissions
| Role | Read | Write | Create | Delete | Submit |
| ...  | ...  | ...   | ...    | ...    | ...    |

### Lifecycle Hooks
- `validate`: <summary from controller>
- `on_update`: ...

### Referenced By (hooks)
- `<app>.<module>.<method>` — fires on `<event>`

### Whitelist Endpoints Touching This DocType
- `<module>.<method>` — <read/write> — caller-set: <roles>

### Frontend References
- `<path>:<line>` — <component or composable>
```

## Tools Touched

- [`bench-console`](../tools/bench-console.yaml) — `frappe.get_meta(...)` inspection
- [`mariadb-query`](../tools/mariadb-query.yaml) — row count, recent activity
