"""Spikes S1 (groom / cloth by value clip vs Sublayer $F4) and S2 (Graft Stages per instance), plan Task 4.

hython tools/fx/anim_loader/dev/spike_s1_s2.py <fake_project> <out_dir>

Writes <out_dir>/spike.json. Motion blur is checked the way Karma samples it: the points of the groom at a
sub-frame (10.5) must lie between those at 10 and 11; a stage that holds only the current frame's file
returns the same points at 10.5 as at 10, so it cannot blur.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import hou
import numpy as np
from pxr import Sdf, Usd, UsdGeom, UsdShade

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

SH025 = Path("D:/Dropbox/Job/260826_grn_vp97/02_shots/sh025")
HAIR = "/Geo/Groom_grp/Hair_grp/hair"
RESULT: dict = {}


def log(key, value):
    RESULT[key] = value
    print(key, value, flush=True)


def pts(stage: Usd.Stage, path: str, t: float) -> np.ndarray | None:
    prim = stage.GetPrimAtPath(path)
    if not prim:
        return None
    v = UsdGeom.PointBased(prim).GetPointsAttr().Get(Usd.TimeCode(t))
    return None if v is None else np.asarray(v)


def blur_ok(stage: Usd.Stage, path: str, f: float) -> bool | None:
    a, m, b = pts(stage, path, f), pts(stage, path, f + 0.5), pts(stage, path, f + 1)
    if a is None or m is None or b is None or len(a) != len(m):
        return None
    return bool(np.abs(m - a).max() > 1e-6 and np.abs(m - (a + b) / 2).max() < np.abs(b - a).max())


def clip_layer(folder: Path, shot: str, task: str, prim: str, first: int, last: int, out: Path) -> Path:
    """A layer holding the clip metadata on ``prim`` (template ``<shot>_<task>.####.usd``), plus a manifest."""
    files = sorted(folder.glob(f"{shot}_{task}.*.usd"))
    t = time.time()
    layers = [Sdf.Layer.FindOrOpen(str(f)) for f in files]
    manifest = Usd.ClipsAPI.GenerateClipManifestFromLayers(layers, Sdf.Path(prim))
    manifest_path = out / f"{shot}_{task}_manifest.usda"
    manifest.Export(str(manifest_path))
    log(f"S1.{task}.manifest_s", round(time.time() - t, 2))
    lay = Sdf.Layer.CreateNew(str(out / f"{shot}_{task}_clips.usda"))
    st = Usd.Stage.Open(lay)
    p = st.OverridePrim(prim)
    clips = Usd.ClipsAPI(p)
    clips.SetClipPrimPath(prim)
    pad = len(files[0].name.split(".")[-2])
    clips.SetClipTemplateAssetPath((folder / f"{shot}_{task}.{'#' * pad}.usd").as_posix())
    clips.SetClipTemplateStartTime(first)
    clips.SetClipTemplateEndTime(last)
    clips.SetClipTemplateStride(1)
    clips.SetClipManifestAssetPath(Sdf.AssetPath(manifest_path.as_posix()))
    lay.subLayerPaths.append(files[0].as_posix())  # topology (counts) from the first frame
    lay.Save()
    return Path(lay.realPath)


def lop(parent, kind, name, inputs=(), **parms):
    n = parent.createNode(kind, name)
    for i, src in enumerate(inputs):
        n.setInput(i, src)
    for k, v in parms.items():
        n.parm(k).set(v)
    return n


def timed_frames(node, frames, prim: str = HAIR) -> tuple[float, float]:
    """Cook the stage and read the points at each frame, as a viewport or render would."""
    hou.setFrame(frames[0])
    t = time.time()
    pts(node.stage(), prim, frames[0])
    first = time.time() - t
    t = time.time()
    for f in frames[1:]:
        hou.setFrame(f)
        pts(node.stage(), prim, f)
    return round(first, 3), round((time.time() - t) / max(1, len(frames) - 1), 4)


def s1(out: Path) -> None:
    folder = SH025 / "02_fx/groom/publish/v900/char_Helen"
    stage_net = hou.node("/stage")
    hou.setFps(30)
    sub = lop(stage_net, "sublayer", "s1_sublayer", filepath1=(folder / "sh025_groom.$F4.usd").as_posix())
    log("S1.sublayer.first_s, per_frame_s", timed_frames(sub, list(range(0, 46))))
    hou.setFrame(10)
    log("S1.sublayer.blur", blur_ok(sub.stage(), HAIR, 10))

    layer = clip_layer(folder, "sh025", "groom", HAIR, 0, 45, out)
    clip = lop(stage_net, "sublayer", "s1_clip", filepath1=layer.as_posix())
    log("S1.clip.first_s, per_frame_s", timed_frames(clip, list(range(0, 46))))
    st = clip.stage()
    log("S1.clip.blur", blur_ok(st, HAIR, 10))
    raw = Usd.Stage.Open(str(folder / "sh025_groom.0010.usd"))
    log("S1.clip.matches_file_at_10", bool(np.allclose(pts(st, HAIR, 10), pts(raw, HAIR, 10))))

    fake = Path(sys.argv[1]) / "02_shots/sh900/02_fx/groom/publish/v002/char_Robot"
    layer2 = clip_layer(fake, "sh900", "groom", HAIR, 1, 24, out)
    st2 = Usd.Stage.Open(str(layer2))
    a, b = pts(st2, HAIR, 3), pts(st2, HAIR, 12)
    log("S1.clip.default_only_animates", bool(a is not None and b is not None and np.abs(a - b).max() > 1e-6))


def s2(root: Path, out: Path) -> None:
    net = hou.node("/stage").createNode("lopnet", "s2")
    anim = root / "02_shots/sh900/01_anim/publish/v002"
    look = {a: root / f"01_assets/_characters/{a}/05_lookdev/publish/v002/{a}_lookdev_publish.usd"
            for a in ("char_Robot", "char_Robot_2")}
    groom = root / "02_shots/sh900/02_fx/groom/publish/v001"
    clips_dir = out / "s2"
    clips_dir.mkdir(exist_ok=True)
    cases = {"char_Robot": ("char_Robot", groom / "char_Robot"),
             "char_Robot_inst02": ("char_Robot", groom / "Robot_inst02"),
             "char_Robot_2": ("char_Robot_2", None)}
    cur = None
    for name, (asset, gfolder) in cases.items():
        files = [(anim / f"geo_{name}.usd").as_posix(), look[asset].as_posix()]
        if gfolder is not None:
            d = clips_dir / name
            d.mkdir(exist_ok=True)
            files.append(clip_layer(gfolder, "sh900", "groom", HAIR, 1, 24, d).as_posix())
        branch = lop(net, "sublayer", f"{name}_layers", num_files=len(files))
        for i, f in enumerate(reversed(files)):  # first file is strongest in a Sublayer LOP
            branch.parm(f"filepath{i + 1}").set(f)
        g = net.createNode("graftstages", f"{name}_graft")
        if cur is not None:
            g.setInput(0, cur)
        g.setInput(1, branch)
        g.parm("primpath").set(f"/{name}")
        g.parm("destpath").set("")  # "/" would nest under the input node's name
        cur = g
    hou.setFrame(12)
    st = cur.stage()
    a = pts(st, f"/char_Robot/Geo/Base_grp/Body_grp/Geo_Body", 12)
    b = pts(st, f"/char_Robot_inst02/Geo/Base_grp/Body_grp/Geo_Body", 12)
    log("S2.instances_present", [p.GetPath().pathString for p in st.GetPseudoRoot().GetChildren()])
    log("S2.instances_differ", bool(a is not None and b is not None and np.abs(a - b).max() > 1e-3))
    binds = {}
    for name in cases:
        prim = st.GetPrimAtPath(f"/{name}/Geo/Base_grp/Body_grp/Geo_Body")
        mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial() if prim else (None, None)
        binds[name] = mat.GetPath().pathString if mat else None
    log("S2.bound_material", binds)
    log("S2.groom_present", {n: bool(st.GetPrimAtPath(f"/{n}{HAIR}")) for n in cases})
    log("S2.groom_blur_after_graft", blur_ok(st, f"/char_Robot_inst02{HAIR}", 10))
    hair = pts(st, f"/char_Robot_inst02{HAIR}", 12)
    drv = pts(st, "/char_Robot_inst02/Geo/Groom_grp/HairDriver_grp/Geo_HairBase", 12)
    if hair is not None and drv is not None:
        roots = hair.reshape(-1, 8, 3)[:, 0]
        d = np.min(np.linalg.norm(roots[:200, None, :] - drv[None, :, :], axis=2), axis=1)
        log("S2.groom_roots_on_own_driver_max_m", round(float(d.max()), 6))
    t = time.time()
    for f in range(1, 25):
        hou.setFrame(f)
        cur.stage()
    log("S2.per_frame_s", round((time.time() - t) / 24, 4))
    log("S2.layers_of_graft", [l.identifier.split("/")[-1][:60] for l in cur.stage().GetLayerStack()][:8])


if __name__ == "__main__":
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for step in (lambda: s1(out), lambda: s2(root, out)):
        try:
            step()
        except Exception as e:  # keep what ran
            import traceback

            log(f"error.{len(RESULT)}", traceback.format_exc()[-1500:])
    (out / "spike.json").write_text(json.dumps(RESULT, indent=2), encoding="utf-8")
