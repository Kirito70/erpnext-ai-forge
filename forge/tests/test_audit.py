"""Tests for forge.audit — JSONL append + tail."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from forge.audit import audit_log, tail


@pytest.fixture
def tmp_repo(tmp_path):
    """A temp dir resembling a repo root (only audit/ is exercised)."""
    (tmp_path / "audit").mkdir()
    return tmp_path


def test_audit_log_appends_jsonl(tmp_repo):
    audit_log(tmp_repo, {"action": "sync.dry_run", "tool": "claude-code"})
    audit_log(tmp_repo, {"action": "sync.live", "tool": "claude-code", "files_count": 12})

    # Find the written file
    files = list((tmp_repo / "audit").rglob("forge-audit.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().strip().splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["action"] == "sync.dry_run"
    assert parsed[1]["files_count"] == 12
    # Enriched fields present
    for entry in parsed:
        assert "ts" in entry
        assert "session_id" in entry
        assert "host" in entry


def test_audit_log_creates_year_month_dir(tmp_repo):
    audit_log(tmp_repo, {"action": "x"})
    now = datetime.now(timezone.utc)
    expected = tmp_repo / "audit" / f"{now.year:04d}" / f"{now.month:02d}" / "forge-audit.jsonl"
    assert expected.is_file()


def test_tail_returns_zero_when_empty(tmp_repo, capsys):
    code = tail(tmp_repo, n=10)
    assert code == 0
    out = capsys.readouterr().out
    assert "No audit entries" in out


def test_tail_respects_n_limit(tmp_repo, capsys):
    for i in range(5):
        audit_log(tmp_repo, {"action": f"a{i}", "tool_or_agent": "test"})
    code = tail(tmp_repo, n=2)
    assert code == 0
    out = capsys.readouterr().out
    # Should show 2 entries (rendered in table)
    assert "a3" in out or "a4" in out
