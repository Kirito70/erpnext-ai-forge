# OpenCode Adapter

Renders canonical erpnext-ai-forge content into OpenCode's native multi-file layout. OpenCode is the second subagent-capable target alongside Claude Code, and as of adapter v0.2.0 it gets the same per-artifact treatment instead of one monolithic AGENTS.md.

## Output

```
<bench>/
  AGENTS.md                              # slim index pointing at .opencode/
  .opencode/
    agents/
      architect.md                       # 8 files (one per canonical agent)
      backend-specialist.md
      frontend-frappe-ui-specialist.md
      frontend-quasar-specialist.md
      integrations-specialist.md
      security-reviewer.md
      qa-test-engineer.md
      devops-deployment.md
    commands/
      scaffold-doctype.md                # 17 files (one per canonical command)
      review-security.md
      ...
    skills/
      frappe-core/                       # 30 files across 10 domain subdirs
        conventions.md
        doctype-authoring.md
        ...
      frontend/
        novizna-crm-override-system.md
        ...
      data/
        sql-best-practices.md
        ...
      (10 domains total)
    tools/
      bench-migrate.md                   # 14 reference docs (one per canonical tool)
      doctype-scaffolder.md
      ...
    .forge-manifest.json                 # provenance
```

**70 files total: 8 agents + 17 commands + 30 skills + 14 tools + 1 AGENTS.md index.** Same count as the Claude Code adapter produces.

## Strategy

OpenCode supports agents, slash commands, skills, and tools as first-class artifacts at `.opencode/<kind>/`, mirroring Claude Code's `.claude/<kind>/`. This adapter renders the canonical layer into that native shape — one file per artifact — so OpenCode gets fine-grained context the same way Claude Code does.

- **`AGENTS.md`** at the bench root is a slim **index**, not the full body. It lists every agent/command/skill/tool with its file location so OpenCode can locate detail on demand.
- **Per-agent files** under `.opencode/agents/<id>.md` carry full frontmatter (`name`, `description`, `tools`, `model`) plus the body — same shape as Claude Code subagent files.
- **Per-skill files** under `.opencode/skills/<domain>/<id>.md` preserve the `foundational` + `scope` frontmatter so OpenCode's skill discovery loads the right ones.
- **Per-tool reference docs** under `.opencode/tools/<id>.md` document each canonical tool's inputs, safety checks, and allowed callers. Actual tool wiring (allow-lists, MCP-style integrations) lives in `opencode.json` separately.

## Char Budget

No single-file budget (`max_total_chars: null`). Each rendered artifact is small (typical agent < 8KB, skill < 8KB), so the per-file shape stays under any reasonable budget naturally. The v0.1.0 budget of 20K applied to the old monolithic AGENTS.md, which no longer exists.

## Limitations

- **Tool wiring beyond reference docs:** `opencode.json` is managed by hand (or by a future forge feature). This adapter only emits reference docs at `.opencode/tools/<id>.md` for OpenCode to read.
- **No per-app context files:** unlike Cursor/Cline/Copilot, OpenCode reads a single bench-root AGENTS.md; per-app detail surfaces via skills + the architect's pre-flight discovery check.

## Sync

```bash
forge sync --tool opencode --dry-run    # stage + validate
forge sync --tool opencode              # atomic swap into bench
```
