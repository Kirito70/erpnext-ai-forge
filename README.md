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

## Install (team members)

The easiest path: run `forge invite "<name>"` on a configured machine and send the printed command. It carries the settings you choose (your company's apps, owned GitHub orgs, a token if the repo is private), so the new user is only asked for their bench path and site.

Without an invite, one command installs the latest release read-only. No repo access or GitHub account needed; requires `git` and `curl` (it offers to install [uv](https://docs.astral.sh/uv/) if missing).

Linux / macOS / WSL:

```bash
curl -fsSL https://github.com/Kirito70/erpnext-ai-forge/releases/latest/download/install.sh | bash
```

Windows (PowerShell; installs into WSL2, where Frappe benches run):

```powershell
irm https://github.com/Kirito70/erpnext-ai-forge/releases/latest/download/install.ps1 | iex
```

The installer runs `forge setup`, which asks for your bench and site, lists the bench's non-upstream apps and asks which are your company's. Answers go to `~/.forge.yaml`, never into this repo. Add apps you create later with `forge apps add <app>`; re-run `forge setup` to change anything.

Re-run the install command to upgrade (settings are kept). Pin a version with `| bash -s -- --version v0.8.0` (`$env:FORGE_VERSION='v0.8.0'` on Windows); remove with `| bash -s -- --uninstall`. For a private repo, `forge invite --token <read-only token>` prints commands that authenticate.

### Configuration files

| File | Tracked | Holds |
|------|---------|-------|
| `forge.config.example.yaml` | yes | Company-neutral defaults |
| `forge.config.yaml` | no (gitignored) | Your overlay in a dev checkout |
| `~/.forge.yaml` | — | Your overlay for installed copies |

Forge layers one overlay on the defaults: `$FORGE_CONFIG` if set, else `forge.config.yaml` beside the defaults, else `~/.forge.yaml`. Mappings merge; lists replace.

## Quick Start (development)

Prerequisite: **[uv](https://docs.astral.sh/uv/)** ≥ 0.10.

```bash
# One-time install: creates forge/.venv, syncs from uv.lock
cd forge && uv sync --all-extras && cd ..

# Render canonical spec into the bench for a specific tool
uv run --project forge forge sync --tool claude-code

# Render for all configured tools (staged + atomic swap)
uv run --project forge forge sync --all

# Refresh discovery snapshot
uv run --project forge forge discover

# Validate schemas + drift
uv run --project forge forge validate

# Score every artifact for security risk
uv run --project forge forge score --path canonical/
```

The `uv run --project forge` prefix can be replaced with `source forge/.venv/bin/activate && forge ...` if you prefer activating the venv.

## Planning Documents

- [`/home/tayyab/Work/Projects/erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md`](../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md) — full v0.2 ultraplan
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — system design, including ADR-001 (AI Forge convention import)
- [`PROJECT-STATUS.md`](./PROJECT-STATUS.md) — current phase, progress, blockers

## License

Proprietary. Internal use within Novizna projects only. See [`LICENSE`](./LICENSE).
