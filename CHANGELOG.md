# Changelog

All notable changes to **erpnext-ai-forge** are recorded here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Section order per release: **Added / Changed / Deprecated / Removed / Fixed / Security**.

---

## [Unreleased]

---

## [0.3.0] — 2026-05-24

### Added — Phase 1b (canonical skill content)
- **30 skill modules** across 10 domain directories (`canonical/skills/`), ~5,274 lines total. All grounded in real bench facts from `discovery/data/*.json`:
  - `frappe-core/` — 6 skills (conventions, doctype-authoring, hooks-and-events, whitelist-api-patterns, permissions-model, migration-patches)
  - `frontend/` — 3 skills (frappe-ui-components, novizna-crm-override-system, vue3-quasar-patterns)
  - `data/` — 2 skills (sql-best-practices, mariadb-debugging) with AP-001 file:line attribution
  - `reporting/` — 4 skills (script-report-authoring, query-report-authoring, print-format-authoring, workflow-authoring)
  - `integrations/` — 3 skills (oauth-patterns, webhooks, queueing-retry-backoff)
  - `security/` — 2 skills (review-checklist, secrets-handling)
  - `testing/` — 3 skills (frappe-unittest, pytest-patterns, e2e-playwright)
  - `debugging/` — 1 skill (bench-logs)
  - `erpnext-domains/` — 5 skills (sales, accounting, hr-payroll, pos, crm)
  - `meta/` — 1 skill (skill-authoring-guide)
- 14 skills classified `foundational: true` per agent-spec scoping
- Every "Don't" example links to a discovery AP-id when it mirrors a standing finding

### Added — Phase 2 (forge sync engine)
- `forge/src/forge/loader.py` — parses canonical/ Markdown + frontmatter + tools YAML + discovery JSON into typed dataclasses
- `forge/src/forge/models.py` — `CanonicalArtifact`, `ToolSpec`, `DiscoverySnapshot`, `ForgeContext`
- `forge/src/forge/render.py` — Jinja-based renderer; consumes adapter.yaml, produces `RenderedArtifact` list
- `forge/src/forge/sync.py` — transactional sync per v0.2 Part B item 7: render → stage → validate → atomic per-file swap; aborts whole `--all` run if any adapter fails
- `forge/src/forge/manifest.py` — `.forge-manifest.json` writer + reader (ADR-002 schema with source_commit, sha256 per file)
- `forge/src/forge/settings_merge.py` — deep merge for `.claude/settings.json` (Part B item 6): deep merge dicts, union arrays by identity, forge-wins scalars with conflict log, `.forge-backup` on every write
- `forge/src/forge/audit.py` — JSONL append + tail viewer + monthly tar+gpg backup
- `forge/src/forge/scoring.py` — security score against canonical/policies/security-scoring.yaml deductions with per-extension and per-path filters
- All 8 CLI commands wired to real implementations (no more "not yet implemented")

### Added — Tests
- 63 tests, 100% passing:
  - `test_loader.py` (14 tests) — frontmatter, discovery, tools, adapter config
  - `test_render.py` (6 tests) — Claude Code renders 8 agents + 17 commands + 30 skills + 14 tools + 8 per-app CLAUDE.md + root CLAUDE.md
  - `test_manifest.py` (5 tests) — schema, write/read roundtrip
  - `test_settings_merge.py` (8 tests) — deep merge, array union, scalar conflict, backup
  - `test_scoring.py` (10 tests) — per-rule deductions, path/extension filters, canonical sanity
  - `test_audit.py` (4 tests) — JSONL append, year/month dir, tail filters
  - `test_cli_smoke.py` (11 tests) — every CLI command exits 0
  - `test_cli_integration.py` (5 tests) — end-to-end validate/render/score/sync against real canonical

### Changed
- AUTO-GENERATED markers in Jinja templates switched from `{# ... #}` (stripped by Jinja) to `<!-- ... -->` (preserved in output)
- `command.md.j2` description derives from frontmatter `trigger` when no explicit `description` is set
- `tool-reference.md.j2` uses `spec.get(...)` for optional dict fields (description, type, required)
- `forge/pyproject.toml` dropped `readme = "../README.md"` (setuptools rejects parent paths)
- `VERSION` bumped 0.2.0 → 0.3.0 (MINOR — substantial new content + sync engine)
- `PROJECT-STATUS.md` updated to reflect Phase 1b + Phase 2 completion

### Security
- Per-extension filtering ensures `.py`-only patterns (D-SQL-FSTRING, D-IGNORE-PERMISSIONS, D-GUEST-WHITELIST) don't fire on pedagogical "Don't" examples in canonical Markdown
- `canonical/` documentation that names a deduction by literal string (e.g., "curl ... | sh") is exempt from triggering that same deduction

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
