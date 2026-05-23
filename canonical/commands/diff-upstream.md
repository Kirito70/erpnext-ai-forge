---
id: diff-upstream
kind: command
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-05-23
triggers_agents: [architect, frontend-frappe-ui-specialist]
---

# /diff-upstream

Show the diff between a `src_override/` file and its upstream counterpart in `apps/crm/frontend/src/`.

## Usage

```
/diff-upstream <override-path>
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `<override-path>` | yes | Path under `apps/novizna_crm/frontend/src_override/` |

## Example

```
/diff-upstream apps/novizna_crm/frontend/src_override/components/Leads/LeadsListHeader.vue
```

## Pipeline

1. **Architect:** validate the override file exists and its upstream counterpart exists
2. **Frontend Specialist (Frappe-UI):**
   - Resolve upstream path by stripping `src_override/` prefix and prefixing with `apps/crm/frontend/src/`
   - Run `git diff --no-index <upstream> <override>` to produce the unified diff
   - Compute drift % (lines changed / total)
   - If drift > 50% → suggest extracting into a net-new component under `src/`
3. **Architect:** present diff + drift % + recommendation

## Output

```markdown
## Diff: <override-path>

**Upstream:** apps/crm/frontend/src/<same-path>
**Drift:** 23% (47 lines changed / 204 total)

<unified diff>

**Recommendation:** keep as override (drift is reasonable)
```

## Notes

- Drift > 50% suggests the override has become a near-rewrite; extraction to a net-new component is usually clearer and survives upstream renames better
- Use after CRM upstream updates to see whether the override still makes sense vs. the new upstream baseline

## Tools Touched

- [`override-checker`](../tools/override-checker.yaml) — sibling validation
