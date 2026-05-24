---
id: migration-patches
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Authoring a one-shot data migration or schema fix-up that runs on `bench migrate`"
scope: [agent:architect, agent:backend-specialist, agent:devops-deployment]
foundational: true
domain: frappe-core
security_score: 100
supersedes: []
---

# Migration Patches

How to author idempotent, rollback-safe Frappe patches that run on `bench migrate`. Used whenever a DocType schema change requires data backfill or a one-shot data transformation is needed.

## When to Load
- Adding fields that need data backfill on existing rows
- Renaming a DocType, field, or naming series
- Migrating Custom Fields from one app to another
- Recovering from an aborted prior migration

## Key Concepts

1. **Patch path** — `apps/<app>/<app>/patches/v16_0_0/<YYYY_MM_DD>_<slug>.py`. Version directory matches Frappe major.
2. **`patches.txt`** — ordered list at `apps/<app>/<app>/patches.txt`. Entries are dotted Python paths. Order matters.
3. **Idempotency** — patches re-run if `bench migrate` is interrupted. Early-return if the migration is already done.
4. **Reload DocType first** — `frappe.reload_doc(...)` before reading/writing fields that the schema change just added.
5. **No commits in patches** — `bench migrate` manages the transaction.
6. **`execute()` entry point** — patches export a module-level `execute()` function with no args.
7. **Rollback-safe drafting** — write patches so partial completion + re-run produces the same final state.

## Patterns

### Pattern: Standard patch skeleton

**When:** New patch for `noviznaerp_payroll`.

**Do:**
```python
# apps/noviznaerp_payroll/noviznaerp_payroll/patches/v16_0_0/2026_05_24_backfill_eobi_policy.py
"""Backfill EOBI Policy default rate for Employees missing the field."""

import frappe

def execute() -> None:
    """Idempotent backfill: only updates rows where eobi_rate is NULL."""
    # Make sure the field exists before we touch it
    frappe.reload_doc("noviznaerp_payroll", "doctype", "eobi_policy")

    # Idempotent guard
    pending = frappe.db.count("EOBI Policy", {"eobi_rate": ("is", "not set")})
    if pending == 0:
        return

    frappe.db.sql(
        """
        UPDATE `tabEOBI Policy`
        SET eobi_rate = %(default_rate)s
        WHERE eobi_rate IS NULL
        """,
        values={"default_rate": 1.0},
    )
```

Add to `apps/noviznaerp_payroll/noviznaerp_payroll/patches.txt`:
```
noviznaerp_payroll.patches.v16_0_0.2026_05_24_backfill_eobi_policy
```

**Don't:** Skip the `pending == 0` guard. Without it, every `bench migrate` re-runs the UPDATE (cheap here, but expensive for large patches and noisy in logs).

### Pattern: Schema change + data backfill in one patch

**When:** New field on `crm_lead_industry` requires computed default from existing fields.

**Do:**
```python
import frappe

def execute() -> None:
    """Add `slug` field on CRM Lead Industry and backfill from industry_name."""
    frappe.reload_doc("novizna_crm", "doctype", "crm_lead_industry")

    rows = frappe.get_all(
        "CRM Lead Industry",
        filters={"slug": ("in", [None, ""])},
        fields=["name", "industry_name"],
    )
    if not rows:
        return

    for row in rows:
        slug = frappe.utils.scrub(row.industry_name).replace(" ", "-").lower()
        frappe.db.set_value(
            "CRM Lead Industry", row.name, "slug", slug, update_modified=False,
        )
```

`update_modified=False` keeps `modified` timestamps intact so audit logs aren't polluted.

### Pattern: Patch ordering with cross-app dependency

**When:** Patch A in `novizna_crm` depends on a field added by patch B in `novizna_core`.

**Do:** Order in `patches.txt` puts B first within `novizna_core`, and the app load order via `required_apps` in hooks.py ensures `novizna_core` migrates first. Per [`apps-index.json`](../../../discovery/data/apps-index.json), `novizna_core` already declares `requires: [erpnext_location]`.

### Pattern: Rename a DocType

**When:** Renaming `cash_variance_entry` → `pos_cash_variance_entry`.

**Do (use Frappe's built-in helper):**
```python
import frappe
from frappe.model.rename_doc import rename_doc

def execute() -> None:
    """Rename DocType from Cash Variance Entry to POS Cash Variance Entry."""
    if not frappe.db.exists("DocType", "Cash Variance Entry"):
        return  # idempotent — already renamed
    rename_doc("DocType", "Cash Variance Entry", "POS Cash Variance Entry", force=True)
    frappe.reload_doctype("POS Cash Variance Entry")
```

**Don't:** Do raw SQL `ALTER TABLE` or `UPDATE tabDocType` — misses naming series, perms, dependent fields.

### Pattern: Conditional patch for fixture-installed apps

**When:** Patch only applies if a sibling app is installed.

**Do:**
```python
def execute() -> None:
    """Skip if invoice_ninja_integration is not installed in this site."""
    if "invoice_ninja_integration" not in frappe.get_installed_apps():
        return
    ...
```

## Common Pitfalls
- Forgetting `frappe.reload_doc(...)` before touching a newly-added field — schema cache returns old definition; writes silently no-op.
- Calling `frappe.db.commit()` inside the patch — `bench migrate` wraps everything in one transaction; commits break rollback.
- Patch path doesn't match the entry in `patches.txt` — silently skipped (no error). Always grep both after authoring.
- Patch raises an exception → `bench migrate` aborts mid-flight; next attempt starts from the failed patch. Idempotency is what saves you.
- Using f-string SQL — same SQL injection rule applies inside patches. See [`data/sql-best-practices`](../data/sql-best-practices.md) and [AP-001](../../../discovery/data/anti-pattern-findings.json).
- Long-running patch with no progress logging — developer thinks `bench migrate` hung. Use `frappe.utils.update_progress_bar` or periodic `print` statements for patches that loop over many rows.

## References
- [`frappe-core/doctype-authoring`](./doctype-authoring.md) — for the DocType change that motivates the patch
- [`tools/patch-generator`](../../tools/patch-generator.yaml) — scaffolds the patch file + `patches.txt` entry
- [`tools/bench-migrate`](../../tools/bench-migrate.yaml) — to run after authoring
- [`data/sql-best-practices`](../data/sql-best-practices.md) — for the parameterized SQL rule
