"""
Render Preview Maya — defaults and QSettings keys.
"""

from __future__ import annotations

from pathlib import Path

WINDOW_TITLE = "Render Preview"
SETTINGS_ORG = "MonoFXSuite"
SETTINGS_APP = "RenderPreviewMaya"

SETTINGS_KEY_OUTPUT_ROOT = "output_root"
SETTINGS_KEY_BASENAME = "basename"
SETTINGS_KEY_EXT = "ext"  # "jpg" | "png" | "avi" | "mov"
SETTINGS_KEY_START = "start_frame"
SETTINGS_KEY_END = "end_frame"
SETTINGS_KEY_WIDTH = "width"
SETTINGS_KEY_HEIGHT = "height"
SETTINGS_KEY_ACTIVATE_SHOT_CAMERA = "activate_shot_camera"
SETTINGS_KEY_RENAME_TO_CAMERA = "rename_to_camera"
SETTINGS_KEY_LOOP = "loop_playback"

# Overscan behavior during playblast
SETTINGS_KEY_FORCE_SHOT_OVERSCAN_1 = "force_shot_overscan_1"

# Viewport HUD during playblast
SETTINGS_KEY_VIEWPORT_HUD_ENABLED = "viewport_hud_enabled"
SETTINGS_KEY_VIEWPORT_HUD_FONT_SIZE = "viewport_hud_font_size"  # "small" | "large"
SETTINGS_KEY_VIEWPORT_HUD_SHOW_SHOT = "viewport_hud_show_shot"
SETTINGS_KEY_VIEWPORT_HUD_SHOW_FRAME = "viewport_hud_show_frame"
SETTINGS_KEY_VIEWPORT_HUD_SHOW_CAMERA = "viewport_hud_show_camera"
SETTINGS_KEY_VIEWPORT_HUD_SHOW_FOCAL = "viewport_hud_show_focal_length"
SETTINGS_KEY_VIEWPORT_HUD_SHOW_FPS = "viewport_hud_show_fps"


def _tool_dir() -> Path:
    return Path(__file__).resolve().parent

