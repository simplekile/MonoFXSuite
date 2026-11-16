"""MONO Grooming panel, density layers (v0.2a): the controller's layer commands with a fake adapter (no Houdini).

The fake keeps the layer list in groom_data like the real one (`model.GroomData.add_mask` ...) and records each
call that would be one undo step of the adapter."""

from __future__ import annotations

import pytest

from tools.fx.grooming import config
from tools.fx.grooming import controller as ctl
from tools.fx.grooming.layers import SEL_LAYER, LayersMixin
from tools.fx.grooming.model import GroomData

from test_grooming_controller import FakeAdapter, RecordingView


class LayerAdapter(FakeAdapter):
    """FakeAdapter + the v0.2a layer functions of grooming_masks / grooming_adapter."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple] = []
        self.cooks = 0
        self.painting: int | None = None
        self.BRUSH = {"radius_cm": 1.0, "value": 1.0, "soft": 0.5, "erase": False, "xray": False, "view": "density"}
        self.HOOKS = {"stroke": None, "exit": None}
        self.settings = {"lookup": True, "lookup_kept": False, "lookup_text": "", "undo_cache_gb": 2.0,
                         "undo_deform_gb": 4.0}
        self.dropped = ""
        self.has_viewer = True

    def _step(self, label, data=None) -> None:
        if data is not None:
            self.text = data.to_json()
        self.calls.append(label)
        self.writes.append(label)

    def cook_display(self, node) -> None:
        self.cooks += 1

    def mask_add(self, node, name="", mode="normal", opacity=1.0, scope="all", group="", locks=(), kind=None,
                 value=1.0, parent=None, density=config.MASK_DENSITY_DEFAULT) -> int:
        data = self.read_data(node)
        kind = kind or ("density" if parent is None else "paint")
        layer = data.add_mask(name, mode, opacity, scope, group, locks, kind, value, parent, density)
        self._step(("add", kind, layer.id), data)
        return layer.id

    def mask_remove(self, node, layer_id) -> bool:
        data = self.read_data(node)
        data.remove_mask(layer_id)
        self._step(("remove", layer_id), data)
        return True

    def mask_move(self, node, layer_id, index, parent="keep") -> None:
        data = self.read_data(node)
        data.move_mask(layer_id, index, parent)
        self._step(("move", layer_id, index), data)

    def mask_set(self, node, layer_id, **fields) -> bool:
        data = self.read_data(node)
        layer = data.mask(layer_id)
        if layer.kind == "base":
            raise ValueError("base")
        before = dict(layer.__dict__)
        for k, v in fields.items():
            setattr(layer, k, list(v) if k == "locks" else v)
        if dict(layer.__dict__) == before:
            return False
        self._step(("set", layer_id, tuple(sorted(fields))), data)
        return True

    def mask_fill(self, node, layer_id, value=1.0):
        self._step(("fill", layer_id))

    def mask_clear(self, node, layer_id):
        self._step(("clear", layer_id))

    def mask_invert(self, node, layer_id):
        self._step(("invert", layer_id))

    def paint_enter(self, node, layer_id) -> bool:
        if self.read_data(node).mask(layer_id).kind != "paint":
            raise ValueError("not a paint layer")
        self.painting = layer_id if self.has_viewer else None
        return self.has_viewer

    def paint_exit(self, node=None) -> None:
        self.painting = None

    def paint_layer(self, node):
        return self.painting

    def set_brush(self, **fields) -> dict:
        self.BRUSH.update(fields)
        return dict(self.BRUSH)

    def brush(self) -> dict:
        return dict(self.BRUSH)

    def undo_cache_usage(self, node) -> dict:
        return {"bytes": 1.52 * 2 ** 30, "live_bytes": 0.65 * 2 ** 30, "undo_bytes": 0.87 * 2 ** 30, "undo_states": 14,
                "limit_bytes": 2 * 2 ** 30, "dropped": 0, "capture_bytes": 0, "deformed_bytes": 0,
                "deformed_states": 0, "deformed_limit_bytes": 4 * 2 ** 30}

    def mask_dropped(self, node) -> str:
        return self.dropped

    def node_settings(self, node) -> dict:
        return dict(self.settings)

    def set_node_setting(self, node, name, value) -> None:
        self.settings[name] = value
        self.calls.append(("node", name, value))


def _env(adapter: LayerAdapter | None = None):
    adapter = adapter or LayerAdapter()
    view = RecordingView()
    view.set_paint_state = lambda on, brush: setattr(view, "paint", (on, brush))
    c = ctl.GroomController(adapter, view, adapter.node)
    return adapter, view, c


@pytest.fixture
def env():
    return _env()


def _layered(adapter: LayerAdapter) -> dict[str, int]:
    """All locks: Crown thin (D 75; paint Crown, fill Soften). Group fringe: Fringe up. Lock 3: Start thin."""
    data = adapter.read_data(None)
    ids = {}
    ids["crown_thin"] = data.add_mask("Crown thin", kind="density", density=75.0).id
    ids["crown"] = data.add_mask("Crown", kind="paint", parent=ids["crown_thin"]).id
    ids["soften"] = data.add_mask("Soften", kind="fill", mode="multiply", opacity=0.6, value=0.5,
                                  parent=ids["crown_thin"]).id
    ids["fringe_up"] = data.add_mask("Fringe up", kind="density", scope="group", group="fringe").id
    ids["start_thin"] = data.add_mask("Start thin", kind="density", scope="locks", locks=[3], density=0.0).id
    ids["upper"] = data.add_mask("Upper", kind="density", density=300.0).id
    adapter.text = data.to_json()
    return ids


def _row(rows, kind, rid):
    for r in rows:
        if (r["kind"], r["id"]) == (kind, rid):
            return r
        for c in r.get("children", []):
            if (c["kind"], c["id"]) == (kind, rid):
                return c
    raise KeyError((kind, rid))


# ---------------------------------------------------------------------------
# The tree: lock row > density layers > mask layers
# ---------------------------------------------------------------------------
def test_tree_puts_each_layer_under_its_owner_row_top_first(env) -> None:
    adapter, view, c = env
    ids = _layered(adapter)
    c.refresh()
    top = _row(view.tree, "defaults", "")
    names = [r["name"] for r in top["layers"]]
    assert names == ["Upper", "Crown thin", "Automatic"]          # upper wins; Automatic at the bottom
    assert top["layers"][-1]["layer"] == "base"
    crown = top["layers"][1]
    assert [m["name"] for m in crown["masks"]] == ["Soften", "Crown"]   # the mask's top first
    assert crown["masks"][0]["mode"] == "multiply" and crown["masks"][0]["layer"] == "fill"
    assert [r["name"] for r in _row(view.tree, "group", "fringe")["layers"]] == ["Fringe up"]
    assert [r["name"] for r in _row(view.tree, "locks", 3)["layers"]] == ["Start thin"]
    assert _row(view.tree, "locks", 1)["layers"] == []
    assert ids


def test_no_layer_shows_only_automatic(env) -> None:
    _adapter, view, _c = env
    top = _row(view.tree, "defaults", "")
    assert [r["layer"] for r in top["layers"]] == ["base"]


# ---------------------------------------------------------------------------
# Add / delete / reorder / rename / eye
# ---------------------------------------------------------------------------
def test_new_density_layer_takes_the_selected_row_as_owner(env) -> None:
    adapter, view, c = env
    c.select_group("fringe")
    lid = c.add_density_layer()
    data = adapter.read_data(None)
    layer = data.mask(lid)
    assert (layer.kind, layer.scope, layer.group, layer.density) == ("density", "group", "fringe",
                                                                     config.MASK_DENSITY_DEFAULT)
    assert adapter.calls == [("add", "density", lid)]          # one adapter call: one undo step
    assert c.selection == (SEL_LAYER, (lid,))
    assert "changes nothing until" in view.messages[-1][0]
    assert adapter.cooks >= 1                                  # cooked inside the loading line


def test_new_density_layer_on_one_lock_and_refused_on_several(env) -> None:
    adapter, view, c = env
    c.select_locks([2])
    lid = c.add_density_layer()
    assert adapter.read_data(None).mask(lid).locks == [2]
    c.select_locks([1, 2])
    assert c.add_density_layer() is None
    assert view.messages[-1] == ("Select one lock (or its group) for a density layer of its own", True)
    assert len(adapter.calls) == 1


def test_nothing_selected_makes_an_all_locks_layer(env) -> None:
    adapter, _view, c = env
    lid = c.add_density_layer()
    assert adapter.read_data(None).mask(lid).scope == "all"


def test_mask_layer_goes_into_the_selected_density_layer_or_its_parent(env) -> None:
    adapter, view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["crown"],))
    new = c.add_mask_layer("paint")
    data = adapter.read_data(None)
    assert data.mask(new).parent == ids["crown_thin"] and data.mask(new).kind == "paint"
    c.select(SEL_LAYER, (ids["fringe_up"],))
    fill = c.add_mask_layer("fill")
    assert adapter.read_data(None).mask(fill).parent == ids["fringe_up"]
    assert "applies everywhere" in view.messages[-1][0]
    c.select_locks([1])
    assert c.add_mask_layer("paint") is None
    assert view.messages[-1][1] is True


def test_delete_density_layer_takes_its_mask_and_selects_its_row(env) -> None:
    adapter, _view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["crown_thin"],))
    assert c.delete_layer()
    data = adapter.read_data(None)
    assert data.mask(ids["crown_thin"]) is None and data.mask(ids["crown"]) is None
    assert c.selection == ("defaults", ())
    c.select(SEL_LAYER, (ids["start_thin"],))
    c.delete_layer()
    assert c.selection == ("locks", (3,))


def test_delete_mask_layer_selects_its_density_layer(env) -> None:
    adapter, _view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["soften"],))
    c.delete_layer()
    assert c.selection == (SEL_LAYER, (ids["crown_thin"],))


def test_automatic_cannot_be_deleted_moved_or_set(env) -> None:
    adapter, view, c = env
    c.select(SEL_LAYER, (config.MASK_BASE_ID,))
    assert not c.delete_layer()
    assert not c.move_layer(True)
    assert not c.set_layer(config.MASK_BASE_ID, density=10.0)
    assert adapter.calls == []
    assert all(err for _t, err in view.messages[-3:])
    assert "Automatic" in view.props["title"] and "cannot be painted" in view.props["note"]


def test_move_up_and_down_stays_among_the_rows_own_layers(env) -> None:
    adapter, view, c = env
    ids = _layered(adapter)
    # density layers bottom first: Crown thin, Fringe up, Start thin, Upper; All locks owns Crown thin and Upper
    c.select(SEL_LAYER, (ids["crown_thin"],))
    assert c.move_layer(True)
    order = [m.id for m in adapter.read_data(None).density_layers()]
    assert order.index(ids["crown_thin"]) > order.index(ids["upper"])
    top = _row(view.tree, "defaults", "")
    assert [r["name"] for r in top["layers"]] == ["Crown thin", "Upper", "Automatic"]
    assert not c.move_layer(True)                      # already the top of All locks
    assert "already at the top" in view.messages[-1][0]
    assert c.move_layer(False)
    assert [r["name"] for r in _row(view.tree, "defaults", "")["layers"]] == ["Upper", "Crown thin", "Automatic"]


def test_move_mask_layer_inside_its_mask(env) -> None:
    adapter, view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["soften"],))
    assert not c.move_layer(True)                      # Soften is the mask's top
    assert c.move_layer(False)
    masks = [m.id for m in adapter.read_data(None).mask_layers(ids["crown_thin"])]
    assert masks == [ids["soften"], ids["crown"]]
    assert c.selection == (SEL_LAYER, (ids["soften"],))


def test_rename_eye_density_opacity_mode_value(env) -> None:
    adapter, view, c = env
    ids = _layered(adapter)
    assert c.rename_layer(ids["crown_thin"], "  Crown down ")
    assert c.set_layer_on(ids["crown"], False)
    assert c.set_layer(ids["crown_thin"], density=300.0)
    assert view.messages[-1][0] == "Crown down: density 300 / cm²"
    assert c.set_layer(ids["crown_thin"], opacity=0.5)
    assert c.set_layer(ids["soften"], mode="add")
    assert c.set_layer(ids["soften"], value=0.25)
    data = adapter.read_data(None)
    assert data.mask(ids["crown_thin"]).name == "Crown down"
    assert data.mask(ids["crown"]).on is False
    assert (data.mask(ids["crown_thin"]).density, data.mask(ids["crown_thin"]).opacity) == (300.0, 0.5)
    assert (data.mask(ids["soften"]).mode, data.mask(ids["soften"]).value) == ("add", 0.25)
    assert len(adapter.calls) == 6                     # one undo step each
    assert not c.set_layer(ids["soften"], value=0.25)  # nothing changed: no step
    assert not c.rename_layer(ids["soften"], "  ")
    assert len(adapter.calls) == 6


def test_owner_change_moves_the_layer_to_another_row(env) -> None:
    adapter, view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["crown_thin"],))
    owners = view.props["owners"]
    assert owners[0] == "All locks" and view.props["owner_index"] == 0
    assert c.set_layer_owner(ids["crown_thin"], owners.index("Group Back"))
    layer = adapter.read_data(None).mask(ids["crown_thin"])
    assert (layer.scope, layer.group) == ("group", "back")
    assert "Crown thin" in [r["name"] for r in _row(view.tree, "group", "back")["layers"]]
    assert not c.set_layer_owner(ids["crown_thin"], 999)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------
def test_properties_show_only_the_selected_rows_parms(env) -> None:
    adapter, view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["crown_thin"],))
    p = view.props
    assert p["kind"] == SEL_LAYER and p["layer"]["layer"] == "density"
    assert p["picks"] == [0.0, 75.0, 150.0, 300.0] and "owners" in p and "brush" not in p
    c.select(SEL_LAYER, (ids["soften"],))
    p = view.props
    assert p["layer"]["layer"] == "fill" and p["value_picks"] == [0.0, 0.5, 1.0] and "brush" not in p
    assert [k for k, _l in p["modes"]] == list(config.MASK_MODES)
    c.select(SEL_LAYER, (ids["crown"],))
    p = view.props
    assert p["layer"]["layer"] == "paint" and p["brush"]["radius_cm"] == 1.0 and p["painting"] is False
    assert "mask of Crown thin (75 / cm²)" in p["subtitle"]


def test_layer_selection_focuses_its_owners_locks(env) -> None:
    adapter, _view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["fringe_up"],))
    assert adapter.selected[-1] == [1, 2]
    c.select(SEL_LAYER, (ids["start_thin"],))
    assert adapter.selected[-1] == [3]


# ---------------------------------------------------------------------------
# Paint
# ---------------------------------------------------------------------------
def test_paint_on_a_paint_layer_only(env) -> None:
    adapter, view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["crown_thin"],))
    assert not c.toggle_paint()
    assert "paint layer" in view.messages[-1][0] and adapter.painting is None
    c.select(SEL_LAYER, (ids["crown"],))
    assert c.toggle_paint()
    assert adapter.painting == ids["crown"] and c.paint_layer_id == ids["crown"]
    assert adapter.HOOKS["stroke"] is not None and adapter.HOOKS["exit"] is not None
    assert view.paint[0] is True and view.props["painting"] is True
    assert c.toggle_paint() and adapter.painting is None and view.paint[0] is False
    assert adapter.calls == []                         # Paint itself writes nothing


def test_paint_shows_hair_preview_and_puts_hair_back(env) -> None:
    adapter, _view, c = env
    ids = _layered(adapter)
    c.set_display("hair")
    c.select(SEL_LAYER, (ids["crown"],))
    c.paint_on()
    assert c.display_mode == "hair_preview" and adapter.display[-1][0] == "hair_preview"
    c.paint_off()
    assert c.display_mode == "hair" and adapter.display[-1][0] == "hair"


def test_the_brush_follows_the_selection(env) -> None:
    adapter, view, c = env
    ids = _layered(adapter)
    data = adapter.read_data(None)
    other = data.add_mask("Edge", kind="paint", parent=ids["fringe_up"]).id
    adapter.text = data.to_json()
    c.select(SEL_LAYER, (ids["crown"],))
    c.paint_on()
    c.select(SEL_LAYER, (other,))                       # another paint layer: it takes the brush
    assert adapter.painting == other and c.paint_layer_id == other
    c.select(SEL_LAYER, (ids["fringe_up"],))            # a density layer paints nothing
    assert adapter.painting is None and c.paint_layer_id is None
    c.select(SEL_LAYER, (ids["crown"],))
    c.paint_on()
    c.select_locks([1])                                 # a lock row ends Paint too
    assert adapter.painting is None
    c.select(SEL_LAYER, (ids["crown"],))
    c.paint_on()
    assert c.escape() and adapter.painting is None      # Esc in the panel: Paint off first


def test_deleting_or_undoing_the_painted_layer_ends_paint(env) -> None:
    adapter, _view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["crown"],))
    c.paint_on()
    c.delete_layer()
    assert adapter.painting is None and c.paint_layer_id is None
    c.select(SEL_LAYER, (ids["soften"],))
    data = adapter.read_data(None)
    paint = data.add_mask("P", kind="paint", parent=ids["crown_thin"]).id
    adapter.text = data.to_json()
    c.select(SEL_LAYER, (paint,))
    c.paint_on()
    data = adapter.read_data(None)
    data.remove_mask(paint)                              # e.g. an undo of its add, outside the panel
    adapter.text = data.to_json()
    c.poll()
    assert c.paint_layer_id is None and adapter.painting is None and c.selection[0] == "none"


def test_paint_ended_in_the_viewport_reaches_the_panel(env) -> None:
    adapter, view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["crown"],))
    c.paint_on()
    adapter.painting = None
    adapter.HOOKS["exit"]()
    assert c.paint_layer_id is None and view.paint[0] is False
    c.paint_on()
    adapter.painting = None                              # an adapter reloaded under it: the poll sees it
    c.poll()
    assert c.paint_layer_id is None


def test_a_stroke_cooks_in_the_loading_line_and_says_so(env) -> None:
    adapter, view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["crown"],))
    c.paint_on()
    cooks = adapter.cooks
    adapter.HOOKS["stroke"](adapter.node)
    assert adapter.cooks == cooks + 1
    assert view.messages[-1][0] == "Stroke on Crown: Ctrl+Z takes it back"


def test_paint_without_a_viewer_says_so(env) -> None:
    adapter, view, c = env
    adapter.has_viewer = False
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["crown"],))
    assert not c.paint_on()
    assert c.paint_layer_id is None and view.messages[-1] == ("Paint needs a Scene Viewer showing this node", True)


def test_brush_and_scalp_view_are_session_state(env) -> None:
    adapter, view, c = env
    c.set_brush(value=0.5, radius_cm=2.0, soft=0.2, erase=True)
    c.set_brush(view="layer", xray=True)
    assert adapter.BRUSH["value"] == 0.5 and adapter.BRUSH["view"] == "layer" and adapter.BRUSH["xray"]
    assert view.paint[1]["radius_cm"] == 2.0
    assert adapter.writes == []                         # nothing written to the node, no undo step


def test_fill_clear_invert_only_on_a_paint_layer(env) -> None:
    adapter, _view, c = env
    ids = _layered(adapter)
    c.select(SEL_LAYER, (ids["crown"],))
    for action in ("fill", "clear", "invert"):
        assert c.paint_layer_action(action)
    assert adapter.calls == [("fill", ids["crown"]), ("clear", ids["crown"]), ("invert", ids["crown"])]
    c.select(SEL_LAYER, (ids["soften"],))
    assert not c.paint_layer_action("fill")


# ---------------------------------------------------------------------------
# Settings and notes
# ---------------------------------------------------------------------------
def test_settings_info_and_the_usage_readout(env) -> None:
    adapter, _view, c = env
    info = c.settings_info()
    assert info["editable"] and info["undo_cache_gb"] == 2.0 and info["usage"]["undo_states"] == 14
    text = LayersMixin.usage_text(info["usage"])
    assert text.startswith("Holds 1.52 of 2.00 GB: shown now 0.65 GB, 14 earlier states 0.87 GB")
    assert "no deformed state held" in LayersMixin.usage_text(info["usage"], deformed=True)
    assert LayersMixin.usage_text(None).startswith("Nothing held yet")


def test_node_settings_go_through_the_adapter(env) -> None:
    adapter, view, c = env
    assert c.set_node_setting("undo_cache_gb", 3.0)
    assert c.set_node_setting("lookup", False)
    assert adapter.calls == [("node", "undo_cache_gb", 3.0), ("node", "lookup", False)]
    assert view.messages[-1][0].startswith("Fit lookup per lock: off")
    with pytest.raises(KeyError):
        c.set_node_setting("region_subdiv", 2)


def test_opening_a_node_tells_the_older_build_and_the_lookup(env) -> None:
    adapter = LayerAdapter()
    adapter.dropped = "1 layer dropped (a factor over 1)"
    adapter.settings.update(lookup=False, lookup_kept=True, lookup_text="this scene was saved before it")
    _a, view, _c = _env(adapter)
    text, error = view.messages[-1]
    assert "1 layer dropped" in text and "This scene was saved before it" in text and error


def test_an_adapter_without_layers_keeps_the_v01_panel_working() -> None:
    adapter = FakeAdapter()
    view = RecordingView()
    c = ctl.GroomController(adapter, view, adapter.node)
    top = _row(view.tree, "defaults", "")
    assert [r["layer"] for r in top["layers"]] == ["base"]
    assert c.add_density_layer() is None and view.messages[-1][1] is True
    assert c.settings_info() == {"editable": False}
    assert isinstance(GroomData.from_json(adapter.text), GroomData)


# ---------------------------------------------------------------------------
# The Qt panel, offscreen
# ---------------------------------------------------------------------------
from test_grooming_controller import app, prefs  # noqa: E402,F401  (pytest fixtures)


def _qt_panel(app):
    from tools.fx.grooming.ui import GroomingUI

    adapter = LayerAdapter()
    ids = _layered(adapter)
    ui = GroomingUI()
    c = ctl.GroomController(adapter, ui)
    ctl.bind(ui, c)
    c.set_node(adapter.node)
    ui.resize(1100, 800)
    ui.show()
    app.processEvents()
    return adapter, ui, c, ids


def test_panel_tree_holds_layers_first_and_the_eye_left(app, prefs) -> None:
    from tools.fx.grooming.ui import COL_EYE, COL_NAME

    adapter, ui, c, ids = _qt_panel(app)
    root = ui._rows[(ctl.SEL_DEFAULTS, "")]
    assert [root.child(k).text(COL_NAME) for k in range(3)] == ["Upper", "Crown thin", "Automatic"]
    crown = ui._rows[(SEL_LAYER, ids["crown_thin"])]
    assert [crown.child(k).text(COL_NAME) for k in range(crown.childCount())] == ["Soften", "Crown"]
    assert crown.isExpanded()
    lock3 = ui._rows[(ctl.SEL_LOCKS, 3)]
    assert lock3.child(0).text(COL_NAME) == "Start thin" and lock3.isExpanded()
    assert ui._tree.header().visualIndex(COL_EYE) == 0
    ui.close()


def test_panel_layer_eye_select_rename_and_delete_key(app, prefs) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from tools.fx.grooming.ui import COL_EYE, COL_NAME

    adapter, ui, c, ids = _qt_panel(app)
    tree = ui._tree
    item = ui._rows[(SEL_LAYER, ids["crown"])]
    tree.scrollToItem(item)
    app.processEvents()
    rect = tree.visualItemRect(item)
    x = tree.header().sectionViewportPosition(COL_EYE) + tree.header().sectionSize(COL_EYE) // 2
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(x, rect.center().y()))
    app.processEvents()
    assert adapter.read_data(None).mask(ids["crown"]).on is False
    ui._rows[(SEL_LAYER, ids["soften"])].setSelected(True)
    app.processEvents()
    assert c.selection == (SEL_LAYER, (ids["soften"],))
    assert ui._props["layer"]["layer"] == "fill" and not ui._row_bar_lay.parentWidget().isHidden()
    item = ui._rows[(SEL_LAYER, ids["soften"])]
    item.setText(COL_NAME, "Softer")                       # what an F2 edit ends with
    app.processEvents()
    app.processEvents()
    assert adapter.read_data(None).mask(ids["soften"]).name == "Softer"
    tree.setFocus()
    QTest.keyClick(tree, Qt.Key.Key_Delete)
    app.processEvents()
    assert adapter.read_data(None).mask(ids["soften"]) is None
    ui.close()


def test_panel_paint_strip_and_properties_follow_paint(app, prefs) -> None:
    from PySide6.QtWidgets import QToolButton

    adapter, ui, c, ids = _qt_panel(app)
    c.select(SEL_LAYER, (ids["crown"],))
    ui.set_selection(c.selection)
    app.processEvents()
    assert ui._paint_strip.isHidden()
    paint = next(b for b in ui._props_widget.findChildren(QToolButton) if b.text().strip() == "Paint")
    paint.click()
    app.processEvents()
    assert adapter.painting == ids["crown"] and not ui._paint_strip.isHidden()
    ui._view_buttons["roots"].click()
    assert adapter.BRUSH["view"] == "roots" and ui._legend.isHidden()
    fold = next(b for b in ui._props_widget.findChildren(QToolButton) if b.text().strip() == "Fold")
    fold.click()
    app.processEvents()
    assert any(b.text().strip() == "Show" for b in ui._props_widget.findChildren(QToolButton))
    c.paint_off()
    app.processEvents()
    assert ui._paint_strip.isHidden() and ui._props_folded is False
    ui.close()


def test_panel_clear_asks_once_then_clears(app, prefs) -> None:
    from PySide6.QtWidgets import QToolButton

    adapter, ui, c, ids = _qt_panel(app)
    c.select(SEL_LAYER, (ids["crown"],))
    app.processEvents()
    clear = next(b for b in ui._props_widget.findChildren(QToolButton) if b.text() == "Clear")
    clear.click()
    assert adapter.calls == [] and clear.text() == "Clear: click again"
    clear.click()
    assert adapter.calls == [("clear", ids["crown"])]
    ui.close()


def test_panel_settings_page_and_back(app, prefs) -> None:
    adapter, ui, c, ids = _qt_panel(app)
    c.select(SEL_LAYER, (ids["crown_thin"],))
    ui.show_settings(c.settings_info())
    app.processEvents()
    texts = [w.text() for w in ui._props_widget.findChildren(type(ui._message_label))]
    assert "Settings" in texts and any(t.startswith("Holds 1.52 of 2.00 GB") for t in texts)
    c.refresh()                                           # a poll does not close the page
    assert ui._settings_open
    from tools.fx.grooming import ui_layers
    ui_layers.close_settings(ui)
    app.processEvents()
    assert not ui._settings_open and ui._props["layer"]["name"] == "Crown thin"
    ui.close()
