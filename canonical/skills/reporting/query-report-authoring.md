---
id: query-report-authoring
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Authoring or modifying a Query Report (SQL-only report) in any custom app"
scope: [agent:architect, agent:backend-specialist]
foundational: false
domain: reporting
security_score: 100
supersedes: []
---

# Query Report Authoring

Query Reports are pure-SQL reports — no Python execute. Filters bind via `%(name)s` placeholders. Simpler than Script Reports; use when no computed logic is needed.

## When to Load
- A simple "list of rows from a SQL query" report
- Avoiding the overhead of a `.py` execute for trivial reports
- Migrating a slow Script Report whose Python is just a SQL wrapper

## Key Concepts

1. **No Python module** — only a `.sql` file paired with the Report doc.
2. **Filter binding** — `%(filter_name)s` placeholders match filters declared on the Report doc.
3. **Permission filtering** — Frappe injects a WHERE clause based on User Permissions on the report's `ref_doctype` (set on the Report doc).
4. **Column inference** — Columns inferred from the SELECT list; column types come from the underlying DocType field types where matchable.
5. **No charts** — Query Reports don't support `chart_config`; promote to Script Report if you need one.

## File Layout

The Query Report lives **inside the Report DocType row in the DB**. The `.sql` and `.json` files are exported via fixtures or DocType JSON. Typical custom-app layout:

```
apps/<app>/<app>/<module>/report/<report_slug>/
    <report_slug>.json    # Report doc (report_type: "Query Report")
    <report_slug>.sql     # The SQL body (referenced from the Report doc)
```

## Patterns

### Pattern: Basic Query Report

**When:** "Open Parcels by Branch" for `cargo_management`.

**Do:**
```sql
-- apps/cargo_management/cargo_management/parcel_management/report/open_parcels_by_branch/open_parcels_by_branch.sql

SELECT
  p.name           AS "Parcel:Link/Parcel:160",
  p.branch         AS "Branch:Link/Branch:120",
  p.tracking_id    AS "Tracking ID:Data:160",
  p.status         AS "Status:Data:100",
  p.posting_date   AS "Posting Date:Date:110"
FROM `tabParcel` p
WHERE
  p.docstatus = 1
  AND p.status NOT IN ('Delivered', 'Returned')
  AND (%(branch)s = '' OR p.branch = %(branch)s)
  AND p.posting_date BETWEEN %(from_date)s AND %(to_date)s
ORDER BY p.posting_date DESC
```

Column metadata is encoded inline as `"<Label>:<Fieldtype>[/<Options>]:<Width>"`. Frappe parses this from the SELECT alias.

The Report doc declares filters matching the placeholder names:
```json
{
  "doctype": "Report",
  "report_type": "Query Report",
  "ref_doctype": "Parcel",
  "report_name": "Open Parcels by Branch",
  "is_standard": "Yes",
  "filters": [
    { "fieldname": "from_date", "fieldtype": "Date", "reqd": 1 },
    { "fieldname": "to_date",   "fieldtype": "Date", "reqd": 1 },
    { "fieldname": "branch",    "fieldtype": "Link", "options": "Branch" }
  ]
}
```

**Don't:** Concatenate filter values into the SQL body — Query Report bindings are the only safe path. There is no f-string layer here.

### Pattern: NULL-safe optional filter

**When:** A filter may be empty.

**Do:**
```sql
WHERE (%(branch)s = '' OR p.branch = %(branch)s)
```

**Don't:**
```sql
WHERE p.branch = %(branch)s   -- breaks when filter is empty
```

### Pattern: Joining parent and child

**When:** Listing parcel items per parcel.

**Do:**
```sql
SELECT
  p.name              AS "Parcel:Link/Parcel:160",
  pi.item_code        AS "Item:Link/Item:140",
  pi.qty              AS "Qty:Float:80"
FROM `tabParcel` p
JOIN `tabParcel Item` pi ON pi.parent = p.name
WHERE p.docstatus = 1
  AND pi.qty > 0
```

`pi.parent` is auto-indexed.

### Pattern: Promoting a Query Report to Script Report

**When:** You start needing computed columns, charts, or summary cards.

**Do:** Move the SQL into a `.py` `execute()`'s `_fetch()` helper and add `chart` / `report_summary` blocks. See [`reporting/script-report-authoring`](./script-report-authoring.md).

## Common Pitfalls
- Forgetting the column metadata in the alias — Frappe falls back to a `Data` column with a guessed label.
- Missing `ref_doctype` on the Report doc — permission filtering doesn't apply.
- Using `LIKE %(term)s` where the calling code passes the value with no wildcards — produces 0 rows; pass `%term%` from the filter side or use `CONCAT('%', %(term)s, '%')` in SQL.
- Reusing a placeholder name without re-declaring as a filter — silent NULL substitution.
- Using upstream Frappe table aliases that change between minor versions — pin to `` `tab<DocType>` `` qualified names.

## References
- [`reporting/script-report-authoring`](./script-report-authoring.md) — for when to upgrade
- [`data/sql-best-practices`](../data/sql-best-practices.md) — for SQL hygiene
- [`frappe-core/permissions-model`](../frappe-core/permissions-model.md) — for `ref_doctype` perm filtering
