"""PHASE-6: /ticket-review DoD gate, risk-tiered lanes, gap loop, ownership guard.

Covers the acceptance criteria drafted in docs/tickets/PHASE-6.md.
"""

from __future__ import annotations

import pathlib

import click
import pytest

from forge.commands.validate import run as validate_run
from forge.loader import load_agents, load_commands, load_forge_config, load_targets
from forge.render import render
from forge.scoring import score_file


@pytest.fixture
def bench_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_BENCH_PATH", str(tmp_path / "bench"))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "ci-site")
    (tmp_path / "bench" / "apps").mkdir(parents=True)
    return tmp_path / "bench"


# --- artifacts exist --------------------------------------------------------

def test_ticket_review_and_gap_ticket_commands_exist(repo_root):
    commands = {c.id: c for c in load_commands(repo_root)}
    assert "ticket-review" in commands
    assert "gap-ticket" in commands


def test_two_new_reviewer_agents_exist(repo_root):
    agents = {a.id: a for a in load_agents(repo_root)}
    assert "code-reviewer" in agents
    assert "frappe-framework-reviewer" in agents
    for a in (agents["code-reviewer"], agents["frappe-framework-reviewer"]):
        assert a.raw_frontmatter.get("review_only") is True
        assert a.raw_frontmatter.get("tools")


@pytest.mark.parametrize("rel", [
    "canonical/commands/ticket-review.md",
    "canonical/commands/gap-ticket.md",
    "canonical/agents/code-reviewer.md",
    "canonical/agents/frappe-framework-reviewer.md",
])
def test_new_artifacts_score_at_least_95(repo_root, rel):
    result = score_file(pathlib.Path(repo_root) / rel, repo_root)
    assert result.final >= 95, result.findings


# --- reviewer tools are actually read-only ----------------------------------

@pytest.mark.parametrize("agent_id", ["security-reviewer", "code-reviewer", "frappe-framework-reviewer"])
def test_review_only_agents_have_no_write_tools(repo_root, agent_id):
    agents = {a.id: a for a in load_agents(repo_root)}
    a = agents[agent_id]
    assert a.raw_frontmatter.get("review_only") is True
    tools = set(a.raw_frontmatter.get("tools") or [])
    assert tools, f"{agent_id} must declare tools:"
    assert not tools & {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def test_qa_test_engineer_is_not_review_only(repo_root):
    """qa-test-engineer WRITES test files as its primary output — restricting
    it to read-only tools would break its actual job. Only agents whose output
    is purely a review get the restriction."""
    agents = {a.id: a for a in load_agents(repo_root)}
    assert not agents["qa-test-engineer"].raw_frontmatter.get("review_only")


def test_frontend_specialists_keep_full_tools(repo_root):
    """They are producers with a documented review-MODE convention (gated by
    invocation context), not a frontmatter tools: restriction — restricting
    their frontmatter would break their normal producer role in the same file."""
    agents = {a.id: a for a in load_agents(repo_root)}
    for aid in ("frontend-frappe-ui-specialist", "frontend-quasar-specialist"):
        assert not agents[aid].raw_frontmatter.get("review_only")
        body = agents[aid].body
        assert "## Review Mode" in body
        assert "read-only" in body.lower()


# --- validate: review_only + tools invariant --------------------------------

def test_validate_fails_when_review_only_has_no_tools(repo_root, bench_env, monkeypatch, capsys):
    """The actual failure mode this check prevents: a reviewer agent silently
    gaining write access because nobody restricted its tools."""
    from forge import loader as loader_mod

    orig = loader_mod.load_agents

    def _patched(root):
        agents = orig(root)
        for a in agents:
            if a.id == "code-reviewer":
                a.raw_frontmatter = {**a.raw_frontmatter, "tools": None}
        return agents

    monkeypatch.setattr("forge.commands.validate.load_agents", _patched)
    with pytest.raises(click.exceptions.Exit):
        validate_run(path=None, check_drift=False)
    out = capsys.readouterr().out
    assert "review_only: true but no `tools:`" in out


def test_validate_fails_when_review_only_has_write(repo_root, bench_env, monkeypatch, capsys):
    from forge import loader as loader_mod

    orig = loader_mod.load_agents

    def _patched(root):
        agents = orig(root)
        for a in agents:
            if a.id == "code-reviewer":
                a.raw_frontmatter = {**a.raw_frontmatter, "tools": ["Read", "Write"]}
        return agents

    monkeypatch.setattr("forge.commands.validate.load_agents", _patched)
    with pytest.raises(click.exceptions.Exit):
        validate_run(path=None, check_drift=False)
    out = " ".join(capsys.readouterr().out.split())
    assert "includes a write capability" in out


# --- validate: scaffold ownership guard -------------------------------------

def test_validate_flags_scaffold_under_upstream_app(repo_root, bench_env):
    apps_dir = bench_env / "apps" / "frappe" / "docs" / "harness"
    apps_dir.mkdir(parents=True)
    with pytest.raises(click.exceptions.Exit):
        validate_run(path=None, check_drift=False)


def test_validate_clean_with_no_per_app_scaffolds(repo_root, bench_env):
    """The common case today: per-app ledger mirrors are not built, so no
    app directory under a target has a docs/harness/ scaffold at all."""
    validate_run(path=None, check_drift=False)  # must not raise


# --- documentation: risk tiers, gap loop, ownership -------------------------

def test_review_protocol_documents_risk_tiers(repo_root):
    body = (repo_root / "canonical" / "policies" / "review-protocol.md").read_text()
    assert "## 7. Risk-Tiered Lane Selection" in body
    assert "project-pattern" in body and "framework" in body
    assert "Escalate, never de-escalate" in body


def test_ticket_review_never_reruns_gates_per_lane(repo_root):
    body = (repo_root / "canonical" / "commands" / "ticket-review.md").read_text()
    assert "run the gates once" in body.lower()


def test_ticket_review_is_not_a_stop_hook(repo_root):
    body = (repo_root / "canonical" / "commands" / "ticket-review.md").read_text()
    assert "not** wired to any Stop hook" in body


def test_gap_ticket_never_expands_the_parent(repo_root):
    body = (repo_root / "canonical" / "commands" / "gap-ticket.md").read_text()
    assert "never** as an expansion" in body


def test_gap_ticket_documents_the_ownership_guard(repo_root):
    body = (repo_root / "canonical" / "commands" / "gap-ticket.md").read_text()
    assert "Nothing is ever written into the foreign app" in body


# --- rendering still works end-to-end ---------------------------------------

def test_forge_renders_the_new_reviewer_pipeline(repo_root, bench_env):
    tgt = load_targets(repo_root, load_forge_config(repo_root))["bench"]
    rendered = render(repo_root, "claude-code", tgt)
    ids = {a.artifact_id for a in rendered}
    for expected in ("code-reviewer", "frappe-framework-reviewer", "ticket-review", "gap-ticket"):
        assert expected in ids


@pytest.mark.parametrize("tool", ["cursor", "cline", "copilot", "codex", "antigravity"])
def test_char_budget_still_holds(repo_root, bench_env, tool):
    from forge.loader import load_adapter_config

    budget = load_adapter_config(repo_root, tool)["limits"]["max_total_chars"]
    tgt = load_targets(repo_root, load_forge_config(repo_root))["bench"]
    for a in render(repo_root, tool, tgt):
        if a.artifact_kind == "aggregate":
            assert len(a.content) <= budget, (
                f"{tool}/{a.output_path.name} is {len(a.content)} chars, "
                f"over its {budget} budget"
            )
