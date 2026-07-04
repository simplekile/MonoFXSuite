"""Camera rig pose decomposition (pure math, no bpy)."""

from __future__ import annotations

from typing import Tuple

from mathutils import Quaternion, Vector


def _cam_rotation_as_quaternion(cam_rotation) -> Quaternion:
    if isinstance(cam_rotation, Quaternion):
        return cam_rotation.normalized()
    return cam_rotation.to_quaternion().normalized()


def compute_head_rotation_euler_from_camera(
    cam_location: Vector,
    cam_rotation,
    aim_location: Vector,
    *,
    track_aim: bool = True,
) -> Tuple[float, float, float]:
    """
    Head (motion) local XYZ euler from a camera world pose.

    With Track Aim, boom TRACK_TO handles look-at; residual pan / tilt / roll
    (mostly roll / dutch) stay on the head. Without Track Aim, the full camera
    rotation is written to the head.
    """
    cam_quat = _cam_rotation_as_quaternion(cam_rotation)
    if track_aim:
        direction = aim_location - cam_location
        if direction.length < 1e-8:
            return (0.0, 0.0, 0.0)
        track_quat = direction.to_track_quat("-Z", "Y")
        head_quat = track_quat.inverted() @ cam_quat
    else:
        head_quat = cam_quat
    head_euler = head_quat.to_euler("XYZ")
    return (float(head_euler.x), float(head_euler.y), float(head_euler.z))
