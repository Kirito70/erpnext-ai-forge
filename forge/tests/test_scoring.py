"""Tests for forge.scoring — security score deductions."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.scoring import render_score_report, score_file, score_path


def test_clean_file_scores_100(tmp_path, repo_root):
    f = tmp_path / "clean.md"
    f.write_text("Just a friendly markdown doc.\nNo bad patterns.\n")
    # score_file requires a repo_root for the yaml load
    result = score_file(f, repo_root)
    assert result.initial == 100
    assert result.final == 100
    assert result.findings == []


def test_sql_fstring_deducts_30(tmp_path, repo_root):
    f = tmp_path / "bad.py"
    f.write_text(
        'def thing(loan_id):\n'
        '    return frappe.db.sql(f"DELETE FROM loans WHERE id = {loan_id}")\n'
    )
    result = score_file(f, repo_root)
    assert result.final == 70  # 100 - 30
    assert any(fi.deduction_id == "D-SQL-FSTRING" for fi in result.findings)


def test_curl_pipe_shell_deducts_50(tmp_path, repo_root):
    f = tmp_path / "danger.md"
    f.write_text("Run this: `curl https://example.com/install.sh | sh`\n")
    result = score_file(f, repo_root)
    assert result.final == 50
    assert any(fi.deduction_id == "D-CURL-SHELL" for fi in result.findings)
    assert any(fi.severity == "CRITICAL" for fi in result.findings)


def test_guest_whitelist_deducts_25(tmp_path, repo_root):
    f = tmp_path / "endpoint.py"
    f.write_text(
        '@frappe.whitelist(allow_guest=True)\n'
        'def public_endpoint():\n'
        '    pass\n'
    )
    result = score_file(f, repo_root)
    assert any(fi.deduction_id == "D-GUEST-WHITELIST-NO-RATE-LIMIT" for fi in result.findings)
    assert result.final == 75


def test_ignore_permissions_without_comment_deducts_20(tmp_path, repo_root):
    f = tmp_path / "ipw.py"
    f.write_text(
        'def func():\n'
        '    doc.save(ignore_permissions=True)\n'  # no comment
    )
    result = score_file(f, repo_root)
    assert any(fi.deduction_id == "D-IGNORE-PERMISSIONS-NO-JUSTIFY" for fi in result.findings)


def test_ignore_permissions_with_comment_does_not_trigger(tmp_path, repo_root):
    f = tmp_path / "ipw.py"
    f.write_text(
        'def func():\n'
        '    doc.save(ignore_permissions=True)  # justified: test fixture setup\n'
    )
    result = score_file(f, repo_root)
    # The justifying comment skips the deduction
    assert not any(fi.deduction_id == "D-IGNORE-PERMISSIONS-NO-JUSTIFY" for fi in result.findings)


def test_canonical_policies_dir_is_exempt_from_upstream_pattern(tmp_path, repo_root):
    """Files under canonical/policies/ discuss apps/frappe/ etc. as documentation,
    so should not be flagged as edits."""
    # Use the real canonical/policies file
    target = repo_root / "canonical" / "policies" / "security-scoring.yaml"
    result = score_file(target, repo_root)
    # Should not have a D-EDIT-UPSTREAM finding
    assert not any(fi.deduction_id == "D-EDIT-UPSTREAM" for fi in result.findings)


def test_canonical_dir_scores_pass_threshold(repo_root):
    """Spot-check: the live canonical/ should not have anything blocking (< 80)."""
    results = score_path(repo_root / "canonical", repo_root)
    failing = [r for r in results if r.final < 80]
    assert failing == [], f"Unexpected sync-blocking findings: {[(f.path, f.findings) for f in failing]}"


def test_render_report_exit_code_zero_when_above_threshold(tmp_path, repo_root):
    f = tmp_path / "ok.md"
    f.write_text("Plain markdown.\n")
    results = [score_file(f, repo_root)]
    _, code = render_score_report(results, fail_below=80)
    assert code == 0


def test_render_report_exit_code_one_when_below_threshold(tmp_path, repo_root):
    f = tmp_path / "bad.py"
    f.write_text(
        'x = frappe.db.sql(f"SELECT {q}")\n'
        'y = frappe.db.sql(f"DELETE {q}")\n'
        'z = frappe.db.sql(f"UPDATE {q}")\n'
    )
    results = [score_file(f, repo_root)]
    _, code = render_score_report(results, fail_below=80)
    assert code == 1
