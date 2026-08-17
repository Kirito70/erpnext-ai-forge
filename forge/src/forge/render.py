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

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined, select_autoescape

from forge import __version__ as forge_version
from forge.loader import (
    commit_date,
    file_last_commit,
    load_adapter_config,
    load_agents,
    load_app_notes,
    load_commands,
    load_discovery,
    load_forge_config,
    load_harness,
    load_policies,
    load_skills,
    load_target,
    load_tools,
    repo_head_commit,
)
from forge.models import (
    CanonicalArtifact,
    ForgeContext,
    HarnessSpec,
    Target,
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
    mode: int | None = None
    """POSIX permission bits, e.g. 0o755. `None` leaves the umask default.

    Only set for artifacts that must be executable — the harness hook scripts.
    Everything else is Markdown or JSON that nothing execs, so it stays None
    rather than pinning a mode we would then have to keep correct.
    """


def _resolve(template_str: str, ctx: dict[str, Any]) -> str:
    """Resolve simple `{{ env.VAR }}` / `{{ bench.path }}` substitutions in
    adapter.yaml strings. Used for output paths."""
    env = Environment(undefined=StrictUndefined, autoescape=False)
    return env.from_string(template_str).render(**ctx)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _source_provenance(
    repo_root: Path, source: Path, forge_ctx: ForgeContext
) -> tuple[str, str]:
    """`(commit, timestamp)` describing when `source` last changed.

    Falls back to the sync-run values when the file is untracked or git is
    unavailable — a new canonical file has no commit yet, and a footer is not
    worth failing a sync over.
    """
    try:
        rel = str(source.relative_to(repo_root))
    except ValueError:
        return forge_ctx.source_commit or "uncommitted", forge_ctx.rendered_at.isoformat()
    found = file_last_commit(repo_root, rel)
    if found is None:
        return forge_ctx.source_commit or "uncommitted", forge_ctx.rendered_at.isoformat()
    return found


def _unlinted_apps(target: Target, lint_apps: list[str]) -> list[str]:
    """Every app directory in the target that `lint_apps` does not name.

    Read from the filesystem rather than from `upstream_apps`, which lists only
    the Frappe-ecosystem apps and would leave third-party ones (raven,
    cargo_management, changemakers) linted.

    Rendering the inverse of an allow-list means the generated exclude is a
    snapshot: an app vendored into the bench after the last sync is absent from
    it and therefore gets linted. That is the failure direction we want — a
    noisy gate prompts a re-sync, whereas silently skipping a new app is a gap
    nobody notices.
    """
    apps_dir = target.root / "apps"
    if not apps_dir.is_dir():
        return []
    allowed = set(lint_apps)
    return sorted(
        p.name
        for p in apps_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name not in allowed
    )


def render_gate_cmd(cmd: str, site: str = "") -> str:
    """Turn a gates.yaml `cmd` into shell, substituting its placeholders.

    `{file}`, `{app}`, `{app_dir}`, `{js_dir}` expand to shell expressions
    rather than baked-in literals: `{file}` becomes `"$FILE"` so one rendered
    script handles every file, and the rest call the helpers in common.sh so
    the app is derived from the path at run time. Baking those in at render
    time would need one script per app.

    `{app_dir}` and `{js_dir}` are not interchangeable. `{app_dir}` is the
    Frappe app (`apps/<app>`); `{js_dir}` is the nearest package.json above the
    file. They coincide only when an app keeps its JS workspace at its root —
    novizna_pos does not, so a frontend gate given `{app_dir}` fails on every
    edit. Frontend gates want `{js_dir}`; `bench --app` wants `{app}`.

    `{site}` is different: it is a per-TARGET constant (`FORGE_PRIMARY_SITE`),
    known at render time and the same for every invocation of the script, so
    it is substituted as a literal. Left unsubstituted, `bench --site {site}
    run-tests` would run with `{site}` as a literal, nonexistent site name —
    this was shipped that way until caught on the first real sync against the
    Novizna bench.
    """
    return (
        cmd.replace("{file}", '"$(_abs_of "$FILE")"')
        .replace("{app_dir}", '"$(_app_dir_of "$FILE")"')
        .replace("{js_dir}", '"$(_js_dir_of "$FILE")"')
        .replace("{app}", '"$(_app_of "$FILE")"')
        .replace("{site}", site)
    )


def _build_jinja_env(adapter_dir: Path, repo_root: Path) -> Environment:
    """Jinja env for one adapter, with `adapters/_shared/templates` as a fallback.

    Adapter-local templates win, so an adapter can still override a shared
    partial by name. The shared dir exists so cross-cutting blocks (the vault
    ticketing contract, for one) are authored once instead of drifting across
    seven root templates.
    """
    templates_dir = adapter_dir / "templates"
    shared_dir = repo_root / "adapters" / "_shared" / "templates"
    # Harness sources come last so an adapter can still override a script by
    # name — same precedence rule the shared dir already follows.
    harness_dir = repo_root / "canonical" / "harness"
    env = Environment(
        loader=ChoiceLoader(
            [
                FileSystemLoader(str(templates_dir)),
                FileSystemLoader(str(shared_dir)),
                FileSystemLoader(str(harness_dir)),
            ]
        ),
        autoescape=select_autoescape(disabled_extensions=("md", "yaml", "yml", "j2", "json")),
        keep_trailing_newline=True,
        undefined=StrictUndefined,  # fail loudly on missing template variables
    )
    env.filters["render_gate_cmd"] = render_gate_cmd
    return env


# The three ledger files, split by lifecycle. `LEDGER-pending.md` is read on
# every build session; keeping finished work out of it is a saving paid on every
# ticket, forever. Adding a fourth (e.g. blocked) needs only a row here.
LEDGER_PHASES: list[dict[str, Any]] = [
    {
        "id": "proposed",
        "title": "Proposed & Gap",
        "states": ["proposed", "gap"],
        "blurb": (
            "Tickets that have been filed but not yet accepted into the plan, "
            "including gap tickets raised during review. Nothing here is being "
            "built."
        ),
    },
    {
        "id": "pending",
        "title": "Pending",
        "states": [
            "todo", "claimed", "in_progress", "blocked", "gates_green", "reviewed",
        ],
        "blurb": (
            "Accepted work, in flight. **Read this file first** — it is the only "
            "ledger a build session normally needs, and it is kept small on "
            "purpose."
        ),
    },
    {
        "id": "done",
        "title": "Done",
        "states": ["done", "abandoned"],
        "blurb": (
            "Terminal states, append-only. Kept out of the pending ledger so "
            "finished work stops costing context on every session."
        ),
    },
]


def _target_wants(target: Target, group: str) -> bool:
    """Does this target receive the adapter's `group` artifacts?

    Default (None) is everything, so the bench is unaffected. A target that
    names a subset gets only that subset.
    """
    return target.renders is None or group in target.renders


def _managed_apps_for(target: Target) -> set[str] | None:
    """Apps this target may write per-app files into, or None for "no restriction".

    Discovery finds every custom app in the bench, but an app whose upstream
    belongs to another team should not receive a generated CLAUDE.md — that is
    an unwanted diff in a repo we do not own. Opt-in by name, declared per
    target so every adapter honours the same list.
    """
    return set(target.managed_apps) if target.managed_apps else None



def _fallback_stamp(repo_root: Path, commit: str) -> datetime:
    """The stamp for artifacts with no single source file to date them by.

    The committer date of HEAD, not the moment render ran. Aggregates are built
    from many sources and cannot name one, but they can still be dated by
    something that only moves when the repo does. `datetime.now()` here meant
    two renders of the same commit disagreed, which is enough on its own to
    make every downstream idempotency claim false.

    Falls back to wall-clock only in a repo with no commits, where there is
    nothing else to use and nothing yet to be idempotent about.
    """
    stamp = commit_date(repo_root, commit)
    if stamp is None:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(stamp)


def _build_forge_context(
    repo_root: Path, forge_cfg: dict[str, Any], target: Target
) -> ForgeContext:
    head = repo_head_commit(repo_root) or "uncommitted"
    return ForgeContext(
        version=forge_version,
        source_commit=head,
        rendered_at=_fallback_stamp(repo_root, head),
        bench_path=target.root,
        # Only a Frappe target has a site. Templates that interpolate it are
        # bench-only; a profile that has none renders an empty string rather
        # than a plausible-looking wrong site name.
        primary_site=target.primary_site or "",
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
def render(
    repo_root: Path, tool: str, target: Target | None = None
) -> list[RenderedArtifact]:
    """Render every artifact this adapter is responsible for, in memory.

    `target` defaults to the bench, so every existing caller keeps its exact
    behaviour. Returns a list of RenderedArtifact — caller writes them to disk.
    """
    adapter_cfg = load_adapter_config(repo_root, tool)
    forge_cfg = load_forge_config(repo_root)
    target = target or load_target(repo_root, forge_cfg=forge_cfg)
    forge_ctx = _build_forge_context(repo_root, forge_cfg, target)
    discovery = load_discovery(repo_root)
    adapter_dir = repo_root / "adapters" / tool
    env = _build_jinja_env(adapter_dir, repo_root)

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
    if "agents" in adapter_cfg.get("artifacts", {}) and _target_wants(target, "agents"):
        tmpl = env.get_template(adapter_cfg["artifacts"]["agents"]["template"])
        for agent in load_agents(repo_root):
            src_commit, src_at = _source_provenance(
                repo_root, agent.source_path, forge_ctx
            )
            content = tmpl.render(
                artifact=_artifact_to_template_dict(agent),
                forge={
                    "version": forge_ctx.version,
                    "source_commit": src_commit,
                    "rendered_at": src_at,
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
    if "commands" in adapter_cfg.get("artifacts", {}) and _target_wants(target, "commands"):
        tmpl = env.get_template(adapter_cfg["artifacts"]["commands"]["template"])
        for cmd in load_commands(repo_root):
            src_commit, src_at = _source_provenance(
                repo_root, cmd.source_path, forge_ctx
            )
            content = tmpl.render(
                artifact=_artifact_to_template_dict(cmd),
                forge={
                    "version": forge_ctx.version,
                    "source_commit": src_commit,
                    "rendered_at": src_at,
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
    skills_cfg = (adapter_cfg.get("artifacts", {}).get("skills")
                  if _target_wants(target, "skills") else None)
    if skills_cfg:
        tmpl = env.get_template(skills_cfg["template"])
        for skill in load_skills(repo_root):
            src_commit, src_at = _source_provenance(
                repo_root, skill.source_path, forge_ctx
            )
            content = tmpl.render(
                artifact=_artifact_to_template_dict(skill),
                forge={
                    "version": forge_ctx.version,
                    "source_commit": src_commit,
                    "rendered_at": src_at,
                },
                bench={"primary_site": forge_ctx.primary_site},
            )
            domain = skill.domain or "uncategorized"
            # Honour the adapter's `output` template. This was hardcoded to
            # `<domain>/<id>.md`, so adapter.yaml's `output:` key was inert and
            # every tool got the same layout whether it could read it or not —
            # Claude Code discovers skills ONLY at `<name>/SKILL.md`, so all 33
            # were invisible to its loader while appearing correctly synced.
            if skills_cfg.get("output"):
                skill_path = Path(_resolve(
                    skills_cfg["output"],
                    {**output_ctx,
                     "artifact": {"id": skill.id, "domain": domain}},
                ))
            else:
                skill_path = skills_dir / domain / f"{skill.id}.md"
            rendered.append(
                RenderedArtifact(
                    tool=tool,
                    source_path=skill.source_path,
                    output_path=skill_path,
                    content=content,
                    source_commit=skill.source_commit,
                    source_version=skill.version,
                    artifact_id=skill.id,
                    artifact_kind="skill",
                )
            )

    # --- Tools (reference docs only — settings.json fragment is handled by sync) ---
    tools_cfg = (adapter_cfg.get("artifacts", {}).get("tools")
                 if _target_wants(target, "tools") else None)
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
            src_commit, src_at = _source_provenance(
                repo_root, tool_spec.source_path, forge_ctx
            )
            content = tmpl.render(
                artifact=_tool_to_template_dict(tool_spec),
                forge={
                    "version": forge_ctx.version,
                    "source_commit": src_commit,
                    "rendered_at": src_at,
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
    if "root_claude_md" in adapter_cfg.get("artifacts", {}) and _target_wants(target, "root_claude_md"):
        tmpl = env.get_template("claude-md-root.j2")
        # Representative source. It must name a file that exists: `_source_hash`
        # returns None for one it cannot read, and a manifest row without that
        # hash opts out of the staleness check entirely — so a stale path here
        # does not fail, it silently stops checking. `architect.md` was renamed
        # to `novizna-architect.md` in aa89c28 and this was left behind.
        root_source = repo_root / "canonical" / "agents" / "novizna-architect.md"
        root_commit, root_at = _source_provenance(repo_root, root_source, forge_ctx)
        content = tmpl.render(
            forge={
                "version": forge_ctx.version,
                "source_commit": root_commit,
                "rendered_at": root_at,
            },
            bench={"primary_site": forge_ctx.primary_site},
        )
        rendered.append(
            RenderedArtifact(
                tool=tool,
                source_path=root_source,
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
    managed = _managed_apps_for(target)
    if per_app_cfg.get("apps") and _target_wants(target, "per_app_claude_md"):
        tmpl = env.get_template("claude-md-per-app.j2")
        app_notes = load_app_notes(repo_root)
        # `managed_apps` is authoritative when set; the adapter's own `apps:`
        # list then only says "this adapter does per-app files at all". Keeping
        # the adapter list as the source would mean `forge apps add` silently
        # did nothing for claude-code until someone also edited adapter.yaml.
        app_list = sorted(managed) if managed is not None else list(per_app_cfg["apps"])
        for app_name in app_list:
            app_data = discovery.app(app_name)
            if not app_data:
                continue
            notes = app_notes.get(app_name)
            # Provenance describes THIS app's source note, not the sync run.
            # Stamping repo HEAD + wall-clock rewrote every managed app on
            # every sync — footer changes, so sha256 changes, so the manifest
            # changes — and reported drift for apps whose source never moved.
            app_commit, app_stamp = _source_provenance(
                repo_root, repo_root / "canonical" / "apps" / f"{app_name}.md", forge_ctx
            )
            content = tmpl.render(
                app=app_data,
                app_notes=notes.body.strip() if notes else "",
                forge={
                    "version": forge_ctx.version,
                    "source_commit": app_commit,
                    "rendered_at": app_stamp,
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
                    # Per-app, matching the footer: the manifest records this
                    # as the source_commit for the app's output dir, so using
                    # repo HEAD here would reintroduce the churn the footer
                    # change removes.
                    source_commit=app_commit,
                    source_version=forge_version,
                    artifact_id=f"per-app-claude-md/{app_name}",
                    artifact_kind="aggregate",
                )
            )

    # --- Harness scripts (single owning adapter per target) ---
    # The first artifacts forge writes that a machine EXECUTES, so they are the
    # first to carry a mode. `source_path` points at the real .sh.j2 so the
    # existing security gate in sync.py scores them with no change there.
    # Loaded unconditionally: only the owning adapter WRITES the scripts, but
    # every adapter needs the gate table to render the shared AGENTS-HARNESS.md.
    harness: HarnessSpec | None = load_harness(repo_root)
    harness_cfg = adapter_cfg.get("artifacts", {}).get("harness_scripts")
    if (
        harness is not None
        and harness_cfg is not None
        and _target_wants(target, "harness_scripts")
    ):
        profile = harness.profile(target.stack_profile)
        harness_dir = Path(_resolve(harness_cfg["output_dir"], output_ctx))
        for script in harness.scripts:
            tmpl = env.get_template(f"scripts/{script.source_path.name}")
            content = tmpl.render(
                forge=forge_ctx,
                target={
                    "name": target.name,
                    "root": str(target.root),
                    "stack_profile": target.stack_profile,
                    "primary_site": target.primary_site or "",
                    # Reuses `lint_apps`: "ours to lint" and "ours to run gates
                    # against" are the same set, and a second list would drift.
                    "owned_apps": sorted(target.lint_apps or ()),
                },
                profile=profile,
                harness=harness,
                bench={"primary_site": forge_ctx.primary_site},
            )
            rendered.append(
                RenderedArtifact(
                    tool=tool,
                    source_path=script.source_path,
                    output_path=harness_dir / script.filename,
                    content=content,
                    source_commit=forge_ctx.source_commit,
                    source_version=harness.version,
                    artifact_id=f"harness/{script.id}",
                    artifact_kind="harness-script",
                    mode=script.mode,
                )
            )

        # Tool configs ride with the scripts — same owning adapter, same
        # security gate — but land at target-root paths of their own choosing,
        # because a linter reads config from where it is invoked, not from
        # scripts_dir.
        #
        # Skipped entirely when the target declares no `lint_apps`: emitting an
        # unscoped ruff.toml would silently widen the lint scope of a target
        # that never asked for one.
        if target.lint_apps:
            lint_apps = sorted(target.lint_apps)
            excluded_apps = _unlinted_apps(target, lint_apps)
            for cfg_spec in harness.configs:
                # Absolute, like every other rendered path — sync rejects
                # relative ones. Re-checked against the target root afterwards
                # so an `output_path` of `../…` in harness.yaml cannot land a
                # file outside the repo forge was asked to write to.
                config_path = (target.root / cfg_spec.output_path).resolve()
                if not config_path.is_relative_to(target.root.resolve()):
                    raise ValueError(
                        f"harness config {cfg_spec.id!r} has output_path "
                        f"{cfg_spec.output_path!r}, which escapes the target root"
                    )
                tmpl = env.get_template(cfg_spec.source_path.name)
                content = tmpl.render(
                    forge=forge_ctx,
                    target={
                        "name": target.name,
                        "root": str(target.root),
                        "stack_profile": target.stack_profile,
                        "primary_site": target.primary_site or "",
                    },
                    harness=harness,
                    lint_apps=lint_apps,
                    excluded_apps=excluded_apps,
                )
                rendered.append(
                    RenderedArtifact(
                        tool=tool,
                        source_path=cfg_spec.source_path,
                        output_path=config_path,
                        content=content,
                        source_commit=forge_ctx.source_commit,
                        source_version=harness.version,
                        artifact_id=f"harness/{cfg_spec.id}",
                        artifact_kind="harness-config",
                        mode=cfg_spec.mode,
                    )
                )

    # --- Hook wiring (per-tool; emits nothing when the adapter has no hooks) ---
    # Deliberately emits NOTHING rather than an empty file: _validate_staging
    # rejects zero-byte staged files, so an empty emission would abort the sync.
    wiring_cfg = adapter_cfg.get("artifacts", {}).get("hook_wiring")
    if (
        wiring_cfg
        and harness is not None
        and _target_wants(target, "hook_wiring")
        and adapter_cfg.get("capabilities", {}).get("hooks")
    ):
        events = adapter_cfg.get("capabilities", {}).get("hook_events", {})
        # An adapter only wires the events it actually has. opencode has no
        # end-of-session event and antigravity's edit payload carries no file
        # path — for those the missing half is instruction-level, in
        # AGENTS-HARNESS.md, rather than a hook that fires and does nothing.
        hooks_for_tool = [h for h in harness.hooks if h.fires_on in events]
        scripts_dir_rel = forge_cfg.get("harness", {}).get(
            "scripts_dir", "scripts/harness"
        )
        if hooks_for_tool:
            tmpl = env.get_template(wiring_cfg["template"])
            content = tmpl.render(
                forge=forge_ctx,
                target={
                    "name": target.name,
                    "root": str(target.root),
                    "stack_profile": target.stack_profile,
                },
                hooks=hooks_for_tool,
                events=events,
                harness=harness,
                # Only the owning adapter declares `harness_dir`; the others
                # merely point at the scripts it wrote, so fall back to the
                # target-relative path from forge.config.yaml.
                harness_dir=(
                    _resolve(adapter_cfg["output_paths"]["harness_dir"], output_ctx)
                    if "harness_dir" in adapter_cfg.get("output_paths", {})
                    else str(target.root / scripts_dir_rel)
                ),
                scripts_dir=scripts_dir_rel,
                permissions=harness.permissions,
                profile_permissions=(
                    harness.permissions.get("profiles", {}).get(target.stack_profile)
                    or {}
                ),
                bench={"primary_site": forge_ctx.primary_site},
            )
            rendered.append(
                RenderedArtifact(
                    tool=tool,
                    source_path=repo_root / "canonical" / "harness" / "harness.yaml",
                    output_path=Path(_resolve(wiring_cfg["output"], output_ctx)),
                    content=content,
                    source_commit=forge_ctx.source_commit,
                    source_version=harness.version,
                    artifact_id=f"hook-wiring/{tool}",
                    # Not swapped like a normal file — it merges into human-owned
                    # content. See _merge_settings_fragments in sync.py.
                    artifact_kind=wiring_cfg.get("artifact_kind", "hook-wiring"),
                )
            )

    # --- Ledger scaffolds (write-once; agents own the rows) ---
    ledger_cfg = adapter_cfg.get("artifacts", {}).get("ledger")
    if ledger_cfg and _target_wants(target, "ledger"):
        tmpl = env.get_template(ledger_cfg["template"])
        for phase in LEDGER_PHASES:
            content = tmpl.render(
                forge=forge_ctx,
                phase=phase,
                target={"name": target.name},
                bench={"primary_site": forge_ctx.primary_site},
            )
            rendered.append(
                RenderedArtifact(
                    tool=tool,
                    source_path=repo_root
                    / "canonical"
                    / "policies"
                    / "definition-of-done.md",
                    output_path=Path(
                        _resolve(ledger_cfg["output"], {**output_ctx, "phase": phase})
                    ),
                    content=content,
                    source_commit=forge_ctx.source_commit,
                    source_version="1.0.0",
                    artifact_id=f"ledger/{phase['id']}",
                    # Written only if absent — never overwritten. See
                    # _swap_into_bench.
                    artifact_kind="scaffold",
                )
            )

    # --- Aggregate strategies (Cursor, OpenCode, Cline, Copilot, Codex, Antigravity) ---
    # Each entry in adapter.yaml `artifacts:` with strategy: aggregate emits one
    # output file rendered from the full canonical set. The template receives
    # `agents`, `commands`, `skills`, `tools`, `policies`, plus `forge`, `bench`,
    # and `discovery` (for per-app contexts).
    artifacts_cfg = adapter_cfg.get("artifacts", {})
    # `root_claude_md` and `per_app_claude_md` have dedicated blocks above,
    # driven by `output_paths`. Without this exclusion the generic loops render
    # them a SECOND time to the same path — harmless for content (identical),
    # but it writes two manifest `outputs` rows for one file, and the duplicate
    # row defeats hand-edit detection.
    DEDICATED = {"root_claude_md", "per_app_claude_md"}

    aggregate_entries = [
        (kind, spec)
        for kind, spec in artifacts_cfg.items()
        if isinstance(spec, dict)
        and spec.get("strategy") == "aggregate"
        and kind not in DEDICATED
        and _target_wants(target, kind)
    ]
    if aggregate_entries:
        all_agents = [_artifact_to_template_dict(a) for a in load_agents(repo_root)]
        all_commands = [_artifact_to_template_dict(c) for c in load_commands(repo_root)]
        all_skills = [_artifact_to_template_dict(s) for s in load_skills(repo_root)]
        all_tools = [_tool_to_template_dict(t) for t in load_tools(repo_root)]
        for kind, spec in aggregate_entries:
            tmpl = env.get_template(spec["template"])
            content = tmpl.render(
                # The adapter's own config, so a template never has to restate
                # what adapter.yaml already declares. `inlined_specialists_only`
                # was duplicated as a literal id list inside antigravity's
                # template; renaming an agent updated the yaml, the template
                # kept its stale literal, and the persona silently vanished
                # from the rendered output with nothing failing.
                adapter=adapter_cfg,
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
                # Harness context, so the shared harness doc can print the gate
                # table for THIS target. Absent when no harness is authored, in
                # which case the template's `{% if profile %}` skips the section.
                target={
                    "name": target.name,
                    "stack_profile": target.stack_profile,
                    "primary_site": target.primary_site or "",
                },
                profile=(harness.profile(target.stack_profile) if harness else None),
                policies=[
                    _artifact_to_template_dict(p) for p in load_policies(repo_root)
                ],
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
        if isinstance(spec, dict)
        and spec.get("strategy") == "aggregate_per_app"
        and kind not in DEDICATED
    ]
    if per_app_aggregates:
        app_notes = load_app_notes(repo_root)
        for kind, spec in per_app_aggregates:
            tmpl = env.get_template(spec["template"])
            for app_data in discovery.apps.get("custom_apps", []):
                app_name = app_data["name"]
                if managed is not None and app_name not in managed:
                    continue
                notes = app_notes.get(app_name)
                # Same source as the dedicated per-app block above, so the two
                # renderings of one app agree instead of dating from different
                # things.
                app_commit, app_at = _source_provenance(
                    repo_root, repo_root / "canonical" / "apps" / f"{app_name}.md",
                    forge_ctx,
                )
                content = tmpl.render(
                    app=app_data,
                    app_notes=notes.body.strip() if notes else "",
                    forge={
                        "version": forge_ctx.version,
                        "source_commit": app_commit,
                        "rendered_at": app_at,
                    },
                    bench={"primary_site": forge_ctx.primary_site},
                )
                # Pass `app` as the full dict so adapter.yaml output strings can
                # use `{{ app.name }}` (and `{{ app.stack }}`, etc.).
                # Distinct name from the `output_path: Path` bound earlier in
                # this function — reusing it made the same local both str and
                # Path depending on the branch taken.
                resolved_output = _resolve(
                    spec["output"],
                    {**output_ctx, "app": app_data, "app_name": app_name},
                )
                rendered.append(
                    RenderedArtifact(
                        tool=tool,
                        source_path=repo_root / "discovery" / "INVENTORY.md",
                        output_path=Path(resolved_output),
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
