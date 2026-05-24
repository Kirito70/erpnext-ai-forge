---
id: frappe-unittest
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Authoring or running Frappe unit tests for any custom DocType, controller, or whitelist endpoint"
scope: [agent:architect, agent:backend-specialist, agent:qa-test-engineer]
foundational: true
domain: testing
security_score: 100
supersedes: []
---

# Frappe Unit Tests (FrappeTestCase)

The standard testing harness for any code that touches Frappe ORM, DocTypes, or whitelist endpoints. Enforces the project-wide **≥80% line coverage on new code** rule.

## When to Load
- Adding a controller (`validate`, `on_submit`, etc.)
- Adding or modifying a whitelist endpoint
- Adding a patch (migration test variant)
- Reviewing a producer's test scaffold

## Key Concepts

1. **`FrappeTestCase`** — wraps each test in a transaction; rolls back on tearDown. No DB pollution across tests.
2. **`make_test_records`** — auto-loads `test_records.json` from each DocType folder. Use sparingly; explicit fixtures inside the test are clearer.
3. **`setUp` / `tearDown`** — for shared test data construction; rollback is automatic.
4. **`bench run-tests`** — the canonical runner; takes `--app`, `--module`, `--doctype`, `--coverage`.
5. **Coverage** — `bench run-tests --app <app> --coverage` runs `coverage.py` and emits a report.
6. **Permission context in tests** — `frappe.set_user("test@example.com")` switches user; `ignore_permissions=True` is acceptable for fixture setup (with the canonical justifying comment).

## File Layout

```
apps/<app>/<app>/<module>/doctype/<id>/
    <id>.json
    <id>.py
    test_<id>.py        ← tests here
    __init__.py
```

For non-DocType modules:
```
apps/<app>/<app>/api/
    deals.py
    test_deals.py
```

## Patterns

### Pattern: DocType controller test

**When:** Testing `CRM Lead Industry`'s self-parenting guard.

**Do:**
```python
# apps/novizna_crm/novizna_crm/novizna_crm/doctype/crm_lead_industry/test_crm_lead_industry.py
import frappe
from frappe.tests.utils import FrappeTestCase

class TestCRMLeadIndustry(FrappeTestCase):
    def setUp(self) -> None:
        """Create a base industry to test against."""
        self.parent = frappe.get_doc({
            "doctype": "CRM Lead Industry",
            "industry_name": "Manufacturing",
        }).insert(ignore_permissions=True)  # justified: test fixture setup

    def test_self_parent_is_rejected(self) -> None:
        """An industry cannot be its own parent."""
        self.parent.parent_industry = self.parent.name
        with self.assertRaises(frappe.ValidationError):
            self.parent.save(ignore_permissions=True)

    def test_distinct_parent_is_accepted(self) -> None:
        child = frappe.get_doc({
            "doctype": "CRM Lead Industry",
            "industry_name": "Automotive",
            "parent_industry": self.parent.name,
        }).insert(ignore_permissions=True)
        self.assertEqual(child.parent_industry, self.parent.name)
```

Run:
```bash
bench --site novizna-v16 run-tests --app novizna_crm \
  --module novizna_crm.novizna_crm.doctype.crm_lead_industry.test_crm_lead_industry
```

### Pattern: Whitelist endpoint test (auth context)

**When:** Testing `novizna_crm.api.deals.get_deal_addresses`.

**Do:**
```python
import frappe
from frappe.tests.utils import FrappeTestCase
from novizna_crm.api.deals import get_deal_addresses

class TestGetDealAddresses(FrappeTestCase):
    def setUp(self) -> None:
        self.deal = frappe.get_doc({
            "doctype": "CRM Deal", "name": "DEAL-TEST-1",
        }).insert(ignore_permissions=True)  # justified: test fixture

    def test_requires_read_permission(self) -> None:
        """Caller without read perm gets PermissionError."""
        frappe.set_user("guest@example.com")
        with self.assertRaises(frappe.PermissionError):
            get_deal_addresses(deal_name=self.deal.name)

    def test_returns_billing_and_shipping_keys(self) -> None:
        frappe.set_user("Administrator")
        result = get_deal_addresses(deal_name=self.deal.name)
        self.assertIn("billing", result)
        self.assertIn("shipping", result)

    def test_rejects_blank_deal_name(self) -> None:
        frappe.set_user("Administrator")
        with self.assertRaises(frappe.ValidationError):
            get_deal_addresses(deal_name="")
```

### Pattern: Submittable doc test (cash_variance_entry)

**Do:**
```python
class TestCashVarianceEntry(FrappeTestCase):
    def test_submit_then_amend(self) -> None:
        doc = frappe.get_doc({
            "doctype": "Cash Variance Entry",
            "branch": "Main",
            "variance_amount": 250.00,
            "reason": "Counted short",
        }).insert(ignore_permissions=True)
        doc.submit()
        self.assertEqual(doc.docstatus, 1)

        # Amend (only if allow_amend: 1 in DocType JSON)
        amended = frappe.copy_doc(doc)
        amended.amended_from = doc.name
        amended.variance_amount = 200.00
        amended.insert(ignore_permissions=True)
        amended.submit()
        self.assertEqual(amended.docstatus, 1)
```

### Pattern: Patch (migration) test

**When:** Verifying an idempotent patch.

**Do:**
```python
from frappe.tests.utils import FrappeTestCase
from noviznaerp_payroll.patches.v16_0_0.\
    backfill_eobi_policy_2026_05_24 import execute  # name matches your patch slug

class TestBackfillEOBIPolicy(FrappeTestCase):
    def setUp(self) -> None:
        # Insert a row missing the field
        self.policy = frappe.get_doc({
            "doctype": "EOBI Policy", "policy_name": "Default", "eobi_rate": None,
        }).insert(ignore_permissions=True)

    def test_patch_backfills_and_is_idempotent(self) -> None:
        execute()
        self.policy.reload()
        self.assertIsNotNone(self.policy.eobi_rate)

        # Idempotency: second run must be a no-op
        prev = self.policy.eobi_rate
        execute()
        self.policy.reload()
        self.assertEqual(self.policy.eobi_rate, prev)
```

### Pattern: Coverage measurement

**Do:**
```bash
bench --site novizna-v16 run-tests --app novizna_crm --coverage
# Outputs: coverage.xml + console summary

# CI variant — fail under 80
coverage report --fail-under=80
```

A producer that ships a new module with <80% line coverage on that file → QA returns REQUEST_CHANGES.

## Common Pitfalls
- Tests that don't roll back — DB pollution leaks into the next test. `FrappeTestCase` rolls back automatically; raw `unittest.TestCase` does not.
- `frappe.db.commit()` inside a test — defeats rollback. Don't.
- `assertRaises(Exception)` (too broad) — assert specific exception types.
- Skipping `setUp` rollback when using `make_test_records` — fixtures from one DocType folder bleed into another.
- Coverage measured on an aggregate (`all apps`) — masks per-file gaps. Run per-app.
- Tests that depend on `frappe.session.user = "Administrator"` left over from a previous test — always set explicitly.

## References
- [`testing/pytest-patterns`](./pytest-patterns.md) — for non-Frappe / connector tests
- [`testing/e2e-playwright`](./e2e-playwright.md) — for critical user flows
- [`frappe-core/conventions`](../frappe-core/conventions.md) — test file colocation
- [`tools/bench-console`](../../tools/bench-console.yaml) — for one-off REPL setup
