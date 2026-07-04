"""Defaults for Maya Reference Manager."""

from __future__ import annotations

WINDOW_TITLE = "MonoFX Reference Manager"
WORKSPACE_CONTROL_NAME = "MonoFXReferenceManagerWorkspace"
SETTINGS_ORG = "MonoFXSuite"
SETTINGS_APP = "MayaReferenceManager"

SETTINGS_KEY_ASSETS_GROUP = "assets_group"
SETTINGS_KEY_PUBLISH_MODE = "publish_mode"  # bool True = publish, False = work
SETTINGS_KEY_MAIN_TAB = "main_tab_index"  # 0 = Library, 1 = Scene
SETTINGS_KEY_LIB_SEARCH = "library_search"
SETTINGS_KEY_SCENE_FOCUS_SELECTION = "scene_focus_selection"
SETTINGS_KEY_SCENE_FOCUS_MODE = "scene_focus_mode"  # root | geometry | main | top_main | custom
SETTINGS_KEY_SCENE_FOCUS_CUSTOM = "scene_focus_custom"
SETTINGS_KEY_SCENE_FOCUS_CUSTOM_EXCLUDE = "scene_focus_custom_exclude"
SETTINGS_KEY_WINDOW_GEOMETRY = "window_geometry"  # QByteArray from QMainWindow.saveGeometry()
SETTINGS_KEY_LIB_HEADER_STATE = "library_header_state"
SETTINGS_KEY_SCENE_HEADER_STATE = "scene_header_state"
# JSON object: { "<scene_path_norm>": [ {t:g|r, ...}, ... ] } for Scene tab tree layout
SETTINGS_KEY_SCENE_TREE_LAYOUTS = "scene_tree_layouts_v1"

PUBLISH_SUBPATH = "02_rigging/02_build_rig/publish"
WORK_SUBPATH = "02_rigging/02_build_rig/maya/work"
THUMB_RELATIVE = ".meta/thumb_rig.user.png"

KNOWN_DISPLAY_PREFIXES = (
    "char_",
    "prop_",
    "env_",
    "veh_",
    "graphic_",
)
