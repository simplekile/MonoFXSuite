"""
Rig publish path helpers for Blender (no bpy).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional

from .pipeline_common.project_layout import find_project_root, list_asset_groups
from .pipeline_common.rig_library import (
    BLENDER_EXTENSIONS,
    DEFAULT_BLENDER_WORK_SUBPATH,
    DEFAULT_PUBLISH_SUBPATH,
    Mode,
    RigOffer,
    RigVersionEntry,
    display_name_from_asset_folder,
    matching_rig_versions_for_scene_path,
    newer_rig_version_for_scene_path,
    resolve_project_root_from_scene_path,
    rig_paths_equivalent,
    rig_version_index_for_scene_path,
    scan_rigs,
    scene_ref_version_display,
    suggest_namespace_from_asset,
    thumb_path_for_asset,
    thumb_path_for_reference_file,
    version_display_token_from_path,
)

__all__ = [
    "BLENDER_EXTENSIONS",
    "DEFAULT_BLENDER_WORK_SUBPATH",
    "DEFAULT_PUBLISH_SUBPATH",
    "Mode",
    "RigOffer",
    "RigVersionEntry",
    "display_name_from_asset_folder",
    "find_project_root_from_scene",
    "list_asset_groups_for_project",
    "matching_rig_versions_for_scene_path",
    "newer_rig_version_for_scene_path",
    "resolve_project_root_from_scene_path",
    "rig_paths_equivalent",
    "rig_version_index_for_scene_path",
    "scan_blender_rigs",
    "scene_ref_version_display",
    "suggest_namespace_from_asset",
    "thumb_path_for_asset",
    "thumb_path_for_reference_file",
    "version_display_token_from_path",
]


def find_project_root_from_scene(scene_path: Optional[str]) -> Optional[Path]:
    return resolve_project_root_from_scene_path(scene_path)


def list_asset_groups_for_project(project_root: Path) -> List[str]:
    return list_asset_groups(project_root)


def scan_blender_rigs(
    project_root: Path,
    assets_group: str,
    mode: Mode,
) -> List[RigOffer]:
    return scan_rigs(
        project_root,
        assets_group,
        mode,
        publish_subpath=DEFAULT_PUBLISH_SUBPATH,
        work_subpath=DEFAULT_BLENDER_WORK_SUBPATH,
        extensions=BLENDER_EXTENSIONS,
    )
