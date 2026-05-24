---
id: secrets-handling
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Any code that touches site_config.json, frappe.conf, encryption_key, or any vendor secret"
scope: [agent:architect, agent:security-reviewer, agent:integrations-specialist, agent:devops-deployment]
foundational: true
domain: security
security_score: 100
supersedes: []
---

# Secrets Handling

Hard rules for secret-bearing code on this bench. Per Decision 12 and v0.2 §8.5, **values from `site_config.json` never enter model context** — only key names. The 8 keys present on this bench are catalogued in [`site-config-keys.json`](../../../discovery/data/site-config-keys.json).

## When to Load
- Any code touching `frappe.conf`, `frappe.local.conf`, `site_config.json`, or `.env`
- Storing or reading a vendor API token
- Authoring log messages that include vendor responses
- Designing a Settings DocType with credentials

## Key Concepts

1. **Site config holds DB + encryption_key only** — per [`site-config-keys.json`](../../../discovery/data/site-config-keys.json), the 8 keys are: `db_host`, `db_name`, `db_password`, `db_port`, `db_type`, `db_user`, `encryption_key`, `user_type_doctype_limit`. Integration credentials live in Settings DocTypes.
2. **Never read values into output** — `print(frappe.conf)`, `frappe.log_error(message=frappe.local.conf)`, repr-ing the conf dict — all forbidden.
3. **Settings DocType `Password` fields** — Frappe encrypts at-rest using `encryption_key`.
4. **`get_decrypted_password(doctype, name, fieldname)`** — the only legitimate read path for an encrypted field.
5. **Log scrubbing** — log messages with substrings matching `api_key=`, `token=`, `password=`, `bearer `, or PEM headers must be scrubbed by the log writer.
6. **gitleaks pre-commit** — repo-level scan blocks commits that contain secret-shaped strings.

## The 8 Keys in this Bench's site_config.json

(Names only, per [`site-config-keys.json`](../../../discovery/data/site-config-keys.json).)

| Key | Why it exists | Read posture |
|-----|---------------|--------------|
| `db_host` | DB connection | Frappe internals only |
| `db_name` | DB connection | Frappe internals only |
| `db_password` | DB connection | **NEVER read** |
| `db_port` | DB connection | Frappe internals only |
| `db_type` | DB connection | Frappe internals only |
| `db_user` | DB connection | Frappe internals only |
| `encryption_key` | Encrypts `Password` fields | **NEVER read** |
| `user_type_doctype_limit` | License-side limit | Read OK |

Note: integration credentials (Zoho, Google, LinkedIn, HubSpot, Invoice Ninja) are **not** in site config — they live in Settings DocTypes.

## Patterns

### Pattern: Decrypted read from a Settings DocType

**When:** Calling a vendor API.

**Do:**
```python
from frappe.utils.password import get_decrypted_password

token = get_decrypted_password("Zoho Settings", "Zoho Settings", "access_token")
```

**Don't:**
```python
settings = frappe.get_single("Zoho Settings")
token = settings.access_token  # returns "*****" (placeholder) for Password fields
```

Frappe redacts `Password` fields on direct attribute access by design — forces you to use the explicit helper.

### Pattern: Safe error logging from vendor responses

**When:** A vendor 4xx/5xx response needs logging.

**Do:**
```python
# Log status and a short prefix; never the raw body (may echo the secret)
frappe.log_error(
    title="Zoho refresh failed",
    message=f"status={resp.status_code} body_prefix={resp.text[:120]}",
)
```

**Don't:**
```python
frappe.log_error(title="Zoho", message=resp.text)
# Vendor error bodies sometimes contain "your client_secret 'abc...' is invalid"
```

### Pattern: Conditional read of a non-secret site config value

**When:** Need `user_type_doctype_limit`.

**Do:**
```python
limit = frappe.conf.get("user_type_doctype_limit", 0)
```

The other 7 keys never need to be read by app code — Frappe accesses them internally.

### Pattern: Settings DocType field declaration

**When:** Adding `easypost_webhook_secret` to `Cargo Settings`.

**Do:**
```json
{ "fieldname": "easypost_webhook_secret", "fieldtype": "Password", "label": "EasyPost Webhook Secret" }
```

`fieldtype: "Password"` triggers Frappe's at-rest encryption. Plain `Data` would store the secret in cleartext in `tabCargo Settings`.

**Don't:**
```json
{ "fieldname": "easypost_webhook_secret", "fieldtype": "Data" }
```

### Pattern: Scrubbed exception in user-facing message

**When:** An OAuth refresh fails and the user clicks "Reconnect".

**Do:**
```python
frappe.throw(_("Reconnect failed. Check Zoho Settings."))  # generic
# Detailed message goes to the (admin-only) Error Log via frappe.log_error
```

**Don't:**
```python
frappe.throw(f"Zoho says: {resp.text}")  # may surface client_secret to a non-admin user
```

### Pattern: gitleaks pre-commit

**Do (in `.pre-commit-config.yaml` at the repo root):**
```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
```

Scans every commit for secret-shaped strings. If a secret slips through and is committed, **rotate immediately** — never just rewrite history. The exposure window is the moment the commit existed on a developer's machine.

## What Triggers D-READ-SITE-CONFIG (CRITICAL, -50)

Any of the following inside a non-test file is a CRITICAL finding:

- `frappe.conf` (without `.get(specific_key)`)
- `frappe.local.conf` (without `.get(specific_key)`)
- `open("sites/.../site_config.json").read()`
- `print(...)` or `frappe.log_error(message=...)` with the raw conf dict
- `json.dumps(frappe.conf)`

## Common Pitfalls
- Logging `**kwargs` of a function that includes `password=...`.
- Catching an exception and `frappe.log_error(message=str(e))` where the exception args include the secret.
- Echoing vendor response headers (sometimes echo `Authorization`).
- Storing secrets in `Long Text` fields "for convenience" — bypasses Frappe's encryption.
- Committing a `.env` file (use `.env.example` only).
- Hard-coding a dev token "just temporarily".
- Using `frappe.conf` to read integration credentials — integration keys are NOT in site config on this bench; they're in Settings DocTypes.

## References
- [`security/review-checklist`](./review-checklist.md) — full security walkthrough
- [`integrations/oauth-patterns`](../integrations/oauth-patterns.md) — token storage in Settings DocTypes
- [`policies/security-scoring`](../../policies/security-scoring.yaml) — D-READ-SITE-CONFIG deduction
- [`discovery/data/site-config-keys.json`](../../../discovery/data/site-config-keys.json) — confirmed key names (no values)
