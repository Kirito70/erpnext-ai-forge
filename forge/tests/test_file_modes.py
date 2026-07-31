"""File modes survive render → staging → atomic swap.

The harness hook scripts are the first artifacts forge writes that something
*executes*. Before this, every output was Markdown or JSON, so nothing in the
pipeline carried a permission bit and a rendered `gates.sh` would have landed
0644 and failed at run time with "permission denied" — silently, because a hook
that cannot start looks a lot like a hook that found nothing to complain about.
"""

from __future__ import annotations

import stat
from pathlib import Path

from forge.render import RenderedArtifact
from forge.sync import _stage_artifacts, _swap_into_bench


def _artifact(tmp_path: Path, name: str, mode: int | None) -> RenderedArtifact:
    bench = tmp_path / "bench"
    (bench / ".claude").mkdir(parents=True, exist_ok=True)
    return RenderedArtifact(
        tool="claude-code",
        source_path=tmp_path / "canonical" / "harness" / f"{name}.j2",
        output_path=bench / "scripts" / "harness" / name,
        content="#!/usr/bin/env bash\nexit 0\n",
        source_commit="abc123",
        source_version="1.0.0",
        artifact_id=name.removesuffix(".sh"),
        artifact_kind="harness-script",
        mode=mode,
    )


def _is_executable(p: Path) -> bool:
    return bool(p.stat().st_mode & stat.S_IXUSR)


def test_mode_defaults_to_none():
    """Markdown artifacts must not start pinning modes just because the field
    now exists — None means "leave the umask alone"."""
    a = RenderedArtifact(
        tool="claude-code",
        source_path=Path("canonical/agents/architect.md"),
        output_path=Path("/tmp/CLAUDE.md"),
        content="# hi",
        source_commit=None,
        source_version="1.0.0",
        artifact_id="architect",
        artifact_kind="agent",
    )
    assert a.mode is None


def test_staged_file_is_executable(tmp_path):
    art = _artifact(tmp_path, "gates.sh", 0o755)
    staging = _stage_artifacts([art], tmp_path / "bench" / ".forge-staging", "claude-code")
    staged = staging / "scripts" / "harness" / "gates.sh"
    assert staged.is_file()
    assert _is_executable(staged), "ls -l on the staging dir must tell the truth"


def test_mode_survives_the_swap(tmp_path):
    art = _artifact(tmp_path, "gates.sh", 0o755)
    bench = tmp_path / "bench"
    staging = _stage_artifacts([art], bench / ".forge-staging", "claude-code")
    written = _swap_into_bench(staging, bench)

    landed = bench / "scripts" / "harness" / "gates.sh"
    assert landed in written
    assert landed.stat().st_mode & 0o777 == 0o755


def test_unset_mode_leaves_file_non_executable(tmp_path):
    art = _artifact(tmp_path, "notes.md", None)
    bench = tmp_path / "bench"
    staging = _stage_artifacts([art], bench / ".forge-staging", "claude-code")
    _swap_into_bench(staging, bench)
    assert not _is_executable(bench / "scripts" / "harness" / "notes.md")


def test_no_tmp_file_is_left_behind(tmp_path):
    """The swap renames a temp file into place. A leftover `.tmp` would be both
    litter and, for an executable, a second copy of a live hook."""
    art = _artifact(tmp_path, "gates.sh", 0o755)
    bench = tmp_path / "bench"
    staging = _stage_artifacts([art], bench / ".forge-staging", "claude-code")
    _swap_into_bench(staging, bench)
    assert list((bench / "scripts" / "harness").glob("*.tmp")) == []
