"""A loader with a lookdev keeps the anim's frames whatever fps the lookdev says (or does not say).

hython tests/houdini/anim_loader/accept_branch_fps.py <fake_project> <out_dir>

The branch's Sublayer LOP took its time codes per second from its strongest layer, the lookdev. veh_Spaceship's
lookdev V001 authors none, so the branch read USD's fallback 24 and sh002 v004's 30 fps anim came out on 0-24. The
fake project's anim is 24 fps and its lookdev 30 (stretched to 1.25x before the fix); this also checks a lookdev
with no fps at all, with the anim at 30.
"""

from __future__ import annotations

import glob
import json
import shutil
import sys
import traceback
from pathlib import Path

SUITE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(SUITE), str(SUITE / "packages/monofx_pipeline_common/src")]

import hou  # noqa: E402
from pxr import Sdf, Usd, UsdGeom  # noqa: E402

from apps.houdini import anim_loader_adapter as ad  # noqa: E402
from tools.fx.anim_loader import config  # noqa: E402

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
BODY = "Geo/Base_grp/Body_grp/Geo_Body"
CHECKS: list[dict] = []


def check(name, ok, detail=None):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name, "" if detail is None else detail, flush=True)


def copy_project(name: str) -> Path:
    root = OUT / name
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(SRC, root)
    return root


def retime(path: str, fps: float | None) -> None:
    """Set (or clear, None) a file's time codes / frames per second, its samples left at the same time codes."""
    layer = Sdf.Layer.FindOrOpen(path)
    if fps is None:
        layer.ClearTimeCodesPerSecond()
        layer.ClearFramesPerSecond()
    else:
        layer.timeCodesPerSecond = fps
        layer.framesPerSecond = fps
    layer.Save()


def body_times(node) -> list[float]:
    stage = node.stage()
    prim = next((p for p in stage.Traverse() if p.GetPath().pathString.endswith(BODY)
                 and "/char_Robot/" in p.GetPath().pathString), None)
    return list(UsdGeom.Mesh(prim).GetPointsAttr().GetTimeSamples()) if prim else []


def file_times(path: str) -> list[float]:
    stage = Usd.Stage.Open(path)
    return list(UsdGeom.Mesh(stage.GetPrimAtPath("/" + BODY)).GetPointsAttr().GetTimeSamples())


def case(label: str, root: Path) -> None:
    hou.hipFile.clear(suppress_save_prompt=True)
    for name in (config.HDA_FILE, config.OLD_FILE):  # this checkout's loader, not an installed one
        hou.hda.installFile(str(SUITE / "otls" / name))
        for d in hou.hda.definitionsInFile(str(SUITE / "otls" / name)):
            d.setIsPreferred(True)
    net = hou.node("/stage")
    ad.load_shot(net, str(root), "sh900", "v002")
    robot = next(n for n in ad.find_loaders() if n.evalParm(config.P_GEO_CAM) == 0
                 and n.evalParm(config.P_INSTANCE) == "char_Robot")
    anim = str(root / "02_shots/sh900/01_anim/publish/v002/geo_char_Robot.usd")
    want = file_times(anim)
    check(f"{label}: the loader has a lookdev", bool(robot.evalParm(config.P_LAYERS[0])), robot.evalParm(config.P_LAYERS[0]))
    got = body_times(robot)
    check(f"{label}: the anim keeps its frames at the loader", got == want, (got[:2], got[-1:], want[:2], want[-1:]))
    merge = net.createNode("merge", "actors")
    merge.setInput(0, robot)
    graft = net.createNode("graftstages", "graft_anim")
    graft.setInput(1, merge)
    after = body_times(graft)
    check(f"{label}: the same after a Merge and a Graft", after == want, (after[:2], after[-1:]))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    looks = "01_assets/*/char_Robot/05_lookdev/publish/*/char_Robot_lookdev_publish.usd"
    # as made: anim 24, lookdev 30
    case("lookdev 30, anim 24", copy_project("look30_anim24"))
    # as veh_Spaceship V001: the lookdev says no fps, the anim 30
    root = copy_project("look_none_anim30")
    for look in glob.glob(str(root / looks)):
        retime(look, None)
    for anim in glob.glob(str(root / "02_shots/sh900/01_anim/publish/*/*.usd")):
        retime(anim, 30.0)
    case("lookdev without fps, anim 30", root)


try:
    main()
except Exception:
    check("no exception", False, traceback.format_exc())
(OUT / "accept_branch_fps.json").write_text(json.dumps(CHECKS, indent=1, default=str), encoding="utf-8")
failed = [c["name"] for c in CHECKS if not c["ok"]]
print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed", failed)
sys.exit(1 if failed else 0)
