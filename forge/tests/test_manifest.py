"""Tests for forge.manifest — .forge-manifest.json schema + writer."""

from __future__ import annotations

import json
from pathlib import Path

from forge.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
    ManifestEntry,
    build_manifest,
    read_manifest,
    sha256_text,
    write_manifest,
)


def test_sha256_text_is_deterministic():
    a = sha256_text("hello")
    b = sha256_text("hello")
    assert a == b
    assert len(a) == 64


def test_build_and_write_manifest(tmp_path):
    entries = [
        ManifestEntry(path="canonical/agents/architect.md", version="1.0.0", sha256="a" * 64),
        ManifestEntry(path="canonical/agents/backend.md",  version="1.0.0", sha256="b" * 64),
    ]
    m = build_manifest(
        source_repo="erpnext-ai-forge",
        source_commit="abc123",
        adapter_name="claude-code",
        adapter_version="0.1.0",
        entries=entries,
    )
    path = write_manifest(tmp_path, m)
    assert path.name == MANIFEST_FILENAME
    data = json.loads(path.read_text())
    assert data["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert data["source_commit"] == "abc123"
    assert data["adapter"]["name"] == "claude-code"
    assert len(data["source_files"]) == 2


def test_read_manifest_roundtrip(tmp_path):
    entries = [ManifestEntry(path="x", version="1.0.0", sha256="c" * 64)]
    m = build_manifest(
        source_repo="erpnext-ai-forge",
        source_commit="def456",
        adapter_name="claude-code",
        adapter_version="0.1.0",
        entries=entries,
    )
    write_manifest(tmp_path, m)
    read = read_manifest(tmp_path)
    assert read is not None
    assert read.source_commit == "def456"
    assert read.source_files[0].path == "x"


def test_read_manifest_returns_none_when_missing(tmp_path):
    assert read_manifest(tmp_path) is None


def test_read_manifest_returns_none_on_schema_mismatch(tmp_path):
    (tmp_path / MANIFEST_FILENAME).write_text(json.dumps({"schema_version": 999}))
    assert read_manifest(tmp_path) is None
