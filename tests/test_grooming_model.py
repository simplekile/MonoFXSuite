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
