"""`forge score` — security score canonical artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
from rich.console import Console

from forge.loader import find_repo_root
from forge.scoring import render_score_report, score_path

console = Console()


def _staged_files(repo_root: Path) -> list[Path]:
    """Return git-staged files inside canonical/ (and other relevant dirs)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=repo_root, capture_output=True, text=True, check=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        candidate = repo_root / line
        if candidate.is_file() and candidate.suffix in {".md", ".yaml", ".yml", ".py", ".j2"}:
            paths.append(candidate)
    return paths


def run(path: Path, staged: bool, fail_below: int) -> None:
    repo_root = find_repo_root()
    if staged:
        targets = _staged_files(repo_root)
        if not targets:
            console.print("[green]No staged files to score.[/green]")
            return
        results = []
        for t in targets:
            from forge.scoring import score_file
            results.append(score_file(t, repo_root))
    else:
        target = (repo_root / path) if not path.is_absolute() else path
        results = score_path(target, repo_root)

    report, exit_code = render_score_report(results, fail_below)
    console.print(report)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)
