"""
Focus linked rigs in the viewport and auto-select pose bones after link / scene selection.
"""

from __future__ import annotations

from typing import List, Optional

import bpy

from . import anim_pose
from . import rig_adapter

_focus_suppress = False
_last_focused_ref_id: Optional[str] = None


def is_suppressed() -> bool:
    return _focus_suppress


def suppress_focus() -> None:
    global _focus_suppress
    _focus_suppress = True


def release_focus_suppress() -> None:
    global _focus_suppress
    _focus_suppress = False


def schedule_release_suppress() -> None:
    def _clear() -> None:
        release_focus_suppress()
        return None

    try:
        bpy.app.timers.register(_clear, first_interval=0.0)
    except Exception:
        release_focus_suppress()


def should_apply(props) -> bool:
    return bool(props.rig_auto_focus)


def collect_auto_bone_names(armature: bpy.types.Object, props) -> List[str]:
    names: List[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if not name or name in seen:
            return
        if armature.pose.bones.get(name) is None:
            return
        names.append(name)
        seen.add(name)

    if props.rig_bone_pick_1:
        _add((props.rig_bone_pick_1_name or "").strip())
    if props.rig_bone_pick_2:
        _add((props.rig_bone_pick_2_name or "").strip())
    if props.rig_bone_pick_contains:
        pattern = (props.rig_bone_pick_contains_text or "").strip().casefold()
        if pattern:
            for pb in armature.pose.bones:
                if pattern in pb.name.casefold():
                    _add(pb.name)
    return names


def _deselect_all_pose_bones_in_scene() -> None:
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            anim_pose.deselect_all_pose_bones(obj)


def _deselect_rig(ref_id: str) -> None:
    for obj in rig_adapter.iter_rig_objects(ref_id):
        if obj.type == "ARMATURE":
            anim_pose.deselect_all_pose_bones(obj)
        try:
            obj.select_set(False)
        except Exception:
            pass


def _view_selected(context: bpy.types.Context) -> None:
    window = context.window
    if window is None:
        return
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        region = None
        for reg in area.regions:
            if reg.type == "WINDOW":
                region = reg
                break
        if region is None:
            continue
        try:
            with context.temp_override(window=window, area=area, region=region):
                bpy.ops.view3d.view_selected()
        except Exception:
            pass
        return


def _ensure_pose_mode(context: bpy.types.Context, armature: bpy.types.Object) -> None:
    if context.view_layer.objects.active != armature:
        context.view_layer.objects.active = armature
    if context.mode != "POSE":
        try:
            bpy.ops.object.mode_set(mode="POSE")
        except Exception:
            pass


def apply_rig_focus(
    context: bpy.types.Context,
    ref_id: str,
    props,
) -> bool:
    global _last_focused_ref_id

    view_layer = context.view_layer
    if view_layer is not None:
        try:
            view_layer.update()
        except Exception:
            pass

    armature = rig_adapter.find_rig_armature(ref_id, view_layer=view_layer)
    if armature is None:
        return False
    if view_layer is not None:
        try:
            if armature.name not in view_layer.objects:
                return False
        except Exception:
            return False

    if _last_focused_ref_id and _last_focused_ref_id != ref_id:
        _deselect_rig(_last_focused_ref_id)
    _last_focused_ref_id = ref_id

    try:
        bpy.ops.object.select_all(action="DESELECT")
    except Exception:
        pass
    anim_pose.deselect_all_pose_bones(armature)

    bone_names = collect_auto_bone_names(armature, props)
    if bone_names:
        try:
            view_layer.objects.active = armature
        except RuntimeError:
            return False
        _ensure_pose_mode(context, armature)
        anim_pose.select_pose_bones_by_name(armature, bone_names)
        active_pb = armature.pose.bones.get(bone_names[0])
        anim_pose.set_active_pose_bone(context, armature, active_pb)
        try:
            armature.select_set(False)
        except Exception:
            pass
    else:
        try:
            armature.select_set(True)
            view_layer.objects.active = armature
        except RuntimeError:
            return False
        if context.mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

    if props.rig_auto_focus:
        _view_selected(context)
    return True
