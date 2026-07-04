"""
Anim → USD tab UI for animation cache export.
"""

from __future__ import annotations

import bpy
from bpy.types import Context, UILayout

from . import anim_usd_cache_paths_ui as path_ui
from . import anim_usd_cache_scene
from . import anim_usd_cache_asset_list as asset_list
from . import preferences
from . import ui_style
from .anim_usd_cache_exporter import (
    check_pxr_available,
)


_SYNCING_ANIM_USD_FILEPATH: bool = False
_SYNCING_ANIM_USD_VERSION: bool = False


def _on_anim_usd_publish_version(props, _context: Context) -> None:
    global _SYNCING_ANIM_USD_VERSION, _SYNCING_ANIM_USD_FILEPATH
    if _SYNCING_ANIM_USD_VERSION:
        return
    scene_path = path_ui.scene_blend_path()
    publish_root = (
        path_ui.anim_publish_root_for_scene(scene_path) if scene_path else None
    )
    if scene_path is None or publish_root is None:
        return
    if props.anim_usd_output_preset == "auto":
        props.anim_usd_output_preset = "custom"
    ok, filepath, _ = path_ui.compute_auto_anim_usd_path(props.anim_usd_publish_version)
    if not ok:
        return
    _SYNCING_ANIM_USD_FILEPATH = True
    try:
        props.anim_usd_output_filepath = filepath
    finally:
        _SYNCING_ANIM_USD_FILEPATH = False


def _on_anim_usd_output_filepath(props, _context: Context) -> None:
    global _SYNCING_ANIM_USD_FILEPATH
    if _SYNCING_ANIM_USD_FILEPATH:
        return
    if props.anim_usd_output_preset != "auto":
        return
    ok, auto_path, _ = path_ui.compute_auto_anim_usd_path(props.anim_usd_publish_version)
    if not ok:
        return
    if not path_ui.paths_equal(props.anim_usd_output_filepath, auto_path):
        props.anim_usd_output_preset = "custom"


def _on_anim_usd_output_preset(props, _context: Context) -> None:
    if props.anim_usd_output_preset == "auto":
        path_ui.sync_auto_anim_output(props)


def _on_anim_usd_merge_by_link(props, context: Context) -> None:
    _on_anim_usd_export_options_changed(props, context)


def _on_anim_usd_export_options_changed(props, context: Context) -> None:
    if context is None or getattr(context, "scene", None) is None:
        return
    props.anim_usd_export_assets_signature = ""
    from . import anim_usd_cache_asset_list as asset_list

    asset_list.refresh_export_assets(context, props, force=True)


def draw_anim_usd_cache_tab(layout: UILayout, context: Context) -> None:
    prefs = preferences.get_addon_prefs(context)
    if prefs is None:
        return
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
    _tabs, body = ui_style.draw_vertical_tabs(box, prefs, "ui_anim_usd_section")
    section = prefs.ui_anim_usd_section

    if section == "OUTPUT":
        ok, summary, rel, err = path_ui.describe_anim_publish_target(props)
        if ok:
            ui_style.status_label(body, summary, ok=True, icon="CHECKMARK")
            body.label(text=rel, icon="FILE_FOLDER")
        else:
            ui_style.status_label(body, err, ok=False, icon="ERROR")

        body.prop(props, "anim_usd_output_preset", text="Preset")
        if props.anim_usd_output_preset == "auto":
            row = body.row(align=True)
            row.prop(props, "anim_usd_publish_version", text="Version")
        body.prop(props, "anim_usd_output_filepath", text="File")
        ui_style.operator_row(
            body,
            "wm.mono_fx_anim_usd_open_publish_folder",
            text="Open Publish Folder",
            icon=ui_style.ICON_FOLDER,
        )
    elif section == "RANGE":
        body.prop(props, "anim_usd_use_scene_range", text="Use Scene Range")
        row = body.row()
        row.enabled = not props.anim_usd_use_scene_range
        row.prop(props, "anim_usd_frame_start", text="Start")
        row.prop(props, "anim_usd_frame_end", text="End")
        fps = context.scene.render.fps / (context.scene.render.fps_base or 1.0)
        body.label(text=f"FPS: {fps:g}", icon="RENDER_ANIMATION")
    elif section == "ADVANCED":
        body.prop(props, "anim_usd_root_prim", text="Root Prim")
        body.prop(props, "anim_usd_merge_by_link", text="Merge Same Link")
        body.prop(props, "anim_usd_skip_view_hidden", text="Skip Hidden / Excluded")
    elif section == "ASSETS":
        asset_list.ensure_export_assets_refresh(context, props)
        anim_usd_cache_scene.draw_scene_assets_list(body, context, props)

    asset_list.ensure_export_assets_refresh(context, props)
    enabled_count = asset_list.enabled_export_target_count(props)

    if props.anim_usd_status_report:
        ui_style.status_label(
            layout,
            props.anim_usd_status_report,
            ok=True,
            icon="SORTTIME" if props.anim_usd_export_running else "INFO",
        )

    layout.separator()
    row = layout.row()
    if props.anim_usd_export_running:
        ui_style.operator_row(
            row,
            "wm.mono_fx_cancel_anim_usd_export",
            text="Cancel Export",
            icon="PANEL_CLOSE",
            scale_y=1.25,
        )
    else:
        row.enabled = enabled_count > 0
        ui_style.operator_row(
            row,
            "wm.mono_fx_export_anim_usd_cache",
            text="Export Anim Cache",
            icon=ui_style.ICON_EXPORT,
            scale_y=1.25,
        )


def register_anim_usd_property_callbacks() -> None:
    """Called from addon register — RNA update fns attached via Property definitions."""
    pass
