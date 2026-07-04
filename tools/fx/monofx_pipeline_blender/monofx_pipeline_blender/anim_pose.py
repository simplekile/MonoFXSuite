"""
Pose-bone helpers compatible with Blender 4.x and 5.x.
"""

from __future__ import annotations

from typing import Iterable, Optional

import bpy


def set_pose_bone_selected(pb: bpy.types.PoseBone, selected: bool) -> None:
    """Set pose-bone selection (Blender 5+: ``PoseBone.select``)."""
    if pb is None:
        return
    if hasattr(pb, "select"):
        pb.select = bool(selected)
        return
    bone = getattr(pb, "bone", None)
    if bone is not None and hasattr(bone, "select"):
        bone.select = bool(selected)


def deselect_all_pose_bones(armature: bpy.types.Object) -> None:
    if armature is None or armature.type != "ARMATURE":
        return
    for pb in armature.pose.bones:
        set_pose_bone_selected(pb, False)


def select_pose_bones_by_name(
    armature: bpy.types.Object,
    names: Iterable[str],
) -> int:
    count = 0
    for name in names:
        pb = armature.pose.bones.get(name)
        if pb is None:
            continue
        set_pose_bone_selected(pb, True)
        count += 1
    return count


def set_active_pose_bone(
    context: bpy.types.Context,
    armature: bpy.types.Object,
    pb: Optional[bpy.types.PoseBone],
) -> None:
    if pb is None or armature is None:
        return
    set_pose_bone_selected(pb, True)
    try:
        armature.data.bones.active = pb.bone
    except Exception:
        pass
    try:
        context.view_layer.objects.active = armature
    except Exception:
        pass
