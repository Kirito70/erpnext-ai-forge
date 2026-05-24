---
id: script-report-authoring
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Authoring or modifying a Script Report in any custom app"
scope: [agent:architect, agent:backend-specialist, agent:qa-test-engineer]
foundational: false
domain: reporting
security_score: 100
supersedes: []
---

# Script Report Authoring

Script Reports are Python-driven reports that return `(columns, data, message?, chart?, report_summary?)`. They support arbitrary aggregation, computed columns, and chart blocks — used heavily in `noviznaerp_payroll` for loan/salary registers.

## When to Load
- Adding a new Script Report under any custom app
- Modifying an existing Script Report (e.g., `noviznaerp_payroll/.../report/loan_register/`)
- Designing a report with computed columns or charts

## Key Concepts

1. **Module shape** — `execute(filters: dict) -> tuple[list[dict], list[dict], str | None, dict | None]` (last 2 optional).
2. **Columns spec** — list of dicts: `{fieldname, label, fieldtype, options?, width?}`.
3. **Data shape** — list of dicts (or list of lists) matching column fieldnames.
4. **Filter schema** — defined in the report's `.js` file; appears in the report toolbar.
5. **Permissions** — the report row in DocType "Report" carries roles; the Python execute also runs as the calling user.
6. **`chart_config`** — optional block in the return tuple that renders a chart above the table.
7. **`report_summary`** — top-of-report KPI cards.

## File Layout

```
apps/<app>/<app>/<module>/report/<report_slug>/
    <report_slug>.json    # Report doc + filter spec
    <report_slug>.py      # execute() function
    <report_slug>.js      # client-side filter wiring + chart customization
    test_<report_slug>.py # unit tests
    __init__.py
```

## Patterns

### Pattern: Basic Script Report

**When:** Authoring `Loan Register` (matches the existing `noviznaerp_payroll/.../report/loan_register/`).

**Do:**
```python
# loan_register.py
import frappe
from frappe import _
from frappe.utils import flt

def execute(filters: dict | None = None) -> tuple:
    """Loan Register grouped by status, filtered by date range and branch."""
    filters = filters or {}
    columns = _columns()
    data = _fetch(filters)
    chart = _chart(data)
    summary = _summary(data)
    return columns, data, None, chart, summary


def _columns() -> list[dict]:
    return [
        {"fieldname": "loan",         "label": _("Loan"),         "fieldtype": "Link",  "options": "Loan",    "width": 180},
        {"fieldname": "employee",     "label": _("Employee"),     "fieldtype": "Link",  "options": "Employee","width": 180},
        {"fieldname": "loan_amount",  "label": _("Loan Amount"),  "fieldtype": "Currency", "width": 140},
        {"fieldname": "total_payment","label": _("Total Payment"),"fieldtype": "Currency", "width": 140},
        {"fieldname": "status",       "label": _("Status"),       "fieldtype": "Data",  "width": 100},
    ]


def _fetch(filters: dict) -> list[dict]:
    return frappe.db.sql(
        """
        SELECT name AS loan, employee, loan_amount, total_payment, status
        FROM `tabLoan`
        WHERE posting_date BETWEEN %(start)s AND %(end)s
          AND (%(branch)s = '' OR branch = %(branch)s)
        ORDER BY posting_date DESC
        """,
        values={
            "start": filters.get("from_date"),
            "end": filters.get("to_date"),
            "branch": filters.get("branch", ""),
        },
        as_dict=True,
    )


def _chart(data: list[dict]) -> dict:
    """Bar chart of total payment by status."""
    by_status: dict[str, float] = {}
    for row in data:
        by_status[row.status] = by_status.get(row.status, 0.0) + flt(row.total_payment)
    return {
        "data": {
            "labels": list(by_status.keys()),
            "datasets": [{"name": _("Total Payment"), "values": list(by_status.values())}],
        },
        "type": "bar",
        "colors": ["#7575ff"],
    }


def _summary(data: list[dict]) -> list[dict]:
    total = sum(flt(r.loan_amount) for r in data)
    return [
        {"label": _("Total Loans"), "value": len(data), "datatype": "Int"},
        {"label": _("Total Amount"), "value": total, "datatype": "Currency"},
    ]
```

**Don't (mirrors AP-001 in the current `loan_register.py:111`):**
```python
frappe.db.sql(f"SELECT ... WHERE branch = '{filters.get('branch')}'")
```

### Pattern: Filter schema in `.js`

**Do:**
```javascript
// loan_register.js
frappe.query_reports["Loan Register"] = {
  filters: [
    { fieldname: "from_date", label: __("From Date"), fieldtype: "Date",
      default: frappe.datetime.add_months(frappe.datetime.get_today(), -1), reqd: 1 },
    { fieldname: "to_date",   label: __("To Date"),   fieldtype: "Date",
      default: frappe.datetime.get_today(), reqd: 1 },
    { fieldname: "branch",    label: __("Branch"),    fieldtype: "Link",
      options: "Branch" },
  ],
}
```

### Pattern: Linking computed columns to Frappe DocTypes

**When:** A computed column should be clickable to navigate to a doc.

**Do:** Use `fieldtype: "Link"` with `options: "<Target DocType>"` and emit the doc name as the value:
```python
{"fieldname": "loan", "fieldtype": "Link", "options": "Loan"}
# data row: {"loan": "LN-2026-00042", ...}  → renders as a hyperlink
```

### Pattern: Permission-aware report

**When:** Loan Register must respect User Permissions on Branch.

**Do:** Use `frappe.get_list` instead of raw SQL when permission filtering is needed; the ORM applies User Permissions automatically. Reserve raw SQL for reports where you'll apply the filtering manually in `_fetch`.

## Common Pitfalls
- Returning data as list-of-lists when columns expect dict access — column rendering breaks silently.
- Forgetting `reqd: 1` on date filters → expensive queries with no bounds.
- Building chart data with `Decimal` types — `flt()` casts to float.
- Translating `label` but not `name` in summary cards — half-translated UI.
- Long-running aggregations inline in `execute` — for very large data sets, materialize into a cached DocType nightly and serve from cache.

## References
- [`reporting/query-report-authoring`](./query-report-authoring.md) — for the SQL-only alternative
- [`data/sql-best-practices`](../data/sql-best-practices.md) — for parameterized `frappe.db.sql`
- [`reporting/workflow-authoring`](./workflow-authoring.md) — when report state drives a workflow
- [`frappe-core/permissions-model`](../frappe-core/permissions-model.md) — User Permissions interaction
