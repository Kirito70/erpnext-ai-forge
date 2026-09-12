"""Pruning outputs a changed `output:` left behind.

The swap never deletes, so relocating an artifact writes the new path and
leaves the old one — both look generated and nothing says which is live.
Moving 33 skills to `<id>/SKILL.md` once left the bench holding 66 skill
files, 10 stale directories and 43 stale manifests.

Every test here is about a boundary on deletion. The failure mode is not "an
orphan survived" — it is "a file that was not forge's got removed", which is
unrecoverable.
"""

from __future__ import annotations

from pathlib import Path

from forge.manifest import (
    ManifestEntry,
    build_manifest,
    read_manifest,
    sha256_text,
    write_manifest,
)
from forge.render import RenderedArtifact
from forge.sync import find_orphans, prune_orphans


def _artifact(out: Path, content: str, tool: str = "claude-code") -> RenderedArtifact:
    return RenderedArtifact(
        tool=tool,
        source_path=Path("canonical/skills/x.md"),
        output_path=out,
        content=content,
        source_commit="abc123",
        source_version="1.0.0",
        artifact_id="x",
        artifact_kind="skill",
    )


def _record(out_dir: Path, files: dict[str, str], tool: str = "claude-code") -> Path:
    """Write `files` and a manifest claiming this tool rendered them."""
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, content in files.items():
        (out_dir / name).write_text(content)
        outputs.append(
            ManifestEntry(path=name, version="1.0.0",
                          sha256=sha256_text(content), adapter=tool)
        )
    manifest = build_manifest(
        source_repo="erpnext-ai-forge",
        source_commit="abc123",
        adapter_name=tool,
        adapter_version="0.1.0",
        entries=[ManifestEntry(path="canonical/skills/x.md", version="1.0.0",
                               sha256=sha256_text("src"), adapter=tool)],
        outputs=outputs,
        rendered_at="2026-01-01T00:00:00Z",
    )
    write_manifest(out_dir, manifest)
    return out_dir


def test_relocated_output_is_reported(tmp_path):
    """The case that motivated this: `output:` changed, old file left behind."""
    old = _record(tmp_path / ".claude" / "skills" / "pos", {"pos.md": "body"})
    new = tmp_path / ".claude" / "skills" / "pos-skill" / "SKILL.md"

    orphans = find_orphans([_artifact(new, "body")], tmp_path, "claude-code")

    assert [o.path for o in orphans] == [old / "pos.md"]
    assert orphans[0].removable


def test_file_still_rendered_is_never_an_orphan(tmp_path):
    d = _record(tmp_path / ".claude", {"a.md": "body"})
    assert find_orphans([_artifact(d / "a.md", "body")], tmp_path, "claude-code") == []


def test_unmanaged_file_is_never_touched(tmp_path):
    """A file with no manifest row is a human's. Deleting it is the one
    unrecoverable mistake available here."""
    d = _record(tmp_path / ".claude", {"generated.md": "body"})
    mine = d / "notes-i-wrote.md"
    mine.write_text("do not delete")

    orphans = find_orphans([], tmp_path, "claude-code")
    prune_orphans(orphans, "claude-code", tmp_path)

    assert mine.is_file()
    assert mine.read_text() == "do not delete"
    assert not (d / "generated.md").exists()


def test_hand_edited_orphan_is_reported_but_not_removed(tmp_path):
    """The hand-edit guard protects these on write; a prune must not be the
    back door around it."""
    d = _record(tmp_path / ".claude", {"a.md": "generated"})
    (d / "a.md").write_text("generated, then edited by hand")

    orphans = find_orphans([], tmp_path, "claude-code")
    removed = prune_orphans(orphans, "claude-code", tmp_path)

    assert len(orphans) == 1 and not orphans[0].removable
    assert removed == []
    assert (d / "a.md").read_text() == "generated, then edited by hand"


def test_another_adapters_output_is_left_alone(tmp_path):
    """Adapters share directories. Pruning claude-code must not reach into
    opencode's rows."""
    d = tmp_path / ".claude"
    _record(d, {"mine.md": "body"}, tool="claude-code")
    theirs = d / "theirs.md"
    theirs.write_text("other adapter")
    manifest = read_manifest(d)
    manifest.outputs.append(
        ManifestEntry(path="theirs.md", version="1.0.0",
                      sha256=sha256_text("other adapter"), adapter="opencode")
    )
    write_manifest(d, manifest)

    prune_orphans(find_orphans([], tmp_path, "claude-code"), "claude-code", tmp_path)

    assert theirs.is_file()
    assert not (d / "mine.md").exists()
    assert [e.path for e in read_manifest(d).outputs] == ["theirs.md"]


def test_prune_empties_the_directory_and_its_manifest(tmp_path):
    d = _record(tmp_path / ".claude" / "skills" / "pos", {"pos.md": "body"})

    removed = prune_orphans(find_orphans([], tmp_path, "claude-code"), "claude-code", tmp_path)

    assert removed == [d / "pos.md"]
    assert not d.exists(), "an emptied directory is itself an orphan"
    assert not (tmp_path / ".claude" / "skills").exists()


def test_prune_leaves_no_missing_row_behind(tmp_path):
    """A row pointing at a deleted file makes `forge validate` report it
    missing forever — the sync after a prune stops being a no-op."""
    d = _record(tmp_path / ".claude", {"gone.md": "a", "stays.md": "b"})

    prune_orphans(
        find_orphans([_artifact(d / "stays.md", "b")], tmp_path, "claude-code"),
        "claude-code",
        tmp_path,
    )

    manifest = read_manifest(d)
    assert [e.path for e in manifest.outputs] == ["stays.md"]
    assert all((d / e.path).is_file() for e in manifest.outputs)


def test_prune_is_idempotent(tmp_path):
    d = _record(tmp_path / ".claude", {"gone.md": "a", "stays.md": "b"})
    rendered = [_artifact(d / "stays.md", "b")]

    prune_orphans(find_orphans(rendered, tmp_path, "claude-code"), "claude-code", tmp_path)
    second = find_orphans(rendered, tmp_path, "claude-code")

    assert second == [], "a second prune found work to do — the first was incomplete"


def test_unreadable_manifest_yields_no_deletions(tmp_path):
    """No record means no judgement. A schema we cannot parse must not license
    deleting the files it describes."""
    d = tmp_path / ".claude"
    d.mkdir(parents=True)
    (d / "a.md").write_text("body")
    (d / ".forge-manifest.json").write_text('{"schema_version": 999}')

    assert find_orphans([], tmp_path, "claude-code") == []
    assert (d / "a.md").is_file()


def test_staging_dir_is_not_scanned(tmp_path):
    """Staging holds a full copy of every render. Treating its manifests as
    bench records would delete real outputs."""
    _record(tmp_path / ".forge-staging" / "claude-code" / ".claude", {"a.md": "body"})
    assert find_orphans([], tmp_path, "claude-code") == []


def test_directory_cleanup_stops_at_the_bench_root(tmp_path):
    """Emptiness alone is not a safe stop condition. Prune the last managed
    file and an unbounded walk climbs through `.claude` and takes the bench
    root with it."""
    bench = tmp_path / "bench"
    _record(bench / ".claude", {"only.md": "body"})

    prune_orphans(find_orphans([], bench, "claude-code"), "claude-code", bench)

    assert not (bench / ".claude").exists()
    assert bench.is_dir(), "the walk climbed out of the tree it was handed"


def test_reporting_an_orphan_does_not_destroy_its_record(tmp_path):
    """Without `--prune` the orphan stays on disk — and so must its manifest
    row. `merge_manifest` replaces the owning adapter's rows wholesale, so the
    sync that merely *reported* the orphan would strip its row and leave a file
    indistinguishable from one a human wrote: never prunable again, by the very
    rule that protects unmanaged files.
    """
    from forge.manifest import build_manifest
    from forge.sync import _carry_forward_orphan_rows

    d = _record(tmp_path / ".claude", {"gone.md": "a", "stays.md": "b"})
    orphans = find_orphans([_artifact(d / "stays.md", "b")], tmp_path, "claude-code")
    assert [o.path.name for o in orphans] == ["gone.md"]

    # What the next sync writes: only the artifact it still renders.
    fresh = build_manifest(
        source_repo="erpnext-ai-forge", source_commit="abc123",
        adapter_name="claude-code", adapter_version="0.1.0", entries=[],
        outputs=[ManifestEntry(path="stays.md", version="1.0.0",
                               sha256=sha256_text("b"), adapter="claude-code")],
        rendered_at="2026-01-01T00:00:00Z",
    )
    _carry_forward_orphan_rows(fresh, orphans, d)

    assert [e.path for e in fresh.outputs] == ["gone.md", "stays.md"]


def test_removed_orphans_are_not_carried_forward(tmp_path):
    """The row goes only if the file did."""
    from forge.manifest import build_manifest
    from forge.sync import _carry_forward_orphan_rows

    d = _record(tmp_path / ".claude", {"gone.md": "a"})
    orphans = find_orphans([], tmp_path, "claude-code")
    prune_orphans(orphans, "claude-code", tmp_path)

    fresh = build_manifest(
        source_repo="erpnext-ai-forge", source_commit="abc123",
        adapter_name="claude-code", adapter_version="0.1.0", entries=[],
        outputs=[], rendered_at="2026-01-01T00:00:00Z",
    )
    _carry_forward_orphan_rows(fresh, orphans, d)

    assert fresh.outputs == []
