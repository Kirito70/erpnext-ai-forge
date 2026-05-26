"""Render canonical artifacts → per-tool output via Jinja templates.

Consumes:
  - adapter.yaml (mapping rules + output paths)
  - canonical/{agents,commands,skills,tools}/* (parsed via loader)
  - discovery/data/*.json (parsed via loader)
  - adapters/<tool>/templates/*.j2

Produces: a `RenderedArtifact` list describing what would be written and where.
The caller (sync engine) is responsible for actually writing to disk —
render() is pure; sync() handles the filesystem.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from forge import __version__ as forge_version
from forge.loader import (
    load_adapter_config,
    load_agents,
    load_commands,
    load_discovery,
    load_forge_config,
    load_skills,
    load_tools,
    repo_head_commit,
)
from forge.models import (
    CanonicalArtifact,
    DiscoverySnapshot,
    ForgeContext,
    ToolSpec,
)


@dataclass
class RenderedArtifact:
    """One file the renderer wants to write, plus its provenance."""

    tool: str
    source_path: Path             # canonical/<...>
    output_path: Path             # absolute path in the bench (or staging dir)
    content: str
    source_commit: str | None
    source_version: str
    artifact_id: str
    artifact_kind: str


def _resolve(template_str: str, ctx: dict[str, Any]) -> str:
    """Resolve simple `{{ env.VAR }}` / `{{ bench.path }}` substitutions in
    adapter.yaml strings. Used for output paths."""
    env = Environment(undefined=StrictUndefined, autoescape=False)
    return env.from_string(template_str).render(**ctx)


def _build_jinja_env(adapter_dir: Path) -> Environment:
    templates_dir = adapter_dir / "templates"
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(disabled_extensions=("md", "yaml", "yml", "j2", "json")),
        keep_trailing_newline=True,
        undefined=StrictUndefined,  # fail loudly on missing template variables
    )


def _build_forge_context(repo_root: Path, forge_cfg: dict[str, Any]) -> ForgeContext:
    bench_path_str = _resolve(forge_cfg["bench"]["path"], {"env": dict(os.environ)})
    primary_site = _resolve(forge_cfg["bench"]["primary_site"], {"env": dict(os.environ)})
    return ForgeContext(
        version=forge_version,
        source_commit=repo_head_commit(repo_root) or "uncommitted",
        rendered_at=datetime.now(timezone.utc),
        bench_path=Path(bench_path_str),
        primary_site=primary_site,
        env=dict(os.environ),
    )


def _derive_description(body: str, trigger: str | None) -> str:
    """Best-effort description: frontmatter trigger > first sentence of body > id."""
    if trigger:
        return trigger
    # First sentence of the first non-empty paragraph
    for para in body.split("\n\n"):
        para = para.strip()
        if not para or para.startswith("#"):
            continue
        first_sentence = para.split(".")[0].strip()
        return first_sentence[:200]
    return ""


def _artifact_to_template_dict(art: CanonicalArtifact) -> dict[str, Any]:
    """Shape a CanonicalArtifact for consumption by Jinja templates.

    Every field consumed by any template lives here so StrictUndefined never
    fires on a missing attribute. Frontmatter-derived fields fall back to
    sensible defaults derived from the body."""
    return {
        "id": art.id,
        "kind": art.kind,
        "version": art.version,
        "trigger": art.trigger or "",
        "scope": art.scope,
        "scope_agents": art.scope,
        "foundational": art.foundational,
        "domain": art.domain or "",
        "body": art.body.strip(),
        "source_commit": art.source_commit or "uncommitted",
        "tools": art.raw_frontmatter.get("tools"),
        "model": art.raw_frontmatter.get("model"),
        "description": art.raw_frontmatter.get("description") or _derive_description(
            art.body, art.trigger
        ),
        "argument_hint": art.raw_frontmatter.get("argument_hint"),
        "allowed_tools": art.raw_frontmatter.get("allowed_tools"),
        "triggers_agents": art.raw_frontmatter.get("triggers_agents", []),
    }


def _tool_to_template_dict(tool: ToolSpec) -> dict[str, Any]:
    return {
        "id": tool.id,
        "version": tool.version,
        "wraps": tool.wraps,
        "purpose": tool.purpose,
        "inputs": tool.inputs,
        "outputs": tool.outputs,
        "requires_confirmation": tool.requires_confirmation,
        "confirmation_token": tool.confirmation_token,
        "audit_severity": tool.audit_severity,
        "safety_checks": tool.safety_checks,
        "allowed_callers": tool.allowed_callers,
        "source_commit": tool.source_commit or "uncommitted",
    }


# ---------------------------------------------------------------------------
# Render entry point
# ---------------------------------------------------------------------------
def render(repo_root: Path, tool: str) -> list[RenderedArtifact]:
    """Render every artifact this adapter is responsible for, in memory.

    Returns a list of RenderedArtifact — caller writes them to disk."""
    adapter_cfg = load_adapter_config(repo_root, tool)
    forge_cfg = load_forge_config(repo_root)
    forge_ctx = _build_forge_context(repo_root, forge_cfg)
    discovery = load_discovery(repo_root)
    adapter_dir = repo_root / "adapters" / tool
    env = _build_jinja_env(adapter_dir)

    # Resolve adapter output paths. Each adapter declares its own paths;
    # claude-code uses `bench_claude_root`, cursor uses `rules_dir`, etc.
    # Resolve iteratively so later entries can reference earlier ones.
    output_paths_cfg = adapter_cfg.get("output_paths", {})
    resolved_paths: dict[str, Any] = {
        "bench_root": str(forge_ctx.bench_path),
        "bench_claude_root": str(forge_ctx.bench_path / ".claude"),
    }
    output_ctx = {
        "env": dict(os.environ),
        "output_paths": resolved_paths,
        "bench": {"primary_site": forge_ctx.primary_site},
    }
    # Up to 5 passes for forward references like
    # `rules_dir: "{{ output_paths.cursor_root }}/rules"`.
    for _pass in range(5):
        progress = False
        for key, value in output_paths_cfg.items():
            if key in resolved_paths or not isinstance(value, str):
                continue
            try:
                resolved_paths[key] = _resolve(value, output_ctx)
                progress = True
            except Exception:
                continue  # may resolve in a later pass
        if not progress:
            break
    # Pass through any non-string entries (lists, nested dicts e.g. per_app_claude_md)
    for key, value in output_paths_cfg.items():
        if key not in resolved_paths:
            resolved_paths[key] = value

    def resolve_path(template_str: str) -> Path:
        return Path(_resolve(template_str, output_ctx))

    rendered: list[RenderedArtifact] = []

    # --- Agents ---
    agents_dir = resolve_path(output_paths_cfg.get("agents_dir", ""))
    if "agents" in adapter_cfg.get("artifacts", {}):
        tmpl = env.get_template(adapter_cfg["artifacts"]["agents"]["template"])
        for agent in load_agents(repo_root):
            content = tmpl.render(
                artifact=_artifact_to_template_dict(agent),
                forge={
                    "version": forge_ctx.version,
                    "source_commit": forge_ctx.source_commit,
                    "rendered_at": forge_ctx.rendered_at.isoformat(),
                },
                bench={"primary_site": forge_ctx.primary_site},
            )
            rendered.append(
                RenderedArtifact(
                    tool=tool,
                    source_path=agent.source_path,
                    output_path=agents_dir / f"{agent.id}.md",
                    content=content,
                    source_commit=agent.source_commit,
                    source_version=agent.version,
                    artifact_id=agent.id,
                    artifact_kind="agent",
                )
            )

    # --- Commands ---
    commands_dir = resolve_path(output_paths_cfg.get("commands_dir", ""))
    if "commands" in adapter_cfg.get("artifacts", {}):
        tmpl = env.get_template(adapter_cfg["artifacts"]["commands"]["template"])
        for cmd in load_commands(repo_root):
            content = tmpl.render(
                artifact=_artifact_to_template_dict(cmd),
                forge={
                    "version": forge_ctx.version,
                    "source_commit": forge_ctx.source_commit,
                    "rendered_at": forge_ctx.rendered_at.isoformat(),
                },
                bench={"primary_site": forge_ctx.primary_site},
            )
            rendered.append(
                RenderedArtifact(
                    tool=tool,
                    source_path=cmd.source_path,
                    output_path=commands_dir / f"{cmd.id}.md",
                    content=content,
                    source_commit=cmd.source_commit,
                    source_version=cmd.version,
                    artifact_id=cmd.id,
                    artifact_kind="command",
                )
            )

    # --- Skills ---
    skills_dir = resolve_path(output_paths_cfg.get("skills_dir", ""))
    skills_cfg = adapter_cfg.get("artifacts", {}).get("skills")
    if skills_cfg:
        tmpl = env.get_template(skills_cfg["template"])
        for skill in load_skills(repo_root):
            content = tmpl.render(
                artifact=_artifact_to_template_dict(skill),
                forge={
                    "version": forge_ctx.version,
                    "source_commit": forge_ctx.source_commit,
                    "rendered_at": forge_ctx.rendered_at.isoformat(),
                },
                bench={"primary_site": forge_ctx.primary_site},
            )
            domain = skill.domain or "uncategorized"
            rendered.append(
                RenderedArtifact(
                    tool=tool,
                    source_path=skill.source_path,
                    output_path=skills_dir / domain / f"{skill.id}.md",
                    content=content,
                    source_commit=skill.source_commit,
                    source_version=skill.version,
                    artifact_id=skill.id,
                    artifact_kind="skill",
                )
            )

    # --- Tools (reference docs only — settings.json fragment is handled by sync) ---
    tools_cfg = adapter_cfg.get("artifacts", {}).get("tools")
    if tools_cfg and tools_cfg.get("template_doc"):
        tmpl = env.get_template(tools_cfg["template_doc"])
        # Prefer the adapter-declared `tools_dir`; fall back to the Claude Code
        # legacy default (`bench_claude_root/tools`) for backwards compatibility.
        tools_dir_template = output_paths_cfg.get("tools_dir")
        if tools_dir_template:
            tools_doc_dir = resolve_path(tools_dir_template)
        else:
            tools_doc_dir = (
                resolve_path(output_paths_cfg.get("bench_claude_root", "")) / "tools"
            )
        for tool_spec in load_tools(repo_root):
            content = tmpl.render(
                artifact=_tool_to_template_dict(tool_spec),
                forge={
                    "version": forge_ctx.version,
                    "source_commit": forge_ctx.source_commit,
                    "rendered_at": forge_ctx.rendered_at.isoformat(),
                },
                bench={"primary_site": forge_ctx.primary_site},
            )
            rendered.append(
                RenderedArtifact(
                    tool=tool,
                    source_path=tool_spec.source_path,
                    output_path=tools_doc_dir / f"{tool_spec.id}.md",
                    content=content,
                    source_commit=tool_spec.source_commit,
                    source_version=tool_spec.version,
                    artifact_id=tool_spec.id,
                    artifact_kind="tool",
                )
            )

    # --- Bench-root CLAUDE.md ---
    if "root_claude_md" in adapter_cfg.get("artifacts", {}):
        tmpl = env.get_template("claude-md-root.j2")
        content = tmpl.render(
            forge={
                "version": forge_ctx.version,
                "source_commit": forge_ctx.source_commit,
                "rendered_at": forge_ctx.rendered_at.isoformat(),
            },
            bench={"primary_site": forge_ctx.primary_site},
        )
        rendered.append(
            RenderedArtifact(
                tool=tool,
                source_path=repo_root / "canonical" / "agents" / "architect.md",
                output_path=resolve_path(output_paths_cfg.get("root_claude_md", "")),
                content=content,
                source_commit=forge_ctx.source_commit,
                source_version=forge_version,
                artifact_id="root-claude-md",
                artifact_kind="aggregate",
            )
        )

    # --- Per-app CLAUDE.md ---
    per_app_cfg = output_paths_cfg.get("per_app_claude_md", {})
    if per_app_cfg.get("apps"):
        tmpl = env.get_template("claude-md-per-app.j2")
        for app_name in per_app_cfg["apps"]:
            app_data = discovery.app(app_name)
            if not app_data:
                continue
            content = tmpl.render(
                app=app_data,
                forge={
                    "version": forge_ctx.version,
                    "source_commit": forge_ctx.source_commit,
                    "rendered_at": forge_ctx.rendered_at.isoformat(),
                },
                bench={"primary_site": forge_ctx.primary_site},
            )
            per_app_path = _resolve(
                per_app_cfg["base"],
                {**output_ctx, "app": app_name},
            )
            rendered.append(
                RenderedArtifact(
                    tool=tool,
                    source_path=repo_root / "discovery" / "INVENTORY.md",
                    output_path=Path(per_app_path),
                    content=content,
                    source_commit=forge_ctx.source_commit,
                    source_version=forge_version,
                    artifact_id=f"per-app-claude-md/{app_name}",
                    artifact_kind="aggregate",
                )
            )

    # --- Aggregate strategies (Cursor, OpenCode, Cline, Copilot, Codex, Antigravity) ---
    # Each entry in adapter.yaml `artifacts:` with strategy: aggregate emits one
    # output file rendered from the full canonical set. The template receives
    # `agents`, `commands`, `skills`, `tools`, `policies`, plus `forge`, `bench`,
    # and `discovery` (for per-app contexts).
    artifacts_cfg = adapter_cfg.get("artifacts", {})
    aggregate_entries = [
        (kind, spec)
        for kind, spec in artifacts_cfg.items()
        if isinstance(spec, dict) and spec.get("strategy") == "aggregate"
    ]
    if aggregate_entries:
        all_agents = [_artifact_to_template_dict(a) for a in load_agents(repo_root)]
        all_commands = [_artifact_to_template_dict(c) for c in load_commands(repo_root)]
        all_skills = [_artifact_to_template_dict(s) for s in load_skills(repo_root)]
        all_tools = [_tool_to_template_dict(t) for t in load_tools(repo_root)]
        for kind, spec in aggregate_entries:
            tmpl = env.get_template(spec["template"])
            content = tmpl.render(
                agents=all_agents,
                commands=all_commands,
                skills=all_skills,
                tools=all_tools,
                forge={
                    "version": forge_ctx.version,
                    "source_commit": forge_ctx.source_commit,
                    "rendered_at": forge_ctx.rendered_at.isoformat(),
                },
                bench={"primary_site": forge_ctx.primary_site},
                discovery={
                    "custom_apps": discovery.apps.get("custom_apps", []),
                    "anti_patterns": discovery.anti_patterns,
                },
            )
            output_path = resolve_path(spec["output"])
            rendered.append(
                RenderedArtifact(
                    tool=tool,
                    source_path=repo_root / "canonical",
                    output_path=output_path,
                    content=content,
                    source_commit=forge_ctx.source_commit,
                    source_version=forge_version,
                    artifact_id=f"aggregate/{kind}",
                    artifact_kind="aggregate",
                )
            )

    # --- Aggregate per-app strategy (Copilot's per-app applyTo, etc.) ---
    per_app_aggregates = [
        (kind, spec)
        for kind, spec in artifacts_cfg.items()
        if isinstance(spec, dict) and spec.get("strategy") == "aggregate_per_app"
    ]
    if per_app_aggregates:
        for kind, spec in per_app_aggregates:
            tmpl = env.get_template(spec["template"])
            for app_data in discovery.apps.get("custom_apps", []):
                app_name = app_data["name"]
                content = tmpl.render(
                    app=app_data,
                    forge={
                        "version": forge_ctx.version,
                        "source_commit": forge_ctx.source_commit,
                        "rendered_at": forge_ctx.rendered_at.isoformat(),
                    },
                    bench={"primary_site": forge_ctx.primary_site},
                )
                # Pass `app` as the full dict so adapter.yaml output strings can
                # use `{{ app.name }}` (and `{{ app.stack }}`, etc.).
                output_path = _resolve(
                    spec["output"],
                    {**output_ctx, "app": app_data, "app_name": app_name},
                )
                rendered.append(
                    RenderedArtifact(
                        tool=tool,
                        source_path=repo_root / "discovery" / "INVENTORY.md",
                        output_path=Path(output_path),
                        content=content,
                        source_commit=forge_ctx.source_commit,
                        source_version=forge_version,
                        artifact_id=f"aggregate-per-app/{kind}/{app_name}",
                        artifact_kind="aggregate",
                    )
                )

    return rendered


def render_summary(rendered: list[RenderedArtifact]) -> dict[str, int]:
    """Group rendered artifacts by kind for terse reporting."""
    out: dict[str, int] = {}
    for r in rendered:
        out[r.artifact_kind] = out.get(r.artifact_kind, 0) + 1
    return out
