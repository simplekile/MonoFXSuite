"""Auto Material window, offscreen: states that must never stick."""

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
    from tools.fx.auto_material.ui import AutoMaterialUI

    window = AutoMaterialUI()
    yield window
    window.close()


def test_work_before_the_window_shows_does_not_stick(ui) -> None:
    # The first source is read before ui.show(): nothing is visible yet.
    ui.show_loading("Reading Painter exports...")
    ui.hide_loading()
    ui.show()
    QtWidgets.QApplication.processEvents()
    assert not ui._busy.isVisible()
    assert ui._body.isEnabled() and ui._top.isEnabled()


def test_cancel_is_reported_then_cleared(ui) -> None:
    ui.show()
    ui.show_loading("Updating 1/2")
    ui._cancel_btn.click()
    assert ui.is_cancelled()
    ui.hide_loading()
    assert not ui.is_cancelled()
    assert ui._body.isEnabled()
