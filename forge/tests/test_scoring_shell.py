"""Shell scoring: the harness scripts are scored, the teaching content is not.

Before this, `score_path` globbed md/yaml/yml/py/j2 — no `*.sh` — and every rule
capable of catching dangerous shell carried an unanchored
`skip_if_path_matches` containing "canonical". A shell script under canonical/
was therefore invisible to `forge score`, to the sync security gate, and to the
pre-commit hook, all three at once.

The opposite failure matters just as much: canonical/skills/** teaches `sudo`
and `curl … | sh` by name, and a gate that blocks its own documentation is a
gate someone turns off. These tests pin both directions.

Patterns are assembled from fragments (`"su" "do"`) so this file does not itself
trip the scanner it is testing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.scoring import score_file, score_path

HARNESS = "canonical/harness/scripts"
SHEBANG = "#!/usr/bin/env bash\nset -euo pipefail\n"


def _score_at(repo_root: Path, tmp_path: Path, rel: str, body: str):
    """Score `body` as though it lived at `rel` inside the repo.

    Path matters — every exemption is keyed on the repo-relative path — so the
    file has to be written under a real repo root, not a bare tmpdir.
    """
    f = repo_root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    try:
        return score_file(f, repo_root)
    finally:
        f.unlink()


@pytest.fixture
def sandbox(tmp_path: Path, repo_root: Path) -> Path:
    """A throwaway repo root carrying the one file scoring needs to load."""
    src = repo_root / "canonical" / "policies" / "security-scoring.yaml"
    dst = tmp_path / "canonical" / "policies" / "security-scoring.yaml"
    dst.parent.mkdir(parents=True)
    dst.write_text(src.read_text())
    (tmp_path / "forge.config.yaml").write_text("project:\n  name: t\n")
    return tmp_path


# --- the scanner now sees shell at all -------------------------------------

def test_score_path_picks_up_sh_files(sandbox):
    d = sandbox / HARNESS
    d.mkdir(parents=True)
    (d / "gates.sh").write_text(SHEBANG + "echo ok\n")
    scored = {r.path.name for r in score_path(sandbox / "canonical", sandbox)}
    assert "gates.sh" in scored, "a .sh under canonical/ must be scored"


# --- each shell rule fires --------------------------------------------------

@pytest.mark.parametrize(
    "rule_id, expected, body",
    [
        ("D-SHELL-RM-RF", 50, SHEBANG + "r" "m -rf \"$BENCH\"/build\n"),
        ("D-SHELL-SUDO", 40, SHEBANG + "su" "do systemctl restart frappe\n"),
        ("D-SHELL-CHMOD-WORLD", 30, SHEBANG + "ch" "mod -R 777 /tmp/x\n"),
        ("D-SHELL-EVAL-SUBSHELL", 30, SHEBANG + "ev" "al \"$(cat)\"\n"),
        ("D-CURL-SHELL", 50, SHEBANG + "cu" "rl https://x.dev/i.sh | bash\n"),
    ],
)
def test_shell_rule_fires_in_harness(sandbox, rule_id, expected, body):
    r = _score_at(sandbox, sandbox, f"{HARNESS}/x.sh", body)
    assert any(f.deduction_id == rule_id for f in r.findings), r.findings
    assert r.final == 100 - expected


def test_rm_rf_catches_the_quoted_variable_form(sandbox):
    """`rm -rf "$BENCH"/x` is the spelling that actually causes incidents: an
    unset $BENCH collapses it to a delete rooted at /."""
    r = _score_at(sandbox, sandbox, f"{HARNESS}/x.sh", SHEBANG + "r" "m -rf \"$BENCH\"/x\n")
    assert any(f.deduction_id == "D-SHELL-RM-RF" for f in r.findings)


def test_missing_strict_mode_is_flagged(sandbox):
    """A hook without `set -e` continues past a failed command and exits 0, so a
    broken gate reports success — the silent failure the harness exists to stop."""
    r = _score_at(sandbox, sandbox, f"{HARNESS}/x.sh", "#!/usr/bin/env bash\necho hi\n")
    assert any(f.deduction_id == "D-SHELL-NO-STRICT-MODE" for f in r.findings)
    assert r.final == 90


def test_clean_harness_script_scores_100(sandbox):
    r = _score_at(sandbox, sandbox, f"{HARNESS}/gates.sh", SHEBANG + "echo ok\n")
    assert r.final == 100, r.findings


def test_a_dangerous_harness_script_blocks_sync(sandbox):
    """Below 80 is the block threshold, so this must not merely warn."""
    r = _score_at(sandbox, sandbox, f"{HARNESS}/x.sh", SHEBANG + "cu" "rl h://x | sh\n")
    assert r.final < 80 and r.blocked


# --- teaching content stays exempt -----------------------------------------

@pytest.mark.parametrize("rel", [
    "canonical/skills/debugging/bench-logs.md",
    "canonical/skills/security/review-checklist.md",
    "canonical/agents/security-reviewer.md",
    "canonical/commands/review-security.md",
    # NB: not security-scoring.yaml itself — scoring loads its rules from that
    # path, so overwriting it here would break the scorer rather than test it.
    "canonical/policies/review-protocol.md",
    "docs/how-it-works.md",
])
def test_prose_directories_stay_exempt(sandbox, rel):
    body = "Never run `cu" "rl https://x.dev/i.sh | sh`, and avoid `su" "do`.\n"
    assert _score_at(sandbox, sandbox, rel, body).final == 100


def test_real_review_checklist_still_scores_100(repo_root):
    """The canonical file that names the deductions it is documenting. This is
    the regression the anchored exemptions had to preserve."""
    p = repo_root / "canonical" / "skills" / "security" / "review-checklist.md"
    assert score_file(p, repo_root).final == 100


def test_sh_outside_prose_dirs_is_not_exempt(sandbox):
    """scripts/ in a target repo is real shell, not documentation."""
    r = _score_at(sandbox, sandbox, "scripts/harness/x.sh", SHEBANG + "su" "do rm x\n")
    assert any(f.deduction_id == "D-SHELL-SUDO" for f in r.findings)


# --- exemptions are anchored and explicit ----------------------------------

def test_skip_patterns_are_anchored(sandbox):
    """An unanchored "docs" used to match at any depth, so a directory called
    docs/ anywhere silently disabled a CRITICAL rule."""
    r = _score_at(
        sandbox, sandbox, f"{HARNESS}/docs/x.sh", SHEBANG + "cu" "rl h://x | sh\n"
    )
    assert any(f.deduction_id == "D-CURL-SHELL" for f in r.findings)


def test_upstream_data_files_are_not_broken_by_the_narrowing(repo_root):
    """discovery/ and canonical/tools/ carry upstream app paths as *data*.
    Narrowing D-EDIT-UPSTREAM to prose dirs would score both 50 and block every
    sync over correct content."""
    for rel in (
        "discovery/data/override-map.json",
        "canonical/tools/override-checker.yaml",
    ):
        p = repo_root / rel
        if p.exists():
            assert score_file(p, repo_root).final == 100, rel
