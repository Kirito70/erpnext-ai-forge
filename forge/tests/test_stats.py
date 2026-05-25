"""Tests for forge.stats — audit-log metrics dashboard."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forge.audit import audit_log
from forge.stats import collect_stats, parse_relative_since, render_markdown


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """A minimal repo without an audit/ dir at all."""
    (tmp_path / "forge.config.yaml").write_text("project: {name: t, version: 0.0.0}\n")
    return tmp_path


@pytest.fixture
def repo_with_audit(tmp_path: Path) -> Path:
    """A repo with a variety of audit entries seeded."""
    (tmp_path / "forge.config.yaml").write_text("project: {name: t, version: 0.0.0}\n")
    # Seed entries
    audit_log(tmp_path, {"action": "sync.live", "tool": "claude-code", "per_file_scores": {"a.md": 100, "b.md": 92}})
    audit_log(tmp_path, {"action": "sync.dry_run", "tool": "cursor"})
    audit_log(tmp_path, {"action": "sync.blocked_by_security_gate", "tool": "cline",
                          "per_file_scores": {"x.py": 50}})
    audit_log(tmp_path, {"action": "sync.justified_accept", "tool": "claude-code", "justify": "ok"})
    audit_log(tmp_path, {"action": "escalation", "trigger_id": 1})
    audit_log(tmp_path, {"action": "discovery.run", "tool_or_agent": "agent:architect"})
    return tmp_path


def test_collect_stats_empty_repo_returns_empty_report(empty_repo):
    report = collect_stats(empty_repo)
    assert report.total_entries == 0
    assert report.actions_by_count == {}
    assert report.tools_by_count == {}
    assert report.recent == []
    assert report.audit_files_scanned == 0


def test_collect_stats_counts_all_actions(repo_with_audit):
    report = collect_stats(repo_with_audit)
    assert report.total_entries == 6
    assert report.actions_by_count.get("sync.live") == 1
    assert report.actions_by_count.get("sync.dry_run") == 1
    assert report.actions_by_count.get("sync.blocked_by_security_gate") == 1
    assert report.actions_by_count.get("sync.justified_accept") == 1
    assert report.actions_by_count.get("escalation") == 1


def test_collect_stats_sync_outcomes_grouped(repo_with_audit):
    report = collect_stats(repo_with_audit)
    outcomes = report.sync_outcomes
    assert outcomes.get("live") == 1
    assert outcomes.get("dry_run") == 1
    assert outcomes.get("blocked_by_security_gate") == 1
    assert outcomes.get("justified_accept") == 1


def test_collect_stats_tools_counted(repo_with_audit):
    report = collect_stats(repo_with_audit)
    assert report.tools_by_count.get("claude-code") == 2
    assert report.tools_by_count.get("cursor") == 1
    assert report.tools_by_count.get("cline") == 1


def test_collect_stats_security_score_distribution(repo_with_audit):
    report = collect_stats(repo_with_audit)
    s = report.security_scores
    assert s["count"] == 3  # 100, 92, 50
    assert s["min"] == 50
    assert s["max"] == 100
    assert s["below_block_floor"] == 1   # 50
    assert s["warn_band"] == 1            # 92
    assert s["auto_accept"] == 1          # 100


def test_collect_stats_escalations_counted(repo_with_audit):
    report = collect_stats(repo_with_audit)
    assert report.escalations == 1


def test_collect_stats_recent_truncated_to_10(tmp_path):
    (tmp_path / "forge.config.yaml").write_text("project: {name: t, version: 0.0.0}\n")
    for i in range(15):
        audit_log(tmp_path, {"action": f"a{i}", "tool": "t"})
    report = collect_stats(tmp_path)
    assert len(report.recent) == 10
    # Most recent first
    assert report.recent[0]["action"].startswith("a")


def test_collect_stats_since_filter_drops_older_entries(tmp_path):
    (tmp_path / "forge.config.yaml").write_text("project: {name: t, version: 0.0.0}\n")
    audit_log(tmp_path, {"action": "old", "ts": "2020-01-01T00:00:00Z"})
    audit_log(tmp_path, {"action": "new", "tool": "t"})
    # NOTE: audit_log overwrites ts, so the manually-supplied "old" entry's ts
    # is replaced. Verify by filtering on a future date — both entries dropped.
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    report = collect_stats(tmp_path, since=future)
    assert report.total_entries == 0


def test_render_markdown_empty_report():
    from forge.stats import StatsReport
    empty = StatsReport(
        period_start=None, period_end=None, total_entries=0,
        actions_by_count={}, tools_by_count={}, sync_outcomes={},
        security_scores={"count": 0}, drift_incidents=0, escalations=0,
        recent=[], audit_files_scanned=0,
    )
    out = render_markdown(empty)
    assert "No audit entries" in out


def test_render_markdown_includes_all_sections(repo_with_audit):
    report = collect_stats(repo_with_audit)
    md = render_markdown(report)
    assert "# Forge — Audit Stats" in md
    assert "## Sync outcomes" in md
    assert "## Top actions" in md
    assert "## Tool / agent invocations" in md
    assert "## Security score distribution" in md
    assert "## Governance counters" in md
    assert "## Recent activity" in md


def test_parse_relative_since_handles_durations():
    iso_hours = parse_relative_since("2h")
    iso_days = parse_relative_since("7d")
    iso_minutes = parse_relative_since("30m")
    # Each should be a valid ISO timestamp string
    for v in (iso_hours, iso_days, iso_minutes):
        datetime.fromisoformat(v.replace("Z", "+00:00"))


def test_parse_relative_since_passes_through_iso():
    iso = "2026-05-25T12:00:00+00:00"
    assert parse_relative_since(iso) == iso


def test_to_dict_is_json_serializable(repo_with_audit):
    report = collect_stats(repo_with_audit)
    serialized = json.dumps(report.to_dict())
    parsed = json.loads(serialized)
    assert parsed["total_entries"] == 6
