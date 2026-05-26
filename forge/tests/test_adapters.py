"""Per-adapter smoke tests — every enabled adapter renders without error.

Tests are kept lightweight: we verify the renderer produces the expected number
of output files, every output contains a manifest-traceable header, and char
budgets are respected. Detailed template assertions live in test_render.py
(Claude Code) and individual per-adapter test files when richer cases emerge.
"""

from __future__ import annotations

import pytest

from forge.loader import load_adapter_config
from forge.render import render, render_summary


@pytest.fixture(autouse=True)
def fake_bench_env(tmp_path, monkeypatch):
    fake_bench = tmp_path / "fake-bench"
    fake_bench.mkdir()
    (fake_bench / "apps").mkdir()
    monkeypatch.setenv("FORGE_BENCH_PATH", str(fake_bench))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "test-site")
    yield


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------
def test_cursor_renders_main_plus_per_app(repo_root):
    rendered = render(repo_root, "cursor")
    summary = render_summary(rendered)
    # 1 forge-main.mdc + 8 per-app .mdc files
    assert summary.get("aggregate") == 9
    main = next(r for r in rendered if r.artifact_id == "aggregate/forge_main")
    # Must respect the 40k char budget
    assert len(main.content) < 40_000, f"forge-main.mdc {len(main.content)} chars exceeds 40k budget"
    assert "alwaysApply: true" in main.content
    # Per-app filenames must be substituted correctly
    per_app_paths = [r.output_path.name for r in rendered if "per_app" in r.artifact_id]
    assert "forge-novizna_crm.mdc" in per_app_paths
    assert "forge-novizna_pos.mdc" in per_app_paths


# ---------------------------------------------------------------------------
# OpenCode — v0.6.2: first-class agents/commands/skills/tools (like Claude Code)
# ---------------------------------------------------------------------------
def test_opencode_renders_full_artifact_set(repo_root):
    """OpenCode now mirrors Claude Code's per-artifact layout: one file per
    agent, command, skill, and tool under .opencode/<kind>/."""
    rendered = render(repo_root, "opencode")
    summary = render_summary(rendered)
    # Same counts as Claude Code (8 agents + 17 commands + 30 skills + 14 tools)
    # plus a single AGENTS.md index aggregate.
    assert summary.get("agent") == 8
    assert summary.get("command") == 17
    assert summary.get("skill") == 30
    assert summary.get("tool") == 14
    assert summary.get("aggregate") == 1   # AGENTS.md index only
    # AGENTS.md is the bench-root index
    agents_md = next(r for r in rendered if r.artifact_id == "aggregate/forge_agents_index")
    assert agents_md.output_path.name == "AGENTS.md"
    # Index is small (just pointers, not full bodies)
    assert len(agents_md.content) < 20_000, "AGENTS.md index exceeds 20k"


def test_opencode_writes_to_dot_opencode_tree(repo_root):
    """Per-artifact outputs land under .opencode/{agents,commands,skills,tools}/."""
    rendered = render(repo_root, "opencode")
    paths_by_kind: dict[str, list[str]] = {}
    for r in rendered:
        paths_by_kind.setdefault(r.artifact_kind, []).append(str(r.output_path))
    # Every agent lives under .opencode/agents/
    assert all("/.opencode/agents/" in p for p in paths_by_kind["agent"])
    # Every command lives under .opencode/commands/
    assert all("/.opencode/commands/" in p for p in paths_by_kind["command"])
    # Every skill lives under .opencode/skills/<domain>/
    assert all("/.opencode/skills/" in p for p in paths_by_kind["skill"])
    # Every tool reference lives under .opencode/tools/
    assert all("/.opencode/tools/" in p for p in paths_by_kind["tool"])


# ---------------------------------------------------------------------------
# Cline
# ---------------------------------------------------------------------------
def test_cline_renders_main_plus_per_app(repo_root):
    rendered = render(repo_root, "cline")
    summary = render_summary(rendered)
    # 1 main + 8 per-app
    assert summary.get("aggregate") == 9
    main = next(r for r in rendered if r.artifact_id == "aggregate/forge_main")
    assert len(main.content) < 35_000, "00-forge-main.md exceeds 35k budget"
    assert main.output_path.name == "00-forge-main.md"
    per_app_names = [r.output_path.name for r in rendered if "per_app" in r.artifact_id]
    assert "10-app-novizna_crm.md" in per_app_names


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------
def test_copilot_renders_main_plus_per_app(repo_root):
    rendered = render(repo_root, "copilot")
    summary = render_summary(rendered)
    assert summary.get("aggregate") == 9
    main = next(r for r in rendered if r.artifact_id == "aggregate/copilot_instructions")
    assert len(main.content) < 30_000, "copilot-instructions.md exceeds 30k budget"
    assert main.output_path.name == "copilot-instructions.md"
    per_app = [r for r in rendered if "per_app" in r.artifact_id]
    # Per-app must carry applyTo frontmatter
    for r in per_app:
        assert "applyTo:" in r.content
        assert f"apps/" in r.content


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------
def test_codex_renders_single_aggregate(repo_root):
    rendered = render(repo_root, "codex")
    assert len(rendered) == 1
    out = rendered[0]
    assert out.output_path.name == "AGENTS.codex.md"
    assert len(out.content) < 20_000, "AGENTS.codex.md exceeds 20k budget"


# ---------------------------------------------------------------------------
# Antigravity
# ---------------------------------------------------------------------------
def test_antigravity_renders_minimal_aggregate(repo_root):
    rendered = render(repo_root, "antigravity")
    assert len(rendered) == 1
    out = rendered[0]
    assert out.output_path.name == "system.md"
    # Minimal target: respect 15k budget
    assert len(out.content) < 15_000, "system.md exceeds 15k budget"
    # Only the 3 inlined personas should appear as expanded persona sections
    assert "Persona: `architect`" in out.content
    assert "Persona: `backend-specialist`" in out.content
    assert "Persona: `security-reviewer`" in out.content


# ---------------------------------------------------------------------------
# Capability matrix sanity
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "tool",
    ["claude-code", "cursor", "opencode", "cline", "copilot", "codex", "antigravity"],
)
def test_adapter_yaml_has_required_keys(repo_root, tool):
    cfg = load_adapter_config(repo_root, tool)
    assert cfg["tool"] == tool
    assert "capabilities" in cfg
    assert "output_paths" in cfg
    assert "artifacts" in cfg
    assert "manifest" in cfg


@pytest.mark.parametrize(
    "tool,expected_limit",
    [
        ("cursor", 40000),
        # opencode no longer has a single-file budget — it renders per-artifact
        # like Claude Code (see v0.6.2 adapter expansion). Skipped here; the
        # adapter.yaml carries max_total_chars: null.
        ("cline", 35000),
        ("copilot", 30000),
        ("codex", 20000),
        ("antigravity", 15000),
    ],
)
def test_adapter_char_budget_documented(repo_root, tool, expected_limit):
    cfg = load_adapter_config(repo_root, tool)
    assert cfg.get("limits", {}).get("max_total_chars") == expected_limit


# ---------------------------------------------------------------------------
# Manifest provenance — every aggregate output names its forge version
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "tool",
    ["cursor", "opencode", "cline", "copilot", "codex", "antigravity"],
)
def test_every_adapter_writes_provenance_footer(repo_root, tool):
    rendered = render(repo_root, tool)
    for r in rendered:
        if r.artifact_kind == "aggregate":
            assert "erpnext-ai-forge" in r.content
            assert "AUTO-GENERATED" in r.content
