"""Tests for forge.commit_helper — scoped Conventional Commits."""

from __future__ import annotations

from forge.commit_helper import (
    check_message,
    infer_scope_from_paths,
    infer_type_from_body,
    propose,
)


def test_scope_inference_single_dir():
    paths = [
        "canonical/skills/data/sql-best-practices.md",
        "canonical/skills/data/mariadb-debugging.md",
    ]
    assert infer_scope_from_paths(paths) == "skills"


def test_scope_inference_forge_dir():
    assert infer_scope_from_paths(["forge/src/forge/loader.py"]) == "forge"


def test_scope_inference_mixed_returns_scaffold():
    paths = [
        "canonical/skills/data/x.md",
        "canonical/agents/architect.md",
        "forge/src/forge/loader.py",
        "adapters/cursor/adapter.yaml",
    ]
    # No single scope dominates → "scaffold"
    assert infer_scope_from_paths(paths) == "scaffold"


def test_scope_inference_empty_returns_scaffold():
    assert infer_scope_from_paths([]) == "scaffold"


def test_scope_inference_60pct_threshold():
    # 3 of 5 → 60% → dominant scope wins
    paths = [
        "canonical/skills/a.md",
        "canonical/skills/b.md",
        "canonical/skills/c.md",
        "forge/x.py",
        "adapters/y.yaml",
    ]
    assert infer_scope_from_paths(paths) == "skills"


def test_type_inference_fix():
    assert infer_type_from_body("Fix the migration bug in loan_custom") == "fix"


def test_type_inference_refactor():
    assert infer_type_from_body("Refactor the sync engine to use staging") == "refactor"


def test_type_inference_docs():
    assert infer_type_from_body("Update the README with new install steps") == "docs"


def test_type_inference_default_feat():
    assert infer_type_from_body("Add Pipedrive integration") == "feat"


def test_type_inference_no_body_is_chore():
    assert infer_type_from_body(None) == "chore"
    assert infer_type_from_body("") == "chore"


def test_check_message_valid(repo_root):
    msg = "feat(skills): add pipedrive integration\n\nDetails here."
    result = check_message(msg, repo_root)
    assert result.ok, result.issues
    assert result.message_first_line == "feat(skills): add pipedrive integration"


def test_check_message_rejects_unconventional(repo_root):
    msg = "added pipedrive\n"
    result = check_message(msg, repo_root)
    assert not result.ok
    assert any("Conventional Commits" in i for i in result.issues)


def test_check_message_rejects_unknown_type(repo_root):
    msg = "spam(skills): doing something weird\n"
    result = check_message(msg, repo_root)
    # 'spam' isn't in the conventional regex → fails at the regex step
    assert not result.ok


def test_check_message_rejects_unknown_scope(repo_root):
    msg = "feat(this-scope-does-not-exist): some change\n"
    result = check_message(msg, repo_root)
    assert not result.ok
    assert any("commits.scopes" in i for i in result.issues)


def test_check_message_warns_long_subject(repo_root):
    long_subj = "feat(forge): " + ("x" * 100)
    result = check_message(long_subj, repo_root)
    assert not result.ok
    assert any("chars" in i for i in result.issues)


def test_check_message_ignores_comment_lines(repo_root):
    msg = "# Please enter the commit message...\nfeat(forge): real subject\n"
    result = check_message(msg, repo_root)
    assert result.ok
    assert result.message_first_line == "feat(forge): real subject"


def test_propose_with_body(repo_root):
    proposal = propose(
        "Add Pipedrive integration\n\nLong body here describing details.",
        repo_root=repo_root,
    )
    # No files are staged in test, so scope falls to "scaffold"
    assert proposal.scope in {"scaffold", "docs"}
    assert proposal.subject == "Add Pipedrive integration"
    assert proposal.body == "Long body here describing details."
    rendered = proposal.render()
    assert "Add Pipedrive integration" in rendered
