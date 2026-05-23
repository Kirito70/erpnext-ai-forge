"""`forge test` — wrap pytest with golden-file fixtures.

Phase 0 skeleton. Real implementation in Phase 2 will:
  - Discover golden fixtures under forge/tests/golden/<tool>/<artifact>/
  - For each fixture: render canonical input, compare to expected output
  - On --update-golden: write new expected outputs (with confirmation)
"""

from __future__ import annotations

from rich.console import Console

console = Console()


def run(update_golden: bool, verbose: bool) -> None:
    console.print("[yellow]not yet implemented[/yellow]")
    console.print(f"  would run pytest (update_golden={update_golden}, verbose={verbose})")
