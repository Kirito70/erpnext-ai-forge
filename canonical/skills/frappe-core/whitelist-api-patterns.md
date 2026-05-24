---
id: whitelist-api-patterns
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Authoring or reviewing any @frappe.whitelist() endpoint in a custom app — especially when allow_guest=True"
scope: [agent:architect, agent:backend-specialist, agent:integrations-specialist, agent:security-reviewer]
foundational: true
domain: frappe-core
security_score: 100
supersedes: []
---

# Whitelist API Patterns

How to author `@frappe.whitelist()` endpoints that pass Security Reviewer on this bench. The bench currently exposes **205 whitelist methods** across 8 custom apps ([`api-surface.json`](../../../discovery/data/api-surface.json)) — every new one inherits the same posture.

## When to Load
- Adding a new `@frappe.whitelist()` method
- Reviewing an existing endpoint for permission gating
- Considering `allow_guest=True` (webhook, public form, etc.)
- Auditing input validation on an existing endpoint

## Key Concepts

1. **Default `@frappe.whitelist()`** — requires a logged-in user; permission checks still need to be **inside** the method.
2. **`allow_guest=True`** — opens the endpoint to anonymous callers. Requires signature verification (webhooks) or rate-limit (public forms). See [AP-002](../../../discovery/data/anti-pattern-findings.json).
3. **`methods=["POST"]`** — pin the HTTP verb; mismatched verbs return 405 instead of silently allowing GET.
4. **Permission check** — `frappe.has_permission(doctype, ptype, doc_name, throw=True)` is the right gate.
5. **Input validation** — type, length, value range. Never trust `frappe.local.form_dict`.
6. **Pagination** — return `{"data": [...], "total": int, "page": int, "limit": int}` envelopes.
7. **Error envelope** — `frappe.throw(_(...))` produces a translated, structured error. Don't `return {"error": ...}` for error states.
8. **CSRF context** — site-wide `ignore_csrf=true` is set ([AP-005](../../../discovery/data/anti-pattern-findings.json)). Treat it as a known finding, not a license to skip CSRF in POS Quasar calls.

## Patterns

### Pattern: Standard logged-in endpoint with permission gate

**When:** A whitelist method that reads or writes business data.

**Do:**
```python
import frappe
from frappe import _

@frappe.whitelist()
def get_deal_addresses(deal_name: str) -> dict:
    """Return billing + shipping addresses linked to a CRM Deal.

    Args:
        deal_name: The CRM Deal ID.

    Returns:
        Dict with `billing` and `shipping` keys, each a list of Address dicts.
    """
    if not isinstance(deal_name, str) or not deal_name:
        frappe.throw(_("deal_name is required"))

    frappe.has_permission("CRM Deal", "read", deal_name, throw=True)

    deal = frappe.get_doc("CRM Deal", deal_name)
    return {
        "billing": _addresses_for(deal, "Billing"),
        "shipping": _addresses_for(deal, "Shipping"),
    }
```

This mirrors the shape of `novizna_crm.api.deals.get_deal_addresses` (one of the 40 endpoints in `novizna_crm`).

**Don't:**
```python
@frappe.whitelist()
def get_deal_addresses(deal_name):
    return frappe.get_doc("CRM Deal", deal_name).as_dict()  # no perm check, no validation
```

### Pattern: Guest endpoint for a webhook receiver

**When:** External vendor posts to our bench (EasyPost, 17Track, Invoice Ninja).

**Do:**
```python
# apps/cargo_management/cargo_management/parcel_management/doctype/parcel/api/easypost_api.py
import hashlib, hmac
import frappe
from frappe import _

@frappe.whitelist(allow_guest=True, methods=["POST"])
def easypost_webhook() -> dict:
    """Verify HMAC, then enqueue the parcel update."""
    raw = frappe.request.get_data()
    sig = frappe.request.headers.get("X-EasyPost-Signature", "")
    secret = frappe.get_single("Cargo Settings").easypost_webhook_secret

    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        frappe.throw(_("Invalid signature"), frappe.AuthenticationError)

    payload = frappe.parse_json(raw)
    frappe.enqueue(
        method="cargo_management.parcel_management.events.handle_easypost_event",
        queue="default", payload=payload,
    )
    return {"ok": True}
```

The current `easypost_webhook` at `cargo_management/.../easypost_api.py:84` is the canonical guest endpoint on this bench. Per [AP-002](../../../discovery/data/anti-pattern-findings.json) it must keep signature verification before any side effect.

**Don't:** `allow_guest=True` with no signature check — automatic D-GUEST-WHITELIST-NO-PERM deduction (HIGH, -25) per [`security-scoring.yaml`](../../policies/security-scoring.yaml).

### Pattern: Guest endpoint for a public form

**When:** Public careers / job application pages — `noviznaerp_payroll/www/careers.py:9`, `job_apply.py:8`, `job_detail.py:5`.

**Do:** rate-limit + CAPTCHA + bounded input:
```python
@frappe.whitelist(allow_guest=True, methods=["POST"])
def apply_for_job(job_id: str, applicant_email: str, resume_url: str) -> dict:
    """Public job application receiver — rate-limited per IP."""
    frappe.rate_limit(key="job_apply", limit=5, seconds=3600)  # 5/hr/IP

    # Bound every input
    if not (5 < len(applicant_email) < 120):
        frappe.throw(_("Invalid email"))
    if not (5 < len(resume_url) < 500):
        frappe.throw(_("Invalid resume URL"))

    # CAPTCHA verified upstream of this call
    ...
```

The three existing guest endpoints in `noviznaerp_payroll/www/` were authored before this rate-limit pattern was canonized — Phase 2 audit will retrofit them.

### Pattern: Pagination envelope

**When:** Endpoint returns a list that may be long (lead / customer / invoice lists).

**Do:**
```python
@frappe.whitelist()
def import_customers_as_leads(page: int = 1, limit: int = 50) -> dict:
    """Paginated customer-import preview."""
    limit = min(int(limit), 200)  # hard cap
    page = max(int(page), 1)
    start = (page - 1) * limit

    rows = frappe.get_list(
        "Customer", fields=["name", "customer_name"],
        limit_start=start, limit_page_length=limit,
        order_by="creation desc",
    )
    total = frappe.db.count("Customer")
    return {"data": rows, "total": total, "page": page, "limit": limit}
```

**Don't:** Return the bare list — frontend has no way to render "more pages exist".

### Pattern: Verb pinning

**Do:** `@frappe.whitelist(methods=["POST"])` for any write endpoint. Mismatched verbs return 405.

**Don't:** Leave methods open — a write endpoint accidentally callable via GET shows up in URL logs in plaintext (leaks query string parameters as referrer).

## Common Pitfalls
- `@frappe.whitelist()` with no permission check inside — silently lets any logged-in user read/write any doc.
- Trusting `frappe.local.form_dict` types — they're always strings. Cast with `cint`, `flt`, etc.
- Returning ORM objects directly — call `.as_dict()` and strip large/private fields.
- `frappe.throw` inside a try/except that swallows it — defeats the framework's error envelope.
- Using `allow_guest=True` for "convenience" in a test endpoint, then forgetting to remove it before deploy.
- Long synchronous work inside an HTTP request path — enqueue it. See [`integrations/queueing-retry-backoff`](../integrations/queueing-retry-backoff.md).

## References
- [`frappe-core/permissions-model`](./permissions-model.md) — for `has_permission` deeper-dive
- [`security/review-checklist`](../security/review-checklist.md) — full reviewer walkthrough
- [`integrations/webhooks`](../integrations/webhooks.md) — for signature verification patterns
- [`discovery/data/api-surface.json`](../../../discovery/data/api-surface.json) — full whitelist inventory
- [`discovery/data/anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json) — AP-002, AP-005
