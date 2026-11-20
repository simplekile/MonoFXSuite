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


# --- Retarget to this shot -------------------------------------------------------------------------

def test_retarget_moves_to_the_newest_version_of_the_other_shot(tmp_path):
    from tools.fx.anim_loader.logic import retarget_state

    root = _shot(tmp_path)
    sh2 = "02_shots/sh920"
    make(root, [f"{sh2}/01_anim/publish/v001/geo_char_Robot.usd", f"{sh2}/01_anim/publish/v003/geo_char_Robot.usd",
                f"{sh2}/01_anim/publish/v004/cam_sh920.usd", f"{sh2}/01_anim/publish/v003/cam_sh920.usd"]
         + frames(f"{sh2}/02_fx/groom/publish/v002/char_Robot", "sh920_groom", (1, 2)))
    robot = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    robot = replace(robot, versions={**robot.versions, "lookdev": "v001"}, enabled={**robot.enabled, "cloth": False})
    new, note = retarget_state(robot, "sh920")
    assert note == ""
    assert (new.shot, new.anim_version, new.anim_file, new.instance_name) == ("sh920", "v003", "geo_char_Robot.usd",
                                                                             "char_Robot")
    assert new.versions == {"lookdev": "v001", "groom": "v002", "cloth": ""}  # lookdev kept, groom from sh920
    assert new.enabled["cloth"] is False                                       # node settings kept
    cam = initial_state(root, "sh900", "v001", Output("cam_sh900.usd", "cam"))
    new, _ = retarget_state(cam, "sh920")
    assert (new.anim_version, new.anim_file, new.instance_name) == ("v004", "cam_sh920.usd", "sh920")


def test_retarget_says_what_the_other_shot_lacks(tmp_path):
    from tools.fx.anim_loader.logic import retarget_state

    root = _shot(tmp_path)
    make(root, ["02_shots/sh920/01_anim/publish/v001/cam_sh920.usd"])
    robot = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    new, note = retarget_state(robot, "sh920")
    assert new is None and note == "char_Robot is not in sh920"
    assert retarget_state(robot, "sh900") == (robot, "")  # same shot: nothing to do


# --- Project box ----------------------------------------------------------------------------------------

def test_list_shots_only_with_an_anim_publish(tmp_path):
    from tools.fx.anim_loader.logic import list_shots

    root = make(tmp_path, ["02_shots/sh010/01_anim/publish/v001/cam_sh010.usd", "02_shots/SH002a/01_anim/publish/",
                           "02_shots/sh003/02_fx/", "02_shots/notes.txt"])
    assert list_shots(root) == ["SH002a", "sh010"]
    assert list_shots(tmp_path / "missing") == []


def test_remember_project_puts_it_first_once():
    from tools.fx.anim_loader.logic import remember_project

    recent = ["D:/a", "D:/b"]
    assert remember_project(recent, "d:/B/") == ["d:/B/", "D:/a"]
    assert remember_project(recent, "") == recent
    assert len(remember_project([f"D:/p{i}" for i in range(8)], "D:/new")) == 8

# --- parm pane: status in the version menus, the node comment, problems only in mx_status ------------

from tools.fx.anim_loader.logic import status_comment, status_problems, version_choices, version_menu  # noqa: E402


def test_version_menu_labels():
    assert version_menu(["v001", "v002", "v003"], "v002", ["v001", "v002", "v003"]) == [
        ("v001", "v001"), ("v002", "v002  (v003 available)"), ("v003", "v003  newest")]
    assert version_menu(["v001", "v002"], "v002", ["v001", "v002"])[-1] == ("v002", "v002  latest")
    # the version on the node is gone: still listed, so the field is not blank
    assert version_menu(["v001", "v003"], "v002", ["v001", "v003"])[1] == ("v002", "v002  (v003 available)")
    assert version_menu(["v001"], "v002", ["v001"]) == [("v001", "v001  newest"), ("v002", "v002  missing")]
    # nothing known about the instance (asset?): plain names
    assert version_menu(["v001", "v002"], "v001", []) == [("v001", "v001"), ("v002", "v002")]


def test_version_choices_follow_the_disk(tmp_path):
    root = _shot(tmp_path)
    st = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    assert version_choices(st, "lookdev") == [("v001", "v001"), ("v002", "v002  latest")]
    make(root, [f"{ANIM}/v002/geo_char_Robot.usd"])
    assert version_choices(st, "anim") == [("v001", "v001  (v002 available)"), ("v002", "v002  newest")]
    assert version_choices(replace(st, asset=None), "lookdev") == []


def test_comment_and_problems():
    st = {"anim": (STATUS_OK, None), "lookdev": (STATUS_NEWER, "v003"), "groom": (STATUS_MISSING, None),
          "cloth": (STATUS_NONE, None)}
    assert status_comment(st) == "lookdev v003 available, groom missing"
    assert status_problems(st, {"groom": "v002"}) == ["groom v002 missing on disk"]
    ok = {"anim": (STATUS_OK, None), "lookdev": (STATUS_OFF, None)}
    assert status_comment(ok) == "up to date" and status_problems(ok, {}) == []
    unknown = {"anim": (STATUS_OK, None), "lookdev": (STATUS_ASSET, None), "groom": (STATUS_ASSET, None)}
    assert status_comment(unknown) == "asset?" and len(status_problems(unknown, {})) == 1


# --- parm pane guidance: shot change, next step, shot menu -------------------------------------------------

def test_switch_shot_moves_the_same_instance_else_newest_version_and_no_file(tmp_path):
    from tools.fx.anim_loader.logic import switch_shot

    root = _shot(tmp_path)
    make(root, ["02_shots/sh920/01_anim/publish/v001/geo_char_Robot.usd",
                "02_shots/sh920/01_anim/publish/v002/geo_char_Robot.usd",
                "02_shots/sh930/01_anim/publish/v004/cam_sh930.usd",
                "02_shots/sh940/01_anim/publish/"])
    robot = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    moved = switch_shot(replace(robot, shot=""), "sh920")             # old shot unknown: still moves
    assert (moved.shot, moved.anim_version, moved.anim_file) == ("sh920", "v002", "geo_char_Robot.usd")
    other = switch_shot(robot, "sh930")                                 # no robot there
    assert (other.shot, other.anim_version, other.anim_file, other.asset) == ("sh930", "v004", "", None)
    assert set(other.versions.values()) == {""}
    empty = switch_shot(robot, "sh940")                                 # no anim publish at all
    assert (empty.anim_version, empty.anim_file) == ("", "")
    assert switch_shot(robot, "sh900") == robot


def test_next_step_says_one_thing(tmp_path):
    from tools.fx.anim_loader.logic import NO_PROJECT, next_step

    root = _shot(tmp_path)
    make(root, ["02_shots/sh940/01_anim/publish/"])
    robot = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    assert next_step(robot) == ("", "")
    assert next_step(replace(robot, project_root="")) == (NO_PROJECT, "no project")
    assert next_step(replace(robot, project_root=str(tmp_path / "nowhere")))[1] == "no project"
    assert next_step(replace(robot, shot="")) == ("Pick a shot.", "pick a shot")
    assert next_step(replace(robot, shot="sh999"))[1] == "no shot sh999"
    assert next_step(replace(robot, shot="sh940"))[0] == "sh940 has no anim publish yet: pick another shot."
    assert next_step(replace(robot, anim_version=""))[1] == "pick an anim version"
    assert next_step(replace(robot, anim_file="")) == ("Pick an anim file.", "pick an anim file")


def test_shot_menu_marks_shots_without_anim(tmp_path):
    from tools.fx.anim_loader.logic import shot_menu

    root = _shot(tmp_path)
    make(root, ["02_shots/sh940/01_anim/publish/"])
    assert shot_menu(str(root), "sh900") == [("sh900", "sh900"), ("sh940", "sh940  (no anim)")]
    assert ("sh777", "sh777  (no anim)") in shot_menu(str(root), "sh777")  # the node's shot stays listed
    assert shot_menu("", "") == []


# --- Source Asset (docs/plans/anim_loader_asset_source.md) ------------------------------------------------

UV = f"{ROBOT}/01_modelling/03_uv/publish"
GRM = f"{ROBOT}/04_grooming/publish"


def _asset(tmp_path):
    root = _shot(tmp_path)
    make(root, [f"{UV}/v001/char_Robot_uv_publish.usd", f"{UV}/v002/char_Robot_uv_publish.usd",
                f"{UV}/v002/char_Robot_uv_publish_Body.usd", f"{UV}/v003/a.usd", f"{UV}/v003/b.usd",
                f"{GRM}/v001/char_Robot_groom_publish.usd", f"{GRM}/v002/char_Robot_groom_publish.usd"])
    return root


def test_asset_source_picks_newest_model_standard_file_groom_and_lookdev(tmp_path):
    from tools.fx.anim_loader.logic import initial_asset_state, next_step

    root = _asset(tmp_path)
    st = initial_asset_state(root, "char_Robot")
    # v003 has two files and no standard name: not a version of the standard model
    assert (st.source, st.model_version, st.model_file, st.instance_name) == ("asset", "v002",
                                                                            "char_Robot_uv_publish.usd", "char_Robot")
    assert st.versions == {"lookdev": "v002", "groom": "v002", "cloth": ""}
    r = resolve(st)
    assert r.anim.endswith("03_uv/publish/v002/char_Robot_uv_publish.usd")
    assert r.groom.endswith("04_grooming/publish/v002/char_Robot_groom_publish.usd") and r.cloth == ""
    assert next_step(st) == ("", "")
    assert status(st)["cloth"][0] == "off"


def test_asset_source_model_files_and_steps(tmp_path):
    from tools.fx.anim_loader.logic import initial_asset_state, model_file_choices, next_step, pick_file

    root = _asset(tmp_path)
    st = initial_asset_state(root, "char_Robot")
    assert model_file_choices(st) == [("char_Robot_uv_publish.usd", "char_Robot_uv_publish.usd  (standard)"),
                                      ("char_Robot_uv_publish_Body.usd", "char_Robot_uv_publish_Body.usd")]
    v3 = replace(st, model_version="v003", model_file="")
    assert next_step(v3) == ("Pick a model file.", "pick a model file")
    assert pick_file(["a.usd", "b.usd"], "char_Robot", "uv") == ""
    assert pick_file(["only.usd"], "char_Robot", "uv") == "only.usd"
    assert pick_file(["x.usd", "char_Robot_uv_publish.usda"], "char_Robot", "uv", "x.usd") == "x.usd"
    assert next_step(replace(st, asset=None))[0] == "Pick an asset."
    assert next_step(replace(st, asset="char_Nobody"))[1] == "no asset char_Nobody"
    make(root, ["01_assets/_props/prop_Rock/05_lookdev/"])
    assert next_step(replace(st, asset="prop_Rock"))[0] == "prop_Rock has no UV or lookdev publish yet."


def test_asset_source_keeps_shot_fields_and_lookdev(tmp_path):
    from tools.fx.anim_loader.logic import initial_asset_state

    root = _asset(tmp_path)
    shot = replace(initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo")),
                   versions={"lookdev": "v001", "groom": "v001", "cloth": ""})
    st = initial_asset_state(root, "char_Robot", shot)
    assert (st.shot, st.anim_version, st.anim_file) == ("sh900", "v001", "geo_char_Robot.usd")  # kept for Shot
    assert st.versions["lookdev"] == "v001"                                                      # same asset: kept
    assert st.versions["groom"] == "v002"                                                        # the asset's groom


def test_newer_model_is_reported(tmp_path):
    from tools.fx.anim_loader.logic import initial_asset_state, version_choices

    root = _asset(tmp_path)
    st = replace(initial_asset_state(root, "char_Robot"), model_version="v001")
    assert status(st)["anim"] == ("newer", "v002")
    assert ("v001", "v001  (v002 available)") in version_choices(st, "anim")


def test_detect_asset_from_a_scene_path(tmp_path):
    from tools.fx.anim_loader.logic import detect_asset

    root = _asset(tmp_path)
    hip = root / ROBOT / "04_grooming/houdini/work/char_Robot_grooming_v008.hiplc"
    assert detect_asset(root, hip) == "char_Robot"
    assert detect_asset(root, root / "02_shots/sh900/work/a.hip") is None


def test_groom_targets_outside_geo():
    from tools.fx.anim_loader.logic import groom_targets

    assert groom_targets(["/Geo/Groom_grp/Hair_grp/hair", "/Groom/Eyelash", "/Geo/A/hair"]) == [
        ("/Geo/Groom_grp/Hair_grp/hair", "/Groom/hair"), ("/Groom/Eyelash", "/Groom/Eyelash"),
        ("/Geo/A/hair", "/Groom/A_hair")]


def test_character_loader_3_2_becomes_source_asset(tmp_path):
    from tools.fx.anim_loader.logic import from_character_loader

    root = _asset(tmp_path)
    values = {"folder_path": str(root / "01_assets/_characters"), "Model_List": "char_Robot", "Version_List": "v001",
              "File_List": "char_Robot_uv_publish.usd", "Enable_Groom": "off", "Version_Groom_List": "v001",
              "Version_Lookdev_List": "v001", "enableScale": "on", "scale": "2.5", "Enable_Prune": "on",
              "primpattern1": "*HairDriver*", "EnableModify": "on"}
    st, extra, why = from_character_loader(values)
    assert why == "" and (st.source, st.asset, st.instance_name, st.model_version, st.model_file) == (
        "asset", "char_Robot", "char_Robot", "v001", "char_Robot_uv_publish.usd")
    assert st.versions == {"lookdev": "v001", "groom": "v001", "cloth": ""} and st.enabled["groom"] is False
    assert extra == {"scale": 2.5, "mx_hide_enable": 1, "mx_hide_pattern": "**/*HairDriver*"}
    st, _, _ = from_character_loader({**values, "Version_List": "select version", "Version_Lookdev_List": ""})
    assert (st.model_version, st.versions["lookdev"]) == ("v002", "v002")  # nothing picked: newest, once
    assert from_character_loader({"folder_path": "", "Model_List": ""})[0] is None


def test_asset_menu_by_group_and_with_a_model(tmp_path):
    from tools.fx.anim_loader.logic import asset_group_of, asset_groups, asset_menu, group_label

    root = _asset(tmp_path)
    make(root, ["01_assets/_props/prop_Rock/01_modelling/03_uv/publish/v001/prop_Rock_uv_publish.usdc",
                "01_assets/_props/prop_Empty/05_lookdev/"])
    assert asset_groups(root) == ["_characters", "_props"] and group_label("_characters") == "Characters"
    assert [a for a, _ in asset_menu(str(root), "_props", "", True)] == ["prop_Rock"]         # with a model only
    assert [a for a, _ in asset_menu(str(root), "_props", "", False)] == ["prop_Empty", "prop_Rock"]
    assert [a for a, _ in asset_menu(str(root), "", "", True)] == ["char_Robot", "prop_Rock"]  # all groups
    assert asset_menu(str(root), "_props", "char_Robot", True)[0] == ("char_Robot", "char_Robot")  # current kept
    assert asset_group_of(str(root), "prop_Rock") == "_props"


def test_a_part_with_nothing_published_says_so(tmp_path):
    from tools.fx.anim_loader.logic import initial_asset_state, version_choices

    root = _asset(tmp_path)
    make(root, ["01_assets/_props/prop_Rock/01_modelling/03_uv/publish/v001/prop_Rock_uv_publish.usdc"])
    st = initial_asset_state(root, "prop_Rock")
    assert version_choices(st, "groom") == [("", "none published")]


def test_outdated_lists_newer_parts_only():
    from tools.fx.anim_loader import logic

    st = logic.LoaderState("P", "sh025", "v005", "a.usd", "char_Helen", "char_Helen", "geo", {}, {})
    status = {"anim": (logic.STATUS_NEWER, "v006"), "lookdev": (logic.STATUS_OK, None),
              "groom": (logic.STATUS_OFF, None), "cloth": (logic.STATUS_MISSING, None)}
    items = logic.outdated([("char_Helen", st, status), ("cam", st, {"anim": (logic.STATUS_OK, None)})])
    assert items == [("char_Helen", [("anim", "v005", "v006")])]
    assert logic.outdated_lines(items) == ["char_Helen: anim v005 \u2192 v006"]
    assert logic.outdated_signature(items) == "char_Helen:anim:v006"
    assert not logic.outdated_shows([], "")


def test_part_folders_open_each_column(tmp_path):
    """The manager's column menu and the node's Open Folder strip (the user's ask, 2026-11-20): the folder of the
    version on the node, the part's publish folder when that version is gone; cloth never published: none."""
    from dataclasses import replace

    from tools.fx.anim_loader.logic import initial_asset_state, part_folders, part_word

    root = _shot(tmp_path)
    st = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    f = part_folders(st)
    assert list(f) == ["anim", "lookdev", "groom"]
    assert f["anim"] == (root / ANIM / "v001").as_posix()
    assert f["lookdev"].endswith("char_Robot/05_lookdev/publish/v002")
    assert f["groom"] == (root / GROOM / "v001/char_Robot").as_posix()
    gone = replace(st, anim_version="v009", versions={**st.versions, "lookdev": "v007"})
    assert part_folders(gone)["anim"] == (root / ANIM).as_posix()          # the version is gone: its publish folder
    assert part_folders(gone)["lookdev"].endswith("05_lookdev/publish")
    cam = initial_state(root, "sh900", "v001", Output("cam_sh900.usd", "cam"))
    assert list(part_folders(cam)) == ["anim"]
    assert part_word(st, "anim") == "Anim" and part_word(st, "lookdev") == "Lookdev"
    asset = initial_asset_state(_asset(tmp_path / "a"), "char_Robot")
    fa = part_folders(asset)
    assert fa["anim"].endswith("01_modelling/03_uv/publish/v002") and fa["groom"].endswith("04_grooming/publish/v002")
    assert "cloth" not in fa and part_word(asset, "anim") == "Model"


def test_add_places_a_column_clear_of_other_nodes():
    """Add's nodes beside the selected node or mid-view (the user's pick, 2026-11-20), never on top of a node."""
    from tools.fx.anim_loader.logic import NODE_CLEAR, NODE_STEP_Y, free_spots

    assert free_spots((0.0, 0.0), 2, []) == [(0.0, 0.0), (0.0, -NODE_STEP_Y)]
    spots = free_spots((0.0, 0.0), 2, [(-0.5, -1.0)])                 # the second spot would sit on a node
    assert spots == [(NODE_CLEAR[0], 0.0), (NODE_CLEAR[0], -NODE_STEP_Y)]
    assert free_spots((0.0, 0.0), 1, [(5.0, 0.0)]) == [(0.0, 0.0)]    # far enough: stays
