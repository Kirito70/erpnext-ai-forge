"""A sync that changes nothing must write nothing.

Commit 31aa6db made this true for per-app CLAUDE.md and the manifest, by
stamping provenance with the commit a file was rendered FROM rather than the
moment sync ran. The shared artifacts — agents, commands, skills, tools, the
bench-root CLAUDE.md, the aggregates — were never covered, so 83 files still
came out different on every run, differing only in a wall-clock timestamp.

Two properties, because either one alone is not enough:

- **Rendering twice produces the same bytes.** Without this, nothing downstream
  can be idempotent; the content itself is different.
- **Writing content that is already on disk is skipped.** Without this, a sync
  still touches every file's mtime and reports it as written, which is what
  `SyncResult.files_unchanged` was declared for and never assigned.
"""

from __future__ import annotations

from pathlib import Path

from forge.manifest import sha256_text
from forge.render import RenderedArtifact
from forge.sync import _swap_into_bench

TOOL = "claude-code"


def _staged(staging: Path, rel: str, content: str) -> Path:
    path = staging / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _artifact(out: Path, content: str) -> RenderedArtifact:
    return RenderedArtifact(
        tool=TOOL,
        source_path=Path("canonical/skills/x.md"),
        output_path=out,
        content=content,
        source_commit="abc123",
        source_version="1.0.0",
        artifact_id="x",
        artifact_kind="skill",
    )


# ---------------------------------------------------------------------------
# the write path
# ---------------------------------------------------------------------------


def test_identical_content_is_not_rewritten(tmp_path):
    staging = tmp_path / "staging"
    bench = tmp_path / "bench"
    bench.mkdir()
    _staged(staging, "CLAUDE.md", "same bytes\n")
    target = bench / "CLAUDE.md"
    target.write_text("same bytes\n")
    before = target.stat().st_mtime_ns

    written, unchanged = _swap_into_bench(staging, bench)

    assert written == []
    assert unchanged == [target]
    assert target.stat().st_mtime_ns == before, "the file was rewritten in place"


def test_changed_content_is_still_written(tmp_path):
    staging = tmp_path / "staging"
    bench = tmp_path / "bench"
    bench.mkdir()
    _staged(staging, "CLAUDE.md", "new\n")
    target = bench / "CLAUDE.md"
    target.write_text("old\n")

    written, unchanged = _swap_into_bench(staging, bench)

    assert written == [target]
    assert unchanged == []
    assert target.read_text() == "new\n"


def test_a_file_that_does_not_exist_yet_is_written(tmp_path):
    staging = tmp_path / "staging"
    bench = tmp_path / "bench"
    bench.mkdir()
    _staged(staging, "new.md", "body\n")

    written, unchanged = _swap_into_bench(staging, bench)

    assert written == [bench / "new.md"]
    assert unchanged == []


def test_a_protected_file_counts_as_neither(tmp_path):
    """It was not written, and calling it unchanged would report a hand edit as
    agreement with what forge wanted to write."""
    staging = tmp_path / "staging"
    bench = tmp_path / "bench"
    bench.mkdir()
    _staged(staging, "CLAUDE.md", "forge version\n")
    target = bench / "CLAUDE.md"
    target.write_text("human version\n")

    written, unchanged = _swap_into_bench(staging, bench, protected={target})

    assert written == []
    assert unchanged == []
    assert target.read_text() == "human version\n"


def test_mode_still_applies_when_content_matches(tmp_path):
    """Skipping the write must not skip the bit that makes a hook executable."""
    staging = tmp_path / "staging"
    bench = tmp_path / "bench"
    bench.mkdir()
    staged = _staged(staging, "hook.sh", "#!/bin/sh\n")
    staged.chmod(0o755)
    target = bench / "hook.sh"
    target.write_text("#!/bin/sh\n")
    target.chmod(0o644)

    _swap_into_bench(staging, bench)

    assert target.stat().st_mode & 0o111, "executable bit was never applied"


# ---------------------------------------------------------------------------
# the content
# ---------------------------------------------------------------------------


def test_provenance_carries_no_wall_clock(tmp_path, repo_root, monkeypatch):
    """Two renders of the same commit must agree byte for byte. A `Synced at`
    stamped from `datetime.now()` is what made 83 files dirty every run."""
    from forge.render import render

    monkeypatch.setenv("FORGE_BENCH_PATH", str(tmp_path / "bench"))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "test-site")
    first = render(repo_root, TOOL, target=None)
    second = render(repo_root, TOOL, target=None)

    by_path = {r.output_path: r.content for r in first}
    drifted = [
        str(r.output_path)
        for r in second
        if sha256_text(by_path.get(r.output_path, "")) != sha256_text(r.content)
    ]
    assert drifted == [], f"{len(drifted)} artifact(s) differ between two renders"


def test_output_does_not_change_when_only_head_moves(tmp_path, repo_root, monkeypatch):
    """Provenance must date from an artifact's SOURCE, never from repo HEAD.

    The forge repo is one of its own render targets, so HEAD-based provenance
    cannot converge: sync stamps HEAD, committing that render moves HEAD, and
    the next sync stamps the new HEAD and disagrees with what was just
    committed. The self-sync check chases its own tail forever. Anything
    rendered from a source that did not change must render identically no
    matter which commit happens to be checked out.
    """
    from forge import render as render_mod

    monkeypatch.setenv("FORGE_BENCH_PATH", str(tmp_path / "bench"))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "test-site")

    before = {r.output_path: r.content for r in render_mod.render(repo_root, TOOL)}
    # Same tree, different HEAD — exactly what committing a render does.
    monkeypatch.setattr(render_mod, "repo_head_commit", lambda _root: "0" * 40)
    after = render_mod.render(repo_root, TOOL)

    moved = [
        str(r.output_path)
        for r in after
        if sha256_text(before.get(r.output_path, "")) != sha256_text(r.content)
    ]
    assert moved == [], f"{len(moved)} artifact(s) re-dated because HEAD moved"


def test_every_artifact_names_a_source_that_exists(tmp_path, repo_root, monkeypatch):
    """A row whose source cannot be read opts out of the staleness check rather
    than failing it, so a renamed canonical file silently stops being watched.
    `canonical/agents/architect.md` became `novizna-architect.md` and the
    bench-root CLAUDE.md kept pointing at the old name — no error, no check.
    """
    from forge.render import render

    monkeypatch.setenv("FORGE_BENCH_PATH", str(tmp_path / "bench"))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "test-site")

    # A directory is allowed: an aggregate is rendered from the whole canonical
    # tree and says so by naming it, which is honest rather than picking one
    # file to stand in for many. What must never happen is a path that is not
    # there at all.
    missing = sorted(
        {
            str(r.source_path.relative_to(repo_root))
            for r in render(repo_root, TOOL, target=None)
            if repo_root in r.source_path.parents and not r.source_path.exists()
        }
    )
    assert missing == [], f"artifact source(s) that do not exist: {missing}"
