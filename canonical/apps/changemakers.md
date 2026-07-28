---
id: changemakers
kind: app-notes
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
---

## Where Things Live

| Surface | Path |
|---------|------|
| Backend | `apps/changemakers/changemakers/` |
| DocTypes | `apps/changemakers/changemakers/changemakers/doctype/` |
| Patches | `apps/changemakers/changemakers/patches/` |

## App-Specific Rules

- Nonprofit / member workflow domain, spread over a large DocType surface.
- Member and donor records carry personal data — keep it out of logs, error messages,
  and any brain/memory ingestion.
