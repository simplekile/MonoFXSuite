"""A groom cache with time samples keeps moving after a Graft Stages downstream (the shot layout's graft_anim).

hython tests/houdini/anim_loader/accept_groom_graft.py <fake_project> <out_dir>

The fake project's groom has no time samples (it loads as sublayers); this copies the project into <out_dir>, gives
each frame file its points and widths as a time sample at its frame (a real cache, loaded through value clips),
then checks the groom moves at the loader, after Merge LOPs and after a Graft Stages. Before the groom_topology
Python LOP took the copied frame's animated values off, the graft flattened them with the clip metadata into one
layer, where the first frame's samples won and the groom stood still.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import sys
import traceback
from pathlib import Path

SUITE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(SUITE), str(SUITE / "packages/monofx_pipeline_common/src")]

import hou  # noqa: E402
from pxr import Gf, Sdf, Usd, UsdGeom, Vt  # noqa: E402

from apps.houdini import anim_loader_adapter as ad  # noqa: E402
from tools.fx.anim_loader import config  # noqa: E402

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
CHECKS: list[dict] = []


def check(name, ok, detail=None):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name, "" if detail is None else detail, flush=True)


def time_sampled_copy() -> Path:
    root = OUT / "project"
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(SRC, root)
    for folder in glob.glob(str(root / "02_shots/sh900/02_fx/groom/publish/*/char_Robot")):
        for path in sorted(glob.glob(os.path.join(folder, "*.usd"))):
            frame = int(re.search(r"\.(\d+)\.usd$", path).group(1))
            stage = Usd.Stage.Open(path)
            for prim in stage.Traverse():
                if prim.IsA(UsdGeom.BasisCurves):
                    for name in ("points", "widths"):
                        attr = prim.GetAttribute(name)
                        if attr and attr.HasAuthoredValue() and not attr.GetNumTimeSamples():
                            value = attr.Get()
                            attr.Clear()
                            attr.Set(value, Usd.TimeCode(frame))
            stage.GetRootLayer().Export(path + ".tmp.usd")
            del stage
            os.replace(path + ".tmp.usd", path)
    # the lookdev holds its own animated values on the groom prim, as Helen's does: points (a time sample, other
    # values) and a primvar only it has; both used to win over the clips after a Merge
    for look in glob.glob(str(root / "01_assets/*/char_Robot/05_lookdev/publish/*/char_Robot_lookdev_publish.usd")):
        stage = Usd.Stage.Open(look)
        prim = stage.OverridePrim("/Groom/hair")
        prim.CreateAttribute("points", Sdf.ValueTypeNames.Point3fArray).Set(
            Vt.Vec3fArray([Gf.Vec3f(0, 999, 0)] * 4), Usd.TimeCode(1))
        prim.CreateAttribute("primvars:lookOnly", Sdf.ValueTypeNames.FloatArray).Set(Vt.FloatArray([0.5]),
                                                                                    Usd.TimeCode(1))
        stage.GetRootLayer().Export(look + ".tmp.usd")
        del stage
        os.replace(look + ".tmp.usd", look)
    return root


def groom_y(node, frames):
    out = []
    for f in frames:
        hou.setFrame(f)
        curves = [p for p in node.stage().Traverse()
                  if p.IsA(UsdGeom.BasisCurves) and "/char_Robot/" in p.GetPath().pathString]
        pts = UsdGeom.BasisCurves(curves[0]).GetPointsAttr().Get(Usd.TimeCode(f)) if curves else None
        out.append(round(float(pts[0][1]), 4) if pts else None)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in (config.HDA_FILE, config.OLD_FILE):  # this checkout's loader, not an installed one
        hou.hda.installFile(str(SUITE / "otls" / name))
        for d in hou.hda.definitionsInFile(str(SUITE / "otls" / name)):
            d.setIsPreferred(True)
    root = time_sampled_copy()
    net = hou.node("/stage")
    ad.load_shot(net, str(root), "sh900", "v002")
    loaders = [n for n in ad.find_loaders() if n.evalParm(config.P_GEO_CAM) == 0]
    robot = next(n for n in loaders if n.evalParm(config.P_INSTANCE) == "char_Robot")
    other = next(n for n in loaders if n is not robot)
    groom = config.P_FX["groom"]
    check("the cache loads through clips", robot.evalParm(groom["mode"]) == config.FX_MODE_CLIP,
          robot.evalParm(groom["mode"]))
    first, last = robot.evalParm(groom["first"]), robot.evalParm(groom["last"])
    frames = (first, (first + last) // 2, last)
    at_loader = groom_y(robot, frames)
    check("the groom moves at the loader", len(set(at_loader)) == 3, at_loader)
    merge = net.createNode("merge", "actors")
    merge.setInput(0, other)
    merge.setInput(1, robot)
    check("the same after a Merge", groom_y(merge, frames) == at_loader, groom_y(merge, frames))
    graft = net.createNode("graftstages", "graft_anim")  # as the shot layout: input 0 empty, actors grafted
    graft.setInput(1, merge)
    after = groom_y(graft, frames)
    check("the same after a Graft Stages", after == at_loader, after)
    topo = robot.node("groom_topology")
    layer = topo.activeLayer() if topo is not None else None
    sampled = []
    if layer is not None:
        layer.Traverse("/", lambda p: sampled.append(p.pathString)
                       if p.IsPropertyPath() and layer.GetNumTimeSamplesForPath(p) else None)
    check("the topology copy holds no animated value", topo is not None and not sampled, sampled[:3])
    graft_prim = next(p for p in graft.stage().Traverse() if p.IsA(UsdGeom.BasisCurves)
                      and "/char_Robot/" in p.GetPath().pathString)
    look_only = graft_prim.GetAttribute("primvars:lookOnly")
    check("a primvar only the lookdev has keeps its value", look_only and list(look_only.Get(Usd.TimeCode(first)) or [])
          == [0.5], look_only.Get(Usd.TimeCode(first)) if look_only else None)


try:
    main()
except Exception:
    check("no exception", False, traceback.format_exc())
(OUT / "accept_groom_graft.json").write_text(json.dumps(CHECKS, indent=1, default=str), encoding="utf-8")
failed = [c["name"] for c in CHECKS if not c["ok"]]
print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed", failed)
sys.exit(1 if failed else 0)
