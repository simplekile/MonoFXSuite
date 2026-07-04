"""
Rig Link tab UI (draw helpers, thumbnails, context menu).
"""

from __future__ import annotations

from typing import List, Optional

import bpy
from bpy.types import Context, Menu, UILayout

from . import anim_ui
from . import preferences
from . import rig_linking
from . import rig_paths
from . import ui_style

_preview_collection = None


def init_previews() -> None:
    global _preview_collection
    if _preview_collection is None:
        _preview_collection = bpy.utils.previews.new()


def clear_previews() -> None:
    global _preview_collection
    if _preview_collection is not None:
        bpy.utils.previews.remove(_preview_collection)
        _preview_collection = None


def _thumb_icon_id(thumb_path: str) -> int:
    if not thumb_path or _preview_collection is None:
        return 0
    key = thumb_path
    if key not in _preview_collection:
        try:
            _preview_collection.load(key, thumb_path, "IMAGE")
        except Exception:
            return 0
    return _preview_collection[key].icon_id


def _filtered_library_count(props) -> int:
    return len(rig_linking._filtered_library_items(props))


def _asset_groups_from_props(props) -> List[str]:
    raw = (props.rig_asset_group_list or "").strip()
    if not raw:
        return []
    return [g.strip() for g in raw.split("|") if g.strip()]


def _rig_asset_group_menu_label(props) -> str:
    group = (props.rig_asset_group or "").strip()
    if group and group != "_none":
        return group
    groups = _asset_groups_from_props(props)
    if groups:
        return groups[0]
    return "Asset Group"


class MONOFX_MT_rig_asset_groups(Menu):
    bl_label = "Asset Group"

    def draw(self, context: Context) -> None:
        props = context.scene.monofx_pipeline_blender_props
        groups = _asset_groups_from_props(props)
        if not groups:
            self.layout.label(text="Refresh to load groups")
            return
        for group in groups:
            op = self.layout.operator("wm.mono_fx_rig_set_asset_group", text=group)
            op.group = group


class MONOFX_MT_rig_library_versions(Menu):
    bl_label = "Rig Version"

    def draw(self, context: Context) -> None:
        props = context.scene.monofx_pipeline_blender_props
        item = rig_linking._selected_library_item(props)
        if item is None or not item.versions:
            self.layout.label(text="No versions")
            return
        for i, ver in enumerate(item.versions):
            tok = rig_paths.version_display_token_from_path(ver.path, "publish") or ver.label
            op = self.layout.operator(
                "wm.mono_fx_rig_set_library_version",
                text=tok,
            )
            op.index = i


class MONOFX_MT_rig_scene_versions(Menu):
    bl_label = "Switch to Version"

    def draw(self, context: Context) -> None:
        props = context.scene.monofx_pipeline_blender_props
        item = rig_linking._selected_scene_item(props)
        root, _ = rig_linking._project_context(props, context)
        if item is None or root is None:
            self.layout.label(text="Select a linked rig")
            return
        mode = rig_linking._rig_mode(props)
        entries = rig_paths.matching_rig_versions_for_scene_path(item.resolved_path, root, mode)
        if not entries:
            self.layout.label(text="No versions on disk")
            return
        for ver in entries:
            tok = rig_paths.version_display_token_from_path(ver.path, mode) or ver.label
            op = self.layout.operator("wm.mono_fx_rig_switch_version", text=tok)
            op.ref_id = item.ref_id
            op.new_path = ver.path


def draw_rig_context_menu(self, context: Context) -> None:
    props = context.scene.monofx_pipeline_blender_props
    item = rig_linking._selected_scene_item(props)
    if item is None or not item.ref_id:
        return
    layout = self.layout
    layout.separator()
    layout.label(text="MonoFX Rig")
    layout.operator("wm.mono_fx_rig_reload", text="Reload Rig")
    layout.operator("wm.mono_fx_rig_switch_version", text="Update to Latest")
    layout.operator("wm.mono_fx_rig_remove", text="Remove Rig Link")


def draw_rig_link_tab(layout: UILayout, context: Context) -> None:
    prefs = preferences.get_addon_prefs(context)
    if prefs is None:
        return
    props = context.scene.monofx_pipeline_blender_props

    box = layout.box()
    root, err = rig_linking._project_context(props, context)
    if props.rig_project_name:
        box.label(text=f"Project: {props.rig_project_name}", icon="FILE_FOLDER")
    else:
        row = box.row()
        row.alert = True
        row.label(text=err or "Set pipeline project root", icon="ERROR")

    row = box.row(align=True)
    row.prop(props, "pipeline_project_root", text="Project")
    row.operator("wm.mono_fx_rig_browse_project_root", text="", icon="FILE_FOLDER")
    if root is None and (props.pipeline_project_root or "").strip():
        hint = box.row()
        hint.alert = True
        hint.label(text="Invalid project path (need 01_assets and 02_shots)", icon="ERROR")

    tabs_box = layout.box()
    _tabs, body = ui_style.draw_vertical_tabs(tabs_box, prefs, "ui_rig_section")
    section = prefs.ui_rig_section

    if section == "LIBRARY":
        row = body.row(align=True)
        row.prop(props, "rig_mode", expand=True)
        body.separator()
        row = body.row(align=True)
        row.menu("MONOFX_MT_rig_asset_groups", text=_rig_asset_group_menu_label(props))
        row.prop(props, "rig_search", text="", icon="VIEWZOOM")
        body.template_list(
            "MONOFX_UL_rig_library",
            "rig_library",
            props,
            "rig_library_cache",
            props,
            "rig_library_index",
            rows=6,
        )
        item = rig_linking._selected_library_item(props)
        if item and item.versions:
            ver_row = body.row(align=True)
            idx = max(0, min(item.version_index, len(item.versions) - 1))
            tok = rig_paths.version_display_token_from_path(item.versions[idx].path, rig_linking._rig_mode(props))
            ver_row.menu("MONOFX_MT_rig_library_versions", text=f"Version: {tok or '?'}")
            path = item.versions[idx].path
            if path:
                op_folder = ver_row.operator("wm.mono_fx_rig_open_folder", text="", icon="FILE_FOLDER")
                op_folder.filepath = path
        row = body.row(align=True)
        row.operator("wm.mono_fx_rig_link_from_library", text="Link into Scene", icon="LINKED")
        row.operator("wm.mono_fx_rig_refresh", text="", icon="FILE_REFRESH")
    elif section == "SCENE":
        ui_style.prop_checkbox(body, props, "rig_auto_focus", text="Auto Focus Rig")
        if props.rig_auto_focus:
            split = body.split(factor=0.06)
            split.column()
            focus_child = split.column()
            focus_child.label(text="Bone Auto-Select", icon="BONE_DATA")
            row = focus_child.row(align=True)
            ui_style.prop_checkbox(row, props, "rig_bone_pick_1", text="Bone 1")
            row.prop(props, "rig_bone_pick_1_name", text="")
            row = focus_child.row(align=True)
            ui_style.prop_checkbox(row, props, "rig_bone_pick_2", text="Bone 2")
            row.prop(props, "rig_bone_pick_2_name", text="")
            row = focus_child.row(align=True)
            ui_style.prop_checkbox(row, props, "rig_bone_pick_contains", text="Contains")
            row.prop(props, "rig_bone_pick_contains_text", text="")
        body.separator()
        body.label(text="Manual Link", icon="IMPORT")
        row = body.row(align=True)
        row.prop(props, "rig_manual_link_path", text="Rig File")
        row.operator("wm.mono_fx_rig_browse_rig_file", text="", icon="FILE_BLEND")
        row = body.row(align=True)
        row.prop(props, "rig_manual_namespace", text="Namespace")
        row.operator("wm.mono_fx_rig_link_manual", text="Link", icon="LINKED")
        body.separator()
        body.template_list(
            "MONOFX_UL_rig_scene",
            "rig_scene",
            props,
            "rig_scene_cache",
            props,
            "rig_scene_index",
            rows=5,
        )
        si = rig_linking._selected_scene_item(props)
        row = body.row(align=True)
        row.operator("wm.mono_fx_rig_switch_version", text="Update to Latest")
        row.menu("MONOFX_MT_rig_scene_versions", text="Versions")
        row = body.row(align=True)
        row.operator("wm.mono_fx_rig_reload", text="Reload", icon="FILE_REFRESH")
        row.operator("wm.mono_fx_rig_remove", text="Remove", icon="X")
        if si and si.resolved_path:
            row = body.row(align=True)
            op_open = row.operator("wm.mono_fx_rig_open_file", text="Open Rig", icon="FILE_BLEND")
            op_open.filepath = si.resolved_path
            op_loc = row.operator("wm.mono_fx_rig_open_folder", text="", icon="FILE_FOLDER")
            op_loc.filepath = si.resolved_path
        behind = sum(
            1 for x in props.rig_scene_cache if x.has_scan_match and not x.is_on_newest
        )
        if behind:
            alert = body.row()
            alert.alert = True
            alert.operator(
                "wm.mono_fx_rig_update_all",
                text=f"Update All to Latest ({behind})",
                icon="ERROR",
            )
    elif section == "SHOT":
        anim_ui._draw_anim_shot_section(body, context)


RIG_UI_CLASSES = (
    MONOFX_MT_rig_asset_groups,
    MONOFX_MT_rig_library_versions,
    MONOFX_MT_rig_scene_versions,
)
