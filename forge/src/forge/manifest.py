"""`.forge-manifest.json` schema and writer.

Per ADR-002: every bench output directory gets a manifest recording the
source commit, source file paths, source versions, and render metadata.
Used by `forge validate` for drift detection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forge import __version__ as forge_version


MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILENAME = ".forge-manifest.json"


@dataclass
class ManifestEntry:
    path: str        # relative to the canonical repo root
    version: str
    sha256: str


@dataclass
class Manifest:
    schema_version: int
    source_repo: str
    source_commit: str
    source_files: list[ManifestEntry]
    adapter_name: str
    adapter_version: str
    rendered_at: str
    rendered_by: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_repo": self.source_repo,
            "source_commit": self.source_commit,
            "source_files": [asdict(e) for e in self.source_files],
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
) -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        source_repo=source_repo,
        source_commit=source_commit,
        source_files=entries,
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        rendered_at=datetime.now(timezone.utc).isoformat(),
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
        adapter_name=data["adapter"]["name"],
        adapter_version=data["adapter"]["version"],
        rendered_at=data["rendered_at"],
        rendered_by=data["rendered_by"],
    )
