"""`forge ledger sync` — reconcile the vault against the repo ledger.

Per definition-of-done.md: the vault owns `status:`, the repo ledger owns
`build_state:`, and neither is derived from the other. This module does NOT
sync field values — it only checks ticket-key coverage across the two
stores. These tests build throwaway vault + target fixtures rather than
touching any real vault or the real repo's ledgers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.ledger_sync import (
    parse_ledger_rows,
    parse_vault_tickets,
    reconcile,
    resolve_vault_path,
    seed_missing_rows,
)


def _ticket(vault: Path, project: str, key: str, status: str) -> Path:
    d = vault / "wiki" / project / "tickets"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{key}.md"
    p.write_text(f"---\nid: {key}\ntitle: x\nstatus: {status}\ncreated: 2026-07-27\n---\nBody.\n")
    return p


def _ledger(target_root: Path, filename: str, rows: list[str]) -> Path:
    d = target_root / "docs" / "harness"
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    header = "| KEY | build_state | agent | started | finished | last commit | notes |\n|-----|-------------|-------|---------|----------|-------------|-------|\n"
    p.write_text(header + "\n".join(rows) + ("\n" if rows else ""))
    return p


# --- vault path resolution ---------------------------------------------------

def test_explicit_path_wins(tmp_path):
    (tmp_path / "vault").mkdir()
    assert resolve_vault_path(tmp_path / "vault") == tmp_path / "vault"


def test_explicit_nonexistent_path_is_none(tmp_path):
    assert resolve_vault_path(tmp_path / "nope") is None


def test_env_var_used_when_no_explicit_path(tmp_path, monkeypatch):
    (tmp_path / "vault").mkdir()
    monkeypatch.setenv("NOVIZNA_VAULT", str(tmp_path / "vault"))
    assert resolve_vault_path(None) == tmp_path / "vault"


def test_no_resolution_is_none_not_a_guess(monkeypatch, tmp_path):
    """The contract says 'ask the user — do not guess'. Confirms this never
    falls back to a plausible-looking default path."""
    monkeypatch.delenv("NOVIZNA_VAULT", raising=False)
    monkeypatch.setattr("forge.ledger_sync._BRAINS_CONFIG", tmp_path / "nonexistent.toml")
    assert resolve_vault_path(None) is None


# --- parsing ------------------------------------------------------------------

def test_parse_vault_tickets(tmp_path):
    _ticket(tmp_path, "novizna-pos", "NPOS-D5", "In Progress")
    _ticket(tmp_path, "novizna-pos", "NPOS-D6", "To Do")
    tickets = parse_vault_tickets(tmp_path, "novizna-pos")
    assert set(tickets) == {"NPOS-D5", "NPOS-D6"}
    assert tickets["NPOS-D5"].status == "In Progress"


def test_parse_vault_tickets_missing_project_dir_is_empty(tmp_path):
    assert parse_vault_tickets(tmp_path, "nonexistent-project") == {}


def test_parse_ledger_rows_across_all_three_files(tmp_path):
    _ledger(tmp_path, "LEDGER-proposed.md", ["| NPOS-G1 | gap | | | | | |"])
    _ledger(tmp_path, "LEDGER-pending.md", ["| NPOS-D5 | in_progress | | | | | |"])
    _ledger(tmp_path, "LEDGER-done.md", ["| NPOS-D1 | done | | | | | |"])
    rows = parse_ledger_rows(tmp_path)
    assert set(rows) == {"NPOS-G1", "NPOS-D5", "NPOS-D1"}
    assert rows["NPOS-D5"].build_state == "in_progress"
    assert rows["NPOS-D5"].ledger_file == "LEDGER-pending.md"


def test_parse_ledger_rows_skips_header_and_separator(tmp_path):
    _ledger(tmp_path, "LEDGER-pending.md", [])
    rows = parse_ledger_rows(tmp_path)
    assert rows == {}


def test_parse_ledger_rows_no_ledger_dir_is_empty(tmp_path):
    assert parse_ledger_rows(tmp_path) == {}


# --- reconciliation -----------------------------------------------------------

def test_to_do_with_no_row_is_not_a_finding(tmp_path):
    """Most of a backlog is untouched at any time — flagging all of it would
    bury the findings that actually matter."""
    _ticket(tmp_path, "p", "X-1", "To Do")
    tickets = parse_vault_tickets(tmp_path, "p")
    assert reconcile(tickets, {}) == []


def test_in_progress_with_no_row_is_a_finding(tmp_path):
    _ticket(tmp_path, "p", "X-1", "In Progress")
    tickets = parse_vault_tickets(tmp_path, "p")
    findings = reconcile(tickets, {})
    assert len(findings) == 1
    assert findings[0].problem == "missing-ledger-row"
    assert findings[0].key == "X-1"


def test_done_with_no_row_is_also_a_finding(tmp_path):
    _ticket(tmp_path, "p", "X-1", "Done")
    tickets = parse_vault_tickets(tmp_path, "p")
    findings = reconcile(tickets, {})
    assert any(f.problem == "missing-ledger-row" for f in findings)


def test_ledger_row_with_no_vault_ticket_is_an_orphan(tmp_path):
    _ledger(tmp_path, "LEDGER-pending.md", ["| GHOST-1 | todo | | | | | |"])
    rows = parse_ledger_rows(tmp_path)
    findings = reconcile({}, rows)
    assert len(findings) == 1
    assert findings[0].problem == "orphan-ledger-row"


def test_covered_active_ticket_is_clean(tmp_path):
    from forge.ledger_sync import LedgerRow

    _ticket(tmp_path, "p", "X-1", "In Progress")
    tickets = parse_vault_tickets(tmp_path, "p")
    rows = {"X-1": LedgerRow(key="X-1", build_state="in_progress",
                             ledger_file="LEDGER-pending.md", raw_line="")}
    assert reconcile(tickets, rows) == []


def test_status_and_build_state_are_never_compared_to_each_other(tmp_path):
    """A ticket marked Done in the vault with build_state: todo in the ledger
    must NOT be a finding — that would require comparing the two fields, which
    the design deliberately forbids. Only presence/absence of a row matters."""
    _ticket(tmp_path, "p", "X-1", "Done")
    tickets = parse_vault_tickets(tmp_path, "p")
    from forge.ledger_sync import LedgerRow
    rows = {"X-1": LedgerRow(key="X-1", build_state="todo",
                             ledger_file="LEDGER-pending.md", raw_line="")}
    assert reconcile(tickets, rows) == []


# --- --fix seeding --------------------------------------------------------------

def test_fix_seeds_a_conservative_todo_row(tmp_path):
    _ledger(tmp_path, "LEDGER-pending.md", [])
    from forge.ledger_sync import ReconcileFinding
    findings = [ReconcileFinding(key="X-1", problem="missing-ledger-row", detail="")]
    seeded = seed_missing_rows(tmp_path, findings)
    assert seeded == ["X-1"]
    content = (tmp_path / "docs" / "harness" / "LEDGER-pending.md").read_text()
    assert "| X-1 | todo |" in content


def test_fix_never_touches_orphans(tmp_path):
    _ledger(tmp_path, "LEDGER-pending.md", ["| GHOST | todo | | | | | |"])
    from forge.ledger_sync import ReconcileFinding
    findings = [ReconcileFinding(key="GHOST", problem="orphan-ledger-row", detail="")]
    seeded = seed_missing_rows(tmp_path, findings)
    assert seeded == []
    content = (tmp_path / "docs" / "harness" / "LEDGER-pending.md").read_text()
    assert content.count("GHOST") == 1  # unchanged, not duplicated or removed


def test_fix_requires_the_ledger_to_already_exist(tmp_path):
    """Seeding into a target that was never synced would create a ledger
    outside forge's normal render/scaffold path."""
    from forge.ledger_sync import ReconcileFinding
    findings = [ReconcileFinding(key="X-1", problem="missing-ledger-row", detail="")]
    with pytest.raises(FileNotFoundError):
        seed_missing_rows(tmp_path, findings)


def test_fix_is_idempotent_via_full_reconcile_cycle(tmp_path):
    """Seed once, re-reconcile against the new state, confirm clean —
    the actual guarantee the CLI's --fix relies on."""
    _ticket(tmp_path, "p", "X-1", "In Progress")
    _ledger(tmp_path, "LEDGER-pending.md", [])
    tickets = parse_vault_tickets(tmp_path, "p")

    findings = reconcile(tickets, parse_ledger_rows(tmp_path))
    assert len(findings) == 1
    seed_missing_rows(tmp_path, findings)

    findings_after = reconcile(tickets, parse_ledger_rows(tmp_path))
    assert findings_after == []
