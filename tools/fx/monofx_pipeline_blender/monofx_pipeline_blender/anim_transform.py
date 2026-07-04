"""
World-transform clipboard for animation tools (objects and pose bones).
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import bpy

_clipboard_matrix: Optional["bpy.types.Matrix"] = None
_clipboard_source: str = ""


def has_world_transform_clipboard() -> bool:
    return _clipboard_matrix is not None


def clipboard_source_name() -> str:
    return _clipboard_source


def can_paste_world_transform(context: bpy.types.Context) -> bool:
    if not has_world_transform_clipboard():
        return False
    if context.mode == "POSE" and context.selected_pose_bones:
        return True
    return bool(context.selected_objects)


def _evaluated_world_matrix(
    context: bpy.types.Context,
    obj: bpy.types.Object,
) -> "bpy.types.Matrix":
    depsgraph = context.evaluated_depsgraph_get()
    return obj.evaluated_get(depsgraph).matrix_world.copy()


def _pose_bone_world_matrix(
    context: bpy.types.Context,
    armature: bpy.types.Object,
    pb: bpy.types.PoseBone,
) -> "bpy.types.Matrix":
    depsgraph = context.evaluated_depsgraph_get()
    eval_arm = armature.evaluated_get(depsgraph)
    eval_pb = eval_arm.pose.bones.get(pb.name)
    if eval_pb is None:
        return armature.matrix_world @ pb.matrix
    return eval_arm.matrix_world @ eval_pb.matrix


def copy_world_transform(context: bpy.types.Context) -> Tuple[bool, str]:
    global _clipboard_matrix, _clipboard_source

    if context.mode == "POSE":
        pb = context.active_pose_bone
        armature = context.active_object
        if pb is None or armature is None or armature.type != "ARMATURE":
            return False, "No active pose bone."
        _clipboard_matrix = _pose_bone_world_matrix(context, armature, pb)
        _clipboard_source = f"{armature.name}/{pb.name}"
        return True, f"Copied world transform from {_clipboard_source}"

    obj = context.active_object
    if obj is None:
        return False, "No active object."

    _clipboard_matrix = _evaluated_world_matrix(context, obj)
    _clipboard_source = obj.name
    return True, f"Copied world transform from {obj.name}"


def _paste_pose_bone_world_matrix(
    armature: bpy.types.Object,
    pb: bpy.types.PoseBone,
    world_matrix: "bpy.types.Matrix",
) -> bool:
    try:
        pb.matrix = armature.matrix_world.inverted() @ world_matrix
        return True
    except Exception:
        return False


def _paste_to_pose_bones(
    pose_bones: Sequence[bpy.types.PoseBone],
    world_matrix: "bpy.types.Matrix",
) -> Tuple[bool, str, int]:
    count = 0
    for pb in pose_bones:
        armature = pb.id_data
        if armature is None or armature.type != "ARMATURE":
            continue
        if _paste_pose_bone_world_matrix(armature, pb, world_matrix):
            count += 1

    if count == 0:
        return False, "Could not paste world transform to pose bone(s).", 0
    return True, f"Pasted world transform to {count} pose bone(s).", count


def _paste_to_objects(
    objects: Sequence[bpy.types.Object],
    world_matrix: "bpy.types.Matrix",
) -> Tuple[bool, str, int]:
    count = 0
    for obj in objects:
        try:
            obj.matrix_world = world_matrix
            count += 1
        except Exception:
            pass

    if count == 0:
        return False, "Could not paste world transform.", 0
    return True, f"Pasted world transform to {count} object(s).", count


def paste_world_transform(context: bpy.types.Context) -> Tuple[bool, str, int]:
    if _clipboard_matrix is None:
        return False, "Nothing copied. Use Copy World Transform first.", 0

    matrix = _clipboard_matrix.copy()

    if context.mode == "POSE" and context.selected_pose_bones:
        return _paste_to_pose_bones(context.selected_pose_bones, matrix)

    if not context.selected_objects:
        return False, "No objects or pose bones selected.", 0
    return _paste_to_objects(context.selected_objects, matrix)
