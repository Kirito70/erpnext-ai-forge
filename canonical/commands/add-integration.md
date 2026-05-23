---
id: add-integration
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, integrations-specialist, security-reviewer, qa-test-engineer]
---

# /add-integration

Scaffold a new vendor integration: connector class + Settings DocType + optional webhook handler + optional scheduler entry.

## Usage

```
/add-integration <vendor> --auth oauth2|api-key|basic [--webhook] [--scheduler <cron>]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<vendor>` | yes | Vendor identifier (e.g. `pipedrive`, `salesforce`) |
| `--auth` | yes | Auth model |
| `--webhook` | no | Scaffold a webhook handler with signature verification |
| `--scheduler` | no | Cron expression for periodic sync (e.g. `"0 2 * * *"`) |

## Example

```
/add-integration pipedrive --auth oauth2 --webhook --scheduler "0 2 * * *"
```

## Pipeline

1. **Architect:** confirm directory split per [Decision 18](../../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md): vendor SDK in `apps/novizna_crm/novizna_crm/connectors/<vendor>.py`, orchestration in `apps/novizna_crm/novizna_crm/api/<vendor>_sync.py`
2. **Integrations Specialist:**
   - Scaffold connector class with `__init__`, auth helper, `fetch_X` / `push_Y` method placeholders
   - Scaffold `<Vendor> Settings` Singleton DocType (encrypted token field, last_sync_at)
   - If `--webhook`: scaffold guest handler with signature verification first
   - If `--scheduler`: suggest `hooks.py` `scheduler_events` entry
3. **Security Reviewer:** mandatory — verify secret handling, signature verification, retry posture
4. **QA:** scaffold tests with mocked HTTP layer
5. **Architect:** synthesize + manual setup steps (where to put API token in Settings DocType)
6. **Documentation sub-phase:** append to `apps/novizna_crm/CLAUDE.md` Integrations Map

## Tools Touched

- [`doctype-scaffolder`](../tools/doctype-scaffolder.yaml) — for Settings DocType
- [`api-endpoint-tester`](../tools/api-endpoint-tester.yaml) — QA smoke
