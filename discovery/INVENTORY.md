# Bench Inventory — 2026-05-23

**Bench root:** `/home/tayyab/Work/Projects/erp/novizna-v16/novizna-v16/`
**Discovery pass:** Phase 0 initial (hand-authored; `forge discover` will automate in Phase 2)
**Authoritative plan:** [`ULTRAPLAN-AI-FRAMEWORK-v0.2.md`](../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md)

---

## 1. Apps

### Upstream (11 — never modify)

| App | Stack | Frontend |
|-----|-------|----------|
| `frappe` | Python framework | — |
| `erpnext` | Python | — |
| `crm` | Python | Vue 3 + Frappe-UI |
| `hrms` | Python | Vue 3 + Frappe-UI |
| `lending` | Python | — |
| `lms` | Python | Vue 3 + Frappe-UI |
| `education` | Python | Vue 3 + Frappe-UI |
| `helpdesk` | Python | Vue 3 + Frappe-UI |
| `gameplan` | Python | Vue 3 + Frappe-UI |
| `drive` | Python | Vue 3 + Frappe-UI |
| `press` | Python | Vue 3 + Frappe-UI |

### Custom (8 — active development surface)

| App | Stack | Custom DocTypes | Whitelist APIs | Purpose |
|-----|-------|----------------:|---------------:|---------|
| `novizna_crm` | Python + Frappe-UI/Vue3 (3-layer override) | 2 | 40 | CRM extension over upstream `crm` |
| `novizna_core` | Python | 0 | 1 | Cross-app utilities; currency exchange |
| `novizna_pos` | Python + **Quasar PWA** | 3 | 33 | POS PWA with restaurant integration |
| `invoice_ninja_integration` | Python + JS bundle | 10 | 56 | Invoice Ninja two-way sync + webhooks |
| `noviznaerp_payroll` | Python | 73 | 53 | Payroll (EOBI, salary, biometric, loans) |
| `cargo_management` | Python | 12 | 10 | Parcel tracking + EasyPost/17Track |
| `changemakers` | Python + Frappe-UI/Vue3 | 52 | 9 | Nonprofit / member workflows |
| `erpnext_location` | Python | 4 | 3 | Location/geo extensions |
| **TOTAL** | | **156** | **205** | |

---

## 2. Hooks Matrix (custom apps)

| App | `doc_events` | `scheduler_events` | `fixtures` | overrides | includes | `after_install` |
|-----|:-----------:|:------------------:|:----------:|:---------:|:--------:|:---------------:|
| `novizna_crm` | ✅ | ✅ | — | — | ✅ | ✅ |
| `novizna_core` | — | — | — | ✅ | — | ✅ |
| `novizna_pos` | ✅ | — | — | ✅ | — | ✅ |
| `invoice_ninja_integration` | ✅ | ✅ | — | — | ✅ | ✅ |
| `noviznaerp_payroll` | ✅ | ✅ | — | ✅ | ✅ | — |
| `cargo_management` | ✅ | — | ✅ | — | ✅ | — |
| `changemakers` | ✅ | — | ✅ | — | ✅ | ✅ |
| `erpnext_location` | — | ✅ | ✅ | — | — | ✅ |

(Full dispatch chains pending Phase 2 `forge discover`.)

---

## 3. Custom DocTypes (highlights)

Full machine-readable list in [`data/doctype-index.json`](./data/doctype-index.json).

- **novizna_crm** (2): `crm_import_log`, `crm_lead_industry`
- **novizna_pos** (3): `branch_warehouse`, `cash_variance_entry`, `noviznapos_settings`
- **invoice_ninja_integration** (10): All `invoice_ninja_*` (companies, mappings, sync logs, customer groups, tax rate/template mappings, tasks, settings)
- **noviznaerp_payroll** (73): Largest custom app. Categories include EOBI, salary, biometric, loans, geo-fencing, job applications.
- **cargo_management** (12): Parcel tracking + branch warehouse mappings.
- **changemakers** (52): Nonprofit workflows.

### Naming Conventions Observed

| App | Convention | Notes |
|-----|------------|-------|
| `novizna_crm` | `crm_<noun>` | Consistent |
| `invoice_ninja_integration` | `invoice_ninja_<noun>` | Consistent |
| `noviznaerp_payroll` | bare domain nouns | No app prefix — globally ambiguous |
| `novizna_pos` | mixed (`noviznapos_settings` + `branch_warehouse`) | Inconsistent |

Skill to author: `canonical/skills/frappe-core/conventions.md` should set a project-wide rule and document the exceptions above.

---

## 4. Whitelist API Surface

205 total `@frappe.whitelist()` methods across custom apps. Detailed in [`data/api-surface.json`](./data/api-surface.json).

### Guest-Allowed Endpoints (require special review)

| App | Endpoint | Purpose |
|-----|----------|---------|
| `novizna_pos` | `novizna_pos/api.py:82` | POS guest API (verify intent) |
| `cargo_management` | `parcel_management/.../easypost_api.py:84` (POST) | EasyPost webhook receiver |
| `cargo_management` | `webhook_17track` | 17Track webhook |
| `noviznaerp_payroll` | `www/careers.py:9,21` | Public careers page |
| `noviznaerp_payroll` | `www/job_apply.py:8,22` | Public job application |
| `noviznaerp_payroll` | `www/job_detail.py:5` | Public job detail page |

---

## 5. Integration Map

Vendor SDK wrappers at `apps/novizna_crm/novizna_crm/api/connectors/` (per Decision 18):
`google_sheets.py`, `hubspot.py`, `linkedin.py`, `zoho.py`

Vendor endpoints touched:
- **LinkedIn:** `api.linkedin.com/v2`
- **Google:** OAuth, Drive v3, Sheets v4
- **Zoho:** CRM v2, Sheet v2

Orchestration (NOT in `connectors/`): `apps/novizna_crm/novizna_crm/api/{crm_import,universal_import,import_leads,connector_manager,leads,deals,erpnext_sync}.py`.

Separate apps:
- `invoice_ninja_integration` — has own DocTypes + custom fields on ERPNext doctypes
- `cargo_management` — EasyPost + 17Track webhook integrations

Full map in [`data/integrations-map.json`](./data/integrations-map.json).

---

## 6. Frontend Override Map — `novizna_crm`

The 3-layer system (Decision 16). Detailed in [`data/override-map.json`](./data/override-map.json).

### `src_override/` — 10 files shadowing upstream `apps/crm/frontend/src/`

| Override Path | Purpose |
|---------------|---------|
| `main.js` | App entry override |
| `router.js` | Routing override |
| `socket.js` | Realtime override |
| `index.css` | Global styles override |
| `components/Activities/Activities.vue` | Activities tab |
| `components/Layouts/AppSidebar.vue` | Sidebar (Novizna custom items) |
| `composables/useActiveTabManager.js` | Tab state composable |
| `pages/DataImport.vue` | Data import page |
| `pages/Deal.vue` | Deal page |
| `pages/Lead.vue` | Lead page |

### `src/` — net-new top-level entries

`assets/`, `components/`, `index.css`, `index.js`, `noviznaCrmRoutes.js`, `pages/`

### `crm_build/` — **NEVER EDIT** (wiped on every `yarn dev`/`yarn build`)

Validation: `yarn check-conflicts` (`apps/novizna_crm/frontend/`).

---

## 7. POS Frontend Map — `novizna_pos`

- **Workspace:** `apps/novizna_pos/novizna-pos-ui/` (independent Quasar/Vue3/TypeScript)
- **Build:** `quasar build -m pwa` → output copied into `apps/novizna_pos/novizna_pos/public/pos/`
- **Auth model:** Frappe session cookie + CSRF token (per Decision 17; no JWT)
- **Top-level entries:** `App.vue`, `assets/`, `boot/`, `components/`, `composables/`, `css/`, `env.d.ts`, `i18n/`, `layouts/`, `pages/`
- **Restaurant integration:** dedicated composables and components under `src/components/restaurant/`, `src/composables/useRestaurant.ts`

Full map will be expanded in Phase 2 once Quasar pages/composables are catalogued.

---

## 8. Anti-Pattern Findings

| ID | Severity | Pattern | Count | Notes |
|----|----------|---------|------:|-------|
| AP-001 | **HIGH** | `frappe.db.sql(f"...")` SQL injection | 11 | Concentrated in `noviznaerp_payroll` |
| AP-002 | MEDIUM | `@frappe.whitelist(allow_guest=True)` | 10 | Webhooks + public www pages |
| AP-003 | MEDIUM | `ignore_permissions=True` | 99 | Many likely legitimate; verify call-site type |
| AP-004 | MEDIUM | `frappe.db.commit()` in non-test | 73 | Audit per-call-site in Phase 2 |
| AP-005 | **HIGH** | `ignore_csrf=true` in `common_site_config.json` | 1 | Site-wide CSRF disabled — likely for POS; scope it instead |
| AP-006 | INFO | DocType naming convention drift | — | See §3 |

Full details in [`data/anti-pattern-findings.json`](./data/anti-pattern-findings.json).

---

## 9. Site Configuration — Key Names Only

Per Decision 12 + Section 8.5, **never** logs values.

- **`site_config.json` keys:** `db_*`, `encryption_key`, `user_type_doctype_limit` (8 keys)
- **`common_site_config.json` keys:** redis/gunicorn/worker config, `ignore_csrf` (18 keys — see security flag)

Integration credentials (Zoho, HubSpot, Google, LinkedIn, Invoice Ninja) are **not** in `site_config.json` — suggests they live in Settings DocType rows. Phase 2 will inspect Settings DocTypes to map the per-tenant credential layout.

Full list in [`data/site-config-keys.json`](./data/site-config-keys.json).

---

## 10. Open Discovery Gaps

| Gap | Why It's Open | Resolution |
|-----|---------------|------------|
| Full DocType field schemas for `noviznaerp_payroll`, `cargo_management`, `changemakers` | Hand-listing 137 DocTypes is too costly | Phase 2 `forge discover` automation |
| Per-whitelist-method permission check status | Requires AST walk | Phase 2 `forge discover` |
| Fixture content snapshots | Requires `bench export-fixtures` | Phase 2 |
| Print Format inventory | Requires DB query | Phase 2 |
| Workflow inventory | Requires DB query | Phase 2 |
| Vue component dependency graph (CRM + POS) | Requires Vite import analysis | Phase 1b (when authoring frontend skills) |
| Background job inventory (`scheduler_events` dispatch chains) | Requires reading every referenced module | Phase 2 |
| Custom field inventory (Property Setters / Custom Fields fixtures) | Requires DB query OR fixture inspection | Phase 2 |

---

## 11. Recommended Skill Priorities (Phase 1b)

Based on this discovery, the highest-value skills to author first:

1. `frappe-core/conventions.md` — fixes the naming-convention drift (AP-006)
2. `data/sql-best-practices.md` — fixes the 11 HIGH-severity SQL injection findings (AP-001)
3. `frontend/novizna-crm-override-system.md` — encodes the 3-layer rule with the 10 known override files as examples
4. `security/csrf-and-guest-endpoints.md` — addresses AP-002 and AP-005 together
5. `integrations/oauth-patterns.md` — grounded in the real Zoho/Google/LinkedIn connectors
6. `erpnext-domains/pos.md` — grounded in `novizna_pos`'s 33-method API and Quasar workspace

These tie skill content directly to real bench code, satisfying the v0.2 Phase 1b exit criterion (skills carry concrete bench-grounded examples, not generic Frappe).
