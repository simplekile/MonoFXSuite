"""Tests for per-rig anim geo USD basename helpers."""

from __future__ import annotations

from monofx_pipeline_common import anim_geo_naming as _naming


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
