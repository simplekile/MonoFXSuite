"""MonoFX Loaders' Add assets drawer: picking, unpicking, filters, drag and double-click (the user's review,
2026-11-22)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from tests.anim_loader_tree import make as make_tree  # noqa: E402


@pytest.fixture
def drawer(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    import importlib

    from tests.test_anim_loader_controller import FakeBackend
    from tools.fx.anim_loader import ui

    importlib.reload(ui)
    root = tmp_path / "proj"
    files = []
    for grp, names in (("_characters", ["char_Ata", "char_Helen", "char_Omen"]), ("_props", ["prop_Cliff01", "prop_Rock"])):
        files += [f"01_assets/{grp}/{n}/01_modelling/03_uv/publish/v001/{n}_uv_publish.usd" for n in names]
    make_tree(root, files)
    b = FakeBackend()
    b.add_assets = lambda r, names: (b.calls.append(("add", tuple(names))) or (list(names), []))
    w = ui.AnimLoaderManager(b)
    w.resize(1100, 700)
    w.show()
    w.wait()
    w._project = str(root)
    w.open_drawer()
    app.processEvents()
    yield w, w.drawer, ui, b
    w.close()


def _card(d, ui, name):
    g = d.list
    i = [g.item(k).data(ui.ROLE_ROW) for k in range(g.count())].index(name)
    return g.visualItemRect(g.item(i)).center()


def _click(d, ui, name, mod=Qt.KeyboardModifier.NoModifier):
    QTest.mouseClick(d.list.viewport(), Qt.MouseButton.LeftButton, mod, _card(d, ui, name))


def test_picks_survive_chips_and_search(drawer):
    w, d, ui, b = drawer
    _click(d, ui, "char_Ata")
    _click(d, ui, "char_Helen")
    d._pick_group("_props")
    assert d.picked() == ["char_Ata", "char_Helen"] and d.add_button.text() == "Add 2"
    assert "2 hidden by the filter" in d.count.text()
    d._pick_group("")
    assert d.picked() == ["char_Ata", "char_Helen"]
    assert {i.data(ui.ROLE_ROW) for i in d.list.selectedItems()} == {"char_Ata", "char_Helen"}
    d.search.setText("Omen")
    _click(d, ui, "char_Omen")
    d.search.setText("")
    assert d.picked() == ["char_Ata", "char_Helen", "char_Omen"]


def test_add_clears_the_picks(drawer):
    w, d, ui, b = drawer
    _click(d, ui, "char_Ata")
    d.add_button.click()
    assert ("add", ("char_Ata",)) in b.calls
    w.open_drawer()
    assert d.picked() == [] and d.add_button.text() == "Add"


def test_shift_click_picks_a_range_and_clear_unpicks_all(drawer):
    w, d, ui, b = drawer
    _click(d, ui, "char_Helen")
    _click(d, ui, "prop_Cliff01", Qt.KeyboardModifier.ShiftModifier)
    assert set(d.picked()) == {"char_Helen", "char_Omen", "prop_Cliff01"}
    assert not d.clear_link.isHidden()
    d.clear_link.click()
    assert d.picked() == [] and not d.list.selectedItems() and d.clear_link.isHidden()


def test_double_click_adds_that_asset_and_keeps_the_drawer(drawer):
    w, d, ui, b = drawer
    _click(d, ui, "char_Ata")
    _click(d, ui, "char_Omen")  # a real double-click: a click, then the double-click
    QTest.mouseDClick(d.list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      _card(d, ui, "char_Omen"))
    assert ("add", ("char_Omen",)) in b.calls
    assert d.picked() == ["char_Ata"] and not d.isHidden()


def test_a_drag_from_an_unpicked_card_carries_it_alone(drawer):
    w, d, ui, b = drawer
    g = d.list
    _click(d, ui, "char_Ata")
    _click(d, ui, "char_Helen")
    omen = g.item([g.item(k).data(ui.ROLE_ROW) for k in range(g.count())].index("char_Omen"))
    assert g.drag_names(omen, was_picked=False) == ["char_Omen"]
    helen = g.item(1)
    assert g.drag_names(helen, was_picked=True) == ["char_Ata", "char_Helen"]
    d._pick_group("_props")  # a filter hides them: a drag of a pick still carries every pick
    rock = g.item(0)
    rock.setSelected(True)
    assert g.drag_names(rock, was_picked=True) == ["char_Ata", "char_Helen", rock.data(ui.ROLE_ROW)]


def test_cards_say_in_the_scene_after_an_add(drawer):
    w, d, ui, b = drawer
    d.refresh_badges()
    texts = [d.list.item(k).text() for k in range(d.list.count())]
    assert all("UV v001" in t for t in texts)
    assert "drag to place" in d.count.text()
