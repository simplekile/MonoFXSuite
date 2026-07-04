"""Tests for per-rig anim geo USD basename helpers."""

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


_naming = _load_module(
    "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/pipeline_common/anim_geo_naming.py",
    "anim_geo_naming",
)


def test_geo_basename_from_asset_folder():
    assert _naming.geo_usd_basename_from_asset_folder("char_Kahlii") == "geo_char_Kahlii"
    assert _naming.geo_usd_basename_from_asset_folder("char_Tachi") == "geo_char_Tachi"


def test_geo_basename_from_publish_name():
    base = _naming.geo_usd_basename_from_publish_name("CHAR_KAHLII_RIG_PUBLISH")
    assert base.lower().startswith("geo_")
    assert "kahlii" in base.lower()


def test_alloc_unique_basename_for_duplicate_rigs():
    used: set[str] = set()
    first = _naming.resolve_geo_usd_basename(
        asset_folder="char_Tachi",
        used=used,
    )
    second = _naming.resolve_geo_usd_basename(
        asset_folder="char_Tachi",
        used=used,
    )
    assert first == "geo_char_Tachi"
    assert second == "geo_char_Tachi_2"
