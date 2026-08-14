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
    read_manifest,
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
    bench, manifest_dir, bench_file = _make_fake_bench_with_manifest(
        tmp_path, source_commit=head
    )
    bench_file.unlink()

    report = check_drift(repo_root, bench_root=bench)
    assert report.has_drift
    assert any("missing" in f.detail for f in report.findings)


def test_stale_manifest_flagged(repo_root, tmp_path):
    """A canonical source edited after the sync makes the bench copy stale.

    Content-based: the manifest records the source's hash at render time, so
    this fires only when the source actually differs. The earlier commit-based
    forms fired on unrelated commits and reported staleness for files nobody
    had touched.
    """
    bench, manifest_dir, _ = _make_fake_bench_with_manifest(tmp_path)

    # Point the row at a real file in the forge repo, recording a hash that
    # deliberately does not match its current content.
    manifest = read_manifest(manifest_dir)
    manifest.source_files[0].path = "forge.config.yaml"
    manifest.source_files[0].source_sha256 = sha256_text("not what is on disk")
    write_manifest(manifest_dir, manifest)

    report = check_drift(repo_root, bench_root=bench)
    assert report.has_staleness
    assert any("changed since this was rendered" in f.detail for f in report.findings)


def test_unchanged_source_is_not_stale(repo_root, tmp_path):
    """The case the old commit-based checks got wrong: nothing changed."""
    bench, manifest_dir, _ = _make_fake_bench_with_manifest(tmp_path)

    manifest = read_manifest(manifest_dir)
    manifest.source_files[0].path = "forge.config.yaml"
    manifest.source_files[0].source_sha256 = sha256_text(
        (repo_root / "forge.config.yaml").read_text()
    )
    write_manifest(manifest_dir, manifest)

    report = check_drift(repo_root, bench_root=bench)
    assert not report.has_staleness


def test_row_without_source_hash_is_never_stale(repo_root, tmp_path):
    """Manifests written before source_sha256 existed opt out, silently."""
    bench, _, _ = _make_fake_bench_with_manifest(tmp_path)
    report = check_drift(repo_root, bench_root=bench)
    assert not report.has_staleness


def test_staging_dir_skipped(repo_root, tmp_path, monkeypatch):
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
    bench, _, bench_file = _make_fake_bench_with_manifest(tmp_path, source_commit="head")
    bench_file.write_text("drifted content")
    report = check_drift(repo_root, bench_root=bench)
    rendered = render_drift_report(report)
    assert "Drift" in rendered
    assert "architect.md" in rendered


def test_output_with_different_extension_is_not_reported_missing(repo_root, tmp_path):
    """A tool renders canonical/tools/x.yaml -> x.md. Both are correct.

    The old check reconstructed the on-disk name as
    `manifest_dir / basename(source_path)`, i.e. looked for `x.yaml` in a
    directory that only ever holds `x.md`, and reported it gone. That was every
    tool in every adapter — 48 findings on the Novizna bench, none of them a
    real edit.
    """
    bench = tmp_path / "fake-bench"
    (bench / "apps").mkdir(parents=True)
    manifest_dir = bench / ".claude" / "tools"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "mariadb-query.md").write_text("rendered tool doc")

    manifest = build_manifest(
        source_repo="erpnext-ai-forge",
        source_commit="abc123def",
        adapter_name="claude-code",
        adapter_version="0.1.0",
        entries=[ManifestEntry(
            path="canonical/tools/mariadb-query.yaml",
            version="1.0.0",
            sha256=sha256_text("rendered tool doc"),
        )],
        outputs=[ManifestEntry(
            path="mariadb-query.md",
            version="1.0.0",
            sha256=sha256_text("rendered tool doc"),
        )],
    )
    write_manifest(manifest_dir, manifest)

    report = check_drift(repo_root, bench_root=bench)
    assert not report.has_drift, [f.detail for f in report.findings]
