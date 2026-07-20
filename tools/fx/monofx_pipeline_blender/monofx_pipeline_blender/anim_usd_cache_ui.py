"""
Anim → USD tab UI for animation cache export.
"""

from __future__ import annotations

import bpy
from bpy.types import Context, UILayout

from . import anim_usd_cache_paths_ui as path_ui
from . import anim_usd_cache_scene
from . import anim_usd_cache_asset_list as asset_list
from . import ui_style
from .anim_usd_cache_exporter import check_pxr_available


_SYNCING_ANIM_USD_FILEPATH: bool = False
_SYNCING_ANIM_USD_VERSION: bool = False


def _on_anim_usd_version_mode(props, context: Context) -> None:
    path_ui.sync_anim_publish_output(props)
    _on_anim_usd_export_options_changed(props, context)


def _on_anim_usd_publish_version(props, _context: Context) -> None:
    del props, _context


def _on_anim_usd_merge_by_link(props, context: Context) -> None:
    _on_anim_usd_export_options_changed(props, context)


def _on_anim_usd_export_options_changed(props, context: Context) -> None:
    if context is None or getattr(context, "scene", None) is None:
        return
    props.anim_usd_export_assets_signature = ""
    asset_list.refresh_export_assets(context, props, force=True)


def draw_anim_usd_version_toggles(layout: UILayout, props) -> None:
    manual_v = max(1, min(999, int(getattr(props, "anim_usd_manual_version", 1) or 1)))
    current_v, next_v = path_ui.cached_version_toggle_numbers()
    mode = str(getattr(props, "anim_usd_version_mode", "NEXT") or "NEXT")

    row = layout.row(align=True)
    ui_style.operator_row(
        row,
        "wm.mono_fx_pick_anim_publish_version",
        text=f"Manual (v{manual_v:03d})",
        depress=mode == "MANUAL",
    )
    op = ui_style.operator_row(
        row,
        "wm.mono_fx_set_anim_version_mode",
        text=f"Current (v{current_v:03d})",
        depress=mode == "CURRENT",
    )
    op.mode = "CURRENT"
    op = ui_style.operator_row(
        row,
        "wm.mono_fx_set_anim_version_mode",
        text=f"Next (v{next_v:03d})",
        depress=mode == "NEXT",
    )
    op.mode = "NEXT"


def draw_anim_usd_publish_settings(layout: UILayout, props) -> None:
    layout.label(text="Export Options", icon="PREFERENCES")
    layout.prop(props, "anim_usd_root_prim", text="Root Prim")
    layout.prop(props, "anim_usd_merge_by_link", text="Merge Same Link")
    layout.prop(props, "anim_usd_add_selected_mode", text="Add Selected")
    layout.prop(props, "anim_usd_skip_view_hidden", text="Skip Hidden / Excluded")


def draw_anim_usd_cache_tab(layout: UILayout, context: Context) -> None:
    props = context.scene.monofx_pipeline_blender_props

    pxr_ok, pxr_err = check_pxr_available()
    asset_list.ensure_export_assets_refresh(context, props)
    geo_needs_pxr = asset_list.has_enabled_geo_targets(props)
    if not pxr_ok:
        row = layout.row()
        row.alert = True
        row.label(text=pxr_err, icon="ERROR")
        if geo_needs_pxr:
            return

    box = layout.box()
    body = box.column(align=True)

    draw_anim_usd_version_toggles(body, props)
    ok_path, filepath, path_err = path_ui.resolve_output_path(props)
    if ok_path:
        body.label(text=filepath, icon="FILE")
    elif path_err:
        body.label(text=path_err, icon="ERROR")

    body.separator()

    ui_style.prop_checkbox(body, props, "anim_usd_use_scene_range", text="Use Scene Range")
    range_row = body.row()
    range_row.enabled = not props.anim_usd_use_scene_range
    range_row.prop(props, "anim_usd_frame_start", text="Start")
    range_row.prop(props, "anim_usd_frame_end", text="End")
    fps = context.scene.render.fps / (context.scene.render.fps_base or 1.0)
    body.label(text=f"FPS: {fps:g}", icon="RENDER_ANIMATION")

    body.separator()
    enabled_count = anim_usd_cache_scene.draw_scene_assets_list(body, context, props)

    if props.anim_usd_status_report:
        ui_style.status_label(
            layout,
            props.anim_usd_status_report,
            ok=True,
            icon="SORTTIME" if props.anim_usd_export_running else "INFO",
        )
    ok_plan, summary, _rel, err_plan = path_ui.describe_anim_publish_target(props)
    if ok_plan:
        layout.label(text=summary, icon="FILE_TICK")
    else:
        ui_style.status_label(layout, err_plan or "Path unavailable", ok=False)

    layout.separator()
    pub_row = layout.row(align=True)
    pub_row.scale_y = 1.55
    if props.anim_usd_export_running:
        pub_row.operator(
            "wm.mono_fx_cancel_anim_usd_export",
            text="CANCEL EXPORT",
            icon="PANEL_CLOSE",
        )
    else:
        pub_main = pub_row.row(align=True)
        pub_main.enabled = enabled_count > 0
        pub_main.operator(
            "wm.mono_fx_export_anim_usd_cache",
            text="PUBLISH ANIM",
            icon=ui_style.ICON_PUBLISH,
        )
        pub_row.operator(
            "wm.mono_fx_anim_usd_open_publish_folder",
            text="",
            icon=ui_style.ICON_FOLDER,
        )
        pub_settings = pub_row.row(align=True)
        pub_settings.scale_x = 1.15
        pub_settings.operator(
            "wm.mono_fx_anim_usd_publish_settings",
            text="",
            icon="PREFERENCES",
        )


def register_anim_usd_property_callbacks() -> None:
    """Called from addon register — RNA update fns attached via Property definitions."""
    pass
