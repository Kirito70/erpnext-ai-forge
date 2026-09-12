"""Writing into a repo we do not own requires a typed yes.

`managed_apps` says where forge is *configured* to write; the git remote says
whose repo that actually is. When they disagree — an app added to the list
without checking who owns it — sync must stop and ask, and an unattended run
must decline rather than leave generated files in a third party's repository.
"""

from pathlib import Path

import pytest

from forge.render import RenderedArtifact
from forge.repo import is_foreign, remote_owner
from forge.sync import app_of_output, foreign_app_targets


def _artifact(path: Path) -> RenderedArtifact:
    return RenderedArtifact(
        tool="claude-code",
        source_path=path,
        output_path=path,
        content="x",
        source_commit="deadbee",
        source_version="1.0.0",
        artifact_id="test",
        artifact_kind="aggregate",
    )


@pytest.mark.parametrize(
    "path,app",
    [
        ("/bench/apps/novizna_pos/CLAUDE.md", "novizna_pos"),
        ("/bench/apps/novizna_pos/.forge-manifest.json", "novizna_pos"),
        ("/bench/CLAUDE.md", None),
        ("/bench/.claude/agents/architect.md", None),
        ("/bench/apps", None),
    ],
)
def test_app_is_derived_from_the_output_path(path, app):
    assert app_of_output(Path(path)) == app


def test_owned_app_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "forge.sync.owner_of_app", lambda bench, app: "novizna-codes"
    )
    rendered = [_artifact(tmp_path / "apps" / "novizna_pos" / "CLAUDE.md")]
    cfg = {"bench": {"owned_remotes": ["novizna-codes"]}}

    assert foreign_app_targets(rendered, tmp_path, cfg) == {}


def test_foreign_app_is_flagged_with_its_owner(tmp_path, monkeypatch):
    monkeypatch.setattr("forge.sync.owner_of_app", lambda bench, app: "frappe")
    rendered = [_artifact(tmp_path / "apps" / "changemakers" / "CLAUDE.md")]
    cfg = {"bench": {"owned_remotes": ["novizna-codes"]}}

    assert foreign_app_targets(rendered, tmp_path, cfg) == {"changemakers": "frappe"}


def test_check_is_disabled_when_no_owners_are_declared(tmp_path, monkeypatch):
    # A bench that has not declared owned_remotes gets the old behaviour rather
    # than a prompt on every app it cannot classify.
    monkeypatch.setattr("forge.sync.owner_of_app", lambda bench, app: "anyone")
    rendered = [_artifact(tmp_path / "apps" / "whatever" / "CLAUDE.md")]

    assert foreign_app_targets(rendered, tmp_path, {"bench": {}}) == {}


def test_non_per_app_outputs_are_never_flagged(tmp_path, monkeypatch):
    # The bench root is ours by definition — only files landing inside another
    # app's repository are in question.
    monkeypatch.setattr("forge.sync.owner_of_app", lambda bench, app: "frappe")
    rendered = [_artifact(tmp_path / "CLAUDE.md")]
    cfg = {"bench": {"owned_remotes": ["novizna-codes"]}}

    assert foreign_app_targets(rendered, tmp_path, cfg) == {}


@pytest.mark.parametrize(
    "owner,owned,foreign",
    [
        ("frappe", {"novizna-codes"}, True),
        ("novizna-codes", {"novizna-codes"}, False),
        ("AgileShift", {"novizna-codes"}, True),
        # No remote at all: a local-only or freshly scaffolded app. Blocking
        # those would be noise — the guard is about other organisations.
        (None, {"novizna-codes"}, False),
        # No declared owners: check disabled.
        ("frappe", set(), False),
    ],
)
def test_foreign_classification(owner, owned, foreign):
    assert is_foreign(owner, owned) is foreign


@pytest.mark.parametrize(
    "remote,owner",
    [
        ("git@github.com:novizna-codes/novizna_pos.git", "novizna-codes"),
        ("https://github.com/frappe/changemakers.git", "frappe"),
        ("https://github.com/AgileShift/cargo_management", "AgileShift"),
        ("ssh://git@host:2222/org/app.git", "org"),
    ],
)
def test_remote_owner_parsing(remote, owner):
    assert remote_owner(remote) == owner
