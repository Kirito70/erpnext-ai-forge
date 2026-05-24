---
id: sales
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Work touching the Sales cycle DocTypes — Quotation, Sales Order, Delivery Note, Sales Invoice, Customer, or the CRM ↔ ERPNext bridge"
scope: [agent:architect, agent:backend-specialist, agent:qa-test-engineer]
foundational: false
domain: erpnext-domains
security_score: 100
supersedes: []
---

# ERPNext Sales Domain

The Quotation → Sales Order → Delivery Note → Sales Invoice cycle, plus Customer/Address/Contact and the **novizna_crm ↔ ERPNext sync** (`novizna_crm.api.erpnext_sync`). Loaded when work touches any of these DocTypes.

## When to Load
- A change to a `crm_*` flow that pushes to ERPNext (sync)
- Customizing the Quote → SO → DN → SI cycle
- Authoring a Custom Field on `Sales Invoice` / `Sales Order`
- Reviewing or extending `novizna_crm/api/erpnext_sync.py`

## Key DocTypes

| DocType | Owner App | Notes |
|---------|-----------|-------|
| `CRM Lead` | upstream `crm` | Pre-sales |
| `CRM Deal` | upstream `crm` | Mid-sales; convertible to Quotation |
| `Quotation` | `erpnext` | First financial doc; not yet committed |
| `Sales Order` | `erpnext` | Customer commitment; reserves stock if configured |
| `Delivery Note` | `erpnext` | Physical delivery; updates Stock Ledger |
| `Sales Invoice` | `erpnext` | Books revenue + receivable; updates GL |
| `Customer`, `Address`, `Contact` | `erpnext` / `frappe` | Master data |

## The Sales Cycle (default)

```
CRM Lead → CRM Deal → Quotation → Sales Order → Delivery Note → Sales Invoice
                          ↘ (or)                                       ↗
                            Sales Invoice (direct, without DN)
```

Each step has a `make_*` helper (e.g., `make_sales_invoice(source_name)`) that pre-populates from the source doc.

## novizna_crm → ERPNext Bridge

Per [`api-surface.json`](../../../discovery/data/api-surface.json), `novizna_crm/api/erpnext_sync.py` is the canonical bridge. Sample whitelist methods include:

- `get_erpnext_customers` — list ERPNext customers
- `get_erpnext_quotations` — list quotations
- `sync_erpnext_customers` — push CRM Deal-derived customers into ERPNext
- `import_customers_as_leads` — pull ERPNext customers back as CRM Leads

When extending this bridge, follow the orchestration-vs-connector split per [Decision 18](../../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md): vendor-pure code in `connectors/`; orchestration in `api/`. (ERPNext is internal, but the same separation applies — `erpnext_sync.py` is orchestration, not a connector.)

## Patterns

### Pattern: Convert a CRM Deal to a Quotation

**When:** Sales rep clicks "Generate Quote" on a CRM Deal.

**Do:**
```python
import frappe
from frappe import _

@frappe.whitelist()
def make_quotation_from_deal(deal_name: str) -> dict:
    """Create a Quotation from a CRM Deal."""
    frappe.has_permission("CRM Deal", "read", deal_name, throw=True)
    deal = frappe.get_doc("CRM Deal", deal_name)

    quote = frappe.new_doc("Quotation")
    quote.party_name = _ensure_customer(deal)  # finds/creates Customer for the deal
    quote.transaction_date = frappe.utils.nowdate()
    for item in (deal.items or []):
        quote.append("items", {
            "item_code": item.item_code,
            "qty": item.qty,
            "rate": item.rate,
        })
    quote.insert()
    return {"quotation": quote.name}
```

### Pattern: Custom Field on Sales Invoice via fixture

**When:** `cargo_management` needs a `customs_code` field on Sales Invoice.

**Do:**
- Don't edit `apps/erpnext/erpnext/accounts/doctype/sales_invoice/sales_invoice.json` (CRITICAL — D-EDIT-UPSTREAM).
- Add a Custom Field via the UI or `bench --site ... execute frappe.custom.doctype.custom_field.custom_field.create_custom_field` then export the fixture:

```python
# apps/cargo_management/cargo_management/hooks.py
fixtures = [
    {"dt": "Custom Field", "filters": [
        ["name", "in", ["Sales Invoice-customs_code"]]
    ]}
]
```

After every fixture-touching change, run [`fixture-differ`](../../tools/fixture-differ.yaml) to confirm only intended rows landed. See [`frappe-core/doctype-authoring`](../frappe-core/doctype-authoring.md) decision matrix.

### Pattern: Submitting Sales Invoice posts GL entries

**When:** Need to react after the GL is posted (e.g., notify customer).

**Do (in hooks.py):**
```python
doc_events = {
    "Sales Invoice": {
        "on_submit": "cargo_management.parcel_management.events.notify_customer_on_si_submit",
    }
}
```

The handler runs after `make_gl_entries` — the GL is already in the same transaction.

**Don't:** `frappe.db.commit()` inside the handler — see [AP-004](../../../discovery/data/anti-pattern-findings.json).

### Pattern: Multi-currency Customer in Quotation

**Do:** Pull the Customer's `default_currency` and let ERPNext's price list / exchange rate machinery handle conversion. Don't hard-code currency or convert manually.

```python
customer = frappe.get_doc("Customer", quote.party_name)
quote.currency = customer.default_currency or frappe.defaults.get_global_default("currency")
```

### Pattern: Standard sales reports to mirror

When authoring CRM-side reports, mirror ERPNext's:
- `Sales Register` (Sales Invoice list)
- `Item-wise Sales Register`
- `Sales Order Analysis`

Use the same column shapes for visual consistency.

## Permissions

| Role | Typical scope |
|------|---------------|
| `Sales User` | Create/read Quotation, SO, DN, SI for their owned docs |
| `Sales Manager` | All-user scope; cancel; amend |
| `Accounts User` | Read SI for receivable workflows |
| `Accounts Manager` | Cancel SI; modify accounting dimensions |
| `Stock User` | Read DN; create Stock Entry against it |
| `System Manager` | Everything |

User Permissions on `Territory`, `Company`, or `Customer Group` are the common multi-tenant slicers — see [`frappe-core/permissions-model`](../frappe-core/permissions-model.md).

## Common Pitfalls
- Calling `make_sales_invoice(source_name)` without checking docstatus — only works on submitted source docs.
- Adding items to Quotation without a Price List context — rates may be 0 or wrong-currency.
- Hard-coding `Sales User` in tests — that role assumes the user owns the doc; switch tests to `Sales Manager` for cross-user paths.
- Editing the Sales Invoice JSON directly to add a field — CRITICAL upstream-edit violation. Use Custom Field fixture.
- Custom Field naming collision — name format is `<DocType>-<fieldname>`. Two apps adding `Sales Invoice-extra_notes` collide on fixture sync.
- Not reading [`erpnext-domains/accounting`](./accounting.md) when adding fields that affect GL — Sales Invoice posts to GL on submit.

## References
- [`erpnext-domains/crm`](./crm.md) — pre-sales side
- [`erpnext-domains/accounting`](./accounting.md) — what Sales Invoice does on submit
- [`frappe-core/doctype-authoring`](../frappe-core/doctype-authoring.md) — Custom Field decision matrix
- [`frappe-core/hooks-and-events`](../frappe-core/hooks-and-events.md) — for `doc_events` on Sales Invoice
- [`discovery/data/api-surface.json`](../../../discovery/data/api-surface.json) — `novizna_crm/api/erpnext_sync` methods
