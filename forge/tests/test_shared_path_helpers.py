"""One definition each for "which app owns this output" and "where is the bench".

Both questions had two implementations. `_app_for_output` in commands/adopt.py
and `_app_of_output` in sync.py spelled the same guard two different ways
(`idx + 1 < len(parts) - 1` vs `idx + 2 < len(parts)`, algebraically identical),
and `_bench_root` was copied verbatim into commands/adopt.py and commands/apps.py.

Duplication is the finding: nothing forced the copies to agree, so the next edit
to one of them would have been a divergence nobody could see. These tests fail
if a copy comes back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.commands import adopt, apps
from forge.loader import load_target
from forge.sync import app_of_output


def test_adopt_uses_the_shared_app_resolver():
    assert adopt.app_of_output is app_of_output
    assert not hasattr(adopt, "_app_for_output"), "the copy is back"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/bench/apps/novizna_crm/CLAUDE.md", "novizna_crm"),
        ("/bench/apps/novizna_pos/nested/file.md", "novizna_pos"),
        ("/bench/apps/novizna_crm", None),  # the app dir itself owns no output
        ("/bench/apps", None),
        ("/bench/CLAUDE.md", None),
        ("/bench/apps/apps/crm/CLAUDE.md", "crm"),  # the last `apps` wins
    ],
)
def test_app_of_output(path, expected):
    assert app_of_output(Path(path)) == expected


def test_neither_command_keeps_its_own_bench_root():
    for mod in (adopt, apps):
        assert not hasattr(mod, "_bench_root"), f"{mod.__name__} kept a copy"


def test_bench_root_refuses_an_unset_env_var(tmp_path, monkeypatch):
    """The copies did `.replace("{{ env.FORGE_BENCH_PATH }}", os.environ.get(..., ""))`,
    so an unset variable yielded `Path("")` — a relative path that resolves to the
    cwd, which is a real place forge would then write into. `load_target` renders
    with StrictUndefined and refuses instead.
    """
    (tmp_path / "forge.config.yaml").write_text(
        "bench:\n  path: '{{ env.FORGE_BENCH_PATH }}'\nenabled_tools: [claude-code]\n"
    )
    monkeypatch.delenv("FORGE_BENCH_PATH", raising=False)

    with pytest.raises(Exception) as exc:
        load_target(tmp_path)
    assert "FORGE_BENCH_PATH" in str(exc.value) or "root" in str(exc.value).lower()
