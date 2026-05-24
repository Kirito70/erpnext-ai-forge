---
id: bench-logs
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Investigating any production issue — failed request, missed scheduler tick, worker timeout, slow query, socket error"
scope: [agent:architect, agent:backend-specialist, agent:integrations-specialist, agent:devops-deployment]
foundational: true
domain: debugging
security_score: 100
supersedes: []
---

# Bench Logs and Diagnostics

The diagnostic surface for the Novizna v16 bench. Covers the 3 main log files, `frappe.log_error`, the slow query log, and socketio errors. Loaded by every agent that needs to investigate runtime behavior.

## When to Load
- A whitelist endpoint returns 500
- A scheduler entry didn't fire
- A background job timed out
- Realtime / socketio updates aren't reaching the client
- Investigating an AP-001 / AP-002 / AP-003 / AP-004 recurrence in production

## Key Logs

| Log | Path (bench root relative) | Contents |
|-----|---------------------------|----------|
| App requests | `logs/frappe.log` | HTTP request handlers, `frappe.log_error` writes, traceback |
| Workers | `logs/worker.log` | `frappe.enqueue`-d jobs, retry attempts, dead-letters |
| Scheduler | `logs/scheduler.log` | scheduler ticks, dispatched job names |
| Web server | `logs/web.log` | Gunicorn/Werkzeug request log (status codes, latencies) |
| Socketio | `logs/socketio.log` | Realtime subscriber events |
| MariaDB slow | `/var/log/mysql/mariadb-slow.log` | Slow queries (see [`data/mariadb-debugging`](../data/mariadb-debugging.md)) |
| Frappe `Error Log` DocType | inside DB; visible at `/app/error-log` | `frappe.log_error` titles + bodies |

## Patterns

### Pattern: Tail logs for a failing request

**When:** A user reports `novizna_crm.api.deals.get_deal_addresses` returns 500.

**Do:**
```bash
# Terminal 1 — tail app log
tail -F logs/frappe.log | grep -E "deals|ERROR"

# Terminal 2 — reproduce
bench --site novizna-v16 execute novizna_crm.api.deals.get_deal_addresses --kwargs "{'deal_name':'DEAL-1'}"
```

Look for the traceback in `frappe.log` and cross-reference the `Error Log` DocType (sometimes errors are written there with more structured fields than the file log).

### Pattern: Inspect worker log for a stuck job

**When:** A queued job (e.g., Invoice Ninja sync) doesn't complete.

**Do:**
```bash
tail -F logs/worker.log | grep -E "invoice_ninja|ERROR|Traceback"

# List in-flight jobs
bench --site novizna-v16 console
>>> import frappe
>>> from frappe.utils.background_jobs import get_jobs
>>> for j in get_jobs(site='novizna-v16'):
...     print(j.id, j.status, j.func_name)
```

If a job is stuck in `started` for an unreasonable time, the worker likely OOM-killed. Restart workers via DevOps (`bench restart`) — requires typed `novizna-v16` confirmation.

### Pattern: Scheduler debugging — "my cron didn't fire"

**When:** A `scheduler_events.cron` entry added to `hooks.py` doesn't run.

**Do:**
```bash
# Check the scheduler is running
bench --site novizna-v16 doctor

# Tail scheduler log
tail -F logs/scheduler.log

# Verify the entry is in Frappe's scheduler index (after restart)
bench --site novizna-v16 console
>>> from frappe.utils.scheduler import is_scheduler_disabled
>>> is_scheduler_disabled()
False
>>> from frappe.utils.background_jobs import get_jobs_per_method
>>> # inspect
```

If the entry isn't visible: did you `bench restart` after editing `hooks.py`? (Common forgotten step — DevOps reminder.)

### Pattern: Writing log_error with safe content

**When:** Logging a vendor error in a connector.

**Do:**
```python
frappe.log_error(
    title="Zoho fetch failed",
    message=f"status={resp.status_code} url={url} body_prefix={resp.text[:120]}",
)
```

Writes to:
1. The `Error Log` DocType (visible at `/app/error-log` for admins)
2. `logs/frappe.log` if app-side logging is wired

**Don't:**
```python
frappe.log_error(title="Zoho", message=str(resp.headers) + resp.text)
# Headers may echo Authorization; body may echo client_secret
```

See [`security/secrets-handling`](../security/secrets-handling.md).

### Pattern: Socketio diagnostics

**When:** Frappe Desk shows stale data; realtime updates aren't arriving.

**Do:**
```bash
tail -F logs/socketio.log

# Verify the redis broker is up (socketio uses redis_socketio)
bench --site novizna-v16 console
>>> import frappe
>>> frappe.cache().ping()
True
```

Common cause: `redis_socketio` worker died (in Procfile). DevOps restarts via `bench restart`.

### Pattern: Slow query identification

**When:** A page is slow; you suspect DB.

**Do:**
```bash
# Tail slow log during repro
sudo tail -F /var/log/mysql/mariadb-slow.log

# Identify offenders
sudo pt-query-digest /var/log/mysql/mariadb-slow.log | head -100
```

Then `EXPLAIN` the offender per [`data/mariadb-debugging`](../data/mariadb-debugging.md).

### Pattern: Reproducing in a Frappe REPL

**When:** Need to test a function with real DB state.

**Do:**
```bash
bench --site novizna-v16 console
>>> import frappe
>>> frappe.set_user("admin@example.com")
>>> from novizna_crm.api.deals import get_deal_addresses
>>> get_deal_addresses("DEAL-PROBLEMATIC-1")
```

This is faster than browser repro; output goes straight to your terminal.

## Common Pitfalls
- `tail` (not `tail -F`) on a log that rotates — stops following after rotation.
- Looking only at `frappe.log` when the error happened in a worker — check `worker.log`.
- Increasing log verbosity in production via `developer_mode: 1` — performance cost is significant.
- Reading the `Error Log` DocType via SQL — slow on large logs. Use the `/app/error-log` UI with filters.
- `bench restart` to clear logs — restarts processes; doesn't truncate logs. Use logrotate for that.
- Forgetting to check the scheduler is enabled in `common_site_config.json` — if `pause_scheduler: 1` is set, nothing fires.

## References
- [`tools/bench-logs`](../../tools/bench-logs.yaml) — surface the relevant log
- [`tools/bench-console`](../../tools/bench-console.yaml) — for REPL repro
- [`data/mariadb-debugging`](../data/mariadb-debugging.md) — slow query follow-up
- [`security/secrets-handling`](../security/secrets-handling.md) — safe log content rules
- [`integrations/queueing-retry-backoff`](../integrations/queueing-retry-backoff.md) — for worker / retry context
