"""Scoped Conventional Commits helper.

Reads `forge.config.yaml` `commits.scopes` + `commits.types` and infers the
scope of a proposed commit from the set of git-staged file paths. Two modes:

  - `propose(body)` → returns a suggested message in
        `<type>(<scope>): <subject>`
    form, using inferred scope and a type guessed from the body. The caller
    can edit/confirm before running `git commit -m`.

  - `check(message)` → validates an existing commit message string against
    the convention (used by the `commit-msg` git hook).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from forge.loader import find_repo_root, load_forge_config


# Map from path prefix → scope. The first matching prefix wins.
# Order matters: more-specific prefixes first.
_PATH_SCOPE_RULES: list[tuple[str, str]] = [
    ("canonical/agents/", "agents"),
    ("canonical/skills/", "skills"),
    ("canonical/commands/", "commands"),
    ("canonical/tools/", "tools"),
    ("canonical/policies/", "policies"),
    ("adapters/", "adapters"),
    ("forge/", "forge"),
    ("discovery/", "discovery"),
    ("audit/", "audit"),
    (".github/", "ci"),
    ("docs/", "docs"),
]


_CONVENTIONAL_RE = re.compile(
    r"^(?P<type>feat|fix|refactor|chore|docs|test|perf|ci)"
    r"\((?P<scope>[a-z0-9_/-]+)\)"
    r":\s+(?P<subject>.+)"
)


@dataclass
class CommitProposal:
    type: str           # feat / fix / refactor / chore / docs / test / perf / ci
    scope: str          # single scope; "scaffold" for multi-scope/root changes
    subject: str        # one-line summary
    body: str | None    # optional multi-line body

    def render(self) -> str:
        first = f"{self.type}({self.scope}): {self.subject}"
        if self.body:
            return f"{first}\n\n{self.body}"
        return first


@dataclass
class CommitCheckResult:
    ok: bool
    message_first_line: str
    issues: list[str]


# ---------------------------------------------------------------------------
# Scope inference
# ---------------------------------------------------------------------------
def staged_files(repo_root: Path) -> list[str]:
    """Return list of staged paths relative to the repo root (added/modified/renamed)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []


def infer_scope_from_paths(paths: Iterable[str]) -> str:
    """Map staged paths to a single scope.

    Returns the dominant scope (the one with the most staged files). If
    multiple scopes are touched in roughly equal measure, returns "scaffold"
    to signal a cross-cutting change.
    """
    counts: dict[str, int] = {}
    for path in paths:
        for prefix, scope in _PATH_SCOPE_RULES:
            if path.startswith(prefix):
                counts[scope] = counts.get(scope, 0) + 1
                break
        else:
            counts["docs"] = counts.get("docs", 0) + 1  # root-level files default to docs

    if not counts:
        return "scaffold"

    # Sort by count desc; if the leader has > 60% share, use it; else "scaffold"
    total = sum(counts.values())
    leader, leader_count = max(counts.items(), key=lambda kv: kv[1])
    if leader_count / total >= 0.6:
        return leader
    return "scaffold"


# ---------------------------------------------------------------------------
# Type inference (heuristic)
# ---------------------------------------------------------------------------
def infer_type_from_body(body: str | None) -> str:
    """Guess `feat` / `fix` / `refactor` / `docs` / `test` / `chore` from body text."""
    if not body:
        return "chore"
    lower = body.lower()
    # Order matters — more specific keywords first.
    if any(word in lower for word in ("fix ", "fixes ", "bug", "regression")):
        return "fix"
    if any(word in lower for word in ("refactor", "rename", "restructure")):
        return "refactor"
    # Docs operations: README / CHANGELOG / documentation are strong signals
    # regardless of other verbs in the same sentence.
    if any(word in lower for word in ("readme", "changelog", "documentation", "docstring")):
        return "docs"
    if any(word in lower for word in ("test ", "tests ", "coverage", "pytest")):
        if "feat" not in lower and "add " not in lower:
            return "test"
    if any(word in lower for word in ("perf ", "performance", "optimize", "speed up")):
        return "perf"
    if "scaffold" in lower or "skeleton" in lower or "initial " in lower:
        return "chore"
    return "feat"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def propose(body: str | None, repo_root: Path | None = None) -> CommitProposal:
    """Build a commit proposal from staged files + body text.

    The first non-empty line of `body` becomes the subject; the rest becomes
    the body. Both type and scope are inferred; the caller is expected to
    review and edit before committing.
    """
    repo_root = repo_root or find_repo_root()
    paths = staged_files(repo_root)
    scope = infer_scope_from_paths(paths)
    commit_type = infer_type_from_body(body)

    if not body:
        subject = "(no body provided — describe the change)"
        extended_body: str | None = None
    else:
        lines = [line for line in body.splitlines() if line.strip()]
        subject = lines[0] if lines else "(empty body)"
        rest = "\n".join(lines[1:]).strip()
        extended_body = rest if rest else None

    return CommitProposal(
        type=commit_type, scope=scope, subject=subject, body=extended_body
    )


def check_message(message: str, repo_root: Path | None = None) -> CommitCheckResult:
    """Validate a commit message string against the Conventional Commits format.

    Used by the commit-msg git hook. `message` is typically the contents of
    `.git/COMMIT_EDITMSG`.
    """
    repo_root = repo_root or find_repo_root()
    cfg = load_forge_config(repo_root).get("commits", {})
    allowed_scopes = set(cfg.get("scopes", []))
    allowed_types = set(cfg.get("types", []))

    # First non-comment, non-empty line is the subject line
    first_line = next(
        (line for line in message.splitlines() if line.strip() and not line.startswith("#")),
        "",
    )

    issues: list[str] = []
    match = _CONVENTIONAL_RE.match(first_line)
    if not match:
        issues.append(
            "Subject does not match `<type>(<scope>): <subject>` (Conventional Commits)."
        )
        return CommitCheckResult(ok=False, message_first_line=first_line, issues=issues)

    commit_type = match.group("type")
    scope = match.group("scope")

    if allowed_types and commit_type not in allowed_types:
        issues.append(
            f"Type {commit_type!r} not in forge.config.yaml commits.types "
            f"({sorted(allowed_types)})."
        )
    # Scopes can also be path-derived (e.g. `skills/integrations`) — allow
    # those if any segment matches an allowed scope.
    if allowed_scopes:
        first_seg = scope.split("/", 1)[0]
        if scope not in allowed_scopes and first_seg not in allowed_scopes:
            issues.append(
                f"Scope {scope!r} not in forge.config.yaml commits.scopes "
                f"({sorted(allowed_scopes)})."
            )

    if len(first_line) > 100:
        issues.append(f"Subject line is {len(first_line)} chars (recommended ≤ 100).")

    return CommitCheckResult(
        ok=not issues, message_first_line=first_line, issues=issues
    )
