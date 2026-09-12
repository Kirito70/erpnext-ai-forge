---
id: erpnext_location
kind: app-notes
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
---

## Where Things Live

| Surface | Path |
|---------|------|
| Backend | `apps/erpnext_location/erpnext_location/` |
| DocTypes | `apps/erpnext_location/erpnext_location/erpnext_location/doctype/` |
| Patches | `apps/erpnext_location/erpnext_location/patches/` |

## App-Specific Rules

- Location / geo extension for ERPNext: the State / City / Region / Subregion
  doctypes other apps link against (Branch in novizna_pos, for one).
- `novizna_core` depends on this app; renaming or removing a location DocType breaks
  consumers in other apps, so treat the DocType names as a published contract.
