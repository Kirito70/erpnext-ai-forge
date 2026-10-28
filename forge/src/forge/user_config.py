"""The overlay config: company and machine settings kept out of the repo.

`forge.config.example.yaml` is tracked and company-neutral. Everything that
names a company, its apps or a machine lives in ONE overlay file, the first
that exists of:

    1. $FORGE_CONFIG
    2. <repo>/forge.config.yaml      (gitignored; a dev checkout)
    3. ~/.forge.yaml                 (installed copies, which are read-only)

`$FORGE_CONFIG` wins even when the file it names does not exist, so tests and
scripts can point it at nothing and get the bare defaults.

Merge rule: mappings merge key by key; a list or scalar in the overlay
replaces the default outright. Lists do not concatenate — an overlay that says
`managed_apps: [a]` means exactly `[a]`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

DEFAULTS_FILE = "forge.config.example.yaml"
LOCAL_FILE = "forge.config.yaml"
HOME_FILE = ".forge.yaml"
ENV_VAR = "FORGE_CONFIG"


def overlay_path(repo_root: Path) -> Path:
    """Where the overlay is read from and written to (it may not exist yet)."""
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser()
    local = repo_root / LOCAL_FILE
    if local.is_file():
        return local
    return Path.home() / HOME_FILE


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """New dict: `overlay` on top of `base`. Neither input is modified."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def read_overlay(repo_root: Path) -> dict[str, Any]:
    return read_yaml(overlay_path(repo_root))


def write_bench_list(repo_root: Path, key: str, values: list[str]) -> Path:
    """Set `bench.<key>` in the overlay, preserving the file's comments.

    A hand-kept overlay is often commented, and a PyYAML round trip would drop
    every comment, so an existing `<key>:` block is rewritten in place. Only
    when the key is absent does the file go through a full load-and-dump.
    """
    path = overlay_path(repo_root)
    text = path.read_text() if path.is_file() else ""
    match = re.search(
        rf"^(?P<indent>[ \t]+){re.escape(key)}:[^\n]*\n(?P<items>(?:(?P=indent)[ \t]*-[^\n]*\n)*)",
        text,
        re.M,
    )
    if match and "bench" in read_yaml(path):
        indent = match.group("indent")
        if values:
            body = f"{indent}{key}:\n" + "".join(f"{indent}  - {v}\n" for v in values)
        else:
            # Empty, not absent: absent would mean "no restriction".
            body = f"{indent}{key}: []\n"
        start, end = match.span()
        path.write_text(text[:start] + body + text[end:])
        return path
    return write_overlay(repo_root, {"bench": {key: list(values)}})


def write_overlay(repo_root: Path, updates: dict[str, Any]) -> Path:
    """Merge `updates` into the overlay and save it. Comments are not kept."""
    path = overlay_path(repo_root)
    merged = deep_merge(read_yaml(path), updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# erpnext-ai-forge settings — overlay on forge.config.example.yaml.\n"
        "# Written by `forge setup` / `forge apps`; safe to edit by hand.\n"
    )
    path.write_text(header + yaml.safe_dump(merged, sort_keys=False, default_flow_style=False))
    return path
