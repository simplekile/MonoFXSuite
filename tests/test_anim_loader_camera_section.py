"""MonoFX Loaders inspector: the camera's Aperture mode and the publish's values (the user's pick, 2026-11-22: the
empty, disabled Aperture / Ratio fields read as missing values)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from tests.test_anim_loader_ui import app, make  # noqa: E402,F401  (fixtures)

CAM = {"prim": "/sh011/cam", "focal": 35.0, "focal_animated": False, "h_aperture": 20.955, "v_aperture": 11.787,
       "clip": (0.01, 1000.0), "fstop": 0.0, "focus": None}


def _window(make, mode):  # noqa: F811 (the fixture)
    from tests.test_anim_loader_controller import FakeBackend

    mk, ui = make
    b = FakeBackend()
    state = {"mode": mode}
    use = {"publish": {}, "width": {"horizontalAperture": 36.0},
           "ratio": {"horizontalAperture": 36.0, "aspectratiox": 16.0, "aspectratioy": 9.0}}
    b.cam_parms = lambda path: {"clippingRange1": 0.01, "clippingRange2": 1000.0, "xn__houdiniguidescale_s3a": 1.0,
                                **use[state["mode"]]}
    b.cam_mode = lambda path: state["mode"]
    b.set_cam_mode = lambda path, token: b.calls.append(("cam_mode", path, token)) or state.update(mode=token) or True
    b.camera_info = lambda path: dict(CAM)
    w = mk(b)
    w.ctl.camera = lambda path: dict(CAM)
    for i in range(w.list_view.count()):
        r = w.list_view.item(i).data(ui.ROLE_ROW)
        w.list_view.item(i).setSelected(bool(r) and r.node_path == "/stage/c")
    return w, ui, b


def test_publish_aperture_shows_the_publish_values_and_no_empty_fields(make):  # noqa: F811 (the fixture)
    w, ui, b = _window(make, "publish")
    e = w.subd_panel.cam_edit
    assert e.mode_button.text().startswith("Publish's")
    assert e.sensor_label.text() == "20.95 x 11.79 mm, 16:9"  # as Details rounds it
    assert e.focal_label.text() == "35 mm"
    assert e._rows["width"][1].isHidden() and e._rows["ratio"][1].isHidden()  # nothing empty, nothing disabled
    assert not e._rows["sensor"][1].isHidden() and not e._rows["focal"][1].isHidden()


def test_the_aperture_menu_sets_the_mode_and_shows_its_fields(make):  # noqa: F811 (the fixture)
    w, ui, b = _window(make, "publish")
    e = w.subd_panel.cam_edit
    menu = e.mode_menu()
    texts = [a.text() for a in menu.actions()]
    assert texts == ["Publish's aperture", "Set width, keep the publish's ratio", "Set width and ratio"]
    assert not menu.actions()[0].icon().isNull()  # the current one checked
    menu.actions()[2].trigger()
    assert b.calls[-1] == ("cam_mode", "/stage/c", "ratio")
    w.wait()
    e = w.subd_panel.cam_edit
    assert e.mode_button.text().startswith("Width and ratio")
    assert not e._rows["width"][1].isHidden() and not e._rows["ratio"][1].isHidden()
    assert e.fields["aspectratiox"].text() == "16" and e.fields["horizontalAperture"].isEnabled()


def test_ratio_words():
    from tools.fx.anim_loader import ui

    assert ui.ratio_word(36, 20.25) == "16:9" and ui.ratio_word(36, 24) == "3:2" and ui.ratio_word(2.39, 1) == "2.39:1"
