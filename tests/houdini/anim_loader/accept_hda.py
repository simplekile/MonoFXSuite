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
HAIR = "/Groom/hair"  # under the instance: groom outside Geo
CACHE_HAIR = "/Geo/Groom_grp/Hair_grp/hair"  # in the cache files
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
    ref = pts(Usd.Stage.Open(str(gfile)), CACHE_HAIR, 12)
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
    g12 = pts(Usd.Stage.Open(str(gfile).replace("v002", "v001")), CACHE_HAIR, 12)
    check("groom clip equals file at 12", np.allclose(pts(st, f"/char_Robot_inst02{HAIR}", 12), g12, atol=1e-5))
    check("no groom on char_Robot_2", not st.GetPrimAtPath(f"/char_Robot_2{HAIR}"))
    cfile = ROOT / "02_shots/sh900/02_fx/cloth/publish/v001/char_Robot_2/sh900_cloth.0012.usd"
    check("cloth overrides anim", np.allclose(pts(st, f"/char_Robot_2{DRESS}", 12),
                                               pts(Usd.Stage.Open(str(cfile)), DRESS, 12), atol=1e-5))
    check("hair driver hidden", UsdGeom.Imageable(st.GetPrimAtPath(
        "/char_Robot/Geo/Groom_grp/HairDriver_grp")).ComputeVisibility(Usd.TimeCode(12)) == UsdGeom.Tokens.invisible)
    cam_node = nodes["sh900"]
    check("camera clipping defaults to 0.0001 - 1e6", (cam_node.evalParm("clippingRange1"),
          cam_node.evalParm("clippingRange2")) == (0.0001, 1e6), (cam_node.evalParm("clippingRange1"),
                                                                cam_node.evalParm("clippingRange2")))
    cam_node.parm("clippingRange1").set(0.5)  # 2.1's parm names (clippingRange1/2), kept by Upgrade
    cam_node.parm("clippingRange2").set(500.0)
    cam_prim = next(p for p in last.stage().Traverse() if p.IsA(UsdGeom.Camera))
    clip = UsdGeom.Camera(cam_prim).GetClippingRangeAttr().Get(Usd.TimeCode(12))
    check("camera clipping range reaches the camera", clip is not None and abs(clip[0] - 0.5) < 1e-4
          and abs(clip[1] - 500.0) < 1e-2, str(clip))
    st = last.stage()
    cams = [p.GetPath().pathString for p in st.Traverse() if p.IsA(UsdGeom.Camera)]
    check("camera kept at its own path", cams == ["/root/sh900_cam_root/cam_sh900"], cams)

    # Lookdev and groom show in the viewport by default; "Show in Viewport" off makes them render only
    body = st.GetPrimAtPath(f"/char_Robot{BODY}")
    pv, _ = UsdShade.MaterialBindingAPI(body).ComputeBoundMaterial(UsdShade.Tokens.preview)
    check("lookdev in the viewport by default", bool(pv))
    check("groom in the viewport by default", UsdGeom.Imageable(st.GetPrimAtPath(f"/char_Robot_inst02{HAIR}"))
          .ComputePurpose() == UsdGeom.Tokens.default_)
    # Subdivision: shot rule > lookdev > anim > none
    def scheme(path, stage=None):
        return UsdGeom.Mesh((stage or last.stage()).GetPrimAtPath(path)).GetSubdivisionSchemeAttr().Get()

    look_stage = Usd.Stage.Open(str(ROOT / "01_assets/_characters/char_Robot/05_lookdev/publish/v002/"
                                       "char_Robot_lookdev_publish.usd"))
    check("the fake lookdev authors catmullClark on the body (like Helen V009)",
          look_stage.GetPrimAtPath(BODY).GetAttribute("subdivisionScheme").Get() == "catmullClark")
    check("lookdev wins: body catmullClark", scheme(f"/char_Robot{BODY}", st) == UsdGeom.Tokens.catmullClark)
    check("nobody says: dress none (not USD's fallback)", scheme(f"/char_Robot{DRESS}", st) == UsdGeom.Tokens.none)
    check("anim says: hair driver catmullClark",
          scheme("/char_Robot/Geo/Groom_grp/HairDriver_grp/Geo_HairBase", st) == UsdGeom.Tokens.catmullClark)
    robot0 = nodes["char_Robot"]
    robot0.parm(config.P_SUBD_RULES).set('[{"pattern": "Geo/Base_grp/**", "scheme": "none", "dicing": 0.5}]')
    st2 = last.stage()
    body2 = st2.GetPrimAtPath(f"/char_Robot{BODY}")
    check("shot rule beats lookdev", scheme(f"/char_Robot{BODY}", st2) == UsdGeom.Tokens.none)
    dq = UsdGeom.PrimvarsAPI(body2).GetPrimvar("karma:object:dicingquality")
    check("shot rule sets dicing", bool(dq) and abs(dq.Get() - 0.5) < 1e-6)
    robot0.parm(config.P_SUBD_RULES).set("")
    robot0.parm(config.P_ENABLE["lookdev"]).set(0)
    ad.refresh(robot0)
    check("lookdev off: its subdivision opinion is gone", scheme(f"/char_Robot{BODY}") == UsdGeom.Tokens.none)
    robot0.parm(config.P_ENABLE["lookdev"]).set(1)
    ad.refresh(robot0)
    st = last.stage()
    inst.parm(config.P_VIEWPORT).set(0)
    st = last.stage()
    ib = st.GetPrimAtPath(f"/char_Robot_inst02{BODY}")
    full, _ = UsdShade.MaterialBindingAPI(ib).ComputeBoundMaterial(UsdShade.Tokens.full)
    pv, _ = UsdShade.MaterialBindingAPI(ib).ComputeBoundMaterial(UsdShade.Tokens.preview)
    check("render-only lookdev: bound for render (full)", bool(full))
    check("render-only lookdev: not bound in the viewport (preview)", not pv)
    check("render-only groom: purpose render", UsdGeom.Imageable(st.GetPrimAtPath(f"/char_Robot_inst02{HAIR}"))
          .ComputePurpose() == UsdGeom.Tokens.render)
    inst.parm(config.P_VIEWPORT).set(3)
    st = last.stage()

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
        check("comment names v003", "lookdev v003 available" in robot.comment(), robot.comment())
        check("menu label names v003", any("v003 available" in x for x in robot.parm(config.P_VERSION["lookdev"]).menuLabels()),
              robot.parm(config.P_VERSION["lookdev"]).menuLabels())
        check("a newer version is not a problem", "v003" not in robot.evalParm(config.P_STATUS),
              robot.evalParm(config.P_STATUS))
    finally:
        shutil.rmtree(new.parent)

    # a node put down by hand in a scene outside any project, then moved between shots from the parm pane
    extra = [ROOT / "02_shots" / "sh950", ROOT / "02_shots" / "sh960"]
    try:
        (extra[0] / "01_anim/publish/v001").mkdir(parents=True)
        shutil.copy(version / "geo_char_Robot.usd", extra[0] / "01_anim/publish/v001/geo_char_Robot.usd")
        (extra[1] / "01_anim/publish").mkdir(parents=True)
        hand = net.createNode(config.HDA_TYPE, "by_hand")

        def pick(parm, value):
            hand.parm(parm).set(value)
            ad.cb_parm_changed({"node": hand, "parm": hand.parm(parm), "parm_name": parm})
            return hand.evalParm(config.P_STATUS)

        check("outside a project the status says where to set one",
              hand.evalParm(config.P_STATUS) == logic.NO_PROJECT and hand.comment() == "no project",
              (hand.evalParm(config.P_STATUS), hand.comment()))
        check("project set: pick a shot", pick(config.P_ROOT, str(ROOT)) == "Pick a shot.",
              hand.evalParm(config.P_STATUS))
        labels = list(hand.parm(config.P_SHOT).menuLabels())
        check("shot menu lists the shots, no-anim marked", "sh900" in labels and "sh960  (no anim)" in labels,
              labels)
        status = pick(config.P_SHOT, "sh900")
        check("shot picked: newest anim version, then pick a file",
              hand.evalParm(config.P_ANIM_VERSION) == "v002" and status == "Pick an anim file.",
              (hand.evalParm(config.P_ANIM_VERSION), status))
        pick(config.P_ANIM_FILE, "geo_char_Robot.usd")
        status = pick(config.P_SHOT, "sh950")
        check("shot change moves the same character there",
              (hand.evalParm(config.P_ANIM_VERSION), hand.evalParm(config.P_ANIM_FILE)) == ("v001", "geo_char_Robot.usd")
              and "missing" not in status, (hand.evalParm(config.P_ANIM_VERSION), status))
        status = pick(config.P_SHOT, "sh960")
        check("a shot with no anim says so, keeps nothing of the old shot",
              status == "sh960 has no anim publish yet: pick another shot."
              and (hand.evalParm(config.P_ANIM_VERSION), hand.evalParm(config.P_ANIM_FILE)) == ("", ""),
              (status, hand.evalParm(config.P_ANIM_VERSION), hand.evalParm(config.P_ANIM_FILE)))
        hand.destroy()
    finally:
        for d in extra:
            shutil.rmtree(d, ignore_errors=True)

    # Source Asset (docs/plans/anim_loader_asset_source.md): the asset's UV model, groom and lookdev, same paths
    robot_dir = ROOT / "01_assets/_characters/char_Robot"
    made = [robot_dir / "01_modelling", robot_dir / "04_grooming"]
    hip_before = hou.hipFile.path()
    try:
        uv = robot_dir / "01_modelling/03_uv/publish"
        for v in ("v001", "v002"):
            (uv / v).mkdir(parents=True)
            shutil.copy(version / "geo_char_Robot.usd", uv / v / "char_Robot_uv_publish.usd")
        shutil.copy(version / "geo_char_Robot.usd", uv / "v002" / "char_Robot_uv_publish_Body.usd")
        gdir = robot_dir / "04_grooming/publish/v001"
        gdir.mkdir(parents=True)
        gst = Usd.Stage.CreateNew(str(gdir / "char_Robot_groom_publish.usd"))
        UsdGeom.Xform.Define(gst, "/Groom")
        curves = UsdGeom.BasisCurves.Define(gst, "/Groom/strands")
        curves.CreatePointsAttr([(0, 0, 0), (0, 1, 0), (1, 0, 0), (1, 1, 0)])
        curves.CreateCurveVertexCountsAttr([2, 2])
        curves.CreateTypeAttr("linear")
        gst.SetDefaultPrim(gst.GetPrimAtPath("/Groom"))
        gst.GetRootLayer().Save()

        hou.hipFile.setName(str(robot_dir / "04_grooming/houdini/work/char_Robot_grooming_v001.hiplc"))
        rest = net.createNode(config.HDA_TYPE, "rest")
        st_rest = rest.stage()
        check("a scene in the asset folder gives Source Asset with the newest model and groom",
              (rest.evalParm(config.P_SOURCE), rest.evalParm(config.P_ASSET), rest.evalParm(config.P_MODEL_VERSION),
               rest.evalParm(config.P_MODEL_FILE), rest.evalParm(config.P_VERSION["groom"])) ==
              ("asset", "char_Robot", "v002", "char_Robot_uv_publish.usd", "v001"),
              (rest.evalParm(config.P_SOURCE), rest.evalParm(config.P_MODEL_VERSION), rest.evalParm(config.P_STATUS)))
        # Prim Name off for a new Source Asset loader (the user's ask, 2026-11-20): the publish's own paths
        check("asset scene: Prim Name off, the model at its own paths", rest.evalParm(config.P_USE_PRIM) == 0
              and bool(st_rest.GetPrimAtPath(BODY)) and not st_rest.GetPrimAtPath("/char_Robot"))
        check("asset groom outside Geo, at its own path", bool(st_rest.GetPrimAtPath("/Groom/strands")))
        check("asset: lookdev subdivision applies with Prim Name off (body catmullClark)",
              UsdGeom.Mesh(st_rest.GetPrimAtPath(BODY)).GetSubdivisionSchemeAttr().Get()
              == UsdGeom.Tokens.catmullClark)
        rest.parm(config.P_USE_PRIM).set(1)
        st_rest = rest.stage()
        check("asset model grafted at the shot's paths", bool(st_rest.GetPrimAtPath(f"/char_Robot{BODY}")))
        check("asset groom outside Geo", bool(st_rest.GetPrimAtPath("/char_Robot/Groom/strands")))
        check("asset: lookdev subdivision applies (body catmullClark)",
              UsdGeom.Mesh(st_rest.GetPrimAtPath(f"/char_Robot{BODY}")).GetSubdivisionSchemeAttr().Get()
              == UsdGeom.Tokens.catmullClark)
        labels = list(rest.parm(config.P_MODEL_FILE).menuLabels())
        check("model file menu marks the standard file", "char_Robot_uv_publish.usd  (standard)" in labels, labels)
        check("Load shot leaves Source Asset nodes alone", ad._key(rest) == ("", ""))

        def pick(node, parm, value):
            node.parm(parm).set(value)
            ad.cb_parm_changed({"node": node, "parm": node.parm(parm), "parm_name": parm})

        robot0 = nodes["char_Robot"]
        shot_before = (robot0.evalParm(config.P_ANIM_VERSION), robot0.evalParm(config.P_ANIM_FILE))
        mesh_shot = sorted(p.GetPath().pathString for p in Usd.PrimRange(robot0.stage().GetPrimAtPath("/char_Robot/Geo"))
                           if p.IsA(UsdGeom.Mesh))
        pick(robot0, config.P_SOURCE, "asset")
        mesh_asset = sorted(p.GetPath().pathString for p in Usd.PrimRange(robot0.stage().GetPrimAtPath("/char_Robot/Geo"))
                            if p.IsA(UsdGeom.Mesh))
        check("switching to Asset keeps every mesh path", mesh_shot == mesh_asset and bool(mesh_shot),
              (len(mesh_shot), len(mesh_asset)))
        check("Asset status clean", robot0.evalParm(config.P_STATUS) == "", robot0.evalParm(config.P_STATUS))
        pick(robot0, config.P_SOURCE, "shot")
        check("switching back restores the shot",
              (robot0.evalParm(config.P_ANIM_VERSION), robot0.evalParm(config.P_ANIM_FILE),
               robot0.evalParm(config.P_INSTANCE)) == (*shot_before, "char_Robot"),
              (robot0.evalParm(config.P_ANIM_VERSION), robot0.evalParm(config.P_INSTANCE)))
        pick(rest, config.P_MODEL_FILE, "char_Robot_uv_publish_Body.usd")
        pick(rest, config.P_MODEL_VERSION, "v001")
        check("a version without the picked file goes back to the standard file",
              rest.evalParm(config.P_MODEL_FILE) == "char_Robot_uv_publish.usd", rest.evalParm(config.P_MODEL_FILE))
        rest.destroy()

        lib32 = Path("D:/Dropbox/Stock/Plugin/HOU/Mono/hda/lop_mono_character_loader.3.2.hdalc")
        if lib32.is_file():  # the Dropbox HDA: Upgrade turns it into a 2.2 Source Asset in its place
            hou.hda.installFile(str(lib32))
            old = net.createNode("mono_character_loader::3.2", "charload")
            for k, v in (("folder_path", str(ROOT / "01_assets/_characters")), ("Model_List", "char_Robot"),
                         ("Version_List", "v001"), ("File_List", "char_Robot_uv_publish.usd")):
                old.parm(k).set(v)
            # 3.2 takes no input
            after = net.createNode("null", "after_charload")
            after.setInput(0, old)
            done = ad.upgrade([old])
            new = done[0] if done else None
            check("Character Loader 3.2 upgraded in place to Source Asset",
                  new is not None and new.type().name() == config.HDA_TYPE and new.name() == "charload"
                  and new.evalParm(config.P_SOURCE) == "asset" and new.evalParm(config.P_MODEL_VERSION) == "v001"
                  and after.inputs()[0] == new
                  and bool(new.stage().GetPrimAtPath(f"/char_Robot{BODY}")),
                  None if new is None else (new.name(), new.evalParm(config.P_MODEL_VERSION),
                                            new.evalParm(config.P_STATUS)))
            for n in (new, after):
                if n is not None:
                    n.destroy()
    finally:
        hou.hipFile.setName(hip_before)
        for d in made:
            shutil.rmtree(d, ignore_errors=True)

    # MonoFX Loader type: Tab tool names the node monofx_loader; the old 2.2 type upgrades in place; loaders inside a
    # LOP network in /obj are found too
    d = hou.nodeType(hou.lopNodeTypeCategory(), config.HDA_TYPE).definition()
    check("Tab tool names the node monofx_loader", "'monofx_loader'" in d.sections()["Tools.shelf"].contents())
    old_lib = build_hda.build(str(OUT / config.OLD_FILE), config.OLD_TYPE, "Mono Anim Loader 2.2 (old)", "2.2")
    hou.hda.installFile(old_lib)
    old22 = net.createNode(config.OLD_TYPE, "old22")
    ad.write_state(old22, ad.read_state(nodes["char_Robot"]))
    before22 = ad.read_state(old22)
    up = ad.upgrade([old22])
    check("Anim Loader 2.2 upgrades to MonoFX Loader keeping its state",
          len(up) == 1 and up[0].type().name() == config.HDA_TYPE and ad.read_state(up[0]) == before22
          and bool(up[0].stage().GetPrimAtPath(f"/char_Robot{BODY}")))
    up[0].destroy() if up else None
    lopnet = hou.node("/obj").createNode("lopnet", "Character_Loader")
    inside = lopnet.createNode(config.HDA_TYPE, "inside")
    check("loaders in a LOP network inside /obj are found", inside in ad.find_loaders()
          and inside not in ad.find_loaders(hou.node("/stage")), [n.path() for n in ad.find_loaders()][:8])
    lopnet.destroy()

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
