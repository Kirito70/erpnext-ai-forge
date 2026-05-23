---
id: scaffold-doctype
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, backend-specialist, qa-test-engineer, security-reviewer]
---

# /scaffold-doctype

Generate a new DocType with JSON definition, controller stub, test stub, and a suggested `hooks.py` addition.

## Usage

```
/scaffold-doctype <Label> --app <custom-app> --module <module> --fields "<field-spec>" [--submittable] [--child]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<Label>` | yes | DocType display label (will be converted to snake_case ID) |
| `--app` | yes | Custom app target. One of: `novizna_crm`, `novizna_core`, `novizna_pos`, `invoice_ninja_integration`, `noviznaerp_payroll`, `cargo_management`, `changemakers`, `erpnext_location` |
| `--module` | yes | Module within the app (must exist in `modules.txt`) |
| `--fields` | yes | Field spec: `"<name>:<Type>[/<Options>],..."` (e.g. `"manifest_no:Data,branch:Link/Branch,status:Select/Open|Closed|Void"`) |
| `--submittable` | no | Boolean — DocType is submittable |
| `--child` | no | Boolean — DocType is a child table |

## Example

```
/scaffold-doctype "Cargo Manifest" --app cargo_management --module logistics \
  --fields "manifest_no:Data,branch:Link/Branch,status:Select/Open|Closed|Void"
```

## Pipeline

1. **Architect:** draft TASK BRIEF; verify naming convention against [`discovery/data/doctype-index.json`](../../discovery/data/doctype-index.json)
2. **Backend Specialist:** invoke [`doctype-scaffolder`](../tools/doctype-scaffolder.yaml) → controller stub with `validate()` placeholder + JSON + test stub
3. **QA:** scaffold edge-case tests (empty, max-length, permission denied)
4. **Security Reviewer:** verify naming, permission block, no `allow_guest`
5. **Architect:** synthesize, print manual steps (`bench --site novizna-v16 migrate; bench clear-cache`)
6. **Documentation sub-phase:** update per-app `CLAUDE.md` DocType list + `CHANGELOG.md`

## Tools Touched

- [`doctype-scaffolder`](../tools/doctype-scaffolder.yaml) (requires_confirmation: true)
- [`bench-migrate`](../tools/bench-migrate.yaml)
- [`bench-clear-cache`](../tools/bench-clear-cache.yaml)
