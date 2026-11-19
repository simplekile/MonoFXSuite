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
    third = _naming.resolve_geo_usd_basename(asset_folder="char_Tachi", used=used)
    assert first == "geo_char_Tachi"
    assert second == "geo_char_Tachi_inst02"
    assert third == "geo_char_Tachi_inst03"


def test_asset_with_digits_is_not_a_clone():
    used: set[str] = set()
    a = _naming.resolve_geo_usd_basename(asset_folder="char_Robot", used=used)
    b = _naming.resolve_geo_usd_basename(asset_folder="char_Robot_2", used=used)
    c = _naming.resolve_geo_usd_basename(asset_folder="char_Robot", used=used)
    assert (a, b, c) == ("geo_char_Robot", "geo_char_Robot_2", "geo_char_Robot_inst02")


def test_publish_meta_geo_entry(tmp_path):
    (tmp_path / "01_assets/_characters/char_Robot").mkdir(parents=True)
    (tmp_path / "02_shots").mkdir()
    assert _naming.publish_meta_geo_entry("geo_char_Robot_inst02.usd", tmp_path) == {
        "file": "geo_char_Robot_inst02.usd", "type": "geo", "asset": "char_Robot", "instance": 2}
    assert _naming.publish_meta_geo_entry("geo_char_Robot.usd", tmp_path) == {
        "file": "geo_char_Robot.usd", "type": "geo", "asset": "char_Robot", "instance": 1}
    # not an asset folder (publish-name fallback, project unknown): no asset written, the loader guesses
    assert _naming.publish_meta_geo_entry("geo_CHAR_KAHLII.usd", tmp_path) == {
        "file": "geo_CHAR_KAHLII.usd", "type": "geo"}
    assert _naming.publish_meta_geo_entry("geo_char_Robot.usd", None) == {"file": "geo_char_Robot.usd", "type": "geo"}


def test_find_project_root(tmp_path):
    (tmp_path / "01_assets").mkdir()
    (tmp_path / "02_shots/sh010/01_anim/publish/v001").mkdir(parents=True)
    assert _naming.find_project_root(tmp_path / "02_shots/sh010/01_anim/publish/v001") == tmp_path
