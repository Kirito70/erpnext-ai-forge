"""Smoke tests — every CLI command parses its arguments and exits.

These run against the real canonical layer (sanity check that wiring is intact).
Detailed behavior assertions live in test_cli_integration.py.
"""

from __future__ import annotations

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


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "forge" in result.stdout


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_discover_runs() -> None:
    result = runner.invoke(app, ["discover"])
    assert result.exit_code == 0


def test_validate_runs() -> None:
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0


def test_render_requires_tool() -> None:
    result = runner.invoke(app, ["render"])
    assert result.exit_code != 0


def test_render_with_tool(tmp_path) -> None:
    out = tmp_path / "build"
    result = runner.invoke(app, ["render", "--tool", "claude-code", "--out", str(out)])
    assert result.exit_code == 0


def test_sync_dry_run() -> None:
    result = runner.invoke(app, ["sync", "--all", "--dry-run"])
    assert result.exit_code == 0


def test_score_default() -> None:
    # Score against canonical (excluding policies which by design discuss upstream)
    result = runner.invoke(app, ["score", "--path", "canonical/skills"])
    assert result.exit_code == 0


def test_audit_tail() -> None:
    result = runner.invoke(app, ["audit", "tail", "-n", "10"])
    assert result.exit_code == 0


def test_commit_message() -> None:
    result = runner.invoke(app, ["commit", "-m", "scaffold initial repo"])
    assert result.exit_code == 0


def test_new_command_stub_returns_zero() -> None:
    result = runner.invoke(app, ["new", "skill", "test-skill", "--domain", "frappe-core"])
    assert result.exit_code == 0
