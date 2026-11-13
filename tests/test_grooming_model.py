"""MONO Grooming data model: settings resolution and the JSON format."""

from __future__ import annotations

import json

import pytest

from tools.fx.grooming.model import (
    BUILTIN_DEFAULTS, SCHEMA, GroomData, Group, Lock, Orphan,
)


def _data() -> GroomData:
    return GroomData(
        asset="char_Helen",
        defaults={"density": 160.0},
        groups=[Group(id="mai", name="Mái", overrides={"clump": 0.6})],
        locks=[
            Lock(id=1, name="fringe_01", group="mai", overrides={"width_mult": 1.2}),
            Lock(id=2, name="fringe_02", group="mai"),
            Lock(id=3, name="lost_group", group="gone"),
        ],
        orphans=[Orphan(id=9, name="back_04", group="gay", overrides={"density": 90.0})],
    )


def test_resolve_follows_builtin_defaults_group_lock():
    d = _data()
    s = d.resolve(1)
    assert s["density"] == 160.0          # data defaults
    assert s["clump"] == 0.6              # group
    assert s["width_mult"] == 1.2         # lock
    assert s["frizz"] == BUILTIN_DEFAULTS["frizz"]


def test_resolve_missing_group_falls_back_to_defaults():
    assert _data().resolve(3)["clump"] == BUILTIN_DEFAULTS["clump"]


def test_source_of_names_the_level():
    d = _data()
    assert d.source_of(1, "width_mult") == "lock"
    assert d.source_of(2, "clump") == "group"
    assert d.source_of(2, "density") == "defaults"
    assert d.source_of(2, "frizz") == "builtin"


def test_next_lock_id_skips_orphans():
    assert _data().next_lock_id() == 10


def test_json_round_trip():
    d = _data()
    back = GroomData.from_json(d.to_json())
    assert back == d
    assert json.loads(d.to_json())["schema"] == SCHEMA


def test_empty_text_gives_empty_data():
    assert GroomData.from_json("") == GroomData()
    assert GroomData.from_json(None) == GroomData()


def test_unknown_and_non_numeric_overrides_are_dropped():
    text = json.dumps({"schema": 1, "locks": [{"id": 1, "name": "a", "group": "g",
                                                "overrides": {"density": 100, "wind": 3, "clump": "x", "frizz": True}}]})
    assert GroomData.from_json(text).locks[0].overrides == {"density": 100.0}


def test_newer_schema_is_refused():
    with pytest.raises(ValueError):
        GroomData.from_json(json.dumps({"schema": SCHEMA + 1}))


def test_resolve_unknown_lock_raises():
    with pytest.raises(KeyError):
        _data().resolve(42)


def test_deleted_orphan_id_is_never_given_again():
    d = GroomData(locks=[Lock(id=1, name="a", group="g")], orphans=[Orphan(id=7, name="b", group="g")])
    d.note_ids()
    d.orphans = []                      # the panel deleted the orphan
    assert d.next_lock_id() == 8        # 7 may still be named by frozen regions or old publishes
    assert GroomData.from_json(d.to_json()).next_lock_id() == 8


def test_root_flip_excluded_round_trip_and_old_json_defaults():
    data = GroomData(groups=[Group(id="g", name="G", visible=False)],
                     locks=[Lock(id=1, name="a", group="g", root_flip=True, excluded=True)],
                     orphans=[Orphan(id=2, name="b", group="g", root_flip=True)])
    back = GroomData.from_json(data.to_json())
    assert back.lock(1).root_flip and back.lock(1).excluded and back.orphans[0].root_flip
    old = GroomData.from_json('{"schema": 1, "locks": [{"id": 1, "name": "a", "group": "g"}]}')
    assert old.lock(1).root_flip is False and old.lock(1).excluded is False


def test_shown_follows_lock_and_group_eyes():
    data = GroomData(groups=[Group(id="g", name="G"), Group(id="h", name="H", visible=False)],
                     locks=[Lock(id=1, name="a", group="g"), Lock(id=2, name="b", group="g", visible=False),
                            Lock(id=3, name="c", group="h"), Lock(id=4, name="d", group="none")])
    assert [data.shown(i) for i in (1, 2, 3, 4, 99)] == [True, False, False, True, False]


def test_tree_order_moves_locks_and_groups_and_survives_json() -> None:
    from tools.fx.grooming.model import GroomData, Group, Lock

    data = GroomData(groups=[Group("a", "A"), Group("b", "B")],
                     locks=[Lock(1, "a1", "a"), Lock(2, "a2", "a"), Lock(3, "b1", "b"), Lock(4, "b2", "b")])
    data.move_locks([4, 1], "a", before=2)  # keeps their own order: 1 before 4
    assert [(lk.id, lk.group) for lk in data.locks] == [(1, "a"), (4, "a"), (2, "a"), (3, "b")]
    data.move_locks([2], "b")  # no before: the end of the group
    assert [lk.id for lk in data.locks if lk.group == "b"] == [3, 2]
    data.move_group("b", before="a")
    assert [g.id for g in data.groups] == ["b", "a"]
    again = GroomData.from_json(data.to_json())
    assert [lk.id for lk in again.locks] == [lk.id for lk in data.locks]
    assert [g.id for g in again.groups] == ["b", "a"]


# ---- v0.2a density layers ----

def test_v01_data_migrates_to_masks_without_changing_anything_else():
    from tools.fx.grooming.model import MaskLayer, migrate
    old = {"schema": 1, "asset": "char_Helen", "defaults": {"density": 120.0},
           "groups": [{"id": "g", "name": "g"}],
           "locks": [{"id": 1, "name": "g_01", "group": "g", "overrides": {"clump": 0.4}}], "id_high": 1}
    d = GroomData.from_json(json.dumps(old))
    assert d.asset == "char_Helen" and d.defaults == {"density": 120.0}
    assert d.lock(1).overrides == {"clump": 0.4} and d.id_high == 1
    assert d.masks == [] and d.mask_id_high == -1 and d.schema == SCHEMA == 4
    new = migrate(dict(old))
    assert new["schema"] == 4 and "masks" not in old and new["masks_dropped"] == []     # the input is not changed
    with pytest.raises(ValueError, match="newer than this tool"):
        migrate({"schema": SCHEMA + 1})
    assert MaskLayer(0, "x").applies(1, "g")
    assert MaskLayer(0, "x").value == 150.0 and MaskLayer(0, "x").kind == "fill"
    assert not hasattr(MaskLayer(0, "x"), "mode") and not hasattr(MaskLayer(0, "x"), "unit")


def test_mask_layers_roundtrip_order_and_ids():
    d = GroomData()
    a = d.add_mask()
    b = d.add_mask("Crown", value=5104, opacity=0.5)
    c = d.add_mask("Fringe", scope="group", group="bang")
    e = d.add_mask("Two", scope="locks", locks=[9, 3, 9])
    assert [m.id for m in d.masks] == [0, 1, 2, 3] and a.name == "Layer 1" and e.locks == [3, 9]
    assert b.value == 5104.0 and b.opacity == 0.5
    d.move_mask(c.id, 0)
    d.move_mask(a.id, 99)
    assert [m.name for m in d.masks] == ["Fringe", "Crown", "Two", "Layer 1"]
    assert d.remove_mask(b.id) and not d.remove_mask(b.id)
    back = GroomData.from_json(d.to_json())
    assert back.masks == d.masks and back.mask_id_high == 3
    assert '"mode"' not in d.to_json() and '"unit"' not in d.to_json()
    assert back.add_mask().id == 4
    assert back.mask(2).applies(7, "bang") and not back.mask(2).applies(7, "back")
    assert back.mask(3).applies(3, "back") and not back.mask(3).applies(4, "back")
    with pytest.raises(KeyError):
        d.move_mask(77, 0)


def test_mask_layers_from_json_are_cleaned():
    d = GroomData.from_json(json.dumps({"schema": 4, "masks": [
        {"id": 5, "name": "x", "opacity": 7, "scope": "nope", "locks": [3, 3, 1], "value": -4, "kind": "paint",
         "parent": 99}]}))
    m = d.masks[0]
    assert (m.opacity, m.scope, m.locks, m.value, m.kind, m.parent) == (1.0, "all", [1, 3], 0.0, "fill", None)
    assert d.mask_id_high == 5
    big = GroomData.from_json(json.dumps({"schema": 4, "masks": [{"id": 0, "value": 1e9}, {"id": 1, "value": "x"}]}))
    assert big.masks[0].value == 20000.0 and big.masks[1].value == 150.0


def test_schema_3_layers_of_a_removed_kind_are_dropped_and_named():
    from tools.fx.grooming.model import dropped_masks, dropped_text
    old = {"schema": 3, "mask_id_high": 6, "masks": [
        {"id": 0, "name": "Half", "kind": "fill", "mode": "multiply", "value": 0.5, "unit": "factor"},
        {"id": 1, "name": "Thin skin", "kind": "fill", "mode": "replace", "value": 80.0, "unit": "density",
         "opacity": 0.5, "scope": "locks", "locks": [14], "parent": 4},
        {"id": 2, "name": "Plus", "kind": "fill", "mode": "add", "value": 40.0, "unit": "density"},
        {"id": 3, "name": "Hand", "kind": "paint", "mode": "max"},
        {"id": 4, "name": "Crown", "kind": "folder", "opacity": 0.7},
        {"id": 5, "name": "Equal 2", "kind": "fill", "mode": "replace", "value": 2.0, "unit": "factor"},
        {"id": 6, "name": "", "kind": "fill", "mode": "min", "value": 1.0},
    ]}
    text = json.dumps(old)
    d = GroomData.from_json(text)
    assert [m.name for m in d.masks] == ["Thin skin", "Crown"] and d.schema == 4
    kept = d.mask(1)
    assert (kept.value, kept.opacity, kept.scope, kept.locks, kept.parent) == (80.0, 0.5, "locks", [14], 4)
    assert d.mask_id_high == 6 and d.add_mask().id == 7              # a dropped layer's id is never reused
    names = dropped_masks(text)
    assert names == ["Half", "Plus", "Hand", "Equal 2", "6"]
    said = dropped_text(names)
    assert said.startswith("5 density layers") and "Half" in said and "1 more" in said and "= D" in said
    assert dropped_text([]) == "" and dropped_text(["a"]).startswith("1 density layer from")
    # once written again nothing is dropped any more, and nothing unreadable raises
    assert dropped_masks(d.to_json()) == [] and dropped_masks("") == [] and dropped_masks("{broken") == []
    assert dropped_masks(json.dumps({"schema": 1})) == []


def test_schema_2_paint_layers_are_dropped_too():
    from tools.fx.grooming.model import dropped_masks
    text = json.dumps({"schema": 2, "masks": [{"id": 0, "name": "old", "mode": "add"},
                                               {"id": 1, "name": "older", "mode": "multiply"}]})
    d = GroomData.from_json(text)
    assert d.masks == [] and d.schema == 4 and d.mask_id_high == 1
    assert dropped_masks(text) == ["old", "older"]


def test_folders_hold_layers_one_level():
    d = GroomData()
    folder = d.add_mask(kind="folder")
    a = d.add_mask("a", parent=folder.id)
    b = d.add_mask("b")
    assert a.parent == folder.id and folder.name == "Folder 1"
    d.set_mask_parent(b.id, folder.id)
    assert GroomData.from_json(d.to_json()).mask(b.id).parent == folder.id
    other = d.add_mask(kind="folder")
    with pytest.raises(ValueError):
        d.set_mask_parent(other.id, folder.id)          # no folder in a folder
    with pytest.raises(ValueError):
        d.set_mask_parent(b.id, a.id)                   # only a folder holds layers
    d.set_mask_parent(b.id, None)
    assert d.mask(b.id).parent is None
    assert d.remove_mask(folder.id) and d.mask(a.id).parent is None     # deleting a folder keeps its layers


def test_a_layer_owned_by_a_missing_lock_follows_it_to_the_lock_it_is_given_to():
    d = GroomData()
    mine = d.add_mask("Lock B = 0", value=0.0, scope="locks", locks=[14, 3])
    both = d.add_mask("Two", scope="locks", locks=[14, 21])
    other = d.add_mask("Other", scope="locks", locks=[5])
    everyone = d.add_mask("All")
    assert d.reassign_mask_lock(14, 21) == ["Lock B = 0", "Two"]
    assert mine.locks == [3, 21] and both.locks == [21] and other.locks == [5] and everyone.locks == []
    assert d.reassign_mask_lock(14, 21) == []
