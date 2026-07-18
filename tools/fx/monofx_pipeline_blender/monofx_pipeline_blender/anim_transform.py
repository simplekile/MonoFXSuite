"""
World-transform clipboard for animation tools (objects and pose bones).

Copy stores the visual (evaluated) world matrix; paste applies it to the
selection.

When the paste target has constraints, channels are solved from the measured
offset between the channel world (matrix_basis + Blender parent) and the
evaluated visual world:

    visual ≈ offset @ channel
    channel_new = channel @ visual.inverted() @ target

Pasting onto a Child Of *target* only writes that object/bone — dependents
follow through normal constraint evaluation after depsgraph refresh.
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
    if _clipboard_matrix is None:
        return False
    if context.mode == "POSE" and context.selected_pose_bones:
        return True
    return bool(context.selected_objects)


def _force_depsgraph_update(context: bpy.types.Context) -> bpy.types.Depsgraph:
    """Refresh evaluation so constraints see newly written transforms."""
    scene = context.scene
    # frame_set is more reliable than depsgraph.update alone for constraints
    scene.frame_set(scene.frame_current)
    return context.evaluated_depsgraph_get()


def _constraint_is_active(constraint: bpy.types.Constraint) -> bool:
    if constraint.mute:
        return False
    if getattr(constraint, "influence", 1.0) <= 0.0:
        return False
    if hasattr(constraint, "enabled") and not constraint.enabled:
        return False
    return True


def _pose_bone_has_active_constraints(pb: bpy.types.PoseBone) -> bool:
    return any(_constraint_is_active(c) for c in pb.constraints)


def _object_has_active_constraints(obj: bpy.types.Object) -> bool:
    return any(_constraint_is_active(c) for c in obj.constraints)


def _matrices_close(
    left: "bpy.types.Matrix",
    right: "bpy.types.Matrix",
    *,
    location_eps: float = 1e-4,
    angle_eps: float = 1e-3,
) -> bool:
    try:
        delta = left @ right.inverted_safe()
    except Exception:
        return False
    if delta.translation.length > location_eps:
        return False
    return abs(delta.to_quaternion().angle) <= angle_eps


def _channel_for_target_world(
    channel_world: "bpy.types.Matrix",
    visual_world: "bpy.types.Matrix",
    target_world: "bpy.types.Matrix",
) -> "bpy.types.Matrix":
    """Solve channel so visual matches target, given visual ≈ offset @ channel."""
    return channel_world @ visual_world.inverted_safe() @ target_world


def _world_to_pose_matrix(
    armature: bpy.types.Object,
    pb: bpy.types.PoseBone,
    world_matrix: "bpy.types.Matrix",
) -> "bpy.types.Matrix":
    return armature.convert_space(
        pose_bone=pb,
        matrix=world_matrix,
        from_space="WORLD",
        to_space="POSE",
    )


def _object_real_world(
    context: bpy.types.Context,
    obj: bpy.types.Object,
) -> "bpy.types.Matrix":
    depsgraph = _force_depsgraph_update(context)
    return obj.evaluated_get(depsgraph).matrix_world.copy()


def _object_channel_world(
    context: bpy.types.Context,
    obj: bpy.types.Object,
) -> "bpy.types.Matrix":
    """World from matrix_basis + Blender parent only (no object constraints)."""
    basis = obj.matrix_basis.copy()
    parent = obj.parent
    if parent is None:
        return basis

    depsgraph = context.evaluated_depsgraph_get()
    parent_mw = parent.evaluated_get(depsgraph).matrix_world.copy()
    return parent_mw @ obj.matrix_parent_inverse @ basis


def _set_object_channel_world(
    obj: bpy.types.Object,
    channel_world: "bpy.types.Matrix",
) -> None:
    # Prefer matrix_basis when unparented so deltas/constraints aren't confused
    # with assigning a (possibly constrained-looking) matrix_world.
    if obj.parent is None:
        obj.matrix_basis = channel_world
    else:
        obj.matrix_world = channel_world


def _pose_bone_channel_pose_matrix(
    pb: bpy.types.PoseBone,
) -> "bpy.types.Matrix":
    bone = pb.bone
    basis = pb.matrix_basis.copy()
    if pb.parent is not None:
        return bone.convert_local_to_pose(
            basis,
            bone.matrix_local,
            parent_matrix=pb.parent.matrix.copy(),
            parent_matrix_local=pb.parent.bone.matrix_local,
        )
    return bone.convert_local_to_pose(basis, bone.matrix_local)


def _pose_bone_channel_world(
    context: bpy.types.Context,
    armature: bpy.types.Object,
    pb: bpy.types.PoseBone,
) -> "bpy.types.Matrix":
    depsgraph = context.evaluated_depsgraph_get()
    arm_mw = armature.evaluated_get(depsgraph).matrix_world.copy()
    return arm_mw @ _pose_bone_channel_pose_matrix(pb)


def _pose_bone_real_world(
    context: bpy.types.Context,
    armature: bpy.types.Object,
    pb: bpy.types.PoseBone,
) -> "bpy.types.Matrix":
    depsgraph = _force_depsgraph_update(context)
    eval_arm = armature.evaluated_get(depsgraph)
    eval_pb = eval_arm.pose.bones.get(pb.name)
    if eval_pb is None:
        return eval_arm.matrix_world @ pb.matrix.copy()
    return eval_arm.matrix_world @ eval_pb.matrix.copy()


def copy_world_transform(context: bpy.types.Context) -> Tuple[bool, str]:
    global _clipboard_matrix, _clipboard_source

    if context.mode == "POSE":
        pb = context.active_pose_bone
        armature = context.active_object
        if pb is None or armature is None or armature.type != "ARMATURE":
            return False, "No active pose bone."
        world_matrix = _pose_bone_real_world(context, armature, pb)
        _clipboard_source = f"{armature.name}/{pb.name}"
    else:
        obj = context.active_object
        if obj is None:
            return False, "No active object."
        world_matrix = _object_real_world(context, obj)
        _clipboard_source = obj.name

    _clipboard_matrix = world_matrix.copy()
    return True, f"Copied world transform from {_clipboard_source}"


def _set_pose_bone_channel_world(
    armature: bpy.types.Object,
    pb: bpy.types.PoseBone,
    channel_world: "bpy.types.Matrix",
) -> None:
    pb.matrix = _world_to_pose_matrix(armature, pb, channel_world)


def _paste_pose_bone_world_matrix(
    context: bpy.types.Context,
    armature: bpy.types.Object,
    pb: bpy.types.PoseBone,
    target_world: "bpy.types.Matrix",
    *,
    max_iters: int = 12,
) -> bool:
    if not _pose_bone_has_active_constraints(pb):
        try:
            _set_pose_bone_channel_world(armature, pb, target_world)
            _force_depsgraph_update(context)
            return True
        except Exception:
            return False

    for _ in range(max_iters):
        channel = _pose_bone_channel_world(context, armature, pb)
        visual = _pose_bone_real_world(context, armature, pb)
        if _matrices_close(visual, target_world):
            return True
        try:
            _set_pose_bone_channel_world(
                armature,
                pb,
                _channel_for_target_world(channel, visual, target_world),
            )
        except Exception:
            return False
        _force_depsgraph_update(context)

    return _matrices_close(
        _pose_bone_real_world(context, armature, pb),
        target_world,
    )


def _paste_to_pose_bones(
    context: bpy.types.Context,
    pose_bones: Sequence[bpy.types.PoseBone],
    world_matrix: "bpy.types.Matrix",
) -> Tuple[bool, str, int]:
    count = 0
    for pb in pose_bones:
        armature = pb.id_data
        if armature is None or armature.type != "ARMATURE":
            continue
        if _paste_pose_bone_world_matrix(context, armature, pb, world_matrix):
            count += 1

    if count == 0:
        return False, "Could not paste world transform to pose bone(s).", 0
    return True, f"Pasted world transform to {count} pose bone(s).", count


def _paste_object_world_matrix(
    context: bpy.types.Context,
    obj: bpy.types.Object,
    target_world: "bpy.types.Matrix",
    *,
    max_iters: int = 12,
) -> bool:
    if not _object_has_active_constraints(obj):
        try:
            _set_object_channel_world(obj, target_world)
            _force_depsgraph_update(context)
            return True
        except Exception:
            return False

    for _ in range(max_iters):
        channel = _object_channel_world(context, obj)
        visual = _object_real_world(context, obj)
        if _matrices_close(visual, target_world):
            return True
        try:
            _set_object_channel_world(
                obj,
                _channel_for_target_world(channel, visual, target_world),
            )
        except Exception:
            return False
        _force_depsgraph_update(context)

    return _matrices_close(_object_real_world(context, obj), target_world)


def _paste_to_objects(
    context: bpy.types.Context,
    objects: Sequence[bpy.types.Object],
    world_matrix: "bpy.types.Matrix",
) -> Tuple[bool, str, int]:
    count = 0
    for obj in objects:
        if _paste_object_world_matrix(context, obj, world_matrix):
            count += 1

    if count == 0:
        return False, "Could not paste world transform.", 0
    return True, f"Pasted world transform to {count} object(s).", count


def paste_world_transform(context: bpy.types.Context) -> Tuple[bool, str, int]:
    if _clipboard_matrix is None:
        return False, "World transform clipboard is empty.", 0

    matrix = _clipboard_matrix.copy()

    if context.mode == "POSE" and context.selected_pose_bones:
        return _paste_to_pose_bones(context, context.selected_pose_bones, matrix)

    if not context.selected_objects:
        return False, "No objects or pose bones selected.", 0
    return _paste_to_objects(context, context.selected_objects, matrix)
