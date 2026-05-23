---
id: scaffold-api
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, backend-specialist, qa-test-engineer, security-reviewer]
---

# /scaffold-api

Generate a `@frappe.whitelist()` method with input validation, permission check, error envelope, and a test stub.

## Usage

```
/scaffold-api <module.method> [--guest] --inputs "<input-spec>" [--rate-limit <n>/min]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<module.method>` | yes | Dotted Python path (e.g. `novizna_crm.api.leads.bulk_assign`). Must be in a custom app. |
| `--guest` | no | If set, `allow_guest=True` — requires rate-limit AND signature verification per security policy |
| `--inputs` | yes | Comma-separated `name:type` pairs (e.g. `"lead_ids:list,owner:str"`) |
| `--rate-limit` | when `--guest` | Rate limit in calls/minute |

## Example

```
/scaffold-api novizna_crm.api.leads.bulk_assign --inputs "lead_ids:list,owner:str"
```

## Pipeline

1. **Architect:** validate target is in a custom app (not upstream)
2. **Backend Specialist:** scaffold the method with:
   - Type annotations + PEP 257 docstring
   - Input validation block
   - `frappe.has_permission` check
   - Standard error envelope per project pattern
   - Optional rate-limit decorator if `--guest`
3. **QA:** scaffold tests (happy path, missing input, permission denied, [if guest] rate-limit verified)
4. **Security Reviewer:** mandatory review of permission posture, especially for `--guest`
5. **Architect:** synthesize + manual steps

## Notes

- For guest endpoints, see [discovery AP-002](../../discovery/data/anti-pattern-findings.json) and current guest endpoints in [`api-surface.json`](../../discovery/data/api-surface.json)
- The default permission check uses the touched DocType's perm matrix — for non-DocType endpoints, an explicit `frappe.only_for([roles])` is required

## Tools Touched

- [`api-endpoint-tester`](../tools/api-endpoint-tester.yaml) — QA uses for E2E smoke
