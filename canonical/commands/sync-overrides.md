---
id: sync-overrides
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-09-29
triggers_agents: [novizna-architect, frontend-frappe-ui-specialist]
---

# /sync-overrides

Merge upstream `apps/crm` changes into every drifting `src_override/` file and the root vite config override after an upstream pull, keeping Novizna customisations. Run it whenever `apps/crm` is updated.

## Usage

```text
/sync-overrides [<override-path>] [--report-only]
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<override-path>` | no | Sync only this override (path under `apps/novizna_crm/frontend/`). Default: every drifting override |
| `--report-only` | no | Stop after the drift report — no edits |

## Example

```text
/sync-overrides
/sync-overrides src_override/pages/Lead.vue
/sync-overrides --report-only
```

## Pipeline

1. **Architect:** in `apps/novizna_crm/frontend/`, run `yarn check-conflicts` then `yarn check-drift`.
   - A `MISSING-UPSTREAM` row or a failing `check-conflicts` means upstream deleted/renamed the file — stop and ask how to re-home the override.
   - `--report-only` ends here: present the table.
2. **Frontend Specialist (Frappe-UI):** for each `DRIFT` row:
   - `yarn check-drift --diff <path>` — the upstream changes since the override's recorded base (not override-vs-upstream, which is mostly our own customisation).
   - Apply the hunks into the override: `patch -p3 -F2 --no-backup-if-mismatch -r <scratch>.rej src_override/<path> < <diff>` for the bulk, then resolve every `.rej` hunk by hand. Review the resulting diff — fuzzed hunks can land in the wrong place.
   - Keep every `CUSTOM ADDITION` block and Novizna-only section; migrate renamed tokens / icons (`lucide-*`, frappe-ui v2 tokens) the same way upstream did in the merged hunks.
   - If the override is byte-identical to its old upstream base (no customisation), just copy the upstream HEAD file.
3. **Frontend Specialist:** review the `↳ imported upstream file changed since base` rows — changed stores/composables/data modules the override calls (e.g. a store function whose signature changed). Also scan the upstream `git diff <old>..HEAD --stat -- frontend/src` for behaviour that moved *into* a non-overridden file (e.g. error toasts moved into `data/document.js`), which makes our copy of the old behaviour a duplicate.
4. **Frontend Specialist:** fix any "imports that resolve nowhere". Report `REDUNDANT` overrides (identical to upstream) — delete them only with the developer's OK.
5. **QA:** `yarn build` must pass; run `scripts/harness/check-file.sh` on each touched file and the harness gates (`full` on `novizna-test`, never `novizna-v16`).
6. **Frontend Specialist:** `yarn check-drift --stamp <path>` (or `--stamp --all`) so `upstream-base.json` records the upstream HEAD each override is now synced to; commit the manifest with the overrides.
7. **Architect:** per-file report — what was ported, what was deliberately kept divergent, anything left for a smoke test.

## Output

```markdown
## Override sync: upstream <old> → <new>

| Override | Base → HEAD | Ported | Kept divergent |
|---|---|---|---|
| pages/Lead.vue | 32ab6fd → 065f288 | convert-disable for Lost, visited records, … | custom tabs |

**Coupled upstream changes checked:** stores/views.js (getDefaultView(routeName)), …
**Redundant overrides:** src_override/router.js (identical to upstream) — delete?
**Build:** ✓ `yarn build` · **check-drift --strict:** ✓
```

## Notes

- `check-conflicts` only proves each override *still exists* upstream; it says nothing about upstream changes inside the file. That gap is what `check-drift` covers.
- `vite.config.js` is a root override (`custom-build.cjs` copies it over upstream's). Deliberate divergences: dev proxy + `getCommonSiteConfig()`, no VitePWA.
- `socket.js` keeps our dev-proxy branch; the prod branch uses `window.socketio_port` from `get_boot()`.
- Files with no `upstream-base.json` entry get a base inferred from `apps/crm` history (closest upstream version). Always stamp after syncing so the next run is exact.
- Do not run frappe-ui's `migrate-tokens-v2.js` codemod over a mix of merged (v2) and custom code — its typography pass would shift the already-migrated upstream classes.

## Tools Touched

- [`override-checker`](../tools/override-checker.yaml) — `yarn check-conflicts`
- `yarn check-drift` (`apps/novizna_crm/frontend/check-drift.cjs`) — drift report, `--diff`, `--stamp`, `--strict`
- [`frontend-build`](../tools/frontend-build.yaml) — `yarn build`
