"""`forge skills verify|list` — skills provenance lockfile commands."""

from __future__ import annotations

import typer
from rich.console import Console

from forge.loader import find_repo_root
from forge.skills_lock import list_skills, verify

console = Console()


def run_verify() -> None:
    repo_root = find_repo_root()
    findings = verify(repo_root)
    if not findings:
        console.print("[green]✓ no external skills, or all verified clean[/green]")
        return
    console.print(f"[red]{len(findings)} finding(s):[/red]")
    for f in findings:
        console.print(f"  • [{f.problem}] {f.skill_id}: {f.detail}")
    raise typer.Exit(code=1)


def run_list() -> None:
    repo_root = find_repo_root()
    rows = list_skills(repo_root)
    for skill_id, provenance, source in rows:
        tag = "[cyan]internal[/cyan]" if provenance == "internal" else "[yellow]external[/yellow]"
        suffix = f" ← {source}" if source else ""
        console.print(f"{tag}  {skill_id}{suffix}")
    external = sum(1 for _, p, _ in rows if p == "external")
    console.print(f"\n{len(rows)} skill(s), {external} external")
