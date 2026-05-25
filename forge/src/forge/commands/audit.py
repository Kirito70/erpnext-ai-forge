"""`forge audit` — inspect and manage the append-only audit log."""

from __future__ import annotations

from typing import Optional

from rich.console import Console

from forge.audit import backup as audit_backup
from forge.audit import tail as audit_tail
from forge.loader import find_repo_root

console = Console()


def tail(
    n: int,
    agent: Optional[str],
    since: Optional[str],
    action: Optional[str] = None,
    grep: Optional[str] = None,
    as_json: bool = False,
) -> None:
    repo_root = find_repo_root()
    audit_tail(
        repo_root, n=n, agent=agent, since=since, action=action, grep=grep, as_json=as_json,
    )


def backup() -> None:
    repo_root = find_repo_root()
    result = audit_backup(repo_root)
    if result.error:
        console.print(f"[red]Backup error:[/red] {result.error}")
        return
    target = result.encrypted_path or result.archive_path
    console.print(
        f"[green]✓[/green] backed up {result.files_archived} audit file(s) → {target}"
    )
