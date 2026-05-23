---
id: review-security
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, security-reviewer]
---

# /review-security

Run the full Security Reviewer checklist over a path (uncommitted changes, a specific file, or a directory).

## Usage

```
/review-security [--path <p>] [--staged-only]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--path` | no | Path to review (file or directory). Default: uncommitted changes in custom apps. |
| `--staged-only` | no | Only review git-staged files |

## Examples

```
/review-security
/review-security --path apps/novizna_crm
/review-security --path apps/noviznaerp_payroll/noviznaerp_payroll/custom/loan_custom.py --staged-only
```

## Pipeline

1. **Architect:** delegate to Security Reviewer
2. **Security Reviewer:** walk the [checklist](../agents/security-reviewer.md#the-checklist-must-walk-every-time) over the scope:
   - CRITICAL findings → REJECT with veto
   - HIGH findings → REQUEST_CHANGES
   - MEDIUM / LOW → noted in review
3. **Architect:** synthesize, present score deltas, escalate if any CRITICAL is unfixable in 1 round

## Output

Structured review per [review-protocol §1](../policies/review-protocol.md#1-review-output-format) with linked AP-id references for any recurrences of pre-existing standing findings.

## Tools Touched

- [`mariadb-query`](../tools/mariadb-query.yaml) — verify recommended indexes / perm rules
- [`git-status-all-apps`](../tools/git-status-all-apps.yaml) — confirm scope
