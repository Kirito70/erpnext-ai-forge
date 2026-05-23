---
id: sync-erpnext
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, integrations-specialist, devops-deployment]
---

# /sync-erpnext

Run the existing `novizna_crm.api.erpnext_sync` workflow with safety checks.

## Usage

```
/sync-erpnext [--dry-run] [--scope customers|quotations|all]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--dry-run` | no | Compute the diff but do not write |
| `--scope` | no | Limit to one entity type. Default: `all` |

## Example

```
/sync-erpnext --dry-run --scope customers
```

## Pipeline

1. **Architect:** delegate to Integrations Specialist
2. **Integrations Specialist:**
   - Confirm the sync method exists in `apps/novizna_crm/novizna_crm/api/erpnext_sync.py`
   - Invoke via [`api-endpoint-tester`](../tools/api-endpoint-tester.yaml) (or `bench-console` for direct call) with `--dry-run` first
   - Report counts (new, updated, conflicts)
3. **DevOps:** if `--dry-run` was clean and developer types the site name, run the live sync
4. **Architect:** synthesize sync report + `CRM Import Log` reference for audit trail

## Notes

- Live sync writes to ERPNext DocTypes (Customer, Quotation, etc.). The Integrations Specialist confirms upstream-guard compliance: erpnext-sync writes to DocType *instances*, not to upstream app code, so it's allowed.
- Sync errors land in `CRM Import Log` per the app's existing pattern

## Tools Touched

- [`api-endpoint-tester`](../tools/api-endpoint-tester.yaml)
- [`bench-console`](../tools/bench-console.yaml)
- [`bench-logs`](../tools/bench-logs.yaml) — verify worker log shows expected activity
