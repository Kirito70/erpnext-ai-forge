"""The four paths that can destroy work the tool did not create.

`test_prune_orphans.py` covers the boundaries `find_orphans`/`prune_orphans`
already got right. These are the ones that were missing, each found by a review
of PR #1 and each reproduced before it was fixed:

1. A hand-edited file lost its manifest row on the sync that protected it, so
   the sync after that saw an unmanaged file and overwrote it. Protection
   expired after exactly one cycle.
2. `..` in a rendered `output:` escaped both the staging root and the bench.
3. `apps remove --prune` and `prune_harness` deleted without the hash check
   `prune_orphans` applies, so a hand-edited file went with them.
4. An unreadable manifest read as "never synced", which is the same green light
   to overwrite — a schema bump silently disarmed the hand-edit guard.

The bench is not a git repository. Every failure here is unrecoverable, which
is why these assert on the file still being there, not on a return value.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.manifest import (
    ManifestEntry,
    build_manifest,
    merge_manifest,
    read_manifest,
    sha256_text,
    write_manifest,
)
from forge.render import RenderedArtifact
from forge.sync import (
    _assert_resolved_output_path,
    _carry_forward_hand_edited_rows,
    detect_hand_edits,
    prune_harness,
)

TOOL = "claude-code"


def _artifact(out: Path, content: str, kind: str = "skill") -> RenderedArtifact:
    return RenderedArtifact(
        tool=TOOL,
        source_path=Path("canonical/skills/x.md"),
        output_path=out,
        content=content,
        source_commit="abc123",
        source_version="1.0.0",
        artifact_id="x",
        artifact_kind=kind,
    )


def _manifest(outputs: list[ManifestEntry]) -> object:
    return build_manifest(
        source_repo="erpnext-ai-forge",
        source_commit="abc123",
        adapter_name=TOOL,
        adapter_version="0.1.0",
        entries=[
            ManifestEntry(
                path="canonical/skills/x.md",
                version="1.0.0",
                sha256=sha256_text("src"),
                adapter=TOOL,
            )
        ],
        outputs=outputs,
        rendered_at="2026-01-01T00:00:00Z",
    )


def _row(name: str, content: str) -> ManifestEntry:
    return ManifestEntry(
        path=name, version="1.0.0", sha256=sha256_text(content), adapter=TOOL
    )


# ---------------------------------------------------------------------------
# 1. hand-edit protection must not expire
# ---------------------------------------------------------------------------


def test_hand_edited_row_survives_the_manifest_rewrite(tmp_path):
    """The row is the protection. Losing it is losing the file.

    Sync 2 excludes the hand-edited file from `outputs` and `merge_manifest`
    drops the owning adapter's rows wholesale, so without a carry-forward the
    row is gone and sync 3 sees a file forge has no record of — which it adopts
    and overwrites.
    """
    out_dir = tmp_path / ".claude"
    out_dir.mkdir()
    edited = out_dir / "CLAUDE.md"
    edited.write_text("a human wrote this")
    sibling = out_dir / "other.md"
    sibling.write_text("v2")

    previous = _manifest([_row("CLAUDE.md", "what forge wrote"), _row("other.md", "v1")])
    write_manifest(out_dir, previous)

    # Sync 2: CLAUDE.md is hand-edited, so it is excluded from `outputs`;
    # the sibling still renders, which is what drags this dir into the rewrite.
    incoming = _manifest([_row("other.md", "v2")])
    merged = merge_manifest(read_manifest(out_dir), incoming)
    _carry_forward_hand_edited_rows(merged, previous, {edited}, out_dir)
    write_manifest(out_dir, merged)

    # Sync 3 must still see a hand edit.
    still = detect_hand_edits([_artifact(edited, "what forge wrote")], tmp_path)
    assert edited in still, "protection expired — sync 3 would overwrite the edit"


def test_carry_forward_preserves_the_old_hash_not_the_current_one(tmp_path):
    """Recording the file's CURRENT hash would make it match on the next sync
    and stop being reported — protection that erases itself by succeeding."""
    out_dir = tmp_path / ".claude"
    out_dir.mkdir()
    edited = out_dir / "CLAUDE.md"
    edited.write_text("edited by hand")

    previous = _manifest([_row("CLAUDE.md", "what forge wrote")])
    merged = merge_manifest(None, _manifest([]))
    _carry_forward_hand_edited_rows(merged, previous, {edited}, out_dir)

    row = next(e for e in merged.outputs if e.path == "CLAUDE.md")
    assert row.sha256 == sha256_text("what forge wrote")
    assert row.sha256 != sha256_text("edited by hand")


def test_carry_forward_without_a_previous_manifest_is_a_noop(tmp_path):
    merged = merge_manifest(None, _manifest([]))
    _carry_forward_hand_edited_rows(merged, None, {tmp_path / "x.md"}, tmp_path)
    assert merged.outputs == []


# ---------------------------------------------------------------------------
# 2. `..` must not escape the bench
# ---------------------------------------------------------------------------


def test_output_path_with_dotdot_is_refused(tmp_path):
    """`Path.relative_to` prefix-matches without normalising, so `..` survives
    into the staged path and the write lands outside staging AND the bench."""
    evil = tmp_path / "bench" / "apps" / ".." / ".." / "OUTSIDE.txt"
    with pytest.raises(ValueError, match=r"\.\."):
        _assert_resolved_output_path(_artifact(evil, "x"))


def test_a_normal_absolute_output_path_still_passes(tmp_path):
    """The guard must not reject the ordinary case it sits in front of."""
    _assert_resolved_output_path(_artifact(tmp_path / "bench" / "CLAUDE.md", "x"))


# ---------------------------------------------------------------------------
# 3. prune paths need the same hash check prune_orphans applies
# ---------------------------------------------------------------------------


def test_prune_harness_keeps_a_hand_edited_script(tmp_path):
    """`prune_orphans` reports-not-removes a file whose content no longer
    matches its row. A prune must not be the back door around that."""
    harness = tmp_path / "scripts" / "harness"
    harness.mkdir(parents=True)
    edited = harness / "gone.sh"
    edited.write_text("#!/bin/sh\n# a human fixed this\n")
    write_manifest(harness, _manifest([_row("gone.sh", "#!/bin/sh\n# original\n")]))

    removed = prune_harness([], tmp_path, harness)

    assert edited.is_file(), "a hand-edited script was deleted"
    assert removed == []


def test_prune_harness_still_removes_an_untouched_script(tmp_path):
    harness = tmp_path / "scripts" / "harness"
    harness.mkdir(parents=True)
    stale = harness / "gone.sh"
    stale.write_text("#!/bin/sh\n# original\n")
    write_manifest(harness, _manifest([_row("gone.sh", "#!/bin/sh\n# original\n")]))

    removed = prune_harness([], tmp_path, harness)

    assert not stale.exists()
    assert removed == [stale]


def test_prune_harness_leaves_a_file_forge_never_wrote(tmp_path):
    """No manifest row means it is not forge's to delete."""
    harness = tmp_path / "scripts" / "harness"
    harness.mkdir(parents=True)
    mine = harness / "my-own.sh"
    mine.write_text("mine")
    write_manifest(harness, _manifest([]))

    assert prune_harness([], tmp_path, harness) == []
    assert mine.is_file()


# ---------------------------------------------------------------------------
# 4. an unreadable manifest is not "never synced"
# ---------------------------------------------------------------------------


def test_a_manifest_from_a_newer_forge_protects_rather_than_adopts(tmp_path):
    """`drift.py` already reports this state as a finding. The write path read
    it as a green light, so a schema bump on one machine disarmed the guard on
    another — for a whole directory at once."""
    out_dir = tmp_path / ".claude"
    out_dir.mkdir()
    managed = out_dir / "CLAUDE.md"
    managed.write_text("a human edited this")

    manifest = _manifest([_row("CLAUDE.md", "what forge wrote")])
    write_manifest(out_dir, manifest)
    # A newer forge wrote a schema this binary does not understand.
    path = out_dir / ".forge-manifest.json"
    path.write_text(path.read_text().replace('"schema_version": 2', '"schema_version": 99'))
    assert read_manifest(out_dir) is None

    edits = detect_hand_edits([_artifact(managed, "new render")], tmp_path)

    assert managed in edits, "a manifest from a newer forge was read as no manifest"


def test_an_older_schema_is_still_adopted(tmp_path):
    """The other side of the line, and the reason this is not just "unreadable
    means protect": a v1 manifest is the documented upgrade path. Its rows are
    genuinely gone, and protecting those files would bury the first sync after
    an upgrade in conflicts that are not real."""
    out_dir = tmp_path / ".claude"
    out_dir.mkdir()
    managed = out_dir / "CLAUDE.md"
    managed.write_text("whatever")
    (out_dir / ".forge-manifest.json").write_text('{"schema_version": 1}')

    assert detect_hand_edits([_artifact(managed, "new render")], tmp_path) == {}


def test_an_unparseable_manifest_protects(tmp_path):
    """Truncated mid-write, or corrupted. Not evidence that nothing is managed."""
    out_dir = tmp_path / ".claude"
    out_dir.mkdir()
    managed = out_dir / "CLAUDE.md"
    managed.write_text("mine")
    (out_dir / ".forge-manifest.json").write_text('{"schema_version": 2, "outp')

    assert managed in detect_hand_edits([_artifact(managed, "new render")], tmp_path)


def test_a_directory_with_no_manifest_is_still_adopted(tmp_path):
    """The other half of the distinction: never-synced really does mean adopt,
    which is how per-app files come under management without a conflict."""
    out_dir = tmp_path / ".claude"
    out_dir.mkdir()
    unmanaged = out_dir / "CLAUDE.md"
    unmanaged.write_text("pre-existing")

    assert detect_hand_edits([_artifact(unmanaged, "new render")], tmp_path) == {}
