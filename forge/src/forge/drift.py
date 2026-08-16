"""Manifest-based drift detection.

For each `.forge-manifest.json` found in the bench, compare:

  1. The current sha256 of every file the manifest lists, against the manifest's
     recorded sha256. Mismatch = drift (hand-edited or replaced).
  2. The current sha256 of every canonical source, against the `source_sha256`
     recorded when it was rendered. Mismatch = stale sync (re-run `forge sync`).

     Both checks are content comparisons. Staleness was previously inferred
     from git commits — first the manifest's commit vs repo HEAD, then vs the
     newest source commit — and both were proxies that fired constantly on
     unchanged files. A report that is mostly noise is one people stop reading,
     which costs the hand-edit warning its meaning too.

Drift in (1) is louder than (2). Both feed into `forge validate --check-drift`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from forge.loader import load_forge_config
from forge.manifest import MANIFEST_FILENAME, read_manifest, sha256_text


@dataclass
class DriftFinding:
    severity: str           # "DRIFT" (output edited) | "STALE" (source changed)
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

    # Neither check consults git: both compare recorded hashes to what is on
    # disk now, so a finding always means content actually differs.

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

        # 1) STALE — has a canonical source changed since this was rendered?
        #
        #    Compared by CONTENT, per source file. Rows written before
        #    `source_sha256` existed, or whose source cannot be read, are
        #    skipped: no record means no judgement, never a guess.
        for entry in manifest.source_files:
            if not entry.source_sha256:
                continue
            source_file = repo_root / entry.path
            if not source_file.is_file():
                continue
            current = sha256_text(source_file.read_text(errors="replace"))
            if current != entry.source_sha256:
                report.findings.append(
                    DriftFinding(
                        severity="STALE",
                        manifest_path=manifest_path,
                        file_path=source_file,
                        detail=(
                            f"{entry.path} changed since this was rendered — "
                            f"re-run `forge sync`"
                        ),
                    )
                )

        # 2) DRIFT — has a file forge wrote been edited or removed?
        #
        #    Driven by `outputs`, whose `path` is already relative to this
        #    directory and whose sha256 is the file forge actually wrote.
        #
        #    This used to walk `source_files` and reconstruct the on-disk name
        #    as `manifest_dir / basename(source_path)`. That only holds when
        #    source and output share a basename — true for agents and skills
        #    (.md -> .md), false for every tool (canonical/tools/x.yaml -> x.md)
        #    and for aggregates whose output is not a sibling under that name.
        #    It reported 48 files "gone" that were all present and correct.
        #
        #    An EMPTY `outputs` is an answer, not a gap. A manifest whose only
        #    contribution is a settings fragment records sources and no outputs
        #    by design — forge merges into settings.json, it does not own the
        #    file. Reconstructing rows from `source_files` in that case brought
        #    the basename bug back for exactly those manifests: `.claude/`
        #    reported a permanent DRIFT for `harness.yaml`, a canonical source
        #    path checked as though it were a bench output. A pre-`outputs`
        #    manifest cannot reach here anyway — `read_manifest` returns None on
        #    a schema mismatch.
        for entry in manifest.outputs:
            report.files_checked += 1
            bench_file = manifest_dir / entry.path
            if not bench_file.is_file():
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
        lines.append(f"Staleness ({len(stale)} source(s) changed since sync):")
        for f in stale:
            lines.append(f"  ! {f.manifest_path.parent.name}: {f.detail}")
    lines.append(
        f"\nChecked {report.manifests_checked} manifest(s), {report.files_checked} file(s)."
    )
    return "\n".join(lines)
