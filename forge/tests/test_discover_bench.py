"""Tests for forge.discover_bench — automated bench walking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.discover_bench import (
    _detect_stack,
    _list_doctypes,
    _list_whitelist_methods,
    _parse_hooks_signals,
    _scan_anti_patterns,
    discover_bench,
)


@pytest.fixture
def fake_bench(tmp_path: Path) -> Path:
    """Build a minimal fake bench resembling Novizna's layout."""
    bench = tmp_path / "bench"
    bench.mkdir()
    apps = bench / "apps"
    apps.mkdir()

    # --- Custom app: novizna_crm with frontend + connectors ---
    crm = apps / "novizna_crm"
    crm.mkdir()
    (crm / "novizna_crm").mkdir()
    (crm / "novizna_crm" / "hooks.py").write_text(
        'doc_events = {"Lead": {"on_update": "novizna_crm.api.x"}}\n'
        'scheduler_events = {"daily": []}\n'
        'app_include_js = ["x.js"]\n'
        'after_install = "novizna_crm.install.after"\n'
    )
    # DocType
    dt = crm / "novizna_crm" / "novizna_crm" / "doctype" / "crm_lead_industry"
    dt.mkdir(parents=True)
    (dt / "crm_lead_industry.json").write_text('{"name": "CRM Lead Industry"}')
    (dt / "crm_lead_industry.py").write_text(
        "import frappe\n"
        "@frappe.whitelist()\n"
        "def list_industries():\n"
        "    pass\n"
        "@frappe.whitelist(allow_guest=True)\n"
        "def public_endpoint():\n"
        "    pass\n"
    )
    # Anti-pattern: SQL injection
    api_mod = crm / "novizna_crm" / "api"
    api_mod.mkdir(parents=True)
    (api_mod / "leads.py").write_text(
        "import frappe\n"
        "def bad():\n"
        "    frappe.db.sql(f\"SELECT * FROM `tabLead` WHERE name='{n}'\")\n"
    )
    # Frontend (Frappe-UI)
    fe = crm / "frontend"
    fe.mkdir()
    (fe / "package.json").write_text('{"dependencies": {"frappe-ui": "^0.1.0"}}')
    so = fe / "src_override" / "components" / "Layouts"
    so.mkdir(parents=True)
    (so / "AppSidebar.vue").write_text("<template>x</template>")
    src = fe / "src"
    src.mkdir()
    (src / "index.js").write_text("// novizna additions")

    # --- Custom app: novizna_pos (Quasar) ---
    pos = apps / "novizna_pos"
    pos.mkdir()
    (pos / "novizna_pos").mkdir()
    (pos / "novizna_pos" / "hooks.py").write_text(
        'doc_events = {"POS Profile": {}}\n'
        'after_install = "x"\n'
    )
    ui = pos / "novizna-pos-ui"
    ui.mkdir()
    (ui / "quasar.config.ts").write_text("export default {}")
    (ui / "package.json").write_text('{"dependencies": {}}')

    # --- Custom app: pure backend ---
    payroll = apps / "noviznaerp_payroll"
    payroll.mkdir()
    (payroll / "noviznaerp_payroll").mkdir()
    (payroll / "noviznaerp_payroll" / "hooks.py").write_text(
        'doc_events = {}\n'
        'scheduler_events = {}\n'
        'override_doctype_class = {}\n'
    )

    # --- Upstream app: frappe (skip) ---
    fr = apps / "frappe"
    fr.mkdir()
    (fr / "frappe").mkdir()
    (fr / "frappe" / "hooks.py").write_text("# upstream")

    # --- Sites ---
    sites = bench / "sites"
    sites.mkdir()
    primary = sites / "test-site"
    primary.mkdir()
    (primary / "site_config.json").write_text(
        json.dumps({"db_host": "redacted", "db_password": "redacted", "encryption_key": "x"})
    )
    (sites / "common_site_config.json").write_text(
        json.dumps({"developer_mode": 1, "ignore_csrf": 1, "redis_cache": "redis://x"})
    )

    return bench


def test_detect_stack_quasar(fake_bench):
    assert _detect_stack(fake_bench / "apps" / "novizna_pos") == "python + quasar-vue3-pwa"


def test_detect_stack_frappe_ui(fake_bench):
    assert _detect_stack(fake_bench / "apps" / "novizna_crm") == "python + frappe-ui-vue3"


def test_detect_stack_pure_backend(fake_bench):
    assert _detect_stack(fake_bench / "apps" / "noviznaerp_payroll") == "python"


def test_parse_hooks_signals(fake_bench):
    signals = _parse_hooks_signals(
        fake_bench / "apps" / "novizna_crm" / "novizna_crm" / "hooks.py"
    )
    assert signals["doc_events"] is True
    assert signals["scheduler_events"] is True
    assert signals["app_include_js"] is True
    assert signals["after_install"] is True
    assert signals["override_doctype_class"] is False
    assert signals["fixtures"] is False


def test_list_doctypes(fake_bench):
    dts = _list_doctypes(fake_bench / "apps" / "novizna_crm")
    assert dts == ["crm_lead_industry"]


def test_list_whitelist_methods(fake_bench):
    total, sample = _list_whitelist_methods(fake_bench / "apps" / "novizna_crm")
    assert total >= 2
    assert "list_industries" in sample
    assert "public_endpoint" in sample


def test_scan_anti_patterns_detects_sql_fstring(fake_bench):
    findings = _scan_anti_patterns(
        fake_bench / "apps" / "novizna_crm", "novizna_crm"
    )
    assert findings["sql_fstring"], "Expected SQL f-string finding"
    assert any("leads.py" in f for f in findings["sql_fstring"])


def test_scan_anti_patterns_detects_allow_guest(fake_bench):
    findings = _scan_anti_patterns(
        fake_bench / "apps" / "novizna_crm", "novizna_crm"
    )
    assert findings["allow_guest"]


def test_discover_bench_end_to_end(repo_root, fake_bench, monkeypatch, tmp_path):
    # Redirect discovery/ output into a temp clone of the repo to avoid
    # clobbering the real Phase 0 hand-authored snapshot.
    fake_repo = tmp_path / "fake-repo"
    fake_repo.mkdir()
    # forge.config.yaml is the only file the loader requires
    (fake_repo / "forge.config.yaml").write_text(
        "project: {name: erpnext-ai-forge, version: 0.0.0}\n"
        "bench: {path: '{{ env.FORGE_BENCH_PATH }}', primary_site: '{{ env.FORGE_PRIMARY_SITE }}'}\n"
        "enabled_tools: [claude-code]\n"
        "upstream_apps: [frappe, erpnext]\n"
    )
    monkeypatch.setenv("FORGE_BENCH_PATH", str(fake_bench))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "test-site")

    written = discover_bench(repo_root=fake_repo, bench_override=fake_bench)
    assert "apps-index.json" in written
    assert "hooks-index.json" in written
    assert "anti-pattern-findings.json" in written
    assert "site-config-keys.json" in written

    apps_idx = json.loads(written["apps-index.json"].read_text())
    custom = {a["name"]: a for a in apps_idx["custom_apps"]}
    assert "novizna_crm" in custom
    assert "novizna_pos" in custom
    assert "noviznaerp_payroll" in custom
    # frappe is upstream → excluded from custom_apps
    assert "frappe" not in custom
    assert custom["novizna_pos"]["stack"] == "python + quasar-vue3-pwa"

    # site_config keys: names only, values not present
    keys = json.loads(written["site-config-keys.json"].read_text())
    assert keys["site_config_keys"] == ["db_host", "db_password", "encryption_key"]
    assert keys["security_flag"] is not None  # ignore_csrf flagged

    # anti-patterns: sql_fstring counted
    ap = json.loads(written["anti-pattern-findings.json"].read_text())
    assert ap["totals"]["sql_fstring"] >= 1


def test_discover_bench_only_app_filter(repo_root, fake_bench, monkeypatch, tmp_path):
    fake_repo = tmp_path / "fake-repo-2"
    fake_repo.mkdir()
    (fake_repo / "forge.config.yaml").write_text(
        "project: {name: erpnext-ai-forge, version: 0.0.0}\n"
        "bench: {path: '{{ env.FORGE_BENCH_PATH }}', primary_site: '{{ env.FORGE_PRIMARY_SITE }}'}\n"
        "enabled_tools: [claude-code]\n"
        "upstream_apps: [frappe, erpnext]\n"
    )
    monkeypatch.setenv("FORGE_BENCH_PATH", str(fake_bench))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "test-site")
    written = discover_bench(
        repo_root=fake_repo, bench_override=fake_bench, only_app="novizna_crm"
    )
    apps_idx = json.loads(written["apps-index.json"].read_text())
    custom_names = {a["name"] for a in apps_idx["custom_apps"]}
    assert custom_names == {"novizna_crm"}
