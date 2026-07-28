---
id: novizna_crm
kind: app-notes
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
---

## What This App Is

`novizna_crm` **extends** `frappe/crm` (upstream). It is NOT a fork. The upstream CRM app lives at `../crm/` and is treated as read-only. All customisations live here.

---

## ⚠️ CRITICAL: Frontend Override System

The frontend uses a **three-layer merge** system. Never edit files in the wrong place or changes will be silently overwritten.

### Layers

```
Layer 1: apps/crm/frontend/src/          ← UPSTREAM (read-only, never touch)
                   ↓
             crm_build/src/              ← GENERATED workspace (never touch, wiped on every dev/build)
                   ↑
Layer 2: frontend/src_override/          ← OVERRIDE: files that REPLACE upstream CRM files
Layer 3: frontend/src/                   ← NEW: files that DO NOT exist in upstream CRM
```

### Rules

| You want to... | Where to put the file |
|---|---|
| Change an existing CRM component/page/util | `src_override/` at the **same relative path** as in `apps/crm/frontend/src/` |
| Add a brand-new page, component, or utility | `src/` |
| Edit the sidebar | `src/index.js` (add to `customSidebarItems`) — see below |

### Why sidebar changes were not applying

`crm_build/` is **wiped and regenerated** on every `yarn dev` or `yarn build`. If you edited a file directly inside `crm_build/`, it was gone on the next run. Always edit in `src_override/` or `src/`.

---

## Frontend Dev Commands

```bash
cd apps/novizna_crm/frontend

yarn dev              # start dev server (rebuilds crm_build/, then watches src_override/ and src/)
yarn build            # production build → novizna_crm/public/frontend/
yarn check-conflicts  # verify every src_override/ file still exists upstream (run after CRM updates)
```

---

## Sidebar Extension Pattern

### Adding a sidebar item

Edit `frontend/src/index.js`:

```javascript
export const customSidebarItems = [
  {
    label: 'Import',        // display label
    icon: markRaw(ImportIcon),
    to: 'ImportHub',        // named route
  },
  // Add more items here ↓
]
```

**Do NOT** edit `src_override/components/Layouts/AppSidebar.vue` to add items — it reads `customSidebarItems` via `inject('customSidebarItems', [])`. Only touch it if you need to change sidebar layout/structure.

### How it wires together

```
src/index.js
  └─ NoviznaPlugin.install()
       ├─ router.addRoute(route) for each custom route
       └─ app.provide('customSidebarItems', customSidebarItems)

src_override/components/Layouts/AppSidebar.vue
  └─ const customSidebarItems = inject('customSidebarItems', [])
  └─ ...customSidebarItems  spread into links array

src_override/main.js
  └─ import NoviznaPlugin from './index.js'
  └─ app.use(NoviznaPlugin, { router })
```

---

## Adding Routes

Edit `frontend/src/noviznaCrmRoutes.js`:

```javascript
import { defineAsyncComponent } from 'vue'

export const noviznaCrmRoutes = [
  {
    name: 'ImportHub',
    path: '/import-hub',
    component: defineAsyncComponent(() => import('./pages/ImportHub.vue')),
  },
  // Add routes here
]
```

Page components go in `frontend/src/pages/`.

---

## File Structure

```
frontend/
  src/                          ← NEW files (don't exist in upstream CRM)
    index.js                    ← NoviznaPlugin definition + customSidebarItems
    noviznaCrmRoutes.js         ← custom route definitions
    pages/
      ImportHub.vue
      ImportLeads.vue
      ImportDeals.vue
      ImportHistory.vue

  src_override/                 ← REPLACE upstream CRM files (same relative path as apps/crm/frontend/src/)
    main.js                     ← adds NoviznaPlugin registration
    router.js
    socket.js
    index.css
    components/
      Layouts/
        AppSidebar.vue          ← sidebar with inject('customSidebarItems')
      Import/
        ImportSteps.vue
        MappingStep.vue
        StepUpload.vue
        StepMapFields.vue
        StepPreview.vue
        StepImporting.vue
        StepResults.vue
        ImportHistoryTable.vue
        ImportSourceCard.vue
        TemplateModal.vue
        dataImport.ts
        types.ts
    pages/
      DataImport.vue

  custom-build.cjs              ← production build script (3-layer merge + vite build)
  custom-dev.cjs                ← dev server script (3-layer merge + chokidar watch)
  vite.config.js                ← overrides CRM's vite config, copied into crm_build/ at build time
  check-conflicts.cjs           ← validates all src_override/ files still exist in upstream
  package.json                  ← extra deps (xlsx) merged into crm_build/package.json at build time

crm_build/                      ← GENERATED (gitignored, wiped on every build — never edit)
novizna_crm/public/frontend/    ← compiled output (gitignored)
```

---

## Backend Structure

```
novizna_crm/
  hooks.py                            ← app config: doc_events, scheduler_events, after_install
  api/
    crm_hooks.py                      ← doc event handlers (after_insert, on_update)
    crm_import.py                     ← generic import API (validate, execute, log)
    import_leads.py                   ← lead-specific import (CSV/Excel preview + run_import)
    erpnext_sync.py                   ← ERPNext customer ↔ CRM Lead sync
  novizna_crm/
    custom/
      crm_lead.py                     ← after_migrate(): hides upstream industry field
      crm_lead.json                   ← custom fields for CRM Lead
      crm_deal.json                   ← custom fields for CRM Deal
    doctype/
      crm_lead_industry/              ← child table: multi-industry support
      crm_import_log/                 ← import audit log
    page/
      import_leads/                   ← Frappe page: import-leads
```

### Custom Fields Added

**CRM Lead:**
- `lead_category` — Select: Hot / Warm / Cold / Unqualified
- `region` — Link → Territory
- `import_source` — Select: CSV Upload / HubSpot / Salesforce / ERPNext / Web Form (read-only)
- `import_batch_id` — Data, hidden (internal tracking)
- `erpnext_customer` — Link → Customer

**CRM Deal:**
- `quotation_ref` — Link → Quotation (read-only)
- `sales_order_ref` — Link → Sales Order (read-only)
- `deal_region` — Link → Territory

### API Pattern

All API endpoints use `@frappe.whitelist()`. Always add type annotations and a docstring:

```python
@frappe.whitelist()
def my_function(param: str) -> list:
    """
    Brief description of what this does.

    Args:
        param: description of the parameter.

    Returns:
        list of results.
    """
    # validate inputs early
    if not param:
        frappe.throw(frappe._("param is required"))

    result = frappe.get_list("CRM Lead", filters={"some_field": param})
    return result


@frappe.whitelist()
def my_write_function(data: str) -> dict:
    """Write example — commit only in standalone API functions, never in doc events."""
    doc = frappe.get_doc("CRM Lead", data)
    doc.some_field = "value"
    doc.save(ignore_permissions=True)
    frappe.db.commit()  # ✅ OK here — this is a standalone API function
    return {"name": doc.name}
```

### ❌ HARD RULE: `frappe.db.commit()` in doc events

**NEVER call `frappe.db.commit()` inside doc event handlers** (`after_insert`, `on_update`, `before_save`, etc.).
Frappe manages the transaction. Calling `commit()` inside a doc event breaks transaction atomicity and can cause partial writes that are impossible to roll back.

```python
# ❌ WRONG — will corrupt transactions
def after_lead_insert(doc, method):
    doc.some_field = "value"
    doc.save()
    frappe.db.commit()  # ← NEVER do this in doc events

# ✅ CORRECT — let Frappe manage the transaction
def after_lead_insert(doc, method):
    doc.some_field = "value"
    doc.db_set("some_field", "value", update_modified=False)  # direct DB update without commit
```

### Hooks Pattern

Doc events in `hooks.py`:
```python
doc_events = {
    "CRM Lead": {
        "after_insert": "novizna_crm.api.crm_hooks.after_lead_insert",
        "on_update": "novizna_crm.api.crm_hooks.on_lead_update",
    },
    "CRM Deal": {
        "after_insert": "novizna_crm.api.crm_hooks.after_deal_insert",
    }
}
```

Scheduled tasks:
```python
scheduler_events = {
    "daily": ["novizna_crm.api.erpnext_sync.sync_erpnext_customers"]
}
```

---

## Coding Conventions

- Python: immutable patterns, explicit error handling, never swallow exceptions
- `@frappe.whitelist()` on all API functions
- All Python functions must have type annotations and PEP 257 docstrings
- Vue components: match the upstream CRM style (Options API with `setup()` or Composition API `<script setup>`)
- Use `provide`/`inject` for cross-component communication — do NOT reach for Pinia or global state
- **NEVER** `frappe.db.commit()` in doc event handlers — only in standalone `@frappe.whitelist()` functions
- Custom field JSON files must have `"sync_on_migrate": 1`
- DRY: before writing a new utility composable or Python helper, search the codebase for an existing one
- When showing code edits, always include 3-5 lines of context before and after the change

---

## Skill: Calling Backend APIs from Vue

Never use raw `fetch()` or `axios`. Use the Frappe UI `call` helper:

```javascript
import { call } from 'frappe-ui'

// Simple call
const result = await call('novizna_crm.api.import_leads.preview_import', {
  file_url: '/files/leads.csv',
})

// In a component using createResource for reactive data fetching
import { createResource } from 'frappe-ui'

const leads = createResource({
  url: 'novizna_crm.api.erpnext_sync.get_erpnext_customers',
  params: { limit: 20 },
  auto: true,                // fetch immediately on mount
  onSuccess(data) { /* handle */ },
  onError(err)   { /* handle */ },
})

// Trigger a refetch
leads.reload()

// Access data / loading state
leads.data       // reactive array
leads.loading    // boolean
leads.error      // error object or null
```

---

## Skill: Vue 3 Composition API Patterns (used in this codebase)

```javascript
import { ref, reactive, computed, watch, inject, provide, onMounted } from 'vue'

// provide/inject — the sidebar mechanism and plugin system both use this
// Provider (in plugin install or parent component):
app.provide('customSidebarItems', customSidebarItems)

// Consumer (in any descendant component — no prop drilling needed):
const customSidebarItems = inject('customSidebarItems', [])

// Composables — extract reusable stateful logic into composables under src/composables/
export function useLeadImport() {
  const status = ref('idle')
  const run = async (payload) => { /* ... */ }
  return { status, run }
}
```

**Do NOT** replace `inject/provide` with Vuex/Pinia in the sidebar system — it is intentionally lightweight.

---

## Skill: Import Alias Resolution

After the three-layer merge, `crm_build/` is built as if it were the CRM. Aliases resolve as:

| Alias | Resolves to (after merge) | Use for |
|---|---|---|
| `@/` | `crm_build/src/` (= upstream CRM src) | Importing upstream CRM components/utils |
| `@custom/` | `crm_build/src/` (mapped to our custom src) | Importing files from `src/` |

When writing new components in `src/`, import other custom files with relative paths (`./`, `../`) not `@/` — `@/` will resolve to the upstream CRM, not your file.

```javascript
// ✅ Correct — importing your own file from src/
import { useLeadImport } from '../composables/useLeadImport'

// ✅ Correct — importing an upstream CRM utility
import { formatDate } from '@/utils/format'

// ❌ Wrong — @/ doesn't point to your src/ file
import { useLeadImport } from '@/composables/useLeadImport'
```

---

## Skill: Check Upstream Before Overriding

Before placing a file in `src_override/`, always read the upstream version first:

```bash
# Step 1 — find the upstream file
cat apps/crm/frontend/src/components/Layouts/AppSidebar.vue

# Step 2 — copy it to src_override/ at the same relative path
cp apps/crm/frontend/src/components/Layouts/AppSidebar.vue \
   apps/novizna_crm/frontend/src_override/components/Layouts/AppSidebar.vue

# Step 3 — make your minimal surgical changes (mark with // ── CUSTOM ADDITION ──)

# Step 4 — verify the override is valid
cd apps/novizna_crm/frontend && yarn check-conflicts
```

This prevents overriding a file that upstream has renamed/moved.

---

## Recipe: Adding a New DocType

1. Create the directory: `novizna_crm/novizna_crm/doctype/<doctype_name>/`
2. Create `__init__.py` (empty)
3. Create `<doctype_name>.py` (controller class)
4. Create `<doctype_name>.json` (DocType definition)
   - For child tables: `"istable": 1`
   - Include `"module": "Novizna Crm"`
   - Include `"permissions"` array
5. Migrate:
   ```bash
   bench --site novizna-v16 migrate
   bench clear-cache
   ```

---

## Recipe: Adding a Custom Field to an Existing DocType

1. Edit the JSON in `novizna_crm/novizna_crm/custom/<doctype_snake>.json`
2. Add the field object to the `"custom_fields"` array
3. Must include `"sync_on_migrate": 1` at the top level
4. Migrate:
   ```bash
   bench --site novizna-v16 migrate
   bench clear-cache
   ```

Example field object:
```json
{
  "dt": "CRM Lead",
  "fieldname": "my_new_field",
  "fieldtype": "Data",
  "label": "My New Field",
  "insert_after": "email",
  "name": "CRM Lead-my_new_field",
  "owner": "Administrator"
}
```

---

## Verification Commands

After every change, verify your work with these commands:

```bash
# ── After any frontend change ──────────────────────────────────────────────
cd apps/novizna_crm/frontend
yarn check-conflicts          # verify no broken overrides
yarn dev                      # start dev server and check browser

# ── After any Python / DocType / custom field change ───────────────────────
source env/bin/activate
bench --site novizna-v16 migrate
bench clear-cache

# ── Test a Python API function interactively ───────────────────────────────
bench --site novizna-v16 console
# Then inside the REPL:
# import novizna_crm.api.import_leads as m
# print(m.preview_import('/files/test.csv'))

# ── Reload a single DocType in the REPL (faster than full migrate) ─────────
# frappe.reload_doc('novizna_crm', 'doctype', 'crm_lead_industry')
```

---

## Git Commit Convention

Use Conventional Commits format:

```
<type>(<scope>): <description>

[optional body]
```

| Type | When to use |
|---|---|
| `feat` | new feature |
| `fix` | bug fix |
| `refactor` | code change that is neither feature nor bug fix |
| `chore` | build scripts, config, deps |
| `docs` | documentation only |
| `style` | formatting, no logic change |
| `test` | adding tests |

Scopes for this project: `sidebar`, `import`, `leads`, `deals`, `erpnext-sync`, `doctype`, `build`, `hooks`

Examples:
```
feat(sidebar): add Reports link to custom sidebar items
fix(import): handle empty rows in CSV preview
chore(build): merge xlsx dep into crm_build package.json
refactor(leads): extract process_industries into composable
```

---

## After Any Backend Change

```bash
bench --site novizna-v16 migrate
bench clear-cache
```

After adding/modifying custom fields in JSON files, migrate is mandatory.
