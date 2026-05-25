# Incident Response Runbook

Concrete recovery procedures for `erpnext-ai-forge`. Each scenario has numbered steps and a verification step. Keep this short and actionable — long explanations belong in [`ARCHITECTURE.md`](../ARCHITECTURE.md).

Audit log location (referenced by every procedure): `audit/<YYYY>/<MM>/forge-audit.jsonl`

---

## Scenario 1 — `forge sync` blocked by security gate

**Symptom:** `forge sync` exits non-zero with `Blocked: N finding(s); lowest score below 80` or `Warning: ... Re-run with --justify '<reason>'`.

### Procedure

1. **Read the findings printed to console.** Each lists `[SEVERITY] D-ID at <canonical-path>:<line>`.
2. **Inspect the offending canonical source.** The gate scores canonical sources, not the rendered staging output. Open the file at the reported line.
3. **Confirm against the deduction in [`canonical/policies/security-scoring.yaml`](../canonical/policies/security-scoring.yaml).** Decide whether it's a real anti-pattern or a false positive.
4. **If real:** fix the canonical content, re-run `forge sync --dry-run --tool <t>`. Verify the gate passes.
5. **If a 80-94 warning** that you accept the risk on: re-run with `--justify "<one-line reason>"`. The justification is logged to audit JSONL with the rendered manifest hash, so a future audit can see why a not-fully-clean artifact shipped.
6. **If a false positive** in the scorer's regex rule: either narrow the rule's `applies_to_extensions` / `skip_if_path_matches` in `forge/src/forge/scoring.py`, or add the literal phrase to the path-skip list. Verify by re-running the score test that previously caught it.

### Verify

```bash
forge audit tail --action sync.blocked_by_security_gate -n 5
forge audit tail --action sync.justified_accept -n 5
```

---

## Scenario 2 — Drift detected by `forge validate --check-drift`

**Symptom:** `Drift (N file(s))` printed, with `sha256 mismatch` or `missing` lines.

### Procedure

1. **For each drifted file**, decide whether the hand-edit is intentional.
2. **If accidental (lost work, unintended hand-edit):**
   - Re-run `forge sync --tool <t>` to overwrite with the canonical-rendered version.
   - The previous on-disk content is **not** in `.forge-backup` (only `.claude/settings.json` gets a backup); you may need to recover from git history in the bench directory if it's a tracked file.
3. **If intentional but isolated:** add the change to the corresponding `canonical/` source so future syncs preserve it.
4. **If intentional and broad** (lots of hand-edits in one direction): consider that as a signal the canonical layer is missing content — open an issue against `canonical/` to model it properly, then re-sync.

### Verify

```bash
forge validate --check-drift
# Expected: "✓ No drift across N manifest(s) and N file(s)."
```

---

## Scenario 3 — Suspected secret leak (`.env` value, API token, password)

**Severity: HIGH. Treat as urgent.**

### Procedure

1. **Stop all syncs immediately.** Do not run `forge sync` while the leak is unconfirmed.
2. **Search the audit log for what was logged:**
   ```bash
   forge audit tail --json -n 1000 | grep -iE "api[_-]?key|password|token|secret"
   ```
3. **Confirm whether the leak hit:**
   - The audit JSONL log only (limited blast radius — local file)
   - A rendered bench file (`<bench>/.claude/...`, `<bench>/AGENTS.md`, etc.) — broader if the bench is in a tracked repo
4. **Rotate the leaked credential immediately** in its source system (Zoho, HubSpot, GitHub, etc.).
5. **Purge the value from the audit log.** Since the log is append-only by design, the cleanest fix is:
   ```bash
   # Identify the offending line
   grep -n "<leaked-substring>" audit/<YYYY>/<MM>/forge-audit.jsonl
   # Replace the entry with a redacted version (preserves session continuity)
   sed -i.bak 's/<leaked-substring>/REDACTED/g' audit/<YYYY>/<MM>/forge-audit.jsonl
   # Verify, then remove the .bak
   ```
6. **If the leak hit a rendered bench file**, run `forge sync --tool <t>` to overwrite. If the bench file was committed to a remote repo, additional history rewrite (`git filter-repo`) is required — but **do not push --force** without explicit approval.
7. **Investigate the source:** which agent / tool / template emitted the secret value? Add a guard to whatever produced it; update [`security/secrets-handling`](../canonical/skills/security/secrets-handling.md) with the new pattern.

### Verify

```bash
gitleaks detect --source . --no-banner
forge audit tail --json | grep -iE "api[_-]?key|password|token" | head
# Expected: no matches with raw secret values; only key names should appear.
```

---

## Scenario 4 — `forge sync --all` aborted mid-render (multi-tool failure)

**Symptom:** `Abort: <tool> failed validation — no bench files touched`. Some tools rendered successfully into `.forge-staging/` but no swap happened.

### Procedure

1. **Identify the failing adapter** from the printed message. Note that no bench file was modified — `.forge-staging/` carries the in-flight render.
2. **Inspect the staging dir** to see what was about to be written:
   ```bash
   ls -la <bench>/.forge-staging/<failing-tool>/
   ```
3. **Run the failing adapter in isolation** with verbose error output:
   ```bash
   forge render --tool <failing-tool> --out /tmp/forge-debug-<tool>/
   ```
4. **Common causes:**
   - Template references a frontmatter field that doesn't exist on some artifacts (`StrictUndefined` raises)
   - Adapter.yaml `output:` path uses unresolved `{{ ... }}` placeholder
   - Bench path env var (`FORGE_BENCH_PATH`) not set
5. **Fix the template or adapter.yaml**, then re-run `forge sync --all --dry-run` first to confirm.

### Verify

```bash
forge sync --all --dry-run
# Expected: every adapter prints "✓ dry-run for <tool>: N files in <staging>"
```

---

## Scenario 5 — `.claude/settings.json` clobbered or unexpected behaviour

**Symptom:** Claude Code suddenly behaves differently, permissions look wrong, or you notice settings keys you didn't add.

### Procedure

1. **Restore from the per-sync backup:**
   ```bash
   diff <bench>/.claude/settings.json <bench>/.claude/settings.json.forge-backup
   # If the backup is what you want:
   cp <bench>/.claude/settings.json.forge-backup <bench>/.claude/settings.json
   ```
2. **Look up the conflict log entries** to see what forge overrode:
   ```bash
   forge audit tail --grep "scalar.*conflict" -n 20
   ```
3. **If forge's merge logic is at fault**, decide: should the conflict resolution flip (developer-wins instead of forge-wins) for that key? Edit `forge/src/forge/settings_merge.py` if needed and add a test case.

### Verify

```bash
jq . <bench>/.claude/settings.json
# Expected: valid JSON; the keys you care about have the expected values.
```

---

## Scenario 6 — Audit log corruption / disk full / accidental deletion

### Procedure

1. **Check whether monthly tar+gpg backups exist:**
   ```bash
   ls -la "$FORGE_AUDIT_BACKUP_DIR"
   ```
2. **Restore from the most recent backup:**
   ```bash
   cd <repo>
   gpg --decrypt "$FORGE_AUDIT_BACKUP_DIR/forge-audit-<YYYYMM>-<HHMM>.tar.gpg" | tar -xC audit/
   ```
3. **If no backup exists** (bug, missing config, never invoked) — audit history before the loss is unrecoverable. Going forward:
   - Set `FORGE_AUDIT_BACKUP_DIR` and `FORGE_AUDIT_GPG_RECIPIENT` in `.env`
   - Run `forge audit backup` monthly (manual cadence today; a future Phase 5 cron can automate)

### Verify

```bash
forge audit tail -n 10
# Expected: at least the last 10 entries render cleanly.
```

---

## Scenario 7 — CI fails on `forge score` but `forge sync` locally was fine

**Symptom:** `.github/workflows/ci.yml` rejects a PR with score-related failures. Local sync passed.

### Procedure

1. **Confirm versions match.** Local forge may be `pip install -e ../forge/` (live source); CI is `pip install -e forge/` from the PR's snapshot. Discrepancies here are common.
2. **Reproduce locally with the CI flags:**
   ```bash
   forge score --path canonical/ --fail-below 80
   forge validate
   ```
3. **If a new deduction rule was added** (commit to `forge/src/forge/scoring.py`) that flagged previously-clean content: either fix the canonical content, or update the rule's `skip_if_path_matches`. Document in CHANGELOG under **Security**.

### Verify

CI green on the PR after the fix.

---

## Quick-Reference: Key Audit Action Names

| Action | Source | What it records |
|--------|--------|-----------------|
| `sync.dry_run` | `forge sync --dry-run` | files staged but not swapped |
| `sync.live` | `forge sync` (success) | files written to bench |
| `sync.blocked_by_security_gate` | gate < 80 | findings + per-file scores |
| `sync.warned_without_justify` | gate 80-94 without `--justify` | warns + per-file scores |
| `sync.justified_accept` | gate 80-94 with `--justify "<reason>"` | the reason text |
| `sync.error` | uncaught exception | traceback summary |
| `escalation` | architect escalation triggers (Section 1, [`escalation-rules.md`](../canonical/policies/escalation-rules.md)) | trigger id + reviewer positions verbatim |
