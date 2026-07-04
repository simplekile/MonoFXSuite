"""
Rig library scan on disk — no Maya imports.

Re-exports shared logic from ``apps.common.rig_library`` with Maya defaults.
"""

from __future__ import annotations

from apps.common import rig_library as _rl
from apps.common.rig_library import *  # noqa: F403

from tools.fx.maya_reference_manager import config

# Maya-specific defaults for callers that omit scan kwargs.
PUBLISH_SUBPATH = config.PUBLISH_SUBPATH
WORK_SUBPATH = config.WORK_SUBPATH
THUMB_RELATIVE = config.THUMB_RELATIVE
KNOWN_DISPLAY_PREFIXES = config.KNOWN_DISPLAY_PREFIXES


def scan_rigs(project_root, assets_group, mode, **kwargs):
    kwargs.setdefault("publish_subpath", config.PUBLISH_SUBPATH)
    kwargs.setdefault("work_subpath", config.WORK_SUBPATH)
    kwargs.setdefault("extensions", _rl.MAYA_EXTENSIONS)
    return _rl.scan_rigs(project_root, assets_group, mode, **kwargs)


def thumb_path_for_asset(asset_root, *, thumb_relative: str = config.THUMB_RELATIVE):
    return _rl.thumb_path_for_asset(asset_root, thumb_relative=thumb_relative)


def display_name_from_asset_folder(folder_name: str) -> str:
    return _rl.display_name_from_asset_folder(folder_name)


def matching_rig_versions_for_scene_path(file_path, project_root, mode, **kwargs):
    kwargs.setdefault("publish_subpath", config.PUBLISH_SUBPATH)
    kwargs.setdefault("work_subpath", config.WORK_SUBPATH)
    if "extensions" not in kwargs:
        kwargs["extensions"] = _rl.extensions_for_path(file_path)
    return _rl.matching_rig_versions_for_scene_path(file_path, project_root, mode, **kwargs)


def scene_ref_version_display(scene_path, project_root, mode, **kwargs):
    kwargs.setdefault("publish_subpath", config.PUBLISH_SUBPATH)
    if "extensions" not in kwargs and scene_path:
        kwargs["extensions"] = _rl.extensions_for_path(scene_path)
    return _rl.scene_ref_version_display(scene_path, project_root, mode, **kwargs)


def newer_rig_version_for_scene_path(file_path, project_root, mode, **kwargs):
    kwargs.setdefault("publish_subpath", config.PUBLISH_SUBPATH)
    kwargs.setdefault("work_subpath", config.WORK_SUBPATH)
    if "extensions" not in kwargs:
        kwargs["extensions"] = _rl.extensions_for_path(file_path)
    return _rl.newer_rig_version_for_scene_path(file_path, project_root, mode, **kwargs)
