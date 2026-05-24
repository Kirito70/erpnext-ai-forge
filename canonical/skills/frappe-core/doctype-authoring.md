---
id: doctype-authoring
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Authoring a new DocType, child table, Custom DocType, Custom Field, or Property Setter in any custom app"
scope: [agent:architect, agent:backend-specialist]
foundational: true
domain: frappe-core
security_score: 100
supersedes: []
---

# DocType Authoring (Novizna v16)

The schema rules for new DocTypes, plus the decision matrix for "DocType vs Custom Field vs Property Setter" used across all 8 custom apps.

## When to Load
- Scaffolding a new DocType in `novizna_crm`, `noviznaerp_payroll`, etc.
- Deciding whether to add a Custom Field vs a fresh DocType
- Adding a child table or Link/Dynamic Link field
- Reviewing a DocType's permissions block

## Key Concepts

1. **DocType file layout** — `apps/<app>/<module>/doctype/<id>/<id>.{json,py}` + `test_<id>.py`.
2. **Custom DocType vs Custom Field vs Property Setter** — see decision matrix below.
3. **Child tables** — Table field of type `Table` linking to a DocType where `istable: 1`.
4. **Link vs Dynamic Link** — Link locks to one target DocType; Dynamic Link uses a sibling field to pick the target at runtime.
5. **Submittable / Amendable** — `is_submittable: 1` enables docstatus 0/1/2 flow; `allow_amend: 1` allows submit-then-amend.
6. **Permissions block** — declared in the DocType JSON; combines with Role Profiles and User Permissions at runtime.
7. **Naming series** — set via `autoname` field (`naming_series`, `format:CRM-LEAD-{####}`, `field:title`, etc.).

## Patterns

### Pattern: Decision matrix — DocType vs Custom Field vs Property Setter

| You need to... | Use |
|----------------|-----|
| Store a brand-new entity with its own list/form view | **DocType** (under your custom app) |
| Add 1–10 fields to an existing upstream DocType (e.g., `Sales Invoice`) | **Custom Field** (exported as fixture under the custom app — see `cargo_management` pattern) |
| Change a property of an upstream field (label, hidden, mandatory, default) | **Property Setter** (also fixture) |
| Replace upstream controller behavior | **`override_doctype_class`** in `hooks.py` — see [`frappe-core/hooks-and-events`](./hooks-and-events.md) |

Never edit upstream DocType JSON directly — that violates the `D-EDIT-UPSTREAM` guard ([`security-scoring.yaml`](../../policies/security-scoring.yaml)).

### Pattern: Scaffolding a new DocType — `crm_lead_industry`

**When:** Adding a domain entity to a custom app.

**Do:** Use [`doctype-scaffolder`](../../tools/doctype-scaffolder.yaml) or scaffold manually under the correct module:

```
apps/novizna_crm/novizna_crm/novizna_crm/doctype/crm_lead_industry/
    crm_lead_industry.json
    crm_lead_industry.py
    test_crm_lead_industry.py
    __init__.py
```

JSON skeleton (abbreviated):

```json
{
  "doctype": "DocType",
  "name": "CRM Lead Industry",
  "module": "Novizna Crm",
  "autoname": "field:industry_name",
  "track_changes": 1,
  "fields": [
    { "fieldname": "industry_name", "fieldtype": "Data", "label": "Industry Name", "reqd": 1, "unique": 1 },
    { "fieldname": "parent_industry", "fieldtype": "Link", "options": "CRM Lead Industry", "label": "Parent Industry" }
  ],
  "permissions": [
    { "role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1 },
    { "role": "Sales User", "read": 1 }
  ]
}
```

Controller (typed + docstring per CLAUDE.md):

```python
import frappe
from frappe import _
from frappe.model.document import Document

class CRMLeadIndustry(Document):
    """Industry taxonomy for CRM Lead segmentation."""

    def validate(self) -> None:
        """Disallow self-parenting to avoid hierarchy cycles."""
        if self.parent_industry == self.name:
            frappe.throw(_("An industry cannot be its own parent"))
```

**Don't:** Skip the `permissions` block — DocTypes without it default to System Manager only and confuse downstream role tests.

### Pattern: Child table

**When:** A DocType needs an embedded list (e.g., line items).

**Do:**
```json
// Parent field
{ "fieldname": "items", "fieldtype": "Table", "options": "Cargo Parcel Item", "label": "Items" }

// Child DocType (Cargo Parcel Item) — istable: 1, no separate list view
{
  "doctype": "DocType", "name": "Cargo Parcel Item",
  "istable": 1, "module": "Parcel Management",
  "fields": [
    { "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "in_list_view": 1 },
    { "fieldname": "qty", "fieldtype": "Float", "in_list_view": 1 }
  ]
}
```

Access in controller: `for item in self.items: ...`.

### Pattern: Link vs Dynamic Link

**Do (Link — type known at design time):**
```json
{ "fieldname": "lead", "fieldtype": "Link", "options": "CRM Lead" }
```

**Do (Dynamic Link — type chosen per row):**
```json
{ "fieldname": "reference_doctype", "fieldtype": "Link", "options": "DocType" },
{ "fieldname": "reference_name", "fieldtype": "Dynamic Link", "options": "reference_doctype" }
```

The Frappe `Comment`, `ToDo`, and `File` DocTypes use this pattern.

### Pattern: Naming series for CRM Lead extensions

**When:** New transactional DocType that needs human-readable IDs.

**Do:**
```json
"autoname": "naming_series:",
"fields": [
  {
    "fieldname": "naming_series", "fieldtype": "Select",
    "options": "CRM-IMP-LOG-.YYYY.-.####", "reqd": 1
  }
]
```

`crm_import_log` in `novizna_crm` uses a date-prefixed series.

### Pattern: Submittable workflow — `cash_variance_entry`

**When:** The doc needs ledger-like immutability after submit.

**Do:**
```json
{ "is_submittable": 1, "allow_amend": 1, "track_changes": 1 }
```

Then controllers implement `on_submit` / `on_cancel` / `on_update_after_submit` as needed.

## Common Pitfalls
- Setting `unique: 1` on a non-mandatory field — NULLs collide on MariaDB.
- Forgetting `in_list_view: 1` on child table fields — they won't show in the parent's table grid.
- Adding fields to a custom DocType during a hot patch without bumping `track_changes` first.
- Editing the DocType JSON in production without exporting fixtures — see [`frappe-core/migration-patches`](./migration-patches.md).
- Creating Custom Fields ad-hoc through the UI without re-exporting fixtures (loses on next migrate from another env).

## References
- [`frappe-core/conventions`](./conventions.md) — naming rules
- [`frappe-core/permissions-model`](./permissions-model.md) — for permission block design
- [`frappe-core/migration-patches`](./migration-patches.md) — when DocType changes need data backfill
- [`tools/doctype-scaffolder`](../../tools/doctype-scaffolder.yaml) — scaffolding tool
- [`discovery/data/doctype-index.json`](../../../discovery/data/doctype-index.json) — existing DocType inventory
