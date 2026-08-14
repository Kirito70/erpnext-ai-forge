"""The verification harness: canonical shell rendered per target.

Two properties carry this design, and both are tested here:

  1. The scripts are IDENTICAL across targets. A Frappe bench and a Python CLI
     share one `common.sh`, one `hook-posttooluse.sh`, one `hook-stop.sh`; only
     the gate table differs. If a stack difference ever leaks into the shell,
     the abstraction is wrong and these tests should fail loudly.

  2. `settings.json` is MERGED, never swapped. It holds permissions and hooks a
     human wrote and forge never saw; overwriting it destroys their work.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from forge.loader import load_harness, load_target
from forge.render import render, render_gate_cmd
from forge.sync import SETTINGS_FRAGMENT_KIND, _merge_settings_fragments


@pytest.fixture
def bench_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_BENCH_PATH", str(tmp_path / "bench"))
    monkeypatch.setenv("FORGE_PRIMARY_SITE", "ci-site")
    (tmp_path / "bench" / "apps").mkdir(parents=True)
    return tmp_path / "bench"


# --- the spec loads --------------------------------------------------------

def test_harness_spec_loads(repo_root):
    h = load_harness(repo_root)
    assert h is not None
    assert {s.id for s in h.scripts} >= {
        "common", "check-file", "typecheck", "gates", "hook-posttooluse", "hook-stop"
    }


def test_j2_suffix_is_stripped_for_the_target(repo_root):
    """`gates.sh.j2` is a rendering detail; the target sees `gates.sh`."""
    h = load_harness(repo_root)
    assert h.script("gates").filename == "gates.sh"


def test_sourced_file_is_not_executable(repo_root):
    """common.sh is sourced, never run. Marking it +x invites someone to
    execute it, which does nothing useful and looks like it should."""
    h = load_harness(repo_root)
    assert h.script("common").mode == 0o644
    assert h.script("gates").mode == 0o755


def test_hooks_invoke_adapters_not_the_gate_scripts(repo_root):
    """A hook is handed JSON on stdin; check-file.sh takes file paths as
    arguments. Pointing a hook straight at check-file.sh silently lints
    nothing, because it sees no arguments and exits 0."""
    h = load_harness(repo_root)
    for hook in h.hooks:
        assert hook.script.startswith("hook-"), (
            f"hook '{hook.id}' runs '{hook.script}' directly; it must run an "
            f"adapter that parses the payload first"
        )


def test_hook_events_are_tool_neutral(repo_root):
    """canonical/ must never name a tool's own event. The moment it says
    'PostToolUse', the canonical layer has become Claude-specific."""
    h = load_harness(repo_root)
    assert {hook.fires_on for hook in h.hooks} <= {"file_edit", "session_stop"}


def test_stop_hook_runs_quick_not_full(repo_root, bench_env):
    """A Frappe test run is minutes. A Stop hook that takes minutes gets
    disabled, and a disabled hook verifies nothing — so the session-end path
    must never reach the full suite."""
    stop = _harness_files(repo_root, "bench")["hook-stop.sh"]
    assert "gates.sh\" quick" in stop or "gates.sh quick" in stop
    assert "gates.sh full" not in stop and "gates.sh all" not in stop


# --- gate command rendering ------------------------------------------------

def test_placeholders_become_shell_not_literals():
    """`{file}` must become a shell expression, not a baked-in path — one
    rendered script has to handle every file it is called about.

    Absolute rather than bare `"$FILE"`: gates that change directory
    (`yarn --cwd <js_dir> lint <file>`) resolve a bench-relative path against
    the wrong root and exit 2 with "No files matching the pattern".
    """
    out = render_gate_cmd("ruff check --fix {file}")
    assert out == 'ruff check --fix "$(_abs_of "$FILE")"'


def test_js_dir_placeholder_is_distinct_from_app_dir():
    """A frontend gate must get the JS workspace, not the Frappe app.

    They differ whenever an app keeps its frontend in a subdirectory — as
    novizna_pos does — and `yarn --cwd <app_dir>` then fails outright because
    there is no package.json there.
    """
    out = render_gate_cmd("yarn --cwd {js_dir} lint {file}")
    assert '"$(_js_dir_of "$FILE")"' in out
    assert "_app_dir_of" not in out


def test_app_placeholders_resolve_at_runtime():
    """Baking the app name in at render time would need one script per app."""
    out = render_gate_cmd("bench run-tests --app {app}")
    assert '"$(_app_of "$FILE")"' in out


def test_site_placeholder_is_substituted_at_render_time():
    """{site} is a per-target constant (FORGE_PRIMARY_SITE), known at render
    time and identical for every invocation — unlike {file}/{app}, it must be
    baked in as a literal, not a shell expression.

    Shipped unsubstituted for one real sync: `bench --site {site} run-tests`
    ran with `{site}` as a literal, nonexistent site name against the real
    Novizna bench, caught only because someone actually read the generated
    script rather than trusting `bash -n` (which happily accepts `{site}` as
    an ordinary argument token)."""
    out = render_gate_cmd("bench --site {site} run-tests", site="novizna-pos")
    assert out == "bench --site novizna-pos run-tests"
    assert "{site}" not in out


def test_no_unsubstituted_braces_reach_a_rendered_gate_line(repo_root, bench_env):
    """Generic guard against the whole class of bug above: whatever new
    placeholder gates.yaml grows next, catch it here rather than shipping it
    to a real bench first. `bash -n` cannot catch this — `{anything}` is
    syntactically valid as a bare word."""
    for name, content in _harness_files(repo_root, "bench").items():
        for line in content.splitlines():
            if "run_gate" in line or "run_to" in line:
                assert not re.search(r"\{[a-z_]+\}", line), (
                    f"{name}: unsubstituted placeholder in {line!r}"
                )


# --- the two targets share scripts, not gates ------------------------------

def _harness_files(repo_root: Path, target_name: str) -> dict[str, str]:
    tgt = load_target(repo_root, target_name)
    return {
        a.output_path.name: a.content
        for a in render(repo_root, "claude-code", tgt)
        if a.artifact_kind == "harness-script"
    }


def test_plumbing_scripts_are_identical_across_targets(repo_root, bench_env):
    """The promise: one copy of the fiddly part. Only the provenance header,
    which names the target, may differ."""
    bench = _harness_files(repo_root, "bench")
    selff = _harness_files(repo_root, "self")

    def strip_header(text: str) -> str:
        return "\n".join(
            ln for ln in text.splitlines() if not ln.startswith("# Target:")
        )

    for name in ("common.sh", "hook-posttooluse.sh", "hook-stop.sh"):
        assert strip_header(bench[name]) == strip_header(selff[name]), (
            f"{name} differs between targets — a stack difference has leaked "
            f"out of gates.yaml and into the shell"
        )


def test_gate_tables_do_differ(repo_root, bench_env):
    """The simplicity of the forge repo lives here, as fewer rows."""
    bench = _harness_files(repo_root, "bench")["gates.sh"]
    selff = _harness_files(repo_root, "self")["gates.sh"]
    assert "frappe-tests" in bench and "frappe-tests" not in selff
    assert "mypy" in selff and "mypy" not in bench


def test_unverified_gates_are_marked_in_the_output(repo_root, bench_env):
    """The debt has to be visible in the artifact, not just in the source."""
    assert "UNVERIFIED" in _harness_files(repo_root, "bench")["check-file.sh"]


# --- generated shell is real shell -----------------------------------------

@pytest.mark.parametrize("name", [
    "common.sh", "check-file.sh", "typecheck.sh",
    "gates.sh", "hook-posttooluse.sh", "hook-stop.sh",
])
def test_generated_scripts_are_valid_bash(repo_root, bench_env, tmp_path, name):
    """`bash -n` catches the class of template bug that renders fine and then
    fails at 3am inside a hook."""
    content = _harness_files(repo_root, "bench")[name]
    p = tmp_path / name
    p.write_text(content)
    result = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_no_literal_none_in_rendered_scripts(repo_root, bench_env):
    """Jinja's `default` filter only fires on UNDEFINED, but `.get()` returns
    None — which rendered as the literal string 'None' into every timeout slot
    and made every gate die with `timeout: invalid time interval 'None'`."""
    for name, content in _harness_files(repo_root, "bench").items():
        assert "run_gate \"" not in content or " None " not in content, name
        assert "run_to None" not in content, name


def test_scripts_set_strict_mode(repo_root, bench_env):
    """Without `set -e` a hook continues past a failed command and exits 0, so
    a broken gate reports success."""
    for name, content in _harness_files(repo_root, "bench").items():
        assert "set -" in content and "o pipefail" in content, name


def test_no_script_invokes_forge_sync(repo_root, bench_env):
    """A sync from inside a hook rewrites the scripts mid-run, and
    _confirm_foreign_writes fails closed on a non-tty — so it would skip
    silently rather than ask."""
    for name, content in _harness_files(repo_root, "bench").items():
        # Strip comments: common.sh documents this very rule in prose, and the
        # reason belongs next to the code it constrains.
        code = "\n".join(
            ln for ln in content.splitlines() if not ln.lstrip().startswith("#")
        )
        assert "forge sync" not in code, f"{name} invokes forge sync"


# --- settings.json is merged, not owned ------------------------------------

def _fragment(tmp_path: Path, payload: dict):
    from forge.render import RenderedArtifact
    return RenderedArtifact(
        tool="claude-code",
        source_path=Path("canonical/harness/harness.yaml"),
        output_path=tmp_path / ".claude" / "settings.json",
        content=json.dumps(payload),
        source_commit=None,
        source_version="1.0.0",
        artifact_id="hook-wiring/claude-code",
        artifact_kind=SETTINGS_FRAGMENT_KIND,
    )


def test_merge_preserves_human_keys(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({
        "permissions": {"allow": ["Bash(mine *)"]},
        "hooks": {"SessionStart": [{"matcher": "", "hooks": []}]},
        "myOwnSetting": "must survive",
    }))

    frag = _fragment(tmp_path, {
        "permissions": {"allow": ["Bash(forge *)"], "deny": ["Bash(sudo *)"]},
        "hooks": {"Stop": [{"matcher": "", "hooks": []}]},
    })
    written, conflicts, backup = _merge_settings_fragments([frag])

    result = json.loads(settings.read_text())
    assert result["myOwnSetting"] == "must survive"
    assert "Bash(mine *)" in result["permissions"]["allow"]
    assert "Bash(forge *)" in result["permissions"]["allow"]
    assert "SessionStart" in result["hooks"] and "Stop" in result["hooks"]
    assert written == [settings]
    assert backup is not None and backup.is_file()


def test_first_write_takes_no_backup(tmp_path):
    """Nothing to back up, and an empty .forge-backup would look like data loss."""
    (tmp_path / ".claude").mkdir()
    _, _, backup = _merge_settings_fragments([_fragment(tmp_path, {"a": 1})])
    assert backup is None


def test_malformed_fragment_fails_loudly(tmp_path):
    from forge.render import RenderedArtifact
    bad = RenderedArtifact(
        tool="claude-code",
        source_path=Path("x"),
        output_path=tmp_path / "settings.json",
        content="{not json",
        source_commit=None,
        source_version="1.0.0",
        artifact_id="hook-wiring/claude-code",
        artifact_kind=SETTINGS_FRAGMENT_KIND,
    )
    with pytest.raises(ValueError, match="not valid"):
        _merge_settings_fragments([bad])


def test_rendered_wiring_is_valid_json(repo_root, bench_env):
    tgt = load_target(repo_root, "bench")
    frags = [
        a for a in render(repo_root, "claude-code", tgt)
        if a.artifact_kind == SETTINGS_FRAGMENT_KIND
    ]
    assert len(frags) == 1
    data = json.loads(frags[0].content)
    assert set(data["hooks"]) == {"PostToolUse", "Stop"}
    assert data["hooks"]["PostToolUse"][0]["hooks"][0]["timeout"] == 240


# --- per-adapter wiring (Phase 3) ------------------------------------------

ALL_ADAPTERS = [
    "claude-code", "cursor", "opencode", "cline", "copilot", "codex", "antigravity",
]


@pytest.mark.parametrize("tool", ALL_ADAPTERS)
def test_every_adapter_ships_the_harness_doc(repo_root, bench_env, tool):
    """Four of the seven have no hook mechanism at all. For them the harness is
    instruction-level only, so the document IS the enforcement — it cannot be
    the one thing that is missing."""
    tgt = load_target(repo_root, "bench")
    outs = {a.output_path.name for a in render(repo_root, tool, tgt)}
    assert "AGENTS-HARNESS.md" in outs


@pytest.mark.parametrize("tool", ALL_ADAPTERS)
def test_root_instruction_file_points_at_the_harness(repo_root, bench_env, tool):
    """A doc nothing references is a doc nobody reads."""
    tgt = load_target(repo_root, "bench")
    roots = [
        a for a in render(repo_root, tool, tgt)
        if a.artifact_kind == "aggregate"
        and a.output_path.name not in {"AGENTS-HARNESS.md", "AGENTS-TICKETING.md"}
    ]
    assert roots, f"{tool} renders no root instruction file"
    assert any("AGENTS-HARNESS.md" in r.content for r in roots), tool


@pytest.mark.parametrize("tool", ALL_ADAPTERS)
def test_aggregates_stay_within_char_budget(repo_root, bench_env, tool):
    """Adding a shared partial costs every adapter at once. antigravity is the
    binding constraint at 15,000 chars."""
    from forge.loader import load_adapter_config

    budget = (load_adapter_config(repo_root, tool).get("limits") or {}).get(
        "max_total_chars"
    )
    if not budget:
        pytest.skip(f"{tool} has no char budget")
    tgt = load_target(repo_root, "bench")
    for a in render(repo_root, tool, tgt):
        if a.artifact_kind == "aggregate":
            assert len(a.content) <= budget, (
                f"{tool}/{a.output_path.name} is {len(a.content)} chars, "
                f"over its {budget} budget"
            )


def test_only_one_adapter_writes_the_scripts(repo_root, bench_env):
    """Seven adapters writing the same scripts/harness/ would race, and each
    would strip the others' manifest rows."""
    tgt = load_target(repo_root, "bench")
    owners = [
        tool for tool in ALL_ADAPTERS
        if any(
            a.artifact_kind == "harness-script"
            for a in render(repo_root, tool, tgt)
        )
    ]
    assert owners == ["claude-code"], owners


def test_opencode_plugin_calls_the_shared_script(repo_root, bench_env):
    """opencode fires the harness differently; it must not reimplement it.
    Two implementations of "is this file clean" drift within a month."""
    tgt = load_target(repo_root, "bench")
    plugin = next(
        a for a in render(repo_root, "opencode", tgt)
        if a.output_path.name == "harness.js"
    )
    assert "check-file.sh" in plugin.content
    assert "tool.execute.after" in plugin.content


def test_antigravity_wires_stop_only(repo_root, bench_env):
    """Its edit payload carries no file path, so a per-file hook would fire,
    find nothing to lint, and exit 0 — indistinguishable from a passing gate."""
    tgt = load_target(repo_root, "bench")
    hooks = next(
        a for a in render(repo_root, "antigravity", tgt)
        if a.output_path.name == "hooks.json"
    )
    data = json.loads(hooks.content)
    assert [h["event"] for h in data["hooks"]] == ["Stop"]


@pytest.mark.parametrize("tool", ["cursor", "cline", "copilot", "codex"])
def test_instruction_only_adapters_emit_no_wiring(repo_root, bench_env, tool):
    """They have no hook mechanism. Emitting an inert wiring file would imply
    enforcement that is not there."""
    tgt = load_target(repo_root, "bench")
    kinds = {a.artifact_kind for a in render(repo_root, tool, tgt)}
    assert SETTINGS_FRAGMENT_KIND not in kinds
    assert "hook-wiring" not in kinds
