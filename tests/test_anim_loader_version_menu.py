"""MonoFX Loaders: the Anim / Model column and the version menu on a cell (the user's picks, 2026-11-22)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from tests.test_anim_loader_ui import app, make  # noqa: E402,F401  (fixtures)
from tools.fx.anim_loader.logic import VersionPick  # noqa: E402


def _backend():
    from tests.test_anim_loader_controller import FakeBackend

    b = FakeBackend()
    b.version_picks = lambda path, part: [VersionPick("V010", "2026-11-20 10:00", "Mai"),
                                          VersionPick("V009", "2026-11-12 09:00", "Mai", current=True),
                                          VersionPick("V008", "2026-11-02 09:00", "", holds=False)]
    b.set_part_version = lambda paths, part, v: (b.calls.append(("set_version", tuple(paths), part, v))
                                                 or ([f"{p.rsplit('/', 1)[-1]}: {part} V009 -> {v}" for p in paths], []))
    return b


def _item(w, ui, path):
    return next(w.list_view.item(i) for i in range(w.list_view.count())
                if (r := w.list_view.item(i).data(ui.ROLE_ROW)) and r.node_path == path)


def test_the_first_column_is_anim_or_model(make):  # noqa: F811 (the fixture)
    _, ui = make
    assert ui.COLUMNS[0][:2] == ("anim", "Anim / Model")
    row = type("R", (), {"asset_source": True, "kind": "geo"})()
    assert ui.part_word(row, "anim") == "model"


def test_version_menu_lists_the_disk_and_sets_the_pick(make):  # noqa: F811 (the fixture)
    mk, ui = make
    w = mk(_backend())
    row = _item(w, ui, "/stage/b").data(ui.ROLE_ROW)
    menu = w.version_menu(row, "lookdev", ["/stage/b"])
    acts = [a for a in menu.actions() if a.text() and not a.isSeparator()]
    texts = [a.text().split("\t") for a in acts]
    year = __import__("datetime").date.today().year
    short = "11-20" if year == 2026 else "2026-11-20"
    assert texts[0] == ["V010", f"{short}  Mai"]  # compact: no header band, no year this year
    assert texts[1][0] == "V009" and not acts[1].icon().isNull()  # current: checked
    assert texts[2] == ["V008", f"no {row.instance}"] and not acts[2].isEnabled()
    assert texts[-1] == ["Open folder"]
    acts[0].trigger()
    assert w.backend.calls[-1] == ("set_version", ("/stage/b",), "lookdev", "V010")
    assert w.result.text().endswith("lookdev V010.")


def test_only_the_cells_dropdown_arrow_opens_the_versions(make):  # noqa: F811 (the fixture)
    from PySide6.QtCore import QPoint, QRect, Qt
    from PySide6.QtTest import QTest

    mk, ui = make
    w = mk(_backend())
    w.show()
    opened = []
    w._open_version_menu = lambda view, row, part, paths, pos: opened.append((row.node_path, part, tuple(paths)))
    for p in ("/stage/a", "/stage/b"):
        _item(w, ui, p).setSelected(True)
    view = w.list_view
    rect = view.visualItemRect(_item(w, ui, "/stage/b"))
    cols, _ = view.itemDelegate().columns(rect)
    cell = cols["lookdev"]
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(cell.center().x() - 10, rect.top() + 20))  # the cell's text: a plain select
    QTest.qWait(10)
    assert opened == [] and w.ctl.selection == ["/stage/b"]
    for p in ("/stage/a", "/stage/b"):
        _item(w, ui, p).setSelected(True)
    arrow = view.itemDelegate().arrow_rect(QRect(cell.left(), rect.top(), cell.width(), w.px(40)))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, arrow.center())
    QTest.qWait(10)
    assert [(r, part, set(ps)) for r, part, ps in opened] == [("/stage/b", "lookdev", {"/stage/a", "/stage/b"})]
    assert set(w.ctl.selection) == {"/stage/a", "/stage/b"}
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(rect.left() + 120, rect.top() + 20))  # the name: a plain select, no menu
    QTest.qWait(10)
    assert len(opened) == 1 and w.ctl.selection == ["/stage/b"]
    w.hide()


def test_list_columns_menu_stays_open_and_hides_a_column(make):  # noqa: F811 (the fixture)
    """The user's asks: right-click the list's header to turn columns on and off; the menu stays open while
    toggling, remembered per viewer."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    mk, ui = make
    w = mk(_backend())
    menu = w.list_columns_menu()
    menu.popup(w.mapToGlobal(w.rect().center()))
    QTest.qWaitForWindowExposed(menu)
    groom = next(a for a in menu.actions() if a.text() == "Groom")
    assert groom.data() == "shown"
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(groom).center())
    assert menu.isVisible() and groom.data() == "" and groom.icon().isNull()  # still open, check gone
    delegate = w.list_view.itemDelegate()
    assert "groom" not in [k for k, _, _ in delegate.visible_columns(0)]
    assert w.prefs["list_hidden_columns"] == ["groom"]
    menu.close()
    assert mk(_backend()).list_view.itemDelegate().hidden == {"groom"}  # remembered


def test_a_narrow_list_stays_a_table_and_scrolls(make):  # noqa: F811 (the fixture)
    """The user's ask: a narrow window scrolls the table sideways instead of moving the versions to a second line."""
    mk, ui = make
    w = mk(_backend())
    w.resize(420, 640)
    w.show()
    item = _item(w, ui, "/stage/b")
    assert w.list_view.itemDelegate().sizeHint(None, w.list_view.indexFromItem(item)).height() == w.px(40)
    assert w.list_view.itemDelegate().sizeHint(None, w.list_view.indexFromItem(item)).width() \
        >= w.list_view.itemDelegate().table_width()
    w.hide()


def test_a_narrower_prim_column_gives_its_room_to_the_last_column(make):  # noqa: F811 (the fixture)
    """The user's report: dragging PRIM narrower left an empty strip on the right; SCHEME takes it now."""
    from tests.test_anim_loader_select_sync import _two_loader_window

    w, ui, b = _two_loader_window(make)
    w.resize(1600, 700)  # an inspector wide enough that nothing scrolls sideways
    w.show()
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    p = w.subd_panel
    t = p.tree
    p._fit_name()
    vp = t.viewport().width()

    def used():
        return sum(t.columnWidth(c) for c in range(ui.COLS) if not t.isColumnHidden(c))

    p._fit_name()
    scheme = p._content_w[3]  # SCHEME's own width
    assert t.columnWidth(3) == scheme and used() > vp  # PRIM at its 170 px: the tree scrolls sideways
    p._name_width = w.px(60)  # dragged narrow (what _section_resized records)
    p._fit_name()
    assert t.columnWidth(0) == w.px(60) and used() == vp and t.columnWidth(3) > scheme  # SCHEME takes the room
    p._fit_name()  # a refresh keeps the dragged width
    assert t.columnWidth(0) == w.px(60) and used() == vp
    w.hide()


def test_top_icons_stay_together_when_the_crumbs_have_their_own_row(make):  # noqa: F811 (the fixture)
    """The user's report: with the crumbs on their own row (narrow), the top bar's icon buttons drew far apart."""
    from PySide6.QtWidgets import QApplication

    mk, ui = make
    w = mk(_backend())
    w.resize(440, 700)  # the left column under 560 px: the crumbs go to their own row
    w.show()
    QApplication.processEvents()
    w._place_nav()
    QApplication.processEvents()
    assert w.nav_row.isVisible()  # narrow: the crumbs on their own row
    buttons = [w.viewport_button, *w.view_buttons.buttons(), w.refresh_button, w.load_button]
    widths = {b.width() for b in buttons}
    assert max(widths) <= w.px(40), widths  # each keeps its own size
    gaps = [b.geometry().left() - a.geometry().right() for a, b in zip(buttons, buttons[1:])]
    assert max(gaps) <= w.px(16), gaps  # side by side, not spread over the bar
    w.hide()


def test_plus_opens_add_assets_at_once(make):  # noqa: F811 (the fixture)
    """The user's ask: no menu on +, the Add assets drawer opens (a second click closes it)."""
    mk, ui = make
    w = mk(_backend())
    w._project = "P:/proj"
    w.load_button.setEnabled(True)
    w.load_button.click()
    assert w._drawer_open and not w.drawer.isHidden()
    w.load_button.click()
    assert not w._drawer_open


def test_panel_size_follows_houdini_text_by_default(make):  # noqa: F811 (the fixture)
    """The user's report: the window read big next to Houdini. Houdini's text is 12 px at scale 1, the panel's body
    14: "Like Houdini" (the default) draws at 12 / 14 of Houdini's scale; Medium is the size before."""
    mk, ui = make
    assert ui.panel_size() == "houdini"
    assert abs(ui.panel_scale(1.5) - 1.5 * 12 / 14) < 1e-9
    w = mk(_backend())
    menu = w.list_columns_menu()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts[-3:] == ["Like Houdini", "Medium", "Large"]
    next(a for a in menu.actions() if a.text() == "Medium").trigger()
    assert ui.panel_size() == "medium" and ui.panel_scale(1.5) == 1.5


def test_details_sit_at_the_bottom_of_the_inspector(make):  # noqa: F811 (the fixture)
    """The user's ask: Details under the prim tree, at the bottom; the prims right under the name."""
    from PySide6.QtWidgets import QApplication

    from tests.test_anim_loader_select_sync import _two_loader_window

    w, ui, b = _two_loader_window(make)
    w.show()
    QApplication.processEvents()
    p = w.subd_panel
    tree_bottom = p.tree.mapTo(p, p.tree.rect().bottomLeft()).y()
    head_top = p.details_head.mapTo(p, p.details_head.rect().topLeft()).y()
    title_bottom = p.title.mapTo(p, p.title.rect().bottomLeft()).y()
    assert title_bottom < p.tree.mapTo(p, p.tree.rect().topLeft()).y() < tree_bottom < head_top
    w.hide()
