"""A camera loader keeps the publish's aperture, or sets a width with the publish's ratio or its own.

hython tests/houdini/anim_loader/accept_camera_aperture.py <out_dir>

Up to v0.1.44 the camera's Camera LOP set the width alone (Horizontal Aperture, 36 mm by default) and left the height:
sh011's camera, 20.955 x 11.787 mm in its publish as Blender's camera has it, came out 36 x 11.787 (3.05:1). The fake
project's camera is given that aperture; a camera on input 0 must stay as it is in every mode.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

SUITE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(SUITE), str(SUITE / "packages/monofx_pipeline_common/src")]

import hou  # noqa: E402
from pxr import Gf, Sdf, Usd, UsdGeom  # noqa: E402

from apps.houdini import anim_loader_adapter as ad  # noqa: E402
from tools.fx.anim_loader import config  # noqa: E402
from tools.fx.anim_loader.dev import make_fake_shot  # noqa: E402

OUT = Path(sys.argv[1])
CAM = "/root/sh900_cam_root/cam_sh900"
UP = "/upstream_cam"
H, V, FOCAL = 0.20955, 0.11787187, 0.35  # sh011 v003: tenths of a scene unit, 1 m a unit
CHECKS: list[dict] = []


def check(name, ok, detail=None):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name, "" if detail is None else detail, flush=True)


def lens(node, path, frame=1.0):
    prim = node.stage().GetPrimAtPath(path)
    if not prim:
        return None
    cam = UsdGeom.Camera(prim)
    t = Usd.TimeCode(frame)
    xf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(t)
    return (cam.GetHorizontalApertureAttr().Get(t), cam.GetVerticalApertureAttr().Get(t),
            cam.GetFocalLengthAttr().Get(t), xf)


def close(a, b, eps=1e-5):
    return a is not None and b is not None and abs(a - b) < eps


def main():
    root = OUT / "project"
    make_fake_shot.main(root)
    cam_file = root / "02_shots/sh900/01_anim/publish/v002/cam_sh900.usd"
    layer = Sdf.Layer.FindOrOpen(str(cam_file))
    stage = Usd.Stage.Open(layer)
    cam = UsdGeom.Camera(stage.GetPrimAtPath(CAM))
    cam.CreateHorizontalApertureAttr().Set(H)
    cam.CreateVerticalApertureAttr().Set(V)
    cam.CreateFocalLengthAttr().Set(FOCAL)
    layer.Save()

    hou.hipFile.clear(suppress_save_prompt=True)
    for name in (config.HDA_FILE, config.OLD_FILE):  # this checkout's loader, not an installed one
        hou.hda.installFile(str(SUITE / "otls" / name))
        for d in hou.hda.definitionsInFile(str(SUITE / "otls" / name)):
            d.setIsPreferred(True)
    net = hou.node("/stage")
    # a camera already on the stage before the loader (another shot's, a layout camera): never edited
    up = net.createNode("camera", "upstream")
    up.parm("primpath").set(UP)
    up.parm("horizontalAperture").set(50.0)
    up.parm("verticalAperture").set(20.0)
    ad.load_shot(net, str(root), "sh900", "v002")
    loader = next(n for n in ad.find_loaders() if n.evalParm(config.P_GEO_CAM) == 1)
    loader.setInput(0, up)
    up_before = lens(up, UP)

    mode = loader.parm(config.P_CAM_APERTURE)
    check("the loader has the Aperture mode, on the publish's", mode is not None
          and mode.evalAsString() == config.CAM_APERTURE_PUBLISH, mode and mode.evalAsString())
    base = lens(loader, CAM)
    check("publish: the aperture is the publish's", base and close(base[0], H) and close(base[1], V), base and base[:3])
    check("publish: 16:9", base and close(base[0] / base[1], 16 / 9, 1e-4), base and base[0] / base[1])
    check("publish: the focal length is the publish's", base and close(base[2], FOCAL), base and base[2])
    # cam_x100 scales its input's last modified prims: a Python LOP last in the chain left the camera unscaled
    scale = base and Gf.Vec3d(base[3][0][0], base[3][0][1], base[3][0][2]).GetLength()
    check("the camera keeps the loader's x100 scale", base and close(scale, 100.0, 1e-3), scale)
    by_frame = [lens(loader, CAM, f) for f in (1.0, 12.0, 24.0)]
    check("publish: 16:9 on frames 1, 12 and 24", all(close(x[0] / x[1], 16 / 9, 1e-4) for x in by_frame))

    mode.set(config.CAM_APERTURE_WIDTH)
    loader.parm("horizontalAperture").set(36.0)
    w = lens(loader, CAM)
    check("width 36 mm: 0.36 wide", w and close(w[0], 0.36), w and w[:2])
    check("width 36 mm: the publish's ratio (16:9)", w and close(w[0] / w[1], H / V, 1e-4), w and w[0] / w[1])
    check("width: focal and transform unchanged", w and close(w[2], FOCAL) and Gf.IsClose(w[3], base[3], 1e-6))

    mode.set(config.CAM_APERTURE_RATIO)
    loader.parmTuple("aspectratio").set((2.39, 1.0))
    r = lens(loader, CAM)
    check("width and ratio: 2.39:1", r and close(r[0], 0.36) and close(r[0] / r[1], 2.39, 1e-4), r and r[:2])

    up_after = lens(loader, UP)
    check("the camera on input 0 is left as it is", up_before and up_after
          and close(up_before[0], up_after[0]) and close(up_before[1], up_after[1]),
          (up_before and up_before[:2], up_after and up_after[:2]))
    inspector = ad.cam_parms(loader.path())
    check("inspector: every camera field in 'width and ratio'", {"horizontalAperture", "aspectratiox"} <= set(inspector))
    mode.set(config.CAM_APERTURE_PUBLISH)
    inspector = ad.cam_parms(loader.path())
    check("inspector: no aperture / ratio field on the publish's", not {"horizontalAperture", "aspectratiox"}
          & set(inspector) and "clippingRange1" in inspector, sorted(inspector))


try:
    main()
except Exception:
    check("no exception", False, traceback.format_exc())
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "accept_camera_aperture.json").write_text(json.dumps(CHECKS, indent=1, default=str), encoding="utf-8")
failed = [c["name"] for c in CHECKS if not c["ok"]]
print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed", failed)
sys.exit(1 if failed else 0)
