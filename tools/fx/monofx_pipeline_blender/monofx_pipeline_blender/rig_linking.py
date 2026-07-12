"""
Rig linking business logic and operators.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Context, Operator, PropertyGroup, UIList

from . import preferences
from . import rig_adapter
from . import rig_focus
from . import rig_paths
from monofx_pipeline_common.project_context import (
    project_context_error,
    resolve_project_root,
    valid_project_root,
)
from monofx_pipeline_common.project_layout import parse_asset_from_project_path

_MSGBUS_OWNER = object()
_rig_refresh_timer = None


def _tag_rig_ui_redraw() -> None:
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _debounced_rig_cache_refresh() -> None:
    global _rig_refresh_timer

    def _run() -> None:
        global _rig_refresh_timer
        _rig_refresh_timer = None
        for scene in bpy.data.scenes:
            props = getattr(scene, "monofx_pipeline_blender_props", None)
            if props is None:
                continue
            try:
                refresh_rig_cache(props)
            except Exception:
                pass
        _tag_rig_ui_redraw()

    if _rig_refresh_timer is not None:
        try:
            bpy.app.timers.unregister(_rig_refresh_timer)
        except Exception:
            pass
    _rig_refresh_timer = bpy.app.timers.register(_run, first_interval=0.2)


def _on_rig_libraries_changed(*_args) -> None:
    _debounced_rig_cache_refresh()


def register_rig_listeners() -> None:
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.BlendData, "libraries"),
        owner=_MSGBUS_OWNER,
        args=(),
        notify=_on_rig_libraries_changed,
        options={"PERSISTENT"},
    )
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.Library, "filepath"),
        owner=_MSGBUS_OWNER,
        args=(),
        notify=_on_rig_libraries_changed,
        options={"PERSISTENT"},
    )


def unregister_rig_listeners() -> None:
    global _rig_refresh_timer
    bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    if _rig_refresh_timer is not None:
        try:
            bpy.app.timers.unregister(_rig_refresh_timer)
        except Exception:
            pass
        _rig_refresh_timer = None


class MonoFXRigVersionItem(PropertyGroup):
    label: StringProperty(name="Label", default="")
    path: StringProperty(name="Path", default="")


class MonoFXRigLibraryItem(PropertyGroup):
    asset_folder_name: StringProperty(name="Asset Folder", default="")
    display_name: StringProperty(name="Display Name", default="")
    thumb_path: StringProperty(name="Thumb Path", default="")
    version_index: IntProperty(name="Version Index", default=0, min=0)
    versions: CollectionProperty(type=MonoFXRigVersionItem)


class MonoFXRigSceneItem(PropertyGroup):
    ref_id: StringProperty(name="Ref ID", default="")
    namespace: StringProperty(name="Namespace", default="")
    resolved_path: StringProperty(name="Path", default="")
    current_token: StringProperty(name="Current Version", default="")
    newest_token: StringProperty(name="Newest Version", default="")
    is_on_newest: bpy.props.BoolProperty(name="On Newest", default=True)
    has_scan_match: bpy.props.BoolProperty(name="Has Scan Match", default=False)
    newest_path: StringProperty(name="Newest Path", default="")
    is_loaded: bpy.props.BoolProperty(name="Loaded", default=True)
    exists_on_disk: bpy.props.BoolProperty(name="Exists", default=True)
    in_project: bpy.props.BoolProperty(name="In Project", default=False)
    is_override: bpy.props.BoolProperty(name="Has Override", default=False)


def _scene_blend_path() -> Optional[Path]:
    raw = rig_adapter.get_scene_path()
    if not raw:
        return None
    return Path(raw)


def _persist_project_root(props, root: Path, context: Optional[Context] = None) -> None:
    root_text = str(root)
    if getattr(props, "pipeline_project_root", "") != root_text:
        props.pipeline_project_root = root_text
    prefs = preferences.get_addon_prefs(context)
    if prefs is not None and getattr(prefs, "pipeline_project_root", "") != root_text:
        prefs.pipeline_project_root = root_text


def _project_context(
    props=None,
    context: Optional[Context] = None,
) -> Tuple[Optional[Path], str]:
    if props is None:
        try:
            props = bpy.context.scene.monofx_pipeline_blender_props
        except Exception:
            props = None

    scene_path = _scene_blend_path()
    scene_text = str(scene_path) if scene_path is not None else None
    stored = getattr(props, "pipeline_project_root", "") if props is not None else ""
    prefs = preferences.get_addon_prefs(context)
    fallback = getattr(prefs, "pipeline_project_root", "") if prefs is not None else ""

    root, source = resolve_project_root(scene_text, stored, fallback)
    if root is not None:
        if props is not None and source in {"scene", "stored", "fallback"}:
            _persist_project_root(props, root, context)
        return root, ""

    has_stored = bool((stored or "").strip())
    has_fallback = bool((fallback or "").strip())
    return None, project_context_error(scene_text, has_stored=has_stored, has_fallback=has_fallback)


def _rig_mode(props) -> rig_paths.Mode:
    return "publish" if props.rig_mode == "PUBLISH" else "work"


def _filtered_library_items(props) -> List[MonoFXRigLibraryItem]:
    q = (props.rig_search or "").strip().casefold()
    items = list(props.rig_library_cache)
    if not q:
        return items
    return [it for it in items if q in (it.display_name or "").casefold() or q in (it.asset_folder_name or "").casefold()]


def _selected_library_item(props) -> Optional[MonoFXRigLibraryItem]:
    items = _filtered_library_items(props)
    idx = int(props.rig_library_index)
    if idx < 0 or idx >= len(items):
        return None
    return items[idx]


def _selected_scene_item(props) -> Optional[MonoFXRigSceneItem]:
    idx = int(props.rig_scene_index)
    if idx < 0 or idx >= len(props.rig_scene_cache):
        return None
    return props.rig_scene_cache[idx]


def refresh_rig_scene_cache_only(props) -> None:
    """Update linked-rig list without rescanning the library on disk."""
    rig_focus.suppress_focus()
    try:
        root, _ = _project_context(props)
        mode = _rig_mode(props)
        props.rig_scene_cache.clear()
        for row in rig_adapter.collect_file_references(str(root) if root else None):
            path = row.get("resolved_path") or row.get("unresolved_path") or ""
            disp = rig_paths.scene_ref_version_display(path, root, mode) if path and root else None
            si = props.rig_scene_cache.add()
            si.ref_id = row.get("ref_id") or row.get("ref_node_short") or ""
            si.namespace = row.get("namespace") or ""
            si.resolved_path = path
            si.is_loaded = bool(row.get("is_loaded", True))
            si.exists_on_disk = bool(row.get("exists_on_disk", True))
            si.in_project = bool(row.get("in_project"))
            si.is_override = bool(row.get("is_override"))
            if disp:
                si.current_token = disp.current_token
                si.newest_token = disp.newest_token
                si.is_on_newest = disp.is_on_newest
                si.has_scan_match = disp.has_scan_match
                si.newest_path = disp.newest_path
            else:
                si.current_token = rig_paths.version_display_token_from_path(path, mode) or "—"
        props.rig_scene_index = max(0, len(props.rig_scene_cache) - 1)
    finally:
        rig_focus.schedule_release_suppress()


def _schedule_rig_focus(context: Context, ref_id: str, props) -> None:
    if not rig_focus.should_apply(props):
        return

    def _run() -> None:
        try:
            rig_focus.apply_rig_focus(context, ref_id, props)
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_run, first_interval=0.0)
    except Exception:
        try:
            rig_focus.apply_rig_focus(context, ref_id, props)
        except Exception:
            pass


def refresh_rig_cache(props) -> Tuple[bool, str]:
    rig_focus.suppress_focus()
    try:
        return _refresh_rig_cache_impl(props)
    finally:
        rig_focus.schedule_release_suppress()


def _refresh_rig_cache_impl(props) -> Tuple[bool, str]:
    root, err = _project_context(props)
    if root is None:
        props.rig_library_cache.clear()
        props.rig_scene_cache.clear()
        props.rig_project_name = ""
        return False, err

    props.rig_project_name = root.name
    groups = rig_paths.list_asset_groups_for_project(root)
    props.rig_asset_group_list = "|".join(groups)
    mode = _rig_mode(props)
    group = props.rig_asset_group
    if not group or group == "_none":
        if groups:
            group = groups[0]
            props.rig_asset_group = group
        else:
            props.rig_library_cache.clear()
            props.rig_scene_cache.clear()
            return False, "No asset groups found under 01_assets."

    props.rig_library_cache.clear()
    offers = rig_paths.scan_blender_rigs(root, group, mode)
    for offer in offers:
        item = props.rig_library_cache.add()
        item.asset_folder_name = offer.asset_folder_name
        item.display_name = offer.display_name
        tp = rig_paths.thumb_path_for_asset(offer.asset_root)
        item.thumb_path = str(tp) if tp.is_file() else ""
        item.version_index = max(0, offer.default_index)
        for ver in offer.versions:
            vi = item.versions.add()
            vi.label = ver.label
            vi.path = ver.path

    props.rig_scene_cache.clear()
    for row in rig_adapter.collect_file_references(str(root)):
        path = row.get("resolved_path") or row.get("unresolved_path") or ""
        disp = rig_paths.scene_ref_version_display(path, root, mode) if path else None
        si = props.rig_scene_cache.add()
        si.ref_id = row.get("ref_id") or row.get("ref_node_short") or ""
        si.namespace = row.get("namespace") or ""
        si.resolved_path = path
        si.is_loaded = bool(row.get("is_loaded", True))
        si.exists_on_disk = bool(row.get("exists_on_disk", True))
        si.in_project = bool(row.get("in_project"))
        si.is_override = bool(row.get("is_override"))
        if disp:
            si.current_token = disp.current_token
            si.newest_token = disp.newest_token
            si.is_on_newest = disp.is_on_newest
            si.has_scan_match = disp.has_scan_match
            si.newest_path = disp.newest_path
        else:
            si.current_token = rig_paths.version_display_token_from_path(path, mode) or "—"

    props.rig_library_index = min(props.rig_library_index, max(0, len(_filtered_library_items(props)) - 1))
    props.rig_scene_index = min(props.rig_scene_index, max(0, len(props.rig_scene_cache) - 1))
    return True, f"Found {len(offers)} rig(s), {len(props.rig_scene_cache)} link(s)."


def _library_version_path(item: MonoFXRigLibraryItem) -> Optional[str]:
    if not item or not item.versions:
        return None
    idx = max(0, min(int(item.version_index), len(item.versions) - 1))
    path = item.versions[idx].path
    return path if path else None


def _asset_folder_hint_for_rig_file(
    path: str,
    props,
    context: Optional[Context] = None,
) -> str:
    manual = (getattr(props, "rig_manual_namespace", "") or "").strip()
    if manual:
        return manual
    root, _ = _project_context(props, context)
    if root is not None:
        parsed = parse_asset_from_project_path(Path(path), root)
        if parsed:
            return parsed[1]
    return Path(path).stem


def _link_rig_file(
    context: Context,
    props,
    path: str,
) -> Tuple[bool, str]:
    fp = os.path.normpath(path)
    if not os.path.isfile(fp):
        return False, "Rig file not found."
    if Path(fp).suffix.lower() != ".blend":
        return False, "Rig file must be a .blend."
    props.rig_manual_link_path = fp
    hint = _asset_folder_hint_for_rig_file(fp, props, context)
    try:
        ref_id = rig_adapter.create_file_reference(fp, hint)
    except Exception as e:
        return False, str(e)
    refresh_rig_scene_cache_only(props)
    _schedule_rig_focus(context, ref_id, props)
    return True, ref_id


class MONOFX_OT_rig_refresh(Operator):
    bl_idname = "wm.mono_fx_rig_refresh"
    bl_label = "Refresh Rig Lists"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        ok, msg = refresh_rig_cache(props)
        self.report({"INFO"} if ok else {"WARNING"}, msg)
        return {"FINISHED"}


class MONOFX_OT_rig_link_from_library(Operator):
    bl_idname = "wm.mono_fx_rig_link_from_library"
    bl_label = "Link into Scene"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        item = _selected_library_item(props)
        if item is None:
            self.report({"ERROR"}, "Select a rig in the library list.")
            return {"CANCELLED"}
        path = _library_version_path(item)
        if not path:
            self.report({"ERROR"}, "No rig file for the selected asset.")
            return {"CANCELLED"}
        try:
            ref_id = rig_adapter.create_file_reference(path, item.asset_folder_name)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        refresh_rig_scene_cache_only(props)
        _schedule_rig_focus(context, ref_id, props)
        self.report({"INFO"}, f"Linked rig: {ref_id}")
        return {"FINISHED"}


class MONOFX_OT_rig_browse_rig_file(Operator):
    bl_idname = "wm.mono_fx_rig_browse_rig_file"
    bl_label = "Browse Rig File"
    bl_description = "Choose a rig .blend file to link manually"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.blend", options={"HIDDEN"})

    def invoke(self, context: Context, _event) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        start = (props.rig_manual_link_path or "").strip()
        if start and os.path.isfile(start):
            self.filepath = start
        elif start and os.path.isdir(os.path.dirname(start)):
            self.filepath = os.path.dirname(start)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Context) -> set[str]:
        path = (self.filepath or "").strip()
        if not path:
            return {"CANCELLED"}
        context.scene.monofx_pipeline_blender_props.rig_manual_link_path = os.path.normpath(path)
        return {"FINISHED"}


class MONOFX_OT_rig_link_manual(Operator):
    bl_idname = "wm.mono_fx_rig_link_manual"
    bl_label = "Link Rig File"
    bl_description = "Link a rig .blend from disk (manual import)"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.blend", options={"HIDDEN"})

    def invoke(self, context: Context, _event) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        cached = (props.rig_manual_link_path or "").strip()
        if cached and os.path.isfile(cached):
            self.filepath = cached
            return self.execute(context)
        start = cached
        if start and os.path.isfile(start):
            self.filepath = start
        elif start and os.path.isdir(os.path.dirname(start)):
            self.filepath = os.path.dirname(start)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        path = (self.filepath or props.rig_manual_link_path or "").strip()
        ok, msg = _link_rig_file(context, props, path)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, f"Linked rig: {msg}")
        return {"FINISHED"}


_PREFIX_BATCH_SIZE = 4


def _rig_refresh_modal_cleanup(context: Context, op) -> None:
    wm = context.window_manager
    timer = getattr(op, "_timer", None)
    if timer is not None:
        try:
            wm.event_timer_remove(timer)
        except Exception:
            pass
        op._timer = None
    try:
        wm.progress_end()
    except Exception:
        pass
    try:
        context.window.cursor_set("DEFAULT")
    except Exception:
        pass


def _rig_refresh_modal_tick(context: Context, op, *, done_label: str) -> set[str]:
    session = getattr(op, "_session", None)
    if session is None:
        _rig_refresh_modal_cleanup(context, op)
        return {"CANCELLED"}

    err = session.tick(prefix_batch=_PREFIX_BATCH_SIZE)
    current, total = session.progress()
    wm = context.window_manager
    progress_total = getattr(op, "_rig_progress_total", None)
    if progress_total != total:
        op._rig_progress_total = total
        try:
            wm.progress_end()
            wm.progress_begin(0, max(total, 1))
        except Exception:
            pass
    wm.progress_update(current)

    if err:
        _rig_refresh_modal_cleanup(context, op)
        op._session = None
        op.report({"ERROR"}, err)
        return {"CANCELLED"}

    if session.done:
        props = context.scene.monofx_pipeline_blender_props
        refresh_rig_scene_cache_only(props)
        try:
            rig_adapter.load_reference_node(session.ref_id)
        except Exception:
            pass
        renamed = session.renamed
        _rig_refresh_modal_cleanup(context, op)
        op._session = None
        if renamed:
            op.report({"INFO"}, f"{done_label} ({renamed} name(s) prefixed).")
        else:
            op.report({"INFO"}, done_label)
        return {"FINISHED"}

    return {"RUNNING_MODAL"}


def _rig_refresh_modal_invoke(
    context: Context,
    op,
    *,
    ref_id: str,
    new_path: str = "",
) -> set[str]:
    op._session = rig_adapter.RigLibraryRefreshSession(
        ref_id,
        new_path=new_path or None,
    )
    wm = context.window_manager
    wm.progress_begin(0, 1)
    op._timer = wm.event_timer_add(0.01, window=context.window)
    wm.modal_handler_add(op)
    try:
        context.window.cursor_set("WAIT")
    except Exception:
        pass
    return {"RUNNING_MODAL"}


class MONOFX_OT_rig_switch_version(Operator):
    bl_idname = "wm.mono_fx_rig_switch_version"
    bl_label = "Switch Rig Version"
    bl_options = {"REGISTER", "UNDO"}

    ref_id: StringProperty(default="")
    new_path: StringProperty(default="")

    _session = None
    _timer = None

    def _resolve_new_path(self, context: Context, item) -> tuple[str, str]:
        new_path = self.new_path
        if new_path:
            return new_path, ""
        props = context.scene.monofx_pipeline_blender_props
        root, err = _project_context(props)
        if root is None:
            return "", err
        path = item.resolved_path if item else ""
        newer = rig_paths.newer_rig_version_for_scene_path(path, root, _rig_mode(props))
        if newer is None and item and item.newest_path:
            return item.newest_path, ""
        if newer is not None:
            return newer.path, ""
        entries = rig_paths.matching_rig_versions_for_scene_path(path, root, _rig_mode(props))
        if not entries:
            return "", "No matching rig versions on disk."
        return entries[-1].path, ""

    def invoke(self, context: Context, _event) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        item = _selected_scene_item(props)
        ref_id = self.ref_id or (item.ref_id if item else "")
        if not ref_id:
            self.report({"ERROR"}, "Select a linked rig.")
            return {"CANCELLED"}

        new_path, err = self._resolve_new_path(context, item)
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}

        return _rig_refresh_modal_invoke(
            context,
            self,
            ref_id=ref_id,
            new_path=new_path,
        )

    def modal(self, context: Context, event) -> set[str]:
        if event.type == "ESC":
            _rig_refresh_modal_cleanup(context, self)
            self._session = None
            self.report({"WARNING"}, "Rig version update cancelled.")
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        return _rig_refresh_modal_tick(
            context,
            self,
            done_label="Rig version updated",
        )

    def execute(self, context: Context) -> set[str]:
        return self.invoke(context, None)


class MONOFX_OT_rig_reload(Operator):
    bl_idname = "wm.mono_fx_rig_reload"
    bl_label = "Reload Rig"
    bl_options = {"REGISTER", "UNDO"}

    _session = None
    _timer = None

    def invoke(self, context: Context, _event) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        item = _selected_scene_item(props)
        if item is None or not item.ref_id:
            self.report({"ERROR"}, "Select a linked rig.")
            return {"CANCELLED"}
        return _rig_refresh_modal_invoke(context, self, ref_id=item.ref_id)

    def modal(self, context: Context, event) -> set[str]:
        if event.type == "ESC":
            _rig_refresh_modal_cleanup(context, self)
            self._session = None
            self.report({"WARNING"}, "Rig reload cancelled.")
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        return _rig_refresh_modal_tick(
            context,
            self,
            done_label="Rig reloaded from disk",
        )

    def execute(self, context: Context) -> set[str]:
        return self.invoke(context, None)


class MONOFX_OT_rig_remove(Operator):
    bl_idname = "wm.mono_fx_rig_remove"
    bl_label = "Remove Rig Link"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        item = _selected_scene_item(props)
        if item is None or not item.ref_id:
            self.report({"ERROR"}, "Select a linked rig.")
            return {"CANCELLED"}
        try:
            rig_adapter.remove_file_reference(
                item.ref_id,
                exists_on_disk=item.exists_on_disk,
                is_loaded=item.is_loaded,
            )
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        refresh_rig_cache(props)
        self.report({"INFO"}, "Rig link removed.")
        return {"FINISHED"}


class MONOFX_OT_rig_update_all(Operator):
    bl_idname = "wm.mono_fx_rig_update_all"
    bl_label = "Update All to Latest"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        root, err = _project_context(props)
        if root is None:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        mode = _rig_mode(props)
        updated = 0
        errors: List[str] = []
        for si in list(props.rig_scene_cache):
            if si.is_on_newest or not si.has_scan_match:
                continue
            newer = rig_paths.newer_rig_version_for_scene_path(si.resolved_path, root, mode)
            target = newer.path if newer else si.newest_path
            if not target or rig_paths.rig_paths_equivalent(si.resolved_path, target):
                continue
            try:
                rig_adapter.replace_reference_path(si.ref_id, target)
                updated += 1
            except Exception as e:
                errors.append(f"{si.namespace}: {e}")
        refresh_rig_cache(props)
        if errors:
            self.report({"WARNING"}, f"Updated {updated}; errors: {'; '.join(errors[:3])}")
        else:
            self.report({"INFO"}, f"Updated {updated} rig link(s).")
        return {"FINISHED"}


class MONOFX_OT_rig_open_file(Operator):
    bl_idname = "wm.mono_fx_rig_open_file"
    bl_label = "Open Rig File"
    bl_description = "Open the rig .blend in a new Blender session"
    bl_options = {"REGISTER"}

    filepath: StringProperty(default="")

    def execute(self, _context: Context) -> set[str]:
        path = self.filepath
        if not path:
            self.report({"ERROR"}, "No rig file path.")
            return {"CANCELLED"}
        try:
            rig_adapter.open_scene_path_new_session(path)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, "Opened rig in a new Blender session.")
        return {"FINISHED"}


class MONOFX_OT_rig_open_folder(Operator):
    bl_idname = "wm.mono_fx_rig_open_folder"
    bl_label = "Open File Location"
    bl_options = {"REGISTER"}

    filepath: StringProperty(default="")

    def execute(self, _context: Context) -> set[str]:
        path = self.filepath
        if not path or not os.path.isfile(path):
            self.report({"ERROR"}, "File not found.")
            return {"CANCELLED"}
        folder = os.path.normpath(os.path.dirname(path))
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", folder], check=False)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class MONOFX_OT_rig_browse_project_root(Operator):
    bl_idname = "wm.mono_fx_rig_browse_project_root"
    bl_label = "Browse Project Root"
    bl_description = "Choose pipeline project folder (contains 01_assets and 02_shots)"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")
    filter_folder: bpy.props.BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context: Context, _event) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        start = (props.pipeline_project_root or "").strip()
        if not start:
            prefs = preferences.get_addon_prefs(context)
            if prefs is not None:
                start = (prefs.pipeline_project_root or "").strip()
        if start and os.path.isdir(start):
            self.directory = start
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        path = (self.directory or "").strip()
        if not path:
            return {"CANCELLED"}
        root = valid_project_root(path)
        if root is None:
            self.report({"ERROR"}, "Not a pipeline project (need 01_assets and 02_shots).")
            return {"CANCELLED"}
        _persist_project_root(props, root, context)
        ok, msg = refresh_rig_cache(props)
        self.report({"INFO"} if ok else {"WARNING"}, msg)
        return {"FINISHED"}


class MONOFX_OT_rig_set_asset_group(Operator):
    bl_idname = "wm.mono_fx_rig_set_asset_group"
    bl_label = "Set Asset Group"
    bl_options = {"REGISTER", "UNDO"}

    group: StringProperty(default="")

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        g = (self.group or "").strip()
        if not g:
            return {"CANCELLED"}
        props.rig_asset_group = g
        ok, msg = refresh_rig_cache(props)
        self.report({"INFO"} if ok else {"WARNING"}, msg)
        return {"FINISHED"}


class MONOFX_OT_rig_set_library_version(Operator):
    bl_idname = "wm.mono_fx_rig_set_library_version"
    bl_label = "Set Library Version"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=0)

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        item = _selected_library_item(props)
        if item is None:
            return {"CANCELLED"}
        item.version_index = max(0, min(self.index, len(item.versions) - 1))
        return {"FINISHED"}


class MONOFX_UL_rig_library(UIList):
    bl_idname = "MONOFX_UL_rig_library"

    def draw_item(
        self,
        context: Context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index: int,
    ) -> None:
        del context, data, icon, active_data, active_propname, index
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            from . import rig_ui

            row = layout.row(align=True)
            thumb_id = rig_ui._thumb_icon_id(item.thumb_path)
            ver_label = ""
            if item.versions and 0 <= item.version_index < len(item.versions):
                ver_label = rig_paths.version_display_token_from_path(
                    item.versions[item.version_index].path,
                    "publish",
                )
            text = f"{item.display_name}  {ver_label}".strip()
            if thumb_id:
                row.label(text=text, icon_value=thumb_id)
            else:
                row.label(text=text, icon="LINKED")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.display_name, icon="LINKED")


class MONOFX_UL_rig_scene(UIList):
    bl_idname = "MONOFX_UL_rig_scene"

    def draw_item(
        self,
        context: Context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index: int,
    ) -> None:
        del context, data, icon, active_data, active_propname, index
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            load_icon = "HIDE_OFF" if item.is_loaded else "HIDE_ON"
            row.label(text="", icon=load_icon)
            ver = item.current_token or "—"
            if item.has_scan_match and not item.is_on_newest and item.newest_token:
                sub = row.row(align=True)
                sub.alert = True
                sub.label(text=f"{item.namespace}  {ver} → {item.newest_token}", icon="ERROR")
            else:
                label = item.namespace or (
                    Path(item.resolved_path).name if item.resolved_path else "Rig"
                )
                icon = "LIBRARY_DATA_OVERRIDE" if item.is_override else "LINK_BLEND"
                row.label(text=f"{label}  {ver}", icon=icon)
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.namespace, icon="LINKED")


RIG_PROPERTY_GROUP_CLASSES = (
    MonoFXRigVersionItem,
    MonoFXRigLibraryItem,
    MonoFXRigSceneItem,
)

RIG_UI_LIST_CLASSES = (
    MONOFX_UL_rig_library,
    MONOFX_UL_rig_scene,
)

RIG_OPERATOR_CLASSES = (
    MONOFX_OT_rig_browse_project_root,
    MONOFX_OT_rig_browse_rig_file,
    MONOFX_OT_rig_set_asset_group,
    MONOFX_OT_rig_refresh,
    MONOFX_OT_rig_link_from_library,
    MONOFX_OT_rig_link_manual,
    MONOFX_OT_rig_switch_version,
    MONOFX_OT_rig_reload,
    MONOFX_OT_rig_remove,
    MONOFX_OT_rig_update_all,
    MONOFX_OT_rig_open_file,
    MONOFX_OT_rig_open_folder,
    MONOFX_OT_rig_set_library_version,
)
