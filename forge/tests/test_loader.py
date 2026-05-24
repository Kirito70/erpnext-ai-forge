"""Tests for forge.loader — parses canonical/ + discovery/ into dataclasses."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.loader import (
    find_repo_root,
    load_adapter_config,
    load_agents,
    load_commands,
    load_discovery,
    load_forge_config,
    load_policies,
    load_security_scoring_yaml,
    load_skills,
    load_tools,
)


def test_find_repo_root_from_tests_dir():
    root = find_repo_root(Path(__file__).parent)
    assert (root / "forge.config.yaml").is_file()


def test_load_agents(repo_root):
    agents = load_agents(repo_root)
    ids = {a.id for a in agents}
    assert ids == {
        "architect",
        "backend-specialist",
        "frontend-frappe-ui-specialist",
        "frontend-quasar-specialist",
        "integrations-specialist",
        "security-reviewer",
        "qa-test-engineer",
        "devops-deployment",
    }


def test_architect_is_foundational(repo_root):
    architect = next(a for a in load_agents(repo_root) if a.id == "architect")
    assert architect.foundational is True
    assert architect.kind == "agent"
    assert architect.version != "0.0.0"
    assert architect.trigger
    assert architect.body.strip()  # body is non-empty


def test_load_commands_returns_17(repo_root):
    commands = load_commands(repo_root)
    assert len(commands) == 17
    expected_subset = {"scaffold-doctype", "review-security", "forge-sync"}
    assert expected_subset <= {c.id for c in commands}


def test_load_skills_returns_30(repo_root):
    skills = load_skills(repo_root)
    assert len(skills) == 30
    # Every skill has a domain inferred from parent dir
    domains = {s.domain for s in skills}
    assert "frappe-core" in domains
    assert "frontend" in domains
    assert "security" in domains


def test_load_policies(repo_root):
    policies = load_policies(repo_root)
    ids = {p.id for p in policies}
    assert ids == {"review-protocol", "escalation-rules", "governance"}


def test_load_security_scoring_yaml(repo_root):
    yaml_data = load_security_scoring_yaml(repo_root)
    assert yaml_data["starting_score"] == 100
    assert yaml_data["thresholds"]["auto_accept"] == 95
    assert yaml_data["thresholds"]["block_floor"] == 80
    assert yaml_data["thresholds"]["external_skill_minimum"] == 98


def test_load_tools(repo_root):
    tools = load_tools(repo_root)
    ids = {t.id for t in tools}
    assert "bench-restart" in ids
    assert "mariadb-query" in ids
    assert len(tools) == 14
    restart = next(t for t in tools if t.id == "bench-restart")
    assert restart.requires_confirmation is True


def test_load_discovery(repo_root):
    snap = load_discovery(repo_root)
    assert snap.apps  # apps-index.json loaded
    custom = snap.custom_app_names()
    assert "novizna_crm" in custom
    assert "novizna_pos" in custom
    assert len(custom) == 8


def test_discovery_app_lookup(repo_root):
    snap = load_discovery(repo_root)
    app = snap.app("novizna_pos")
    assert app is not None
    assert app["stack"].startswith("python + quasar")


def test_load_adapter_config_claude_code(repo_root):
    cfg = load_adapter_config(repo_root, "claude-code")
    assert cfg["tool"] == "claude-code"
    assert cfg["capabilities"]["agents"] is True
    assert cfg["capabilities"]["subagents"] is True


def test_load_adapter_config_unknown_tool_raises(repo_root):
    with pytest.raises(FileNotFoundError):
        load_adapter_config(repo_root, "nonexistent-tool")


def test_load_forge_config(repo_root):
    cfg = load_forge_config(repo_root)
    assert cfg["project"]["name"] == "erpnext-ai-forge"
    assert "claude-code" in cfg["enabled_tools"]
    assert cfg["security"]["auto_accept_threshold"] == 95
