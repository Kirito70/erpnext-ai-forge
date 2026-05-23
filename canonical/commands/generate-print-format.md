---
id: generate-print-format
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, backend-specialist]
---

# /generate-print-format

Scaffold a Jinja-based Print Format for a DocType.

## Usage

```
/generate-print-format <DocType> "<Format Name>" [--app <custom-app>] [--letterhead <name>]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<DocType>` | yes | DocType the print format renders |
| `<Format Name>` | yes | Display name |
| `--app` | no | Custom app to ship the fixture in. Defaults to the DocType's owning app (rejected if upstream) |
| `--letterhead` | no | Default Letterhead to associate |

## Example

```
/generate-print-format "Sales Invoice" "Cargo Branded" --app cargo_management --letterhead "Novizna Cargo"
```

## Pipeline

1. **Architect:** validate target app
2. **Backend Specialist (Reports cluster):**
   - Scaffold Jinja template under `apps/<app>/<app>/<module>/print_format/<format-name-snake>/`
   - Use `frappe.format_value` for currency / dates (DRY rule)
   - Conditional sections for optional fields
   - Letterhead interactions handled correctly
   - Mark the Print Format as a fixture so it ships with the app
3. **Security Reviewer (if Jinja uses `| safe`):** verify the source is not user-controlled
4. **Architect:** synthesize + manual steps (`bench --site novizna-v16 export-fixtures --app <app>` to capture; `bench --site novizna-v16 migrate`)

## Notes

- PDF rendering uses wkhtmltopdf — known quirks documented in `canonical/skills/reporting/print-format-authoring.md` (Phase 1b)
- Print Formats are stored as documents; making them fixtures ensures they ship with the app

## Tools Touched

- [`fixture-exporter`](../tools/fixture-exporter.yaml)
