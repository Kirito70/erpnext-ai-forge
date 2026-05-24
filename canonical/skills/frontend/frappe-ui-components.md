---
id: frappe-ui-components
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Authoring Vue 3 SFCs inside apps/novizna_crm/frontend/ or wiring frontend code to Frappe whitelist methods"
scope: [agent:architect, agent:frontend-frappe-ui-specialist, agent:qa-test-engineer]
foundational: true
domain: frontend
security_score: 100
supersedes: []
---

# Frappe-UI Components and Composables

Vue 3 component and data-fetching patterns for the `novizna_crm` workspace. Use Frappe-UI primitives before writing custom HTML; use the `createResource` / `createListResource` data layer before raw `fetch`.

## When to Load
- Adding any new Vue SFC under `apps/novizna_crm/frontend/src/` or `src_override/`
- Wiring a frontend call to a Frappe whitelist method
- Building list / form / dialog UI
- Reviewing existing components for primitive reuse

## Key Concepts

1. **Frappe-UI primitives** — `<Button>`, `<Dialog>`, `<ListView>`, `<FormControl>`, `<Avatar>`, `<Badge>`, `<Tooltip>`. Tailwind-styled, themable.
2. **`createResource`** — single-document or single-call resource (auto reactive, auto cached). Call a Frappe whitelist method by name, not URL.
3. **`createListResource`** — paginated list bound to a DocType (uses `frappe.client.get_list` under the hood; supports filters, fields, pageLength).
4. **`call` helper** — one-shot RPC; returns a promise.
5. **Composables** — `useCall`, `useList`, `useDoc` (where available) wrap resource creation with sensible defaults.
6. **Tailwind interop** — Frappe-UI ships Tailwind preset; use utility classes inside components.
7. **Toast / Dialog** — use Frappe-UI's `toast` and `<Dialog>` (don't import a separate notification lib).

## Patterns

### Pattern: `createListResource` for a list view

**When:** Fetching `CRM Lead Industry` rows for a filter dropdown.

**Do:**
```vue
<!-- apps/novizna_crm/frontend/src/components/Leads/LeadsIndustryFilter.vue -->
<script setup>
import { createListResource } from 'frappe-ui'

const industries = createListResource({
  doctype: 'CRM Lead Industry',
  fields: ['name', 'industry_name'],
  orderBy: 'industry_name asc',
  pageLength: 100,
  auto: true,           // fetch on mount
})

const emit = defineEmits(['change'])
</script>

<template>
  <FormControl
    type="autocomplete"
    :options="industries.data || []"
    :loading="industries.loading"
    placeholder="Industry"
    @change="(v) => emit('change', v)"
  />
</template>
```

`createListResource` re-fetches automatically when `filters` are mutated reactively — no manual cache wiring.

**Don't:** `fetch('/api/method/frappe.client.get_list?...')` — bypasses the FUI layer's caching + CSRF token wiring.

### Pattern: `createResource` for a custom whitelist method

**When:** Calling `novizna_crm.api.deals.get_deal_addresses`.

**Do:**
```vue
<script setup>
import { createResource } from 'frappe-ui'

const props = defineProps({ dealId: { type: String, required: true } })

const addresses = createResource({
  url: 'novizna_crm.api.deals.get_deal_addresses',
  params: { deal_name: props.dealId },
  auto: true,
})
</script>

<template>
  <div v-if="addresses.loading">Loading…</div>
  <div v-else-if="addresses.error" class="text-red-500">
    {{ addresses.error.message }}
  </div>
  <AddressList v-else :billing="addresses.data?.billing" :shipping="addresses.data?.shipping" />
</template>
```

**Don't:** `axios.post('/api/method/novizna_crm.api.deals.get_deal_addresses', ...)` — works, but loses reactivity and Frappe's session/error envelope handling.

### Pattern: `<Button>` + `<Dialog>` pair

**When:** "Import Leads" action.

**Do:**
```vue
<script setup>
import { ref } from 'vue'
import { Button, Dialog } from 'frappe-ui'

const showImport = ref(false)
</script>

<template>
  <Button variant="solid" theme="blue" @click="showImport = true">
    Import Leads
  </Button>
  <Dialog v-model="showImport" :options="{ title: 'Import Leads', size: 'lg' }">
    <template #body>
      <LeadImportForm @done="showImport = false" />
    </template>
  </Dialog>
</template>
```

### Pattern: `call` helper for one-shot writes

**When:** "Import Customers as Leads" button click.

**Do:**
```javascript
import { call, toast } from 'frappe-ui'

async function importNow(payload) {
  try {
    const result = await call('novizna_crm.api.import_leads.import_customers_as_leads', payload)
    toast.success(`Imported ${result.imported} leads`)
  } catch (e) {
    toast.error(e.message || 'Import failed')
  }
}
```

### Pattern: `<FormControl>` for typed inputs

**Do:**
```vue
<FormControl type="text"    v-model="state.firstName" label="First Name" required />
<FormControl type="email"   v-model="state.email"     label="Email" />
<FormControl type="select"  v-model="state.status"
  :options="['New', 'Qualified', 'Lost']" label="Status" />
<FormControl type="link"    v-model="state.industry"
  :link-doctype="'CRM Lead Industry'" label="Industry" />
```

The `type="link"` variant uses `createListResource` internally for autocomplete.

### Pattern: Composables on top of resources

**When:** Several components need the same list of industries.

**Do:**
```javascript
// apps/novizna_crm/frontend/src/composables/useLeadIndustries.js
import { createListResource } from 'frappe-ui'
let _resource = null

export function useLeadIndustries() {
  if (!_resource) {
    _resource = createListResource({
      doctype: 'CRM Lead Industry', fields: ['name', 'industry_name'],
      pageLength: 100, auto: true,
    })
  }
  return _resource
}
```

Singleton resource → shared cache across all components consuming it.

## Common Pitfalls
- Wiring `auto: true` then also calling `.reload()` in `onMounted` — double-fetches.
- Mutating `resource.data` directly to "update locally" — breaks the cache. Call `.setData(...)` or `.reload()`.
- Hard-coding a URL like `/api/method/foo` — breaks when the desk path or site name changes.
- Importing Vue 2 patterns (`computed: {}` etc.) — this is Composition API + `<script setup>`.
- Tailwind classes in a `:class="`...`"` expression without `:class` reactivity wiring — silently no-ops on prop changes.
- Forgetting that Frappe-UI components ship their own styles — wrapping them in extra `<div class="border rounded ...">` often double-borders.

## References
- [`frontend/novizna-crm-override-system`](./novizna-crm-override-system.md) — where this component lives in the layer system
- [`frappe-core/whitelist-api-patterns`](../frappe-core/whitelist-api-patterns.md) — for the backend the FUI calls go to
- [`testing/frappe-unittest`](../testing/frappe-unittest.md) — for backend tests of the called whitelist methods
- Frappe-UI docs (verify with `apps/crm/frontend/package.json` for the locked version): https://frappeui.com/
