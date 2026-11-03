"""
Export target list for Anim USD cache (geo, camera, future custom assets).
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Optional, Sequence

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Context, PropertyGroup, UIList, UILayout

from monofx_pipeline_common.anim_geo_naming import (
    alloc_unique_basename,
    sanitize_filename_component,
)

from .anim_usd_cache_camera_writer import camera_usd_output_path
from .anim_usd_cache_exporter import describe_camera_export_rows
from .anim_usd_cache_paths import (
    is_camera_collection_name,
    is_namespace_geo_name,
    is_publish_collection_name,
)
from .anim_usd_cache_paths_ui import ensure_usd_extension, scene_blend_path
from .anim_usd_export_planner import (
    plan_custom_mesh_geo_job,
    plan_geo_export_jobs,
    resolve_export_output_dir,
)

_ASSET_KIND_ITEMS = (
    ("GEO", "Geo", "Deformation mesh cache"),
    ("CAMERA", "Camera", "Animated camera"),
    ("CUSTOM", "Custom", "Custom export target"),
)

_STATUS_ITEMS = (
    ("PENDING", "Pending", "Waiting to export"),
    ("EXPORTING", "Exporting", "Export in progress"),
    ("DONE", "Done", "Export finished"),
    ("ERROR", "Error", "Export failed"),
    ("SKIPPED", "Skipped", "Not exported"),
    ("CANCELLED", "Cancelled", "Export cancelled"),
)

_STATUS_ICONS = {
    "PENDING": "TIME",
    "EXPORTING": "SORTTIME",
    "DONE": "CHECKMARK",
    "ERROR": "CANCEL",
    "SKIPPED": "BLANK1",
    "CANCELLED": "X",
}

_KIND_ICONS = {
    "GEO": "MESH_DATA",
    "CAMERA": "OUTLINER_OB_CAMERA",
    "CUSTOM": "OBJECT_DATA",
}
_anim_usd_refresh_timer = None
_anim_usd_refresh_scene_name: Optional[str] = None
_anim_usd_refresh_pending = False
_ANIM_USD_REFRESH_INTERVAL_S = 0.75


def export_assets_refresh_pending() -> bool:
    return bool(_anim_usd_refresh_pending)


def _lightweight_scene_export_signature(context: Context) -> str:
    """Collection-level scene fingerprint — no depsgraph, visibility, or parenting walks."""
    geo_parts: list[str] = []
    for pub_coll in bpy.data.collections:
        if not is_publish_collection_name(pub_coll.name):
            continue
        mesh_ids: set[int] = set()
        try:
            child_collections = pub_coll.children_recursive
        except Exception:
            child_collections = [pub_coll]
        for coll in child_collections:
            if not is_namespace_geo_name(coll.name):
                continue
            try:
                objects = coll.all_objects
            except Exception:
                objects = coll.objects
            for obj in objects:
                if obj.type == "MESH":
                    mesh_ids.add(id(obj))
        geo_parts.append(f"{pub_coll.name}:{len(mesh_ids)}")

    cam_names: set[str] = set()
    scene = context.scene
    if scene is not None and scene.camera is not None:
        cam_names.add(scene.camera.name)
    for coll in bpy.data.collections:
        if not is_camera_collection_name(coll.name):
            continue
        for obj in coll.objects:
            if obj.type == "CAMERA":
                cam_names.add(obj.name)
    cam_part = ",".join(sorted(cam_names, key=str.lower))
    return f"{'|'.join(sorted(geo_parts, key=str.lower))}#cams:{cam_part}"


def _tag_anim_usd_panel_redraw(context: Optional[Context] = None) -> None:
    """Redraw sidebar UI only — avoid tagging VIEW_3D (triggers depsgraph eval)."""
    if context is not None and getattr(context, "area", None) is not None:
        context.area.tag_redraw()
        return
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            for region in area.regions:
                if region.type == "UI":
                    region.tag_redraw()


def normalize_output_usd_filename(raw: str) -> str:
    """Return a safe ``*.usd`` basename, or empty if ``raw`` is blank."""
    text = (raw or "").strip()
    if not text or text == "—":
        return ""
    name = Path(text.replace("\\", "/")).name
    suffix = Path(name).suffix.lower()
    stem = Path(name).stem if suffix in {".usd", ".usda", ".usdc", ".usdz"} else name
    stem = sanitize_filename_component(stem)
    if not stem:
        return ""
    return f"{stem}.usd"


def _update_anim_usd_output_file(self, _context) -> None:
    """RNA update callback — must be a real function (Blender won't resolve lambdas)."""
    normalized = normalize_output_usd_filename(self.output_file)
    if normalized and self.output_file != normalized:
        self.output_file = normalized


class AnimUsdExportAssetItem(PropertyGroup):
    asset_id: StringProperty(name="Asset ID", default="")
    display_name: StringProperty(name="Name", default="")
    asset_kind: EnumProperty(
        name="Kind",
        items=_ASSET_KIND_ITEMS,
        default="GEO",
    )
    detail: StringProperty(name="Detail", default="")
    output_file: StringProperty(
        name="Output File",
        description="USD filename written into the publish folder (editable)",
        default="",
        update=_update_anim_usd_output_file,
    )
    # Newline-separated mesh object names (CUSTOM targets).
    mesh_names: StringProperty(name="Mesh Names", default="")
    enabled: BoolProperty(name="Enabled", default=True)
    status: EnumProperty(
        name="Status",
        items=_STATUS_ITEMS,
        default="PENDING",
    )
    status_detail: StringProperty(name="Status Detail", default="")


def _frame_range(context: Context, props) -> tuple[int, int]:
    scene = context.scene
    if props.anim_usd_use_scene_range:
        return int(scene.frame_start), int(scene.frame_end)
    return int(props.anim_usd_frame_start), int(props.anim_usd_frame_end)


def _camera_output_basename(context: Context, props, export_cam) -> str:
    ok_dir, out_dir, _ = resolve_export_output_dir(props)
    if ok_dir and export_cam is not None:
        return camera_usd_output_path(
            out_dir,
            export_cam.name,
            scene_path=scene_blend_path(),
        ).name
    return "—"


def compute_export_assets_signature(context: Context, props) -> str:
    """Lightweight scene signature for export-target refresh (no depsgraph eval)."""
    from .anim_usd_cache_paths_ui import resolve_anim_publish_version_number

    job_part = _lightweight_scene_export_signature(context)
    f0, f1 = _frame_range(context, props)
    merge = bool(getattr(props, "anim_usd_merge_by_link", False))
    skip_hidden = bool(getattr(props, "anim_usd_skip_view_hidden", False))
    mode = str(getattr(props, "anim_usd_version_mode", "") or "NEXT")
    version = resolve_anim_publish_version_number(props)
    return (
        f"{job_part}#v{version}#{mode}#"
        f"{f0}-{f1}#merge={int(merge)}#skiphidden={int(skip_hidden)}"
    )


def _find_asset_item(props, asset_id: str) -> Optional[AnimUsdExportAssetItem]:
    for item in props.anim_usd_export_assets:
        if item.asset_id == asset_id:
            return item
    return None


def _snapshot_enabled_flags(props) -> dict[str, bool]:
    return {item.asset_id: bool(item.enabled) for item in props.anim_usd_export_assets}


def _snapshot_output_files(props) -> dict[str, str]:
    return {
        item.asset_id: str(item.output_file or "")
        for item in props.anim_usd_export_assets
        if item.asset_id
    }


def _resolve_output_file_for_item(
    *,
    asset_id: str,
    auto_name: str,
    prev_outputs: dict[str, str],
) -> str:
    prev = normalize_output_usd_filename(prev_outputs.get(asset_id, ""))
    if prev:
        return prev
    return normalize_output_usd_filename(auto_name) or auto_name or "—"


def apply_list_output_overrides(jobs, props, out_dir: Path) -> list:
    """Remap job filepaths to editable ``output_file`` values from the list.

    Read-only on RNA — safe to call from ``Operator.draw()``.
    """
    used: set[str] = set()
    result: list = []
    for job in jobs:
        item = _find_asset_item(props, geo_asset_id_for_job(job))
        override = ""
        if item is not None:
            override = normalize_output_usd_filename(item.output_file)
        if override:
            stem = alloc_unique_basename(Path(override).stem, used)
            filename = f"{stem}.usd"
            filepath = ensure_usd_extension(str(out_dir / filename))
            result.append(
                replace(
                    job,
                    output_basename=stem,
                    filepath=filepath,
                )
            )
            continue
        used.add(Path(job.filepath).stem)
        result.append(job)
    return result


def geo_asset_id_for_job(job) -> str:
    list_id = getattr(job, "list_asset_id", "") or ""
    if list_id:
        return list_id
    return f"geo:{job.asset_id}"


def is_asset_enabled(props, asset_id: str, *, default: bool = True) -> bool:
    item = _find_asset_item(props, asset_id)
    if item is None:
        return default
    return bool(item.enabled)


def filter_enabled_geo_jobs(jobs, props) -> list:
    return [job for job in jobs if is_asset_enabled(props, geo_asset_id_for_job(job))]


def enabled_export_target_count(props) -> int:
    return sum(1 for item in props.anim_usd_export_assets if item.enabled)


def export_target_total_count(props) -> int:
    return len(props.anim_usd_export_assets)


def is_camera_export_enabled(props) -> bool:
    for item in props.anim_usd_export_assets:
        if item.asset_kind == "CAMERA":
            return bool(item.enabled)
    return False


def has_enabled_geo_targets(props) -> bool:
    for item in props.anim_usd_export_assets:
        if item.asset_kind in {"GEO", "CUSTOM"} and item.enabled:
            return True
    return False


def _parse_mesh_names(raw: str) -> tuple[str, ...]:
    return tuple(n.strip() for n in (raw or "").split("\n") if n.strip())


def _encode_mesh_names(names: Sequence[str]) -> str:
    return "\n".join(names)


def custom_asset_id_for_mesh(mesh_name: str) -> str:
    return f"custom:{mesh_name}"


def custom_asset_id_for_meshes(names: Sequence[str]) -> str:
    sorted_names = tuple(sorted({n for n in names if n}, key=str.lower))
    if not sorted_names:
        return "custom:group:empty"
    if len(sorted_names) == 1:
        return custom_asset_id_for_mesh(sorted_names[0])
    joined = "|".join(sorted_names)
    if len(joined) > 180:
        digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]
        return f"custom:group:{digest}"
    return f"custom:group:{joined}"


def _grouped_display_name(context: Context, meshes: Sequence) -> str:
    from .anim_usd_cache_paths_ui import scene_blend_path
    from . import publish_paths

    scene_path = scene_blend_path()
    if scene_path is not None:
        base = publish_paths.default_anim_geo_usd_basename(scene_path)
        if base:
            return base
    if len(meshes) == 1:
        return meshes[0].name
    return "Selection"


def _snapshot_custom_items(props) -> list[dict]:
    rows: list[dict] = []
    for item in props.anim_usd_export_assets:
        if item.asset_kind != "CUSTOM":
            continue
        rows.append(
            {
                "asset_id": item.asset_id,
                "display_name": item.display_name,
                "detail": item.detail,
                "output_file": item.output_file,
                "mesh_names": item.mesh_names,
                "enabled": bool(item.enabled),
            }
        )
    return rows


def _append_custom_item(
    props,
    *,
    asset_id: str,
    display_name: str,
    mesh_names: Sequence[str],
    output_file: str = "—",
    enabled: bool = True,
) -> None:
    names = tuple(sorted({n for n in mesh_names if n}, key=str.lower))
    item = props.anim_usd_export_assets.add()
    item.asset_id = asset_id
    item.display_name = display_name
    item.asset_kind = "CUSTOM"
    item.detail = f"{len(names)} mesh(es)" if names else "custom"
    item.output_file = output_file or "—"
    item.mesh_names = _encode_mesh_names(names)
    item.enabled = enabled
    item.status = "PENDING"
    item.status_detail = ""


def _restore_custom_items(props, rows: Sequence[dict], *, planned_ids: set[str]) -> None:
    for row in rows:
        asset_id = str(row.get("asset_id") or "")
        if not asset_id or asset_id in planned_ids:
            continue
        mesh_names = _parse_mesh_names(str(row.get("mesh_names") or ""))
        if not mesh_names:
            continue
        # Drop meshes that no longer exist in the blend.
        live = tuple(n for n in mesh_names if bpy.data.objects.get(n) is not None)
        if not live:
            continue
        _append_custom_item(
            props,
            asset_id=asset_id,
            display_name=str(row.get("display_name") or live[0]),
            mesh_names=live,
            output_file=str(row.get("output_file") or "—"),
            enabled=bool(row.get("enabled", True)),
        )


def collect_meshes_for_add_selected(context: Context) -> list:
    """Selected mesh objects, plus mesh children of selected non-mesh roots."""
    selected = list(getattr(context, "selected_objects", []) or [])
    meshes: list = []
    seen: set[int] = set()

    def _add_mesh_tree(root) -> None:
        stack = [root]
        while stack:
            current = stack.pop()
            if current.type == "MESH":
                key = id(current)
                if key not in seen:
                    seen.add(key)
                    meshes.append(current)
            stack.extend(list(current.children))

    for obj in selected:
        if obj.type == "MESH":
            key = id(obj)
            if key not in seen:
                seen.add(key)
                meshes.append(obj)
        else:
            _add_mesh_tree(obj)
    return meshes


def add_selected_meshes_to_export_list(context: Context, props) -> tuple[int, str]:
    meshes = collect_meshes_for_add_selected(context)
    if not meshes:
        return 0, "No mesh objects in selection."

    ok_dir, out_dir, _ = resolve_export_output_dir(props)
    used_basenames: set[str] = set()
    for item in props.anim_usd_export_assets:
        name = (item.output_file or "").strip()
        if name.endswith(".usd") or name.endswith(".usda") or name.endswith(".usdc"):
            used_basenames.add(Path(name).stem)

    existing = {item.asset_id for item in props.anim_usd_export_assets if item.asset_id}
    mode = str(getattr(props, "anim_usd_add_selected_mode", "GROUP") or "GROUP").upper()
    added = 0

    if mode != "SEPARATE":
        mesh_names = tuple(sorted({m.name for m in meshes}, key=str.lower))
        asset_id = custom_asset_id_for_meshes(mesh_names)
        if asset_id in existing:
            return 0, "Selected mesh(es) are already in the list."
        display_name = _grouped_display_name(context, meshes)
        output_file = "—"
        if ok_dir:
            job = plan_custom_mesh_geo_job(
                display_name=display_name,
                mesh_names=mesh_names,
                list_asset_id=asset_id,
                out_dir=out_dir,
                used_basenames=used_basenames,
            )
            if job is not None:
                output_file = Path(job.filepath).name
        _append_custom_item(
            props,
            asset_id=asset_id,
            display_name=display_name,
            mesh_names=mesh_names,
            output_file=output_file,
            enabled=True,
        )
        added = 1
    else:
        for mesh in sorted(meshes, key=lambda o: o.name.lower()):
            asset_id = custom_asset_id_for_mesh(mesh.name)
            if asset_id in existing:
                continue
            output_file = "—"
            if ok_dir:
                job = plan_custom_mesh_geo_job(
                    display_name=mesh.name,
                    mesh_names=(mesh.name,),
                    list_asset_id=asset_id,
                    out_dir=out_dir,
                    used_basenames=used_basenames,
                )
                if job is not None:
                    output_file = Path(job.filepath).name
            _append_custom_item(
                props,
                asset_id=asset_id,
                display_name=mesh.name,
                mesh_names=(mesh.name,),
                output_file=output_file,
                enabled=True,
            )
            existing.add(asset_id)
            added += 1

    if added <= 0:
        return 0, "Selected mesh(es) are already in the list."

    # Drop auto Selection fallback — manual list is the source of truth.
    _remove_selection_fallback_items(props)
    props.anim_usd_export_list_locked = True
    if mode != "SEPARATE":
        return added, f"grouped:{len(meshes)}"
    return added, ""


def _remove_selection_fallback_items(props) -> int:
    """Remove auto ``Selection`` GEO rows once CUSTOM targets exist."""
    removed = 0
    for index in range(len(props.anim_usd_export_assets) - 1, -1, -1):
        item = props.anim_usd_export_assets[index]
        if item.asset_kind == "GEO" and item.display_name == "Selection":
            props.anim_usd_export_assets.remove(index)
            removed += 1
    if removed:
        props.anim_usd_export_assets_index = min(
            props.anim_usd_export_assets_index,
            max(0, len(props.anim_usd_export_assets) - 1),
        )
    return removed


def remove_export_list_items(props, indices: Sequence[int]) -> int:
    removed = 0
    for index in sorted({int(i) for i in indices}, reverse=True):
        if index < 0 or index >= len(props.anim_usd_export_assets):
            continue
        props.anim_usd_export_assets.remove(index)
        removed += 1
    props.anim_usd_export_assets_index = min(
        props.anim_usd_export_assets_index,
        max(0, len(props.anim_usd_export_assets) - 1),
    )
    return removed


def clear_export_list_items(props) -> int:
    removed = len(props.anim_usd_export_assets)
    props.anim_usd_export_assets.clear()
    props.anim_usd_export_assets_index = 0
    return removed


def plan_custom_geo_jobs_from_list(
    context: Context,
    props,
    *,
    used_basenames: Optional[set[str]] = None,
) -> list:
    """GEO jobs for enabled CUSTOM list rows (manual Add Selected)."""
    del context
    ok_dir, out_dir, _ = resolve_export_output_dir(props)
    if not ok_dir:
        return []

    used = used_basenames if used_basenames is not None else set()
    jobs: list = []
    for item in props.anim_usd_export_assets:
        if item.asset_kind != "CUSTOM" or not item.enabled:
            continue
        names = _parse_mesh_names(item.mesh_names)
        if not names and item.display_name:
            names = (item.display_name,)
        live = tuple(n for n in names if bpy.data.objects.get(n) is not None)
        if not live:
            continue
        override = normalize_output_usd_filename(item.output_file)
        job = plan_custom_mesh_geo_job(
            display_name=item.display_name or live[0],
            mesh_names=live,
            list_asset_id=item.asset_id or custom_asset_id_for_mesh(live[0]),
            out_dir=out_dir,
            used_basenames=used,
            output_filename=override,
        )
        if job is not None:
            jobs.append(job)
    return jobs


def has_custom_export_targets(props) -> bool:
    return any(item.asset_kind == "CUSTOM" for item in props.anim_usd_export_assets)


def plan_enabled_geo_export_jobs(context: Context, props) -> tuple[list, str]:
    """Auto GEO jobs (filtered by list) plus enabled CUSTOM mesh jobs."""
    allow_selection = not has_custom_export_targets(props)
    jobs, err = plan_geo_export_jobs(
        context,
        props,
        allow_selection_fallback=allow_selection,
    )
    enabled = filter_enabled_geo_jobs(jobs, props)
    used_basenames = {Path(job.filepath).stem for job in enabled}
    enabled.extend(
        plan_custom_geo_jobs_from_list(context, props, used_basenames=used_basenames)
    )
    ok_dir, out_dir, dir_err = resolve_export_output_dir(props)
    if not ok_dir:
        if not enabled and (err or dir_err):
            return [], err or dir_err
        return enabled, err or dir_err
    enabled = apply_list_output_overrides(enabled, props, out_dir)
    if not enabled and err:
        return [], err
    return enabled, err


def resolve_camera_output_filepath(context: Context, props) -> Optional[Path]:
    """Publish-folder camera USD path, honoring editable list filename."""
    from .anim_usd_cache_exporter import (
        collect_camera_collection_objects,
        pick_export_camera,
    )

    if not is_camera_export_enabled(props):
        return None
    ok_dir, out_dir, _ = resolve_export_output_dir(props)
    if not ok_dir:
        return None

    for item in props.anim_usd_export_assets:
        if item.asset_kind != "CAMERA" or not item.enabled:
            continue
        override = normalize_output_usd_filename(item.output_file)
        if override:
            return Path(ensure_usd_extension(str(out_dir / override)))
        break

    cameras = collect_camera_collection_objects(context)
    export_cam = pick_export_camera(cameras, context.scene, context)
    if export_cam is None:
        return None
    return camera_usd_output_path(
        out_dir,
        export_cam.name,
        scene_path=scene_blend_path(),
    )


def _refresh_export_assets_impl(context: Context, props, *, force: bool = False) -> None:
    if props.anim_usd_export_running and not force:
        return

    signature = compute_export_assets_signature(context, props)
    if not force and signature == props.anim_usd_export_assets_signature:
        return

    props.anim_usd_export_assets_signature = signature
    prev_enabled = _snapshot_enabled_flags(props)
    prev_outputs = _snapshot_output_files(props)
    prev_custom = _snapshot_custom_items(props)
    props.anim_usd_export_assets.clear()

    jobs, _ = plan_geo_export_jobs(
        context,
        props,
        allow_selection_fallback=not bool(prev_custom),
    )
    planned_ids: set[str] = set()
    used_basenames: set[str] = set()
    for job in jobs:
        item = props.anim_usd_export_assets.add()
        item.asset_id = geo_asset_id_for_job(job)
        planned_ids.add(item.asset_id)
        if len(job.source_publish_names) > 1:
            stem = Path(job.filepath).stem
            item.display_name = stem if stem else job.source_publish_names[0]
        else:
            item.display_name = job.publish_name
        item.asset_kind = "GEO"
        detail = f"{job.mesh_count} mesh(es)"
        if len(job.source_publish_names) > 1:
            detail += f" · {len(job.source_publish_names)} links"
        item.detail = detail
        auto_name = Path(job.filepath).name
        item.output_file = _resolve_output_file_for_item(
            asset_id=item.asset_id,
            auto_name=auto_name,
            prev_outputs=prev_outputs,
        )
        used_basenames.add(Path(item.output_file).stem if item.output_file not in {"", "—"} else Path(auto_name).stem)
        item.mesh_names = _encode_mesh_names(job.mesh_names)
        item.enabled = prev_enabled.get(item.asset_id, True)
        item.status = "PENDING"
        item.status_detail = ""

    f0, f1 = _frame_range(context, props)
    cam_rows, export_cam = describe_camera_export_rows(
        context,
        frame_start=f0,
        frame_end=f1,
        lightweight=True,
    )
    if export_cam is not None:
        motion_hint = ""
        for row in cam_rows:
            if row.object_name == export_cam.name:
                motion_hint = row.motion_hint
                break
        item = props.anim_usd_export_assets.add()
        item.asset_id = f"cam:{export_cam.name}"
        planned_ids.add(item.asset_id)
        item.display_name = export_cam.name
        item.asset_kind = "CAMERA"
        item.detail = motion_hint or "camera"
        auto_name = _camera_output_basename(context, props, export_cam)
        item.output_file = _resolve_output_file_for_item(
            asset_id=item.asset_id,
            auto_name=auto_name,
            prev_outputs=prev_outputs,
        )
        item.mesh_names = ""
        item.enabled = prev_enabled.get(item.asset_id, True)
        item.status = "PENDING"
        item.status_detail = ""

    # Rebuild CUSTOM outputs — keep edited filenames when present.
    ok_dir, out_dir, _ = resolve_export_output_dir(props)
    restored: list[dict] = []
    for row in prev_custom:
        asset_id = str(row.get("asset_id") or "")
        if not asset_id or asset_id in planned_ids:
            continue
        mesh_names = _parse_mesh_names(str(row.get("mesh_names") or ""))
        live = tuple(n for n in mesh_names if bpy.data.objects.get(n) is not None)
        if not live:
            continue
        output_file = _resolve_output_file_for_item(
            asset_id=asset_id,
            auto_name=str(row.get("output_file") or "—"),
            prev_outputs=prev_outputs,
        )
        if ok_dir and (not output_file or output_file == "—"):
            job = plan_custom_mesh_geo_job(
                display_name=str(row.get("display_name") or live[0]),
                mesh_names=live,
                list_asset_id=asset_id,
                out_dir=out_dir,
                used_basenames=used_basenames,
            )
            if job is not None:
                output_file = Path(job.filepath).name
        elif ok_dir and output_file and output_file != "—":
            stem = alloc_unique_basename(Path(output_file).stem, used_basenames)
            output_file = f"{stem}.usd"
        restored.append(
            {
                **row,
                "mesh_names": _encode_mesh_names(live),
                "output_file": output_file,
            }
        )
    _restore_custom_items(props, restored, planned_ids=planned_ids)

    props.anim_usd_export_assets_index = min(
        props.anim_usd_export_assets_index,
        max(0, len(props.anim_usd_export_assets) - 1),
    )


def schedule_export_assets_refresh(context: Context) -> None:
    """Defer RNA writes — safe to call from panel draw()."""
    global _anim_usd_refresh_timer, _anim_usd_refresh_scene_name, _anim_usd_refresh_pending

    if _anim_usd_refresh_pending:
        return

    _anim_usd_refresh_scene_name = context.scene.name
    _anim_usd_refresh_pending = True

    def _run() -> None:
        global _anim_usd_refresh_timer, _anim_usd_refresh_pending
        _anim_usd_refresh_timer = None
        _anim_usd_refresh_pending = False
        scene = bpy.data.scenes.get(_anim_usd_refresh_scene_name or "")
        if scene is None:
            return None
        props = getattr(scene, "monofx_pipeline_blender_props", None)
        if props is None:
            return None
        if props.anim_usd_export_list_locked:
            return None
        try:
            _refresh_export_assets_impl(bpy.context, props)
        except Exception as exc:
            logger = __import__("logging").getLogger("monofx.anim_usd_cache")
            logger.exception("export assets refresh failed: %s", exc)
        if bpy.context.scene.name == (_anim_usd_refresh_scene_name or ""):
            _tag_anim_usd_panel_redraw(bpy.context)
        return None

    if _anim_usd_refresh_timer is not None:
        return
    _anim_usd_refresh_timer = bpy.app.timers.register(
        _run,
        first_interval=_ANIM_USD_REFRESH_INTERVAL_S,
    )


def ensure_export_assets_refresh(context: Context, props) -> None:
    """Read-only in draw: schedule refresh when scene export targets changed."""
    if props.anim_usd_export_running:
        return
    if props.anim_usd_export_list_locked:
        return
    signature = compute_export_assets_signature(context, props)
    if signature == props.anim_usd_export_assets_signature:
        return
    schedule_export_assets_refresh(context)


def refresh_export_assets(context: Context, props, *, force: bool = False) -> None:
    """Immediate refresh — use from operators, not panel draw()."""
    _refresh_export_assets_impl(context, props, force=force)


def reset_export_statuses(props) -> None:
    for item in props.anim_usd_export_assets:
        if not item.enabled:
            item.status = "SKIPPED"
        else:
            item.status = "PENDING"
        item.status_detail = ""


def mark_export_complete(props) -> None:
    for item in props.anim_usd_export_assets:
        if not item.enabled:
            continue
        item.status = "DONE"
        item.status_detail = ""


def mark_export_error(props, asset_id: Optional[str] = None) -> None:
    for item in props.anim_usd_export_assets:
        if not item.enabled:
            continue
        if asset_id is None or item.asset_id == asset_id:
            item.status = "ERROR"
            item.status_detail = ""


def mark_export_cancelled(props) -> None:
    for item in props.anim_usd_export_assets:
        if item.status == "DONE":
            continue
        if not item.enabled:
            item.status = "SKIPPED"
            continue
        item.status = "CANCELLED"
        item.status_detail = ""


def _status_slot_display(item: AnimUsdExportAssetItem) -> str:
    """Compact label for the right-hand meshes slot."""
    if item.status == "EXPORTING":
        return (item.status_detail or "…").strip() or "…"
    if item.status == "DONE":
        return "Done"
    if item.status == "ERROR":
        return "Err"
    if item.status == "CANCELLED":
        return "Canc"
    return ""


def update_export_statuses(props, session) -> None:
    if session is None:
        return

    from .anim_usd_cache_exporter import (
        UsdAnimCacheExportSession,
        UsdAnimCacheMultiExportSession,
    )

    def _apply_geo_item(item, sub: UsdAnimCacheExportSession) -> None:
        if sub._step >= sub.geo_steps_total and sub.geo_steps_total > 0:
            item.status = "DONE"
            item.status_detail = ""
        else:
            item.status = "EXPORTING"
            item.status_detail = sub.elapsed_label

    def _apply_camera_item(item, sub: UsdAnimCacheExportSession) -> None:
        if sub.is_camera_phase:
            item.status = "EXPORTING"
            item.status_detail = sub.elapsed_label
        else:
            item.status = "PENDING"
            item.status_detail = ""

    if isinstance(session, UsdAnimCacheMultiExportSession):
        sub = session._session
        for index, job in enumerate(session.jobs):
            item = _find_asset_item(props, geo_asset_id_for_job(job))
            if item is None or not item.enabled:
                continue
            if index < session._job_index:
                item.status = "DONE"
                item.status_detail = ""
            elif index == session._job_index and not session._finished and sub is not None:
                _apply_geo_item(item, sub)
            elif session._finished and not session._cancelled:
                item.status = "DONE"
                item.status_detail = ""

        cam_item = None
        for item in props.anim_usd_export_assets:
            if item.asset_kind == "CAMERA":
                cam_item = item
                break
        if cam_item is not None and cam_item.enabled:
            if session._finished and not session._cancelled:
                cam_item.status = "DONE"
                cam_item.status_detail = ""
            elif (
                session._job_index == len(session.jobs) - 1
                and not session._finished
                and sub is not None
            ):
                _apply_camera_item(cam_item, sub)
        return

    if isinstance(session, UsdAnimCacheExportSession):
        for item in props.anim_usd_export_assets:
            if not item.enabled:
                continue
            if session._cancelled:
                if item.status != "DONE":
                    item.status = "CANCELLED"
                    item.status_detail = ""
                continue
            if session.done:
                item.status = "DONE" if session.result.ok else "ERROR"
                item.status_detail = ""
            elif item.asset_kind == "CAMERA":
                _apply_camera_item(item, session)
            else:
                _apply_geo_item(item, session)


class MONOFX_UL_anim_usd_export_assets(UIList):
    bl_idname = "MONOFX_UL_anim_usd_export_assets"

    def draw_item(
        self,
        context: Context,
        layout: UILayout,
        data,
        item: AnimUsdExportAssetItem,
        icon,
        active_data,
        active_propname,
        index: int,
    ) -> None:
        del context, data, icon, active_data, active_propname
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            remove_op = row.operator(
                "wm.mono_fx_anim_usd_export_list_remove_row",
                text="",
                icon="X",
                emboss=False,
            )
            remove_op.index = index
            row.prop(item, "enabled", text="")

            kind_icon = _KIND_ICONS.get(item.asset_kind, "FILE")
            mesh_count = len(_parse_mesh_names(item.mesh_names))
            show_mesh_btn = item.asset_kind != "CAMERA" and mesh_count > 0
            show_status = item.status not in {"PENDING", "SKIPPED"}
            # Always reserve the right slot for meshes button or live status.
            split = row.split(factor=0.88, align=True)

            body = split.row(align=True)
            body.enabled = item.enabled
            body.prop(item, "output_file", text="", icon=kind_icon, emboss=True)

            right = split.row(align=True)
            right.alignment = "RIGHT"
            if show_status:
                status_icon = _STATUS_ICONS.get(item.status, "DOT")
                right.label(text=_status_slot_display(item), icon=status_icon)
            elif item.asset_kind == "CAMERA":
                right.label(text="", icon="OUTLINER_OB_CAMERA")
            elif show_mesh_btn:
                op = right.operator(
                    "wm.mono_fx_anim_usd_export_list_show_meshes",
                    text=str(mesh_count),
                    icon="MESH_DATA",
                    emboss=True,
                )
                op.index = index
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(
                text=item.output_file or item.display_name,
                icon=_KIND_ICONS.get(item.asset_kind, "FILE"),
            )


class MONOFX_OT_anim_usd_export_list_show_meshes(bpy.types.Operator):
    """Show the mesh object names included in this export target."""

    bl_idname = "wm.mono_fx_anim_usd_export_list_show_meshes"
    bl_label = "Meshes"
    bl_options = {"REGISTER", "INTERNAL"}

    index: IntProperty(name="Index", default=0, min=0)

    @classmethod
    def description(cls, context, properties) -> str:
        return "Show mesh objects in this export target"

    def invoke(self, context: Context, _event) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        if self.index < 0 or self.index >= len(props.anim_usd_export_assets):
            self.report({"WARNING"}, "Invalid export target.")
            return {"CANCELLED"}
        item = props.anim_usd_export_assets[self.index]
        names = _parse_mesh_names(item.mesh_names)
        if not names:
            self.report({"INFO"}, "No meshes on this target.")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context: Context) -> None:
        props = context.scene.monofx_pipeline_blender_props
        layout = self.layout
        if self.index < 0 or self.index >= len(props.anim_usd_export_assets):
            layout.label(text="Invalid target.", icon="ERROR")
            return
        item = props.anim_usd_export_assets[self.index]
        names = _parse_mesh_names(item.mesh_names)
        header = layout.row()
        header.label(
            text=item.output_file or item.display_name or "Meshes",
            icon="EXPORT",
        )
        layout.separator()
        col = layout.column(align=True)
        for name in names:
            exists = bpy.data.objects.get(name) is not None
            row = col.row(align=True)
            row.label(text=name, icon="MESH_DATA" if exists else "ERROR")
            if not exists:
                row.alert = True
                row.label(text="missing")

    def execute(self, context: Context) -> set[str]:
        del context
        return {"FINISHED"}


class MONOFX_OT_refresh_anim_usd_export_list(bpy.types.Operator):
    """Refresh the Anim USD export target list from the current scene and options."""

    bl_idname = "wm.mono_fx_refresh_anim_usd_export_list"
    bl_label = "Refresh Export List"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        refresh_export_assets(context, props, force=True)
        enabled = enabled_export_target_count(props)
        total = export_target_total_count(props)
        self.report({"INFO"}, f"Export list: {enabled}/{total} target(s) enabled.")
        return {"FINISHED"}


class MONOFX_OT_anim_usd_export_list_add_selected(bpy.types.Operator):
    """Add selected mesh object(s) to the Anim USD export list."""

    bl_idname = "wm.mono_fx_anim_usd_export_list_add_selected"
    bl_label = "Add Selected"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        added, err = add_selected_meshes_to_export_list(context, props)
        if added <= 0:
            self.report({"WARNING"}, err or "Nothing added.")
            return {"CANCELLED"}
        if err.startswith("grouped:"):
            mesh_count = err.split(":", 1)[1]
            self.report(
                {"INFO"},
                f"Added 1 grouped target ({mesh_count} mesh(es)).",
            )
        else:
            self.report({"INFO"}, f"Added {added} mesh target(s).")
        return {"FINISHED"}


class MONOFX_OT_anim_usd_export_list_remove_row(bpy.types.Operator):
    """Remove this export target row."""

    bl_idname = "wm.mono_fx_anim_usd_export_list_remove_row"
    bl_label = "Remove Row"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    index: IntProperty(name="Index", default=0, min=0)

    @classmethod
    def description(cls, context, properties) -> str:
        return "Remove this export target"

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        removed = remove_export_list_items(props, [self.index])
        if removed <= 0:
            self.report({"WARNING"}, "No row to remove.")
            return {"CANCELLED"}
        props.anim_usd_export_list_locked = True
        return {"FINISHED"}


class MONOFX_OT_anim_usd_export_list_remove(bpy.types.Operator):
    """Remove all rows from the Anim USD export list."""

    bl_idname = "wm.mono_fx_anim_usd_export_list_remove"
    bl_label = "Remove All"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return len(props.anim_usd_export_assets) > 0

    @classmethod
    def description(cls, context, properties) -> str:
        return "Remove all export targets from the list"

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        removed = clear_export_list_items(props)
        if removed <= 0:
            self.report({"WARNING"}, "List is already empty.")
            return {"CANCELLED"}
        props.anim_usd_export_list_locked = True
        self.report({"INFO"}, f"Removed all ({removed}) target(s).")
        return {"FINISHED"}


ANIM_USD_ASSET_PROPERTY_GROUP_CLASSES = (AnimUsdExportAssetItem,)

ANIM_USD_ASSET_UI_LIST_CLASSES = (MONOFX_UL_anim_usd_export_assets,)

ANIM_USD_ASSET_OPERATOR_CLASSES = (
    MONOFX_OT_refresh_anim_usd_export_list,
    MONOFX_OT_anim_usd_export_list_add_selected,
    MONOFX_OT_anim_usd_export_list_remove_row,
    MONOFX_OT_anim_usd_export_list_remove,
    MONOFX_OT_anim_usd_export_list_show_meshes,
)
