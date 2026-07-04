"""
Export collection preview list for Geo USD publish.
"""

from __future__ import annotations

from typing import Optional, Sequence

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import Context, PropertyGroup, UIList, UILayout

from .asset_hierarchy import (
    find_asset_hierarchies_in_scene,
    find_collections_for_keyword_export,
    find_collections_for_selected_export,
    objects_in_collection_for_export,
    resolve_asset_for_publish,
)

_publish_refresh_timer = None
_publish_refresh_scene_name: Optional[str] = None
_publish_refresh_pending = False
_MSGBUS_OWNER = object()


class GeoUsdPublishObjectItem(PropertyGroup):
    object_name: StringProperty(name="Collection", default="")
    object_type: StringProperty(name="Type", default="")
    source_label: StringProperty(name="Detail", default="")
    enabled: BoolProperty(
        name="Export",
        description="Include this collection when publishing",
        default=True,
    )


def _object_count_label(count: int) -> str:
    suffix = "s" if count != 1 else ""
    return f"{count} object{suffix}"


def _collection_row(collection_name: str, object_count: int) -> tuple[str, str, str]:
    return collection_name, "COLLECTION", _object_count_label(object_count)


def _selected_object_names(context: Context) -> tuple[str, ...]:
    return tuple(sorted(o.name for o in getattr(context, "selected_objects", []) or []))


def _existing_collection_names(props) -> set[str]:
    return {item.object_name for item in props.geo_usd_publish_objects if item.object_name}


def _snapshot_enabled_flags(props) -> dict[str, bool]:
    return {item.object_name: bool(item.enabled) for item in props.geo_usd_publish_objects}


def enabled_publish_items(props) -> list[GeoUsdPublishObjectItem]:
    return [item for item in props.geo_usd_publish_objects if item.enabled and item.object_name]


def publish_export_enabled_count(props) -> int:
    return len(enabled_publish_items(props))


def publish_export_object_count(props) -> int:
    return len(props.geo_usd_publish_objects)


def compute_publish_export_signature(context: Context, props) -> str:
    """Lightweight scene signature for export-target refresh."""
    active = context.view_layer.objects.active
    active_name = active.name if active is not None else ""
    sel = _selected_object_names(context)

    cols = ""
    if props.export_selected_collection:
        cols = ",".join(
            sorted(c.name for c in find_collections_for_selected_export(context))
        )

    kw_cols = ""
    if props.export_collections_by_keyword:
        kw_cols = ",".join(
            sorted(
                c.name
                for c in find_collections_for_keyword_export(
                    str(props.export_collection_keyword or "")
                )
            )
        )

    hierarchies = find_asset_hierarchies_in_scene()
    hi_part = f"{len(hierarchies)}:" + ",".join(
        h.asset_collection.name for h in hierarchies[:5]
    )
    return (
        f"sel={int(props.export_selected_collection)}#"
        f"kw={int(props.export_collections_by_keyword)}#"
        f"key={props.export_collection_keyword}#"
        f"tree={int(props.select_hierarchy)}#"
        f"objs={','.join(sel)}#act={active_name}#"
        f"cols={cols}#kwcols={kw_cols}#hi={hi_part}"
    )


def _rows_from_collections(collections) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for col in sorted(collections, key=lambda c: c.name.lower()):
        count = len(objects_in_collection_for_export(col))
        if count <= 0:
            continue
        rows.append(_collection_row(col.name, count))
    return rows


def plan_publish_export_rows(
    context: Context,
    props,
) -> tuple[list[tuple[str, str, str]], str]:
    """Return rows of (collection_name, kind, detail) and an error message."""
    if props.export_selected_collection:
        cols = find_collections_for_selected_export(context)
        if not cols:
            return [], (
                "No collection selected. Select one or more collections in the Outliner, "
                "or activate a collection in the hierarchy."
            )
        rows = _rows_from_collections(cols)
        if not rows:
            return [], "No exportable objects found in selected collection(s)."
        return rows, ""

    if props.export_collections_by_keyword:
        keyword = str(props.export_collection_keyword or "")
        label = keyword.strip() or "all"
        cols = find_collections_for_keyword_export(keyword)
        if not cols:
            return [], f"No collections with objects matching '{label}'."
        rows = _rows_from_collections(cols)
        if not rows:
            return [], "No exportable objects found in matching collections."
        return rows, ""

    selected = list(getattr(context, "selected_objects", []) or [])
    ok, hierarchy, objs, err = resolve_asset_for_publish(
        active=context.view_layer.objects.active,
        selected=selected,
        select_hierarchy=props.select_hierarchy,
    )
    if not ok or hierarchy is None:
        return [], err
    if not objs:
        return [], "No objects to export."
    return [_collection_row(hierarchy.asset_collection.name, len(objs))], ""


def _append_collection_item(
    props,
    collection_name: str,
    *,
    enabled: bool = True,
) -> bool:
    col = bpy.data.collections.get(collection_name)
    if col is None:
        return False
    count = len(objects_in_collection_for_export(col))
    if count <= 0:
        return False
    item = props.geo_usd_publish_objects.add()
    item.object_name = collection_name
    item.object_type = "COLLECTION"
    item.source_label = _object_count_label(count)
    item.enabled = enabled
    return True


def add_selected_collections_to_list(context: Context, props) -> tuple[int, str]:
    cols = find_collections_for_selected_export(context)
    if not cols:
        return 0, (
            "No collection selected. Select one or more collections in the Outliner, "
            "or activate a collection in the hierarchy."
        )

    existing = _existing_collection_names(props)
    added = 0
    for col in sorted(cols, key=lambda c: c.name.lower()):
        if col.name in existing:
            continue
        if _append_collection_item(props, col.name, enabled=True):
            existing.add(col.name)
            added += 1
    if added <= 0:
        return 0, "Selected collection(s) are already in the list or have no objects."
    return added, ""


def remove_publish_list_items(props, indices: Sequence[int]) -> int:
    removed = 0
    for index in sorted({int(i) for i in indices}, reverse=True):
        if index < 0 or index >= len(props.geo_usd_publish_objects):
            continue
        props.geo_usd_publish_objects.remove(index)
        removed += 1
    props.geo_usd_publish_object_index = min(
        props.geo_usd_publish_object_index,
        max(0, len(props.geo_usd_publish_objects) - 1),
    )
    return removed


def _tag_publish_panel_redraw(context: Optional[Context] = None) -> None:
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


def _refresh_publish_export_list_impl(context: Context, props, *, force: bool = False) -> None:
    signature = compute_publish_export_signature(context, props)
    if not force and signature == props.geo_usd_publish_objects_signature:
        return

    props.geo_usd_publish_objects_signature = signature
    prev_enabled = _snapshot_enabled_flags(props)
    rows, err = plan_publish_export_rows(context, props)
    props.geo_usd_publish_list_error = err
    planned_names = {collection_name for collection_name, _kind, _detail in rows}
    collection_export = (
        props.export_collections_by_keyword or props.export_selected_collection
    )

    props.geo_usd_publish_objects.clear()
    for collection_name, kind, detail in rows:
        item = props.geo_usd_publish_objects.add()
        item.object_name = collection_name
        item.object_type = kind
        item.source_label = detail
        item.enabled = prev_enabled.get(collection_name, True)

    if not collection_export:
        for collection_name, enabled in prev_enabled.items():
            if collection_name in planned_names:
                continue
            _append_collection_item(props, collection_name, enabled=enabled)

    props.geo_usd_publish_object_index = min(
        props.geo_usd_publish_object_index,
        max(0, len(props.geo_usd_publish_objects) - 1),
    )


def schedule_publish_export_refresh(context: Context) -> None:
    """Defer RNA writes — safe to call from panel draw()."""
    global _publish_refresh_timer, _publish_refresh_scene_name, _publish_refresh_pending

    if _publish_refresh_pending:
        return

    _publish_refresh_scene_name = context.scene.name
    _publish_refresh_pending = True
    refresh_context = context

    def _run() -> None:
        global _publish_refresh_timer, _publish_refresh_pending
        _publish_refresh_timer = None
        _publish_refresh_pending = False
        scene = bpy.data.scenes.get(_publish_refresh_scene_name or "")
        if scene is None:
            return None
        props = getattr(scene, "monofx_pipeline_blender_props", None)
        if props is None:
            return None
        if props.geo_usd_publish_list_locked:
            return None
        context = refresh_context
        if getattr(context, "scene", None) is not scene:
            context = bpy.context
        try:
            _refresh_publish_export_list_impl(context, props, force=True)
        except Exception as exc:
            logger = __import__("logging").getLogger("monofx.geo_usd_publish")
            logger.exception("publish export list refresh failed: %s", exc)
        _tag_publish_panel_redraw(context)
        return None

    if _publish_refresh_timer is not None:
        try:
            bpy.app.timers.unregister(_publish_refresh_timer)
        except Exception:
            pass
    _publish_refresh_timer = bpy.app.timers.register(_run, first_interval=0.15)


def ensure_publish_export_refresh(context: Context, props) -> None:
    """Read-only in draw: schedule refresh when export targets changed."""
    if props.geo_usd_publish_list_locked:
        return
    signature = compute_publish_export_signature(context, props)
    if signature == props.geo_usd_publish_objects_signature:
        return
    schedule_publish_export_refresh(context)


def invalidate_publish_export_list_signature(props) -> None:
    props.geo_usd_publish_objects_signature = ""


def refresh_publish_export_list(context: Context, props, *, force: bool = False) -> None:
    """Immediate refresh — use from operators, not panel draw()."""
    _refresh_publish_export_list_impl(context, props, force=force)
    _tag_publish_panel_redraw(context)


def _invalidate_publish_export_signatures() -> None:
    for scene in bpy.data.scenes:
        props = getattr(scene, "monofx_pipeline_blender_props", None)
        if props is None:
            continue
        if props.geo_usd_publish_list_locked:
            continue
        if not (
            props.export_selected_collection or props.export_collections_by_keyword
        ):
            continue
        props.geo_usd_publish_objects_signature = ""


def _debounced_publish_export_refresh() -> None:
    global _publish_refresh_timer

    def _run() -> None:
        global _publish_refresh_timer
        _publish_refresh_timer = None
        context = bpy.context
        scene = getattr(context, "scene", None)
        if scene is None:
            return None
        props = getattr(scene, "monofx_pipeline_blender_props", None)
        if props is None:
            return None
        if props.geo_usd_publish_list_locked:
            return None
        try:
            _refresh_publish_export_list_impl(context, props, force=True)
        except Exception as exc:
            logger = __import__("logging").getLogger("monofx.geo_usd_publish")
            logger.exception("publish export list refresh failed: %s", exc)
        _tag_publish_panel_redraw(context)
        return None

    if _publish_refresh_timer is not None:
        try:
            bpy.app.timers.unregister(_publish_refresh_timer)
        except Exception:
            pass
    _publish_refresh_timer = bpy.app.timers.register(_run, first_interval=0.15)


def _on_view_layer_collection_changed(*_args) -> None:
    _invalidate_publish_export_signatures()
    _debounced_publish_export_refresh()


def register_publish_list_listeners() -> None:
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.ViewLayer, "active_layer_collection"),
        owner=_MSGBUS_OWNER,
        args=(),
        notify=_on_view_layer_collection_changed,
        options={"PERSISTENT"},
    )


def unregister_publish_list_listeners() -> None:
    global _publish_refresh_timer
    bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    if _publish_refresh_timer is not None:
        try:
            bpy.app.timers.unregister(_publish_refresh_timer)
        except Exception:
            pass
        _publish_refresh_timer = None
    _publish_refresh_pending = False


class MONOFX_UL_geo_usd_publish_objects(UIList):
    bl_idname = "MONOFX_UL_geo_usd_publish_objects"

    def draw_item(
        self,
        context: Context,
        layout: UILayout,
        data,
        item: GeoUsdPublishObjectItem,
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
            body.label(text=item.object_name, icon="OUTLINER_COLLECTION")
            if item.source_label:
                detail = body.row()
                detail.alignment = "RIGHT"
                detail.scale_x = 0.85
                detail.label(text=item.source_label)
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.object_name, icon="OUTLINER_COLLECTION")


class MONOFX_OT_refresh_geo_usd_publish_list(bpy.types.Operator):
    """Refresh the Geo USD export collection list from the current scene and options."""

    bl_idname = "wm.mono_fx_refresh_geo_usd_publish_list"
    bl_label = "Refresh Export List"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        refresh_publish_export_list(context, props, force=True)
        enabled = publish_export_enabled_count(props)
        total = publish_export_object_count(props)
        if props.geo_usd_publish_list_error and total == 0:
            self.report({"WARNING"}, props.geo_usd_publish_list_error)
        else:
            self.report({"INFO"}, f"Export list: {enabled}/{total} collection(s) enabled.")
        return {"FINISHED"}


class MONOFX_OT_geo_usd_publish_list_add_selected(bpy.types.Operator):
    """Add collection(s) selected in the Outliner to the export list."""

    bl_idname = "wm.mono_fx_geo_usd_publish_list_add_selected"
    bl_label = "Add Selected"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        added, err = add_selected_collections_to_list(context, props)
        if added <= 0:
            self.report({"WARNING"}, err or "Nothing added.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Added {added} collection(s).")
        return {"FINISHED"}


class MONOFX_OT_geo_usd_publish_list_remove(bpy.types.Operator):
    """Remove the active row from the export list."""

    bl_idname = "wm.mono_fx_geo_usd_publish_list_remove"
    bl_label = "Remove"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return len(props.geo_usd_publish_objects) > 0

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        removed = remove_publish_list_items(props, [props.geo_usd_publish_object_index])
        if removed <= 0:
            self.report({"WARNING"}, "No rows to remove.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Removed {removed} collection(s).")
        return {"FINISHED"}


GEO_USD_PUBLISH_PROPERTY_GROUP_CLASSES = (GeoUsdPublishObjectItem,)
GEO_USD_PUBLISH_UI_LIST_CLASSES = (MONOFX_UL_geo_usd_publish_objects,)
GEO_USD_PUBLISH_OPERATOR_CLASSES = (
    MONOFX_OT_refresh_geo_usd_publish_list,
    MONOFX_OT_geo_usd_publish_list_add_selected,
    MONOFX_OT_geo_usd_publish_list_remove,
)
