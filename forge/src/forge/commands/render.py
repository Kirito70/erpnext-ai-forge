"""`forge render` — render canonical → per-tool artifacts without syncing.

Phase 0 skeleton. Real implementation in Phase 2 will:
  - Load adapter.yaml for the requested tool
  - For each canonical artifact in scope, run Jinja templates from
    adapters/<tool>/templates/
  - Write to ./build/<tool>/... preserving expected output paths
  - Apply context-loading strategy per v0.2 Section 4.0
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

console = Console()


def run(tool: str, out: Path) -> None:
    console.print("[yellow]not yet implemented[/yellow]")
    console.print(f"  would render tool={tool} → {out}/")
