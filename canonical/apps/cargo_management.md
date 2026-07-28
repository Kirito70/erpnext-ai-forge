---
id: cargo_management
kind: app-notes
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
---

## Where Things Live

| Surface | Path |
|---------|------|
| Backend | `apps/cargo_management/cargo_management/` |
| Parcel DocTypes | `apps/cargo_management/cargo_management/parcel_management/` |
| Patches | `apps/cargo_management/cargo_management/patches/` |

## App-Specific Rules

- EasyPost + 17Track webhook receivers: **every guest-allowed handler must verify the
  signature before doing anything else.** An unverified guest endpoint here accepts
  forged shipment state from anyone on the internet.
- Parcel-related DocTypes live under `parcel_management/`.
