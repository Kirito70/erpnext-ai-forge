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
from typing import Any

from rich.console import Console
from rich.prompt import Confirm

from forge.audit import audit_log
from forge.drift import _iter_manifests
from forge.loader import (
    commit_date,
    find_repo_root,
    load_adapter_config,
    load_forge_config,
    load_target,
    load_targets,
)
from forge.manifest import (
    Manifest,
    ManifestEntry,
    build_manifest,
    is_from_a_newer_forge,
    merge_manifest,
    read_manifest,
    sha256_text,
    write_manifest,
)
from forge.models import Target
from forge.render import RenderedArtifact, render
from forge.repo import is_foreign, owner_of_app
from forge.scoring import Finding, score_file
from forge.settings_merge import (
    ScalarConflict,
    merge_settings_json,
    settings_text,
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
    orphans: list[Orphan] = field(default_factory=list)
    files_pruned: list[Path] = field(default_factory=list)
    success: bool = True
    error: str | None = None


def _stage_artifacts(
    rendered: list[RenderedArtifact],
    staging_root: Path,
    tool: str,
    target_root: Path | None = None,
) -> Path:
    """Write rendered artifacts into staging directory.

    Returns the per-tool staging root (e.g., <bench>/.forge-staging/claude-code/).

    `target_root` is authoritative when given. Without it the root is *inferred*
    by looking for an `apps/` directory or an existing `.claude` — which works
    for a populated bench and fails for a repo receiving its first sync, because
    neither marker exists yet. The inferred fallback then produced staging paths
    like `.forge-staging/claude-code/Work/Projects/...`.
    """
    tool_staging = staging_root / tool
    if tool_staging.exists():
        shutil.rmtree(tool_staging)
    tool_staging.mkdir(parents=True)

    for r in rendered:
        _assert_resolved_output_path(r)
        # Recreate the target-relative structure inside staging.
        try:
            root = target_root or _bench_root_from(r)
            bench_relative = r.output_path.relative_to(root)
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
        if r.mode is not None:
            # Set it here, not just at swap time, so `ls -l` on the staging dir
            # tells the truth about what is going to land.
            staged_path.chmod(r.mode)

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
    if ".." in r.output_path.parts:
        # `Path.relative_to` prefix-matches on parts without normalising, so a
        # `..` survives into the staged path and the write lands outside the
        # staging root AND outside the bench. Refused rather than normalised:
        # an `output:` that needs to climb out of the bench is a mistake in
        # adapter.yaml, and silently rewriting it to somewhere plausible is the
        # same "writes somewhere nobody intended" this function exists to stop.
        raise ValueError(
            f"{r.tool}: output path for '{r.artifact_id}' escapes the bench with "
            f"'..': {raw!r}. Write an `output:` that resolves inside the target."
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
    forge_cfg: dict[str, Any],
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


SETTINGS_FRAGMENT_KIND = "settings-fragment"


def _settings_fragments(rendered: list[RenderedArtifact]) -> list[RenderedArtifact]:
    return [r for r in rendered if r.artifact_kind == SETTINGS_FRAGMENT_KIND]


def _source_hash(source_path: Path) -> str | None:
    """Hash of a canonical source file, or None if it cannot be read.

    None rather than raising: several artifacts name a representative source
    (an aggregate points at `discovery/INVENTORY.md`) and a missing or binary
    one must not fail a sync. A row without this simply opts out of the
    staleness check instead of producing a false finding.
    """
    try:
        return sha256_text(source_path.read_text())
    except (OSError, UnicodeDecodeError):
        return None


def _merge_settings_fragments(
    rendered: list[RenderedArtifact],
) -> tuple[list[Path], list[ScalarConflict], Path | None]:
    """Merge forge's settings fragments into the target's settings.json.

    This is the one artifact that must NOT go through the atomic swap. Every
    other output is forge's to own outright; settings.json is shared — it holds
    permissions and hooks a human added and forge never wrote. Overwriting it
    would silently delete their work on every sync.

    So the fragment is rendered, scored and staged like anything else (the
    evidence trail matters for incident response), but landed by deep-merging
    into whatever is already on disk, after taking a `.forge-backup`.

    Until now `merge_settings_json` and `write_settings_with_backup` existed but
    were never called from anywhere, which quietly made
    `sync.backup_claude_settings: true` in forge.config.yaml untrue.
    """
    written: list[Path] = []
    conflicts: list[ScalarConflict] = []
    backup: Path | None = None

    by_path: dict[Path, list[dict[str, Any]]] = {}
    for frag in _settings_fragments(rendered):
        try:
            parsed = json.loads(frag.content)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{frag.tool}: settings fragment '{frag.artifact_id}' is not valid "
                f"JSON ({exc}). Check the adapter's wiring template."
            ) from exc
        by_path.setdefault(frag.output_path, []).append(parsed)

    for path, fragments in by_path.items():
        merged, path_conflicts = merge_settings_json(path, fragments)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Asked before the write, because after it the answer is always "no".
        changed = not path.is_file() or path.read_text() != settings_text(merged)
        this_backup = write_settings_with_backup(path, merged)
        backup = backup or this_backup
        conflicts.extend(path_conflicts)
        if changed:
            written.append(path)

    return written, conflicts, backup


def prune_harness(
    rendered: list[RenderedArtifact], target_root: Path, harness_dir: Path
) -> list[Path]:
    """Delete files under `harness_dir` that this render no longer produces.

    The swap never deletes, so a script removed from canonical stays in the
    target and keeps running — a hook nobody can find the source of.

    Deliberately opt-in (`--prune-harness`) rather than automatic. Deleting
    files in someone's repo because a render came out shorter than last time is
    exactly the kind of surprise that costs trust in the tool, and the failure
    mode without pruning is mild: the wiring file is the only thing that invokes
    these scripts, so an orphan is inert.

    Deletion obeys the same two rules as `prune_orphans`, for the same reason:
    a file with no manifest row belongs to a human, and a file whose content no
    longer matches its row carries edits forge never adopted. Skipping those
    checks here made `--prune-harness` the back door around the hand-edit guard.
    """
    if not harness_dir.is_dir():
        return []
    expected = {
        r.output_path.name for r in rendered if r.artifact_kind == "harness-script"
    }
    manifest = read_manifest(harness_dir)
    recorded = {e.path: e.sha256 for e in manifest.outputs} if manifest else {}

    removed: list[Path] = []
    for path in sorted(harness_dir.iterdir()):
        if not path.is_file() or path.name in expected:
            continue
        row = recorded.get(path.name)
        if row is None:
            continue  # never forge's to delete
        try:
            current = sha256_text(path.read_text(errors="replace"))
        except OSError:
            continue
        if current != row:
            continue  # hand-edited since; reported by find_orphans, not removed
        path.unlink()
        removed.append(path)
    return removed


@dataclass(frozen=True)
class Orphan:
    """A file forge wrote at a path it no longer renders."""

    path: Path
    manifest_path: Path
    removable: bool
    reason: str
    manifest_row: ManifestEntry


def find_orphans(
    rendered: list[RenderedArtifact],
    bench_root: Path,
    tool: str,
    still_managed: list[RenderedArtifact] | None = None,
) -> list[Orphan]:
    """Outputs this adapter recorded writing but no longer produces.

    Changing an artifact's `output:` writes the new location and leaves the old
    one behind. Both then look generated and nothing says which is live —
    moving the 33 skills to `<id>/SKILL.md` left the bench with 66 skill files,
    10 stale directories and 43 stale manifests, cleaned up by hand.

    Everything needed is already recorded: the manifest's `outputs` rows are
    exactly the paths forge wrote. Two rules make consulting them safe:

    - **A file with no manifest row is never an orphan.** It belongs to a
      human, and deleting it is the one unrecoverable mistake available here.
    - **A file whose content no longer matches its row is reported, not
      removed.** It carries edits forge never adopted; the hand-edit guard
      protects those on write, and a prune must not be the back door around it.

    `still_managed` is the render BEFORE any app was dropped for ownership.
    An app skipped at the foreign-write prompt is missing from `rendered`, and
    absence there otherwise means "no longer produced" — so without this,
    answering "no, do not write to that repo" queued its existing files for
    deletion, and `--prune` carried it out. Declining a write must never be the
    thing that removes what is already there.

    Must run BEFORE the manifest is rewritten: `merge_manifest` replaces the
    owning adapter's rows wholesale, so the record of the old path is gone the
    moment the new manifest lands.
    """
    produced = {r.output_path for r in (still_managed if still_managed else rendered)}
    orphans: list[Orphan] = []

    for manifest_path in _iter_manifests(bench_root):
        out_dir = manifest_path.parent
        manifest = read_manifest(out_dir)
        if manifest is None:
            # Unreadable, or a schema we do not understand. No record means no
            # judgement — never a deletion on a guess.
            continue
        for entry in manifest.outputs:
            if (entry.adapter or manifest.adapter_name) != tool:
                continue
            path = out_dir / entry.path
            if path in produced or not path.is_file():
                continue
            try:
                current = sha256_text(path.read_text(errors="replace"))
            except OSError:
                continue
            matches = current == entry.sha256
            orphans.append(
                Orphan(
                    path=path,
                    manifest_path=manifest_path,
                    manifest_row=entry,
                    removable=matches,
                    reason=(
                        "no longer rendered"
                        if matches
                        else "no longer rendered, and hand-edited since"
                    ),
                )
            )
    return sorted(orphans, key=lambda o: str(o.path))


def prune_orphans(orphans: list[Orphan], tool: str, bench_root: Path) -> list[Path]:
    """Delete removable orphans, then tidy the records and directories.

    Rewriting the manifest is part of the deletion, not an extra: rows left
    pointing at files just removed make `forge validate` report them missing
    forever, and the sync after a prune stops being a no-op.
    """
    removed: list[Path] = []
    by_manifest: dict[Path, list[Orphan]] = {}
    for o in orphans:
        if o.removable:
            by_manifest.setdefault(o.manifest_path, []).append(o)

    for manifest_path, group in by_manifest.items():
        out_dir = manifest_path.parent
        gone = set()
        for o in group:
            o.path.unlink()
            removed.append(o.path)
            gone.add(o.path.name)

        manifest = read_manifest(out_dir)
        if manifest is None:
            continue
        manifest.outputs = [
            e
            for e in manifest.outputs
            if not (e.path in gone and (e.adapter or manifest.adapter_name) == tool)
        ]
        # Source rows are only worth keeping while this adapter still has an
        # output here. Once it renders nothing into the directory they describe
        # a render that no longer happens, and validate keeps checking them for
        # staleness against it.
        if not any(
            (e.adapter or manifest.adapter_name) == tool for e in manifest.outputs
        ):
            manifest.source_files = [
                e
                for e in manifest.source_files
                if (e.adapter or manifest.adapter_name) != tool
            ]

        if manifest.outputs or manifest.source_files:
            write_manifest(out_dir, manifest)
        else:
            manifest_path.unlink()

        _remove_if_empty(out_dir, stop_at=bench_root)

    return removed


def _carry_forward_orphan_rows(
    manifest: Manifest, orphans: list[Orphan], out_dir: Path
) -> None:
    """Re-record orphans that still exist on disk.

    `merge_manifest` replaces the owning adapter's rows wholesale, so an orphan
    that was reported but not removed would lose its row and become
    indistinguishable from a file a human wrote — unprunable ever after, by the
    very rule that protects unmanaged files. Reporting must not be the step
    that destroys the evidence.
    """
    kept = [o.manifest_row for o in orphans if o.path.parent == out_dir and o.path.is_file()]
    if not kept:
        return
    have = {e.path for e in manifest.outputs}
    manifest.outputs = sorted(
        manifest.outputs + [e for e in kept if e.path not in have],
        key=lambda e: e.path,
    )


def _carry_forward_hand_edited_rows(
    manifest: Manifest,
    previous: Manifest | None,
    hand_edited: set[Path],
    out_dir: Path,
) -> None:
    """Re-record the rows of files we refused to overwrite.

    A hand-edited file is left out of `outputs` — forge did not write it, so
    claiming it did would be a lie the next staleness check trips over. But
    `merge_manifest` replaces the owning adapter's rows wholesale, so leaving it
    out is also how the row disappears, and a file with no row is one forge has
    no record of: `detect_hand_edits` adopts it and the next sync overwrites the
    edit. Protection that lasts exactly one sync is worse than none, because the
    warning already told someone their file was safe.

    The row carried forward is the OLD one — what forge last wrote. Recording
    the file's current bytes would make it match on the next run and stop being
    reported, which is protection that erases itself by working.
    """
    if previous is None:
        return
    names = {p.name for p in hand_edited if p.parent == out_dir}
    if not names:
        return
    have = {e.path for e in manifest.outputs}
    manifest.outputs = sorted(
        manifest.outputs
        + [e for e in previous.outputs if e.path in names and e.path not in have],
        key=lambda e: e.path,
    )


def _print_orphans(
    tool: str, orphans: list[Orphan], prune: bool, dry_run: bool
) -> None:
    """Report orphans. Silent when there are none — a clean sync stays quiet."""
    if not orphans:
        return
    removable = [o for o in orphans if o.removable]
    kept = [o for o in orphans if not o.removable]

    if removable:
        verb = "would remove" if (dry_run or not prune) else "removing"
        console.print(
            f"[yellow]![/yellow] {tool}: {len(removable)} orphaned output(s) "
            f"— {verb}:"
        )
        for o in removable:
            console.print(f"    {o.path}")
        if not prune:
            console.print("    Pass [cyan]--prune[/cyan] to remove them.")

    for o in kept:
        console.print(
            f"[yellow]![/yellow] {tool}: {o.path} is {o.reason} — left in place. "
            f"Run [cyan]forge adopt[/cyan] or delete it yourself."
        )


def _remove_if_empty(directory: Path, stop_at: Path) -> None:
    """Remove `directory` and any parent it just emptied, exclusive of `stop_at`.

    Emptiness alone is not a safe stop condition: prune the last managed file
    in a bench and the walk would climb through `.claude` and take the bench
    root with it. The boundary is what makes this a tidy-up rather than a
    recursive delete.
    """
    stop_at = stop_at.resolve()
    current = directory.resolve()
    while (
        current != stop_at
        and stop_at in current.parents
        and current.is_dir()
        and not any(current.iterdir())
    ):
        parent = current.parent
        current.rmdir()
        current = parent


def _swap_into_bench(
    tool_staging: Path, bench_root: Path, protected: set[Path] | None = None
) -> tuple[list[Path], list[Path]]:
    """Per-file atomic copy: temp file → fsync → rename. Returns (written,
    unchanged). Caller has already validated staging.

    Paths in ``protected`` are skipped — they carry hand edits forge has not
    adopted yet, and overwriting them would destroy the only copy. They count as
    neither written nor unchanged: calling a hand edit "unchanged" would report
    it as agreement with what forge wanted to write.

    A file whose bytes already match is not rewritten. Re-writing identical
    content still moves the mtime and still reports as a write, which is how a
    sync that changed nothing looked like a sync that changed everything — and
    what `SyncResult.files_unchanged` was declared for and never given.
    """
    protected = protected or set()
    written: list[Path] = []
    unchanged: list[Path] = []
    for staged_path in tool_staging.rglob("*"):
        if not staged_path.is_file():
            continue
        rel = staged_path.relative_to(tool_staging)
        target = bench_root / rel
        if target in protected:
            continue
        staged_text = staged_path.read_text()
        staged_mode = staged_path.stat().st_mode & 0o777
        if target.is_file() and target.read_text() == staged_text:
            # Mode is still applied: content can match while the executable bit
            # does not, and a hook that is not executable does not run.
            if target.stat().st_mode & 0o777 != staged_mode:
                target.chmod(staged_mode)
            unchanged.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(staged_text)
        # Carry the staged mode across, and set it on the temp file *before* the
        # rename. Chmod-after-rename leaves a window where the file is live but
        # still 0644 — a hook firing in that window fails with "permission
        # denied". Setting it first keeps the swap genuinely atomic: the file
        # appears at its final path already executable.
        tmp.chmod(staged_mode)
        tmp.replace(target)
        written.append(target)
    return written, unchanged


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

    A manifest written by a NEWER forge is not the same as no manifest. Both
    make `read_manifest` return None, but only one of them means "nothing is
    managed here". A v1 manifest is the documented upgrade path and its files
    really are adoptable; a schema above ours was written by a binary that knows
    more than we do, so its rows may be protecting something we cannot see.
    Treating that as unmanaged is how a schema bump on one machine wipes hand
    edits on another. `drift.py` already reports the state as a finding; the
    write path has more to lose, so it protects the whole directory instead.
    """
    edited: dict[Path, str] = {}
    manifest_cache: dict[Path, dict[str, str]] = {}
    from_the_future: set[Path] = set()

    for art in rendered:
        target = art.output_path
        if not target.is_file():
            continue
        if art.artifact_kind == "scaffold":
            # Seeded once, then owned by whoever writes into it. The swap
            # already refuses to touch these; reporting them as hand-edited
            # asked the user to adopt build-history rows back into canonical.
            continue

        out_dir = target.parent
        if out_dir not in manifest_cache:
            manifest = read_manifest(out_dir)
            if manifest is None and is_from_a_newer_forge(out_dir):
                from_the_future.add(out_dir)
            manifest_cache[out_dir] = (
                {e.path: e.sha256 for e in manifest.outputs} if manifest else {}
            )
        if out_dir in from_the_future:
            # A record we are too old to read, and a file already on disk.
            # Refuse the write rather than guess what it is.
            edited[target] = sha256_text(target.read_text(errors="replace"))
            continue
        recorded = manifest_cache[out_dir].get(target.name)
        if not recorded:
            continue  # never generated here, or a pre-v2 manifest — adopt it

        current = sha256_text(target.read_text())
        if current != recorded and current != sha256_text(art.content):
            # Differs from what we wrote AND from what we are about to write:
            # a genuine human edit, not a no-op re-render.
            edited[target] = current

    return edited


def _owns_rows_in(out_dir: Path, tool: str) -> bool:
    """True when `tool` already has output rows in this directory's manifest.

    The test for "may this adapter refresh this manifest without changing who
    owns what". A directory several adapters render into has one owner per row,
    and that owner decides who may prune the row later.
    """
    manifest = read_manifest(out_dir)
    if manifest is None:
        return False
    return any(
        (e.adapter or manifest.adapter_name) == tool for e in manifest.outputs
    )


def app_of_output(path: Path) -> str | None:
    """`<bench>/apps/<app>/<file>` → `<app>`; anything else → None."""
    parts = path.parts
    if "apps" in parts:
        idx = len(parts) - 1 - parts[::-1].index("apps")
        if idx + 2 < len(parts):
            return parts[idx + 1]
    return None


def foreign_app_targets(
    rendered: list[RenderedArtifact],
    bench_root: Path,
    forge_cfg: dict[str, Any],
    target: Target | None = None,
) -> dict[str, str]:
    """{app: owner} for per-app outputs whose repo belongs to someone else.

    managed_apps says where forge is *configured* to write; this says where it
    would actually land. The two disagree the moment an app is added to the
    list without checking whose repo it is, which is exactly the mistake worth
    catching before files appear in a third party's working tree.
    """
    if target is not None and target.self_target:
        # We are running inside this repo. Ownership is not the question, and
        # prompting about it would be noise on every self-sync.
        return {}

    owned = set(
        (target.owned_remotes if target is not None else None)
        or (forge_cfg.get("bench") or {}).get("owned_remotes")
        or []
    )
    if not owned:
        return {}

    foreign: dict[str, str] = {}
    seen: set[str] = set()
    for art in rendered:
        app = app_of_output(art.output_path)
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
    target: Target | None = None,
    prune_harness_dir: bool = False,
    prune: bool = False,
    report_orphans: bool = True,
) -> SyncResult:
    """Sync a single tool into one target. Renders, stages, validates, swaps.

    `report_orphans` exists for `sync_all`, which runs every tool through a
    forced dry run to populate staging before it swaps anything. That pass is
    internal bookkeeping; reporting from it would print every orphan twice.
    """
    result = SyncResult(tool=tool)
    try:
        forge_cfg = load_forge_config(repo_root)
        target = target or load_target(repo_root, forge_cfg=forge_cfg)
        bench_root = target.root
        if not bench_root or not bench_root.is_dir():
            raise FileNotFoundError(
                f"Target '{target.name}' root not found: {str(bench_root)!r}. "
                f"Set the environment variable it interpolates, or fix `root:` "
                f"in forge.config.yaml."
            )

        staging_root = bench_root / forge_cfg["sync"].get("staging_dir", ".forge-staging")
        rendered = render(repo_root, tool, target)
        _warn_oversized_aggregates(repo_root, tool, rendered)
        tool_staging = _stage_artifacts(rendered, staging_root, tool, bench_root)

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
            console.print("  Re-run with --justify '<one-line reason>' to proceed.")
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
            # Orphan detection reads manifests and hashes files; it writes
            # nothing, so a dry run can show exactly what `--prune` would take.
            if report_orphans:
                result.orphans = find_orphans(rendered, bench_root, tool)
                _print_orphans(tool, result.orphans, prune, dry_run=True)
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
        foreign = foreign_app_targets(rendered, bench_root, forge_cfg, target)
        skip_apps = _confirm_foreign_writes(foreign, assume_yes) if foreign else set()
        # Kept so orphan detection can tell "we chose not to write this" from
        # "this is no longer produced". They look identical in `rendered`, and
        # only one of them should ever lead to a deletion.
        still_managed = rendered
        if skip_apps:
            rendered = [
                r for r in rendered if app_of_output(r.output_path) not in skip_apps
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
            if staged.is_file() and app_of_output(staged) in skip_apps:
                staged.unlink()

        # Settings fragments are merged, not swapped. Protect them from the swap
        # so the human's own permissions and hooks survive.
        fragments = _settings_fragments(rendered)
        protected |= {f.output_path for f in fragments}

        # Scaffolds are seeded once and then owned by whoever writes into them.
        # The ledgers accumulate agent-written rows; re-rendering the header
        # over them on every sync would delete the entire build history.
        protected |= {
            r.output_path
            for r in rendered
            if r.artifact_kind == "scaffold" and r.output_path.exists()
        }

        # Live swap
        written, unchanged = _swap_into_bench(
            tool_staging, bench_root, protected=protected
        )
        result.files_unchanged = unchanged

        # …then merge the fragments into whatever is already on disk.
        merged_paths, conflicts, backup = _merge_settings_fragments(fragments)
        written.extend(merged_paths)
        result.settings_conflicts = conflicts
        result.settings_backup = backup
        if conflicts:
            console.print(
                f"[yellow]![/yellow] {tool}: overrode {len(conflicts)} value(s) "
                f"already set in settings.json (previous values logged to audit):"
            )
            for c in conflicts:
                console.print(f"    {c.path}: {c.prior_value!r} → {c.new_value!r}")
            audit_log(
                repo_root,
                {
                    "action": "sync.settings_conflicts",
                    "tool": tool,
                    "conflicts": [
                        {"path": c.path, "prior": c.prior_value, "new": c.new_value}
                        for c in conflicts
                    ],
                },
            )

        # Before the manifest is rewritten — `merge_manifest` replaces this
        # adapter's rows wholesale, taking the record of any moved output with
        # it. Reported by default; removed only when asked.
        result.orphans = find_orphans(
            rendered, bench_root, tool, still_managed=still_managed
        )
        _print_orphans(tool, result.orphans, prune, dry_run=False)
        if prune:
            result.files_pruned = prune_orphans(result.orphans, tool, bench_root)
            audit_log(
                repo_root,
                {
                    "action": "sync.pruned",
                    "tool": tool,
                    "files": [str(p) for p in result.files_pruned],
                },
            )

        if prune_harness_dir:
            harness_out = {
                r.output_path.parent
                for r in rendered
                if r.artifact_kind == "harness-script"
            }
            for hdir in harness_out:
                for gone in prune_harness(rendered, bench_root, hdir):
                    console.print(f"[yellow]pruned[/yellow] {gone}")

        result.files_written = written

        # Directories we wrote into, plus directories where this adapter
        # already owns rows.
        #
        # Keying off `written` alone meant a converged bench could never have
        # its manifests corrected: nothing is written, so no manifest is
        # rewritten, so a row stays exactly as wrong as it was — which would
        # have made the `write_once` flag below unreachable on the one bench
        # that needed it.
        #
        # Refreshing every rendered directory instead is too much. Three
        # adapters render the harness doc to the same root, and the manifest
        # models one owner per row, so the last adapter to sync would quietly
        # take ownership of rows another adapter wrote. Ownership decides which
        # adapter may prune a row, so it must not drift on a no-op sync.
        # Requiring an existing row keeps the current owner the owner.
        already_owned = {
            r.output_path.parent
            for r in rendered
            if _owns_rows_in(r.output_path.parent, tool)
        }
        bench_output_dirs = {p.parent for p in written} | already_owned
        for out_dir in bench_output_dirs:
            relevant = [r for r in rendered if r.output_path.parent == out_dir]
            entries = [
                ManifestEntry(
                    path=str(r.source_path.relative_to(repo_root)),
                    version=r.source_version,
                    sha256=sha256_text(r.content),
                    adapter=tool,
                    # What the bench was rendered FROM, so staleness is a
                    # content question rather than a guess from commit shas.
                    source_sha256=_source_hash(r.source_path),
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
                    mode=r.mode,
                    adapter=tool,
                    write_once=r.artifact_kind == "scaffold",
                )
                for r in relevant
                if r.output_path not in hand_edited
                # Settings fragments get no `outputs` row. Forge contributes to
                # settings.json, it does not own the file: what lands on disk is
                # the MERGE of forge's fragment and the human's own keys, so a
                # hash of the fragment can never match the file. Recording one
                # would make detect_hand_edits report "hand-edited" on every
                # single sync, which trains people to ignore that warning — the
                # one warning that must stay meaningful.
                and r.artifact_kind != SETTINGS_FRAGMENT_KIND
            ]
            if entries:
                manifest_commit = next(
                    iter([r.source_commit or "" for r in relevant]), ""
                )
                # Deterministic stamp: the date of the commit this output was
                # rendered from, not the moment sync ran. A wall-clock value
                # rewrote the manifest on every sync — and since the manifest
                # records each output's sha256, and those outputs carry the
                # same stamp in their own footer, one clock read dirtied two
                # files in every managed app, every time.
                manifest = build_manifest(
                    source_repo="erpnext-ai-forge",
                    source_commit=manifest_commit,
                    adapter_name=tool,
                    adapter_version="0.1.0",
                    entries=entries,
                    outputs=outputs,
                    rendered_at=commit_date(repo_root, manifest_commit),
                )
                # Fold into whatever is already there. Several adapters write
                # the same bench-root dir; overwriting would strip their rows
                # and with them their hand-edit protection.
                previous = read_manifest(out_dir)
                manifest = merge_manifest(previous, manifest)
                # Keep the row of anything we refused to overwrite. Without
                # this the hand-edit guard disarms itself: the file is excluded
                # from `outputs`, the merge drops the old row with it, and the
                # next sync sees a file forge has no record of and adopts it.
                _carry_forward_hand_edited_rows(
                    manifest, previous, set(hand_edited), out_dir
                )
                # Carry forward rows for orphans we did NOT remove. The merge
                # replaces this adapter's rows wholesale, so a reported-but-kept
                # orphan would lose its row and become indistinguishable from a
                # file a human wrote — unprunable ever after, by the very rule
                # that protects unmanaged files. Reporting must not be the thing
                # that destroys the evidence.
                _carry_forward_orphan_rows(manifest, result.orphans, out_dir)
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
    target: Target | None = None,
    prune_harness_dir: bool = False,
    prune: bool = False,
) -> list[SyncResult]:
    """Multi-tool sync into one target. Per Part B item 7: render + validate every
    tool first; only swap if all pass. On any failure: abort the whole run."""
    # Phase 1: render + stage every tool
    staged_results: list[SyncResult] = []
    for tool in tools:
        # Force dry_run during the first pass to populate staging without swapping
        r = sync_tool(repo_root, tool, dry_run=True, justify=justify, assume_yes=True,
                      target=target, prune=prune,
                      report_orphans=dry_run)
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
            sync_tool(repo_root, tool, dry_run=False, justify=justify,
                      assume_yes=assume_yes, target=target,
                      prune_harness_dir=prune_harness_dir, prune=prune)
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
    target: str | None = None,
    all_targets: bool = False,
    prune_harness_dir: bool = False,
    prune: bool = False,
) -> int:
    """CLI entry. Returns process exit code."""
    repo_root = find_repo_root()
    forge_cfg = load_forge_config(repo_root)
    targets = load_targets(repo_root, forge_cfg)

    if all_targets:
        selected = list(targets.values())
    else:
        try:
            selected = [load_target(repo_root, target, forge_cfg=forge_cfg)]
        except KeyError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

    exit_code = 0
    for tgt in selected:
        # Each target declares which adapters can act on it. The forge repo has
        # no apps and no Frappe tooling, so syncing cursor/cline/copilot into it
        # would emit files for tools that have nothing to say about a Python CLI.
        if all_tools:
            tools = list(tgt.enabled_tools)
        elif tool:
            requested = [t.strip() for t in tool.split(",")]
            tools = [t for t in requested if t in tgt.enabled_tools]
            skipped = [t for t in requested if t not in tgt.enabled_tools]
            if skipped:
                console.print(
                    f"[yellow]![/yellow] {tgt.name}: skipping "
                    f"{', '.join(skipped)} — not in this target's enabled_tools."
                )
        else:
            console.print("[red]Pass --tool <name> or --all[/red]")
            return 2

        if not tools:
            console.print(f"[yellow]{tgt.name}: no enabled tools to sync.[/yellow]")
            continue

        if len(selected) > 1:
            console.print(f"\n[bold cyan]── target: {tgt.name} ──[/bold cyan]")
        results = sync_all(
            repo_root, tools, dry_run=dry_run, justify=justify,
            assume_yes=assume_yes, target=tgt,
            prune_harness_dir=prune_harness_dir, prune=prune,
        )
        if any(not r.success for r in results):
            exit_code = 1
    return exit_code
