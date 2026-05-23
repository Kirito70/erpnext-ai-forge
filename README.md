# erpnext-ai-forge

**Canonical source of truth for AI coding agents, skills, slash commands, and tools targeting the Novizna v16 ERPNext/Frappe bench.**

A single set of canonical specifications is rendered into per-tool configuration surfaces (Claude Code, Cursor, OpenCode, Cline, Copilot, Codex, Antigravity) via the `forge` CLI.

---

## Target Bench

`/home/tayyab/Work/Projects/erp/novizna-v16/novizna-v16/` — Frappe v16 multi-app bench with 8 custom apps (`novizna_crm`, `novizna_core`, `novizna_pos`, `invoice_ninja_integration`, `noviznaerp_payroll`, `cargo_management`, `changemakers`, `erpnext_location`) and 11 upstream apps (never modified).

## Repo Layout

| Path | Purpose |
|------|---------|
| `canonical/agents/` | 8 agent specs (architect + 7 specialists) |
| `canonical/skills/` | 20 skill domains (Frappe core, frontend, integrations, security, testing, etc.) |
| `canonical/commands/` | 17 slash command definitions |
| `canonical/tools/` | 14 concrete tool specs (bench wrappers, scaffolders, query runners) |
| `canonical/policies/` | Security scoring, review protocol, escalation rules |
| `adapters/<tool>/` | Per-tool translation rules + Jinja templates |
| `forge/` | Python CLI (`discover`, `validate`, `render`, `sync`, `audit`, `score`, `test`, `commit`) |
| `discovery/` | Output of bench audit passes (`INVENTORY.md` + JSON data) |
| `audit/` | Append-only JSONL audit logs (gitignored) |
| `docs/` | Onboarding, adapter authoring, incident response |

## Quick Start

```bash
# Render canonical spec into the bench for a specific tool
forge sync --tool claude-code

# Render for all configured tools (staged + atomic swap)
forge sync --all

# Refresh discovery snapshot
forge discover

# Validate schemas + drift
forge validate

# Score every artifact for security risk
forge score --path canonical/
```

## Planning Documents

- [`/home/tayyab/Work/Projects/erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md`](../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md) — full v0.2 ultraplan
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — system design, including ADR-001 (AI Forge convention import)
- [`PROJECT-STATUS.md`](./PROJECT-STATUS.md) — current phase, progress, blockers

## License

Proprietary. Internal use within Novizna projects only. See [`LICENSE`](./LICENSE).
