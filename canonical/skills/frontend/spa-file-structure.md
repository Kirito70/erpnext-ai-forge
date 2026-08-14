---
id: spa-file-structure
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-08-12
trigger: "Creating, renaming or moving ANY page, view, or component in a Vue/SPA workspace of a managed app (novizna_pos, novizna_crm, or any future frontend)"
scope: [agent:architect, agent:frontend-quasar-specialist, agent:frontend-frappe-ui-specialist, agent:code-reviewer, agent:qa-test-engineer, agent:ticket-refiner]
foundational: true
domain: frontend
security_score: 100
supersedes: []
---

# SPA File Structure — the filesystem mirrors the IA

Stack-neutral. Applies to every Vue frontend in the bench — Quasar
(`novizna_pos/novizna-pos-ui/`), Frappe-UI (`novizna_crm/frontend/`), and any
workspace added later. Framework-specific rules live in
[`vue3-quasar-patterns`](./vue3-quasar-patterns.md) and
[`frappe-ui-components`](./frappe-ui-components.md); **this file owns where files go.**

**One exception, and it is not a loophole:** in `novizna_crm`, a file under
`src_override/` must mirror its upstream path in `apps/crm/frontend/src/`
byte-for-byte — the build resolves it by path. The override system wins there.
This skill governs `src/` (net-new files), which is where the flat-directory
problem actually happens.

## When to Load

- Adding a page, view, dialog, or component to any SPA workspace
- Adding a route
- Reviewing a frontend diff (a misplaced file is a review finding, not a nit)
- Writing or refining a frontend ticket

## The Rule

> **A page's path on disk is its path in the navigation, minus the leading slash.**

A route of `/pos/manage/catalog/items` means the page file lives at
`src/pages/pos/manage/catalog/items/`. Nothing else. If you cannot say which
folder a new page belongs in, the IA has no home for it — that is a design
question for the ticket, not a reason to drop the file at the top level.

This exists because a flat directory is write-cheap and read-expensive, and
frontends are read far more than they are written. Seventy files named
`PosManage<Thing>Page.vue` in one folder is not a structure; it is a naming
convention doing a directory's job — and it fails the moment two people guess
different names for the same concept.

### The three levels

```
src/pages/<area>/<category>/<entity>/
```

| Level | Is | Example | Source of truth |
|-------|-----|---------|-----------------|
| `<area>` | A top-level surface of the app | `pos`, `manage`, `auth` | The router tree |
| `<category>` | A nav group | `catalog`, `customers`, `pricing`, `payments-tax`, `organization`, `system`, `records`, `reports` | The nav config (e.g. `src/config/manageNav.ts`) |
| `<entity>` | One doctype / one concept | `items`, `item-groups`, `uom`, `uom-conversions` | The nav entry |

**Three levels is the cap.** A fourth means the category is really two
categories — split it in the nav config first, and the folders follow.

**The category tier exists only where the nav actually has groups.** A surface
with a grouped sidebar (an admin/manage console) gets all three levels; a flat
surface (the till screens, auth) gets `<area>/<entity>/` and stops there. Do not
manufacture a category to fill the slot — an invented one is worse than none,
because the next author has to guess which invented name you used.

The nav config is the authority. Do not invent a category in the filesystem
that the sidebar does not have: a group that exists on disk and not in the nav
is a page no user can reach.

### What lives in an entity folder

Everything used only by that entity, and nothing else:

```
src/pages/pos/manage/catalog/items/
  ItemsPage.vue              # register / list
  ItemsPage.spec.ts
  ItemRecordPage.vue         # detail / create / edit
  ItemRecordPage.spec.ts
  ItemRecordPage.pricing.spec.ts
  components/
    ItemEditorPanel.vue
    ItemStockPanel.vue
```

- **Drop the redundant prefix once inside the folder.** `catalog/items/ItemsPage.vue`,
  not `catalog/items/PosManageItemsPage.vue` — the path already said "pos",
  "manage" and "items" three times. (Same principle the backend test layout
  uses: `tests/repair/test_policy.py`, not `test_repair_policy.py`.)
- **Specs sit beside the file they test.** A spec that has to walk `../../..` to
  reach its subject is telling you the subject moved and it did not.
- **Folder names are kebab-case, file names are PascalCase.** `item-groups/ItemGroupsPage.vue`.
  Not `item_groups`, not `itemgroups`, not `ItemGroups`. Mixed conventions in one
  tree (`cost_center/` beside `price-list/` beside `itemtaxtemplate/`) are how
  `grep` starts missing things.
- **A folder appears when there are two files.** One standalone page with no
  siblings and no private components stays a file at the category level
  (`auth/LoginPage.vue`). Register/record pairs always earn a folder — they
  always grow specs.

### Where a shared component goes

**Lift to the nearest common ancestor, and no higher.**

| Used by | Lives in |
|---------|----------|
| One page | That page's `components/` folder |
| Two entities in one category | `<area>/<category>/components/` |
| Two categories | `<area>/components/` |
| The whole app | `src/components/<domain>/` |

Promote a component the moment its second consumer appears — in the same commit
that adds the second consumer. Never pre-place a component in `src/components/`
"because it might be shared later"; that is how a global folder accumulates
things with exactly one caller.

The inverse is also a rule: a component in `src/components/` that ends up with a
single consumer moves down to it.

### Stores, services, composables

These mirror the same category segment, one level deep:

```
src/services/catalog/items.ts
src/stores/catalog/items.ts
src/composables/catalog/useItemPricing.ts
```

They do **not** repeat the full page path — services are consumed across areas,
and a service buried at `services/pos/manage/catalog/items.ts` reads as if only
the manage console may call it. Category is enough.

## Migration — how an existing flat tree gets fixed

Do not open a seventy-file rename PR. It is unreviewable, it collides with
every open branch, and it stalls.

**The rule is "touch it, move it":**

1. A ticket that touches an entity moves **that entity's** files into their
   folder, in the **same commit**, with `git mv` so history follows.
2. Route **names** never change — only `component:` import paths. Every existing
   link, bookmark and test that pushes by name keeps working, and the diff stays
   mechanically checkable.
3. New entities are born in the right place. There is no grace period for new
   files; a new page in a flat legacy directory is a review block.
4. Update the nav config and the route path in the same commit if they disagree
   with the new folder — all three must agree when the commit lands.

An entity whose files are already correctly placed needs no churn.

## Verify

Before claiming a frontend change done:

- [ ] Every new/moved file's path matches its route path (area / category / entity).
- [ ] The category exists in the nav config, not just on disk.
- [ ] Folders kebab-case, files PascalCase, no redundant prefix inside the folder.
- [ ] Specs sit beside their subject.
- [ ] No new component in a global `components/` dir with one consumer.
- [ ] Moves used `git mv`; route **names** are unchanged.
- [ ] The workspace build ran for real and passed (`yarn build` — report the output).

## Anti-Patterns

**Don't:** add `PosManageCouponCodesPage.vue` next to sixty-nine siblings because
"that is where the others are". Consistency with a known-bad layout is not a
justification; it is the mechanism by which the layout got that bad.

**Don't:** create `src/pages/<entity>/` with no category. A flat entity list is
the same problem one directory deeper.

**Don't:** mirror the doctype name literally when the nav says otherwise
(`uom/`, because the sidebar says "Units of Measure" under Catalog — not
`unitofmeasure/`). The nav label's slug wins; the doctype name belongs in the
service layer.

**Don't:** rename route names during a move. Names are the stable public
surface; paths are the private one.
