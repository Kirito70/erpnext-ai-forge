---
id: e2e-playwright
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Authoring an E2E test for a critical user flow — POS invoice submission, CRM lead creation, restaurant order"
scope: [agent:architect, agent:qa-test-engineer, agent:frontend-quasar-specialist, agent:frontend-frappe-ui-specialist]
foundational: true
domain: testing
security_score: 100
supersedes: []
---

# E2E Tests with Playwright

When and how to write Playwright E2E tests on this bench. E2E is **expensive**: reserve it for critical user flows where regression risk is highest. Most coverage stays at the unit + integration level.

## When to Load
- A POS critical flow needs regression protection (save invoice, close POS, cash variance)
- A CRM lead-creation flow has multiple Vue components and routing involved
- A restaurant order-to-KDS flow needs end-to-end coverage
- An auth flow change (e.g., Decision 17 CSRF rotation)

## Key Concepts

1. **E2E budget** — at most ~10 tests per app, covering the 1–2 highest-business-risk flows. Not "test everything in the UI".
2. **Frappe session in Playwright** — log in once per test via the `/api/method/login` POST, then store the session cookie.
3. **`data-test` attributes** — every E2E-targeted element gets `data-test="some-stable-id"`. Don't query by text (i18n breaks tests).
4. **Page Object Model** — wrap each page in a class with semantic methods (`pos.addCustomer(...)`, `pos.submitInvoice()`).
5. **CSRF context** — POS auth model (Decision 17) means tests must send `X-Frappe-CSRF-Token` on writes; the token is hydrated at app boot.
6. **Fixtures via API** — seed data through Frappe whitelist methods or `bench --site novizna-v16 execute`, not by clicking through the UI.
7. **Cleanup** — fixtures created in a test should be deleted in afterEach; rollback isn't automatic outside FrappeTestCase.

## Suggested Structure

```
apps/novizna_pos/novizna-pos-ui/tests/e2e/
    playwright.config.ts
    fixtures/
        auth.ts                  # login helper
        seed-customer.ts         # API-based seed
    pages/
        pos.page.ts              # Page Object
    specs/
        pos-save-and-submit.spec.ts
        pos-cash-variance.spec.ts
```

## Patterns

### Pattern: Playwright config for Frappe session

**Do:**
```typescript
// playwright.config.ts
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './specs',
  timeout: 30_000,
  use: {
    baseURL: process.env.FRAPPE_BASE_URL ?? 'http://novizna-v16.localhost:8000',
    storageState: 'fixtures/.auth.json',  // populated by global setup
    trace: 'retain-on-failure',
  },
  globalSetup: './fixtures/global-setup.ts',
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
})
```

### Pattern: Global setup — login once, reuse session

**Do:**
```typescript
// fixtures/global-setup.ts
import { request } from '@playwright/test'

export default async function globalSetup() {
  const ctx = await request.newContext({ baseURL: process.env.FRAPPE_BASE_URL })
  await ctx.post('/api/method/login', {
    form: {
      usr: process.env.TEST_USER ?? 'Administrator',
      pwd: process.env.TEST_PASSWORD ?? '',
    },
  })
  await ctx.storageState({ path: 'fixtures/.auth.json' })
}
```

`TEST_PASSWORD` reads from env, never hardcoded. CI sets it via secret.

### Pattern: POS save-and-submit invoice E2E

**When:** The single most critical flow in `novizna_pos`.

**Do:**
```typescript
// specs/pos-save-and-submit.spec.ts
import { test, expect } from '@playwright/test'

test.describe('POS save and submit invoice', () => {
  test('completes the standard happy path', async ({ page }) => {
    await page.goto('/pos')

    await page.click('[data-test="customer-search"]')
    await page.fill('[data-test="customer-search-input"]', 'Test Customer')
    await page.click('[data-test="customer-result-0"]')

    await page.click('[data-test="product-add-1"]')
    await expect(page.locator('[data-test="cart-line-1"]')).toBeVisible()

    await page.click('[data-test="checkout"]')
    await page.click('[data-test="payment-method-cash"]')
    await page.click('[data-test="submit-invoice"]')

    await expect(page.locator('[data-test="invoice-id"]')).toContainText(/^SI-/)
    await expect(page.locator('[data-test="invoice-status"]')).toHaveText('Submitted')
  })
})
```

### Pattern: Seed via API, not UI

**When:** A test needs a Customer that doesn't yet exist.

**Do:**
```typescript
// fixtures/seed-customer.ts
import { APIRequestContext } from '@playwright/test'

export async function seedCustomer(api: APIRequestContext, name: string): Promise<string> {
  const resp = await api.post('/api/method/frappe.client.insert', {
    data: { doc: JSON.stringify({ doctype: 'Customer', customer_name: name }) },
    headers: { 'X-Frappe-CSRF-Token': await getCsrfToken(api) },
  })
  return (await resp.json()).message.name
}
```

UI-driven seeding is slow and fragile; API-driven seeding is fast and deterministic.

### Pattern: `data-test` attribute convention

**Do (in Vue/SFC):**
```vue
<q-btn data-test="submit-invoice" @click="submit" :loading="submitting">
  Submit
</q-btn>
```

**Don't:** Query by visible text — translation switches break tests:
```typescript
await page.click('text=Submit')   // breaks when i18n switches to "Enviar"
```

### Pattern: Cleanup in afterEach

**Do:**
```typescript
test.afterEach(async ({ request }) => {
  // Delete the invoice we just created
  if (createdInvoiceId) {
    await request.post('/api/method/frappe.client.delete', {
      data: { doctype: 'POS Invoice', name: createdInvoiceId },
    })
  }
})
```

## Recommended E2E Test Inventory (this bench)

| App | Critical flow | Why |
|-----|---------------|-----|
| `novizna_pos` | Save and submit POS Invoice | Core revenue path |
| `novizna_pos` | POS Closing Entry | Cash reconciliation depends on it |
| `novizna_pos` | Cash Variance Entry | Audit trail |
| `novizna_crm` | Create Lead → Convert to Deal | Core CRM funnel |
| `novizna_crm` | Bulk Customer Import | Sets the rest of the data |
| `cargo_management` | Parcel creation + tracking lookup | Customer-facing |

That's ~6 specs total across two apps. Not 60.

## Common Pitfalls
- Querying by class name or DOM structure — every refactor breaks tests. Use `data-test`.
- Reusing the same Customer name across tests without cleanup — second test hits unique-constraint.
- Hard-coding `localhost:8000` — breaks on CI. Use `baseURL`.
- `await page.waitForTimeout(2000)` — flaky. Use `await expect(...).toBeVisible({ timeout: 5000 })` (auto-waits).
- Running E2E on every commit — too slow. Run on PRs / nightly only.
- Forgetting the CSRF token on POST seed calls — fails with 403; tests can't seed.
- Tests that depend on prior test state — each spec must be independent.

## References
- [`testing/frappe-unittest`](./frappe-unittest.md) — for backend-driven tests
- [`testing/pytest-patterns`](./pytest-patterns.md) — for connector tests
- [`frontend/vue3-quasar-patterns`](../frontend/vue3-quasar-patterns.md) — POS-side auth model
- [`erpnext-domains/pos`](../erpnext-domains/pos.md) — POS DocType context
- Playwright docs: https://playwright.dev/
