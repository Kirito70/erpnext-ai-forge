"""Typed dataclasses for canonical artifacts and discovery data.

These are the in-memory shape that loaders produce and renderers consume.
Kept intentionally minimal — fields are added as downstream consumers need them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


ArtifactKind = Literal["agent", "skill", "command", "tool", "policy", "harness"]
SkillClassification = Literal["F", "M"]
Provenance = Literal["internal", "external"]
PROVENANCE_VALUES: tuple[str, ...] = ("internal", "external")


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
    provenance: Provenance = "internal"
    """`internal` (authored in this repo) or `external` (imported from
    elsewhere). Only `external` artifacts need a `canonical/skills-lock.json`
    entry — see forge/src/forge/skills_lock.py.

    Closed on purpose. Three call sites ask this field three different
    questions — `!= "external"` to skip the lockfile check, `== "external"` to
    pick the source, `== "internal"` to pick the label — so a third value does
    not land somewhere consistent, it lands in the gap between them: a skill
    written `External` was exempt from verification while still displaying as
    external. Validated in `loader.py`, where the frontmatter is read."""
    source_url: str | None = None
    source_ref: str | None = None

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
                found: dict[str, Any] = a
                return found
        return None


@dataclass(frozen=True)
class HarnessScript:
    """One shell file the harness ships."""

    id: str
    source_path: Path        # canonical/harness/scripts/<id>.sh.j2
    filename: str            # <id>.sh — what it is called in the target
    mode: int                # 0o755 for executables, 0o644 for sourced files
    purpose: str


@dataclass(frozen=True)
class HarnessConfig:
    """One tool-config file the harness ships (ruff.toml, and later friends).

    Separate from HarnessScript because the two differ in the way that matters
    to rendering: every script lands in a single `scripts_dir`, while a config
    has to land where its tool looks for it. Ruff resolves configuration from
    the directory a check is invoked in, so a `scripts/harness/ruff.toml` would
    be silently ignored. Hence `output_path`, relative to the target root.
    """

    id: str
    source_path: Path        # canonical/harness/<name>.j2
    output_path: str         # target-root-relative, e.g. "ruff.toml"
    mode: int
    purpose: str


@dataclass(frozen=True)
class HookSpec:
    """One hook: an event, and the script it runs."""

    id: str
    fires_on: str            # forge-neutral: file_edit | session_stop
    script: str              # id of a HarnessScript
    policy: str              # blocking | advisory
    timeout_seconds: int
    args: tuple[str, ...] = ()
    loop_guard: str | None = None
    description: str = ""


@dataclass(frozen=True)
class HarnessSpec:
    """canonical/harness/ as a whole: scripts, hooks, gates, permissions."""

    version: str
    scripts: tuple[HarnessScript, ...]
    hooks: tuple[HookSpec, ...]
    gates: dict[str, Any]        # gates.yaml -> stacks
    permissions: dict[str, Any]  # permissions.yaml
    source_paths: tuple[Path, ...]
    configs: tuple[HarnessConfig, ...] = ()
    """Tool-config files rendered next to the scripts. Defaults to empty so a
    canonical checkout predating `configs:` still loads."""

    def script(self, script_id: str) -> HarnessScript | None:
        for s in self.scripts:
            if s.id == script_id:
                return s
        return None

    def profile(self, stack_profile: str) -> dict[str, Any]:
        """Gate table for one stack, or an empty one.

        Empty rather than raising: a target whose profile has no gates yet
        should render a harness that does nothing, not fail to render.
        """
        prof: dict[str, Any] = self.gates.get(stack_profile) or {}
        return prof


@dataclass(frozen=True)
class Target:
    """One repository forge renders into.

    Until now there was exactly one — the bench — so its settings sat at the top
    level of forge.config.yaml under `bench:` and seven separate call sites each
    re-did the same `cfg["bench"]["path"].replace(env…)` substitution. Naming the
    concept lets the forge repo become a target too, which is the point: the repo
    that generates everyone else's harness had none of its own, and hand-writing
    one would guarantee the two drift.

    `stack_profile` is what makes a single canonical harness serve repos that
    share no tooling. The bench runs `bench run-tests`; this repo runs pytest and
    mypy. Same scripts, different gate table, resolved by profile.
    """

    name: str
    root: Path
    stack_profile: str
    enabled_tools: list[str]
    primary_site: str | None = None
    owned_remotes: frozenset[str] = frozenset()
    managed_apps: tuple[str, ...] | None = None
    lint_apps: tuple[str, ...] | None = None
    """Apps whose Python the linter is allowed to see. None disables scoping.

    Deliberately NOT derived from either half of the write guard, because
    neither half is a lint-scope answer on its own:

    - `owned_remotes` answers "may we commit here". On this bench the upstream
      apps are forks into our own org (frappe -> novizna_framework,
      erpnext -> noviznaerp, crm -> novizna_crm_core, hrms -> novizna_hrms,
      press -> novizna_press_core), so remote ownership says yes to all five;
      lint scope must say no.
    - `upstream_apps` names the Frappe-ecosystem apps and omits third-party
      ones we equally never lint (raven, cargo_management, changemakers).

    The guard combines the two (`is_upstream or is_foreign`) and is exact; it
    is only their individual use that would be wrong here. Kept as its own list
    anyway, since "may we write here" and "is this ours to fix" are different
    questions that will not always have the same answer.

    An allow-list rather than a deny-list so a newly vendored app is loud
    (linted, noisy) rather than quiet (skipped, and nobody notices)."""
    renders: frozenset[str] | None = None
    """Which adapter artifact groups this target receives; None means all.

    Not every target wants every artifact. The canonical agents, skills, tools
    and per-app notes are about a Frappe bench — rendering `bench-migrate` and
    the ERPNext accounting skill into a Python CLI repo would be actively
    misleading, and per-app files would invent apps that do not exist here.

    Scoping is by adapter.yaml artifact-group name (`agents`, `commands`,
    `skills`, `tools`, `root_claude_md`, `per_app_claude_md`, …).
    """

    self_target: bool = False
    """True for the forge repo itself.

    Ownership is not in question for a repo we are already running inside, so
    the foreign-write confirmation is skipped. Hand-edit detection and the
    security gate still apply — those protect against forge, not against
    strangers.
    """


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
