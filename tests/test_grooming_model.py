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


# ---- v0.2a density mask layers ----

def test_v01_data_migrates_to_masks_without_changing_anything_else():
    from tools.fx.grooming.model import MaskLayer, migrate
    old = {"schema": 1, "asset": "char_Helen", "defaults": {"density": 120.0},
           "groups": [{"id": "g", "name": "g"}],
           "locks": [{"id": 1, "name": "g_01", "group": "g", "overrides": {"clump": 0.4}}], "id_high": 1}
    d = GroomData.from_json(json.dumps(old))
    assert d.asset == "char_Helen" and d.defaults == {"density": 120.0}
    assert d.lock(1).overrides == {"clump": 0.4} and d.id_high == 1
    assert d.masks == [] and d.mask_id_high == -1 and d.schema == SCHEMA == 5
    new = migrate(dict(old))
    assert new["schema"] == 5 and "masks" not in old and new["masks_dropped"] == []     # the input is not changed
    with pytest.raises(ValueError, match="newer than this tool"):
        migrate({"schema": SCHEMA + 1})
    layer = MaskLayer(0, "x")
    assert layer.applies(1, "g") and (layer.kind, layer.mode, layer.value, layer.opacity) == ("paint", "normal", 1.0, 1.0)
    assert not hasattr(layer, "unit")


def test_mask_layers_roundtrip_order_and_ids():
    d = GroomData()
    a = d.add_mask()
    b = d.add_mask("Crown", mode="multiply", opacity=0.5)
    c = d.add_mask("Fringe", scope="group", group="bang", kind="fill", value=0.25)
    e = d.add_mask("Two", scope="locks", locks=[9, 3, 9])
    assert [m.id for m in d.masks] == [0, 1, 2, 3] and a.name == "Layer 1" and e.locks == [3, 9]
    assert (b.mode, b.opacity) == ("multiply", 0.5) and (c.kind, c.value) == ("fill", 0.25)
    d.move_mask(c.id, 0)
    d.move_mask(a.id, 99)
    assert [m.name for m in d.masks] == ["Fringe", "Crown", "Two", "Layer 1"]
    assert d.remove_mask(b.id) and not d.remove_mask(b.id)
    back = GroomData.from_json(d.to_json())
    assert back.masks == d.masks and back.mask_id_high == 3 and '"unit"' not in d.to_json()
    assert back.add_mask().id == 4
    assert back.mask(2).applies(7, "bang") and not back.mask(2).applies(7, "back")
    assert back.mask(3).applies(3, "back") and not back.mask(3).applies(4, "back")
    with pytest.raises(KeyError):
        d.move_mask(77, 0)


def test_mask_layers_from_json_are_cleaned():
    d = GroomData.from_json(json.dumps({"schema": 5, "masks": [
        {"id": 5, "name": "x", "mode": "screen", "opacity": 7, "scope": "nope", "locks": [3, 3, 1], "value": 4,
         "kind": "sticker", "parent": 99}]}))
    m = d.masks[0]
    assert (m.mode, m.opacity, m.scope, m.locks, m.value, m.kind, m.parent) == ("normal", 1.0, "all", [1, 3], 1.0, "paint", None)
    assert d.mask_id_high == 5
    low = GroomData.from_json(json.dumps({"schema": 5, "masks": [{"id": 0, "value": -3}, {"id": 1, "value": "x"}]}))
    assert low.masks[0].value == 0.0 and low.masks[1].value == 1.0           # every value is 0..1


def test_older_dev_files_carry_over_what_has_a_meaning_and_name_what_is_dropped():
    from tools.fx.grooming.model import dropped_masks, dropped_text
    old = {"schema": 3, "mask_id_high": 7, "masks": [
        {"id": 0, "name": "Half", "kind": "fill", "mode": "multiply", "value": 0.5, "unit": "factor", "opacity": 0.8},
        {"id": 1, "name": "Thin skin", "kind": "fill", "mode": "replace", "value": 80.0, "unit": "density"},
        {"id": 2, "name": "Double", "kind": "fill", "mode": "multiply", "value": 2.0, "unit": "factor"},
        {"id": 3, "name": "Hand", "kind": "paint", "mode": "replace", "scope": "locks", "locks": [14], "parent": 4},
        {"id": 4, "name": "Crown", "kind": "folder", "opacity": 0.7},
        {"id": 5, "name": "Bare", "kind": "fill", "mode": "replace", "value": 0.0, "unit": "factor"},
    ]}
    text = json.dumps(old)
    d = GroomData.from_json(text)
    assert [m.name for m in d.masks] == ["Half", "Hand", "Crown", "Bare"] and d.schema == 5
    half, hand, crown, bare = d.masks
    # a fill layer had one value under a painted mask: a paint layer of that value, its mask the coverage
    assert (half.kind, half.mode, half.value, half.opacity) == ("paint", "multiply", 0.5, 0.8)
    assert (hand.kind, hand.mode, hand.locks, hand.parent) == ("paint", "normal", [14], 4)      # replace is Normal
    assert (crown.kind, crown.opacity) == ("folder", 0.7)
    assert (bare.kind, bare.mode, bare.value) == ("paint", "normal", 0.0)
    assert d.mask_id_high == 7 and d.add_mask().id == 8              # a dropped layer's id is never reused
    names = dropped_masks(text)
    assert names == ["Thin skin", "Double"]                          # strands / cm2, and a factor over 1
    said = dropped_text(names)
    assert said.startswith("2 density layers") and "Thin skin" in said and "0 to 1" in said
    assert dropped_text([]) == "" and dropped_text(["a"]).startswith("1 density layer from")
    assert dropped_masks(d.to_json()) == [] and dropped_masks("") == [] and dropped_masks("{broken") == []
    assert dropped_masks(json.dumps({"schema": 1})) == []


def test_schema_2_paint_layers_stay_and_schema_4_density_layers_go():
    from tools.fx.grooming.model import dropped_masks
    two = json.dumps({"schema": 2, "masks": [{"id": 0, "name": "old", "mode": "add"}, {"id": 1, "name": "older"}]})
    d = GroomData.from_json(two)
    assert [(m.name, m.kind, m.mode) for m in d.masks] == [("old", "paint", "add"), ("older", "paint", "multiply")]
    assert dropped_masks(two) == []
    four = json.dumps({"schema": 4, "masks": [{"id": 0, "name": "= 120", "kind": "fill", "value": 120.0},
                                               {"id": 1, "name": "F", "kind": "folder", "opacity": 0.5}]})
    d = GroomData.from_json(four)
    assert [(m.name, m.kind, m.opacity) for m in d.masks] == [("F", "folder", 0.5)] and d.mask_id_high == 1
    assert dropped_masks(four) == ["= 120"]


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


def test_reassigning_a_missing_lock_carries_its_settings_and_its_layers():
    from tools.fx.grooming.model import Group, Lock, Orphan
    d = GroomData(groups=[Group("back", "back")],
                  locks=[Lock(21, "hair_back_21", "back", match="new"), Lock(3, "hair_back_03", "back")],
                  orphans=[Orphan(14, "hair_back_14", "back", {"density": 80.0})])
    own = d.add_mask("Lock B bare", kind="fill", value=0.0, scope="locks", locks=[14])
    assert d.reassign_orphan(99, 21) is None and d.reassign_orphan(14, 99) is None and own.locks == [14]
    assert d.reassign_orphan(14, 21) == ["Lock B bare"]
    assert own.locks == [21] and d.lock(21).overrides == {"density": 80.0} and d.lock(21).match == "ok"
    assert d.orphans == [] and own.applies(21, "back") and not own.applies(14, "back")
    assert GroomData.from_json(d.to_json()).mask(own.id).locks == [21]


def test_a_layer_owned_by_a_missing_lock_follows_it_to_the_lock_it_is_given_to():
    d = GroomData()
    mine = d.add_mask("Lock B", scope="locks", locks=[14, 3])
    both = d.add_mask("Two", scope="locks", locks=[14, 21])
    other = d.add_mask("Other", scope="locks", locks=[5])
    everyone = d.add_mask("All")
    assert d.reassign_mask_lock(14, 21) == ["Lock B", "Two"]
    assert mine.locks == [3, 21] and both.locks == [21] and other.locks == [5] and everyone.locks == []
    assert d.reassign_mask_lock(14, 21) == []
