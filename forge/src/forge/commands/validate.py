"""`forge validate` — schema + drift validation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from forge.loader import (
    find_repo_root,
    load_adapter_config,
    load_agents,
    load_commands,
    load_forge_config,
    load_harness,
    load_policies,
    load_skills,
    load_targets,
    load_tools,
)
from forge.skills_lock import verify as verify_skills_lock

console = Console()


def run(path: Optional[Path], check_drift: bool) -> None:
    repo_root = find_repo_root()
    issues: list[str] = []

    agents = load_agents(repo_root)
    commands = load_commands(repo_root)
    skills = load_skills(repo_root)
    policies = load_policies(repo_root)
    tools = load_tools(repo_root)

    # Schema: every artifact has id matching basename
    for art in agents + commands + skills + policies:
        if art.id != art.source_path.stem:
            issues.append(f"id mismatch: {art.source_path} → frontmatter id={art.id!r}")

    # Version present
    for art in agents + commands + skills + policies:
        if art.version == "0.0.0":
            issues.append(f"missing/invalid version: {art.source_path}")

    # Tool callers reference real agents / commands
    known_callers = {f"agent:{a.id}" for a in agents} | {f"command:/{c.id}" for c in commands}
    for tool in tools:
        for caller in tool.allowed_callers:
            if caller not in known_callers:
                issues.append(f"unknown caller in {tool.source_path.name}: {caller}")

    # Harness invariants. These are written down in canonical/harness/harness.yaml
    # under `invariants:`; this is where they are actually enforced.
    warnings: list[str] = []
    harness = load_harness(repo_root)
    if harness is not None:
        for script in harness.scripts:
            if not script.source_path.is_file():
                issues.append(f"harness script '{script.id}' missing: {script.source_path}")
            stem = script.source_path.name.removesuffix(".j2").removesuffix(".sh")
            if stem != script.id:
                issues.append(
                    f"harness id/filename mismatch: id={script.id!r} "
                    f"file={script.source_path.name!r}"
                )

        script_ids = {s.id for s in harness.scripts}
        for hook in harness.hooks:
            if hook.script not in script_ids:
                issues.append(
                    f"hook '{hook.id}' runs unknown script {hook.script!r}"
                )
            elif not hook.script.startswith("hook-"):
                # A hook is handed JSON on stdin; check-file.sh takes paths as
                # arguments. Wiring one straight to the other lints nothing and
                # exits 0 — a gate that silently passes is worse than no gate.
                issues.append(
                    f"hook '{hook.id}' runs '{hook.script}' directly; hooks must "
                    f"run an adapter script that parses the payload first"
                )

        # No harness script may invoke `forge sync`: it would rewrite the
        # scripts mid-run, and _confirm_foreign_writes fails closed on a
        # non-tty, so it would skip silently rather than ask.
        for script in harness.scripts:
            if not script.source_path.is_file():
                continue
            code = "\n".join(
                ln for ln in script.source_path.read_text().splitlines()
                if not ln.lstrip().startswith("#")
            )
            if "forge sync" in code:
                issues.append(f"harness script '{script.id}' invokes `forge sync`")

        # Exactly one enabled adapter per target may own scripts/harness/.
        # Two would race, and each would strip the other's manifest rows.
        forge_cfg = load_forge_config(repo_root)
        for tname, target in load_targets(repo_root, forge_cfg).items():
            owners = []
            for tool_name in target.enabled_tools:
                try:
                    acfg = load_adapter_config(repo_root, tool_name)
                except FileNotFoundError:
                    continue
                if (acfg.get("artifacts") or {}).get("harness_scripts"):
                    owners.append(tool_name)
            if len(owners) > 1:
                issues.append(
                    f"target '{tname}': {len(owners)} adapters declare "
                    f"harness_scripts ({', '.join(owners)}); exactly one may"
                )

            # Adapters that wire hooks do not write the scripts — they point at
            # the ones the owning adapter wrote. If no enabled adapter owns
            # them, every hook references a path that will never exist and
            # fails at run time with "no such file".
            wirers = []
            for tool_name in target.enabled_tools:
                try:
                    acfg = load_adapter_config(repo_root, tool_name)
                except FileNotFoundError:
                    continue
                if (acfg.get("artifacts") or {}).get("hook_wiring"):
                    wirers.append(tool_name)
            if wirers and not owners:
                issues.append(
                    f"target '{tname}': {', '.join(wirers)} wire hooks but no "
                    f"enabled adapter declares harness_scripts, so the scripts "
                    f"they invoke are never written"
                )

        # Unverified gate commands stay visible on every run rather than
        # rotting in a comment nobody reads again.
        for stack, profile in (harness.gates or {}).items():
            for phase in ("file_lint", "typecheck", "quick", "full"):
                for gate in profile.get(phase) or []:
                    if gate.get("verify_status") == "UNVERIFIED":
                        warnings.append(
                            f"gate {stack}/{phase}/{gate['id']} is UNVERIFIED: "
                            f"{gate['cmd']}"
                        )

    # Reviewer tools must actually be read-only. A `review_only: true` agent
    # whose output is a review, not a code change, gets its tools restricted so
    # a reviewer can never silently become a producer. Agents that legitimately
    # write output as part of reviewing (qa-test-engineer writes test files)
    # are NOT review_only and are unaffected by this check.
    for agent in agents:
        if not agent.raw_frontmatter.get("review_only"):
            continue
        agent_tools = agent.raw_frontmatter.get("tools")
        if not agent_tools:
            issues.append(
                f"{agent.source_path.name}: review_only: true but no `tools:` "
                f"declared — a reviewer with unrestricted tools can silently "
                f"become a producer"
            )
        elif {"Write", "Edit", "MultiEdit", "NotebookEdit"} & set(agent_tools):
            issues.append(
                f"{agent.source_path.name}: review_only: true but tools: "
                f"{agent_tools} includes a write capability"
            )

    # Ownership guard on scaffold outputs (ledgers today; forward-compatible
    # with any future per-app mirror). A finding about an upstream or
    # foreign-remote app must never deposit a file inside that app's own
    # directory — mirrors the write guard `forge sync` already applies to
    # rendered artifacts (forge/src/forge/repo.py::owner_of_app/is_foreign),
    # so the rule agents follow and the rule the code enforces are the same
    # rule, not two that can drift apart.
    from forge.repo import is_foreign, owner_of_app

    forge_cfg_for_ownership = load_forge_config(repo_root)
    upstream_apps = set(forge_cfg_for_ownership.get("upstream_apps") or [])
    for tname, target in load_targets(repo_root, forge_cfg_for_ownership).items():
        apps_dir = target.root / "apps"
        if not apps_dir.is_dir():
            continue
        owned = target.owned_remotes
        for app_dir in sorted(p for p in apps_dir.iterdir() if p.is_dir()):
            app = app_dir.name
            scaffold_dir = app_dir / "docs" / "harness"
            if not scaffold_dir.is_dir():
                continue
            is_upstream = app in upstream_apps
            is_owned_foreign = bool(owned) and is_foreign(
                owner_of_app(target.root, app), set(owned)
            )
            if is_upstream or is_owned_foreign:
                reason = "an upstream app" if is_upstream else "a foreign-remote app"
                issues.append(
                    f"target '{tname}': {scaffold_dir} exists under {app!r}, "
                    f"which is {reason} — a ledger/ticket scaffold must never "
                    f"be written into a repo we do not own"
                )

    # Ledger invariant: a key lives in exactly one ledger file. A build_state
    # transition is a MOVE, and this is the one place the design rots — a copied
    # row leaves two sources of truth for the same ticket and nothing to say
    # which is current.
    for tname, target in load_targets(repo_root, load_forge_config(repo_root)).items():
        ledger_dir = target.root / "docs" / "harness"
        if not ledger_dir.is_dir():
            continue
        seen: dict[str, list[str]] = {}
        for ledger in sorted(ledger_dir.glob("LEDGER-*.md")):
            for line in ledger.read_text(errors="replace").splitlines():
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip("|").split("|")]
                key = cells[0] if cells else ""
                # Skip the header row and its separator.
                if not key or key.upper() == "KEY" or set(key) <= set("- "):
                    continue
                seen.setdefault(key, []).append(ledger.name)
        for key, files in sorted(seen.items()):
            if len(files) > 1:
                issues.append(
                    f"target '{tname}': ticket {key} appears in "
                    f"{len(files)} ledgers ({', '.join(files)}); a build_state "
                    f"change must MOVE the row, not copy it"
                )

    # Skills provenance: every provenance: external skill must match its
    # canonical/skills-lock.json entry (hash + score). Internal skills (the
    # default, and all 31 currently in this repo) are untouched by this.
    for finding in verify_skills_lock(repo_root):
        issues.append(f"skills-lock [{finding.problem}]: {finding.detail}")

    # Drift check: read every .forge-manifest.json in the bench and verify
    # recorded sha256s + source commits.
    if check_drift:
        from forge.drift import check_drift as run_drift_check
        from forge.drift import render_drift_report
        report = run_drift_check(repo_root)
        console.print("\n[cyan]Drift check:[/cyan]")
        console.print(render_drift_report(report))
        if report.has_drift:
            issues.append(f"{sum(1 for f in report.findings if f.severity == 'DRIFT')} drift finding(s)")

    console.print(
        f"\n[cyan]Loaded:[/cyan] {len(agents)} agents, {len(commands)} commands, "
        f"{len(skills)} skills, {len(policies)} policies, {len(tools)} tools"
    )
    if warnings:
        # Warnings, not issues: an unverified gate is honest debt, not a broken
        # repo. It must not fail CI, and it must not become invisible either.
        console.print(f"\n[yellow]Unverified gate commands:[/yellow] {len(warnings)}")
        for w in warnings:
            console.print(f"  • {w}")
        console.print(
            "  [dim]Run each against the real target, then set "
            "verify_status: VERIFIED in canonical/harness/gates.yaml.[/dim]"
        )

    if issues:
        console.print(f"\n[red]Issues:[/red] {len(issues)}")
        for i in issues:
            console.print(f"  • {i}")
        raise typer.Exit(code=1)
    console.print("[green]✓ schema valid[/green]")
