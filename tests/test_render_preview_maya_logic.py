"""Tests for render_preview_maya.logic (no Maya)."""

from __future__ import annotations

from pathlib import Path

from tools.fx.render_preview_maya.logic import (
    default_basename_from_scene,
    default_output_root_from_scene,
    frame_file_path,
    normalize_ext,
    playblast_filename_prefix,
    validate_frame_range,
)


def test_validate_frame_range_swaps() -> None:
    assert validate_frame_range(10, 1) == (1, 10)


def test_normalize_ext() -> None:
    assert normalize_ext("PNG") == "png"
    assert normalize_ext("unknown", "jpg") == "jpg"


def test_default_basename_from_scene() -> None:
    assert default_basename_from_scene(r"E:\proj\shot01\maya\work\sc001_v003.ma") == "sc001_v003"
    assert default_basename_from_scene("") == "untitled"


def test_default_output_root_from_scene() -> None:
    root = default_output_root_from_scene(r"E:\proj\shot01\maya\work\sc001_v003.ma")
    assert root.endswith(str(Path(r"E:\proj\shot01\maya\work").joinpath("Preview")))


def test_frame_file_path_padding() -> None:
    p = frame_file_path(r"E:\out", "cam_shot01", 12, "jpg")
    assert p.endswith(r"cam_shot01\cam_shot01.0012.jpg")


def test_playblast_filename_prefix_is_folder_plus_basename() -> None:
    p = playblast_filename_prefix(r"E:\out", "cam_shot01")
    assert p.endswith(r"cam_shot01\cam_shot01")

