"""
Camera anim USD via Blender ``wm.usd_export`` (same path as model publish).
"""

from __future__ import annotations

import logging
from typing import Optional

import bpy

from . import config
from .transform import usd_export

logger = logging.getLogger("monofx.anim_usd_cache")


def _ancestor_chain(obj: bpy.types.Object) -> list[bpy.types.Object]:
    chain: list[bpy.types.Object] = []
    current: Optional[bpy.types.Object] = obj
    while current is not None:
        chain.append(current)
        current = current.parent
    chain.reverse()
    return chain


def collect_camera_usd_export_objects(cam_obj: bpy.types.Object) -> list[bpy.types.Object]:
    """
    Camera rig objects for ``wm.usd_export`` — parents, rig empties, and aim target.

    Includes ``*_aim`` (TRACK_TO target) which is not in the camera parent chain.
    """
    from monofx_pipeline_common.camera_naming import (
        camera_name_from_rig_part,
        iter_camera_rig_object_names,
    )

    seen: set[str] = set()
    ordered: list[bpy.types.Object] = []

    def _add(obj: bpy.types.Object | None) -> None:
        if obj is None or obj.name in seen:
            return
        seen.add(obj.name)
        ordered.append(obj)

    for obj in _ancestor_chain(cam_obj):
        _add(obj)

    cam_base = camera_name_from_rig_part(cam_obj.name)
    if not cam_base:
        leaf = (cam_obj.name or "").strip().split(":")[-1]
        cam_base = leaf if leaf else None
    if cam_base:
        for rig_obj_name in iter_camera_rig_object_names(cam_base):
            _add(bpy.data.objects.get(rig_obj_name))

    if not ordered:
        ordered.append(cam_obj)
    return ordered


def export_camera_anim_usd_cache(
    context: bpy.types.Context,
    cam_obj: bpy.types.Object,
    output_filepath: str,
    *,
    frame_start: int,
    frame_end: int,
    convert_orientation: bool = config.DEFAULT_CONVERT_ORIENTATION,
    export_forward_axis: str = config.DEFAULT_EXPORT_FORWARD,
    export_up_axis: str = config.DEFAULT_EXPORT_UP,
    convert_scene_units: str = config.DEFAULT_CONVERT_SCENE_UNITS,
) -> None:
    """Export animated camera USD using Blender's built-in exporter."""
    scene = context.scene
    prev_start = int(scene.frame_start)
    prev_end = int(scene.frame_end)
    prev_frame = int(scene.frame_current)
    export_objects = collect_camera_usd_export_objects(cam_obj)

    logger.info(
        "Camera USD via wm.usd_export: %s, %d object(s), frames %d–%d → %s",
        cam_obj.name,
        len(export_objects),
        frame_start,
        frame_end,
        output_filepath,
    )

    try:
        scene.frame_start = int(frame_start)
        scene.frame_end = int(frame_end)
        usd_export(
            output_filepath=output_filepath,
            export_animation=True,
            export_uvmaps=False,
            export_normals=False,
            export_materials=False,
            export_lights=False,
            export_cameras=True,
            export_meshes=False,
            export_objects=export_objects,
            convert_orientation=bool(convert_orientation),
            export_global_forward_selection=str(export_forward_axis),
            export_global_up_selection=str(export_up_axis),
            convert_scene_units=str(convert_scene_units),
            evaluation_mode="VIEWPORT",
        )
    finally:
        scene.frame_start = prev_start
        scene.frame_end = prev_end
        try:
            scene.frame_set(prev_frame)
        except Exception:
            pass


def camera_usd_path_from_geo(geo_path) -> Optional["Path"]:
    """Legacy: derive ``cam_*`` filename from a geo USD path (asset-based)."""
    from pathlib import Path

    path = Path(geo_path)
    stem = path.stem
    if stem.casefold().startswith("geo_"):
        cam_stem = f"cam_{stem[4:]}"
    else:
        cam_stem = f"cam_{stem}"
    return path.with_name(f"{cam_stem}.usd")


def camera_usd_output_path(
    output_dir,
    cam_object_name: str,
    *,
    scene_path=None,
) -> "Path":
    """``cam_sh###.usd`` beside geo files (shot-based, not geo asset name)."""
    from pathlib import Path

    from monofx_pipeline_common.camera_naming import resolve_camera_usd_basename

    base = resolve_camera_usd_basename(cam_object_name, scene_path=scene_path)
    return Path(output_dir) / f"{base}.usd"
