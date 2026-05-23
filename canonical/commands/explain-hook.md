---
id: explain-hook
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, backend-specialist]
---

# /explain-hook

Walk through a `hooks.py` entry and trace its full dispatch chain.

## Usage

```
/explain-hook <app> <hook-name>
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<app>` | yes | Custom app name |
| `<hook-name>` | yes | Hook key (e.g. `doc_events`, `scheduler_events`, `override_doctype_class`, `boot_session`) |

## Examples

```
/explain-hook novizna_pos doc_events
/explain-hook invoice_ninja_integration scheduler_events
```

## Pipeline

1. **Architect:** check [`hooks-index.json`](../../discovery/data/hooks-index.json) to confirm the hook is declared
2. **Backend Specialist:** read the hook entry from the app's `hooks.py`, follow each referenced method, summarize:
   - When the hook fires (event, cadence, condition)
   - Each referenced handler — purpose, side effects, idempotency notes
   - Dispatch order if multiple handlers
   - Common pitfalls (commit-in-doc-event, recursion, missing rollback)
3. **Architect:** present as a structured walkthrough

## Output

```markdown
## Hook: <app>.<hook-name>

**Declaration:** apps/<app>/<app>/hooks.py:<line>

**Fires when:** <event description>

### Dispatch chain
1. `<handler-1>` — purpose, side effects, idempotency
2. `<handler-2>` — ...

### Pitfalls observed
- <e.g. handler-1 calls frappe.db.commit() — review for atomicity>
```

## Tools Touched

- [`bench-logs`](../tools/bench-logs.yaml) — to show the hook's recent firings
