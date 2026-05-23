# Changelog

All notable changes to **erpnext-ai-forge** are recorded here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Section order per release: **Added / Changed / Deprecated / Removed / Fixed / Security**.

---

## [Unreleased]

### Added
- (Phase 1b) 20 skill modules with bench-grounded examples (pending)

---

## [0.2.0] — 2026-05-24

### Added
- **Canonical layer** populated for Phase 1a (~50 files):
  - 4 policies (`security-scoring.yaml`, `review-protocol.md`, `escalation-rules.md`, `governance.md`)
  - 14 tool specs (bench-{migrate,clear-cache,restart,console,logs}, doctype-scaffolder, fixture-exporter, patch-generator, override-checker, frontend-build, mariadb-query, api-endpoint-tester, git-status-all-apps, fixture-differ)
  - 8 agent specs (architect + backend, frontend-frappe-ui, frontend-quasar, integrations, security-reviewer, qa-test-engineer, devops-deployment)
  - 17 slash command specs (scaffold-doctype, scaffold-api, review-security, write-tests, migrate-patch, add-integration, explain-hook, optimize-query, forge-sync, audit-skills, override-frontend, generate-report, generate-print-format, sync-erpnext, explain-doctype, bench-logs, diff-upstream)
- **Claude Code adapter** (`adapters/claude-code/`):
  - `adapter.yaml` with capability profile, output paths, mapping rules, settings.json merge strategy
  - 7 Jinja templates (`agent.md.j2`, `command.md.j2`, `skill.md.j2`, `settings-tool-permission.json.j2`, `tool-reference.md.j2`, `claude-md-root.j2`, `claude-md-per-app.j2`)
  - Per-app `CLAUDE.md` generation per Decision 19 (root carries cross-cutting only; per-app gets specifics)
- Tightened security thresholds encoded in `policies/security-scoring.yaml` (≥95 auto-accept / 80–94 typed justification / <80 block / external ≥98)
- 2-loop revision cap encoded in `policies/review-protocol.md` (Part B item 2)
- Reports/Print and Database/Data specialists consolidated into Backend Specialist as skill clusters (Part B item 1)
- Documentation Writer removed; folded into Architect closing sub-phase (Part B item 1)
- `mariadb-query` upgraded to grant-based read-only user with sqlglot parser fallback (Part B item 5)

### Changed
- `VERSION` bumped 0.1.0 → 0.2.0 (MINOR — new agents, skills schema, commands, tools)

---

## [0.1.0] — 2026-05-23

### Added
- Phase 0 repo scaffold per [`ULTRAPLAN-AI-FRAMEWORK-v0.2.md`](../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md)
- Full directory tree (`canonical/`, `adapters/`, `forge/`, `discovery/`, `audit/`, `docs/`)
- Root docs: `README.md`, `PROJECT-STATUS.md`, `ARCHITECTURE.md` (with ADR-001), `LICENSE`, `VERSION`
- Config: `.gitignore`, `.env.example`, `forge.config.yaml`, `.pre-commit-config.yaml`
- `forge` CLI skeletons (`discover`, `validate`, `render`, `sync`, `audit`, `score`, `test`, `commit`)
- Initial bench discovery output (`discovery/INVENTORY.md` + JSON data)
- GitHub Actions CI placeholder (`forge validate`, `forge score`, golden tests)

### Security
- `.gitignore` excludes `.env`, `secrets/`, `audit/*.jsonl`, `discovery/data/*.private.json`
- Pre-commit hooks: `gitleaks`, `markdownlint`, `yamllint`, `forge score --staged`
- Security scoring thresholds: auto-accept ≥95, warn 80–94 (typed justification), block <80, external skills ≥98
