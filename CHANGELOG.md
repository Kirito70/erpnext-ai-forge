# Changelog

All notable changes to **erpnext-ai-forge** are recorded here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Section order per release: **Added / Changed / Deprecated / Removed / Fixed / Security**.

---

## [Unreleased]

### Added
- (Phase 1a) Architect agent spec
- (Phase 1a) 7 specialist agent specs
- (Phase 1a) Claude Code adapter templates
- (Phase 1a) 17 slash command definitions
- (Phase 1a) 14 tool specs
- (Phase 1b) 20 skill modules with bench-grounded examples

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
