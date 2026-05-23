"""Smoke tests — every CLI command parses its arguments and exits 0.

Phase 0 baseline: ensure the skeleton doesn't break before Phase 2 fills in
real behavior.
"""

from __future__ import annotations

from typer.testing import CliRunner

from forge.cli import app

runner = CliRunner()


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
    assert "not yet implemented" in result.stdout


def test_validate_runs() -> None:
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0


def test_render_requires_tool() -> None:
    result = runner.invoke(app, ["render"])
    assert result.exit_code != 0


def test_render_with_tool() -> None:
    result = runner.invoke(app, ["render", "--tool", "claude-code"])
    assert result.exit_code == 0


def test_sync_dry_run() -> None:
    result = runner.invoke(app, ["sync", "--all", "--dry-run"])
    assert result.exit_code == 0


def test_score_default() -> None:
    result = runner.invoke(app, ["score"])
    assert result.exit_code == 0


def test_audit_tail() -> None:
    result = runner.invoke(app, ["audit", "tail", "-n", "10"])
    assert result.exit_code == 0


def test_test_command() -> None:
    result = runner.invoke(app, ["test"])
    assert result.exit_code == 0


def test_commit_message() -> None:
    result = runner.invoke(app, ["commit", "-m", "scaffold initial repo"])
    assert result.exit_code == 0
