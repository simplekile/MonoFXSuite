"""Mono Anim Loader manager window, offscreen with a fake backend (plan Task 9)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from tests.test_anim_loader_controller import FakeBackend  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def make(app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import importlib

    from tools.fx.anim_loader import ui as ui_mod

    importlib.reload(ui_mod)  # PREFS follows APPDATA
    windows = []

    def _make(backend=None):
        w = ui_mod.AnimLoaderManager(backend or FakeBackend())
        w.resize(1100, 640)
        w.wait()
        windows.append(w)
        return w

    yield _make, ui_mod
    for w in windows:
        w.close()


def _rows(view):
    from tools.fx.anim_loader.ui import ROLE_ROW

    return [view.item(i).data(ROLE_ROW) for i in range(view.count()) if view.item(i).data(ROLE_ROW)]


def test_list_shows_every_loader_grouped(make):
    mk, ui = make
    w = mk()
    rows = _rows(w.list_view)
    assert [r.instance for r in rows] == ["char_Helen", "veh_Spaceship", "sh025", "char_Robot_2", "old_robot"]
    headers = [w.list_view.item(i).data(ui.ROLE_HEADER) for i in range(w.list_view.count())
               if w.list_view.item(i).data(ui.ROLE_HEADER)]
    assert headers == ["sh025 · 3", "sh900 · 1", "old loaders · 1"]
    assert w.headline.text() == "2 behind, 1 needs an asset, 1 old loader"
    assert w.primary.text() == "Update 2 behind" and w.primary.isEnabled()
    assert w.upgrade_button.text() == "Upgrade 1 old" and not w.upgrade_button.isHidden()


def test_grid_and_list_hold_the_same_rows_and_the_view_is_remembered(make):
    mk, ui = make
    w = mk()
    w.set_view("grid")
    assert w.stack.currentWidget() is w.grid_view
    assert [r.node_path for r in _rows(w.grid_view)] == [r.node_path for r in _rows(w.list_view)]
    again = mk()
    assert again._view_key == "grid"  # per viewer, from %APPDATA%


def test_selection_changes_the_primary_button(make):
    mk, ui = make
    w = mk()
    target = next(i for i in range(w.list_view.count())
                  if (r := w.list_view.item(i).data(ui.ROLE_ROW)) and r.node_path == "/stage/a")
    w.list_view.item(target).setSelected(True)
    assert w.primary.text() == "Update 1 selected"
    w.primary.click()
    assert w.backend.calls[-1][0] == "update" and w.backend.calls[-1][1] == ("/stage/a",)
    assert "moved" in w.result.text()


def test_chip_words_never_colour_alone(make):
    _, ui = make
    from tools.fx.anim_loader import logic

    assert ui.chip(logic.STATUS_NEWER, "v003", "v002")[0] == "v002 → v003"
    assert ui.chip(logic.STATUS_MISSING, None, "")[0] == "missing"
    assert ui.chip(logic.STATUS_ASSET, None, "")[0] == "asset?"
    assert ui.chip(logic.STATUS_OFF, None, "")[0] == "off"


def test_empty_scene(make):
    mk, _ = make
    b = FakeBackend()
    b.infos = []
    w = mk(b)
    assert w.stack.currentWidget() is w.empty
    assert w.headline.text() == "No anim loaders in the scene"
    assert not w.primary.isEnabled() and w.upgrade_button.isHidden()


def test_paints_at_both_scales(make):
    mk, ui = make
    for scale in (1.0, 1.5):
        w = ui.AnimLoaderManager(FakeBackend(), scale=scale)
        w.resize(400, 760)
        w.wait()
        for view in ("list", "grid"):
            w.set_view(view)
            assert not w.grab().isNull()
        w.close()


def _subd_window(make):
    from tests.test_anim_loader_controller import _subd_backend

    mk, ui = make
    return mk(_subd_backend()), ui


def _select(w, ui, path):
    for i in range(w.list_view.count()):
        r = w.list_view.item(i).data(ui.ROLE_ROW)
        w.list_view.item(i).setSelected(bool(r) and r.node_path == path)


def test_subd_detail_shows_groups_and_meshes(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    tree = w.subd_panel.tree
    groups = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert groups == ["Base_grp", "Outfit_grp"]
    base = tree.topLevelItem(0)
    assert base.text(2) == "mixed" and base.childCount() == 2
    assert "~6.6 M" in w.subd_panel.load.text()


def test_subd_set_on_selection_calls_backend(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/b")
    tree = w.subd_panel.tree
    tree.topLevelItem(0).setSelected(True)
    w.subd_panel.scheme.setCurrentText("Off")
    w.subd_panel.dicing.setText("0.5")
    w.subd_panel.set_button.click()
    assert w.backend.calls[-1] == ("set_subd", "/stage/b", ("Geo/Base_grp/**",), "none", 0.5)


def test_subd_chip_in_rows(make):
    w, ui = _subd_window(make)
    helen = next(r for r in [w.list_view.item(i).data(ui.ROLE_ROW) for i in range(w.list_view.count())]
                 if r and r.node_path == "/stage/b")
    assert ui.subd_chip(helen) == "subd 2 · ~6.6 M"


def test_subd_empty_state(make):
    w, ui = _subd_window(make)
    _select(w, ui, "/stage/c")  # the camera
    assert w.subd_panel.tree.topLevelItemCount() == 0 and "No meshes" in w.subd_panel.title.text()
