"""The model publish marks the asset root as a USD component (needs pxr)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("pxr")
from pxr import Sdf, Usd  # noqa: E402

_MOD = (
    Path(__file__).resolve().parents[1]
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/usd_asset_kind.py"
)
_spec = importlib.util.spec_from_file_location("usd_asset_kind", _MOD)
kind_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kind_mod)

_BASE = """#usda 1.0
(
    defaultPrim = "Geo"
)
def Xform "Geo"%s
{
    def Xform "Body_grp"%s
    {
        def Mesh "Body"
        {
        }
    }
}
"""


def _write(tmp_path, root_meta="", child_meta="", text=None):
    path = tmp_path / "m.usda"
    path.write_text(text if text is not None else _BASE % (root_meta, child_meta), encoding="utf-8")
    return str(path)


def _kind(path, prim_path):
    stage = Usd.Stage.Open(path)  # keep alive while reading
    return str(Usd.ModelAPI(stage.GetPrimAtPath(prim_path)).GetKind())


def test_default_prim_becomes_component(tmp_path):
    path = _write(tmp_path)
    assert kind_mod.set_default_prim_kind(path) is True
    assert _kind(path, "/Geo") == "component"
    assert _kind(path, "/Geo/Body_grp") == ""


def test_existing_kind_is_kept(tmp_path):
    path = _write(tmp_path, root_meta=' (\n    kind = "assembly"\n)')
    assert kind_mod.set_default_prim_kind(path) is False
    assert _kind(path, "/Geo") == "assembly"


def test_already_component_is_not_rewritten(tmp_path):
    path = _write(tmp_path, root_meta=' (\n    kind = "component"\n)')
    before = Path(path).read_text(encoding="utf-8")
    assert kind_mod.set_default_prim_kind(path) is False
    assert Path(path).read_text(encoding="utf-8") == before


def test_nested_group_kind_blocks_it(tmp_path):
    # a component may not contain a group/component: leave the file alone rather than break kind rules
    path = _write(tmp_path, child_meta=' (\n    kind = "group"\n)')
    assert kind_mod.set_default_prim_kind(path) is False
    assert _kind(path, "/Geo") == ""


def test_no_default_prim_or_missing_file_changes_nothing(tmp_path):
    path = _write(tmp_path, text=_BASE.replace('    defaultPrim = "Geo"\n', "") % ("", ""))
    assert kind_mod.set_default_prim_kind(path) is False
    assert kind_mod.set_default_prim_kind(str(tmp_path / "missing.usda")) is False
