"""`forge diff` — what would `forge sync` change, without changing anything.

`--dry-run` already proves a render *succeeds*, but it stages into
`.forge-staging/` and says how many files it wrote. That answers "did it work",
not "what is about to happen to my repo" — and those are different questions the
moment sync starts writing things that are hard to eyeball after the fact:
executable hook scripts, and a `.claude/settings.json` that is *merged* into
human-owned content rather than replaced.

So this renders in memory, compares against what is on disk, and prints the
delta. It never writes. Read it before a sync you cannot easily undo.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from forge.loader import find_repo_root, load_target
from forge.manifest import sha256_text
from forge.render import RenderedArtifact, render
from forge.sync import detect_hand_edits

console = Console()

# Statuses, ordered by how much they should worry the reader.
NEW = "new"
MODIFIED = "modified"
MODE = "mode"
HAND_EDITED = "hand-edited"
UNCHANGED = "unchanged"
MERGED = "merged"

_MARKER = {
    NEW: ("+", "green"),
    MODIFIED: ("~", "yellow"),
    MODE: ("m", "cyan"),
    HAND_EDITED: ("!", "red"),
    MERGED: ("m", "magenta"),
    UNCHANGED: ("=", "dim"),
}


@dataclass
class FileDiff:
    path: Path
    status: str
    before: str | None
    after: str
    mode_before: int | None = None
    mode_after: int | None = None

    @property
    def unified(self) -> str:
        return "".join(
            difflib.unified_diff(
                (self.before or "").splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile=f"a/{self.path.name}",
                tofile=f"b/{self.path.name}",
                n=3,
            )
        )


def compute_diffs(
    rendered: list[RenderedArtifact], bench_root: Path
) -> list[FileDiff]:
    """Classify every rendered artifact against what is on disk.

    `hand-edited` outranks `modified` on purpose: when a human has changed a
    generated file, the fact that forge would overwrite it is the headline, and
    sync will refuse to touch it until `forge adopt` routes the edit back into
    canonical.
    """
    hand_edited = detect_hand_edits(rendered, bench_root)
    diffs: list[FileDiff] = []

    for art in rendered:
        target = art.output_path
        exists = target.is_file()
        before = target.read_text(errors="replace") if exists else None
        mode_before = (target.stat().st_mode & 0o777) if exists else None

        if art.artifact_kind == "settings-fragment":
            # This file is merged into, not replaced. Its bytes will never equal
            # the fragment's, so "modified" would be a permanent false alarm.
            status = MERGED if exists else NEW
        elif not exists:
            status = NEW
        elif target in hand_edited:
            status = HAND_EDITED
        elif before is not None and sha256_text(before) != sha256_text(art.content):
            status = MODIFIED
        elif art.mode is not None and mode_before != art.mode:
            # Content identical but the permission bit is wrong — the case that
            # matters for hook scripts, and the one a content-only diff misses
            # entirely.
            status = MODE
        else:
            status = UNCHANGED

        diffs.append(
            FileDiff(
                path=target,
                status=status,
                before=before,
                after=art.content,
                mode_before=mode_before,
                mode_after=art.mode,
            )
        )

    return diffs


def render_diff_report(
    diffs: list[FileDiff], bench_root: Path, *, show_content: bool, show_unchanged: bool
) -> str:
    lines: list[str] = []
    counts: dict[str, int] = {}
    for d in diffs:
        counts[d.status] = counts.get(d.status, 0) + 1

    for d in sorted(diffs, key=lambda x: str(x.path)):
        if d.status == UNCHANGED and not show_unchanged:
            continue
        marker, colour = _MARKER[d.status]
        try:
            shown = d.path.relative_to(bench_root)
        except ValueError:
            shown = d.path
        suffix = ""
        if d.status == MERGED:
            suffix = "  [merged into, not replaced]"
        elif d.status == MODE:
            suffix = f"  [{_fmt_mode(d.mode_before)} → {_fmt_mode(d.mode_after)}]"
        elif d.status == NEW and d.mode_after is not None:
            suffix = f"  [{_fmt_mode(d.mode_after)}]"
        lines.append(f"[{colour}]{marker} {shown}{suffix}[/{colour}]")

        if show_content and d.status in (MODIFIED, HAND_EDITED):
            body = d.unified
            if body:
                lines.append(f"[dim]{_escape(body).rstrip()}[/dim]")

    if not lines:
        lines.append("[green]No changes — the target matches canonical.[/green]")

    summary = ", ".join(
        f"{counts[k]} {k}" for k in (NEW, MODIFIED, MODE, MERGED, HAND_EDITED, UNCHANGED)
        if counts.get(k)
    )
    lines.append("")
    lines.append(f"[bold]{summary or 'nothing rendered'}[/bold]")
    if counts.get(HAND_EDITED):
        lines.append(
            "[red]Hand-edited files will NOT be overwritten by sync.[/red] "
            "Run [cyan]forge adopt[/cyan] to fold those edits back into canonical."
        )
    return "\n".join(lines)


def _fmt_mode(mode: int | None) -> str:
    return "default" if mode is None else format(mode, "04o")


def _escape(text: str) -> str:
    """Rich treats [..] as markup; diff bodies are arbitrary text."""
    return text.replace("[", r"\[")


def run(
    tool: str,
    *,
    show_content: bool = True,
    show_unchanged: bool = False,
    target: str | None = None,
) -> int:
    repo_root = find_repo_root()
    tgt = load_target(repo_root, target)
    rendered = render(repo_root, tool, tgt)
    if not rendered:
        console.print(f"[yellow]{tool} rendered nothing.[/yellow]")
        return 0

    bench_root = tgt.root
    diffs = compute_diffs(rendered, bench_root)
    console.print(
        render_diff_report(
            diffs, bench_root, show_content=show_content, show_unchanged=show_unchanged
        )
    )
    return 0

