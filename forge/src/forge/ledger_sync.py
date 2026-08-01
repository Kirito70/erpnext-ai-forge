"""`forge ledger sync` — reconcile the vault against the repo ledger.

Per canonical/policies/definition-of-done.md: the vault owns intent
(`status:`), the repo ledger owns build evidence (`build_state:`), and
neither is derived from the other. This module does NOT sync those field
values — doing so would recreate exactly the coupling that split them in the
first place. What it checks is coverage and consistency of TICKET KEYS across
the two stores:

  - a ledger row whose key has no matching vault ticket (orphan — the vault
    ticket may have been deleted, renamed, or scoped to a different project)
  - a vault ticket marked `In Progress` or `Done` with NO ledger row anywhere
    (a coverage gap — work happened, or is happening, with nothing recording
    it, which defeats the point of LEDGER-pending.md being the one file a
    build session needs to read)

A `To Do` ticket with no ledger row is normal, not a finding — most of a
project's backlog is untouched at any given time, and flagging all of it
would bury the two or three findings that matter under hundreds that don't.

`--fix` only ever CREATES a `todo` row in LEDGER-pending.md for a coverage
gap. It never touches the vault, never modifies an existing ledger row, and
never guesses a `build_state` beyond the conservative default — an agent or
human corrects it through the normal build flow once they look at the ticket.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import frontmatter

# Mirrors the discovery order in canonical/policies/ticketing-contract.md
# exactly. A literal path here would be the bug that policy exists to prevent.
_BRAINS_CONFIG = Path.home() / ".config" / "brain" / "brains.toml"

LEDGER_FILES = ("LEDGER-proposed.md", "LEDGER-pending.md", "LEDGER-done.md")


def resolve_vault_path(explicit: Path | None = None) -> Path | None:
    """`--vault-path` > `$NOVIZNA_VAULT` > brains.toml default > None.

    None means "ask the user — do not guess", per the contract. This function
    never falls back to a guessed path.
    """
    if explicit is not None:
        return explicit if explicit.is_dir() else None

    env_path = os.environ.get("NOVIZNA_VAULT")
    if env_path:
        p = Path(env_path)
        return p if p.is_dir() else None

    if _BRAINS_CONFIG.is_file():
        try:
            data = tomllib.loads(_BRAINS_CONFIG.read_text())
        except (tomllib.TOMLDecodeError, OSError):
            return None
        vaults = data.get("vaults", [])
        chosen = [v for v in vaults if v.get("default")] or vaults
        if chosen and chosen[0].get("path"):
            p = Path(chosen[0]["path"])
            return p if p.is_dir() else None

    return None


@dataclass(frozen=True)
class VaultTicket:
    key: str
    status: str
    source_path: Path


@dataclass(frozen=True)
class LedgerRow:
    key: str
    build_state: str
    ledger_file: str
    raw_line: str


@dataclass(frozen=True)
class ReconcileFinding:
    key: str
    problem: str
    """One of: 'orphan-ledger-row', 'missing-ledger-row'."""
    detail: str


def parse_vault_tickets(vault_path: Path, project: str) -> dict[str, VaultTicket]:
    """Every ticket under `wiki/<project>/tickets/*.md`, keyed by its id.

    A ticket file missing or unparsable is skipped rather than raising — one
    malformed file in a project's backlog must not stop reconciliation of
    every other ticket.
    """
    tickets_dir = vault_path / "wiki" / project / "tickets"
    if not tickets_dir.is_dir():
        return {}

    out: dict[str, VaultTicket] = {}
    for path in sorted(tickets_dir.glob("*.md")):
        try:
            post = frontmatter.load(path)
        except Exception:
            continue
        fm: dict[str, Any] = post.metadata or {}
        key = str(fm.get("id") or path.stem)
        status = str(fm.get("status", "To Do"))
        out[key] = VaultTicket(key=key, status=status, source_path=path)
    return out


_ROW_RE = re.compile(r"^\|\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|")


def parse_ledger_rows(target_root: Path) -> dict[str, LedgerRow]:
    """Every row across all three ledger files, keyed by ticket key.

    Does not itself enforce the one-file invariant (that is `forge
    validate`'s job) — if a key somehow appears in two files, the second one
    parsed wins here, which is fine for reconciliation purposes: either
    location proves the ledger has SOME coverage for that key.
    """
    ledger_dir = target_root / "docs" / "harness"
    out: dict[str, LedgerRow] = {}
    if not ledger_dir.is_dir():
        return out

    for filename in LEDGER_FILES:
        path = ledger_dir / filename
        if not path.is_file():
            continue
        for line in path.read_text(errors="replace").splitlines():
            m = _ROW_RE.match(line)
            if not m:
                continue
            key, build_state = m.group(1).strip(), m.group(2).strip()
            if not key or key.upper() == "KEY" or set(key) <= set("- "):
                continue
            out[key] = LedgerRow(
                key=key, build_state=build_state, ledger_file=filename, raw_line=line
            )
    return out


# Vault states that mean "something has actually happened on this ticket" —
# the only states worth requiring ledger coverage for. "To Do" is the resting
# state of most of a backlog at any given time.
_ACTIVE_VAULT_STATUSES = {"in progress", "done"}


def reconcile(
    vault_tickets: dict[str, VaultTicket], ledger_rows: dict[str, LedgerRow]
) -> list[ReconcileFinding]:
    findings: list[ReconcileFinding] = []

    for key, row in sorted(ledger_rows.items()):
        if key not in vault_tickets:
            findings.append(
                ReconcileFinding(
                    key=key,
                    problem="orphan-ledger-row",
                    detail=(
                        f"{row.ledger_file} has a row for {key!r} (build_state: "
                        f"{row.build_state}) but no matching vault ticket was found "
                        f"for this project — deleted, renamed, or wrong --project?"
                    ),
                )
            )

    for key, ticket in sorted(vault_tickets.items()):
        if ticket.status.strip().lower() not in _ACTIVE_VAULT_STATUSES:
            continue
        if key not in ledger_rows:
            findings.append(
                ReconcileFinding(
                    key=key,
                    problem="missing-ledger-row",
                    detail=(
                        f"{key} is {ticket.status!r} in the vault but has no ledger "
                        f"row in any of {', '.join(LEDGER_FILES)} — work happened "
                        f"with nothing recording it"
                    ),
                )
            )

    return findings


def seed_missing_rows(
    target_root: Path, findings: list[ReconcileFinding]
) -> list[str]:
    """Append a conservative `todo` row for every `missing-ledger-row` finding.

    Never touches the vault. Never modifies an existing row. Never guesses a
    real build_state — `todo` is the honest minimum, corrected by whoever
    actually looks at the ticket next through the normal build flow.
    """
    to_seed = [f.key for f in findings if f.problem == "missing-ledger-row"]
    if not to_seed:
        return []

    pending = target_root / "docs" / "harness" / "LEDGER-pending.md"
    if not pending.is_file():
        raise FileNotFoundError(
            f"{pending} does not exist — run `forge sync` for this target first "
            f"so the ledger scaffolds are seeded."
        )

    today = datetime.now(timezone.utc).date().isoformat()
    lines = [
        f"| {key} | todo | | {today} | | | seeded by `forge ledger sync --fix` — "
        f"verify actual build state |"
        for key in to_seed
    ]
    with pending.open("a") as f:
        f.write("\n".join(lines) + "\n")

    return to_seed
