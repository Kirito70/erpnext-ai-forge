---
id: crm
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Work on novizna_crm — CRM Lead, CRM Deal, vendor connectors, ERPNext sync, or the frontend override system"
scope: [agent:architect, agent:backend-specialist, agent:frontend-frappe-ui-specialist, agent:integrations-specialist]
foundational: false
domain: erpnext-domains
security_score: 100
supersedes: []
---

# CRM Domain (novizna_crm)

The pre-sales funnel: Lead → Opportunity → Deal → handoff to Sales (Quotation). Built on upstream `crm` extended by `novizna_crm` (custom DocTypes + 40 whitelist APIs + 4 vendor connectors + 10-file frontend override). Loaded for any CRM-domain backend, frontend, or sync task.

## When to Load
- Adding fields/controllers to `CRM Lead`, `CRM Deal`, `CRM Lead Industry`, `CRM Import Log`
- Authoring or extending the 4 vendor connectors (Zoho, HubSpot, LinkedIn, Google)
- Wiring a new flow into the `novizna_crm` frontend override system
- Designing or modifying `novizna_crm/api/erpnext_sync.py`

## Key DocTypes

### Upstream (`crm` app)

| DocType | Purpose |
|---------|---------|
| `CRM Lead` | Top-of-funnel prospect |
| `CRM Deal` | Qualified opportunity |
| `CRM Communication` | Email/call/note log |
| `CRM Task` | Follow-up tasks |
| `CRM Note` | Free-form notes |

### Custom (`novizna_crm`, 2)

Per [`doctype-index.json`](../../../discovery/data/doctype-index.json):

| DocType | Purpose |
|---------|---------|
| `crm_lead_industry` | Industry taxonomy for Lead segmentation |
| `crm_import_log` | Trace of bulk imports (CSV, Zoho, HubSpot, etc.) |

Both follow the `crm_<noun>` naming convention per [`frappe-core/conventions`](../frappe-core/conventions.md).

## Whitelist API Surface

40 endpoints across [`api-surface.json`](../../../discovery/data/api-surface.json):

| Module | Sample methods |
|--------|----------------|
| `api/leads.py` | Lead-side CRUD + custom queries |
| `api/deals.py` | `get_deal_addresses`, deal-side helpers |
| `api/erpnext_sync.py` | `get_erpnext_customers`, `sync_erpnext_customers`, `get_erpnext_quotations` |
| `api/crm_import.py` | Generic CSV import |
| `api/universal_import.py` | Multi-source import orchestration |
| `api/import_leads.py` | `import_customers_as_leads` |
| `api/connector_manager.py` | Vendor connector dispatcher |

## Vendor Connectors (Decision 18)

Per [`integrations-map.json`](../../../discovery/data/integrations-map.json), the 4 connectors live at `apps/novizna_crm/novizna_crm/api/connectors/`:

| Connector | Endpoint | Auth |
|-----------|----------|------|
| `zoho.py` | `www.zohoapis.com/crm/v2` | OAuth2 |
| `hubspot.py` | (verify in code) | OAuth2 or API key |
| `linkedin.py` | `api.linkedin.com/v2` | OAuth2 |
| `google_sheets.py` | `sheets.googleapis.com/v4`, `googleapis.com/drive/v3` | OAuth2 |

Orchestration (NOT in `connectors/`) lives in the `api/*.py` modules above. Keep the separation per Decision 18.

## The Frontend Override System

`apps/novizna_crm/frontend/` overrides upstream `apps/crm/frontend/` via the 3-layer rule. **This is the single most important frontend rule on this bench** — see [`frontend/novizna-crm-override-system`](../frontend/novizna-crm-override-system.md) for the full set.

Currently 10 overrides per [`override-map.json`](../../../discovery/data/override-map.json):
`main.js`, `router.js`, `socket.js`, `index.css`, `components/Activities/Activities.vue`, `components/Layouts/AppSidebar.vue`, `composables/useActiveTabManager.js`, `pages/DataImport.vue`, `pages/Deal.vue`, `pages/Lead.vue`.

## Patterns

### Pattern: New Lead with Industry classification

**Do (backend):**
```python
import frappe
from frappe import _

@frappe.whitelist(methods=["POST"])
def create_lead_with_industry(first_name: str, last_name: str, email: str, industry: str) -> dict:
    """Create a CRM Lead with a CRM Lead Industry link."""
    frappe.has_permission("CRM Lead", "create", throw=True)
    if not frappe.db.exists("CRM Lead Industry", industry):
        frappe.throw(_("Unknown industry: {0}").format(industry))
    lead = frappe.get_doc({
        "doctype": "CRM Lead",
        "first_name": first_name, "last_name": last_name, "email": email,
        "industry": industry,
    }).insert()
    return {"name": lead.name}
```

### Pattern: Frontend filter on Industry

**Do (frontend, net-new under `src/`):** see the `LeadsIndustryFilter.vue` example in [`frontend/frappe-ui-components`](../frontend/frappe-ui-components.md) and [`frontend/novizna-crm-override-system`](../frontend/novizna-crm-override-system.md).

The pattern: net-new component under `src/components/Leads/`, slotted into an `src_override/components/Leads/LeadsListHeader.vue` override.

### Pattern: Bulk import with CRM Import Log

**When:** Importing 1000 customers as Leads.

**Do:**
```python
@frappe.whitelist(methods=["POST"])
def import_customers_as_leads(source: str = "ERPNext") -> dict:
    """Enqueue a bulk import and log it to crm_import_log."""
    frappe.has_permission("CRM Lead", "create", throw=True)
    log = frappe.get_doc({
        "doctype": "CRM Import Log",
        "source": source,
        "status": "Queued",
    }).insert()
    frappe.enqueue(
        method="novizna_crm.api.import_leads._run_import",
        queue="long", timeout=1800,
        log_name=log.name, source=source,
    )
    return {"log_name": log.name}
```

The log gives the user a place to see status and re-run failed imports — see [`integrations/queueing-retry-backoff`](../integrations/queueing-retry-backoff.md) for the dead-letter pattern.

### Pattern: ERPNext customer sync from CRM Deal

**Do (in `api/erpnext_sync.py`):**
```python
@frappe.whitelist(methods=["POST"])
def sync_erpnext_customers(deal_names: list[str]) -> dict:
    """For each Deal, upsert the matching ERPNext Customer."""
    frappe.has_permission("CRM Deal", "read", throw=True)
    created, updated = 0, 0
    for deal_name in deal_names:
        deal = frappe.get_doc("CRM Deal", deal_name)
        existing = frappe.db.exists("Customer", {"customer_name": deal.organization})
        if existing:
            cust = frappe.get_doc("Customer", existing)
            cust.email_id = deal.email
            cust.save()
            updated += 1
        else:
            cust = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": deal.organization,
                "customer_type": "Company",
                "email_id": deal.email,
            }).insert()
            created += 1
    return {"created": created, "updated": updated}
```

### Pattern: Sidebar customization

**When:** Adding "Reports" entry to the CRM sidebar.

**Do (in `apps/novizna_crm/frontend/src/index.js`):**
```javascript
export const customSidebarItems = [
  { name: 'Reports', icon: ChartBarIcon, to: { name: 'NoviznaReports' } },
]
```

The `src_override/components/Layouts/AppSidebar.vue` override reads `customSidebarItems` and renders them. See [`frontend/novizna-crm-override-system`](../frontend/novizna-crm-override-system.md).

## Permissions

| Role | Scope |
|------|-------|
| `Sales User` | Read/write own Leads + Deals |
| `Sales Manager` | All-user scope; convert; assign |
| `CRM Manager` | All CRM DocTypes; import; sync |
| `System Manager` | Everything |

User Permissions on `Territory` are the common slicer.

## Common Pitfalls
- Adding a frontend file outside `src/` or `src_override/` — see the layer rule.
- Putting orchestration code inside `connectors/<vendor>.py` — violates Decision 18; keep `connectors/` vendor-pure.
- Creating Customers without the dedupe check — bulk imports produce duplicates with similar names.
- Editing upstream `apps/crm/` files — CRITICAL D-EDIT-UPSTREAM.
- Forgetting to log to `crm_import_log` — users have no recourse when an import fails silently.
- Hard-coding vendor endpoints in `api/` — they belong in the connector.
- Adding a new Industry without populating `crm_lead_industry` first — Link field validation fails.

## References
- [`erpnext-domains/sales`](./sales.md) — handoff target (Deal → Quotation)
- [`frontend/novizna-crm-override-system`](../frontend/novizna-crm-override-system.md) — the 3-layer rule
- [`frontend/frappe-ui-components`](../frontend/frappe-ui-components.md) — for component patterns
- [`integrations/oauth-patterns`](../integrations/oauth-patterns.md) — for the 4 vendor connectors
- [`integrations/queueing-retry-backoff`](../integrations/queueing-retry-backoff.md) — for the bulk-import dead-letter
- [`discovery/data/integrations-map.json`](../../../discovery/data/integrations-map.json) — connector inventory
- [`discovery/data/override-map.json`](../../../discovery/data/override-map.json) — the 10 overrides
