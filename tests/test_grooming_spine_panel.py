"""MONO Grooming panel, lock shapes (v0.2b B4): the Tool bar, its strip, Reset shape, handles, drawn locks, with a
fake adapter (B2's functions) and a fake viewer state (B3's interface); no Houdini."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

from tools.fx.grooming import config
from tools.fx.grooming import controller as ctl
from tools.fx.grooming import spine as S
from tools.fx.grooming.layers import SEL_LAYER, owner_name
from tools.fx.grooming.logic import LockInfo
from tools.fx.grooming.model import GroomData, Group, Lock

from test_grooming_controller import RecordingView, app, prefs  # noqa: F401  (pytest fixtures)
from test_grooming_layers import LayerAdapter

CURVE = [(0.0, 0.0, 0.0), (0.0, 0.05, 0.0), (0.0, 0.1, 0.02), (0.0, 0.14, 0.05)]


def _data() -> GroomData:
    data = GroomData(asset="char_Helen", groups=[Group(id="fringe", name="Fringe"), Group(id="back", name="Back")],
                     locks=[Lock(id=1, name="fringe_01", group="fringe", spine=[(0.0, 0.0, 0.0)] * 5),
                            Lock(id=2, name="fringe_02", group="fringe", overrides={"clump": 0.8}),
                            Lock(id=3, name="back_01", group="back"),
                            Lock(id=4, name="back_02", group="back")])
    data.locks.append(Lock(id=5, name="drawn_01", group="back", source=config.SOURCE_DRAWN, curve=list(CURVE),
                           drawn_curve=list(CURVE), width_cm=2.0, thick_cm=0.6, taper=0.3))
    data.id_high = 5
    return data


class SpineAdapter(LayerAdapter):
    """LayerAdapter + B2's lock-shape functions (each one undo step) and `animated_scalp`."""

    LENGTHS = {1: 20.0, 2: 35.0, 3: 10.0, 4: 50.0, 5: 14.0}   # cm: 4, 6, 4, 8 handles by length

    def __init__(self) -> None:
        super().__init__()
        self.text = _data().to_json()
        self.scalp = {"wired": False, "ok": False, "drawn": 1,
                      "message": "No animated scalp wired into input 4: the drawn lock stays at rest in a shot (the"
                                 " mesh locks deform as before)"}
        self.groups: list[str] = []

    def unit_cm(self, node) -> float:
        return 1.0

    def lock_infos(self, node):
        return [LockInfo(lk.id, lk.name, lk.group, (0, 0, 0), self.LENGTHS.get(lk.id, 10.0), 1.5, 0.4, 0.2, 1000, 3.0)
                for lk in self.read_data(node).locks]

    @contextlib.contextmanager
    def undo_group(self, label):
        self.groups.append(label)
        yield

    def reset_points(self, node, ids):
        data = self.read_data(node)
        done = [i for i in ids if data.lock(i).reset_spine()]
        self._step(("reset", tuple(done)), data)
        return {"locks": done, "roots_moved": [], "message": "Reset: " + ", ".join(data.lock(i).name for i in done)}

    def set_handle_count(self, node, ids, count):
        data = self.read_data(node)
        for i in ids:
            data.lock(i).handles = count
        self._step(("handles", tuple(ids), count), data)
        return {"locks": list(ids), "gap_cm": {}, "message": f"Handles: {len(ids)} locks"}

    def set_drawn(self, node, ids, width_cm=None, thick_cm=None, taper=None):
        data = self.read_data(node)
        for i in ids:
            lk = data.lock(i)
            lk.width_cm = width_cm if width_cm is not None else lk.width_cm
            lk.thick_cm = thick_cm if thick_cm is not None else lk.thick_cm
            lk.taper = taper if taper is not None else lk.taper
        self._step(("drawn", tuple(ids)), data)
        return {"locks": list(ids), "roots_moved": [], "message": "Drawn lock: " + ", ".join(
            data.lock(i).name for i in ids)}

    def delete_drawn_locks(self, node, ids):
        data = self.read_data(node)
        names = [data.lock(i).name for i in ids if data.lock(i) is not None and data.lock(i).drawn]
        done = [i for i in ids if data.remove_drawn_lock(i)]
        data.regions_stale = False
        self._step(("delete", tuple(done)), data)
        return {"locks": done, "took": ["back_01"], "took_ids": [3],
                "message": f"Deleted {', '.join(names)}; its skin to back_01"}

    def animated_scalp(self, node):
        return dict(self.scalp)


def _state_module():
    calls = []
    now = {"tool": "select"}

    def rec(name):
        def fn(*args):
            calls.append((name, args))
            if name == "enter_points":
                now["tool"] = "points"
            elif name == "enter_draw":
                now["tool"] = "draw"
            elif name == "exit_tool":
                now["tool"] = "select"
        return fn

    mod = SimpleNamespace(**{n: rec(n) for n in ("enter_points", "enter_draw", "exit_tool", "set_mode", "set_locks",
                                                 "set_new_lock")})
    mod.current_tool = lambda: now["tool"]
    mod.calls, mod.now = calls, now
    return mod


@pytest.fixture(autouse=True)
def _keys_hooks():
    """The panel registers on B3's real `points_keys.HOOKS` (a module global): each test starts and ends clean."""
    keys = S.points_keys()
    if keys is None:
        yield
        return
    saved = (list(keys.HOOKS["tool"]) if isinstance(keys.HOOKS["tool"], list) else keys.HOOKS["tool"],
             keys.HOOKS["write"])
    keys.HOOKS["tool"], keys.HOOKS["write"] = [], None
    yield
    keys.HOOKS["tool"], keys.HOOKS["write"] = saved


@pytest.fixture
def env():
    adapter = SpineAdapter()
    adapter.points_state = _state_module()
    view = RecordingView()
    view.show_tools = lambda cells, strip: setattr(view, "tools", (cells, strip))
    c = ctl.GroomController(adapter, view, adapter.node)
    return adapter, view, c


def _on(view) -> str:
    return next(c["id"] for c in view.tools[0] if c["on"])


def _child(rows, lid):
    return next(ch for r in rows for ch in r.get("children", []) if ch["kind"] == "locks" and ch["id"] == lid)


# ---------------------------------------------------------------------------
# Pure
# ---------------------------------------------------------------------------
def test_handles_summary_auto_range_own_and_mixed() -> None:
    assert S.handles_summary([5], [None])["text"] == "auto (5)"
    assert S.handles_summary([4, 6, 5], [None, None, None])["text"] == "auto (4 to 6)"
    own = S.handles_summary([7, 7], [7, 7])
    assert own["text"] == "7" and own["own"] and not own["mixed"]
    mixed = S.handles_summary([4, 7], [None, 7])
    assert mixed["text"] == "mixed" and mixed["mixed"] and mixed["set"] == 1
    assert S.handles_summary([12], [None])["max"] and S.handles_summary([4], [None])["min"]
    assert S.handles_summary([], [])["text"] == ""


def test_stepped_counts_clamp_and_group_by_target() -> None:
    assert S.stepped_counts({1: 4, 2: 6, 3: 6}, 1) == {5: [1], 7: [2, 3]}
    assert S.stepped_counts({1: 4, 2: 12}, 1) == {5: [1]}          # 12 is the most
    assert S.stepped_counts({1: 4}, -1) == {}                        # 4 is the fewest


def test_shape_who_and_typed_values() -> None:
    data = _data()
    assert S.shape_text(data.lock(2), 6) == "measured spine"
    assert S.shape_text(data.lock(1), 5) == "edited, 5 handles"
    assert S.shape_text(data.lock(5), 4) == "as drawn, 4 handles"
    data.lock(3).handles = 7
    assert S.shape_text(data.lock(3), 7) == "measured spine, 7 handles (set here)"
    assert S.shapes_text([data.lock(1), data.lock(2), data.lock(5)]) == "1 edited: fringe_01; 1 drawn"
    assert S.shapes_text([data.lock(2)]) == "measured spines"
    assert S.who_text([]) == S.SELECT_A_LOCK
    assert S.who_text([data.lock(1)]) == "fringe_01, edited"
    assert S.who_text([data.lock(1), data.lock(2)]) == "2 locks, 1 edited"
    assert S.clean_value("width_cm", "2,5") == 2.5 and S.clean_value("width_cm", "0") is None
    assert S.clean_value("taper", 3) == 1.0 and S.clean_value("thick_cm", "nan") is None
    assert S.clean_value("taper", "x") is None


def test_the_warning_colour_is_the_panels() -> None:
    from tools.fx.auto_material.logic import STATUS_PINNED
    from tools.fx.auto_material.ui import STATUS_COLORS
    assert S.WARN_COLOR == STATUS_COLORS[STATUS_PINNED]


def test_tools_and_modes_are_points_keys_names() -> None:
    keys = S.points_keys()
    if keys is None:
        pytest.skip("points_keys (B3) not on this branch")
    assert (keys.TOOL_SELECT, keys.TOOL_POINTS, keys.TOOL_DRAW, keys.TOOL_PAINT) == S.TOOLS
    assert tuple(keys.MODES) == S.MODES


# ---------------------------------------------------------------------------
# The Tool bar: one tool at a time
# ---------------------------------------------------------------------------
def test_select_is_on_and_paint_is_dim_with_the_reason(env) -> None:
    adapter, view, c = env
    assert _on(view) == S.TOOL_SELECT
    paint = next(x for x in view.tools[0] if x["id"] == S.TOOL_PAINT)
    assert paint["dim"] and "paint layer" in paint["tip"]
    assert view.tools[1] == {"tool": S.TOOL_SELECT}


def test_a_click_on_dim_paint_says_why_and_changes_nothing(env) -> None:
    adapter, view, c = env
    c.select_locks([2])
    before = list(adapter.writes)
    assert c.set_tool(S.TOOL_PAINT) is False
    assert view.messages[-1][1] and "paint layer" in view.messages[-1][0]
    assert adapter.painting is None and adapter.writes == before and _on(view) == S.TOOL_SELECT


def test_paint_cell_paints_the_selected_paint_layer_and_ends_edit_points(env) -> None:
    adapter, view, c = env
    data = adapter.read_data(None)
    dens = data.add_mask("Crown thin", kind="density", density=75.0).id
    crown = data.add_mask("Crown", kind="paint", parent=dens).id
    adapter.text = data.to_json()
    c.select_locks([2])
    c.set_tool(S.TOOL_POINTS)
    assert _on(view) == S.TOOL_POINTS
    c.select(SEL_LAYER, (crown,))
    assert c.set_tool(S.TOOL_PAINT)
    assert adapter.painting == crown and _on(view) == S.TOOL_PAINT
    assert ("exit_tool", ()) in adapter.points_state.calls and c.tool == S.TOOL_SELECT
    assert c.set_tool(S.TOOL_POINTS)           # Edit points ends Paint first
    assert adapter.painting is None and _on(view) == S.TOOL_POINTS


def test_a_lock_row_picked_while_painting_ends_paint_and_keeps_the_lock(env) -> None:
    """select() inside the tree's selection signal: Paint ends without a tree rebuild there (it re-selected the
    paint layer over the clicked lock, t82 gui4); the next poll rebuilds it with the lock selected."""
    adapter, view, c = env
    data = adapter.read_data(None)
    dens = data.add_mask("Crown thin", kind="density", density=75.0).id
    crown = data.add_mask("Crown", kind="paint", parent=dens).id
    adapter.text = data.to_json()
    c.select(SEL_LAYER, (crown,))
    assert c.set_tool(S.TOOL_PAINT) and adapter.painting == crown
    built = []
    shown = view.show_tree
    view.show_tree = lambda rows: (built.append(rows), shown(rows))
    c.select("locks", (2,))
    assert adapter.painting is None and c.selection == ("locks", (2,)) and built == []
    c.poll()
    assert built and view.selection == ("locks", (2,))   # on the poll, outside the signal


def test_edit_points_with_nothing_selected_is_on_and_asks_for_a_lock(env) -> None:
    adapter, view, c = env
    assert c.set_tool(S.TOOL_POINTS)
    assert ("enter_points", (adapter.node, [])) in adapter.points_state.calls
    assert view.tools[1]["who"] == S.SELECT_A_LOCK and view.tools[1]["lock_ids"] == []
    assert "select a lock" in view.messages[-1][0]


def test_a_group_counts_as_its_locks_and_hidden_ones_get_no_handles(env) -> None:
    adapter, view, c = env
    data = adapter.read_data(None)
    data.lock(4).visible = False
    adapter.text = data.to_json()
    c.select_group("back")
    c.set_tool(S.TOOL_POINTS)
    assert ("enter_points", (adapter.node, [3, 5])) in adapter.points_state.calls
    assert "back_02 is hidden" in view.messages[-1][0]
    rows = view.tree
    assert _child(rows, 3)["editing"] and not _child(rows, 4)["editing"]


def test_handles_follow_the_selection_while_edit_points_is_on(env) -> None:
    adapter, view, c = env
    c.select_locks([1])
    c.set_tool(S.TOOL_POINTS)
    c.select_locks([2, 3])
    assert adapter.points_state.calls[-1] == ("set_locks", ([2, 3],))
    assert view.tools[1]["who"] == "2 locks" and view.tools[1]["handles"]["text"] == "auto (4 to 6)"


def test_esc_ends_the_tool_first_then_deselects(env) -> None:
    adapter, view, c = env
    c.select_locks([1])
    c.set_tool(S.TOOL_DRAW)
    assert c.escape() and c.tool == S.TOOL_SELECT and c.selection[1] == (1,)
    assert ("exit_tool", ()) in adapter.points_state.calls
    assert c.escape() and c.selection[0] == "none"


def test_enter_toggles_edit_points(env) -> None:
    adapter, view, c = env
    c.select_locks([1])
    assert c.toggle_tool(S.TOOL_POINTS) and c.tool == S.TOOL_POINTS
    assert c.toggle_tool(S.TOOL_POINTS) and c.tool == S.TOOL_SELECT


def test_without_the_viewer_state_the_tool_is_the_panels_and_says_so(env) -> None:
    adapter, view, c = env
    del adapter.points_state
    c.select_locks([1])
    assert c.set_tool(S.TOOL_POINTS) and c.tool == S.TOOL_POINTS
    assert S.NOT_INSTALLED in view.messages[-1][0]
    assert c.reset_shape() and adapter.read_data(None).lock(1).spine == []


def test_the_state_ending_in_the_viewport_reaches_the_panel(env) -> None:
    adapter, view, c = env
    c.select_locks([1])
    c.set_tool(S.TOOL_POINTS)
    keys = S.points_keys()
    if keys is None:
        pytest.skip("points_keys (B3) not on this branch")
    hooks = keys.HOOKS
    assert c._on_tool_record in hooks["tool"] and hooks["write"] == c._on_state_write
    adapter.points_state.now["tool"] = "select"        # Esc in the viewport
    c.poll()
    assert c.tool == S.TOOL_SELECT and _on(view) == S.TOOL_SELECT
    c.set_tool(S.TOOL_POINTS)
    rec = SimpleNamespace(tool="points", mode="rotate", held="scale", width_cm=3.0, thick_cm=0.6, taper=0.5,
                          message="Turned: fringe_01")
    hooks["tool"][-1](rec)
    c.poll()
    assert c.drag_mode == "rotate" and view.tools[1]["held"] == "scale" and c.new_lock["width_cm"] == 3.0
    assert view.messages[-1][0] == "Turned: fringe_01"
    c.set_node(adapter.node)                         # another node: the hook goes
    assert c._on_tool_record not in hooks["tool"]


def test_the_real_record_reaches_the_panel_and_paint_ends_the_shape_tool(env) -> None:
    """B3's own `points_keys.update` (what the state calls on R / E, a drag's message, Paint's `yield_to_paint`)."""
    keys = S.points_keys()
    if keys is None:
        pytest.skip("points_keys (B3) not on this branch")
    adapter, view, c = env
    keys.reset()
    c.select_locks([1])
    c.set_tool(S.TOOL_POINTS)
    keys.update(tool="points", mode="scale", held="rotate", message="Moved 2 handles of fringe_01")
    c.poll()
    assert c.drag_mode == "scale" and view.tools[1]["held"] == "rotate"
    assert view.messages[-1][0] == "Moved 2 handles of fringe_01"
    keys.update(held="")
    c.poll()
    assert view.tools[1]["held"] == ""
    keys.update(lock_ids=[2])                           # a click on another lock's hair in the viewport
    c.poll()
    assert c.selection == ("locks", (2,))
    keys.update(lock_ids=[])                            # a click on empty space keeps the selection
    c.poll()
    assert c.selection == ("locks", (2,))
    keys.update(tool="paint", held="")                  # yield_to_paint: Paint took the viewport
    adapter.points_state.now["tool"] = "paint"
    c.poll()
    assert c.tool == S.TOOL_SELECT
    keys.reset()


def test_a_row_picked_in_edit_points_rebuilds_the_tree_only_on_the_next_poll(env) -> None:
    """select() runs inside Qt's selection signal of the tree: a rebuild there deleted the item Qt was selecting
    and Houdini crashed (t82 gui3)."""
    adapter, view, c = env
    c.select_locks([1])
    c.set_tool(S.TOOL_POINTS)
    built = []
    shown = view.show_tree
    view.show_tree = lambda rows: (built.append(rows), shown(rows))
    c.select("locks", (2,))
    assert built == [] and adapter.points_state.calls[-1] == ("set_locks", ([2],))
    c.poll()
    assert len(built) == 1 and any(r.get("editing") for r in _flat(built[0]))
    c.poll()
    assert len(built) == 1


def _flat(rows):
    for r in rows:
        yield r
        yield from _flat(r.get("children", []))


def test_drag_mode_and_next_lock_go_to_the_state(env) -> None:
    adapter, view, c = env
    c.set_tool(S.TOOL_DRAW)
    assert ("set_new_lock", (2.0, 0.6, 0.3)) in adapter.points_state.calls
    c.set_new_lock(width_cm="2.5", taper="0.8")
    assert adapter.points_state.calls[-1] == ("set_new_lock", (2.5, 0.6, 0.8))
    assert view.tools[1]["width_cm"] == 2.5
    c.set_new_lock(thick_cm="-1")
    assert view.messages[-1][1] and c.new_lock["thick_cm"] == 0.6
    c.set_drag_mode("scale")
    assert adapter.points_state.calls[-1] == ("set_mode", ("scale",))
    with pytest.raises(ValueError):
        c.set_drag_mode("bend")


def test_the_handle_count_is_the_adapters_when_it_has_one(env) -> None:
    """t82 GUI: lock_infos' length gave hair_bang_03 5 handles, the measured spine (lock_handles, the viewer state's
    source) 4: the panel shows the adapter's number."""
    adapter, view, c = env
    adapter.lock_handles = lambda node, ids: {i: {"count": 9} for i in ids}
    c.refresh()
    c.select_locks([2])
    c.set_tool(S.TOOL_POINTS)
    assert view.tools[1]["handles"]["text"] == "auto (9)"
    adapter.calls.clear()
    assert c.step_handles(1) and adapter.calls == [("handles", (2,), 10)]


# ---------------------------------------------------------------------------
# Strip: handles and reset
# ---------------------------------------------------------------------------
def test_minus_plus_act_on_each_lock_in_one_undo_step(env) -> None:
    adapter, view, c = env
    c.select_locks([2, 3])            # 6 and 4 handles by length
    c.set_tool(S.TOOL_POINTS)
    adapter.calls.clear()
    assert c.step_handles(1)
    assert adapter.calls == [("handles", (3,), 5), ("handles", (2,), 7)]
    assert adapter.groups == [config.UNDO_SPINE["handles"]]
    assert view.tools[1]["handles"]["text"] == "mixed" or view.tools[1]["handles"]["own"]
    assert c.handles_auto()
    assert view.tools[1]["handles"]["text"] == "auto (4 to 6)"
    assert all(adapter.read_data(None).lock(i).handles is None for i in (2, 3))
    assert c.handles_auto() is False


def test_reset_shape_resets_only_the_edited_locks(env) -> None:
    adapter, view, c = env
    c.select_locks([1, 2])
    assert c.properties()["state"]["reset_ids"] == [1]
    assert c.reset_shape()
    assert adapter.calls[-1] == ("reset", (1,)) and "Ctrl+Z" in view.messages[-1][0]
    assert c.reset_shape() is False and "no edited lock" in view.messages[-1][0]


def test_reset_shape_sits_in_the_strip_while_edit_points_is_on(env) -> None:
    adapter, view, c = env
    c.select_locks([1])
    c.set_tool(S.TOOL_POINTS)
    assert view.tools[1]["reset"]["n"] == 1
    assert view.props["state"]["tool"] == S.TOOL_POINTS


# ---------------------------------------------------------------------------
# Rows and Properties
# ---------------------------------------------------------------------------
def test_rows_say_edited_drawn_and_at_rest(env) -> None:
    adapter, view, c = env
    rows = view.tree
    assert _child(rows, 1)["shape_edited"] and not _child(rows, 1)["drawn"]
    assert _child(rows, 2)["badges"] == ["edited"]          # own settings: the dot, as before
    d = _child(rows, 5)
    assert d["drawn"] and d["at_rest"] and not d["shape_edited"]
    adapter.scalp = {"wired": True, "ok": True, "drawn": 1, "message": ""}
    c._scalp_cache = None
    c.refresh()
    assert not _child(view.tree, 5)["at_rest"]


def test_a_drawn_lock_shows_its_shape_and_the_shot_warning(env) -> None:
    adapter, view, c = env
    c.select_locks([5])
    props = view.props
    d = {row[0]: row for row in props["details"]}
    assert d["Kind"][1] == "Drawn lock" and d["Shape"][1] == "as drawn, 4 handles"
    assert d["In shots"][1].startswith("at rest") and d["In shots"][2] == S.WARN_COLOR
    shape = props["drawn_shape"]
    assert shape["ids"] == [5] and shape["values"]["width_cm"]["value"] == 2.0 and props["drawn_ids"] == [5]


def test_drawn_values_write_one_step_and_become_the_next_locks(env) -> None:
    adapter, view, c = env
    c.select_locks([5])
    assert c.set_drawn_value("width_cm", 3.0)
    assert adapter.calls[-1] == ("drawn", (5,)) and adapter.read_data(None).lock(5).width_cm == 3.0
    assert c.new_lock["width_cm"] == 3.0 and "Update regions" in view.messages[-1][0]
    assert c.set_drawn_value("taper", "abc") is False and view.messages[-1][1]


def test_delete_drawn_gives_skin_back_and_refuses_a_mesh_lock(env) -> None:
    adapter, view, c = env
    c.select_locks([2])
    assert c.delete_drawn() is False and view.messages[-1][1]
    c.select_locks([5])
    assert c.delete_drawn()
    assert adapter.calls[-1] == ("delete", (5,)) and "back_01" in view.messages[-1][0]
    assert c.selection == ("none", ()) and adapter.read_data(None).lock(5) is None


def test_a_layer_of_a_deleted_drawn_lock_stays_with_no_lock(env) -> None:
    adapter, view, c = env
    data = adapter.read_data(None)
    lid = data.add_mask("Drawn thin", kind="density", scope="locks", locks=[5], density=40.0).id
    adapter.text = data.to_json()
    c.select_locks([5])
    c.delete_drawn()
    data = adapter.read_data(None)
    assert data.mask(lid) is not None and S.no_lock_layers(data)[0].id == lid
    top = view.tree[0]
    row = next(r for r in top["layers"] if r["id"] == lid)
    assert row["no_lock"] and top["layers"][-1]["layer"] == "base"
    assert owner_name(data, data.mask(lid)).startswith("no lock")


def test_a_lock_drawn_while_draw_lock_is_on_becomes_the_selection(env) -> None:
    adapter, view, c = env
    c.set_tool(S.TOOL_DRAW)
    c._on_state_write(adapter.node, {"id": 6, "gave": ["back_01", "back_02"]})
    data = adapter.read_data(None)
    data.locks.append(Lock(id=6, name="drawn_02", group="back", source=config.SOURCE_DRAWN, curve=list(CURVE),
                           drawn_curve=list(CURVE), width_cm=2.0, thick_cm=0.6))
    adapter.text = data.to_json()
    c.poll()
    assert c.selection == ("locks", (6,)) and c.tool == S.TOOL_DRAW
    d = {row[0]: row[1] for row in view.props["details"]}
    assert d["Skin from"] == "back_01, back_02"
    assert view.props["drawn_shape"]["note"] == "the next lock takes these"
    assert "stays at rest" in view.messages[-1][0]


def test_opening_a_node_with_a_drawn_lock_warns_once_unwired(env) -> None:
    adapter, view, c = env
    assert any("stays at rest" in m for m, _e in view.messages)
    view.messages.clear()
    adapter.scalp["message"] = ""
    c.set_node(adapter.node)
    assert not any("stays at rest" in m for m, _e in view.messages)


def test_overview_counts_drawn_and_edited(env) -> None:
    adapter, view, c = env
    rows = dict(view.props["overview"])
    assert rows["Locks"] == "5, 1 drawn" and rows["Edited"] == "1 lock"
    keys = dict(view.props["shortcuts"])
    assert "Enter" in keys and "Del" in keys


def test_node_gone_while_a_tool_is_on_raises_nothing(env) -> None:
    adapter, view, c = env
    c.set_tool(S.TOOL_POINTS)
    c.node_gone()
    assert c.tool == S.TOOL_SELECT and c.set_tool(S.TOOL_POINTS) is False


def test_an_adapter_without_v02b_keeps_the_panel_working() -> None:
    adapter = LayerAdapter()
    view = RecordingView()
    c = ctl.GroomController(adapter, view, adapter.node)
    c.select_locks([1])
    assert c.set_tool(S.TOOL_POINTS)
    c.set_tool(S.TOOL_SELECT)
    assert c.reset_shape() is False
    c.select_locks([1])
    assert c.step_handles(-1) is False and "newer" in view.messages[-1][0]


# ---------------------------------------------------------------------------
# The Qt panel, offscreen
# ---------------------------------------------------------------------------
def _qt(app, width=1100):
    from tools.fx.grooming.ui import GroomingUI

    adapter = SpineAdapter()
    adapter.points_state = _state_module()
    ui = GroomingUI()
    c = ctl.GroomController(adapter, ui)
    ctl.bind(ui, c)
    c.set_node(adapter.node)
    ui.resize(width, 800)
    ui.show()
    app.processEvents()
    return adapter, ui, c


def test_panel_tool_bar_strip_and_narrow_words(app, prefs) -> None:
    adapter, ui, c = _qt(app)
    assert ui._tool_cells["select"].isChecked() and ui._tool_strip.isHidden()
    assert ui._tool_cells["points"].text().strip() == "Edit points"
    assert ui._tool_cells["paint"].property("dim") is True
    c.select_locks([1, 2])
    ui.set_selection(c.selection)
    ui._tool_cells["points"].click()
    app.processEvents()
    assert c.tool == S.TOOL_POINTS and ui._tool_cells["points"].isChecked() and not ui._tool_strip.isHidden()
    assert ui._tool_cells["select"].key == "Esc"
    assert ui._handles_value.text() == "auto (5 to 6)" and not ui._strip_reset.isHidden()   # an edit keeps its 5
    assert ui._strip_reset.text().strip() == "Reset shape"
    ui._mode_cells["redraw"].click()
    assert c.drag_mode == "redraw" and ui._mode_cells["redraw"].isChecked()
    ui._handles_plus.click()
    assert ("handles", (1,), 6) in adapter.calls and ("handles", (2,), 7) in adapter.calls
    ui.resize(400, 800)
    app.processEvents()
    assert ui._tool_cells["points"].text().strip() == "Points" and ui._tool_cells["select"].key == ""
    assert ui._mode_cells["move"].text() == "" and ui._strip_reset.text() == ""
    ui.close()


def test_panel_rows_words_icon_and_filter(app, prefs) -> None:
    from tools.fx.grooming import ui as U
    from tools.fx.grooming import ui_spine as SP

    adapter, ui, c = _qt(app)
    row1 = ui._rows[("locks", 1)].data(U.COL_NAME, U.ROLE_ROW)
    row5 = ui._rows[("locks", 5)].data(U.COL_NAME, U.ROLE_ROW)
    assert ("edited", U.TEXT_LABEL) in U._RowDelegate.parts(row1)
    words = [t for t, _c in U._RowDelegate.parts(row5)]
    assert words[-2:] == ["drawn", SP.WARN_ICON]
    assert S.AT_REST_TIP in ui._rows[("locks", 5)].toolTip(U.COL_STATUS)
    assert U.FILTER_WORDS["edited"](row1) and not U.FILTER_WORDS["own"](row1)
    row2 = ui._rows[("locks", 2)].data(U.COL_NAME, U.ROLE_ROW)
    assert U.FILTER_WORDS["own"](row2) and not U.FILTER_WORDS["edited"](row2)
    assert U.FILTER_WORDS["drawn"](row5)
    ui._filter.setText("drawn")
    assert not ui._rows[("locks", 5)].isHidden() and ui._rows[("locks", 1)].isHidden()
    ui._filter.setText("")
    c.select_locks([1])
    ui.set_selection(c.selection)
    c.set_tool(S.TOOL_POINTS)
    app.processEvents()
    assert ui._rows[("locks", 1)].data(U.COL_NAME, U.ROLE_ROW)["editing"]
    ui.close()


def test_panel_reset_in_properties_drawn_section_and_delete_key(app, prefs) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QToolButton

    adapter, ui, c = _qt(app)
    c.select_locks([1])
    ui.set_selection(c.selection)
    app.processEvents()
    reset = next(b for b in ui._props_widget.findChildren(QToolButton) if b.text().strip() == "Reset shape")
    reset.click()
    assert adapter.calls[-1] == ("reset", (1,))
    c.select_locks([5])
    ui.set_selection(c.selection)
    app.processEvents()
    assert ui._layer_tools["delete"].isEnabled()
    assert any(b.objectName() == "DeleteLock" for b in ui._props_widget.findChildren(QToolButton))
    ui._tree.setFocus()
    QTest.keyClick(ui._tree, Qt.Key.Key_Delete)
    app.processEvents()
    assert adapter.calls[-1] == ("delete", (5,))
    ui.close()


def test_panel_paint_layer_properties_have_no_paint_button(app, prefs) -> None:
    from PySide6.QtWidgets import QToolButton

    adapter, ui, c = _qt(app)
    data = adapter.read_data(None)
    dens = data.add_mask("Crown thin", kind="density", density=75.0).id
    crown = data.add_mask("Crown", kind="paint", parent=dens).id
    adapter.text = data.to_json()
    c.refresh()
    c.select(SEL_LAYER, (crown,))
    ui.set_selection(c.selection)
    app.processEvents()
    texts = [b.text().strip() for b in ui._props_widget.findChildren(QToolButton)]
    assert "Paint" not in texts and "Painting" not in texts and "Eraser" in texts
    assert ui._tool_cells["paint"].property("dim") is False
    ui._tool_cells["paint"].click()
    app.processEvents()
    assert adapter.painting == crown and ui._tool_cells["paint"].isChecked()
    ui._tool_cells["select"].click()
    app.processEvents()
    assert adapter.painting is None and ui._tool_cells["select"].isChecked()
    ui.close()
