# Antigravity Adapter

Renders a minimal system prompt into `<bench>/.antigravity/system.md`.

Per [Decision 6](../../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md), Antigravity is treated as a minimal-capability target until its actual config surface is confirmed by direct inspection. The current adapter:

- Inlines only the **architect, backend-specialist, and security-reviewer** personas
- Lists all other specialists as a one-line summary table
- Lists foundational skills as a TOC; never inlines skill bodies
- Treats commands as paste-able recipes (no slash-command support assumed)

## Output

```
<bench>/.antigravity/
  system.md                  # minimal aggregate
  .forge-manifest.json
```

## Char Budget

`max_total_chars: 15000` (provisional). Once the real Antigravity config surface is confirmed, we'll either:
- Bump the budget and inline more specialists/skills, or
- Keep this minimal shape if Antigravity's actual context window is tight.

## Phase 3 Re-Scope Checkpoint

The adapter ships in its minimal form. Confirmation work to do:
- Verify the output path `.antigravity/system.md` is what Antigravity reads
- Confirm whether subagents / slash commands are supported (then re-enable in `capabilities:`)
- Adjust `max_total_chars` to match the real budget
