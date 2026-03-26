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


def _tool_dir() -> Path:
    return Path(__file__).resolve().parent


def default_rules_path() -> str:
    return str(_tool_dir() / "default_rules.json")


def suite_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent
