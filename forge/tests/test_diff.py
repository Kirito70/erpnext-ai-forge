"""`forge diff` — classify pending changes without writing anything.

`--dry-run` answers "did the render succeed". This answers "what is about to
happen to my repo", which is a different question once sync starts writing
executable hook scripts and merging into a human-owned settings.json.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.commands.diff import (
    HAND_EDITED,
    MODE,
    MODIFIED,
    NEW,
    UNCHANGED,
    compute_diffs,
    render_diff_report,
)
from forge.manifest import ManifestEntry, build_manifest, sha256_text, write_manifest
from forge.render import RenderedArtifact


def _art(bench: Path, name: str, content: str, mode: int | None = None):
    return RenderedArtifact(
        tool="claude-code",
        source_path=Path("canonical/agents/architect.md"),
        output_path=bench / name,
        content=content,
        source_commit="abc123",
        source_version="1.0.0",
        artifact_id="architect",
        artifact_kind="agent",
        mode=mode,
    )


@pytest.fixture
def bench(tmp_path: Path) -> Path:
    b = tmp_path / "bench"
    (b / ".claude").mkdir(parents=True)
    return b


def _record(bench: Path, name: str, content: str, mode: int | None = None) -> None:
    """Pretend a previous sync wrote `content` to `name`."""
    write_manifest(
        (bench / name).parent,
        build_manifest(
            source_repo="erpnext-ai-forge",
            source_commit="abc123",
            adapter_name="claude-code",
            adapter_version="0.1.0",
            entries=[ManifestEntry(path="canonical/agents/architect.md",
                                   version="1.0.0", sha256="a" * 64,
                                   adapter="claude-code")],
            outputs=[ManifestEntry(path=Path(name).name, version="1.0.0",
                                   sha256=sha256_text(content), mode=mode,
                                   adapter="claude-code")],
        ),
    )


def test_absent_file_is_new(bench):
    d = compute_diffs([_art(bench, "CLAUDE.md", "hello")], bench)[0]
    assert d.status == NEW
    assert d.before is None


def test_identical_file_is_unchanged(bench):
    (bench / "CLAUDE.md").write_text("hello")
    _record(bench, "CLAUDE.md", "hello")
    assert compute_diffs([_art(bench, "CLAUDE.md", "hello")], bench)[0].status == UNCHANGED


def test_changed_content_is_modified(bench):
    (bench / "CLAUDE.md").write_text("old")
    _record(bench, "CLAUDE.md", "old")
    d = compute_diffs([_art(bench, "CLAUDE.md", "new")], bench)[0]
    assert d.status == MODIFIED
    assert "-old" in d.unified and "+new" in d.unified


def test_hand_edited_outranks_modified(bench):
    """When a human changed a generated file, that is the headline — sync will
    refuse to touch it until `forge adopt` routes the edit into canonical."""
    _record(bench, "CLAUDE.md", "what forge wrote")
    (bench / "CLAUDE.md").write_text("what a human wrote")
    d = compute_diffs([_art(bench, "CLAUDE.md", "what forge wants now")], bench)[0]
    assert d.status == HAND_EDITED


def test_mode_only_change_is_detected(bench):
    """Content-equal but non-executable: the failure mode a content diff misses
    entirely, and the one that silently stops a hook from ever running."""
    script = bench / "gates.sh"
    script.write_text("#!/usr/bin/env bash\n")
    script.chmod(0o644)
    _record(bench, "gates.sh", "#!/usr/bin/env bash\n", mode=0o644)
    d = compute_diffs([_art(bench, "gates.sh", "#!/usr/bin/env bash\n", mode=0o755)], bench)[0]
    assert d.status == MODE
    assert d.mode_before == 0o644 and d.mode_after == 0o755


def test_mode_matching_is_unchanged(bench):
    script = bench / "gates.sh"
    script.write_text("#!/usr/bin/env bash\n")
    script.chmod(0o755)
    _record(bench, "gates.sh", "#!/usr/bin/env bash\n", mode=0o755)
    d = compute_diffs([_art(bench, "gates.sh", "#!/usr/bin/env bash\n", mode=0o755)], bench)[0]
    assert d.status == UNCHANGED


def test_diff_writes_nothing(bench):
    """The whole point: it is safe to run against a repo you care about."""
    before = {p: p.read_bytes() for p in bench.rglob("*") if p.is_file()}
    compute_diffs([_art(bench, "CLAUDE.md", "hello")], bench)
    assert not (bench / "CLAUDE.md").exists()
    assert {p: p.read_bytes() for p in bench.rglob("*") if p.is_file()} == before


def test_report_lists_new_file_with_its_mode(bench):
    out = render_diff_report(
        compute_diffs([_art(bench, "gates.sh", "x", mode=0o755)], bench),
        bench, show_content=False, show_unchanged=False,
    )
    assert "gates.sh" in out and "0755" in out and "1 new" in out


def test_report_warns_about_hand_edits(bench):
    _record(bench, "CLAUDE.md", "forge")
    (bench / "CLAUDE.md").write_text("human")
    out = render_diff_report(
        compute_diffs([_art(bench, "CLAUDE.md", "next")], bench),
        bench, show_content=False, show_unchanged=False,
    )
    assert "forge adopt" in out, "the report must say how to recover the edit"


def test_report_hides_unchanged_by_default(bench):
    (bench / "CLAUDE.md").write_text("same")
    _record(bench, "CLAUDE.md", "same")
    diffs = compute_diffs([_art(bench, "CLAUDE.md", "same")], bench)
    quiet = render_diff_report(diffs, bench, show_content=False, show_unchanged=False)
    loud = render_diff_report(diffs, bench, show_content=False, show_unchanged=True)
    assert "CLAUDE.md" not in quiet and "No changes" in quiet
    assert "CLAUDE.md" in loud


def test_square_brackets_in_content_do_not_break_the_report(bench):
    """Rich reads [..] as markup; diff bodies are arbitrary text."""
    (bench / "CLAUDE.md").write_text("scope: [agent:architect]\n")
    _record(bench, "CLAUDE.md", "scope: [agent:architect]\n")
    out = render_diff_report(
        compute_diffs([_art(bench, "CLAUDE.md", "scope: [agent:qa]\n")], bench),
        bench, show_content=True, show_unchanged=False,
    )
    assert "agent:qa" in out
