"""forge CLI — entry point.

See ULTRAPLAN-AI-FRAMEWORK-v0.2.md Section 3.5 for the full CLI contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

from forge import __version__
from forge.commands import (
    adopt as adopt_cmd,
    apps as apps_cmd,
    audit as audit_cmd,
    commit as commit_cmd,
    discover as discover_cmd,
    ledger as ledger_cmd,
    render as render_cmd,
    score as score_cmd,
    skills as skills_cmd,
    stats as stats_cmd,
    sync as sync_cmd,
    test as test_cmd,
    validate as validate_cmd,
)


def _load_env_files() -> None:
    """Auto-load `.env` from the repo root and the current working directory.

    Repo-root `.env` wins (covers the common case of running forge from any
    subdirectory of the repo). Cwd `.env` is a fallback for ad-hoc setups.
    Existing environment variables are NOT overridden — explicit `export`
    in the shell always takes precedence.
    """
    # Walk upward from cwd looking for forge.config.yaml (the repo root marker)
    current = Path.cwd().resolve()
    for parent in [current, *current.parents]:
        if (parent / "forge.config.yaml").is_file():
            env_path = parent / ".env"
            if env_path.is_file():
                load_dotenv(env_path, override=False)
            break
    # Fallback: cwd/.env if cwd isn't inside a forge repo
    cwd_env = current / ".env"
    if cwd_env.is_file():
        load_dotenv(cwd_env, override=False)


_load_env_files()

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
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Write into apps whose git remote is not ours without asking. "
        "Without it, an unattended run skips them.",
    ),
    target: Optional[str] = typer.Option(
        None,
        "--target",
        help="Which repo to render into: 'bench' (default) or 'self' (this repo).",
    ),
    all_targets: bool = typer.Option(
        False,
        "--all-targets",
        help="Sync every declared target, each with its own enabled_tools.",
    ),
    prune_harness: bool = typer.Option(
        False,
        "--prune-harness",
        help="Delete harness scripts the render no longer produces. Opt-in: the "
             "swap never deletes, so an orphaned script would otherwise linger.",
    ),
    prune: bool = typer.Option(
        False,
        "--prune",
        help="Delete outputs a manifest records but the render no longer "
             "produces — what a changed `output:` leaves behind. Orphans are "
             "reported without this flag; files with no manifest row, and "
             "hand-edited ones, are never removed.",
    ),
) -> None:
    """Render and sync canonical artifacts into a target (transactional per file)."""
    sync_cmd.run(
        tool=tool, all_tools=all_tools, dry_run=dry_run, justify=justify,
        assume_yes=yes, target=target, all_targets=all_targets,
        prune_harness_dir=prune_harness, prune=prune,
    )


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
# apps
# ---------------------------------------------------------------------------
apps_app = typer.Typer(
    help="Choose which apps forge writes per-app instruction files into.",
    no_args_is_help=False,
    invoke_without_command=True,
)
app.add_typer(apps_app, name="apps")


@apps_app.callback()
def apps_default(ctx: typer.Context) -> None:
    """List every app, whether forge manages it, and the remote it points at."""
    if ctx.invoked_subcommand is None:
        raise typer.Exit(apps_cmd.run_list())


@apps_app.command("add")
def apps_add(
    names: list[str] = typer.Argument(..., help="App name(s) to start managing."),
) -> None:
    """Start writing per-app instruction files into these apps."""
    raise typer.Exit(apps_cmd.run_add(names))


@apps_app.command("remove")
def apps_remove(
    names: list[str] = typer.Argument(..., help="App name(s) to stop managing."),
    prune: bool = typer.Option(
        False,
        "--prune",
        help="Also delete files already written into those apps.",
    ),
) -> None:
    """Stop writing per-app files into these apps (third-party repos, usually)."""
    raise typer.Exit(apps_cmd.run_remove(names, prune=prune))


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------
skills_app = typer.Typer(
    help="Skills provenance lockfile — detect unreviewed drift in external skills.",
)
app.add_typer(skills_app, name="skills")


@skills_app.command("verify")
def skills_verify() -> None:
    """Verify every provenance: external skill against canonical/skills-lock.json."""
    skills_cmd.run_verify()


@skills_app.command("list")
def skills_list() -> None:
    """List every skill with its provenance (internal/external)."""
    skills_cmd.run_list()


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------
ledger_app = typer.Typer(
    help="Reconcile vault tickets against the repo build ledger.",
)
app.add_typer(ledger_app, name="ledger")


@ledger_app.command("sync")
def ledger_sync(
    project: str = typer.Option(..., "--project", help="Vault project, e.g. novizna-pos."),
    target: Optional[str] = typer.Option(
        None, "--target", help="Which target's ledger to check. Default: bench."
    ),
    vault_path: Optional[Path] = typer.Option(
        None, "--vault-path", help="Override vault discovery ($NOVIZNA_VAULT, brains.toml)."
    ),
    fix: bool = typer.Option(
        False, "--fix",
        help="Seed a `todo` row for tickets with no ledger coverage. Never touches "
             "the vault, never edits an existing row, never removes an orphan row.",
    ),
) -> None:
    """Report vault tickets with no ledger coverage, and orphan ledger rows.

    Does not sync field values — the vault's `status:` and the ledger's
    `build_state:` are deliberately independent (see definition-of-done.md).
    This only checks that every actively-worked ticket has SOME ledger row.
    """
    ledger_cmd.run_sync(project, target, vault_path, fix)


# ---------------------------------------------------------------------------
# adopt
# ---------------------------------------------------------------------------
@app.command()
def adopt(
    tool: str = typer.Option(
        "claude-code",
        "--tool",
        help="Adapter whose outputs to inspect for hand edits.",
    ),
    app_name: Optional[str] = typer.Option(
        None,
        "--app",
        help="Limit adoption to one app (e.g. --app novizna_pos).",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write the changes. Without this, adopt only reports what it would do.",
    ),
) -> None:
    """Fold hand edits in generated files back into canonical/apps/<app>.md.

    `forge sync` refuses to overwrite a file someone edited by hand; this is how
    that edit gets back into the source of truth so the next sync keeps it.
    """
    raise typer.Exit(adopt_cmd.run(tool=tool, app=app_name, apply=apply))


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
    console.print("\n[cyan]Suggested CHANGELOG line:[/cyan]")
    console.print(f"  {result.changelog_line}")


@app.command()
def diff(
    tool: str = typer.Option(..., "--tool", help="Adapter to diff, e.g. claude-code"),
    content: bool = typer.Option(
        True, "--content/--no-content", help="Show the unified diff body, not just the file list"
    ),
    unchanged: bool = typer.Option(
        False, "--unchanged", help="Also list files that would not change"
    ),
    target: Optional[str] = typer.Option(
        None, "--target", help="Which repo to diff against: 'bench' (default) or 'self'."
    ),
) -> None:
    """Show what `forge sync --tool <tool>` would change. Writes nothing.

    Worth running before any sync you cannot easily eyeball afterwards — the
    settings.json merge and the executable hook scripts in particular.
    """
    from forge.commands import diff as diff_cmd

    raise typer.Exit(
        code=diff_cmd.run(
            tool, show_content=content, show_unchanged=unchanged, target=target
        )
    )


if __name__ == "__main__":
    app()
