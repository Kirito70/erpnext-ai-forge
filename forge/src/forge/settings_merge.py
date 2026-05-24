"""Deep-merge logic for `.claude/settings.json` per v0.2 Part B item 6.

Rules:
  - Top-level keys: deep merge
  - Array values: union by identity (no dedup of unrelated entries)
  - Conflicting scalars: forge's value wins; prior value logged
  - `.claude/settings.json.forge-backup` written before merge
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ScalarConflict:
    """Recorded when forge overrides a scalar set by hand-edit / prior sync."""

    path: str         # dotted JSON path, e.g. "permissions.defaultMode"
    prior_value: Any
    new_value: Any


def deep_merge(
    existing: Any,
    incoming: Any,
    *,
    path: str = "",
    conflicts: list[ScalarConflict] | None = None,
) -> Any:
    """Merge `incoming` into `existing` per the rules above.

    Returns the merged value. Records scalar overrides in `conflicts`.
    """
    if conflicts is None:
        conflicts = []

    # Both dicts: recurse key-wise
    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged: dict[str, Any] = dict(existing)
        for key, val in incoming.items():
            child_path = f"{path}.{key}" if path else key
            if key in merged:
                merged[key] = deep_merge(
                    merged[key], val, path=child_path, conflicts=conflicts
                )
            else:
                merged[key] = val
        return merged

    # Both lists: union by identity (preserve insertion order; dedupe exact dupes)
    if isinstance(existing, list) and isinstance(incoming, list):
        merged_list = list(existing)
        for item in incoming:
            if item not in merged_list:
                merged_list.append(item)
        return merged_list

    # Scalar conflict: forge wins, but record the prior value
    if existing != incoming:
        conflicts.append(
            ScalarConflict(path=path or "(root)", prior_value=existing, new_value=incoming)
        )
    return incoming


def merge_settings_json(
    bench_settings_path: Path,
    incoming_fragments: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[ScalarConflict]]:
    """Load the existing settings.json (or {} if none), deep-merge each
    fragment in order, return (final dict, conflicts list).

    The caller writes the result + backs up the prior file.
    """
    if bench_settings_path.is_file():
        existing = json.loads(bench_settings_path.read_text())
    else:
        existing = {}

    conflicts: list[ScalarConflict] = []
    merged = existing
    for fragment in incoming_fragments:
        merged = deep_merge(merged, fragment, conflicts=conflicts)

    return merged, conflicts


def write_settings_with_backup(
    bench_settings_path: Path,
    merged: dict[str, Any],
) -> Path | None:
    """Write `merged` to `bench_settings_path`. If a prior file exists, write
    a sibling `.forge-backup` first. Returns the backup path (or None)."""
    backup_path: Path | None = None
    if bench_settings_path.is_file():
        backup_path = bench_settings_path.with_suffix(
            bench_settings_path.suffix + ".forge-backup"
        )
        shutil.copy2(bench_settings_path, backup_path)

    bench_settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = bench_settings_path.with_suffix(bench_settings_path.suffix + ".tmp")
    tmp.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")
    tmp.replace(bench_settings_path)
    return backup_path
