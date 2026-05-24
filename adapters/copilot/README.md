# Copilot Adapter (GitHub Copilot + VS Code Copilot)

Per [Decision 7](../../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md), one adapter targets both. Writes to `.github/`.

## Output

```
<bench>/.github/
  copilot-instructions.md                  # main always-loaded
  instructions/
    novizna_crm.instructions.md            # applyTo: apps/novizna_crm/**/*
    novizna_pos.instructions.md            # applyTo: apps/novizna_pos/**/*
    novizna_core.instructions.md
    invoice_ninja_integration.instructions.md
    noviznaerp_payroll.instructions.md
    cargo_management.instructions.md
    changemakers.instructions.md
    erpnext_location.instructions.md
  .forge-manifest.json
```

## Strategy

- `copilot-instructions.md` is loaded for every Copilot Chat interaction in this repo
- Per-app instruction files use Copilot's `applyTo:` glob frontmatter to activate contextually
- Skills are TOC-only (Copilot has no skill-discovery mechanism)
- Custom slash-command support is limited; canonical commands are paste-able recipes

## Char Budget

`max_total_chars: 30000` per file (v0.2 §4.0).

## Limitations

- No subagents → persona switching via prompts
- No custom tools → commands are recipes
- No skill discovery → TOC + expand-on-demand
