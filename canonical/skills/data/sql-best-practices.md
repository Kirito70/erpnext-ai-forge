---
id: sql-best-practices
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Writing or reviewing any frappe.db.sql() call or raw SQL string in a custom app"
scope: [agent:architect, agent:backend-specialist, agent:security-reviewer]
foundational: false
domain: data
security_score: 100
supersedes: []
---

# SQL Best Practices (Frappe + MariaDB)

How to write safe, fast, and reviewable SQL on this bench. Directly addresses the **11 known SQL-injection findings** in [AP-001](../../../discovery/data/anti-pattern-findings.json) — every new occurrence is a HIGH-severity blocker.

## When to Load
- Writing `frappe.db.sql(...)` calls
- Reviewing existing SQL for AP-001 recurrence
- Optimizing a slow query against `tab<DocType>` tables
- Designing a query that joins parent + child tables

## Key Concepts

1. **Always parameterize** — pass `values=` dict; never f-string or `.format()` SQL.
2. **Avoid `SELECT *`** — list columns; `tab<DocType>` tables can have 100+ columns.
3. **`tab<DocType>` naming** — Frappe stores rows in `` `tab<DocType>` `` (backticks include spaces).
4. **Auto-indexed columns** — `name`, `creation`, `modified`, `parent` (for child tables), and any field with `search_index: 1` in DocType JSON.
5. **N+1 avoidance** — `frappe.get_all(..., fields=[...])` fetches in bulk; loop-then-fetch is slow.
6. **`as_dict=True`** — returns list of dicts (vs default tuples). Required for `.get('field')` access.
7. **No mid-transaction `commit`** — `frappe.db.commit()` inside `doc_events` breaks atomicity. See [AP-004](../../../discovery/data/anti-pattern-findings.json).

## Patterns

### Pattern: Parameterized SELECT-by-id

**When:** Looking up loan details by loan name (the recurring AP-001 shape in `noviznaerp_payroll`).

**Do:**
```python
import frappe

row = frappe.db.sql(
    """
    SELECT name, total_payment, status
    FROM `tabLoan`
    WHERE name = %(loan_id)s
    """,
    values={"loan_id": loan_id},
    as_dict=True,
)
```

**Don't (AP-001 anti-pattern — 11 known occurrences):**
```python
# apps/noviznaerp_payroll/noviznaerp_payroll/custom/loan_custom.py:137
row = frappe.db.sql(f"""
    SELECT name FROM `tabLoan` WHERE name = '{loan_id}'
""")
```

Every f-string SQL in a custom app is a D-SQL-FSTRING deduction (-30, HIGH).

### Pattern: Parameterized UPDATE

**When:** Updating loan interest fields (matches `loan_interest_accrual_custom.py:57`).

**Do:**
```python
frappe.db.sql(
    """
    UPDATE `tabLoan Interest Accrual`
    SET interest_amount = %(amount)s,
        status = 'Accrued'
    WHERE loan = %(loan_id)s AND posting_date = %(posting_date)s
    """,
    values={"amount": amount, "loan_id": loan_id, "posting_date": posting_date},
)
```

**Don't (AP-001 anti-pattern):**
```python
frappe.db.sql(f"""
    UPDATE `tabLoan Interest Accrual`
    SET interest_amount = {amount}, status = 'Accrued'
    WHERE loan = '{loan_id}'
""")
```

Even when `amount` is "definitely a number", interpolation crosses the boundary; future refactors lose the implicit cast. Use bindings always.

### Pattern: IN-clause with a list

**When:** Fetching salary structures for several employees (`salary_structure_custom.py:11-12`).

**Do:**
```python
# Frappe accepts a list as a single binding for IN
rows = frappe.db.sql(
    """
    SELECT name, employee
    FROM `tabSalary Structure`
    WHERE employee IN %(employees)s AND is_active = 'Yes'
    """,
    values={"employees": tuple(employee_ids)},  # tuple required
    as_dict=True,
)
```

**Don't:**
```python
employees_csv = "','".join(employee_ids)
frappe.db.sql(f"SELECT ... WHERE employee IN ('{employees_csv}')")  # AP-001 recurrence
```

### Pattern: Use `frappe.get_all` instead of raw SQL when possible

**When:** The query is a simple SELECT with filters and field projection.

**Do:**
```python
rows = frappe.get_all(
    "Salary Slip",
    filters={"employee": ("in", employee_ids), "docstatus": 1},
    fields=["name", "employee", "net_pay"],
    limit=100,
)
```

Frappe's query builder generates parameterized SQL automatically — no injection surface. Prefer this over `frappe.db.sql` for vanilla queries; reserve raw SQL for joins, aggregates, or vendor-specific functions.

### Pattern: Parent-child JOIN

**When:** Joining Salary Slip with its child Salary Detail rows.

**Do:**
```python
rows = frappe.db.sql(
    """
    SELECT ss.name, ss.employee, sd.salary_component, sd.amount
    FROM `tabSalary Slip` ss
    JOIN `tabSalary Detail` sd ON sd.parent = ss.name
    WHERE ss.docstatus = 1 AND ss.posting_date BETWEEN %(start)s AND %(end)s
    """,
    values={"start": start, "end": end},
    as_dict=True,
)
```

`sd.parent` is auto-indexed on child tables — fast.

### Pattern: Avoid N+1 in a loop

**When:** Need salary details for a list of employees.

**Do:**
```python
slips = frappe.get_all(
    "Salary Slip",
    filters={"employee": ("in", employee_ids), "docstatus": 1},
    fields=["name", "employee", "net_pay"],
)
```

**Don't:**
```python
slips = []
for emp in employee_ids:  # N round trips
    slip = frappe.db.get_value("Salary Slip",
        {"employee": emp, "docstatus": 1}, ["name", "net_pay"], as_dict=True)
    slips.append(slip)
```

### Pattern: No `frappe.db.commit()` mid-transaction

**Don't:**
```python
def on_submit(doc, method):
    log_to_audit(doc)
    frappe.db.commit()  # AP-004 — breaks atomicity if a later handler fails
    notify_users(doc)
```

`frappe.db.commit()` is only legitimate inside scheduled tasks that batch independent units of work. Inside `doc_events` it forces partial-success states.

## Common Pitfalls
- Forgetting `as_dict=True` and then using `row.field` (works only on dicts; tuples need `row[0]`).
- Mixing positional and named bindings — pick one (`values={"a": 1}` OR `values=(1,)`).
- Forgetting backticks around `tabDocType With Spaces` — MariaDB fails the parse.
- Building a query string concatenation across multiple branches "for flexibility" — each branch is a chance for injection. Use `frappe.qb` (query builder) when query shape is dynamic.
- `SELECT * FROM tabSales Invoice` — pulls 100+ columns; profile the page to see the cost.
- Querying a non-indexed column on a large table — see [`data/mariadb-debugging`](./mariadb-debugging.md).

## References
- [`data/mariadb-debugging`](./mariadb-debugging.md) — for performance follow-up
- [`frappe-core/conventions`](../frappe-core/conventions.md) — for `get_value` / `get_list` / `get_all` semantics
- [`security/review-checklist`](../security/review-checklist.md) — for the D-SQL-FSTRING deduction
- [`discovery/data/anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json) — AP-001 with file:line examples
