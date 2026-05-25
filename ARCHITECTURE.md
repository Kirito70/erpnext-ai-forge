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

### ADR-005 — Aggregate Strategy + Per-Tool Char Budgets (Phase 3)

**Status:** Accepted
**Date:** 2026-05-24
**Context:** Phase 3 added six non-Claude adapters (Cursor, OpenCode, Cline, Copilot, Codex, Antigravity). None of them have a subagent / Task-tool equivalent. Per v0.2 §4.0 the spec called for inlining specialists into the architect's rule file with foundational skills inlined and on-demand skills as a TOC, enforced by a per-tool char budget.

**Decision:** Introduce two new render strategies alongside the per-artifact strategies that Claude Code uses:

| Strategy | Behavior | Used by |
|----------|----------|---------|
| `aggregate` | Render the full canonical set (agents + commands + skills + tools) into ONE output file via a single template. Template iterates over the lists and renders persona summaries + skill TOC + tool table + command recipes. | Cursor (`forge-main.mdc`), OpenCode (`AGENTS.md`), Cline (`00-forge-main.md`), Copilot (`copilot-instructions.md`), Codex (`AGENTS.codex.md`), Antigravity (`system.md`) |
| `aggregate_per_app` | Render ONE output per custom app, with each app's discovery facts passed as context. Used for tools that scope context by directory (Cursor `globs:`, Copilot `applyTo:`). | Cursor, Cline, Copilot |

The renderer iterates `adapter_cfg["artifacts"]` and dispatches by `strategy:` key. Existing per-artifact strategies (`one_file_per_agent`, `one_file_per_command`, `one_file_per_skill_in_domain_dir`) continue to work for Claude Code.

Per-tool char budgets (advisory in Phase 3; could become hard-enforced in a future phase):

| Tool | `max_total_chars` per file |
|------|---------------------------:|
| Claude Code | unlimited (Task spawning keeps contexts fresh) |
| Cursor | 40,000 |
| Cline | 35,000 |
| Copilot | 30,000 |
| OpenCode / Codex | 20,000 |
| Antigravity | 15,000 (provisional — re-scope when actual config surface is confirmed) |

**Consequences:**
- Aggregate templates inline specialist personas as **summary tables**, not full bodies. Full agent bodies stay at `canonical/agents/<id>.md` and the templates direct the model to ask the developer to expand if detail is needed.
- Foundational skills are TOC-only on the non-Claude tools (inlining them all blew the budget — Cursor's `forge-main.mdc` was 183KB in the first draft).
- Tools' canonical contracts surface in every adapter (so behavior is consistent), but each tool's actual integration mechanism (MCP, Cursor MCP, none) lives outside `forge sync`.
- A new tool joining the framework needs only an `adapter.yaml` declaring its capability profile + output paths + which strategies to use + Jinja templates. No renderer changes.

### ADR-006 — Security Gate Scores Canonical Sources, Not Staging (Phase 4)

**Status:** Accepted
**Date:** 2026-05-25
**Context:** Phase 4 wires `_security_gate()` into `forge sync` to block before any bench file is touched. The natural-feeling approach was to score the rendered staging output (i.e. the files about to be swapped into the bench). That produced false positives.

**Decision:** Score the **canonical sources** contributing to each render, not the staged rendered output.

**Why:**
- Skills legitimately discuss the deduction patterns by name. `security/review-checklist.md` mentions `curl ... | sh` to teach the rule. Scoring staging fires D-CURL-SHELL on that text inside `.forge-staging/<tool>/.claude/skills/security/review-checklist.md`.
- The scorer already has `skip_if_path_matches: (canonical|docs)` for exactly this reason. But staging paths don't include `canonical/`.
- Rendering is template substitution — it never introduces new anti-patterns. If the canonical source is clean, the rendered output is clean. Scoring canonical sources is sufficient AND eliminates the false-positive class entirely.

`_security_gate(rendered: list[RenderedArtifact])` walks every distinct `source_path` from the rendered set, runs `score_file()`, and aggregates findings. Block/warn thresholds come from `forge.config.yaml` `security:`.

**Consequences:**
- The gate runs the same scoring rules as `forge score --path canonical/` — single source of truth for scoring behavior.
- Tests writing poisoned files to a fake repo had to be careful about path collisions: a file named `_outside-canonical.py` had "canonical" in its path and tripped the skip rule for D-CURL-SHELL. Document this caveat in the test.
- Adapters can never sneak past the gate by emitting templates that introduce CRITICAL patterns at render time — those patterns would be in the canonical source.

### ADR-007 — Deprecation Lifecycle (Phase 5)

**Status:** Accepted
**Date:** 2026-05-25
**Context:** v0.2 governance §3 mandates a deprecation flow: mark `status: deprecated`, move to `canonical/_deprecated/`, retain for one MINOR cycle before removal. The first deprecation cycle is the Phase 5 exit criterion.

**Decision:** Implement `forge deprecate <kind> <name> [--superseded-by <name>]` as a transactional helper that:

1. Loads the artifact's frontmatter and sets `status: deprecated` (atomic temp+rename write).
2. If a replacement is named, finds the replacement artifact, loads its frontmatter, and appends `<name>` to its `supersedes:` list (idempotent — does nothing if already present).
3. Moves the deprecated file from `canonical/<kind>s/<...>` to `canonical/_deprecated/<kind>s/<...>` preserving the relative subpath.
4. Prints a suggested CHANGELOG line in scoped Conventional Commits format.

The `_deprecated/` tree is NOT picked up by `load_agents`, `load_skills`, etc. — those functions glob under `canonical/<subdir>/` and the underscore prefix excludes it. `forge sync` therefore stops rendering deprecated artifacts immediately; the v0.2 plan's "render with [DEPRECATED] banner for one MINOR cycle" is a future enhancement, deferred until we actually have an artifact to deprecate and a reason to keep rendering it.

Manual purge after one MINOR cycle: `rm -rf canonical/_deprecated/<...>` and append a Removed entry to CHANGELOG. Automation can come later if the volume demands it.

**Consequences:**
- Frontmatter mutation reuses `python-frontmatter`'s `dumps()` round-trip. Comments above frontmatter are preserved by python-frontmatter; comments inside the YAML block are NOT preserved (this is a python-frontmatter limitation). No canonical file currently has in-frontmatter comments, so this is fine.
- Deprecation is a write to `canonical/`, so the pre-commit hook's `forge score --staged` runs against the modified file. As long as the deprecated artifact was clean before, setting `status: deprecated` doesn't change its score.
- `forge stats` can read `audit/<YYYY>/<MM>/forge-audit.jsonl` for deprecation-action entries (`forge deprecate` currently doesn't emit one — could be added).

---

## 9. Out of Scope (initial Phase 0)

The following were explicitly **not** part of Phase 0 and have since been implemented. Status as of v0.6.0:

- ✅ Canonical agent/skill/command/tool content (Phase 1a v0.2.0 + Phase 1b v0.3.0)
- ✅ Adapter rendering code (Phase 2 v0.3.0)
- ✅ Per-tool adapter templates (Phase 2 v0.3.0 + Phase 3 v0.4.0)
- ✅ Multi-tool rollout (Phase 3 v0.4.0 — 7 adapters)
- ✅ Security gates + audit enforcement (Phase 4 v0.5.0)
- ✅ Iteration metrics dashboard (Phase 5 v0.6.0 — `forge stats`)

The v0.2 roadmap is complete. Future work is iteration-driven: skill calibration, new adapters as new tools emerge, recurring `/audit-skills` cadence, periodic AI Forge convention checkpoint (next: 2026-08-23 per ADR-001).
