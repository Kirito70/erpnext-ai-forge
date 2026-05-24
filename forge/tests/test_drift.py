"""Tests for forge.drift — manifest-based drift detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.drift import check_drift, render_drift_report
from forge.manifest import (
    ManifestEntry,
    build_manifest,
    sha256_text,
    write_manifest,
)


def _make_fake_bench_with_manifest(
    tmp_path: Path,
    *,
    source_commit: str = "abc123def",
    file_content: str = "hello from agent",
    file_name: str = "architect.md",
) -> tuple[Path, Path, Path]:
    """Build a fake bench with one synced file + manifest.

    Returns (bench_root, manifest_dir, bench_file).
    """
    bench = tmp_path / "fake-bench"
    bench.mkdir()
    (bench / "apps").mkdir()  # required by resolver

    manifest_dir = bench / ".claude" / "agents"
    manifest_dir.mkdir(parents=True)
    bench_file = manifest_dir / file_name
    bench_file.write_text(file_content)

    entry = ManifestEntry(
        path=f"canonical/agents/{file_name}",
        version="1.0.0",
        sha256=sha256_text(file_content),
    )
    manifest = build_manifest(
        source_repo="erpnext-ai-forge",
        source_commit=source_commit,
        adapter_name="claude-code",
        adapter_version="0.1.0",
        entries=[entry],
    )
    write_manifest(manifest_dir, manifest)
    return bench, manifest_dir, bench_file


def test_clean_bench_no_drift(repo_root, tmp_path, monkeypatch):
    head = "abc123def"
    monkeypatch.setattr("forge.drift.repo_head_commit", lambda _: head)
    bench, manifest_dir, _ = _make_fake_bench_with_manifest(
        tmp_path, source_commit=head
    )
    report = check_drift(repo_root, bench_root=bench)
    assert report.manifests_checked == 1
    assert report.files_checked == 1
    assert not report.has_drift
    assert not report.has_staleness
    assert "No drift" in render_drift_report(report)


def test_hand_edited_file_flagged_as_drift(repo_root, tmp_path, monkeypatch):
    head = "abc123def"
    monkeypatch.setattr("forge.drift.repo_head_commit", lambda _: head)
    bench, _, bench_file = _make_fake_bench_with_manifest(
        tmp_path, source_commit=head
    )
    # User hand-edits the synced file
    bench_file.write_text("hello — hand-edited by developer")

    report = check_drift(repo_root, bench_root=bench)
    assert report.has_drift
    assert any("sha256 mismatch" in f.detail for f in report.findings)


def test_missing_file_flagged_as_drift(repo_root, tmp_path, monkeypatch):
    head = "abc123def"
    monkeypatch.setattr("forge.drift.repo_head_commit", lambda _: head)
    bench, manifest_dir, bench_file = _make_fake_bench_with_manifest(
        tmp_path, source_commit=head
    )
    bench_file.unlink()

    report = check_drift(repo_root, bench_root=bench)
    assert report.has_drift
    assert any("missing" in f.detail for f in report.findings)


def test_stale_manifest_flagged(repo_root, tmp_path, monkeypatch):
    monkeypatch.setattr("forge.drift.repo_head_commit", lambda _: "new-head-7890")
    bench, _, _ = _make_fake_bench_with_manifest(
        tmp_path, source_commit="old-commit-12345"
    )
    report = check_drift(repo_root, bench_root=bench)
    assert report.has_staleness
    assert any(
        "manifest source_commit=old-com" in f.detail for f in report.findings
    )


def test_staging_dir_skipped(repo_root, tmp_path, monkeypatch):
    monkeypatch.setattr("forge.drift.repo_head_commit", lambda _: "head")
    bench, _, _ = _make_fake_bench_with_manifest(tmp_path, source_commit="head")
    # Put another manifest under .forge-staging/ — should be ignored
    staging = bench / ".forge-staging" / "claude-code" / ".claude" / "agents"
    staging.mkdir(parents=True)
    (staging / "x.md").write_text("staged")
    entry = ManifestEntry(path="canonical/agents/x.md", version="1.0.0", sha256=sha256_text("staged"))
    write_manifest(staging, build_manifest(
        source_repo="erpnext-ai-forge",
        source_commit="head",
        adapter_name="claude-code",
        adapter_version="0.1.0",
        entries=[entry],
    ))
    report = check_drift(repo_root, bench_root=bench)
    # Only the non-staging manifest counts
    assert report.manifests_checked == 1


def test_drift_render_lists_findings(repo_root, tmp_path, monkeypatch):
    monkeypatch.setattr("forge.drift.repo_head_commit", lambda _: "head")
    bench, _, bench_file = _make_fake_bench_with_manifest(tmp_path, source_commit="head")
    bench_file.write_text("drifted content")
    report = check_drift(repo_root, bench_root=bench)
    rendered = render_drift_report(report)
    assert "Drift" in rendered
    assert "architect.md" in rendered
