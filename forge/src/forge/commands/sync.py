"""`forge sync` — render and atomically swap into the bench."""

from __future__ import annotations

from typing import Optional

import typer

from forge.sync import run_sync


def run(
    tool: Optional[str],
    all_tools: bool,
    dry_run: bool,
    justify: Optional[str],
    assume_yes: bool = False,
    target: Optional[str] = None,
    all_targets: bool = False,
    prune_harness_dir: bool = False,
    prune: bool = False,
) -> None:
    exit_code = run_sync(
        tool=tool, all_tools=all_tools, dry_run=dry_run, justify=justify,
        assume_yes=assume_yes, target=target, all_targets=all_targets,
        prune_harness_dir=prune_harness_dir, prune=prune,
    )
    if exit_code != 0:
        raise typer.Exit(code=exit_code)
