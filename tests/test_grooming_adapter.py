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
        (1, "hair_bang_01", "hair_bang", "ok"), (2, "tuft", "main", "ok")]   # the first Detect: none "new"
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


def test_lock_display_attribs_row_display_lock_wins_over_group():
    # each row's own Display reaches the HDA (it was stored but never read): lock, else group, else -1
    data = GroomData(groups=[Group(id="g", name="G", display="guide"), Group(id="h", name="H")],
                     locks=[Lock(id=1, name="a", group="g"), Lock(id=2, name="b", group="g", display="mesh"),
                            Lock(id=3, name="c", group="h"), Lock(id=4, name="d", group="h", display="hair_preview")])
    out = ga.lock_display_attribs(data, [1, 2, 3, 4, -1])
    modes = list(config.DISPLAY_MODES)
    assert out["row_display"] == [modes.index("guide"), modes.index("mesh"), -1, modes.index("hair_preview"), -1]


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


def test_lock_cache_keeps_every_state_while_memory_lasts():
    c = ga.LockCache(limit=1000)
    for i in range(30):                              # 30 strokes on one lock, 10 bytes a state
        c.put(7, 1, "hair", f"k{i}", f"g{i}", size=10)
    assert all(c.has(7, 1, "hair", f"k{i}") for i in range(30))      # a count of states is no limit any more
    assert c.get(7, 1, "hair", "k3") == "g3" and c.get(7, 9, "hair", "k1") is None
    use = c.usage(7)
    assert use["bytes"] == 300 and use["limit_bytes"] == 1000 and use["dropped"] == 0
    assert use["live_bytes"] > 0 and use["undo_bytes"] == use["bytes"] - use["live_bytes"]
    c.drop_node(7)
    assert len(c) == 0 and c.nodes() == set() and c.usage(7)["bytes"] == 0


def test_lock_cache_drops_the_states_used_longest_ago_when_full():
    c = ga.LockCache(limit=100)
    c.begin(7)
    for i in range(10):
        c.put(7, 1, "hair", f"k{i}", i, size=10)
    c.begin(7)
    assert c.usage(7)["bytes"] == 100
    assert c.get(7, 1, "hair", "k0") == 0            # an undo all the way back: k0 is now the state in use
    c.begin(7)
    c.put(7, 1, "hair", "k10", 10, size=30)          # 30 bytes more: the ones used longest ago go, down to
    # TRIM_TO of the limit (95), so the next stores find room without another pass
    assert [i for i in range(11) if c.has(7, 1, "hair", f"k{i}")] == [0, 5, 6, 7, 8, 9, 10]
    assert c.usage(7)["bytes"] == 90 and c.usage(7)["dropped"] == 4
    # another node has its own limit and is not touched
    c.put(8, 1, "hair", "x", "other", size=5000)
    assert c.has(8, 1, "hair", "x") and c.usage(7)["bytes"] == 90
    c.begin(7)                                       # (asking above counted as using: a new cook)
    c.set_limit(7, 40)                               # the artist lowers the limit: trimmed at once
    assert c.usage(7)["bytes"] <= 40 and c.limit(7) == 40


def test_lock_cache_never_drops_the_state_in_use():
    c = ga.LockCache(limit=25)
    c.begin(7)
    c.put(7, 1, "hair", "a", "lock 1", size=20)
    c.put(7, 2, "hair", "a", "lock 2", size=20)       # over the limit, but both are what the node shows
    c.put(7, 3, "hair", "a", "lock 3", size=20)
    assert all(c.has(7, k, "hair", "a") for k in (1, 2, 3)) and c.usage(7)["bytes"] == 60
    c.begin(7)                                        # the next cook: lock_keys asks for what it will read
    assert c.has(7, 1, "hair", "a")
    c.put(7, 1, "hair", "b", "lock 1 edited", size=20)
    # "a" of lock 1 was asked for in this cook and may still be read: kept until the next one
    assert c.has(7, 1, "hair", "a") and c.get(7, 1, "hair", "b") == "lock 1 edited"
    c.begin(7)
    c.put(7, 2, "hair", "b", "lock 2 edited", size=20)
    assert not c.has(7, 1, "hair", "a")               # an older state: the first to go
    assert c.get(7, 1, "hair", "b") == "lock 1 edited" and c.get(7, 3, "hair", "a") == "lock 3"
    # a limit of 0 keeps what the node shows and nothing else: undo is then a recook, still right
    z = ga.LockCache(limit=0)
    z.put(7, 1, "hair", "a", "x", size=20)
    z.begin(7)
    z.put(7, 1, "hair", "b", "y", size=20)
    z.begin(7)
    z.put(7, 1, "hair", "c", "z", size=20)
    assert z.get(7, 1, "hair", "c") == "z" and not z.has(7, 1, "hair", "a") and z.usage(7)["bytes"] <= 40


def test_lock_cache_sizes_values_with_its_sizer_and_keeps_only_named_copies():
    c = ga.LockCache(sizer=len, limit=10 ** 6)
    c.put(7, 1, "hair", "k", "12345")
    c.put(7, 1, "hair", "k", "123")                  # the same key again replaces it
    assert c.usage(7)["bytes"] == 3
    c.put(7, 1, "hair#cd", "k|red", "copy one")
    c.put(7, 1, "hair#cd", "k|red|ghost", "copy two")
    c.put(7, 1, "hair#cd", "old|red", "an earlier state's copy")
    c.keep_only(7, 1, "hair#cd", ("k|red", "k|red|ghost"))
    assert not c.has(7, 1, "hair#cd", "old|red") and c.has(7, 1, "hair#cd", "k|red|ghost")
    assert c.usage(7)["bytes"] == 3 + len("copy one") + len("copy two")
    c.put_derived(7, 1, "hair#cd", "k|blue", "a copy is stored like anything else")
    assert c.get(7, 1, "hair#cd", "k|blue") and c.usage(7)["entries"] == 4
    assert sorted(c.values(7, "hair#cd")) == ["a copy is stored like anything else", "copy one", "copy two"]
    assert c.values(7, "nothing") == [] and c.values(8, "hair#cd") == []
    assert c.latest(7, 1, "hair#cd") == "a copy is stored like anything else" and c.latest(7, 5, "hair") is None
    assert ga._geo_bytes("not a geometry") == 0
    assert ga.LockCache().limit(1) == int(config.UNDO_CACHE_GB * 2 ** 30) and config.UNDO_CACHE_GB == 2.0
    assert config.UNDO_CACHE_PARM in ga._KEY_SKIP_PARMS      # changing the limit regrows nothing


def test_lock_cache_drop_forgets_one_slot_only():
    # the whole merge (hair_cache / groom_cache) keeps one key: the old one is dropped before a put
    c = ga.LockCache()
    c.put(7, ga.MERGED_LOCK, ga.MERGED_MODE + "groom_cache", "a", "whole a")
    c.put(7, ga.MERGED_LOCK, ga.MERGED_MODE + "hair_cache", "a", "display")
    c.put(7, 1, "hair", "k", "lock 1")
    c.drop(7, ga.MERGED_LOCK, ga.MERGED_MODE + "groom_cache")
    c.put(7, ga.MERGED_LOCK, ga.MERGED_MODE + "groom_cache", "b", "whole b")
    assert not c.has(7, ga.MERGED_LOCK, ga.MERGED_MODE + "groom_cache", "a")
    assert c.get(7, ga.MERGED_LOCK, ga.MERGED_MODE + "groom_cache", "b") == "whole b"
    assert c.get(7, ga.MERGED_LOCK, ga.MERGED_MODE + "hair_cache", "a") == "display"
    assert c.get(7, 1, "hair", "k") == "lock 1"
    c.drop(7, 99, "nothing there")   # no error


def test_groom_output_contract():
    assert config.OUTPUT_LABELS == ("Display", "Groom")
    assert set(config.GROOM_ATTRIBS) == {"width", "lock_id", "name", "group", "clump_id", "id"}
    assert not set(config.GROOM_ATTRIBS) & set(config.LOOP_ONLY_ATTRIBS)


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
    assert rec["masks"] == {} and rec["schema"] == 6
    rec = ga.publish_record("char_Helen", "v007", "x.usd", "s.hip", data, 1, "/obj/g/n", masks={"file": "m.bgeo"})
    assert rec["masks"] == {"file": "m.bgeo"}


def test_adapter_api_is_complete():
    for name in ("find_nodes", "create_node", "read_data", "write_data", "lock_infos", "detect",
                 "split_regions", "set_display", "selected_lock_ids", "select_locks", "publish",
                 "set_isolate", "isolate_ids", "set_root_flip", "set_excluded",
                 # v0.2a density masks
                 "mask_add", "mask_remove", "mask_move", "mask_set", "mask_fill", "mask_clear", "mask_values",
                 "mask_cover", "mask_dropped", "mask_stroke", "mask_problem", "mask_rebake", "set_brush", "brush",
                 "paint_enter", "paint_exit", "paint_layer", "import_masks", "masks_from_publish",
                 "cook_mask_read"):
        assert callable(getattr(ga, name))
        assert name in ga.__all__ or name == "cook_mask_read"
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


def test_playing_state_from_playbar_events():
    assert ga.playing_state("Started") is True and ga.playing_state("Stopped") is False
    assert ga.playing_state("FrameChanged") is None


def test_only_a_deforming_node_plays_lighter():
    # without the deform nothing cooks per frame: switching to the While playing display only recooked
    assert ga.playing_flag(True, True) == 1
    assert ga.playing_flag(True, False) == 0
    assert ga.playing_flag(False, True) == 0 and ga.playing_flag(False, False) == 0


def test_install_playbar_callback_needs_houdini():
    ga.install_playbar_callback()   # no hou here: does nothing, raises nothing


def test_scene_opens_at_rest_in_the_ui_but_keeps_the_deform_when_caching():
    """t56: a hython / farm job caching output 1 opened the shot scene, OnLoaded turned Shot deform off,
    and every cached frame was the rest groom (342 m from the character on sh020)."""
    ui = dict(ga.loaded_resets(True))
    batch = dict(ga.loaded_resets(False))
    assert ui["shot_deform"] == 0
    assert "shot_deform" not in batch
    for name in (ga.PARM_ISOLATE, ga.PARM_FOCUS, ga.PARM_PLAYING):   # view state goes back either way
        assert name in ui and name in batch


def test_anim_mismatch_text():
    assert ga.anim_mismatch_text(196202, 196202) == ""
    assert ga.anim_mismatch_text(196102, 196202) == "Anim hair mesh: 196102 points, rest hair mesh 196202: no deform"
    assert "no prims named like" in ga.anim_mismatch_text(0, 196202)
    assert callable(ga.deform_problem)


def test_a_scene_from_before_the_fit_lookup_keeps_it_off():
    """Only a stored groom_data of schema 1 to 4 is such a scene; a new node (no data) keeps the default."""
    import json
    assert ga.scene_before_lookup(json.dumps({"schema": 1, "locks": []}))
    assert ga.scene_before_lookup(json.dumps({"locks": []}))               # v0.1 wrote schema 1; none = 1
    assert ga.scene_before_lookup(json.dumps({"schema": 4}))
    assert not ga.scene_before_lookup(json.dumps({"schema": ga.LOOKUP_SINCE_SCHEMA}))
    assert not ga.scene_before_lookup(json.dumps({"schema": 6}))
    assert not ga.scene_before_lookup("") and not ga.scene_before_lookup(None) and not ga.scene_before_lookup("{broken")
    assert callable(ga.keep_old_lookup) and "off" in ga.LOOKUP_KEPT_TEXT


def test_no_output_captures_in_the_loop():
    """Every output's locks are the rest strands, one cache entry a state; the capture a deform needs is made
    apart (cook_groom_captured). In the loop it held 800 B a point for every state of every lock, and with
    Shot deform on every undo regrew its locks (t64 B6)."""
    for groom in (True, False):
        for wired in (True, False):
            for deforming in (True, False):
                assert ga.capture_flag(groom=groom, wired=wired, deforming=deforming) == 0
    # one capture a lock per kind of hair: the display in Hair shares output 1's, a preview has its own
    assert ga.capture_slot("hair") == ga.GROOM_CAPTURE_MODE != ga.capture_slot("hair_preview")
    assert callable(ga.cook_deform_keys) and callable(ga.cook_deform_store) and callable(ga.cook_deform_load)


def test_deformed_states_never_push_the_hair_out():
    """`keep_bytes`: one slot's states inside a share of the limit, the oldest going first, the last kept."""
    c = ga.LockCache(sizer=len, limit=10_000)
    slot = ga.DEFORMED_MODE + "hair"
    for k in "abcd":
        c.put_derived(1, ga.MERGED_LOCK, slot, k, "x" * 100)
    c.put(1, 5, "hair", "h", "y" * 50)
    assert c.keep_bytes(1, ga.MERGED_LOCK, slot, 250) == 2
    assert [c.has(1, ga.MERGED_LOCK, slot, k) for k in "abcd"] == [False, False, True, True]
    assert c.keep_bytes(1, ga.MERGED_LOCK, slot, 0) == 1 and c.has(1, ga.MERGED_LOCK, slot, "d")    # the last stays
    assert c.has(1, 5, "hair", "h") and c.usage(1)["bytes"] == 150
    assert c.keep_bytes(1, ga.MERGED_LOCK, "nothing", 0) == 0
    # full: a deformed state goes before any hair state, however lately it was used
    c = ga.LockCache(sizer=len, limit=450)
    c.put(1, 5, "hair", "h0", "y" * 100)
    c.put(1, 5, "hair", "h1", "y" * 100)
    c.put_derived(1, ga.MERGED_LOCK, slot, "d0", "x" * 100)
    c.put_derived(1, ga.MERGED_LOCK, slot, "d1", "x" * 100)
    c.begin(1)
    c.put(1, 5, "hair", "h2", "y" * 100)             # over the limit
    assert not c.has(1, ga.MERGED_LOCK, slot, "d0") and c.has(1, 5, "hair", "h0") and c.has(1, 5, "hair", "h1")
    assert ga.GROOM_CAPTURE_MODE != ga.cache_mode(False, 1.0, 1) and callable(ga.cook_groom_captured)
    assert callable(ga.cook_capture_keys) and callable(ga.cook_capture_load) and callable(ga.cook_capture_store)


def test_captured_strands_have_a_cache_slot_of_their_own():
    assert ga.cache_mode(drag=False, factor=1.0, capture=0) == "hair"
    assert ga.cache_mode(drag=False, factor=1.0, capture=1) == "hair" + ga.CAPTURE_MODE
    assert ga.cache_mode(drag=False, factor=0.1, capture=0) == "hair_preview"
    assert ga.cache_mode(drag=True, factor=1.0, capture=1) == "drag" + ga.CAPTURE_MODE
    c = ga.LockCache()
    plain, captured = ga.cache_mode(False, 1.0, 0), ga.cache_mode(False, 1.0, 1)
    c.put(1, 7, plain, "before", "hair before")
    c.put(1, 7, captured, "before", "captured before")
    c.put(1, 7, plain, "after", "hair after")
    c.put(1, 7, captured, "after", "captured after")
    assert c.has(1, 7, plain, "before") and c.has(1, 7, captured, "before")   # the undo finds both


# ---- v0.2a density masks (apps/houdini/grooming_masks.py, the parts without hou) ----

def _grid_brush(n=9, step=0.01):
    """A flat n x n grid of scalp points facing +y, each joined to its 4 neighbours."""
    np = pytest.importorskip("numpy")
    from apps.houdini import grooming_masks as gm
    P = np.array([(x * step, 0.0, z * step) for z in range(n) for x in range(n)], np.float32)
    N = np.tile(np.array([0.0, 1.0, 0.0], np.float32), (n * n, 1))
    nb = []
    for z in range(n):
        for x in range(n):
            nb.append([zz * n + xx for xx, zz in ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1))
                       if 0 <= xx < n and 0 <= zz < n])
    return gm, np, P, N, nb


def test_mask_digest_is_empty_for_skin_at_one_and_changes_with_any_value():
    np = pytest.importorskip("numpy")
    from apps.houdini import grooming_masks as gm
    ones = np.ones(50, np.float32)
    assert gm.values_digest(ones) == "" and gm.values_digest(np.zeros(0, np.float32)) == ""
    a = ones.copy(); a[7] = 0.5
    b = ones.copy(); b[8] = 0.5          # the same sum, another place: the 9 region sums could not tell
    assert gm.values_digest(a) and gm.values_digest(a) != gm.values_digest(b)
    assert gm.values_digest(a) == gm.values_digest(a.copy())


def test_points_by_lock_gives_shared_points_to_each_owner():
    from apps.houdini import grooming_masks as gm
    got = gm.points_by_lock([(3,), (3, 5), (), (5,)])
    assert sorted(got) == [3, 5] and list(got[3]) == [0, 1] and list(got[5]) == [1, 3]


def test_neighbours_are_the_points_sharing_a_prim_in_any_vertex_order():
    np = pytest.importorskip("numpy")
    from apps.houdini import grooming_masks as gm
    # two quads sharing the edge 1-2 and a triangle on point 5, vertices listed out of order
    vertex_prim = [1, 0, 0, 1, 0, 1, 0, 1, 2, 2, 2]
    vertex_point = [1, 0, 1, 2, 2, 4, 3, 5, 5, 6, 7]
    table = gm.shared_prim_neighbours(vertex_prim, vertex_point, 9)
    nb = [sorted(int(i) for i in row if i >= 0) for row in table]
    assert nb[0] == [1, 2, 3] and nb[1] == [0, 2, 3, 4, 5] and nb[5] == [1, 2, 4, 6, 7]
    assert nb[6] == [5, 7] and nb[8] == []                      # a point in no prim has no neighbour
    assert gm.shared_prim_neighbours([], [], 3).shape == (3, 1)


def test_brush_reaches_only_joined_skin_facing_the_same_way():
    gm, np, P, N, nb = _grid_brush()
    brush = gm.ScalpBrush(P, N, gm.neighbour_table(nb))
    idx, dist = brush.reach((0.04, 0.0, 0.04), 0.025)
    assert 40 in idx and len(idx) == 21 and float(dist.max()) < 0.025     # a disc on the open grid
    # the same points, but the right half faces away (skin behind an ear): the dab stays on its side
    N2 = N.copy(); N2[P[:, 0] > 0.045] = (0.0, -1.0, 0.0)
    idx2, _ = gm.ScalpBrush(P, N2, gm.neighbour_table(nb)).reach((0.04, 0.0, 0.04), 0.025)
    assert len(idx2) < 21 and float(P[idx2][:, 0].max()) < 0.045
    # a wall of removed neighbours (two sheets lying close): skin beyond it is inside the radius, not reached
    cut = [[j for j in row if (P[i, 0] > 0.045) == (P[j, 0] > 0.045)] for i, row in enumerate(nb)]
    idx3, _ = gm.ScalpBrush(P, N, gm.neighbour_table(cut)).reach((0.03, 0.0, 0.04), 0.025)
    assert float(P[idx3][:, 0].max()) < 0.045 and len(idx3) > 5
    assert len(brush.reach((5.0, 0.0, 5.0), 0.025)[0]) == 0             # off the scalp: nothing


def _layers(*density):
    """A GroomData with one density layer per number, each with one paint layer: (data, [(density, paint)])."""
    from tools.fx.grooming.model import GroomData
    data = GroomData()
    rows = []
    for d in density:
        layer = data.add_mask(kind="density", density=d)
        rows.append((layer, data.add_mask(parent=layer.id)))
    return data, rows


def test_mask_data_dab_and_cover():
    gm, np, P, N, nb = _grid_brush()
    data, [(layer, paint)] = _layers(300.0)
    md = gm.MaskData(P)
    brush = gm.ScalpBrush(P, N, gm.neighbour_table(nb))
    idx, dist = brush.reach((0.04, 0.0, 0.04), 0.025)
    md.dab(paint.id, idx, logic.brush_weights(dist, 0.025, 0.5), 1.0)     # white, soft edge
    assert md.painted(paint.id) == int((logic.brush_weights(dist, 0.025, 0.5) > 0).sum())
    keep, add = md.compose(data, [layer])
    assert keep[40] == 0.0 and add[40] == pytest.approx(300.0)            # painted white: D, over the lock's 150 too
    assert keep[0] == 1.0 and add[0] == 0.0 and keep.dtype == np.float32  # not painted: the automatic groom
    edge = int(idx[np.argmax(dist)])
    assert 0.0 < keep[edge] < 1.0 and add[edge] == pytest.approx(300.0 * (1.0 - keep[edge]), rel=1e-5)
    layer.opacity = 0.5
    keep, add = md.compose(data, [layer])
    assert keep[40] == pytest.approx(0.5) and add[40] == pytest.approx(150.0)
    layer.opacity = 1.0
    assert md.mask_of(data, layer.id)[40] == 1.0 and md.mask_of(data, layer.id)[0] == 0.0
    never = gm.MaskData(P).compose(data, [layer])
    assert never[0].min() == 1.0 and never[1].max() == 0.0               # a paint layer never painted is transparent
    md.dab(paint.id, idx, np.ones(len(idx), np.float32), 9.0)             # a mask value is kept inside 0..1
    assert float(md.v[paint.id].max()) == 1.0
    md.dab(paint.id, idx, np.ones(len(idx), np.float32), 0.0)             # black over the white: the density below
    keep, add = md.compose(data, [layer])
    assert keep[40] == 1.0 and add[40] == 0.0 and md.painted(paint.id) == len(idx)
    md.dab(paint.id, idx, np.ones(len(idx), np.float32), erase=True)      # erase: the layer's paint is gone
    assert md.painted(paint.id) == 0 and md.compose(data, [layer])[0].min() == 1.0


def test_density_layers_stack_and_each_reads_its_own_mask():
    gm, np, P, N, nb = _grid_brush()
    data, [(low, low_paint), (high, high_paint)] = _layers(40.0, 300.0)
    md = gm.MaskData(P)
    brush = gm.ScalpBrush(P, N, gm.neighbour_table(nb))
    idx, dist = brush.reach((0.04, 0.0, 0.04), 0.025)
    w = logic.brush_weights(dist, 0.025, 0.0)                      # a hard brush
    md.dab(low_paint.id, idx, w, 1.0)
    md.dab(high_paint.id, idx, w, 0.5)                             # the upper layer at half
    keep, add = md.compose(data, [low, high])
    assert keep[40] == 0.0 and add[40] == pytest.approx(40.0 + (300.0 - 40.0) * 0.5)
    keep_w, ws = md.weights(data, [low, high])
    assert ws[0][40] == pytest.approx(0.5) and ws[1][40] == pytest.approx(0.5) and keep_w[40] == 0.0
    # a fill layer: one value over all the skin, full coverage, nothing stored for it
    fill = data.add_mask(kind="fill", parent=high.id, value=1.0)
    assert fill.id not in md.a and md.coverage(fill).min() == 1.0 and md.value(fill)[0] == pytest.approx(1.0)
    keep, add = md.compose(data, [low, high])
    assert keep.max() == 0.0 and add == pytest.approx(np.full(len(P), 300.0))
    # Multiply as the top layer of a mask bounds what is below it in that mask
    fill.mode, fill.value = "multiply", 0.5
    assert md.mask_of(data, high.id)[40] == pytest.approx(0.25) and md.mask_of(data, high.id)[0] == 0.0
    # D = 0 painted white: no hair
    data0, [(none, none_paint)] = _layers(0.0)
    md0 = gm.MaskData(P)
    md0.dab(none_paint.id, idx, w, 1.0)
    keep, add = md0.compose(data0, [none])
    assert keep[40] == 0.0 and add[40] == 0.0 and keep[0] == 1.0
    # a layer carried over from an older file: coverage only, its row's one value under it
    md2 = gm.MaskData(P)
    md2.a[low_paint.id] = np.zeros(len(P), np.float32)
    md2.a[low_paint.id][idx] = 1.0
    low_paint.value = 0.5
    assert md2.mask_of(data, low.id)[40] == pytest.approx(0.5)


def test_a_layer_of_an_older_build_thins_and_keeps_black_as_no_hair():
    """A `legacy` density layer (a schema 5 file's 0..1 mask): its mask layers blend by that build's rule."""
    import json
    from tools.fx.grooming.model import GroomData
    gm, np, P, N, nb = _grid_brush()
    five = json.dumps({"schema": 5, "defaults": {"density": 200.0}, "masks": [
        {"id": 0, "name": "Paint", "kind": "paint"},
        {"id": 1, "name": "Min", "kind": "fill", "mode": "min", "value": 0.9},
        {"id": 2, "name": "Group", "kind": "fill", "mode": "multiply", "value": 0.5, "scope": "group", "group": "g"}]})
    data = GroomData.from_json(five)
    old, grp = data.density_layers()
    assert old.legacy and grp.legacy and old.density == 200.0
    md = gm.MaskData(P)
    md.ensure(0)
    md.a[0][:3] = 1.0
    md.v[0][:3] = (1.0, 0.0, 0.5)                                  # white, black, grey
    keep, add = md.compose(data, [old])
    # white: 0.9 of the owner's Density (the Min fill over it); black: no hair; grey: 0.5 of it; unpainted
    # skin: the automatic groom thinned to 0.9 by the Min fill (it did nothing before the fix)
    assert list(keep[:4]) == pytest.approx([0.0, 0.0, 0.0, 0.9]) and list(add[:4]) == pytest.approx([180.0, 0.0, 100.0, 0.0])
    assert list(md.mask_of(data, old.id)[:4]) == pytest.approx([1.0, 1.0, 1.0, 0.1])     # what it takes of the density below
    keep, add = md.compose(data, [old, grp])                       # the group's stack over it: x 0.5 on both parts
    assert list(keep[:4]) == pytest.approx([0.0, 0.0, 0.0, 0.45]) and list(add[:4]) == pytest.approx([90.0, 0.0, 50.0, 0.0])
    old.opacity = 0.5                                              # the layer's own opacity: half way to what is below
    keep, add = md.compose(data, [old])
    assert list(keep[:4]) == pytest.approx([0.5, 0.5, 0.5, 0.95]) and list(add[:4]) == pytest.approx([90.0, 0.0, 50.0, 0.0])
    # under a plain density layer nothing changed: a layer of 300 over the older build's
    old.opacity = 1.0
    top = data.add_mask(kind="density", density=300.0)
    data.add_mask(kind="fill", parent=top.id, value=0.5)
    keep, add = md.compose(data, [old, top])
    assert keep[3] == pytest.approx(0.45) and add[0] == pytest.approx(180.0 * 0.5 + 150.0)


def test_layers_for_view_shows_what_a_lock_of_the_painted_owner_gets():
    from apps.houdini import grooming_masks as gm
    from tools.fx.grooming.model import GroomData
    data = GroomData()
    everyone = data.add_mask(kind="density")
    bang = data.add_mask(kind="density", scope="group", group="bang")
    back = data.add_mask(kind="density", scope="group", group="back")
    top = data.add_mask(kind="density")
    paint = data.add_mask(parent=bang.id)
    assert [m.id for m in gm.layers_for_view(data.masks, everyone.id)] == [everyone.id, top.id]
    assert [m.id for m in gm.layers_for_view(data.masks, paint.id)] == [everyone.id, top.id, bang.id]
    assert [m.id for m in gm.layers_for_view(data.masks, None)] == [everyone.id, top.id]
    back.on = False
    assert [m.id for m in gm.layers_for_view(data.masks, back.id)] == [everyone.id, top.id]


def test_view_colours_density_and_one_layer_alone():
    np = pytest.importorskip("numpy")
    from apps.houdini import grooming_masks as gm
    value = np.array([1.0, 0.0, 1.0, 0.5], np.float32)
    cover = np.array([0.0, 1.0, 1.0, 0.5], np.float32)
    dens = np.array([0.0, 150.0, 7059.0, 40.0], np.float32)
    d = gm.view_colours("density", density=dens, reference=150.0)
    assert d.shape == (4, 3) and d.dtype == np.float32
    for i in range(4):
        assert d[i] == pytest.approx(logic.density_color(float(dens[i]), 150.0), abs=1e-5)
    # the density view is the final density map and nothing over it: a layer does not change a colour
    assert gm.view_colours("density", value, cover, density=dens, reference=150.0) == pytest.approx(d)
    plain = gm.view_colours("roots", points=4)
    assert plain.shape == (4, 3) and np.allclose(plain, plain[0])       # the dots carry the roots view
    one = gm.view_colours("layer", value, cover)
    for i in range(4):
        assert one[i] == pytest.approx(logic.layer_color(float(value[i]), float(cover[i])), abs=1e-6)
    assert one[2] == pytest.approx([1, 1, 1]) and one[1] == pytest.approx([0, 0, 0])
    assert one[0] == pytest.approx(logic.LAYER_UNPAINTED)
    with pytest.raises(ValueError):
        ga.set_brush(view="wireframe")
    assert config.MASK_VIEWS == ("density", "layer", "roots")


def test_strand_roots_are_each_strands_first_point():
    np = pytest.importorskip("numpy")
    from apps.houdini import grooming_masks as gm
    pts = np.arange(4 * 3 * 3, dtype=np.float32).reshape(-1, 3)        # 4 strands of 3 points
    roots = gm.strand_roots(pts.ravel(), 4)
    assert roots.shape == (4, 3) and roots[1] == pytest.approx(pts[3]) and roots[3] == pytest.approx(pts[9])
    assert gm.strand_roots(pts.ravel(), 5) is None and gm.strand_roots(pts.ravel(), 0) is None
    assert ga.set_brush(view="roots")["view"] == "roots" and ga.set_brush(view="density")["view"] == "density"


def test_root_density_counts_roots_over_the_skin_round_each_point():
    np = pytest.importorskip("numpy")
    from apps.houdini import grooming_masks as gm
    # a flat 21 x 21 patch of skin, points 1 mm apart, each owning 0.01 cm2; 400 roots / cm2 on its left half
    xs = np.arange(21) * 0.001
    P = np.array([(x, 0.0, z) for z in xs for x in xs])
    area = np.full(len(P), 0.01)
    rng = np.random.default_rng(1)
    roots = np.column_stack([rng.uniform(0.0, 0.010, 400 * 2 // 2), np.zeros(400), rng.uniform(0.0, 0.020, 400)])
    d = gm.root_density(P, area, roots, cell=0.002)
    left = d[(P[:, 0] < 0.006) & (P[:, 2] > 0.004) & (P[:, 2] < 0.016)]
    right = d[(P[:, 0] > 0.016)]
    assert 150 < float(np.median(left)) < 260           # 400 roots on 2 cm2 of skin: 200 / cm2
    assert float(right.max()) == 0.0                    # no root near: nothing
    assert d.dtype == np.float32 and d.shape == (len(P),)
    assert gm.root_density(P, area, np.zeros((0, 3)), 0.002).max() == 0.0
    assert gm.root_density(np.zeros((0, 3)), [], roots, 0.002).shape == (0,)


def test_brush_settings_are_clamped_and_kept_for_the_session():
    from apps.houdini import grooming_masks as gm
    before = gm.brush()
    try:
        got = ga.set_brush(radius_cm=2.5, value=7, soft=3, erase=True)
        assert got["radius_cm"] == 2.5 and got["value"] == 1.0 and got["soft"] == 1.0 and "level" not in got
        assert got["erase"] is True and ga.brush() == got and ga.set_brush(value=-1)["value"] == 0.0
        assert ga.set_brush(radius_cm=0)["radius_cm"] == 0.05
        assert ga.paint_layer(None) is None
    finally:
        gm.BRUSH.update(before)


def test_kept_share_follows_roots_to_where_they_end_up():
    np = pytest.importorskip("numpy")
    from apps.houdini import grooming_masks as gm
    n = np.array([100.0, 100.0, 100.0, 100.0])
    none = np.zeros(4)
    assert gm.kept_share(n, none, np.ones(4), 1.0) == pytest.approx(1.0)
    assert gm.kept_share(n, none, np.array([1.0, 1.0, 0.0, 0.0]), 1.0) == pytest.approx(0.5)
    # two prims under floating mesh send their roots to the lock's start: painting them changes nothing,
    # painting the start removes them
    far = np.array([0.0, 0.0, 1.0, 1.0])
    assert gm.kept_share(n, far, np.array([1.0, 1.0, 0.0, 0.0]), 1.0) == pytest.approx(1.0)
    assert gm.kept_share(n, far, np.ones(4), 0.0) == pytest.approx(0.5)
    assert gm.kept_share(np.zeros(4), far, np.ones(4), 0.0) == 1.0          # a lock with no strands
