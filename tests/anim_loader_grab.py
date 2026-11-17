"""Factory for grab_offscreen.py: the Anim Loader manager with fake loaders and real Monos thumbnails when present."""

from __future__ import annotations

import os

from tests.test_anim_loader_controller import FakeBackend

HELEN = "D:/Dropbox/Job/260826_grn_vp97/01_assets/_characters/char_Helen/thumbnail.user.png"


class GrabBackend(FakeBackend):
    def thumbnail(self, state):
        return HELEN if state.asset == "char_Helen" and os.path.isfile(HELEN) else ""


def _make(scale: float, view: str):
    from tools.fx.anim_loader.ui import AnimLoaderManager

    w = AnimLoaderManager(GrabBackend(), scale=scale)
    w.wait()
    w.set_view(view)
    w.ctl.message = "Loaded sh900 v002: created 3, kept 1."
    w._update_bar()
    return w


def make_list(scale: float):
    return _make(scale, "list")


def make_grid(scale: float):
    return _make(scale, "grid")


def make_subd(scale: float):
    from tests.test_anim_loader_controller import _subd_backend
    from tools.fx.anim_loader.ui import ROLE_ROW, AnimLoaderManager

    b = _subd_backend()
    b.thumbnail = GrabBackend().thumbnail
    w = AnimLoaderManager(b, scale=scale)
    w.wait()
    w.set_view("list")
    for i in range(w.list_view.count()):
        r = w.list_view.item(i).data(ROLE_ROW)
        w.list_view.item(i).setSelected(bool(r) and r.node_path == "/stage/b")
    w.subd_panel.tree.expandAll()
    w.subd_panel.tree.topLevelItem(0).setSelected(True)
    return w


def _make_a(scale: float):
    from tests.test_anim_loader_ui_a import BackendA
    from tools.fx.anim_loader.ui import ROLE_ROW, AnimLoaderManager

    b = BackendA()
    b.thumbnail = GrabBackend().thumbnail
    w = AnimLoaderManager(b, scale=scale)
    w.ctl.target_shot, w.ctl.target_root = "sh025", "D:/Dropbox/Job/260826_grn_vp97"
    w.refresh()
    w.wait()
    w.set_view("list")
    return w, ROLE_ROW


def make_a(scale: float):
    """Layout A: a loader with a newer lookdev selected (what is new, Source, links), the shot gap on the status line."""
    w, role = _make_a(scale)
    for i in range(w.list_view.count()):
        r = w.list_view.item(i).data(role)
        w.list_view.item(i).setSelected(bool(r) and r.node_path == "/stage/a")
    w.ctl.message = "Updated char_Helen: lookdev V008 -> V009."
    w._update_bar()
    return w


def make_drawer(scale: float):
    """Layout A with the Add drawer open on the real project (assets with a UV or lookdev publish)."""
    w, _ = _make_a(scale)
    w._project = "D:/Dropbox/Job/260826_grn_vp97"
    w.open_drawer()
    if w.drawer.list.count() > 1:
        w.drawer.list.item(0).setSelected(True)
        w.drawer.list.item(1).setSelected(True)
    return w
