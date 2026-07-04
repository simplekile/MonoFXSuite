"""Tests for anim USD cache path helpers and publish path resolution."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load_module(relative: str, name: str):
    path = _ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_paths = _load_module(
    "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/anim_usd_cache_paths.py",
    "anim_usd_cache_paths",
)
_pp = _load_module(
    "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/publish_paths.py",
    "publish_paths",
)


def test_strip_blender_namespace():
    assert _paths.strip_blender_namespace("rig:char:geo_Body") == "geo_Body"
    assert _paths.strip_blender_namespace("tachirig::Geo_Body") == "Geo_Body"
    assert _paths.strip_blender_namespace("Body") == "Body"


def test_namespace_prefix_from_name():
    assert _paths.namespace_prefix_from_name("tachirig::Geo") == "tachirig"
    assert _paths.namespace_prefix_from_name("tachirig2::Geo_Body") == "tachirig2"
    assert _paths.namespace_prefix_from_name("Geo") == ""


def test_multi_instance_root_path_single_instance():
    used: dict[str, set[str]] = {}
    path = _paths.multi_instance_root_path(
        "tachirig::Geo",
        multi_instance=False,
        used_siblings=used,
    )
    assert path == ""


def test_multi_instance_root_path_multi_instance():
    used: dict[str, set[str]] = {}
    p1 = _paths.multi_instance_root_path(
        "tachirig::Geo",
        multi_instance=True,
        used_siblings=used,
    )
    p2 = _paths.multi_instance_root_path(
        "tachirig2::Geo",
        multi_instance=True,
        used_siblings=used,
    )
    assert p1 == "/tachirig"
    assert p2 == "/tachirig2"


def test_camera_collection_name_helpers():
    assert _paths.is_camera_collection_name("Cameras")
    assert _paths.is_camera_collection_name("camera")
    assert _paths.is_camera_collection_name("cam")
    assert _paths.is_camera_collection_name("shot::Cameras")
    assert not _paths.is_camera_collection_name("Characters")
    assert not _paths.is_camera_collection_name("Geo")


def test_publish_geo_name_helpers():
    assert _paths.is_publish_collection_name("CHAR_TACHI_RIG_PUBLISH")
    assert _paths.is_publish_collection_name("char_publish_rig")
    assert not _paths.is_publish_collection_name("Geo_Tachi")

    assert _paths.is_namespace_geo_name("tachirig::Geo")
    assert _paths.is_namespace_geo_name("tachirig::geo")
    assert not _paths.is_namespace_geo_name("tachirig::Geo_Body")
    assert not _paths.is_namespace_geo_name("tachirig_Geo")


def test_sanitize_prim_segment():
    assert _paths.sanitize_prim_segment("geo-Body.001") == "geo_Body_001"


def test_prim_path_from_object_chain():
    path = _paths.prim_path_from_object_chain(["Char", "Body", "geo_Head"])
    assert path == "/Char/Body/geo_Head"


def test_root_override():
    path = _paths.prim_path_from_object_chain(
        ["Char", "Body"],
        root_override="Zephys",
    )
    assert path == "/Zephys/Body"


def test_resolve_anim_publish_root():
    blend = Path(
        r"D:\proj\02_shots\sh002\01_anim\blender\work\char_Zephys_anim_v001.blend"
    )
    root = _pp.resolve_anim_publish_root_from_scene(blend)
    assert root is not None
    assert root.parts[-3:] == ("sh002", "01_anim", "publish")


def test_default_anim_geo_basename():
    blend = Path(
        r"D:\proj\02_shots\sh002\01_anim\blender\work\char_Zephys_anim_v001.blend"
    )
    base = _pp.default_anim_geo_usd_basename(blend)
    assert base.lower().startswith("geo_")
    assert "zephys" in base.lower()


def test_usd_output_uses_dot_usd_extension():
    blend = Path(r"D:\proj\02_shots\sh002\01_anim\publish")
    usd = blend / "v001" / f"{_pp.default_anim_geo_usd_basename(Path('char_Zephys_anim.blend'))}.usd"
    assert usd.suffix == ".usd"
