"""forge CLI — entry point.

Phase 0 skeleton: every command parses its arguments and prints what it would
do, then exits with code 0. Real implementations land in Phase 2 (sync engine,
adapter rendering, audit, etc.) and Phase 4 (security scoring enforcement).

See ULTRAPLAN-AI-FRAMEWORK-v0.2.md Section 3.5 for the full CLI contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from forge import __version__
from forge.commands import (
    audit as audit_cmd,
    commit as commit_cmd,
    discover as discover_cmd,
    render as render_cmd,
    score as score_cmd,
    stats as stats_cmd,
    sync as sync_cmd,
    test as test_cmd,
    validate as validate_cmd,
)

app = typer.Typer(
    name="forge",
    help="erpnext-ai-forge CLI — render canonical AI agent specs into per-tool configs.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"forge {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show forge version and exit.",
    ),
) -> None:
    """erpnext-ai-forge — canonical → per-tool agent config renderer."""


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------
@app.command()
def discover(
    bench: Optional[Path] = typer.Option(
        None,
        "--bench",
        help="Path to the Frappe bench (overrides FORGE_BENCH_PATH).",
    ),
    app_name: Optional[str] = typer.Option(
        None,
        "--app",
        help="Limit discovery to a single app (e.g. --app novizna_crm).",
    ),
    json_only: bool = typer.Option(
        False,
        "--json-only",
        help="Skip INVENTORY.md regeneration; refresh only discovery/data/*.json.",
    ),
) -> None:
    """Walk the bench and refresh discovery/INVENTORY.md + JSON data."""
    discover_cmd.run(bench=bench, app_name=app_name, json_only=json_only)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
@app.command()
def validate(
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        help="Limit validation to a subtree of canonical/.",
    ),
    check_drift: bool = typer.Option(
        True,
        "--check-drift/--no-check-drift",
        help="Compare bench output against .forge-manifest.json files.",
    ),
) -> None:
    """Schema + drift validation across canonical/ and bench outputs."""
    validate_cmd.run(path=path, check_drift=check_drift)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------
@app.command()
def render(
    tool: str = typer.Option(..., "--tool", help="Target adapter (e.g. claude-code)."),
    out: Path = typer.Option(
        Path("./build"),
        "--out",
        help="Output directory (not written to bench).",
    ),
) -> None:
    """Render canonical → per-tool artifacts into a local build dir without syncing."""
    render_cmd.run(tool=tool, out=out)


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------
@app.command()
def sync(
    tool: Optional[str] = typer.Option(
        None,
        "--tool",
        help="Comma-separated adapter names (e.g. --tool claude-code,cursor).",
    ),
    all_tools: bool = typer.Option(
        False,
        "--all",
        help="Sync every adapter in forge.config.yaml enabled_tools.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Render to staging dir and validate; do not swap into bench.",
    ),
    justify: Optional[str] = typer.Option(
        None,
        "--justify",
        help="One-line justification when a 80–94 score artifact is being synced.",
    ),
) -> None:
    """Render and sync canonical artifacts into the bench (transactional per file)."""
    sync_cmd.run(tool=tool, all_tools=all_tools, dry_run=dry_run, justify=justify)


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------
audit_app = typer.Typer(help="Inspect and manage the append-only audit log.")
app.add_typer(audit_app, name="audit")


@audit_app.command("tail")
def audit_tail(
    n: int = typer.Option(50, "-n", "--lines", help="Number of recent entries."),
    agent: Optional[str] = typer.Option(None, "--filter-agent", help="Substring match on tool_or_agent + action."),
    since: Optional[str] = typer.Option(None, "--since", help="ISO timestamp; entries older are skipped."),
    action: Optional[str] = typer.Option(None, "--action", help="Prefix match on action (e.g. 'sync.', 'discovery.')."),
    grep: Optional[str] = typer.Option(None, "--grep", help="Regex search across raw JSONL lines."),
    as_json: bool = typer.Option(False, "--json", help="Emit raw JSONL on stdout for piping."),
) -> None:
    """Tail the audit JSONL log with optional filters."""
    audit_cmd.tail(n=n, agent=agent, since=since, action=action, grep=grep, as_json=as_json)


@audit_app.command("backup")
def audit_backup() -> None:
    """Create a monthly tar+gpg backup of the audit log (per Decision 14)."""
    audit_cmd.backup()


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------
@app.command()
def score(
    path: Path = typer.Option(
        Path("canonical/"),
        "--path",
        help="Path to score (file or directory).",
    ),
    staged: bool = typer.Option(
        False,
        "--staged",
        help="Score only git-staged files (used by pre-commit hook).",
    ),
    fail_below: int = typer.Option(
        80,
        "--fail-below",
        help="Exit non-zero if any file scores below this threshold.",
    ),
) -> None:
    """Security score canonical artifacts (deduction-based, starts at 100)."""
    score_cmd.run(path=path, staged=staged, fail_below=fail_below)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------
@app.command()
def stats(
    since: Optional[str] = typer.Option(
        None,
        "--since",
        help="ISO timestamp or duration ('1h', '7d') — restrict to entries since.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit the report as JSON instead of Markdown.",
    ),
) -> None:
    """Audit-log metrics: sync outcomes, score distribution, drift, escalations."""
    stats_cmd.run(since=since, as_json=as_json)


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------
@app.command()
def test(
    update_golden: bool = typer.Option(
        False,
        "--update-golden",
        help="Regenerate golden snapshots (use with care).",
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Run pytest with golden-file fixtures under forge/tests/golden/."""
    test_cmd.run(update_golden=update_golden, verbose=verbose)


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------
@app.command()
def commit(
    message: Optional[str] = typer.Option(
        None,
        "-m",
        "--message",
        help="Commit message body; scope is inferred from staged changes.",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Validate the commit message at .git/COMMIT_EDITMSG against Conventional Commits.",
    ),
) -> None:
    """Helper for scoped Conventional Commits (v0.2 Decision 20)."""
    commit_cmd.run(message=message, check=check)


# ---------------------------------------------------------------------------
# new (skill | agent | command | tool)
# ---------------------------------------------------------------------------
@app.command()
def new(
    kind: str = typer.Argument(..., help="Artifact kind: skill | agent | command | tool"),
    name: str = typer.Argument(..., help="Artifact name (kebab-case)."),
    domain: Optional[str] = typer.Option(None, "--domain", help="For skills: domain subfolder."),
) -> None:
    """Scaffold a new canonical artifact from the appropriate template."""
    console.print(f"[yellow]not yet implemented[/yellow] — would scaffold {kind}/{name}")
    raise typer.Exit(code=0)


@app.command()
def deprecate(
    kind: str = typer.Argument(..., help="Artifact kind: agent | command | skill | tool | policy"),
    name: str = typer.Argument(..., help="Artifact id (file basename without .md/.yaml)"),
    superseded_by: Optional[str] = typer.Option(
        None,
        "--superseded-by",
        help="If supplied, sets `supersedes:` on the replacement artifact.",
    ),
) -> None:
    """Mark an artifact deprecated and move it to canonical/_deprecated/.

    Per governance.md §3, deprecated artifacts are retained for one MINOR
    release cycle before removal. `forge sync` continues to render them
    with a [DEPRECATED] banner during that window.
    """
    from forge.deprecate import deprecate as run_deprecate
    from forge.loader import find_repo_root as _find

    repo_root = _find()
    try:
        result = run_deprecate(repo_root, kind, name, superseded_by=superseded_by)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(f"[green]✓[/green] deprecated {result.artifact_kind}/{result.artifact_id}")
    console.print(f"  moved: {result.source_path.relative_to(repo_root)}")
    console.print(f"     →   {result.new_path.relative_to(repo_root)}")
    if result.superseded_by_path:
        console.print(
            f"  supersedes: set on {result.superseded_by_path.relative_to(repo_root)}"
        )
    console.print(f"\n[cyan]Suggested CHANGELOG line:[/cyan]")
    console.print(f"  {result.changelog_line}")


@app.command()
def diff(
    tool: str = typer.Option(..., "--tool"),
) -> None:
    """Show what `forge sync --tool <tool>` would change in the bench."""
    console.print(f"[yellow]not yet implemented[/yellow] — would diff for tool={tool}")
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
