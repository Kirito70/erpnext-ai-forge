---
id: review-protocol
kind: policy
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
scope: [agent:architect, agent:security-reviewer, agent:qa-test-engineer, agent:backend-specialist, agent:frontend-frappe-ui-specialist, agent:frontend-quasar-specialist, agent:integrations-specialist, agent:devops-deployment]
---

# Peer Review Protocol

Every code or config artifact produced by a specialist is reviewed by at least one other specialist before the architect accepts it. This document defines the review output format, acceptance criteria, loop cap, and mandatory pairings.

Spec: [v0.2 §9](../../../../erp/novizna-v16/novizna-v16/ULTRAPLAN-AI-FRAMEWORK-v0.2.md).

---

## 1. Review Output Format

Every reviewer emits Markdown in this exact shape. The architect parses these blocks to compute acceptance.

```markdown
## Review: <artifact id>
**Reviewer:** <agent-id>
**Date:** <ISO-8601 UTC>
**Decision:** APPROVE | REQUEST_CHANGES | REJECT

### Summary
<3–5 sentences. State the artifact's intent and your overall verdict.>

### Issues
| ID | Severity | Location | Description |
|----|----------|----------|-------------|
| 1  | CRITICAL | path/to/file.py:42 | <one-line description> |
| 2  | HIGH     | path/to/file.py:88 | ... |
| 3  | MEDIUM   | ...                | ... |
| 4  | LOW      | ...                | ... |

### Suggested Fixes
1. <concrete, copy-pastable suggestion>
2. ...

### Score Delta
- Before: 100
- After:  <computed>
- Net:    <Δ> (<N CRITICAL>, <N HIGH>, <N MEDIUM>, <N LOW>)
```

If there are no issues at a severity, omit the row. Keep one table for all severities.

---

## 2. Acceptance Criteria (v0.2)

The architect accepts an artifact only when **all** of the following hold:

| Criterion | Threshold |
|-----------|-----------|
| CRITICAL findings | exactly 0 |
| HIGH findings | 0 (or each carries a typed justification from the developer) |
| Final security score | ≥ 95, OR 80–94 with typed justification per [`security-scoring.yaml`](./security-scoring.yaml) |
| Mandatory reviewer pair has signed off | yes (see §4) |
| Acceptance criteria from the original TASK BRIEF | all checked |

If any fails, the artifact returns to the producing specialist for revision.

---

## 3. Loop Cap (Tightened — v0.2 Part B item 2)

| Loop | Action |
|------|--------|
| 1 | Producer addresses issues; resubmits |
| 2 | Final attempt; producer addresses issues again |
| **>2** | **Auto-escalate to human** with a synthesized summary that includes both reviewer positions **verbatim** (no paraphrasing) |

The architect never accepts on loop 3 by default. Human escalation is the next step.

---

## 4. Mandatory Reviewer Pairings

| Producer | Mandatory Reviewer | Optional |
|----------|--------------------|----|
| `backend-specialist` | `security-reviewer`, `qa-test-engineer` | — |
| `frontend-frappe-ui-specialist` | `qa-test-engineer` | `security-reviewer` (if API calls added) |
| `frontend-quasar-specialist` | `qa-test-engineer`, `security-reviewer` (offline-cache leak risk) | — |
| `integrations-specialist` | `security-reviewer`, `qa-test-engineer` | `devops-deployment` |
| `devops-deployment` | `security-reviewer` | `architect` |
| `architect` (closing documentation sub-phase) | (self-reviewed; no peer) | — |

`security-reviewer` holds **veto** on any CRITICAL finding — cannot be overridden by majority.

---

## 5. Conflict Resolution

| Situation | Action |
|-----------|--------|
| Two reviewers disagree | Architect summons a third reviewer (typically `qa-test-engineer`) to break the tie |
| Persistent disagreement after 2 tiebreaks | Human escalation; surface both positions verbatim |
| Security Reviewer flags CRITICAL | Veto — fix is mandatory, no override |

---

## 6. Documentation Sub-Phase (Architect Closing Step)

After acceptance, the architect runs a mandatory documentation update (replacing the removed Documentation Writer agent — v0.2 Part B item 1):

1. Append a `CHANGELOG.md` line in `<type>(<scope>): <description>` form
2. Update the affected per-app `CLAUDE.md` if behavior or APIs changed
3. Append an ADR to `ARCHITECTURE.md` if a non-reversible decision was made
4. Update `PROJECT-STATUS.md` "Recently Completed" list

These updates are committed in the same scoped Conventional Commits commit as the implementation.
