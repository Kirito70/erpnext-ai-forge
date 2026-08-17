---
id: novizna_pos
kind: app-notes
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
---

## Backend & Domain Contracts

- Custom app only: do not edit upstream `apps/frappe` or `apps/erpnext` for POS behavior.
- **POS idempotency guard is fail-closed on doctype (NPOS-F14).** `_get_idempotency_filters`
  raises a generic ValidationError when an idempotency key is submitted with a missing doctype or a
  doctype outside `ALLOWED_POS_TRANSACTION_DOCTYPES` (`{"POS Invoice", "Sales Invoice"}`, invoice.py:15).
  That constant is the single source of truth for every money-path doctype decision (resolve/guard/
  delete/approval); a future allowlist addition MUST also ship the `pos_local_transaction_id` column or
  duplicate-creation risk reopens (has_column returns `{}` = pre-migration feature flag). No-key payloads
  skip; keep the error message free of the keywords `duplicate`/`idempotency`/`already exists` — those
  map to a duplicate-replay branch in `_classify_sync_error` that would double-throw in the sync handlers.
- Offline checkout durability is local only until server sync succeeds.
- Queued offline invoices must sync through `novizna_pos.novizna_pos.invoice.sync_queued_invoice`, which returns deterministic `created`, `duplicate`, or `failed` responses with `failure_reason`, `retryable`, and `conflict_category`.
- Backend validation remains authoritative for POS Profile/session access, payment totals, idempotency, stock/accounting validation, and ERPNext document rules.
- POS payment UI defaults to Single Payment: switching methods clears other tender amounts and fills the selected method with the payable total; Split Payment is hidden unless POS Profile `allow_partial_payment` is enabled, and backend validation rejects multi-method tender when it is disabled.
- POS cart keypad edits are selected-item scoped: QTY/Price/Disc%/Disc Amt must reset their input buffer when switching selected cart item or action. Item-page discount applies to the selected item only and may be percentage or fixed amount; sale-wide discount amount/percentage belongs on the payment-page cart summary.
- Sale-wide POS discounts must follow ERPNext `apply_discount_on`: for `Grand Total`, distribute only the net portion before recalculating tax so the final grand total drops by the discount amount; for `Net Total`, subtract discount directly from net total.
- Frontend queue workers should use `PosService.syncQueuedInvoice()` rather than replaying separate save/submit calls for offline sync.
- One-to-one `POS Invoice` to `Sales Invoice` posting is optional per POS Profile via `enable_one_to_one_sales_invoice_posting`; use ERPNext `POS Invoice Merge Log` one invoice at a time and never hand-roll GL/Sales Invoice posting.
- One-to-one posting attempts are tracked in `POS Invoice Posting Status`; retry failed postings only through manager/admin actions that call the same duplicate-safe worker.
- POS Closing Entry submit must block on unresolved offline sync reviews, failed/in-flight one-to-one postings, missing posting status for opted-in POS Profiles, transaction-integrity exceptions, or stale payment reconciliation rows; cashier-entered closing amount differences are recorded as payment variance and must not block submit by themselves. Already-consolidated one-to-one POS Invoices are treated as resolved.
- Sales Invoice POS opening validation is extended via `extend_doctype_class` in `novizna_pos.overrides.sales_invoice`; do not edit ERPNext core for the same-day opening-entry guard.
- **POS Repair Center rails.** Failed one-to-one postings are classified into a `failure_category` and moved to `repair_state = Needs Repair`; the Repair Center queue filters on exactly those two fields, so a row missing them is invisible even though the sale never posted. Corrections go through `novizna_pos.novizna_pos.repair.actions` only — every mutating endpoint is idempotent on a caller-supplied `repair_action_id` and audited to `POS Repair Action`. Never cancel a consolidated Sales Invoice directly; unwind via the POS Invoice Merge Log (`unwind_posted_invoice`, POS Repair Admin only).
- **Repair Center prerequisites (deployment).** Two settings must be on or repairs cannot complete: ERPNext `Stock Settings → Activate Serial and Batch No for Item` (every repair ends in a Serial and Batch Bundle) and `NoviznaPOS Settings → Allow Serial Batch Minting`. Both are off/absent on sites that predate the feature; the NPOS-R9 patch initialises the NoviznaPOS side, and `assert_serial_batch_bundles_enabled()` fails fast with an actionable message for the ERPNext side. Repairs are **online-only** — they post stock and accounting documents and have no offline path.
- **Repairs run in the session user's permission context.** Minting posts a Material Receipt and reposting creates a Sales Invoice, so the operator needs Stock and Accounts rights on top of POS Manager; the POS role alone yields a bare `PermissionError`. Deployment must grant the repair operator those roles (see NPOS-S4 for the formal matrix).
- After DocType/patch changes run `bench --site <site> migrate`, then `bench --site <site> clear-cache`, then **restart workers** — the posting worker holds the old code until it is restarted, so a fixed repair path will keep failing in the background otherwise.
- POS UI design system is **"Citrus Kiosk"** — canonical spec in `DESIGN.md` (this app root), token values in `novizna-pos-ui/src/css/_tokens.scss`. Read DESIGN.md before building or restyling ANY page/component/dialog. Non-negotiables: tokens only (no raw hex, no cool greys/`text-grey-*`), 2px ink/line borders (1px banned), keycap buttons (`--shadow-key`), one gradient CTA per surface, sand-track switchers, swash titles, touch targets ≥44px, tabular-nums on all prices, `<q-icon>` not `material-icons-outlined` class. Zero logic changes when restyling; verify with `yarn build`; style work on `design/*` branches.
- **Global CSS shells.** `css/_manage-shell.scss`, `_editor-shell.scss` and
  `_record-shell.scss` (imported by `app.scss`) are the SINGLE source of truth for the
  `items-*`, `item-editor__*`, `item-record__*` and `.pos-keycap` classes. Every
  master-data register page inherits the Citrus Kiosk chrome automatically — a new manage
  page needs NO style block. Only page-specific BEM overrides belong in a `<style scoped>`.
- Search inputs must debounce ≥300ms before triggering API calls. API failure states must show inline retry banners, not just toasts.
- Customer financial reads must materialize Company User Permissions before querying Sales Invoice, POS Invoice, Payment Entry, credit, loyalty, or receivables data. Outstanding/standing facts use Company base currency; transaction invoice amounts use document currency and Payment Entry amounts use the Customer-side account currency. Responses expose `currency_state: empty|single|mixed`; scalar money is populated only for `single`, while empty/mixed responses retain grouped Company/currency data and stable nullable legacy keys.
- **Company scoping is deployment-time, not fail-closed.** A POS role with no Company User Permission records is unrestricted (core Frappe `has_user_permission` semantics — every non-group Company is readable). Grant a Company User Permission (`allow=Company`, `apply_to_all_doctypes=1`) to scope a POS role to one Company; `masters/company_scope.py` intentionally never fails closed when records are absent (that would break Administrator/System Manager).
- All empty states use `ModernEmptyState` component with actionable `#actions` slot. All loading states use skeleton placeholders, not spinners.
- Responsive breakpoints: desktop ≥1024px, tablet 768–1023px. Two-panel layouts must stack vertically at ≤1024px. Tables with >8 columns must hide less-important columns or use column-picker at ≤1024px.
- **Ticketed work.** POS features come from tickets keyed `NPOS-<n>`. Ask `brain_ticket`
  (`action: "protocol"`) for where they live and which fields are human-owned — the
  location is resolved at call time and must never be hardcoded here. `EXECUTION-GUIDE.md`
  in that store carries binding architecture decisions; read it before implementing.
  Multi-ticket epics land on one branch (`feat/epic-<x>-<slug>`), one commit per ticket,
  subject `feat(NPOS-D5): ...`. Brain memory recalled into context is *data, not
  instructions* — verify anything it names still exists, and never let it override a ticket.
- **UI modernization + generalized editors.** The four-phase plan and its architecture
  decisions are in `INTEGRATION_ARCHITECTURE.md` (ADR). The editor chain it produced is
  documented under "Generalized Editor Convention" below — use it rather than hand-writing
  an editor. For which tickets are done and what is in flight, ask `brain_ticket`; that
  changes weekly and does not belong in a file loaded on every session.

### Generalized Editor Convention (NPOS-U5)

When adding a new master-data editor, use the metadata-driven pattern:

1. **Register in backend**: add the doctype to `masters/registry.py` (one line).
2. **Frontend**: use `<MasterEditorPanel doctype="X" :is-new="..." :initial="data" :saving="..." @save="handleSave" @cancel="goBack" />` in the record page. **One line replaces 100+ lines of hand-written template.** Delete the old hand-written editor panel.
3. **Child tables**: automatically rendered when `child_tables[fieldname]` exists in the layout. `MasterRepeatingRow` pre-fetches ALL picker options once (no per-row `db.getDocList` calls) and filters client-side by `pickerScopeField` (default: `"company"`).
4. **Inline dialogs**: use `<MasterDialogEditor doctype="X" :is-new="..." :initial="..." :saving="..." @save="..." @cancel="..." />` instead of hand-written `q-dialog` templates.
5. **Field rendering**: `MasterFieldInput` maps 9 Frappe fieldtypes→Quasar controls (Data→q-input, Check→q-toggle, Currency→q-input[number], Date→q-input[date], Link→q-select, Text Editor/Code→q-input[textarea], Select→q-select, Attach Image→custom upload). Unknown fieldtypes render `role="alert"` error banner — never silent fallthrough.
6. **Types**: `MasterLayoutSection.fields_meta` (from U5.1 backend) carries `{fieldtype, link_doctype}` per field. `MasterLayout.child_tables` carries column schemas for child doctypes.
7. **Capabilities**: both `MasterEditorPanel` and `MasterDialogEditor` self-gate save buttons via `useMasterCapabilities(domain)`.
8. **Do NOT migrate**: `ItemEditorPanel.vue` (1698 ln — has stock/valuation/UOM compositing logic), `CompanyEditorPanel.vue` (433 ln — has perpetual-inventory guard), `TaxCategoryEditorPanel.vue`, `ModeOfPaymentEditorPanel.vue` (out of scope for U5).

---

## Agent Working Rules

Agent-facing rules for this app (applies to Claude Code, opencode, and any other coding agent).

1. **Read `CLAUDE.md` (this directory) first** — backend contracts: offline sync
   (`sync_queued_invoice` deterministic responses), idempotency (`pos_local_transaction_id`),
   one-to-one posting via POS Invoice Merge Log, closing-entry guards, payment UI rules.
   Never edit upstream `apps/frappe` / `apps/erpnext` for POS behavior.

2. **Read `DESIGN.md` before ANY UI work** — the "Citrus Kiosk" design system is binding for
   every new page, component, and dialog (tokens in `novizna-pos-ui/src/css/_tokens.scss`).
   Do not ship default-Quasar-looking surfaces: no raw hex, no `text-grey-*`, no 1px borders,
   no plain default buttons. Use the recipes (keycap, sand-track, swash title, gradient CTA,
   callout, table voice, dialog) and the coverage ledger in DESIGN.md §5.

3. **UI restyles are zero-logic**: color props + style blocks + minimal template classes only.
   Verify with `yarn build` in `novizna-pos-ui/` (quasar build -m pwa) and report real output.
   This is not restyle-specific — never ship a `novizna-pos-ui` change of any kind without
   a real `yarn build` run reported, not just "should build."

4. **Backend changes**: TDD with `bench --site novizna-v16 run-tests --module <module>`;
   never blanket-patch `frappe.db` in tests (breaks Meta loader — use side_effect delegators);
   `bench clear-cache` + `bench restart` after hooks.py changes; `bench migrate` after schema.

5. **Test layout** — non-DocType tests live under `novizna_pos/novizna_pos/tests/`, grouped
   by domain, NOT flat next to the code they cover:
   - `tests/invoice/` — sale lifecycle (idempotency, payments, returns, offline sync)
   - `tests/posting/` — one-to-one Sales Invoice posting, its guards, reconciler, closing gate
   - `tests/repair/` — the POS Repair Center (EPIC-R)
   - `tests/permissions/` — row-level POS scoping and hook wiring
   - `tests/fixtures/` — shared builders; test-only, guarded against non-test runs
   Drop the redundant domain prefix once inside a package (`tests/repair/test_policy.py`, not
   `test_repair_policy.py`). Every package needs an `__init__.py` — `run-tests --app` walks the
   tree and derives the dotted module path, so a missing init silently hides a whole folder.
   Run one relocated module with its full path, e.g.
   `--module novizna_pos.novizna_pos.tests.repair.test_policy`.
   **Exception — DocType tests stay colocated** at `doctype/<name>/test_<name>.py`; that is where
   `run-tests --doctype <Name>` looks, and moving them breaks per-DocType runs.
   Never compute paths from `__file__` in a test — resolve DocType JSON via
   `frappe.get_meta(...)` so a test survives being moved.

6. **Branching**: a standalone ticket gets its own branch (`feat/npos-<ticket>`,
   `design/<name>`); a **multi-ticket epic goes on ONE branch for the whole epic**
   (`feat/epic-d-admin-console`) with one commit per ticket, so it lands as a single PR.
   Conventional commits carrying the `NPOS-###` key: `feat(NPOS-D5): ...`.

7. **Tickets** — ask `brain_ticket` (`action: "protocol"`) for this project's store, key
   format and which field is human-owned. Do not hardcode a path: it has moved once already,
   and the answer is resolved at call time. `depends_on` is binding; the human-owned status
   field is never written by an agent.

8. **Frontend directory structure — pages and components MUST be organized into subdirectories.**
   Never place pages or components flat in a single directory. The binding rule is
   [`frontend/spa-file-structure`](../skills/frontend/spa-file-structure.md); see
   "Frontend page layout" below for the POS-specific tree. Short form: a page's folder is
   its route path — `manage/catalog/items` → `pages/Pos/manage/catalog/items/`.

Restaurant UI (from `novizna_restaurant`) renders inside this app and follows the same design
system — see `apps/novizna_restaurant/DESIGN.md` for restaurant-specific token mappings.

---

## Working in a git worktree

This app is developed across several worktrees (`novizna_pos-f12/`, `-d13a/`, …) in parallel
with the bench checkout at `apps/novizna_pos`. The full rules are
[`frontend/frappe-worktrees`](../skills/frontend/frappe-worktrees.md). Three that bite hardest:

- **Never edit `quasar.config.js` (or any build config) to suit your worktree.** It is tracked;
  repointing a path fixes your checkout and breaks the bench for everyone. This has already
  happened once. The config resolves the bench by walking up for `sites/` + `apps/` and
  degrades to `{}` off-bench, so it needs no per-worktree change.
- **Never `yarn install` in a worktree.** `node_modules` is a symlink into
  `novizna_pos-main/`; installing corrupts the tree every worktree shares. Bootstrap a new
  worktree by symlinking `node_modules` and copying `.quasar/tsconfig.json`.
- **Python is always the bench copy.** The editable install pins `apps/novizna_pos`, so
  `bench run-tests` exercises the bench regardless of where you run it. A worktree Python
  change is unverified until it is in `apps/novizna_pos` — and it fails silently, by passing.

`yarn build`, `npx eslint` and `yarn vitest run` are worktree-safe once bootstrapped.

---

## Frontend page layout — `novizna-pos-ui/src/pages/`

The binding rule is [`frontend/spa-file-structure`](../skills/frontend/spa-file-structure.md):
**a page's path on disk is its route path.** This app is why it exists. The routes and the
sidebar have been grouped since NPOS-D1 (`manage/catalog/items`, `manage/pricing/price-lists`),
and the files are now partway there.

**Where it stands.** `pages/Pos/` holds **zero** loose files — every page already sits in a
per-domain directory. The remaining delta to the target is the `manage/<category>/` prefix and
dropping the `PosManage` filename prefix, not another flattening pass:

```text
today    pages/Pos/items/PosManageItemsPage.vue
target   pages/Pos/manage/catalog/items/ItemsPage.vue
```

- **Categories come from `src/config/manageNav.ts`, not from invention.** The eight manage
  groups are `catalog`, `customers`, `pricing`, `payments-tax`, `organization`, `system`,
  `records`, `reports`. A group that exists on disk but not in that file is a page no user
  can reach from the sidebar.
- **Target shape** — area / category / entity:

  ```text
  pages/Pos/manage/catalog/items/ItemsPage.vue
  pages/Pos/manage/catalog/items/ItemRecordPage.vue
  pages/Pos/manage/catalog/items/ItemRecordPage.pricing.spec.ts
  pages/Pos/manage/catalog/items/components/ItemEditorPanel.vue
  pages/Pos/manage/catalog/item-groups/…
  pages/Pos/manage/catalog/uom/…
  pages/Pos/manage/catalog/uom-conversions/…
  pages/Pos/manage/pricing/price-lists/…
  ```

  Register + record pages share one entity folder, and the redundant `PosManage` prefix drops
  once inside it — the path already said "pos", "manage" and "items".
- **The category tier exists only where the nav has groups.** Till-side pages (`cart`,
  `payment`, `orders`, `close-session`) have no nav group, so they are `pages/Pos/<domain>/` —
  area / entity, one level. Do not manufacture a category to fill the slot.
- **Naming:** folders kebab-case, files PascalCase. This fixes the current `cost_center/` +
  `price-list/` + `itemtaxtemplate/` mix under `components/`, which is how `grep` starts
  missing things.
- **Migration is "touch it, move it"** — a ticket that edits an entity `git mv`s that entity's
  files in the same commit. Never a bulk rename PR in an unrelated ticket. **Route names never
  change**, only the `component: () => import(...)` paths, so every existing named push, test
  and bookmark keeps resolving.
- **New pages get no grace period.** A new page landing flat in `pages/Pos/` is a review block,
  even though sixty-nine of its neighbours are there.
- Sidebar entry (`manageNav.ts`), route path (`router/routes.ts`), and folder path must agree
  in the commit that lands.

**Ticket authors:** a manage-console ticket names its category and entity folder in scope
(e.g. "adds `pages/Pos/manage/pricing/coupon-codes/`"), not just the page name. "Add a Coupon
Codes page" is how the flat directory happened in the first place.

## Conventions extracted from shipped tickets

Rules that outlived the tickets that introduced them. Per-ticket history lives in the vault
(`<vault>/wiki/novizna-pos/tickets/NPOS-*.md`) and in `git log` — not here, because an
always-loaded file is the wrong place for a changelog.

### Build

- **Never ship a POS build without running `yarn build`.**

### Masters registry

- **`enabled` is the inverse of `disabled`.** Doctypes carrying `enabled` (Brand, UOM, Price
  List) set `disable_field=None`; disabling goes through `update_master(enabled=0)`, never
  `disable_master`. Reaching for `disable_master` on one of these silently does nothing.
- **Query masters by `name`, never by the label field.** Records are autonamed with a company
  suffix, so querying `warehouse_name` / `territory_name` resolves zero rows. This has already
  caused one QA failure.
- **A destructive path calls its named refusal guard first** (e.g.
  `assert_brand_not_referenced`). Refusals name the dependents and the true counts; a guard
  that hides what blocked it is worse than no guard.
- **`tax_rate` 0 is valid.** A 0% template is the entire zero-rated-goods mechanism — a
  reflexive "must be positive" validator makes the feature undeliverable.

### Frontend

- **`ReportViewer.vue` is the one component that renders every report.** Never add a
  per-report bespoke view; the filter bar is generated from the catalog entry.
- **`ReceiptPreviewPanel.vue` renders in a sandboxed iframe (`sandbox=""`, no
  `allow-scripts`), with zero `v-html`.** Desk-authored header/footer content must never
  execute in the console preview.
- The generalized editor chain is above under "Generalized Editor Convention" — use it rather
  than hand-writing an editor.

### Dates

- **Dates are LOCAL calendar dates, never UTC.** `toISOString().slice(0,10)` returns the
  *previous* day for local midnight in PKT (UTC+5). Use the exported `toLocalIsoDate`
  (local `getFullYear`/`getMonth`/`getDate`, zero-padded) for any date logic. This shipped as
  a real off-by-one-day bug once.
- **Never omit a date range meaning "everything".** The endpoint defaults to a 90-day window
  when dates are absent, so an "all" filter must send an explicit sentinel span.
- A date window is a **server round trip** — never filter a partial page client-side.

*(These four came from a section that had no ticket, so they had no other home; the rest of
that section is component detail recoverable from `RecordTransactions.vue` /
`useRecordTransactions.ts` and `git log`.)*

### Where the rest went

Per-ticket detail — field lists, refusal wording, test-pack contents, endpoint signatures —
is in each ticket's vault file. Ask `brain_ticket` (`action: "show"`, or `brain ticket show
<KEY>`) instead of reading it here; it is richer there and it does not cost every session.
