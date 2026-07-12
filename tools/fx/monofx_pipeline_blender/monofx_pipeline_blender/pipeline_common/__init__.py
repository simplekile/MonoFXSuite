"""Blender-only pipeline helpers (requires mathutils)."""

from .camera_rig_pose import compute_head_rotation_euler_from_camera

__all__ = ["compute_head_rotation_euler_from_camera"]
