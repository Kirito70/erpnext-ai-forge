"""Security scoring engine.

Reads canonical/policies/security-scoring.yaml, applies the deduction table
to a canonical artifact (or any text file), returns a score + list of findings.

Phase 2 baseline: regex-based pattern matching. Phase 4 will add AST-aware
checks for Python files and improve the YAML rule set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.loader import find_repo_root, load_security_scoring_yaml


@dataclass
class Finding:
    deduction_id: str
    severity: str           # CRITICAL | HIGH | MEDIUM | LOW
    deduction: int
    location: str           # file:line or "frontmatter"
    snippet: str            # 100-char preview


@dataclass
class ScoreResult:
    path: Path
    initial: int
    final: int
    findings: list[Finding]

    @property
    def passed_auto_accept(self) -> bool:
        return self.final >= 95

    @property
    def passed_warn(self) -> bool:
        return self.final >= 80

    @property
    def blocked(self) -> bool:
        return self.final < 80


# ---------------------------------------------------------------------------
# Pattern compilers
# ---------------------------------------------------------------------------
# These patterns mirror the deduction table in canonical/policies/security-scoring.yaml.
# When the YAML table evolves, update this map in lockstep.
#
# `applies_to_extensions`: restrict the rule to specific file suffixes. Code-pattern
# rules (SQL injection, allow_guest, ignore_permissions) should only fire on .py
# files — they appear in Markdown skills as pedagogical examples ("Don't do this")
# inside code fences, and firing on those would block our own teaching content.
_DEDUCTION_PATTERNS: dict[str, dict[str, Any]] = {
    "D-EDIT-UPSTREAM": {
        "regex": re.compile(
            r"\bapps/(frappe|erpnext|crm|hrms|lending|lms|education|helpdesk|gameplan|drive|press)/",
        ),
        "severity": "CRITICAL",
        "deduction": 50,
        # Canonical/discovery/adapters/docs all discuss upstream apps by name as
        # documentation; only fire when the path string appears in code or config.
        "applies_to_extensions": {".py", ".yaml", ".yml", ".json", ".sh"},
        "skip_if_path_matches": re.compile(r"(canonical|discovery|adapters|docs)"),
    },
    "D-READ-SITE-CONFIG": {
        "regex": re.compile(
            r"(read|open|cat|json\.load).*?site_config\.json",
            re.IGNORECASE,
        ),
        "severity": "CRITICAL",
        "deduction": 50,
        "applies_to_extensions": {".py", ".sh"},
        "skip_if_path_matches": re.compile(r"(canonical|discovery|docs|tests/)"),
    },
    "D-CURL-SHELL": {
        # Catches the dangerous shell pattern. Documentation that names the
        # deduction (security-reviewer.md, review-checklist.md, the YAML rule
        # table itself) is exempt; everywhere else fires regardless of extension.
        "regex": re.compile(r"(curl|wget)[^\n]+\|\s*(sh|bash)"),
        "severity": "CRITICAL",
        "deduction": 50,
        "skip_if_path_matches": re.compile(r"(canonical|docs)"),
    },
    "D-DANGEROUS-SKIP-PERMS": {
        # Skip canonical/ entirely — policies and agents reference the deduction
        # id by name, which contains the literal string we're matching on.
        "regex": re.compile(r"dangerously-skip-permissions"),
        "severity": "HIGH",
        "deduction": 40,
        "skip_if_path_matches": re.compile(r"(canonical|docs)"),
    },
    "D-SQL-FSTRING": {
        "regex": re.compile(r"frappe\.db\.sql\(\s*f['\"]"),
        "severity": "HIGH",
        "deduction": 30,
        "applies_to_extensions": {".py"},
    },
    "D-IGNORE-PERMISSIONS-NO-JUSTIFY": {
        # Heuristic: ignore_permissions=True with no #/justification comment on the same line.
        "regex": re.compile(r"ignore_permissions\s*=\s*True(?![^\n]*#[^\n]+)"),
        "severity": "HIGH",
        "deduction": 20,
        "applies_to_extensions": {".py"},
    },
    "D-GUEST-WHITELIST-NO-RATE-LIMIT": {
        "regex": re.compile(r"@frappe\.whitelist\(\s*[^)]*allow_guest\s*=\s*True"),
        "severity": "HIGH",
        "deduction": 25,
        "applies_to_extensions": {".py"},
    },
}


def _load_rules(repo_root: Path) -> dict[str, Any]:
    """Load the YAML rule set (used for threshold lookup; pattern definitions
    are mirrored in code above for performance)."""
    return load_security_scoring_yaml(repo_root)


def score_file(path: Path, repo_root: Path | None = None) -> ScoreResult:
    """Score a single file. Returns a ScoreResult with findings."""
    repo_root = repo_root or find_repo_root(path)
    rules = _load_rules(repo_root)
    initial = int(rules.get("starting_score", 100))
    text = path.read_text(errors="replace")
    # For path-based skip matching, only consider the repo-relative path. If the
    # file lives outside the repo (e.g., pytest tmpdir), use only the basename so
    # transient ancestor dir names ("pytest-of-...", "test_X_0") can't match.
    if path.is_relative_to(repo_root):
        rel_path = str(path.relative_to(repo_root))
    else:
        rel_path = path.name

    findings: list[Finding] = []
    score = initial

    for rule_id, spec in _DEDUCTION_PATTERNS.items():
        # Extension filter (e.g., SQL-FSTRING rule only applies to .py files)
        ext_filter = spec.get("applies_to_extensions")
        if ext_filter and path.suffix not in ext_filter:
            continue
        skip = spec.get("skip_if_path_matches")
        if skip and skip.search(rel_path):
            continue
        for match in spec["regex"].finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            snippet = text[match.start(): match.end() + 60].replace("\n", " ")[:100]
            findings.append(
                Finding(
                    deduction_id=rule_id,
                    severity=spec["severity"],
                    deduction=spec["deduction"],
                    location=f"{rel_path}:{line_no}",
                    snippet=snippet,
                )
            )
            score -= int(spec["deduction"])

    score = max(0, score)
    return ScoreResult(path=path, initial=initial, final=score, findings=findings)


def score_path(target: Path, repo_root: Path | None = None) -> list[ScoreResult]:
    """Score a file or every relevant file under a directory."""
    repo_root = repo_root or find_repo_root(target)
    results: list[ScoreResult] = []
    if target.is_file():
        results.append(score_file(target, repo_root))
    else:
        for ext in ("*.md", "*.yaml", "*.yml", "*.py", "*.j2"):
            for path in target.rglob(ext):
                if "__pycache__" in str(path):
                    continue
                results.append(score_file(path, repo_root))
    return results


def render_score_report(results: list[ScoreResult], fail_below: int) -> tuple[str, int]:
    """Render a brief text report; return (report, exit_code).

    exit_code = 1 if any file is below fail_below."""
    lines: list[str] = []
    lowest = 100
    failed_files: list[ScoreResult] = []
    for r in results:
        lowest = min(lowest, r.final)
        marker = "✓" if r.final >= 95 else "!" if r.final >= 80 else "✗"
        rel = r.path.name
        if r.findings:
            lines.append(f"{marker} {r.final:>3} — {rel} ({len(r.findings)} finding{'s' if len(r.findings) != 1 else ''})")
            for f in r.findings:
                lines.append(f"      [{f.severity}] {f.deduction_id} at {f.location}")
        else:
            lines.append(f"{marker} {r.final:>3} — {rel}")
        if r.final < fail_below:
            failed_files.append(r)

    summary = f"\nLowest score: {lowest}. Failed (<{fail_below}): {len(failed_files)} file(s)."
    return "\n".join(lines) + summary, (1 if failed_files else 0)
