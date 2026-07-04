"""
Export target list for Anim USD cache (geo, camera, future custom assets).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Context, PropertyGroup, UIList, UILayout

from .anim_usd_cache_camera_writer import camera_usd_output_path
from .anim_usd_cache_exporter import describe_camera_export_rows
from .anim_usd_cache_paths_ui import scene_blend_path
from .anim_usd_export_planner import plan_geo_export_jobs, resolve_export_output_dir

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
    "CUSTOM": "FILE",
}

_anim_usd_refresh_timer = None
_anim_usd_refresh_scene_name: Optional[str] = None
_anim_usd_refresh_pending = False


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


class AnimUsdExportAssetItem(PropertyGroup):
    asset_id: StringProperty(name="Asset ID", default="")
    display_name: StringProperty(name="Name", default="")
    asset_kind: EnumProperty(
        name="Kind",
        items=_ASSET_KIND_ITEMS,
        default="GEO",
    )
    detail: StringProperty(name="Detail", default="")
    output_file: StringProperty(name="Output File", default="")
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
    from .anim_usd_cache_exporter import (
        collect_camera_collection_objects,
        collect_publish_geo_groups,
        pick_export_camera,
    )

    groups = collect_publish_geo_groups(context)
    job_part = "|".join(
        f"{g.publish_name}:{len(g.mesh_names)}" for g in groups
    )
    cameras = collect_camera_collection_objects(context)
    export_cam = pick_export_camera(cameras, context.scene, context)
    cam_name = export_cam.name if export_cam is not None else ""
    f0, f1 = _frame_range(context, props)
    merge = bool(getattr(props, "anim_usd_merge_by_link", False))
    skip_hidden = bool(getattr(props, "anim_usd_skip_view_hidden", False))
    preset = str(getattr(props, "anim_usd_output_preset", "") or "")
    version = int(getattr(props, "anim_usd_publish_version", 0) or 0)
    filepath = str(getattr(props, "anim_usd_output_filepath", "") or "")
    return (
        f"{job_part}#{cam_name}#{filepath}#v{version}#{preset}#"
        f"{f0}-{f1}#merge={int(merge)}#skiphidden={int(skip_hidden)}"
    )


def _find_asset_item(props, asset_id: str) -> Optional[AnimUsdExportAssetItem]:
    for item in props.anim_usd_export_assets:
        if item.asset_id == asset_id:
            return item
    return None


def _snapshot_enabled_flags(props) -> dict[str, bool]:
    return {item.asset_id: bool(item.enabled) for item in props.anim_usd_export_assets}


def geo_asset_id_for_job(job) -> str:
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


def is_camera_export_enabled(props) -> bool:
    for item in props.anim_usd_export_assets:
        if item.asset_kind == "CAMERA":
            return bool(item.enabled)
    return False


def has_enabled_geo_targets(props) -> bool:
    for item in props.anim_usd_export_assets:
        if item.asset_kind == "GEO" and item.enabled:
            return True
    return False


def _refresh_export_assets_impl(context: Context, props, *, force: bool = False) -> None:
    if props.anim_usd_export_running and not force:
        return

    signature = compute_export_assets_signature(context, props)
    if not force and signature == props.anim_usd_export_assets_signature:
        return

    props.anim_usd_export_assets_signature = signature
    prev_enabled = _snapshot_enabled_flags(props)
    props.anim_usd_export_assets.clear()

    jobs, _ = plan_geo_export_jobs(context, props)
    for job in jobs:
        item = props.anim_usd_export_assets.add()
        item.asset_id = geo_asset_id_for_job(job)
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
        item.output_file = Path(job.filepath).name
        item.enabled = prev_enabled.get(item.asset_id, True)
        item.status = "PENDING"
        item.status_detail = ""

    f0, f1 = _frame_range(context, props)
    cam_rows, export_cam = describe_camera_export_rows(
        context, frame_start=f0, frame_end=f1
    )
    if export_cam is not None:
        motion_hint = ""
        for row in cam_rows:
            if row.object_name == export_cam.name:
                motion_hint = row.motion_hint
                break
        item = props.anim_usd_export_assets.add()
        item.asset_id = f"cam:{export_cam.name}"
        item.display_name = export_cam.name
        item.asset_kind = "CAMERA"
        item.detail = motion_hint or "camera"
        item.output_file = _camera_output_basename(context, props, export_cam)
        item.enabled = prev_enabled.get(item.asset_id, True)
        item.status = "PENDING"
        item.status_detail = ""


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
        try:
            _refresh_export_assets_impl(bpy.context, props)
        except Exception as exc:
            logger = __import__("logging").getLogger("monofx.anim_usd_cache")
            logger.exception("export assets refresh failed: %s", exc)
        _tag_anim_usd_panel_redraw(bpy.context)
        return None

    if _anim_usd_refresh_timer is not None:
        try:
            bpy.app.timers.unregister(_anim_usd_refresh_timer)
        except Exception:
            pass
    _anim_usd_refresh_timer = bpy.app.timers.register(_run, first_interval=0.15)


def ensure_export_assets_refresh(context: Context, props) -> None:
    """Read-only in draw: schedule refresh when scene export targets changed."""
    if props.anim_usd_export_running:
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


def _status_display(item: AnimUsdExportAssetItem) -> str:
    if item.status == "PENDING":
        return item.output_file or "—"
    if item.status == "EXPORTING":
        return item.status_detail or "Exporting…"
    if item.status == "DONE":
        return "Done"
    if item.status == "ERROR":
        return "Error"
    if item.status == "SKIPPED":
        return "Skipped"
    if item.status == "CANCELLED":
        return "Cancelled"
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
            item.status_detail = sub.geo_progress_time_label

    def _apply_camera_item(item, sub: UsdAnimCacheExportSession) -> None:
        if sub.is_camera_phase:
            item.status = "EXPORTING"
            item.status_detail = sub.camera_progress_time_label
        else:
            item.status = "PENDING"
            item.status_detail = ""

    if isinstance(session, UsdAnimCacheMultiExportSession):
        sub = session._session
        for index, job in enumerate(session.jobs):
            item = _find_asset_item(props, f"geo:{job.asset_id}")
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
        del context, data, icon, active_data, active_propname, index
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.prop(item, "enabled", text="")
            body = row.row(align=True)
            body.enabled = item.enabled
            left = body.split(factor=0.58, align=True)
            left_col = left.column(align=True)
            kind_icon = _KIND_ICONS.get(item.asset_kind, "FILE")
            left_col.label(text=item.display_name, icon=kind_icon)
            if item.detail:
                detail_row = left_col.row()
                detail_row.scale_y = 0.9
                detail_row.label(text=item.detail)

            right = body.row(align=True)
            right.alignment = "RIGHT"
            status_icon = _STATUS_ICONS.get(item.status, "DOT")
            right.label(text=_status_display(item), icon=status_icon)
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.display_name, icon=_KIND_ICONS.get(item.asset_kind, "FILE"))


ANIM_USD_ASSET_PROPERTY_GROUP_CLASSES = (AnimUsdExportAssetItem,)

ANIM_USD_ASSET_UI_LIST_CLASSES = (MONOFX_UL_anim_usd_export_assets,)
