"""Per-app ownership: canonical app-notes, hand-edit detection, adoption.

The contract these tests defend: forge owning a generated file must not mean a
human's edit to that file disappears on the next sync. Sync notices the edit and
backs off; `forge adopt` routes it into canonical; the sync after that owns the
file again, with the edit still in it.
"""

from pathlib import Path

import pytest

from forge.commands.adopt import _strip_generated_scaffolding
from forge.loader import load_app_notes
from forge.manifest import ManifestEntry, build_manifest, read_manifest, sha256_text, write_manifest
from forge.render import RenderedArtifact, render
from forge.sync import detect_hand_edits


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# canonical/apps/<app>.md
# ---------------------------------------------------------------------------
def test_every_managed_app_has_canonical_notes(repo_root):
    notes = load_app_notes(repo_root)
    managed = {
        "novizna_crm",
        "novizna_core",
        "novizna_pos",
        "invoice_ninja_integration",
        "noviznaerp_payroll",
        "cargo_management",
        "changemakers",
        "erpnext_location",
    }
    assert managed <= set(notes), f"missing app notes for {managed - set(notes)}"


def test_app_notes_are_rendered_into_the_per_app_file(repo_root, monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_BENCH_PATH", str(tmp_path))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "test-site")
    (tmp_path / "apps").mkdir()

    rendered = render(repo_root, "claude-code")
    pos = next(
        r for r in rendered if r.output_path.parts[-2:] == ("novizna_pos", "CLAUDE.md")
    )
    notes = load_app_notes(repo_root)["novizna_pos"].body.strip()

    # Not a summary or a link — the notes body is present verbatim.
    assert notes in pos.content


def test_no_output_path_is_rendered_twice(repo_root, monkeypatch, tmp_path):
    # A path rendered twice writes two manifest rows for one file, and the
    # duplicate row silently defeats hand-edit detection.
    monkeypatch.setenv("FORGE_BENCH_PATH", str(tmp_path))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "test-site")
    (tmp_path / "apps").mkdir()

    for tool in ["claude-code", "cursor", "cline", "copilot"]:
        paths = [r.output_path for r in render(repo_root, tool)]
        assert len(paths) == len(set(paths)), f"{tool} renders a duplicate output path"


# ---------------------------------------------------------------------------
# hand-edit detection
# ---------------------------------------------------------------------------
def _artifact(path: Path, content: str) -> RenderedArtifact:
    return RenderedArtifact(
        tool="claude-code",
        source_path=path,
        output_path=path,
        content=content,
        source_commit="deadbee",
        source_version="1.0.0",
        artifact_id="test",
        artifact_kind="aggregate",
    )


def _manifest_for(directory: Path, filename: str, content: str) -> None:
    write_manifest(
        directory,
        build_manifest(
            source_repo="erpnext-ai-forge",
            source_commit="deadbee",
            adapter_name="claude-code",
            adapter_version="0.1.0",
            entries=[ManifestEntry(path="canonical/x.md", version="1.0.0", sha256="x")],
            outputs=[
                ManifestEntry(path=filename, version="1.0.0", sha256=sha256_text(content))
            ],
        ),
    )


def test_untouched_file_is_not_reported_as_hand_edited(tmp_path):
    target = tmp_path / "CLAUDE.md"
    target.write_text("generated\n")
    _manifest_for(tmp_path, "CLAUDE.md", "generated\n")

    assert detect_hand_edits([_artifact(target, "generated v2\n")], tmp_path) == {}


def test_edited_file_is_reported(tmp_path):
    target = tmp_path / "CLAUDE.md"
    _manifest_for(tmp_path, "CLAUDE.md", "generated\n")
    target.write_text("generated\nplus a human rule\n")

    edits = detect_hand_edits([_artifact(target, "generated v2\n")], tmp_path)
    assert target in edits


def test_unmanaged_file_is_adopted_not_flagged(tmp_path):
    # No manifest at all: this is the first time forge writes here, which is how
    # the eight existing per-app files come under management without conflict.
    target = tmp_path / "CLAUDE.md"
    target.write_text("hand-written, forge has never seen this\n")

    assert detect_hand_edits([_artifact(target, "generated\n")], tmp_path) == {}


def test_a_file_already_matching_the_new_render_is_not_a_conflict(tmp_path):
    target = tmp_path / "CLAUDE.md"
    _manifest_for(tmp_path, "CLAUDE.md", "old\n")
    target.write_text("new\n")

    # Disk differs from what was recorded, but equals what we are about to
    # write — converged, not a conflict.
    assert detect_hand_edits([_artifact(target, "new\n")], tmp_path) == {}


def test_pre_v2_manifest_does_not_flag_everything(tmp_path):
    # A v1 manifest has no `outputs`; read_manifest returns None on the schema
    # mismatch, so every file reads as unmanaged rather than hand-edited.
    (tmp_path / ".forge-manifest.json").write_text('{"schema_version": 1}')
    target = tmp_path / "CLAUDE.md"
    target.write_text("whatever\n")

    assert detect_hand_edits([_artifact(target, "generated\n")], tmp_path) == {}
    assert read_manifest(tmp_path) is None


# ---------------------------------------------------------------------------
# adoption
# ---------------------------------------------------------------------------
def test_adoption_strips_generated_scaffolding():
    rendered = (
        "<!-- AUTO-GENERATED FROM erpnext-ai-forge 0.1.0 -->\n"
        "<!-- Edit canonical/apps/x.md -->\n"
        "# novizna_pos — App-Specific Context\n"
        "\n"
        "**Stack:** python\n"
        "**Custom DocTypes:** 3\n"
        "\n"
        "---\n"
        "\n"
        "## Real Notes\n"
        "\n"
        "- something a human wrote\n"
        "\n"
        "---\n"
        "\n"
        "## Common Commands\n"
        "\n"
        "```bash\n"
        "bench migrate\n"
        "```\n"
        "\n"
        "---\n"
        "\n"
        "<sub>Source: canonical/apps/x.md</sub>\n"
    )
    body = _strip_generated_scaffolding(rendered)

    assert body.startswith("## Real Notes")
    assert "something a human wrote" in body
    # None of the generator's own output round-trips back into canonical.
    assert "AUTO-GENERATED" not in body
    assert "App-Specific Context" not in body
    assert "**Stack:**" not in body
    assert "## Common Commands" not in body
    assert "<sub>" not in body


def test_adoption_is_idempotent_on_already_clean_notes():
    body = "## Real Notes\n\n- something a human wrote\n"
    assert _strip_generated_scaffolding(body) == body


# ---------------------------------------------------------------------------
# unresolved output paths (the bench-root CLAUDE.md corruption)
# ---------------------------------------------------------------------------
def test_unrendered_output_path_raises_instead_of_writing_to_bench_root(tmp_path):
    from forge.sync import _stage_artifacts

    # Exactly the shape that used to slip through: an `output:` pointing at a
    # nested dict entry, passed through unresolved. Staging dropped every
    # directory component and the swap wrote it to the bench root.
    bad = _artifact(Path("{{ output_paths.bench_root }}/apps/x/CLAUDE.md"), "content\n")

    with pytest.raises(ValueError, match="never rendered"):
        _stage_artifacts([bad], tmp_path, "claude-code")


def test_brace_placeholder_output_path_raises(tmp_path):
    from forge.sync import _stage_artifacts

    bad = _artifact(Path("/bench/apps/{app}/CLAUDE.md"), "content\n")

    with pytest.raises(ValueError, match="unsubstituted placeholder"):
        _stage_artifacts([bad], tmp_path, "claude-code")


def test_relative_output_path_raises(tmp_path):
    from forge.sync import _stage_artifacts

    bad = _artifact(Path("apps/x/CLAUDE.md"), "content\n")

    with pytest.raises(ValueError, match="not absolute"):
        _stage_artifacts([bad], tmp_path, "claude-code")
