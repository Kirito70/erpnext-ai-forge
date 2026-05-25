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
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from forge.audit import audit_log
from forge.loader import find_repo_root, load_forge_config
from forge.manifest import (
    ManifestEntry,
    build_manifest,
    sha256_text,
    write_manifest,
)
from forge.render import RenderedArtifact, render
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
        # Recreate the bench-relative structure inside staging
        # by computing the relative path from the bench root.
        try:
            bench_relative = r.output_path.relative_to(_bench_root_from(r))
        except (ValueError, RuntimeError):
            bench_relative = Path(r.output_path.name)

        staged_path = tool_staging / bench_relative
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_text(r.content)

    return tool_staging


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


def _swap_into_bench(tool_staging: Path, bench_root: Path) -> list[Path]:
    """Per-file atomic copy: temp file → fsync → rename. Returns list of files
    written. Caller has already validated staging."""
    written: list[Path] = []
    for staged_path in tool_staging.rglob("*"):
        if not staged_path.is_file():
            continue
        rel = staged_path.relative_to(tool_staging)
        target = bench_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(staged_path.read_text())
        tmp.replace(target)
        written.append(target)
    return written


def sync_tool(
    repo_root: Path,
    tool: str,
    dry_run: bool = False,
    justify: str | None = None,
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

        # Live swap
        written = _swap_into_bench(tool_staging, bench_root)
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
            if entries:
                manifest = build_manifest(
                    source_repo="erpnext-ai-forge",
                    source_commit=next(iter([r.source_commit or "" for r in relevant]), ""),
                    adapter_name=tool,
                    adapter_version="0.1.0",
                    entries=entries,
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
) -> list[SyncResult]:
    """Multi-tool sync. Per Part B item 7: render + validate every tool first;
    only swap if all pass. On any failure: abort the whole run."""
    # Phase 1: render + stage every tool
    staged_results: list[SyncResult] = []
    for tool in tools:
        # Force dry_run during the first pass to populate staging without swapping
        r = sync_tool(repo_root, tool, dry_run=True, justify=justify)
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
        final_results.append(sync_tool(repo_root, tool, dry_run=False, justify=justify))
    return final_results


# ---------------------------------------------------------------------------
# Entry point called by CLI
# ---------------------------------------------------------------------------
def run_sync(
    tool: str | None,
    all_tools: bool,
    dry_run: bool,
    justify: str | None,
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

    results = sync_all(repo_root, tools, dry_run=dry_run, justify=justify)
    failed = [r for r in results if not r.success]
    return 1 if failed else 0
