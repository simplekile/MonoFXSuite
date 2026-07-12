"""
USD Animation Cache exporter — OpenUSD authoring for Solaris animation layers.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import bpy
from mathutils import Vector

from . import config
from .anim_usd_cache_camera_writer import (
    camera_usd_output_path,
    export_camera_anim_usd_cache,
)
from .anim_usd_cache_mesh_writer import UsdAnimCacheMeshWriter
from .anim_usd_cache_xform_writer import (
    author_hierarchy_bind_xforms,
    resolve_orientation_matrix,
)
from .anim_usd_cache_paths import (
    dedupe_sibling_segment,
    is_camera_collection_name,
    is_namespace_geo_name,
    is_publish_collection_name,
    multi_instance_root_path,
    namespace_prefix_from_name,
    sanitize_prim_segment,
    segments_to_prim_path,
    strip_blender_namespace,
)
from .anim_usd_cache_visibility import (
    filter_object_names_for_export,
    filter_objects_for_export,
    resolve_export_visibility,
)

logger = logging.getLogger("monofx.anim_usd_cache")

try:
    from pxr import Gf, Usd, UsdGeom

    PXR_AVAILABLE = True
except ImportError:  # pragma: no cover - runtime guard in Blender
    PXR_AVAILABLE = False
    Gf = None  # type: ignore[assignment,misc]
    Usd = None  # type: ignore[assignment,misc]
    UsdGeom = None  # type: ignore[assignment,misc]


@dataclass
class UsdAnimCacheExportResult:
    ok: bool
    filepath: str = ""
    camera_filepath: str = ""
    geo_filepaths: list[str] = field(default_factory=list)
    frames_written: int = 0
    mesh_count: int = 0
    camera_count: int = 0
    elapsed_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    error: str = ""


_DEFAULT_BLENDER_CAMERAS = frozenset({"persp", "top", "front", "side"})


def format_export_elapsed(seconds: float) -> str:
    if seconds < 0.0:
        seconds = 0.0
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60.0
    return f"{minutes}m {secs:.0f}s"


def estimate_export_remaining_seconds(
    elapsed_seconds: float,
    current_step: int,
    total_steps: int,
    *,
    min_steps: int = 2,
) -> Optional[float]:
    """Linear ETA from elapsed time and completed export steps."""
    if elapsed_seconds <= 0.0 or current_step < min_steps or total_steps <= 0:
        return None
    if current_step >= total_steps:
        return 0.0
    rate = current_step / elapsed_seconds
    if rate <= 0.0:
        return None
    return (total_steps - current_step) / rate


def format_progress_time_label(
    elapsed_seconds: float,
    current_step: int,
    total_steps: int,
) -> str:
    """Human-readable progress for a step range (per export target)."""
    total = max(int(total_steps), 1)
    current = max(0, min(int(current_step), total))
    pct = int(round(100.0 * current / total))
    elapsed = format_export_elapsed(elapsed_seconds)
    remaining = estimate_export_remaining_seconds(
        elapsed_seconds,
        current,
        total,
    )
    if remaining is None:
        return f"{elapsed} elapsed · {pct}%"
    return f"{elapsed} · ~{format_export_elapsed(remaining)} left · {pct}%"


@dataclass(frozen=True)
class _HierarchyNode:
    obj_name: str
    parent_name: Optional[str]
    is_mesh: bool
    prim_path: str


@dataclass(frozen=True)
class _MeshTopology:
    face_vertex_counts: tuple[int, ...]
    face_vertex_indices: tuple[int, ...]


def _setup_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("[%(name)s] %(levelname)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def vector_to_gf(vec: Vector) -> Gf.Vec3f:
    return Gf.Vec3f(float(vec.x), float(vec.y), float(vec.z))


def meters_scale_from_scene(scene: bpy.types.Scene) -> float:
    """Multiply Blender units to meters (``scale_length``)."""
    scale_length = float(getattr(scene.unit_settings, "scale_length", 1.0) or 1.0)
    return scale_length if scale_length > 0.0 else 1.0


def collect_selected_mesh_objects(
    context: bpy.types.Context,
    *,
    view_layer: Optional[bpy.types.ViewLayer] = None,
    respect_visibility: Optional[bool] = None,
) -> list[bpy.types.Object]:
    view_layer, respect_visibility = resolve_export_visibility(
        context,
        view_layer=view_layer,
        respect_visibility=respect_visibility,
    )
    meshes = [o for o in context.selected_objects if o.type == "MESH"]
    return filter_objects_for_export(
        meshes,
        view_layer,
        respect_visibility=respect_visibility,
    )


def _iter_collections_recursive(coll: bpy.types.Collection):
    yield coll
    for child in coll.children:
        yield from _iter_collections_recursive(child)


def _find_publish_collection(name: str) -> Optional[bpy.types.Collection]:
    coll = bpy.data.collections.get(name)
    if coll is not None:
        return coll
    for candidate in bpy.data.collections:
        if candidate.name == name:
            return candidate
    return None


def _object_names_in_collection(coll: bpy.types.Collection) -> set[str]:
    names: set[str] = set()
    try:
        for obj in coll.all_objects:
            names.add(obj.name)
    except Exception:
        pass
    try:
        for child in coll.children_recursive:
            for obj in child.all_objects:
                names.add(obj.name)
    except Exception:
        pass
    return names


def _object_in_publish_collection(
    obj: bpy.types.Object,
    pub_coll: bpy.types.Collection,
) -> bool:
    return obj.name in _object_names_in_collection(pub_coll)


def _namespace_prefix_from_name(name: str) -> str:
    text = (name or "").strip()
    if "::" not in text:
        return ""
    return text.rsplit("::", 1)[0]


def _namespace_prefixes_for_publish(publish_name: str) -> tuple[str, ...]:
    pub_coll = _find_publish_collection(publish_name)
    if pub_coll is None:
        return ()
    from monofx_pipeline_common.anim_geo_namespace import namespace_prefixes_from_geo_collections

    geo_names: list[str] = []
    for coll in _iter_collections_recursive(pub_coll):
        geo_names.append(coll.name)
    for obj in pub_coll.all_objects:
        if is_namespace_geo_name(obj.name):
            geo_names.append(obj.name)
    return namespace_prefixes_from_geo_collections(geo_names)


def collect_mesh_names_for_merged_publishes(
    publish_names: Sequence[str],
    context: Optional[bpy.types.Context] = None,
    *,
    view_layer: Optional[bpy.types.ViewLayer] = None,
    respect_visibility: Optional[bool] = None,
) -> tuple[str, ...]:
    """
    Geo mesh names for a merged export job.

    Matches ``tachirig::Geo_*`` / ``tachirig2::Geo_*`` via ``*::Geo`` roots
    under each linked ``*_publish*`` override.
    """
    view_layer, respect_visibility = resolve_export_visibility(
        context,
        view_layer=view_layer,
        respect_visibility=respect_visibility,
    )

    prefixes: set[str] = set()
    for publish_name in publish_names:
        prefixes.update(_namespace_prefixes_for_publish(publish_name))

    if not prefixes:
        return collect_mesh_names_for_publish_names(
            publish_names,
            context=context,
            view_layer=view_layer,
            respect_visibility=respect_visibility,
        )

    names: set[str] = set()
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        obj_prefix = _namespace_prefix_from_name(obj.name)
        if obj_prefix and obj_prefix in prefixes:
            names.add(obj.name)

    if not names and prefixes:
        for obj in collect_publish_geo_mesh_objects(
            context,
            view_layer=view_layer,
            respect_visibility=respect_visibility,
        ):
            obj_prefix = _namespace_prefix_from_name(obj.name)
            if obj_prefix and obj_prefix in prefixes:
                names.add(obj.name)

    return filter_object_names_for_export(
        tuple(sorted(names, key=str.lower)),
        view_layer,
        respect_visibility=respect_visibility,
    )


def collect_publish_geo_mesh_objects_for_publish(
    publish_name: str,
    context: Optional[bpy.types.Context] = None,
    *,
    view_layer: Optional[bpy.types.ViewLayer] = None,
    respect_visibility: Optional[bool] = None,
) -> list[bpy.types.Object]:
    """Meshes under ``<namespace>::Geo`` inside one linked ``*_publish*`` collection."""
    view_layer, respect_visibility = resolve_export_visibility(
        context,
        view_layer=view_layer,
        respect_visibility=respect_visibility,
    )
    pub_coll = _find_publish_collection(publish_name)
    if pub_coll is None or not is_publish_collection_name(pub_coll.name):
        return []

    prefixes = _namespace_prefixes_for_publish(publish_name)
    if prefixes:
        meshes: list[bpy.types.Object] = []
        seen: set[int] = set()
        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            obj_prefix = _namespace_prefix_from_name(obj.name)
            if not obj_prefix or obj_prefix not in prefixes:
                continue
            if not _object_in_publish_collection(obj, pub_coll):
                continue
            key = id(obj)
            if key in seen:
                continue
            seen.add(key)
            meshes.append(obj)
        if meshes:
            meshes.sort(key=lambda o: o.name.lower())
            return filter_objects_for_export(
                meshes,
                view_layer,
                respect_visibility=respect_visibility,
            )

    allowed = _object_names_in_collection(pub_coll)
    meshes: list[bpy.types.Object] = []
    seen: set[int] = set()
    for obj in collect_publish_geo_mesh_objects(
        context,
        view_layer=view_layer,
        respect_visibility=respect_visibility,
    ):
        if obj.name not in allowed:
            continue
        key = id(obj)
        if key in seen:
            continue
        seen.add(key)
        meshes.append(obj)
    meshes.sort(key=lambda o: o.name.lower())
    return filter_objects_for_export(
        meshes,
        view_layer,
        respect_visibility=respect_visibility,
    )


def collect_mesh_names_for_publish_names(
    publish_names: Sequence[str],
    context: Optional[bpy.types.Context] = None,
    *,
    view_layer: Optional[bpy.types.ViewLayer] = None,
    respect_visibility: Optional[bool] = None,
) -> tuple[str, ...]:
    """Union of geo mesh object names across linked publish overrides."""
    view_layer, respect_visibility = resolve_export_visibility(
        context,
        view_layer=view_layer,
        respect_visibility=respect_visibility,
    )
    names: list[str] = []
    seen: set[str] = set()
    for publish_name in publish_names:
        for obj in collect_publish_geo_mesh_objects_for_publish(
            publish_name,
            context,
            view_layer=view_layer,
            respect_visibility=respect_visibility,
        ):
            if obj.name in seen:
                continue
            seen.add(obj.name)
            names.append(obj.name)
    return tuple(sorted(names, key=str.lower))


def resolve_geo_job_mesh_objects(
    mesh_names: Sequence[str],
    *,
    source_publish_names: Sequence[str] = (),
    context: Optional[bpy.types.Context] = None,
    view_layer: Optional[bpy.types.ViewLayer] = None,
    respect_visibility: Optional[bool] = None,
) -> list[bpy.types.Object]:
    """Resolve planned mesh names to scene objects."""
    view_layer, respect_visibility = resolve_export_visibility(
        context,
        view_layer=view_layer,
        respect_visibility=respect_visibility,
    )
    names = tuple(mesh_names)
    if not names and source_publish_names:
        if len(source_publish_names) > 1:
            names = collect_mesh_names_for_merged_publishes(
                source_publish_names,
                context,
                view_layer=view_layer,
                respect_visibility=respect_visibility,
            )
        else:
            names = collect_mesh_names_for_publish_names(
                source_publish_names,
                context,
                view_layer=view_layer,
                respect_visibility=respect_visibility,
            )

    out: list[bpy.types.Object] = []
    seen: set[int] = set()
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.type == "MESH":
            key = id(obj)
            if key not in seen:
                seen.add(key)
                out.append(obj)

    if out or not source_publish_names:
        out.sort(key=lambda o: o.name.lower())
        return filter_objects_for_export(
            out,
            view_layer,
            respect_visibility=respect_visibility,
        )

    if len(source_publish_names) > 1:
        for obj_name in collect_mesh_names_for_merged_publishes(
            source_publish_names,
            context,
            view_layer=view_layer,
            respect_visibility=respect_visibility,
        ):
            obj = bpy.data.objects.get(obj_name)
            if obj is None or obj.type != "MESH":
                continue
            key = id(obj)
            if key in seen:
                continue
            seen.add(key)
            out.append(obj)
        out.sort(key=lambda o: o.name.lower())
        return filter_objects_for_export(
            out,
            view_layer,
            respect_visibility=respect_visibility,
        )

    for publish_name in source_publish_names:
        for obj in collect_publish_geo_mesh_objects_for_publish(
            publish_name,
            context,
            view_layer=view_layer,
            respect_visibility=respect_visibility,
        ):
            key = id(obj)
            if key in seen:
                continue
            seen.add(key)
            out.append(obj)
    out.sort(key=lambda o: o.name.lower())
    return filter_objects_for_export(
        out,
        view_layer,
        respect_visibility=respect_visibility,
    )


def collect_publish_geo_mesh_objects(
    context: Optional[bpy.types.Context] = None,
    *,
    view_layer: Optional[bpy.types.ViewLayer] = None,
    respect_visibility: Optional[bool] = None,
) -> list[bpy.types.Object]:
    """
    Meshes under ``<namespace>::Geo`` collections inside any *publish* collection.

    Walks linked rig override trees such as ``CHAR_TACHI_RIG_PUBLISH`` →
    ``tachirig::Geo`` → character meshes.
    """
    meshes: list[bpy.types.Object] = []
    seen: set[int] = set()

    for pub_coll in bpy.data.collections:
        if not is_publish_collection_name(pub_coll.name):
            continue
        for coll in _iter_collections_recursive(pub_coll):
            if coll is pub_coll:
                continue
            if not is_namespace_geo_name(coll.name):
                continue
            for obj in coll.all_objects:
                if obj.type != "MESH":
                    continue
                key = id(obj)
                if key in seen:
                    continue
                seen.add(key)
                meshes.append(obj)

        for obj in pub_coll.all_objects:
            if not is_namespace_geo_name(obj.name):
                continue
            stack = [obj]
            while stack:
                current = stack.pop()
                if current.type == "MESH":
                    key = id(current)
                    if key not in seen:
                        seen.add(key)
                        meshes.append(current)
                stack.extend(list(current.children))

    meshes.sort(key=lambda o: o.name.lower())
    view_layer, respect_visibility = resolve_export_visibility(
        context,
        view_layer=view_layer,
        respect_visibility=respect_visibility,
    )
    return filter_objects_for_export(
        meshes,
        view_layer,
        respect_visibility=respect_visibility,
    )


@dataclass(frozen=True)
class PublishGeoGroup:
    """Meshes from one linked ``*_publish*`` rig override."""

    publish_name: str
    geo_collections: tuple[str, ...]
    mesh_names: tuple[str, ...]

    @property
    def mesh_count(self) -> int:
        return len(self.mesh_names)


def _publish_root_for_mesh(obj: bpy.types.Object) -> Optional[str]:
    """Pick the publish override that owns this mesh (namespace-aware)."""
    obj_ns = _namespace_prefix_from_name(obj.name)
    candidates: list[str] = []

    for pub_coll in bpy.data.collections:
        if not is_publish_collection_name(pub_coll.name):
            continue
        if not _object_in_publish_collection(obj, pub_coll):
            continue
        if obj_ns:
            for coll in _iter_collections_recursive(pub_coll):
                if not is_namespace_geo_name(coll.name):
                    continue
                geo_ns = _namespace_prefix_from_name(coll.name)
                if geo_ns == obj_ns:
                    return pub_coll.name
        candidates.append(pub_coll.name)

    if not candidates:
        return None
    return max(candidates, key=len)


def collect_publish_geo_groups(
    context: Optional[bpy.types.Context] = None,
    *,
    view_layer: Optional[bpy.types.ViewLayer] = None,
    respect_visibility: Optional[bool] = None,
) -> list[PublishGeoGroup]:
    """Group publish-rig geo meshes by linked ``*_publish*`` collection."""
    buckets: dict[str, dict[str, Any]] = {}

    for obj in collect_publish_geo_mesh_objects(
        context,
        view_layer=view_layer,
        respect_visibility=respect_visibility,
    ):
        publish_name = _publish_root_for_mesh(obj) or "Unknown Publish"
        bucket = buckets.setdefault(
            publish_name,
            {"geo_collections": set(), "mesh_names": []},
        )
        bucket["mesh_names"].append(obj.name)
        for coll in obj.users_collection:
            if is_namespace_geo_name(coll.name):
                bucket["geo_collections"].add(coll.name)

    groups: list[PublishGeoGroup] = []
    for publish_name in sorted(buckets, key=str.lower):
        data = buckets[publish_name]
        names = sorted(set(data["mesh_names"]), key=str.lower)
        if not names:
            continue
        groups.append(
            PublishGeoGroup(
                publish_name=publish_name,
                geo_collections=tuple(sorted(data["geo_collections"], key=str.lower)),
                mesh_names=tuple(names),
            )
        )
    return groups


def camera_collection_label(cam_obj: bpy.types.Object) -> str:
    """Collection path hint for a camera (prefers Cameras / cam collections)."""
    for coll in cam_obj.users_collection:
        if is_camera_collection_name(coll.name):
            return coll.name
    for coll in bpy.data.collections:
        if not is_camera_collection_name(coll.name):
            continue
        if cam_obj.name in _object_names_in_collection(coll):
            return coll.name
    if cam_obj.users_collection:
        return cam_obj.users_collection[0].name
    return "—"


@dataclass(frozen=True)
class CameraExportRow:
    object_name: str
    collection_label: str
    motion_hint: str
    will_export: bool
    is_scene_camera: bool
    source: str


def _camera_has_object_keyframes(cam: bpy.types.Object) -> bool:
    anim = getattr(cam, "animation_data", None)
    if anim is None or anim.action is None:
        return False
    try:
        for fc in anim.action.fcurves:
            if fc.data_path.startswith(("location", "rotation", "scale")):
                return True
    except (AttributeError, TypeError):
        pass
    return False


def _camera_matrix_changed_over_range(
    cam: bpy.types.Object,
    scene: bpy.types.Scene,
    context: bpy.types.Context,
    frame_start: int,
    frame_end: int,
) -> bool:
    if frame_end <= frame_start:
        return False
    prev_frame = int(scene.frame_current)
    try:
        depsgraph = context.evaluated_depsgraph_get()
        scene.frame_set(int(frame_start))
        depsgraph.update()
        m0 = cam.evaluated_get(depsgraph).matrix_world.copy()
        scene.frame_set(int(frame_end))
        depsgraph.update()
        m1 = cam.evaluated_get(depsgraph).matrix_world.copy()
    except Exception:
        return False
    finally:
        try:
            scene.frame_set(prev_frame)
        except Exception:
            pass
    if (m0.translation - m1.translation).length > 1e-4:
        return True
    for i in range(3):
        for j in range(3):
            if abs(m0[i][j] - m1[i][j]) > 1e-4:
                return True
    return False


_RIG_TRACKING_CONSTRAINTS = frozenset(
    {"CHILD_OF", "COPY_ROTATION", "COPY_TRANSFORMS", "TRANSFORM", "DAMPED_TRACK", "TRACK_TO"}
)


def _camera_has_rig_constraints(cam: bpy.types.Object) -> bool:
    obj: Optional[bpy.types.Object] = cam
    while obj is not None:
        if any(c.type in _RIG_TRACKING_CONSTRAINTS for c in obj.constraints):
            return True
        obj = obj.parent
    return False


def camera_motion_hint(
    cam: bpy.types.Object,
    context: bpy.types.Context,
    *,
    frame_start: int,
    frame_end: int,
) -> str:
    """How the export camera is animated (UI hint)."""
    if _camera_has_object_keyframes(cam):
        return "Keyed"
    scene = context.scene
    rig_driven = _camera_has_rig_constraints(cam)
    if _camera_matrix_changed_over_range(cam, scene, context, frame_start, frame_end):
        if rig_driven:
            return "Rig-driven"
        return "Animated"
    if rig_driven:
        return "Rig-driven (static?)"
    return "Static"


def describe_camera_export_rows(
    context: bpy.types.Context,
    *,
    frame_start: Optional[int] = None,
    frame_end: Optional[int] = None,
) -> tuple[list[CameraExportRow], Optional[bpy.types.Object]]:
    scene = context.scene
    cameras = collect_camera_collection_objects(context)
    export_cam = pick_export_camera(cameras, scene, context)
    f0 = int(frame_start if frame_start is not None else scene.frame_start)
    f1 = int(frame_end if frame_end is not None else scene.frame_end)

    rows: list[CameraExportRow] = []
    if cameras:
        for cam in cameras:
            rows.append(
                CameraExportRow(
                    object_name=cam.name,
                    collection_label=camera_collection_label(cam),
                    motion_hint=camera_motion_hint(cam, context, frame_start=f0, frame_end=f1),
                    will_export=export_cam is not None and cam == export_cam,
                    is_scene_camera=scene is not None and scene.camera == cam,
                    source="Cameras",
                )
            )
        return rows, export_cam

    cam = scene.camera if scene is not None else None
    if cam is not None and cam.type == "CAMERA":
        leaf = strip_blender_namespace(cam.name).casefold()
        if leaf not in _DEFAULT_BLENDER_CAMERAS:
            view_layer, respect_visibility = resolve_export_visibility(context)
            visible = filter_objects_for_export(
                [cam],
                view_layer,
                respect_visibility=respect_visibility,
            )
            if not visible:
                return rows, None
            rows.append(
                CameraExportRow(
                    object_name=cam.name,
                    collection_label=camera_collection_label(cam),
                    motion_hint=camera_motion_hint(cam, context, frame_start=f0, frame_end=f1),
                    will_export=True,
                    is_scene_camera=True,
                    source="Scene Camera",
                )
            )
            return rows, cam
    return rows, None


def collect_camera_collection_objects(
    context: Optional[bpy.types.Context] = None,
    *,
    view_layer: Optional[bpy.types.ViewLayer] = None,
    respect_visibility: Optional[bool] = None,
) -> list[bpy.types.Object]:
    """
    Camera objects inside collections named ``Cameras``, ``camera``, or ``cam``.

    Walks the full collection hierarchy (including ``Anim_<shot>/Cameras``).
    """
    cameras: list[bpy.types.Object] = []
    seen: set[int] = set()

    for coll in bpy.data.collections:
        if not is_camera_collection_name(coll.name):
            continue
        for obj in coll.all_objects:
            if obj.type != "CAMERA":
                continue
            leaf = strip_blender_namespace(obj.name).casefold()
            if leaf in _DEFAULT_BLENDER_CAMERAS:
                continue
            key = id(obj)
            if key in seen:
                continue
            seen.add(key)
            cameras.append(obj)

    cameras.sort(key=lambda o: o.name.lower())
    view_layer, respect_visibility = resolve_export_visibility(
        context,
        view_layer=view_layer,
        respect_visibility=respect_visibility,
    )
    return filter_objects_for_export(
        cameras,
        view_layer,
        respect_visibility=respect_visibility,
    )


def pick_export_camera(
    cameras: Sequence[bpy.types.Object],
    scene: Optional[bpy.types.Scene],
    context: Optional[bpy.types.Context] = None,
) -> Optional[bpy.types.Object]:
    if not cameras:
        if scene is not None and scene.camera is not None:
            cam = scene.camera
            leaf = strip_blender_namespace(cam.name).casefold()
            if cam.type == "CAMERA" and leaf not in _DEFAULT_BLENDER_CAMERAS:
                view_layer, respect_visibility = resolve_export_visibility(context)
                visible = filter_objects_for_export(
                    [cam],
                    view_layer,
                    respect_visibility=respect_visibility,
                )
                return visible[0] if visible else None
        return None
    if scene is not None and scene.camera is not None:
        for cam in cameras:
            if cam == scene.camera:
                return cam
    return cameras[0]


def collect_export_camera_objects(
    context: bpy.types.Context,
) -> list[bpy.types.Object]:
    auto = collect_camera_collection_objects(context)
    if auto:
        return auto
    cam = context.scene.camera if context.scene else None
    if cam is not None and cam.type == "CAMERA":
        leaf = strip_blender_namespace(cam.name).casefold()
        if leaf not in _DEFAULT_BLENDER_CAMERAS:
            view_layer, respect_visibility = resolve_export_visibility(context)
            visible = filter_objects_for_export(
                [cam],
                view_layer,
                respect_visibility=respect_visibility,
            )
            return visible
    return []


def collect_export_mesh_objects(context: bpy.types.Context) -> list[bpy.types.Object]:
    """Auto-find publish rig geo meshes; fall back to current selection."""
    auto = collect_publish_geo_mesh_objects(context)
    if auto:
        return auto
    return collect_selected_mesh_objects(context)


def _object_by_name(name: str) -> Optional[bpy.types.Object]:
    try:
        return bpy.data.objects.get(name)
    except Exception:
        return None


def _ancestor_chain(obj: bpy.types.Object) -> list[bpy.types.Object]:
    chain: list[bpy.types.Object] = []
    current: Optional[bpy.types.Object] = obj
    while current is not None:
        chain.append(current)
        current = current.parent
    chain.reverse()
    return chain


def _assign_paths_top_down(
    mesh_objects: Sequence[bpy.types.Object],
    *,
    root_override: str = "",
) -> dict[str, _HierarchyNode]:
    mesh_names = {o.name for o in mesh_objects}
    included: set[str] = set()
    parent_of: dict[str, Optional[str]] = {}

    for mesh_obj in mesh_objects:
        for obj in _ancestor_chain(mesh_obj):
            included.add(obj.name)
            parent_of[obj.name] = obj.parent.name if obj.parent else None

    roots = sorted(n for n in included if parent_of.get(n) not in included)
    children: dict[str, list[str]] = {name: [] for name in included}
    for name in included:
        parent = parent_of.get(name)
        if parent in included:
            children.setdefault(parent, []).append(name)

    root_namespaces = {
        namespace_prefix_from_name(name) for name in roots if namespace_prefix_from_name(name)
    }
    multi_instance = len(root_namespaces) > 1

    nodes: dict[str, _HierarchyNode] = {}
    used_siblings: dict[str, set[str]] = {}

    def _walk(obj_name: str, parent_path: str) -> None:
        obj = _object_by_name(obj_name)
        raw_name = obj.name if obj else obj_name
        segment = sanitize_prim_segment(raw_name)
        if not parent_path and root_override.strip():
            segment = sanitize_prim_segment(root_override.strip())
        sibling_key = parent_path or "/"
        used = used_siblings.setdefault(sibling_key, set())
        segment = dedupe_sibling_segment(segment, used)
        prim_path = (
            segments_to_prim_path([segment])
            if not parent_path
            else f"{parent_path}/{segment}"
        )
        nodes[obj_name] = _HierarchyNode(
            obj_name=obj_name,
            parent_name=parent_of.get(obj_name),
            is_mesh=obj_name in mesh_names,
            prim_path=prim_path,
        )
        for child_name in sorted(children.get(obj_name, [])):
            _walk(child_name, prim_path)

    for root_name in roots:
        start_path = multi_instance_root_path(
            root_name,
            multi_instance=multi_instance,
            used_siblings=used_siblings,
        )
        _walk(root_name, start_path)
    return nodes


def _collect_hierarchy_nodes(
    mesh_objects: Sequence[bpy.types.Object],
    *,
    root_override: str = "",
) -> dict[str, _HierarchyNode]:
    """Build stable prim paths for all ancestors of selected meshes."""
    return _assign_paths_top_down(
        mesh_objects,
        root_override=root_override,
    )


def _collect_camera_hierarchy_nodes(
    cam_obj: bpy.types.Object,
) -> dict[str, _HierarchyNode]:
    """Include camera rig parents (``*_root`` / ``*_body`` / …) in the USD stage."""
    return _collect_hierarchy_nodes([cam_obj])


def _get_evaluated_mesh(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
) -> tuple[Optional[bpy.types.Mesh], bool]:
    """Return (mesh, needs_clear)."""
    eval_obj = obj.evaluated_get(depsgraph)
    if hasattr(eval_obj, "evaluated_geometry"):
        try:
            geom = eval_obj.evaluated_geometry()
            if geom and getattr(geom, "type", "") == "MESH":
                return geom, False
        except Exception as exc:
            logger.warning("evaluated_geometry failed for %s: %s", obj.name, exc)
    try:
        mesh = eval_obj.to_mesh(
            preserve_all_data_layers=False,
            depsgraph=depsgraph,
        )
        return mesh, True
    except Exception as exc:
        logger.error("to_mesh failed for %s: %s", obj.name, exc)
        return None, False


def _release_evaluated_mesh(obj: bpy.types.Object, needs_clear: bool) -> None:
    if not needs_clear:
        return
    try:
        if hasattr(obj, "to_mesh_clear"):
            obj.to_mesh_clear()
    except Exception:
        pass


def _extract_topology(mesh: bpy.types.Mesh) -> _MeshTopology:
    face_vertex_counts: list[int] = []
    face_vertex_indices: list[int] = []
    for poly in mesh.polygons:
        face_vertex_counts.append(len(poly.vertices))
        face_vertex_indices.extend(int(i) for i in poly.vertices)
    return _MeshTopology(
        face_vertex_counts=tuple(face_vertex_counts),
        face_vertex_indices=tuple(face_vertex_indices),
    )


def _extract_local_mesh_points(
    mesh: bpy.types.Mesh,
    *,
    unit_scale: float,
) -> list[Gf.Vec3f]:
    """
    Evaluated mesh points in object-local space (no axis reorientation).

    Lookdev publish applies Z-up → Y-up on Xform ops; points stay object-local.
    """
    points: list[Gf.Vec3f] = []
    for vert in mesh.vertices:
        local = vert.co
        if unit_scale != 1.0:
            local = local * unit_scale
        points.append(vector_to_gf(local))
    return points


def _write_publish_meta(
    version_dir: Path,
    *,
    geo_paths: Sequence[Path],
    fps: float,
    frame_start: int,
    frame_end: int,
    camera_path: Optional[Path] = None,
) -> None:
    outputs = [
        {
            "file": geo_path.name,
            "type": "geo",
        }
        for geo_path in geo_paths
    ]
    if camera_path is not None:
        outputs.append(
            {
                "file": camera_path.name,
                "type": "cam",
            }
        )
    meta = {
        "fps": float(fps),
        "playback_range": [int(frame_start), int(frame_end)],
        "outputs": outputs,
    }
    meta_path = version_dir / "publish_meta.json"
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)
        handle.write("\n")
    logger.info("Wrote publish meta: %s", meta_path)


class UsdAnimCacheExporter:
    """Export selected meshes as a deformation-only USD animation cache."""

    def __init__(
        self,
        context: bpy.types.Context,
        filepath: str,
        *,
        frame_start: int,
        frame_end: int,
        fps: float,
        root_prim_override: str = "",
        strict_topology: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> None:
        self.context = context
        self.filepath = str(filepath)
        self.frame_start = int(frame_start)
        self.frame_end = int(frame_end)
        self.fps = float(fps)
        self.root_prim_override = (root_prim_override or "").strip()
        self.strict_topology = bool(strict_topology)
        self.progress_callback = progress_callback

    def export(self) -> UsdAnimCacheExportResult:
        session = UsdAnimCacheExportSession(
            self.context,
            self.filepath,
            frame_start=self.frame_start,
            frame_end=self.frame_end,
            fps=self.fps,
            root_prim_override=self.root_prim_override,
            strict_topology=self.strict_topology,
        )
        err = session.begin()
        if err:
            return UsdAnimCacheExportResult(ok=False, error=err)
        while not session.done:
            err = session.step(frames_per_tick=1)
            if self.progress_callback:
                self.progress_callback(
                    session.current_step,
                    session.total_steps,
                    session.status_label,
                )
            if err:
                session.cancel()
                out = session.result
                out.ok = False
                out.error = err
                return out
        return session.finish()


class UsdAnimCacheExportSession:
    """Incremental USD anim cache export — one mesh per timer tick keeps UI responsive."""

    def __init__(
        self,
        context: bpy.types.Context,
        filepath: str,
        *,
        frame_start: int,
        frame_end: int,
        fps: float,
        root_prim_override: str = "",
        strict_topology: bool = True,
        mesh_objects: Optional[Sequence[bpy.types.Object]] = None,
        export_camera: bool = True,
        write_publish_meta: bool = True,
        job_label: str = "",
    ) -> None:
        self.context = context
        self.filepath = str(filepath)
        self.frame_start = int(frame_start)
        self.frame_end = int(frame_end)
        self.fps = float(fps)
        self.root_prim_override = (root_prim_override or "").strip()
        self.strict_topology = bool(strict_topology)
        self._mesh_objects_override = list(mesh_objects) if mesh_objects is not None else None
        self.export_camera = bool(export_camera)
        self.write_publish_meta = bool(write_publish_meta)
        self.job_label = (job_label or "").strip()

        self.result = UsdAnimCacheExportResult(ok=False)
        self.status_label = ""
        self._current_frame = self.frame_start
        self._initialized = False
        self._finished = False
        self._cancelled = False
        self._step = 0
        self._frames_written = 0
        self._prev_frame: Optional[int] = None
        self._out_path: Optional[Path] = None
        self._scene: Optional[bpy.types.Scene] = None
        self._mesh_objects: list[bpy.types.Object] = []
        self._camera_objects: list[bpy.types.Object] = []
        self._camera_obj: Optional[bpy.types.Object] = None
        self._total_steps = 1
        self._stage = None
        self._writer: Optional[UsdAnimCacheMeshWriter] = None
        self._cam_out_path: Optional[Path] = None
        self._hierarchy: dict[str, _HierarchyNode] = {}
        self._mesh_prims: dict[str, UsdGeom.Mesh] = {}
        self._reference_topology: dict[str, _MeshTopology] = {}
        self._depsgraph = None
        self._orient_matrix = None
        self._xform_prims: dict[str, UsdGeom.Xform] = {}
        self._unit_scale = 1.0
        self._start_time: Optional[float] = None
        self._mesh_index = 0
        self._frame_depsgraph_ready = False

    def _ensure_frame_evaluated(self) -> None:
        if self._scene is None or self._depsgraph is None or self._frame_depsgraph_ready:
            return
        self._scene.frame_set(self._current_frame)
        try:
            self.context.view_layer.update()
        except Exception:
            pass
        self._depsgraph.update()
        self._frame_depsgraph_ready = True

    def _advance_frame(self) -> None:
        self._frames_written += 1
        self._current_frame += 1
        self._mesh_index = 0
        self._frame_depsgraph_ready = False
        if self._current_frame > self.frame_end:
            self._finished = True

    def _export_mesh_frame(
        self,
        mesh_obj: bpy.types.Object,
        frame: int,
    ) -> Optional[str]:
        if self._writer is None or self._depsgraph is None:
            return "Export session is not initialized."
        node = self._hierarchy.get(mesh_obj.name)
        if node is None:
            return None
        self.status_label = (
            (f"{self.job_label}: " if self.job_label else "")
            + f"Frame {frame}: {strip_blender_namespace(mesh_obj.name)}"
        )
        eval_obj = mesh_obj.evaluated_get(self._depsgraph)
        mesh_data, needs_clear = _get_evaluated_mesh(mesh_obj, self._depsgraph)
        if mesh_data is None:
            msg = f"Frame {frame}: no evaluated mesh for {mesh_obj.name}"
            self.result.warnings.append(msg)
            logger.warning(msg)
            return None

        try:
            topo = _extract_topology(mesh_data)
            if mesh_obj.name not in self._reference_topology:
                self._reference_topology[mesh_obj.name] = topo
                self._writer.write_topology(
                    self._mesh_prims[mesh_obj.name],
                    topo.face_vertex_counts,
                    topo.face_vertex_indices,
                )
            elif topo != self._reference_topology[mesh_obj.name]:
                msg = (
                    f"Frame {frame}: topology changed on "
                    f"{strip_blender_namespace(mesh_obj.name)}"
                )
                self.result.warnings.append(msg)
                logger.warning(msg)
                if self.strict_topology:
                    return msg
                return None

            points = _extract_local_mesh_points(
                mesh_data,
                unit_scale=self._unit_scale,
            )
            self._writer.write_frame(
                self._mesh_prims[mesh_obj.name],
                points,
                float(frame),
            )
        finally:
            _release_evaluated_mesh(eval_obj, needs_clear)
        return None

    @property
    def elapsed_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.perf_counter() - self._start_time

    @property
    def elapsed_label(self) -> str:
        return format_export_elapsed(self.elapsed_seconds)

    @property
    def remaining_seconds(self) -> Optional[float]:
        return estimate_export_remaining_seconds(
            self.elapsed_seconds,
            self._step,
            self._total_steps,
        )

    @property
    def remaining_label(self) -> str:
        remaining = self.remaining_seconds
        if remaining is None:
            return "…"
        return format_export_elapsed(remaining)

    @property
    def progress_percent(self) -> int:
        total = max(self._total_steps, 1)
        return int(round(100.0 * self._step / total))

    @property
    def frame_count(self) -> int:
        return max(0, self.frame_end - self.frame_start + 1)

    @property
    def geo_steps_total(self) -> int:
        return self.frame_count * len(self._mesh_objects)

    @property
    def camera_steps_total(self) -> int:
        return 0

    @property
    def is_camera_phase(self) -> bool:
        if self._camera_obj is None or self._finished:
            return False
        return self.geo_steps_total == 0 or self._step >= self.geo_steps_total

    @property
    def geo_progress_time_label(self) -> str:
        total = max(1, self.geo_steps_total)
        current = min(self._step, total)
        return format_progress_time_label(self.elapsed_seconds, current, total)

    @property
    def camera_progress_time_label(self) -> str:
        return "wm.usd_export"

    @property
    def progress_time_label(self) -> str:
        return format_progress_time_label(
            self.elapsed_seconds,
            self._step,
            self._total_steps,
        )

    @property
    def total_steps(self) -> int:
        return self._total_steps

    @property
    def current_step(self) -> int:
        return self._step

    @property
    def done(self) -> bool:
        return self._finished or self._cancelled

    def begin(self) -> Optional[str]:
        _setup_logging()

        self._mesh_objects = (
            list(self._mesh_objects_override)
            if self._mesh_objects_override is not None
            else collect_export_mesh_objects(self.context)
        )
        if not self._mesh_objects and not self.export_camera:
            return (
                "No mesh objects to export. Link a *_publish* rig with a "
                "<namespace>::Geo collection, or select mesh object(s)."
            )
        if self.frame_end < self.frame_start:
            return "Frame End must be >= Frame Start."

        if not PXR_AVAILABLE and self._mesh_objects:
            return "OpenUSD (pxr) is not available in this Blender build."

        out_path = Path(self.filepath)
        if out_path.suffix.lower() != ".usd":
            out_path = out_path.with_suffix(".usd")
        out_dir = out_path.parent
        if out_dir and not out_dir.is_dir():
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as exc:
                return f"Cannot create output directory: {exc}"

        self._out_path = out_path
        self._scene = self.context.scene
        self._camera_objects = collect_export_camera_objects(self.context)
        self._camera_obj = (
            pick_export_camera(self._camera_objects, self._scene, self.context)
            if self.export_camera
            else None
        )
        self._prev_frame = int(self._scene.frame_current)
        self._orient_matrix = resolve_orientation_matrix(self.context)
        self._unit_scale = meters_scale_from_scene(self._scene)
        self._hierarchy = _collect_hierarchy_nodes(
            self._mesh_objects,
            root_override=self.root_prim_override,
        )
        steps_per_frame = len(self._mesh_objects)
        if steps_per_frame:
            self._total_steps = max(
                1,
                (self.frame_end - self.frame_start + 1) * steps_per_frame,
            )
        else:
            self._total_steps = 1

        cam_note = ""
        if self._camera_obj is not None:
            cam_note = f", camera {strip_blender_namespace(self._camera_obj.name)}"
        label = f" ({self.job_label})" if self.job_label else ""
        logger.info(
            "Exporting %d mesh(es)%s%s, frames %d–%d → %s",
            len(self._mesh_objects),
            label,
            cam_note,
            self.frame_start,
            self.frame_end,
            out_path,
        )

        try:
            if self._mesh_objects:
                self._stage = Usd.Stage.CreateNew(str(out_path))
                UsdGeom.SetStageUpAxis(self._stage, UsdGeom.Tokens.y)
                UsdGeom.SetStageMetersPerUnit(self._stage, 1.0)
                self._stage.SetTimeCodesPerSecond(self.fps)
                self._stage.SetStartTimeCode(float(self.frame_start))
                self._stage.SetEndTimeCode(float(self.frame_end))

                self._writer = UsdAnimCacheMeshWriter(self._stage)
                self._xform_prims = {}
                for node in self._hierarchy.values():
                    if node.is_mesh:
                        self._mesh_prims[node.obj_name] = self._writer.define_mesh(
                            node.prim_path
                        )
                    else:
                        self._xform_prims[node.obj_name] = UsdGeom.Xform.Define(
                            self._stage, node.prim_path
                        )

                author_hierarchy_bind_xforms(
                    context=self.context,
                    hierarchy=self._hierarchy,
                    mesh_prims=self._mesh_prims,
                    xform_prims=self._xform_prims,
                    frame=self.frame_start,
                    orient_matrix=self._orient_matrix,
                    unit_scale=self._unit_scale,
                )
            else:
                self._stage = None
                self._writer = None

            self._depsgraph = self.context.evaluated_depsgraph_get()
            if self._camera_obj is not None:
                from .anim_usd_cache_paths_ui import scene_blend_path

                self._cam_out_path = camera_usd_output_path(
                    out_path.parent,
                    self._camera_obj.name,
                    scene_path=scene_blend_path(),
                )
                logger.info(
                    "Camera will export via wm.usd_export → %s",
                    self._cam_out_path,
                )

            if not self._mesh_objects and self._camera_obj is not None:
                self._finished = True
                self._step = self._total_steps

            self._current_frame = self.frame_start
            self._start_time = time.perf_counter()
            self._initialized = True
            return None
        except Exception as exc:
            logger.exception("USD anim cache export setup failed")
            return str(exc)

    def step(self, *, units_per_tick: int = 1, frames_per_tick: int = 1) -> Optional[str]:
        del frames_per_tick  # legacy alias; export is mesh-unit based now
        if self._cancelled or self._finished or not self._initialized:
            return None
        if self._scene is None or self._depsgraph is None:
            return "Export session is not initialized."
        if self._writer is None and not self._mesh_objects and self._camera_obj is None:
            return "Export session is not initialized."

        mesh_count = len(self._mesh_objects)
        if mesh_count == 0:
            self._finished = True
            self._step = self._total_steps
            return None

        batch = max(1, int(units_per_tick))

        for _ in range(batch):
            if self._cancelled or self._finished:
                break
            if self._current_frame > self.frame_end:
                self._finished = True
                break

            frame = self._current_frame
            self.status_label = f"Frame {frame}"

            if self._mesh_index < mesh_count:
                self._ensure_frame_evaluated()
                err = self._export_mesh_frame(self._mesh_objects[self._mesh_index], frame)
                if err:
                    return err
                self._mesh_index += 1
                self._step += 1
                continue

            self._advance_frame()

        return None

    def _export_camera_via_blender_usd(self) -> Optional[str]:
        if self._camera_obj is None or self._cam_out_path is None:
            return None
        props = getattr(self.context.scene, "monofx_pipeline_blender_props", None)
        convert_orientation = bool(getattr(props, "convert_orientation", True))
        export_forward = str(
            getattr(props, "export_forward_axis", config.DEFAULT_EXPORT_FORWARD)
        )
        export_up = str(getattr(props, "export_up_axis", config.DEFAULT_EXPORT_UP))
        convert_units = str(
            getattr(props, "convert_scene_units", config.DEFAULT_CONVERT_SCENE_UNITS)
        )
        self.status_label = (
            (f"{self.job_label}: " if self.job_label else "")
            + f"Camera: {strip_blender_namespace(self._camera_obj.name)}"
        )
        try:
            export_camera_anim_usd_cache(
                self.context,
                self._camera_obj,
                str(self._cam_out_path),
                frame_start=self.frame_start,
                frame_end=self.frame_end,
                convert_orientation=convert_orientation,
                export_forward_axis=export_forward,
                export_up_axis=export_up,
                convert_scene_units=convert_units,
            )
        except Exception as exc:
            logger.exception("Camera wm.usd_export failed")
            return str(exc)
        return None

    def finish(self) -> UsdAnimCacheExportResult:
        if self._cancelled:
            return self.result
        if not self._initialized or self._out_path is None:
            self.result.error = "Export session is not initialized."
            return self.result

        try:
            if self._stage is not None:
                self._stage.GetRootLayer().Save()
            if self._camera_obj is not None and self.export_camera:
                cam_err = self._export_camera_via_blender_usd()
                if cam_err:
                    self.result.error = cam_err
                    return self.result
            if self.write_publish_meta:
                _write_publish_meta(
                    self._out_path.parent,
                    geo_paths=[self._out_path] if self._stage is not None else [],
                    fps=self.fps,
                    frame_start=self.frame_start,
                    frame_end=self.frame_end,
                    camera_path=self._cam_out_path,
                )
            self.result.ok = True
            if self._stage is not None:
                self.result.filepath = str(self._out_path)
                self.result.geo_filepaths = [str(self._out_path)]
            elif self._cam_out_path is not None:
                self.result.filepath = str(self._cam_out_path)
                self.result.geo_filepaths = []
            self.result.frames_written = self._frames_written
            self.result.mesh_count = len(self._mesh_objects)
            self.result.elapsed_seconds = self.elapsed_seconds
            if self._cam_out_path is not None:
                self.result.camera_filepath = str(self._cam_out_path)
                self.result.camera_count = 1 if self._camera_obj else 0
            logger.info(
                "Export complete: %d frames, %d meshes, %s in %s → %s",
                self._frames_written,
                len(self._mesh_objects),
                f"1 camera ({self._cam_out_path.name})"
                if self._cam_out_path
                else "no camera",
                self.elapsed_label,
                self._out_path,
            )
        except Exception as exc:
            self.result.error = str(exc)
            logger.exception("USD anim cache export save failed")
        finally:
            self._restore_frame()
        return self.result

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        self._restore_frame()
        if self._out_path is not None and self._out_path.is_file():
            try:
                self._out_path.unlink()
            except OSError:
                pass
        if self._cam_out_path is not None and self._cam_out_path.is_file():
            try:
                self._cam_out_path.unlink()
            except OSError:
                pass

    def _restore_frame(self) -> None:
        if self._scene is None or self._prev_frame is None:
            return
        try:
            self._scene.frame_set(self._prev_frame)
        except Exception:
            pass
        self._depsgraph = None


class UsdAnimCacheMultiExportSession:
    """Queue one USD file per linked rig (Maya-style), camera on the last job."""

    def __init__(
        self,
        context: bpy.types.Context,
        jobs: Sequence[Any],
        *,
        frame_start: int,
        frame_end: int,
        fps: float,
        root_prim_override: str = "",
        strict_topology: bool = True,
        export_camera: bool = True,
    ) -> None:
        self.context = context
        self.jobs = list(jobs)
        self.frame_start = int(frame_start)
        self.frame_end = int(frame_end)
        self.fps = float(fps)
        self.root_prim_override = (root_prim_override or "").strip()
        self.strict_topology = bool(strict_topology)
        self._export_camera = bool(export_camera)

        self.result = UsdAnimCacheExportResult(ok=False)
        self.status_label = ""
        self._job_index = 0
        self._session: Optional[UsdAnimCacheExportSession] = None
        self._finished = False
        self._cancelled = False
        self._completed_steps = 0
        self._total_steps = 1
        self._start_time: Optional[float] = None
        self._completed_geo_paths: list[Path] = []
        self._camera_path: Optional[Path] = None
        self._total_mesh_count = 0
        self._total_frames_written = 0

    def _mesh_objects_for_job(self, job: Any) -> list[bpy.types.Object]:
        publish_names = tuple(getattr(job, "source_publish_names", ()) or ())
        return resolve_geo_job_mesh_objects(
            job.mesh_names,
            source_publish_names=publish_names,
            context=self.context,
        )

    def _is_last_job(self) -> bool:
        return self._job_index >= len(self.jobs) - 1

    def _start_current_job(self) -> Optional[str]:
        if self._job_index >= len(self.jobs):
            self._finished = True
            return None
        job = self.jobs[self._job_index]
        meshes = self._mesh_objects_for_job(job)
        if not meshes:
            return f"No mesh objects found for rig {job.publish_name}."

        self._session = UsdAnimCacheExportSession(
            self.context,
            job.filepath,
            frame_start=self.frame_start,
            frame_end=self.frame_end,
            fps=self.fps,
            root_prim_override=self.root_prim_override,
            strict_topology=self.strict_topology,
            mesh_objects=meshes,
            export_camera=self._is_last_job() and self._export_camera,
            write_publish_meta=False,
            job_label=job.publish_name,
        )
        err = self._session.begin()
        if err:
            return err
        if self._start_time is None:
            self._start_time = time.perf_counter()
        return None

    @property
    def elapsed_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.perf_counter() - self._start_time

    @property
    def elapsed_label(self) -> str:
        return format_export_elapsed(self.elapsed_seconds)

    @property
    def remaining_seconds(self) -> Optional[float]:
        return estimate_export_remaining_seconds(
            self.elapsed_seconds,
            self.current_step,
            self.total_steps,
        )

    @property
    def remaining_label(self) -> str:
        remaining = self.remaining_seconds
        if remaining is None:
            return "…"
        return format_export_elapsed(remaining)

    @property
    def progress_percent(self) -> int:
        total = max(self.total_steps, 1)
        return int(round(100.0 * self.current_step / total))

    @property
    def progress_time_label(self) -> str:
        return format_progress_time_label(
            self.elapsed_seconds,
            self.current_step,
            self.total_steps,
        )

    @property
    def total_steps(self) -> int:
        return self._total_steps

    @property
    def current_step(self) -> int:
        session_steps = self._session.current_step if self._session else 0
        return self._completed_steps + session_steps

    @property
    def done(self) -> bool:
        return self._finished or self._cancelled

    def begin(self) -> Optional[str]:
        if not PXR_AVAILABLE:
            return "OpenUSD (pxr) is not available in this Blender build."
        if not self.jobs:
            return "No export jobs planned."
        if self.frame_end < self.frame_start:
            return "Frame End must be >= Frame Start."

        self._total_steps = 0
        for job in self.jobs:
            meshes = self._mesh_objects_for_job(job)
            if not meshes:
                return f"No mesh objects found for rig {job.publish_name}."
            cam_steps = 0
            frame_count = self.frame_end - self.frame_start + 1
            self._total_steps += frame_count * len(meshes)
        self._total_steps = max(self._total_steps, 1)
        return self._start_current_job()

    def step(self, *, units_per_tick: int = 1, frames_per_tick: int = 1) -> Optional[str]:
        del frames_per_tick
        if self._cancelled or self._finished:
            return None
        if self._session is None:
            return "Export session is not initialized."

        err = self._session.step(units_per_tick=units_per_tick)
        if self._session is not None and self._session.status_label:
            self.status_label = self._session.status_label

        if err:
            return err
        if not self._session.done:
            return None

        partial = self._session.finish()
        if not partial.ok and partial.error:
            return partial.error

        self.result.warnings.extend(partial.warnings)
        if partial.filepath:
            geo_path = Path(partial.filepath)
            self._completed_geo_paths.append(geo_path)
        if partial.camera_filepath:
            self._camera_path = Path(partial.camera_filepath)
        self._total_mesh_count += partial.mesh_count
        self._total_frames_written = max(self._total_frames_written, partial.frames_written)
        self._completed_steps += self._session.total_steps
        self._session = None
        self._job_index += 1

        if self._job_index >= len(self.jobs):
            self._finished = True
            return None
        return self._start_current_job()

    def finish(self) -> UsdAnimCacheExportResult:
        if self._cancelled:
            return self.result
        if not self._finished or not self._completed_geo_paths:
            self.result.error = "Export session did not complete."
            return self.result

        try:
            _write_publish_meta(
                self._completed_geo_paths[0].parent,
                geo_paths=self._completed_geo_paths,
                fps=self.fps,
                frame_start=self.frame_start,
                frame_end=self.frame_end,
                camera_path=self._camera_path,
            )
            self.result.ok = True
            self.result.filepath = str(self._completed_geo_paths[0])
            self.result.geo_filepaths = [str(p) for p in self._completed_geo_paths]
            self.result.mesh_count = self._total_mesh_count
            self.result.frames_written = self._total_frames_written
            self.result.elapsed_seconds = self.elapsed_seconds
            if self._camera_path is not None:
                self.result.camera_filepath = str(self._camera_path)
                self.result.camera_count = 1
        except Exception as exc:
            self.result.error = str(exc)
            logger.exception("USD multi-rig export finalize failed")
        return self.result

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        if self._session is not None:
            self._session.cancel()
        for geo_path in self._completed_geo_paths:
            if geo_path.is_file():
                try:
                    geo_path.unlink()
                except OSError:
                    pass
        if self._camera_path is not None and self._camera_path.is_file():
            try:
                self._camera_path.unlink()
            except OSError:
                pass


def check_pxr_available() -> tuple[bool, str]:
    if PXR_AVAILABLE:
        return True, ""
    return False, "OpenUSD Python bindings (pxr) are not available in this Blender build."
