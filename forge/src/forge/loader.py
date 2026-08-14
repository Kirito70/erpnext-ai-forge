"""Load canonical/* and discovery/* into typed dataclasses.

Used by renderer, sync engine, scorer, validator. Read-only — never mutates
the canonical layer.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import frontmatter
import yaml

from forge.models import (
    CanonicalArtifact,
    DiscoverySnapshot,
    HarnessConfig,
    HarnessScript,
    HarnessSpec,
    HookSpec,
    Target,
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
    # Annotated because `post.metadata` is untyped: without this every
    # `fm.get(...)` below is `object`, and each one becomes a mypy error at the
    # CanonicalArtifact constructor. Frontmatter is arbitrary YAML, so `Any` is
    # the honest type — the validator checks the shape, not the type checker.
    fm: dict[str, Any] = post.metadata or {}

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
        provenance=str(fm.get("provenance", "internal")),
        source_url=fm.get("source_url"),
        source_ref=fm.get("source_ref"),
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


def load_app_notes(repo_root: Path) -> dict[str, CanonicalArtifact]:
    """Load ``canonical/apps/<app>.md`` — hand-authored per-app knowledge.

    Keyed by app name so a template can look up its own notes. This is the
    editable half of a per-app instruction file: the generator supplies the
    facts it can derive from discovery, and everything a human knows about the
    app that no scanner can infer lives here.

    An app with no file simply renders without a notes section — a missing
    entry is normal, not an error.
    """
    apps_dir = repo_root / "canonical" / "apps"
    if not apps_dir.is_dir():
        return {}
    return {
        p.stem: _parse_markdown_artifact(p, "app-notes", repo_root)
        for p in sorted(apps_dir.glob("*.md"))
        if not p.name.startswith("_")
    }


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
        data: dict[str, Any] = yaml.safe_load(f) or {}
    return data


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
        data: dict[str, Any] = json.load(f)
    return data


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
        adapter_cfg: dict[str, Any] = yaml.safe_load(f) or {}
    return adapter_cfg


def load_forge_config(repo_root: Path) -> dict[str, Any]:
    """Load forge.config.yaml as a plain dict."""
    path = repo_root / "forge.config.yaml"
    with path.open() as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}
    return cfg


def load_harness(repo_root: Path) -> HarnessSpec | None:
    """Parse canonical/harness/. Returns None when the directory is absent.

    None rather than raising, so a checkout without a harness still renders
    everything else — the harness is additive, not a precondition.
    """
    base = repo_root / "canonical" / "harness"
    spec_path = base / "harness.yaml"
    if not spec_path.is_file():
        return None

    with spec_path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    sources = [spec_path]

    def _read_yaml(name: str) -> dict[str, Any]:
        path = base / name
        if not path.is_file():
            return {}
        sources.append(path)
        with path.open() as fh:
            data: dict[str, Any] = yaml.safe_load(fh) or {}
        return data

    gates = _read_yaml("gates.yaml").get("stacks") or {}
    permissions = _read_yaml("permissions.yaml")

    scripts: list[HarnessScript] = []
    for entry in raw.get("scripts") or []:
        rel = entry["file"]
        source = base / rel
        sources.append(source)
        # `scripts/gates.sh.j2` -> `gates.sh`. The .j2 is a rendering detail;
        # the target sees a plain shell file.
        filename = Path(rel).name
        if filename.endswith(".j2"):
            filename = filename[: -len(".j2")]
        scripts.append(
            HarnessScript(
                id=str(entry["id"]),
                source_path=source,
                filename=filename,
                mode=int(str(entry.get("mode", "0755")), 8),
                purpose=str(entry.get("purpose", "")),
            )
        )

    configs: list[HarnessConfig] = []
    for entry in raw.get("configs") or []:
        rel = entry["file"]
        source = base / rel
        sources.append(source)
        # Unlike scripts, the landing place is declared rather than derived:
        # a config has to sit where its tool looks for it.
        configs.append(
            HarnessConfig(
                id=str(entry["id"]),
                source_path=source,
                output_path=str(entry["output_path"]),
                mode=int(str(entry.get("mode", "0644")), 8),
                purpose=str(entry.get("purpose", "")),
            )
        )

    hooks = tuple(
        HookSpec(
            id=str(h["id"]),
            fires_on=str(h["fires_on"]),
            script=str(h["script"]),
            policy=str(h.get("policy", "advisory")),
            timeout_seconds=int(h.get("timeout_seconds", 120)),
            args=tuple(str(a) for a in (h.get("args") or ())),
            loop_guard=h.get("loop_guard"),
            description=str(h.get("description", "")),
        )
        for h in (raw.get("hooks") or [])
    )

    return HarnessSpec(
        version=str(raw.get("version", "0.0.0")),
        scripts=tuple(scripts),
        hooks=hooks,
        gates=gates,
        permissions=permissions,
        source_paths=tuple(sources),
        configs=tuple(configs),
    )


DEFAULT_TARGET = "bench"


def resolve_config_str(value: str, env: dict[str, str] | None = None) -> str:
    """Expand `{{ env.VAR }}` in a config string.

    Every consumer of `bench.path` used to inline this. Sharing it means a
    target's root is expanded the same way no matter who asks.
    """
    from jinja2 import Environment, StrictUndefined

    jenv = Environment(undefined=StrictUndefined, autoescape=False)
    return jenv.from_string(value).render(env=env if env is not None else dict(os.environ))


def load_targets(repo_root: Path, forge_cfg: dict[str, Any] | None = None) -> dict[str, Target]:
    """Every target declared in forge.config.yaml, keyed by name.

    Back-compat is deliberate: a config carrying only the original `bench:`
    block still yields exactly one target named "bench", with the same root,
    same tools, same behaviour. Nothing has to be migrated for sync to keep
    working, and `targets:` is purely additive.
    """
    cfg = forge_cfg if forge_cfg is not None else load_forge_config(repo_root)
    env = dict(os.environ)

    # `bench:` is the original single-target shape and stays authoritative for
    # the bench. `targets:` is additive on top, so adding a second target does
    # not require migrating (or re-commenting) the block that already works.
    declared: dict[str, Any] = {}
    if cfg.get("bench"):
        declared[DEFAULT_TARGET] = {"stack_profile": "frappe", **dict(cfg["bench"])}
    for name, raw in (cfg.get("targets") or {}).items():
        declared[name] = {**declared.get(name, {}), **(raw or {})}

    targets: dict[str, Target] = {}
    for name, raw in declared.items():
        raw = raw or {}
        # `root` is the new spelling; `path` is what `bench:` called it.
        root_str = raw.get("root") or raw.get("path")
        if not root_str:
            raise ValueError(
                f"target '{name}' declares neither `root:` nor `path:` in "
                f"forge.config.yaml. A target with no root has nowhere to render to."
            )
        root_str = resolve_config_str(str(root_str), env)
        if not root_str.strip():
            raise ValueError(
                f"target '{name}': root resolved to an empty string. Check the "
                f"environment variable it interpolates."
            )
        root = Path(root_str)
        if not root.is_absolute():
            # "." for the self target, and any relative path, is relative to the
            # forge repo — not to the cwd, which changes per invocation.
            root = (repo_root / root).resolve()

        site = raw.get("primary_site")
        managed = raw.get("managed_apps")
        lint = raw.get("lint_apps")
        targets[name] = Target(
            name=name,
            root=root,
            stack_profile=raw.get("stack_profile", "frappe"),
            enabled_tools=list(raw.get("enabled_tools") or cfg.get("enabled_tools") or []),
            primary_site=resolve_config_str(str(site), env) if site else None,
            owned_remotes=frozenset(raw.get("owned_remotes") or []),
            managed_apps=tuple(managed) if managed else None,
            lint_apps=tuple(lint) if lint else None,
            renders=frozenset(raw["renders"]) if raw.get("renders") is not None else None,
            self_target=bool(raw.get("self_target", False)),
        )
    return targets


def load_target(repo_root: Path, name: str | None = None,
                forge_cfg: dict[str, Any] | None = None) -> Target:
    """One target by name, defaulting to the bench."""
    targets = load_targets(repo_root, forge_cfg)
    key = name or DEFAULT_TARGET
    if key not in targets:
        known = ", ".join(sorted(targets)) or "none"
        raise KeyError(f"unknown target '{key}'. Declared targets: {known}.")
    return targets[key]
