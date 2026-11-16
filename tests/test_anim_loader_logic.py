"""Mono Anim Loader 2.2: pure logic (no hou). Spec: docs/plans/anim_loader_v2_2.md."""

from __future__ import annotations

from tools.fx.anim_loader.logic import Output, instance_name, resolve_instance

A = {"char_Robot", "char_Robot_2", "prop_CoralSet_001", "char_Helen"}


def test_instance_name_strips_prefix_and_extension():
    assert instance_name("geo_char_Helen_inst02.usdc") == "char_Helen_inst02"
    assert instance_name("cam_sh010.usd") == "sh010"


def test_meta_wins():
    i = resolve_instance(Output("geo_char_Robot_2.usd", "geo", "char_Robot", 2), A)
    assert (i.name, i.asset, i.instance, i.guessed) == ("char_Robot_2", "char_Robot", 2, False)


def test_new_clone_suffix():
    i = resolve_instance(Output("geo_char_Robot_inst02.usd", "geo"), A)
    assert (i.name, i.asset, i.instance) == ("char_Robot_inst02", "char_Robot", 2)


def test_first_instance_is_one():
    i = resolve_instance(Output("geo_char_Helen.usd", "geo"), A)
    assert (i.asset, i.instance, i.guessed) == ("char_Helen", 1, True)


def test_asset_with_digits():
    i = resolve_instance(Output("geo_prop_CoralSet_001.usd", "geo"), A)
    assert (i.asset, i.instance) == ("prop_CoralSet_001", 1)


def test_old_clone_suffix():
    i = resolve_instance(Output("geo_char_Helen_2.usd", "geo"), A)
    assert (i.name, i.asset, i.instance, i.guessed) == ("char_Helen_2", "char_Helen", 2, True)


def test_ambiguous_old_clone():
    i = resolve_instance(Output("geo_char_Robot_2.usd", "geo"), A)
    assert i.asset is None and set(i.candidates) == {"char_Robot", "char_Robot_2"}


def test_no_asset_name():
    i = resolve_instance(Output("geo_sh011.usd", "geo"), A)
    assert i.asset is None and i.candidates == () and i.name == "sh011"


def test_camera():
    i = resolve_instance(Output("cam_sh010.usd", "cam"), A)
    assert (i.kind, i.asset, i.name) == ("cam", None, "sh010")


# --- Task 2: publishes on disk ---------------------------------------------------------------

from pathlib import Path  # noqa: E402

from tests.anim_loader_tree import frames, make  # noqa: E402
from tools.fx.anim_loader.logic import (  # noqa: E402
    Instance,
    anim_publish_dir,
    detect_shot,
    find_project_root,
    fx_match,
    list_asset_dirs,
    list_versions,
    lookdev_file,
    read_outputs,
    read_timeline,
)

SH = "02_shots/sh900"
GROOM = f"{SH}/02_fx/groom/publish"


def _inst(name, asset, n=1):
    return Instance(name, f"geo_{name}.usd", "geo", asset, n, False)


def test_project_root_and_shot(tmp_path):
    root = make(tmp_path / "proj", [f"{SH}/01_anim/houdini/work/sh900_v003.hiplc"])
    hip = root / SH / "01_anim/houdini/work/sh900_v003.hiplc"
    assert find_project_root(hip) == root
    assert detect_shot(hip) == "sh900"


def test_asset_dirs(tmp_path):
    root = make(tmp_path, ["01_assets/_characters/char_Robot/", "01_assets/_props/prop_CoralSet_001/",
                           "01_assets/notes/char_Fake/"])
    assert set(list_asset_dirs(root)) == {"char_Robot", "prop_CoralSet_001"}


def test_versions_case_and_junk(tmp_path):
    pub = tmp_path / "publish"
    for v in ("v001", "V002", "v002_old", "tmp", "v010"):
        (pub / v).mkdir(parents=True)
    assert list_versions(pub) == ["v001", "V002", "v010"]
    assert list_versions(tmp_path / "missing") == []


def test_outputs_from_meta(tmp_path):
    v = f"{SH}/01_anim/publish/v002"
    root = make(tmp_path, [f"{v}/geo_char_Robot_inst02.usd"], meta={v: {
        "fps": 24.0, "playback_range": [1, 24],
        "outputs": [{"file": "geo_char_Robot_inst02.usd", "type": "geo", "asset": "char_Robot", "instance": 2},
                    {"file": "cam_sh900.usd", "type": "cam"}]}})
    outs = read_outputs(root / v)
    assert outs == [Output("geo_char_Robot_inst02.usd", "geo", "char_Robot", 2), Output("cam_sh900.usd", "cam")]
    assert read_timeline(root / v) == (24.0, 1, 24)


def test_outputs_from_files_without_meta(tmp_path):
    v = f"{SH}/01_anim/publish/v001"
    root = make(tmp_path, [f"{v}/geo_char_Robot.usd", f"{v}/cam_sh900.usdc", f"{v}/notes.txt", f"{v}/old.usd"])
    assert read_outputs(root / v) == [Output("geo_char_Robot.usd", "geo"), Output("cam_sh900.usdc", "cam")]
    assert read_timeline(root / v) is None
    assert anim_publish_dir(root, "sh900") == root / SH / "01_anim/publish"


def test_lookdev_by_version(tmp_path):
    a = "01_assets/_characters/char_Robot"
    root = make(tmp_path, [f"{a}/05_lookdev/publish/v002/char_Robot_lookdev_publish.usd"])
    assert lookdev_file(root / a, "v002") == root / a / "05_lookdev/publish/v002/char_Robot_lookdev_publish.usd"
    assert lookdev_file(root / a, "v003") is None


def test_fx_exact_folder_only(tmp_path):
    root = make(tmp_path, frames(f"{GROOM}/v001/char_Robot", "sh900_groom", range(1, 25)))
    m = fx_match(root, "sh900", "groom", "v001", _inst("char_Robot_inst02", "char_Robot", 2), geo_count=3)
    assert m.folder is None and "char_Robot_inst02" in m.reason
    m = fx_match(root, "sh900", "groom", "v001", _inst("char_Robot", "char_Robot"), geo_count=3)
    assert m.folder == root / GROOM / "v001/char_Robot"
    assert m.pattern == (root / GROOM / "v001/char_Robot" / "sh900_groom.$F4.usd").as_posix()
    assert (m.first, m.last, m.missing) == (1, 24, ())


def test_fx_old_folder_style(tmp_path):
    root = make(tmp_path, frames(f"{GROOM}/v001/Robot_inst02", "sh900_groom", range(1, 4)))
    m = fx_match(root, "sh900", "groom", "v001", _inst("char_Robot_inst02", "char_Robot", 2), geo_count=2)
    assert m.folder == root / GROOM / "v001/Robot_inst02"


def test_fx_flat_only_when_single_instance(tmp_path):
    root = make(tmp_path, frames(f"{GROOM}/v001", "sh900_groom", range(1, 4)))
    one = fx_match(root, "sh900", "groom", "v001", _inst("char_Robot", "char_Robot"), geo_count=1)
    two = fx_match(root, "sh900", "groom", "v001", _inst("char_Robot", "char_Robot"), geo_count=2)
    assert one.folder == root / GROOM / "v001" and two.folder is None


def test_fx_gaps_and_padding(tmp_path):
    root = make(tmp_path, frames(f"{GROOM}/v001/char_Robot", "SH900_Groom", (1, 2, 4))
                + frames(f"{SH}/02_fx/cloth/publish/v001/char_Robot", "sh900_cloth", (0, 1), pad=3))
    m = fx_match(root, "sh900", "groom", "v001", _inst("char_Robot", "char_Robot"), geo_count=1)
    assert (m.first, m.last, m.missing) == (1, 4, (3,))
    assert m.pattern.endswith("SH900_Groom.$F4.usd")
    c = fx_match(root, "sh900", "cloth", "v001", _inst("char_Robot", "char_Robot"), geo_count=1)
    assert c.pattern.endswith("sh900_cloth.$F3.usd") and (c.first, c.last) == (0, 1)


def test_fx_unknown_asset(tmp_path):
    root = make(tmp_path, frames(f"{GROOM}/v001/char_Robot", "sh900_groom", (1,)))
    m = fx_match(root, "sh900", "groom", "v001", _inst("sh011", None), geo_count=1)
    assert m.folder is None and "asset?" in m.reason


# --- Task 3: loader state ------------------------------------------------------------------

from dataclasses import replace  # noqa: E402

from tools.fx.anim_loader.logic import (  # noqa: E402
    STATUS_ASSET,
    STATUS_MISSING,
    STATUS_NONE,
    STATUS_NEWER,
    STATUS_OFF,
    STATUS_OK,
    initial_state,
    resolve,
    status,
    with_latest,
)

ROBOT = "01_assets/_characters/char_Robot"
ANIM = f"{SH}/01_anim/publish"


def _shot(tmp_path):
    files = [f"{ANIM}/v001/geo_char_Robot.usd", f"{ANIM}/v001/geo_sh011.usd", f"{ANIM}/v001/cam_sh900.usd",
             f"{ROBOT}/05_lookdev/publish/v001/char_Robot_lookdev_publish.usd",
             f"{ROBOT}/05_lookdev/publish/v002/char_Robot_lookdev_publish.usd"]
    files += frames(f"{GROOM}/v001/char_Robot", "sh900_groom", (1, 2))
    return make(tmp_path, files)


def test_initial_picks_latest_once(tmp_path):
    root = _shot(tmp_path)
    st = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    assert (st.asset, st.instance_name, st.versions["lookdev"], st.versions["groom"]) == ("char_Robot", "char_Robot", "v002", "v001")
    r = resolve(st)
    assert r.anim == (root / ANIM / "v001/geo_char_Robot.usd").as_posix()
    assert r.lookdev.endswith("v002/char_Robot_lookdev_publish.usd") and r.groom.endswith("sh900_groom.$F4.usd")
    assert r.frames["groom"] == (1, 2) and r.cloth == ""
    make(root, [f"{ROBOT}/05_lookdev/publish/v003/char_Robot_lookdev_publish.usd"])
    assert resolve(st).lookdev == r.lookdev
    s = status(st)
    assert s["lookdev"] == (STATUS_NEWER, "v003") and s["anim"] == (STATUS_OK, None)
    assert s["groom"] == (STATUS_OK, None) and s["cloth"][0] == STATUS_NONE  # never published: not an error


def test_newer_anim_version(tmp_path):
    root = _shot(tmp_path)
    st = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    make(root, [f"{ANIM}/v002/cam_sh900.usd"])
    assert status(st)["anim"] == (STATUS_OK, None)  # v002 does not hold this instance
    make(root, [f"{ANIM}/v003/geo_char_Robot.usd"])
    assert status(st)["anim"] == (STATUS_NEWER, "v003")


def test_off_part(tmp_path):
    root = _shot(tmp_path)
    st = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    st = replace(st, enabled={**st.enabled, "groom": False})
    assert status(st)["groom"] == (STATUS_OFF, None) and resolve(st).groom == ""


def test_asset_unknown_parts(tmp_path):
    root = _shot(tmp_path)
    st = initial_state(root, "sh900", "v001", Output("geo_sh011.usd", "geo"))
    s = status(st)
    assert s["anim"] == (STATUS_OK, None)
    assert {s[p][0] for p in ("lookdev", "groom", "cloth")} == {STATUS_ASSET}


def test_camera_has_no_parts(tmp_path):
    root = _shot(tmp_path)
    st = initial_state(root, "sh900", "v001", Output("cam_sh900.usd", "cam"))
    assert st.kind == "cam" and {status(st)[p][0] for p in ("lookdev", "groom", "cloth")} == {STATUS_OFF}


def test_with_latest_only_named_parts(tmp_path):
    root = _shot(tmp_path)
    st = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    make(root, [f"{ROBOT}/05_lookdev/publish/v003/char_Robot_lookdev_publish.usd", f"{ANIM}/v004/geo_char_Robot.usd"]
         + frames(f"{GROOM}/v002/char_Robot", "sh900_groom", (1,)))
    up = with_latest(st, ("lookdev",))
    assert (up.versions["lookdev"], up.versions["groom"], up.anim_version) == ("v003", "v001", "v001")
    up = with_latest(st, ("anim", "groom"))
    assert (up.anim_version, up.versions["groom"], up.versions["lookdev"]) == ("v004", "v002", "v002")


def test_list_part_versions(tmp_path):
    from tools.fx.anim_loader.logic import list_part_versions

    root = _shot(tmp_path)
    st = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    assert list_part_versions(st, "lookdev") == ["v001", "v002"]
    assert list_part_versions(st, "groom") == ["v001"] and list_part_versions(st, "cloth") == []


def test_asset_thumbnail_like_monos(tmp_path):
    import os
    import time

    from tools.fx.anim_loader.logic import asset_thumbnail

    a = tmp_path / "char_Helen"
    (a / ".meta").mkdir(parents=True)
    assert asset_thumbnail(a) is None
    (a / ".meta/thumb_uv.user.png").write_bytes(b"x")
    time.sleep(0.01)
    (a / ".meta/thumb_rig.user.png").write_bytes(b"x")
    os.utime(a / ".meta/thumb_uv.user.png", (1, 1))
    assert asset_thumbnail(a) == a / ".meta/thumb_rig.user.png"  # newest department picture
    (a / ".meta/thumb_lookdev.user.png").write_bytes(b"x")
    os.utime(a / ".meta/thumb_lookdev.user.png", (1, 1))
    assert asset_thumbnail(a) == a / ".meta/thumb_lookdev.user.png"  # lookdev before other departments
    (a / "thumbnail.user.png").write_bytes(b"x")
    assert asset_thumbnail(a) == a / "thumbnail.user.png"  # the picture Monos shows


def test_missing_only_when_the_version_on_the_node_is_gone(tmp_path):
    import shutil

    root = _shot(tmp_path)
    st = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    shutil.rmtree(root / ROBOT / "05_lookdev/publish/v002")
    assert status(st)["lookdev"] == (STATUS_MISSING, None)  # v002 named on the node, gone from disk


# --- subdivision: shot rule > lookdev > anim > none (the user's decision, 2026-11-17) ---------------

from tools.fx.anim_loader.logic import SUBD_CATMULL, SUBD_NONE, SubdChoice, parse_subd_rules, subd_plan, subd_polygons  # noqa: E402

MESHES = ["/Geo/Base_grp/Body_grp/Geo_Body", "/Geo/Base_grp/Head_grp/Geo_Head",
          "/Geo/Outfit_grp/Costume_grp/Geo_Dress", "/Geo/Groom_grp/HairDriver_grp/Geo_HairBase"]


def test_subd_nobody_says_none():
    plan = subd_plan(MESHES, lookdev={}, anim={}, rules=[])
    assert all(c == SubdChoice(SUBD_NONE, "default", None) for c in plan.values())


def test_subd_lookdev_beats_anim():
    plan = subd_plan(MESHES, lookdev={MESHES[0]: "catmullClark"}, anim={MESHES[0]: "none", MESHES[1]: "catmullClark"},
                     rules=[])
    assert plan[MESHES[0]] == SubdChoice(SUBD_CATMULL, "lookdev", None)
    assert plan[MESHES[1]] == SubdChoice(SUBD_CATMULL, "publish", None)
    assert plan[MESHES[2]].source == "default"


def test_subd_shot_rules_later_wins_and_publish_keeps():
    rules = [{"pattern": "Geo/**", "scheme": "none"},
             {"pattern": "Geo/Base_grp/**", "scheme": "catmullClark", "dicing": 0.5},
             {"pattern": "Geo/Base_grp/Head_grp/Geo_Head", "scheme": "publish"}]
    plan = subd_plan(MESHES, lookdev={MESHES[1]: "none"}, anim={}, rules=rules)
    assert plan[MESHES[0]] == SubdChoice(SUBD_CATMULL, "shot", 0.5)
    assert plan[MESHES[1]] == SubdChoice(SUBD_NONE, "lookdev", 0.5)  # "publish": scheme from below, dicing stays
    assert plan[MESHES[2]] == SubdChoice(SUBD_NONE, "shot", None)


def test_subd_single_star_stays_in_one_level():
    plan = subd_plan(MESHES, lookdev={}, anim={}, rules=[{"pattern": "Geo/*", "scheme": "catmullClark"}])
    assert plan[MESHES[0]].source == "default"


def test_parse_subd_rules_drops_bad_entries():
    good = '[{"pattern": "Geo/**", "scheme": "catmullClark", "dicing": 2}]'
    assert parse_subd_rules(good) == [{"pattern": "Geo/**", "scheme": "catmullClark", "dicing": 2.0}]
    assert parse_subd_rules("") == [] and parse_subd_rules("not json") == []
    assert parse_subd_rules('[{"pattern": "Geo/**", "scheme": "loopy"}, {"scheme": "none"}]') == []


def test_subd_polygons_counts_catmull_only():
    plan = subd_plan(MESHES[:2], lookdev={MESHES[0]: "catmullClark"}, anim={}, rules=[])
    assert subd_polygons({MESHES[0]: 1000, MESHES[1]: 5000}, plan, level=2) == 16000


def test_heavy_shot_message():
    from tools.fx.anim_loader.logic import heavy_shot_message

    assert heavy_shot_message([("char_Helen", 9_900_000), ("veh_Spaceship", 0)], threshold=5_000_000) == \
        "Heavy shot: ~9.9 M subdivision polygons (char_Helen)"
    assert heavy_shot_message([("a", 3_000_000), ("b", 2_500_000), ("c", 1_000_000), ("d", 900_000)],
                              threshold=5_000_000) == "Heavy shot: ~7.4 M subdivision polygons (a, b, c, +1)"
    assert heavy_shot_message([("a", 4_000_000)], threshold=5_000_000) is None


def test_set_subd_rules_replaces_same_pattern_and_appends():
    from tools.fx.anim_loader.logic import clear_subd_rules, mesh_groups, set_subd_rules

    r = set_subd_rules([], ["Geo/Base_grp/**"], "none")
    r = set_subd_rules(r, ["Geo/Groom_grp/HairDriver_grp/Geo_HairBack"], "catmullClark", dicing=0.5)
    r = set_subd_rules(r, ["Geo/Base_grp/**"], "catmullClark")
    assert r == [{"pattern": "Geo/Groom_grp/HairDriver_grp/Geo_HairBack", "scheme": "catmullClark", "dicing": 0.5},
                 {"pattern": "Geo/Base_grp/**", "scheme": "catmullClark"}]
    assert set_subd_rules(r, ["Geo/Base_grp/**"], "publish") == r[:1]  # publish, no dicing: the override is dropped
    assert clear_subd_rules(r, ["Geo/Base_grp/**"]) == r[:1] and clear_subd_rules(r, None) == []
    assert mesh_groups(["/Geo/Base_grp/Body_grp/Geo_Body", "/Geo/Base_grp/Head_grp/Geo_Head", "/Geo/Groom_grp/x",
                        "/Other"]) == {"Geo/Base_grp": ["/Geo/Base_grp/Body_grp/Geo_Body", "/Geo/Base_grp/Head_grp/Geo_Head"],
                                       "Geo/Groom_grp": ["/Geo/Groom_grp/x"], "Other": ["/Other"]}


def test_set_subd_rules_keeps_the_other_field():
    from tools.fx.anim_loader.logic import KEEP, set_subd_rules

    r = set_subd_rules([], ["Geo/Base_grp/**"], "none", dicing=0.5)
    r = set_subd_rules(r, ["Geo/Base_grp/**"], "catmullClark")            # scheme only: dicing stays
    assert r == [{"pattern": "Geo/Base_grp/**", "scheme": "catmullClark", "dicing": 0.5}]
    r = set_subd_rules(r, ["Geo/Base_grp/**"], None, dicing=2.0)           # dicing only: scheme stays
    assert r == [{"pattern": "Geo/Base_grp/**", "scheme": "catmullClark", "dicing": 2.0}]
    r = set_subd_rules(r, ["Geo/Base_grp/**"], None, dicing=None)          # dicing cleared
    assert r == [{"pattern": "Geo/Base_grp/**", "scheme": "catmullClark"}]
    assert set_subd_rules([], ["Geo/x"], None, dicing=1.0) == [{"pattern": "Geo/x", "scheme": "publish", "dicing": 1.0}]
    assert KEEP is not None
