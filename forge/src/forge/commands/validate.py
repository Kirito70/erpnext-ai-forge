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

    # Drift check is a Phase-2.x deliverable (compare manifest sha vs current sha)
    if check_drift:
        console.print(
            "[yellow]Drift check:[/yellow] manifest-based drift detection ships in Phase 2.x. "
            "For now, run `forge sync --dry-run` to compare staged vs bench output."
        )

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
