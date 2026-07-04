"""
Transform pipeline for MonoFX asset publish in Blender.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

import bpy

from . import config
from .logic import is_descendant_of


@dataclass
class ObjectBackup:
    obj_name: str
    parent: Optional[bpy.types.Object]
    location: "mathutils.Vector"
    rotation_mode: str
    rotation_euler: "mathutils.Euler"
    rotation_quaternion: "mathutils.Quaternion"
    scale: "mathutils.Vector"
    matrix_world: "mathutils.Matrix"
    data: Optional[object]


def _get_obj_by_name(name: str) -> Optional[bpy.types.Object]:
    try:
        return bpy.data.objects.get(name)
    except Exception:
        return None


def backup_object_transform(obj: bpy.types.Object) -> ObjectBackup:
    import mathutils

    return ObjectBackup(
        obj_name=obj.name,
        parent=obj.parent,
        location=obj.location.copy(),
        rotation_mode=obj.rotation_mode,
        rotation_euler=obj.rotation_euler.copy()
        if hasattr(obj, "rotation_euler")
        else mathutils.Euler((0.0, 0.0, 0.0)),
        rotation_quaternion=obj.rotation_quaternion.copy()
        if hasattr(obj, "rotation_quaternion")
        else mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)),
        scale=obj.scale.copy(),
        matrix_world=obj.matrix_world.copy(),
        data=obj.data,
    )


def isolate_object_data(obj: bpy.types.Object) -> Optional[object]:
    """
    Replace obj.data with a copy so transform_apply modifies only the copy.
    Returns the original data reference so caller can restore it.
    """
    data = getattr(obj, "data", None)
    if data is None:
        return None
    try:
        new_data = data.copy()
    except Exception:
        return None
    obj.data = new_data
    return data


def restore_object_state(backup: ObjectBackup, *, depsgraph_update: bool = True) -> None:
    obj = _get_obj_by_name(backup.obj_name)
    if obj is None:
        return

    # Restore world matrix only. Do NOT restore parent (publish must not touch parenting).
    obj.matrix_world = backup.matrix_world
    try:
        obj.rotation_mode = backup.rotation_mode
    except Exception:
        pass

    if backup.data is not None:
        try:
            obj.data = backup.data
        except Exception:
            pass

    if depsgraph_update:
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass


def _parent_depth(obj: bpy.types.Object) -> int:
    d = 0
    p = obj.parent
    while p is not None:
        d += 1
        p = p.parent
    return d


def restore_object_states_ordered(backups: Sequence[ObjectBackup]) -> None:
    """
    Restore saved matrix_world + data in a stable order: shallow objects (parents) first,
    then deeper descendants. Dict/set iteration order when backing up was undefined; this
    avoids inconsistent transforms after Restore.
    """
    blist = list(backups)

    def sort_key(b: ObjectBackup) -> tuple[int, str]:
        obj = _get_obj_by_name(b.obj_name)
        if obj is None:
            return (1_000_000, b.obj_name)
        return (_parent_depth(obj), b.obj_name)

    for b in sorted(blist, key=sort_key):
        restore_object_state(b, depsgraph_update=False)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


def _view_layer() -> bpy.types.ViewLayer:
    view_layer = bpy.context.view_layer
    if view_layer is None:
        raise RuntimeError("No active view layer.")
    return view_layer


def _deselect_all_objects(view_layer: bpy.types.ViewLayer) -> None:
    for obj in view_layer.objects:
        try:
            obj.select_set(False)
        except RuntimeError:
            pass


def _with_single_selection(obj: bpy.types.Object):
    view_layer = _view_layer()
    prev_active = view_layer.objects.active
    prev_selected = [o for o in bpy.context.selected_objects]
    _deselect_all_objects(view_layer)
    obj.select_set(True)
    view_layer.objects.active = obj
    return prev_active, prev_selected


def _restore_selection(prev_active: Optional[bpy.types.Object], prev_selected: List[bpy.types.Object]) -> None:
    try:
        view_layer = _view_layer()
        _deselect_all_objects(view_layer)
        for o in prev_selected:
            if o and o.name in bpy.data.objects:
                try:
                    o.select_set(True)
                except RuntimeError:
                    pass
        if prev_active and prev_active.name in bpy.data.objects:
            view_layer.objects.active = prev_active
    except Exception:
        pass


def apply_transforms_for_publish(
    asset_obj: bpy.types.Object,
    transform_targets: Iterable[bpy.types.Object],
) -> tuple[list[str], list[str]]:
    import mathutils

    # Reset Geo root location only; orientation is handled by USD export.
    asset_obj.location = mathutils.Vector((0.0, 0.0, 0.0))

    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    print(f"[MonoFX Pipeline] Geo root '{asset_obj.name}': reset location (orientation via USD export)")

    # Apply location/rotation only (no scale bake) to targets
    targets = [t for t in transform_targets if t is not None]
    if not targets:
        print("[MonoFX Pipeline] transform_apply: no targets (empty list)")
        return ([], [])

    print(f"[MonoFX Pipeline] transform_apply: {len(targets)} target(s): {', '.join(t.name for t in targets[:40])}{' …' if len(targets) > 40 else ''}")

    # transform_apply requires Object Mode.
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass

    applied: list[str] = []
    failed: list[str] = []

    # Apply per-object to avoid the entire operator cancelling due to one un-applicable object.
    for t in targets:
        # Skip linked/library objects (not editable).
        try:
            if getattr(t, "library", None) is not None:
                reason = f"{t.name} (linked)"
                failed.append(reason)
                print(f"[MonoFX Pipeline] transform_apply SKIP: {reason}")
                continue
        except Exception:
            pass

        # Applying transforms on a parent can change descendants. Preserve world matrices of
        # descendant targets (same list, top-down order) then restore after this apply.
        preserve_world: list[tuple[str, "mathutils.Matrix"]] = []
        for other in targets:
            if other is None or other is t:
                continue
            if not is_descendant_of(other, t):
                continue
            try:
                preserve_world.append((other.name, other.matrix_world.copy()))
            except Exception:
                pass

        prev_active, prev_selected = _with_single_selection(t)
        try:
            res = bpy.ops.object.transform_apply(location=True, rotation=True, scale=False)
            if "FINISHED" in set(res or []):
                applied.append(t.name)
                print(f"[MonoFX Pipeline] transform_apply OK: {t.name}")
            else:
                failed.append(t.name)
                print(f"[MonoFX Pipeline] transform_apply FAIL: {t.name} (return={res!r})")
        except Exception as ex:
            failed.append(t.name)
            print(f"[MonoFX Pipeline] transform_apply FAIL: {t.name} ({type(ex).__name__}: {ex})")
        finally:
            _restore_selection(prev_active, prev_selected)
            for name, mw in preserve_world:
                obj = _get_obj_by_name(name)
                if obj is None:
                    continue
                try:
                    obj.matrix_world = mw
                except Exception:
                    pass
            if preserve_world:
                try:
                    bpy.context.view_layer.update()
                except Exception:
                    pass

    print(f"[MonoFX Pipeline] transform_apply summary: applied={len(applied)}, failed={len(failed)}")
    return (applied, failed)


def usd_export(
    *,
    output_filepath: str,
    export_animation: bool,
    export_uvmaps: bool,
    export_normals: bool,
    export_materials: bool,
    export_lights: bool,
    export_cameras: bool,
    export_objects: Iterable[bpy.types.Object],
    convert_orientation: bool = config.DEFAULT_CONVERT_ORIENTATION,
    export_global_forward_selection: str = config.DEFAULT_EXPORT_FORWARD,
    export_global_up_selection: str = config.DEFAULT_EXPORT_UP,
    convert_scene_units: str = config.DEFAULT_CONVERT_SCENE_UNITS,
    root_prim_path: str = config.DEFAULT_USD_ROOT_PRIM_PATH,
    export_meshes: bool = True,
    evaluation_mode: str = "RENDER",
    merge_parent_xform: bool = True,
    generate_preview_surface: bool = config.DEFAULT_GENERATE_PREVIEW_SURFACE,
    generate_materialx_network: bool = config.DEFAULT_GENERATE_MATERIALX_NETWORK,
) -> None:
    import os

    export_objects = [o for o in export_objects if o is not None]
    if not export_objects:
        raise RuntimeError("No export objects found for USD export.")

    out_dir = os.path.dirname(output_filepath)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    view_layer = _view_layer()
    prev_active = view_layer.objects.active
    prev_selected = [o for o in bpy.context.selected_objects]
    try:
        _deselect_all_objects(view_layer)
        for o in export_objects:
            try:
                o.select_set(True)
            except RuntimeError:
                pass
        view_layer.objects.active = export_objects[0]

        # World→dome only if both export_lights and convert_world_material are True (Blender io_usd.cc).
        export_kwargs = dict(
            filepath=output_filepath,
            selected_objects_only=True,
            check_existing=True,
            export_animation=bool(export_animation),
            export_uvmaps=bool(export_uvmaps),
            export_normals=bool(export_normals),
            export_materials=bool(export_materials),
            export_subdivision="BEST_MATCH",
            export_armatures=True,
            convert_orientation=bool(convert_orientation),
            export_global_forward_selection=str(export_global_forward_selection),
            export_global_up_selection=str(export_global_up_selection),
            convert_scene_units=str(convert_scene_units),
            xform_op_mode="TRS",
            root_prim_path=str(root_prim_path or config.DEFAULT_USD_ROOT_PRIM_PATH),
            export_lights=bool(export_lights),
            export_cameras=bool(export_cameras),
            convert_world_material=False,
            author_blender_name=False,
            merge_parent_xform=bool(merge_parent_xform),
            evaluation_mode=str(evaluation_mode),
            export_meshes=bool(export_meshes),
            generate_preview_surface=bool(generate_preview_surface),
            generate_materialx_network=bool(generate_materialx_network),
        )
        try:
            bpy.ops.wm.usd_export(**export_kwargs)
        except TypeError:
            for key in (
                "export_meshes",
                "evaluation_mode",
                "generate_preview_surface",
                "generate_materialx_network",
            ):
                export_kwargs.pop(key, None)
            bpy.ops.wm.usd_export(**export_kwargs)
    finally:
        try:
            _deselect_all_objects(view_layer)
            for o in prev_selected:
                if o and o.name in bpy.data.objects:
                    try:
                        o.select_set(True)
                    except RuntimeError:
                        pass
            if prev_active and prev_active.name in bpy.data.objects:
                view_layer.objects.active = prev_active
        except Exception:
            pass

