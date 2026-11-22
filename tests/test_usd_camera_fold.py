"""Blender 5.2.2 drops an animated, merged camera; the writer exports unmerged and folds (needs pxr)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("pxr")
from pxr import Sdf, Usd  # noqa: E402

_MOD = (
    Path(__file__).resolve().parents[1]
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/usd_camera_fold.py"
)
_spec = importlib.util.spec_from_file_location("usd_camera_fold", _MOD)
fold_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fold_mod)

# What Blender 5.2.2 writes with merge_parent_xform=False (sh012a v007's rig, cut down).
_UNMERGED = """#usda 1.0
(
    defaultPrim = "cam_sh012a_root"
)
def Xform "cam_sh012a_root"
{
    def Xform "cam_sh012a_head"
    {
        def Xform "cam_sh012a"
        {
            double3 xformOp:translate.timeSamples = {
                0: (0, 0, 0),
                10: (1, 2, 3),
            }
            uniform token[] xformOpOrder = ["xformOp:translate"]

            def Camera "cam_sh012a"
            {
                float2 clippingRange = (0.01, 1000)
                float focalLength.timeSamples = {
                    0: 0.8,
                    10: 0.5,
                }
                float horizontalAperture = 0.36
                token projection = "perspective"
                float verticalAperture = 0.2025
            }
        }
    }
    def Xform "cam_sh012a_aim"
    {
    }
}
"""

_CAM = "/cam_sh012a_root/cam_sh012a_head/cam_sh012a"


def _write(tmp_path, text=_UNMERGED):
    path = tmp_path / "cam.usda"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_camera_takes_its_object_path(tmp_path):
    path = _write(tmp_path)
    assert fold_mod.fold_cameras(path) == 1
    stage = Usd.Stage.Open(path)
    cam = stage.GetPrimAtPath(_CAM)
    assert cam.GetTypeName() == "Camera"
    assert not stage.GetPrimAtPath(_CAM + "/cam_sh012a")
    assert [p.GetTypeName() for p in stage.Traverse()].count("Camera") == 1


def test_transform_and_lens_animation_are_kept(tmp_path):
    path = _write(tmp_path)
    fold_mod.fold_cameras(path)
    stage = Usd.Stage.Open(path)
    cam = stage.GetPrimAtPath(_CAM)
    assert tuple(cam.GetAttribute("xformOp:translate").Get(10)) == (1, 2, 3)
    assert cam.GetAttribute("focalLength").Get(10) == pytest.approx(0.5)
    assert cam.GetAttribute("horizontalAperture").Get() == pytest.approx(0.36)
    assert cam.GetAttribute("projection").Get() == "perspective"


def test_an_already_merged_camera_is_left_alone(tmp_path):
    path = _write(tmp_path)
    fold_mod.fold_cameras(path)
    before = Path(path).read_text(encoding="utf-8")
    assert fold_mod.fold_cameras(path) == 0
    assert Path(path).read_text(encoding="utf-8") == before


def test_xform_with_other_children_is_not_folded(tmp_path):
    text = _UNMERGED.replace(
        'def Camera "cam_sh012a"', 'def Xform "extra"\n            {\n            }\n            def Camera "cam_sh012a"'
    )
    path = _write(tmp_path, text)
    assert fold_mod.fold_cameras(path) == 0
    assert Sdf.Layer.FindOrOpen(path).GetPrimAtPath(_CAM + "/cam_sh012a").typeName == "Camera"


def test_missing_file_changes_nothing(tmp_path):
    assert fold_mod.fold_cameras(str(tmp_path / "missing.usda")) == 0
