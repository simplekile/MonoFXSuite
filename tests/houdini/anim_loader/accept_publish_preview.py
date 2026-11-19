"""Test in Houdini (Blender add-on button), the Houdini side, on the fake project. Needs Houdini; not collected by pytest.

hython tests/houdini/anim_loader/accept_publish_preview.py <out_dir>

Makes the fake project (tools/fx/anim_loader/dev/make_fake_shot.py) in <out_dir>/fake_project, adds two UV publishes
of char_Robot (v001 as Blender 5.2 writes it, v002 broken: a binding to no Material, no subdivisionScheme, no kind),
builds the HDA, then runs ``apps.houdini.publish_preview.build`` for each and for anim sh900 v002, each in a new scene.
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
from pxr import Sdf, Usd, UsdGeom, UsdShade  # noqa: E402

from apps.houdini import publish_preview as ppa  # noqa: E402
from tools.fx.anim_loader import build_hda, config  # noqa: E402
from tools.fx.anim_loader.dev import fake_usd as fu  # noqa: E402
from tools.fx.anim_loader.dev import make_fake_shot  # noqa: E402

OUT = Path(sys.argv[1])
ROOT = OUT / "fake_project"
CHECKS: list[dict] = []
UV = ROOT / "01_assets/_characters/char_Robot/01_modelling/03_uv/publish"


def check(name: str, ok, detail=None) -> None:
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name, "" if detail is None else detail, flush=True)


def write_model(path: Path, good: bool) -> None:
    """A UV publish like Blender's model publish: /Geo (kind component), materials at /_materials, 24 fps."""
    st = fu._stage(path, 24.0, 1, 1)
    for p in ("/Geo", "/Geo/Base_grp", "/Geo/Base_grp/Body_grp", "/Geo/Groom_grp", "/Geo/Groom_grp/HairDriver_grp"):
        UsdGeom.Xform.Define(st, p)
    st.SetDefaultPrim(st.GetPrimAtPath("/Geo"))
    UsdGeom.Scope.Define(st, "/_materials")
    mat = UsdShade.Material.Define(st, "/_materials/M_Body")
    for mesh_path, (pts, c, i) in {make_fake_shot.BODY: fu.grid(45, 45, 1.0, 1.0),
                                   "/Geo/Groom_grp/HairDriver_grp/Geo_HairBase": fu.grid(30, 30, 0.4, 1.7)}.items():
        m = UsdGeom.Mesh.Define(st, mesh_path)
        m.CreateFaceVertexCountsAttr(c)
        m.CreateFaceVertexIndicesAttr(i)
        m.CreatePointsAttr([tuple(map(float, p)) for p in pts])
        if good:
            m.CreateSubdivisionSchemeAttr("none")
        binding = UsdShade.MaterialBindingAPI.Apply(m.GetPrim())
        if good or mesh_path != make_fake_shot.BODY:
            binding.Bind(mat)
        else:
            binding.GetDirectBindingRel().SetTargets([Sdf.Path("/_materials/M_Missing")])
    if good:
        Usd.ModelAPI(st.GetPrimAtPath("/Geo")).SetKind("component")
    st.GetRootLayer().Save()


def new_scene() -> None:
    hou.hipFile.clear(suppress_save_prompt=True)
    hou.hda.installFile(str(OUT / "monofx_loader.hdalc"))  # after the clear: the hip's library list is replaced


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    make_fake_shot.main(ROOT)
    write_model(UV / "v001/char_Robot_uv_publish.usd", good=True)
    write_model(UV / "v002/char_Robot_uv_publish.usd", good=False)
    build_hda.build(str(OUT / "monofx_loader.hdalc"))

    new_scene()
    r = ppa.build("model", str(UV / "v001/char_Robot_uv_publish.usd"))
    print(r["note"])
    node = r["display"]
    check("model: a MonoFX Loader", node is not None and node.type().name() == config.HDA_TYPE,
          node.type().name() if node else None)
    check("model: on Source Asset at v001", node is not None and node.evalParm(config.P_SOURCE) == config.SOURCE_ASSET
          and node.evalParm(config.P_MODEL_VERSION) == "v001",
          (node.evalParm(config.P_SOURCE), node.evalParm(config.P_MODEL_VERSION)) if node else None)
    st = node.stage() if node else None
    check("model: body under /char_Robot", st is not None and bool(st.GetPrimAtPath(f"/char_Robot{make_fake_shot.BODY}")))
    check("model: with lookdev v002", "with lookdev v002" in r["note"], r["note"])
    check("model v001 reads clean", r["ok"], r["line"])
    check("model: line counts 2 meshes and kind", "2 meshes" in r["line"] and "kind component" in r["line"], r["line"])
    check("model: sticky note in /stage", hou.node("/stage").findStickyNote(ppa.NOTE_NAME) is not None)

    new_scene()
    r = ppa.build("model", str(UV / "v002/char_Robot_uv_publish.usd"))
    print(r["line"])
    check("model v002 has problems", not r["ok"], r["line"])
    check("model v002: broken binding found", "broken material binding" in r["line"] and "M_Missing" in r["note"],
          r["line"])
    check("model v002: meshes without subdivisionScheme", "2 meshes without subdivisionScheme" in r["line"], r["line"])
    check("model v002: kind not component", "not component" in r["note"], r["note"])

    new_scene()
    r = ppa.build("anim", str(ROOT / "02_shots/sh900/01_anim/publish/v002"))
    print(r["note"])
    loaders = [n for n in hou.node("/stage").children() if n.type().name() == config.HDA_TYPE]
    check("anim: a loader per output", len(loaders) == 4, [n.name() for n in loaders])
    check("anim: the shot merge is displayed", r["display"] is not None and r["display"].isDisplayFlagSet()
          and r["display"].type().name() == "merge", r["display"].path() if r["display"] else None)
    check("anim: timeline from publish_meta", hou.fps() == 24 and tuple(hou.playbar.frameRange()) == (1, 24),
          (hou.fps(), hou.playbar.frameRange()))
    check("anim: every file has time samples", "with time samples" in r["line"] and "no time samples" not in r["line"],
          r["line"])
    # the fake anim publish authors subdivisionScheme on one mesh of three, like publishes before v0.1.26
    check("anim: meshes without subdivisionScheme are named", "without subdivisionScheme" in r["line"], r["line"])
    st = r["display"].stage()
    check("anim: three characters in the stage", all(st.GetPrimAtPath(f"/{n}{make_fake_shot.BODY}")
                                                     for n in ("char_Robot", "char_Robot_inst02", "char_Robot_2")))

    new_scene()
    r = ppa.build("model", str(ROOT / "02_shots/sh900/01_anim/publish/v002/geo_char_Robot.usd"))
    check("a file the loader cannot read: plain Sublayer", r["display"] is not None
          and r["display"].type().name() == "sublayer", r["line"])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        check("no exception", False)
    (OUT / "accept.json").write_text(json.dumps(CHECKS, indent=2, default=str), encoding="utf-8")
    failed = [c["name"] for c in CHECKS if not c["ok"]]
    print(f"{len(CHECKS) - len(failed)}/{len(CHECKS)} passed", failed or "")
    sys.exit(1 if failed else 0)
