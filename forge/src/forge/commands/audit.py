"""`forge audit` — inspect and manage the append-only audit log.

Phase 0 skeleton. Real implementation in Phase 2/4 will:
  - tail: stream audit/<YYYY>/<MM>/forge-audit.jsonl entries with filters
  - backup: tar+gpg the audit/ tree, write to FORGE_AUDIT_BACKUP_DIR
"""

from __future__ import annotations

from typing import Optional

from rich.console import Console

console = Console()


def tail(n: int, agent: Optional[str], since: Optional[str]) -> None:
    console.print("[yellow]not yet implemented[/yellow]")
    console.print(f"  would tail n={n} agent={agent} since={since}")


def backup() -> None:
    console.print("[yellow]not yet implemented[/yellow]")
    console.print("  would tar+gpg audit/ → FORGE_AUDIT_BACKUP_DIR")
