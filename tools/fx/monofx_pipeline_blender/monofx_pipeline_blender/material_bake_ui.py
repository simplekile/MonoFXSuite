"""
Materials → USD bake list UI (Geo USD publish workflow).
"""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.types import Context, UILayout

from . import ui_style
from .material_bake import describe_bake_output_target
from .material_bake_targets import (
    compute_material_bake_signature,
    enabled_bake_target_count,
    ensure_material_bake_targets_refresh,
    material_bake_action_label,
    restorable_bake_target_count,
)
from .publish_paths import resolve_publish_root_from_scene


def draw_material_bake_tab(layout: UILayout, context: Context) -> None:
    props = context.scene.monofx_pipeline_blender_props
    box = layout.box()
    enabled_count = draw_material_bake_targets_list(box, context, props)
    layout.separator()
    output_ok = draw_material_bake_output(box, props)
    draw_material_bake_actions(
        box, props, enabled_count=enabled_count, output_ok=output_ok
    )


def draw_material_bake_scope_options(layout: UILayout, props) -> None:
    mesh_filter = (
        props.material_bake_selected_only or props.material_bake_keyword_filter
    )
    tree_row = layout.row()
    tree_row.enabled = not mesh_filter
    ui_style.prop_checkbox(tree_row, props, "material_bake_use_geo_tree", text="Geo Asset Tree")
    ui_style.prop_checkbox(layout, props, "material_bake_selected_only", text="Selected Meshes")
    ui_style.prop_checkbox(layout, props, "material_bake_keyword_filter", text="Keyword Filter")
    kw_row = layout.row()
    kw_row.enabled = props.material_bake_keyword_filter
    kw_row.prop(props, "material_bake_mesh_keyword", text="Keyword")
    layout.separator()
    layout.label(text="Bake Grouping")
    grouping_row = layout.row(align=True)
    grouping_row.prop(props, "material_bake_scope", expand=True)
    grouping_hint = layout.row()
    grouping_hint.scale_y = 0.85
    if (props.material_bake_scope or "").upper() == "PER_MESH":
        grouping_hint.label(text="One texture set per mesh", icon="INFO")
    else:
        grouping_hint.label(text="One texture set per material", icon="INFO")


def draw_material_bake_targets_list(layout: UILayout, context: Context, props) -> int:
    """Draw bake target list; returns enabled target count."""
    draw_material_bake_scope_options(layout, props)
    layout.separator()

    ensure_material_bake_targets_refresh(context, props)

    items = props.material_bake_targets
    if not items:
        pending_sig = (
            compute_material_bake_signature(context, props)
            != props.material_bake_targets_signature
        )
        if pending_sig and not props.material_bake_list_locked:
            layout.label(text="Updating bake targets…", icon="FILE_REFRESH")
            return 0
        if props.material_bake_list_error:
            alert = layout.row()
            alert.alert = True
            alert.label(text=props.material_bake_list_error, icon="ERROR")
        else:
            alert = layout.row()
            alert.alert = True
            alert.label(
                text="No bake targets — create Geo tree and assign materials",
                icon="ERROR",
            )
        return 0

    enabled_count = enabled_bake_target_count(props)
    total_count = len(items)
    list_header = layout.row(align=True)
    list_header.label(
        text=f"Bake Targets ({enabled_count}/{total_count})",
        icon="OUTLINER_OB_MESH",
    )
    lock_row = list_header.row(align=True)
    lock_row.prop(
        props,
        "material_bake_list_locked",
        text="",
        icon="LOCKED" if props.material_bake_list_locked else "UNLOCKED",
        toggle=True,
        emboss=True,
    )
    list_header.operator(
        "wm.mono_fx_refresh_material_bake_list",
        text="",
        icon="FILE_REFRESH",
    )

    layout.template_list(
        "MONOFX_UL_material_bake_targets",
        "material_bake_targets",
        props,
        "material_bake_targets",
        props,
        "material_bake_target_index",
        rows=6,
    )

    list_ops = layout.row(align=True)
    list_ops.operator(
        "wm.mono_fx_material_bake_add_selected",
        text="Add Selected",
        icon="ADD",
    )
    list_ops.operator(
        "wm.mono_fx_material_bake_remove",
        text="Remove",
        icon="REMOVE",
    )

    if props.material_bake_list_error:
        err_row = layout.row()
        err_row.alert = True
        err_row.label(text=props.material_bake_list_error, icon="ERROR")
    elif enabled_count == 0:
        hint = layout.row()
        hint.alert = True
        hint.label(text="Enable at least one target to bake.", icon="ERROR")

    return enabled_count


def draw_material_bake_output(layout: UILayout, props) -> bool:
    """Output folder mode and resolved path; returns True when bake path is valid."""
    layout.label(text="Output", icon="FILE_FOLDER")
    layout.prop(props, "material_bake_output_mode", text="")
    if (props.material_bake_output_mode or "").upper() == "CUSTOM":
        layout.prop(props, "material_bake_output_dir", text="Folder")
    blend_path = Path(bpy.data.filepath) if bpy.data.filepath else None
    publish_root = (
        resolve_publish_root_from_scene(blend_path) if blend_path is not None else None
    )
    ok, summary, err = describe_bake_output_target(
        output_mode=props.material_bake_output_mode,
        blend_path=blend_path,
        publish_root=publish_root,
        custom_dir=props.material_bake_output_dir,
    )
    hint = layout.row()
    hint.scale_y = 0.85
    if ok:
        hint.label(text=summary, icon="FILE_TICK")
    else:
        hint.alert = True
        hint.label(text=err, icon="ERROR")
    return ok


def draw_material_bake_actions(
    layout: UILayout,
    props,
    *,
    enabled_count: int,
    output_ok: bool = True,
) -> None:
    if props.material_bake_running and props.material_bake_report:
        ui_style.status_label(
            layout,
            props.material_bake_report,
            ok=True,
            icon="SORTTIME",
        )
    elif props.material_bake_report:
        ui_style.status_label(layout, props.material_bake_report, ok=True)

    layout.separator()
    bake_row = layout.row(align=True)
    bake_row.scale_y = 1.5
    bake_row.enabled = (
        enabled_count > 0
        and not props.material_bake_list_error
        and output_ok
        and not props.material_bake_running
    )
    bake_main = bake_row.row(align=True)
    bake_main.operator(
        "wm.mono_fx_bake_materials_usd",
        text=material_bake_action_label(props),
        icon="RENDER_STILL",
    )
    bake_folder = bake_row.row(align=True)
    bake_folder.enabled = output_ok
    bake_folder.operator(
        "wm.mono_fx_material_bake_open_output_folder",
        text="",
        icon="FILE_FOLDER",
    )
    bake_restore = bake_row.row(align=True)
    bake_restore.enabled = (
        restorable_bake_target_count(props) > 0 and not props.material_bake_running
    )
    bake_restore.operator(
        "wm.mono_fx_material_bake_restore_sources",
        text="",
        icon="LOOP_BACK",
    )
    bake_settings = bake_row.row(align=True)
    bake_settings.scale_x = 1.15
    bake_settings.operator(
        "wm.mono_fx_bake_materials_usd_settings",
        text="",
        icon="PREFERENCES",
    )
