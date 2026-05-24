"""`forge commit` — scoped Conventional Commits helper."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from forge.commit_helper import check_message, propose
from forge.loader import find_repo_root

console = Console()


def run(message: Optional[str], check: bool) -> None:
    repo_root = find_repo_root()

    if check:
        # Validate .git/COMMIT_EDITMSG (commit-msg hook contract)
        commit_msg_path = repo_root / ".git" / "COMMIT_EDITMSG"
        if not commit_msg_path.is_file():
            console.print(f"[red]No COMMIT_EDITMSG at {commit_msg_path}[/red]")
            raise typer.Exit(code=2)
        result = check_message(commit_msg_path.read_text(), repo_root)
        if result.ok:
            console.print(f"[green]✓[/green] {result.message_first_line}")
            return
        console.print(f"[red]✗ Commit message rejected:[/red] {result.message_first_line}")
        for issue in result.issues:
            console.print(f"  • {issue}")
        raise typer.Exit(code=1)

    # Propose mode
    proposal = propose(message, repo_root)
    console.print("[cyan]Proposed commit message:[/cyan]")
    console.print(proposal.render())
    console.print(
        f"\n[dim]Type:[/dim] {proposal.type}  "
        f"[dim]Scope:[/dim] {proposal.scope}\n"
        f"[dim]Run:[/dim] git commit -m {proposal.render()!r}"
    )
