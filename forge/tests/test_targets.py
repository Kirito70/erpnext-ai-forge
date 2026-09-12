"""Sync targets: more than one repo can be rendered into.

Until now there was exactly one destination, so its settings sat at the top of
forge.config.yaml under `bench:` and seven call sites each re-did the same
`cfg["bench"]["path"].replace(env…)` substitution. Naming the concept lets the
forge repo become a target too — the repo that generates everyone else's harness
had none of its own, and hand-writing one guarantees the two drift.

Two invariants carry the weight here:
  - a config with only `bench:` behaves exactly as before (no migration), and
  - a target only receives artifacts that make sense for it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from forge.loader import load_target, load_targets
from forge.models import Target
from forge.render import _managed_apps_for, _target_wants


def _write_cfg(root: Path, cfg: dict) -> Path:
    (root / "forge.config.yaml").write_text(yaml.safe_dump(cfg))
    return root


# --- back-compat -----------------------------------------------------------

def test_legacy_bench_only_config_yields_one_target(tmp_path):
    """The shape that exists in every checkout today must keep working."""
    _write_cfg(tmp_path, {
        "bench": {"path": "/tmp/bench", "primary_site": "site1",
                  "managed_apps": ["a", "b"], "owned_remotes": ["us"]},
        "enabled_tools": ["claude-code", "cursor"],
    })
    targets = load_targets(tmp_path)
    assert set(targets) == {"bench"}
    t = targets["bench"]
    assert t.root == Path("/tmp/bench")
    assert t.primary_site == "site1"
    assert t.stack_profile == "frappe"
    assert t.enabled_tools == ["claude-code", "cursor"]
    assert t.managed_apps == ("a", "b")
    assert t.owned_remotes == frozenset({"us"})
    assert t.self_target is False
    assert t.renders is None, "unset means 'everything', as before"


def test_bench_is_the_default_target(tmp_path):
    _write_cfg(tmp_path, {"bench": {"path": "/tmp/b"}, "enabled_tools": []})
    assert load_target(tmp_path).name == "bench"


def test_targets_block_is_additive_not_replacing(tmp_path):
    """Adding a second target must not require migrating the first."""
    _write_cfg(tmp_path, {
        "bench": {"path": "/tmp/bench", "primary_site": "s"},
        "targets": {"self": {"root": ".", "stack_profile": "python_cli"}},
        "enabled_tools": ["claude-code"],
    })
    targets = load_targets(tmp_path)
    assert set(targets) == {"bench", "self"}
    assert targets["bench"].root == Path("/tmp/bench")


def test_target_entry_can_override_bench_keys(tmp_path):
    _write_cfg(tmp_path, {
        "bench": {"path": "/tmp/bench", "stack_profile": "frappe"},
        "targets": {"bench": {"stack_profile": "other"}},
        "enabled_tools": [],
    })
    assert load_targets(tmp_path)["bench"].stack_profile == "other"


# --- root resolution -------------------------------------------------------

def test_env_var_is_expanded_in_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_BENCH", "/somewhere/bench")
    _write_cfg(tmp_path, {"bench": {"path": "{{ env.MY_BENCH }}"}, "enabled_tools": []})
    assert load_targets(tmp_path)["bench"].root == Path("/somewhere/bench")


def test_relative_root_resolves_against_the_repo_not_cwd(tmp_path, monkeypatch):
    """`root: "."` must mean the forge repo. Resolving against cwd would make a
    sync write somewhere different depending on where it was invoked from."""
    _write_cfg(tmp_path, {
        "targets": {"self": {"root": "."}},
        "enabled_tools": [],
    })
    monkeypatch.chdir(tmp_path.parent)
    assert load_targets(tmp_path)["self"].root == tmp_path.resolve()


def test_missing_root_is_an_error(tmp_path):
    _write_cfg(tmp_path, {"targets": {"broken": {"stack_profile": "x"}}, "enabled_tools": []})
    with pytest.raises(ValueError, match="neither `root:` nor `path:`"):
        load_targets(tmp_path)


def test_root_resolving_to_empty_is_an_error(tmp_path, monkeypatch):
    """An unset env var used to yield Path('') and a sync that wrote to cwd."""
    monkeypatch.setenv("EMPTY_VAR", "")
    _write_cfg(tmp_path, {"targets": {"b": {"root": "{{ env.EMPTY_VAR }}"}}, "enabled_tools": []})
    with pytest.raises(ValueError, match="empty string"):
        load_targets(tmp_path)


def test_unknown_target_names_the_ones_that_exist(tmp_path):
    _write_cfg(tmp_path, {"bench": {"path": "/tmp/b"}, "enabled_tools": []})
    with pytest.raises(KeyError, match="bench"):
        load_target(tmp_path, "nope")


# --- per-target tool lists -------------------------------------------------

def test_target_can_narrow_enabled_tools(tmp_path):
    """The forge repo has nothing to say to cursor or copilot."""
    _write_cfg(tmp_path, {
        "bench": {"path": "/tmp/bench"},
        "targets": {"self": {"root": ".", "enabled_tools": ["claude-code"]}},
        "enabled_tools": ["claude-code", "cursor", "copilot"],
    })
    targets = load_targets(tmp_path)
    assert targets["bench"].enabled_tools == ["claude-code", "cursor", "copilot"]
    assert targets["self"].enabled_tools == ["claude-code"]


# --- render scoping --------------------------------------------------------

def _t(**kw) -> Target:
    base = dict(name="t", root=Path("/tmp/t"), stack_profile="frappe", enabled_tools=[])
    return Target(**{**base, **kw})


def test_unscoped_target_wants_everything():
    t = _t()
    for group in ("agents", "skills", "tools", "per_app_claude_md", "anything"):
        assert _target_wants(t, group)


def test_scoped_target_wants_only_its_groups():
    t = _t(renders=frozenset({"harness_scripts"}))
    assert _target_wants(t, "harness_scripts")
    assert not _target_wants(t, "agents")
    assert not _target_wants(t, "per_app_claude_md")


def test_empty_scope_wants_nothing():
    """An empty list is not the same as an absent key. This is what stops the
    forge repo receiving Frappe agents and phantom apps/ directories."""
    t = _t(renders=frozenset())
    assert not _target_wants(t, "agents")
    assert not _target_wants(t, "per_app_claude_md")


def test_managed_apps_none_means_unrestricted():
    assert _managed_apps_for(_t(managed_apps=None)) is None


def test_managed_apps_restricts_to_the_named_set():
    assert _managed_apps_for(_t(managed_apps=("a", "b"))) == {"a", "b"}


# --- the real config -------------------------------------------------------

def test_repo_declares_both_targets(repo_root, monkeypatch):
    monkeypatch.setenv("FORGE_BENCH_PATH", "/tmp/bench")
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "site")
    targets = load_targets(repo_root)
    assert {"bench", "self"} <= set(targets)

    self_t = targets["self"]
    assert self_t.self_target is True
    assert self_t.stack_profile == "python_cli"
    assert self_t.root == repo_root.resolve()
    assert self_t.renders == frozenset(
        {"harness_scripts", "hook_wiring", "harness_doc", "operating_manual_doc"}
    ), (
        "the self target receives the harness and nothing else — the bench's "
        "Frappe agents, skills and per-app files do not belong in a Python CLI "
        "repo, and per_app_claude_md would invent apps/ dirs that do not exist"
    )
    assert targets["bench"].self_target is False


# --- ownership ------------------------------------------------------------

def test_self_target_skips_the_foreign_write_prompt(tmp_path):
    """We are running inside this repo; asking whose it is would be noise on
    every self-sync. Hand-edit detection and the security gate still apply —
    those protect against forge, not against strangers."""
    from forge.render import RenderedArtifact
    from forge.sync import foreign_app_targets

    art = RenderedArtifact(
        tool="claude-code",
        source_path=Path("canonical/apps/x.md"),
        output_path=tmp_path / "apps" / "someone_elses" / "CLAUDE.md",
        content="x", source_commit=None, source_version="1.0.0",
        artifact_id="x", artifact_kind="app-notes",
    )
    cfg = {"bench": {"owned_remotes": ["us"]}}

    assert foreign_app_targets([art], tmp_path, cfg, _t(self_target=True)) == {}


def test_non_self_target_still_checks_ownership(tmp_path, monkeypatch):
    """The guard must not be weakened for real targets."""
    from forge.render import RenderedArtifact
    from forge import sync as sync_mod

    monkeypatch.setattr(sync_mod, "owner_of_app", lambda root, app: "someone-else")
    art = RenderedArtifact(
        tool="claude-code",
        source_path=Path("canonical/apps/x.md"),
        output_path=tmp_path / "apps" / "theirs" / "CLAUDE.md",
        content="x", source_commit=None, source_version="1.0.0",
        artifact_id="x", artifact_kind="app-notes",
    )
    found = sync_mod.foreign_app_targets(
        [art], tmp_path, {"bench": {"owned_remotes": ["us"]}},
        _t(owned_remotes=frozenset({"us"})),
    )
    assert found == {"theirs": "someone-else"}
