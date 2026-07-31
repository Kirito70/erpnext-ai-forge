"""Tests for forge.manifest — .forge-manifest.json schema + writer."""

from __future__ import annotations

import json
from pathlib import Path

from forge.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
    ManifestEntry,
    build_manifest,
    merge_manifest,
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


def _manifest(adapter: str, outputs: list[ManifestEntry]) -> object:
    return build_manifest(
        source_repo="erpnext-ai-forge",
        source_commit="abc123",
        adapter_name=adapter,
        adapter_version="0.1.0",
        entries=[ManifestEntry(path=f"canonical/x-{adapter}.md", version="1.0.0",
                               sha256="a" * 64, adapter=adapter)],
        outputs=outputs,
    )


def test_optional_fields_omitted_when_unset():
    """An entry with no mode/adapter serialises exactly as it always did.

    Guards the decision not to bump MANIFEST_SCHEMA_VERSION: existing manifests
    must keep round-tripping unchanged.
    """
    e = ManifestEntry(path="x", version="1.0.0", sha256="a" * 64)
    assert e.to_dict() == {"path": "x", "version": "1.0.0", "sha256": "a" * 64}


def test_old_manifest_without_optional_fields_still_parses(tmp_path):
    (tmp_path / MANIFEST_FILENAME).write_text(json.dumps({
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_repo": "erpnext-ai-forge",
        "source_commit": "abc123",
        "source_files": [{"path": "x", "version": "1.0.0", "sha256": "a" * 64}],
        "outputs": [{"path": "CLAUDE.md", "version": "1.0.0", "sha256": "b" * 64}],
        "adapter": {"name": "claude-code", "version": "0.1.0"},
        "rendered_at": "2026-07-30T00:00:00+00:00",
        "rendered_by": "forge 0.6.3",
    }))
    m = read_manifest(tmp_path)
    assert m is not None
    assert m.outputs[0].mode is None
    assert m.outputs[0].adapter is None


def test_mode_round_trips(tmp_path):
    m = _manifest("claude-code", [
        ManifestEntry(path="gates.sh", version="1.0.0", sha256="c" * 64,
                      mode=0o755, adapter="claude-code"),
    ])
    write_manifest(tmp_path, m)
    back = read_manifest(tmp_path)
    assert back is not None
    assert back.outputs[0].mode == 0o755


def test_two_adapters_same_dir_both_retained(tmp_path):
    """The bug this fixes: all seven adapters write bench-root
    AGENTS-TICKETING.md, and whichever synced last used to erase the other six
    adapters' rows — silently costing them hand-edit protection."""
    first = _manifest("claude-code", [
        ManifestEntry(path="CLAUDE.md", version="1.0.0", sha256="1" * 64,
                      adapter="claude-code"),
    ])
    write_manifest(tmp_path, merge_manifest(read_manifest(tmp_path), first))

    second = _manifest("cursor", [
        ManifestEntry(path="forge-main.mdc", version="1.0.0", sha256="2" * 64,
                      adapter="cursor"),
    ])
    write_manifest(tmp_path, merge_manifest(read_manifest(tmp_path), second))

    back = read_manifest(tmp_path)
    assert back is not None
    paths = {e.path for e in back.outputs}
    assert paths == {"CLAUDE.md", "forge-main.mdc"}
    # Source rows from both adapters survive too.
    assert {e.path for e in back.source_files} == {
        "canonical/x-claude-code.md", "canonical/x-cursor.md"
    }


def test_merge_retires_a_row_its_own_adapter_stopped_rendering(tmp_path):
    """Ownership cuts both ways: an adapter's re-sync replaces its own rows
    wholesale, so a file it no longer renders leaves the manifest."""
    write_manifest(tmp_path, _manifest("claude-code", [
        ManifestEntry(path="old.md", version="1.0.0", sha256="1" * 64,
                      adapter="claude-code"),
        ManifestEntry(path="kept.md", version="1.0.0", sha256="2" * 64,
                      adapter="claude-code"),
    ]))
    incoming = _manifest("claude-code", [
        ManifestEntry(path="kept.md", version="1.0.0", sha256="2" * 64,
                      adapter="claude-code"),
    ])
    merged = merge_manifest(read_manifest(tmp_path), incoming)
    assert {e.path for e in merged.outputs} == {"kept.md"}


def test_legacy_rows_without_adapter_are_attributed_to_incoming(tmp_path):
    """Pre-merge manifests only ever held one adapter's rows, so an unlabelled
    row belongs to whoever is syncing — it must not be preserved forever."""
    (tmp_path / MANIFEST_FILENAME).write_text(json.dumps({
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_repo": "erpnext-ai-forge",
        "source_commit": "abc123",
        "source_files": [],
        "outputs": [{"path": "stale.md", "version": "1.0.0", "sha256": "9" * 64}],
        "adapter": {"name": "claude-code", "version": "0.1.0"},
        "rendered_at": "2026-07-30T00:00:00+00:00",
        "rendered_by": "forge 0.6.3",
    }))
    merged = merge_manifest(read_manifest(tmp_path), _manifest("claude-code", []))
    assert merged.outputs == []
