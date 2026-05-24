---
id: accounting
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Work touching the General Ledger, Journal Entries, Accounting Dimensions, Cost Centers, or ERPNext financial DocTypes"
scope: [agent:architect, agent:backend-specialist]
foundational: false
domain: erpnext-domains
security_score: 100
supersedes: []
---

# ERPNext Accounting Domain

The GL/Journal/Dimension model used by `erpnext` and consumed by `noviznaerp_payroll`, `invoice_ninja_integration`, and `cargo_management`. Loaded when work touches financial DocTypes or posts to the General Ledger.

## When to Load
- Adding a controller hook that posts to GL
- Authoring an accounting report (Trial Balance, P&L derivative)
- Adding an Accounting Dimension or Cost Center
- Reviewing a JE auto-generator in `noviznaerp_payroll` or `invoice_ninja_integration`

## Key DocTypes

| DocType | Purpose |
|---------|---------|
| `Account` | Chart of Accounts node |
| `GL Entry` | Single ledger row (one debit or one credit) |
| `Journal Entry` | Multi-row manual or automated posting |
| `Payment Entry` | Customer / Supplier payments |
| `Cost Center` | Departmental cost grouping |
| `Accounting Dimension` | Custom slicer (Project, Branch, Campaign…) |
| `Fiscal Year` | Period boundaries |
| `Account Settings` | Per-company accounting prefs |

## Key Concepts

1. **GL Entries are immutable** — once posted (via submitted parent doc), they're append-only. Reversals via cancellation of the parent or compensating JE.
2. **Posting via parent DocType** — Sales Invoice, Purchase Invoice, Payment Entry, Journal Entry all post their own GL via `make_gl_entries()`.
3. **Cost Center is mandatory** on many GL entries — Item-level default, then Company default.
4. **Accounting Dimensions** are pluggable extra slicers — add new ones via `Accounting Dimension` DocType; ERPNext auto-adds the field everywhere.
5. **Cancellation reverses GL** — cancelling a submitted SI emits negating GL Entries; the original rows stay.
6. **Multi-currency** — `Account` has `account_currency`; transactions in non-default currency carry an `exchange_rate`.

## Patterns

### Pattern: Posting a Journal Entry from custom code

**When:** `noviznaerp_payroll` posts an EOBI deduction JE on Salary Slip submission.

**Do:**
```python
import frappe
from frappe import _
from frappe.utils import flt

def post_eobi_je(salary_slip) -> str:
    """Create + submit a JE for the EOBI deduction on this slip."""
    if not flt(salary_slip.eobi_amount):
        return ""

    je = frappe.new_doc("Journal Entry")
    je.posting_date = salary_slip.posting_date
    je.company = salary_slip.company
    je.voucher_type = "Journal Entry"

    je.append("accounts", {
        "account": "EOBI Expense - " + salary_slip.company_abbr,
        "debit_in_account_currency": flt(salary_slip.eobi_amount),
        "cost_center": salary_slip.cost_center,
    })
    je.append("accounts", {
        "account": "EOBI Payable - " + salary_slip.company_abbr,
        "credit_in_account_currency": flt(salary_slip.eobi_amount),
        "cost_center": salary_slip.cost_center,
    })

    je.insert(ignore_permissions=True)  # justified: triggered by Salary Slip submit
    je.submit()
    return je.name
```

**Don't:** Insert directly into `tabGL Entry` — bypasses ERPNext's validation, balance checks, and dimension propagation.

### Pattern: Account name resolution

**When:** Code references an account that varies by company.

**Do:** Use `frappe.db.get_value("Company", company, "default_<x>_account")` or look up via abbreviation, never hard-code account names.

```python
income_account = frappe.db.get_value("Company", company, "default_income_account")
```

**Don't:**
```python
income_account = "Sales - NVZ"  # breaks for any other company / abbreviation
```

### Pattern: Adding an Accounting Dimension

**When:** Need to slice GL by Branch (not built-in).

**Do (one-time, via UI or fixture):**
1. Create an `Accounting Dimension` with `document_type = "Branch"`.
2. ERPNext auto-adds a `branch` field to every transactional DocType.
3. New GL Entries carry the dimension; reports can filter on it.

**Don't:** Add a Custom Field called `branch` to Sales Invoice manually — the Accounting Dimension machinery is what makes it appear on GL Entries.

### Pattern: Cost Center default cascade

**Order ERPNext picks Cost Center for a GL row:**
1. Explicit on the line item
2. Item's default cost center (per company)
3. Parent doc's cost center
4. Company's default cost center

Don't hard-code Cost Center on the line if the cascade gives the right answer.

### Pattern: Trial Balance / GL report extension

**When:** Authoring a derivative report.

**Do:** Use `frappe.get_all("GL Entry", filters=..., fields=...)` or join `tabGL Entry` with `tabAccount` in raw SQL. The `against_voucher` / `against_voucher_type` fields trace the originating doc.

```python
rows = frappe.db.sql(
    """
    SELECT account, SUM(debit) - SUM(credit) AS balance
    FROM `tabGL Entry`
    WHERE company = %(company)s
      AND posting_date BETWEEN %(start)s AND %(end)s
      AND is_cancelled = 0
    GROUP BY account
    """,
    values={"company": company, "start": start, "end": end},
    as_dict=True,
)
```

Always include `is_cancelled = 0` (cancelled rows still exist with offsetting entries).

### Pattern: Multi-currency posting

**When:** Sales Invoice in EUR for a USD-base company.

**Do:** Let ERPNext compute via `Sales Invoice.conversion_rate`; never compute manually. The GL Entry gets:
- `debit` / `credit` (in account currency, usually base)
- `debit_in_account_currency` / `credit_in_account_currency` (in transaction currency)

## Reports to Know

| Report | What it answers |
|--------|-----------------|
| `Trial Balance` | Account-level debit/credit balances |
| `General Ledger` | Per-account transaction list |
| `Accounts Receivable` | Open invoices per customer |
| `Accounts Payable` | Open bills per supplier |
| `Profit and Loss Statement` | P&L by period |
| `Balance Sheet` | Snapshot at date |

Extend these by overriding the report class in `hooks.py:override_doctype_class`-style or by writing a sibling Script Report under your custom app.

## Patches that Touch GL

When a patch modifies submitted accounting docs, you must usually re-post GL:

```python
def execute() -> None:
    """After fixing posting_date, re-post GL for affected SIs."""
    for si_name in _affected_si_names():
        si = frappe.get_doc("Sales Invoice", si_name)
        si.cancel()    # emits negating GL Entries
        si.posting_date = _corrected_date(si)
        si.docstatus = 0
        si.submit()    # re-posts with corrected date
```

This pattern is destructive — pair with a `bench backup` and human approval.

## Common Pitfalls
- Inserting directly into `tabGL Entry` — bypasses cancellation logic.
- Forgetting `Cost Center` on a line → balance check failure on submit.
- Reporting on `tabGL Entry` without `is_cancelled = 0` filter — sees both original and reversal rows.
- Modifying account names of in-use Accounts (parent of GL Entries) without using `rename_doc` — orphans the GL rows.
- Hard-coding company-specific account names instead of using `frappe.db.get_value("Company", ..., "default_*_account")`.
- Posting JEs from `doc_events:on_validate` instead of `on_submit` — fires before the parent is committed.

## References
- [`erpnext-domains/sales`](./sales.md) — for SI / SO that drive GL
- [`erpnext-domains/hr-payroll`](./hr-payroll.md) — payroll-driven JEs (EOBI, salary)
- [`frappe-core/hooks-and-events`](../frappe-core/hooks-and-events.md) — for `on_submit` hook placement
- [`reporting/script-report-authoring`](../reporting/script-report-authoring.md) — for extending accounting reports
