# Changelog

All notable changes to **erpnext-ai-forge** are recorded here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Section order per release: **Added / Changed / Deprecated / Removed / Fixed / Security**.

---

## [Unreleased]

---

## [0.5.0] — 2026-05-25

### Added — Phase 4 (security gates + audit hardening + CI)

- **Pre-sync security gate** in `forge/src/forge/sync.py`. Every `forge sync` now scores the canonical sources contributing to the render before any bench file is touched:
  - Score `< 80` (`block_floor`) → sync aborts; rejection logged to audit JSONL as `sync.blocked_by_security_gate` with `findings` + `per_file_scores`.
  - Score `80–94` without `--justify` → sync aborts with a `sync.warned_without_justify` audit entry; developer must re-run with `--justify "<one-line reason>"`.
  - Score `80–94` with `--justify` → sync proceeds; `sync.justified_accept` audit entry records the reason text and per-file scores.
  - Gate scores canonical sources (not staged rendered output) — templates never introduce new anti-patterns; scoring sources eliminates false positives from skill content that legitimately discusses deduction patterns by name.
- **Audit viewer hardening** (`forge audit tail`):
  - `--action <prefix>` filter (e.g. `--action sync.` to see all sync entries)
  - `--grep <regex>` filter across raw JSONL
  - `--json` flag emits raw JSONL on stdout for piping into `jq`
- **`docs/incident-response.md`** — 7 numbered recovery procedures: security-gate block, drift, suspected secret leak, multi-tool sync abort, settings.json clobber, audit corruption, CI-only failure. Each with a verification step.
- **Real CI workflow** at `.github/workflows/ci.yml` — three jobs:
  1. `gitleaks` (secrets scan, gates the rest)
  2. `lint` (markdownlint + yamllint in parallel)
  3. `forge` — installs forge, runs `validate` + `score --fail-below 80` + `test` + `sync --all --dry-run`; uploads `audit/` as artifact on failure for forensics
- **4 new exit-criterion tests** in `forge/tests/test_security_gate.py`:
  - Poisoned `.py` file outside `canonical/` scores below `block_floor`
  - Synthetic blocked render (multiple findings, gate blocks)
  - Audit JSONL records `sync.blocked_by_security_gate` entry with findings detail
  - 80–94 warning band requires `--justify`; with justification, warning is downgraded

122 tests total, 100% passing.

### Changed
- `forge/src/forge/sync.py` imports `Finding` and `score_file` from `forge.scoring`
- `forge audit tail` API signature gained `action`, `grep`, `as_json` parameters (backwards-compatible — existing callers continue working)
- `VERSION` 0.4.0 → 0.5.0 (MINOR — new sync gate semantics)
- `PROJECT-STATUS.md` reflects Phase 4 completion; only Phase 5 (iteration metrics) remains

### Security
- The Phase 4 exit criterion from v0.2 §10 is satisfied: an intentionally poisoned canonical source carrying a CRITICAL deduction is now blocked at sync time before any bench file is touched, and the rejection is recorded in the audit JSONL with finding-level detail.
- All 80–94 score artifacts now require typed justification per [Decision 11](../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md#section-11--decision-log). Justifications are logged to audit JSONL alongside the per-file scores so a future review can reconstruct why a not-fully-clean artifact shipped.

---

## [0.4.0] — 2026-05-24

### Added — Phase 3 (per-tool adapter rollout)

All 6 non-Claude adapters from v0.2 Decision 5 are now implemented. `forge.config.yaml` `enabled_tools` now lists 7 adapters total.

| Adapter | Output | Char budget | Strategy |
|---------|--------|------------:|----------|
| `cursor` | `<bench>/.cursor/rules/forge-main.mdc` + 8 per-app `.mdc` | 40k | Aggregate + per-app with `globs:` |
| `opencode` | `<bench>/AGENTS.md` + `.opencode/commands/*.md` (×17) | 20k | Aggregate + native slash commands |
| `cline` | `<bench>/.clinerules/00-forge-main.md` + 8 per-app | 35k | Aggregate + per-app |
| `copilot` | `<bench>/.github/copilot-instructions.md` + 8 per-app instructions | 30k | Aggregate + per-app `applyTo:` glob |
| `codex` | `<bench>/AGENTS.codex.md` (Decision 8 — separate from OpenCode) | 20k | Single aggregate |
| `antigravity` | `<bench>/.antigravity/system.md` (architect + 2 specialists only) | 15k | Minimal (Decision 6) |

### Added — renderer enhancements
- **`strategy: aggregate`** in render.py — renders the full canonical set (agents, commands, skills, tools) into one output file via a single template. Used by every non-Claude adapter.
- **`strategy: aggregate_per_app`** — renders one output per custom app (Cursor, Cline, Copilot use this for `globs:` / `applyTo:` scoped per-app context files).
- **Iterative output_paths resolution** — adapter.yaml can declare arbitrary path keys (e.g., `rules_dir`, `instructions_dir`) and they're resolved in dependency order so later entries can reference earlier ones.
- Per-app aggregate passes the full app dict (not just the name), so adapter.yaml output strings like `forge-{{ app.name }}.mdc` resolve correctly.

### Tests
- 25 new tests in `test_adapters.py`, 118 total, 100% passing:
  - Per-adapter render smoke (file counts, char budgets, expected output names)
  - Parametrized capability matrix check (all 7 adapters expose required keys)
  - Parametrized char budget assertion (Cursor 40k / Cline 35k / Copilot 30k / OpenCode-Codex 20k / Antigravity 15k)
  - Provenance footer check (every aggregate output carries `erpnext-ai-forge` + `AUTO-GENERATED`)

### Changed
- `forge.config.yaml` `enabled_tools` flipped from `[claude-code]` to all 7 adapters
- `VERSION` 0.3.1 → 0.4.0 (MINOR — six new adapters)
- `PROJECT-STATUS.md` reflects Phase 3 completion

### Notes on context-loading strategy (v0.2 §4.0)
The renderer correctly implements the per-tool strategies:
- **Claude Code:** Task tool spawns specialists in fresh contexts; skills loaded on demand
- **Cursor / Cline / Copilot:** specialists inlined as persona summary tables; foundational skills as TOC (not inlined — would exceed budget); on-demand skills as a separate TOC the developer expands
- **OpenCode / Codex:** same as no-subagent tools but using `AGENTS.md` / `AGENTS.codex.md` as host file
- **Antigravity:** even more restrictive — only architect + Backend + Security personas inlined; all other specialists in a one-line summary table

---

## [0.3.1] — 2026-05-24

### Added — Phase 2.x deferred pieces
- **`forge commit`** — scoped Conventional Commits helper (`forge/src/forge/commit_helper.py`):
  - Infers commit scope from staged file paths against `forge.config.yaml` `commits.scopes` (canonical/agents → `agents`, canonical/skills → `skills`, forge/ → `forge`, etc.). Multi-scope changes resolve to `scaffold` when no single scope reaches 60% share.
  - Infers commit type (`feat`/`fix`/`refactor`/`docs`/`test`/`perf`/`chore`) from body text via keyword heuristics.
  - `--check` mode validates `.git/COMMIT_EDITMSG` against the convention — wires up the commit-msg git hook contract declared in `.pre-commit-config.yaml`.
- **`forge discover`** — automated bench walking (`forge/src/forge/discover_bench.py`):
  - Walks `<bench>/apps/<custom-app>/`, skipping upstream apps from `forge.config.yaml`.
  - Detects per-app stack: Quasar PWA / Frappe-UI Vue3 / pure backend.
  - Parses `hooks.py` for boolean signals (`doc_events`, `scheduler_events`, `fixtures`, `app_include_js`, `after_install`, etc.) via regex.
  - Lists DocType IDs, counts `@frappe.whitelist()` declarations, samples method names.
  - Scans for the four standing anti-patterns: SQL f-string, `allow_guest=True`, `ignore_permissions=True`, and `frappe.db.commit()` in non-test code, with file:line attribution.
  - Builds the novizna_crm override map from `apps/novizna_crm/frontend/{src,src_override}/`.
  - Records `site_config.json` and `common_site_config.json` **key names only** (never values), flags `ignore_csrf` if present.
  - Writes 7 JSON files matching the Phase 0 schema. `INVENTORY.md` stays human-authored.
- **`forge validate --check-drift`** — manifest-based drift detection (`forge/src/forge/drift.py`):
  - For every `.forge-manifest.json` in the bench, verifies each listed file's current sha256 matches the manifest's recorded sha256 (catches hand-edits and missing files).
  - Compares `manifest.source_commit` against current repo HEAD; flags staleness when out of date.
  - Skips `.forge-staging/` (transient sync artifacts).

### Changed
- `forge/src/forge/commands/discover.py` — wired to the real walker (was Phase 0 stub printing snapshot freshness only).
- `forge/src/forge/commands/commit.py` — wired to `commit_helper.propose()` and `check_message()`.
- `forge/src/forge/commands/validate.py` — `--check-drift` flag now invokes `drift.check_drift()` and rolls drift findings into the issues list.
- Removed `test_discover_runs` from `test_cli_smoke.py` and `test_discover_prints_snapshot` / `test_discover_app_lookup` from `test_cli_integration.py` — discover writes into the host repo's `discovery/data/` tree, which would clobber the Phase 0 hand-authored snapshot. Behavior is covered by `test_discover_bench.py` against isolated fake benches.

### Tests
- 30 new tests, 93 total, 100% passing:
  - `test_commit_helper.py` (16 tests) — scope inference, type inference, check_message validation, propose
  - `test_discover_bench.py` (8 tests) — stack detection, hooks parsing, DocType/whitelist listing, anti-pattern scanning, end-to-end with fake bench
  - `test_drift.py` (6 tests) — clean bench, hand-edit detection, missing file, staleness, staging dir skipped

### Fixed
- `infer_type_from_body` no longer mis-classifies "Update the README" as `feat` (the word "new" in "new install steps" was suppressing the docs branch). Doc-noun signals now win unconditionally.

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
