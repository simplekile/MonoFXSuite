"""MONO Grooming adapter: the hou-free helpers (Houdini parts are checked by hython in the sandbox)."""

from __future__ import annotations

import pytest

from apps.houdini import grooming_adapter as ga
from tools.fx.grooming import config, logic
from tools.fx.grooming.logic import DetectReport, Match, MeshPiece
from tools.fx.grooming.model import BUILTIN_DEFAULTS, GroomData, Group, Lock


@pytest.fixture
def lock_names(monkeypatch):
    """logic.lock_name is the logic session's; here a stand-in with its rule (one above the highest)."""
    def lock_name(prefix, taken):
        nums = [int(t.rsplit("_", 1)[1]) for t in taken if t.startswith(prefix + "_") and t.rsplit("_", 1)[1].isdigit()]
        return f"{prefix}_{max(nums, default=0) + 1:02d}"
    monkeypatch.setattr(logic, "lock_name", lock_name)


def _piece(i, name="", root=(0.0, 0.0, 0.0), length=0.2):
    return MeshPiece(index=i, name=name, root=root, length=length, direction=(0.0, -1.0, 0.0))


def test_group_id_from_mesh_name():
    assert ga.group_id_from_mesh_name("Geo_HairBang") == "hair_bang"
    assert ga.group_id_from_mesh_name("/char/Geo_HairBack") == "hair_back"
    assert ga.group_id_from_mesh_name("fringe left") == "fringe_left"
    assert ga.group_id_from_mesh_name("") == ga.DEFAULT_GROUP


def test_unique_names_keep_only_names_of_one_piece():
    assert ga.unique_names(["Geo_HairBang", "Geo_HairBang", "lock_a", ""]) == ["", "", "lock_a", ""]


def test_asset_from_scene():
    assert ga.asset_from_scene("char_Helen_grooming_v007.hiplc") == "char_Helen"
    assert ga.asset_from_scene("C:/x/char_Bob_grooming.hip") == "char_Bob"
    assert ga.asset_from_scene("prop_hat_v003.hipnc") == "prop_hat"


def test_preview_factor_is_fraction_capped_by_max_strands():
    assert ga.preview_factor(10_000) == pytest.approx(config.PREVIEW_FRACTION)
    capped = ga.preview_factor(1_000_000)
    assert capped <= config.PREVIEW_MAX_STRANDS / 1_000_000 < capped / config.PREVIEW_FACTOR_STEP
    assert ga.preview_factor(0) == pytest.approx(config.PREVIEW_FRACTION)
    assert ga.preview_factor(100, fraction=3.0) == 1.0


def test_lock_color_is_stable_and_distinct():
    assert ga.lock_color(5) == ga.lock_color(5)
    assert ga.lock_color(1) != ga.lock_color(2)
    assert ga.lock_color(-1) == ga.UNDETECTED_COLOR
    assert all(0.0 <= c <= 1.0 for c in ga.lock_color(42))


@pytest.mark.parametrize("cands, want", [
    ([("OUT_SCALP", 1500), ("OUT_HAIR", 196000)], (0, 1)),
    ([("OUT_HAIR", 196000), ("OUT_SCALP", 1500)], (1, 0)),
    ([("hair_driver", 10), ("head_skin", 5000)], (1, 0)),       # names win over counts
    ([("a", 1000), ("b", 9000)], (0, 1)),                       # no names: the big one is hair
    ([("a", 1000), ("b", 1500)], None),                         # cannot tell
    ([("OUT_SCALP", 10)], None),
])
def test_classify_inputs(cands, want):
    assert ga.classify_inputs(cands) == want


def test_assign_pieces_by_name_then_stored_root():
    locks = [Lock(id=1, name="a", group="g", root=(0, 0, 0), length=0.2),
             Lock(id=2, name="b", group="g", root=(1, 0, 0), length=0.2),
             Lock(id=3, name="c", group="g", root=(2, 0, 0), length=0.2)]
    pieces = [("", (1.0, 0.0, 0.0), 0.2),         # root of b
              ("a", (5.0, 0.0, 0.0), 0.2),        # name a, moved
              ("", (2.005, 0.0, 0.0), 0.2),       # within 5 % of c
              ("", (9.0, 0.0, 0.0), 0.2)]         # unknown
    assert ga.assign_pieces(pieces, locks) == [2, 1, 3, -1]


def test_assign_pieces_uses_each_lock_once():
    locks = [Lock(id=7, name="", group="g", root=(0, 0, 0), length=1.0)]
    pieces = [("", (0.01, 0, 0), 1.0), ("", (0.0, 0, 0), 1.0)]
    assert ga.assign_pieces(pieces, locks) == [-1, 7]


def test_apply_detect_first_time_names_groups_and_stale(lock_names):
    data = GroomData()
    pieces = [_piece(0, root=(0.1, 0.2, 0.3)), _piece(1, name="tuft", root=(1, 1, 1))]
    report = DetectReport(matches=[Match(0, 1, "new"), Match(1, 2, "new")])
    out = ga.apply_detect(data, pieces, ["hair_bang", "main"], report, asset="char_Helen")
    assert out.asset == "char_Helen"
    assert [(lk.id, lk.name, lk.group, lk.match) for lk in out.locks] == [
        (1, "hair_bang_01", "hair_bang", "new"), (2, "tuft", "main", "new")]
    assert out.locks[0].root == (0.1, 0.2, 0.3)
    assert {g.id for g in out.groups} == {"hair_bang", "main"}
    assert out.regions_stale is True
    assert data.locks == []  # input untouched


def test_apply_detect_keeps_settings_moves_orphans_and_only_stales_on_change(lock_names):
    data = GroomData(
        groups=[Group(id="g", name="G")],
        locks=[Lock(id=1, name="g_01", group="g", root=(0, 0, 0), length=0.2, overrides={"clump": 0.9}),
               Lock(id=2, name="g_02", group="g", root=(1, 0, 0), length=0.2, overrides={"frizz": 0.5})])
    same = DetectReport(matches=[Match(0, 1, "ok")], orphaned=[])
    out = ga.apply_detect(data, [_piece(0, root=(0, 0, 0))], ["g"], same)
    assert out.regions_stale is False and out.lock(1).overrides == {"clump": 0.9}

    gone = DetectReport(matches=[Match(0, 1, "unsure"), Match(1, 3, "new")], orphaned=[2])
    out = ga.apply_detect(data, [_piece(0, root=(0.01, 0, 0)), _piece(1, root=(3, 0, 0))], ["g", "g"], gone)
    assert [lk.id for lk in out.locks] == [1, 3]
    assert out.lock(1).match == "unsure" and out.lock(1).root == (0.01, 0.0, 0.0)
    assert out.lock(3).name == "g_03"          # g_02 stays taken by the orphan
    assert [(o.id, o.overrides) for o in out.orphans] == [(2, {"frizz": 0.5})]
    assert out.regions_stale is True


def test_detect_again_on_unchanged_unnamed_mesh_is_ok():
    """A mesh without per-lock names, detected twice: identical root and length match "ok" in
    logic.match_locks; a lock that moved a little stays "unsure"."""
    locks = [Lock(id=1, name="", group="g", root=(0, 0, 0), length=0.2),
             Lock(id=2, name="", group="g", root=(1, 0, 0), length=0.2)]
    pieces = [_piece(0, root=(0, 0, 0)), _piece(1, root=(1.01, 0, 0))]
    rep = logic.match_locks(pieces, locks, next_id=3)
    assert [(m.lock_id, m.status) for m in rep.matches] == [(1, "ok"), (2, "unsure")]


def test_apply_detect_stores_direction():
    out = ga.apply_detect(GroomData(), [_piece(0)], ["g"], DetectReport(matches=[Match(0, 1, "new")]))
    assert out.lock(1).direction == (0.0, -1.0, 0.0)


def test_lock_display_attribs_resolve_settings_and_visibility():
    data = GroomData(
        defaults={"density": 120.0},
        groups=[Group(id="g", name="G", color=(1.0, 0.0, 0.0), overrides={"clump": 0.8}),
                Group(id="hidden", name="H", visible=False)],
        locks=[Lock(id=1, name="a", group="g", overrides={"frizz": 0.3}),
               Lock(id=2, name="b", group="hidden")])
    out = ga.lock_display_attribs(data, [1, 2, -1])
    assert out["name"] == ["a", "b", ""]
    assert out["visible"] == [1, 0, 0]
    assert out["density"] == [120.0, 120.0, BUILTIN_DEFAULTS["density"]]
    assert out["clump"][0] == 0.8 and out["frizz"][0] == 0.3
    assert out["group_cd"][0] == (1.0, 0.0, 0.0)
    assert out["lock_cd"][2] == ga.UNDETECTED_COLOR
    assert out["lock_match"] == ["ok", "ok", "undetected"]
    assert out["root_flip"] == [0, 0, 0] and out["excluded"] == [0, 0, 0]


def test_preview_factor_capped_snaps_to_steps_so_small_edits_keep_it():
    # the factor is in every lock's cache key: a 1 % density edit must not change it (no full recook)
    assert ga.preview_factor(1_000_000) == ga.preview_factor(1_010_000)
    assert ga.preview_factor(1_000_000) > ga.preview_factor(2_000_000)


def test_lock_display_attribs_flip_exclude_and_hidden_group_keeps_lock_state():
    data = GroomData(groups=[Group(id="g", name="G", visible=False)],
                     locks=[Lock(id=1, name="a", group="g", root_flip=True, excluded=True)])
    out = ga.lock_display_attribs(data, [1])
    assert out["root_flip"] == [1] and out["excluded"] == [1] and out["visible"] == [0]
    assert data.lock(1).visible is True          # the lock's own eye is kept under the hidden group


def test_apply_detect_keeps_root_flip_and_exclude(lock_names):
    data = GroomData(locks=[Lock(id=1, name="a", group="g", root=(0.0, 0.0, 0.0), length=0.2,
                                 root_flip=True, excluded=True)])
    rep = DetectReport(matches=[Match(0, 1, "ok")])
    out = ga.apply_detect(data, [_piece(0, name="a")], ["g"], rep)
    assert out.lock(1).root_flip and out.lock(1).excluded
    gone = ga.apply_detect(data, [], [], DetectReport(orphaned=[1]))
    assert gone.orphans[0].root_flip and gone.orphans[0].excluded


def test_isolate_parse_and_format():
    assert ga.parse_isolate("") == [] and ga.parse_isolate(None) == []
    assert ga.parse_isolate("3 17,3 x 20") == [3, 17, 20]
    assert ga.format_isolate([20, 3, 3]) == "3 20" and ga.format_isolate(None) == ""


def test_lock_key_changes_with_any_part():
    k = ga.lock_key(["a", 1.0, b"\x00\x01"])
    assert k == ga.lock_key(["a", 1.0, b"\x00\x01"])
    assert k != ga.lock_key(["a", 1.0000001, b"\x00\x01"]) and k != ga.lock_key(["a", 1.0, b"\x00\x02"])


def test_lock_cache_keeps_last_two_keys_per_lock_and_mode():
    c = ga.LockCache()
    c.put(7, 1, "3", "k1", "g1")
    c.put(7, 1, "3", "k2", "g2")
    c.put(7, 2, "3", "k1", "other lock")
    c.put(7, 1, "2", "k1", "preview")
    assert c.has(7, 1, "3", "k1") and c.get(7, 1, "3", "k2") == "g2"
    assert c.get(7, 1, "3", "k1") == "g1"          # undo back to k1: found, now most recent
    c.put(7, 1, "3", "k3", "g3")                   # drops the least recently used: k2
    assert not c.has(7, 1, "3", "k2") and c.has(7, 1, "3", "k1") and c.has(7, 1, "3", "k3")
    assert c.get(7, 2, "3", "k1") == "other lock" and c.get(7, 1, "2", "k1") == "preview"
    assert c.get(7, 9, "3", "k1") is None
    c.drop_node(7)
    assert len(c) == 0 and c.nodes() == set()


def test_hair_cache_survives_adapter_reload():
    import importlib
    c = ga.hair_cache()
    c.put(-1, 1, "3", "k", "g")
    try:
        importlib.reload(ga)
        assert ga.hair_cache().get(-1, 1, "3", "k") == "g"
    finally:
        ga.hair_cache().drop_node(-1)


def test_publish_record_fields():
    data = GroomData(locks=[Lock(id=1, name="a", group="g")], groups=[Group(id="g", name="G")])
    rec = ga.publish_record("char_Helen", "v007", "x.usd", "s.hip", data, 1234, "/obj/g/n", "22.0")
    assert rec["asset"] == "char_Helen" and rec["version"] == "v007"
    assert rec["locks"] == 1 and rec["strands"] == 1234 and rec["department"] == "grooming"


def test_adapter_api_is_complete():
    for name in ("find_nodes", "create_node", "read_data", "write_data", "lock_infos", "detect",
                 "split_regions", "set_display", "selected_lock_ids", "select_locks", "publish",
                 "set_isolate", "isolate_ids", "set_root_flip", "set_excluded"):
        assert callable(getattr(ga, name))
    assert logic.LockInfo is ga.LockInfo


def test_detect_twice_on_unchanged_unnamed_short_locks_is_ok():
    """2 cm locks in a metre scene with float32-like roots: stored unrounded, so Detect again is ok."""
    import random
    rnd = random.Random(3)
    pieces = [MeshPiece(index=i, name="", root=(rnd.uniform(-.1, .1), rnd.uniform(1.5, 1.7), rnd.uniform(-.1, .1)),
                        length=rnd.uniform(0.01, 0.05), direction=(0.0, -1.0, 0.0)) for i in range(50)]
    first = logic.match_locks(pieces, [], next_id=1)
    data = GroomData.from_json(ga.apply_detect(GroomData(), pieces, ["g"] * 50, first).to_json())
    again = logic.match_locks(pieces, data.locks, data.next_lock_id())
    assert again.counts["ok"] == 50
