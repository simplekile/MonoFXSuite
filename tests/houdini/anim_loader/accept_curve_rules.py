"""Groom curve rules (Karma's curve basis / width scale / style per shot) on the loader's stage.

hython tests/houdini/anim_loader/accept_curve_rules.py <fake_project> <out_dir>

Loads sh900 v002 of the fake project (make_fake_shot.py), sets curve rules on char_Robot's groom through the manager's
backend and checks: the primvars land on the curves prims at the loader and after a Merge, the groom's points are
left as the cache has them, one undo step per change, Remove the shot's overrides takes them off, and a bake keeps
them. sh025's char_Helen was checked the same way (2026-11-22).
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

SUITE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(SUITE), str(SUITE / "packages/monofx_pipeline_common/src")]

import hou  # noqa: E402
from pxr import Usd, UsdGeom  # noqa: E402

from apps.houdini import anim_loader_adapter as ad  # noqa: E402
from tools.fx.anim_loader import config, logic  # noqa: E402

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
CHECKS: list[dict] = []


def check(name, ok, detail=None):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name, "" if detail is None else detail, flush=True)


def curves(node, inst="char_Robot"):
    """{curves prim path: {basis, width, style, points}} under the instance on the node's stage."""
    out = {}
    for prim in node.stage().Traverse():
        if prim.IsA(UsdGeom.BasisCurves) and f"/{inst}/" in prim.GetPath().pathString:
            vals = {}
            for key, pv in logic.CURVE_PRIMVARS.items():
                a = prim.GetAttribute("primvars:" + pv)
                vals[key] = a.Get() if a and a.HasAuthoredValue() else None
            pts = UsdGeom.BasisCurves(prim).GetPointsAttr().Get(Usd.TimeCode(hou.frame()))
            vals["points"] = len(pts) if pts is not None else 0
            out[prim.GetPath().pathString] = vals
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in (config.HDA_FILE, config.OLD_FILE):  # this checkout's loader, not an installed one
        hou.hda.installFile(str(SUITE / "otls" / name))
        for d in hou.hda.definitionsInFile(str(SUITE / "otls" / name)):
            d.setIsPreferred(True)
    net = hou.node("/stage")
    ad.load_shot(net, str(SRC), "sh900", "v002")
    robot = next(n for n in ad.find_loaders() if n.evalParm(config.P_GEO_CAM) == 0
                 and n.evalParm(config.P_INSTANCE) == "char_Robot")
    check("the loader has the curve rules parm", robot.parm(config.P_CURVE_RULES) is not None)
    before = curves(robot)
    check("the groom has curves", before, list(before))
    b = ad.HoudiniBackend("/stage")
    info = [i for i in b.loaders() if i.path == robot.path()]
    detail = b.subd(info)[robot.path()]
    check("the manager reads a plan for every curves prim", set(detail["curve_plan"]) == set(detail["curves"])
          and detail["curves"], {k: (c.basis, c.basis_source) for k, c in detail["curve_plan"].items()})
    b.set_curves_many({robot.path(): ["Groom/**"]}, basis="bspline", width=1.5)
    after = curves(robot)
    check("basis and width land on every curves prim", after and all(
        v["basis"] == logic.CURVE_BASIS_KARMA["bspline"] and v["width"] == 1.5 and v["style"] is None
        for v in after.values()), after)
    check("the points stay the cache's", {k: v["points"] for k, v in after.items()}
          == {k: v["points"] for k, v in before.items()})
    merge = net.createNode("merge", "actors_check")
    merge.setInput(0, robot)
    check("the same after a Merge", {k: (v["basis"], v["width"]) for k, v in curves(merge).items()}
          == {k: (v["basis"], v["width"]) for k, v in after.items()})
    one = next(iter(after)).rsplit("/Groom/", 1)[-1]
    b.set_curves(robot.path(), [f"Groom/{one}"], style="flat")
    rules = robot.evalParm(config.P_CURVE_RULES)
    check("a later rule adds its field", any(v["style"] == 0 for v in curves(robot).values()), rules)
    hou.undos.performUndo()
    check("one undo step takes the last change back",
          json.loads(robot.evalParm(config.P_CURVE_RULES)) == [{"pattern": "Groom/**", "basis": "bspline",
                                                                "width": 1.5}], robot.evalParm(config.P_CURVE_RULES))
    hou.undos.performRedo()
    live = {k: (v["basis"], v["width"], v["style"]) for k, v in curves(robot).items()}
    done, _ = ad.bake_loaders([robot.path()])
    baked = hou.node("/stage/" + done[0]) if done else None
    got = {k: (v["basis"], v["width"], v["style"]) for k, v in curves(baked).items()} if baked else None
    check("a bake keeps them", baked is not None and baked.type().name() == "subnet" and got == live, got)
    hou.undos.performUndo()  # back to the loader
    robot = hou.node("/stage/" + done[0])
    b.clear_overrides(robot.path(), None)
    check("Remove the shot's overrides takes them off",
          robot.evalParm(config.P_CURVE_RULES) == "" and all(
              v["basis"] is None and v["width"] is None and v["style"] is None for v in curves(robot).values()))


try:
    main()
except Exception:
    check("no exception", False, traceback.format_exc())
(OUT / "accept_curve_rules.json").write_text(json.dumps(CHECKS, indent=1, default=str), encoding="utf-8")
failed = [c["name"] for c in CHECKS if not c["ok"]]
print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed", failed)
sys.exit(1 if failed else 0)
