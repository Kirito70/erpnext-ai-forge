"""Skills provenance lockfile — canonical/skills-lock.json.

Detects unreviewed drift in externally-sourced skills. This is deliberately
narrow: it does NOT fetch, install, or import anything. Importing
network-fetched, untrusted content automatically is a materially riskier
feature than this — see `D-EXTERNAL-UNREVIEWED` in
canonical/policies/security-scoring.yaml, which exists precisely because
unreviewed external content is a real threat model here. The lockfile's whole
value is catching drift in content a human already reviewed and approved,
after the fact.

Only skills with `provenance: external` in frontmatter need an entry. All
skills authored in this repo (`provenance: internal`, the default) are
untouched by any of this.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.loader import load_forge_config, load_security_scoring_yaml, load_skills
from forge.scoring import score_text

LOCKFILE_NAME = "skills-lock.json"


@dataclass(frozen=True)
class LockEntry:
    skill_id: str
    source: str
    source_type: str
    skill_path: str
    upstream_ref: str
    computed_hash: str
    imported_at: str
    security_score: int
    reviewed_by: str
    reviewed_at: str


@dataclass(frozen=True)
class VerifyFinding:
    skill_id: str
    problem: str
    """One of: 'missing-lock-entry', 'hash-mismatch', 'score-below-threshold'."""
    detail: str


def lockfile_path(repo_root: Path) -> Path:
    return repo_root / "canonical" / LOCKFILE_NAME


def load_lockfile(repo_root: Path) -> dict[str, LockEntry]:
    """Parse skills-lock.json. Missing file is treated as empty — a repo with
    zero external skills needs no lockfile content, only the ability to prove
    it has none."""
    path = lockfile_path(repo_root)
    if not path.is_file():
        return {}
    raw: dict[str, Any] = json.loads(path.read_text())
    entries: dict[str, LockEntry] = {}
    for skill_id, data in (raw.get("skills") or {}).items():
        entries[skill_id] = LockEntry(
            skill_id=skill_id,
            source=str(data.get("source", "")),
            source_type=str(data.get("sourceType", "")),
            skill_path=str(data.get("skillPath", "")),
            upstream_ref=str(data.get("upstreamRef", "")),
            computed_hash=str(data.get("computedHash", "")),
            imported_at=str(data.get("importedAt", "")),
            security_score=int(data.get("securityScore", 0)),
            reviewed_by=str(data.get("reviewedBy", "")),
            reviewed_at=str(data.get("reviewedAt", "")),
        )
    return entries


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(repo_root: Path) -> list[VerifyFinding]:
    """Check every EXTERNAL skill against its lock entry.

    Two independent failure modes, reported distinctly so the operator knows
    which one they're looking at:
      - hash moved without a matching lock update → someone edited an
        externally-sourced file without going through re-review
      - security score dropped below the external threshold → even an
        intentional edit that lowers the bar past the line drawn for imported
        content
    A skill marked `provenance: external` with no lock entry at all is its own
    finding — the entry should have been created at import time.
    """
    cfg = load_forge_config(repo_root)
    threshold = int(cfg.get("security", {}).get("external_skill_threshold", 98))
    lock = load_lockfile(repo_root)

    findings: list[VerifyFinding] = []
    for skill in load_skills(repo_root):
        if skill.provenance != "external":
            continue

        entry = lock.get(skill.id)
        if entry is None:
            findings.append(
                VerifyFinding(
                    skill_id=skill.id,
                    problem="missing-lock-entry",
                    detail=(
                        f"{skill.source_path.name} is provenance: external but "
                        f"has no entry in {LOCKFILE_NAME}"
                    ),
                )
            )
            continue

        current_hash = sha256_of(skill.source_path)
        if current_hash != entry.computed_hash:
            findings.append(
                VerifyFinding(
                    skill_id=skill.id,
                    problem="hash-mismatch",
                    detail=(
                        f"{skill.source_path.name} hash changed "
                        f"({entry.computed_hash[:12]}... → {current_hash[:12]}...) "
                        f"but {LOCKFILE_NAME} was not updated — re-review and "
                        f"bump computedHash + importedAt, or revert the edit"
                    ),
                )
            )

        # `honor_path_exemptions=False`: canonical/skills/** is exempted from
        # dangerous-shell rules so OUR OWN skills can discuss bad patterns
        # didactically ("don't do this"). That trust does not extend to
        # imported content nobody here wrote — scoring it as prose-exempt
        # would make `external_skill_threshold` unreachable for exactly the
        # case it exists to catch.
        rules = load_security_scoring_yaml(repo_root)
        text = skill.source_path.read_text(errors="replace")
        score, _ = score_text(
            text, str(skill.source_path), rules,
            suffix=skill.source_path.suffix, honor_path_exemptions=False,
        )
        if score < threshold:
            findings.append(
                VerifyFinding(
                    skill_id=skill.id,
                    problem="score-below-threshold",
                    detail=(
                        f"{skill.source_path.name} scores {score}, "
                        f"below the external_skill_threshold of {threshold}"
                    ),
                )
            )

    return findings


def list_skills(repo_root: Path) -> list[tuple[str, str, str | None]]:
    """(skill_id, provenance, source) for every skill — the `forge skills list` view."""
    lock = load_lockfile(repo_root)
    out: list[tuple[str, str, str | None]] = []
    for skill in load_skills(repo_root):
        source = None
        if skill.provenance == "external":
            entry = lock.get(skill.id)
            source = entry.source if entry else skill.source_url
        out.append((skill.id, skill.provenance, source))
    return sorted(out)
