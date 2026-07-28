"""Git-remote inspection for bench apps.

Which organisation an app's remote points at is the only reliable signal for
"is this repo ours to write into?". A bench installs upstream apps, vendor
apps and our own side by side, and nothing in the app's own metadata
distinguishes them — but `git remote get-url` always does.

Shared by `forge apps` (which reports ownership) and `forge sync` (which
refuses to write into a foreign repo without confirmation).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_REMOTE_OWNER = re.compile(r"[:/]([^/:]+)/[^/]+?(?:\.git)?/?$")


def git_remote(app_dir: Path) -> str | None:
    """The app's push remote URL, or None if it is not a git repo / has none."""
    if not (app_dir / ".git").exists():
        return None
    try:
        listed = subprocess.run(
            ["git", "-C", str(app_dir), "remote"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        remotes = listed.stdout.split()
        if not remotes:
            return None
        # `origin` when present, else the single remote whatever it is called —
        # several apps in this bench use `upstream` as their only remote.
        name = "origin" if "origin" in remotes else remotes[0]
        url = subprocess.run(
            ["git", "-C", str(app_dir), "remote", "get-url", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return url.stdout.strip() or None
    except (subprocess.SubprocessError, OSError):
        return None


def remote_owner(remote: str | None) -> str | None:
    """Extract the org/user from a git remote URL, SSH or HTTPS form."""
    if not remote:
        return None
    match = _REMOTE_OWNER.search(remote)
    return match.group(1) if match else None


def owner_of_app(bench_root: Path, app: str) -> str | None:
    return remote_owner(git_remote(bench_root / "apps" / app))


def is_foreign(owner: str | None, owned_remotes: set[str]) -> bool:
    """Whether writing into this app means writing into someone else's repo.

    An app with no discoverable remote is NOT treated as foreign: it is
    usually a local-only or freshly-scaffolded app, and blocking those would
    be noise. The check exists to stop us pushing generated files at other
    organisations, not to police unpublished work.
    """
    if not owned_remotes or owner is None:
        return False
    return owner not in owned_remotes
