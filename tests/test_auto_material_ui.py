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


def test_reading_leaves_the_window_free(ui) -> None:
    ui.show()
    ui.show_reading("Reading Painter exports…")
    assert ui._busy.isVisible() and not ui._cancel_btn.isVisible()
    assert ui._body.isEnabled() and ui._top.isEnabled() and not ui.is_blocking()
    # A scene write while reading blocks; when it ends the read is still shown
    ui.show_loading("Updating 1/1")
    assert ui.is_blocking() and not ui._body.isEnabled()
    ui.hide_loading()
    assert ui._busy.isVisible() and ui._body.isEnabled()
    ui.hide_reading()
    assert not ui._busy.isVisible()


def test_thumbnails_load_off_the_main_thread(app, tmp_path) -> None:
    import time

    from PySide6.QtGui import QColor, QImage

    from tools.fx.auto_material.ui import _Thumbnails

    image = QImage(64, 32, QImage.Format.Format_RGB32)
    image.fill(QColor("#b88a73"))
    path = tmp_path / "M_Body_BaseColor_sRGB.1001.png"
    image.save(str(path))
    ready = []
    thumbs = _Thumbnails(lambda: ready.append(1))
    udim = str(tmp_path / "M_Body_BaseColor_sRGB.<UDIM>.png")
    assert thumbs.get(udim) is None  # asked for: comes later
    end = time.time() + 5
    while not ready and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    pm = thumbs.get(udim)
    assert pm is not None and not pm.isNull()
