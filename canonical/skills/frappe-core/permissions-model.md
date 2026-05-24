---
id: permissions-model
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Designing DocType permissions, calling has_permission, reviewing ignore_permissions usage, or planning Role Profiles / User Permissions"
scope: [agent:architect, agent:backend-specialist, agent:security-reviewer, agent:qa-test-engineer]
foundational: false
domain: frappe-core
security_score: 100
supersedes: []
---

# Frappe Permissions Model

How role-based perms, permlevels, User Permissions, Document Share, and Role Profiles compose at runtime — and which checks belong in your code.

## When to Load
- Drafting the permissions block in a new DocType
- Adding `frappe.has_permission(...)` calls in a whitelist endpoint
- Reviewing an `ignore_permissions=True` occurrence (see [AP-003](../../../discovery/data/anti-pattern-findings.json) — 99 known)
- Designing a multi-role workflow (e.g., Salary Slip approval)

## Key Concepts

1. **Role-based perms** — declared in DocType JSON; the base layer.
2. **`permlevel`** — field-level perms. `permlevel=0` is the document; `permlevel=1+` are field clusters with their own role rules.
3. **User Permissions** — per-user filters scoped to a Link DocType (e.g., "User X may only see Customers in Region Y").
4. **Document Share** — share a specific doc with a specific user/role at read/write/share level. Overrides role perms upward only.
5. **Role Profiles** — bundle multiple Roles for org-wide assignment.
6. **`frappe.has_permission(doctype, ptype, doc=None, user=None, throw=False)`** — the canonical runtime check.
7. **`ignore_permissions=True`** — escape hatch for `insert`, `save`, `delete`, `get_doc`. Requires justifying comment.
8. **ERPNext roles to know** — `System Manager`, `Sales User`, `Sales Manager`, `Accounts User`, `Accounts Manager`, `HR User`, `HR Manager`, `Stock User`, `Item Manager`, `POS User`, `POS Manager`.

## Patterns

### Pattern: DocType permissions block — graduated access

**When:** Designing perms for a new transactional DocType (e.g., `cash_variance_entry`).

**Do:**
```json
"permissions": [
  { "role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1 },
  { "role": "POS Manager",    "read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1 },
  { "role": "POS User",       "read": 1, "write": 1, "create": 1, "if_owner": 1 }
]
```

`if_owner: 1` restricts non-Manager users to docs they created — a common POS pattern.

**Don't:**
```json
[{ "role": "All", "read": 1, "write": 1, "create": 1, "delete": 1 }]
```
The `All` role plus full perms exposes every authenticated user. Security Reviewer flags as MEDIUM.

### Pattern: `has_permission` at the whitelist boundary

**When:** Endpoint reads or mutates a specific doc.

**Do:**
```python
@frappe.whitelist()
def submit_invoice(invoice_id: str) -> dict:
    """Submit a POS Invoice if the caller has submit perm."""
    frappe.has_permission("POS Invoice", "submit", invoice_id, throw=True)
    doc = frappe.get_doc("POS Invoice", invoice_id)
    doc.submit()
    return {"name": doc.name, "docstatus": doc.docstatus}
```

This mirrors the `novizna_pos.api.submit_invoice` endpoint (one of the 33 in `novizna_pos`).

**Don't:** Rely on `get_doc(...).save()` raising a `PermissionError` later — by then the controller may have side effects already executed. Check up-front.

### Pattern: Justified `ignore_permissions=True`

**When:** Truly needed (scheduled tasks, post-install patches, system-generated logs).

**Do:**
```python
def on_invoice_submit(doc, method):
    """Log the submit to Parcel Log (system action — current user may not own Parcel Log)."""
    frappe.get_doc({
        "doctype": "Parcel Log",
        "invoice": doc.name,
    }).insert(ignore_permissions=True)  # system log; caller has submit perm on the SI but not Parcel Log
```

The 1-line justification before or beside the call is what Security Reviewer looks for. Without it, the AP-003 deduction applies.

**Don't:**
```python
# (no comment)
new_doc.insert(ignore_permissions=True)
```
Phase 2 `forge score` flags any `ignore_permissions=True` without a justifying comment within 3 lines.

### Pattern: User Permissions for tenant isolation

**When:** A user should only see Customers in their Region.

**Do (configured via UI or fixture, not code):**
```json
// User Permission row
{
  "user": "regional.manager@example.com",
  "allow": "Territory",
  "for_value": "PAK-North",
  "apply_to_all_doctypes": 0,
  "applicable_for": "Customer"
}
```

This causes `frappe.get_list("Customer", ...)` for that user to be silently filtered to Customers where `territory = PAK-North`.

**Don't:** Hand-roll the filter in every list query — User Permissions does it at the ORM layer, including in Reports.

### Pattern: Field-level perm with `permlevel`

**When:** Manager can see `internal_notes`; user cannot.

**Do (in DocType JSON):**
```json
{
  "fieldname": "internal_notes", "fieldtype": "Small Text",
  "label": "Internal Notes", "permlevel": 1
}
```

```json
"permissions": [
  { "role": "Sales Manager", "read": 1, "write": 1, "permlevel": 1 },
  { "role": "Sales User",    "read": 1, "write": 1, "permlevel": 0 }
]
```

`Sales User` can read/write the doc but the `internal_notes` field is hidden in both API and UI responses.

## Permissions Composition (order of resolution)

When Frappe decides "can user X do ptype on doc Y?":

1. Is user `Administrator`? → yes
2. Does any Role-based perm grant ptype at the matching permlevel? → if no, deny
3. Do User Permissions filter Y out for X? → if yes, deny
4. Is there a Document Share for (X, Y) that grants ptype? → if yes, allow (overrides #3 in the share's favor)
5. Does `if_owner` restrict to docs created by X? → enforce

## Common Pitfalls
- Defining a `permlevel: 1` field but no `permlevel: 1` permission row — nobody can read it (not even System Manager — they have to add the row).
- Using `frappe.get_all` in a user-triggered handler — bypasses permissions and User Permissions filtering. Use `frappe.get_list` instead.
- `frappe.set_user("Administrator")` inside a handler to "work around" permission failures — that's a permission bypass; use `ignore_permissions=True` with justification at the specific call instead.
- Granting `submit` without `write` — UI shows submit button but save first fails.
- Forgetting that `frappe.has_permission` with `doc=None` checks the DocType-level perm, not a specific row.

## References
- [`frappe-core/doctype-authoring`](./doctype-authoring.md) — for the JSON permissions block
- [`frappe-core/whitelist-api-patterns`](./whitelist-api-patterns.md) — for the boundary-check pattern
- [`security/review-checklist`](../security/review-checklist.md) — for the AP-003 review walkthrough
- [`discovery/data/anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json) — AP-003 (99 known `ignore_permissions=True`)
