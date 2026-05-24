---
id: vue3-quasar-patterns
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Any change under apps/novizna_pos/novizna-pos-ui/ — Quasar PWA work for the POS"
scope: [agent:architect, agent:frontend-quasar-specialist, agent:qa-test-engineer]
foundational: true
domain: frontend
security_score: 100
supersedes: []
---

# Vue 3 + Quasar Patterns (novizna_pos)

Patterns specific to the `novizna_pos` Quasar PWA workspace — TypeScript strict, Pinia stores, offline queue, PWA service worker, and the **CSRF token + session cookie** auth model (Decision 17).

## When to Load
- Adding a page, composable, or store under `apps/novizna_pos/novizna-pos-ui/`
- Wiring an API call from the POS
- Touching the PWA service worker config
- Building a restaurant component or composable

## Key Concepts

1. **Quasar workspace** — `apps/novizna_pos/novizna-pos-ui/`, builds via `quasar build -m pwa` into `apps/novizna_pos/novizna_pos/public/pos/`.
2. **Auth model (Decision 17)** — Frappe session cookie (HttpOnly) + `X-Frappe-CSRF-Token` header on non-GET. **No JWT.**
3. **Pinia stores** — single source of truth for shared state; under `src/stores/`.
4. **Composables** — under `src/composables/`; wrap stores for ergonomic component reuse.
5. **Boot files** — under `src/boot/`; initialize Axios, i18n, etc. Centralize headers/interceptors here.
6. **TypeScript strict** — no `any` without a typed adapter and `// FIXME: typing` comment.
7. **Offline queue** — failed writes enqueue into a Pinia store and retry on `online` event with exponential backoff.
8. **PWA workbox** — new asset classes (e.g., PDF print formats) must be allowlisted in `quasar.config.ts:pwa.workboxOptions`.
9. **Restaurant scope** — restaurant components live under `src/components/restaurant/`; the `lint:restaurant` script enforces it.

## Patterns

### Pattern: Centralized Axios boot file with CSRF token

**When:** Every API call from the POS shell.

**Do:**
```typescript
// apps/novizna_pos/novizna-pos-ui/src/boot/axios.ts
import { boot } from 'quasar/wrappers'
import axios, { AxiosInstance } from 'axios'

const api: AxiosInstance = axios.create({
  baseURL: '/',
  withCredentials: true,  // sends the Frappe session cookie
})

declare global { interface Window { frappe?: { csrf_token?: string } } }

api.interceptors.request.use((config) => {
  const method = (config.method || 'get').toLowerCase()
  if (method !== 'get' && window.frappe?.csrf_token) {
    config.headers = config.headers || {}
    config.headers['X-Frappe-CSRF-Token'] = window.frappe.csrf_token
  }
  return config
})

export default boot(({ app }) => {
  app.config.globalProperties.$api = api
})

export { api }
```

The CSRF token is hydrated at app boot from the bootstrap response (or a meta tag injected by `boot_session`). Per [AP-005](../../../discovery/data/anti-pattern-findings.json), site-wide `ignore_csrf=true` is **not** a license to skip this — keep the header on every POS write.

**Don't:** Inline `axios.post(...)` calls in components — no centralized header injection, easy to forget the CSRF token.

### Pattern: Composable wrapping a Pinia store

**When:** Components consume the POS profile.

**Do:**
```typescript
// apps/novizna_pos/novizna-pos-ui/src/stores/pos-profile.ts
import { defineStore } from 'pinia'
import { api } from 'boot/axios'

export interface PosProfile { name: string; warehouse: string; currency: string }

export const usePosProfileStore = defineStore('pos-profile', {
  state: (): { profile: PosProfile | null; loading: boolean } => ({ profile: null, loading: false }),
  actions: {
    async load(name: string): Promise<void> {
      this.loading = true
      try {
        const { data } = await api.get('/api/method/novizna_pos.api.get_pos_profile', {
          params: { name },
        })
        this.profile = data.message
      } finally { this.loading = false }
    },
  },
})
```

```typescript
// apps/novizna_pos/novizna-pos-ui/src/composables/usePosProfile.ts
import { storeToRefs } from 'pinia'
import { usePosProfileStore } from 'stores/pos-profile'

export function usePosProfile() {
  const store = usePosProfileStore()
  const { profile, loading } = storeToRefs(store)
  return { profile, loading, load: store.load }
}
```

### Pattern: Offline write queue

**When:** Network is flaky; invoice saves must not be lost.

**Do:**
```typescript
// src/stores/offline-queue.ts
import { defineStore } from 'pinia'
import { api } from 'boot/axios'

interface QueuedWrite { id: string; method: string; payload: unknown; attempts: number }

export const useOfflineQueue = defineStore('offline-queue', {
  state: (): { queue: QueuedWrite[] } => ({ queue: [] }),
  actions: {
    enqueue(method: string, payload: unknown): void {
      this.queue.push({ id: crypto.randomUUID(), method, payload, attempts: 0 })
    },
    async flush(): Promise<void> {
      const delays = [2000, 4000, 8000, 16000, 32000]  // exponential backoff
      while (this.queue.length) {
        const item = this.queue[0]
        try {
          await api.post(`/api/method/${item.method}`, item.payload)
          this.queue.shift()
        } catch {
          item.attempts += 1
          if (item.attempts >= 5) {
            this.queue.shift()  // dead-letter (log to Sentry / sync log)
            continue
          }
          await new Promise((r) => setTimeout(r, delays[item.attempts - 1]))
        }
      }
    },
  },
})

window.addEventListener('online', () => { useOfflineQueue().flush() })
```

### Pattern: Quasar Notify / Dialog / Loading

**Do:**
```typescript
import { Notify, Dialog, Loading } from 'quasar'

Notify.create({ type: 'positive', message: 'Invoice saved' })

Dialog.create({
  title: 'Cancel invoice?',
  message: 'This cannot be undone.',
  ok: 'Cancel invoice', cancel: 'Keep',
}).onOk(() => { /* ... */ })

Loading.show()
try { await save() } finally { Loading.hide() }
```

These plugins must be enabled in `quasar.config.ts:framework.plugins`.

### Pattern: New page + route

**Do:**
```typescript
// src/router/routes.ts
const routes = [
  { path: '/', component: () => import('layouts/MainLayout.vue'),
    children: [
      { path: '', component: () => import('pages/IndexPage.vue') },
      { path: 'cash-variance',
        component: () => import('pages/CashVariancePage.vue') },
    ]
  },
]
```

Restaurant pages go under `src/pages/restaurant/`; their components under `src/components/restaurant/`.

### Pattern: Service worker allowlist

**When:** Caching PDF print formats for offline receipt printing.

**Do:**
```typescript
// quasar.config.ts (excerpt)
pwa: {
  workboxOptions: {
    runtimeCaching: [
      {
        urlPattern: /\/api\/method\/.*print.*\.pdf$/,
        handler: 'CacheFirst',
        options: { cacheName: 'pos-print-pdfs', expiration: { maxEntries: 50 } },
      },
    ],
  },
}
```

## Common Pitfalls
- Reading `document.cookie` to extract the session — it's `HttpOnly`; JS cannot see it. Use `withCredentials: true`.
- Hard-coding `X-Frappe-CSRF-Token` from a public endpoint — defeats CSRF protection.
- `any` typing to silence TS errors — the project enforces strict mode; QA flags as LOW.
- Putting shared state in a composable's module scope — composables should wrap stores, not be the store.
- Restaurant components placed outside `src/components/restaurant/` — `lint:restaurant` will fail CI.
- Forgetting to add `Notify`/`Dialog`/`Loading` to `framework.plugins` in `quasar.config.ts` — runtime "plugin not registered" error.
- Reading or writing to `localStorage` for credentials — never, even temporarily.

## References
- [`erpnext-domains/pos`](../erpnext-domains/pos.md) — POS domain model + invoice / closing entry flows
- [`integrations/queueing-retry-backoff`](../integrations/queueing-retry-backoff.md) — for the offline-queue retry semantics
- [`security/review-checklist`](../security/review-checklist.md) — CSRF + offline cache leak checks
- [`discovery/data/anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json) — AP-005 (`ignore_csrf=true`)
- Quasar docs: https://quasar.dev/
