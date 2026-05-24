"""`forge validate` — schema + drift validation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from forge.loader import (
    find_repo_root,
    load_agents,
    load_commands,
    load_policies,
    load_skills,
    load_tools,
)

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

    # Drift check: read every .forge-manifest.json in the bench and verify
    # recorded sha256s + source commits.
    if check_drift:
        from forge.drift import check_drift as run_drift_check
        from forge.drift import render_drift_report
        report = run_drift_check(repo_root)
        console.print(f"\n[cyan]Drift check:[/cyan]")
        console.print(render_drift_report(report))
        if report.has_drift:
            issues.append(f"{sum(1 for f in report.findings if f.severity == 'DRIFT')} drift finding(s)")

    console.print(
        f"\n[cyan]Loaded:[/cyan] {len(agents)} agents, {len(commands)} commands, "
        f"{len(skills)} skills, {len(policies)} policies, {len(tools)} tools"
    )
    if issues:
        console.print(f"\n[red]Issues:[/red] {len(issues)}")
        for i in issues:
            console.print(f"  • {i}")
        raise typer.Exit(code=1)
    console.print("[green]✓ schema valid[/green]")
