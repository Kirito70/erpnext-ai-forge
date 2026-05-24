"""Tests for forge.settings_merge — deep merge per v0.2 Part B item 6."""

from __future__ import annotations

import json
from pathlib import Path

from forge.settings_merge import (
    ScalarConflict,
    deep_merge,
    merge_settings_json,
    write_settings_with_backup,
)


def test_deep_merge_dicts():
    existing = {"a": 1, "b": {"x": 1, "y": 2}}
    incoming = {"b": {"y": 99, "z": 3}, "c": 4}
    conflicts: list = []
    result = deep_merge(existing, incoming, conflicts=conflicts)
    assert result == {"a": 1, "b": {"x": 1, "y": 99, "z": 3}, "c": 4}
    # b.y was 2, becomes 99 — that's a scalar conflict
    assert len(conflicts) == 1
    assert conflicts[0].path == "b.y"
    assert conflicts[0].prior_value == 2
    assert conflicts[0].new_value == 99


def test_array_union_by_identity():
    existing = ["Bash(ls)", "Bash(git status)"]
    incoming = ["Bash(git diff)", "Bash(ls)"]  # ls already present
    result = deep_merge(existing, incoming)
    assert result == ["Bash(ls)", "Bash(git status)", "Bash(git diff)"]


def test_scalar_conflict_forge_wins():
    existing = "old-value"
    incoming = "new-value"
    conflicts: list = []
    result = deep_merge(existing, incoming, path="theme", conflicts=conflicts)
    assert result == "new-value"
    assert len(conflicts) == 1
    assert conflicts[0].prior_value == "old-value"


def test_no_conflict_when_scalars_equal():
    conflicts: list = []
    result = deep_merge("same", "same", conflicts=conflicts)
    assert result == "same"
    assert len(conflicts) == 0


def test_merge_settings_json_creates_if_missing(tmp_path):
    settings_path = tmp_path / "settings.json"  # does not exist
    fragments = [{"permissions": {"allow": ["Bash(ls)"]}}]
    merged, conflicts = merge_settings_json(settings_path, fragments)
    assert merged == {"permissions": {"allow": ["Bash(ls)"]}}
    assert conflicts == []


def test_merge_settings_json_deep_merges_existing(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "theme": "dark"}))
    fragments = [{"permissions": {"allow": ["Bash(git status)"]}}, {"theme": "light"}]
    merged, conflicts = merge_settings_json(settings_path, fragments)
    assert merged["permissions"]["allow"] == ["Bash(ls)", "Bash(git status)"]
    assert merged["theme"] == "light"
    assert len(conflicts) == 1
    assert conflicts[0].path == "theme"
    assert conflicts[0].prior_value == "dark"


def test_write_settings_creates_backup(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"existing": true}')
    backup = write_settings_with_backup(settings_path, {"new": True})
    assert backup is not None
    assert backup.name == "settings.json.forge-backup"
    assert json.loads(backup.read_text()) == {"existing": True}
    assert json.loads(settings_path.read_text()) == {"new": True}


def test_write_settings_no_backup_when_file_missing(tmp_path):
    settings_path = tmp_path / "settings.json"  # does not exist
    backup = write_settings_with_backup(settings_path, {"new": True})
    assert backup is None
    assert json.loads(settings_path.read_text()) == {"new": True}
