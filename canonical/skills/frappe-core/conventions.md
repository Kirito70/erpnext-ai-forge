---
id: conventions
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Any backend or frontend work that touches DocType names, app modules, field IDs, or Frappe helper usage on the Novizna v16 bench"
scope: [agent:architect, agent:backend-specialist, agent:frontend-frappe-ui-specialist, agent:qa-test-engineer]
foundational: true
domain: frappe-core
security_score: 100
supersedes: []
---

# Frappe Conventions (Novizna v16)

Canonical naming, module layout, and helper-usage rules for this bench. Loaded for every backend task; loaded by Architect at pre-flight so brief drafts use the right vocabulary.

## When to Load
- Drafting a DocType ID, app name, or module path
- Choosing between `frappe.db.get_value` / `get_list` / `get_all`
- Using `frappe.get_doc`, `new_doc`, or `delete_doc` semantics
- Reviewing DocType naming for the AP-006 drift finding

## Key Concepts

1. **DocType ID vs label** — ID is the canonical key (e.g., `crm_lead_industry`); label is human-facing.
2. **App prefix policy** — Optional but consistent per-app. Mixed prefixing is a smell (see AP-006).
3. **Standard fields** — Every DocType inherits `name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`, `idx`. Never redefine.
4. **`get_doc` vs `new_doc`** — `new_doc` returns an unsaved skeleton; `get_doc` loads existing (by name) or builds from a dict.
5. **`get_value` vs `get_list` vs `get_all`** — single field/row vs filtered set vs unfiltered (no permission check). `get_all` skips perms by default.
6. **`frappe.utils`** — Search here before writing your own date/string/number helper.
7. **`_()` (translation)** — Wrap every user-facing string in `_("...")`; throws and msgprints must be translated.

## Patterns

### Pattern: DocType naming per app

**When:** Scaffolding a new DocType in any custom app.

**Do:** Use the per-app convention from [`discovery/data/doctype-index.json`](../../../discovery/data/doctype-index.json):

| App | Convention | Example |
|-----|------------|---------|
| `novizna_crm` | `crm_<noun>` | `crm_import_log`, `crm_lead_industry` |
| `invoice_ninja_integration` | `invoice_ninja_<noun>` | `invoice_ninja_settings`, `invoice_ninja_sync_logs` |
| `noviznaerp_payroll` | bare snake_case nouns | `eobi`, `attendance_tool`, `biometric_device` |
| `novizna_pos` | mixed (see AP-006) — prefer `noviznapos_<noun>` for new DocTypes | `noviznapos_settings` |
| `cargo_management` | bare snake_case nouns | `parcel`, `branch_warehouse` |

**Don't:** Invent a fresh prefix in an app that already has a dominant pattern — see [AP-006](../../../discovery/data/anti-pattern-findings.json) (naming drift). If the app has no convention, propose one to the developer before adding a second style.

### Pattern: Choosing the right read helper

**When:** Reading one or more rows from a DocType table.

**Do:**
```python
# Single scalar — fastest
status = frappe.db.get_value("CRM Lead", lead_name, "status")

# Multiple fields from one doc
row = frappe.db.get_value(
    "CRM Lead", lead_name, ["status", "lead_owner", "email"], as_dict=True
)

# Filtered list, permission-checked (use this in user-triggered code)
leads = frappe.get_list(
    "CRM Lead",
    filters={"status": "Open"},
    fields=["name", "lead_owner"],
    limit=50,
)

# Filtered list, NO permission check (only inside scheduler/patch context)
all_leads = frappe.get_all(
    "CRM Lead", filters={"status": "Open"}, fields=["name"]
)
```

**Don't:**
```python
# N+1 — one query per loop iteration
for name in lead_names:
    status = frappe.db.get_value("CRM Lead", name, "status")  # one round trip each
```
Fetch in bulk with `get_all(..., fields=[...])` instead.

### Pattern: get_doc / new_doc / delete_doc lifecycles

**When:** Creating, mutating, or removing a Frappe document.

**Do:**
```python
# New record — explicit dict insert; no name yet
lead = frappe.get_doc({
    "doctype": "CRM Lead",
    "first_name": "Acme",
    "lead_owner": frappe.session.user,
}).insert()  # respects permissions by default

# Load existing, mutate, save
lead = frappe.get_doc("CRM Lead", lead_name)
lead.status = "Qualified"
lead.save()

# Delete with permission check
frappe.delete_doc("CRM Lead", lead_name)
```

**Don't:** Use `frappe.db.set_value` to mutate a doc that has `validate` / `on_update` hooks — bypasses controller logic.

### Pattern: Use `frappe.utils` before writing your own helper

**When:** Need date math, money formatting, string slugification, etc.

**Do:**
```python
from frappe.utils import (
    nowdate, add_days, getdate,          # date helpers
    flt, cint, cstr,                     # safe numeric/string casts
    money_in_words, fmt_money,           # currency
    cstr, scrub, slug,                   # string helpers
)
total = flt(invoice.grand_total, 2)
```

**Don't:** Reimplement `flt` with `float(...)` — it doesn't handle `None`/`""` the same way and tests will diverge from upstream behavior. See the CLAUDE.md DRY rule.

### Pattern: Translate every user-facing string

**Do:** `frappe.throw(_("Score must be between 0 and 100"))`

**Don't:** `frappe.throw("Score must be between 0 and 100")` — won't be translatable; QA flags as a LOW finding.

## Common Pitfalls
- Calling `get_all` in a user-triggered code path (skips perms — see [AP-003](../../../discovery/data/anti-pattern-findings.json) lineage).
- Mutating a doc with `frappe.db.set_value` and expecting `on_update` to fire — it won't.
- Using `frappe.local.conf` or `frappe.conf` in logs — see [`security/secrets-handling`](../security/secrets-handling.md).
- Mixing snake_case and CamelCase DocType IDs in the same app — flags AP-006.

## References
- [`frappe-core/doctype-authoring`](./doctype-authoring.md) — DocType JSON authoring
- [`frappe-core/hooks-and-events`](./hooks-and-events.md) — controller lifecycle
- [`data/sql-best-practices`](../data/sql-best-practices.md) — when reading via raw SQL
- [`discovery/data/doctype-index.json`](../../../discovery/data/doctype-index.json) — current per-app naming
- [`discovery/data/anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json) — AP-006 lineage
