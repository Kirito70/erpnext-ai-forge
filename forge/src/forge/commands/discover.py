"""`forge discover` — walk the bench and refresh discovery/ outputs.

Phase 0 skeleton. Real implementation in Phase 2 will:
  - Walk apps/<custom>/ (skipping upstream apps from forge.config.yaml)
  - Parse hooks.py, doctype JSONs, fixtures, patches.txt
  - Detect per-app stack (Frappe-UI vs Quasar vs pure backend)
  - Write discovery/data/*.json + regenerate discovery/INVENTORY.md
  - Record source commit hashes for ADR-style traceability
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()


def run(bench: Optional[Path], app_name: Optional[str], json_only: bool) -> None:
    target = bench or Path("/home/tayyab/Work/Projects/erp/novizna-v16/novizna-v16")
    scope = f"app={app_name}" if app_name else "full bench"
    mode = "JSON only" if json_only else "JSON + INVENTORY.md"
    console.print(f"[yellow]not yet implemented[/yellow]")
    console.print(f"  would discover: {target} ({scope}, {mode})")
    console.print("  initial Phase 0 discovery is hand-authored — see discovery/INVENTORY.md")
