"""hython: the manager layout A backend on the fake project (Add assets into the shot layout or assets_merge, Solo,
Show in Viewport, Source, what is new, hand off). Usage: hython accept_manager_a.py <fake project> <out dir>"""

from __future__ import annotations

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
from tools.fx.anim_loader import build_hda, config, logic  # noqa: E402

ROOT = Path(sys.argv[1])
OUT = Path(sys.argv[2])
CHECKS: list[dict] = []


def check(name, ok, detail=None):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name, "" if detail is None else detail, flush=True)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    hou.hda.installFile(build_hda.build(str(OUT / config.HDA_FILE)))
    robot = ROOT / "01_assets/_characters/char_Robot"
    rock = ROOT / "01_assets/_props/prop_Rock"
    made = [robot / "01_modelling", rock]
    version = logic.anim_publish_dir(ROOT, "sh900") / "v002"
    try:
        for d, name in ((robot / "01_modelling/03_uv/publish/v001", "char_Robot"),
                        (rock / "01_modelling/03_uv/publish/v001", "prop_Rock")):
            d.mkdir(parents=True)
            shutil.copy(version / "geo_char_Robot.usd", d / f"{name}_uv_publish.usd")
        net = hou.node("/stage")

        # a network without the shot layout: assets_merge
        r = ad.add_assets(net, str(ROOT), ["prop_Rock", "char_Robot"])
        merge = net.node("assets_merge")
        check("no shot layout: the assets go into assets_merge",
              r.created == ["prop_Rock", "char_Robot"] and merge is not None
              and [i.name() for i in merge.inputs()] == ["prop_Rock", "char_Robot"], r.created)
        again = ad.add_assets(net, str(ROOT), ["prop_Rock"])
        second = net.node(again.created[0]) if again.created else None
        check("an asset already placed gets another instance (set dressing)", second is not None
              and second.evalParm(config.P_INSTANCE) == "prop_Rock_inst02"
              and bool(second.stage().GetPrimAtPath("/prop_Rock_inst02/Geo")), again.created)
        second.destroy() if second else None
        node = net.node("prop_Rock")
        check("added on Source Asset, newest model", node.evalParm(config.P_SOURCE) == "asset"
              and node.evalParm(config.P_MODEL_VERSION) == "v001" and bool(node.stage().GetPrimAtPath("/prop_Rock/Geo")))

        # the shot layout: characters with the actors, the rest in the environments; Load shot uses them too
        lay = hou.node("/obj").createNode("lopnet", "layout")
        for name in ("merge_actors", "merge_cameras", "merge_environments"):
            lay.createNode("merge", name)
        r = ad.add_assets(lay, str(ROOT), ["prop_Rock", "char_Robot"])
        check("shot layout: prop -> merge_environments, character -> merge_actors",
              [i.name() for i in lay.node("merge_environments").inputs()] == ["prop_Rock"]
              and [i.name() for i in lay.node("merge_actors").inputs()] == ["char_Robot"]
              and lay.node("assets_merge") is None)
        lay.node("char_Robot").destroy()
        ls = ad.load_shot(lay, str(ROOT), "sh900", "v002")
        cams = [i.name() for i in lay.node("merge_cameras").inputs()]
        actors = [i.name() for i in lay.node("merge_actors").inputs() if i is not None]
        check("shot layout: Load shot wires geo -> merge_actors, camera -> merge_cameras, no sh900_merge",
              cams == ["sh900"] and "char_Robot" in actors and lay.node("sh900_merge") is None, (actors, cams))

        # view: Solo Geometry (view state), Show in Viewport (parm)
        disp = lay.node("merge_actors")
        disp.setDisplayFlag(True)
        n = ad.solo([lay.node("char_Robot").path()])
        with lay.viewportOverrides(disp) as o:
            solo = [str(x) for x in o.soloGeometry()]
        check("solo puts the instance in Solo Geometry", n == 1 and "/char_Robot" in str(solo), solo)
        ad.solo([])
        with lay.viewportOverrides(disp) as o:
            left = [str(x) for x in o.soloGeometry()]
        check("solo off clears it", not left, left)
        ad.set_viewport_part("groom", False)
        check("groom off in the viewport on every loader", not ad.viewport_part_on("groom")
              and all(not (int(x.evalParm(config.P_VIEWPORT)) & 2) for x in ad.find_loaders()))
        ad.set_viewport_part("groom", True)

        # Source
        robot_node = lay.node("char_Robot")
        ad.set_source([robot_node.path()], "asset")
        check("set_source switches to Asset, shot kept on the node",
              robot_node.evalParm(config.P_SOURCE) == "asset" and robot_node.evalParm(config.P_ANIM_FILE)
              == "geo_char_Robot.usd" and robot_node.evalParm(config.P_MODEL_VERSION) == "v001")
        ad.set_source([robot_node.path()], "shot")

        # what is new: an older anim version on the node
        robot_node.parm(config.P_ANIM_VERSION).set("v001")
        ad.refresh(robot_node)
        infos = ad.HoudiniBackend("/obj/layout").loaders()
        extras = ad.HoudiniBackend.extras(infos, str(ROOT), "sh900")
        news = extras["news"].get(robot_node.path(), [])
        check("what is new: anim v002 for a loader on v001", bool(news) and news[0].part == "anim"
              and news[0].new == "v002", [(w.part, w.old, w.new, w.lines) for w in news])

        # hand off: one USD with the instance, flattened, textures copied, relative paths
        hand = OUT / "handoff"
        lines = ad.handoff([node.path()], str(hand))
        usd = hand / "prop_Rock_handoff" / "prop_Rock.usd"
        layer = Sdf.Layer.FindOrOpen(str(usd)) if usd.exists() else None
        st = Usd.Stage.Open(str(usd)) if usd.exists() else None
        absolute = []
        if layer is not None:
            def scan(path):
                spec = layer.GetObjectAtPath(path)
                if isinstance(spec, Sdf.AttributeSpec) and spec.typeName == Sdf.ValueTypeNames.Asset:
                    v = spec.default
                    if v and ":" in v.path:
                        absolute.append(v.path)
            layer.Traverse(Sdf.Path.absoluteRootPath, scan)
        check("hand off writes one USD of the instance, no MonoFX needed", st is not None
              and st.GetDefaultPrim().GetName() == "prop_Rock" and not layer.subLayerPaths
              and any(p.IsA(UsdGeom.Mesh) for p in st.Traverse()), lines)
        check("hand off leaves no absolute asset path", not absolute, absolute[:3])
    finally:
        for d in made:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        check("no exception", False, traceback.format_exc()[-2000:])
    (OUT / "accept.json").write_text(json.dumps(CHECKS, indent=2), encoding="utf-8")
    failed = [c["name"] for c in CHECKS if not c["ok"]]
    print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed", failed)
    sys.exit(1 if failed else 0)
