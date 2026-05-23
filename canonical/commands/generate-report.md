---
id: generate-report
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, backend-specialist, security-reviewer]
---

# /generate-report

Scaffold a Script Report or Query Report.

## Usage

```
/generate-report <Report Name> --type script|query --doctype <Reference DocType> [--app <custom-app>]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<Report Name>` | yes | Display name |
| `--type` | yes | `script` for Python-backed reports; `query` for SQL-only reports |
| `--doctype` | yes | The reference DocType the report queries |
| `--app` | no | Custom app target. Defaults to the app that owns the reference DocType (rejected if upstream) |

## Examples

```
/generate-report "Aged Receivables by Branch" --type script --doctype "Sales Invoice"
/generate-report "Cargo Manifests by Status" --type query --doctype "Cargo Manifest" --app cargo_management
```

## Pipeline

1. **Architect:** validate target app is custom; identify the DocType
2. **Backend Specialist (Reports cluster loaded):**
   - For Script Report: module with `execute(filters)` returning `(columns, data)`, columns spec, filter schema with linked DocTypes
   - For Query Report: SQL file with parameterized filters
   - Permissions block restricting to appropriate roles
3. **Security Reviewer (mandatory for raw SQL):** verify no f-string interpolation; verify role restriction; verify column data doesn't leak fields the role isn't permitted to see
4. **Architect:** synthesize + manual steps (`bench --site novizna-v16 migrate` to register, then it's visible in Report list)

## Notes

- Script Reports are preferred when the logic isn't expressible in a single SQL query, or when permissions need per-row filtering
- Query Reports are preferred when the SQL is straightforward and you want to leverage Frappe's UI filter rendering

## Tools Touched

- [`mariadb-query`](../tools/mariadb-query.yaml) — Security Reviewer uses for EXPLAIN
