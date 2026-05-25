# Onboarding — erpnext-ai-forge

A 30-minute walk through the framework. Run the commands as you read; the test repo is small enough that everything works locally.

---

## What this framework is

A **single source of truth** (the `canonical/` tree) that gets rendered into per-tool configs for every AI coding tool you use. Edit a skill in `canonical/skills/data/sql-best-practices.md`, run `forge sync --all`, and Claude Code, Cursor, OpenCode, Cline, Copilot, Codex, and Antigravity all pick up the same content in the format each tool natively expects.

**Bench target:** `/home/tayyab/Work/Projects/erp/novizna-v16/novizna-v16/` (Frappe v16 with 8 custom apps).

---

## 1 — Install

```bash
cd ~/Work/Projects/ai/erpnext-ai-forge

# Editable install + dev deps
python3 -m venv forge/.venv
source forge/.venv/bin/activate
pip install -e 'forge/[dev]'

# Verify the CLI works
forge --version
forge --help
```

Set the two env vars `forge sync` needs:

```bash
export FORGE_BENCH_PATH=/home/tayyab/Work/Projects/erp/novizna-v16/novizna-v16
export FORGE_PRIMARY_SITE=novizna-v16
```

(Or copy `.env.example` to `.env` and fill those in.)

---

## 2 — Tour the repo

```text
canonical/          ← edit here; everything else is derived
  agents/           ← 8 agent specs (architect + 7 specialists)
  skills/           ← 30 skill files across 10 domains
  commands/         ← 17 slash command definitions
  tools/            ← 14 tool YAML specs
  policies/         ← security scoring, review protocol, escalation, governance

adapters/           ← per-tool translation rules + Jinja templates
  claude-code/      ← subagent-capable, one file per artifact
  cursor/           ← MDC rules with globs:
  opencode/         ← AGENTS.md + native slash commands
  cline/            ← .clinerules/ aggregate
  copilot/          ← .github/copilot-instructions.md + applyTo:
  codex/            ← AGENTS.codex.md
  antigravity/      ← minimal system.md

forge/              ← the CLI implementation
  src/forge/        ← loader, renderer, sync, scoring, audit, drift, etc.
  tests/            ← 122 tests, 100% passing

discovery/          ← snapshot of the bench's apps + DocTypes + hooks
  INVENTORY.md      ← human-readable summary
  data/*.json       ← machine-readable for skills/agents to cite

audit/              ← append-only JSONL log of every forge invocation
                       (gitignored; backup via `forge audit backup`)

docs/               ← onboarding (this file), incident-response.md
```

---

## 3 — Read before you edit

Three files are essential context:

1. **[`canonical/agents/architect.md`](../canonical/agents/architect.md)** — how the architect orchestrates, what review pairings are mandatory, what the closing documentation sub-phase requires.
2. **[`canonical/policies/security-scoring.yaml`](../canonical/policies/security-scoring.yaml)** — the deduction table; every pattern the security gate watches for.
3. **[`discovery/INVENTORY.md`](../discovery/INVENTORY.md)** — what's actually in the bench. Skills reference real apps and DocTypes from here, not generic Frappe.

---

## 4 — Run the basic loop

```bash
# Verify the canonical layer is well-formed
forge validate

# Score every canonical file against the security rules
forge score --path canonical/

# Render Claude Code's per-tool output (in-memory; doesn't write to bench)
forge render --tool claude-code --out /tmp/forge-build/

# Stage + validate every adapter (no bench write)
forge sync --all --dry-run

# Live sync — writes into the bench
forge sync --tool claude-code
```

After a live sync, the bench has these new files:

```text
<bench>/.claude/
  agents/*.md            ← 8 files (one per agent)
  commands/*.md          ← 17 files
  skills/<domain>/*.md   ← 30 files
  tools/*.md             ← 14 reference docs
  settings.json          ← deep-merged with the existing one
  settings.json.forge-backup
  .forge-manifest.json   ← provenance (source commit, sha256s)
```

---

## 5 — Edit a skill

Open `canonical/skills/data/sql-best-practices.md`. Edit the body. Run:

```bash
forge score --path canonical/skills/data/sql-best-practices.md
forge sync --tool claude-code --dry-run
forge sync --tool claude-code
```

Verify the change landed:

```bash
diff canonical/skills/data/sql-best-practices.md \
     "$FORGE_BENCH_PATH/.claude/skills/data/sql-best-practices.md"
```

The rendered version has an `AUTO-GENERATED` header but otherwise mirrors the canonical body. Edits to the bench file directly are flagged as drift on the next `forge validate --check-drift`.

---

## 6 — When the security gate blocks you

If you edit canonical content in a way that introduces a CRITICAL or HIGH pattern, `forge sync` aborts:

```text
✗ claude-code: Blocked: 1 finding(s); lowest score below 80
  [CRITICAL] D-CURL-SHELL at canonical/skills/data/sql-best-practices.md:42
```

Three responses:

1. **Real anti-pattern:** fix the canonical content and re-run.
2. **Justified risk (80–94 band):** `forge sync --tool claude-code --justify "<one-line reason>"`. The reason is logged to `audit/<YYYY>/<MM>/forge-audit.jsonl`.
3. **False positive in the scorer:** narrow the rule in `forge/src/forge/scoring.py` `_DEDUCTION_PATTERNS` (then add a regression test).

Full recovery procedures are in [`incident-response.md`](./incident-response.md).

---

## 7 — Deprecate something

```bash
# Mark a skill deprecated; move to canonical/_deprecated/
forge deprecate skill foo --superseded-by bar

# The skill body is unchanged; only frontmatter `status: deprecated` is set,
# and `bar`'s frontmatter gains `supersedes: [foo]`.
# `forge sync` continues to render the deprecated artifact for one MINOR cycle.
```

After one MINOR release, manually delete the file from `canonical/_deprecated/`. (No automated purge yet.)

---

## 8 — Audit and metrics

Every `forge sync`, `forge score`, etc. appends a JSONL entry to `audit/<YYYY>/<MM>/forge-audit.jsonl`.

```bash
# View the last 50 entries as a Rich table
forge audit tail

# Filter by action prefix
forge audit tail --action sync. -n 100

# Pipe raw JSONL into jq
forge audit tail --json -n 1000 | jq 'select(.action == "sync.blocked_by_security_gate")'

# Monthly summary (Markdown report)
forge stats --since 30d

# Same data as JSON for dashboards
forge stats --since 30d --json
```

Monthly tar+gpg backup:

```bash
export FORGE_AUDIT_BACKUP_DIR=~/Backups/forge-audit
export FORGE_AUDIT_GPG_RECIPIENT=m.tayyab9736@gmail.com
forge audit backup
```

---

## 9 — Refresh discovery when the bench changes

When you add a DocType or app to the bench, the canonical layer's references to discovery facts become stale. Refresh:

```bash
forge discover                    # walks the whole bench
forge discover --app novizna_crm  # narrow to one app

# Inspect what changed
git diff discovery/data/
```

`discovery/INVENTORY.md` is human-authored — update it manually when the structure (not the counts) shifts.

---

## 10 — Adding a new adapter for a new tool

If you start using a new vibe-coding tool, add an adapter under `adapters/<tool>/`:

```text
adapters/<tool>/
  adapter.yaml          ← capability profile, output paths, mapping rules
  templates/*.j2        ← Jinja templates per artifact strategy
  README.md             ← per-tool limitations and notes
```

Reference one of the existing adapters as a starting point:

- **Subagent-capable** like Claude Code: `adapters/claude-code/`
- **Aggregate single file** like Codex: `adapters/codex/`
- **Aggregate + per-app glob** like Cursor: `adapters/cursor/`
- **Minimal target** like Antigravity: `adapters/antigravity/`

Add the tool to `forge.config.yaml` `enabled_tools:` and write a test in `forge/tests/test_adapters.py`.

---

## 11 — Commit style

Scoped Conventional Commits. The pre-commit hook validates the format. `forge commit -m "<subject>"` infers a `<type>(<scope>):` line from the staged file paths.

```bash
git add canonical/skills/data/sql-best-practices.md
forge commit -m "Add EXPLAIN walkthrough to sql-best-practices"
# Outputs:
#   Proposed commit message:
#     feat(skills): Add EXPLAIN walkthrough to sql-best-practices
#   Type: feat  Scope: skills
#   Run: git commit -m 'feat(skills): Add EXPLAIN walkthrough to sql-best-practices'
```

---

## Where to go next

- **[`ARCHITECTURE.md`](../ARCHITECTURE.md)** — system design + ADRs
- **[`PROJECT-STATUS.md`](../PROJECT-STATUS.md)** — current state of each phase
- **[`ULTRAPLAN-AI-FRAMEWORK-v0.2.md`](../../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md)** — the original plan + 20 resolved decisions
- **[`incident-response.md`](./incident-response.md)** — recovery from common failures
