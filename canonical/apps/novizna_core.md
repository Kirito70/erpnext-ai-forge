---
id: novizna_core
kind: app-notes
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
---

## Where Things Live

| Surface | Path |
|---------|------|
| Backend | `apps/novizna_core/novizna_core/` |
| Currency providers | `apps/novizna_core/novizna_core/currency_exchange/` |
| DocTypes | `apps/novizna_core/novizna_core/novizna_core/doctype/` |
| Patches | `apps/novizna_core/novizna_core/patches/` |

## App-Specific Rules

- Cross-app utility app — code here is imported by other custom apps, so a breaking
  change here breaks several apps at once. Treat its public surface as an API.
- Currency exchange providers live under `currency_exchange/`.
- Requires `erpnext_location`; do not add a reverse dependency back the other way.
