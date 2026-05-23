---
id: optimize-query
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, backend-specialist]
---

# /optimize-query

Profile a slow query, propose indexes or refactor.

## Usage

```
/optimize-query <sql-or-file:line>
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<sql-or-file:line>` | yes | Either a SQL snippet in quotes, or a `path:line` pointing at a `frappe.db.sql()` call site |

## Examples

```
/optimize-query "SELECT * FROM `tabSales Invoice` WHERE customer = 'X' AND posting_date > '2025-01-01'"
/optimize-query apps/novizna_crm/novizna_crm/api/deals.py:142
```

## Pipeline

1. **Architect:** delegate to Backend Specialist (Database cluster loads)
2. **Backend Specialist:**
   - For SQL: run `EXPLAIN` via [`mariadb-query`](../tools/mariadb-query.yaml)
   - For a file:line: read the call site to extract the query + parameters + Frappe context
   - Analyze: full scans, missing indexes, N+1, unbounded result sets
   - Propose: index DDL (as a patch), query rewrite, `frappe.get_all(..., fields=[...])` alternative
3. **Security Reviewer (if DDL):** confirm the patch is idempotent and uses the correct version section
4. **Architect:** synthesize: before/after EXPLAIN, proposed patch, expected speedup

## Output

```markdown
## Query Optimization Report

**Target:** <SQL or file:line>

### Current EXPLAIN
| id | select_type | type | rows | key | Extra |
| 1  | SIMPLE      | ALL  | 50000 | NULL | Using where |

### Findings
- Full scan on `tabSales Invoice` (50k rows)
- Filter on `(customer, posting_date)` not covered by any index

### Proposed Patch
\`\`\`python
def execute():
    """Add covering index on Sales Invoice (customer, posting_date)."""
    frappe.db.sql("CREATE INDEX IF NOT EXISTS idx_si_customer_date ON `tabSales Invoice` (customer, posting_date)")
\`\`\`

### Expected EXPLAIN after patch
| id | select_type | type | rows | key | Extra |
| 1  | SIMPLE      | ref  | 120 | idx_si_customer_date | Using where |
```

## Tools Touched

- [`mariadb-query`](../tools/mariadb-query.yaml) — read-only, runs EXPLAIN
- [`patch-generator`](../tools/patch-generator.yaml) — if proposing DDL
