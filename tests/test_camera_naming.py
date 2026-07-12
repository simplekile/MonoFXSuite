"""Tests for camera naming helpers."""

from __future__ import annotations

from pathlib import Path

from monofx_pipeline_common import camera_naming as _cam
from monofx_pipeline_common.shot_paths import detect_shot_from_path


def test_normalize_shot_token() -> None:
    assert _cam.normalize_shot_token("sh1") == "sh001"
    assert _cam.normalize_shot_token("SH003a") == "sh003a"


def test_format_camera_object_name_no_suffix_for_first() -> None:
    assert _cam.format_camera_object_name("sh010", 1) == "cam_sh010"
    assert _cam.format_camera_object_name("sh010", 2) == "cam_sh010_02"


def test_next_camera_name_increments() -> None:
    assert _cam.next_camera_name("sh010", []) == "cam_sh010"
    assert _cam.next_camera_name("sh010", ["cam_sh010"]) == "cam_sh010_02"
    assert _cam.next_camera_name("sh010", ["cam_sh010", "cam_sh010_02"]) == "cam_sh010_03"
    assert _cam.next_camera_name("sh001", ["cam_sh001_01"]) == "cam_sh001_02"


def test_camera_name_matches_shot() -> None:
    assert _cam.camera_name_matches_shot("cam_sh010", "sh010")
    assert _cam.camera_name_matches_shot("cam_sh010_02", "sh010")
    assert not _cam.camera_name_matches_shot("cam_sh001", "sh010")
    assert not _cam.camera_name_matches_shot("Dolly_Camera", "sh010")


def test_resolve_name_fixer_camera_name() -> None:
    assert _cam.resolve_name_fixer_camera_name("cam_sh010", "sh010", ["cam_sh010_02"]) == "cam_sh010"
    assert _cam.resolve_name_fixer_camera_name("Dolly_Camera", "sh010", []) == "cam_sh010"
    assert _cam.resolve_name_fixer_camera_name("cam_sh001", "sh010", []) == "cam_sh010"


def test_normalize_camera_rename_name() -> None:
    assert _cam.normalize_camera_rename_name("cam_sh010") == "cam_sh010"
    assert _cam.normalize_camera_rename_name("cam_sh010_02") == "cam_sh010_02"
    assert _cam.normalize_camera_rename_name("cam_sh010_2") == "cam_sh010_02"
    assert _cam.normalize_camera_rename_name("cam_shot_2") == "cam_shot_02"
    assert _cam.normalize_camera_rename_name("cam_shot") == "cam_shot"
    assert _cam.normalize_camera_rename_name("Dolly_Camera") is None


def test_camera_rig_names() -> None:
    names = _cam.camera_rig_names("cam_sh010")
    assert names == {
        "root": "cam_sh010_root",
        "body": "cam_sh010_mount",
        "look": "cam_sh010_boom",
        "motion": "cam_sh010_head",
        "aim": "cam_sh010_aim",
        "orbit": "cam_sh010_orbit",
    }


def test_iter_rig_part_name_candidates_includes_legacy() -> None:
    body_names = list(_cam.iter_rig_part_name_candidates("cam_sh010", "body"))
    assert body_names == ["cam_sh010_mount", "cam_sh010_rig", "cam_sh010_body"]
    orbit_names = list(_cam.iter_rig_part_name_candidates("cam_sh010", "orbit"))
    assert orbit_names == ["cam_sh010_orbit", "cam_sh010_pan"]


def test_rig_part_suffix_matches() -> None:
    assert _cam.rig_part_suffix_matches("cam_sh010_mount", "body")
    assert _cam.rig_part_suffix_matches("cam_sh010_body", "body")
    assert _cam.rig_part_suffix_matches("cam_sh010_orbit", "orbit")
    assert _cam.rig_part_suffix_matches("cam_sh010_pan", "orbit")
    assert not _cam.rig_part_suffix_matches("cam_sh010_aim", "body")


def test_legacy_camera_rig_names() -> None:
    legacy = _cam.legacy_camera_rig_names("cam_sh010")
    assert legacy == {
        "body": "cam_sh010_rig",
        "look": "cam_sh010_offset",
        "motion": "cam_sh010_ctrl",
    }


def test_camera_name_from_rig_part() -> None:
    assert _cam.camera_name_from_rig_part("cam_sh010_root") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_mount") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_body") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_rig") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_boom") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_look") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_offset") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_head") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_motion") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_bank") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_roll") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_ctrl") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_orbit") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_pan") == "cam_sh010"
    assert _cam.camera_name_from_rig_part("cam_sh010_02_aim") == "cam_sh010_02"
    assert _cam.camera_name_from_rig_part("cam_sh010") is None


def test_usd_camera_basename() -> None:
    assert _cam.usd_camera_basename("cam_sh010") == "cam_sh010"
    assert _cam.usd_camera_basename("sh010") == "cam_sh010"


def test_usd_basename_from_camera_leaf_no_double_prefix() -> None:
    assert _cam.usd_basename_from_camera_leaf("cam_sh010", prefix="cam_") == "cam_sh010"
    assert _cam.usd_basename_from_camera_leaf("sh010", prefix="cam_") == "cam_sh010"


def test_resolve_camera_usd_basename_from_shot_path() -> None:
    assert _cam.resolve_camera_usd_basename("cam_sh010") == "cam_sh010"
    blend = Path(r"D:\proj\02_shots\sh003a\01_anim\blender\work\scene.blend")
    assert _cam.resolve_camera_usd_basename("Dolly_Camera", scene_path=blend) == "cam_sh003a"


def test_detect_shot_from_path() -> None:
    p = Path(r"D:\proj\02_shots\sh003a\01_anim\blender\work\scene.blend")
    assert detect_shot_from_path(p) == "sh003a"
