"""`forge discover` — walk the bench and refresh discovery/ outputs.

Phase 2 baseline: re-reads existing discovery/INVENTORY.md and reports
its current freshness. The full bench-walking automation is still in
flight (Phase 2.x). For now, the initial Phase 0 hand-authored discovery
under discovery/ is the authoritative snapshot; this command surfaces
its age and freshness so the developer knows when to re-author it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console

from forge.loader import find_repo_root, load_discovery

console = Console()


def run(bench: Optional[Path], app_name: Optional[str], json_only: bool) -> None:
    repo_root = find_repo_root()
    discovery = load_discovery(repo_root)

    console.print(f"[cyan]Discovery snapshot:[/cyan] {repo_root / 'discovery'}")
    if discovery.generated_at:
        console.print(f"  generated_at: {discovery.generated_at}")
    console.print(
        f"  custom apps:  {len(discovery.apps.get('custom_apps', []))}"
    )
    console.print(
        f"  upstream apps: {len(discovery.apps.get('upstream_apps', []))}"
    )
    if app_name:
        info = discovery.app(app_name)
        if info:
            console.print(f"\n[cyan]App {app_name}:[/cyan]")
            for k, v in info.items():
                console.print(f"  {k}: {v}")
        else:
            console.print(f"[red]Unknown app: {app_name}[/red]")

    console.print(
        "\n[yellow]Note:[/yellow] full bench-walking automation lands in Phase 2.x; "
        "current discovery is hand-authored at discovery/INVENTORY.md."
    )
