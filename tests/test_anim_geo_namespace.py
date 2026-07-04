"""Tests for anim geo namespace mesh matching."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load_namespace():
    path = (
        _ROOT
        / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/pipeline_common/anim_geo_namespace.py"
    )
    spec = importlib.util.spec_from_file_location("anim_geo_namespace_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ns = _load_namespace()


def test_namespace_prefixes_from_geo_collections():
    prefixes = _ns.namespace_prefixes_from_geo_collections(
        ["tachirig::Geo", "tachirig2::Geo", "tachirig::Rig", "Other"]
    )
    assert prefixes == ("tachirig", "tachirig2")


def test_mesh_names_matching_namespace_prefixes():
    names = _ns.mesh_names_matching_namespace_prefixes(
        [
            "tachirig::Geo_Belt",
            "tachirig2::Geo_Belt",
            "tachirig::Tachi_rig",
            "Body",
        ],
        ("tachirig", "tachirig2"),
    )
    assert set(names) == {
        "tachirig::Geo_Belt",
        "tachirig2::Geo_Belt",
        "tachirig::Tachi_rig",
    }
