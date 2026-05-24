---
id: hr-payroll
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Work touching Employee, Salary Structure, Salary Slip, Payroll Entry, EOBI, biometric attendance, loans, or any noviznaerp_payroll DocType"
scope: [agent:architect, agent:backend-specialist, agent:security-reviewer]
foundational: false
domain: erpnext-domains
security_score: 100
supersedes: []
---

# HR / Payroll Domain (with noviznaerp_payroll extensions)

The HRMS Employee/Salary cycle plus the **73 custom DocTypes in `noviznaerp_payroll`** (the largest custom app on this bench). Critical reading because `noviznaerp_payroll` carries every standing anti-pattern finding: AP-001 (11 SQL f-strings), AP-003 (`ignore_permissions`), AP-004 (`db.commit`).

## When to Load
- Adding fields or controllers to `Employee`, `Salary Slip`, `Salary Structure`, `Payroll Entry`
- Working with `noviznaerp_payroll` DocTypes (EOBI, biometric, loans, attendance tool)
- Reviewing an override under `noviznaerp_payroll/overrides/`
- Authoring a payroll report or print format

## Key DocTypes — Upstream

| DocType | Owner App | Notes |
|---------|-----------|-------|
| `Employee` | `hrms` | Master record |
| `Salary Structure` | `hrms` | Component template |
| `Salary Structure Assignment` | `hrms` | Employee ↔ Structure |
| `Salary Slip` | `hrms` | Per-period payroll record |
| `Payroll Entry` | `hrms` | Bulk run that emits Salary Slips |
| `Loan` | `lending` | Employee loan master |
| `Leave Encashment` | `hrms` | Leave-to-cash conversion |

## Key DocTypes — `noviznaerp_payroll` (custom, 73 total)

Per [`doctype-index.json`](../../../discovery/data/doctype-index.json), highlights:

- **EOBI** — `eobi`, `eobi_policy`
- **Biometric attendance** — `biometric_device`, `biometric_device_logs`, `employee_biometric_attendance`, `geo_fancing_by_city`, `geo_fancing_by_radius`
- **Attendance tooling** — `attendance_tool`
- **Bulk salary** — `bulk_additional_salary_tool`, `additional_salary_details`, `bimonthly_employees`, `bimonthly_salaries`
- **Loans** — `loan_criteria`, `loan_product_emi`, `advance_policy_setup`
- **Off-boarding** — `full_and_final_accounts_setup`, `full_and_final_account_details`, `notice_period_policy`

## Standing Anti-Pattern Concentration

Per [`anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json), `noviznaerp_payroll` carries:

| AP | Severity | Examples in this app |
|----|----------|---------------------|
| AP-001 | HIGH | 11 known f-string SQL — all 11 are in this app's files (`custom/loan_custom.py`, `custom/salary_structure_custom.py`, `overrides/leave_encashment_override.py`, etc.) |
| AP-003 | MEDIUM | Significant share of the 99 `ignore_permissions=True` |
| AP-004 | MEDIUM | Significant share of the 73 `frappe.db.commit()` |

Any new code in `noviznaerp_payroll` is reviewed against these findings extra carefully. New occurrences are blockers.

## Overrides in this App

Per [`hooks-index.json`](../../../discovery/data/hooks-index.json), `noviznaerp_payroll` declares `overrides: true`. Confirmed in the discovery:

- `noviznaerp_payroll/overrides/salary_slip_override.py` — overrides `SalarySlip` controller
- `noviznaerp_payroll/overrides/leave_encashment_override.py`

When extending these, prefer adding methods over modifying `validate` (which is already complex).

## Patterns

### Pattern: Salary Slip controller extension (parameterized SQL — fixing AP-001)

**When:** Computing EOBI deduction (lines around `salary_slip_override.py:149` flagged in AP-001).

**Do:**
```python
import frappe
from erpnext.payroll.doctype.salary_slip.salary_slip import SalarySlip

class SalarySlipNovizna(SalarySlip):
    """Adds EOBI deduction and biometric attendance rollup."""

    def validate(self) -> None:
        super().validate()
        self._compute_eobi_deduction()

    def _compute_eobi_deduction(self) -> None:
        """Fetch EOBI Policy for this employee's grade."""
        rows = frappe.db.sql(
            """
            SELECT eobi_rate
            FROM `tabEOBI Policy`
            WHERE grade = %(grade)s AND is_active = 1
            LIMIT 1
            """,
            values={"grade": self.employee_grade},
            as_dict=True,
        )
        if not rows:
            return
        self.eobi_amount = (self.gross_pay or 0) * (rows[0].eobi_rate or 0) / 100
```

**Don't (AP-001 lineage):**
```python
rows = frappe.db.sql(f"""
    SELECT eobi_rate FROM `tabEOBI Policy`
    WHERE grade = '{self.employee_grade}' AND is_active = 1 LIMIT 1
""")
```

### Pattern: Posting EOBI Journal Entry on submit

**When:** Salary Slip submit should also post EOBI to GL.

**Do:** Combine `on_submit` controller hook with the JE pattern in [`erpnext-domains/accounting`](./accounting.md). Never put `frappe.db.commit()` in the hook (AP-004).

### Pattern: Biometric attendance ingestion

**When:** Push event from a biometric device to `biometric_device_logs`.

**Do:** Receive via a signed webhook (see [`integrations/webhooks`](../integrations/webhooks.md)) → enqueue → background job materializes `employee_biometric_attendance` rows. Don't process in the request path.

### Pattern: Loan amortization with parameterized SQL

**When:** Recomputing the loan schedule (currently `custom/loan_custom.py:137,150,240` — AP-001 recurrences).

**Do:**
```python
def update_loan_payment(loan_id: str, paid_amount: float) -> None:
    """Apply a payment to the loan; recompute total_payment."""
    frappe.db.sql(
        """
        UPDATE `tabLoan` SET total_payment = total_payment - %(amount)s
        WHERE name = %(loan_id)s
        """,
        values={"amount": paid_amount, "loan_id": loan_id},
    )
```

### Pattern: EOBI Settings & per-grade policy

**When:** EOBI rate varies by Employee Grade.

**Do:** Reference the `EOBI Policy` DocType (already in the app). Look up by grade; cache per request:
```python
@functools.lru_cache(maxsize=64)
def _eobi_rate(grade: str) -> float:
    return frappe.db.get_value("EOBI Policy", {"grade": grade, "is_active": 1}, "eobi_rate") or 0.0
```

Clear the cache after any policy change (`frappe.cache().delete_keys("eobi_rate_*")` if you migrate to Frappe's cache).

## Permissions

| Role | Scope |
|------|-------|
| `HR User` | Read Employee; create Attendance; read Salary Slip (own) |
| `HR Manager` | Full Employee, Salary Slip, Payroll Entry; submit |
| `Employee Self Service` | Read own Salary Slip + Leave + Loan; raise requests |
| `Accounts Manager` | Read Salary Slip; submit JE generated from payroll |
| `System Manager` | Everything |

## Print Formats

`noviznaerp_payroll` typically ships custom Salary Slip print formats for local compliance. See [`reporting/print-format-authoring`](../reporting/print-format-authoring.md) for the safe-rendering rules — Salary Slips contain salary numbers that should never go through `| safe`.

## Common Pitfalls
- New code touching this app that introduces another `frappe.db.sql(f"...")` — instant AP-001 recurrence.
- Calling `frappe.db.commit()` after auto-posting JE — breaks atomicity if a later assertion fails.
- Editing `Salary Slip` JSON directly to add a field instead of Custom Field fixture.
- Hard-coding company-specific account names in JE postings — see [`erpnext-domains/accounting`](./accounting.md).
- Biometric device logs without idempotency keys — duplicate timestamps reprocess into double attendance.
- Bulk Salary tool that processes synchronously — use `frappe.enqueue` for any N>100 batch.

## References
- [`erpnext-domains/accounting`](./accounting.md) — for the JE shape this app emits
- [`data/sql-best-practices`](../data/sql-best-practices.md) — for the AP-001 fixes
- [`frappe-core/hooks-and-events`](../frappe-core/hooks-and-events.md) — for `override_doctype_class`
- [`security/review-checklist`](../security/review-checklist.md) — AP-001/003/004 hot-spots
- [`discovery/data/doctype-index.json`](../../../discovery/data/doctype-index.json) — the 73 DocTypes
- [`discovery/data/anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json) — file:line lineage
