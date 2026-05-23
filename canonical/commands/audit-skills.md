---
id: audit-skills
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, security-reviewer]
---

# /audit-skills

Lint canonical agents / skills / commands / tools for drift, dead links, and security score.

## Usage

```
/audit-skills [--scope <dir>]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--scope` | no | Limit to a subdirectory (e.g. `canonical/skills/integrations`). Default: all of `canonical/` |

## Examples

```
/audit-skills
/audit-skills --scope canonical/skills/integrations
```

## Pipeline

1. **Architect:** delegate to Security Reviewer
2. **Security Reviewer:**
   - Schema-validate every artifact's frontmatter against [`security-scoring.yaml`](../policies/security-scoring.yaml)
   - Run `forge score` on every artifact
   - Check `[[other-name]]` cross-references resolve
   - Check `version:` was bumped if `last_reviewed:` is recent but content unchanged would be suspicious
   - Flag any deprecated artifacts still in the active tree
3. **Architect:** synthesize a per-domain report with:
   - Total artifacts scanned
   - Distribution of scores (≥95 / 80–94 / <80)
   - Dead cross-references
   - Drift warnings
4. **Documentation sub-phase:** if any deprecation is overdue (>1 MINOR cycle), update CHANGELOG

## Cadence

Run quarterly as part of the [calibration cadence](../policies/governance.md#5-calibration-cadence). Also run before any MINOR release.

## Tools Touched

- `forge score` (via the CLI directly)
- `forge validate`
