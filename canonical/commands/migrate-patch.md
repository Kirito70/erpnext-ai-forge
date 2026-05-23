---
id: migrate-patch
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, backend-specialist, devops-deployment]
---

# /migrate-patch

Create a correctly-numbered, idempotent Frappe patch and add it to `patches.txt`.

## Usage

```
/migrate-patch <app> <description>
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<app>` | yes | Custom app target (rejected for upstream apps) |
| `<description>` | yes | One-line description used for the patch slug and docstring |

## Example

```
/migrate-patch novizna_crm "backfill industry on existing leads"
```

## Pipeline

1. **Architect:** validate app is custom; classify as schema change or data backfill
2. **Backend Specialist:** invoke [`patch-generator`](../tools/patch-generator.yaml):
   - File at `apps/<app>/<app>/patches/v16_0_0/YYYY_MM_DD_<slug>.py`
   - Template enforces: `execute()` function, docstring, `frappe.reload_doc()` when DocType is touched, idempotency guard
   - `patches.txt` entry appended in correct version section
3. **DevOps:** runbook section with `bench --site novizna-v16 migrate` command
4. **Architect:** synthesize + document closing (CHANGELOG line in `feat`/`fix` form depending on intent)

## Idempotency Pattern

Every patch must be safe to re-run:

```python
def execute():
    """Backfill industry on existing leads (idempotent)."""
    leads_missing_industry = frappe.get_all(
        "CRM Lead",
        filters={"industry": ["is", "not set"]},
        pluck="name",
    )
    if not leads_missing_industry:
        return  # already applied
    for name in leads_missing_industry:
        # ... backfill logic
        frappe.db.commit()  # OK in a patch — explicit transactional boundary
```

## Tools Touched

- [`patch-generator`](../tools/patch-generator.yaml) (requires_confirmation: true)
- [`bench-migrate`](../tools/bench-migrate.yaml)
