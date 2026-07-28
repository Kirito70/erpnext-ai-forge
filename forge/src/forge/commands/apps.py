"""`forge apps` — choose which apps forge writes per-app instruction files into.

A bench mixes apps we own with apps that merely happen to be installed. Forge
generating a `CLAUDE.md` into the second kind puts an unwanted diff in someone
else's repository, so per-app rendering is opt-in: `bench.managed_apps` in
forge.config.yaml lists the apps forge may write to, and everything else is
skipped by both render paths.

This command is the way to see and edit that list without hand-editing YAML,
and — more usefully — to tell the two kinds of app apart, by showing the git
remote each one actually points at.

    forge apps                          # what is managed, what is skipped, and why
    forge apps add novizna_billing
    forge apps remove cargo_management --prune

`remove` alone only stops FUTURE syncs; files already written stay on disk.
`--prune` deletes them, which is almost always what you meant.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from rich.console import Console
from rich.table import Table

from forge.loader import find_repo_root, load_discovery, load_forge_config

console = Console()

MANAGED_KEY = "managed_apps"
_PER_APP_FILES = ("CLAUDE.md", ".forge-manifest.json")


def _bench_root(repo_root: Path) -> Path:
    cfg = load_forge_config(repo_root)
    return Path(
        cfg["bench"]["path"].replace(
            "{{ env.FORGE_BENCH_PATH }}", os.environ.get("FORGE_BENCH_PATH", "")
        )
    )


def _git_remote(app_dir: Path) -> str | None:
    """The app's push remote, or None when it is not a git repo at all."""
    if not (app_dir / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(app_dir), "remote"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        remotes = out.stdout.split()
        if not remotes:
            return None
        # `origin` when present, else whatever the single remote is called —
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


def _owner_of(remote: str | None) -> str | None:
    """Extract the org/user from a git remote URL, SSH or HTTPS."""
    if not remote:
        return None
    match = re.search(r"[:/]([^/:]+)/[^/]+?(?:\.git)?/?$", remote)
    return match.group(1) if match else None


def _read_managed(repo_root: Path) -> list[str]:
    cfg = load_forge_config(repo_root)
    return list((cfg.get("bench") or {}).get(MANAGED_KEY) or [])


def _write_managed(repo_root: Path, apps: list[str]) -> None:
    """Rewrite the managed_apps list in place, preserving comments.

    forge.config.yaml is heavily commented and PyYAML round-tripping would
    discard every one of those comments, so this rewrites just the list items
    under the existing key and leaves the rest of the file byte-identical.
    """
    path = repo_root / "forge.config.yaml"
    text = path.read_text()

    match = re.search(
        rf"^(?P<indent>[ \t]*){MANAGED_KEY}:[ \t]*\n(?P<items>(?:[ \t]*-[ \t]*\S.*\n)*)",
        text,
        re.M,
    )
    if not match:
        raise ValueError(
            f"`{MANAGED_KEY}:` not found in {path}. Add it under `bench:` first."
        )

    indent = match.group("indent")
    item_indent = indent + "  "
    rendered = "".join(f"{item_indent}- {app}\n" for app in apps)
    if not apps:
        # An empty YAML list is not the same as an absent one: absent means "no
        # restriction" to the renderer, which would write into every app.
        rendered = f"{item_indent}[]\n"

    start, end = match.span()
    path.write_text(text[:start] + f"{indent}{MANAGED_KEY}:\n" + rendered + text[end:])


def _discovered_apps(repo_root: Path) -> list[str]:
    discovery = load_discovery(repo_root)
    return [a["name"] for a in discovery.apps.get("custom_apps", [])]


def run_list(repo_root: Path | None = None) -> int:
    repo_root = repo_root or find_repo_root()
    managed = _read_managed(repo_root)
    bench_root = _bench_root(repo_root)
    apps = sorted(set(_discovered_apps(repo_root)) | set(managed))

    # Whatever orgs our managed apps live in are "ours"; an unmanaged app from
    # a different org is the third-party case this list exists to keep out.
    our_owners = {
        owner
        for app in managed
        if (owner := _owner_of(_git_remote(bench_root / "apps" / app)))
    }

    table = Table(title="Per-app instruction files", title_justify="left")
    table.add_column("app")
    table.add_column("status")
    table.add_column("remote owner")
    table.add_column("notes")
    table.add_column("on disk")

    for app in apps:
        app_dir = bench_root / "apps" / app
        owner = _owner_of(_git_remote(app_dir))
        is_managed = app in managed
        has_notes = (repo_root / "canonical" / "apps" / f"{app}.md").is_file()
        on_disk = (app_dir / "CLAUDE.md").is_file()

        if is_managed:
            status = "[green]managed[/green]"
        elif owner and our_owners and owner not in our_owners:
            status = "[yellow]skipped (third-party)[/yellow]"
        else:
            status = "[dim]skipped[/dim]"

        notes = (
            "[green]yes[/green]"
            if has_notes
            else ("[red]MISSING[/red]" if is_managed else "[dim]—[/dim]")
        )
        disk = "yes" if on_disk else "[dim]—[/dim]"
        if on_disk and not is_managed:
            disk = "[yellow]stale[/yellow]"

        table.add_row(app, status, owner or "[dim]—[/dim]", notes, disk)

    console.print(table)

    stale = [
        a for a in apps if a not in managed and (bench_root / "apps" / a / "CLAUDE.md").is_file()
    ]
    if stale:
        console.print(
            f"\n[yellow]![/yellow] {len(stale)} unmanaged app(s) still carry a generated "
            f"file from an earlier sync: {', '.join(stale)}\n"
            f"    Remove with [cyan]forge apps remove {stale[0]} --prune[/cyan]."
        )
    missing_notes = [
        a for a in managed if not (repo_root / "canonical" / "apps" / f"{a}.md").is_file()
    ]
    if missing_notes:
        console.print(
            f"\n[yellow]![/yellow] managed but no canonical notes: {', '.join(missing_notes)}\n"
            f"    They render a contentless stub until "
            f"canonical/apps/<app>.md exists."
        )
    return 0


def run_add(names: list[str], repo_root: Path | None = None) -> int:
    repo_root = repo_root or find_repo_root()
    managed = _read_managed(repo_root)
    discovered = set(_discovered_apps(repo_root))

    added: list[str] = []
    for name in names:
        if name in managed:
            console.print(f"[dim]already managed:[/dim] {name}")
            continue
        if name not in discovered:
            console.print(
                f"[yellow]![/yellow] {name} is not a custom app in this bench "
                f"(discovery knows: {', '.join(sorted(discovered))}). Adding anyway — "
                f"re-run [cyan]forge discover[/cyan] if the app is new."
            )
        managed.append(name)
        added.append(name)

    if not added:
        return 0

    _write_managed(repo_root, managed)
    console.print(f"[green]✓[/green] managing {', '.join(added)}")
    for name in added:
        if not (repo_root / "canonical" / "apps" / f"{name}.md").is_file():
            console.print(
                f"    next: write [cyan]canonical/apps/{name}.md[/cyan], "
                f"else it renders a contentless stub."
            )
    console.print("    then [cyan]forge sync --all[/cyan].")
    return 0


def run_remove(names: list[str], prune: bool, repo_root: Path | None = None) -> int:
    repo_root = repo_root or find_repo_root()
    managed = _read_managed(repo_root)
    bench_root = _bench_root(repo_root)

    removed = [n for n in names if n in managed]
    unknown = [n for n in names if n not in managed]
    for name in unknown:
        console.print(f"[dim]not managed:[/dim] {name}")

    if removed:
        _write_managed(repo_root, [a for a in managed if a not in removed])
        console.print(f"[green]✓[/green] no longer managing {', '.join(removed)}")

    # Dropping the name stops future writes; it does not clean up past ones.
    targets = removed + unknown
    pruned: list[Path] = []
    leftovers: list[Path] = []
    for name in targets:
        for filename in _PER_APP_FILES:
            path = bench_root / "apps" / name / filename
            if not path.is_file():
                continue
            if prune:
                path.unlink()
                pruned.append(path)
            else:
                leftovers.append(path)

    if pruned:
        console.print(f"[green]✓[/green] pruned {len(pruned)} generated file(s):")
        for path in pruned:
            console.print(f"    {path}")
        console.print(
            "    Those repos now have a deletion to commit."
        )
    if leftovers:
        console.print(
            f"[yellow]![/yellow] {len(leftovers)} generated file(s) left on disk — "
            f"future syncs will not touch them, but they are still there:"
        )
        for path in leftovers:
            console.print(f"    {path}")
        console.print("    Re-run with [cyan]--prune[/cyan] to delete them.")

    return 0
