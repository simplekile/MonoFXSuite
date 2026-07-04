"""
USD Export Maya — defaults and paths.
"""

from __future__ import annotations

import os
from pathlib import Path

WINDOW_TITLE = "USD Publish"
SETTINGS_ORG = "MonoFXSuite"
SETTINGS_APP = "UsdExportMaya"

META_FILENAME = "publish_meta.json"
SETTINGS_KEY_CAMERA_RENDERABLE = "camera_require_renderable"
SETTINGS_KEY_PUBLISH_LOCKED = "publish_root_locked"
SETTINGS_KEY_SKIP_HIDDEN = "skip_hidden_outliner"
# ref_geometry rule: also match native transforms (Geometry / GEO / …), not only file references
SETTINGS_KEY_GEOMETRY_INCLUDE_NON_REFERENCE = "geometry_include_non_reference"
SETTINGS_KEY_SUBDIVIDE = "export_subdivide"
SETTINGS_KEY_NORMALS = "export_normals"
SETTINGS_KEY_EXPORT_UVS = "export_uvs"
SETTINGS_KEY_EXPORT_ANIM = "export_animation"
SETTINGS_KEY_SCALE = "export_scale"

# Advanced: raw USD Export options string (Maya `file -options "...";`)
SETTINGS_KEY_USD_OPTIONS_RAW = "usd_options_raw"

# Rule editor override (JSON). If set, overrides rules file.
SETTINGS_KEY_RULES_OVERRIDE_JSON = "rules_override_json"

# Publish version selection
SETTINGS_KEY_PUBLISH_VERSION_MODE = "publish_version_mode"  # "auto" | "manual" | "overwrite"
SETTINGS_KEY_PUBLISH_VERSION_NUMBER = "publish_version_number"  # int
SETTINGS_KEY_PUBLISH_VERSION_FOLDER = "publish_version_folder"  # e.g. "v002" when mode is overwrite

# Output path preset (how to resolve publish root from scene)
SETTINGS_KEY_OUTPUT_PATH_PRESET = "output_path_preset"  # "anim" | "uv" | "custom"
SETTINGS_KEY_AUTO_NAME_FROM_SCENE = "auto_name_from_scene"


def _tool_dir() -> Path:
    return Path(__file__).resolve().parent


def default_rules_path() -> str:
    return str(_tool_dir() / "default_rules.json")


def suite_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent
