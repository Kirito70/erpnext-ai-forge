# Codex Adapter

Renders canonical content into `<bench>/AGENTS.codex.md`.

Per [Decision 8](../../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md), Codex gets its **own file** — separate from OpenCode's `AGENTS.md` — so hand-edits don't conflict across tools (no shared FORGE markers).

## Output

```
<bench>/
  AGENTS.codex.md          # full aggregate
  .forge-manifest.json     # written in same directory
```

## Char Budget

`max_total_chars: 20000` per v0.2 §4.0.

## Limitations

- No subagents, slash commands, skill discovery
- All canonical content surfaces as TOC / persona summaries / command recipes
- Tool integration limited; canonical tools listed for reference only

## Phase 3 Re-Verification

The exact filename (`AGENTS.codex.md` vs alternative) should be verified against Codex's actual behavior when running it for the first time. If Codex picks up only `AGENTS.md`, we'll fall back to a single shared `AGENTS.md` with section markers per the original v0.2 plan note.
