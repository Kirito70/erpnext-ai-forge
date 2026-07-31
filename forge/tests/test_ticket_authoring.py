"""PHASE-5: ticket authoring and refinement.

Covers the acceptance criteria drafted in docs/tickets/PHASE-5.md:
  - the skill/commands/agent exist with correct frontmatter and score well
  - forge validate passes with the new artifacts
  - char budget stays within limits after landing them
  - the ownership guard and gap-loop mechanics are actually documented, not
    just implied
"""

from __future__ import annotations

import pytest

from forge.loader import (
    load_agents,
    load_commands,
    load_skills,
    load_target,
)
from forge.render import render
from forge.scoring import score_file


@pytest.fixture
def bench_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_BENCH_PATH", str(tmp_path / "bench"))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "ci-site")
    (tmp_path / "bench" / "apps").mkdir(parents=True)
    return tmp_path / "bench"


# --- artifacts exist with correct frontmatter -------------------------------

def test_ticket_authoring_guide_exists_as_a_skill(repo_root):
    skills = {s.id: s for s in load_skills(repo_root)}
    assert "ticket-authoring-guide" in skills
    s = skills["ticket-authoring-guide"]
    assert s.domain == "meta"
    assert s.version != "0.0.0"
    assert s.owners


def test_write_and_refine_ticket_commands_exist(repo_root):
    commands = {c.id: c for c in load_commands(repo_root)}
    assert "write-ticket" in commands
    assert "refine-ticket" in commands
    for c in (commands["write-ticket"], commands["refine-ticket"]):
        assert c.raw_frontmatter.get("triggers_agents")
        assert c.version != "0.0.0"


def test_ticket_refiner_agent_exists(repo_root):
    agents = {a.id: a for a in load_agents(repo_root)}
    assert "ticket-refiner" in agents
    a = agents["ticket-refiner"]
    assert a.scope == ["agent:architect"]
    assert a.foundational is False


# --- security score --------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "canonical/skills/meta/ticket-authoring-guide.md",
    "canonical/commands/write-ticket.md",
    "canonical/commands/refine-ticket.md",
    "canonical/agents/ticket-refiner.md",
])
def test_new_artifacts_score_at_least_95(repo_root, rel):
    result = score_file(repo_root / rel, repo_root)
    assert result.final >= 95, result.findings


# --- cross-references actually resolve --------------------------------------

def test_refine_ticket_triggers_agents_includes_ticket_refiner(repo_root):
    """`forge validate` checks that every triggers_agents entry resolves to a
    real agent — this pins the specific reference that matters here."""
    commands = {c.id: c for c in load_commands(repo_root)}
    assert "ticket-refiner" in commands["refine-ticket"].raw_frontmatter["triggers_agents"]


def test_skill_cross_references_point_at_real_files(repo_root):
    guide = repo_root / "canonical" / "skills" / "meta" / "ticket-authoring-guide.md"
    for rel in (
        "../../policies/ticketing-contract.md",
        "../../policies/definition-of-done.md",
        "../../policies/review-protocol.md",
        "../../agents/architect.md",
        "../../commands/write-ticket.md",
        "../../commands/refine-ticket.md",
        "../frappe-core/whitelist-api-patterns.md",
    ):
        target = (guide.parent / rel).resolve()
        assert target.is_file(), f"{rel} referenced but does not exist"


# --- the gap loop and ownership guard are actually documented ---------------

def test_write_ticket_documents_the_ownership_guard(repo_root):
    body = (repo_root / "canonical" / "commands" / "write-ticket.md").read_text()
    assert "owner_of_app" in body or "is_foreign" in body
    assert "Nothing is ever written into the foreign app" in body


def test_write_ticket_documents_the_gap_flow(repo_root):
    body = (repo_root / "canonical" / "commands" / "write-ticket.md").read_text()
    assert "--gap-of" in body
    assert "LEDGER-proposed.md" in body
    assert "never expands" in body.lower() or "never touches it again" in body.lower()


def test_refine_ticket_never_touches_status(repo_root):
    body = (repo_root / "canonical" / "commands" / "refine-ticket.md").read_text()
    assert "never changes `status:`" in body


def test_ticket_refiner_cites_a_real_standing_finding(repo_root):
    """The plan called for citing concrete, verified anti-pattern findings —
    not hypothetical examples. This pins one of them."""
    body = (repo_root / "canonical" / "agents" / "ticket-refiner.md").read_text()
    assert "loan_custom.py" in body, (
        "must cite the real sql_fstring finding in "
        "noviznaerp_payroll/custom/loan_custom.py, not a hypothetical example"
    )


# --- forge validate stays clean ---------------------------------------------

def test_forge_validate_has_no_new_issues(repo_root, bench_env):
    """Rendering must not blow up now that an agent (ticket-refiner) has no
    dedicated skills of its own beyond the shared ticket-authoring-guide."""
    tgt = load_target(repo_root, "bench")
    # Rendering claude-code exercises the full agent/command/skill pipeline;
    # a broken cross-reference or malformed frontmatter raises here.
    rendered = render(repo_root, "claude-code", tgt)
    ids = {a.artifact_id for a in rendered}
    assert "ticket-refiner" in ids
    assert "write-ticket" in ids
    assert "refine-ticket" in ids


# --- char budget -------------------------------------------------------------

@pytest.mark.parametrize("tool", ["cursor", "cline", "copilot", "codex", "antigravity"])
def test_char_budget_still_holds(repo_root, bench_env, tool):
    from forge.loader import load_adapter_config

    budget = load_adapter_config(repo_root, tool)["limits"]["max_total_chars"]
    tgt = load_target(repo_root, "bench")
    for a in render(repo_root, tool, tgt):
        if a.artifact_kind == "aggregate":
            assert len(a.content) <= budget, (
                f"{tool}/{a.output_path.name} is {len(a.content)} chars, "
                f"over its {budget} budget"
            )
