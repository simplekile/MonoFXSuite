"""Heavy-shot prompt (non-modal), offscreen: Draw Hulls Only, Later, Don't ask again."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def ui(app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import importlib

    from tools.fx.anim_loader import ui as ui_mod

    importlib.reload(ui_mod)
    return ui_mod


def test_hulls_button_calls_back_and_closes(ui):
    calls = []
    p = ui.HeavyShotPrompt("Heavy shot: ~9.9 M subdivision polygons (char_Helen)", on_hulls=lambda: calls.append(1))
    p.show()
    assert not p.isModal()
    p.hulls_button.click()
    assert calls == [1] and not p.isVisible()


def test_dont_ask_again_is_saved(ui):
    p = ui.HeavyShotPrompt("x", on_hulls=lambda: None)
    p.dont_ask.setChecked(True)
    p.later_button.click()
    assert ui.prompt_allowed() is False


def test_prompt_allowed_by_default_and_auto_hides(ui):
    assert ui.prompt_allowed() is True
    p = ui.HeavyShotPrompt("x", on_hulls=lambda: None, hide_after_ms=10)
    p.show()
    QtWidgets.QApplication.processEvents()
    import time
    time.sleep(0.05)
    QtWidgets.QApplication.processEvents()
    assert not p.isVisible()


# --- loaders behind when the scene opens (the user's ask, 2026-11-19) ----------------------------------

ITEMS = [("char_Helen", [("anim", "v005", "v006"), ("groom", "v002", "v003")]), ("cam_sh025", [("anim", "v005", "v006")])]


def test_outdated_prompt_lists_and_updates(ui):
    calls = []
    p = ui.OutdatedPrompt(ITEMS, "E:/p/sh025_lighting_v004.hiplc", lambda: calls.append("update"),
                          lambda: calls.append("open"))
    p.show()
    assert not p.isModal()
    assert p.title.text().startswith("2 loaders behind")
    assert p.update_button.text() == "Update 2"
    p.update_button.click()
    assert calls == ["update"] and not p.isVisible()


def test_dont_show_again_holds_for_these_versions_only(ui):
    hip = "E:/p/sh025_lighting_v004.hiplc"
    p = ui.OutdatedPrompt(ITEMS, hip, lambda: None, lambda: None)
    p.dont_ask.setChecked(True)
    p.later_button.click()
    sig = ui.outdated_dismissed(hip)
    assert sig and not ui.logic.outdated_shows(ITEMS, sig)
    assert ui.logic.outdated_shows(ITEMS, "")  # another scene: nothing dismissed there
    assert ui.outdated_dismissed("E:/p/other.hiplc") == ""
    # Helen updated, the camera still behind at the version dismissed: quiet
    assert not ui.logic.outdated_shows([ITEMS[1]], sig)
    # a newer publish than the one dismissed: shown again
    newer = [("cam_sh025", [("anim", "v005", "v007")])]
    assert ui.logic.outdated_shows(newer, sig)


def test_a_scene_brought_up_to_date_drops_its_dismissal(ui, monkeypatch):
    import sys
    import types

    hou = types.SimpleNamespace(isUIAvailable=lambda: False)
    monkeypatch.setitem(sys.modules, "hou", hou)
    hip = "E:/p/sh025_lighting_v004.hiplc"
    ui.set_outdated_dismissed(hip, ui.logic.outdated_signature(ITEMS))
    assert ui.show_outdated_prompt([], hip, None, None) is False
    assert ui.outdated_dismissed(hip) == ""  # the same versions published again later show the prompt


def test_prompts_stack(ui):
    parent = QtWidgets.QWidget()
    parent.setGeometry(0, 0, 1400, 900)
    ui._show_prompt("hulls", lambda: ui.HeavyShotPrompt("Heavy shot", lambda: None, parent))
    ui._show_prompt("outdated", lambda: ui.OutdatedPrompt(ITEMS, "x.hip", lambda: None, lambda: None, parent))
    QtWidgets.QApplication.processEvents()
    hulls, outdated = ui._PROMPTS["hulls"], ui._PROMPTS["outdated"]
    assert outdated.geometry().bottom() < hulls.geometry().top()  # loaders behind above the heavy shot
    hulls.later_button.click()
    QtWidgets.QApplication.processEvents()
    assert not hulls.isVisible()
    assert abs(outdated.geometry().bottom() - (parent.geometry().bottom() - 48)) <= 1  # moved down into its place
    outdated.close()


def test_refresh_manager_without_a_window(ui):
    ui._WINDOW = None
    assert ui.refresh_manager() is False
