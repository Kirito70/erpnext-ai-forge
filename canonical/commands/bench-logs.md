---
id: bench-logs
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, devops-deployment]
---

# /bench-logs

Tail / grep bench log files with automatic secret redaction.

## Usage

```
/bench-logs [--source frappe|worker|scheduler|web.error|web.access] [--tail <n>] [--grep <regex>]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--source` | no | Log file. Default: `frappe` |
| `--tail` | no | Lines to read. Default: 200, max: 5000 |
| `--grep` | no | Regex applied after tail |

## Examples

```
/bench-logs --grep "Zoho" --source worker
/bench-logs --source scheduler --tail 500
/bench-logs --source web.error --grep "500"
```

## Pipeline

1. **Architect:** delegate to DevOps (read-only)
2. **DevOps:** invoke [`bench-logs`](../tools/bench-logs.yaml) tool — automatic redaction of secret-name patterns
3. **Architect:** if a specific error pattern appears, suggest the relevant `/explain-hook` or `/optimize-query` follow-up

## Notes

- Read-only. Never rotates or deletes logs.
- Output is capped at 5,000 lines after grep filter
- Lines containing `api_key`, `password`, `token`, `Authorization: Bearer` are redacted

## Tools Touched

- [`bench-logs`](../tools/bench-logs.yaml)
