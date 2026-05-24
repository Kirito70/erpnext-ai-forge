"""Load canonical/* and discovery/* into typed dataclasses.

Used by renderer, sync engine, scorer, validator. Read-only — never mutates
the canonical layer.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import frontmatter
import yaml

from forge.models import (
    CanonicalArtifact,
    DiscoverySnapshot,
    ToolSpec,
)


# ---------------------------------------------------------------------------
# Repo root resolution
# ---------------------------------------------------------------------------
def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` (default: cwd) until a `forge.config.yaml` is found."""
    current = (start or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        if (parent / "forge.config.yaml").is_file():
            return parent
    raise FileNotFoundError(
        "Could not locate erpnext-ai-forge repo root (no forge.config.yaml found)."
    )


def repo_head_commit(repo_root: Path) -> str | None:
    """Return the current HEAD commit sha, or None if not a git repo / no commits."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def file_commit(repo_root: Path, file_path: Path) -> str | None:
    """Return the last commit sha that touched `file_path` (relative to repo_root)."""
    try:
        rel = file_path.relative_to(repo_root)
    except ValueError:
        return None
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", str(rel)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


# ---------------------------------------------------------------------------
# Canonical artifact loaders
# ---------------------------------------------------------------------------
def _parse_markdown_artifact(
    path: Path, kind: str, repo_root: Path
) -> CanonicalArtifact:
    """Parse a Markdown file with YAML frontmatter into a CanonicalArtifact."""
    post = frontmatter.load(path)
    fm = post.metadata or {}

    # `id` must match basename for unique linking
    artifact_id = fm.get("id") or path.stem
    if artifact_id != path.stem:
        # tolerate but log; downstream validator catches it
        pass

    return CanonicalArtifact(
        id=str(artifact_id),
        kind=fm.get("kind", kind),
        version=str(fm.get("version", "0.0.0")),
        status=str(fm.get("status", "stable")),
        owners=list(fm.get("owners", [])),
        trigger=fm.get("trigger"),
        scope=list(fm.get("scope", [])),
        foundational=bool(fm.get("foundational", False)),
        last_reviewed=fm.get("last_reviewed"),
        security_score=fm.get("security_score"),
        supersedes=list(fm.get("supersedes", [])),
        source_path=path,
        source_commit=file_commit(repo_root, path),
        body=post.content,
        raw_frontmatter=fm,
        domain=fm.get("domain"),
    )


def load_agents(repo_root: Path) -> list[CanonicalArtifact]:
    agents_dir = repo_root / "canonical" / "agents"
    return sorted(
        (_parse_markdown_artifact(p, "agent", repo_root) for p in agents_dir.glob("*.md")),
        key=lambda a: a.id,
    )


def load_commands(repo_root: Path) -> list[CanonicalArtifact]:
    cmd_dir = repo_root / "canonical" / "commands"
    return sorted(
        (_parse_markdown_artifact(p, "command", repo_root) for p in cmd_dir.glob("*.md")),
        key=lambda a: a.id,
    )


def load_skills(repo_root: Path) -> list[CanonicalArtifact]:
    """Recursively load canonical/skills/<domain>/*.md."""
    skills_dir = repo_root / "canonical" / "skills"
    out: list[CanonicalArtifact] = []
    for path in sorted(skills_dir.rglob("*.md")):
        if path.name.startswith("_"):
            continue
        artifact = _parse_markdown_artifact(path, "skill", repo_root)
        # infer domain from parent dir if not set in frontmatter
        if not artifact.domain:
            artifact.domain = path.parent.name
        out.append(artifact)
    return out


def load_policies(repo_root: Path) -> list[CanonicalArtifact]:
    """Load canonical/policies/*.md (the yaml one — security-scoring — is loaded
    separately via load_security_scoring_yaml)."""
    pol_dir = repo_root / "canonical" / "policies"
    return sorted(
        (_parse_markdown_artifact(p, "policy", repo_root) for p in pol_dir.glob("*.md")),
        key=lambda a: a.id,
    )


def load_security_scoring_yaml(repo_root: Path) -> dict[str, Any]:
    """Load canonical/policies/security-scoring.yaml as a plain dict (no Markdown body)."""
    path = repo_root / "canonical" / "policies" / "security-scoring.yaml"
    with path.open() as f:
        return yaml.safe_load(f)


def load_tools(repo_root: Path) -> list[ToolSpec]:
    tools_dir = repo_root / "canonical" / "tools"
    out: list[ToolSpec] = []
    for path in sorted(tools_dir.glob("*.yaml")):
        with path.open() as f:
            data = yaml.safe_load(f)
        out.append(
            ToolSpec(
                id=str(data.get("id", path.stem)),
                version=str(data.get("version", "0.0.0")),
                wraps=str(data.get("wraps", "")),
                purpose=str(data.get("purpose", "")),
                inputs=data.get("inputs", {}) or {},
                outputs=data.get("outputs", {}) or {},
                requires_confirmation=bool(data.get("requires_confirmation", False)),
                confirmation_token=data.get("confirmation_token"),
                audit_severity=str(data.get("audit_severity", "low")),
                safety_checks=list(data.get("safety_checks", [])),
                allowed_callers=list(data.get("allowed_callers", [])),
                source_path=path,
                raw=data,
                source_commit=file_commit(repo_root, path),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Discovery loader
# ---------------------------------------------------------------------------
def _load_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as f:
        return json.load(f)


def load_discovery(repo_root: Path) -> DiscoverySnapshot:
    data_dir = repo_root / "discovery" / "data"
    return DiscoverySnapshot(
        generated_at=_load_json_or_empty(data_dir / "apps-index.json").get("generated_at"),
        apps=_load_json_or_empty(data_dir / "apps-index.json"),
        hooks=_load_json_or_empty(data_dir / "hooks-index.json"),
        doctypes=_load_json_or_empty(data_dir / "doctype-index.json"),
        api_surface=_load_json_or_empty(data_dir / "api-surface.json"),
        override_map=_load_json_or_empty(data_dir / "override-map.json"),
        integrations=_load_json_or_empty(data_dir / "integrations-map.json"),
        anti_patterns=_load_json_or_empty(data_dir / "anti-pattern-findings.json"),
        site_config_keys=_load_json_or_empty(data_dir / "site-config-keys.json"),
    )


# ---------------------------------------------------------------------------
# Adapter config loader
# ---------------------------------------------------------------------------
def load_adapter_config(repo_root: Path, tool: str) -> dict[str, Any]:
    """Load adapters/<tool>/adapter.yaml as a plain dict."""
    path = repo_root / "adapters" / tool / "adapter.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Adapter config not found: {path}")
    with path.open() as f:
        return yaml.safe_load(f)


def load_forge_config(repo_root: Path) -> dict[str, Any]:
    """Load forge.config.yaml as a plain dict."""
    path = repo_root / "forge.config.yaml"
    with path.open() as f:
        return yaml.safe_load(f)
