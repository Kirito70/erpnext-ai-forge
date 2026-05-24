# OpenCode Adapter

Renders canonical erpnext-ai-forge content into OpenCode's `AGENTS.md` + slash-command files.

## Output

```
<bench>/
  AGENTS.md                       # aggregate: architect + personas + skill TOC + tool ref
  .opencode/
    commands/
      scaffold-doctype.md
      ... (17 total)
    .forge-manifest.json
```

## Strategy

OpenCode reads `AGENTS.md` as the primary bootstrap file. Specialists are inlined as persona sections (no subagent / Task-tool equivalent). Skills are TOC-only — too large to fit in OpenCode's 20K char budget.

Slash commands are supported natively: each canonical command renders to `.opencode/commands/<id>.md`, invocable as `/<id>`.

## Limitations

- No subagents → persona switch via prompt patterns
- No skill discovery mechanism → TOC + expand-on-demand
- Custom tools via `opencode.json` separately
