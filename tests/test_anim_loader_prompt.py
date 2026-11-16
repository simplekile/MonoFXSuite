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
