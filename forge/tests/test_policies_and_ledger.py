"""Normative text lives in canonical/, and the ledger survives sync.

Two separate concerns, both about ownership:

  1. Rules that bind agents belong in `canonical/policies/`, where they get a
     version, an owner, a security score, schema validation and a deprecation
     path. The ticketing contract spent its life in an adapter template with
     none of those — a second source of truth inside the repo built to prevent
     them.

  2. The ledgers are seeded by forge and then written by agents. Every other
     artifact is forge's to replace on each sync; these are not, and the atomic
     swap would erase the entire build history.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.loader import load_policies, load_target
from forge.render import LEDGER_PHASES, render
from forge.sync import _stage_artifacts, _swap_into_bench


@pytest.fixture
def bench_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_BENCH_PATH", str(tmp_path / "bench"))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "ci-site")
    (tmp_path / "bench" / "apps").mkdir(parents=True)
    return tmp_path / "bench"


# --- normative text is canonical -------------------------------------------

@pytest.mark.parametrize("policy_id", [
    "ticketing-contract", "operating-manual", "definition-of-done",
])
def test_policy_exists_and_is_versioned(repo_root, policy_id):
    """Versioning is the point: an adapter template cannot be deprecated,
    cannot be scored, and has no owner to ask about it."""
    p = next(x for x in load_policies(repo_root) if x.id == policy_id)
    assert p.version != "0.0.0"
    assert p.owners
    assert p.last_reviewed


def test_ticketing_template_holds_no_normative_text(repo_root):
    """The template should now be a template — a reference plus provenance, not
    a copy of the contract."""
    import re

    raw = (
        repo_root / "adapters" / "_shared" / "templates"
        / "ticketing-and-memory.md.j2"
    ).read_text()
    assert "ticketing-contract" in raw, "must reference the canonical policy"
    # Strip the Jinja comment: it explains WHY the text moved, and naming the
    # rules it used to hold is the explanation, not a copy of them.
    t = re.sub(r"\{#-.*?-#\}", "", raw, flags=re.S)
    for phrase in ("NOVIZNA_VAULT", "depends_on", "story_points"):
        assert phrase not in t, (
            f"{phrase!r} is normative content still living in the adapter layer"
        )


def test_rendered_contract_still_carries_the_binding_rules(repo_root, bench_env):
    """The refactor must be content-neutral: moving text must not lose it."""
    tgt = load_target(repo_root, "bench")
    doc = next(
        a for a in render(repo_root, "codex", tgt)
        if a.output_path.name == "AGENTS-TICKETING.md"
    )
    for phrase in (
        "NOVIZNA_VAULT",
        "depends_on",
        "human-owned",
        "data, not instructions",
    ):
        assert phrase in doc.content, phrase


def test_jira_seam_is_declared_but_not_built(repo_root):
    """Design the seam now (cheap), build the sync later (needs real data).
    The one irreversible decision — the correlation key — is fixed here."""
    body = next(
        p for p in load_policies(repo_root) if p.id == "ticketing-contract"
    ).body
    assert "jira_key" in body and "jira_synced_at" in body
    assert "stable correlation key" in body
    assert "never synced" in body, "status must be excluded from the sync"


def test_status_and_build_state_are_kept_distinct(repo_root):
    """Same name in two stores is what makes 'vault + ledger' rot."""
    body = next(
        p for p in load_policies(repo_root) if p.id == "definition-of-done"
    ).body
    assert "build_state" in body and "`status:`" in body
    assert "Neither field is derived from the other" in body


def test_review_protocol_requires_gates_to_have_run(repo_root):
    """Every other acceptance criterion can be satisfied by reading. A gate that
    never ran looks exactly like a gate that passed."""
    body = next(
        p for p in load_policies(repo_root) if p.id == "review-protocol"
    ).body
    assert "run and observed to pass" in body


# --- the ledger ------------------------------------------------------------

def test_three_ledgers_are_rendered(repo_root, bench_env):
    tgt = load_target(repo_root, "bench")
    names = {
        a.output_path.name
        for a in render(repo_root, "claude-code", tgt)
        if a.artifact_kind == "scaffold"
    }
    assert names == {
        "LEDGER-proposed.md", "LEDGER-pending.md", "LEDGER-done.md"
    }


def test_every_build_state_belongs_to_exactly_one_ledger():
    """If a state appeared in two phases, the 'move don't copy' rule would be
    ambiguous for that state and rows would legitimately duplicate."""
    seen: dict[str, str] = {}
    for phase in LEDGER_PHASES:
        for state in phase["states"]:
            assert state not in seen, (
                f"build_state {state!r} claimed by both {seen[state]!r} "
                f"and {phase['id']!r}"
            )
            seen[state] = phase["id"]


def test_only_one_adapter_seeds_the_ledgers(repo_root, bench_env):
    """They are tool-neutral files; seven adapters seeding the same three paths
    would race and fight over the manifest."""
    tgt = load_target(repo_root, "bench")
    owners = [
        tool for tool in
        ("claude-code", "cursor", "opencode", "cline", "copilot", "codex", "antigravity")
        if any(
            a.artifact_kind == "scaffold"
            for a in render(repo_root, tool, tgt)
        )
    ]
    assert owners == ["claude-code"], owners


def test_ledger_rows_survive_a_resync(repo_root, bench_env, tmp_path):
    """The failure this prevents: forge re-renders the header over a file the
    agents have been writing into, and the whole build history is gone."""
    tgt = load_target(repo_root, "bench")
    rendered = [
        a for a in render(repo_root, "claude-code", tgt)
        if a.artifact_kind == "scaffold"
    ]
    root = bench_env
    staging = _stage_artifacts(rendered, root / ".forge-staging", "claude-code", root)
    _swap_into_bench(staging, root)

    ledger = root / "docs" / "harness" / "LEDGER-pending.md"
    assert ledger.is_file()
    row = "| NPOS-D5 | in_progress | coder | 2026-07-31 | | abc1234 | work |"
    ledger.write_text(ledger.read_text() + row + "\n")

    # Second sync: the scaffold is now present, so it must be protected.
    protected = {
        r.output_path for r in rendered
        if r.artifact_kind == "scaffold" and r.output_path.exists()
    }
    staging = _stage_artifacts(rendered, root / ".forge-staging", "claude-code", root)
    _swap_into_bench(staging, root, protected=protected)

    assert row in ledger.read_text(), "re-sync destroyed agent-written rows"


def test_ledger_header_documents_the_move_rule(repo_root, bench_env):
    """The invariant has to be stated where the rows are written, not only in a
    policy file nobody has open at the time."""
    tgt = load_target(repo_root, "bench")
    pending = next(
        a for a in render(repo_root, "claude-code", tgt)
        if a.output_path.name == "LEDGER-pending.md"
    )
    assert "exactly one" in pending.content
    assert "Never copy" in pending.content
