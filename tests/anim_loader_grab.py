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
