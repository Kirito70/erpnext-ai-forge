"""BRAIN-T14: density, not size, decides whether an app note warns."""

from pathlib import Path

from forge.loader import load_app_notes
from forge.narration import measure


def _note(ticket_bullets: int, filler_bullets: int) -> str:
    rows = [f"- NPOS-D{i}: {'x' * 60}" for i in range(ticket_bullets)]
    rows += [f"- plain domain rule {i}: {'y' * 60}" for i in range(filler_bullets)]
    return "# Note\n\n" + "\n".join(rows) + "\n"


def test_low_density_does_not_warn():
    assert measure("n", _note(1, 40)).warnings() == []


def test_high_density_warns_and_names_lines():
    (w,) = measure("n", _note(10, 30)).warnings()
    assert "ticket detail" in w and "L3" in w


def test_large_clean_file_does_not_warn():
    # size alone must not fire below the file cap (the novizna_crm shape)
    text = _note(0, 200)
    assert len(text) < 24 * 1024
    assert measure("n", text).warnings() == []


def test_long_bullet_warns_with_line():
    text = "# T\n\n- " + "z" * 900 + "\n"
    (w,) = measure("n", text).warnings()
    assert "L3" in w and "bullet" in w


def test_continuation_lines_belong_to_bullet():
    text = "# T\n\n- NPOS-D1 start\n  " + "c" * 100 + "\n- other\n"
    r = measure("n", text)
    assert r.ticket_bytes > 100


def test_live_canonical_notes_flag_only_pos():
    repo = Path(__file__).resolve().parents[2]
    flagged = {
        n for n, note in load_app_notes(repo).items() if measure(n, note.body).warnings()
    }
    assert flagged == {"novizna_pos"}
