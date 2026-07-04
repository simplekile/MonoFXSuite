"""Camera hierarchy USD xforms — parent chain must carry rig motion."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_xform_writer():
    path = (
        Path(__file__).resolve().parents[1]
        / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/anim_usd_cache_xform_writer.py"
    )
    spec = importlib.util.spec_from_file_location("anim_usd_cache_xform_writer", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ModuleNotFoundError as exc:
        if exc.name not in {"bpy", "pxr", "mathutils"}:
            raise
        return None
    return mod


class _Node:
    def __init__(self, parent_name: str | None) -> None:
        self.parent_name = parent_name


def test_camera_child_uses_parent_relative_not_local_origin() -> None:
    """
    Rig leaf camera at local origin inherits motion from ``*_root`` parent.

    Baking only ``matrix_local`` on the camera prim leaves it at (0,0,0).
    """
    mod = _load_xform_writer()
    if mod is None:
        return

    import mathutils

    orient = mathutils.Matrix.Identity(4)
    root_world = mathutils.Matrix.Translation((10.0, 20.0, 30.0))
    cam_world = root_world.copy()

    hierarchy = {
        "cam_sh010_root": _Node(None),
        "cam_sh010": _Node("cam_sh010_root"),
    }
    worlds = {
        "cam_sh010_root": root_world,
        "cam_sh010": cam_world,
    }

    root_xf = mod.usd_xform_from_evaluated_worlds(
        "cam_sh010_root",
        hierarchy["cam_sh010_root"],
        set(hierarchy),
        worlds,
        orient_matrix=orient,
        unit_scale=1.0,
    )
    cam_xf = mod.usd_xform_from_evaluated_worlds(
        "cam_sh010",
        hierarchy["cam_sh010"],
        set(hierarchy),
        worlds,
        orient_matrix=orient,
        unit_scale=1.0,
    )

    assert root_xf.translation[0] == 10.0
    assert root_xf.translation[1] == 20.0
    assert root_xf.translation[2] == 30.0

    # Parent-relative xform on the camera prim (not identity at origin).
    assert cam_xf.translation.length < 1e-6

    composed = root_xf @ cam_xf
    assert abs(composed.translation[0] - 10.0) < 1e-6
    assert abs(composed.translation[1] - 20.0) < 1e-6
    assert abs(composed.translation[2] - 30.0) < 1e-6


def test_body_empty_has_parent_relative_offset() -> None:
    """Rig body carries Z offset relative to root (not all zeros)."""
    mod = _load_xform_writer()
    if mod is None:
        return

    import mathutils

    orient = mathutils.Matrix.Identity(4)
    root_world = mathutils.Matrix.Translation((5.0, 0.0, 0.0))
    body_local = mathutils.Matrix.Translation((0.0, 0.0, 2.5))
    body_world = root_world @ body_local

    hierarchy = {
        "cam_sh010_root": _Node(None),
        "cam_sh010_body": _Node("cam_sh010_root"),
    }
    worlds = {
        "cam_sh010_root": root_world,
        "cam_sh010_body": body_world,
    }

    body_xf = mod.usd_xform_from_evaluated_worlds(
        "cam_sh010_body",
        hierarchy["cam_sh010_body"],
        set(hierarchy),
        worlds,
        orient_matrix=orient,
        unit_scale=1.0,
    )
    assert abs(body_xf.translation[2] - 2.5) < 1e-6


def test_single_camera_without_parents_uses_oriented_world() -> None:
    mod = _load_xform_writer()
    if mod is None:
        return

    import mathutils

    orient = mathutils.Matrix.Rotation(1.5707963267948966, 4, "X")
    cam_world = mathutils.Matrix.Translation((1.0, 2.0, 3.0))
    hierarchy = {"cam_sh010": _Node(None)}
    worlds = {"cam_sh010": cam_world}

    xf = mod.usd_xform_from_evaluated_worlds(
        "cam_sh010",
        hierarchy["cam_sh010"],
        set(hierarchy),
        worlds,
        orient_matrix=orient,
        unit_scale=1.0,
    )
    expected = orient @ cam_world
    for row in range(4):
        for col in range(4):
            assert abs(xf[row][col] - expected[row][col]) < 1e-6
