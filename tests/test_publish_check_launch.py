"""Test in Houdini (Blender add-on): finding Houdini, the command line, the publishes offered (no bpy), and the
Houdini side's plan and check line (no hou, no pxr). The scene itself: hython
tests/houdini/anim_loader/accept_publish_preview.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tools.fx.anim_loader import publish_preview as pp

SUITE = Path(__file__).resolve().parents[1]
PKG = SUITE / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender"


def _mod():
    spec = importlib.util.spec_from_file_location("publish_check_launch", PKG / "publish_check_launch.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["publish_check_launch"] = mod  # dataclasses look the module up while the class is made
    spec.loader.exec_module(mod)
    return mod


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    return path


def test_newest_houdini_or_the_prefs_path(tmp_path):
    ht = _mod()
    pf = tmp_path / "pf"
    for v in ("21.0.440", "22.0.466", "22.0.12"):
        _touch(pf / "Side Effects Software" / f"Houdini {v}" / "bin" / "houdini.exe")
    (pf / "Side Effects Software" / "Houdini Engine").mkdir()
    (pf / "Side Effects Software" / "Houdini 23.0.1").mkdir()  # no exe: not an install
    assert ht.find_houdini("", str(pf)).parts[-3] == "Houdini 22.0.466"
    own = _touch(tmp_path / "hfs" / "bin" / "houdini.exe")
    assert ht.find_houdini(str(tmp_path / "hfs"), str(pf)) == own  # a folder holding bin/houdini.exe
    assert ht.find_houdini(f'"{own}"', str(pf)) == own
    assert ht.find_houdini(str(tmp_path / "nothing"), str(pf)).parts[-3] == "Houdini 22.0.466"
    assert ht.find_houdini("", str(tmp_path / "empty")) is None


def test_command_line_puts_the_publish_in_env(tmp_path):
    ht = _mod()
    argv, env = ht.launch_command(Path("C:/H/bin/houdini.exe"), PKG / ht.STARTUP_SCRIPT, "model",
                                  "E:/p/a.usd", base_env={"MONOFX_TEST_SUITE": "old", "KEEP": "1"})
    assert argv[1] == "-foreground" and argv[2].endswith("houdini_test_startup.py")
    assert env[ht.ENV_KIND] == "model" and Path(env[ht.ENV_PATH]) == Path("E:/p/a.usd")
    assert ht.ENV_SUITE not in env and env["KEEP"] == "1"
    try:
        ht.launch_command(Path("h"), Path("s"), "rig", "x")
    except ValueError:
        pass
    else:
        raise AssertionError("rig is not a kind")
    assert (PKG / ht.STARTUP_SCRIPT).is_file()
    assert ht.work_dir(str(tmp_path)) == tmp_path / "MonoFX" / "houdini_test"  # houdini by default


def test_publishes_offered_newest_first(tmp_path):
    ht = _mod()
    pub = tmp_path / "03_uv" / "publish"
    _touch(pub / "v001" / "char_A_uv_publish.usd")
    _touch(pub / "v003" / "char_A_uv_publish.usd")
    _touch(pub / "v003" / "char_A_uv_publish_Body.usd")
    _touch(pub / "v002" / "notes.txt")
    (pub / "old").mkdir()
    labels = [c.label for c in ht.model_publishes(pub)]
    assert labels == ["v003  char_A_uv_publish.usd", "v003  char_A_uv_publish_Body.usd", "v001  char_A_uv_publish.usd"]
    anim = tmp_path / "01_anim" / "publish"
    _touch(anim / "v001" / "geo_char_A.usd")
    _touch(anim / "v002" / "geo_char_A.usd")
    _touch(anim / "v002" / "geo_char_B.usd")
    _touch(anim / "v002" / "cam_sh010.usd")
    _touch(anim / "v002" / "publish_meta.json")
    choices = ht.anim_publishes(anim)
    assert [c.label for c in choices] == ["v002  (2 geo, 1 camera)", "v001  (1 geo)"]
    assert Path(choices[0].path) == anim / "v002"
    assert ht.model_publishes(None) == [] and ht.anim_publishes(tmp_path / "missing") == []
    assert Path(ht.anim_test_path(["", str(anim / "v002" / "geo_char_A.usd")])) == anim / "v002"


def test_plan_reads_the_publish_path(tmp_path):
    root = tmp_path / "proj"
    uv = _touch(root / "01_assets/_characters/char_A/01_modelling/03_uv/publish/v004/char_A_uv_publish.usd")
    pl = pp.plan("model", str(uv))
    assert (pl.mode, pl.asset, pl.model_version, pl.model_file) == ("asset", "char_A", "v004", "char_A_uv_publish.usd")
    assert pl.title == "char_A model v004" and Path(pl.root) == root
    retopo = _touch(root / "01_assets/_characters/char_A/01_modelling/02_retopo/publish/v001/char_A.usd")
    assert pp.plan("model", str(retopo)).mode == "sublayer"
    shot = root / "02_shots/sh010/01_anim/publish/v002"
    _touch(shot / "geo_char_A.usd")
    _touch(shot / "cam_sh010.usd")
    for path in (shot, shot / "geo_char_A.usd"):
        pl = pp.plan("anim", str(path))
        assert (pl.mode, pl.shot, pl.anim_version, len(pl.files)) == ("shot", "sh010", "v002", 2)
    asset_anim = _touch(root / "01_assets/_characters/char_A/06_anim/publish/v001/geo_char_A.usd")
    assert pp.plan("anim", str(asset_anim.parent)).mode == "sublayer"


def test_check_line():
    good = pp.FileFacts("char_A_uv_publish.usd", meshes=3, fps=24.0, kind="component", default_prim="/Geo")
    line, ok = pp.check_line("char_A model v004", "model", [good], pp.StageFacts(meshes=3))
    assert ok and line == "MonoFX test, char_A model v004: reads clean. 3 meshes, 24 fps, kind component."
    bad = pp.FileFacts("a.usd", meshes=2, no_scheme=["/Geo/x", "/Geo/y"], kind="", default_prim="/Geo")
    line, ok = pp.check_line("t", "model", [bad], pp.StageFacts(meshes=2, broken=["/A/x -> /A/_materials/M"],
                                                                node_errors=["char_A: file missing"]))
    assert not ok
    assert line.startswith("MonoFX test, t: 5 problems: char_A: file missing; 1 broken material binding")
    assert "+2 more" in line
    probs = pp.problems("model", [bad], pp.StageFacts(meshes=2))
    assert probs == ["2 meshes without subdivisionScheme (/Geo/x)", "a.usd has no fps",
                     "a.usd: default prim /Geo is kind (none), not component"]
    still = pp.FileFacts("geo_a.usd", meshes=1, fps=24.0)
    moving = pp.FileFacts("geo_b.usd", meshes=1, fps=25.0, animated=1)
    probs = pp.problems("anim", [still, moving], pp.StageFacts(meshes=2))
    assert probs == ["files disagree on fps (24, 25)", "geo_a.usd has no time samples"]
    cam = pp.FileFacts("cam_sh010.usd", fps=24.0, animated=1, camera=True)
    assert pp.problems("anim", [cam], pp.StageFacts()) == []  # a camera alone has no mesh, and that is fine
    note = pp.note_text("t", "model", [bad], pp.StageFacts(meshes=2), "plain Sublayer")
    assert "PROBLEM  2 meshes without subdivisionScheme" in note and "plain Sublayer" in note


def test_blender_command_and_work_dir(tmp_path):
    ht = _mod()
    script = ht.startup_script(PKG, "blender")
    assert script.name == "blender_test_startup.py" and script.is_file()
    argv, env = ht.launch_command(Path("C:/B/blender.exe"), script, "anim", "E:/p/v002", base_env={}, app="blender")
    assert argv[1:] == ["--python", str(script)]  # no --factory-startup: the artist's add-ons and prefs come along
    assert env[ht.ENV_KIND] == "anim" and Path(env[ht.ENV_PATH]) == Path("E:/p/v002")
    assert ht.work_dir(str(tmp_path), "blender") == tmp_path / "MonoFX" / "blender_test"
    try:
        ht.launch_command(Path("b"), script, "model", "x", app="maya")
    except ValueError:
        pass
    else:
        raise AssertionError("maya is not an app")


def test_checks_are_shared_with_blender():
    from monofx_pipeline_common import publish_checks as pc

    assert pp.check_line is pc.check_line and pp.FileFacts is pc.FileFacts
    note = pc.note_text("t", "model", [], pc.StageFacts(meshes=1), save_hint="Not saved.")
    assert note.endswith("Not saved.")
