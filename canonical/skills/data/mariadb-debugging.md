---
id: mariadb-debugging
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Investigating slow Frappe pages, list views, or reports backed by MariaDB"
scope: [agent:architect, agent:backend-specialist]
foundational: false
domain: data
security_score: 100
supersedes: []
---

# MariaDB Debugging (Novizna v16)

How to find and fix slow queries against `tab<DocType>` tables on this bench's MariaDB instance. Covers slow query log, `EXPLAIN`, indexing rules, and Frappe's auto-index conventions.

## When to Load
- A list view, Report, or whitelist endpoint is slow
- A new query is being designed against a large table (Sales Invoice, Salary Slip, GL Entry)
- A scheduled task is timing out
- Reviewing a `frappe.db.sql` for index awareness

## Key Concepts

1. **Slow query log** — MariaDB-side log of queries above a threshold. On this bench typically at `/var/log/mysql/mariadb-slow.log` (verify in your environment).
2. **`EXPLAIN`** — prepend to any SELECT to see access type, key used, rows examined.
3. **Access types (best → worst)** — `const`, `eq_ref`, `ref`, `range`, `index`, `ALL` (full scan, avoid).
4. **Frappe auto-indexed columns** — `name` (PRIMARY), `creation`, `modified`, `parent` (child tables), any field with `search_index: 1` in DocType JSON.
5. **Composite indexes** — multi-column. Order matters: `(customer, posting_date)` serves queries filtering by customer (with or without posting_date), but NOT queries filtering only by posting_date.
6. **MariaDB default collation** — typically `utf8mb4_unicode_ci` (case-insensitive). String compares ignore case.
7. **`LIMIT` does not skip work** — `LIMIT 10` on an unindexed `ORDER BY` still scans the whole table to find the top 10.

## Patterns

### Pattern: Reading the slow query log

**When:** A page is taking >2s and you suspect a query.

**Do:**
```bash
# Verify the log path from MariaDB config
mysql -u root -p -e "SHOW VARIABLES LIKE 'slow_query_log_file';"

# Tail it during page load reproduction
sudo tail -F /var/log/mysql/mariadb-slow.log

# Aggregate top offenders (requires percona-toolkit)
sudo pt-query-digest /var/log/mysql/mariadb-slow.log | head -100
```

The bench's `bench-logs` tool can surface app-side timings; this skill is the MariaDB-side counterpart.

### Pattern: `EXPLAIN` walkthrough

**When:** A query in `noviznaerp_payroll/.../loan_register/loan_register.py:111` is slow.

**Do:**
```sql
EXPLAIN SELECT name, total_payment, status
FROM `tabLoan`
WHERE status = 'Disbursed' AND posting_date BETWEEN '2026-01-01' AND '2026-05-24'
ORDER BY posting_date DESC LIMIT 100;
```

Reading the output:

| Column | What to look for |
|--------|------------------|
| `type` | `ALL` = full scan (bad); `range`/`ref` = OK; `const`/`eq_ref` = ideal |
| `possible_keys` | Indexes MariaDB considered |
| `key` | Index actually used (NULL = none, full scan) |
| `rows` | Estimated rows examined; should be ≪ table size |
| `Extra` | `Using filesort` and `Using temporary` are red flags |

If `key` is NULL and `rows` is large → missing index. Add one or rewrite the query to hit an existing index.

### Pattern: When to add a composite index

**When:** A list view repeatedly filters on `(customer, posting_date)` for Sales Invoice.

**Do:** Add a Property Setter or DocType change to mark `customer` with `search_index: 1` (if not already), and add a composite index via migration:

```python
# Migration patch — apps/<custom_app>/.../patches/v16_0_0/2026_05_24_add_si_customer_date_index.py
import frappe

def execute() -> None:
    """Add composite index on Sales Invoice (customer, posting_date) for list view perf."""
    idx_name = "idx_si_customer_posting_date"
    rows = frappe.db.sql(
        """SELECT 1 FROM information_schema.statistics
           WHERE table_schema = DATABASE() AND table_name = 'tabSales Invoice'
             AND index_name = %(idx)s LIMIT 1""",
        values={"idx": idx_name},
    )
    if rows:
        return
    frappe.db.sql(
        """ALTER TABLE `tabSales Invoice`
           ADD INDEX idx_si_customer_posting_date (customer, posting_date)"""
    )
```

The idempotent guard is critical — patches re-run on interruption. See [`frappe-core/migration-patches`](../frappe-core/migration-patches.md).

**Don't:** Add a composite index speculatively — every index slows writes. Profile first; index second.

### Pattern: Avoiding `Using filesort` on `ORDER BY`

**When:** `ORDER BY posting_date DESC` shows `Using filesort` in EXPLAIN.

**Do:** Add an index that includes the ORDER BY column **last**:
- Query: `WHERE customer = X ORDER BY posting_date DESC`
- Index: `(customer, posting_date)` — MariaDB walks the index in reverse for the matching `customer`, no filesort needed.

### Pattern: Case-insensitivity gotcha

**When:** Query for `email = 'Foo@Example.COM'` returns rows with `foo@example.com` — and you didn't expect that.

This is MariaDB's default `utf8mb4_unicode_ci` collation. Email lookups silently merge case variants.

**Do:** If you need exact case matching (rare), `WHERE email COLLATE utf8mb4_bin = %(email)s` — but accept the index won't be used. Better: normalize on write.

## Frappe-Specific Indexing Behaviors

- **Set `search_index: 1`** in DocType JSON on any column you'll filter / join on heavily. Frappe creates the index on next `bench migrate`.
- **`unique: 1`** also adds a unique index.
- **Child table queries** that use `WHERE parent = %(parent)s` are already indexed (auto on `parent`).
- **`name` column** is the PRIMARY KEY — never needs a separate index.

## Common Pitfalls
- Adding an index then forgetting `bench migrate` — DocType JSON change isn't synced.
- Adding indexes to small tables (<10k rows) — adds write cost with no read benefit.
- Indexing low-cardinality columns (e.g., `status` with 3 values) alone — MariaDB ignores low-selectivity single-column indexes. Pair with a high-cardinality column in a composite.
- Running `EXPLAIN` on a query with literal values then expecting the same plan with bindings — usually the same, but verify.
- Reading the slow log via raw `cat` over a network mount — use `tail -F` locally.
- Forgetting that `LIMIT 1` doesn't help if there's no `ORDER BY` on an indexed column (MariaDB picks the first matching row, which may be from any disk position).

## References
- [`data/sql-best-practices`](./sql-best-practices.md) — for query authoring rules
- [`frappe-core/migration-patches`](../frappe-core/migration-patches.md) — for adding indexes idempotently
- [`tools/mariadb-query`](../../tools/mariadb-query.yaml) — for read-only EXPLAIN runs
- [`debugging/bench-logs`](../debugging/bench-logs.md) — for app-side timing
- MariaDB EXPLAIN docs: https://mariadb.com/kb/en/explain/
