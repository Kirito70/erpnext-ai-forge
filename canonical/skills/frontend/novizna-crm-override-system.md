---
id: novizna-crm-override-system
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Any change touching apps/novizna_crm/frontend/ — overriding an upstream CRM file or adding a net-new component"
scope: [agent:architect, agent:frontend-frappe-ui-specialist, agent:qa-test-engineer]
foundational: true
domain: frontend
security_score: 100
supersedes: []
---

# novizna_crm Frontend Override System (3-Layer)

The single most important frontend rule in this bench. Per [Decision 16](../../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md#section-11--decision-log), `novizna_crm` extends upstream `apps/crm/` via three layers and **only three layers**. Any file you write must land in exactly one of them.

## When to Load
- Adding any file under `apps/novizna_crm/frontend/`
- Changing existing CRM behavior (page, component, composable)
- Reviewing a frontend PR for layer correctness
- Auditing whether `crm_build/` was accidentally edited

## Key Concepts

1. **Layer 1 — `src/`** — Net-new files that have **no upstream counterpart**.
2. **Layer 2 — `src_override/`** — Files that **shadow** an upstream file at the **identical relative path**. One-for-one strict.
3. **Layer 3 — `crm_build/`** — **GENERATED** workspace. Wiped on every `yarn dev` / `yarn build`. **READ-ONLY** to humans and AI.
4. **No fourth layer** — `novizna_crm/public/frontend/` is the compiled output. Never edit.
5. **Path mirroring** — `src_override/components/Layouts/AppSidebar.vue` shadows `apps/crm/frontend/src/components/Layouts/AppSidebar.vue` exactly.
6. **Drift threshold** — when an override diverges >50% from upstream, extract to a net-new component under `src/` and remove the override.
7. **Validation** — `yarn check-conflicts` (run after upstream `crm` updates) flags broken overrides.

## Current overrides (10 files — ground truth)

From [`override-map.json`](../../../discovery/data/override-map.json):

| Override (`src_override/...`) | Shadows (`apps/crm/frontend/src/...`) | Purpose |
|---|---|---|
| `main.js` | `main.js` | App entry override |
| `router.js` | `router.js` | Routing override (additional routes from `noviznaCrmRoutes.js`) |
| `socket.js` | `socket.js` | Realtime override |
| `index.css` | `index.css` | Global styles override |
| `components/Activities/Activities.vue` | same | Activities tab |
| `components/Layouts/AppSidebar.vue` | same | Sidebar with Novizna custom items |
| `composables/useActiveTabManager.js` | same | Tab state composable |
| `pages/DataImport.vue` | same | Data import page |
| `pages/Deal.vue` | same | Deal page |
| `pages/Lead.vue` | same | Lead page |

These 10 files are the entire override surface today. Any addition appears in this list after the next discovery refresh.

## Patterns

### Pattern: Net-new component → `src/`

**When:** Adding a feature that has no counterpart in upstream CRM (e.g., LinkedIn lead enrichment panel).

**Do:**
```
apps/novizna_crm/frontend/src/components/Leads/LinkedInEnrichmentPanel.vue
```

Then expose it through one of the extension points:

- **A page that needs it:** import directly in the relevant `src_override/pages/<Page>.vue`.
- **A new route:** register in `apps/novizna_crm/frontend/src/noviznaCrmRoutes.js`.
- **A sidebar item:** push to `customSidebarItems` in `apps/novizna_crm/frontend/src/index.js`.

**Don't:** Drop it into `src_override/components/Leads/...` if no such file exists upstream — `override-checker` will fail with "no upstream counterpart".

### Pattern: Override an existing upstream file → `src_override/`

**When:** Adjusting how the Activities tab renders.

**Do:**
```bash
# 1. Verify upstream exists at this path
ls apps/crm/frontend/src/components/Activities/Activities.vue

# 2. Copy upstream content as the starting point
cp apps/crm/frontend/src/components/Activities/Activities.vue \
   apps/novizna_crm/frontend/src_override/components/Activities/Activities.vue

# 3. Modify the copy

# 4. Verify with override-checker
yarn check-conflicts
```

**Don't:** Create `src_override/components/Activities/MyActivities.vue` — the filename must match upstream **exactly**. A renamed file is not an override; it's a net-new component (and the upstream original still ships).

### Pattern: Detect drift → extract to net-new

**When:** Your `src_override/pages/Lead.vue` has diverged so far from upstream that upstream updates are painful to merge.

**Do:**
```
apps/novizna_crm/frontend/src/pages/NoviznaLead.vue     # the new heavily-customized version
apps/novizna_crm/frontend/src/noviznaCrmRoutes.js       # route '/novizna-leads/:id' → NoviznaLead.vue
# Delete src_override/pages/Lead.vue so upstream Lead.vue ships as-is for the original route
```

The rule: when the override-vs-upstream diff exceeds ~50% of lines changed, the override has stopped being an "override" and become a fork. Extracting it makes upstream merges cheap again.

### Pattern: Sidebar items via `customSidebarItems`

**When:** Adding a "Reports" link to the CRM sidebar.

**Do (in `apps/novizna_crm/frontend/src/index.js`):**
```javascript
import { ChartBarIcon } from '@heroicons/vue/24/outline'

export const customSidebarItems = [
  { name: 'Reports', icon: ChartBarIcon, to: { name: 'NoviznaReports' } },
]
```

The override in `src_override/components/Layouts/AppSidebar.vue` reads this array and renders the items.

**Don't:** Hard-code the sidebar item inside `src_override/components/Layouts/AppSidebar.vue` — increases drift; future upstream sidebar changes become expensive to merge.

### Pattern: Routes via `noviznaCrmRoutes.js`

**Do (in `apps/novizna_crm/frontend/src/noviznaCrmRoutes.js`):**
```javascript
export default [
  { path: '/novizna-leads/:id', name: 'NoviznaLead',
    component: () => import('@/pages/NoviznaLead.vue') },
]
```

The override `src_override/router.js` merges this array with the upstream routes.

## Common Pitfalls
- Editing `crm_build/...` and watching changes vanish on next `yarn dev`. The build wipes it every time.
- Editing `novizna_crm/public/frontend/` (compiled output) — same fate.
- Adding `src_override/...` without checking the upstream path exists → silently does nothing (Vite resolves to upstream).
- Renaming a file in `src_override/` (e.g., `LeadV2.vue`) — not an override, just an orphan.
- Forgetting to run `yarn check-conflicts` after upstream pulled new commits — overrides may now shadow files that moved or no longer exist.
- Importing from `apps/novizna_pos/novizna-pos-ui/` — different workspace, different upstream. Never cross.

## References
- [`frontend/frappe-ui-components`](./frappe-ui-components.md) — for component-level patterns
- [`tools/override-checker`](../../tools/override-checker.yaml) — the validator
- [`tools/frontend-build`](../../tools/frontend-build.yaml) — for the build invocation
- [`discovery/data/override-map.json`](../../../discovery/data/override-map.json) — current override inventory
- `apps/novizna_crm/CLAUDE.md` — project-level notes on the override system
