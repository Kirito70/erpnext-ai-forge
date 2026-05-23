"""`forge score` — security score canonical artifacts.

Phase 0 skeleton. Real implementation in Phase 4 will:
  - Start each artifact at 100
  - Apply deduction table from canonical/policies/security-scoring.yaml
    (e.g. -50 reads site_config, -50 edits upstream apps, -40 dangerously-skip-permissions)
  - Thresholds per v0.2 Decision 11 + Part B item 3:
      ≥ 95 auto-accept | 80-94 warn (typed justification) | < 80 block | external ≥ 98
  - Write computed score back to artifact frontmatter (security_score)
  - Exit non-zero if any file scores below --fail-below
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

console = Console()


def run(path: Path, staged: bool, fail_below: int) -> None:
    scope = "git-staged files" if staged else str(path)
    console.print("[yellow]not yet implemented[/yellow]")
    console.print(f"  would score: {scope} (fail below {fail_below})")
