"""`forge discover` — walk the bench and refresh discovery/ outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from forge.discover_bench import discover_bench
from forge.loader import find_repo_root

console = Console()


def run(bench: Optional[Path], app_name: Optional[str], json_only: bool) -> None:
    repo_root = find_repo_root()

    try:
        written = discover_bench(
            repo_root=repo_root,
            bench_override=bench,
            only_app=app_name,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)

    scope = f"app={app_name}" if app_name else "all custom apps"
    console.print(f"[green]✓[/green] discovered {scope} — wrote {len(written)} files:")
    for name, path in sorted(written.items()):
        console.print(f"  {name}  →  {path.relative_to(repo_root)}")
    if not json_only:
        console.print(
            "\n[yellow]Note:[/yellow] INVENTORY.md is human-authored. "
            "Update it manually if structural narrative changes (counts come from JSON above)."
        )
