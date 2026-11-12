"""The dcc-panel-design skill's contrast checker: WCAG ratios, translucent fills, suggestions, exit codes,
and the suite palette file it ships with."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "dcc-panel-design"


def _load():
    spec = importlib.util.spec_from_file_location("contrast_check", _SKILL / "scripts" / "contrast_check.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


cc = _load()


def test_black_on_white_is_21_and_symmetric() -> None:
    assert cc.ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert cc.ratio((255, 255, 255), (0, 0, 0)) == pytest.approx(21.0)


def test_the_classic_grey_fails_text_and_passes_ui() -> None:
    # #777777 on white is 4.48:1: the textbook just-under-AA pair
    rows = cc.check_pairs([{"label": "a", "fg": "#777777", "bg": "#ffffff", "kind": "text"},
                           {"label": "b", "fg": "#777777", "bg": "#ffffff", "kind": "ui"}])
    assert rows[0]["ratio"] == pytest.approx(4.48, abs=0.01)
    assert rows[0]["pass"] is False and rows[1]["pass"] is True


def test_three_digit_hex_and_bad_colours() -> None:
    assert cc.parse_hex("#fff") == (255, 255, 255)
    with pytest.raises(ValueError):
        cc.parse_hex("#12345")
    with pytest.raises(ValueError):
        cc.resolve({"alpha": 0.5})


def test_translucent_fill_is_composited_over_its_surface() -> None:
    # white at 50 % over black is mid grey
    assert cc.composite("#ffffff", 0.5, "#000000") == (128, 128, 128)
    rows = cc.check_pairs([{"label": "pill", "fg": "#5b8cff",
                            "bg": {"color": "#5b8cff", "alpha": 0.16, "over": "#18181d"}, "kind": "text"}])
    # the fill is darker than the accent text and lighter than the pane
    assert cc.parse_hex(rows[0]["bg"]) > (0x18, 0x18, 0x1d)
    assert rows[0]["ratio"] < cc.ratio(cc.parse_hex("#5b8cff"), cc.parse_hex("#18181d"))


def test_suggest_moves_a_failing_foreground_until_it_passes() -> None:
    rows = cc.check_pairs([{"label": "dim", "fg": "#4a4a53", "bg": "#17171b", "kind": "text"}], want_suggest=True)
    assert rows[0]["pass"] is False
    fixed = rows[0]["suggest"]
    assert fixed and cc.ratio(cc.parse_hex(fixed), cc.parse_hex("#17171b")) >= 4.5
    # a passing pair gets no suggestion
    ok = cc.check_pairs([{"label": "ok", "fg": "#ededf0", "bg": "#17171b"}], want_suggest=True)
    assert "suggest" not in ok[0]


def test_unknown_kind_is_an_error() -> None:
    with pytest.raises(ValueError):
        cc.check_pairs([{"fg": "#fff", "bg": "#000", "kind": "huge"}])


def test_main_exit_codes(tmp_path, capsys) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"pairs": [{"label": "ok", "fg": "#ededf0", "bg": "#17171b", "kind": "text"}]}))
    assert cc.main(["--pairs", str(good)]) == 0
    assert "1 of 1 pass" in capsys.readouterr().out
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"label": "no", "fg": "#4a4a53", "bg": "#17171b", "kind": "text"}]))
    assert cc.main(["--pairs", str(bad), "--suggest"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  -> #" in out and "1 fail" in out
    assert cc.main(["--fg", "#ffffff", "--bg", "#3d6cf0"]) == 0
    assert cc.main(["--fg", "#zzzzzz", "--bg", "#000000"]) == 2
    capsys.readouterr()
    assert cc.main(["--pairs", str(bad), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)[0]["pass"] is False


def test_a_known_failure_is_reported_but_does_not_fail_the_run(tmp_path, capsys) -> None:
    known = tmp_path / "known.json"
    known.write_text(json.dumps([{"label": "dim", "fg": "#62626c", "bg": "#17171b", "kind": "text",
                                  "known_fail": "hidden rows are meant to read as off"}]))
    assert cc.main(["--pairs", str(known)]) == 0
    assert "FAIL (known)" in capsys.readouterr().out


def test_the_suite_palette_file_matches_its_known_failures() -> None:
    """Every pair the skill lists for this suite's palette meets its threshold, except the ones marked
    known_fail (documented in design-system.md). A palette change that breaks another pair fails here
    with the pair's name; one that fixes a known failure fails too, so the mark gets removed."""
    with open(_SKILL / "references" / "palette_pairs.json", encoding="utf-8") as f:
        pairs = json.load(f)["pairs"]
    rows = cc.check_pairs(pairs, want_suggest=True)
    unexpected = [(r["label"], r["ratio"], r.get("suggest")) for r in rows if not r["pass"] and not r["known"]]
    assert not unexpected, unexpected
    now_passing = [r["label"] for r in rows if r["pass"] and r["known"]]
    assert not now_passing, now_passing
