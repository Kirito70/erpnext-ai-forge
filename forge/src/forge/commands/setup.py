"""`forge setup` — write the overlay config for this machine.

Asks for the bench and site, then lists the bench's apps that are not
upstream Frappe apps and asks which belong to your company. Nothing about any
company is baked into forge: the candidates come from the bench on disk, and
the answers land in the overlay (`~/.forge.yaml` for installed copies).

An invite (`forge invite`) pre-answers the company questions; the bench and
site are always asked, because they differ per machine.

    forge setup
    forge setup --invite <payload> --bench /srv/bench --site site1 --yes
"""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.table import Table

from forge.loader import find_repo_root, load_forge_config
from forge.repo import owner_of_app
from forge.user_config import overlay_path, read_overlay, write_overlay

console = Console()

Ask = Callable[[str, str], str]

# Machine-specific; an invite never carries them.
MACHINE_KEYS = ("path", "primary_site")


@dataclass(frozen=True)
class BenchApp:
    name: str
    owner: str | None


def decode_invite(payload: str) -> dict[str, Any]:
    """The settings an invite carries. Raises ValueError on a corrupt payload."""
    try:
        text = base64.b64decode(payload.strip(), validate=True).decode()
        data = yaml.safe_load(text) or {}
    except (binascii.Error, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"invite is not valid (was it copied whole?): {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("invite is not valid: expected a mapping of settings")
    bench = data.get("bench")
    if isinstance(bench, dict):
        data = {**data, "bench": {k: v for k, v in bench.items() if k not in MACHINE_KEYS}}
    return data


def encode_invite(settings: dict[str, Any]) -> str:
    return base64.b64encode(yaml.safe_dump(settings, sort_keys=False).encode()).decode()


def scan_bench_apps(bench: Path, upstream: set[str]) -> list[BenchApp]:
    """Every app directory in the bench that is not an upstream Frappe app."""
    apps_dir = bench / "apps"
    if not apps_dir.is_dir():
        return []
    names = sorted(
        p.name
        for p in apps_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name not in upstream
    )
    return [BenchApp(name, owner_of_app(bench, name)) for name in names]


def list_sites(bench: Path) -> list[str]:
    sites = bench / "sites"
    if not sites.is_dir():
        return []
    return sorted(p.parent.name for p in sites.glob("*/site_config.json"))


def parse_selection(answer: str, apps: list[BenchApp], default: list[str]) -> list[str]:
    """Numbers or names, comma/space separated; blank keeps `default`; `none` clears."""
    answer = answer.strip()
    if not answer:
        return list(default)
    if answer.lower() == "none":
        return []
    by_number = {str(i): a.name for i, a in enumerate(apps, 1)}
    known = {a.name for a in apps}
    picked: list[str] = []
    for token in answer.replace(",", " ").split():
        name = by_number.get(token, token)
        if name not in known:
            raise ValueError(f"{token!r} is not one of the listed apps")
        if name not in picked:
            picked.append(name)
    return picked


def default_selection(
    apps: list[BenchApp], invited: list[str], owned_remotes: list[str]
) -> list[str]:
    """Invited apps present on this bench; else apps under an owned remote."""
    present = [a.name for a in apps]
    if invited:
        return [n for n in invited if n in present]
    owned = set(owned_remotes)
    return [a.name for a in apps if a.owner and a.owner in owned]


def _literal(value: Any) -> str:
    """A configured value, or '' when it is still the `{{ env.X }}` default."""
    text = "" if value is None else str(value)
    return "" if "{{" in text else text


def _ask_bench(ask: Ask, default: str, assume_yes: bool) -> Path:
    for _ in range(3):
        answer = default if assume_yes and default else ask("Absolute path to your Frappe bench", default)
        bench = Path(answer).expanduser()
        if bench.is_absolute() and (bench / "apps").is_dir():
            return bench
        console.print(f"[yellow]![/yellow] {bench} is not a bench (no apps/ directory).")
        if assume_yes:
            break
    raise ValueError("no valid bench path given")


def _show_apps(apps: list[BenchApp], selected: list[str]) -> None:
    table = Table(title="Apps on this bench that are not upstream Frappe apps", title_justify="left")
    table.add_column("#", justify="right")
    table.add_column("app")
    table.add_column("remote owner")
    table.add_column("default")
    for i, app in enumerate(apps, 1):
        table.add_row(str(i), app.name, app.owner or "[dim]local[/dim]", "✓" if app.name in selected else "")
    console.print(table)


def run_setup(
    repo_root: Path | None = None,
    *,
    bench: str | None = None,
    site: str | None = None,
    invite: str | None = None,
    assume_yes: bool = False,
    if_needed: bool = False,
    ask: Ask | None = None,
) -> int:
    repo_root = repo_root or find_repo_root()
    if if_needed and not invite and not needs_setup(repo_root):
        console.print(f"[dim]settings kept: {overlay_path(repo_root)} (re-run `forge setup` to change)[/dim]")
        return 0
    ask = ask or _typer_ask
    cfg = load_forge_config(repo_root)
    current = (read_overlay(repo_root).get("bench") or {})
    invited = decode_invite(invite) if invite else {}
    invited_bench = invited.get("bench") or {}

    if invited:
        console.print("[bold]This invite sets:[/bold]")
        console.print(yaml.safe_dump(invited, sort_keys=False).rstrip())
        if not assume_yes and ask("Apply these settings? (Y/n)", "Y").lower().startswith("n"):
            invited, invited_bench = {}, {}

    bench_default = bench or _literal(current.get("path")) or os.environ.get("FORGE_BENCH_PATH", "")
    bench_path = _ask_bench(ask, bench_default, assume_yes or bool(bench))

    sites = list_sites(bench_path)
    site_default = (
        site
        or _literal(current.get("primary_site"))
        or os.environ.get("FORGE_PRIMARY_SITE", "")
        or (sites[0] if sites else "")
    )
    if site or (assume_yes and site_default):
        site_name = site_default
    else:
        if sites:
            console.print(f"Sites on this bench: {', '.join(sites)}")
        site_name = ask("Primary site name", site_default)
    if not site_name:
        raise ValueError("a primary site name is required")

    upstream = set(cfg.get("upstream_apps") or [])
    apps = scan_bench_apps(bench_path, upstream)
    owned_default = list(invited_bench.get("owned_remotes") or current.get("owned_remotes") or [])
    selected = default_selection(
        apps,
        list(invited_bench.get("managed_apps") or current.get("managed_apps") or []),
        owned_default,
    )
    missing = [n for n in invited_bench.get("managed_apps") or [] if n not in {a.name for a in apps}]
    if missing:
        console.print(f"[yellow]![/yellow] not on this bench, skipped: {', '.join(missing)}")

    if apps and not assume_yes:
        _show_apps(apps, selected)
        while True:
            answer = ask(
                "Your company's apps (numbers or names, comma-separated; 'none' for none)",
                ",".join(selected),
            )
            try:
                selected = parse_selection(answer, apps, selected)
                break
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
    elif not apps:
        console.print("[dim]No non-upstream apps found; add them later with `forge apps add`.[/dim]")

    owners = sorted({a.owner for a in apps if a.name in selected and a.owner})
    owned = owned_default or owners
    if selected and not assume_yes:
        answer = ask("GitHub org(s)/user(s) that own your company's apps", ",".join(owned))
        owned = [o for o in answer.replace(",", " ").split() if o]

    present = {a.name for a in apps}
    lint = sorted(set(selected) | {n for n in invited_bench.get("lint_apps") or [] if n in present})

    updates = {
        **{k: v for k, v in invited.items() if k != "bench"},
        "bench": {
            **{k: v for k, v in invited_bench.items() if k not in ("managed_apps", "lint_apps", "owned_remotes")},
            "path": str(bench_path),
            "primary_site": site_name,
            "owned_remotes": owned,
            "managed_apps": selected,
            "lint_apps": lint,
        },
    }
    path = write_overlay(repo_root, updates)
    console.print(f"[green]✓[/green] settings saved to {path}")
    console.print(
        f"    {len(selected)} company app(s): {', '.join(selected) or '—'}\n"
        "    Change later with [cyan]forge apps add|remove <app>[/cyan] or re-run [cyan]forge setup[/cyan].\n"
        "    Next: [cyan]forge discover[/cyan], then [cyan]forge sync --all --dry-run[/cyan]."
    )
    return 0


def _typer_ask(prompt: str, default: str) -> str:
    import typer

    return str(typer.prompt(prompt, default=default, show_default=bool(default)))


def needs_setup(repo_root: Path) -> bool:
    """True until the overlay names a concrete bench path."""
    if not overlay_path(repo_root).is_file():
        return True
    return not _literal((read_overlay(repo_root).get("bench") or {}).get("path"))
