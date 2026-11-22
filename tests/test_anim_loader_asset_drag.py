"""Dragging assets out of MonoFX Loaders' Add assets (the user's ask, 2026-11-22): the drag carries one
``<asset>.monofx_asset`` file per asset; the loaders list, a Network Editor and a Scene Viewer take them in."""

from __future__ import annotations

import os

import pytest

from tools.fx.anim_loader import logic as lg


def test_drag_files_name_project_and_asset(tmp_path):
    files = lg.write_asset_drags(tmp_path / "drag", "P:/proj", ["char_Helen", "prop_Cliff05"])
    assert [os.path.basename(f) for f in files] == ["char_Helen.monofx_asset", "prop_Cliff05.monofx_asset"]
    assert all(lg.is_asset_drag(f) for f in files) and not lg.is_asset_drag("C:/x/char_Helen_uv_publish.usd")
    assert lg.read_asset_drags([*files, "C:/x/a.usd", files[0]]) == {"P:/proj": ["char_Helen", "prop_Cliff05"]}


def test_drag_drop_hands_asset_drags_to_the_loader_even_with_drops_off(monkeypatch):
    """Never back to Houdini (it would open the file as a scene), whatever the drop setting says."""
    from apps.houdini import drag_drop

    seen = []
    monkeypatch.setattr(drag_drop, "hou", object())
    fake = type("M", (), {"drop_assets": staticmethod(lambda files: seen.append(files) or True)})
    monkeypatch.setitem(__import__("sys").modules, "apps.houdini.anim_loader_adapter", fake)
    monkeypatch.setattr(drag_drop.drop_prefs, "load_prefs", lambda: {"enabled": False})
    assert drag_drop.handle_drop(["C:/t/char_Helen.monofx_asset"]) is True
    assert seen == [["C:/t/char_Helen.monofx_asset"]]


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_the_drawer_drags_its_cards_and_the_list_takes_them(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication, QListWidgetItem

    QApplication.instance() or QApplication([])
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import importlib

    from tests.test_anim_loader_controller import FakeBackend
    from tools.fx.anim_loader import ui

    importlib.reload(ui)
    monkeypatch.setattr(ui, "DRAG_FOLDER", tmp_path / "drag")
    grid = ui._AssetGrid()
    grid.root = "P:/proj"
    items = []
    for name in ("char_Helen", "prop_Cliff05"):
        it = QListWidgetItem(name)
        it.setData(ui.ROLE_ROW, name)
        grid.addItem(it)
        items.append(it)
    mime = grid.mimeData(items)
    files = [u.toLocalFile() for u in mime.urls()]
    assert [os.path.basename(f) for f in files] == ["char_Helen.monofx_asset", "prop_Cliff05.monofx_asset"]

    b = FakeBackend()
    b.add_assets = lambda root, names: (b.calls.append(("add_assets", root, tuple(names))) or (list(names), []))
    w = ui.AnimLoaderManager(b)
    w.ctl.target_root = "P:/proj"
    w.wait()
    drop = QMimeData()
    drop.setUrls([QUrl.fromLocalFile(f) for f in files])
    ev = QDropEvent(QPointF(QPoint(40, 40)), Qt.DropAction.CopyAction, drop, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    assert w.eventFilter(w.list_view.viewport(), ev) is True
    QApplication.processEvents()
    assert ("add_assets", "P:/proj", ("char_Helen", "prop_Cliff05")) in b.calls
    other = QMimeData()
    other.setUrls([QUrl.fromLocalFile("C:/x/a.usd")])
    ev2 = QDropEvent(QPointF(QPoint(40, 40)), Qt.DropAction.CopyAction, other, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    assert w.eventFilter(w.list_view.viewport(), ev2) is False  # not ours: the list does what it did
    w.close()


def test_pressing_an_unpicked_card_and_moving_drags_it(tmp_path, monkeypatch):
    """The user's report: a press on a card that was not picked and a move drew a marquee instead of a drag."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QListView, QListWidgetItem

    QApplication.instance() or QApplication([])
    from tools.fx.anim_loader import ui

    grid = ui._AssetGrid()
    grid.setViewMode(QListView.ViewMode.IconMode)
    grid.setSelectionMode(ui.QAbstractItemView.SelectionMode.MultiSelection)
    grid.resize(400, 300)
    grid.root = "P:/proj"
    for name in ("char_Helen", "prop_Cliff05"):
        it = QListWidgetItem(name)
        it.setData(ui.ROLE_ROW, name)
        grid.addItem(it)
    grid.show()
    QTest.qWaitForWindowExposed(grid)
    started = []
    grid.start_asset_drag = lambda item: started.append(item.data(ui.ROLE_ROW))
    first = grid.visualItemRect(grid.item(0)).center()
    QTest.mousePress(grid.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first)
    QTest.mouseMove(grid.viewport(), first + QPoint(QApplication.startDragDistance() + 5, 0))
    QTest.mouseRelease(grid.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       first + QPoint(QApplication.startDragDistance() + 5, 0))
    assert started == ["char_Helen"]
    empty = QPoint(390, 290)  # the empty space: still the marquee, no drag
    QTest.mousePress(grid.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, empty)
    QTest.mouseMove(grid.viewport(), empty - QPoint(30, 30))
    QTest.mouseRelease(grid.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       empty - QPoint(30, 30))
    assert started == ["char_Helen"]
    grid.close()
