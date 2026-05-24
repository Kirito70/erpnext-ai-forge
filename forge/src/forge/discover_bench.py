"""Automated bench discovery.

Walks `<bench>/apps/<custom-app>/` and produces the same JSON files that
were hand-authored during Phase 0:

  apps-index.json
  hooks-index.json
  doctype-index.json
  api-surface.json
  override-map.json
  integrations-map.json
  anti-pattern-findings.json
  site-config-keys.json

The hand-authored `discovery/INVENTORY.md` is left alone — it's a human-curated
summary that references these JSONs.

The custom-app list comes from `forge.config.yaml` `upstream_apps` (everything
under `<bench>/apps/` that ISN'T in that list).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forge.loader import find_repo_root, load_forge_config


# ---------------------------------------------------------------------------
# Patterns used by the walker
# ---------------------------------------------------------------------------
_WHITELIST_RE = re.compile(r"@frappe\.whitelist\s*\([^)]*\)")
_WHITELIST_DEF_RE = re.compile(
    r"@frappe\.whitelist\s*\(([^)]*)\)\s*\n\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)"
)
_ALLOW_GUEST_RE = re.compile(r"allow_guest\s*=\s*True")
_SQL_FSTRING_RE = re.compile(r"frappe\.db\.sql\(\s*f['\"]")
_IGNORE_PERMS_RE = re.compile(r"ignore_permissions\s*=\s*True")
_DB_COMMIT_RE = re.compile(r"frappe\.db\.commit\(\)")
_HOOK_KEYS = (
    "doc_events",
    "scheduler_events",
    "fixtures",
    "boot_session",
    "override_doctype_class",
    "override_whitelisted_methods",
    "app_include_js",
    "web_include_js",
    "app_include_css",
    "web_include_css",
    "after_install",
)


# ---------------------------------------------------------------------------
# Per-app stack detection
# ---------------------------------------------------------------------------
def _detect_stack(app_dir: Path) -> str:
    """Match the Phase 0 heuristic: Frappe-UI Vue3 / Quasar PWA / pure-backend."""
    # Quasar config anywhere under the app (within reason — avoid node_modules)
    for candidate in app_dir.rglob("quasar.config.*"):
        if "node_modules" not in candidate.parts:
            return "python + quasar-vue3-pwa"
    for candidate in app_dir.rglob("quasar.conf.*"):
        if "node_modules" not in candidate.parts:
            return "python + quasar-vue3-pwa"
    # Frappe-UI: any package.json under the app referencing frappe-ui
    for pkg in app_dir.rglob("package.json"):
        if "node_modules" in pkg.parts:
            continue
        try:
            content = pkg.read_text()
        except OSError:
            continue
        if "frappe-ui" in content:
            return "python + frappe-ui-vue3"
    return "python"


# ---------------------------------------------------------------------------
# Hooks parser (regex-based — doesn't import hooks.py)
# ---------------------------------------------------------------------------
def _parse_hooks_signals(hooks_path: Path) -> dict[str, bool]:
    signals: dict[str, bool] = {}
    if not hooks_path.is_file():
        return {key: False for key in _HOOK_KEYS}
    text = hooks_path.read_text(errors="replace")
    for key in _HOOK_KEYS:
        # Look for top-of-line assignment: `doc_events = {...}` or `after_install = "..."`
        signals[key] = bool(re.search(rf"^\s*{re.escape(key)}\s*=", text, re.MULTILINE))
    return signals


# ---------------------------------------------------------------------------
# DocType + whitelist API walkers
# ---------------------------------------------------------------------------
def _list_doctypes(app_dir: Path) -> list[str]:
    """Return DocType IDs found under app_dir (basename of containing folder)."""
    out: list[str] = []
    for jsonp in app_dir.rglob("doctype/*/*.json"):
        if "__pycache__" in jsonp.parts:
            continue
        # The DocType ID is the parent dir name (e.g. crm_lead_industry)
        out.append(jsonp.parent.name)
    return sorted(set(out))


def _list_whitelist_methods(app_dir: Path) -> tuple[int, list[str]]:
    """Return (total count, first-N method names) for @frappe.whitelist() in app_dir."""
    methods: list[str] = []
    total = 0
    for py in app_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            text = py.read_text(errors="replace")
        except OSError:
            continue
        for match in _WHITELIST_DEF_RE.finditer(text):
            methods.append(match.group(2))
            total += 1
        # Also count decorator hits that didn't match the def pattern
        extra = len(_WHITELIST_RE.findall(text)) - len(
            list(_WHITELIST_DEF_RE.finditer(text))
        )
        if extra > 0:
            total += extra
    return total, methods[:5]


# ---------------------------------------------------------------------------
# Anti-pattern scanner
# ---------------------------------------------------------------------------
def _scan_anti_patterns(app_dir: Path, app_name: str) -> dict[str, list[str]]:
    """Return categorized file:line examples (top 10 per category)."""
    found: dict[str, list[str]] = {
        "sql_fstring": [],
        "allow_guest": [],
        "ignore_permissions": [],
        "db_commit_non_test": [],
    }
    for py in app_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        # Skip test files for db_commit (commits in tests are expected)
        is_test = py.name.startswith("test_") or "/tests/" in str(py)
        try:
            text = py.read_text(errors="replace")
        except OSError:
            continue
        for match in _SQL_FSTRING_RE.finditer(text):
            line = text[: match.start()].count("\n") + 1
            found["sql_fstring"].append(f"{py.relative_to(app_dir.parent.parent)}:{line}")
        for match in _ALLOW_GUEST_RE.finditer(text):
            line = text[: match.start()].count("\n") + 1
            found["allow_guest"].append(f"{py.relative_to(app_dir.parent.parent)}:{line}")
        for match in _IGNORE_PERMS_RE.finditer(text):
            line = text[: match.start()].count("\n") + 1
            found["ignore_permissions"].append(
                f"{py.relative_to(app_dir.parent.parent)}:{line}"
            )
        if not is_test:
            for match in _DB_COMMIT_RE.finditer(text):
                line = text[: match.start()].count("\n") + 1
                found["db_commit_non_test"].append(
                    f"{py.relative_to(app_dir.parent.parent)}:{line}"
                )
    # Sort and cap each list at 15 examples
    return {k: sorted(set(v))[:15] for k, v in found.items()}


# ---------------------------------------------------------------------------
# Override map for novizna_crm specifically
# ---------------------------------------------------------------------------
def _build_override_map(bench: Path) -> dict[str, Any]:
    crm_frontend = bench / "apps" / "novizna_crm" / "frontend"
    if not crm_frontend.is_dir():
        return {}
    override_dir = crm_frontend / "src_override"
    src_dir = crm_frontend / "src"

    override_files: list[str] = []
    if override_dir.is_dir():
        for p in override_dir.rglob("*"):
            if p.is_file() and p.suffix in {".vue", ".js", ".ts", ".css"}:
                override_files.append(str(p.relative_to(override_dir)))

    src_entries: list[str] = []
    if src_dir.is_dir():
        src_entries = sorted(p.name for p in src_dir.iterdir())

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Automated discovery — novizna_crm 3-layer override system (v0.2 Decision 16). All paths in src_override/ MUST be one-for-one with apps/crm/frontend/src/.",
        "app": "novizna_crm",
        "frontend_root": "apps/novizna_crm/frontend",
        "layers": {
            "src_override": {
                "purpose": "Files that REPLACE upstream apps/crm/frontend/src/ files (strict one-for-one)",
                "files": sorted(override_files),
                "override_count": len(override_files),
            },
            "src": {
                "purpose": "Net-new files that do not exist in upstream",
                "top_level_entries": src_entries,
            },
            "crm_build": {
                "purpose": "GENERATED workspace, wiped on every yarn dev/yarn build",
                "modifiable": False,
                "warning": "NEVER edit files here — they will be silently overwritten",
            },
        },
        "validation_tool": "yarn check-conflicts (run after upstream crm updates)",
    }


# ---------------------------------------------------------------------------
# site_config keys (names only)
# ---------------------------------------------------------------------------
def _site_config_keys(bench: Path, primary_site: str) -> dict[str, Any]:
    site_cfg_path = bench / "sites" / primary_site / "site_config.json"
    common_cfg_path = bench / "sites" / "common_site_config.json"

    def _keys(p: Path) -> list[str]:
        if not p.is_file():
            return []
        try:
            return sorted(json.loads(p.read_text()).keys())
        except (OSError, json.JSONDecodeError):
            return []

    site_keys = _keys(site_cfg_path)
    common_keys = _keys(common_cfg_path)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Per v0.2 §8.5 and Decision 12: only KEY NAMES recorded. Values are never read into the model context.",
        "primary_site": primary_site,
        "site_config_keys": site_keys,
        "common_site_config_keys": common_keys,
        "security_flag": (
            {"key": "ignore_csrf", "severity": "HIGH",
             "finding": "CSRF protection disabled site-wide."}
            if "ignore_csrf" in common_keys
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def discover_bench(
    repo_root: Path | None = None,
    bench_override: Path | None = None,
    only_app: str | None = None,
) -> dict[str, Path]:
    """Walk the bench, write JSON files under discovery/data/, return what was written."""
    repo_root = repo_root or find_repo_root()
    cfg = load_forge_config(repo_root)

    if bench_override is not None:
        bench = bench_override
    else:
        # Resolve `{{ env.FORGE_BENCH_PATH }}` ourselves to avoid dragging in Jinja
        import os
        bench_str = cfg["bench"]["path"].replace(
            "{{ env.FORGE_BENCH_PATH }}", os.environ.get("FORGE_BENCH_PATH", "")
        )
        bench = Path(bench_str)
    if not bench.is_dir() or not (bench / "apps").is_dir():
        raise FileNotFoundError(f"Bench apps/ not found at {bench}")

    upstream = set(cfg.get("upstream_apps", []))
    apps_dir = bench / "apps"
    all_apps = sorted(p.name for p in apps_dir.iterdir() if p.is_dir())
    custom_apps_names = [a for a in all_apps if a not in upstream]
    upstream_apps_names = [a for a in all_apps if a in upstream]

    now = datetime.now(timezone.utc).isoformat()
    data_dir = repo_root / "discovery" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    # Decide which custom apps to walk this run.
    walk_targets = (
        [a for a in custom_apps_names if a == only_app]
        if only_app
        else custom_apps_names
    )

    # --- per-app data ---
    apps_payload: list[dict[str, Any]] = []
    hooks_payload: dict[str, dict[str, Any]] = {}
    doctype_payload: dict[str, list[str] | dict[str, Any]] = {}
    api_payload: dict[str, dict[str, Any]] = {}
    anti_patterns_per_app: dict[str, dict[str, list[str]]] = {}

    for app in walk_targets:
        app_root = apps_dir / app
        nested = app_root / app  # canonical Frappe app dir
        if not nested.is_dir():
            # Some apps nest differently; fall back to the outer dir
            nested = app_root
        stack = _detect_stack(app_root)
        doctypes = _list_doctypes(app_root)
        api_count, api_sample = _list_whitelist_methods(app_root)
        hooks_path = nested / "hooks.py"
        hook_signals = _parse_hooks_signals(hooks_path)
        ap = _scan_anti_patterns(app_root, app)

        apps_payload.append(
            {
                "name": app,
                "type": "custom",
                "stack": stack,
                "doctype_count": len(doctypes),
                "whitelist_api_count": api_count,
            }
        )
        hooks_payload[app] = {
            "hooks_path": str(hooks_path.relative_to(bench)),
            "signals": hook_signals,
        }
        doctype_payload[app] = (
            doctypes if len(doctypes) <= 20
            else {"_count": len(doctypes), "_sample": doctypes[:20]}
        )
        api_payload[app] = {
            "total_whitelist_methods": api_count,
            "sample_methods": api_sample,
        }
        anti_patterns_per_app[app] = ap

    # --- upstream apps list (unchanged from forge.config.yaml ordering) ---
    upstream_payload = [
        {"name": a, "type": "upstream", "modifiable": False}
        for a in upstream_apps_names
    ]

    # --- aggregate writes ---
    files: dict[str, Any] = {
        "apps-index.json": {
            "schema_version": 1,
            "generated_at": now,
            "generated_by": "forge discover",
            "bench_path": str(bench),
            "upstream_apps": upstream_payload,
            "custom_apps": apps_payload,
            "totals": {
                "upstream_app_count": len(upstream_payload),
                "custom_app_count": len(apps_payload),
                "custom_doctype_count": sum(a["doctype_count"] for a in apps_payload),
                "custom_whitelist_api_count": sum(a["whitelist_api_count"] for a in apps_payload),
            },
        },
        "hooks-index.json": {
            "schema_version": 1,
            "generated_at": now,
            "generated_by": "forge discover",
            "custom_apps": hooks_payload,
        },
        "doctype-index.json": {
            "schema_version": 1,
            "generated_at": now,
            "generated_by": "forge discover",
            "custom_apps": doctype_payload,
        },
        "api-surface.json": {
            "schema_version": 1,
            "generated_at": now,
            "generated_by": "forge discover",
            "custom_apps": api_payload,
        },
        "anti-pattern-findings.json": {
            "schema_version": 1,
            "generated_at": now,
            "generated_by": "forge discover",
            "per_app": anti_patterns_per_app,
            "totals": {
                "sql_fstring": sum(len(v["sql_fstring"]) for v in anti_patterns_per_app.values()),
                "allow_guest": sum(len(v["allow_guest"]) for v in anti_patterns_per_app.values()),
                "ignore_permissions": sum(
                    len(v["ignore_permissions"]) for v in anti_patterns_per_app.values()
                ),
                "db_commit_non_test": sum(
                    len(v["db_commit_non_test"]) for v in anti_patterns_per_app.values()
                ),
            },
        },
        "override-map.json": _build_override_map(bench),
        "site-config-keys.json": _site_config_keys(
            bench, cfg["bench"]["primary_site"].replace(
                "{{ env.FORGE_PRIMARY_SITE }}",
                __import__("os").environ.get("FORGE_PRIMARY_SITE", ""),
            )
        ),
    }

    for name, payload in files.items():
        if only_app and name not in {
            "apps-index.json",
            "hooks-index.json",
            "doctype-index.json",
            "api-surface.json",
            "anti-pattern-findings.json",
        }:
            # When narrowing to one app, only rewrite per-app files
            continue
        target = data_dir / name
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
        tmp.replace(target)
        written[name] = target

    return written
