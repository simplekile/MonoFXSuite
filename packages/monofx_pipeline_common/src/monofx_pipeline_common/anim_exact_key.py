"""
Exact keyframe edit helpers (no bpy).
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

_AXIS_LABELS: Sequence[str] = ("X", "Y", "Z", "W")


def fcurve_channel_label(data_path: Optional[str], array_index: int) -> str:
    """Human-readable channel label for an F-Curve."""
    path = (data_path or "").strip() or "<channel>"
    if 0 <= int(array_index) < len(_AXIS_LABELS):
        return f"{path} [{_AXIS_LABELS[int(array_index)]}]"
    return f"{path} [{int(array_index)}]"


def apply_keyframe_value_delta(
    old_value: float,
    new_value: float,
    handle_left_y: float,
    handle_right_y: float,
) -> Tuple[float, float, float]:
    """
    Return ``(new_value, new_handle_left_y, new_handle_right_y)`` preserving
    handle vertical offsets relative to the key value.
    """
    delta = float(new_value) - float(old_value)
    return (
        float(new_value),
        float(handle_left_y) + delta,
        float(handle_right_y) + delta,
    )


def apply_keyframe_frame_delta(
    old_frame: float,
    new_frame: float,
    handle_left_x: float,
    handle_right_x: float,
) -> Tuple[float, float, float]:
    """
    Return ``(new_frame, new_handle_left_x, new_handle_right_x)`` preserving
    handle horizontal offsets relative to the key frame.
    """
    delta = float(new_frame) - float(old_frame)
    return (
        float(new_frame),
        float(handle_left_x) + delta,
        float(handle_right_x) + delta,
    )
