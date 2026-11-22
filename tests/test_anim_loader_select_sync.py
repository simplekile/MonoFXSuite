"""Selection follows between the Scene Viewer and the MonoFX Loaders inspector tree (the user's ask, 2026-11-22)."""

from __future__ import annotations

import os

import pytest

from tools.fx.anim_loader import logic as lg


def test_row_prim_names_the_stage_prim():
    assert lg.row_prim("/char_Helen", "Geo/Base_grp/Geo_Body") == "/char_Helen/Geo/Base_grp/Geo_Body"
    assert lg.row_prim("/char_Helen", "Geo/**") == "/char_Helen/Geo"
    assert lg.row_prim("/char_Helen", "**") == "/char_Helen"
    assert lg.row_prim("", "Geo/**") == "/Geo"  # Prim Name off: the publish's own root prims
    assert lg.row_prim("", "**") == ""


def test_prims_go_to_the_loader_that_holds_them():
    roots = {"/stage/a": "/char_Helen", "/stage/b": "/char_Helen_inst02", "/stage/c": ""}
    tops = {"/stage/c": {"Geo", "Groom"}}
    got = lg.prims_by_loader(["/char_Helen_inst02/Geo/Body", "/char_Helen/Geo", "/char_Helen",
                              "/Geo/Rock[3]", "/lights/key"], roots, tops)
    assert got == {"/stage/b": ["Geo/Body"], "/stage/a": ["Geo", ""], "/stage/c": ["Geo/Rock"]}


def test_a_pick_below_the_tree_selects_its_nearest_row():
    rows = {"Geo", "Geo/Base_grp", "Geo/Base_grp/Geo_Body"}
    assert lg.nearest_row("Geo/Base_grp/Geo_Body/subset_skin", rows) == "Geo/Base_grp/Geo_Body"
    assert lg.nearest_row("Geo/Base_grp", rows) == "Geo/Base_grp"
    assert lg.nearest_row("", rows) is None
    assert lg.nearest_row("", rows | {lg.ROOT}) == lg.ROOT


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from tests.test_anim_loader_ui import _two_loader_window, app, make  # noqa: E402,F401  (fixtures)


def _viewport(b, roots):
    """A fake Scene Viewer on /stage that takes what the manager sets."""
    vp = {"/stage": ()}
    b.viewport_prims = lambda: dict(vp)
    b.instance_roots = lambda paths: {p: roots[p] for p in paths if p in roots}
    b.select_prims = lambda net, prims: vp.__setitem__(net, tuple(prims)) or True
    return vp


def _names(p):
    return sorted(i.text(0) for i in p.tree.selectedItems())


def test_a_viewport_pick_selects_its_row_and_its_loader(make):  # noqa: F811 (the fixture)
    w, ui, b = _two_loader_window(make)
    vp = _viewport(b, {"/stage/b": "/char_Helen", "/stage/a": "/veh_Spaceship"})
    p = w.subd_panel
    # one loader in the list; a mesh of the other picked in the viewport: the list follows, then the row
    for i in range(w.list_view.count()):
        r = w.list_view.item(i).data(ui.ROLE_ROW)
        w.list_view.item(i).setSelected(bool(r) and r.node_path == "/stage/b")
    vp["/stage"] = ("/veh_Spaceship/Geo/Hull_grp/Geo_Wing",)
    w.sync_from_viewport(force=True)
    assert w.ctl.selection == ["/stage/a"] and _names(p) == ["Geo_Wing"]
    # a subset under a mesh picks the mesh; a group picks the group row; nothing of a loader clears the rows
    vp["/stage"] = ("/veh_Spaceship/Geo/Hull_grp/Geo_Hull/skin", "/veh_Spaceship/Geo/Hull_grp")
    w.sync_from_viewport(force=True)
    assert _names(p) == ["Geo_Hull", "Hull_grp"]
    vp["/stage"] = ("/lights/key",)
    w.sync_from_viewport(force=True)
    assert _names(p) == [] and w.ctl.selection == ["/stage/a"]  # the list keeps its loader


def test_rows_picked_in_the_tree_select_their_prims_in_the_viewport(make):  # noqa: F811 (the fixture)
    w, ui, b = _two_loader_window(make)
    vp = _viewport(b, {"/stage/b": "/char_Helen", "/stage/a": ""})  # veh_Spaceship with Prim Name off
    p = w.subd_panel
    body = next(i for i in p._all_items() if i.text(0) == "Geo_Body")
    hull = next(i for i in p._all_items() if i.text(0) == "Hull_grp")
    body.setSelected(True)
    hull.setSelected(True)
    assert set(vp["/stage"]) == {"/char_Helen/Geo/Base_grp/Body_grp/Geo_Body", "/Geo/Hull_grp"}
    w.sync_from_viewport(force=True)  # reading back what was set changes nothing
    assert _names(p) == ["Geo_Body", "Hull_grp"]
    # the viewport's pick under a Prim Name off loader finds it by its top prims
    vp["/stage"] = ("/Geo/Hull_grp/Geo_Wing",)
    w.sync_from_viewport(force=True)
    assert _names(p) == ["Geo_Wing"]
    calls = []
    b.select_prims = lambda net, prims: calls.append(prims) or True
    w.refresh()  # a rebuild of the tree sends nothing to the viewport
    w.wait()
    assert calls == []


def test_only_loaders_the_display_node_draws_take_part(make):  # noqa: F811 (the fixture)
    """The user's case: the display flag on one node, another node selected. The viewer draws the display node's
    stage, so a pick belongs only to loaders feeding it, and rows of a loader outside it select nothing there."""
    w, ui, b = _two_loader_window(make)
    vp = _viewport(b, {"/stage/b": "/char_Helen", "/stage/a": "/char_Helen"})  # same root, two branches
    b.displayed_loaders = lambda net: ["/stage/merge1", "/stage/a"]
    p = w.subd_panel
    vp["/stage"] = ("/char_Helen/Geo/Hull_grp/Geo_Hull",)
    w.sync_from_viewport(force=True)
    assert _names(p) == ["Geo_Hull"]  # veh_Spaceship (/stage/a), not char_Helen under the same root
    for i in range(w.list_view.count()):
        r = w.list_view.item(i).data(ui.ROLE_ROW)
        w.list_view.item(i).setSelected(bool(r) and r.node_path == "/stage/b")
    next(i for i in p._all_items() if i.text(0) == "Geo_Body").setSelected(True)
    assert vp["/stage"] == () and "not in what the viewport draws" in w.result.text()


def test_a_root_moved_by_the_shot_layout_is_found_on_the_drawn_stage():
    """sh025: merge_actors grafts the loaders under /World/anim/actors, so /char_Helen is drawn elsewhere."""
    drawn = {"": {"World", "lights"}, "/World": {"anim"}, "/World/anim": {"actors", "env"},
             "/World/anim/actors": {"char_Helen", "char_Helen_inst02"},
             "/World/anim/actors/char_Helen": {"Geo", "Groom"}, "/World/anim/actors/char_Helen_inst02": {"Geo"},
             "/World/anim/env": {"Geo"}, "/lights": {"key"}, "/veh_Spaceship": {"Geo"}}
    got = lg.drawn_roots(drawn, {"/stage/a": ("/char_Helen", ["Geo", "Groom"]),
                                 "/stage/b": ("/char_Helen_inst02", ["Geo"]),
                                 "/stage/s": ("/veh_Spaceship", ["Geo"]),  # not moved
                                 "/stage/e": ("", ["Geo"]),  # Prim Name off: /Geo under many prims, no one place
                                 "/stage/x": ("/char_Gone", ["Geo"])})
    assert got == {"/stage/a": "/World/anim/actors/char_Helen", "/stage/b": "/World/anim/actors/char_Helen_inst02",
                   "/stage/s": "/veh_Spaceship"}
    assert lg.drawn_roots({"": {"Geo"}, "/Geo": {"Body"}}, {"/stage/e": ("", ["Geo"])}) == {"/stage/e": ""}


def test_shift_or_ctrl_click_on_an_arrow_folds_a_whole_branch_or_the_tree(make):  # noqa: F811 (the fixture)
    """The user's ask: fold / unfold everything with a modifier on the arrow."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    w, ui, b = _two_loader_window(make)
    w.show()
    t = w.subd_panel.tree
    items = list(w.subd_panel._all_items())
    groups = [i for i in items if i.childCount()]
    helen = next(i for i in items if i.text(0) == "char_Helen")
    space = next(i for i in items if i.text(0) == "veh_Spaceship")

    def click(item, mod):
        index = t.indexFromItem(item, 0)
        t.scrollTo(index)
        rect = t.visualRect(index)
        assert t.on_chevron(index, rect.left() - 2) and not t.on_chevron(index, rect.left() + 4)
        QTest.mouseClick(t.viewport(), Qt.MouseButton.LeftButton, mod, QPoint(rect.left() - 2, rect.center().y()))

    def under(item):
        out, todo = [], [item.child(i) for i in range(item.childCount())]
        while todo:
            it = todo.pop()
            if it.childCount():
                out.append(it)
            todo += [it.child(i) for i in range(it.childCount())]
        return out

    assert all(g.isExpanded() for g in groups)
    click(helen, Qt.KeyboardModifier.ShiftModifier)  # Helen and every group under it fold, Spaceship stays open
    assert not helen.isExpanded() and not any(g.isExpanded() for g in under(helen))
    assert space.isExpanded() and all(g.isExpanded() for g in under(space))
    click(helen, Qt.KeyboardModifier.ShiftModifier)
    assert helen.isExpanded() and all(g.isExpanded() for g in under(helen))
    click(space, Qt.KeyboardModifier.ControlModifier)  # every group in the tree
    assert not any(g.isExpanded() for g in groups)
    click(space, Qt.KeyboardModifier.ControlModifier)
    assert all(g.isExpanded() for g in groups)
    w.hide()
