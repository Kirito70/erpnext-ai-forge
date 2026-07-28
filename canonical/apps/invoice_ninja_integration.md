---
id: invoice_ninja_integration
kind: app-notes
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
---

## Where Things Live

| Surface | Path |
|---------|------|
| Backend | `apps/invoice_ninja_integration/invoice_ninja_integration/` |
| DocTypes | `apps/invoice_ninja_integration/invoice_ninja_integration/invoice_ninja_integration/doctype/` |
| Patches | `apps/invoice_ninja_integration/invoice_ninja_integration/patches/` |

## App-Specific Rules

- DocType naming: `invoice_ninja_<noun>` prefix.
- Custom fields on ERPNext doctypes are scoped via this app's fixture, never applied
  directly with a property setter.
- Sync activity is logged to the `Invoice Ninja Sync Logs` DocType — an integration
  path that writes nothing there is unauditable and is treated as incomplete.
