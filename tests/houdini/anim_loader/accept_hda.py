"""Mono Anim Loader 2.2 HDA acceptance (plan Task 5). Needs Houdini; not collected by pytest.

hython tests/houdini/anim_loader/accept_hda.py <fake_project> <out_dir>

Builds the HDA into <out_dir>, loads sh900 v002 (char_Robot, char_Robot_inst02, char_Robot_2, camera) and
checks prims, motion, lookdev, groom / cloth, input pass-through, refresh and a save / reopen.
Writes <out_dir>/accept.json; exit code 1 when a check fails.
"""

from __future__ import annotations

import json
import shutil
import sys
import traceback
from pathlib import Path

SUITE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SUITE))
sys.path.insert(0, str(SUITE / "packages/monofx_pipeline_common/src"))

import hou  # noqa: E402
import numpy as np  # noqa: E402
from pxr import Usd, UsdGeom, UsdShade  # noqa: E402

from apps.houdini import anim_loader_adapter as ad  # noqa: E402
from tools.fx.anim_loader import build_hda, config, logic  # noqa: E402

ROOT = Path(sys.argv[1])
OUT = Path(sys.argv[2])
CHECKS: list[dict] = []
HAIR = "/Geo/Groom_grp/Hair_grp/hair"
BODY = "/Geo/Base_grp/Body_grp/Geo_Body"
DRESS = "/Geo/Outfit_grp/Costume_grp/Geo_Dress"


def check(name: str, ok, detail=None) -> None:
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name, "" if detail is None else detail, flush=True)


def pts(stage, path, t):
    prim = stage.GetPrimAtPath(path)
    if not prim:
        return None
    v = UsdGeom.PointBased(prim).GetPointsAttr().Get(Usd.TimeCode(t))
    return None if v is None else np.asarray(v)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    lib = build_hda.build(str(OUT / "mono_anim_loader.hdalc"))
    hou.hda.installFile(lib)
    check("hda type", hou.nodeType(hou.lopNodeTypeCategory(), config.HDA_TYPE) is not None)
    hou.setFps(24)
    net = hou.node("/stage")
    upstream = net.createNode("primitive", "upstream")
    upstream.parm("primpath").set("/upstream_thing")

    version = logic.anim_publish_dir(ROOT, "sh900") / "v002"
    nodes = {}
    for out in logic.read_outputs(version):
        nodes[logic.instance_name(out.file)] = ad.create_loader(net, str(ROOT), "sh900", "v002", out)
    check("four loaders", sorted(nodes) == ["char_Robot", "char_Robot_2", "char_Robot_inst02", "sh900"],
          sorted(nodes))
    order = [nodes[n] for n in ("char_Robot", "char_Robot_inst02", "char_Robot_2", "sh900")]
    order[0].setInput(0, upstream)
    for a, b in zip(order, order[1:]):
        b.setInput(0, a)
    last = order[-1]

    hou.setFrame(12)
    st = last.stage()
    check("no errors", not any(n.errors() for n in order), [n.errors() for n in order])
    check("input passes through", bool(st.GetPrimAtPath("/upstream_thing")))
    for n in ("char_Robot", "char_Robot_inst02", "char_Robot_2"):
        check(f"{n} body under its root", bool(st.GetPrimAtPath(f"/{n}{BODY}")))
    a, b = pts(st, f"/char_Robot{BODY}", 12), pts(st, f"/char_Robot_inst02{BODY}", 12)
    check("instances move differently", a is not None and b is not None and np.abs(a - b).max() > 1e-3)
    mats = {}
    for n in ("char_Robot", "char_Robot_inst02", "char_Robot_2"):
        m, _ = UsdShade.MaterialBindingAPI(st.GetPrimAtPath(f"/{n}{BODY}")).ComputeBoundMaterial()
        mats[n] = m.GetPath().pathString if m else None
    check("lookdev bound per instance", mats == {
        "char_Robot": "/char_Robot/materials/char_Robot_mtl",
        "char_Robot_inst02": "/char_Robot_inst02/materials/char_Robot_mtl",
        "char_Robot_2": "/char_Robot_2/materials/char_Robot_2_mtl"}, mats)

    gfile = ROOT / "02_shots/sh900/02_fx/groom/publish/v002/Robot_inst02/sh900_groom.0012.usd"
    ref = pts(Usd.Stage.Open(str(gfile)), HAIR, 12)
    hair = pts(st, f"/char_Robot_inst02{HAIR}", 12)
    check("groom of inst02 present", hair is not None)
    check("groom v002 (no time samples) equals frame 12's file", hair is not None and ref is not None
          and np.allclose(hair, ref, atol=1e-5))
    inst = nodes["char_Robot_inst02"]
    check("groom mode follows the cache", inst.evalParm(config.P_FX["groom"]["mode"]) == config.FX_MODE_SUBLAYER,
          inst.evalParm(config.P_FX["groom"]["mode"]))
    check("no-blur note", "no motion blur" in inst.evalParm(config.P_STATUS), inst.evalParm(config.P_STATUS))

    inst.parm(config.P_VERSION["groom"]).set("v001")
    ad.refresh(inst)
    st = last.stage()
    check("groom v001 by clip", inst.evalParm(config.P_FX["groom"]["mode"]) == config.FX_MODE_CLIP)
    h10, h105, h11 = (pts(st, f"/char_Robot_inst02{HAIR}", t) for t in (10, 10.5, 11))
    check("groom blurs (10.5 between 10 and 11)", h10 is not None and np.abs(h105 - h10).max() > 1e-6
          and np.allclose(h105, (h10 + h11) / 2, atol=1e-4))
    g12 = pts(Usd.Stage.Open(str(gfile).replace("v002", "v001")), HAIR, 12)
    check("groom clip equals file at 12", np.allclose(pts(st, f"/char_Robot_inst02{HAIR}", 12), g12, atol=1e-5))
    check("no groom on char_Robot_2", not st.GetPrimAtPath(f"/char_Robot_2{HAIR}"))
    cfile = ROOT / "02_shots/sh900/02_fx/cloth/publish/v001/char_Robot_2/sh900_cloth.0012.usd"
    check("cloth overrides anim", np.allclose(pts(st, f"/char_Robot_2{DRESS}", 12),
                                               pts(Usd.Stage.Open(str(cfile)), DRESS, 12), atol=1e-5))
    check("hair driver hidden", UsdGeom.Imageable(st.GetPrimAtPath(
        "/char_Robot/Geo/Groom_grp/HairDriver_grp")).ComputeVisibility(Usd.TimeCode(12)) == UsdGeom.Tokens.invisible)
    cams = [p.GetPath().pathString for p in st.Traverse() if p.IsA(UsdGeom.Camera)]
    check("camera kept at its own path", cams == ["/root/sh900_cam_root/cam_sh900"], cams)

    robot = nodes["char_Robot"]
    look_before = robot.evalParm(config.P_PATH["lookdev"])
    robot.parm(config.P_VERSION["lookdev"]).set("v001")
    ad.refresh(robot)
    check("lookdev version change rewrites path", "/v001/" in robot.evalParm(config.P_PATH["lookdev"]))
    robot.parm(config.P_VERSION["lookdev"]).set("v002")
    ad.refresh(robot)
    check("back to v002", robot.evalParm(config.P_PATH["lookdev"]) == look_before)
    new = ROOT / "01_assets/_characters/char_Robot/05_lookdev/publish/v003/char_Robot_lookdev_publish.usd"
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(look_before, new)
    try:
        ad.refresh(robot)
        check("newer lookdev does not change the path", robot.evalParm(config.P_PATH["lookdev"]) == look_before)
        check("status names v003", "v003" in robot.evalParm(config.P_STATUS), robot.evalParm(config.P_STATUS))
    finally:
        shutil.rmtree(new.parent)

    hip = OUT / "accept_hda.hiplc"
    saved = {n.name(): {p.name(): p.eval() for p in n.parms()} for n in order}
    hou.hipFile.save(str(hip))
    hou.hipFile.load(str(hip), suppress_save_prompt=True)
    again = {n: {p.name(): p.eval() for p in hou.node(f"/stage/{n}").parms()} for n in saved}
    check("reopen keeps every parm", again == saved,
          [(n, k) for n in saved for k in saved[n] if saved[n][k] != again[n].get(k)][:5])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        check("no exception", False, traceback.format_exc()[-2000:])
    (OUT / "accept.json").write_text(json.dumps(CHECKS, indent=2), encoding="utf-8")
    failed = [c["name"] for c in CHECKS if not c["ok"]]
    print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed", failed)
    sys.exit(1 if failed else 0)
