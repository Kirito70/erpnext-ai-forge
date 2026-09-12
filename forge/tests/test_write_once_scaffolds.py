"""A ledger row is not drift.

Forge writes `docs/harness/LEDGER-*.md` only when the file is absent and is
forbidden from touching it again — agents append build-history rows below the
header. The swap already knew that (`artifact_kind == "scaffold"` is in
`protected`), but the two readers of the manifest hash did not:

- `forge sync` reported the ledger as hand-edited on every single run and
  advised `forge adopt`, which for a ledger would mean folding build history
  into canonical.
- `forge validate` carried a DRIFT finding that no action could ever clear.

Neither could be resolved, and on a real bench the ledger was the *only* drift
finding — so a genuine one would have arrived as the second line of a warning
everyone had already learned to skip.
"""

from __future__ import annotations

from pathlib import Path

from forge.drift import check_drift
from forge.manifest import ManifestEntry, build_manifest, sha256_text, write_manifest
from forge.render import RenderedArtifact
from forge.sync import detect_hand_edits

HEADER = "# Build Ledger — Done\n\n| KEY | build_state |\n|-----|-------------|\n"
WITH_ROWS = HEADER + "| BRAIN-T9 | done |\n"


def _ledger(out: Path) -> RenderedArtifact:
    return RenderedArtifact(
        tool="claude-code",
        source_path=Path("canonical/harness/ledger.md"),
        output_path=out,
        content=HEADER,
        source_commit="abc123",
        source_version="1.0.0",
        artifact_id="ledger-done",
        artifact_kind="scaffold",
    )


def _seed(bench: Path, *, write_once: bool) -> Path:
    out_dir = bench / "docs" / "harness"
    out_dir.mkdir(parents=True)
    ledger = out_dir / "LEDGER-done.md"
    ledger.write_text(HEADER)
    write_manifest(
        out_dir,
        build_manifest(
            source_repo="erpnext-ai-forge",
            source_commit="abc123",
            adapter_name="claude-code",
            adapter_version="0.1.0",
            entries=[],
            outputs=[
                ManifestEntry(
                    path="LEDGER-done.md",
                    version="1.0.0",
                    sha256=sha256_text(HEADER),
                    write_once=write_once,
                )
            ],
            rendered_at="2026-08-17T00:00:00+00:00",
        ),
    )
    return ledger


def test_appended_rows_are_not_reported_as_hand_edits(tmp_path):
    bench = tmp_path / "bench"
    ledger = _seed(bench, write_once=True)
    ledger.write_text(WITH_ROWS)  # an agent appended a row

    assert detect_hand_edits([_ledger(ledger)], bench) == {}


def test_appended_rows_are_not_reported_as_drift(tmp_path):
    bench = tmp_path / "bench"
    ledger = _seed(bench, write_once=True)
    ledger.write_text(WITH_ROWS)

    report = check_drift(tmp_path, bench_root=bench)

    assert [f.detail for f in report.findings] == []
    assert report.files_checked == 1, "the entry should still be counted as checked"


def test_a_missing_ledger_is_still_reported(tmp_path):
    """Write-once means forge will not rewrite it — not that forge stops caring
    whether it is there at all."""
    bench = tmp_path / "bench"
    ledger = _seed(bench, write_once=True)
    ledger.unlink()

    report = check_drift(tmp_path, bench_root=bench)

    assert len(report.findings) == 1
    assert "missing" in report.findings[0].detail


def test_a_normal_output_still_reports_drift(tmp_path):
    """The exemption must be scoped to write-once rows, or it would disable the
    hand-edit guard for everything."""
    bench = tmp_path / "bench"
    ledger = _seed(bench, write_once=False)
    ledger.write_text(WITH_ROWS)

    report = check_drift(tmp_path, bench_root=bench)

    assert len(report.findings) == 1
    assert "sha256 mismatch" in report.findings[0].detail
