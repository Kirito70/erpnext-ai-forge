"""`forge commit` — scoped Conventional Commits helper.

Phase 0 skeleton. Real implementation in Phase 2 will:
  - Infer scope from staged file paths against forge.config.yaml `commits.scopes`
  - Propose a commit message in `<type>(<scope>): <subject>` form
  - --check: validate .git/COMMIT_EDITMSG matches the convention (commit-msg hook)
"""

from __future__ import annotations

from typing import Optional

from rich.console import Console

console = Console()


def run(message: Optional[str], check: bool) -> None:
    if check:
        console.print("[yellow]not yet implemented[/yellow] — would validate commit message format")
    else:
        body = message or "(no body supplied)"
        console.print("[yellow]not yet implemented[/yellow]")
        console.print(f"  would propose: <type>(<scope>): {body}")
