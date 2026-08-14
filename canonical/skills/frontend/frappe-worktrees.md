---
id: frappe-worktrees
kind: skill
version: 1.0.0
status: stable
owners: [m.tayyab9736@gmail.com]
last_reviewed: 2026-08-13
trigger: "Working in a git worktree of any bench app (novizna_pos-f12/, novizna_restaurant-*/, …) — before running ANY build, lint, test or bench command, and before editing ANY build config"
scope: [agent:architect, agent:frontend-quasar-specialist, agent:frontend-frappe-ui-specialist, agent:backend-specialist, agent:qa-test-engineer, agent:code-reviewer]
foundational: true
domain: frontend
security_score: 100
supersedes: []
---

# Git worktrees in a Frappe bench

A bench app is installed at `<bench>/apps/<app>`, and that path is load-bearing:
the Python package is installed editable against it, and build tooling resolves
the bench relative to it. A git worktree lives *outside* that path, so some
commands work there and some silently do the wrong thing.

This skill is the map of which is which.

## The rule that matters most

**Never edit a build config to make it work in your worktree.**

`quasar.config.js`, `vite.config.js`, `build.json` and friends are tracked. An
edit that repoints a path at `novizna_pos-f12/` fixes your checkout and breaks
the bench for everyone else — this has already happened once. If a config
cannot find the bench, that is a bug in the config's *resolution strategy*, to
be fixed once for all worktrees (walk up and degrade gracefully), never
per-checkout.

## The trap: Python is always the bench copy

```
env/lib/python3.*/site-packages/__editable__.novizna_pos-0.0.1.pth  ->  apps/novizna_pos
```

`bench --site … run-tests`, `bench build`, `bench migrate` and every `frappe.*`
import resolve through that path. They exercise **`apps/<app>`, never your
worktree** — no matter which directory you run them from.

This fails *silently*: the tests pass, but they tested different code. So:

> **Python verification is bench-only.** A change made in a worktree is
> unverified until it is in `apps/<app>`.

There is no cheap fix. Re-installing the package per worktree would repoint the
bench at your branch, which is worse.

## Two frontend shapes, two answers

Check what the app actually has before assuming:

| the app has… | build | worktree-capable? |
|---|---|---|
| its own `package.json` (`novizna_pos/novizna-pos-ui/`) | `yarn build` | **yes**, after bootstrap |
| `public/build.json` + `app_include_js` (`novizna_restaurant/`) | `bench build --app <app>` | **no** — bench-only |

A Frappe-bundled frontend is built by Frappe's own esbuild, which resolves apps
through `apps/`. There is nothing to configure and nothing to fix: treat its
assets exactly like Python.

## Worktree bootstrap (own-`package.json` apps only)

A fresh worktree needs two things that are not in git:

```bash
WT=…/novizna_pos-f12/novizna-pos-ui
MAIN=…/novizna_pos-main/novizna-pos-ui

# 1. Dependencies — SYMLINK, never `yarn install`.
#    All worktrees share one tree; installing into a worktree corrupts it for
#    every other one.
ln -s "$MAIN/node_modules" "$WT/node_modules"

# 2. Generated tsconfig — gitignored, produced by a build. vitest and tsc both
#    need it and fail confusingly without it.
mkdir -p "$WT/.quasar" && cp "$MAIN/.quasar/tsconfig.json" "$WT/.quasar/"
```

## What runs where

```
WORKTREE (novizna_pos-f12/)          BENCH (apps/novizna_pos/)
-----------------------------        --------------------------------
git branch / commit / rebase         bench --site … run-tests
edit .py .ts .vue .scss              bench build / migrate / install-app
npx eslint <files>                   python integration tests
yarn vitest run                      Frappe-bundled frontend builds
yarn build                           FINAL pre-merge verification
quasar dev  (see below)
```

`quasar dev` from a worktree needs the ports, since the bench's
`common_site_config.json` is not reachable:

```bash
WEBSERVER_PORT=8000 WEBSOCKET_PORT=9000 npx quasar dev
```

## Before you open a PR

Re-run the gates from `apps/<app>`, not from the worktree. A green worktree run
proves the frontend; it proves nothing about Python, and `bench build` output
for a bundled frontend is a *committed artifact* — build it in the bench or the
diff will be wrong.

## Why the resolution strategy is what it is

`quasar.config.js` finds the bench by walking up for a directory containing both
`sites/` and `apps/`, and falls back to `{}` when there is none. Only the
dev-server proxy consumes that data, so lint, test and build work anywhere,
while `quasar dev` degrades to env-var ports instead of throwing at import time.

The earlier fixed `path.resolve(__dirname, '../../../sites/…')` resolved outside
the bench from any worktree and threw during module load — breaking `yarn
build`, eslint and vitest, none of which need the file at all. Same approach as
`novizna_crm/frontend/vite.config.js`.
