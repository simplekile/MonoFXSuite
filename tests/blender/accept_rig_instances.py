"""Rig instances: link, remove and anim USD prim names. Needs Blender; not collected by pytest.

blender -b --factory-startup --python-exit-code 1 --python tests/blender/accept_rig_instances.py -- <out_dir>

Builds a rig publish whose names collide as in sh014 / sh015 / sh017 (/Geo_Whale_001 in the
anim USD) and checks what the anim cache writes for one and for several instances.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
from pxr import Usd

SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "tools/fx/monofx_pipeline_blender"))

import monofx_pipeline_blender  # noqa: E402
from monofx_pipeline_blender import rig_adapter  # noqa: E402
from monofx_pipeline_blender.anim_usd_cache_exporter import (  # noqa: E402
    UsdAnimCacheExportSession,
)

assert Path(monofx_pipeline_blender.__file__).resolve().is_relative_to(SUITE)

OUT = Path(sys.argv[sys.argv.index("--") + 1])
ASSET = "char_Whale"
PUBLISH = "CHAR_WHALE_RIG_PUBLISH"
RIG = (
    OUT / "proj/01_assets/_characters" / ASSET
    / "02_rigging/02_build_rig/publish/v001/char_Whale_rig_publish.blend"
)
GOOD = {"/Geo_Whale", "/Geo_Whale/Geo_Pants_001", "/Geo_Whale/Geo_Top"}
FAILED: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def build_rig() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root = bpy.data.collections.new(PUBLISH)
    bpy.context.scene.collection.children.link(root)
    geo = bpy.data.collections.new("Geo")
    rig = bpy.data.collections.new("rig")
    root.children.link(geo)
    root.children.link(rig)
    arm = bpy.data.objects.new("Armature", bpy.data.armatures.new("Armature"))
    rig.objects.link(arm)
    grp = bpy.data.objects.new("Geo_Whale", None)
    geo.objects.link(grp)
    mat = bpy.data.materials.new("M")
    for name in ("Geo_Top", "Geo_Pants.001"):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        mesh.materials.append(mat)
        obj = bpy.data.objects.new(name, mesh)
        obj.parent = grp
        obj.modifiers.new("Armature", "ARMATURE").object = arm
        geo.objects.link(obj)
    RIG.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(RIG))


def shot(*collections: str) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for name in collections:
        bpy.context.scene.collection.children.link(bpy.data.collections.new(name))


def link(collection: str) -> str:
    vl = bpy.context.view_layer
    vl.active_layer_collection = vl.layer_collection.children[collection]
    return rig_adapter.create_file_reference(str(RIG), ASSET)


def local_objects() -> list[str]:
    return sorted(o.name for o in bpy.data.objects if o.library is None)


def tree_meshes(ref_id: str) -> list[bpy.types.Object]:
    coll = rig_adapter._override_for_ref(ref_id)
    return sorted((o for o in coll.all_objects if o.type == "MESH"), key=lambda o: o.name)


def export(name: str, meshes: list[bpy.types.Object]) -> set[str]:
    path = OUT / f"{name}.usd"
    session = UsdAnimCacheExportSession(
        bpy.context, str(path), frame_start=1, frame_end=2, fps=24.0,
        mesh_objects=meshes, export_camera=False, write_publish_meta=False,
    )
    err = session.begin()
    while not err and not session.done:
        err = session.step(units_per_tick=8)
    result = session.finish()
    check(f"{name} exported", not err and result.ok, err or result.error)
    layer = Usd.Stage.Open(str(path))
    layer.Reload()
    return {str(p.GetPath()) for p in layer.Traverse()}


build_rig()
monofx_pipeline_blender.register()

# One rig whose override Blender renamed (what sh015 v003 holds).
shot("Characters")
ref = link("Characters")
bpy.data.objects["whalerig::Geo_Whale"].name = "whalerig::Geo_Whale.001"
got = export("suffixed", tree_meshes(ref))
check("suffixed override exports the rig's names", got == GOOD, sorted(got))

# Two instances in one collection.
shot("Characters")
a, b = link("Characters"), link("Characters")
got = export("same_a", tree_meshes(a))
check("same collection: one file each, first", got == GOOD, sorted(got))
got = export("same_b", tree_meshes(b))
check("same collection: one file each, second", got == GOOD, sorted(got))
merged = {p for ns in ("/whalerig", "/whalerig2") for p in {ns} | {ns + g for g in GOOD}}
got = export("same_merged", tree_meshes(a) + tree_meshes(b))
check("same collection: merged keeps both apart", got == merged, sorted(got))

# Two instances in different collections.
shot("Characters", "Background")
a, b = link("Characters"), link("Background")
names = [o.name for o in tree_meshes(b)]
check(
    "different collections: second instance has its own namespace",
    all(n.startswith("whalerig2::") for n in names),
    names,
)
got = export("diff_b", tree_meshes(b))
check("different collections: one file each, second", got == GOOD, sorted(got))
got = export("diff_merged", tree_meshes(a) + tree_meshes(b))
check("different collections: merged keeps both apart", got == merged, sorted(got))

# A file linked before the fix: the second instance suffixed in the same namespace.
shot("Characters", "Background")
a, b = link("Characters"), link("Background")
for obj in rig_adapter._override_for_ref(b).all_objects:
    if obj.type != "ARMATURE":
        obj.name = obj.name.replace("whalerig2::", "whalerig::")
got = export("old_b", tree_meshes(b))
check("old file: one file each, second", got == GOOD, sorted(got))
got = export("old_merged", tree_meshes(a) + tree_meshes(b))
check(
    "old file: merged keeps the second root's name",
    {p for p in got if p.count("/") == 1} == {"/Geo_Whale", "/Geo_Whale_001"},
    sorted(got),
)

# Remove leaves nothing behind, so linking again gets the plain names.
PLAIN = ["Armature", "whalerig::Geo_Pants.001", "whalerig::Geo_Top", "whalerig::Geo_Whale"]
shot("Characters")
ref = link("Characters")
rig_adapter.remove_file_reference(ref)
check("remove leaves no objects", local_objects() == [], local_objects())
left = sorted(c.name for c in bpy.data.collections if c.library is None)
check("remove leaves no collections", left == ["Characters"], left)
libs = [x.name for x in bpy.data.libraries]
check("remove drops the library", not libs, libs)
link("Characters")
check("link after remove has the plain names", local_objects() == PLAIN, local_objects())

# Remove one of two: the other is untouched.
shot("Characters", "Background")
a, b = link("Characters"), link("Background")
kept = sorted(o.name for o in rig_adapter._override_for_ref(b).all_objects)
rig_adapter.remove_file_reference(a)
check("remove first keeps the second", local_objects() == kept, local_objects())
got = export("kept", tree_meshes(b))
check("second still exports", got == GOOD, sorted(got))

# The artist's own objects stay, with the linked data they use.
shot("Characters")
ref = link("Characters")
mesh = bpy.data.meshes.new("mine")
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
mesh.materials.append(bpy.data.objects["whalerig::Geo_Top"].data.materials[0])
mine = bpy.data.objects.new("mine", mesh)
bpy.data.collections["Characters"].objects.link(mine)
mine.parent = bpy.data.objects["whalerig::Geo_Whale"]
rig_adapter.remove_file_reference(ref)
check("remove keeps the artist's objects", local_objects() == ["mine"], local_objects())
mat = mesh.materials[0] if len(mesh.materials) else None
check(
    "remove keeps linked data the artist's objects use",
    mat is not None and mat.library is not None,
    mat,
)

print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
sys.exit(1 if FAILED else 0)
