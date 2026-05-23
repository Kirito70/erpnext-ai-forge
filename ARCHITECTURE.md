# erpnext-ai-forge — Architecture

**Version:** 0.1.0
**Status:** Phase 0 — scaffold complete
**Authoritative plan:** [`ULTRAPLAN-AI-FRAMEWORK-v0.2.md`](../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md)

---

## 1. System Overview

`erpnext-ai-forge` is the canonical source of truth for AI-coding-agent configuration targeting the Novizna v16 ERPNext/Frappe bench. It is structured in three layers:

```
┌─────────────────────────────────────────────────────────────────┐
│  CANONICAL LAYER (tool-agnostic Markdown + YAML)                │
│  canonical/{agents,skills,commands,tools,policies}              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                  forge render
                  forge sync
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  ADAPTER LAYER (per-tool translation + Jinja templates)         │
│  adapters/{claude-code, cursor, opencode, cline,                │
│            copilot, codex, antigravity}                         │
└────────────────────────┬────────────────────────────────────────┘
                         │
                  per-tool output paths
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  BENCH INTEGRATION (rendered configs land here)                 │
│  <bench>/.claude/, <bench>/.cursor/rules/,                      │
│  <bench>/AGENTS.md, <bench>/.github/, etc.                      │
└─────────────────────────────────────────────────────────────────┘
```

The discovery layer (`discovery/`) feeds the canonical layer with bench-specific grounding (DocType IDs, hook handlers, override paths) so agents and skills reference what actually exists, not generic Frappe.

The audit layer (`audit/`) records every agent/tool/command invocation as append-only JSONL, with 1-year local retention.

---

## 2. Canonical Layer

Every canonical file is **Markdown with YAML frontmatter** (except `canonical/tools/*.yaml` which are pure YAML specs). Frontmatter schema:

```yaml
---
id: backend-specialist
kind: agent          # agent | skill | command | tool | policy
version: 1.0.0
status: stable       # stable | beta | deprecated
owners: [m.tayyab9736@gmail.com]
trigger: "When Python/Frappe backend work is requested"
scope: [agent:architect]
foundational: false  # skills only
security_score: 100  # last computed
last_reviewed: 2026-05-23
supersedes: []
---
```

Skills are classified as **F** (foundational — always loaded for in-scope agents) or **M** (model-invoked — loaded on demand).

---

## 3. Adapter Layer

Each adapter has an `adapter.yaml` declaring how to translate canonical artifacts into the target tool's surface. Example fragment:

```yaml
tool: cursor
version: "0.45"
artifacts:
  agents:
    strategy: collapse_into_rules
    output_dir: .cursor/rules
    template: agent.mdc.j2
  skills:
    strategy: scoped_rule_files
    glob_strategy: from_frontmatter
limits:
  max_total_chars: 40000
```

Per-tool capability constraints (no subagents, no slash commands, etc.) are handled via the strategies documented in v0.2 Section 4.0 ("Context Loading Strategy").

---

## 4. Sync Pipeline

```
discovery/ ──┐
canonical/ ──┼──► forge render ──► .forge-staging/<tool>/
adapters/ ───┘                              │
                                            ▼
                              forge validate (per-tool)
                                            │
                                  all pass?
                                            │
                            ┌───────────────┴────────────┐
                          yes                            no
                            │                            │
                            ▼                            ▼
                  atomic per-tool swap          abort entire --all run
                  into <bench>/...              leave bench untouched
                            │
                            ▼
                  write .forge-manifest.json
                  per output dir (source commit hash,
                  source file path, source version,
                  render timestamp, adapter version)
                            │
                            ▼
                  append audit JSONL entry
```

`forge sync --all` is **transactional across adapters**. If any adapter fails render or validation, the entire run aborts before any bench file is touched. Recovery procedure in [`docs/incident-response.md`](./docs/incident-response.md) (to be written).

### 4.1 `.forge-manifest.json` Schema

Written into every bench output directory by `forge sync`:

```json
{
  "schema_version": 1,
  "source_repo": "erpnext-ai-forge",
  "source_commit": "<sha1>",
  "source_files": [
    {
      "path": "canonical/agents/backend-specialist.md",
      "version": "1.0.0",
      "sha256": "<hex>"
    }
  ],
  "adapter": {
    "name": "claude-code",
    "version": "0.1.0"
  },
  "rendered_at": "2026-05-23T14:00:00Z",
  "rendered_by": "forge 0.1.0"
}
```

`forge validate` compares manifest against the canonical repo HEAD to detect drift.

---

## 5. Audit & Governance

- **JSONL format:** one entry per agent/tool/command invocation
- **Path:** `audit/<YYYY>/<MM>/forge-audit.jsonl`
- **Rotation:** daily file; gzip after 30 days
- **Retention:** 1 year local-only; monthly `tar + gpg` backup via `forge audit backup`
- **Secret handling:** key names only; values never logged
- **Schema** (per v0.2 Section 8.4):

```json
{
  "ts": "2026-05-23T14:02:11Z",
  "session_id": "uuid",
  "tool_or_agent": "agent:backend-specialist",
  "action": "render",
  "command": "/scaffold-doctype",
  "inputs_hash": "sha256:...",
  "outputs_hash": "sha256:...",
  "files_written": ["..."],
  "files_read": ["..."],
  "risk_score": 96,
  "warnings": [],
  "human_confirmations": ["bench-restart"]
}
```

### 5.1 Security Scoring

Start each artifact at **100**. Deductions per v0.2 Section 8.2. Thresholds:

| Score | Outcome |
|------:|---------|
| ≥ 95 | auto-accept |
| 80–94 | warn; require typed one-line justification logged to audit JSONL |
| < 80 | block sync |
| External skills | must clear ≥ 98 |

---

## 6. Bench Integration Points

| Tool | Output Target |
|------|---------------|
| Claude Code | `<bench>/.claude/{CLAUDE.md, agents/*.md, commands/*.md, skills/<domain>/*.md, settings.json}` |
| Cursor | `<bench>/.cursor/rules/*.mdc` |
| OpenCode | `<bench>/AGENTS.md` + `<bench>/.opencode/commands/*.md` |
| Cline | `<bench>/.clinerules/*.md` |
| Copilot (GitHub + VS Code, single adapter) | `<bench>/.github/copilot-instructions.md` + `.github/instructions/*.instructions.md` + `.github/prompts/*.prompt.md` |
| Codex | `<bench>/AGENTS.codex.md` (separate file, verified in Phase 3) |
| Antigravity | `<bench>/.antigravity/system.md` + minimal-capability target |

**Per-app `CLAUDE.md` generation:** Bench-root `CLAUDE.md` carries only cross-cutting conventions and points to per-app docs. Each custom app gets its own `apps/<app>/CLAUDE.md` synthesized from the canonical layer (Decision 19).

### 6.1 Upstream-App Guard

Any file write under `apps/{frappe,erpnext,crm,hrms,lending,lms,education,helpdesk,gameplan,drive,press}` is **rejected at the tool layer**. Agents must redirect into a custom app or fixture.

### 6.2 `.claude/settings.json` Merge Rules

- Top-level keys: deep merge
- Array values (e.g., permissions lists): union by identity (no dedup of unrelated entries)
- Conflicting scalars: forge's value wins; prior value logged to audit JSONL with developer's manifest hash (recoverable)
- `.claude/settings.json.forge-backup` written on every sync to prior state

---

## 7. Failure Modes & Recovery

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Adapter render fails mid-`--all` | `forge sync` aborts before any bench write | Re-run after fixing the failing adapter; staging dir cleared automatically |
| Drift in bench output | `forge validate` reports mismatched manifest | `forge sync --tool <t>` re-renders; or hand-edit then snapshot |
| Score below 80 on canonical commit | Pre-commit hook blocks commit | Fix the artifact or override with `--justify "<reason>"` (logged) |
| Lost `.claude/settings.json` keys | `.forge-backup` written on every sync | Restore from `.claude/settings.json.forge-backup` |
| Lost audit log | Monthly `tar + gpg` backup | Restore from backup |

---

## 8. Decision Log (Architecture Decision Records)

### ADR-001 — AI Forge Convention Import

**Status:** Accepted
**Date:** 2026-05-23
**Context:** A pre-existing `ai-forge` repo at `~/Work/Projects/ai/ai-forge/` already encodes useful conventions for agent/skill packaging, security scoring, audit logging, and project status tracking. We need to decide whether `erpnext-ai-forge` depends on that repo as a library, monorepos with it, or copies conventions outright.

**Decision:** **Copy** the following AI Forge conventions into `erpnext-ai-forge`, do **not** declare a runtime dependency:

| Imported Convention | Source in AI Forge | Adaptation Here |
|---------------------|--------------------|----|
| Security scoring (start at 100, deduction-based) | `shared/scoring/base-rubric.yaml` | Adopted; thresholds tightened (≥95 auto-accept vs. AI Forge ≥60 internal; ≥98 external vs. AI Forge ≥75) per v0.2 Decision 11 and Section 8.2 |
| JSONL audit format | `shared/logging/log-schema.yaml` | Adopted shape (id, timestamp, session_id, agent, action, target, status, duration_ms); extended with `risk_score`, `human_confirmations`, `files_written`/`files_read` arrays |
| `PROJECT-STATUS.md` structure | `PROJECT-STATUS.md` | Adopted: Last-Updated/Version/Status header, Quick Stats table, per-section completion tables, Recently Completed, In Progress, Blocked, Metrics, Next Milestones |
| `ARCHITECTURE.md` ADR-inline style | `ARCHITECTURE.md` | Adopted: ADRs inline at Section 8 with Status/Date/Context/Decision/Consequences |
| Skill frontmatter (name, description, version, scope, tags, author) | `shared/schemas/skill-schema.yaml` | Adopted as base; extended with `id`, `kind`, `status`, `owners`, `trigger`, `foundational`, `security_score`, `last_reviewed`, `supersedes` |
| `.gitignore` patterns for Python/Node/IDE/audit | `.gitignore` | Adopted |
| Security threat taxonomy (T1–T7: prompt injection, code exec, FS access, data exfil, API abuse, supply chain, social eng) | `shared/scoring/base-rubric.yaml` | **Not adopted now.** v0.2 uses a flat deduction table per Decision 11. Adopting the T1–T7 categorization is a candidate for the post-Phase-1b calibration pass. |

**Consequences:**
- We can evolve `erpnext-ai-forge`'s conventions independently of AI Forge churn.
- Future merge with AI Forge (per v0.2 Decision 1, 3-month review checkpoint) is still possible. Copied schemas are byte-comparable for that merge.
- We pay a duplication cost: schema drift between the two repos is possible and should be reconciled at each 3-month checkpoint.
- The 3-month merge checkpoint is a recurring agenda item; no implementation work yet.

### ADR-002 — Copy with Header, Not Symlinks or Submodules

**Status:** Accepted
**Date:** 2026-05-23
**Context:** Per v0.2 Decision 3 and Section 2.9, we need a mechanism to project canonical artifacts into the bench.

**Decision:** Render with a `# AUTO-GENERATED FROM erpnext-ai-forge vX.Y.Z — DO NOT EDIT` header and copy via `forge sync`. Write a `.forge-manifest.json` to each output directory.

**Consequences:**
- Symlinks rejected: break in sandboxed tools (Antigravity), opaque to indexers (Cursor).
- Git submodules rejected: too operationally heavy for a single developer across many vibe-coding tools.
- Manifest enables drift detection beyond byte-equality (compares against source commit hash).
- Every sync is auditable via `forge audit --tail`.

### ADR-003 — Phase 1 Split

**Status:** Accepted
**Date:** 2026-05-23
**Context:** v0.2 Decision (Part B item 4) splits Phase 1 into 1a (agents/commands/tools, ~40 files) and 1b (skills with bench-grounded examples, ~30+ files).

**Decision:** Phase 1a runs first to produce a working Claude Code setup with stub skills. Phase 1b runs partially in parallel with Phase 2 (adapter engine), since skill authoring does not depend on adapter renderer code.

**Consequences:**
- Earlier feedback on whether the agent/command shape works.
- Risk: Phase 1b skills authored before Phase 2 adapter rendering may not survive the per-tool translation. Mitigated by golden tests in Phase 2.

### ADR-004 — Separate Codex File, Not Shared `AGENTS.md` Markers

**Status:** Accepted
**Date:** 2026-05-23
**Context:** Per v0.2 Decision 8.

**Decision:** Codex gets `AGENTS.codex.md` (exact filename verified in Phase 3). OpenCode owns the bench-root `AGENTS.md`. No `<!-- FORGE:BEGIN/END -->` markers on shared files.

**Consequences:**
- Markers create merge conflicts the first time the developer hand-edits one section.
- Separate files keep tool-specific contexts isolated.
- Bench-root file count grows by one per added "AGENTS-style" tool — acceptable.

---

## 9. Out of Scope (Phase 0)

The following are explicitly **not** part of Phase 0 and are tracked in the roadmap (`PROJECT-STATUS.md` §10):

- Canonical agent/skill/command/tool content (Phase 1a/1b)
- Adapter rendering code (Phase 2)
- Per-tool adapter templates (Phase 2)
- Multi-tool rollout (Phase 3)
- Security gates + audit enforcement (Phase 4)
- Iteration metrics dashboard (Phase 5)
