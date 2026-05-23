"""`forge validate` — schema + drift validation.

Phase 0 skeleton. Real implementation in Phase 2 will:
  - Load all canonical/**/*.md + frontmatter, validate against forge schemas
  - Load all adapters/**/adapter.yaml, validate template references
  - For each adapter with output in <bench>, re-render in memory and diff against
    on-disk artifacts; report drift against .forge-manifest.json source commits
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()


def run(path: Optional[Path], check_drift: bool) -> None:
    console.print("[yellow]not yet implemented[/yellow]")
    console.print(f"  would validate path={path or 'canonical/'} check_drift={check_drift}")
