"""`forge stats` — audit log metrics summary."""

from __future__ import annotations

import json as _json
from typing import Optional

from rich.console import Console

from forge.loader import find_repo_root
from forge.stats import collect_stats, parse_relative_since, render_markdown

console = Console()


def run(since: Optional[str], as_json: bool) -> None:
    repo_root = find_repo_root()
    iso_since = parse_relative_since(since) if since else None
    report = collect_stats(repo_root, since=iso_since)

    if as_json:
        print(_json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return

    console.print(render_markdown(report))
