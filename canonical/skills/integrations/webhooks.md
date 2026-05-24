---
id: webhooks
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Authoring or reviewing an inbound webhook receiver (EasyPost, 17Track, Invoice Ninja, Stripe-style)"
scope: [agent:architect, agent:integrations-specialist, agent:security-reviewer]
foundational: true
domain: integrations
security_score: 100
supersedes: []
---

# Webhook Receivers

How to write webhook receivers that verify signatures, rate-limit, log, and dispatch safely. Grounded in the two existing webhook receivers on this bench: **EasyPost** (`cargo_management/.../easypost_api.py:84`) and **17Track** (`cargo_management — webhook_17track`).

## When to Load
- Adding a webhook receiver for a new vendor
- Reviewing an existing receiver for the AP-002 finding (guest endpoint without protection)
- Investigating a webhook failure (signature mismatch, retries, duplicates)

## Key Concepts

1. **`allow_guest=True`** — required because the vendor has no Frappe session. **Always** paired with signature verification.
2. **Signature verification first** — before any DB read, before any log write. If signature fails, return 401.
3. **HMAC-SHA256 is the common pattern** — `hmac.compare_digest` for constant-time comparison.
4. **Idempotency keys** — many vendors retry on transient errors; record event_id and short-circuit duplicates.
5. **Enqueue, don't process** — the receiver returns 200 quickly; the actual work happens in a background job.
6. **Rate-limit** — even with signature, rate-limit per-IP to absorb retry storms.
7. **Log to a sync log DocType** — every arrival (whether processed or rejected) goes into the per-app log.

## Patterns

### Pattern: HMAC-verified webhook receiver

**When:** EasyPost webhook for parcel status updates.

**Do:**
```python
# apps/cargo_management/cargo_management/parcel_management/doctype/parcel/api/easypost_api.py
import hashlib, hmac
import frappe
from frappe import _

@frappe.whitelist(allow_guest=True, methods=["POST"])
def easypost_webhook() -> dict:
    """Receive EasyPost tracking updates. Verify signature, log, enqueue."""

    # 1. Read raw body BEFORE parsing (signature is over the raw bytes)
    raw = frappe.request.get_data()
    sig = frappe.request.headers.get("X-EasyPost-Signature", "")

    # 2. Rate-limit per source IP
    frappe.rate_limit(key="easypost_webhook", limit=100, seconds=60)

    # 3. Verify signature BEFORE any side effect
    secret = frappe.get_single("Cargo Settings").easypost_webhook_secret
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        # Log the failure (with sig+ip but never the secret)
        frappe.log_error(
            title="EasyPost signature mismatch",
            message=f"ip={frappe.local.request_ip} got_sig={sig[:8]}...",
        )
        frappe.throw(_("Invalid signature"), frappe.AuthenticationError)

    payload = frappe.parse_json(raw)
    event_id = payload.get("id")

    # 4. Idempotency — short-circuit if we've seen this event
    if event_id and frappe.db.exists("Parcel Sync Log", {"event_id": event_id}):
        return {"ok": True, "duplicate": True}

    # 5. Log the arrival
    frappe.get_doc({
        "doctype": "Parcel Sync Log",
        "vendor": "EasyPost",
        "event_id": event_id,
        "raw_payload": frappe.as_json(payload),
        "status": "Received",
    }).insert(ignore_permissions=True)  # justified: webhook arrives without Frappe user context

    # 6. Enqueue the actual work
    frappe.enqueue(
        method="cargo_management.parcel_management.events.handle_easypost_event",
        queue="default", timeout=300, payload=payload,
    )

    return {"ok": True}
```

**Don't (AP-002 lineage):**
```python
@frappe.whitelist(allow_guest=True)
def easypost_webhook():
    payload = frappe.parse_json(frappe.request.get_data())
    parcel = frappe.get_doc("Parcel", payload["tracking_code"])  # side effect before any verification
    parcel.status = payload["status"]
    parcel.save()
```

This is the kind of pattern that puts AP-002 at MEDIUM in [`anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json) — `allow_guest=True` with no verification.

### Pattern: Signature verification for the 17Track variant

**When:** 17Track uses a different signature scheme (often `X-17track-Sign` MD5 of `body+secret`).

**Do:** Read the vendor's docs; isolate the verification in a small helper:
```python
def _verify_17track_signature(raw: bytes, sig: str, secret: str) -> bool:
    expected = hashlib.md5(raw + secret.encode()).hexdigest()
    return hmac.compare_digest(expected, sig)
```

Each vendor differs. The pattern is constant: read raw → derive expected → constant-time compare → reject on mismatch.

### Pattern: Idempotency log DocType

**Do:** Each integration owns a sync log DocType (e.g., `Parcel Sync Log`, `Invoice Ninja Sync Logs` — the latter already exists per [`doctype-index.json`](../../../discovery/data/doctype-index.json)). Schema:

```
event_id   (Data, unique, search_index)
vendor     (Data)
received_at (Datetime, default now)
status     (Select: Received, Processing, Done, Failed)
raw_payload (Long Text)
error      (Long Text)
```

The unique `event_id` index makes duplicate detection O(1).

### Pattern: Background processor

**When:** The enqueued job that does the actual work.

**Do:**
```python
def handle_easypost_event(payload: dict) -> None:
    """Apply an EasyPost tracking update to the matching Parcel."""
    tracking_code = payload.get("result", {}).get("tracking_code")
    parcel_name = frappe.db.get_value("Parcel", {"tracking_id": tracking_code})
    if not parcel_name:
        return  # parcel may belong to another tenant / unknown
    frappe.db.set_value("Parcel", parcel_name, "status", payload["result"]["status"])
```

Background processors are the right place for `frappe.db.set_value` / `ignore_permissions=True` patterns because they run outside a user request context.

## Common Pitfalls
- Parsing the JSON body before computing signature — signature is over the raw bytes; `json.dumps(parsed)` produces different bytes (key order, whitespace).
- Returning a non-200 on duplicate events — vendor will retry forever. Return 200 with `duplicate: True`.
- Logging the raw signature secret in error messages — leaks the secret. Log only the prefix or hash.
- Synchronous processing in the request — vendor timeout (often 5–10s) triggers retries and double-processing.
- Same `allow_guest=True` whitelist used for both webhooks and a public dashboard — make them separate methods so signature checks aren't conditional.
- `frappe.local.request_ip` behind a reverse proxy without `X-Forwarded-For` honoring — rate limit miscounts.

## References
- [`integrations/oauth-patterns`](./oauth-patterns.md) — for the outbound counterpart
- [`integrations/queueing-retry-backoff`](./queueing-retry-backoff.md) — for the background job semantics
- [`frappe-core/whitelist-api-patterns`](../frappe-core/whitelist-api-patterns.md) — for `@frappe.whitelist(allow_guest=True, methods=["POST"])`
- [`security/review-checklist`](../security/review-checklist.md) — for the AP-002 review
- [`discovery/data/integrations-map.json`](../../../discovery/data/integrations-map.json) — current webhook endpoints
- [`discovery/data/anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json) — AP-002
