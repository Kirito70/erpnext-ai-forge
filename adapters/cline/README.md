# Cline Adapter

Renders canonical erpnext-ai-forge content into Cline's `.clinerules/` directory.

## Output

```
<bench>/.clinerules/
  00-forge-main.md            # always-loaded — architect + personas + skill TOC
  10-app-novizna_crm.md       # per-app context
  10-app-novizna_pos.md
  10-app-novizna_core.md
  10-app-invoice_ninja_integration.md
  10-app-noviznaerp_payroll.md
  10-app-cargo_management.md
  10-app-changemakers.md
  10-app-erpnext_location.md
  .forge-manifest.json
```

`00-` / `10-` prefix controls load order in Cline (lower first).

## Limitations

- No subagents → persona switch via prompts
- No slash commands → command recipes paste-able from `00-forge-main.md`
- No skill discovery → TOC + expand-on-demand
- Tools via MCP, configured separately

## Char Budget

`max_total_chars: 35000` per file (v0.2 §4.0).
