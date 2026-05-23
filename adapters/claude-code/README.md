# Claude Code Adapter

Renders canonical agents / commands / skills / tools into `<bench>/.claude/` for use by Claude Code.

## Files

| File | Purpose |
|------|---------|
| `adapter.yaml` | Mapping rules (canonical → bench paths, templates per artifact type, settings.json merge strategy) |
| `templates/agent.md.j2` | Subagent format (frontmatter `name` + `description` + body) |
| `templates/command.md.j2` | Slash command format (frontmatter `description` + body) |
| `templates/skill.md.j2` | Skill format — used by Phase 1b skill content |
| `templates/settings-tool-permission.json.j2` | Bash allow-list entries derived from tool specs |
| `templates/tool-reference.md.j2` | Human-readable tool reference doc |
| `templates/claude-md-root.j2` | Bench-root `CLAUDE.md` (cross-cutting only, per Decision 19) |
| `templates/claude-md-per-app.j2` | Per-app `apps/<app>/CLAUDE.md` (Decision 19) |

## What `forge sync --tool claude-code` Produces

```
<bench>/
├── CLAUDE.md                              # cross-cutting only (rendered)
├── apps/<custom-app>/CLAUDE.md            # per-app (rendered × 8 custom apps)
└── .claude/
    ├── CLAUDE.md                           # optional Claude-only override (not currently used)
    ├── settings.json                       # deep-merged; .forge-backup written on every sync
    ├── settings.json.forge-backup
    ├── agents/
    │   ├── architect.md
    │   ├── backend-specialist.md
    │   ├── frontend-frappe-ui-specialist.md
    │   ├── frontend-quasar-specialist.md
    │   ├── integrations-specialist.md
    │   ├── security-reviewer.md
    │   ├── qa-test-engineer.md
    │   └── devops-deployment.md
    ├── commands/
    │   └── *.md                            # 17 slash commands
    ├── skills/
    │   └── <domain>/*.md                   # populated by Phase 1b
    ├── tools/
    │   └── *.md                            # 14 tool reference docs
    └── .forge-manifest.json                # per-output-dir provenance
```

## Context-Loading Strategy

Per [v0.2 §4.0](../../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md), Claude Code is the **subagent-capable** branch:

- Architect uses the **Task tool** to spawn specialists in fresh contexts
- Each specialist receives only the skills with matching `scope_agents:` frontmatter
- Foundational skills (`classification: F`) always present for in-scope agents
- No strict character budget; the Task spawn pattern keeps individual contexts lean

## settings.json Merge Rules (v0.2 Part B item 6)

- Top-level keys: deep merge
- Array values (e.g. permissions lists): union by identity
- Conflicting scalars: forge's value wins; prior value logged to audit JSONL with developer's manifest hash
- `.claude/settings.json.forge-backup` written on every sync

## Phase 2 Work (not yet implemented)

The `forge` CLI commands referenced here (`render`, `sync`, `validate`, `score`) are skeletons today. Phase 2 fills in the actual Jinja rendering, transactional staging, atomic per-tool swap, drift detection against `.forge-manifest.json`, and audit JSONL emission.
