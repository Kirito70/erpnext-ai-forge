---
id: workflow-authoring
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-24
trigger: "Designing a Workflow on a DocType (states + transitions + role-based approvals)"
scope: [agent:architect, agent:backend-specialist]
foundational: false
domain: reporting
security_score: 100
supersedes: []
---

# Workflow Authoring

How to design a Frappe Workflow (states + transitions + role-based actions) and avoid the common pitfalls — self-approval, notification storms, lost state on amendment.

## When to Load
- Adding an approval flow on a custom DocType (e.g., `noviznaerp_payroll` loan approval)
- Wiring notifications to state transitions
- Reviewing a workflow JSON for self-approval bypass

## Key Concepts

1. **Workflow** — DocType that ties a state machine to a target DocType.
2. **Workflow State** — DocType for the named states (Draft, Pending Approval, Approved, Rejected, etc.).
3. **Workflow Action Master** — DocType for the action names users see on the form (Submit for Approval, Approve, Reject, etc.).
4. **Transition** — (from_state, action, next_state, allowed_role, condition?).
5. **Self-approval guard** — by default a user can approve their own submission. Block with `condition`.
6. **Notification** — Notification doc bound to a doc event AND a workflow state.
7. **State persisted in `workflow_state` field** — auto-injected on the DocType when the workflow is installed.
8. **Amendment + cancellation** — workflows interact with `docstatus`. Submitting from the final state sets `docstatus=1`; cancellation handling needs an explicit Cancelled state.

## Patterns

### Pattern: Loan Approval Workflow

**When:** Adding approval to `noviznaerp_payroll`'s Loan DocType.

**Do:**
```json
{
  "doctype": "Workflow",
  "workflow_name": "Loan Approval",
  "document_type": "Loan",
  "is_active": 1,
  "send_email_alert": 1,
  "workflow_state_field": "workflow_state",
  "states": [
    { "state": "Draft",            "doc_status": "0", "allow_edit": "Employee" },
    { "state": "Pending Approval", "doc_status": "0", "allow_edit": "HR Manager" },
    { "state": "Approved",         "doc_status": "1", "allow_edit": "HR Manager" },
    { "state": "Rejected",         "doc_status": "0", "allow_edit": "HR Manager" }
  ],
  "transitions": [
    { "state": "Draft",            "action": "Submit for Approval",
      "next_state": "Pending Approval", "allowed": "Employee",
      "condition": "doc.loan_amount > 0" },

    { "state": "Pending Approval", "action": "Approve",
      "next_state": "Approved", "allowed": "HR Manager",
      "condition": "doc.owner != frappe.session.user" },

    { "state": "Pending Approval", "action": "Reject",
      "next_state": "Rejected", "allowed": "HR Manager",
      "condition": "doc.owner != frappe.session.user" }
  ]
}
```

The `doc.owner != frappe.session.user` condition on the Approve/Reject transitions blocks **self-approval** — the most common workflow vulnerability.

**Don't:** Omit the self-approval guard. An Employee with the HR Manager role (common during demos / debugging) would be able to approve their own loan.

### Pattern: Notifications tied to a workflow state

**When:** Email HR Manager when a Loan enters Pending Approval.

**Do (create a Notification doc):**
```json
{
  "doctype": "Notification",
  "subject": "Loan {{ doc.name }} needs your approval",
  "document_type": "Loan",
  "event": "Value Change",
  "value_changed": "workflow_state",
  "condition": "doc.workflow_state == 'Pending Approval'",
  "recipients": [{ "receiver_by_role": "HR Manager" }],
  "channel": "Email"
}
```

`Value Change` event on `workflow_state` fires exactly once per transition.

### Pattern: Document scopes that restrict who sees what state

**When:** Only the HR Manager team should see Pending Approval rows.

**Do:** Combine the workflow with role-based DocType perms and `if_owner` on the Employee role:
```json
"permissions": [
  { "role": "Employee", "read": 1, "write": 1, "create": 1, "if_owner": 1 },
  { "role": "HR Manager", "read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1 }
]
```

Then list views naturally filter so each persona sees only what they should.

### Pattern: Cancellation state

**When:** An Approved loan needs to be cancelled (docstatus 1 → 2).

**Do:** Add a Cancelled state and a transition:
```json
{ "state": "Cancelled", "doc_status": "2", "allow_edit": "HR Manager" }

// in transitions:
{ "state": "Approved", "action": "Cancel",
  "next_state": "Cancelled", "allowed": "HR Manager" }
```

`doc_status: "2"` matches Frappe's docstatus = 2 (Cancelled).

### Pattern: Controller hook on transition

**When:** Need side effect (e.g., create Loan Disbursement) when state becomes Approved.

**Do:** Use the DocType controller's `on_update_after_submit` or a `doc_events` handler that checks `self.has_value_changed("workflow_state") and self.workflow_state == "Approved"`. Don't bury business logic inside the workflow JSON.

## Common Pitfalls
- Missing self-approval guard — anyone with both roles can approve their own submission.
- Transition condition references `frappe.session.user` but workflow runs in a background context (rare) — condition silently fails.
- State name typo (e.g., `Approve` vs `Approved`) between the workflow JSON and the Notification condition — notification never fires.
- Forgetting `doc_status` on the final state — workflow completes but doc never submits.
- Two workflows attempting to bind to the same DocType — only the most recently activated runs.
- Renaming a Workflow State after rows have been created in that state — orphans the existing rows.

## References
- [`frappe-core/doctype-authoring`](../frappe-core/doctype-authoring.md) — the target DocType's perms
- [`frappe-core/permissions-model`](../frappe-core/permissions-model.md) — role + User Permissions interaction
- [`erpnext-domains/hr-payroll`](../erpnext-domains/hr-payroll.md) — for HR-specific approval patterns
