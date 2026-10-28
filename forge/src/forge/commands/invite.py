"""`forge invite` — print ready-to-paste install commands for a teammate.

Asks which of your overlay settings to hand over (company apps, owned remotes,
anything else you have set), optionally a read-only GitHub token, and prints a
Linux/WSL command and a Windows PowerShell command that install forge and run
`forge setup` with those answers filled in. The teammate is only asked for what
differs per machine: their bench path and site.

    forge invite "Ali"
    forge invite --all --no-token
    forge invite --only bench.managed_apps,bench.owned_remotes --token github_pat_...

The command carries the settings base64-encoded (not encrypted). If it carries
a token, share it the way you would share the token itself.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from rich.console import Console

from forge.commands.setup import MACHINE_KEYS, encode_invite
from forge.loader import find_repo_root, load_forge_config
from forge.user_config import overlay_path, read_overlay

console = Console()

DEFAULT_REPO = "Kirito70/erpnext-ai-forge"
Ask = Callable[[str, str], str]


def copyable_items(overlay: dict[str, Any]) -> dict[str, Any]:
    """Overlay settings flattened to `section.key`, minus machine-specific ones."""
    items: dict[str, Any] = {}
    for key, value in overlay.items():
        if isinstance(value, dict):
            for sub, sub_value in value.items():
                if key == "bench" and sub in MACHINE_KEYS:
                    continue
                items[f"{key}.{sub}"] = sub_value
        else:
            items[key] = value
    return items


def unflatten(items: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for dotted, value in items.items():
        if "." in dotted:
            section, key = dotted.split(".", 1)
            out.setdefault(section, {})[key] = value
        else:
            out[dotted] = value
    return out


def install_commands(repo: str, payload: str, token: str | None) -> tuple[str, str]:
    """(linux, windows) one-liners."""
    if token:
        api = f"https://api.github.com/repos/{repo}/contents/scripts"
        linux = (
            f'curl -fsSL -H "Authorization: Bearer {token}" -H "Accept: application/vnd.github.raw" '
            f"{api}/install.sh | FORGE_REPO='{repo}' FORGE_GITHUB_TOKEN='{token}' "
            f"FORGE_INVITE='{payload}' bash"
        )
        windows = (
            f"$env:FORGE_REPO='{repo}'; $env:FORGE_GITHUB_TOKEN='{token}'; "
            f"$env:FORGE_INVITE='{payload}'; "
            f"irm -Headers @{{Authorization='Bearer {token}'; Accept='application/vnd.github.raw'}} "
            f"{api}/install.ps1 | iex"
        )
    else:
        dl = f"https://github.com/{repo}/releases/latest/download"
        linux = f"curl -fsSL {dl}/install.sh | FORGE_REPO='{repo}' FORGE_INVITE='{payload}' bash"
        windows = (
            f"$env:FORGE_REPO='{repo}'; $env:FORGE_INVITE='{payload}'; irm {dl}/install.ps1 | iex"
        )
    return linux, windows


def _choose(items: dict[str, Any], ask: Ask, copy_all: bool, only: list[str] | None) -> dict[str, Any]:
    if only is not None:
        unknown = [k for k in only if k not in items]
        if unknown:
            raise ValueError(f"not in your settings: {', '.join(unknown)} (have: {', '.join(items)})")
        return {k: items[k] for k in only}
    if copy_all:
        return dict(items)
    chosen: dict[str, Any] = {}
    for key, value in items.items():
        if ask(f"Copy {key} = {value!r}? (Y/n)", "Y").strip().lower() not in ("n", "no"):
            chosen[key] = value
    return chosen


def run_invite(
    name: str | None = None,
    *,
    copy_all: bool = False,
    only: list[str] | None = None,
    token: str | None = None,
    no_token: bool = False,
    ask: Ask | None = None,
    ask_secret: Callable[[str], str] | None = None,
) -> int:
    repo_root = find_repo_root()
    ask = ask or _typer_ask
    overlay = read_overlay(repo_root)
    items = copyable_items(overlay)
    if not items:
        console.print(
            f"[yellow]![/yellow] {overlay_path(repo_root)} has no settings to share yet; "
            "the invite will only install forge. Run [cyan]forge setup[/cyan] first to include your apps."
        )
    settings = unflatten(_choose(items, ask, copy_all, only))

    if no_token:
        token = None
    elif token is None:
        token = os.environ.get("FORGE_GITHUB_TOKEN") or (ask_secret or _typer_secret)(
            "Read-only GitHub token (only needed if the repo is private; Enter to skip)"
        ).strip() or None

    repo = str((load_forge_config(repo_root).get("distribution") or {}).get("repo") or DEFAULT_REPO)
    linux, windows = install_commands(repo, encode_invite(settings), token)

    who = f" for {name}" if name else ""
    console.print(f"\n[bold]Install{who}[/bold] — they will be asked only for their bench path and site.\n")
    console.print("[bold]Linux / WSL / macOS[/bold] (bash):")
    console.print(linux, soft_wrap=True, highlight=False, markup=False)
    console.print("\n[bold]Windows[/bold] (PowerShell; installs into WSL2, where the bench runs):")
    console.print(windows, soft_wrap=True, highlight=False, markup=False)
    shared = ", ".join(copyable_items(settings)) or "nothing (defaults only)"
    console.print(f"\n[dim]Carries: {shared}.[/dim]")
    if token:
        console.print("[yellow]![/yellow] These commands contain the token. Send them privately.")
    return 0


def _typer_ask(prompt: str, default: str) -> str:
    import typer

    return str(typer.prompt(prompt, default=default))


def _typer_secret(prompt: str) -> str:
    import typer

    return str(typer.prompt(prompt, default="", hide_input=True, show_default=False))
