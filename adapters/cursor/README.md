# Cursor Adapter

Renders canonical erpnext-ai-forge content into Cursor MDC rule files.

## Output

```
<bench>/.cursor/rules/
  forge-main.mdc                      # alwaysApply: true — architect + all specialists inlined
  forge-novizna_crm.mdc                # globs: apps/novizna_crm/**/*
  forge-novizna_pos.mdc
  forge-novizna_core.mdc
  forge-invoice_ninja_integration.mdc
  forge-noviznaerp_payroll.mdc
  forge-cargo_management.mdc
  forge-changemakers.mdc
  forge-erpnext_location.mdc
  .forge-manifest.json                 # provenance
```

## Context-Loading Strategy

Cursor has **no subagent concept** — specialists are inlined into `forge-main.mdc` as named personas. The architect prompt explicitly says "switch persona when task type matches." Foundational skills are inlined; model-invoked skills appear as a table of contents the developer can expand on demand.

Per-app `.mdc` files use Cursor's `globs:` frontmatter to scope content to the relevant app directory.

## Char Budget (v0.2 §4.0)

- `max_total_chars: 40000` per rule file (advisory in Phase 3; hard-enforced in Phase 4)
- If the rendered `forge-main.mdc` approaches the budget, consider moving more skills to TOC-only or splitting specialists into separate `.mdc` files

## Limitations

- **No native agents:** rules are the closest analogue
- **No slash commands:** canonical commands surface as paste-able prompt recipes in `forge-main.mdc`
- **Custom tools:** Cursor uses MCP — see `forge.config.yaml` Phase 4 work for MCP wiring
- **Subagent skill-discovery mechanism:** absent — TOC strategy applies

## Sync

```bash
forge sync --tool cursor --dry-run    # stage to .forge-staging/cursor/, validate
forge sync --tool cursor              # atomic swap into <bench>/.cursor/rules/
```
