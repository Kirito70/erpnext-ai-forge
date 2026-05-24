"""`forge test` — wrap pytest with golden-file fixtures."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from forge.loader import find_repo_root


def run(update_golden: bool, verbose: bool) -> None:
    repo_root = find_repo_root()
    test_dir = repo_root / "forge" / "tests"
    args = [sys.executable, "-m", "pytest", str(test_dir)]
    if verbose:
        args.append("-v")
    if update_golden:
        # Each golden test reads FORGE_UPDATE_GOLDEN; set it for the child
        import os
        os.environ["FORGE_UPDATE_GOLDEN"] = "1"
    exit_code = subprocess.call(args, cwd=repo_root)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)
