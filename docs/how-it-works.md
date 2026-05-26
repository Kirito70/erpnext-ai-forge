# How erpnext-ai-forge Works

A complete walkthrough of the project: what problem it solves, how it's built, why every file exists, and what happens end-to-end when you run a command. Read top-to-bottom or jump to the section you need.

---

## Table of Contents

1. [The problem this solves](#1-the-problem-this-solves)
2. [The big picture in one diagram](#2-the-big-picture-in-one-diagram)
3. [Three layers + the discovery sidecar](#3-three-layers--the-discovery-sidecar)
4. [Repository layout — every file explained](#4-repository-layout--every-file-explained)
5. [End-to-end: what happens when you run `forge sync --all`](#5-end-to-end-what-happens-when-you-run-forge-sync---all)
6. [The eight `forge` CLI commands](#6-the-eight-forge-cli-commands)
7. [The security gate](#7-the-security-gate)
8. [The audit trail](#8-the-audit-trail)
9. [Why each piece is needed (removal impact)](#9-why-each-piece-is-needed-removal-impact)
10. [Glossary](#10-glossary)

---

## 1. The problem this solves

You use many AI coding tools daily — Claude Code, Cursor, OpenCode, Cline, GitHub Copilot, Codex, Antigravity. Each one reads instructions from a different file in a different format:

| Tool | Reads |
|------|-------|
| Claude Code | `.claude/agents/*.md`, `.claude/skills/<domain>/*.md`, `.claude/commands/*.md`, `.claude/settings.json` |
| Cursor | `.cursor/rules/*.mdc` |
| OpenCode | `AGENTS.md` + `.opencode/commands/*.md` |
| Cline | `.clinerules/*.md` |
| Copilot | `.github/copilot-instructions.md` + `.github/instructions/*.instructions.md` |
| Codex | `AGENTS.codex.md` |
| Antigravity | `.antigravity/system.md` |

Without this framework, you'd hand-author each tool's config and they'd drift apart immediately. Edit a skill in one place and every other tool stays stale. The same Frappe convention gets written seven different ways with subtle inconsistencies.

**This project keeps a single source of truth (`canonical/`) and renders it into all seven tool formats automatically.** Edit a skill once, run `forge sync --all`, and every tool picks up the same content in its native format.

A second job: ground every skill in the **real Novizna v16 bench**, not generic Frappe. The `discovery/` layer captures bench-specific facts (the 8 custom apps, the 3-layer override system, the standing anti-patterns) so canonical content can reference them concretely instead of speaking in abstractions.

A third job: enforce a **security gate** before anything is written to the bench. Edit a skill in a way that introduces a CRITICAL anti-pattern (SQL injection, `curl | sh`, upstream-app modification) and `forge sync` blocks before any bench file is touched.

---

## 2. The big picture in one diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  CANONICAL LAYER  (you edit here — the source of truth)         │
│                                                                 │
│  canonical/                                                     │
│    agents/      (8 .md files — architect + 7 specialists)       │
│    skills/      (30 .md files — Frappe/frontend/etc.)           │
│    commands/    (17 .md files — slash commands)                 │
│    tools/       (14 .yaml — bench command wrappers)             │
│    policies/    (4 files — scoring, review, escalation, gov)    │
└────────────────────────┬────────────────────────────────────────┘
                         │
              forge render / forge sync
                         │
                  ┌──────┴──────┐
                  ▼             ▼
┌─────────────────────────────────┐   ┌─────────────────────────┐
│  DISCOVERY LAYER  (bench facts) │   │  ADAPTER LAYER          │
│                                 │   │  (per-tool translators) │
│  discovery/                     │   │                         │
│    INVENTORY.md (human-curated) │   │  adapters/              │
│    data/*.json  (auto-gen)      │   │    claude-code/         │
│                                 │   │    cursor/              │
│  Updated by `forge discover`    │   │    opencode/            │
│  reading the bench at           │   │    cline/               │
│  $FORGE_BENCH_PATH              │   │    copilot/             │
└─────────────────────────────────┘   │    codex/               │
                                      │    antigravity/         │
                                      │                         │
                                      │  Each has adapter.yaml  │
                                      │  + Jinja templates      │
                                      └───────────┬─────────────┘
                                                  │
                              forge sync stages here, then atomic-swaps
                                                  │
                                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│  BENCH INTEGRATION  (rendered configs land here)                │
│                                                                 │
│  $FORGE_BENCH_PATH/                                             │
│    .claude/{agents,skills,commands,tools}/  (Claude Code)       │
│    .cursor/rules/*.mdc                       (Cursor)           │
│    AGENTS.md, .opencode/commands/            (OpenCode)         │
│    .clinerules/                              (Cline)            │
│    .github/copilot-instructions.md + ...     (Copilot)          │
│    AGENTS.codex.md                           (Codex)            │
│    .antigravity/system.md                    (Antigravity)      │
│    apps/<custom-app>/CLAUDE.md               (per-app contexts) │
│    .forge-manifest.json (in every output dir for drift detect)  │
└─────────────────────────────────────────────────────────────────┘

                  Every action above appends to:
                  audit/<YYYY>/<MM>/forge-audit.jsonl
```

The CLI sits between layers. `forge` orchestrates: it reads canonical + discovery, runs through an adapter, and writes the bench output transactionally. The audit log records every step.

---

## 3. Three layers + the discovery sidecar

### 3.1 Canonical Layer

Tool-agnostic Markdown + YAML. You edit here. Every file has YAML frontmatter (`id`, `kind`, `version`, `status`, `owners`, `trigger`, `scope`, `foundational`, `last_reviewed`, `security_score`, `supersedes`) followed by Markdown body.

Five kinds of canonical artifact:

| Kind | What it is | File location |
|------|------------|---------------|
| **Agent** | An AI persona with a role, triggers, mandatory reviewers, skills, tools | `canonical/agents/<id>.md` |
| **Skill** | A focused knowledge pack (when to load, patterns, pitfalls) | `canonical/skills/<domain>/<id>.md` |
| **Command** | A slash-command definition (`/scaffold-doctype`, etc.) | `canonical/commands/<id>.md` |
| **Tool** | A wrapper around a bench command or capability with safety checks | `canonical/tools/<id>.yaml` |
| **Policy** | Cross-cutting rules: scoring deductions, review protocol, escalation, governance | `canonical/policies/<id>.{md,yaml}` |

### 3.2 Adapter Layer

Each adapter is a directory under `adapters/<tool>/` containing:

- **`adapter.yaml`** — a capability profile (does the tool support subagents? slash commands? skills?), output paths (where in the bench to write), char budget, artifact-to-strategy mapping
- **`templates/*.j2`** — Jinja2 templates rendering canonical artifacts into the tool's native format
- **`README.md`** — tool-specific limitations and notes

The renderer (`forge/src/forge/render.py`) is the same for all adapters. The differences live in `adapter.yaml` + templates.

### 3.3 Bench Integration

The Frappe v16 bench at `$FORGE_BENCH_PATH`. Forge writes into specific paths inside the bench:
- `.claude/...` for Claude Code
- `.cursor/...` for Cursor
- `.github/...` for Copilot
- `AGENTS.md`, `AGENTS.codex.md` at bench root
- `apps/<custom-app>/CLAUDE.md` for per-app context

Every output directory gets a `.forge-manifest.json` recording source commit + sha256s for drift detection.

### 3.4 Discovery Sidecar

`discovery/INVENTORY.md` (human-authored) + `discovery/data/*.json` (auto-generated by `forge discover` from the live bench). The canonical layer references discovery to ground content in real bench facts: real DocType names, the 10 known `src_override/` files, the 11 known SQL-injection sites in `noviznaerp_payroll`, etc.

---

## 4. Repository layout — every file explained

### Top level

| File | Purpose | Tracked? |
|------|---------|----------|
| `README.md` | Repo intro + Quick Start | ✅ |
| `LICENSE` | Proprietary, internal-use license | ✅ |
| `VERSION` | Repo-level SemVer (currently `0.6.1`) | ✅ |
| `CHANGELOG.md` | Per-release entries in Keep-a-Changelog format | ✅ |
| `PROJECT-STATUS.md` | Current phase, completion counts, blockers | ✅ |
| `ARCHITECTURE.md` | System design + 7 ADRs documenting non-reversible decisions | ✅ |
| `forge.config.yaml` | Global config: bench path, enabled tools, security thresholds, audit retention, commit conventions | ✅ |
| `.env.example` | Template for required env vars (`FORGE_BENCH_PATH`, `FORGE_PRIMARY_SITE`, `FORGE_MARIADB_DSN`, audit-backup vars) | ✅ |
| `.env` | Your actual values (auto-loaded by `cli.py` via python-dotenv) | ❌ gitignored |
| `.gitignore` | Excludes `.env`, `.venv/`, `audit/**/*.jsonl`, `.forge-staging/`, build artifacts | ✅ |
| `.markdownlint.yaml` | Markdown lint config (used by pre-commit + CI) | ✅ |
| `.yamllint.yaml` | YAML lint config | ✅ |
| `.pre-commit-config.yaml` | Local pre-commit hooks: gitleaks, markdownlint, yamllint, `forge score --staged`, `forge validate`, `forge commit --check` | ✅ |

### `.github/`

| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | CI pipeline: `gitleaks` (secrets scan) → `lint` (markdownlint + yamllint via uv tool install) → `forge` (uv sync --frozen + validate + score --fail-below 80 + pytest + sync --all --dry-run). Uploads `audit/` as artifact on failure. |

### `canonical/agents/` — 8 files

The architect orchestrator + 7 specialist personas. Each file has frontmatter + Markdown body following the same structure (role table, triggers, skills, tools, rules, workflow, example task).

| File | Specialist role |
|------|-----------------|
| `architect.md` | Top-level orchestrator. Decomposes tasks, delegates to specialists, runs peer review, escalates per rules, does closing documentation. Foundational. |
| `backend-specialist.md` | Frappe Python work (DocTypes, hooks, whitelist APIs, patches, fixtures, reports, print formats, database queries). Consolidates the v0.1 Reports & Database specialists. |
| `frontend-frappe-ui-specialist.md` | `novizna_crm` Vue3/Frappe-UI work using the 3-layer override system. |
| `frontend-quasar-specialist.md` | `novizna_pos` Quasar PWA work. Knows the Frappe session cookie + CSRF auth model. |
| `integrations-specialist.md` | Vendor connectors (Zoho, HubSpot, LinkedIn, Google, Invoice Ninja), webhooks, OAuth, retry/backoff. |
| `security-reviewer.md` | Mandatory reviewer for backend/integrations/devops outputs. Holds veto on CRITICAL findings. |
| `qa-test-engineer.md` | Tests every change to ≥80% coverage. FrappeTestCase + pytest + Playwright. |
| `devops-deployment.md` | Procfile/scheduler/cron, app install, bench restart (only agent allowed to invoke it). |

### `canonical/skills/` — 30 files across 10 domains

Each skill is a Markdown file with frontmatter (`foundational: true|false`, `scope: [agent:...]`, `trigger`, `domain`) plus body sections (When to Load, Key Concepts, Patterns, Common Pitfalls, References).

```
canonical/skills/
  frappe-core/          (6 skills — conventions, doctype-authoring, hooks-and-events,
                         whitelist-api-patterns, permissions-model, migration-patches)
  frontend/             (3 — frappe-ui-components, novizna-crm-override-system,
                         vue3-quasar-patterns)
  data/                 (2 — sql-best-practices, mariadb-debugging)
  reporting/            (4 — script-report-authoring, query-report-authoring,
                         print-format-authoring, workflow-authoring)
  integrations/         (3 — oauth-patterns, webhooks, queueing-retry-backoff)
  security/             (2 — review-checklist, secrets-handling)
  testing/              (3 — frappe-unittest, pytest-patterns, e2e-playwright)
  debugging/            (1 — bench-logs)
  erpnext-domains/      (5 — sales, accounting, hr-payroll, pos, crm)
  meta/                 (1 — skill-authoring-guide)
```

14 of these are **foundational** (always loaded for their in-scope agents). The other 16 are **model-invoked** (loaded on demand).

Every skill is grounded in real bench facts — it cites AP-ids from `discovery/data/anti-pattern-findings.json` when discussing anti-patterns, references real DocType names, and uses real app paths in examples.

### `canonical/commands/` — 17 files

Each command file declares: which agents it triggers, what arguments it takes, the pipeline of work, and example invocations.

```
scaffold-doctype, scaffold-api, review-security, write-tests, migrate-patch,
add-integration, explain-hook, optimize-query, forge-sync, audit-skills,
override-frontend, generate-report, generate-print-format, sync-erpnext,
explain-doctype, bench-logs, diff-upstream
```

### `canonical/tools/` — 14 YAML files

Each tool spec declares:

- `wraps:` — the bench command or capability
- `inputs:` — argument schema
- `outputs:` — what comes back
- `requires_confirmation:` + `confirmation_token:` — destructive tools require typing the site name
- `audit_severity:` — `low | medium | high`
- `safety_checks:` — pre/post conditions
- `allowed_callers:` — which agents can invoke this tool

```
bench-{migrate, clear-cache, restart, console, logs}
doctype-scaffolder, fixture-exporter, patch-generator,
override-checker, frontend-build, mariadb-query,
api-endpoint-tester, git-status-all-apps, fixture-differ
```

### `canonical/policies/` — 4 files

| File | Purpose |
|------|---------|
| `security-scoring.yaml` | Deduction table: starting score 100, per-rule deductions (e.g. -50 reads site_config, -40 dangerously-skip-permissions, -30 SQL f-string). Thresholds: ≥95 auto-accept / 80–94 warn (typed justification) / <80 block / external ≥98. |
| `review-protocol.md` | Mandatory reviewer pairings, review output format, 2-loop revision cap, conflict resolution. |
| `escalation-rules.md` | 10 escalation triggers, escalation message format, audit-trail rules. |
| `governance.md` | Ownership, versioning, deprecation lifecycle, calibration cadence, out-of-scope hard limits. |

### `adapters/` — 7 adapters

Each adapter directory has the same shape: `adapter.yaml`, `templates/*.j2`, `README.md`.

| Adapter | adapter.yaml strategy | Templates |
|---------|-----------------------|-----------|
| `claude-code/` | `one_file_per_{agent,command,skill,tool}` + `root_claude_md` + `per_app_claude_md` | 7 templates (agent.md, command.md, skill.md, settings-tool-permission.json, tool-reference.md, claude-md-root, claude-md-per-app) |
| `cursor/` | `aggregate` + `aggregate_per_app` | 2 templates (forge-main.mdc, forge-per-app.mdc) |
| `opencode/` | `aggregate` + `one_file_per_command` (OpenCode has native slash commands) | 2 templates (AGENTS.md, command.md) |
| `cline/` | `aggregate` + `aggregate_per_app` | 2 templates (00-forge-main.md, forge-per-app.md) |
| `copilot/` | `aggregate` + `aggregate_per_app` (per-app uses `applyTo:` globs) | 2 templates (copilot-instructions.md, per-app.instructions.md) |
| `codex/` | `aggregate` (single file, per Decision 8) | 1 template (AGENTS.codex.md) |
| `antigravity/` | `aggregate` (minimal — architect + 2 specialists only) | 1 template (system.md) |

### `forge/` — the CLI implementation

```
forge/
  pyproject.toml          ← uv-managed dependencies + project metadata
  uv.lock                 ← reproducible install (committed)
  .python-version         ← pins Python 3.14 for uv auto-install
  src/forge/
    __init__.py           ← package marker; __version__
    cli.py                ← Typer entry point; .env auto-load; routes to commands
    models.py             ← typed dataclasses (CanonicalArtifact, ToolSpec, DiscoverySnapshot, ForgeContext)
    loader.py             ← parses canonical/* + discovery/*.json into models
    render.py             ← Jinja-based renderer; dispatches by strategy
    sync.py               ← transactional staging + atomic swap + manifest writer; calls _security_gate
    scoring.py            ← regex-based deduction engine (security-scoring.yaml rules)
    audit.py              ← JSONL append, tail viewer, tar+gpg backup
    manifest.py           ← .forge-manifest.json schema, write/read
    settings_merge.py     ← deep merge for .claude/settings.json
    discover_bench.py     ← walks $FORGE_BENCH_PATH/apps/, writes discovery/data/*.json
    drift.py              ← reads bench manifests, verifies sha256s, reports drift
    commit_helper.py      ← infers scope+type for Conventional Commits; validates messages
    deprecate.py          ← moves artifacts to canonical/_deprecated/, sets supersedes
    stats.py              ← parses audit JSONL, produces metrics dashboard
    commands/             ← per-CLI-command thin wrappers
      __init__.py
      audit.py, commit.py, discover.py, render.py, score.py, stats.py,
      sync.py, test.py, validate.py
  tests/
    __init__.py
    conftest.py           ← shared pytest fixture (repo_root resolver)
    test_loader.py        ← 14 tests
    test_render.py        ← 6 tests
    test_sync.py / test_manifest.py / test_settings_merge.py / test_scoring.py /
    test_audit.py / test_discover_bench.py / test_drift.py / test_commit_helper.py /
    test_security_gate.py / test_stats.py / test_deprecate.py /
    test_cli_smoke.py / test_cli_integration.py / test_adapters.py
    golden/.gitkeep       ← reserved for golden-fixture tests
```

**146 tests total, 100% passing.**

#### Why each `forge/src/forge/` module exists

| Module | Why it exists |
|--------|---------------|
| `cli.py` | Entry point. Without it, there's no `forge` command. Also handles `.env` auto-loading on startup. |
| `models.py` | Typed dataclasses give every other module a stable contract for what a "canonical artifact" or "discovery snapshot" looks like. Without it, every module would re-parse frontmatter into ad-hoc dicts. |
| `loader.py` | Reading canonical files and discovery JSONs is needed by render, sync, scoring, validate, deprecate, discover. Centralized so the parsing logic exists once. |
| `render.py` | Translates canonical artifacts into per-tool output via Jinja. The single most-imported module across the codebase. |
| `sync.py` | Transactional staging + atomic swap. Without it, you'd have partial writes corrupting the bench on failure. Also hosts `_security_gate` — the Phase 4 enforcement point. |
| `scoring.py` | Regex-based anti-pattern detection. Without it, the security gate has nothing to block on. |
| `audit.py` | Append-only JSONL log. Without it, you can't reconstruct what `forge` did, can't satisfy the v0.2 §8.4 audit trail requirement, can't run `forge stats`. |
| `manifest.py` | `.forge-manifest.json` schema. Without manifests in the bench, drift detection can't tell whether a file was edited or just unchanged. |
| `settings_merge.py` | `.claude/settings.json` deep-merge with backup. Without it, `forge sync --tool claude-code` would either clobber the developer's local settings or fail to merge new permissions. |
| `discover_bench.py` | Walks the live bench. Without it, `discovery/data/*.json` would stay frozen from Phase 0 hand-authoring forever — skills would reference outdated DocType counts. |
| `drift.py` | Compares bench manifests to renderable output. Without it, hand-edits silently rot the bench's relationship to canonical. |
| `commit_helper.py` | Scoped Conventional Commits. Without it, commit format drifts and the changelog automation breaks. |
| `deprecate.py` | Lifecycle management. Without it, retired skills/agents accumulate forever and confuse the next reader. |
| `stats.py` | Metrics dashboard. Without it, the audit log is opaque — no way to see "what blocked last week?". |

### `discovery/` — bench snapshot

| File | Purpose | Maintained by |
|------|---------|---------------|
| `INVENTORY.md` | Human-readable bench summary: app stack table, hooks matrix, DocType highlights, override map, anti-pattern findings, recommended skill priorities | Hand-authored; refresh manually when structure changes |
| `data/apps-index.json` | Per-app metadata: name, stack, custom DocType count, whitelist API count, purpose (from pyproject.toml) | `forge discover` auto-generates |
| `data/hooks-index.json` | Per-app boolean signals: doc_events / scheduler_events / fixtures / overrides / app_include_js / after_install | `forge discover` |
| `data/doctype-index.json` | DocType IDs per custom app | `forge discover` |
| `data/api-surface.json` | Whitelist method counts + sample names per app | `forge discover` |
| `data/override-map.json` | The 10 `src_override/` files in `novizna_crm`, plus `src/` top-level entries | `forge discover` |
| `data/integrations-map.json` | Vendor connector files + endpoint URLs | Hand-curated (not yet automated) |
| `data/anti-pattern-findings.json` | Per-app file:line attribution for SQL f-string, allow_guest, ignore_permissions, db.commit() in non-test | `forge discover` |
| `data/site-config-keys.json` | **Key names only** from site_config.json + common_site_config.json (values never read). Flags `ignore_csrf` if set. | `forge discover` |

Skills cite these JSONs by relative path so the AI agents can ground recommendations in real facts: `[discovery AP-001](../../../discovery/data/anti-pattern-findings.json)`.

### `docs/`

| File | Purpose |
|------|---------|
| `onboarding.md` | 11-step walkthrough for first-time developers: install → tour → run the loop → edit a skill → handle gate blocks → deprecate → audit/metrics → adapter additions → commit style |
| `incident-response.md` | 7 numbered recovery procedures: security-gate block, drift, secret leak, multi-tool sync abort, settings.json clobber, audit corruption, CI-only failure. Each with verification step. |
| `how-it-works.md` | This document |

### `audit/`

| File | Purpose |
|------|---------|
| `audit/.gitkeep` | Keeps the directory tracked; the actual logs are gitignored |
| `audit/<YYYY>/<MM>/forge-audit.jsonl` | Append-only log; one entry per `forge` invocation. Gitignored. |

Schema per entry (enriched by `audit.py:audit_log()`):
```json
{"ts": "...", "session_id": "uuid", "host": "...", "user": "...",
 "action": "sync.live", "tool": "claude-code", "files_written": [...],
 "per_file_scores": {...}, ...}
```

### Ephemeral / build dirs

- `build/` — `forge render --out build/` writes per-tool output here for inspection (not committed)
- `forge/.venv/` — uv-managed virtualenv (gitignored)
- `forge/forge.egg-info/` — pip artifact (gitignored)
- `forge/.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/` — tool caches (gitignored)
- `$FORGE_BENCH_PATH/.forge-staging/` — sync stages here before atomic swap (gitignored at the bench, not in this repo)

---

## 5. End-to-end: what happens when you run `forge sync --all`

Concrete trace of every step for a single invocation:

```bash
cd ~/Work/Projects/ai/erpnext-ai-forge/forge
uv run forge sync --all
```

### Step 1 — `uv run forge` resolves to the venv

`uv run` activates `forge/.venv/` (created by `uv sync`) and invokes the `forge` script declared in `forge/pyproject.toml` `[project.scripts]`. That entry resolves to `forge.cli:app`.

### Step 2 — `cli.py` loads `.env`

At module import (before Typer dispatches), `_load_env_files()` walks up from cwd looking for `forge.config.yaml`, finds it at `~/Work/Projects/ai/erpnext-ai-forge/`, and `load_dotenv()` reads the adjacent `.env`. `FORGE_BENCH_PATH` and `FORGE_PRIMARY_SITE` are now in `os.environ`. Existing shell exports win (`override=False`).

### Step 3 — Typer dispatches to `sync_cmd.run()`

`forge sync --all` matches the `@app.command()` defined in `cli.py`. It calls `forge.commands.sync.run(tool=None, all_tools=True, dry_run=False, justify=None)`, which calls `forge.sync.run_sync(...)`.

### Step 4 — `run_sync` reads `forge.config.yaml` and iterates `enabled_tools`

`load_forge_config()` parses `forge.config.yaml`. The `enabled_tools:` list yields the 7 adapter names. For each tool, `sync_tool()` is called.

### Step 5 — `sync_tool` builds the render plan

For each tool:
1. Resolves `$FORGE_BENCH_PATH` to a `Path`. Refuses if the path doesn't exist or has no `apps/` directory.
2. Calls `render.render(repo_root, tool)`.

### Step 6 — `render.render()` loads everything and runs Jinja

1. `loader.load_adapter_config(tool)` reads `adapters/<tool>/adapter.yaml`
2. `loader.load_forge_config()` reads `forge.config.yaml`
3. `loader.load_discovery()` reads `discovery/data/*.json` into a `DiscoverySnapshot`
4. Builds a `ForgeContext` (repo HEAD commit, render timestamp, bench path)
5. Resolves the adapter's `output_paths:` dict iteratively (later keys can reference earlier ones via Jinja)
6. Sets up a Jinja2 `Environment` with `FileSystemLoader(adapters/<tool>/templates/)` and `StrictUndefined` (catches typos loudly)
7. Iterates the `artifacts:` dict in `adapter.yaml`. For each entry, dispatches on `strategy:`:
   - `one_file_per_agent` → for each `canonical/agents/*.md`, render the named template, produce one `RenderedArtifact`
   - `one_file_per_command`, `one_file_per_skill_in_domain_dir` → similar
   - `settings_permissions_plus_doc` → for each tool spec, render the doc and emit a settings-fragment for the merger
   - `aggregate` → render ONE file from the whole canonical set (used by cursor/opencode/cline/copilot/codex/antigravity)
   - `aggregate_per_app` → render ONE file per custom app, passing the app dict as `app:` context

Returns a list of `RenderedArtifact` dataclasses (in-memory only — no disk writes yet).

### Step 7 — `sync_tool` stages to `.forge-staging/<tool>/`

`_stage_artifacts()` creates a fresh `<bench>/.forge-staging/<tool>/` directory (deleting any previous staging), then writes each `RenderedArtifact.content` to a path mirroring its final bench location.

### Step 8 — `_validate_staging` checks for empty files

Any zero-byte staged file aborts the sync.

### Step 9 — `_security_gate` scores canonical sources

`scoring.score_file()` runs the deduction-table regex matches against every unique `source_path` referenced by the rendered artifacts (not against the staging output — see [ADR-006](../ARCHITECTURE.md#adr-006--security-gate-scores-canonical-sources-not-staging-phase-4) for why). Computes a `GateOutcome`:
- `blocked` if any file scores `< block_floor` (80)
- `warned` if any file scores in `[warn_floor, auto_accept)` (80–94)

If blocked: audit-log `sync.blocked_by_security_gate` with findings and per-file scores, then return error.
If warned without `--justify`: audit-log `sync.warned_without_justify`, return error asking for justification.
If warned with `--justify`: audit-log `sync.justified_accept` with the reason text, then proceed.

### Step 10 — `--all` mode: stage every adapter before swapping any

`sync_all()` runs Step 5–9 in dry-run mode for every enabled tool first. If ANY adapter fails, the whole run aborts before any bench file is touched. This is the v0.2 Part B item 7 transactional contract.

### Step 11 — Atomic per-file swap

For each successful tool, `_swap_into_bench()` walks the staging tree and for each staged file:
1. Computes target path under the bench
2. Creates parent dirs
3. Writes content to `target.with_suffix(...tmp)`
4. `tmp.replace(target)` — atomic rename

Existing `.claude/settings.json` gets special handling via `settings_merge.deep_merge()` with a `.forge-backup` snapshot.

### Step 12 — Manifest writing

For each bench output directory that received files, `manifest.write_manifest()` writes a `.forge-manifest.json` recording source commit hash + per-file sha256s + render timestamp + adapter version. Used later by `forge validate --check-drift`.

### Step 13 — Audit entry

`audit.audit_log()` appends a `sync.live` entry to `audit/<YYYY>/<MM>/forge-audit.jsonl` listing files written, tool name, justification if any, per-file scores.

### Step 14 — Console output

`Rich` console prints `✓ synced <tool>: N files written` for each adapter. On failure, prints `✗ <tool>: <error>` with finding details.

---

## 6. The eight `forge` CLI commands

Every command is a thin wrapper in `forge/src/forge/commands/<name>.py` over the real logic in `forge/src/forge/<name>.py` (or relevant module). The wrappers exist so Typer's decoration stays in `cli.py` and the business logic stays pure-Python (testable in isolation).

| Command | What it does | Reads | Writes |
|---------|--------------|-------|--------|
| `forge discover` | Walks `$FORGE_BENCH_PATH/apps/<custom>/`; detects stack; parses hooks.py; lists DocTypes; counts whitelist methods; scans for anti-patterns; records site_config key names (never values) | The bench | `discovery/data/*.json` |
| `forge validate` | Loads every canonical artifact, checks frontmatter schema, verifies tool `allowed_callers` resolve to real agents/commands, optionally runs drift check against bench manifests | `canonical/`, optionally bench `.forge-manifest.json`s | Console report |
| `forge render` | Renders one adapter's output into a local build dir (no bench writes); for inspecting templates | `canonical/`, `adapters/<tool>/`, `discovery/` | `<out-dir>/` |
| `forge sync` | Real sync: render → stage → security gate → validate → atomic per-tool swap → manifest → audit | Everything | Bench + audit log + staging dir |
| `forge audit tail` | Stream recent audit entries with filters (`--action sync.`, `--grep regex`, `--since 1h`, `--json` for piping) | `audit/<YYYY>/<MM>/*.jsonl` | Rich table or JSONL on stdout |
| `forge audit backup` | tar+gpg the audit/ tree to `$FORGE_AUDIT_BACKUP_DIR` for the monthly retention rotation | `audit/` | Backup archive |
| `forge score` | Runs the deduction-table scorer over a path or staged files; exits non-zero if anything scores below `--fail-below` | `canonical/policies/security-scoring.yaml` + target files | Console report |
| `forge test` | Wraps pytest with the project's testpaths | `forge/tests/` | Console |
| `forge commit` | Infers Conventional Commits scope from staged files; `--check` validates `.git/COMMIT_EDITMSG` | git staged paths, `forge.config.yaml` `commits.scopes` | Console |
| `forge stats` | Parses audit JSONL across the repo, summarizes sync outcomes, score distribution, drift incidents, escalations | `audit/<YYYY>/<MM>/*.jsonl` | Markdown report (or `--json`) |
| `forge deprecate <kind> <name>` | Sets `status: deprecated` on the artifact, appends to replacement's `supersedes:`, moves file to `canonical/_deprecated/` | `canonical/<kind>s/` | Mutates artifact, prints suggested CHANGELOG line |
| `forge new` (skeleton) | Placeholder for a future scaffolder | — | — |
| `forge diff` (skeleton) | Placeholder for a future diff command | — | — |

---

## 7. The security gate

The gate sits in `forge.sync._security_gate()` and runs **before** any bench write happens.

### Inputs
- The list of `RenderedArtifact` objects from the render step
- The `security:` block from `forge.config.yaml` (`auto_accept_threshold`, `warn_threshold`, `block_threshold`, `external_skill_threshold`)
- An optional `--justify "<one-line reason>"` from the CLI

### Process
1. For each distinct `source_path` in the rendered set, call `scoring.score_file(path)`
2. `score_file` reads the file, starts at 100, iterates `_DEDUCTION_PATTERNS`, subtracts deductions for matches (respecting `applies_to_extensions` and `skip_if_path_matches` filters)
3. Aggregate min/max across files into a `GateOutcome`

### Outcomes
| Score band | Outcome | Audit action |
|------------|---------|--------------|
| ≥ 95 | sync proceeds silently | `sync.live` |
| 80–94 + `--justify "<reason>"` | sync proceeds; reason logged | `sync.justified_accept` |
| 80–94 without justify | sync aborts; developer must re-run with `--justify` | `sync.warned_without_justify` |
| < 80 | sync aborts unconditionally | `sync.blocked_by_security_gate` |

### Rule table (excerpt from `scoring.py`)

| Rule | Pattern | Severity | Deduction | Applies to |
|------|---------|----------|-----------|-----------|
| D-EDIT-UPSTREAM | `apps/(frappe\|erpnext\|crm\|...)/` | CRITICAL | -50 | `.py / .yaml / .json / .sh` outside docs |
| D-READ-SITE-CONFIG | `(read\|open\|cat\|json.load).*site_config.json` | CRITICAL | -50 | `.py / .sh` outside docs |
| D-CURL-SHELL | `(curl\|wget) … \| (sh\|bash)` | CRITICAL | -50 | anywhere outside canonical/ docs |
| D-DANGEROUS-SKIP-PERMS | `dangerously-skip-permissions` | HIGH | -40 | anywhere outside canonical/ docs |
| D-SQL-FSTRING | `frappe.db.sql(f"...")` | HIGH | -30 | `.py` only |
| D-GUEST-WHITELIST-NO-RATE-LIMIT | `@frappe.whitelist(allow_guest=True)` | HIGH | -25 | `.py` only |
| D-IGNORE-PERMISSIONS-NO-JUSTIFY | `ignore_permissions=True` without same-line `#` comment | HIGH | -20 | `.py` only |

### Why this approach is sound (ADR-006)

The gate scores **canonical sources**, not rendered staging output. Reason: skills legitimately discuss patterns by name (e.g. `security/review-checklist.md` mentions `curl | sh` to teach the rule). Scoring rendered output would fire D-CURL-SHELL on that text. Scoring sources gets the same result with no false positives — rendering is template substitution and never introduces new anti-patterns.

---

## 8. The audit trail

Every `forge` action appends one JSONL line to `audit/<YYYY>/<MM>/forge-audit.jsonl`. The file structure is by-month so a year of activity stays browsable.

Each entry is enriched with:
- `ts` — UTC ISO-8601 timestamp
- `session_id` — random UUID per process (groups related entries)
- `host`, `user` — environment context
- `action` — the verb (`sync.live`, `sync.blocked_by_security_gate`, `discover.run`, `escalation`, etc.)
- Action-specific fields (`tool`, `files_written`, `per_file_scores`, `findings`, `justify`, ...)

### Why this matters

The audit log is the only thing that survives between sessions. When `forge stats --since 30d` reports "5 syncs blocked, 3 with typed justifications, 12 clean", that's derived purely from JSONL. When you investigate "did we ship something risky last month?", you `forge audit tail --action sync.justified_accept --since 30d` and read the `justify` field.

The log is gitignored — secret values must never be committed even by accident. Backup via `forge audit backup` creates monthly tar+gpg archives to `$FORGE_AUDIT_BACKUP_DIR`.

---

## 9. Why each piece is needed (removal impact)

A directory-by-directory thought experiment: what breaks if you delete it?

| Remove this | What breaks |
|-------------|-------------|
| `canonical/agents/` | No personas to render. Every tool gets empty agent dirs. The Architect's orchestration logic disappears. |
| `canonical/skills/` | Tools have no domain knowledge. `forge sync` produces output but it's a hollow shell — Skills TOC is empty everywhere. |
| `canonical/commands/` | `/scaffold-doctype`, `/review-security`, etc. don't exist in any tool. |
| `canonical/tools/` | Agents lose their concrete capabilities. settings.json permission entries don't get generated. |
| `canonical/policies/` | Security scoring rules undefined → `forge score` fails → `forge sync` can't enforce thresholds. Review protocol absent → no defined reviewer pairings. |
| `adapters/` | `forge render` has nothing to render with. Only thing that still works: `forge validate` of canonical alone. |
| `adapters/<one-tool>/` | That tool stops getting synced. Other tools unaffected. |
| `forge/src/forge/cli.py` | CLI entry point gone. Nothing runs. |
| `forge/src/forge/loader.py` | Nothing can read canonical/ — everything that imports it breaks. |
| `forge/src/forge/render.py` | `forge render` + `forge sync` both fail. Score + validate still work. |
| `forge/src/forge/sync.py` | `forge sync` fails. Render still works (it's pure). |
| `forge/src/forge/scoring.py` | Security gate disables → sync stops blocking on findings. |
| `forge/src/forge/audit.py` | No JSONL written. `forge stats` shows empty. Forensics impossible. |
| `forge/src/forge/manifest.py` | No `.forge-manifest.json` written. `forge validate --check-drift` can't tell drift from intentional bench state. |
| `forge/src/forge/settings_merge.py` | `forge sync --tool claude-code` clobbers `.claude/settings.json`. |
| `forge/src/forge/discover_bench.py` | `forge discover` doesn't refresh the snapshot — canonical references to discovery facts go stale forever. |
| `forge/src/forge/drift.py` | `forge validate --check-drift` becomes a no-op. Hand-edits rot silently. |
| `forge/src/forge/deprecate.py` | Can't manage artifact lifecycle. Deprecated content piles up in active dirs. |
| `forge/src/forge/stats.py` | Audit log is opaque. No way to summarize last week's activity. |
| `forge/src/forge/commit_helper.py` | Pre-commit hook for commit-msg format breaks. Commits get inconsistent scoping. |
| `forge/tests/` | CI fails. No regression protection. |
| `discovery/INVENTORY.md` | Onboarding gets harder; no human-readable bench summary. Auto-discovery still works. |
| `discovery/data/*.json` | Canonical skills' cross-references to AP-ids etc. dangle. `forge discover` can regenerate. |
| `forge.config.yaml` | Forge can't find the bench, can't find enabled tools, can't find security thresholds. Nothing works. |
| `forge/pyproject.toml` | `uv sync` fails — no install. |
| `forge/uv.lock` | Reproducible installs disappear. `uv sync` resolves fresh each time → CI versions drift from local. |
| `forge/.python-version` | `uv` picks whatever Python it finds. Might be 3.10 → typing-feature mismatches break the codebase. |
| `.env` | Forge can't resolve `FORGE_BENCH_PATH` → every command that needs the bench fails with a clear error. |
| `.env.example` | New developers don't know which env vars to set. |
| `.github/workflows/ci.yml` | No CI enforcement. PRs can land with failing tests, gitleaks misses, or below-threshold scores. |
| `.pre-commit-config.yaml` | Local hooks don't run pre-commit. Score-staged + commit-format checks are bypassed. |
| `audit/.gitkeep` | The `audit/` dir disappears from git → first `forge sync` has to recreate it. Cosmetic only. |
| `ARCHITECTURE.md` | Future you forgets WHY the system was built this way. ADRs lost. |
| `CHANGELOG.md` | Release history lost. Hard to answer "when did this change?". |
| `PROJECT-STATUS.md` | Current state of phases is opaque. |
| `LICENSE` | Legal ambiguity for any future contributor. |
| `VERSION` | SemVer reference lost. Build/release scripts that read it break. |
| `README.md` | First-impression doc gone. Quick Start unavailable. |
| `docs/onboarding.md` | New developers have no guided walkthrough. |
| `docs/incident-response.md` | When something breaks, no runbook. Recovery becomes ad-hoc. |
| `docs/how-it-works.md` | This document. |
| `.markdownlint.yaml` / `.yamllint.yaml` | Lint becomes inconsistent. CI may pass locally but fail on subtleties. |

---

## 10. Glossary

| Term | Definition |
|------|------------|
| **Agent** | An AI persona with a defined role, mandatory reviewers, and skill access. Lives under `canonical/agents/`. The **architect** orchestrates; **specialists** implement. |
| **Skill** | A focused knowledge pack the AI loads (always or on-demand) to handle a specific task type. Lives under `canonical/skills/<domain>/`. Either `foundational: true` (always loaded for in-scope agents) or `foundational: false` (loaded by demand / TOC reference). |
| **Command** | A slash-command definition like `/scaffold-doctype`. The CLI doesn't actually invoke these — they're rendered as instructions for each AI tool's native slash-command surface (Claude Code, OpenCode) or as paste-able prompt recipes (Cursor, Cline, Copilot, Codex). |
| **Tool** (canonical) | A YAML spec wrapping a bench command (`bench-migrate`) or capability (`doctype-scaffolder`). Has `inputs:`, `safety_checks:`, `requires_confirmation:`. Agents reference tools; the actual implementation is the agent calling the underlying bench command directly. |
| **Adapter** | Per-tool translator under `adapters/<tool>/`. Each has `adapter.yaml` declaring capabilities + output paths + render strategy, plus Jinja templates. |
| **Aggregate strategy** | One template renders the full canonical set into one output file. Used by every adapter except Claude Code. |
| **Aggregate-per-app strategy** | One template renders one output per custom app, passing the app dict as Jinja context. Used by Cursor/Cline/Copilot for app-scoped rules. |
| **`.forge-manifest.json`** | Per-bench-output-directory file recording source commit + per-file sha256s. Read by `forge validate --check-drift`. |
| **`.forge-backup`** | Snapshot of `.claude/settings.json` taken on every sync that touches it. Lets you recover from an unwanted merge. |
| **`.forge-staging/`** | Temp dir under the bench where `forge sync` writes before atomic swap. Auto-cleared on success. |
| **Security gate** | Pre-sync scoring step. Blocks bench writes if any canonical source scores < 80. Defined in `_security_gate()` in `sync.py`. |
| **Justification (typed)** | When a source scores 80–94, developer runs `forge sync --justify "<reason>"`. The reason is logged to audit JSONL alongside the per-file scores. |
| **Drift** | Bench output diverges from canonical source. Detected by comparing on-disk sha256 against `.forge-manifest.json`. |
| **AP-id** | Anti-pattern identifier (AP-001 through AP-006) from `discovery/data/anti-pattern-findings.json`. Skills cite these when discussing specific known issues in the bench. |
| **Canonical source** | The Markdown/YAML file under `canonical/`. The single source of truth. Edit here; everything else is derived. |
| **Rendered artifact** | The output of running a canonical source through a Jinja template. Lives in memory during `forge render` and on disk after `forge sync`. |
| **Foundational vs. model-invoked** | Skill classification. Foundational = always loaded when the relevant agent is active. Model-invoked = loaded on demand. The split exists because inlining all 30 skill bodies into Cursor's `forge-main.mdc` blew the 40K char budget. |
| **uv** | Astral's Python package + venv manager. Replaces pip+venv. Forge uses uv exclusively as of v0.6.1. |
| **`uv run forge ...`** | Activates the uv-managed venv and runs the forge CLI in one step. Alternative: `source forge/.venv/bin/activate` then `forge ...`. |
| **uv.lock** | uv's lockfile recording exact resolved versions. Committed for reproducible installs. CI uses `uv sync --frozen` against it. |
| **`.python-version`** | Tells uv which Python to use (currently 3.14). uv installs it if not present. |
| **ADR** | Architecture Decision Record. Numbered entries in `ARCHITECTURE.md` §8 documenting non-reversible choices with their context + consequences. |

---

## Closing notes

**The framework is feature-complete per the v0.2 ULTRAPLAN roadmap.** All 5 phases shipped (Phase 0 scaffold, Phase 1a/b canonical authoring, Phase 2 sync engine, Phase 3 per-tool adapters, Phase 4 security gates + CI, Phase 5 stats + deprecate + onboarding). 146 tests passing on Python 3.14 under uv.

Future iteration is calibration-driven, not roadmap-driven:
- Skill scoring re-calibration after the first 10 real-bench tasks
- Quarterly `/audit-skills` runs per `governance.md` §5
- 3-month AI Forge convention checkpoint (next: 2026-08-23 per ADR-001)
- New adapters when new vibe-coding tools emerge

The README's Quick Start is the entry point for daily use. This document is the entry point for *understanding* the system.
