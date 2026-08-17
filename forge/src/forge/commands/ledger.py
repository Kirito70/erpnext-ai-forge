"""`forge ledger sync` — reconcile the vault against the repo ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from forge.ledger_sync import (
    parse_ledger_rows,
    _brain_bin,
    parse_vault_tickets,
    reconcile,
    resolve_vault_path,
    seed_missing_rows,
)
from forge.loader import find_repo_root, load_forge_config, load_target

console = Console()


def run_sync(
    project: str, target: Optional[str], vault_path: Optional[Path], fix: bool
) -> None:
    repo_root = find_repo_root()
    forge_cfg = load_forge_config(repo_root)
    tgt = load_target(repo_root, target, forge_cfg=forge_cfg)

    vault, vault_source = resolve_vault_path(vault_path)
    if vault is None:
        console.print(
            "[red]Could not resolve the vault path.[/red] Set $NOVIZNA_VAULT, "
            "configure a default in ~/.config/brain/brains.toml, or pass "
            "--vault-path. Not guessing."
        )
        raise typer.Exit(code=2)

    if vault_source == "brains.toml" and _brain_bin():
        # brain is installed but did not answer. Its registry is the source of
        # truth for where the vault is, so a static default standing in for it
        # can be pointing somewhere that moved.
        console.print(
            f"[yellow]![/yellow] brain is installed but did not answer; using the "
            f"brains.toml default [cyan]{vault}[/cyan]. Check `brain vault path` if "
            f"this is not the vault you expected."
        )

    vault_tickets, unreadable = parse_vault_tickets(vault, project)
    if not vault_tickets:
        console.print(
            f"[yellow]No tickets found under {vault / 'wiki' / project / 'tickets'}[/yellow] "
            f"— check --project."
        )
    if unreadable:
        # Excluded from the comparison below, so say so: a ticket nobody can
        # parse is reported by neither findings branch, and silence here reads
        # as agreement.
        console.print(
            f"[yellow]![/yellow] {len(unreadable)} ticket file(s) could not be parsed "
            f"and were left out of the comparison:"
        )
        for path in unreadable:
            console.print(f"    {path}")

    ledger_rows = parse_ledger_rows(tgt.root)
    findings = reconcile(vault_tickets, ledger_rows)

    console.print(
        f"[cyan]{len(vault_tickets)}[/cyan] vault ticket(s), "
        f"[cyan]{len(ledger_rows)}[/cyan] ledger row(s), target [cyan]{tgt.name}[/cyan]"
        + (f", vault via [cyan]{vault_source}[/cyan]" if vault_source else "")
    )

    if not findings:
        console.print("[green]✓ vault and ledger agree[/green]")
        return

    console.print(f"\n[yellow]{len(findings)} finding(s):[/yellow]")
    for f in findings:
        console.print(f"  • [{f.problem}] {f.detail}")

    if fix:
        seeded = seed_missing_rows(tgt.root, findings)
        if seeded:
            console.print(
                f"\n[green]Seeded {len(seeded)} row(s) in LEDGER-pending.md:[/green] "
                f"{', '.join(seeded)}"
            )
            console.print(
                "[dim]build_state is a conservative 'todo' — verify and correct "
                "through the normal build flow.[/dim]"
            )
        orphans = [f for f in findings if f.problem == "orphan-ledger-row"]
        if orphans:
            console.print(
                f"\n[yellow]{len(orphans)} orphan ledger row(s) were NOT touched[/yellow] "
                f"— --fix only creates missing rows, it never removes or edits one."
            )
        raise typer.Exit(code=0 if not orphans else 1)

    raise typer.Exit(code=1)
