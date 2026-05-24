---
id: hooks-and-events
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Adding or modifying entries in any custom app's hooks.py — doc_events, scheduler_events, overrides, fixtures, boot_session, app_include_*"
scope: [agent:architect, agent:backend-specialist, agent:integrations-specialist, agent:devops-deployment]
foundational: false
domain: frappe-core
security_score: 100
supersedes: []
---

# hooks.py and Event Dispatch

How Frappe dispatches `doc_events`, scheduler entries, overrides, and includes — grounded in the 8 active `hooks.py` files in this bench.

## When to Load
- Adding a `doc_events` handler for a custom or upstream DocType
- Adding a scheduler entry
- Overriding an upstream controller class or whitelisted method
- Adding fixtures, app includes, or boot session callbacks

## Key Concepts

1. **Dispatch order in `doc_events`** — for the same trigger, hooks from all installed apps fire in `installed_apps` order. Order is not configurable inside one app.
2. **Scheduler cadences** — `cron`, `all` (every 4 min), `hourly`, `daily`, `weekly`, `monthly`. Long jobs must be `enqueue`-d, not run inline in the scheduler tick.
3. **`override_doctype_class`** — replaces the controller class for a DocType (custom or upstream). All field schema still comes from the original DocType JSON.
4. **`override_whitelisted_methods`** — redirect a whitelisted method to your replacement. Used to monkey-patch an upstream endpoint without forking it.
5. **`fixtures`** — exported on `bench export-fixtures`; imported on `bench migrate`. Watch out for **DocType bleed** (unrelated rows tagged into your export — use [`fixture-differ`](../../tools/fixture-differ.yaml)).
6. **`app_include_js` / `app_include_css`** — bundled into the desk shell on every load. Heavy includes hurt every page.
7. **`boot_session`** — runs once per login; the right place to inject per-user runtime config into `frappe.boot`.
8. **Idempotency** — scheduler handlers and webhook handlers must be idempotent (cron retries, duplicate webhooks happen).

## Hooks signal inventory (this bench)

Per [`hooks-index.json`](../../../discovery/data/hooks-index.json) — which app uses which hook category:

| App | doc_events | scheduler | fixtures | overrides | includes | after_install |
|-----|:-:|:-:|:-:|:-:|:-:|:-:|
| `novizna_crm` | yes | yes | — | — | yes | yes |
| `novizna_core` | — | — | — | yes | — | yes |
| `novizna_pos` | yes | — | — | yes | — | yes |
| `invoice_ninja_integration` | yes | yes | — | — | yes | yes |
| `noviznaerp_payroll` | yes | yes | — | yes | yes | — |
| `cargo_management` | yes | — | yes | — | yes | — |
| `changemakers` | yes | — | yes | — | yes | yes |
| `erpnext_location` | — | yes | yes | — | — | yes |

## Patterns

### Pattern: `doc_events` handler with no commit

**When:** React to a Sales Invoice submission to log to `cargo_management`.

**Do:**
```python
# apps/cargo_management/cargo_management/hooks.py
doc_events = {
    "Sales Invoice": {
        "on_submit": "cargo_management.parcel_management.events.log_invoice_submit",
    },
}
```

```python
# events.py
import frappe
from frappe.model.document import Document

def log_invoice_submit(doc: Document, method: str) -> None:
    """Record a Parcel log entry when a Sales Invoice with parcels is submitted."""
    if not doc.get("parcels"):
        return
    frappe.get_doc({
        "doctype": "Parcel Log",
        "invoice": doc.name,
        "status": "submitted",
    }).insert(ignore_permissions=True)  # justified: triggered by user with submit perm on SI
    # NO frappe.db.commit() — the outer transaction handles it
```

**Don't:** Call `frappe.db.commit()` inside a `doc_events` handler — breaks atomicity if the parent transaction rolls back. See [AP-004](../../../discovery/data/anti-pattern-findings.json) (73 known occurrences across the bench).

### Pattern: Scheduler entry with `frappe.enqueue`

**When:** Nightly sync, e.g., Invoice Ninja two-way reconciliation.

**Do:**
```python
# apps/invoice_ninja_integration/invoice_ninja_integration/hooks.py
scheduler_events = {
    "cron": {
        "0 2 * * *": [
            "invoice_ninja_integration.sync.schedule_nightly_sync"
        ]
    }
}
```

```python
# sync.py
def schedule_nightly_sync() -> None:
    """Scheduler tick: enqueue the actual sync on the long queue."""
    frappe.enqueue(
        method="invoice_ninja_integration.sync.run_nightly_sync",
        queue="long", timeout=1800, now=False,
    )
```

**Don't:** Do the actual sync work inline in `schedule_nightly_sync` — the scheduler tick has a tight default timeout.

### Pattern: `override_doctype_class` (upstream class extension)

**When:** Need to extend ERPNext's `Salary Slip` for payroll-specific behavior.

**Do:**
```python
# apps/noviznaerp_payroll/noviznaerp_payroll/hooks.py
override_doctype_class = {
    "Salary Slip": "noviznaerp_payroll.overrides.salary_slip_override.SalarySlipNovizna",
}
```

```python
# overrides/salary_slip_override.py
from erpnext.payroll.doctype.salary_slip.salary_slip import SalarySlip

class SalarySlipNovizna(SalarySlip):
    """Adds EOBI deduction and biometric attendance rollup to the standard Salary Slip."""

    def validate(self) -> None:
        super().validate()
        self._compute_eobi_deduction()
```

**Don't:** Edit `apps/erpnext/erpnext/payroll/.../salary_slip.py` directly — that's an upstream-app violation (D-EDIT-UPSTREAM, CRITICAL).

### Pattern: Fixtures with a scoped filter

**When:** Exporting Custom Fields scoped to one app.

**Do:**
```python
# apps/cargo_management/cargo_management/hooks.py
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["name", "in", [
            "Sales Invoice-customs_code",
            "Delivery Note-parcel_tracking_id"
        ]]]
    }
]
```

After every fixture-touching change, run [`fixture-differ`](../../tools/fixture-differ.yaml) to confirm only the intended rows landed.

**Don't:** `{"dt": "Custom Field"}` with no filter — picks up every Custom Field on the bench. Classic DocType bleed.

### Pattern: `boot_session` injection

**When:** Frontend needs per-user runtime values without an extra round trip.

**Do:**
```python
# hooks.py
boot_session = "novizna_pos.boot.add_pos_boot"

# boot.py
def add_pos_boot(bootinfo: dict) -> None:
    """Hydrate POS profile and branch warehouse for the desk shell."""
    user = frappe.session.user
    bootinfo["pos_profile"] = frappe.db.get_value(
        "POS Profile User", {"user": user}, "parent"
    )
```

## Common Pitfalls
- `doc_events` handler raises an exception → the whole transaction rolls back (sometimes desired, sometimes catastrophic). Wrap recoverable side-effects in try/except and log via `frappe.log_error`.
- Scheduler event registered but you didn't `bench restart` — it never fires. DevOps reminder.
- `override_whitelisted_methods` shadows a method that has multiple legitimate callers — verify with grep before adding.
- Including a large JS bundle via `app_include_js` — degrades every desk page; use `web_include_js` for portal-only.
- Fixture exports drag in unrelated Custom Fields — always run `fixture-differ` after `bench export-fixtures`.

## References
- [`frappe-core/migration-patches`](./migration-patches.md) — for one-shot data migrations triggered after a hook change
- [`integrations/queueing-retry-backoff`](../integrations/queueing-retry-backoff.md) — for scheduler-driven jobs
- [`discovery/data/hooks-index.json`](../../../discovery/data/hooks-index.json) — current hook signals per app
- [`discovery/data/anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json) — AP-004 (`frappe.db.commit` in handlers)
