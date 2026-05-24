"""End-to-end CLI smoke against the real repo.

These tests exercise the wired-up commands (no longer 'not yet implemented')
to ensure they succeed on the real canonical layer.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from forge.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def fake_bench_env(tmp_path, monkeypatch):
    fake_bench = tmp_path / "fake-bench"
    fake_bench.mkdir()
    (fake_bench / "apps").mkdir()
    monkeypatch.setenv("FORGE_BENCH_PATH", str(fake_bench))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "test-site")
    yield


def test_validate_passes_on_real_canonical():
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0, result.stdout
    assert "schema valid" in result.stdout or "Loaded:" in result.stdout


def test_render_claude_code_to_tmp(tmp_path):
    out = tmp_path / "build"
    result = runner.invoke(app, ["render", "--tool", "claude-code", "--out", str(out)])
    assert result.exit_code == 0, result.stdout
    assert out.exists()
    # Should have written something
    files = list(out.rglob("*.md"))
    assert len(files) > 50  # 8 agents + 17 commands + 30 skills + extras


def test_score_canonical_skills():
    result = runner.invoke(app, ["score", "--path", "canonical/skills", "--fail-below", "80"])
    # Skills should all be above 80
    assert result.exit_code == 0, result.stdout


# discover CLI is exercised via test_discover_bench.py with fake benches —
# we deliberately avoid running it against the host repo here so the real
# discovery/data/*.json snapshot stays intact during test runs.


def test_sync_dry_run_claude_code():
    result = runner.invoke(app, ["sync", "--tool", "claude-code", "--dry-run"])
    assert result.exit_code == 0, result.stdout
