---
id: pytest-patterns
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Testing pure-Python code that does not require the Frappe app/DB context — typically connector classes and helper modules"
scope: [agent:architect, agent:backend-specialist, agent:integrations-specialist, agent:qa-test-engineer]
foundational: true
domain: testing
security_score: 100
supersedes: []
---

# Pytest Patterns

When to reach for pytest instead of `FrappeTestCase`, and how to mock the Frappe boundary cleanly. Used heavily for vendor connectors (Zoho, HubSpot, LinkedIn, Google) where the test should not require a live DB.

## When to Load
- Testing a vendor connector class
- Testing a pure-Python helper (no `frappe.get_doc`, no DB)
- Testing an OAuth refresh flow with a mocked HTTP layer
- Coverage measurement on modules that don't need the bench

## Key Concepts

1. **`pytest` vs `FrappeTestCase`** — pytest for code that has no Frappe context dependency; FrappeTestCase for code that does. The cost of bringing up a Frappe test DB for a simple unit is high.
2. **`monkeypatch` fixture** — substitute attributes (e.g., `frappe.get_single`) without leaking across tests.
3. **`requests_mock`** — block real HTTP and return canned responses. Mandatory for vendor calls; CI must never hit a vendor.
4. **`pytest-cov`** — coverage measurement with `--cov=<package> --cov-fail-under=80`.
5. **Fixtures** — `@pytest.fixture` constructs reusable test inputs; scope (`function`, `module`, `session`) controls reuse.
6. **`parametrize`** — table-driven tests for boundary cases.

## Patterns

### Pattern: Connector unit test with mocked Frappe + HTTP

**When:** Testing `ZohoConnector.fetch_leads`.

**Do:**
```python
# apps/novizna_crm/novizna_crm/api/connectors/test_zoho.py
from unittest.mock import MagicMock
from datetime import datetime, timedelta
import pytest

from novizna_crm.api.connectors.zoho import ZohoConnector

@pytest.fixture
def connector(monkeypatch):
    """Build a ZohoConnector with a fully-mocked Frappe boundary."""
    settings_mock = MagicMock(
        client_id="cid",
        expires_at=(datetime.utcnow() + timedelta(hours=1)).isoformat(),
    )
    monkeypatch.setattr("frappe.get_single", lambda _: settings_mock)
    monkeypatch.setattr(
        "frappe.utils.password.get_decrypted_password",
        lambda dt, n, f: {"refresh_token": "rt", "client_secret": "cs",
                          "access_token": "at"}[f],
    )
    return ZohoConnector()

def test_get_returns_parsed_json(connector, requests_mock):
    requests_mock.get(
        "https://www.zohoapis.com/crm/v2/leads",
        json={"data": [{"id": "1"}, {"id": "2"}]},
    )
    result = connector.get("leads")
    assert len(result["data"]) == 2

def test_get_refreshes_when_expired(connector, requests_mock, monkeypatch):
    # Force expiry
    connector.settings.expires_at = (datetime.utcnow() - timedelta(seconds=10)).isoformat()
    requests_mock.post(
        "https://accounts.zoho.com/oauth/v2/token",
        json={"access_token": "new", "expires_in": 3600},
    )
    requests_mock.get("https://www.zohoapis.com/crm/v2/leads", json={"data": []})

    set_value = MagicMock()
    monkeypatch.setattr("frappe.db.set_value", set_value)
    connector.get("leads")

    # Refresh was called
    assert requests_mock.call_count == 2
    set_value.assert_called()  # tokens saved
```

`requests_mock` is the pytest fixture from the `requests-mock` package; it intercepts every `requests.*` call inside the test.

### Pattern: Parametrized boundary test

**When:** Validating a CSV parser's edge cases.

**Do:**
```python
import pytest
from novizna_crm.api.universal_import import parse_csv_row

@pytest.mark.parametrize("row, expected", [
    ({"email": "foo@bar.com"},       True),
    ({"email": ""},                  False),  # empty
    ({"email": "not-an-email"},      False),  # malformed
    ({"email": "x" * 121 + "@y.z"}, False),   # too long
])
def test_email_validation(row, expected):
    assert parse_csv_row(row).is_valid == expected
```

### Pattern: Coverage measurement

**Do:**
```bash
cd apps/novizna_crm
pytest --cov=novizna_crm.api.connectors --cov-report=term-missing --cov-fail-under=80
```

CI integration:
```yaml
# .github/workflows/test.yml (if/when CI is added)
- run: pytest --cov=novizna_crm --cov-fail-under=80
```

### Pattern: monkeypatch a Frappe module function

**When:** The code under test calls `frappe.db.get_value` once and doesn't otherwise need Frappe.

**Do:**
```python
def test_helper_uses_db_get_value(monkeypatch):
    monkeypatch.setattr("frappe.db.get_value",
                       lambda *a, **kw: "DEAL-EXAMPLE")
    from novizna_crm.api.helpers import resolve_default_deal
    assert resolve_default_deal() == "DEAL-EXAMPLE"
```

`monkeypatch` reverts on test exit — no cross-test bleed.

### Pattern: Skipping a test under partial bench

**Do:**
```python
import pytest

frappe = pytest.importorskip("frappe")
pytest.importorskip("requests_mock")
```

Skips the test cleanly if `frappe` isn't on the path (e.g., running pytest from outside the bench's venv).

## When to use FrappeTestCase instead

| Situation | Use |
|-----------|-----|
| Code calls `frappe.get_doc` against real DocTypes | FrappeTestCase |
| Code uses `frappe.session.user` for permission checks | FrappeTestCase |
| Code triggers `doc_events` chain | FrappeTestCase |
| Code is a pure helper or connector | pytest |
| Coverage target is just the connector module | pytest |

See [`testing/frappe-unittest`](./frappe-unittest.md) for the FrappeTestCase path.

## Common Pitfalls
- Forgetting `requests_mock` fixture in the signature — the real vendor gets called.
- `monkeypatch.setattr("frappe.X", ...)` after the SUT has already imported the original — Python caches the import; patch via the SUT's module if it does `from frappe import X`.
- Real `time.sleep` in retry tests — slow CI. Patch `time.sleep` to a no-op for retry tests.
- Coverage with `--cov=apps/novizna_crm` (filesystem path) instead of `--cov=novizna_crm` (package) — different result.
- Fixtures with `scope="session"` that mutate state — leaks across tests.
- Hitting a real vendor in CI "to verify the contract" — that's an integration test, run on a schedule, not per commit.

## References
- [`testing/frappe-unittest`](./frappe-unittest.md) — for DocType / DB tests
- [`integrations/oauth-patterns`](../integrations/oauth-patterns.md) — the SUT shape for connector tests
- [`integrations/queueing-retry-backoff`](../integrations/queueing-retry-backoff.md) — retry behavior to assert
