"""`forge apps` — the managed-app list and its editing.

What matters here: editing the list must not shred forge.config.yaml's comments
(PyYAML round-tripping would), and an empty list must not be written in a way
the renderer reads as "no restriction" — that would silently re-enable writing
into every app in the bench.
"""

from pathlib import Path

import pytest

from forge.commands.apps import _owner_of, _read_managed, _write_managed


CONFIG = """\
project:
  name: erpnext-ai-forge

bench:
  path: "{{ env.FORGE_BENCH_PATH }}"

  # A comment that must survive editing.
  managed_apps:
    - alpha
    - beta

enabled_tools:
  - claude-code
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "forge.config.yaml").write_text(CONFIG)
    return tmp_path


def test_reads_the_managed_list(repo):
    assert _read_managed(repo) == ["alpha", "beta"]


def test_editing_preserves_comments_and_surrounding_keys(repo):
    _write_managed(repo, ["alpha", "beta", "gamma"])
    text = (repo / "forge.config.yaml").read_text()

    assert "# A comment that must survive editing." in text
    assert "enabled_tools:" in text
    assert "  - claude-code" in text
    assert _read_managed(repo) == ["alpha", "beta", "gamma"]


def test_round_trip_is_byte_identical(repo):
    before = (repo / "forge.config.yaml").read_text()
    _write_managed(repo, ["alpha", "beta", "gamma"])
    _write_managed(repo, ["alpha", "beta"])

    assert (repo / "forge.config.yaml").read_text() == before


def test_removing_every_app_writes_an_explicit_empty_list(repo):
    # `managed_apps:` with nothing under it parses as None, which the renderer
    # reads as "no restriction" — the opposite of what removing them all means.
    _write_managed(repo, [])
    text = (repo / "forge.config.yaml").read_text()

    assert "[]" in text
    assert _read_managed(repo) == []


def test_missing_key_is_a_clear_error(tmp_path):
    (tmp_path / "forge.config.yaml").write_text("bench:\n  path: x\n")

    with pytest.raises(ValueError, match="managed_apps"):
        _write_managed(tmp_path, ["alpha"])


@pytest.mark.parametrize(
    "remote,owner",
    [
        ("git@github.com:novizna-codes/novizna_pos.git", "novizna-codes"),
        ("https://github.com/frappe/changemakers.git", "frappe"),
        ("https://github.com/AgileShift/cargo_management", "AgileShift"),
        ("git@gitlab.com:group/sub/app.git", "sub"),
        (None, None),
        ("not-a-url", None),
    ],
)
def test_owner_extraction(remote, owner):
    # The owner is what distinguishes "our app" from "installed here but
    # someone else's", so both SSH and HTTPS forms have to parse.
    assert _owner_of(remote) == owner
