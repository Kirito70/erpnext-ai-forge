---
id: governance
kind: policy
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
scope: [agent:architect, agent:security-reviewer]
---

# Governance

How the canonical layer evolves, how artifacts are versioned, deprecated, and rotated. Mirrors AI Forge governance conventions (ADR-001) with bench-specific adaptations.

---

## 1. Ownership

| Role | Owner |
|------|-------|
| Repo owner | m.tayyab9736@gmail.com |
| Security policy reviewer | m.tayyab9736@gmail.com |
| Calibration cadence reviewer | m.tayyab9736@gmail.com |
| 3-month AI Forge merge checkpoint | m.tayyab9736@gmail.com |

Per-artifact owners are declared in frontmatter (`owners:` field). An artifact may have multiple owners; the first listed is the on-call for incident response.

---

## 2. Versioning

Every artifact carries `version:` in frontmatter. Repo-level `VERSION` follows SemVer:

| Bump | Trigger |
|------|---------|
| MAJOR | Breaking change to adapter contract or frontmatter schema |
| MINOR | New agent, skill, command, tool, policy, or adapter |
| PATCH | Content refinement (no schema or contract change) |

Per-artifact versions bump independently of the repo version. The repo-level bump captures the highest-impact change in the release.

---

## 3. Deprecation Process

When an artifact is superseded:

1. Author sets `status: deprecated` in frontmatter
2. Author sets `supersedes:` on the replacement artifact (forward reference)
3. Author moves the deprecated file to `canonical/_deprecated/<original-path>/`
4. Deprecated file is **retained for exactly one MINOR cycle** before removal
5. `forge sync` continues to render the deprecated artifact with a `[DEPRECATED]` banner
6. `CHANGELOG.md` records the deprecation in the **Deprecated** section, and removal in the **Removed** section one MINOR later

---

## 4. Pull-Request Conventions

(Phase 4+ when GitHub PRs become the contribution mechanism.)

| PR Type | Requires |
|---------|----------|
| New agent | Architect's existing spec; reviewer pairings declared |
| New skill | Trigger description, scope, F/M classification, at least one bench-grounded example |
| New tool | Safety checks documented; `requires_confirmation` set correctly |
| New command | Triggered agents listed; argument schema declared |
| Adapter change | Golden tests updated; drift validation runs in CI |
| Policy change | Calibration impact analysis; affected artifacts' scores recomputed |

---

## 5. Calibration Cadence

| Item | Cadence | Owner |
|------|---------|-------|
| Security score deduction tuning | After every 10 new skills, then quarterly | Repo owner |
| Adapter capability matrix refresh | When any vibe-coding tool ships a major version | Repo owner |
| Discovery snapshot freshness | On-demand + stale-reference auto-trigger (Decision 15) | Architect (automatic) |
| AI Forge merge review | Every 3 months from 2026-05-23 (next: 2026-08-23) | Repo owner |
| Audit log backup | Monthly tar+gpg via `forge audit backup` (Decision 14) | Repo owner |
| Deprecation purge | At each MINOR release | Repo owner |

---

## 6. Out-of-Scope (Hard Limits)

These are governed at the policy level — no agent or skill may override them:

- Edit upstream apps (`frappe`, `erpnext`, `crm`, `hrms`, `lending`, `lms`, `education`, `helpdesk`, `gameplan`, `drive`, `press`)
- Read secret values from `site_config.json` or `.env` into model context
- Make business-logic decisions on the developer's behalf
- Push to git remotes without typed confirmation
- Run `bench drop-site`, `bench setup add-domain`, or mutate `common_site_config.json` without explicit chat confirmation
- Disable CSRF, permission checks, or rate limits in production paths (test fixtures excepted)
- Auto-run discovery on a schedule (cron); it is on-demand only

Violations are blocked at the tool layer and logged as escalation trigger #5 or #6.

---

## 7. Incident Response

When a sync produces unexpected bench state, when a secret is suspected to have leaked, or when an audit anomaly is detected:

1. Stop. Do not run further `forge sync` commands.
2. Open the `.forge-staging/` directory if present; preserve evidence.
3. Restore from `.claude/settings.json.forge-backup` if relevant.
4. Restore from the latest `forge audit backup` if audit integrity is questioned.
5. File the incident in `docs/incident-response.md` (Phase 4 deliverable).
6. Rotate any potentially exposed secrets.
7. Run a full `forge validate` after recovery.

---

## 8. Acceptable Use

This framework is for **single-developer** internal use within Novizna projects. It is not designed for multi-tenant or shared-organization deployments. If those use cases emerge, governance scope expands at the next MAJOR.
