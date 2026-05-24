---
id: oauth-patterns
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Implementing or reviewing OAuth2 flows for any vendor integration (Zoho, Google, HubSpot, LinkedIn, Invoice Ninja)"
scope: [agent:architect, agent:integrations-specialist, agent:security-reviewer]
foundational: true
domain: integrations
security_score: 100
supersedes: []
---

# OAuth Patterns

OAuth2 token storage, refresh, and revocation for the bench's existing integrations: Zoho CRM, Google (Sheets/Drive), LinkedIn, HubSpot, Invoice Ninja. Tokens live in **Settings DocType rows**, **not** in `site_config.json` (verified via [`site-config-keys.json`](../../../discovery/data/site-config-keys.json) — none of the integration keys are present).

## When to Load
- Adding a new vendor integration that uses OAuth2
- Reviewing the connector class for an existing vendor
- Investigating a token refresh failure
- Designing a Settings DocType for a new vendor

## Key Concepts

1. **Tokens go in Settings DocTypes** — not `site_config.json`. The bench convention (per [`integrations-map.json`](../../../discovery/data/integrations-map.json)) is one Settings singleton per vendor: `Zoho Settings`, `Google Sheets Settings`, `Invoice Ninja Settings`, etc.
2. **Encrypted storage** — sensitive fields use `fieldtype: "Password"` (Frappe encrypts at-rest using the site's `encryption_key`).
3. **Decrypted read** — `frappe.utils.password.get_decrypted_password(doctype, name, fieldname)`.
4. **Auto-refresh on expiry** — every API call checks `expires_at`; if <60s remaining, refresh first.
5. **Atomic refresh** — refresh in a transaction; on success, save new tokens; on failure, mark `auth_status = 'Expired'`.
6. **Revocation** — on disconnect, hit the vendor's revoke endpoint AND clear local tokens.
7. **Redirect URI** — documented in the per-app `CLAUDE.md` for repeatability across environments.

## Patterns

### Pattern: Settings DocType for a vendor

**When:** Adding `Zoho Settings` (singleton).

**Do:**
```json
{
  "doctype": "DocType",
  "name": "Zoho Settings",
  "issingle": 1,
  "module": "Novizna Crm",
  "fields": [
    { "fieldname": "client_id",      "fieldtype": "Data",     "label": "Client ID" },
    { "fieldname": "client_secret",  "fieldtype": "Password", "label": "Client Secret" },
    { "fieldname": "refresh_token",  "fieldtype": "Password", "label": "Refresh Token" },
    { "fieldname": "access_token",   "fieldtype": "Password", "label": "Access Token" },
    { "fieldname": "expires_at",     "fieldtype": "Datetime", "label": "Expires At" },
    { "fieldname": "redirect_uri",   "fieldtype": "Data",     "label": "Redirect URI" },
    { "fieldname": "auth_status",    "fieldtype": "Select",   "options": "Disconnected\nActive\nExpired" }
  ],
  "permissions": [
    { "role": "System Manager", "read": 1, "write": 1, "create": 1 }
  ]
}
```

Singleton + System Manager perms only. Never expose to Sales User / regular roles.

### Pattern: Connector class with auto-refresh

**When:** Calling `https://www.zohoapis.com/crm/v2` (matches [`integrations-map.json`](../../../discovery/data/integrations-map.json)).

**Do:**
```python
# apps/novizna_crm/novizna_crm/api/connectors/zoho.py
import frappe
import requests
from datetime import datetime, timedelta
from frappe.utils import now_datetime, get_datetime
from frappe.utils.password import get_decrypted_password

class ZohoConnector:
    """Zoho CRM API wrapper. Auth: OAuth2 with refresh token in Zoho Settings."""

    REFRESH_URL = "https://accounts.zoho.com/oauth/v2/token"
    BASE = "https://www.zohoapis.com/crm/v2"
    REFRESH_THRESHOLD_SECONDS = 60

    def __init__(self) -> None:
        self.settings = frappe.get_single("Zoho Settings")

    def _decrypted(self, field: str) -> str:
        return get_decrypted_password("Zoho Settings", "Zoho Settings", field) or ""

    def _ensure_fresh_token(self) -> None:
        """Refresh access token if <60s remaining."""
        expires_at = get_datetime(self.settings.expires_at) if self.settings.expires_at else None
        if expires_at and (expires_at - now_datetime()).total_seconds() > self.REFRESH_THRESHOLD_SECONDS:
            return

        resp = requests.post(self.REFRESH_URL, data={
            "refresh_token": self._decrypted("refresh_token"),
            "client_id":     self.settings.client_id,
            "client_secret": self._decrypted("client_secret"),
            "grant_type":    "refresh_token",
        }, timeout=15)

        if resp.status_code != 200:
            frappe.db.set_value("Zoho Settings", "Zoho Settings", "auth_status", "Expired")
            frappe.throw("Zoho token refresh failed")  # never log resp.text — may contain secrets

        body = resp.json()
        frappe.db.set_value("Zoho Settings", "Zoho Settings", {
            "access_token": body["access_token"],
            "expires_at": now_datetime() + timedelta(seconds=body.get("expires_in", 3600)),
            "auth_status": "Active",
        })
        self.settings = frappe.get_single("Zoho Settings")  # reload

    def get(self, path: str, **params) -> dict:
        self._ensure_fresh_token()
        headers = {"Authorization": f"Zoho-oauthtoken {self._decrypted('access_token')}"}
        return requests.get(f"{self.BASE}/{path}", headers=headers, params=params, timeout=30).json()
```

**Don't:**
```python
# Reading secret from site_config — wrong place + AP-like pattern
zoho_token = frappe.conf.get("zoho_access_token")
```

The integration keys list in [`site-config-keys.json`](../../../discovery/data/site-config-keys.json) confirms `zoho_client_id`, `zoho_client_secret`, etc. are **not** in site config. They live in `Zoho Settings`.

### Pattern: Initial OAuth handshake (redirect flow)

**When:** Admin clicks "Connect Zoho" in the Zoho Settings form.

**Do:**
1. Whitelist method generates the auth URL with `redirect_uri` from settings + state token
2. User authorizes at Zoho → Zoho redirects back to `redirect_uri` with `code`
3. A second whitelist method (the callback) exchanges `code` for refresh + access tokens
4. Store refresh_token (long-lived) + access_token + expires_at

```python
@frappe.whitelist()
def begin_zoho_oauth() -> str:
    """Returns the Zoho authorization URL for the admin to visit."""
    frappe.has_permission("Zoho Settings", "write", throw=True)
    settings = frappe.get_single("Zoho Settings")
    params = {
        "scope": "ZohoCRM.modules.ALL",
        "client_id": settings.client_id,
        "response_type": "code",
        "access_type": "offline",
        "redirect_uri": settings.redirect_uri,
    }
    return "https://accounts.zoho.com/oauth/v2/auth?" + urlencode(params)
```

### Pattern: Revocation on disconnect

**Do:**
```python
@frappe.whitelist()
def disconnect_zoho() -> dict:
    """Revoke Zoho tokens and clear local state."""
    frappe.has_permission("Zoho Settings", "write", throw=True)
    refresh = get_decrypted_password("Zoho Settings", "Zoho Settings", "refresh_token")
    if refresh:
        requests.post("https://accounts.zoho.com/oauth/v2/token/revoke",
                      data={"token": refresh}, timeout=10)
    frappe.db.set_value("Zoho Settings", "Zoho Settings", {
        "access_token": None, "refresh_token": None,
        "expires_at": None, "auth_status": "Disconnected",
    })
    return {"ok": True}
```

## Common Pitfalls
- Storing tokens as plain `Data` instead of `Password` — leaks in CSV export and any UI that shows raw fields.
- Logging `resp.text` from a failed refresh — vendor may echo the secret in error responses.
- Using `frappe.conf.get(...)` to read tokens — confirms keys present in site config; this bench's site config has none of the integration keys.
- Refreshing on every call instead of checking expiry — wastes the vendor's rate limit.
- Concurrent refresh (two workers refresh simultaneously, one invalidates the other's token) — guard with a `frappe.db.get_value(..., for_update=True)` lock.
- Hard-coding `redirect_uri` instead of reading from Settings — breaks across dev / staging / prod.

## References
- [`integrations/webhooks`](./webhooks.md) — for the inbound counterpart
- [`integrations/queueing-retry-backoff`](./queueing-retry-backoff.md) — for sync orchestration
- [`security/secrets-handling`](../security/secrets-handling.md) — never log token values
- [`discovery/data/integrations-map.json`](../../../discovery/data/integrations-map.json) — current connector inventory
- [`discovery/data/site-config-keys.json`](../../../discovery/data/site-config-keys.json) — confirms integration keys absent from site config
