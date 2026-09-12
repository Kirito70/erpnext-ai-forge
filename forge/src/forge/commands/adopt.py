"""`forge adopt` — fold hand edits in generated files back into canonical.

Forge owning a file must not mean "your edits vanish on the next sync".
Someone correcting a wrong instruction is editing the file actually in front of
them, which is the reasonable thing to do; the failure mode to avoid is the
next sync silently discarding that correction.

So the loop is: `forge sync` detects the edit and refuses to overwrite →
`forge adopt` moves the edit into `canonical/apps/<app>.md` → the next sync
regenerates cleanly from canonical and everyone stays in agreement.

Adoption is deliberately reviewable, not automatic. It rewrites the canonical
file and leaves the result in your working tree for `git diff` — forge never
commits on your behalf.
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from forge.loader import find_repo_root, load_target
from forge.manifest import ManifestEntry, read_manifest, sha256_text, write_manifest
from forge.render import render
from forge.sync import app_of_output, detect_hand_edits

console = Console()

# Everything the generator contributes, which must NOT be carried back into
# canonical or it would be duplicated on the next render.
_GENERATED_HEAD = re.compile(r"\A(?:<!--.*?-->\s*)+", re.S)
# `#` NOT followed by another `#` — otherwise a notes body that opens with an
# H2 loses its first heading on every adoption.
_H1 = re.compile(r"\A#(?!#)[^\n]*\n", re.S)
_FACTS = re.compile(r"\A(?:\*\*(?:Stack|Custom DocTypes|Whitelist APIs|Purpose):\*\*[^\n]*\n)+", re.S)
# Matches ANY footer-shaped block, not just the trailing one — a document can
# accumulate a stray earlier footer (e.g. a leftover from a prior sync that
# never got cleaned up). Only the LAST such match is ever the real trailing
# footer; see `_strip_generated_scaffolding` for why that distinction matters.
_FOOTER_BLOCK = re.compile(r"\n*---\n+<sub>.*?</sub>\s*", re.S)
_COMMON_COMMANDS = re.compile(r"\n*(?:---\n+)?## Common Commands\n.*?(?=\n---\n|\Z)", re.S)


def _strip_generated_scaffolding(text: str) -> str:
    """Reduce a rendered per-app file back to just its notes body.

    The rendered file is `generated header + facts + notes + commands + footer`.
    Only the notes belong in canonical; re-adopting the rest would duplicate it
    on every round trip.
    """
    body = text
    # Strip only the LAST footer-shaped block, and only if nothing but
    # whitespace follows it. A naive "lazy .*? anchored to \Z" regex matches
    # from the FIRST footer-shaped block all the way to the end whenever two
    # exist, silently swallowing everything in between — including hand-added
    # sections sitting after a stray leftover footer.
    footer_matches = list(_FOOTER_BLOCK.finditer(body))
    if footer_matches:
        last = footer_matches[-1]
        if not body[last.end() :].strip():
            body = body[: last.start()]
    # Any OTHER footer-shaped block is stale leftover, not notes — drop it too,
    # rather than carrying it into canonical as if a human wrote it.
    body = _FOOTER_BLOCK.sub("", body)
    body = _COMMON_COMMANDS.sub("", body)
    body = _GENERATED_HEAD.sub("", body)
    body = _H1.sub("", body).lstrip("\n")
    body = _FACTS.sub("", body).lstrip("\n")
    body = re.sub(r"\A---\n+", "", body)
    return body.strip() + "\n"


def _mark_adopted(output_path: Path) -> None:
    """Record ``output_path``'s current content as forge's own in the manifest.

    Adoption hands ownership back: canonical carries the edit now, so the next
    sync must be free to regenerate this file rather than keep skipping it.
    """
    manifest = read_manifest(output_path.parent)
    if manifest is None:
        return
    current = sha256_text(output_path.read_text())
    for entry in manifest.outputs:
        if entry.path == output_path.name:
            entry.sha256 = current
            break
    else:
        manifest.outputs.append(
            ManifestEntry(path=output_path.name, version="adopted", sha256=current)
        )
    write_manifest(output_path.parent, manifest)


def run(tool: str, app: str | None, apply: bool) -> int:
    repo_root = find_repo_root()
    bench_root = load_target(repo_root).root
    if not bench_root.is_dir():
        console.print(f"[red]Bench path not found: {bench_root}. Set FORGE_BENCH_PATH.[/red]")
        return 2

    rendered = render(repo_root, tool)
    edits = detect_hand_edits(rendered, bench_root)
    if not edits:
        console.print(f"[green]✓[/green] {tool}: no hand edits to adopt.")
        return 0

    adoptable: list[tuple[Path, str]] = []
    skipped: list[Path] = []
    for path in sorted(edits):
        app_name = app_of_output(path)
        if app_name is None:
            skipped.append(path)
            continue
        if app and app_name != app:
            continue
        adoptable.append((path, app_name))

    for path in skipped:
        console.print(
            f"[yellow]![/yellow] {path} is hand-edited but is not a per-app file — "
            "adopt it by editing the template or shared partial it came from."
        )

    if not adoptable:
        return 1 if skipped else 0

    apps_dir = repo_root / "canonical" / "apps"
    apps_dir.mkdir(parents=True, exist_ok=True)

    for path, app_name in adoptable:
        target = apps_dir / f"{app_name}.md"
        notes = _strip_generated_scaffolding(path.read_text())

        if not apply:
            console.print(
                f"[cyan]would adopt[/cyan] {path} → canonical/apps/{app_name}.md "
                f"({len(notes):,} chars)"
            )
            continue

        if target.is_file():
            existing = target.read_text()
            # Keep the frontmatter, replace the body.
            match = re.match(r"\A(---\n.*?\n---\n)", existing, re.S)
            frontmatter = match.group(1) if match else ""
        else:
            frontmatter = (
                "---\n"
                f"id: {app_name}\n"
                "kind: app-notes\n"
                "version: 1.0.0\n"
                "status: stable\n"
                "---\n"
            )
        target.write_text(frontmatter + "\n" + notes)

        # Clear the conflict: record the file's CURRENT hash as what forge last
        # produced. Without this the edit stays flagged forever — canonical now
        # holds the change, but the on-disk file still differs from the hash
        # recorded before the edit, so every later sync would skip it and the
        # file would quietly stop being regenerated.
        _mark_adopted(path)

        console.print(f"[green]✓[/green] adopted {path} → canonical/apps/{app_name}.md")

    if apply:
        console.print(
            "\nReview with [cyan]git diff canonical/apps/[/cyan], then re-run "
            "[cyan]forge sync[/cyan] to regenerate."
        )
    else:
        console.print("\nNothing written — pass [cyan]--apply[/cyan] to adopt.")
    return 0
