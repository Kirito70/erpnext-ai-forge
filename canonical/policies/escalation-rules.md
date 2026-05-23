---
id: escalation-rules
kind: policy
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
scope: [agent:architect]
---

# Escalation Rules

When the architect must stop automated execution and hand control to the human (the developer). The trigger conditions are deliberately conservative — auto-execution is the exception, not the default.

---

## 1. Automatic Escalation Triggers

The architect **must** escalate immediately when any of these conditions hold:

| # | Trigger | Why |
|---|---------|-----|
| 1 | Any **CRITICAL** security finding from `security-reviewer` that the producing specialist cannot auto-fix in one revision | Veto power; CRITICAL cannot ship |
| 2 | Revision loop count reaches **3** for the same artifact (see [review-protocol §3](./review-protocol.md#3-loop-cap-tightened--v02-part-b-item-2)) | Loop cap hit |
| 3 | An artifact's security score is **< 80** after deductions | Block threshold |
| 4 | A tool with `requires_confirmation: true` is about to run | Developer must type the site name (Decision 13) |
| 5 | Any write under `apps/{frappe,erpnext,crm,hrms,lending,lms,education,helpdesk,gameplan,drive,press}` is attempted | Upstream-app guard ([Section 6.1 of ARCHITECTURE.md](../../ARCHITECTURE.md#61-upstream-app-guard)) |
| 6 | Any DocType, fixture, or patch creation is queued | Schema decisions require developer approval (Non-Goal #3) |
| 7 | Any `git push` to a remote is queued | Developer must type the remote host (Non-Goal #4) |
| 8 | An agent's discovery lookup misses (referenced DocType / app / path not in `discovery/data/*.json`) | Trigger targeted re-scan first; if still missing, escalate |
| 9 | Conflicting reviewer opinions persist after 2 tiebreaks | Surface both positions verbatim |
| 10 | A `forge sync --all` run fails mid-render | Abort entire run, leave bench untouched, escalate with adapter name + error |

---

## 2. Escalation Message Format

When escalating, the architect emits:

```markdown
## ⚠ Escalation: <trigger id>
**Artifact:** <artifact id / path>
**Trigger:** <one-line cause>
**Recommended action by developer:** <one or two sentences>

### Context
<3–5 sentences of background>

### Reviewer Positions (verbatim, if applicable)
**Position A (<reviewer-id>):**
> <quoted verbatim>

**Position B (<reviewer-id>):**
> <quoted verbatim>

### What I Have Done
- <files written>
- <decisions deferred>

### What I Will Not Do Without Approval
- <list>
```

The format guarantees the developer can resume the task without losing context.

---

## 3. Non-Escalating Conditions

The architect handles these inline (no escalation):

- Score 80–94 with typed justification supplied via `--justify` flag
- LOW or MEDIUM findings that fit within remaining revision loops
- Stale-reference auto-trigger of `forge discover` (Decision 15) — runs silently
- `bench-clear-cache`, `bench-logs` tail, `git-status-all-apps` — `requires_confirmation: false`
- Read-only `mariadb-query` against the read-only grant (Decision 12)

---

## 4. Audit Trail of Escalations

Every escalation appends an entry to `audit/<YYYY>/<MM>/forge-audit.jsonl` with:

```json
{
  "ts": "...",
  "action": "escalation",
  "trigger_id": "<1-10>",
  "artifact": "<path or id>",
  "agent": "agent:architect",
  "human_responded_at": null,
  "resolution": null
}
```

When the human resolves the escalation, a follow-up entry records the resolution.
