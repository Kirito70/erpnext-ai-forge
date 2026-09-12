"""Four ways the tool kept working while quietly doing the wrong thing.

None of these raise, and that is the point. Each one degrades into a plausible
answer — a deletion that looks like tidying, a skipped security check, a clean
reconciliation report, a vault path that resolves — with nothing in the output
saying a decision was made on worse information than the operator assumes.

Fail-open is the right call in most of them. Being silent about it is not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.ledger_sync import parse_vault_tickets, resolve_vault_path
from forge.loader import load_skills
from forge.manifest import ManifestEntry, build_manifest, sha256_text, write_manifest
from forge.render import RenderedArtifact
from forge.sync import find_orphans

TOOL = "claude-code"


def _artifact(out: Path, content: str = "body") -> RenderedArtifact:
    return RenderedArtifact(
        tool=TOOL,
        source_path=Path("canonical/skills/x.md"),
        output_path=out,
        content=content,
        source_commit="abc123",
        source_version="1.0.0",
        artifact_id="x",
        artifact_kind="skill",
    )


def _record(out_dir: Path, files: dict[str, str]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, content in files.items():
        (out_dir / name).write_text(content)
        outputs.append(
            ManifestEntry(
                path=name, version="1.0.0", sha256=sha256_text(content), adapter=TOOL
            )
        )
    write_manifest(
        out_dir,
        build_manifest(
            source_repo="erpnext-ai-forge",
            source_commit="abc123",
            adapter_name=TOOL,
            adapter_version="0.1.0",
            entries=[
                ManifestEntry(
                    path="canonical/skills/x.md",
                    version="1.0.0",
                    sha256=sha256_text("src"),
                    adapter=TOOL,
                )
            ],
            outputs=outputs,
            rendered_at="2026-01-01T00:00:00Z",
        ),
    )
    return out_dir


# ---------------------------------------------------------------------------
# 5. declining to write must never become a deletion
# ---------------------------------------------------------------------------


def test_an_app_skipped_for_ownership_is_not_an_orphan(tmp_path):
    """Saying "no, do not write to that repo" dropped the app from `rendered`,
    and `find_orphans` reads absence from `rendered` as "no longer produced" —
    so with --prune, declining a write deleted the files already there."""
    app_dir = _record(tmp_path / "apps" / "theirs", {"CLAUDE.md": "generated"})
    ours = _record(tmp_path / "apps" / "ours", {"CLAUDE.md": "generated"})

    # Both apps rendered; the foreign one was then skipped at the prompt.
    everything = [_artifact(app_dir / "CLAUDE.md", "generated"),
                  _artifact(ours / "CLAUDE.md", "generated")]
    after_skip = [everything[1]]

    orphans = find_orphans(after_skip, tmp_path, TOOL, still_managed=everything)

    assert orphans == [], "a file we declined to write was queued for deletion"


def test_a_genuinely_relocated_output_is_still_an_orphan(tmp_path):
    """The carve-out must not blunt the thing orphan detection is for."""
    old = _record(tmp_path / ".claude" / "skills", {"pos.md": "body"})
    moved = [_artifact(tmp_path / ".claude" / "skills" / "pos" / "SKILL.md", "body")]

    orphans = find_orphans(moved, tmp_path, TOOL, still_managed=moved)

    assert [o.path for o in orphans] == [old / "pos.md"]


# ---------------------------------------------------------------------------
# 6. provenance is a two-value domain, so make it one
# ---------------------------------------------------------------------------


def test_an_unrecognised_provenance_is_refused(tmp_path):
    """Three call sites test this field three different ways: `!= "external"`
    skips the lockfile check, `== "external"` picks the source, `== "internal"`
    picks the label. A typo silently exempts a skill from verification while
    the list command still shows it as external."""
    skills = tmp_path / "canonical" / "skills"
    skills.mkdir(parents=True)
    (skills / "s.md").write_text(
        "---\nid: s\nname: s\ndescription: d\nprovenance: External\n---\n\nbody\n"
    )

    with pytest.raises(ValueError, match="(?i)provenance"):
        load_skills(tmp_path)


def test_the_two_real_values_still_load(tmp_path):
    skills = tmp_path / "canonical" / "skills"
    skills.mkdir(parents=True)
    (skills / "a.md").write_text(
        "---\nid: a\nname: a\ndescription: d\nprovenance: internal\n---\n\nbody\n"
    )
    (skills / "b.md").write_text(
        "---\nid: b\nname: b\ndescription: d\nprovenance: external\n---\n\nbody\n"
    )

    got = {s.id: s.provenance for s in load_skills(tmp_path)}
    assert got == {"a": "internal", "b": "external"}


def test_provenance_defaults_to_internal_when_absent(tmp_path):
    skills = tmp_path / "canonical" / "skills"
    skills.mkdir(parents=True)
    (skills / "a.md").write_text("---\nid: a\nname: a\ndescription: d\n---\n\nbody\n")

    assert [s.provenance for s in load_skills(tmp_path)] == ["internal"]


# ---------------------------------------------------------------------------
# 7. a ticket that cannot be parsed is the one most worth reporting
# ---------------------------------------------------------------------------


def test_an_unparsable_ticket_is_reported_not_dropped(tmp_path):
    """`forge ledger sync` exists to catch a ticket with no ledger row. A
    malformed one vanished from the comparison entirely, so the command printed
    agreement while missing exactly the ticket it was run to find."""
    tickets = tmp_path / "wiki" / "novizna" / "tickets"
    tickets.mkdir(parents=True)
    (tickets / "good.md").write_text("---\nid: N-1\nstatus: Done\n---\n\nbody\n")
    (tickets / "broken.md").write_text("---\nid: N-2\nstatus: [unclosed\n---\n\nbody\n")

    tickets_found, unreadable = parse_vault_tickets(tmp_path, "novizna")

    assert set(tickets_found) == {"N-1"}
    assert [p.name for p in unreadable] == ["broken.md"]


def test_a_clean_backlog_reports_nothing_unreadable(tmp_path):
    tickets = tmp_path / "wiki" / "novizna" / "tickets"
    tickets.mkdir(parents=True)
    (tickets / "good.md").write_text("---\nid: N-1\nstatus: Done\n---\n\nbody\n")

    tickets_found, unreadable = parse_vault_tickets(tmp_path, "novizna")

    assert set(tickets_found) == {"N-1"} and unreadable == []


# ---------------------------------------------------------------------------
# 8. a fallback the operator cannot see is a guess
# ---------------------------------------------------------------------------


def test_falling_back_past_a_broken_brain_says_so(tmp_path, monkeypatch):
    """Brain missing, crashing, timing out and erroring all collapse to None,
    then brains.toml answers instead. Using the fallback is right; not saying
    which source answered means a stale default looks like a confirmation."""
    vault = tmp_path / "vault"
    vault.mkdir()
    config = tmp_path / "brains.toml"
    config.write_text(f'[[vaults]]\npath = "{vault}"\ndefault = true\n')
    monkeypatch.setattr("forge.ledger_sync._BRAINS_CONFIG", config)
    monkeypatch.setattr("forge.ledger_sync._ask_brain", lambda: None)
    monkeypatch.setattr("forge.ledger_sync._brain_bin", lambda: "/usr/bin/brain")
    monkeypatch.delenv("NOVIZNA_VAULT", raising=False)

    path, source = resolve_vault_path()

    assert path == vault
    assert source == "brains.toml"


def test_brain_answering_is_reported_as_brain(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr("forge.ledger_sync._ask_brain", lambda: vault)
    monkeypatch.delenv("NOVIZNA_VAULT", raising=False)

    assert resolve_vault_path() == (vault, "brain")


def test_an_explicit_path_is_reported_as_explicit(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    assert resolve_vault_path(vault) == (vault, "--vault-path")


def test_nothing_resolving_still_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("forge.ledger_sync._BRAINS_CONFIG", tmp_path / "absent.toml")
    monkeypatch.setattr("forge.ledger_sync._ask_brain", lambda: None)
    monkeypatch.delenv("NOVIZNA_VAULT", raising=False)

    assert resolve_vault_path() == (None, None)
