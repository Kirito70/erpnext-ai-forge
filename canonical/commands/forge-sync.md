---
id: forge-sync
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, devops-deployment]
---

# /forge-sync

Run `forge sync` for the current tool, a specific tool, or all enabled tools.

## Usage

```
/forge-sync [--tool <name>|--all] [--dry-run] [--justify "<reason>"]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--tool` | one of | Comma-separated adapter names (e.g. `--tool claude-code,cursor`) |
| `--all` | one of | Sync every adapter in `forge.config.yaml` `enabled_tools` |
| `--dry-run` | no | Render to staging dir + validate; do not swap into bench |
| `--justify` | no | One-line justification required when any artifact scores 80–94 |

## Examples

```
/forge-sync --tool claude-code --dry-run
/forge-sync --all
/forge-sync --tool cursor --justify "Accepted lower score on cursor-rules size cap"
```

## Pipeline

1. **Architect:** delegate to DevOps
2. **DevOps:**
   - Pre-flight: `git-status-all-apps` on the bench (warn if dirty)
   - Run `forge validate` first
   - Run `forge sync --dry-run` if `--all` is set (recommend it)
   - On live run, expect:
     - Staging directory written to `<bench>/.forge-staging/`
     - Per-tool validation of staged output
     - On success: atomic per-tool swap into bench paths
     - On failure of any adapter: full abort, bench untouched
3. **Audit:** every sync writes an entry to `audit/<YYYY>/<MM>/forge-audit.jsonl`
4. **Architect:** synthesize sync report (files written/changed/unchanged per adapter)

## Notes

- Sync is transactional across adapters when `--all` is used ([Part B item 7](../../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md))
- `.forge-manifest.json` is written into every bench output directory recording source commit, version, render timestamp
- `.claude/settings.json.forge-backup` is created on every sync that touches Claude settings (per Part B item 6)

## Tools Touched

- `forge` CLI (canonical/tools/* are not in scope here; this command wraps the forge entry-point itself)
