"""The overlay config: where it is read from, and how it merges.

Company and machine settings live outside the repo. These tests pin the two
things that would silently leak or lose them: which file wins, and that an
empty list in the overlay means "none", never "no restriction".
"""

from pathlib import Path

import pytest

from forge.loader import load_forge_config, load_target
from forge.user_config import deep_merge, overlay_path

DEFAULTS = """\
project: {name: t, version: 0.0.0}
bench:
  path: /srv/default
  owned_remotes: []
  managed_apps: []
enabled_tools: [claude-code]
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "forge.config.example.yaml").write_text(DEFAULTS)
    monkeypatch.delenv("FORGE_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return root


def test_defaults_alone_when_no_overlay_exists(repo):
    cfg = load_forge_config(repo)
    assert cfg["bench"]["path"] == "/srv/default"
    assert cfg["bench"]["managed_apps"] == []


def test_home_overlay_is_used_by_installed_copies(repo, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".forge.yaml").write_text("bench: {managed_apps: [acme_crm]}\n")

    cfg = load_forge_config(repo)

    assert cfg["bench"]["managed_apps"] == ["acme_crm"]
    assert cfg["bench"]["path"] == "/srv/default"  # untouched keys survive


def test_checkout_overlay_beats_home(repo, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".forge.yaml").write_text("bench: {managed_apps: [from_home]}\n")
    (repo / "forge.config.yaml").write_text("bench: {managed_apps: [from_checkout]}\n")

    assert load_forge_config(repo)["bench"]["managed_apps"] == ["from_checkout"]
    assert overlay_path(repo) == repo / "forge.config.yaml"


def test_env_var_beats_everything_even_when_absent(repo, tmp_path, monkeypatch):
    (repo / "forge.config.yaml").write_text("bench: {managed_apps: [from_checkout]}\n")
    monkeypatch.setenv("FORGE_CONFIG", str(tmp_path / "missing.yaml"))

    # Pointing at nothing is how tests and scripts ask for bare defaults.
    assert load_forge_config(repo)["bench"]["managed_apps"] == []


def test_overlay_lists_replace_rather_than_extend():
    merged = deep_merge({"a": {"xs": [1, 2], "k": 1}}, {"a": {"xs": [3]}})
    assert merged == {"a": {"xs": [3], "k": 1}}


def test_merge_does_not_mutate_its_inputs():
    base = {"a": {"b": 1}}
    deep_merge(base, {"a": {"b": 2}})
    assert base == {"a": {"b": 1}}


def test_empty_managed_apps_means_no_app_not_every_app(repo):
    # Regression: `[]` used to collapse to None, which the renderer reads as
    # "no restriction" — so the shipped empty default wrote into every app.
    assert load_target(repo).managed_apps == ()


def test_absent_managed_apps_still_means_no_restriction(repo):
    (repo / "forge.config.example.yaml").write_text(
        DEFAULTS.replace("  managed_apps: []\n", "")
    )
    assert load_target(repo).managed_apps is None
