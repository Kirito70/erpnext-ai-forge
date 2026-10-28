"""`forge setup` and `forge invite`: company apps come from the bench, not code.

A fake bench with real git remotes stands in for a company's: one app under
the company's org, one vendored from elsewhere, one upstream Frappe app.
"""

import subprocess
from pathlib import Path

import pytest
import yaml

from forge.commands import invite as invite_cmd
from forge.commands.setup import (
    BenchApp,
    decode_invite,
    encode_invite,
    parse_selection,
    run_setup,
    scan_bench_apps,
)

DEFAULTS = """\
project: {name: t, version: 0.0.0}
bench:
  path: "{{ env.FORGE_BENCH_PATH }}"
  primary_site: "{{ env.FORGE_PRIMARY_SITE }}"
  owned_remotes: []
  managed_apps: []
upstream_apps: [frappe]
"""


def _app(bench: Path, name: str, remote: str | None) -> None:
    app = bench / "apps" / name
    app.mkdir(parents=True)
    if remote:
        subprocess.run(["git", "init", "-q", str(app)], check=True)
        subprocess.run(["git", "-C", str(app), "remote", "add", "origin", remote], check=True)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "forge.config.example.yaml").write_text(DEFAULTS)
    bench = tmp_path / "bench"
    _app(bench, "frappe", "https://github.com/frappe/frappe.git")
    _app(bench, "acme_crm", "git@github.com:acme/acme_crm.git")
    _app(bench, "vendor_tool", "https://github.com/someone/vendor_tool")
    _app(bench, "scratch_app", None)
    (bench / "sites" / "site1").mkdir(parents=True)
    (bench / "sites" / "site1" / "site_config.json").write_text("{}")
    overlay = tmp_path / "home" / ".forge.yaml"
    monkeypatch.setenv("FORGE_CONFIG", str(overlay))
    monkeypatch.delenv("FORGE_BENCH_PATH", raising=False)
    monkeypatch.delenv("FORGE_PRIMARY_SITE", raising=False)
    monkeypatch.chdir(repo)
    return {"repo": repo, "bench": bench, "overlay": overlay}


def _scripted(*answers: str):
    queue = list(answers)

    def ask(prompt: str, default: str) -> str:
        # Blank means "take the default", as typer.prompt does.
        answer = queue.pop(0) if queue else ""
        return answer or default

    return ask


def test_scan_skips_upstream_and_reports_owners(env):
    apps = scan_bench_apps(env["bench"], {"frappe"})
    assert apps == [
        BenchApp("acme_crm", "acme"),
        BenchApp("scratch_app", None),
        BenchApp("vendor_tool", "someone"),
    ]


@pytest.mark.parametrize(
    "answer,expected",
    [("", ["x"]), ("none", []), ("1, 3", ["a", "c"]), ("b a", ["b", "a"]), ("2,b", ["b"])],
)
def test_parse_selection(answer, expected):
    apps = [BenchApp("a", None), BenchApp("b", None), BenchApp("c", None)]
    assert parse_selection(answer, apps, ["x"]) == expected


def test_parse_selection_rejects_unknown_app():
    with pytest.raises(ValueError, match="nope"):
        parse_selection("nope", [BenchApp("a", None)], [])


def test_invite_payload_never_carries_machine_settings():
    payload = encode_invite({"bench": {"path": "/mine", "primary_site": "s", "managed_apps": ["a"]}})
    assert decode_invite(payload) == {"bench": {"managed_apps": ["a"]}}


def test_corrupt_invite_is_a_clear_error():
    with pytest.raises(ValueError, match="copied whole"):
        decode_invite("not base64!!")


def test_interactive_setup_without_invite_asks_and_infers_owner(env):
    # bench, site, apps (#1 = acme_crm), owned remotes (accept inferred default)
    ask = _scripted(str(env["bench"]), "site1", "1", "")

    run_setup(env["repo"], ask=ask)

    bench = yaml.safe_load(env["overlay"].read_text())["bench"]
    assert bench["path"] == str(env["bench"])
    assert bench["primary_site"] == "site1"
    assert bench["managed_apps"] == ["acme_crm"]
    assert bench["owned_remotes"] == ["acme"]
    assert bench["lint_apps"] == ["acme_crm"]


def test_invite_preselects_apps_and_drops_ones_missing_here(env):
    payload = encode_invite(
        {"bench": {"managed_apps": ["acme_crm", "not_here"], "owned_remotes": ["acme"]}}
    )

    run_setup(env["repo"], invite=payload, bench=str(env["bench"]), site="site1", assume_yes=True)

    bench = yaml.safe_load(env["overlay"].read_text())["bench"]
    assert bench["managed_apps"] == ["acme_crm"]
    assert bench["owned_remotes"] == ["acme"]


def test_no_company_apps_is_a_valid_answer(env):
    run_setup(env["repo"], ask=_scripted(str(env["bench"]), "site1", "none"))

    bench = yaml.safe_load(env["overlay"].read_text())["bench"]
    assert bench["managed_apps"] == []


def test_if_needed_keeps_existing_settings(env):
    env["overlay"].parent.mkdir(parents=True)
    env["overlay"].write_text("bench: {path: /already/set}\n")

    run_setup(env["repo"], if_needed=True, ask=_scripted())

    assert yaml.safe_load(env["overlay"].read_text()) == {"bench": {"path": "/already/set"}}


def test_bad_bench_path_is_rejected(env, tmp_path):
    with pytest.raises(ValueError, match="bench"):
        run_setup(env["repo"], bench=str(tmp_path / "nope"), site="s", assume_yes=True)


def test_invite_copies_only_what_was_chosen(env, capsys):
    env["overlay"].parent.mkdir(parents=True)
    env["overlay"].write_text(
        "bench: {path: /mine, primary_site: s, managed_apps: [acme_crm], owned_remotes: [acme]}\n"
    )

    invite_cmd.run_invite(only=["bench.managed_apps"], no_token=True)

    out = capsys.readouterr().out
    payload = out.split("FORGE_INVITE='")[1].split("'")[0]
    assert decode_invite(payload) == {"bench": {"managed_apps": ["acme_crm"]}}
    assert "/mine" not in out
    assert "install.ps1" in out and "install.sh" in out


def test_invite_asks_per_setting(env, capsys):
    env["overlay"].parent.mkdir(parents=True)
    env["overlay"].write_text("bench: {managed_apps: [acme_crm], owned_remotes: [acme]}\n")

    invite_cmd.run_invite(ask=_scripted("y", "n"), no_token=True)

    payload = capsys.readouterr().out.split("FORGE_INVITE='")[1].split("'")[0]
    assert decode_invite(payload) == {"bench": {"managed_apps": ["acme_crm"]}}


def test_private_repo_commands_use_the_api_with_the_token():
    linux, windows = invite_cmd.install_commands("o/r", "UEFZ", "tok123")
    assert "api.github.com/repos/o/r/contents/scripts/install.sh" in linux
    assert "FORGE_GITHUB_TOKEN='tok123'" in linux
    assert "Bearer tok123" in windows and "install.ps1" in windows


def test_public_repo_commands_use_the_release_download():
    linux, windows = invite_cmd.install_commands("o/r", "UEFZ", None)
    assert "github.com/o/r/releases/latest/download/install.sh" in linux
    assert "Bearer" not in linux + windows
