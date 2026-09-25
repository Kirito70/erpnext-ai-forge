"""App-note narration guard (BRAIN-T14).

An always-loaded per-app note is the wrong home for ticket history. This
measures *narration* — bytes in bullets that carry a ticket key — rather than
raw size, so a large but well-structured domain file does not warn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TICKET_KEY = re.compile(r"\b[A-Z]{3,5}-[A-Z]?\d+[a-z]?\b")
MAX_DENSITY = 0.10
MAX_BULLET_BYTES = 800
MAX_FILE_BYTES = 24 * 1024


@dataclass(frozen=True)
class NarrationReport:
    name: str
    total_bytes: int
    ticket_bytes: int
    long_bullets: tuple[tuple[int, int], ...] = field(default_factory=tuple)  # (line, bytes)
    ticket_bullets: tuple[tuple[int, int], ...] = field(default_factory=tuple)  # (line, bytes)

    @property
    def density(self) -> float:
        return self.ticket_bytes / self.total_bytes if self.total_bytes else 0.0

    def warnings(self) -> list[str]:
        out: list[str] = []
        if self.density > MAX_DENSITY:
            lines = ", ".join(f"L{n}" for n, _ in self.ticket_bullets)
            out.append(
                f"{self.name}: {self.density:.0%} of the note is ticket detail "
                f"(limit {MAX_DENSITY:.0%}) — bullets at {lines}"
            )
        for line, size in self.long_bullets:
            out.append(f"{self.name}: bullet at L{line} is {size} B (limit {MAX_BULLET_BYTES} B)")
        if self.total_bytes > MAX_FILE_BYTES:
            out.append(
                f"{self.name}: {self.total_bytes} B exceeds {MAX_FILE_BYTES} B"
            )
        return out


def _bullets(text: str) -> list[tuple[int, str]]:
    """Split into (start_line, block) where a block is a bullet plus its continuation."""
    blocks: list[tuple[int, list[str]]] = []
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith(("- ", "* ")):
            blocks.append((n, [line]))
        elif line.startswith("#") or not line.strip():
            blocks.append((n, []))
        elif blocks and blocks[-1][1]:
            blocks[-1][1].append(line)
    return [(n, "\n".join(b)) for n, b in blocks if b]


def measure(name: str, text: str) -> NarrationReport:
    ticket: list[tuple[int, int]] = []
    long: list[tuple[int, int]] = []
    for line, block in _bullets(text):
        size = len(block.encode())
        if size > MAX_BULLET_BYTES:
            long.append((line, size))
        if TICKET_KEY.search(block):
            ticket.append((line, size))
    return NarrationReport(
        name=name,
        total_bytes=len(text.encode()),
        ticket_bytes=sum(s for _, s in ticket),
        long_bullets=tuple(long),
        ticket_bullets=tuple(ticket),
    )
