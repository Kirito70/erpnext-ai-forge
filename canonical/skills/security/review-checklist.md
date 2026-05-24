---
id: review-checklist
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Every backend, integrations, or devops review; loaded for all security-reviewer invocations"
scope: [agent:architect, agent:backend-specialist, agent:security-reviewer]
foundational: true
domain: security
security_score: 100
supersedes: []
---

# Security Review Checklist

The walkthrough Security Reviewer applies to every artifact, cross-referenced to deduction IDs in [`security-scoring.yaml`](../../policies/security-scoring.yaml) and standing anti-pattern findings in [`anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json).

## When to Load
- Every Security Reviewer invocation (mandatory; foundational)
- Backend Specialist self-review before handoff
- `/review-security` command
- Auditing an existing module against current standards

## Checklist (walk in order)

### 1. Upstream-edit guard (CRITICAL — veto, -50, D-EDIT-UPSTREAM)
Any write under `apps/{frappe,erpnext,crm,hrms,lending,lms,education,helpdesk,gameplan,drive,press}/` → REJECT.

**Action:** redirect to a custom app, Custom Field, Property Setter, or fixture.

### 2. site_config.json read (CRITICAL — veto, -50, D-READ-SITE-CONFIG)
Reading or echoing contents of `sites/<site>/site_config.json` or `sites/common_site_config.json` → REJECT.

Per [`site-config-keys.json`](../../../discovery/data/site-config-keys.json), this bench's site config contains `db_*`, `encryption_key`, `user_type_doctype_limit` (8 keys). Key names may be surfaced; values must never enter model context. See [`security/secrets-handling`](./secrets-handling.md).

### 3. SQL injection — f-string SQL (HIGH, -30, D-SQL-FSTRING)
`frappe.db.sql(f"...{var}...")` or `.format()` interpolation → HIGH.

**Standing finding:** [AP-001](../../../discovery/data/anti-pattern-findings.json) — 11 known occurrences in `noviznaerp_payroll`. Link any new occurrence to AP-001 lineage.

**Fix:** parameterize with `values=` per [`data/sql-best-practices`](../data/sql-best-practices.md).

### 4. Guest endpoints (HIGH, -25, D-GUEST-WHITELIST-NO-PERM)
`@frappe.whitelist(allow_guest=True)` without signature verification AND/OR rate-limit → HIGH.

**Standing finding:** [AP-002](../../../discovery/data/anti-pattern-findings.json) — 10 known occurrences (EasyPost webhook, careers/job pages, novizna_pos api:82).

**Fix:**
- Webhooks → HMAC signature verification per [`integrations/webhooks`](../integrations/webhooks.md)
- Public pages → `frappe.rate_limit()` + bounded input validation
- "I'm not sure it needs to be guest" → recheck; switch to logged-in

### 5. ignore_permissions=True without justification (HIGH, -20, D-IGNORE-PERMISSIONS)
**Standing finding:** [AP-003](../../../discovery/data/anti-pattern-findings.json) — 99 known. New occurrences require a 1-line justifying comment within 3 lines of the call.

**Acceptable:**
```python
doc.insert(ignore_permissions=True)  # background processor; webhook arrives without user context
```

**Not acceptable:**
```python
doc.insert(ignore_permissions=True)
```

### 6. CSRF posture (MEDIUM)
**Standing finding:** [AP-005](../../../discovery/data/anti-pattern-findings.json) — `ignore_csrf=true` set site-wide in `common_site_config.json`. Likely for Quasar POS (Decision 17). Any new code that *depends* on CSRF being off (rather than tolerating it) is a blocker.

POS clients still send `X-Frappe-CSRF-Token` per [`frontend/vue3-quasar-patterns`](../frontend/vue3-quasar-patterns.md).

### 7. frappe.db.commit() inside doc_events (MEDIUM)
**Standing finding:** [AP-004](../../../discovery/data/anti-pattern-findings.json) — 73 known. Inside doc_events handlers: blocker. Inside scheduled tasks: usually fine; flag if uncertain.

### 8. XSS in Jinja Print Formats / web templates (MEDIUM)
`{{ user_field | safe }}` on user-controlled fields → MEDIUM. Sanitize with `frappe.utils.sanitize_html` or rely on default escaping.

See [`reporting/print-format-authoring`](../reporting/print-format-authoring.md).

### 9. File upload validation (MEDIUM)
Endpoints that accept uploads must validate:
- Mime type via Frappe's `is_image` / explicit allowlist
- Size cap
- Filename sanitization (`frappe.utils.scrub`)
- Storage path scoped per-doctype, not user-controlled

### 10. Mass-assignment via update() (MEDIUM)
```python
doc.update(frappe.local.form_dict)  # caller controls every field, including docstatus
```
**Fix:** explicit field list:
```python
ALLOWED = {"first_name", "last_name", "email"}
for k in ALLOWED & set(frappe.local.form_dict.keys()):
    setattr(doc, k, frappe.local.form_dict[k])
```

### 11. Hardcoded site / app / user names (LOW)
`bench --site novizna-v16 ...` in a snippet that ships to other environments → LOW. Use a placeholder.

### 12. Network call in HTTP request path (MEDIUM)
A vendor API call inline in `@frappe.whitelist()` → MEDIUM. Enqueue per [`integrations/queueing-retry-backoff`](../integrations/queueing-retry-backoff.md).

### 13. Bench-restart recommendation without confirmation (HIGH, -25, D-BENCH-RESTART-NO-CONFIRM)
Any "run `bench restart`" without the typed `novizna-v16` confirmation gate → HIGH. Only DevOps may invoke; see [`tools/bench-restart`](../../tools/bench-restart.yaml).

### 14. Git push without remote confirmation (HIGH, -20, D-PUSH-NO-REMOTE)
Pushing without echoing remote URL → HIGH. The developer pushes; agents never push.

### 15. curl-to-shell (CRITICAL — veto, -50, D-CURL-SHELL)
`curl ... | sh`, `wget ... | bash` → REJECT.

### 16. Type annotations + docstrings (LOW)
Missing type annotations or PEP 257 docstrings per CLAUDE.md → LOW. One deduction per file, not per function.

### 17. Hardcoded secrets (CRITICAL — pre-commit gate)
Anything resembling an API key, password, token, JWT, or PEM block in a non-test file. Coordinate with `gitleaks` pre-commit per [`security/secrets-handling`](./secrets-handling.md).

### 18. Inconsistent DocType naming (LOW)
Per [AP-006](../../../discovery/data/anti-pattern-findings.json), naming drift across apps. Producer should surface; reviewer flags as LOW informational.

## Scoring Workflow

1. Walk every item; assign severity per [`security-scoring.yaml`](../../policies/security-scoring.yaml)
2. Sum deductions; subtract from 100
3. **CRITICAL** → REJECT regardless of total
4. **Final < 80** → REJECT (blocks sync)
5. **Final 80–94** → REQUEST_CHANGES (justification logged per `security-scoring.yaml`)
6. **Final ≥ 95** → APPROVE

## Output

Emit the structured review block from [`security-reviewer.md`](../../agents/security-reviewer.md). Always include AP-id linkage when flagging a recurrence of a standing finding.

## References
- [`policies/security-scoring`](../../policies/security-scoring.yaml) — deduction table
- [`policies/review-protocol`](../../policies/review-protocol.md) — output format
- [`policies/escalation-rules`](../../policies/escalation-rules.md) — when CRITICAL keeps recurring
- [`security/secrets-handling`](./secrets-handling.md) — for items 2, 17
- [`data/sql-best-practices`](../data/sql-best-practices.md) — for item 3
- [`integrations/webhooks`](../integrations/webhooks.md) — for item 4 (webhook variant)
- [`discovery/data/anti-pattern-findings.json`](../../../discovery/data/anti-pattern-findings.json) — AP-001 through AP-006
