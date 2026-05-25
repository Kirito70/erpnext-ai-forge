"""Artifact deprecation lifecycle.

Per governance.md §3:
  1. Set frontmatter `status: deprecated`
  2. If a replacement is named, set `supersedes:` on the replacement
  3. Move file to `canonical/_deprecated/<original-relative-path>`
  4. Print a CHANGELOG line for the developer to append
  5. After one MINOR cycle, the file is removed (manual cadence — Phase 5
     `forge deprecate --purge` could automate)
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import frontmatter

from forge.loader import find_repo_root, load_agents, load_commands, load_skills, load_tools


@dataclass
class DeprecationResult:
    artifact_kind: str
    artifact_id: str
    source_path: Path           # original location (before move)
    new_path: Path              # canonical/_deprecated/... location
    superseded_by: str | None
    superseded_by_path: Path | None  # path to the replacement (if found)
    changelog_line: str


def _all_canonical_files(repo_root: Path) -> Iterator[tuple[str, Path]]:
    """Yield (kind, path) for every canonical artifact (Markdown + YAML)."""
    for kind, subdir in (
        ("agent", "agents"),
        ("command", "commands"),
        ("skill", "skills"),
        ("tool", "tools"),
        ("policy", "policies"),
    ):
        base = repo_root / "canonical" / subdir
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            yield kind, path
        for path in base.rglob("*.yaml"):
            yield kind, path


def find_artifact(repo_root: Path, kind: str, name: str) -> Path:
    """Locate a canonical artifact by kind + id (basename). Raises if missing
    or ambiguous. Search is restricted to `canonical/<kind-plural>/`."""
    subdir_map = {
        "agent": "agents",
        "command": "commands",
        "skill": "skills",
        "tool": "tools",
        "policy": "policies",
    }
    subdir = subdir_map.get(kind)
    if subdir is None:
        raise ValueError(f"Unknown artifact kind: {kind!r}")
    base = repo_root / "canonical" / subdir
    matches = list(base.rglob(f"{name}.md")) + list(base.rglob(f"{name}.yaml"))
    if not matches:
        raise FileNotFoundError(f"No canonical {kind} named {name!r} under {base}")
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous match for {kind}/{name}: {[str(m) for m in matches]}"
        )
    return matches[0]


def _set_frontmatter_status(path: Path, **updates) -> None:
    """Mutate the frontmatter of `path` with the supplied key/value pairs.

    Preserves body and existing keys. Writes atomically (temp + rename).
    """
    post = frontmatter.load(path)
    post.metadata.update(updates)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(frontmatter.dumps(post) + "\n")
    tmp.replace(path)


def _append_to_supersedes(replacement_path: Path, deprecated_id: str) -> None:
    """Add `deprecated_id` to the `supersedes:` list on the replacement
    artifact. Idempotent — does nothing if already present."""
    post = frontmatter.load(replacement_path)
    existing = list(post.metadata.get("supersedes", []) or [])
    if deprecated_id not in existing:
        existing.append(deprecated_id)
        post.metadata["supersedes"] = existing
        tmp = replacement_path.with_suffix(replacement_path.suffix + ".tmp")
        tmp.write_text(frontmatter.dumps(post) + "\n")
        tmp.replace(replacement_path)


def deprecate(
    repo_root: Path,
    kind: str,
    name: str,
    superseded_by: str | None = None,
) -> DeprecationResult:
    """Run the deprecation flow on an artifact.

    Returns a DeprecationResult with everything the caller needs to render
    output and update the CHANGELOG.
    """
    source = find_artifact(repo_root, kind, name)

    # 1. Mutate the artifact's frontmatter
    _set_frontmatter_status(source, status="deprecated")

    # 2. Set supersedes: on the replacement (if named)
    replacement_path: Path | None = None
    if superseded_by:
        replacement_path = find_artifact(repo_root, kind, superseded_by)
        _append_to_supersedes(replacement_path, name)

    # 3. Move the deprecated file
    rel_under_canonical = source.relative_to(repo_root / "canonical")
    new_path = repo_root / "canonical" / "_deprecated" / rel_under_canonical
    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(new_path))

    # 4. CHANGELOG line
    if superseded_by:
        changelog = (
            f"chore({kind}s): deprecate `{name}` (superseded by `{superseded_by}`)"
        )
    else:
        changelog = f"chore({kind}s): deprecate `{name}`"

    return DeprecationResult(
        artifact_kind=kind,
        artifact_id=name,
        source_path=source,
        new_path=new_path,
        superseded_by=superseded_by,
        superseded_by_path=replacement_path,
        changelog_line=changelog,
    )


def list_deprecated(repo_root: Path) -> list[Path]:
    """List every artifact currently sitting in `canonical/_deprecated/`."""
    base = repo_root / "canonical" / "_deprecated"
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*") if p.is_file())
