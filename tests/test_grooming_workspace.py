"""MONO Grooming's workspace and the Paint state's keys (v0.2a last task): the radial entries call what the
panel's buttons call, the shipped radial menu file is the one the entries make, the brush keys move the brush
the right way, and a brush change from the viewport reaches the panel without a loop."""

from __future__ import annotations

import json
import math
import os

import pytest

from tools.fx.grooming import brush_keys as bk
from tools.fx.grooming import config
from tools.fx.grooming import controller as ctl
from tools.fx.grooming import workspace as ws
from tools.fx.grooming.layers import SEL_LAYER

from test_grooming_layers import LayerAdapter, _env, _layered

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Brush keys (pure)
# ---------------------------------------------------------------------------
def test_wheel_sizes_the_radius_and_stays_inside_the_limits() -> None:
    assert bk.wheel_radius(1.0, 1) == pytest.approx(1.1)
    assert bk.wheel_radius(1.0, -1) == pytest.approx(1 / 1.1)
    assert bk.wheel_radius(1.0, 3) == pytest.approx(1.1 ** 3)
    assert bk.wheel_radius(49.0, 5) == bk.RADIUS_MAX_CM
    assert bk.wheel_radius(0.06, -5) == bk.RADIUS_MIN_CM


def test_ctrl_shift_drag_doubles_every_step_to_the_right() -> None:
    assert bk.drag_radius(1.0, 0) == pytest.approx(1.0)
    assert bk.drag_radius(1.0, bk.DRAG_DOUBLE_PX) == pytest.approx(2.0)
    assert bk.drag_radius(1.0, -bk.DRAG_DOUBLE_PX) == pytest.approx(0.5)
    assert bk.drag_radius(1.0, 10 * bk.DRAG_DOUBLE_PX) == bk.RADIUS_MAX_CM


def test_hud_shows_the_keys_and_the_live_brush() -> None:
    t = bk.hud_template()
    ids = {r.get("id") for r in t["rows"]}
    brush = {"radius_cm": 1.25, "soft": 0.4, "value": 0.5, "erase": True}
    v = bk.hud_values(brush, "Crown")
    assert set(v) <= ids                     # every value has its row
    assert v["layer"] == "Crown" and v["mode"] == "Erase" and v["mode_g"] == 1
    assert v["radius"] == "1.25 cm" and v["radius_g"] == pytest.approx(0.25)
    assert v["soft"] == "40 %" and v["grey"] == "0.5"
    assert v["lmb"] == {"label": "Erase"} and v["ctrl_lmb"] == {"label": "Paint"}   # Ctrl paints the other way
    keys = {r.get("key") for r in t["rows"]}
    assert {"F", "LMB", "Ctrl + LMB", "RMB", "esc", "mousewheel", "Ctrl + Shift + LMB"} <= keys
    rows = {r.get("id"): r for r in t["rows"]}
    assert rows["radius"]["key"] == "mousewheel"            # the wheel on its own row (t73: it was not shown)
    assert rows["radius_drag"]["key"] == "Ctrl + Shift + LMB"
    assert bk.hud_values({"radius_cm": 40.0})["radius_g"] == 1.0


def test_bar_and_its_change_have_no_loop() -> None:
    brush = {"radius_cm": 1.0, "soft": 0.5, "value": 1.0, "erase": False}
    assert bk.bar_values(brush) == {"radius": 1.0, "soft": 0.5, "grey": 1.0, "eraser": False}
    # the bar written from the brush gives the same value back: nothing to set (no loop)
    for name, value in bk.bar_values(brush).items():
        assert bk.field_change(name, value, brush) == {}
    assert bk.field_change("radius", 2.5, brush) == {"radius_cm": 2.5}
    assert bk.field_change("grey", 0.0, brush) == {"value": 0.0}
    assert bk.field_change("eraser", True, brush) == {"erase": True}
    assert bk.field_change("eraser", "on", brush) == {"erase": True}
    assert bk.field_change("unknown", 1, brush) == {}


def test_f_and_the_menu_change_the_brush() -> None:
    brush = {"radius_cm": 1.0, "value": 1.0, "erase": False}
    assert bk.menu_fields(bk.SWAP, brush) == {"erase": True}
    assert bk.menu_fields(bk.SWAP, {**brush, "erase": True}) == {"erase": False}
    assert bk.menu_fields("radius_up", brush) == {"radius_cm": 1.25}
    assert bk.menu_fields("radius_down", brush) == {"radius_cm": 0.8}
    assert bk.menu_fields("radius_2", brush) == {"radius_cm": 2.0}
    assert bk.menu_fields("grey_0.5", brush) == {"value": 0.5}
    assert bk.menu_fields("nothing", brush) == {}
    items = bk.menu_items()
    assert items[0] == ("", bk.SWAP, "Paint / Erase")
    for _sub, item, _label in items:      # every item the menu has does something
        assert bk.menu_fields(item, brush), item
    assert {i for s, i, _l in items if s == "Grey"} == {f"grey_{g:g}" for g in config.MASK_VALUE_PICKS}


# ---------------------------------------------------------------------------
# The radial menu
# ---------------------------------------------------------------------------
def test_shipped_radial_file_is_the_one_the_entries_make() -> None:
    path = os.path.join(ROOT, "radialmenu", ws.RADIAL_NAME + ".radialmenu")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert text == ws.radial_menu_text()
    menu = json.loads(text)
    assert menu[menu.index("name") + 1] == ws.RADIAL_NAME
    flat = json.dumps(menu)
    for entry in ws.entry_ids():
        assert f"grooming_workspace.radial('{entry}')" in flat
    # 8 places at the root at most, each used once
    root = menu[menu.index("submenu") + 1]
    places = root[3::2]
    assert len(places) == len(set(places)) <= 8


def test_desk_and_python_panel_ship_at_the_suite_root() -> None:
    with open(os.path.join(ROOT, "desktop", ws.DESK_NAME + ".desk"), encoding="utf-8") as fh:
        desk = fh.read()
    assert "-m sceneview" in desk and "-m pythonpanel" in desk and "-m neteditor" in desk
    assert f"pythonpanel -s on -t off -n {ctl.PYPANEL_NAME} " in desk
    assert "radial menu set" not in desk        # the panel switches it (switching desks did not put it back)
    assert os.path.isfile(os.path.join(ROOT, "python_panels", "mono_grooming.pypanel"))
    with open(os.path.join(ROOT, "build", "installer", "MonoFXSuite.iss"), encoding="utf-8-sig") as fh:
        iss = fh.read()
    for folder in ("desktop", "radialmenu", "python_panels"):
        assert f'Source: "..\\..\\{folder}\\*"; DestDir: "{{app}}\\{folder}"' in iss


def _panel_env():
    adapter, view, c = _env(LayerAdapter())
    ids = _layered(adapter)
    c.refresh()
    return adapter, view, c, ids


class _FakeUI:
    def __init__(self) -> None:
        self.cb = {}

    def on(self, event, fn) -> None:
        self.cb[event] = fn

    def fire(self, event, *a, **k):
        return self.cb[event](*a, **k)


# the panel's button for each entry: (ui event, args, kwargs given the brush now)
BUTTONS = {
    "paint": lambda b: ("toggle_paint", (), {}),
    "erase": lambda b: ("set_brush", (), {"erase": not b["erase"]}),
    "scalp_xray": lambda b: ("set_brush", (), {"xray": not b["xray"]}),
    "guide": lambda b: ("set_display", ("guide", None), {}),
    "hair_preview": lambda b: ("set_display", ("hair_preview", None), {}),
    "hair": lambda b: ("set_display", ("hair", None), {}),
    "isolate": lambda b: ("isolate", (), {}),
    "update_regions": lambda b: ("split_regions", (), {}),
    "detect": lambda b: ("detect", (), {}),
}


def _state(adapter, c) -> tuple:
    return (adapter.text, adapter.painting, json.dumps(adapter.BRUSH, sort_keys=True), list(adapter.display),
            getattr(adapter, "isolated", None), c.display_mode, c.paint_layer_id, c.isolated, list(adapter.writes))


@pytest.mark.parametrize("entry", ws.entry_ids())
def test_every_radial_entry_leaves_the_node_as_its_panel_button(entry) -> None:
    assert set(BUTTONS) == set(ws.entry_ids())
    results = []
    for how in ("radial", "button"):
        adapter, view, c, ids = _panel_env()
        if entry in ("paint", "erase"):              # the panel's Paint and Eraser sit on a paint layer
            c.select(SEL_LAYER, (ids["crown"],))
        elif entry == "isolate":
            c.select(ctl.SEL_LOCKS, (1, 2))
        if how == "radial":
            ws.run(c, entry)
        else:
            ui = _FakeUI()
            ctl.bind(ui, c)
            event, args, kwargs = BUTTONS[entry](c.brush_state())
            ui.fire(event, *args, **kwargs)
        results.append(_state(adapter, c))
    assert results[0] == results[1]
    assert results[0] != _state(*(lambda a, v, c, i: (a, c))(*_panel_env()))   # and it did something


def test_radial_without_a_node_says_so_and_never_raises() -> None:
    view = __import__("test_grooming_controller").RecordingView()
    c = ctl.GroomController(LayerAdapter(), view)        # no node
    for entry in ws.entry_ids():
        assert ws.run(c, entry) is False
        assert ws.checked(c, entry) is False
    assert view.messages[-1] == (ws.NO_NODE, True)
    assert ws.run(None, "detect") is False
    with pytest.raises(KeyError):
        ws.run(c, "nothing")


def test_check_marks_follow_the_panel() -> None:
    adapter, view, c, ids = _panel_env()
    c.select(SEL_LAYER, (ids["crown"],))
    assert not ws.checked(c, "paint")
    ws.run(c, "paint")
    assert ws.checked(c, "paint")
    ws.run(c, "erase")
    assert ws.checked(c, "erase")
    ws.run(c, "hair_preview")
    assert ws.checked(c, "hair_preview") and not ws.checked(c, "hair")


# ---------------------------------------------------------------------------
# The brush from the viewport reaches the panel; the panel's own change does not come back
# ---------------------------------------------------------------------------
def test_a_brush_changed_in_the_viewport_shows_in_the_panel_on_the_next_poll() -> None:
    adapter, view, c, ids = _panel_env()
    c.select(SEL_LAYER, (ids["crown"],))
    assert c.toggle_paint() and adapter.HOOKS["brush"] is not None
    adapter.BRUSH["radius_cm"] = 2.5                 # the state's wheel (grooming_masks.set_brush, source state)
    adapter.HOOKS["brush"]()
    assert view.props["brush"]["radius_cm"] != 2.5   # not at once (a drag would rebuild the panel per move)
    c.poll()
    assert view.props["brush"]["radius_cm"] == 2.5 and view.paint[1]["radius_cm"] == 2.5
    shown = view.props
    c.poll()
    assert view.props is shown                        # nothing new: no rebuild


def test_grooming_masks_tells_the_panel_only_of_a_change_from_the_viewport(monkeypatch) -> None:
    gm = pytest.importorskip("apps.houdini.grooming_masks")
    if gm.hou is not None:
        pytest.skip("only without Houdini")
    calls = []
    monkeypatch.setitem(gm.HOOKS, "brush", lambda: calls.append(dict(gm.BRUSH)))
    before = dict(gm.BRUSH)
    try:
        gm.set_brush(radius_cm=2.0)                       # the panel
        assert calls == []
        gm.set_brush(radius_cm=3.0, source="state")       # the viewport
        assert len(calls) == 1 and calls[0]["radius_cm"] == 3.0
    finally:
        gm.BRUSH.clear()
        gm.BRUSH.update(before)


# ---------------------------------------------------------------------------
# The panel shown / hidden switches the radial menu
# ---------------------------------------------------------------------------
def test_panel_shown_switches_the_radial_menu_and_asks_once_when_it_cannot() -> None:
    adapter, view, c, ids = _panel_env()
    calls = []
    adapter.radial_on = lambda: calls.append("on") or False
    adapter.radial_off = lambda: calls.append("off") or True
    ui = _FakeUI()
    ctl.bind(ui, c)
    ui.fire("shown")
    ui.fire("shown")
    ui.fire("hidden")
    assert calls == ["on", "on", "off"]
    asked = [m for m in view.messages if m[0] == ws.RADIAL_BY_HAND]
    assert len(asked) == 1


def test_panel_hidden_ends_paint() -> None:
    adapter, view, c, ids = _panel_env()
    c.select(SEL_LAYER, (ids["crown"],))
    c.toggle_paint()
    c.panel_hidden()
    assert adapter.painting is None and c.paint_layer_id is None


def test_live_panels_drop_closed_ones(monkeypatch) -> None:
    class UI:
        def __init__(self, alive):
            self.alive = alive

        def is_alive(self):
            return self.alive

    a, b = UI(True), UI(False)
    monkeypatch.setattr(ctl, "_LIVE", [(a, "ca"), (b, "cb")])
    assert ctl.live_panels() == [(a, "ca")] and ctl._LIVE == [(a, "ca")]


def test_radius_steps_are_geometric() -> None:
    r = 1.0
    for _ in range(10):
        r = bk.wheel_radius(r, 1)
    assert math.isclose(r, 1.1 ** 10)


def test_paint_ended_by_a_deleted_node_reads_nothing() -> None:
    """The node deleted (or File > New) while painting: the state's exit hook must not touch it (t72: it raised
    hou.ObjectWasDeleted inside the state's _came_back)."""
    adapter, view, c, ids = _panel_env()
    c.select(SEL_LAYER, (ids["crown"],))
    assert c.toggle_paint()

    class Gone:
        def path(self):
            raise RuntimeError("ObjectWasDeleted")

    c.node = Gone()
    adapter.read_data = lambda node: (_ for _ in ()).throw(RuntimeError("ObjectWasDeleted"))
    adapter.HOOKS["exit"]()                        # what the state calls when Paint is over
    assert c.paint_layer_id is None and view.paint[0] is False


def test_a_grey_pick_shows_only_itself_checked() -> None:
    adapter, view, c, ids = _panel_env()
    c.select(SEL_LAYER, (ids["crown"],))
    c.set_brush(value=0.5)
    assert view.props["brush"]["value"] == 0.5


# ---------------------------------------------------------------------------
# Fix round t73
# ---------------------------------------------------------------------------
def _selections(ids):
    """(name, selection) for every kind of selection the panel has, the paint layer last."""
    return [("nothing", (ctl.SEL_NONE, ())), ("all_locks", (ctl.SEL_DEFAULTS, ())), ("group", (ctl.SEL_GROUP, ("fringe",))),
            ("lock", (ctl.SEL_LOCKS, (1,))), ("several_locks", (ctl.SEL_LOCKS, (1, 3))),
            # the panel keeps one layer of several rows picked: the one clicked last (here the fill layer)
            ("several_layer_rows", (SEL_LAYER, (ids["soften"], ids["crown"]))),
            ("lock_and_group_rows", (ctl.SEL_LOCKS, (1, 2))),
            ("density_layer", (SEL_LAYER, (ids["crown_thin"],))), ("fill_layer", (SEL_LAYER, (ids["soften"],))),
            ("automatic", (SEL_LAYER, (config.MASK_BASE_ID,))), ("paint_layer", (SEL_LAYER, (ids["crown"],)))]


@pytest.mark.parametrize("entry", ["paint", "erase"])
def test_radial_paint_and_erase_say_what_is_needed_for_every_selection(entry) -> None:
    from tools.fx.grooming.layers import PAINT_NEEDS
    for name, sel in _selections(_panel_env()[3]):
        adapter, view, c, ids = _panel_env()
        c.select(*sel)
        before = (adapter.text, list(adapter.writes), dict(adapter.BRUSH), adapter.painting)
        n = len(view.messages)
        ok = ws.run(c, entry)
        said = view.messages[n:]
        if name == "paint_layer":
            assert ok, name
            assert (adapter.painting == ids["crown"]) if entry == "paint" else adapter.BRUSH["erase"] is True
            continue
        assert ok is False, name
        assert said and said[-1][1] is True and said[-1][0].startswith(PAINT_NEEDS), (name, said)
        # no state entered, no scene write, brush unchanged
        assert (adapter.text, list(adapter.writes), dict(adapter.BRUSH), adapter.painting) == before, name
        assert c.paint_layer_id is None, name
    # what it names
    adapter, view, c, ids = _panel_env()
    c.select(SEL_LAYER, (ids["crown_thin"],))
    assert "a density layer is selected" in c.paint_needs()
    c.select(SEL_LAYER, (config.MASK_BASE_ID,))
    assert "Automatic is selected" in c.paint_needs()
    c.selection = (SEL_LAYER, (ids["crown"], ids["soften"]))     # held directly: the panel never sends it
    assert "several rows" in c.paint_needs()


def test_erase_while_painting_needs_no_paint_layer_selected() -> None:
    adapter, view, c, ids = _panel_env()
    c.select(SEL_LAYER, (ids["crown"],))
    assert ws.run(c, "paint")
    c.selection = (ctl.SEL_LOCKS, (1,))          # the selection moved on (Paint is still on)
    assert ws.run(c, "erase") and adapter.BRUSH["erase"] is True


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 1e308, -1e308, "x", None])
def test_brush_keys_give_a_finite_clamped_radius_for_absurd_input(bad) -> None:
    for got in (bk.wheel_radius(1.0, bad), bk.wheel_radius(bad, 1), bk.drag_radius(1.0, bad), bk.drag_radius(bad, 10),
                bk.clamp_radius(bad), bk.wheel_radius(bad, bad), bk.drag_radius(bad, bad)):
        assert math.isfinite(got) and bk.RADIUS_MIN_CM <= got <= bk.RADIUS_MAX_CM, (bad, got)
    v = bk.hud_values({"radius_cm": bad})
    assert v["radius"].endswith(" cm") and 0.0 <= v["radius_g"] <= 1.0
    assert bk.menu_fields("radius_up", {"radius_cm": bad}).get("radius_cm", 1.0) <= bk.RADIUS_MAX_CM
    change = bk.field_change("radius", bad, {"radius_cm": 1.0})
    assert change == {} or (math.isfinite(change["radius_cm"])
                            and bk.RADIUS_MIN_CM <= change["radius_cm"] <= bk.RADIUS_MAX_CM)


def test_huge_wheel_and_drag_land_on_the_limits() -> None:
    assert bk.wheel_radius(1.0, 1e9) == bk.RADIUS_MAX_CM and bk.wheel_radius(1.0, -1e9) == bk.RADIUS_MIN_CM
    assert bk.drag_radius(1.0, 1e12) == bk.RADIUS_MAX_CM and bk.drag_radius(1.0, -1e12) == bk.RADIUS_MIN_CM
    assert bk.field_change("grey", 7.0, {"value": 1.0}) == {}          # clamped to 1: what the brush has
    assert bk.field_change("soft", -3.0, {"soft": 0.5}) == {"soft": 0.0}
    assert bk.menu_fields("radius_1e400", {"radius_cm": 1.0}) == {"radius_cm": bk.RADIUS_MAX_CM}


def test_desk_gives_the_panel_its_own_pane_on_the_left() -> None:
    """The user (t74, docked): MONO Grooming alone in the left pane, not a tab beside the parameter editor."""
    import re

    with open(os.path.join(ROOT, "desktop", ws.DESK_NAME + ".desk"), encoding="utf-8") as fh:
        desk = fh.read()
    root = desk[desk.index("root {"):]
    tabs = re.findall(r"tabs \d+ \d+ \{(.*?)\}", root, re.S)
    first = [line.strip() for line in tabs[0].strip().splitlines()]
    assert len(first) == 1 and "-m pythonpanel" in first[0]
    assert root.index("-m pythonpanel") < root.index("-m sceneview")       # left of the viewport
