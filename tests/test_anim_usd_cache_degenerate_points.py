"""Anim USD export flags meshes whose evaluated points are unusable (no bpy)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
_path = (
    _ROOT
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/anim_usd_cache_points.py"
)
_spec = importlib.util.spec_from_file_location("anim_usd_cache_points", _path)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
degenerate_points_reason = _mod.degenerate_points_reason


def test_normal_points_are_fine():
    pts = np.array([[0, 0, 0], [1, 2, 3], [4, 5, 6]], dtype=np.float32)
    assert degenerate_points_reason(pts) is None


def test_all_points_at_origin_is_flagged():
    reason = degenerate_points_reason(np.zeros((5839, 3), dtype=np.float32))
    assert reason is not None
    assert "origin" in reason and "5839" in reason


def test_no_points_is_flagged():
    reason = degenerate_points_reason(np.zeros((0, 3), dtype=np.float32))
    assert reason is not None and "no points" in reason


def test_single_point_mesh_at_origin_is_not_flagged():
    # one lone point at (0,0,0) is a legitimate (if odd) mesh; the check needs more than one point
    assert degenerate_points_reason(np.zeros((1, 3), dtype=np.float32)) is None


def test_non_finite_points_are_flagged():
    pts = np.array([[0, 0, 0], [np.nan, 1, 1]], dtype=np.float32)
    reason = degenerate_points_reason(pts)
    assert reason is not None and "non-finite" in reason
