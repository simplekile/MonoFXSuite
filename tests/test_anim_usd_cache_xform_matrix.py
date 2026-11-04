"""Blender matrices must reach USD with their translation. Needs bpy and pxr: runs in Blender's Python."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy")
pxr = pytest.importorskip("pxr")

_ADDON_PARENT = Path(__file__).resolve().parents[1] / "tools/fx/monofx_pipeline_blender"


def _xform_module():
    if str(_ADDON_PARENT) not in sys.path:
        sys.path.insert(0, str(_ADDON_PARENT))
    return importlib.import_module("monofx_pipeline_blender.anim_usd_cache_xform_writer")


class _Node:
    def __init__(self, parent_name=None):
        self.parent_name = parent_name


def _usd_point(gf, point):
    return tuple(gf.Transform(pxr.Gf.Vec3d(*point)))


def test_matrix_to_gf_keeps_translation():
    import mathutils

    gf = _xform_module().matrix_to_gf(mathutils.Matrix.Translation((1.0, 2.0, 3.0)))
    assert tuple(gf.ExtractTranslation()) == (1.0, 2.0, 3.0)


def test_matrix_to_gf_transforms_points_like_blender():
    import mathutils

    mat = mathutils.Matrix.Translation((5.0, -6.0, 7.0)) @ mathutils.Matrix.Rotation(0.7, 4, "Z")
    point = mathutils.Vector((1.0, 2.0, 3.0))
    got = _usd_point(_xform_module().matrix_to_gf(mat), point)
    assert got == pytest.approx(tuple(mat @ point), abs=1e-5)


def test_default_orientation_is_z_up_to_y_up_in_usd():
    mod = _xform_module()
    gf = mod.matrix_to_gf(mod.build_axis_conversion_matrix("NEGATIVE_Z", "Y"))
    assert _usd_point(gf, (0.0, 0.0, 1.0)) == pytest.approx((0.0, 1.0, 0.0))
    assert _usd_point(gf, (0.0, 1.0, 0.0)) == pytest.approx((0.0, 0.0, -1.0))


def test_recorder_samples_only_prims_that_move():
    import mathutils

    mod = _xform_module()
    still = bpy.data.objects.new("rec_still", None)
    moving = bpy.data.objects.new("rec_moving", None)
    scene = bpy.context.scene
    scene.collection.objects.link(still)
    scene.collection.objects.link(moving)
    stage = pxr.Usd.Stage.CreateInMemory()
    prims = {
        "rec_still": pxr.UsdGeom.Xform.Define(stage, "/still").GetPrim(),
        "rec_moving": pxr.UsdGeom.Xform.Define(stage, "/moving").GetPrim(),
    }
    cache = mod.MatrixXformOpCache()
    for prim in prims.values():
        cache.set(prim, pxr.Gf.Matrix4d(1.0))
    recorder = mod.HierarchyXformRecorder(
        hierarchy={name: _Node() for name in prims},
        prims=prims,
        op_cache=cache,
        orient_matrix=mathutils.Matrix.Identity(4),
        unit_scale=1.0,
    )
    for frame in (1, 2, 3):
        moving.location = (float(frame), 0.0, 0.0)
        bpy.context.view_layer.update()
        recorder.sample(float(frame), bpy.context.evaluated_depsgraph_get())
    recorder.author()

    still_op = pxr.UsdGeom.Xformable(prims["rec_still"]).GetOrderedXformOps()[0]
    moving_op = pxr.UsdGeom.Xformable(prims["rec_moving"]).GetOrderedXformOps()[0]
    assert still_op.GetTimeSamples() == []
    assert moving_op.GetTimeSamples() == [1.0, 2.0, 3.0]
    assert moving_op.Get(2.0).ExtractTranslation()[0] == 2.0
