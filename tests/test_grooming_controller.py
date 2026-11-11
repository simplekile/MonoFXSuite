"""MONO Grooming panel controller with a fake adapter (no Houdini): what each action writes, and shows."""

from __future__ import annotations

import os

import pytest

from tools.fx.grooming import controller as ctl
from tools.fx.grooming.logic import DetectReport, LockInfo, Match, PublishResult
from tools.fx.grooming.model import GroomData, Group, Lock, Orphan


class FakeNode:
    def path(self) -> str:
        return "/obj/char_Helen/mono_grooming1"


def _data() -> GroomData:
    return GroomData(
        asset="char_Helen",
        groups=[Group(id="fringe", name="Fringe", color=(0.9, 0.4, 0.4)), Group(id="back", name="Back")],
        locks=[
            Lock(id=1, name="fringe_01", group="fringe"),
            Lock(id=2, name="fringe_02", group="fringe", overrides={"clump": 0.8}),
            Lock(id=3, name="back_01", group="back", match="unsure"),
            Lock(id=4, name="back_02", group="back", match="new"),
        ],
        orphans=[Orphan(id=9, name="back_old", group="back", overrides={"frizz": 0.3})],
    )


class FakeAdapter:
    """The spec's Adapter API, storing groom_data as JSON like the parm does."""

    def __init__(self) -> None:
        self.node = FakeNode()
        self.text = _data().to_json()
        self.writes: list[str] = []
        self.viewport: list[int] = []
        self.selected: list[list[int]] = []
        self.display: list[tuple] = []
        self.report = DetectReport()
        self.publish_result = PublishResult(True, "", "v008", "")

    def find_nodes(self):
        return [self.node]

    def create_node(self, parent=None):
        return self.node

    def read_data(self, node) -> GroomData:
        return GroomData.from_json(self.text)

    def write_data(self, node, data: GroomData, label: str) -> None:
        self.text = data.to_json()
        self.writes.append(label)

    deform = (True, True)

    def deform_state(self, node):
        return self.deform

    def set_shot_deform(self, node, on) -> None:
        self.deform = (self.deform[0], bool(on))

    def set_drag_preview(self, node, ids) -> None:
        self.light = sorted(ids) if ids else None

    def write_data_live(self, node, data: GroomData) -> None:   # no undo step
        self.text = data.to_json()
        self.live = getattr(self, "live", 0) + 1

    def lock_infos(self, node):
        return [LockInfo(i, f"l{i}", "g", (0, 0, 0), 10.0, 1.5, 0.4, 0.2, 1000, 3.0) for i in (1, 2, 3, 4)]

    def detect(self, node) -> DetectReport:
        data = self.read_data(node)
        data.regions_stale = True
        self.text = data.to_json()
        self.writes.append("detect")   # the real adapter writes groom_data once (one undo step)
        return self.report

    def split_regions(self, node) -> None:
        data = self.read_data(node)
        data.regions_stale = False
        self.text = data.to_json()
        self.writes.append("split")

    def set_display(self, node, mode, color_by, preview) -> None:
        self.display.append((mode, color_by, preview))

    def selected_lock_ids(self, node):
        return list(self.viewport)

    def select_locks(self, node, ids) -> None:
        self.selected.append(list(ids))

    def publish(self, node, version):
        self.published_version = version
        return self.publish_result

    # session 009's isolate: a view state, not in groom_data
    isolated = None

    def set_isolate(self, node, ids) -> None:
        self.isolated = sorted(ids) if ids else None

    def isolate_ids(self, node):
        return self.isolated

    # session 009's per-lock flags: one write, regions out of date
    def _flag(self, ids, field, value):
        data = self.read_data(self.node)
        changed = 0
        for lk in data.locks:
            if lk.id in ids and getattr(lk, field) != value:
                setattr(lk, field, value)
                changed += 1
        data.regions_stale = True
        self.write_data(self.node, data, field)
        return changed

    def set_root_flip(self, node, ids, flip):
        return self._flag(ids, "root_flip", flip)

    def set_excluded(self, node, ids, excluded):
        return self._flag(ids, "excluded", excluded)


class RecordingView:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []
        self.tree: list[dict] = []
        self.props: dict = {}
        self.selection = None
        self.stale = None
        self.version = None

    def show_node(self, path, asset):
        self.node = (path, asset)

    def show_tree(self, rows):
        self.tree = rows

    def set_selection(self, selection):
        self.selection = selection

    def show_properties(self, props):
        self.props = props

    def set_message(self, text, error=False):
        self.messages.append((text, error))

    def set_regions_stale(self, stale):
        self.stale = stale

    def set_display_state(self, mode, color_by):
        self.display_state = (mode, color_by)

    def set_publish_version(self, version, note):
        self.version = (version, note)

    isolate = ""
    publish_warning = ""
    deform_state = None

    def set_deform_state(self, wired, on):
        self.deform_state = (wired, on)

    def set_isolate(self, text):
        self.isolate = text

    def set_publish_warning(self, text):
        self.publish_warning = text


@pytest.fixture
def env():
    adapter = FakeAdapter()
    view = RecordingView()
    c = ctl.GroomController(adapter, view, adapter.node)
    return adapter, view, c


def _setting(view: RecordingView, key: str) -> dict:
    return next(s for s in view.props["settings"] if s["key"] == key)


def test_lock_edit_is_one_write_with_the_lock_override(env) -> None:
    adapter, view, c = env
    c.select_locks([1])
    assert adapter.selected == [[1]]  # the viewport follows the panel
    c.set_value("density", 220.0)
    assert len(adapter.writes) == 1
    data = adapter.read_data(None)
    assert data.lock(1).overrides == {"density": 220.0}
    assert data.lock(2).overrides == {"clump": 0.8}  # other locks untouched
    s = _setting(view, "density")
    assert (s["value"], s["source"], s["resettable"]) == (220.0, "lock", True)


def test_edit_on_several_locks_is_one_write(env) -> None:
    adapter, _view, c = env
    c.select_locks([1, 3])
    c.set_value("frizz", 0.5)
    data = adapter.read_data(None)
    assert len(adapter.writes) == 1
    assert data.lock(1).overrides["frizz"] == data.lock(3).overrides["frizz"] == 0.5


def test_reset_removes_the_override(env) -> None:
    adapter, view, c = env
    c.select_locks([2])
    assert _setting(view, "clump")["source"] == "lock"
    c.reset_value("clump")
    assert adapter.read_data(None).lock(2).overrides == {}
    s = _setting(view, "clump")
    assert s["source"] == "builtin" and not s["resettable"]
    assert len(adapter.writes) == 1
    c.reset_value("clump")  # nothing to reset: no write
    assert len(adapter.writes) == 1


def test_group_edit_applies_to_its_locks(env) -> None:
    adapter, view, c = env
    c.select_group("fringe")
    assert sorted(adapter.selected[-1]) == [1, 2]
    c.set_value("clump", 0.2)
    data = adapter.read_data(None)
    assert len(adapter.writes) == 1
    assert data.group("fringe").overrides == {"clump": 0.2}
    assert data.resolve(1)["clump"] == 0.2 and data.source_of(1, "clump") == "group"
    assert data.resolve(2)["clump"] == 0.8  # its own override still wins
    assert data.resolve(3)["clump"] == 0.2  # other group: built-in
    assert _setting(view, "clump")["source"] == "group"


def test_defaults_edit_and_mixed_source(env) -> None:
    adapter, view, c = env
    c.select(ctl.SEL_DEFAULTS)
    c.set_value("length_mult", 1.3)
    assert adapter.read_data(None).defaults == {"length_mult": 1.3}
    c.select_locks([1, 2])
    assert _setting(view, "clump")["source"] == "mixed"
    assert _setting(view, "length_mult")["source"] == "defaults"


def test_tree_rows_badges_and_orphans(env) -> None:
    _adapter, view, _c = env
    kinds = [r["kind"] for r in view.tree]
    assert kinds == [ctl.SEL_DEFAULTS, ctl.SEL_GROUP, ctl.SEL_GROUP, ctl.ORPHANS_ROW]
    back = view.tree[2]
    assert {c["id"]: c["badges"] for c in back["children"]} == {3: ["unsure"], 4: ["new"]}
    assert set(back["badges"]) == {"unsure", "new"}
    assert view.tree[1]["children"][1]["badges"] == ["edited"]
    assert [o["id"] for o in view.tree[3]["children"]] == [9]


def test_visibility_display_and_colour_are_one_write_each(env) -> None:
    adapter, _view, c = env
    c.set_visible(ctl.SEL_LOCKS, [1, 2], False)
    c.set_row_display(ctl.SEL_GROUP, ["back"], "hair")
    c.set_group_color("back", (0.1, 0.2, 0.3))
    assert len(adapter.writes) == 3
    data = adapter.read_data(None)
    assert not data.lock(1).visible and not data.lock(2).visible and data.lock(3).visible
    assert data.group("back").display == "hair" and data.group("back").color == (0.1, 0.2, 0.3)
    c.set_row_display(ctl.SEL_GROUP, ["back"], None)
    assert adapter.read_data(None).group("back").display is None


def test_confirm_and_reassign_orphan(env) -> None:
    adapter, view, c = env
    c.confirm_matches([3])
    assert adapter.read_data(None).lock(3).match == "ok"
    c.reassign_orphan(9, 4)
    data = adapter.read_data(None)
    assert data.orphans == []
    # the lock keeps its own (hair-mesh) name, so the next Detect still matches it by name
    old_name = env[0].read_data(None).lock(4).name
    assert (data.lock(4).overrides, data.lock(4).match) == ({"frizz": 0.3}, "ok")
    assert data.lock(4).name != "back_old" and data.lock(4).name == old_name
    assert len(adapter.writes) == 2
    assert view.selection == (ctl.SEL_LOCKS, (4,))
    assert ctl.ORPHANS_ROW not in [r["kind"] for r in view.tree]


def test_detect_report_is_shown(env) -> None:
    adapter, view, c = env
    adapter.report = DetectReport(
        matches=[Match(0, 1, "ok"), Match(1, 2, "ok"), Match(2, 3, "unsure"), Match(3, 10, "new")],
        orphaned=[9])
    c.detect()
    text, error = view.messages[-1]
    assert not error
    assert "4 locks" in text and "2 ok" in text and "1 unsure" in text and "1 new" in text and "1 orphaned" in text
    assert "regions out of date" in text
    assert view.stale is True
    c.split_regions()
    assert view.stale is False


def test_publish_refusal_message_is_shown(env) -> None:
    adapter, view, c = env
    adapter.publish_result = PublishResult(False, "", "v007", "v007 already exists; next free is v008")
    c.publish(" v007 ")
    assert adapter.published_version == "v007"
    text, error = view.messages[-1]
    assert error and "Not published" in text and "v008" in text
    c.publish("")
    assert adapter.published_version is None  # empty field: the adapter's default


def test_publish_version_prefilled_from_logic(env, monkeypatch) -> None:
    adapter, view, c = env
    adapter.publish_context = lambda node: ("char_Helen_grooming_v007", ["v007"])
    monkeypatch.setattr(ctl.logic, "publish_version", lambda scene, existing: ("v008", "v007 exists"))
    assert c.refresh_publish_version() == "v008"
    assert view.version == ("v008", "v007 exists")


def test_adapter_error_goes_to_the_message_line(env) -> None:
    adapter, view, c = env

    def broken(node):
        raise RuntimeError("hair mesh input is empty")

    adapter.detect = broken
    assert c.detect() is None
    assert view.messages[-1] == ("Detect failed: hair mesh input is empty", True)


def test_viewport_selection_and_outside_changes_are_polled(env) -> None:
    adapter, view, c = env
    adapter.viewport = [3, 4]
    c.poll()
    assert view.selection == (ctl.SEL_LOCKS, (3, 4))
    assert view.props["title"] == "2 locks"
    # Undo in Houdini changes the parm: the panel shows it on the next tick, without writing
    data = adapter.read_data(None)
    data.lock(1).name = "renamed"
    adapter.text = data.to_json()
    c.poll()
    assert view.tree[1]["children"][0]["name"] == "renamed"
    assert adapter.writes == []
    # The panel's own selection is not echoed back as a viewport change
    c.select_locks([1])
    adapter.viewport = [1]
    view.selection = None
    c.poll()
    assert view.selection is None


def test_display_mode_and_colour_by(env) -> None:
    adapter, view, c = env
    c.set_display("hair_preview", None)
    c.set_display(None, "group")
    assert adapter.display == [("hair_preview", "lock", 0.1), ("hair_preview", "group", 0.1)]
    assert view.display_state == ("hair_preview", "group")
    assert view.tree[1]["children"][0]["color"] == (0.9, 0.4, 0.4)  # coloured by its group now


def test_shelf_node_prefers_found_then_creates() -> None:
    adapter = FakeAdapter()
    assert ctl._shelf_node(adapter) is adapter.node
    created = FakeNode()
    adapter.find_nodes = lambda: []
    adapter.create_node = lambda parent=None: created
    assert ctl._shelf_node(adapter) is created


def test_several_locks_with_different_values_show_mixed(env) -> None:
    _adapter, view, c = env
    c.select_locks([1, 2])
    clump = _setting(view, "clump")
    assert clump["mixed"] and clump["source"] == "mixed"
    assert not _setting(view, "density")["mixed"]
    c.set_value("clump", 0.4)  # an edit sets all of them
    assert not _setting(view, "clump")["mixed"]


def test_measured_values_are_in_cm(env) -> None:
    _adapter, view, c = env
    c.unit_cm = 100.0  # scene in metres; FakeAdapter widths are 1.5 units
    c.select_locks([1])
    measured = dict(view.props["measured"])
    assert measured["Width"] == "150.0 cm" and measured["Length"] == "1000.0 cm"
    assert measured["Twist"].endswith("°")


def test_hidden_group_dims_its_locks_and_keeps_their_state(env) -> None:
    adapter, view, c = env
    c.set_visible(ctl.SEL_GROUP, ["fringe"], False)
    fringe = view.tree[1]
    assert fringe["visible"] is False
    assert all(ch["hidden_by_group"] and ch["visible"] for ch in fringe["children"])
    assert not any(ch["hidden_by_group"] for ch in view.tree[2]["children"])
    c.set_visible(ctl.SEL_GROUP, ["fringe"], True)
    assert adapter.read_data(None).lock(1).visible  # own state untouched


def test_isolate_selection_and_back(env) -> None:
    adapter, view, c = env
    c.toggle_isolate()  # nothing selected
    assert adapter.isolated is None and "select" in view.messages[-1][0]
    c.select_group("fringe")
    c.toggle_isolate()
    assert adapter.isolated == [1, 2]
    assert view.isolate.startswith("Isolated: Fringe")
    assert [ch["isolated_out"] for ch in view.tree[2]["children"]] == [True, True]
    assert adapter.writes == []  # a view state: no groom_data write, no undo step
    c.isolate_off()
    assert adapter.isolated is None and view.isolate == ""
    c.isolate_off()  # Esc when not isolated: nothing


def test_root_flip_and_exclude_reach_the_adapter_and_show_on_rows(env) -> None:
    adapter, view, c = env
    assert c.set_root_flip([1], True)
    assert c.set_excluded([1, 2], True)
    data = adapter.read_data(adapter.node)
    assert data.lock(1).root_flip and data.lock(1).excluded and data.lock(2).excluded
    rows = {ch["id"]: ch for g in view.tree if "children" in g for ch in g["children"]}
    assert rows[1]["root_flip"] and rows[1]["excluded"] and not rows[3]["excluded"]
    assert "Split regions" in view.messages[-1][0]
    assert not c.set_excluded([], True)          # nothing selected: nothing written


def test_slider_drag_follows_live_and_is_one_undo_step(env) -> None:
    adapter, view, c = env
    c.select_locks([1])
    before = adapter.read_data(adapter.node).resolve(1)["density"]
    writes = len(adapter.writes)
    assert c.preview_value("density", 200.0) and c.preview_value("density", 260.0)
    assert adapter.read_data(adapter.node).lock(1).overrides["density"] == 260.0   # the viewport follows
    assert adapter.light == [1]                                                    # light while dragging
    assert len(adapter.writes) == writes and adapter.live == 2                     # no undo step yet
    c.set_value("density", 300.0)                                                  # the release
    assert len(adapter.writes) == writes + 1 and adapter.live == 3                 # origin back, then one step
    assert adapter.read_data(adapter.node).lock(1).overrides["density"] == 300.0
    assert before != 300.0
    assert adapter.light is None                                                   # full again after


def test_shot_deform_toggle_turns_the_anim_off_for_fast_edits(env) -> None:
    adapter, view, c = env
    assert c.deform_state() == (True, True)
    assert c.set_shot_deform(False)
    assert adapter.deform == (True, False) and view.deform_state == (True, False)
    assert "edits are fast" in view.messages[-1][0]


def test_isolate_without_adapter_support_says_so(env) -> None:
    adapter, view, c = env
    del FakeAdapter.set_isolate
    try:
        c.select_locks([1])
        assert not c.toggle_isolate()
        assert view.messages[-1][1]
    finally:
        FakeAdapter.set_isolate = lambda self, node, ids: setattr(self, "isolated", sorted(ids) if ids else None)


def test_publish_warns_about_hidden_and_isolated_then_second_click_goes(env) -> None:
    adapter, view, c = env
    adapter.published_version = "untouched"
    c.set_visible(ctl.SEL_LOCKS, [3], False)
    c.set_visible(ctl.SEL_GROUP, ["fringe"], False)
    assert c.publish("v008") is None
    assert adapter.published_version == "untouched"
    assert "3 hidden locks" in view.publish_warning and "back_01" in view.publish_warning
    assert c.publish("v008") is not None  # second click with the same hidden locks
    assert adapter.published_version == "v008" and view.publish_warning == ""
    # A change in what is hidden asks again
    c.set_visible(ctl.SEL_LOCKS, [4], False)
    adapter.published_version = "untouched"
    c.publish("v009")
    assert adapter.published_version == "untouched"
    c.set_visible(ctl.SEL_LOCKS, [3, 4], True)  # the warning goes when what it named changes
    assert view.publish_warning == ""
    c.set_visible(ctl.SEL_GROUP, ["fringe"], True)
    c.select_locks([1])
    c.toggle_isolate()
    c.publish("v009")
    assert adapter.published_version == "untouched" and "isolated" in view.publish_warning


def test_nothing_hidden_publishes_at_once(env) -> None:
    adapter, view, c = env
    c.publish("v008")
    assert adapter.published_version == "v008" and view.publish_warning == ""


def test_drop_reorders_and_moves_locks_between_groups(env) -> None:
    adapter, view, c = env
    L, G = ctl.SEL_LOCKS, ctl.SEL_GROUP
    # reorder inside a group: fringe_02 above fringe_01
    assert c.drop([(L, 2)], (L, 1), ctl.DROP_ABOVE)
    data = adapter.read_data(None)
    assert [lk.id for lk in data.locks if lk.group == "fringe"] == [2, 1]
    assert not data.regions_stale and "Reordered" in view.messages[-1][0]
    # two locks into Back, which sets clump 0.5: fringe_01 takes it, fringe_02 keeps its own 0.8
    c.select_group("back")
    c.set_value("clump", 0.5)
    c.select_locks([1, 2])
    writes = len(adapter.writes)
    assert c.drop([(L, 1), (L, 2)], (G, "back"), ctl.DROP_ON)
    assert len(adapter.writes) == writes + 1  # one undo step
    data = adapter.read_data(None)
    assert [lk.id for lk in data.locks if lk.group == "back"] == [3, 4, 2, 1]
    assert data.resolve(2)["clump"] == 0.8 and data.resolve(1)["clump"] == 0.5
    assert data.regions_stale
    text = view.messages[-1][0]
    assert "Moved 2 locks to Back" in text and "Clump" in text and "regions out of date" in text
    assert view.selection == (L, (1, 2))
    # just below a group row: first in it
    assert c.drop([(L, 4)], (G, "fringe"), ctl.DROP_BELOW)
    assert adapter.read_data(None).lock(4).group == "fringe"


def test_drop_moves_groups_and_refuses_what_makes_no_sense(env) -> None:
    adapter, view, c = env
    L, G, D = ctl.SEL_LOCKS, ctl.SEL_GROUP, ctl.SEL_DEFAULTS
    assert c.drop([(G, "back")], (G, "fringe"), ctl.DROP_ABOVE)
    assert [g.id for g in adapter.read_data(None).groups] == ["back", "fringe"]
    writes = len(adapter.writes)
    refused = {
        "defaults": c.plan_drop([(L, 1)], (D, ""), ctl.DROP_ON),
        "itself": c.plan_drop([(L, 1)], (L, 1), ctl.DROP_ON),
        "group into group": c.plan_drop([(G, "back")], (G, "fringe"), ctl.DROP_ON),
        "group onto a lock": c.plan_drop([(G, "back")], (L, 1), ctl.DROP_BELOW),
        "group onto itself": c.plan_drop([(G, "back")], (G, "back"), ctl.DROP_BELOW),
        "mixed drag": c.plan_drop([(G, "back"), (L, 1)], (G, "fringe"), ctl.DROP_ON),
        "orphan": c.plan_drop([(ctl.SEL_ORPHAN, 9)], (G, "fringe"), ctl.DROP_ON),
        "into orphans": c.plan_drop([(L, 1)], (ctl.ORPHANS_ROW, ctl.ORPHANS_ROW), ctl.DROP_ON),
        "above defaults": c.plan_drop([(G, "back")], (D, ""), ctl.DROP_ABOVE),
    }
    assert all(isinstance(r, str) for r in refused.values()), refused
    assert not c.drop([(L, 1)], (D, ""), ctl.DROP_ON)
    assert "Not moved" in view.messages[-1][0]
    assert len(adapter.writes) == writes  # never half applied


# ---------------------------------------------------------------------------
# The Qt panel, offscreen
# ---------------------------------------------------------------------------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def prefs(tmp_path, monkeypatch):
    from tools.fx.grooming import ui as ui_mod
    monkeypatch.setattr(ui_mod, "PREFS_PATH", str(tmp_path / "grooming_prefs.json"))
    return ui_mod


def test_panel_smoke(app, prefs) -> None:
    from tools.fx.grooming.ui import GroomingUI

    adapter = FakeAdapter()
    ui = GroomingUI()
    c = ctl.GroomController(adapter, ui)
    ctl.bind(ui, c)
    c.set_node(adapter.node)
    ui.show()
    app.processEvents()
    assert ui._tree.topLevelItemCount() == 4
    # Selecting a lock row in the tree selects it in the viewport and shows its settings
    ui._rows[(ctl.SEL_LOCKS, 2)].setSelected(True)
    assert adapter.selected[-1] == [2]
    assert ui._props["title"] == "fringe_02"
    # A slider change is one write
    from tools.fx.grooming.ui import _SettingRow

    rows = ui._props_widget.findChildren(_SettingRow)
    assert [r.key for r in rows] == list(ctl.SETTING_RANGES)
    rows[0].slider.setValue(rows[0].slider.value() + 100)
    assert len(adapter.writes) == 1
    assert "density" in adapter.read_data(None).lock(2).overrides
    adapter.publish_result = PublishResult(False, "", "v007", "v007 already exists")
    ui._version_edit.setText("v007")
    ui._publish_btn.click()
    assert "already exists" in ui.message()
    ui.set_regions_stale(True)
    assert not ui._stale.isHidden()
    ui.close()


def _panel(app):
    from tools.fx.grooming.ui import GroomingUI

    adapter = FakeAdapter()
    ui = GroomingUI()
    c = ctl.GroomController(adapter, ui)
    ctl.bind(ui, c)
    c.set_node(adapter.node)
    ui.show()
    app.processEvents()
    return adapter, ui, c


def test_wheel_over_a_slider_scrolls_the_panel_not_the_value(app, prefs) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from tools.fx.grooming.ui import _SettingRow

    adapter, ui, c = _panel(app)
    c.select_locks([1])
    app.processEvents()
    row = ui._props_widget.findChildren(_SettingRow)[0]
    before = row.slider.value()
    event = QWheelEvent(QPointF(5, 5), QPointF(row.slider.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(row.slider, event)
    assert row.slider.value() == before and adapter.writes == []
    assert not event.isAccepted()  # handed up to the scroll area
    combo_event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                              Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    index = ui._display_combo.currentIndex()
    QApplication.sendEvent(ui._display_combo, combo_event)
    assert ui._display_combo.currentIndex() == index
    ui.close()


def test_rows_show_mixed_reset_only_when_set_here_and_drag_is_one_write(app, prefs) -> None:
    from tools.fx.grooming.ui import _SettingRow

    adapter, ui, c = _panel(app)
    c.select_locks([1, 2])
    app.processEvents()
    rows = {r.key: r for r in ui._props_widget.findChildren(_SettingRow)}
    assert rows["clump"].field.text() == "" and rows["clump"].field.placeholderText() == "mixed"
    assert rows["density"].field.text() == "150"
    assert rows["density"].reset.isHidden()  # inherited: no reset
    c.select_locks([2])
    app.processEvents()
    rows = {r.key: r for r in ui._props_widget.findChildren(_SettingRow)}
    assert not rows["clump"].reset.isHidden() and rows["clump"].source.text() == ""
    assert rows["density"].source.text() == "built-in"
    # A drag: many value changes while the handle is down, one write on release
    slider = rows["frizz"].slider
    slider.setSliderDown(True)
    for v in (100, 200, 300, 400):
        slider.setValue(v)
    assert adapter.writes == []
    slider.setSliderDown(False)
    slider.sliderReleased.emit()
    assert len(adapter.writes) == 1
    ui.close()


def test_eye_shape_says_drawn_tone_says_why(app, prefs) -> None:
    """Open eye = drawn, crossed = not drawn; the tooltip says the row's own eye and who decided."""
    adapter, ui, c = _panel(app)
    eye = lambda lid: ui._rows[(ctl.SEL_LOCKS, lid)].toolTip(2)  # noqa: E731
    assert eye(1).startswith("Shown")
    c.set_visible(ctl.SEL_LOCKS, [3], False)
    app.processEvents()
    assert eye(3).startswith("Hidden: click")
    c.set_visible(ctl.SEL_GROUP, ["fringe"], False)
    app.processEvents()
    assert eye(1) == "Hidden by its group (its own eye: shown). Click to change its own eye"
    c.set_visible(ctl.SEL_GROUP, ["fringe"], True)
    c.select_locks([3])
    c.toggle_isolate()                     # isolate a lock whose own eye is off: it is drawn
    app.processEvents()
    assert eye(3).startswith("Drawn: isolated (its own eye: hidden)")
    assert eye(1).startswith("Not drawn while isolating (its own eye: shown)")
    assert ui._isolate_btn.isChecked()
    ui.close()


def test_hidden_group_dims_its_rows_and_publish_warns_in_the_panel(app, prefs) -> None:
    from tools.fx.grooming.ui import DIM, ROLE_ROW, COL_NAME

    adapter, ui, c = _panel(app)
    c.set_visible(ctl.SEL_GROUP, ["fringe"], False)
    app.processEvents()
    lock = ui._rows[(ctl.SEL_LOCKS, 1)]
    assert lock.data(COL_NAME, ROLE_ROW)["dimmed"]
    assert lock.foreground(COL_NAME).color().name() == DIM
    assert "group" in lock.toolTip(2)  # the eye column
    assert not ui._rows[(ctl.SEL_LOCKS, 3)].data(COL_NAME, ROLE_ROW)["dimmed"]
    ui._publish_btn.click()
    assert "2 hidden locks" in ui.publish_warning() and "anyway" in ui._publish_btn.text()
    assert not hasattr(adapter, "published_version")
    ui._publish_btn.click()
    assert adapter.published_version == "v008" or adapter.published_version is None
    assert ui.publish_warning() == ""
    ui.close()


def test_isolate_shortcut_and_banner(app, prefs) -> None:
    adapter, ui, c = _panel(app)
    c.select_group("back")
    ui._isolate_btn.click()
    app.processEvents()
    assert adapter.isolated == [3, 4]
    assert not ui._banner.isHidden() and "Back" in ui._banner_label.text()
    assert ui._isolate_btn.isChecked()
    ui._fire("isolate_off")
    assert adapter.isolated is None and ui._banner.isHidden()
    ui.close()


def test_ui_size_scales_fonts_and_is_saved(app, prefs) -> None:
    adapter, ui, c = _panel(app)
    normal = ui.z.px(15)
    ui.set_ui_size("Larger")
    assert ui.z.px(15) == round(15 * 1.3) > normal
    assert prefs.load_prefs()["ui_size"] == "Larger"
    assert f"font-size: {ui.z.px(15)}px" in ui.styleSheet()
    ui.close()
    from tools.fx.grooming.ui import GroomingUI
    again = GroomingUI()
    assert again._ui_size == "Larger"
    again.close()


def test_tree_drop_places_map_to_the_controller(app, prefs) -> None:
    from PySide6.QtCore import QPoint

    adapter, ui, c = _panel(app)
    tree = ui._tree
    ui.set_selection((ctl.SEL_LOCKS, (1, 2)))
    rect = tree.visualItemRect(ui._rows[(ctl.SEL_GROUP, "back")])
    target, where, _r = tree._place(QPoint(rect.left() + 20, rect.center().y()))
    assert target == (ctl.SEL_GROUP, "back") and where == ctl.DROP_ON
    assert isinstance(ui._ask("can_drop", tree._dragged(), target, where), dict)
    rect = tree.visualItemRect(ui._rows[(ctl.SEL_LOCKS, 3)])
    target, where, _r = tree._place(QPoint(20, rect.top() + 2))
    assert (target, where) == ((ctl.SEL_LOCKS, 3), ctl.DROP_ABOVE)
    ui._fire("drop", tree._dragged(), target, where)
    assert [lk.id for lk in adapter.read_data(None).locks if lk.group == "back"] == [1, 2, 3, 4]
    ui.close()
