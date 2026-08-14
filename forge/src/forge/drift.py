"""Manifest-based drift detection.

For each `.forge-manifest.json` found in the bench, compare:

  1. The current sha256 of every file the manifest lists, against the manifest's
     recorded sha256. Mismatch = drift (hand-edited or replaced).
  2. The manifest's `source_commit` against the newest commit touching the
     sources it was rendered from. Behind = stale sync (re-run `forge sync`).

     Deliberately not a comparison against repo HEAD. Provenance is recorded
     per source file, so a manifest legitimately sits on an older commit while
     its own sources are unchanged; measuring against HEAD marked every managed
     app stale the moment any unrelated forge commit landed, and a report that
     is mostly noise is a report people stop reading.

Drift in (1) is louder than (2). Both feed into `forge validate --check-drift`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from forge.loader import file_last_commit, load_forge_config
from forge.manifest import MANIFEST_FILENAME, ManifestEntry, read_manifest, sha256_text


def _newest_source_commit(
    repo_root: Path, entries: Iterable[ManifestEntry]
) -> str | None:
    """The most recent commit touching any of `entries`' source paths.

    Returns None when none of them are tracked, in which case there is nothing
    to compare and the manifest is left alone rather than reported stale.
    """
    newest: str | None = None
    newest_date = ""
    for entry in entries:
        found = file_last_commit(repo_root, entry.path)
        if found is None:
            continue
        sha, date = found
        if date > newest_date:
            newest, newest_date = sha, date
    return newest


@dataclass
class DriftFinding:
    severity: str           # "DRIFT" (file changed) | "STALE" (source_commit behind)
    manifest_path: Path     # path to the .forge-manifest.json
    file_path: Path | None  # specific file that drifted (None for STALE)
    detail: str             # human-readable description


@dataclass
class DriftReport:
    findings: list[DriftFinding] = field(default_factory=list)
    manifests_checked: int = 0
    files_checked: int = 0

    @property
    def has_drift(self) -> bool:
        return any(f.severity == "DRIFT" for f in self.findings)

    @property
    def has_staleness(self) -> bool:
        return any(f.severity == "STALE" for f in self.findings)


def _resolve_bench_root(repo_root: Path) -> Path:
    cfg = load_forge_config(repo_root)
    bench_str = cfg["bench"]["path"].replace(
        "{{ env.FORGE_BENCH_PATH }}", os.environ.get("FORGE_BENCH_PATH", "")
    )
    return Path(bench_str)


def _iter_manifests(bench_root: Path) -> Iterable[Path]:
    """Yield every .forge-manifest.json in the bench (recursive)."""
    if not bench_root.is_dir():
        return
    for path in bench_root.rglob(MANIFEST_FILENAME):
        # Skip the staging dir's manifests — they're transient
        if ".forge-staging" in path.parts:
            continue
        yield path


def check_drift(
    repo_root: Path,
    bench_root: Path | None = None,
) -> DriftReport:
    """Walk every manifest in the bench and report drift + staleness."""
    bench_root = bench_root or _resolve_bench_root(repo_root)
    report = DriftReport()
    if not bench_root.is_dir():
        return report

    # Repo HEAD is deliberately no longer consulted: staleness is now judged
    # per manifest against its own sources (see below), not against whatever
    # the forge repo happens to be pointing at.

    for manifest_path in _iter_manifests(bench_root):
        report.manifests_checked += 1
        manifest_dir = manifest_path.parent
        manifest = read_manifest(manifest_dir)
        if manifest is None:
            report.findings.append(
                DriftFinding(
                    severity="DRIFT",
                    manifest_path=manifest_path,
                    file_path=None,
                    detail="Manifest unreadable or schema mismatch",
                )
            )
            continue

        # 1) Is the manifest's source_commit still the last commit that touched
        #    the sources it was rendered from?
        #
        #    NOT a comparison against repo HEAD. Provenance is per source file,
        #    so a manifest legitimately records an older commit when its own
        #    sources have not moved — comparing to HEAD marked every managed app
        #    STALE the moment any unrelated forge commit landed, which is noise
        #    that trains people to ignore the report.
        if manifest.source_commit and manifest.source_files:
            newest = _newest_source_commit(repo_root, manifest.source_files)
            if newest and newest != manifest.source_commit:
                report.findings.append(
                    DriftFinding(
                        severity="STALE",
                        manifest_path=manifest_path,
                        file_path=None,
                        detail=(
                            f"rendered from {manifest.source_commit[:7]}, but its "
                            f"sources have changed since ({newest[:7]}) — re-run "
                            f"`forge sync`"
                        ),
                    )
                )

        # 2) For each manifest entry, verify the rendered bench file still
        #    matches the recorded sha256. The manifest stores entries by
        #    canonical-source path, but the bench file lives in manifest_dir.
        for entry in manifest.source_files:
            report.files_checked += 1
            # The synced output lives in manifest_dir/<basename>
            # (each artifact's bench filename is preserved relative to the
            # manifest's parent dir). For agents, this is e.g.
            # .claude/agents/architect.md alongside the manifest.
            bench_file = manifest_dir / Path(entry.path).name
            if not bench_file.is_file():
                # Try a few alternative suffixes (e.g. command file)
                alt = manifest_dir / Path(entry.path).stem
                if alt.is_file():
                    bench_file = alt
                else:
                    report.findings.append(
                        DriftFinding(
                            severity="DRIFT",
                            manifest_path=manifest_path,
                            file_path=bench_file,
                            detail=f"missing — manifest lists {entry.path} but file is gone",
                        )
                    )
                    continue

            actual_sha = sha256_text(bench_file.read_text(errors="replace"))
            if actual_sha != entry.sha256:
                report.findings.append(
                    DriftFinding(
                        severity="DRIFT",
                        manifest_path=manifest_path,
                        file_path=bench_file,
                        detail=(
                            f"sha256 mismatch (recorded {entry.sha256[:8]}…, "
                            f"actual {actual_sha[:8]}…) — likely hand-edited"
                        ),
                    )
                )

    return report


def render_drift_report(report: DriftReport) -> str:
    """Render a terse human-readable report."""
    if not report.findings:
        return (
            f"✓ No drift across {report.manifests_checked} manifest(s) "
            f"and {report.files_checked} file(s)."
        )
    lines: list[str] = []
    drift = [f for f in report.findings if f.severity == "DRIFT"]
    stale = [f for f in report.findings if f.severity == "STALE"]
    if drift:
        lines.append(f"Drift ({len(drift)} file(s)):")
        for f in drift:
            target = f.file_path.name if f.file_path else f.manifest_path.parent.name
            lines.append(f"  ✗ {target}: {f.detail}")
    if stale:
        lines.append(f"Staleness ({len(stale)} manifest(s) behind HEAD):")
        for f in stale:
            lines.append(f"  ! {f.manifest_path.parent.name}: {f.detail}")
    lines.append(
        f"\nChecked {report.manifests_checked} manifest(s), {report.files_checked} file(s)."
    )
    return "\n".join(lines)
