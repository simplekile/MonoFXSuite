"""The pure part of the Edit points / Draw lock viewer state (v0.2b B3): `tools/fx/grooming/points_keys.py`."""

import math

import pytest

from tools.fx.grooming import config
from tools.fx.grooming import points_keys as pk


@pytest.fixture
def rec():
    return pk.ToolRecord()


@pytest.fixture
def heard():
    """The shared record back to its first values, a hook recording what it was called with."""
    got = []
    keep = pk.HOOKS["tool"]
    pk.STATE.__init__()
    pk.HOOKS["tool"] = [lambda r: got.append(r.as_dict())]
    yield got
    pk.HOOKS["tool"] = keep
    pk.STATE.__init__()


def test_interface_names():
    assert (pk.TOOL_SELECT, pk.TOOL_POINTS, pk.TOOL_DRAW, pk.TOOL_PAINT) == ("select", "points", "draw", "paint")
    assert pk.MODES == ("move", "rotate", "scale", "redraw")
    for field in ("tool", "mode", "lock_ids", "width_cm", "thick_cm", "taper"):
        assert hasattr(pk.STATE, field)
    assert "tool" in pk.HOOKS
    assert pk.STATE.width_cm == config.DRAWN_WIDTH_CM and pk.STATE.taper == config.DRAWN_TAPER_DEFAULT


def test_update_calls_hooks_once_per_change(heard):
    assert pk.update(tool="points", lock_ids=[3, 3, 5])
    assert heard[-1]["tool"] == "points" and heard[-1]["lock_ids"] == [3, 5]
    assert len(heard) == 1
    assert not pk.update(tool="points")          # nothing changed: no call
    assert len(heard) == 1
    pk.update(mode="rotate")
    assert len(heard) == 2 and heard[-1]["mode"] == "rotate"


def test_update_with_one_callable_and_a_hook_that_raises(heard):
    got = []
    pk.HOOKS["tool"] = lambda r: got.append(r.tool)
    pk.update(tool="draw")
    assert got == ["draw"]

    def bad(_r):
        raise RuntimeError("panel bug")
    pk.HOOKS["tool"] = [bad, lambda r: got.append(r.tool)]
    pk.update(tool="points")                     # the bad hook does not stop the tool nor the next hook
    assert got == ["draw", "points"]


def test_update_refuses_unknown(rec):
    with pytest.raises(ValueError):
        pk.update(rec, tool="brush")
    with pytest.raises(ValueError):
        pk.update(rec, mode="twist")
    with pytest.raises(KeyError):
        pk.update(rec, colour="red")


def test_new_lock_values_clamped(rec):
    pk.update(rec, width_cm=0.0, thick_cm=1e9, taper=-3)
    assert rec.width_cm == pk.WIDTH_MIN_CM and rec.thick_cm == pk.THICK_MAX_CM and rec.taper == 0.0
    pk.update(rec, width_cm=float("nan"))        # not finite: kept
    assert rec.width_cm == pk.WIDTH_MIN_CM


def test_reset_keeps_new_lock_values(rec):
    pk.update(rec, tool="draw", width_cm=3.0, lock_ids=[4], mode="scale", held="rotate")
    pk.reset(rec)
    assert rec.tool == "select" and rec.lock_ids == [] and rec.held == ""
    assert rec.width_cm == 3.0 and rec.mode == "scale"


def test_drag_mode_held_key_for_one_drag():
    assert pk.drag_mode("move") == "move"
    assert pk.drag_mode("move", held="rotate") == "rotate"
    assert pk.drag_mode("scale", held="") == "scale"
    assert pk.drag_mode("rotate", held="scale", shift=True) == "redraw"
    assert pk.drag_mode("bogus") == "move"


def test_handle_keys_and_counts():
    assert pk.handle_step("-") == -1 and pk.handle_step("Minus") == -1
    assert pk.handle_step("+") == 1 and pk.handle_step("Shift+=") == 1 and pk.handle_step("=") == 1
    assert pk.handle_step("r") == 0
    assert pk.next_count(4, -1) == config.HANDLES_MIN
    assert pk.next_count(12, 1) == config.HANDLES_MAX
    assert pk.next_count(6, 1) == 7


def test_bar_handles():
    assert pk.bar_handles(0) is None and pk.bar_handles(-2) is None
    assert pk.bar_handles(2) == config.HANDLES_MIN
    assert pk.bar_handles(99) == config.HANDLES_MAX
    assert pk.bar_handles("7") == 7


def test_scale_and_wheel():
    assert pk.scale_factor(0) == 1.0
    assert math.isclose(pk.scale_factor(pk.SCALE_DOUBLE_PX), 2.0)
    assert math.isclose(pk.scale_factor(-pk.SCALE_DOUBLE_PX), 0.5)
    assert pk.scale_factor(1e9) == pk.SCALE_MAX and pk.scale_factor(-1e9) == pk.SCALE_MIN
    assert pk.scale_factor(float("nan")) == 1.0
    assert math.isclose(pk.wheel_width(2.0, 1), 2.2)
    assert pk.wheel_width(2.0, -1e6) == pk.WIDTH_MIN_CM


def test_signed_angle_right_handed():
    z = (0.0, 0.0, 1.0)
    assert math.isclose(pk.signed_angle((1, 0, 0), (0, 1, 0), z), 90.0)
    assert math.isclose(pk.signed_angle((1, 0, 0), (0, -1, 0), z), -90.0)
    # the parts along the axis are dropped
    assert math.isclose(pk.signed_angle((1, 0, 5), (0, 1, -3), z), 90.0)
    assert pk.signed_angle((0, 0, 1), (1, 0, 0), z) == 0.0
    assert pk.signed_angle((1, 0, 0), (0, 1, 0), (0, 0, 0)) == 0.0


def test_map_handle():
    assert pk.map_handle(0, 5, 8) == 0
    assert pk.map_handle(4, 5, 8) == 7          # tip to tip
    assert pk.map_handle(2, 5, 9) == 4          # middle to middle
    assert pk.map_handle(1, 5, 4) == 1
    assert 1 <= pk.map_handle(3, 12, 4) <= 2    # never the root or the tip for an inner handle


def test_click_selection():
    assert pk.click_selection([1, 2], 5) == [5]
    assert pk.click_selection([1, 2], 5, shift=True) == [1, 2, 5]
    assert pk.click_selection([1, 2], 2, shift=True) == [1, 2]
    assert pk.click_selection([1, 2], 2, ctrl=True) == [1]
    assert pk.click_selection([1], 3, ctrl=True) == [1, 3]
    assert pk.click_selection([1, 2], None) == [1, 2]   # empty space keeps the selection


def test_is_drag_and_nearest():
    assert not pk.is_drag((10, 10), (12, 11))
    assert pk.is_drag((10, 10), (10, 10 + pk.DRAG_PX))
    assert pk.nearest({3: 9.0, 1: 5.0, 2: 5.0}, 14.0) == 1
    assert pk.nearest({3: 20.0}, 14.0) is None


def test_hud_rows_as_sketched():
    edit = pk.hud_template("points")
    labels = [r.get("label") for r in edit["rows"] if "label" in r]
    for want in ("Locks", "Drag", "Rotate about root", "Scale about root", "Redraw", "Handles", "Done"):
        assert want in labels
    keys = {r.get("label"): r.get("key") for r in edit["rows"]}
    assert keys["Rotate about root"] == "R + LMB" and keys["Scale about root"] == "E + LMB"
    assert keys["Redraw"] == "Shift + LMB" and keys["Done"] == "esc"
    draw = pk.hud_template("draw")
    labels = [r.get("label") for r in draw["rows"] if "label" in r]
    for want in ("Draw", "Width", "Thickness", "Tip taper", "Done"):
        assert want in labels
    for t in (edit, draw):
        own = [r["id"] for r in t["rows"] if "id" in r]
        assert len(own) == len(set(own))


def test_hud_values(rec):
    locks = {1: {"name": "hair_bang_11", "edited": True, "count": 4, "count_set": None},
             2: {"name": "hair_bang_12", "edited": False, "count": 6, "count_set": None}}
    pk.update(rec, tool="points", lock_ids=[1, 2])
    v = pk.hud_values(rec, locks)
    assert v["locks"] == "2, 1 edited" and v["drag"] == "Move" and v["handles"] == "auto (4 to 6)"
    pk.update(rec, lock_ids=[1], held="rotate")
    v = pk.hud_values(rec, locks)
    assert v["locks"] == "hair_bang_11, edited" and v["drag"] == "Rotate (held)" and v["handles"] == "auto (4)"
    pk.update(rec, lock_ids=[])
    assert pk.hud_values(rec, locks)["locks"] == "Select a lock"
    pk.update(rec, tool="draw", width_cm=2.5)
    v = pk.hud_values(rec)
    assert v["width"] == "2.5 cm" and v["taper"] == f"{config.DRAWN_TAPER_DEFAULT:g}"


def test_handles_text():
    assert pk.handles_text([5, 5], [None, None]) == "auto (5)"
    assert pk.handles_text([8, 8], [8, 8]) == "8"
    assert pk.handles_text([8, 5], [8, None]) == "mixed"
    assert pk.handles_text([], []) == ""


def test_bar_values_and_visibility(rec):
    locks = {1: {"count": 8, "count_set": 8}, 2: {"count": 8, "count_set": 8}, 3: {"count": 5, "count_set": None}}
    pk.update(rec, lock_ids=[1, 2], mode="scale")
    b = pk.bar_values(rec, locks)
    assert b["drag_mode"] == pk.MODES.index("scale") and b["handles"] == 8
    pk.update(rec, lock_ids=[1, 3])
    assert pk.bar_values(rec, locks)["handles"] == pk.HANDLES_AUTO
    vis = pk.bar_visible("points")
    assert vis["drag_mode"] and vis["handles"] and not vis["width"]
    vis = pk.bar_visible("draw")
    assert vis["width"] and vis["thickness"] and vis["taper"] and not vis["drag_mode"]


def test_field_change(rec):
    assert pk.field_change("drag_mode", 1, rec) == {"mode": "rotate"}
    assert pk.field_change("drag_mode", 0, rec) == {}              # already move
    assert pk.field_change("drag_mode", 9, rec) == {}
    assert pk.field_change("handles", 0, rec) == {"handles": None}
    assert pk.field_change("handles", 7, rec) == {"handles": 7}
    assert pk.field_change("width", rec.width_cm, rec) == {}
    assert pk.field_change("width", 3.0, rec) == {"width_cm": 3.0}
    assert pk.field_change("taper", 5, rec) == {"taper": 1.0}
    assert pk.field_change("nothing", 1, rec) == {}


def test_status_text(rec):
    pk.update(rec, tool="points")
    assert "Select a lock" in pk.status_text(rec, 0)
    assert "Esc" in pk.status_text(rec, 2)
    pk.update(rec, tool="draw")
    assert "Draw lock" in pk.status_text(rec, 0)
    pk.update(rec, tool="select")
    assert pk.status_text(rec, 0) == ""


def test_no_hou_no_qt():
    import sys
    assert "hou" not in pk.__dict__
    src = open(pk.__file__, encoding="utf-8").read()
    assert "import hou" not in src and "PySide" not in src
    assert "\r\n" not in open(pk.__file__, "rb").read().decode("utf-8")
    assert sys.modules.get("tools.fx.grooming.points_keys") is pk
