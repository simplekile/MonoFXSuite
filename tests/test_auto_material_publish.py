"""Auto Material: Monos Painter publish names, colour space tokens, latest publish version (no hou)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.houdini.solaris_adapter import colorspace_token_for_slot
from tools.fx.auto_material.config import IMAGE_EXTENSIONS
from tools.fx.auto_material.logic import (
    latest_publish_version,
    resolve_scan_folder,
    scan_and_group,
    try_pipeline_parse,
)


@pytest.mark.parametrize(
    ("filename", "slot", "colorspace"),
    [
        ("M_char_Body_BaseColor_sRGB.1001.png", "base_color", "sRGB"),
        ("M_char_Body_BaseColor_ACEScg.1001.exr", "base_color", "ACEScg"),
        ("M_char_Body_BaseColor_Linear.1001.exr", "base_color", "Linear"),
        ("M_char_Body_Metallic_Raw.1007.png", "metallic", "Raw"),
        ("M_char_Body_Displacement_Raw.1001.exr", "displacement", "Raw"),
        ("M_char_Body_Normal_Raw.1002.tif", "normal", "Raw"),
        ("M_char_Body_Roughness.1001.png", "roughness", None),
    ],
)
def test_pipeline_parse_monos_names(filename: str, slot: str, colorspace: str | None) -> None:
    r = try_pipeline_parse(filename)
    assert r is not None
    assert r.prefix == "M_char_Body"
    assert r.slot == slot
    assert r.colorspace == colorspace
    assert r.udim


def test_float_and_tiff_extensions_scanned() -> None:
    assert {".exr", ".tif", ".tiff", ".png"} <= IMAGE_EXTENSIONS


@pytest.mark.parametrize(
    ("slot", "colorspace", "token"),
    [
        ("base_color", "sRGB", "srgb_texture"),
        ("base_color", "ACEScg", "ACEScg"),
        ("base_color", "acescg", "ACEScg"),
        ("base_color", "Linear", "lin_rec709"),
        ("base_color", "Raw", "Raw"),
        ("normal", "RAW", "Raw"),
        ("emission_color", "ACEScg", "ACEScg"),
        ("metallic", "sRGB", "srgb_texture"),
        # No word in the name (generic naming) or an unknown one: the slot's default.
        ("base_color", None, "srgb_texture"),
        ("base_color", "v2", "srgb_texture"),
        ("roughness", None, "Raw"),
        ("unknown_slot", None, "Raw"),
    ],
)
def test_colorspace_token_from_file_then_slot(slot: str, colorspace: str | None, token: str) -> None:
    assert colorspace_token_for_slot(slot, colorspace) == token


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def _publish(root: Path) -> Path:
    for v in ("v001", "v002", "v010"):
        _touch(root / v / "textures" / f"M_char_Body_BaseColor_sRGB.1001.png")
    _touch(root / "v010" / "textures" / "M_char_Body_Metallic_Raw.1001.png")
    (root / "v1_backup").mkdir()  # not a version folder
    return root


def test_latest_publish_version_numeric(tmp_path: Path) -> None:
    root = _publish(tmp_path / "publish")
    assert latest_publish_version(str(root)) == root / "v010"
    assert resolve_scan_folder(str(root)) == str(root / "v010" / "textures")


def test_non_publish_folder_scanned_as_given(tmp_path: Path) -> None:
    _touch(tmp_path / "tex" / "M_a_BaseColor_sRGB.1001.png")
    assert latest_publish_version(str(tmp_path / "tex")) is None
    assert resolve_scan_folder(str(tmp_path / "tex")) == str(tmp_path / "tex")


def test_scan_publish_folder_only_latest(tmp_path: Path) -> None:
    root = _publish(tmp_path / "publish")
    groups, unmatched = scan_and_group(str(root))
    assert unmatched == []
    body = groups["M_char_Body"]
    assert set(body.slots) == {"base_color", "metallic"}
    assert all("v010" in Path(s.filepath).parts for s in body.slots.values())


def test_publish_json_fills_missing_space(tmp_path: Path) -> None:
    v = tmp_path / "publish" / "v003"
    _touch(v / "textures" / "M_char_Body_BaseColor.1001.exr")
    _touch(v / "textures" / "M_char_Body_Roughness_Raw.1001.png")
    _touch(v / "textures" / "M_char_Body_Normal.1001.png")
    (v / "publish.json").write_text(json.dumps({"cleaned": {"textures": 3, "maps": [
        {"channel": "basecolor", "name": "BaseColor", "format": "exr", "bits": "16f", "space": "ACEScg"},
        {"channel": "roughness", "name": "Roughness", "format": "png", "bits": "16", "space": "sRGB"},
        {"channel": "normal", "name": "Normal", "format": "png", "bits": "16", "space": "Raw, sRGB"},
    ]}}), encoding="utf-8")
    groups, _ = scan_and_group(str(tmp_path / "publish"))
    slots = groups["M_char_Body"].slots
    assert slots["base_color"].colorspace == "ACEScg"
    assert slots["roughness"].colorspace == "Raw"  # the file name wins
    assert slots["normal"].colorspace is None  # several spaces: left to the slot default
