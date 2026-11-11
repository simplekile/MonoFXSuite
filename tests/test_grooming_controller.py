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

    def set_drag_preview(self, node, ids, factor=1.0) -> None:
        self.light = sorted(ids) if ids else None
        self.drag_factor = factor

    # Houdini's undo, from the panel's Ctrl+Z
    undo_labels: list = []

    def undo(self, node, redo=False) -> str:
        if not self.undo_labels:
            return ""
        self.undone = ("redo" if redo else "undo", self.undo_labels[0])
        return self.undo_labels.pop(0)

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

    # locks drawn as strands: a view state like isolate
    strands = None

    def set_strands(self, node, ids) -> None:
        self.strands = sorted(ids) if ids else None

    def strand_ids(self, node):
        return self.strands or []

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

    strands = ""

    def set_strands(self, text):
        self.strands = text

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


def test_selecting_never_draws_strands_enter_does_and_again_packs(env) -> None:
    adapter, view, c = env
    adapter.deform = (True, False)
    c.select_group("fringe")
    assert adapter.strands is None                      # a selection alone: still packed
    selected = len(adapter.selected)
    assert c.toggle_strands()
    assert adapter.strands == [1, 2] and view.strands == "Strands: fringe_01, fringe_02"
    assert len(adapter.selected) > selected             # the prim numbers changed: selected again
    assert adapter.writes == []                         # a view state: no groom_data write, no undo step
    assert c.toggle_strands()                           # the same locks again: packed again
    assert adapter.strands is None and view.strands == ""
    c.toggle_strands()
    c.select_locks([3])
    assert c.toggle_strands()                           # other locks: added, the first ones stay
    assert adapter.strands == [1, 2, 3]
    assert c.set_strands_of(ctl.SEL_LOCKS, [1], False)  # a row's icon: that lock packed again
    assert adapter.strands == [2, 3]
    rows = {r["id"]: r for g in c.tree_rows(c.data()) for r in [g] + g.get("children", [])}
    assert rows[2]["strands"] and not rows[1]["strands"]
    assert not rows["fringe"]["strands"]                # a group: only when all its locks are
    assert c.set_strands_of(ctl.SEL_GROUP, ["fringe"], True)
    assert adapter.strands == [1, 2, 3]
    assert c.set_strands_of(ctl.SEL_GROUP, ["fringe"], False)
    assert adapter.strands == [3]
    assert c.set_strands_of(ctl.SEL_LOCKS, [3], False) and adapter.strands is None


def test_a_change_and_its_cook_show_the_loading_line(env) -> None:
    adapter, view, c = env
    seen = []
    view.set_busy = lambda what: seen.append(what)
    adapter.cook_display = lambda node: seen.append("cook")
    c.select_locks([1])
    c.set_value("clump", 0.4)
    assert seen[-3:] == ["Clump on fringe_01", "cook", None]         # cooked inside, the line cleared after
    c.toggle_isolate()
    assert seen[seen.index("Isolate") + 1] == "cook" and seen[-1] is None


def test_strands_refuse_too_many_locks_and_anim_on(env) -> None:
    adapter, view, c = env
    c.select_locks([1])
    adapter.deform = (True, True)
    assert not c.toggle_strands()
    assert adapter.strands is None and "already shows its strands" in view.messages[-1][0]
    adapter.deform = (True, False)
    old = ctl.config.STRANDS_MAX
    ctl.config.STRANDS_MAX = 1
    try:
        c.select_locks([1, 2])
        assert not c.toggle_strands()
        assert adapter.strands is None and "at most 1" in view.messages[-1][0]
    finally:
        ctl.config.STRANDS_MAX = old
    c.select("none")
    assert not c.toggle_strands() and "select a lock" in view.messages[-1][0]


def test_isolate_selects_the_same_locks_again(env) -> None:
    """Isolating changes the output's prim numbers: the viewport selection follows the locks."""
    adapter, view, c = env
    c.select_locks([3])
    before = len(adapter.selected)
    c.toggle_isolate()
    assert len(adapter.selected) == before + 1 and adapter.selected[-1] == [3]
    c.isolate_off()
    assert len(adapter.selected) == before + 2 and adapter.selected[-1] == [3]


def test_poll_outside_houdini_runs_at_once() -> None:
    calls = []
    assert ctl._when_idle(lambda: calls.append(1))() is None and calls == [1]


def test_escape_leaves_isolate_and_strands(env) -> None:
    adapter, view, c = env
    adapter.deform = (True, False)
    c.select_locks([1, 2])
    c.toggle_isolate()
    c.toggle_strands()
    assert adapter.isolated == [1, 2] and adapter.strands == [1, 2]
    assert c.escape()
    assert adapter.isolated is None and adapter.strands is None
    assert not c.escape()                               # nothing left to leave


def test_an_edit_with_strands_on_selects_the_locks_again(env) -> None:
    """An edit changes the strand count of a lock drawn as strands: the viewport's prim numbers are
    stale, so the panel's locks are selected again by lock id."""
    adapter, view, c = env
    adapter.deform = (True, False)
    c.select_locks([1])
    c.toggle_strands()
    before = len(adapter.selected)
    c.set_value("density", 250.0)
    assert len(adapter.selected) > before and adapter.selected[-1] == [1]
    adapter.strands = None                              # cleared outside (scene loaded again)
    c.poll()
    assert c.strands is None and view.strands == ""


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
    adapter.deform = (True, False)             # Anim off: the drag is live
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


def test_slider_drag_with_anim_on_applies_on_release_and_poll_keeps_the_slider(env) -> None:
    adapter, view, c = env
    adapter.deform = (True, True)              # Anim on: a tick would deform the whole groom
    c.select_locks([1])
    assert not c.preview_value("density", 200.0)
    assert "applies when you let go" in view.messages[-1][0]
    adapter.deform = (True, False)
    c.preview_value("density", 210.0)          # a drag in progress...
    rebuilt = len(view.messages)
    tree_before = view.tree
    c.poll()                                   # ...the poll must not rebuild the panel under the mouse
    assert view.tree is tree_before
    c.set_value("density", 220.0)
    assert adapter.read_data(adapter.node).lock(1).overrides["density"] == 220.0


def test_shot_deform_toggle_turns_the_anim_off_for_fast_edits(env) -> None:
    adapter, view, c = env
    assert c.deform_state() == (True, True)
    assert c.set_shot_deform(False)
    assert adapter.deform == (True, False) and view.deform_state == (True, False)
    assert "edits are fast" in view.messages[-1][0]


def test_isolate_another_lock_while_isolated_switches_to_it(env) -> None:
    adapter, view, c = env
    c.select_locks([1, 2])
    c.toggle_isolate()
    assert adapter.isolated == [1, 2]
    c.select_locks([3])
    assert c.toggle_isolate()                     # no need to show everything first
    assert adapter.isolated == [3] and view.isolate.startswith("Isolated: back_01")
    assert c.toggle_isolate()                     # the same lock again: everything shown
    assert adapter.isolated is None


def test_focus_replaces_the_viewport_highlight(env, monkeypatch) -> None:
    """With focus the panel's selection keeps its colour in the viewport and the other locks go
    see-through; Houdini's selection highlight (which painted the lock over) is never set, and a pick
    in the viewport becomes the panel's selection and the focus."""
    adapter, view, c = env
    calls = []

    def set_focus(node, ids):
        calls.append(sorted(ids) if ids else None)
        adapter.viewport = []                      # the real one clears Houdini's highlight

    monkeypatch.setattr(adapter, "set_focus", set_focus, raising=False)
    c.select_locks([2])
    assert calls[-1] == [2] and adapter.selected == []
    c.select_group("back")
    assert calls[-1] == [3, 4]
    c.select("none")
    assert calls[-1] is None                       # nothing selected: every lock in its colour
    adapter.viewport = [1]                         # a pick in the viewport
    c.poll()
    assert c.selection == ("locks", (1,)) and calls[-1] == [1] and adapter.viewport == []
    c.poll()                                       # the cleared highlight is no new pick
    assert c.selection == ("locks", (1,))
    c.focus_off()
    assert calls[-1] is None


def test_focus_only_on_drawn_locks(env, monkeypatch) -> None:
    """A selected lock the viewport does not draw (its eye off, outside the isolate) takes no focus:
    focusing it would leave every drawn lock see-through and nothing solid on screen."""
    adapter, view, c = env
    calls = []
    monkeypatch.setattr(adapter, "set_focus", lambda node, ids: calls.append(sorted(ids) if ids else None),
                        raising=False)
    c.select_locks([1])
    c.toggle_isolate()
    c.select_locks([3])                            # outside the isolate
    assert calls[-1] is None and "outside the isolate" in view.messages[-1][0]
    c.toggle_isolate()                             # I on it: isolated, and in focus
    assert adapter.isolated == [3] and calls[-1] == [3]
    c.toggle_isolate()
    c.select_locks([2, 3])
    c.set_visible(ctl.SEL_LOCKS, [3], False)       # its eye off: focus keeps only what is drawn
    assert calls[-1] == [2]
    c.set_visible(ctl.SEL_LOCKS, [3], True)
    assert calls[-1] == [2, 3]
    c.set_visible(ctl.SEL_LOCKS, [2, 3], False)
    assert calls[-1] is None


def test_undo_from_the_panel_runs_houdinis_undo_and_shows_it(env) -> None:
    adapter, view, c = env
    adapter.undo_labels = ["Grooming: Density on fringe_01"]
    assert c.undo()
    assert adapter.undone == ("undo", "Grooming: Density on fringe_01")
    assert view.messages[-1][0] == "Undone: Grooming: Density on fringe_01"
    assert not c.undo(redo=True) and view.messages[-1][0] == "Nothing to redo"


def test_a_drag_shows_the_real_strand_count_up_to_the_budget(env, monkeypatch) -> None:
    adapter, view, c = env
    adapter.deform = (True, False)
    c.select_locks([1])                            # 1000 strands (FakeAdapter.lock_infos)
    c.preview_value("clump", 0.5)
    assert adapter.light == [1] and adapter.drag_factor == 1.0
    c.set_value("clump", 0.5)
    monkeypatch.setattr(ctl.config, "DRAG_STRAND_BUDGET", 1500)
    monkeypatch.setattr(ctl.logic.config, "DRAG_STRAND_BUDGET", 1500)
    c.select_group("back")                         # 2 x 1000 strands, over the budget
    c.preview_value("clump", 0.6)
    assert adapter.drag_factor < 1.0 and "showing 1 in" in view.messages[-1][0]
    c.set_value("clump", 0.6)
    c.select_locks([1])
    c.preview_value("density", 300.0)              # density 150 -> 300 doubles its strands: 2000
    assert adapter.drag_factor < 1.0


def test_drag_factor_snaps_to_steps() -> None:
    from tools.fx.grooming import logic
    assert logic.drag_factor(5000, 10000) == 1.0
    f = logic.drag_factor(30000, 10000)
    assert f <= 1 / 3 and abs(f - 0.8 ** 5) < 1e-9
    assert logic.drag_factor(30500, 10000) == f    # a nearby count reuses the same factor (cache key)


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


def test_slider_drag_survives_a_window_popping_up_and_taking_the_mouse(app, prefs) -> None:
    """Houdini's cook-interrupt button pops up mid-drag and takes Qt's mouse grab: the slider keeps
    following the cursor and writes once when the button really comes up."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget

    from tools.fx.grooming.ui import _SettingRow

    adapter, ui, c = _panel(app)
    c.select_locks([1])
    app.processEvents()
    row = {r.key: r for r in ui._props_widget.findChildren(_SettingRow)}["density"]
    slider = row.slider
    slider.resize(400, slider.height())
    down = {"v": True}
    slider.button_down = lambda: down["v"]
    groove, handle = slider._rects()
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, handle.center())
    assert slider.isSliderDown()
    popup = QWidget(None, Qt.WindowType.Popup)  # takes the grab; the slider hears nothing more
    popup.show()
    app.processEvents()
    slider.cursor_x = lambda: groove.right()
    slider._poll()
    assert slider.isSliderDown() and slider.value() == slider.maximum()
    assert adapter.writes == []
    down["v"] = False
    slider._poll()
    popup.close()
    assert not slider.isSliderDown()
    assert len(adapter.writes) == 1
    assert adapter.read_data(None).lock(1).overrides["density"] == row._hi
    ui.close()


def test_rebuilding_the_settings_shows_no_window_of_its_own(app, prefs) -> None:
    """Reset was shown before it had a parent: a little window flashed up on every edit and took the
    mouse from the slider being dragged."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QWidget

    adapter, ui, c = _panel(app)
    shown = []

    class Spy(QObject):
        def eventFilter(self, obj, event):  # noqa: N802
            if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow() and obj is not ui:
                shown.append(type(obj).__name__)
            return False

    spy = Spy()
    app.installEventFilter(spy)
    try:
        c.select_locks([2])  # a lock with its own values: rows with Reset
        c.set_value("density", 180.0)
        app.processEvents()
    finally:
        app.removeEventFilter(spy)
    assert shown == []
    ui.close()


def test_eye_click_on_a_selected_row_hides_the_whole_selection(app, prefs) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from tools.fx.grooming.ui import COL_EYE

    adapter, ui, c = _panel(app)
    ui.show()
    c.select_locks([1, 2])
    ui.set_selection(c.selection)
    app.processEvents()
    tree = ui._tree
    item = ui._rows[(ctl.SEL_LOCKS, 1)]
    tree.scrollToItem(item)
    app.processEvents()
    rect = tree.visualItemRect(item)
    x = tree.header().sectionViewportPosition(COL_EYE) + tree.header().sectionSize(COL_EYE) // 2
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     rect.center().__class__(x, rect.center().y()))
    app.processEvents()
    data = adapter.read_data(adapter.node)
    assert not data.lock(1).visible and not data.lock(2).visible   # both, not just the clicked one
    assert data.lock(3).visible
    ui.close()


def test_eye_shape_says_drawn_tone_says_why(app, prefs) -> None:
    """Open eye = drawn, crossed = not drawn; the tooltip says the row's own eye and who decided."""
    adapter, ui, c = _panel(app)
    eye = lambda lid: ui._rows[(ctl.SEL_LOCKS, lid)].toolTip(3)  # noqa: E731
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
    assert "group" in lock.toolTip(3)  # the eye column
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


def test_enter_and_double_click_draw_strands_double_click_on_the_eye_is_two_clicks(app, prefs) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from tools.fx.grooming.ui import COL_EYE

    adapter, ui, c = _panel(app)
    adapter.deform = (True, False)
    ui.show()
    c.select_locks([3])
    ui.set_selection(c.selection)
    app.processEvents()
    tree = ui._tree
    tree.setFocus()
    QTest.keyClick(tree, Qt.Key.Key_Return)
    assert adapter.strands == [3]
    assert not ui._banner.isHidden() and "back_01" in ui._banner_label.text()
    assert "Packed" in ui._banner_btn.text()
    QTest.keyClick(ui, Qt.Key.Key_Escape)
    app.processEvents()
    assert adapter.strands is None and ui._banner.isHidden()
    group = ui._rows[(ctl.SEL_GROUP, "back")]
    expanded = group.isExpanded()
    rect = tree.visualItemRect(group)
    at = QPoint(tree.header().sectionViewportPosition(0) + 60, rect.center().y())
    # a real double-click is press, release, double-click, release; QTest's sends the double-click only
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    app.processEvents()
    # the tree is shown again (new items): no collapse on double-click
    assert adapter.strands == [3, 4] and ui._rows[(ctl.SEL_GROUP, "back")].isExpanded() == expanded
    item = ui._rows[(ctl.SEL_LOCKS, 1)]
    rect = tree.visualItemRect(item)
    x = tree.header().sectionViewportPosition(COL_EYE) + tree.header().sectionSize(COL_EYE) // 2
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(x, rect.center().y()))
    QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      QPoint(x, rect.center().y()))
    app.processEvents()
    assert adapter.read_data(adapter.node).lock(1).visible               # hidden, then shown again
    assert adapter.strands == [3, 4]                                     # the eye draws no strands
    ui.close()


def test_ctrl_z_in_the_panel_and_the_packed_strands_icon(app, prefs) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from tools.fx.grooming.ui import COL_STRANDS

    adapter, ui, c = _panel(app)
    adapter.undo_labels = ["Grooming: Clump on back_01"]
    ui._tree.setFocus()
    QTest.keyClick(ui._tree, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert adapter.undone == ("undo", "Grooming: Clump on back_01")
    adapter.deform = (True, False)
    ui.show()
    tree = ui._tree

    def click_icon(key):
        rect = tree.visualItemRect(ui._rows[key])
        h = tree.header()
        x = h.sectionViewportPosition(COL_STRANDS) + h.sectionSize(COL_STRANDS) // 2
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(x, rect.center().y()))
        app.processEvents()

    assert "Packed" in ui._rows[(ctl.SEL_LOCKS, 1)].toolTip(COL_STRANDS)
    click_icon((ctl.SEL_LOCKS, 1))
    assert adapter.strands == [1] and "strands" in ui._rows[(ctl.SEL_LOCKS, 1)].toolTip(COL_STRANDS)
    click_icon((ctl.SEL_GROUP, "back"))                  # a group's icon: all its locks
    assert adapter.strands == [1, 3, 4]
    click_icon((ctl.SEL_LOCKS, 1))
    assert adapter.strands == [3, 4]
    ui.set_busy("Clump")                                  # the loading line waits a moment
    assert not ui.is_busy()
    QTest.qWait(ui.BUSY_DELAY_MS + 100)
    assert ui.is_busy() and "Clump" in ui._busy_label.text()
    ui.set_busy(None)
    assert not ui.is_busy()
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
