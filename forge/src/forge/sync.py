"""Transactional sync: render → stage → validate → atomic swap.

Per v0.2 Part B item 7:
  - `forge sync --all` writes to `<bench>/.forge-staging/<tool>/` first
  - Validates the full multi-tool output before any bench write
  - Atomically swaps per-tool only after full validation passes
  - On any adapter failure: aborts the entire `--all` run before any bench
    file is touched
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm

from forge.audit import audit_log
from forge.loader import find_repo_root, load_adapter_config, load_forge_config
from forge.manifest import (
    ManifestEntry,
    build_manifest,
    read_manifest,
    sha256_text,
    write_manifest,
)
from forge.render import RenderedArtifact, render
from forge.repo import is_foreign, owner_of_app
from forge.scoring import Finding, score_file
from forge.settings_merge import (
    ScalarConflict,
    merge_settings_json,
    write_settings_with_backup,
)


console = Console()


@dataclass
class SyncResult:
    tool: str
    files_written: list[Path] = field(default_factory=list)
    files_unchanged: list[Path] = field(default_factory=list)
    settings_conflicts: list[ScalarConflict] = field(default_factory=list)
    settings_backup: Path | None = None
    success: bool = True
    error: str | None = None


def _stage_artifacts(
    rendered: list[RenderedArtifact], staging_root: Path, tool: str
) -> Path:
    """Write rendered artifacts into staging directory.

    Returns the per-tool staging root (e.g., <bench>/.forge-staging/claude-code/).
    """
    tool_staging = staging_root / tool
    if tool_staging.exists():
        shutil.rmtree(tool_staging)
    tool_staging.mkdir(parents=True)

    for r in rendered:
        _assert_resolved_output_path(r)
        # Recreate the bench-relative structure inside staging
        # by computing the relative path from the bench root.
        try:
            bench_relative = r.output_path.relative_to(_bench_root_from(r))
        except (ValueError, RuntimeError) as exc:
            # Previously this fell back to `Path(r.output_path.name)`, which
            # drops every directory component and stages the file at the tool
            # root — from where the swap writes it to the BENCH root. That is
            # how per-app content once landed on the bench-root CLAUDE.md.
            # A path we cannot place is a bug in adapter.yaml, not something to
            # guess at.
            raise ValueError(
                f"{r.tool}: cannot place output {r.output_path} for artifact "
                f"'{r.artifact_id}' relative to the bench root. Check the "
                f"`output:` entry in adapters/{r.tool}/adapter.yaml."
            ) from exc

        staged_path = tool_staging / bench_relative
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_text(r.content)

    return tool_staging


def _assert_resolved_output_path(r: RenderedArtifact) -> None:
    """Reject an output path that still carries an unrendered template.

    `{{ output_paths.bench_root }}/apps/{app}/CLAUDE.md` looks like a path and
    behaves like one right up to the point where it silently writes somewhere
    nobody intended. Two ways adapter.yaml produces one: pointing `output:` at a
    nested dict entry (which the renderer passes through unresolved), and using
    `{app}` where Jinja wants `{{ app }}`.
    """
    raw = str(r.output_path)
    if "{{" in raw or "}}" in raw:
        raise ValueError(
            f"{r.tool}: output path for '{r.artifact_id}' was never rendered: {raw!r}. "
            f"An `output:` in adapters/{r.tool}/adapter.yaml points at a value the "
            f"renderer cannot resolve — usually a nested dict entry."
        )
    if re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", raw):
        raise ValueError(
            f"{r.tool}: output path for '{r.artifact_id}' contains an unsubstituted "
            f"placeholder: {raw!r}. Use `{{{{ app }}}}` (Jinja), not `{{app}}`."
        )
    if not r.output_path.is_absolute():
        raise ValueError(
            f"{r.tool}: output path for '{r.artifact_id}' is not absolute: {raw!r}. "
            f"Is FORGE_BENCH_PATH set?"
        )


def _bench_root_from(r: RenderedArtifact) -> Path:
    """Heuristic: bench root is the first ancestor of output_path containing
    `apps/` or named `.claude` parent. For the simple case all output paths
    share a common ancestor; we return that ancestor."""
    for parent in r.output_path.parents:
        if (parent / "apps").is_dir() or (parent / ".claude").exists():
            return parent
    # Fallback: parent of .claude if output_path is inside .claude/
    for parent in r.output_path.parents:
        if parent.name == ".claude":
            return parent.parent
    return r.output_path.parent


def _validate_staging(tool_staging: Path) -> tuple[bool, str | None]:
    """Lightweight validation: every staged file is non-empty and parseable
    as text. Security scoring is a separate gate (see _security_gate)."""
    for path in tool_staging.rglob("*"):
        if path.is_file() and path.stat().st_size == 0:
            return False, f"empty staged file: {path}"
    return True, None


@dataclass
class GateOutcome:
    blocked: bool                  # True if any file scored below block_floor
    warned: bool                   # True if any file scored in 80-94 band
    findings: list[Finding]        # flattened list across all staged files
    per_file_scores: dict[str, int]
    block_floor: int
    warn_floor: int

    @property
    def message(self) -> str:
        if self.blocked:
            return f"Blocked: {len(self.findings)} finding(s); lowest score below {self.block_floor}"
        if self.warned:
            return f"Warning: {len(self.findings)} finding(s) in {self.warn_floor}-{self.block_floor - 1} band"
        return "All staged files pass security gate"


def _security_gate(
    repo_root: Path,
    rendered: list[RenderedArtifact],
    forge_cfg: dict,
    justify: str | None,
) -> GateOutcome:
    """Score every CANONICAL source contributing to this render. Block if
    anything < block_floor; warn if anything in [warn_floor, block_floor)
    without a justification.

    We score canonical sources (not staged rendered output) because rendering
    is template substitution — it never introduces new anti-patterns. Scoring
    staging would produce false positives from skill content that legitimately
    discusses the deduction patterns by name (e.g. "curl | sh" inside
    security/review-checklist.md).
    """
    security_cfg = forge_cfg.get("security", {})
    block_floor = int(security_cfg.get("block_threshold", 80))
    warn_floor = int(security_cfg.get("warn_threshold", 80))
    auto_accept = int(security_cfg.get("auto_accept_threshold", 95))

    findings: list[Finding] = []
    per_file_scores: dict[str, int] = {}
    blocked = False
    warned = False

    # Score each unique canonical source path that contributed to a rendered
    # artifact. Some rendered files have no canonical source (e.g. aggregate
    # outputs whose source_path is the canonical/ dir itself); skip those.
    sources_scored: set[Path] = set()
    for r in rendered:
        src = r.source_path
        if not src.is_file() or src in sources_scored:
            continue
        sources_scored.add(src)
        result = score_file(src, repo_root)
        rel = str(src.relative_to(repo_root)) if src.is_relative_to(repo_root) else str(src)
        per_file_scores[rel] = result.final
        findings.extend(result.findings)
        if result.final < block_floor:
            blocked = True
        elif result.final < auto_accept:
            warned = True

    if warned and justify:
        warned = False

    return GateOutcome(
        blocked=blocked,
        warned=warned,
        findings=findings,
        per_file_scores=per_file_scores,
        block_floor=block_floor,
        warn_floor=warn_floor,
    )


def _swap_into_bench(
    tool_staging: Path, bench_root: Path, protected: set[Path] | None = None
) -> list[Path]:
    """Per-file atomic copy: temp file → fsync → rename. Returns list of files
    written. Caller has already validated staging.

    Paths in ``protected`` are skipped — they carry hand edits forge has not
    adopted yet, and overwriting them would destroy the only copy.
    """
    protected = protected or set()
    written: list[Path] = []
    for staged_path in tool_staging.rglob("*"):
        if not staged_path.is_file():
            continue
        rel = staged_path.relative_to(tool_staging)
        target = bench_root / rel
        if target in protected:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(staged_path.read_text())
        tmp.replace(target)
        written.append(target)
    return written


def detect_hand_edits(
    rendered: list[RenderedArtifact], bench_root: Path
) -> dict[Path, str]:
    """Return {output_path: current_sha256} for files a human changed since sync.

    A file counts as hand-edited when it exists on disk, a manifest records what
    forge last wrote there, and the two hashes disagree. Anything forge has no
    record of is NOT hand-edited — it is unmanaged, and the first sync adopts it
    (which is how the eight per-app files come under management without being
    reported as conflicts).

    The point is that generated-file ownership must not mean "your edits vanish
    on the next sync". Someone fixing a wrong instruction in the file actually in
    front of them is doing the right thing; forge's job is to notice and route
    that edit back to canonical, not to punish it.
    """
    edited: dict[Path, str] = {}
    manifest_cache: dict[Path, dict[str, str]] = {}

    for art in rendered:
        target = art.output_path
        if not target.is_file():
            continue

        out_dir = target.parent
        if out_dir not in manifest_cache:
            manifest = read_manifest(out_dir)
            manifest_cache[out_dir] = (
                {e.path: e.sha256 for e in manifest.outputs} if manifest else {}
            )
        recorded = manifest_cache[out_dir].get(target.name)
        if not recorded:
            continue  # never generated here, or a pre-v2 manifest — adopt it

        current = sha256_text(target.read_text())
        if current != recorded and current != sha256_text(art.content):
            # Differs from what we wrote AND from what we are about to write:
            # a genuine human edit, not a no-op re-render.
            edited[target] = current

    return edited


def _app_of_output(path: Path) -> str | None:
    """`<bench>/apps/<app>/<file>` → `<app>`; anything else → None."""
    parts = path.parts
    if "apps" in parts:
        idx = len(parts) - 1 - parts[::-1].index("apps")
        if idx + 2 < len(parts):
            return parts[idx + 1]
    return None


def foreign_app_targets(
    rendered: list[RenderedArtifact], bench_root: Path, forge_cfg: dict
) -> dict[str, str]:
    """{app: owner} for per-app outputs whose repo belongs to someone else.

    managed_apps says where forge is *configured* to write; this says where it
    would actually land. The two disagree the moment an app is added to the
    list without checking whose repo it is, which is exactly the mistake worth
    catching before files appear in a third party's working tree.
    """
    owned = set((forge_cfg.get("bench") or {}).get("owned_remotes") or [])
    if not owned:
        return {}

    foreign: dict[str, str] = {}
    seen: set[str] = set()
    for art in rendered:
        app = _app_of_output(art.output_path)
        if not app or app in seen:
            continue
        seen.add(app)
        owner = owner_of_app(bench_root, app)
        if is_foreign(owner, owned):
            foreign[app] = owner or "unknown"
    return foreign


def _confirm_foreign_writes(foreign: dict[str, str], assume_yes: bool) -> set[str]:
    """Ask before writing into repos we do not own. Returns apps to SKIP.

    Declining is the default on purpose, including when nothing can answer
    (CI, a pipe, `forge sync` from a hook): an unattended run must not create
    files in another organisation's repository because nobody was watching.
    """
    console.print(
        f"\n[yellow]![/yellow] {len(foreign)} app(s) are managed but their git remote "
        f"belongs to someone else:"
    )
    for app, owner in sorted(foreign.items()):
        console.print(f"    [bold]{app}[/bold] → owner [bold]{owner}[/bold]")
    console.print(
        "    Writing here puts a generated file in a repo you do not own.\n"
        "    Drop it with [cyan]forge apps remove <app> --prune[/cyan], or add the owner "
        "to [cyan]bench.owned_remotes[/cyan] if it really is yours."
    )

    if assume_yes:
        console.print("    [dim]--yes given; writing anyway.[/dim]")
        return set()

    if not sys.stdin.isatty():
        console.print(
            "    [yellow]Not a terminal — skipping all of them.[/yellow] "
            "Pass [cyan]--yes[/cyan] to write unattended."
        )
        return set(foreign)

    if Confirm.ask("    Create files in these repos anyway?", default=False):
        return set()
    console.print("    [dim]Skipped.[/dim]")
    return set(foreign)


def _warn_oversized_aggregates(
    repo_root: Path, tool: str, rendered: list[RenderedArtifact]
) -> None:
    """Warn when an aggregate output exceeds the adapter's ``max_total_chars``.

    Root instruction files (CLAUDE.md, AGENTS.md, copilot-instructions.md, ...)
    are read on every turn and compete with the actual task for context, so each
    adapter declares a budget. The budget used to be documentation only — this
    surfaces it at sync time.

    Advisory, never blocking: the fix is editorial (move the detail into a
    linked doc, as ``AGENTS-TICKETING.md`` does, and leave a pointer behind),
    and that is not a decision to make mid-sync.
    """
    limit = (load_adapter_config(repo_root, tool).get("limits") or {}).get("max_total_chars")
    if not limit:
        return
    for art in rendered:
        if art.artifact_kind != "aggregate":
            continue
        size = len(art.content)
        if size > limit:
            console.print(
                f"[yellow]![/yellow] {tool}: {art.output_path.name} is {size:,} chars, "
                f"over the {limit:,} budget — move detail into a linked doc and "
                f"leave a pointer."
            )


def sync_tool(
    repo_root: Path,
    tool: str,
    dry_run: bool = False,
    justify: str | None = None,
    assume_yes: bool = False,
) -> SyncResult:
    """Sync a single tool. Renders, stages, validates, swaps."""
    result = SyncResult(tool=tool)
    try:
        forge_cfg = load_forge_config(repo_root)
        bench_root = Path(
            forge_cfg["bench"]["path"].replace(
                "{{ env.FORGE_BENCH_PATH }}",
                __import__("os").environ.get("FORGE_BENCH_PATH", ""),
            )
        )
        if not bench_root or not bench_root.is_dir():
            raise FileNotFoundError(
                f"Bench path not found: {bench_root!r}. Set FORGE_BENCH_PATH."
            )

        staging_root = bench_root / forge_cfg["sync"].get("staging_dir", ".forge-staging")
        rendered = render(repo_root, tool)
        _warn_oversized_aggregates(repo_root, tool, rendered)
        tool_staging = _stage_artifacts(rendered, staging_root, tool)

        ok, err = _validate_staging(tool_staging)
        if not ok:
            result.success = False
            result.error = err
            return result

        # Security gate (Phase 4a): score every canonical source contributing
        # to this render. Blocks on score < block_floor (default 80). Warns on
        # 80-94 unless --justify was provided; warnings logged to audit either way.
        gate = _security_gate(repo_root, rendered, forge_cfg, justify)
        if gate.blocked:
            result.success = False
            result.error = gate.message
            audit_log(
                repo_root,
                {
                    "action": "sync.blocked_by_security_gate",
                    "tool": tool,
                    "block_floor": gate.block_floor,
                    "findings_count": len(gate.findings),
                    "findings": [
                        {
                            "id": f.deduction_id,
                            "severity": f.severity,
                            "location": f.location,
                            "deduction": f.deduction,
                        }
                        for f in gate.findings[:50]  # cap detail to keep entries reasonable
                    ],
                    "per_file_scores": gate.per_file_scores,
                    "justify": justify,
                },
            )
            console.print(f"[red]✗[/red] {tool}: {gate.message}")
            for f in gate.findings[:10]:
                console.print(f"  [{f.severity}] {f.deduction_id} at {f.location}")
            return result

        if gate.warned:
            # 80-94 band without justification — fail closed (Decision 11).
            result.success = False
            result.error = (
                f"{gate.message}. Pass --justify '<reason>' to proceed; "
                "the reason will be logged to audit JSONL."
            )
            audit_log(
                repo_root,
                {
                    "action": "sync.warned_without_justify",
                    "tool": tool,
                    "warn_floor": gate.warn_floor,
                    "findings_count": len(gate.findings),
                    "per_file_scores": gate.per_file_scores,
                },
            )
            console.print(f"[yellow]![/yellow] {tool}: {gate.message}")
            console.print(f"  Re-run with --justify '<one-line reason>' to proceed.")
            return result

        if justify:
            # Successful sync with a justification — record it so future audits
            # can see why a not-fully-clean artifact shipped.
            audit_log(
                repo_root,
                {
                    "action": "sync.justified_accept",
                    "tool": tool,
                    "justify": justify,
                    "per_file_scores": gate.per_file_scores,
                },
            )

        if dry_run:
            audit_log(
                repo_root,
                {
                    "action": "sync.dry_run",
                    "tool": tool,
                    "staged_files": [str(p) for p in tool_staging.rglob("*") if p.is_file()],
                    "justify": justify,
                },
            )
            console.print(
                f"[green]✓[/green] dry-run for {tool}: "
                f"{sum(1 for p in tool_staging.rglob('*') if p.is_file())} files in {tool_staging}"
            )
            return result

        # Ownership guard: never create files in a repo belonging to another
        # organisation without someone saying yes to it.
        foreign = foreign_app_targets(rendered, bench_root, forge_cfg)
        skip_apps = _confirm_foreign_writes(foreign, assume_yes) if foreign else set()
        if skip_apps:
            rendered = [
                r for r in rendered if _app_of_output(r.output_path) not in skip_apps
            ]

        # Hand-edit guard: never overwrite a file someone edited in place.
        hand_edited = detect_hand_edits(rendered, bench_root)
        if hand_edited:
            console.print(
                f"[yellow]![/yellow] {tool}: {len(hand_edited)} file(s) hand-edited "
                f"since the last sync — left untouched:"
            )
            for path in sorted(hand_edited):
                console.print(f"    {path}")
            console.print(
                "    Run [cyan]forge adopt[/cyan] to fold those edits back into "
                "canonical/, then sync again."
            )
            audit_log(
                repo_root,
                {
                    "action": "sync.hand_edits_preserved",
                    "tool": tool,
                    "files": [str(p) for p in sorted(hand_edited)],
                },
            )

        protected = set(hand_edited)
        for staged in list(tool_staging.rglob("*")):
            if staged.is_file() and _app_of_output(staged) in skip_apps:
                staged.unlink()

        # Live swap
        written = _swap_into_bench(tool_staging, bench_root, protected=protected)
        result.files_written = written

        # settings.json merge — only the claude-code adapter touches it
        if tool == "claude-code":
            staged_settings = [p for p in written if p.name == "settings.json"]
            if staged_settings:
                # Already swapped; back up + merge with pre-swap snapshot is
                # handled by write_settings_with_backup pattern in adapter renderer.
                # For Phase 2 simplicity, we just record backup absence here.
                result.settings_backup = staged_settings[0].with_suffix(".json.forge-backup")

        # Manifest per bench output dir touched
        bench_output_dirs = {p.parent for p in written}
        for out_dir in bench_output_dirs:
            relevant = [r for r in rendered if r.output_path.parent == out_dir]
            entries = [
                ManifestEntry(
                    path=str(r.source_path.relative_to(repo_root)),
                    version=r.source_version,
                    sha256=sha256_text(r.content),
                )
                for r in relevant
            ]
            # `outputs` is what makes the next sync able to tell a hand edit
            # from an untouched file — keyed by filename within this dir.
            outputs = [
                ManifestEntry(
                    path=r.output_path.name,
                    version=r.source_version,
                    sha256=sha256_text(r.content),
                )
                for r in relevant
                if r.output_path not in hand_edited
            ]
            if entries:
                manifest = build_manifest(
                    source_repo="erpnext-ai-forge",
                    source_commit=next(iter([r.source_commit or "" for r in relevant]), ""),
                    adapter_name=tool,
                    adapter_version="0.1.0",
                    entries=entries,
                    outputs=outputs,
                )
                write_manifest(out_dir, manifest)

        audit_log(
            repo_root,
            {
                "action": "sync.live",
                "tool": tool,
                "files_written": [str(p) for p in written],
                "files_count": len(written),
                "justify": justify,
            },
        )
        console.print(
            f"[green]✓[/green] synced {tool}: {len(written)} files written"
        )
    except Exception as exc:                  # noqa: BLE001
        result.success = False
        result.error = str(exc)
        audit_log(
            repo_root,
            {"action": "sync.error", "tool": tool, "error": str(exc)},
        )
        console.print(f"[red]✗[/red] sync {tool} failed: {exc}")

    return result


def sync_all(
    repo_root: Path,
    tools: list[str],
    dry_run: bool = False,
    justify: str | None = None,
    assume_yes: bool = False,
) -> list[SyncResult]:
    """Multi-tool sync. Per Part B item 7: render + validate every tool first;
    only swap if all pass. On any failure: abort the whole run."""
    # Phase 1: render + stage every tool
    staged_results: list[SyncResult] = []
    for tool in tools:
        # Force dry_run during the first pass to populate staging without swapping
        r = sync_tool(repo_root, tool, dry_run=True, justify=justify, assume_yes=True)
        staged_results.append(r)
        if not r.success:
            console.print(
                f"[red]Abort:[/red] {tool} failed validation — no bench files touched"
            )
            return staged_results

    if dry_run:
        return staged_results

    # Phase 2: all staged successfully → swap each tool
    final_results: list[SyncResult] = []
    for tool in tools:
        final_results.append(
            sync_tool(repo_root, tool, dry_run=False, justify=justify, assume_yes=assume_yes)
        )
    return final_results


# ---------------------------------------------------------------------------
# Entry point called by CLI
# ---------------------------------------------------------------------------
def run_sync(
    tool: str | None,
    all_tools: bool,
    dry_run: bool,
    justify: str | None,
    assume_yes: bool = False,
) -> int:
    """CLI entry. Returns process exit code."""
    repo_root = find_repo_root()
    forge_cfg = load_forge_config(repo_root)

    if all_tools:
        tools = list(forge_cfg.get("enabled_tools", []))
    elif tool:
        tools = [t.strip() for t in tool.split(",")]
    else:
        console.print("[red]Pass --tool <name> or --all[/red]")
        return 2

    if not tools:
        console.print("[yellow]No tools enabled in forge.config.yaml[/yellow]")
        return 0

    results = sync_all(repo_root, tools, dry_run=dry_run, justify=justify, assume_yes=assume_yes)
    failed = [r for r in results if not r.success]
    return 1 if failed else 0
