"""Tests for forge.deprecate — artifact deprecation lifecycle.

Phase 5 exit criterion: first deprecation cycle completes cleanly.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from forge.deprecate import (
    DeprecationResult,
    deprecate,
    find_artifact,
    list_deprecated,
)


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Build a tiny repo with one skill that will get deprecated and one
    that will supersede it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "forge.config.yaml").write_text("project: {name: t, version: 0.0.0}\n")
    skills_dir = repo / "canonical" / "skills" / "frappe-core"
    skills_dir.mkdir(parents=True)

    (skills_dir / "old-skill.md").write_text(
        "---\n"
        "id: old-skill\n"
        "kind: skill\n"
        "version: 1.0.0\n"
        "status: stable\n"
        "domain: frappe-core\n"
        "trigger: \"when X\"\n"
        "scope: [agent:backend-specialist]\n"
        "foundational: false\n"
        "supersedes: []\n"
        "---\n\n"
        "# Old Skill\n\n"
        "Body text.\n"
    )
    (skills_dir / "new-skill.md").write_text(
        "---\n"
        "id: new-skill\n"
        "kind: skill\n"
        "version: 1.0.0\n"
        "status: stable\n"
        "domain: frappe-core\n"
        "trigger: \"when Y\"\n"
        "scope: [agent:backend-specialist]\n"
        "foundational: false\n"
        "supersedes: []\n"
        "---\n\n"
        "# New Skill\n\n"
        "Body text.\n"
    )
    return repo


def test_find_artifact_resolves_skill(fake_repo):
    path = find_artifact(fake_repo, "skill", "old-skill")
    assert path.name == "old-skill.md"
    assert path.exists()


def test_find_artifact_raises_on_missing(fake_repo):
    with pytest.raises(FileNotFoundError):
        find_artifact(fake_repo, "skill", "nonexistent")


def test_find_artifact_raises_on_unknown_kind(fake_repo):
    with pytest.raises(ValueError):
        find_artifact(fake_repo, "elephant", "anything")


def test_deprecate_sets_frontmatter_status(fake_repo):
    result = deprecate(fake_repo, "skill", "old-skill")
    # The deprecated artifact has moved; load from new path
    post = frontmatter.load(result.new_path)
    assert post.metadata["status"] == "deprecated"


def test_deprecate_moves_file_to_deprecated_dir(fake_repo):
    result = deprecate(fake_repo, "skill", "old-skill")
    assert not (fake_repo / "canonical" / "skills" / "frappe-core" / "old-skill.md").exists()
    assert result.new_path.exists()
    expected = fake_repo / "canonical" / "_deprecated" / "skills" / "frappe-core" / "old-skill.md"
    assert result.new_path == expected


def test_deprecate_with_supersedes_updates_replacement(fake_repo):
    deprecate(fake_repo, "skill", "old-skill", superseded_by="new-skill")
    replacement = frontmatter.load(
        fake_repo / "canonical" / "skills" / "frappe-core" / "new-skill.md"
    )
    assert "old-skill" in (replacement.metadata.get("supersedes") or [])


def test_deprecate_supersedes_is_idempotent(fake_repo):
    """Pre-populating supersedes on the replacement doesn't cause duplicates."""
    new_path = fake_repo / "canonical" / "skills" / "frappe-core" / "new-skill.md"
    post = frontmatter.load(new_path)
    post.metadata["supersedes"] = ["old-skill"]
    new_path.write_text(frontmatter.dumps(post))

    deprecate(fake_repo, "skill", "old-skill", superseded_by="new-skill")

    post = frontmatter.load(new_path)
    assert post.metadata["supersedes"] == ["old-skill"]  # not ['old-skill', 'old-skill']


def test_deprecate_changelog_line_with_superseded_by(fake_repo):
    result = deprecate(fake_repo, "skill", "old-skill", superseded_by="new-skill")
    assert "deprecate" in result.changelog_line
    assert "old-skill" in result.changelog_line
    assert "new-skill" in result.changelog_line
    assert result.changelog_line.startswith("chore(skills)")


def test_deprecate_changelog_line_without_superseded_by(fake_repo):
    result = deprecate(fake_repo, "skill", "old-skill")
    assert result.changelog_line == "chore(skills): deprecate `old-skill`"


def test_list_deprecated_returns_moved_files(fake_repo):
    assert list_deprecated(fake_repo) == []
    deprecate(fake_repo, "skill", "old-skill")
    listed = list_deprecated(fake_repo)
    assert len(listed) == 1
    assert listed[0].name == "old-skill.md"


def test_first_deprecation_cycle_completes_cleanly(fake_repo):
    """Phase 5 exit criterion. Walk the full lifecycle:
    1. Mark deprecated + move
    2. Manual purge (simulating one MINOR later)
    3. Verify clean state
    """
    # Step 1: deprecate
    result = deprecate(fake_repo, "skill", "old-skill", superseded_by="new-skill")
    assert result.new_path.exists()
    assert "old-skill" in (
        frontmatter.load(
            fake_repo / "canonical" / "skills" / "frappe-core" / "new-skill.md"
        ).metadata.get("supersedes") or []
    )

    # Step 2: simulate manual purge after one MINOR cycle
    result.new_path.unlink()
    deprecated_dir = fake_repo / "canonical" / "_deprecated"
    # Clean up empty parent dirs (the developer would just rm -rf the file)
    for parent in result.new_path.parents:
        if parent == deprecated_dir.parent:
            break
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()

    # Step 3: clean state
    assert list_deprecated(fake_repo) == []
    # Replacement still carries the supersedes record — historical trace remains
    final = frontmatter.load(
        fake_repo / "canonical" / "skills" / "frappe-core" / "new-skill.md"
    )
    assert "old-skill" in (final.metadata.get("supersedes") or [])
