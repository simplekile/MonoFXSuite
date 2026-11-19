"""Anim USD cache subdivisionScheme acceptance. Needs Blender; not collected by pytest.

blender -b --factory-startup --python-exit-code 1 --python tests/blender/accept_anim_usd_subdiv.py -- <out_dir>

Exports a few animated cubes through UsdAnimCacheExportSession and checks every Mesh
authors subdivisionScheme (none unless a render Subdivision ends the stack), that the
points under catmullClark are the cage, and that Subdivisions are switched back on.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
from pxr import Usd, UsdGeom

SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "tools/fx/monofx_pipeline_blender"))

import monofx_pipeline_blender  # noqa: E402
from monofx_pipeline_blender.anim_usd_cache_exporter import (  # noqa: E402
    UsdAnimCacheExportSession,
)

OUT = Path(sys.argv[sys.argv.index("--") + 1])
FAILED: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def cube(name: str, x: float, mods: list[tuple[str, bool, bool, int]]) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=(x, 0.0, 0.0))
    obj = bpy.context.object
    obj.name = name
    obj.keyframe_insert("location", frame=1)
    obj.location.z = 2.0
    obj.keyframe_insert("location", frame=3)
    for kind, viewport, render, levels in mods:
        mod = obj.modifiers.new(kind.lower(), kind)
        mod.show_viewport = viewport
        mod.show_render = render
        if kind == "SUBSURF":
            mod.levels = levels
    return obj


bpy.ops.wm.read_factory_settings(use_empty=True)
monofx_pipeline_blender.register()  # the session reads the add-on's scene props
objs = [
    cube("Plain", 0, []),
    cube("SubOn", 3, [("SUBSURF", True, True, 2)]),
    cube("SubRenderOnly", 6, [("SUBSURF", False, True, 1)]),
    cube("SubViewOnly", 9, [("SUBSURF", True, False, 1)]),
    cube("SubThenBevel", 12, [("SUBSURF", True, True, 1), ("BEVEL", True, True, 0)]),
    cube("Multires", 15, [("MULTIRES", True, True, 0)]),
]
EXPECTED = {
    "Plain": ("none", 8),
    "SubOn": ("catmullClark", 8),
    "SubRenderOnly": ("catmullClark", 8),
    "SubViewOnly": ("none", 26),  # viewport Subdivision baked in, level 1
    "SubThenBevel": ("none", None),
    "Multires": ("none", 8),
}

OUT.mkdir(parents=True, exist_ok=True)
path = OUT / "subdiv_anim.usd"
session = UsdAnimCacheExportSession(
    bpy.context,
    str(path),
    frame_start=1,
    frame_end=3,
    fps=24.0,
    mesh_objects=objs,
    export_camera=False,
    write_publish_meta=False,
)
err = session.begin()
check("begin", err is None, err)
while not session.done:
    err = session.step(units_per_tick=8)
    if err:
        check("step", False, err)
        break
result = session.finish()
check("finish", result.ok, result.error)

stage = Usd.Stage.Open(str(path))
for prim in stage.Traverse():
    if prim.IsA(UsdGeom.Mesh):
        mesh = UsdGeom.Mesh(prim)
        attr = mesh.GetSubdivisionSchemeAttr()
        check(f"{prim.GetPath()} scheme authored", attr.HasAuthoredValue())
        check(f"{prim.GetPath()} scheme not time sampled", attr.GetNumTimeSamples() == 0)

meshes = {
    p.GetName(): UsdGeom.Mesh(p) for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)
}
for name, (scheme, n_points) in EXPECTED.items():
    match = [m for key, m in meshes.items() if key.startswith(name)]
    check(f"{name} exported", len(match) == 1, sorted(meshes))
    if len(match) != 1:
        continue
    mesh = match[0]
    check(f"{name} scheme", mesh.GetSubdivisionSchemeAttr().Get() == scheme,
          mesh.GetSubdivisionSchemeAttr().Get())
    if n_points is not None:
        pts = mesh.GetPointsAttr().Get(Usd.TimeCode(1))
        check(f"{name} points", len(pts) == n_points, len(pts))
    check(f"{name} points animated", mesh.GetPointsAttr().GetNumTimeSamples() >= 2,
          mesh.GetPointsAttr().GetNumTimeSamples())

sub_on = bpy.data.objects["SubOn"].modifiers[0]
check("SubOn Subdivision back on in viewport", sub_on.show_viewport)
check("SubRenderOnly left off in viewport",
      not bpy.data.objects["SubRenderOnly"].modifiers[0].show_viewport)

print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
sys.exit(1 if FAILED else 0)
