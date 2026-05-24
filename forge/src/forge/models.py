"""Typed dataclasses for canonical artifacts and discovery data.

These are the in-memory shape that loaders produce and renderers consume.
Kept intentionally minimal — fields are added as downstream consumers need them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


ArtifactKind = Literal["agent", "skill", "command", "tool", "policy"]
SkillClassification = Literal["F", "M"]


@dataclass
class CanonicalArtifact:
    """One parsed canonical file (md or yaml) — agents, skills, commands, policies."""

    id: str
    kind: ArtifactKind
    version: str
    status: str
    owners: list[str]
    trigger: str | None
    scope: list[str]
    foundational: bool
    last_reviewed: str | None
    security_score: int | None
    supersedes: list[str]
    source_path: Path
    source_commit: str | None
    body: str
    raw_frontmatter: dict[str, Any]
    domain: str | None = None  # only set for skills

    @property
    def short_commit(self) -> str:
        if self.source_commit:
            return self.source_commit[:7]
        return "unknown"


@dataclass
class ToolSpec:
    """A canonical/tools/*.yaml — kept separate from CanonicalArtifact because its
    schema is structured (inputs, outputs, safety_checks), not body Markdown."""

    id: str
    version: str
    wraps: str
    purpose: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    requires_confirmation: bool
    confirmation_token: str | None
    audit_severity: str
    safety_checks: list[dict[str, Any]]
    allowed_callers: list[str]
    source_path: Path
    raw: dict[str, Any]
    source_commit: str | None = None

    @property
    def short_commit(self) -> str:
        if self.source_commit:
            return self.source_commit[:7]
        return "unknown"


@dataclass
class DiscoverySnapshot:
    """Parsed discovery/data/*.json blob; passed into Jinja contexts for the
    per-app CLAUDE.md template and any skill that wants to cite real bench facts."""

    generated_at: str | None
    apps: dict[str, Any]              # apps-index.json
    hooks: dict[str, Any]              # hooks-index.json
    doctypes: dict[str, Any]           # doctype-index.json
    api_surface: dict[str, Any]        # api-surface.json
    override_map: dict[str, Any]       # override-map.json
    integrations: dict[str, Any]       # integrations-map.json
    anti_patterns: dict[str, Any]      # anti-pattern-findings.json
    site_config_keys: dict[str, Any]   # site-config-keys.json

    def custom_app_names(self) -> list[str]:
        return [a["name"] for a in self.apps.get("custom_apps", [])]

    def app(self, name: str) -> dict[str, Any] | None:
        for a in self.apps.get("custom_apps", []):
            if a["name"] == name:
                return a
        return None


@dataclass
class ForgeContext:
    """Shared render-time context. Injected into every Jinja template as `forge`,
    `bench`, `env` namespaces. Matches the variables referenced in
    adapters/*/templates/*.j2."""

    version: str
    source_commit: str
    rendered_at: datetime
    bench_path: Path
    primary_site: str
    env: dict[str, str] = field(default_factory=dict)
