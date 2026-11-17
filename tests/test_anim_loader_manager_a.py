"""Manager layout A (the user's pick, 2026-11-17): what is new, shot gaps, the Add drawer's catalog, Monos links."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

from tests.anim_loader_tree import make
from tools.fx.anim_loader.logic import (
    Output,
    asset_catalog,
    initial_asset_state,
    initial_state,
    mesh_change_lines,
    monos_link,
    shot_gaps,
    whats_new,
    work_author,
)

ROBOT = "01_assets/_characters/char_Robot"
ANIM = "02_shots/sh900/01_anim/publish"
UV = f"{ROBOT}/01_modelling/03_uv/publish"


def _tree(tmp_path):
    meta1 = {"fps": 24, "playback_range": [1, 48], "outputs": [{"file": "geo_char_Robot.usd", "type": "geo"}]}
    meta2 = {"fps": 24, "playback_range": [1, 60], "outputs": [{"file": "geo_char_Robot.usd", "type": "geo"},
                                                                {"file": "geo_char_Ata.usd", "type": "geo"}]}
    root = make(tmp_path, [f"{ANIM}/v001/geo_char_Robot.usd", f"{ANIM}/v002/geo_char_Robot.usd",
                           f"{ANIM}/v002/geo_char_Ata.usd", f"{UV}/v001/char_Robot_uv_publish.usd",
                           f"{UV}/v002/char_Robot_uv_publish.usd",
                           f"{ROBOT}/05_lookdev/publish/v001/char_Robot_lookdev_publish.usd",
                           "01_assets/_characters/char_Ata/05_lookdev/",
                           "01_assets/_props/prop_Rock/01_modelling/03_uv/publish/v001/prop_Rock_uv_publish.usdc"],
                {f"{ANIM}/v001": meta1, f"{ANIM}/v002": meta2})
    (root / f"{ANIM}/v002/geo_char_Robot.usd").write_bytes(b"x" * 2_000_000)
    monos = root / ROBOT / ".monos"
    monos.mkdir(parents=True)
    (monos / "authors.json").write_text(json.dumps({"files": {
        "01_modelling/03_uv/blender/work/char_Robot_uv_v002.blend": {"name": "Linh", "at": "2026-11-16T10:00:00Z"},
        "01_modelling/03_uv/blender/work/char_Robot_uv_v001.blend": {"name": "An", "at": "2026-11-01T10:00:00Z"},
        "05_lookdev/houdini/work/char_Robot_lookdev_v002.hiplc": {"name": "Mai", "at": "2026-11-15T10:00:00Z"}}}))
    return root


def test_whats_new_anim_lists_outputs_frames_and_size(tmp_path):
    root = _tree(tmp_path)
    st = initial_state(root, "sh900", "v001", Output("geo_char_Robot.usd", "geo"))
    st = replace(st, anim_version="v001")
    w = whats_new(st, "anim")
    assert (w.part, w.old, w.new) == ("anim", "v001", "v002")
    assert "+ geo_char_Ata.usd" in w.lines and "Frames 1-48 -> 1-60" in w.lines
    assert any(line.endswith("-> 2.0 MB") for line in w.lines)
    assert w.new_path.endswith("v002/geo_char_Robot.usd") and w.date
    assert whats_new(replace(st, anim_version="v002"), "anim") is None  # nothing newer


def test_whats_new_model_names_the_work_file_author(tmp_path):
    root = _tree(tmp_path)
    st = replace(initial_asset_state(root, "char_Robot"), model_version="v001")
    w = whats_new(st, "anim")
    assert (w.part, w.new, w.author) == ("model", "v002", "Linh")


def test_work_author_matches_department_and_version(tmp_path):
    root = _tree(tmp_path)
    assert work_author(root / ROBOT, "05_lookdev", "v002") == ("Mai", "2026-11-15T10:00:00Z")
    assert work_author(root / ROBOT, "05_lookdev", "v009") is None
    assert work_author(root / "nowhere", "05_lookdev", "v002") is None


def test_mesh_change_lines():
    assert mesh_change_lines(["/Geo/a"], ["/Geo/a", "/Geo/Fin_L", "/Geo/Fin_R"]) == ["+ 2 meshes: Fin_L, Fin_R"]
    assert mesh_change_lines(["/Geo/a", "/Geo/Tail"], ["/Geo/a"]) == ["- 1 mesh: Tail"]
    assert mesh_change_lines(["/a"], ["/a"]) == []


def test_shot_gaps_are_the_newest_outputs_without_a_loader(tmp_path):
    root = _tree(tmp_path)
    version, missing = shot_gaps(str(root), "sh900", {"geo_char_Robot.usd"})
    assert version == "v002" and [o.file for o in missing] == ["geo_char_Ata.usd"]
    assert shot_gaps(str(root), "sh999", set()) == ("", [])


def test_catalog_filters_group_search_and_model(tmp_path):
    root = _tree(tmp_path)
    assert [i.name for i in asset_catalog(str(root))] == ["char_Robot", "prop_Rock"]          # with a model only
    assert [i.name for i in asset_catalog(str(root), with_model=False)] == ["char_Ata", "char_Robot", "prop_Rock"]
    assert [i.name for i in asset_catalog(str(root), "_props")] == ["prop_Rock"]
    assert [i.name for i in asset_catalog(str(root), search="ROB")] == ["char_Robot"]
    robot = asset_catalog(str(root))[0]
    assert (robot.group, robot.model, robot.lookdev) == ("_characters", "v002", "v001")


def test_monos_link_matches_monos_deep_link(tmp_path):
    root = _tree(tmp_path)
    link = monos_link(root, root / ROBOT)
    short = hashlib.sha256(ROBOT.encode()).hexdigest()[:10]
    assert link == f"monos://open?project={root.name}&page=assets&e={short}"
    assert monos_link(root, Path(os.sep) / "elsewhere") == ""
