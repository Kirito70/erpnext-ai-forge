---
id: novizna_integrations
kind: app-notes
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
---

## Where Things Live

| Surface | Path |
|---------|------|
| Backend | `apps/novizna_integrations/novizna_integrations/` |
| Capability contracts | `apps/novizna_integrations/novizna_integrations/core/capabilities/` |
| Canonical DTOs | `apps/novizna_integrations/novizna_integrations/core/dto/` |
| Services | `apps/novizna_integrations/novizna_integrations/services/` |
| Providers | `apps/novizna_integrations/novizna_integrations/providers/` |
| Consumers (base + registry) | `apps/novizna_integrations/novizna_integrations/consumers/` |
| Background jobs | `apps/novizna_integrations/novizna_integrations/jobs/` |
| DocTypes | `apps/novizna_integrations/novizna_integrations/novizna_integrations/doctype/` |
| Patches | `apps/novizna_integrations/novizna_integrations/patches/` |

Planned work is ticketed in the Obsidian vault under `wiki/novizna-integrations/`
(Jira key `NINT`). **`EXECUTION-GUIDE.md` there is binding** and outranks a source brief
where the two disagree — read it before changing anything in this app.

## App-Specific Rules

- **Vocabulary is load-bearing.** `novizna_crm/api/connectors/` is a *different, unrelated*
  system (legacy one-shot bulk import). Never name a file, class or DocType `*Connector*`
  here. A *connection* is an authenticated provider instance; a *provider* is code; a
  *capability* (`mail`, `storage`) is a contract, not a vendor; a *consumer* is a business
  app that consumes one.
- **Standalone, and it stays that way.** This app depends on `frappe` and nothing else. The
  core must import nothing from `crm`, `erpnext`, `hrms` or `novizna_crm` — consumers live in
  the business app and register through a hook, so the dependency only ever points inward:
  ```bash
  grep -rnE '^\s*(from|import)\s+(crm|erpnext|hrms|novizna_crm)\b' \
    apps/novizna_integrations/novizna_integrations/{core,services,providers}/   # must be empty
  ```
- **No new runtime dependencies.** `pyproject.toml` `dependencies` is `[]` and must stay `[]`.
  The HTTP client, OAuth2 pair and template engine all arrive through `frappe`; a second
  declaration here lets the two pins drift.
- **Discovery is the bench's existing plugin pattern**, copied from
  `novizna_core/currency_exchange/` (`provider_registry.py` + `plugin_loader.py`). Hook keys
  are `novizna_integration_providers` and `novizna_integration_consumers`; discovery runs from
  `after_migrate` and is idempotent. **A provider is code, never a database row** — the
  `Integration Provider` DocType is a catalog record, and one with no registered class must
  raise a validation error rather than fail silently.
- **OAuth is not implemented here.** It bridges to Frappe's `Connected App` + `Token Cache`,
  which already provide filelock-guarded refresh, CSRF `state` validation, `DF.Password`
  credential encryption and `get_backend_app_token()` for org scope.
  **Trap:** `TokenCache.get_expires_in()` derives expiry from `self.modified`, so *any*
  `save()` on a Token Cache silently extends a token's perceived validity. Never write to a
  Token Cache outside `update_data()`.
- **Never set `email_account` on an imported Communication.** `crm/hooks.py` wires
  `Communication.after_insert -> crm.utils.on_communication_insert`, gated on that field; it
  would auto-create Leads and Contacts from recipients. This is a negative acceptance
  criterion on every ticket that writes a Communication, not a comment.
- **One Communication, many records.** `get_communication_data()` UNIONs
  `reference_doctype`/`reference_name` with a join on `tabCommunication Link`, so set the
  primary match as the reference and append `timeline_links` for the rest. Do not write
  duplicate Communication rows to reach multiple timelines.
- **Message-ID is stored bracket-stripped** (`get_string_between("<", ..., ">")`), and its
  index is non-unique and truncated to 140 chars. Strip brackets before lookup, and take
  uniqueness from `Integration External Reference`, never from the Communication table.
- **Secrets never surface.** No access or refresh token may appear in a log line, an error
  message, or any whitelisted API response.
