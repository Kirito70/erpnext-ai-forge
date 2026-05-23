---
id: write-tests
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, qa-test-engineer]
---

# /write-tests

Generate missing tests until the target reaches ≥ 80% line coverage.

## Usage

```
/write-tests <path> [--type unit|integration|e2e]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<path>` | yes | File or directory to cover |
| `--type` | no | Restrict to a single test type. Default: choose per the [QA test matrix](../agents/qa-test-engineer.md#test-type-matrix) |

## Examples

```
/write-tests apps/novizna_crm/novizna_crm/api/leads.py
/write-tests apps/novizna_pos/novizna-pos-ui/src/composables/useCart.ts --type unit
```

## Pipeline

1. **Architect:** delegate to QA
2. **QA:** measure current coverage, identify uncovered lines, scaffold tests using framework matching the path (FrappeTestCase / pytest / Vitest / Playwright)
3. **QA:** run tests, iterate until coverage ≥ 80% on changed file
4. **Architect:** synthesize coverage report

## Notes

- 80% line coverage is enforced per file (not aggregated)
- Edge cases required: empty, max-length, permission-denied, error path
- E2E tests reserved for critical user flows (POS save/submit, novizna_crm Lead create, etc.)

## Tools Touched

- [`bench-console`](../tools/bench-console.yaml) — run integration scenarios
- [`api-endpoint-tester`](../tools/api-endpoint-tester.yaml) — E2E HTTP-level
- [`frontend-build`](../tools/frontend-build.yaml) — verify Vue change builds before Vitest
