---
id: queueing-retry-backoff
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Designing background jobs, scheduler-driven syncs, or retry semantics for any integration or long-running operation"
scope: [agent:architect, agent:integrations-specialist, agent:devops-deployment, agent:frontend-quasar-specialist]
foundational: true
domain: integrations
security_score: 100
supersedes: []
---

# Queueing, Retry, Backoff

The canonical pattern for moving slow work off the request path and surviving transient failures. Used by every vendor sync on the bench (Zoho, HubSpot, Invoice Ninja, Google, LinkedIn, EasyPost, 17Track) and by the Quasar POS offline queue.

## When to Load
- Wrapping a vendor API call so it doesn't block the HTTP request
- Designing retry semantics for a scheduled sync
- Building the POS offline write queue
- Reviewing an integration for sync-vs-async correctness

## Key Concepts

1. **`frappe.enqueue(method, queue=..., timeout=..., now=False, **kwargs)`** — moves work to a background worker.
2. **Queues** — `default`, `short`, `long`. Pick by expected duration; `long` for >60s jobs.
3. **Worker timeout** — default 300s; override per-job. Hitting timeout kills the worker → job lost unless idempotent.
4. **Retry with exponential backoff + jitter** — 2s, 4s, 8s, 16s, 32s. **Max 5 attempts**, then dead-letter.
5. **Dead letter** — failed-after-retry events land in the per-vendor sync log DocType with `status='Failed'`.
6. **Idempotency** — every retried job must be safe to run twice.
7. **`enqueue_doc(doctype, name, method, ...)`** — variant that hydrates the doc on the worker side; avoids serializing a stale doc snapshot.

## Patterns

### Pattern: Enqueue from a request path

**When:** Invoice Ninja sync triggered by a button click.

**Do:**
```python
@frappe.whitelist()
def trigger_invoice_ninja_sync() -> dict:
    """Enqueue an Invoice Ninja two-way sync and return immediately."""
    frappe.has_permission("Invoice Ninja Settings", "write", throw=True)
    job = frappe.enqueue(
        method="invoice_ninja_integration.sync.run_sync",
        queue="long",
        timeout=1800,
        now=False,
    )
    return {"job_id": job.id, "queued_at": frappe.utils.now()}
```

The user sees a fast response; the work happens off-thread.

**Don't:** Inline the sync in the request:
```python
@frappe.whitelist()
def trigger_invoice_ninja_sync():
    return invoice_ninja_integration.sync.run_sync()  # 30s+ — blocks the worker; user sees timeout
```

This is the MEDIUM finding "Network call inside an HTTP request path without `frappe.enqueue`" in [`security/review-checklist`](../security/review-checklist.md).

### Pattern: Retry with exponential backoff + jitter

**When:** A vendor API call may transiently fail (timeout, 5xx, rate-limit 429).

**Do:**
```python
import random, time
import requests
import frappe

DELAYS = [2, 4, 8, 16, 32]  # seconds; jitter applied per attempt
MAX_ATTEMPTS = len(DELAYS)

def call_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """HTTP call with exponential backoff + jitter; 5 attempts max."""
    last_exc: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = requests.request(method, url, timeout=30, **kwargs)
            if resp.status_code < 500 and resp.status_code != 429:
                return resp
            last_exc = RuntimeError(f"HTTP {resp.status_code}")
        except requests.RequestException as e:
            last_exc = e

        delay = DELAYS[attempt] + random.uniform(0, DELAYS[attempt] * 0.25)  # jitter
        time.sleep(delay)

    raise last_exc or RuntimeError("Unknown failure")
```

`429` (rate limited) and `5xx` are retried; `4xx` (auth, validation) are not — they won't fix themselves.

### Pattern: Dead-letter to a sync log

**When:** All retries exhausted; preserve the event for manual replay.

**Do:**
```python
def run_invoice_ninja_sync_for_invoice(invoice_id: str) -> None:
    """Sync one invoice with dead-letter on permanent failure."""
    try:
        result = call_with_retry("POST", f"{BASE}/invoices/{invoice_id}", json=payload)
        _record_log("Done", invoice_id, result.text)
    except Exception as e:
        _record_log("Failed", invoice_id, str(e))
        # Don't re-raise; the job has completed (in failure state)
        # A manual replay tool reads "Failed" rows and re-enqueues them


def _record_log(status: str, invoice_id: str, message: str) -> None:
    frappe.get_doc({
        "doctype": "Invoice Ninja Sync Logs",
        "status": status, "invoice": invoice_id, "message": message,
    }).insert(ignore_permissions=True)  # justified: background context
```

`Invoice Ninja Sync Logs` already exists per [`doctype-index.json`](../../../discovery/data/doctype-index.json) — use it.

### Pattern: Scheduler → enqueue → process

**When:** Nightly sync should not run inline in the scheduler tick.

**Do:**
```python
# hooks.py
scheduler_events = {
    "cron": {
        "0 2 * * *": ["invoice_ninja_integration.sync.schedule_nightly"],
    }
}
```

```python
# sync.py
def schedule_nightly() -> None:
    """Scheduler tick — enqueue the actual sync; return fast."""
    frappe.enqueue("invoice_ninja_integration.sync.run_nightly", queue="long", timeout=3600)

def run_nightly() -> None:
    """The real work; runs on a worker."""
    for invoice in _invoices_to_sync():
        frappe.enqueue("invoice_ninja_integration.sync.run_invoice_ninja_sync_for_invoice",
                       queue="default", timeout=300, invoice_id=invoice.name)
```

Fan-out pattern: one scheduler tick enqueues one worker; that worker enqueues N per-item jobs.

### Pattern: Quasar POS offline queue (frontend mirror)

The same retry shape lives on the Quasar side. See [`frontend/vue3-quasar-patterns`](../frontend/vue3-quasar-patterns.md) — the offline-queue store uses the same `[2000, 4000, 8000, 16000, 32000]` delays and 5-attempt cap.

## Common Pitfalls
- Jobs that mutate state without idempotency keys — re-running creates duplicates.
- Catching exceptions in the worker and not logging — silent failures.
- `queue="default"` for a job that takes >120s — worker starvation; use `queue="long"`.
- Re-enqueueing inside `except` without a backoff cap — runaway loop.
- Dead-letter rows without a replay tool — they accumulate; design replay early.
- Synchronous retry without jitter — synchronized retry storms when a vendor is degraded.
- Retrying 4xx errors — wastes the rate limit; will never succeed without code change.

## References
- [`integrations/oauth-patterns`](./oauth-patterns.md) — auth refresh as a precursor to the call
- [`integrations/webhooks`](./webhooks.md) — webhook receivers enqueue into this pattern
- [`frontend/vue3-quasar-patterns`](../frontend/vue3-quasar-patterns.md) — POS offline queue mirror
- [`debugging/bench-logs`](../debugging/bench-logs.md) — worker.log inspection
- [`tools/bench-logs`](../../tools/bench-logs.yaml) — log surface
