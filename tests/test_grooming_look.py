"""MONO Grooming panel, the MonoFX Loader's look (t74, the user's pick "C", 2026-11-19), offscreen with the fake
adapter: the delegate-painted tree (row colours, hover, selection, branch area, separators), the icon buttons'
tooltips and accessible names, the eye, the status column, the result line, the inspector's sections, no "·"."""

from __future__ import annotations

import pytest

from tools.fx.grooming import controller as ctl
from tools.fx.grooming.layers import SEL_LAYER

from test_grooming_layers import LayerAdapter, _layered


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def prefs(tmp_path, monkeypatch):
    from tools.fx.grooming import ui as ui_mod
    monkeypatch.setattr(ui_mod, "PREFS_PATH", str(tmp_path / "grooming_prefs.json"))
    return ui_mod


def _panel(app, width=1100, height=820):
    from tools.fx.grooming.ui import GroomingUI

    adapter = LayerAdapter()
    ids = _layered(adapter)
    ui = GroomingUI()
    c = ctl.GroomController(adapter, ui)
    ctl.bind(ui, c)
    c.set_node(adapter.node)
    ui.resize(width, height)
    ui.show()
    for _ in range(4):
        app.processEvents()
    return adapter, ui, c, ids


def _grab(ui):
    from PySide6.QtGui import QImage
    tree = ui._tree
    tree.viewport().repaint()
    return tree.viewport().grab().toImage().convertToFormat(QImage.Format.Format_RGB32)


def _hex(img, x, y) -> str:
    return img.pixelColor(x, y).name()


# ---------------------------------------------------------------------------
# The helpers named as in the Loader
# ---------------------------------------------------------------------------
def test_border_px_is_two_at_least_and_follows_the_scale() -> None:
    from tools.fx.grooming.ui_look import _border_px, round_borders, scale_css
    assert [_border_px(s) for s in (0.8, 1.0, 1.5, 2.0, 3.0)] == [2, 2, 2, 3, 4]
    assert round_borders("border: 1px solid red; border-bottom: 1px solid blue;", 2.0) == \
        "border: 3px solid red; border-bottom: 1px solid blue;"
    assert scale_css("padding: 4px; border-bottom: 1px solid x;", 1.5) == "padding: 6px; border-bottom: 1px solid x;"


def test_filled_eye_cuts_its_pupil_out(app) -> None:
    from tools.fx.grooming.ui_look import eye_pixmap
    on = eye_pixmap(True, 24, "#a3a3ae", 1.0).toImage()
    off = eye_pixmap(False, 24, "#a3a3ae", 1.0).toImage()
    assert on.pixelColor(12, 12).alpha() == 0          # the pupil: the row shows through
    assert on.pixelColor(6, 12).alpha() > 200          # the body: solid
    assert off.pixelColor(6, 12).alpha() < 200         # the outline eye is not filled


# ---------------------------------------------------------------------------
# The tree, painted by its delegate
# ---------------------------------------------------------------------------
def test_tree_rows_paint_their_states_and_the_branch_area_follows(app, prefs) -> None:
    from tools.fx.grooming import ui as U
    from tools.fx.grooming.ui_look import SELECTED_HOVER

    adapter, ui, c, ids = _panel(app)
    tree = ui._tree
    sel = ui._rows[(SEL_LAYER, ids["crown"])]
    plain = ui._rows[(SEL_LAYER, ids["soften"])]
    hov = ui._rows[(ctl.SEL_LOCKS, 1)]
    c.select(SEL_LAYER, (ids["crown"],))
    ui.set_selection(c.selection)
    tree._hover = hov
    for _ in range(3):
        app.processEvents()
    img = _grab(ui)
    name_x = lambda it: tree.visualRect(tree.indexFromItem(it, U.COL_NAME)).left() + 2   # noqa: E731: the name cell
    branch_x = lambda it: tree.visualRect(tree.indexFromItem(it, U.COL_NAME)).left() - 4  # noqa: E731: the branch area
    for item, want in ((sel, U.SELECTED), (plain, U.PANE), (hov, U.BG_HOVER)):
        r = tree.visualItemRect(item)
        y = r.top() + 3
        assert _hex(img, name_x(item), y) == want.lower(), item.text(U.COL_NAME)
        assert _hex(img, branch_x(item), y) == want.lower(), "branch area " + item.text(U.COL_NAME)
    assert tree.row_color(tree.indexFromItem(sel)) == U.SELECTED
    tree._hover = sel
    assert tree.row_color(tree.indexFromItem(sel)) == SELECTED_HOVER
    tree._hover = None
    assert tree.row_color(tree.indexFromItem(hov)) == U.PANE
    ui.close()


def test_separators_on_plain_rows_and_covered_on_hover_and_selection(app, prefs) -> None:
    from tools.fx.grooming import ui as U

    adapter, ui, c, ids = _panel(app)
    tree = ui._tree
    sel = ui._rows[(SEL_LAYER, ids["crown"])]
    plain = ui._rows[(SEL_LAYER, ids["soften"])]
    hov = ui._rows[(ctl.SEL_LOCKS, 1)]
    c.select(SEL_LAYER, (ids["crown"],))
    ui.set_selection(c.selection)
    tree._hover = hov
    for _ in range(3):
        app.processEvents()
    img = _grab(ui)
    head = tree.header()
    eye_right = head.sectionViewportPosition(U.COL_EYE) + head.sectionSize(U.COL_EYE) - 1
    status_left = head.sectionViewportPosition(U.COL_STATUS)
    for item, fill, lines in ((plain, U.PANE, True), (sel, U.SELECTED, False), (hov, U.BG_HOVER, False)):
        r = tree.visualItemRect(item)
        mid = r.center().y()
        want = U.LINE if lines else fill
        assert _hex(img, eye_right, mid) == want.lower(), ("eye | name", item.text(U.COL_NAME))
        assert _hex(img, status_left, mid) == want.lower(), ("name | status", item.text(U.COL_NAME))
        assert _hex(img, status_left + 20, r.bottom()) == want.lower(), ("under the row", item.text(U.COL_NAME))
    ui.close()


def test_status_column_takes_its_widest_words_for_every_row(app, prefs) -> None:
    from tools.fx.grooming import ui as U

    adapter, ui, c, ids = _panel(app)
    tree = ui._tree
    cells = tree.itemDelegateForColumn(U.COL_STATUS)
    widest = max(cells.status_width(it.data(U.COL_NAME, U.ROLE_ROW) or {}) for it in ui._rows.values())
    room = tree.viewport().width() - tree.header().sectionSize(U.COL_EYE)
    assert tree.header().sectionSize(U.COL_STATUS) == max(ui.z.px(24), min(widest, int(room * 0.4)))
    auto = ui._rows[(SEL_LAYER, -1)].data(U.COL_NAME, U.ROLE_ROW)
    assert auto["parts"][0][0] == "per lock"                     # it was cut to "each lock's D…"
    ui.close()


def test_eye_cells_fill_when_drawn_and_never_take_the_accent(app, prefs) -> None:
    from tools.fx.grooming import ui as U

    adapter, ui, c, ids = _panel(app)
    shown = ui._rows[(ctl.SEL_LOCKS, 1)].data(U.COL_EYE, U.ROLE_ICON).pixmap(32).toImage()
    c.set_visible(ctl.SEL_LOCKS, [1], False)
    hidden = ui._rows[(ctl.SEL_LOCKS, 1)].data(U.COL_EYE, U.ROLE_ICON).pixmap(32).toImage()
    w = shown.width()
    assert shown.pixelColor(w // 2, w // 2).alpha() == 0 and shown.pixelColor(w // 4, w // 2).alpha() > 200
    assert hidden.pixelColor(w // 4, w // 2).alpha() < 200
    ui.close()


def test_refresh_keeps_scroll_folds_selection_and_current_row(app, prefs) -> None:
    adapter, ui, c, ids = _panel(app, 1100, 420)
    tree = ui._tree
    crown_thin = ui._rows[(SEL_LAYER, ids["crown_thin"])]
    crown_thin.setExpanded(False)
    last = ui._rows[(ctl.SEL_LOCKS, 4)]
    tree.setCurrentItem(last)
    c.select_locks([4])
    ui.set_selection(c.selection)
    tree.verticalScrollBar().setValue(tree.verticalScrollBar().maximum())
    before = tree.verticalScrollBar().value()
    c._last_json = None
    c.refresh()
    for _ in range(3):
        app.processEvents()
    assert not ui._rows[(SEL_LAYER, ids["crown_thin"])].isExpanded()
    assert tree.currentItem() is ui._rows[(ctl.SEL_LOCKS, 4)] and ui._rows[(ctl.SEL_LOCKS, 4)].isSelected()
    assert tree.verticalScrollBar().value() == before
    ui.close()


# ---------------------------------------------------------------------------
# Fewer words: icon buttons with a tooltip and an accessible name
# ---------------------------------------------------------------------------
def test_icon_buttons_say_what_they_do_in_tooltip_and_accessible_name(app, prefs) -> None:
    adapter, ui, c, ids = _panel(app)
    c.select(SEL_LAYER, (ids["crown"],))
    c.paint_on()
    app.processEvents()
    names = {}
    for b in ui._icon_buttons:
        try:
            name, tip = b.accessibleName(), b.toolTip()
        except RuntimeError:   # a Properties button of an earlier selection, deleted
            continue
        assert name and tip and tip.startswith(name), (name, tip)
        assert b.text().strip() == "", name                  # only the primary keeps words
        names[name] = b
    for want in ("Settings", "Dock", "Deform", "Isolate", "X-ray (X)", "Detect locks", "Update regions",
                 "New density layer", "New paint layer", "Move up", "Move down", "Delete", "Scalp X-ray", "Fold"):
        assert want in names, want
    assert ui._publish_btn.text().strip() == "Publish"
    side = ui.z.px(28)
    assert all(b.width() == side and b.height() == side for b in names.values() if b.isVisible())
    ui.close()


def test_view_controls_move_to_the_top_bar_when_wide(app, prefs) -> None:
    adapter, ui, c, ids = _panel(app, 1100)
    assert ui._view_box.parentWidget() is ui._top_view and ui._view_bar.isHidden()
    ui.resize(420, 900)
    for _ in range(3):
        app.processEvents()
    assert ui._view_box.parentWidget() is ui._view_bar and not ui._view_bar.isHidden()
    ui.resize(1100, 820)
    for _ in range(3):
        app.processEvents()
    assert ui._view_box.parentWidget() is ui._top_view
    ui.close()


# ---------------------------------------------------------------------------
# The result line, the inspector, the joiners
# ---------------------------------------------------------------------------
def test_result_line_is_two_lines_at_most_with_the_whole_text_in_its_tooltip(app, prefs) -> None:
    adapter, ui, c, ids = _panel(app, 400, 900)
    long = "Detect locks: 61 locks, 58 ok; " + "a long reason that goes on and on, " * 12 + "the end"
    ui.set_message(long)
    for _ in range(3):
        app.processEvents()
    ui._fit_message()
    label = ui._message_label
    assert ui.message() == long and label.text().endswith("…") and label.toolTip() == long
    assert label.maximumHeight() <= label.fontMetrics().lineSpacing() * 2 + 4
    ui.set_message("Crown: density 75 / cm²")
    assert label.text() == "Crown: density 75 / cm²" and label.toolTip() == ""
    ui.close()


def test_properties_read_as_an_inspector_with_sections_kept_per_viewer(app, prefs) -> None:
    from tools.fx.grooming.ui_look import _Props, _Section

    adapter, ui, c, ids = _panel(app)
    c.select(SEL_LAYER, (ids["crown_thin"],))
    app.processEvents()
    sections = {s.key: s for s in ui._props_widget.findChildren(_Section) if s.isVisible()}
    assert list(sections) == ["details", "values"]
    rows = [p.rows() for p in ui._props_widget.findChildren(_Props) if p.isVisible()]
    assert any(r.get("Kind") == "Density layer" and r.get("Owner") == "All locks" for r in rows)
    sections["details"].click()                                           # fold it: kept in the prefs
    assert prefs.load_prefs().get("inspector_details") is False
    c.select(SEL_LAYER, (ids["soften"],))
    app.processEvents()
    again = {s.key: s for s in ui._props_widget.findChildren(_Section) if s.isVisible()}
    assert not again["details"].isChecked() and again["details"].body.isHidden()
    c.select(SEL_LAYER, (ids["crown"],))                                  # a paint layer: Layer starts folded
    app.processEvents()
    paint = {s.key: s for s in ui._props_widget.findChildren(_Section) if s.isVisible()}
    assert list(paint) == ["brush", "layer_actions", "details"] and not paint["layer_actions"].isChecked()
    ui.close()


def test_no_dot_joins_words_in_the_panel(app, prefs) -> None:
    from PySide6.QtWidgets import QLabel

    adapter, ui, c, ids = _panel(app)
    states = [lambda: c.select(SEL_LAYER, (ids["crown_thin"],)), lambda: c.select(SEL_LAYER, (ids["crown"],)),
              lambda: c.paint_on(), lambda: c.select(SEL_LAYER, (-1,)), lambda: c.select_locks([3]),
              lambda: c.select("group", ("fringe",)), lambda: ui.show_settings(c.settings_info())]
    for go in states:
        go()
        app.processEvents()
        texts = [w.text() for w in ui.findChildren(QLabel) if w.isVisible()] + [ui.windowTitle()]
        assert not [t for t in texts if "·" in t], [t for t in texts if "·" in t]
        for item in ui._rows.values():
            row = item.data(0, ui_role()) or {}
            assert all("·" not in t for t, _c in row.get("parts", [])), row.get("parts")
    ui.close()


def ui_role():
    from tools.fx.grooming.ui import ROLE_ROW
    return ROLE_ROW


def test_a_faint_eye_is_lighter_on_a_selected_row(app, prefs) -> None:
    """FAINT on SELECTED is 2.1-2.4:1 (under the 3:1 of an icon): a selected row draws it in FAINT_ON_SELECTED."""
    from PySide6.QtGui import QColor
    from tools.fx.grooming import ui as U

    adapter, ui, c, ids = _panel(app)
    c.set_visible(ctl.SEL_GROUP, ["fringe"], False)              # its locks: eyes decided by the group (FAINT)
    item = ui._rows[(ctl.SEL_LOCKS, 1)]
    assert item.data(U.COL_EYE, U.ROLE_EYE)[1] == U.FAINT
    tree = ui._tree
    tree.scrollToItem(item)
    app.processEvents()

    def eye_colours():
        img = _grab(ui)
        r = tree.visualRect(tree.indexFromItem(item, U.COL_EYE))
        bg = QColor(tree.row_color(tree.indexFromItem(item)))
        return max(img.pixelColor(x, y).lightness() for x in range(r.left() + 2, r.right() - 2)
                   for y in range(r.top() + 2, r.bottom() - 2))   # the eye's strokes, inside the separators
    plain = eye_colours()
    tree.blockSignals(True)
    item.setSelected(True)
    tree.blockSignals(False)
    selected = eye_colours()
    assert plain <= QColor(U.FAINT).lightness() + 2
    assert selected >= QColor(U.FAINT_ON_SELECTED).lightness() - 12 and selected > plain + 15
    ui.close()


# ---------------------------------------------------------------------------
# The user's asks on the docked panel (2026-11-19)
# ---------------------------------------------------------------------------
def test_picking_a_density_layer_does_not_move_the_rows(app, prefs) -> None:
    """The row bar sits UNDER the tree: above it, showing it on the click pushed the clicked row down."""
    from tools.fx.grooming import ui as U

    adapter, ui, c, ids = _panel(app, 760, 820)
    tree = ui._tree
    c.select(ctl.SEL_LOCKS, (1,))
    for _ in range(4):
        app.processEvents()
    assert ui._row_bar.isHidden()
    item = ui._rows[(SEL_LAYER, ids["crown_thin"])]

    def y() -> int:
        return tree.viewport().mapTo(ui, tree.visualItemRect(item).topLeft()).y()
    before = y()
    c.select(SEL_LAYER, (ids["crown_thin"],))
    for _ in range(4):
        app.processEvents()
    item = ui._rows[(SEL_LAYER, ids["crown_thin"])]
    assert not ui._row_bar.isHidden()
    assert y() == before
    bar_top = ui._row_bar.mapTo(ui, ui._row_bar.rect().topLeft()).y()
    assert bar_top >= tree.mapTo(ui, tree.rect().bottomLeft()).y()     # under the tree
    ui.close()


def test_density_status_shows_the_value_and_its_unit_in_the_tooltip(app, prefs) -> None:
    from tools.fx.grooming import ui as U

    adapter, ui, c, ids = _panel(app)
    item = ui._rows[(SEL_LAYER, ids["crown_thin"])]
    row = item.data(U.COL_NAME, U.ROLE_ROW)
    assert row["parts"][-1][0] == "75"                   # "75 /cm²" was cut to "75 /c…"
    assert "strands / cm²" in item.toolTip(U.COL_STATUS) and "100%" in item.toolTip(U.COL_STATUS)
    ui.close()


def test_buttons_are_filled_and_fields_are_not(app, prefs) -> None:
    """Quick picks read as fields when both were outlined on the pane: a button has a fill, a field stays inset."""
    from PySide6.QtWidgets import QLineEdit, QToolButton

    from tools.fx.grooming import ui_look as K

    adapter, ui, c, ids = _panel(app)
    c.select(SEL_LAYER, (ids["crown_thin"],))
    for _ in range(4):
        app.processEvents()
    pick = next(b for b in ui._props_widget.findChildren(QToolButton) if b.text().strip() == "150")
    field = next(f for f in ui.findChildren(QLineEdit) if f.isVisible() and f is not ui._filter)
    b = pick.grab().toImage()
    f = field.grab().toImage()
    inset = ui.z.px(6)
    assert b.pixelColor(inset, b.height() // 2).name() == K.BUTTON
    assert f.pixelColor(inset, f.height() // 2).name() != K.BUTTON
    ui.close()


def test_a_disabled_icon_button_looks_disabled(app, prefs) -> None:
    """Up / Down / Delete with nothing to act on drew like the usable ones in Houdini (the user, t74)."""
    from tools.fx.grooming import ui_look as K

    adapter, ui, c, ids = _panel(app)
    c.select(ctl.SEL_LOCKS, (1,))
    for _ in range(4):
        app.processEvents()
    tools = ui._layer_tools
    assert not tools["delete"].isEnabled() and tools["density"].isEnabled()

    whole = ui.grab().toImage()          # a button grabbed alone has no pane behind it

    def brightest(b) -> int:
        dpr = whole.devicePixelRatio()
        o = b.mapTo(ui, b.rect().topLeft())
        return max(whole.pixelColor(int((o.x() + x) * dpr), int((o.y() + y) * dpr)).lightness()
                   for x in range(b.width()) for y in range(b.height()))
    from PySide6.QtGui import QColor
    assert brightest(tools["delete"]) <= QColor(K.DISABLED_ICON).lightness() + 8
    assert brightest(tools["density"]) > QColor(K.DISABLED_ICON).lightness() + 40
    ui.close()
