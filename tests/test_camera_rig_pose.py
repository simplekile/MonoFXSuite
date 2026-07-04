"""Head rotation decomposition for camera rig setup / bake."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

pytest.importorskip("mathutils")
from mathutils import Euler, Vector  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN_COMMON = (
    _ROOT
    / "tools"
    / "fx"
    / "monofx_pipeline_blender"
    / "monofx_pipeline_blender"
    / "pipeline_common"
)
if str(_PLUGIN_COMMON) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_COMMON))

from camera_rig_pose import compute_head_rotation_euler_from_camera  # noqa: E402


def test_track_aim_residual_roll_on_head_z() -> None:
    cam_loc = Vector((0.0, 0.0, 1.5))
    aim_loc = Vector((0.0, -10.0, 1.5))
    roll_rad = math.radians(30.0)

    direction = aim_loc - cam_loc
    track_quat = direction.to_track_quat("-Z", "Y")
    cam_quat = track_quat @ Euler((0.0, 0.0, roll_rad), "XYZ").to_quaternion()

    tilt, pan, roll = compute_head_rotation_euler_from_camera(
        cam_loc,
        cam_quat,
        aim_loc,
        track_aim=True,
    )
    assert abs(tilt) < 1e-4
    assert abs(pan) < 1e-4
    assert abs(roll - roll_rad) < 1e-4


def test_no_track_aim_writes_full_rotation_to_head() -> None:
    cam_loc = Vector((1.0, 2.0, 3.0))
    aim_loc = Vector((1.0, -7.0, 3.0))
    cam_euler = Euler((0.2, -0.4, 0.6), "XYZ")

    tilt, pan, roll = compute_head_rotation_euler_from_camera(
        cam_loc,
        cam_euler,
        aim_loc,
        track_aim=False,
    )
    assert abs(tilt - 0.2) < 1e-4
    assert abs(pan + 0.4) < 1e-4
    assert abs(roll - 0.6) < 1e-4
