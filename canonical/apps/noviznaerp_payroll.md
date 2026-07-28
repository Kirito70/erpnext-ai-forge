---
id: noviznaerp_payroll
kind: app-notes
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
---

## Where Things Live

| Surface | Path |
|---------|------|
| Backend | `apps/noviznaerp_payroll/noviznaerp_payroll/` |
| DocTypes | `apps/noviznaerp_payroll/noviznaerp_payroll/noviznaerp_payroll/doctype/` |
| Patches | `apps/noviznaerp_payroll/noviznaerp_payroll/patches/` |
| Fixtures | `apps/noviznaerp_payroll/noviznaerp_payroll/fixtures/` |

## App-Specific Rules

- The largest custom app by DocType count. Naming uses bare domain nouns; that is
  accepted for what exists, but disambiguate new DocTypes with an app prefix.
- **Known anti-pattern:** occurrences of `frappe.db.sql(f"...")` are flagged HIGH as
  AP-001 in `discovery/data/anti-pattern-findings.json`. Do not add more — use
  parameter binding (`values=`).
