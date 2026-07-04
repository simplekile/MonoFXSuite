"""
Render Preview Maya — pure-python helpers (no maya imports).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Tuple

Ext = Literal["jpg", "png", "avi", "mov"]


@dataclass(frozen=True)
class PlayblastRequest:
    output_root: str
    basename: str
    start_frame: int
    end_frame: int
    width: int
    height: int
    ext: Ext
    rename_to_camera: bool = False
    activate_shot_camera: bool = True
    force_shot_overscan_1: bool = True
    viewport_hud_enabled: bool = True
    viewport_hud_font_size: Literal["small", "large"] = "large"
    viewport_hud_show_shot: bool = True
    viewport_hud_show_frame: bool = True
    viewport_hud_show_camera: bool = True
    viewport_hud_show_focal_length: bool = True
    viewport_hud_show_fps: bool = True
    viewport_hud_scene_fps: float = 24.0


def default_output_root_from_scene(scene_path: str) -> str:
    if not scene_path:
        return ""
    try:
        d = str(Path(scene_path).resolve().parent)
    except Exception:
        d = os.path.dirname(os.path.normpath(scene_path))
    return os.path.normpath(os.path.join(d, "Preview"))


def default_basename_from_scene(scene_path: str) -> str:
    if not scene_path:
        return "untitled"
    base = os.path.basename(scene_path)
    name, _ext = os.path.splitext(base)
    return name or "untitled"


def output_dir(output_root: str, basename: str) -> str:
    return os.path.normpath(os.path.join(output_root, basename))


def frame_file_path(
    output_root: str,
    basename: str,
    frame: int,
    ext: Ext,
) -> str:
    d = output_dir(output_root, basename)
    return os.path.normpath(os.path.join(d, f"{basename}.{int(frame):04d}.{ext}"))


def playblast_filename_prefix(output_root: str, basename: str) -> str:
    # Maya playblast expects filename without frame/ext for image sequence.
    return os.path.normpath(os.path.join(output_dir(output_root, basename), basename))


def is_image_ext(ext: str) -> bool:
    return str(ext).lower().strip() in ("jpg", "png")


def validate_frame_range(start_frame: int, end_frame: int) -> Tuple[int, int]:
    a = int(start_frame)
    b = int(end_frame)
    if b < a:
        a, b = b, a
    return a, b


def normalize_ext(ext: str, default: Ext = "jpg") -> Ext:
    e = str(ext).lower().strip()
    if e in ("jpg", "png", "avi", "mov"):
        return e  # type: ignore[return-value]
    return default


def compression_for_ext(ext: Ext) -> str:
    # Maya playblast compression names typically match file extension for common codecs.
    return ext


def format_for_ext(ext: Ext) -> str:
    return "image" if ext in ("jpg", "png") else "movie"


def first_preview_frame_path(req: PlayblastRequest) -> Optional[str]:
    if not is_image_ext(req.ext):
        return None
    p = frame_file_path(req.output_root, req.basename, req.start_frame, req.ext)
    return p if os.path.exists(p) else None

