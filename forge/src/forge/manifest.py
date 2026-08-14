"""`.forge-manifest.json` schema and writer.

Per ADR-002: every bench output directory gets a manifest recording the
source commit, source file paths, source versions, and render metadata.
Used by `forge validate` for drift detection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forge import __version__ as forge_version


# v2 adds `outputs`: the sha256 of each file forge actually WROTE, keyed by its
# bench-relative path. `source_files` records what forge read; only `outputs`
# can answer "has a human edited this since we generated it?". A v1 manifest is
# read as None, so the first v2 sync sees "no record" and adopts rather than
# reporting every file as hand-edited.
MANIFEST_SCHEMA_VERSION = 2
MANIFEST_FILENAME = ".forge-manifest.json"


@dataclass
class ManifestEntry:
    path: str        # relative to the canonical repo root
    version: str
    sha256: str
    mode: int | None = None
    """POSIX permission bits forge wrote, when it pinned them (harness scripts).

    Optional and defaulted on purpose. Adding it does NOT bump
    MANIFEST_SCHEMA_VERSION: `read_manifest` returns None on a version
    mismatch, and `detect_hand_edits` reads "no manifest record" as "unmanaged,
    adopt it" — so a bump would make every file in the bench look unmanaged and
    silently discard one full round of hand-edit protection. An optional field
    parses old manifests unchanged, which is the whole point.
    """
    adapter: str | None = None
    """Which adapter rendered this row.

    Several adapters legitimately write into the same directory — all seven
    emit bench-root `AGENTS-TICKETING.md`. Without per-row ownership a merge
    cannot tell "another adapter still owns this" from "I used to render this
    and no longer do", so it could neither preserve the first nor retire the
    second. See `merge_manifest`.
    """

    def to_dict(self) -> dict[str, Any]:
        # Omit optional fields when unset so manifests for the existing
        # Markdown/JSON artifacts stay byte-identical to previous versions.
        d: dict[str, Any] = {
            "path": self.path,
            "version": self.version,
            "sha256": self.sha256,
        }
        if self.mode is not None:
            d["mode"] = self.mode
        if self.adapter is not None:
            d["adapter"] = self.adapter
        return d


@dataclass
class Manifest:
    schema_version: int
    source_repo: str
    source_commit: str
    source_files: list[ManifestEntry]
    outputs: list[ManifestEntry]
    adapter_name: str
    adapter_version: str
    rendered_at: str
    rendered_by: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_repo": self.source_repo,
            "source_commit": self.source_commit,
            "source_files": [e.to_dict() for e in self.source_files],
            "outputs": [e.to_dict() for e in self.outputs],
            "adapter": {
                "name": self.adapter_name,
                "version": self.adapter_version,
            },
            "rendered_at": self.rendered_at,
            "rendered_by": self.rendered_by,
        }


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_manifest(
    *,
    source_repo: str,
    source_commit: str,
    adapter_name: str,
    adapter_version: str,
    entries: list[ManifestEntry],
    outputs: list[ManifestEntry] | None = None,
    rendered_at: str | None = None,
) -> Manifest:
    """Build a manifest.

    `rendered_at` defaults to now, but callers writing into a git-tracked
    directory should pass a deterministic stamp instead. A wall-clock value
    means the manifest differs on every sync even when nothing was rendered
    differently — and since the manifest records each output's sha256, and the
    outputs carry the same stamp in their provenance footer, one clock read
    dirties two files in every managed app, forever.
    """
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        source_repo=source_repo,
        source_commit=source_commit,
        source_files=entries,
        outputs=outputs or [],
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        rendered_at=rendered_at or datetime.now(timezone.utc).isoformat(),
        rendered_by=f"forge {forge_version}",
    )


def write_manifest(directory: Path, manifest: Manifest) -> Path:
    """Write `.forge-manifest.json` into `directory` (atomic — temp + rename)."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / MANIFEST_FILENAME
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n")
    tmp.replace(target)
    return target


def merge_manifest(existing: Manifest | None, incoming: Manifest) -> Manifest:
    """Fold `incoming` into `existing`, preserving other adapters' rows.

    Each `sync_tool` call used to write the manifest for its own adapter only,
    which meant the last adapter to sync a shared directory erased every other
    adapter's record of what it had written there. Those adapters then lost
    hand-edit protection on their files: with no manifest row,
    `detect_hand_edits` treats a file as unmanaged and the next sync silently
    overwrites whatever the human put there.

    The merge rule follows ownership. Rows belonging to `incoming.adapter_name`
    are replaced wholesale — so a file that adapter no longer renders correctly
    disappears from the manifest. Rows belonging to any other adapter are kept
    untouched. Legacy rows with no `adapter` are attributed to the incoming
    adapter, because before this function existed a manifest only ever
    contained one adapter's rows anyway.
    """
    if existing is None:
        return incoming

    owner = incoming.adapter_name

    def _fold(
        old: list[ManifestEntry], new: list[ManifestEntry]
    ) -> list[ManifestEntry]:
        kept = [e for e in old if (e.adapter or owner) != owner]
        by_path = {e.path: e for e in kept}
        for e in new:
            by_path[e.path] = e
        return sorted(by_path.values(), key=lambda e: e.path)

    return Manifest(
        schema_version=incoming.schema_version,
        source_repo=incoming.source_repo,
        source_commit=incoming.source_commit,
        source_files=_fold(existing.source_files, incoming.source_files),
        outputs=_fold(existing.outputs, incoming.outputs),
        adapter_name=owner,
        adapter_version=incoming.adapter_version,
        rendered_at=incoming.rendered_at,
        rendered_by=incoming.rendered_by,
    )


def read_manifest(directory: Path) -> Manifest | None:
    """Read a manifest if present, else None. Returns None on schema mismatch."""
    target = directory / MANIFEST_FILENAME
    if not target.is_file():
        return None
    data = json.loads(target.read_text())
    if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return None
    return Manifest(
        schema_version=data["schema_version"],
        source_repo=data["source_repo"],
        source_commit=data["source_commit"],
        source_files=[ManifestEntry(**e) for e in data.get("source_files", [])],
        outputs=[ManifestEntry(**e) for e in data.get("outputs", [])],
        adapter_name=data["adapter"]["name"],
        adapter_version=data["adapter"]["version"],
        rendered_at=data["rendered_at"],
        rendered_by=data["rendered_by"],
    )
