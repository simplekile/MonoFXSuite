"""
Rig publish: a cleaned copy of the rig work file for Anim > Link.

Writes ``<asset>/02_rigging/<NN_task>/publish/vNNN/<asset>_rig_publish.blend`` holding only the
rig's publish collection (``CHAR_ATA_RIG_PUBLISH``): Anim links that collection by its
``_publish`` name. The open file is never changed: the session is saved as a copy beside the
target (so relative paths stay right), then a background Blender cleans the copy (other
collections and scenes off, orphans purged, paths relative) and saves it under the final name.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import bpy
from bpy.types import Context, Operator

from . import publish_paths, ui_style

_PARTIAL_SUFFIX = ".partial"
_RESULT_TAG = "MONOFX_RIG_PUBLISH_RESULT "
_TIMEOUT_S = 900

# Runs inside ``blender -b <copy> --python-expr``; argv after ``--``: collection, final path.
_CLEANUP_SCRIPT = r'''
import bpy, json, sys
argv = sys.argv[sys.argv.index("--") + 1:]
coll_name, final_path = argv[0], argv[1]
pub = bpy.data.collections.get(coll_name)
if pub is None:
    raise SystemExit("publish collection missing in the copy: " + coll_name)
scene = None
for s in bpy.data.scenes:
    if pub in s.collection.children_recursive:
        scene = s
        break
scene = scene or bpy.context.scene
for s in list(bpy.data.scenes):
    if s != scene:
        bpy.data.scenes.remove(s)
root = scene.collection
for c in list(root.children):
    if c != pub:
        root.children.unlink(c)
if pub.name not in root.children:
    root.children.link(pub)
for o in list(root.objects):
    root.objects.unlink(o)
for t in bpy.data.texts:
    if t.use_module:
        t.use_fake_user = True
bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
try:
    bpy.ops.file.make_paths_relative()
except Exception:
    pass
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=final_path, relative_remap=True)
print("MONOFX_RIG_PUBLISH_RESULT " + json.dumps({
    "objects": len(pub.all_objects),
    "armatures": sum(1 for o in pub.all_objects if o.type == "ARMATURE"),
    "meshes": sum(1 for o in pub.all_objects if o.type == "MESH"),
}))
'''


@dataclass
class RigPublishPlan:
    ok: bool
    error: str = ""
    collection: str = ""
    armatures: List[str] = field(default_factory=list)
    publish_root: Optional[Path] = None
    version: str = ""
    out_path: Optional[Path] = None
    warnings: List[str] = field(default_factory=list)


def _publish_collections(scene: bpy.types.Scene) -> List[bpy.types.Collection]:
    return [
        c for c in scene.collection.children_recursive if publish_paths.is_publish_collection_name(c.name)
    ]


def plan_rig_publish(context: Context) -> RigPublishPlan:
    if not bpy.data.filepath:
        return RigPublishPlan(False, "Save the rig work file first.")
    scene_path = Path(bpy.data.filepath)
    root = publish_paths.resolve_rig_publish_root_from_scene(scene_path)
    if root is None:
        return RigPublishPlan(False, "Not a rig work file (…/02_rigging/<NN_task>/…).")
    colls = _publish_collections(context.scene)
    if not colls:
        return RigPublishPlan(False, "No publish collection (e.g. CHAR_ATA_RIG_PUBLISH).")
    if len(colls) > 1:
        names = ", ".join(c.name for c in colls)
        return RigPublishPlan(False, f"Several publish collections: {names}")
    coll = colls[0]
    arms = [o.name for o in coll.all_objects if o.type == "ARMATURE"]
    if not arms:
        return RigPublishPlan(False, f"No armature in {coll.name}.")
    version = publish_paths.next_version_name(root)
    out = root / version / f"{publish_paths.rig_publish_basename(scene_path)}.blend"
    warnings: List[str] = []
    if len(arms) > 1:
        warnings.append(f"{len(arms)} armatures in the publish collection")
    if coll.library is not None or coll.override_library is not None:
        warnings.append("The publish collection is linked")
    return RigPublishPlan(
        True,
        collection=coll.name,
        armatures=arms,
        publish_root=root,
        version=version,
        out_path=out,
        warnings=warnings,
    )


def _run_cleanup(partial: Path, coll_name: str, final: Path) -> dict:
    cmd = [
        bpy.app.binary_path,
        "-b",
        "--factory-startup",
        str(partial),
        "--python-exit-code",
        "3",
        "--python-expr",
        _CLEANUP_SCRIPT,
        "--",
        coll_name,
        str(final),
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT_S,
        creationflags=flags,
    )
    for line in (proc.stdout or "").splitlines():
        if line.startswith(_RESULT_TAG):
            return json.loads(line[len(_RESULT_TAG):])
    tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[-8:])
    raise RuntimeError(f"Cleaning the copy failed (exit {proc.returncode}):\n{tail}")


def publish_rig(context: Context) -> tuple[bool, str]:
    plan = plan_rig_publish(context)
    if not plan.ok or plan.out_path is None:
        return False, plan.error
    out = plan.out_path
    ver_dir = out.parent
    made_dir = not ver_dir.exists()
    partial = out.with_name(out.stem + _PARTIAL_SUFFIX)
    try:
        ver_dir.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(partial), copy=True, relative_remap=True)
        counts = _run_cleanup(partial, plan.collection, out)
    except Exception as e:
        if out.exists():
            try:
                out.unlink()
            except OSError:
                pass
        if made_dir:
            try:
                for p in ver_dir.iterdir():
                    p.unlink()
                ver_dir.rmdir()
            except OSError:
                pass
        return False, str(e)
    finally:
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass
    msg = (
        f"Published {plan.version}: {counts.get('objects', 0)} objects, "
        f"{counts.get('meshes', 0)} meshes, {counts.get('armatures', 0)} armature"
    )
    return True, msg


class MONOFX_OT_rig_publish(Operator):
    """Save a cleaned copy of the rig (only its publish collection) as the next rig publish version"""

    bl_idname = "wm.mono_fx_rig_publish"
    bl_label = "Publish Rig"
    bl_options = {"REGISTER"}

    def invoke(self, context: Context, _event) -> set[str]:
        plan = plan_rig_publish(context)
        if not plan.ok:
            self.report({"ERROR"}, plan.error)
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=420, confirm_text="Publish")

    def draw(self, context: Context) -> None:
        plan = plan_rig_publish(context)
        col = self.layout.column(align=True)
        if not plan.ok:
            ui_style.status_label(col, plan.error, ok=False)
            return
        col.label(text=f"Collection: {plan.collection}", icon="OUTLINER_COLLECTION")
        col.label(text=f"Armature: {', '.join(plan.armatures)}", icon="ARMATURE_DATA")
        col.label(text=f"{plan.version} / {plan.out_path.name}", icon="FILE_BLEND")
        col.separator()
        col.label(text="Other collections and scenes are left out.", icon="INFO")
        col.label(text="The open file is not changed.")
        for w in plan.warnings:
            ui_style.status_label(col, w, ok=False)

    def execute(self, context: Context) -> set[str]:
        wm = context.window_manager
        wm.progress_begin(0, 1)
        try:
            ok, msg = publish_rig(context)
        finally:
            wm.progress_end()
        props = context.scene.monofx_pipeline_blender_props
        props.rig_publish_status = msg
        props.rig_publish_ok = ok
        self.report({"INFO"} if ok else {"ERROR"}, msg)
        return {"FINISHED"} if ok else {"CANCELLED"}


class MONOFX_OT_rig_open_publish_folder(Operator):
    """Open the rig publish folder"""

    bl_idname = "wm.mono_fx_rig_open_publish_folder"
    bl_label = "Open Rig Publish Folder"
    bl_options = {"REGISTER"}

    def execute(self, context: Context) -> set[str]:
        if not bpy.data.filepath:
            self.report({"ERROR"}, "Save the rig work file first.")
            return {"CANCELLED"}
        root = publish_paths.resolve_rig_publish_root_from_scene(Path(bpy.data.filepath))
        if root is None:
            self.report({"ERROR"}, "Not a rig work file.")
            return {"CANCELLED"}
        versions = publish_paths.list_version_numbers(root)
        target = root / publish_paths.version_folder_from_number(versions[-1]) if versions else root
        if not target.is_dir():
            self.report({"ERROR"}, f"Folder does not exist yet: {root}")
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=str(target))
        return {"FINISHED"}


def draw_rig_publish(layout, context: Context) -> None:
    plan = plan_rig_publish(context)
    props = context.scene.monofx_pipeline_blender_props
    box = layout.box()
    col = box.column(align=True)
    if plan.ok:
        col.label(text=plan.collection, icon="OUTLINER_COLLECTION")
        col.label(text=", ".join(plan.armatures), icon="ARMATURE_DATA")
        col.label(text=f"Next: {plan.version} / {plan.out_path.name}", icon="FILE_TICK")
        for w in plan.warnings:
            ui_style.status_label(col, w, ok=False)
    else:
        ui_style.status_label(col, plan.error, ok=False)
    if props.rig_publish_status:
        ui_style.status_label(layout, props.rig_publish_status, ok=bool(props.rig_publish_ok))
    layout.separator()
    row = layout.row(align=True)
    row.scale_y = 1.55
    main = row.row(align=True)
    main.enabled = plan.ok
    main.operator("wm.mono_fx_rig_publish", text="PUBLISH RIG", icon=ui_style.ICON_PUBLISH)
    row.operator("wm.mono_fx_rig_open_publish_folder", text="", icon=ui_style.ICON_FOLDER)


CLASSES = (
    MONOFX_OT_rig_publish,
    MONOFX_OT_rig_open_publish_folder,
)
