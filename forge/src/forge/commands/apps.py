"""`forge apps` — choose which apps forge writes per-app instruction files into.

A bench mixes apps we own with apps that merely happen to be installed. Forge
generating a `CLAUDE.md` into the second kind puts an unwanted diff in someone
else's repository, so per-app rendering is opt-in: `bench.managed_apps` in
the overlay config (see forge.user_config) lists the apps forge may write to,
and everything else is skipped by both render paths.

This command is the way to see and edit that list without hand-editing YAML,
and — more usefully — to tell the two kinds of app apart, by showing the git
remote each one actually points at.

    forge apps                          # what is managed, what is skipped, and why
    forge apps add acme_billing
    forge apps remove cargo_management --prune

`remove` alone only stops FUTURE syncs; files already written stay on disk.
`--prune` deletes them, which is almost always what you meant.
"""

from __future__ import annotations

from pathlib import Path

from jinja2.exceptions import UndefinedError

from rich.console import Console
from rich.table import Table

from forge.commands.setup import scan_bench_apps
from forge.loader import find_repo_root, load_forge_config, load_target
from forge.manifest import read_manifest, sha256_text
from forge.repo import git_remote as _git_remote, is_foreign, remote_owner as _owner_of
from forge.user_config import write_bench_list

console = Console()

MANAGED_KEY = "managed_apps"
_PER_APP_FILES = ("CLAUDE.md", ".forge-manifest.json")




def _read_managed(repo_root: Path) -> list[str]:
    cfg = load_forge_config(repo_root)
    return list((cfg.get("bench") or {}).get(MANAGED_KEY) or [])


def _write_managed(repo_root: Path, apps: list[str]) -> None:
    path = write_bench_list(repo_root, MANAGED_KEY, apps)
    console.print(f"[dim]saved to {path}[/dim]")


def _discovered_apps(repo_root: Path) -> list[str]:
    """Non-upstream apps in the bench on disk.

    Read live rather than from the discovery snapshot: the snapshot is whatever
    bench last ran `forge discover`, which for an installed copy is not this
    user's bench, and listing it would show another company's apps.
    """
    upstream = set(load_forge_config(repo_root).get("upstream_apps") or [])
    try:
        bench_root = load_target(repo_root).root
    except (KeyError, ValueError, FileNotFoundError, UndefinedError):
        return []  # no bench configured yet: `forge setup` has not run
    return [a.name for a in scan_bench_apps(bench_root, upstream)]


def run_list(repo_root: Path | None = None) -> int:
    repo_root = repo_root or find_repo_root()
    managed = _read_managed(repo_root)
    bench_root = load_target(repo_root).root
    apps = sorted(set(_discovered_apps(repo_root)) | set(managed))

    # `bench.owned_remotes` is the authority on which orgs are ours; falling
    # back to the orgs our managed apps live in keeps this useful on a bench
    # that has not declared the key yet.
    cfg = load_forge_config(repo_root)
    our_owners = set((cfg.get("bench") or {}).get("owned_remotes") or [])
    if not our_owners:
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

        foreign = is_foreign(owner, our_owners)
        if is_managed and foreign:
            # Configured to write, but into a repo that is not ours — sync will
            # stop and ask before creating anything here.
            status = "[red]managed (FOREIGN)[/red]"
        elif is_managed:
            status = "[green]managed[/green]"
        elif foreign:
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
                f"[yellow]![/yellow] {name} is not in this bench's apps/ "
                f"(found: {', '.join(sorted(discovered)) or 'none'}). Adding anyway."
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
    bench_root = load_target(repo_root).root

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
    kept_edits: list[Path] = []
    for name in targets:
        app_dir = bench_root / "apps" / name
        manifest = read_manifest(app_dir)
        recorded = {e.path: e.sha256 for e in manifest.outputs} if manifest else {}
        for filename in _PER_APP_FILES:
            path = app_dir / filename
            if not path.is_file():
                continue
            if not prune:
                leftovers.append(path)
                continue
            # Same two rules as `prune_orphans`: a file with no row is not
            # forge's to delete, and one whose content has moved on carries
            # edits forge never adopted. Unmanaging an app must not be the way
            # to lose them — the manifest goes last, because deleting it first
            # would destroy the evidence for the files after it.
            row = recorded.get(filename)
            if row is None or sha256_text(path.read_text(errors="replace")) != row:
                kept_edits.append(path)
                continue
            path.unlink()
            pruned.append(path)

    if pruned:
        console.print(f"[green]✓[/green] pruned {len(pruned)} generated file(s):")
        for path in pruned:
            console.print(f"    {path}")
        console.print(
            "    Those repos now have a deletion to commit."
        )
    if kept_edits:
        console.print(
            f"[yellow]![/yellow] {len(kept_edits)} file(s) not deleted — forge has no "
            f"record of writing them, or they changed since it did:"
        )
        for path in kept_edits:
            console.print(f"    {path}")
        console.print("    Delete by hand if you are sure. Forge will not.")
    if leftovers:
        console.print(
            f"[yellow]![/yellow] {len(leftovers)} generated file(s) left on disk — "
            f"future syncs will not touch them, but they are still there:"
        )
        for path in leftovers:
            console.print(f"    {path}")
        console.print("    Re-run with [cyan]--prune[/cyan] to delete them.")

    return 0
