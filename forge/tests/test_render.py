"""Tests for forge.render — Jinja-based canonical → per-tool rendering."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from forge.render import render, render_summary


@pytest.fixture(autouse=True)
def fake_bench_env(tmp_path, monkeypatch):
    """Render against a temp bench so tests don't need the real bench mounted."""
    fake_bench = tmp_path / "fake-bench"
    fake_bench.mkdir()
    (fake_bench / "apps").mkdir()
    monkeypatch.setenv("FORGE_BENCH_PATH", str(fake_bench))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "test-site")
    yield


def test_render_claude_code_produces_artifacts(repo_root):
    rendered = render(repo_root, "claude-code")
    summary = render_summary(rendered)

    assert summary.get("agent") == 8
    assert summary.get("command") == 17
    assert summary.get("skill") == 30
    assert summary.get("tool") == 14
    assert summary.get("aggregate") >= 1  # root CLAUDE.md + per-app CLAUDE.md files


def test_rendered_agent_has_frontmatter(repo_root):
    rendered = render(repo_root, "claude-code")
    architect = next(r for r in rendered if r.artifact_id == "architect")
    content = architect.content
    assert "AUTO-GENERATED FROM erpnext-ai-forge" in content
    assert "---" in content
    assert "name: architect" in content
    assert "description:" in content


def test_rendered_command_has_description(repo_root):
    rendered = render(repo_root, "claude-code")
    scaffold = next(r for r in rendered if r.artifact_id == "scaffold-doctype")
    assert "description:" in scaffold.content
    assert "Triggers agents:" in scaffold.content


def test_rendered_skill_carries_domain(repo_root):
    rendered = render(repo_root, "claude-code")
    skill = next(
        r for r in rendered
        if r.artifact_kind == "skill" and r.artifact_id == "novizna-crm-override-system"
    )
    # Skill should be written under .claude/skills/frontend/
    assert "skills/frontend" in str(skill.output_path)
    assert "novizna-crm-override-system" in skill.content


def test_rendered_per_app_includes_all_custom_apps(repo_root):
    rendered = render(repo_root, "claude-code")
    per_app = [r for r in rendered if r.artifact_id.startswith("per-app-claude-md/")]
    app_names = {r.artifact_id.split("/", 1)[1] for r in per_app}
    assert "novizna_crm" in app_names
    assert "novizna_pos" in app_names
    assert "noviznaerp_payroll" in app_names
    assert len(app_names) == 8


def test_rendered_root_claude_md_has_cross_cutting_only(repo_root):
    rendered = render(repo_root, "claude-code")
    root = next(r for r in rendered if r.artifact_id == "root-claude-md")
    body = root.content
    assert "Per-app context lives in" in body
    # Should not mention specific app implementation details beyond pointers
    assert "novizna-v16" in body  # primary site token
