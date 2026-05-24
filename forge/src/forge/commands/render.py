"""`forge render` — render canonical → per-tool artifacts into a local build dir."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from forge.loader import find_repo_root
from forge.render import render, render_summary

console = Console()


def run(tool: str, out: Path) -> None:
    repo_root = find_repo_root()
    out_dir = out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rendered = render(repo_root, tool)
    for r in rendered:
        # Preserve bench-relative structure under the build dir for inspection
        rel = Path(*r.output_path.parts[-4:])  # heuristic: keep last few segments
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(r.content)

    summary = render_summary(rendered)
    console.print(f"[green]✓[/green] rendered {len(rendered)} files for [cyan]{tool}[/cyan] → {out_dir}")
    for kind, count in sorted(summary.items()):
        console.print(f"  {kind}: {count}")
