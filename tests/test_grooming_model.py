"""MONO Grooming data model: settings resolution and the JSON format."""

from __future__ import annotations

import json

import pytest

from tools.fx.grooming import config

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

def test_v01_data_migrates_to_layers_without_changing_anything_else():
    from tools.fx.grooming.model import MaskLayer, migrate
    old = {"schema": 1, "asset": "char_Helen", "defaults": {"density": 120.0},
           "groups": [{"id": "g", "name": "g"}],
           "locks": [{"id": 1, "name": "g_01", "group": "g", "overrides": {"clump": 0.4}}], "id_high": 1}
    d = GroomData.from_json(json.dumps(old))
    assert d.asset == "char_Helen" and d.defaults == {"density": 120.0}
    assert d.lock(1).overrides == {"clump": 0.4} and d.id_high == 1
    # the automatic groom is the base layer, always there; nothing else
    assert [(m.id, m.kind, m.name) for m in d.masks] == [(-1, "base", "Automatic")]
    assert not d.has_layers() and d.density_layers() == [] and d.mask_id_high == -1 and d.schema == SCHEMA == 7
    new = migrate(dict(old))
    assert new["schema"] == 7 and "masks" not in old and new["masks_dropped"] == []     # the input is not changed
    with pytest.raises(ValueError, match="newer than this tool"):
        migrate({"schema": SCHEMA + 1})
    layer = MaskLayer(0, "x")
    assert layer.applies(1, "g") and (layer.kind, layer.mode, layer.value, layer.opacity) == ("paint", "normal", 1.0, 1.0)
    assert GroomData().masks[0].kind == "base"


def test_density_layers_and_their_masks_roundtrip_order_and_ids():
    d = GroomData()
    a = d.add_mask(kind="density", density=120.0)
    b = d.add_mask("Crown", kind="density", density=300.0, opacity=0.5, scope="group", group="bang")
    p = d.add_mask(parent=a.id)
    f = d.add_mask("Bound", kind="fill", parent=a.id, mode="multiply", value=0.25)
    e = d.add_mask("Two", kind="density", scope="locks", locks=[9, 3, 9])
    assert [m.id for m in d.masks] == [-1, 0, 2, 3, 1, 4]       # each density layer followed by its mask layers
    assert (a.name, p.name, e.locks, p.parent, f.parent) == ("Density 1", "Paint 1", [3, 9], 0, 0)
    assert (b.density, b.opacity, f.mode, f.value) == (300.0, 0.5, "multiply", 0.25)
    assert [m.id for m in d.density_layers()] == [0, 1, 4] and [m.id for m in d.mask_layers(0)] == [2, 3]
    d.move_mask(e.id, 0)                                        # a density layer among the density layers
    assert [m.id for m in d.masks] == [-1, 4, 0, 2, 3, 1]
    d.move_mask(f.id, 0)                                        # a mask layer inside its mask
    assert [m.id for m in d.mask_layers(0)] == [3, 2]
    d.move_mask(p.id, 0, parent=b.id)                           # ... or into another density layer's mask
    assert [m.id for m in d.mask_layers(1)] == [2] and d.mask(2).parent == 1
    back = GroomData.from_json(d.to_json())
    assert back.masks == d.masks and back.mask_id_high == 4
    assert back.add_mask(kind="density").id == 5
    assert back.mask(1).applies(7, "bang") and not back.mask(1).applies(7, "back")
    assert back.mask(4).applies(3, "back") and not back.mask(4).applies(4, "back")
    assert d.remove_mask(b.id) == [1, 2] and d.remove_mask(b.id) == []      # a density layer goes with its mask
    assert d.remove_mask(f.id) == [3] and [m.id for m in d.masks] == [-1, 4, 0]
    with pytest.raises(KeyError):
        d.move_mask(77, 0)


def test_the_base_layer_stays_first_and_cannot_be_deleted_or_moved():
    d = GroomData()
    a = d.add_mask(kind="density")
    with pytest.raises(ValueError):
        d.remove_mask(-1)
    with pytest.raises(ValueError):
        d.move_mask(-1, 3)
    d.move_mask(a.id, 0)
    assert [m.kind for m in d.masks] == ["base", "density"]
    with pytest.raises(ValueError):
        d.add_mask(kind="paint")                    # a mask layer belongs to a density layer
    with pytest.raises(ValueError):
        d.add_mask(kind="paint", parent=-1)         # the base holds none: its mask is full
    with pytest.raises(ValueError):
        d.add_mask(kind="folder")
    # a stored list without a base, or with it out of place, is put right on reading
    raw = json.loads(d.to_json())
    raw["masks"] = [m for m in raw["masks"] if m["kind"] != "base"]
    assert [m.kind for m in GroomData.from_json(json.dumps(raw)).masks] == ["base", "density"]


def test_layers_from_json_are_cleaned():
    d = GroomData.from_json(json.dumps({"schema": 6, "masks": [
        {"id": 5, "name": "x", "kind": "density", "opacity": 7, "scope": "nope", "locks": [3, 3, 1], "density": -4},
        {"id": 6, "name": "m", "mode": "screen", "value": 4, "kind": "sticker", "parent": 5},
        {"id": 7, "name": "lost", "kind": "paint", "parent": 99},
        {"id": 8, "name": "huge", "kind": "density", "density": 1e9}]}))
    x, m, huge = d.masks[1:]
    assert (x.opacity, x.scope, x.locks, x.density) == (1.0, "all", [1, 3], 0.0)
    assert (m.mode, m.value, m.kind, m.parent) == ("normal", 1.0, "paint", 5)
    assert huge.density == config.MASK_DENSITY_MAX and d.mask(7) is None       # a mask layer without its density layer
    assert d.mask_id_high == 8


def test_schema_4_density_layers_become_density_layers_with_their_mask():
    from tools.fx.grooming.model import converted_masks, dropped_masks, dropped_text
    four = json.dumps({"schema": 4, "mask_id_high": 2, "masks": [
        {"id": 0, "name": "= 120", "kind": "fill", "value": 120.0, "opacity": 0.5, "scope": "group", "group": "bang"},
        {"id": 1, "name": "F", "kind": "folder", "opacity": 0.5, "on": False},
        {"id": 2, "name": "Bare", "kind": "fill", "value": 0.0, "parent": 1}]})
    d = GroomData.from_json(four)
    assert [(m.id, m.kind, m.name, m.parent) for m in d.masks[1:]] == [
        (3, "density", "= 120", None), (0, "paint", "Mask", 3), (4, "density", "Bare", None), (2, "paint", "Mask", 4)]
    a, bare = d.mask(3), d.mask(4)
    assert (a.density, a.opacity, a.scope, a.group, a.on) == (120.0, 0.5, "group", "bang", True)
    assert (bare.density, bare.opacity, bare.on) == (0.0, 0.5, False)       # the folder's opacity and eye
    assert d.mask_id_high == 4 and d.add_mask(kind="density").id == 5
    assert dropped_masks(four) == [] and converted_masks(four) == ["= 120", "Bare"]
    said = dropped_text(dropped_masks(four), converted_masks(four))
    assert "2 layers" in said and "density layers" in said and "black = no hair" in said
    assert not d.mask(3).legacy and not d.mask(4).legacy                # "= D" layers are plain density layers
    assert converted_masks(d.to_json()) == [] and dropped_text([]) == ""


def test_schema_5_mask_layers_become_one_density_layer_per_owner():
    from tools.fx.grooming.model import converted_masks, dropped_masks
    five = json.dumps({"schema": 5, "defaults": {"density": 200.0},
                       "groups": [{"id": "bang", "name": "bang", "overrides": {"density": 90.0}}],
                       "locks": [{"id": 3, "name": "a", "group": "bang", "overrides": {"density": 60.0}}],
                       "masks": [{"id": 0, "name": "A", "kind": "paint"},
                                 {"id": 1, "name": "Folder", "kind": "folder", "opacity": 0.5},
                                 {"id": 2, "name": "B", "kind": "fill", "value": 0.5, "mode": "multiply",
                                  "scope": "locks", "locks": [3], "parent": 1},
                                 {"id": 3, "name": "C", "kind": "paint", "mode": "multiply", "opacity": 0.8},
                                 {"id": 4, "name": "G", "kind": "paint", "scope": "group", "group": "bang"}]})
    d = GroomData.from_json(five)
    rows = [(m.id, m.kind, m.name, m.parent) for m in d.masks[1:]]
    assert rows == [(5, "density", "Older build 1", None), (0, "paint", "A", 5), (3, "paint", "C", 5),
                    (6, "density", "Older build 2", None), (2, "fill", "B", 6),
                    (7, "density", "Older build 3", None), (4, "paint", "G", 7)]
    # each keeps the older build's rule for its mask (black = no hair, Multiply thins), also after a save
    assert all(d.mask(i).legacy for i in (5, 6, 7)) and not d.mask(0).legacy
    again = GroomData.from_json(d.to_json())
    assert all(again.mask(i).legacy for i in (5, 6, 7)) and not again.add_mask(kind="density").legacy
    # D = the owner's Density setting when the file is read: the groom's, the lock's, the group's
    assert (d.mask(5).density, d.mask(6).density, d.mask(7).density) == (200.0, 60.0, 90.0)
    assert (d.mask(6).scope, d.mask(6).locks, d.mask(7).group) == ("locks", [3], "bang")
    assert (d.mask(3).mode, d.mask(3).opacity, d.mask(2).mode, d.mask(2).value) == ("multiply", 0.8, "multiply", 0.5)
    assert d.mask(2).opacity == 0.5                                     # the folder's opacity
    assert dropped_masks(five) == [] and converted_masks(five) == ["A", "B", "C", "G"]


def test_schema_3_layers_carry_over_what_has_a_meaning_and_name_what_is_dropped():
    from tools.fx.grooming.model import converted_masks, dropped_masks, dropped_text
    old = {"schema": 3, "mask_id_high": 7, "masks": [
        {"id": 0, "name": "Half", "kind": "fill", "mode": "multiply", "value": 0.5, "unit": "factor", "opacity": 0.8},
        {"id": 1, "name": "Thin skin", "kind": "fill", "mode": "replace", "value": 80.0, "unit": "density"},
        {"id": 2, "name": "Double", "kind": "fill", "mode": "multiply", "value": 2.0, "unit": "factor"},
        {"id": 3, "name": "Hand", "kind": "paint", "mode": "replace", "scope": "locks", "locks": [14], "parent": 4},
        {"id": 4, "name": "Crown", "kind": "folder", "opacity": 0.7},
        {"id": 5, "name": "More", "kind": "fill", "mode": "add", "value": 40.0, "unit": "density"},
    ]}
    text = json.dumps(old)
    d = GroomData.from_json(text)
    assert d.schema == SCHEMA
    assert [(m.id, m.kind, m.name, m.parent) for m in d.masks[1:]] == [
        (8, "density", "Older build 1", None), (0, "paint", "Half", 8),
        (9, "density", "Thin skin", None), (1, "paint", "Mask", 9),
        (10, "density", "Older build 2", None), (3, "paint", "Hand", 10)]
    assert (d.mask(8).legacy, d.mask(9).legacy, d.mask(10).legacy) == (True, False, True)
    assert (d.mask(0).mode, d.mask(0).value, d.mask(0).opacity) == ("multiply", 0.5, 0.8)
    assert d.mask(9).density == 80.0                                   # strands / cm2 under its mask: as it was
    assert (d.mask(10).scope, d.mask(10).locks, d.mask(3).mode, d.mask(3).opacity) == ("locks", [14], "normal", 0.7)
    assert d.mask_id_high == 10 and d.add_mask(kind="density").id == 11         # no id is ever reused
    assert dropped_masks(text) == ["Double", "More"]                   # a factor over 1; strands / cm2 not in Replace
    assert converted_masks(text) == ["Half", "Thin skin", "Hand"]
    said = dropped_text(dropped_masks(text), converted_masks(text))
    assert said.startswith("2 layers from an older test build dropped (Double, More)") and "Thin skin" in said
    assert dropped_text(["a"]).startswith("1 layer from")
    assert dropped_masks(d.to_json()) == [] and dropped_masks("") == [] and dropped_masks("{broken") == []
    assert dropped_masks(json.dumps({"schema": 1})) == []
    two = json.dumps({"schema": 2, "masks": [{"id": 0, "name": "old", "mode": "add"}, {"id": 1, "name": "older"}]})
    d = GroomData.from_json(two)
    assert [(m.name, m.kind, m.mode) for m in d.masks[2:]] == [("old", "paint", "add"), ("older", "paint", "multiply")]


def test_reassigning_a_missing_lock_carries_its_settings_and_its_layers():
    from tools.fx.grooming.model import Group, Lock, Orphan
    d = GroomData(groups=[Group("back", "back")],
                  locks=[Lock(21, "hair_back_21", "back", match="new"), Lock(3, "hair_back_03", "back")],
                  orphans=[Orphan(14, "hair_back_14", "back", {"density": 80.0})])
    own = d.add_mask("Lock B bare", kind="density", density=0.0, scope="locks", locks=[14])
    assert d.reassign_orphan(99, 21) is None and d.reassign_orphan(14, 99) is None and own.locks == [14]
    assert d.reassign_orphan(14, 21) == ["Lock B bare"]
    assert own.locks == [21] and d.lock(21).overrides == {"density": 80.0} and d.lock(21).match == "ok"
    assert d.orphans == [] and own.applies(21, "back") and not own.applies(14, "back")
    assert GroomData.from_json(d.to_json()).mask(own.id).locks == [21]


def test_a_layer_owned_by_a_missing_lock_follows_it_to_the_lock_it_is_given_to():
    d = GroomData()
    mine = d.add_mask("Lock B", kind="density", scope="locks", locks=[14, 3])
    both = d.add_mask("Two", kind="density", scope="locks", locks=[14, 21])
    other = d.add_mask("Other", kind="density", scope="locks", locks=[5])
    everyone = d.add_mask("All", kind="density")
    assert d.reassign_mask_lock(14, 21) == ["Lock B", "Two"]
    assert mine.locks == [3, 21] and both.locks == [21] and other.locks == [5] and everyone.locks == []
    assert d.reassign_mask_lock(14, 21) == []
