---
id: pos
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Work on novizna_pos — POS Invoice, POS Profile, POS Opening/Closing Entry, or any of the 33 novizna_pos whitelist endpoints"
scope: [agent:architect, agent:backend-specialist, agent:frontend-quasar-specialist, agent:qa-test-engineer]
foundational: true
domain: erpnext-domains
security_score: 100
supersedes: []
---

# POS Domain (novizna_pos)

The POS cycle on this bench. Combines upstream ERPNext POS DocTypes with `novizna_pos`'s 3 custom DocTypes and 33 whitelist endpoints — frontend is the Quasar PWA (see [`frontend/vue3-quasar-patterns`](../frontend/vue3-quasar-patterns.md)). Loaded for every POS-domain task on either backend or frontend.

## When to Load
- Backend changes in `apps/novizna_pos/novizna_pos/api.py` or `invoice.py`
- Frontend changes in `apps/novizna_pos/novizna-pos-ui/`
- Authoring tests for POS critical flows
- Designing CSRF posture for new POS endpoints

## Key DocTypes — Upstream

| DocType | Purpose |
|---------|---------|
| `POS Invoice` | Cash/card sale; lighter than Sales Invoice; consolidates nightly |
| `POS Profile` | Per-terminal config (warehouse, payment methods, default customer) |
| `POS Profile User` | User ↔ Profile binding |
| `POS Opening Entry` | Open-of-shift cash declaration |
| `POS Closing Entry` | Close-of-shift cash reconciliation |
| `POS Settings` | Global POS prefs |

## Key DocTypes — `novizna_pos` (custom, 3)

Per [`doctype-index.json`](../../../discovery/data/doctype-index.json):

| DocType | Purpose |
|---------|---------|
| `Branch Warehouse` | Maps a Branch to its operating Warehouse(s) |
| `Cash Variance Entry` | Records cash discrepancies at shift close (submittable) |
| `Noviznapos Settings` | App-specific config singleton |

## Auth Model — Decision 17 (CRITICAL)

The Quasar POS authenticates against Frappe via:
- **Frappe session cookie** (HttpOnly; set on login; sent via `withCredentials: true`)
- **`X-Frappe-CSRF-Token`** header on every non-GET request

There is **no JWT**. The bench has `ignore_csrf=true` set site-wide (AP-005) — that is a known finding that POS-side code does **not** depend on. POS clients still send the CSRF token. New POS code that "works around" CSRF being off is a blocker.

See [`frontend/vue3-quasar-patterns`](../frontend/vue3-quasar-patterns.md) for the Axios boot file that wires this up.

## Whitelist API Surface

Per [`api-surface.json`](../../../discovery/data/api-surface.json), the 33 `novizna_pos` whitelist methods live in:

- `novizna_pos/novizna_pos/api.py`
- `novizna_pos/novizna_pos/invoice.py`

Sample methods (5 of 33):
- `get_users_for_pos_profile` — list users bound to a POS Profile
- `save_invoice` — partial-save (draft) POS Invoice
- `submit_invoice` — final submit + GL post
- `get_pos_closing_entry` — read existing closing for the shift
- `save_pos_closing_entry` — persist closing variance

One of these endpoints (`api.py:82`) is in the AP-002 guest-endpoint finding. Phase 2 audit will verify whether `allow_guest=True` is intentional.

## Patterns

### Pattern: Save-and-submit POS Invoice (backend)

**Do:**
```python
import frappe
from frappe import _

@frappe.whitelist(methods=["POST"])
def save_invoice(payload: dict) -> dict:
    """Save (or update) a POS Invoice draft."""
    frappe.has_permission("POS Invoice", "create", throw=True)
    doc = frappe.get_doc({"doctype": "POS Invoice", **payload})
    doc.insert()
    return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist(methods=["POST"])
def submit_invoice(invoice_id: str) -> dict:
    """Submit a saved POS Invoice."""
    frappe.has_permission("POS Invoice", "submit", invoice_id, throw=True)
    doc = frappe.get_doc("POS Invoice", invoice_id)
    doc.submit()
    return {"name": doc.name, "docstatus": doc.docstatus, "grand_total": doc.grand_total}
```

Both verbs pinned to POST (per [`frappe-core/whitelist-api-patterns`](../frappe-core/whitelist-api-patterns.md)).

### Pattern: Cash Variance Entry on shift close

**When:** Cashier closes shift; counted cash differs from expected.

**Do:**
```python
@frappe.whitelist(methods=["POST"])
def record_cash_variance(branch: str, variance_amount: float, reason: str) -> dict:
    """Create + submit a Cash Variance Entry."""
    frappe.has_permission("Cash Variance Entry", "create", throw=True)
    doc = frappe.get_doc({
        "doctype": "Cash Variance Entry",
        "branch": branch, "variance_amount": variance_amount,
        "reason": reason, "posting_date": frappe.utils.nowdate(),
    })
    doc.insert()
    doc.submit()
    return {"name": doc.name}
```

`Cash Variance Entry` is submittable (`docstatus 0/1/2`); amend with `allow_amend: 1`.

### Pattern: Branch → Warehouse resolution

**When:** Need the operating warehouse for the current Branch.

**Do:**
```python
def warehouse_for_branch(branch: str) -> str:
    """Return the primary Warehouse mapped to this Branch."""
    return frappe.db.get_value("Branch Warehouse",
                               {"branch": branch, "is_primary": 1}, "warehouse")
```

### Pattern: POS Profile context for a user

**Do:**
```python
@frappe.whitelist()
def get_pos_profile_for_user() -> dict:
    """Return the active POS Profile for the calling user."""
    profile_name = frappe.db.get_value(
        "POS Profile User", {"user": frappe.session.user}, "parent"
    )
    if not profile_name:
        frappe.throw(_("No POS Profile assigned"))
    return frappe.get_doc("POS Profile", profile_name).as_dict()
```

### Pattern: Offline-safe POS Invoice save (frontend)

The Quasar offline queue enqueues `save_invoice` payloads when the network is down and flushes on reconnect with exponential backoff. See [`frontend/vue3-quasar-patterns`](../frontend/vue3-quasar-patterns.md) and [`integrations/queueing-retry-backoff`](../integrations/queueing-retry-backoff.md).

### Pattern: Receipt print format

POS receipts use a narrow (e.g., 80mm) Print Format. See [`reporting/print-format-authoring`](../reporting/print-format-authoring.md) for the POS-specific receipt example — currency uses `doc.currency` from the Invoice, not a hard-coded symbol.

## Permissions

| Role | Scope |
|------|-------|
| `POS User` | Create/read/submit own POS Invoices; create Cash Variance Entry |
| `POS Manager` | All POS Invoices in their branch; submit/cancel; modify POS Profile |
| `Accounts User` | Read POS Invoice; reconcile via Payment Entry |
| `System Manager` | Everything |

`if_owner: 1` on POS Invoice for POS User is the common pattern — see [`frappe-core/permissions-model`](../frappe-core/permissions-model.md).

## Common Pitfalls
- Forgetting `X-Frappe-CSRF-Token` on a new POST endpoint — Quasar tests catch this; production users hit 403.
- POS Invoice without a POS Profile — falls back to global defaults; usually wrong warehouse.
- Submitting POS Invoice from a worker context where `frappe.session.user = "Administrator"` — bypasses User Permissions; data leaks across branches.
- Print format with hard-coded currency symbol — breaks for multi-currency operations.
- `allow_guest=True` on `novizna_pos/api.py:82` (current AP-002 lineage) — verify intent before adding more.
- Storing card / payment tokens in localStorage — never. The session cookie is `HttpOnly` for a reason.
- Mutating cart state across tabs without a sync mechanism — Pinia store + BroadcastChannel is one option.

## References
- [`frontend/vue3-quasar-patterns`](../frontend/vue3-quasar-patterns.md) — frontend counterpart
- [`erpnext-domains/sales`](./sales.md) — for SI / Customer machinery POS leans on
- [`erpnext-domains/accounting`](./accounting.md) — POS Invoice posts to GL on submit
- [`integrations/queueing-retry-backoff`](../integrations/queueing-retry-backoff.md) — for offline queue retry shape
- [`security/review-checklist`](../security/review-checklist.md) — AP-002 and CSRF posture
- [`discovery/data/doctype-index.json`](../../../discovery/data/doctype-index.json) — `novizna_pos` DocTypes
- [`discovery/data/api-surface.json`](../../../discovery/data/api-surface.json) — 33 whitelist methods
