"""Append-only audit log emitter (JSONL).

Schema per v0.2 §8.4. Path: audit/<YYYY>/<MM>/forge-audit.jsonl.
Retention: 1 year local + monthly tar+gpg via `forge audit backup`.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tarfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from rich.console import Console
from rich.table import Table

console = Console()


# ---------------------------------------------------------------------------
# Append
# ---------------------------------------------------------------------------
def _audit_dir_for_now(repo_root: Path) -> Path:
    now = datetime.now(timezone.utc)
    d = repo_root / "audit" / f"{now.year:04d}" / f"{now.month:02d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def audit_log(repo_root: Path, entry: dict[str, Any]) -> None:
    """Append one JSONL entry to the current month's audit file."""
    audit_dir = _audit_dir_for_now(repo_root)
    target = audit_dir / "forge-audit.jsonl"

    enriched: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": os.environ.get("FORGE_SESSION_ID") or str(uuid.uuid4()),
        "host": socket.gethostname(),
        "user": os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown",
        **entry,
    }
    with target.open("a") as f:
        f.write(json.dumps(enriched, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Tail
# ---------------------------------------------------------------------------
def _iter_audit_files(repo_root: Path) -> Iterator[Path]:
    """Yield audit files newest-first."""
    root = repo_root / "audit"
    if not root.is_dir():
        return
    files = sorted(root.rglob("forge-audit.jsonl"), reverse=True)
    for f in files:
        yield f


def tail(
    repo_root: Path,
    n: int = 50,
    agent: str | None = None,
    since: str | None = None,
) -> int:
    """Stream the last N audit entries to the console with optional filters.

    Returns process exit code."""
    entries: list[dict[str, Any]] = []
    for f in _iter_audit_files(repo_root):
        for line in reversed(f.read_text().splitlines()):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if agent and agent not in str(e.get("tool_or_agent", "") + e.get("action", "")):
                continue
            if since and e.get("ts", "") < since:
                continue
            entries.append(e)
            if len(entries) >= n:
                break
        if len(entries) >= n:
            break

    if not entries:
        console.print("[yellow]No audit entries found.[/yellow]")
        return 0

    table = Table(title=f"Audit log — last {len(entries)} entries", show_lines=False)
    table.add_column("Timestamp", style="cyan", no_wrap=True)
    table.add_column("Action", style="green")
    table.add_column("Tool/Agent", style="magenta")
    table.add_column("Detail")
    for e in reversed(entries):  # chronological order
        ts = e.get("ts", "")[:19]
        action = e.get("action", "")
        ta = e.get("tool_or_agent", e.get("tool", ""))
        detail_keys = [k for k in e if k not in {"ts", "action", "tool_or_agent", "tool", "session_id", "host", "user"}]
        detail = ", ".join(f"{k}={str(e[k])[:40]}" for k in detail_keys[:3])
        table.add_row(ts, action, str(ta), detail)
    console.print(table)
    return 0


# ---------------------------------------------------------------------------
# Monthly backup (tar + gpg) per v0.2 Decision 14
# ---------------------------------------------------------------------------
@dataclass
class BackupResult:
    archive_path: Path | None
    encrypted_path: Path | None
    files_archived: int
    error: str | None = None


def backup(repo_root: Path) -> BackupResult:
    """Create a tar of the audit/ tree and (if configured) gpg-encrypt it.

    Destination from env FORGE_AUDIT_BACKUP_DIR; gpg recipient from
    FORGE_AUDIT_GPG_RECIPIENT. Returns BackupResult.
    """
    audit_root = repo_root / "audit"
    if not audit_root.is_dir():
        return BackupResult(None, None, 0, "no audit/ directory")

    dest_dir = os.environ.get("FORGE_AUDIT_BACKUP_DIR")
    if not dest_dir:
        return BackupResult(None, None, 0, "FORGE_AUDIT_BACKUP_DIR not set")

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    archive_name = f"forge-audit-{now:%Y%m%d-%H%M%S}.tar"
    archive_path = dest / archive_name
    files_archived = 0
    with tarfile.open(archive_path, "w") as tar:
        for f in audit_root.rglob("*.jsonl"):
            tar.add(f, arcname=str(f.relative_to(audit_root)))
            files_archived += 1

    recipient = os.environ.get("FORGE_AUDIT_GPG_RECIPIENT")
    encrypted_path: Path | None = None
    if recipient:
        encrypted_path = archive_path.with_suffix(".tar.gpg")
        proc = subprocess.run(
            [
                "gpg", "--batch", "--yes",
                "--encrypt", "--recipient", recipient,
                "--output", str(encrypted_path),
                str(archive_path),
            ],
            capture_output=True, text=True,
        )
        if proc.returncode == 0:
            archive_path.unlink()  # keep only the encrypted copy
        else:
            return BackupResult(archive_path, None, files_archived, f"gpg failed: {proc.stderr.strip()}")

    return BackupResult(
        archive_path=None if encrypted_path else archive_path,
        encrypted_path=encrypted_path,
        files_archived=files_archived,
    )
