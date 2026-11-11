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


# ---------------------------------------------------------------------------
# The Qt panel, offscreen
# ---------------------------------------------------------------------------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_panel_smoke(app) -> None:
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
