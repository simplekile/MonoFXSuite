"""Blender's /_materials scope is moved under the default prim (needs pxr; skipped without it)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("pxr")
from pxr import Sdf, Usd, UsdShade  # noqa: E402

_MOD = (
    Path(__file__).resolve().parents[1]
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/usd_material_scope.py"
)
_spec = importlib.util.spec_from_file_location("usd_material_scope", _MOD)
scope = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scope)

_USDA = """#usda 1.0
(
    defaultPrim = "Geo"
)
def Xform "Geo"
{
    def Mesh "Body" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        prepend rel material:binding = </_materials/M_char_Body>
    }
}
def Scope "_materials"
{
    def Material "M_char_Body"
    {
        token outputs:surface.connect = </_materials/M_char_Body/Principled_BSDF.outputs:surface>
        prepend token outputs:extra.connect = </_materials/M_char_Body/Tex.outputs:rgb>
        def Shader "Principled_BSDF"
        {
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor.connect = </_materials/M_char_Body/Tex.outputs:rgb>
            token outputs:surface
        }
        def Shader "Tex"
        {
            uniform token info:id = "UsdUVTexture"
            float3 outputs:rgb
        }
    }
}
"""


def _write(tmp_path, text=_USDA):
    path = tmp_path / "model.usda"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_scope_moves_under_default_prim_and_bindings_follow(tmp_path):
    path = _write(tmp_path)
    assert scope.move_materials_under_default_prim(path) == "/Geo/material"

    stage = Usd.Stage.Open(path)
    assert not stage.GetPrimAtPath("/_materials")
    mat = stage.GetPrimAtPath("/Geo/material/M_char_Body")
    assert mat and mat.IsA(UsdShade.Material)

    bound = UsdShade.MaterialBindingAPI(stage.GetPrimAtPath("/Geo/Body")).ComputeBoundMaterial()[0]
    assert str(bound.GetPath()) == "/Geo/material/M_char_Body"

    surf = UsdShade.Material(mat).GetSurfaceOutput().GetConnectedSources()[0][0]
    assert str(surf.source.GetPath()) == "/Geo/material/M_char_Body/Principled_BSDF"
    diffuse = UsdShade.Shader(stage.GetPrimAtPath("/Geo/material/M_char_Body/Principled_BSDF")).GetInput("diffuseColor")
    assert str(diffuse.GetConnectedSources()[0][0].source.GetPath()) == "/Geo/material/M_char_Body/Tex"


def test_no_materials_scope_changes_nothing(tmp_path):
    text = "#usda 1.0\n(\n    defaultPrim = \"Geo\"\n)\ndef Xform \"Geo\"\n{\n}\n"
    path = _write(tmp_path, text)
    assert scope.move_materials_under_default_prim(path) is None
    assert Path(path).read_text(encoding="utf-8") == text


def test_existing_target_is_left_alone(tmp_path):
    text = _USDA.replace('def Xform "Geo"\n{', 'def Xform "Geo"\n{\n    def Scope "material"\n    {\n    }')
    path = _write(tmp_path, text)
    assert scope.move_materials_under_default_prim(path) is None
    stage = Usd.Stage.Open(path)  # keep the stage alive: a prim is invalid once its stage is gone
    assert stage.GetPrimAtPath("/_materials")


def test_no_default_prim_changes_nothing(tmp_path):
    path = _write(tmp_path, _USDA.replace('    defaultPrim = "Geo"\n', ""))
    assert scope.move_materials_under_default_prim(path) is None
    stage = Usd.Stage.Open(path)
    assert stage.GetPrimAtPath("/_materials")
