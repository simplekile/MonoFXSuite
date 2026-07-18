"""
Geo USD publish version modes (Manual / Current / Next) and path helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy.types import Context, Operator, PropertyGroup, UILayout, UIList

from . import publish_paths
from . import ui_style


_PUBLISH_VERSION_SCAN_CACHE: dict[str, int] = {}
_VERSION_TOGGLE_CACHE: dict[str, float | int] = {"mono": 0.0, "current": 1, "next": 1}

def scene_blend_path() -> Optional[Path]:
    raw = str(getattr(bpy.data, "filepath", "") or "").strip()
    if not raw:
        return None
    try:
        return Path(raw)
    except Exception:
        return None


def geo_publish_root_for_scene(scene_path: Path) -> Optional[Path]:
    return publish_paths.resolve_publish_root_from_scene(scene_path)


def invalidate_geo_publish_version_cache() -> None:
    _PUBLISH_VERSION_SCAN_CACHE.clear()
    _VERSION_TOGGLE_CACHE["mono"] = 0.0


def list_geo_publish_versions() -> tuple[list[int], str]:
    """Version numbers with existing folders under modelling task ``publish``."""
    scene_path = scene_blend_path()
    if scene_path is None:
        return [], "Save the .blend file first."
    publish_root = geo_publish_root_for_scene(scene_path)
    if publish_root is None:
        return [], "Save .blend under 01_assets/.../01_modelling/<task>/..."
    return publish_paths.list_version_numbers(publish_root), ""


def current_geo_version_from_scene(*, use_cache: bool = True) -> int:
    """Latest existing geo publish folder, or ``1`` if none."""
    scene_path = scene_blend_path()
    if scene_path is None:
        return 1
    cache_key = f"current|{scene_path}"
    if use_cache:
        cached = _PUBLISH_VERSION_SCAN_CACHE.get(cache_key)
        if cached is not None:
            return int(cached)
    versions, _ = list_geo_publish_versions()
    version = versions[-1] if versions else 1
    if use_cache:
        _PUBLISH_VERSION_SCAN_CACHE[cache_key] = version
    return version


def next_geo_version_from_scene(*, use_cache: bool = True) -> int:
    """Next publish folder after the latest Manual list entry (or ``1`` if empty)."""
    scene_path = scene_blend_path()
    if scene_path is None:
        return 1
    cache_key = f"next|{scene_path}"
    if use_cache:
        cached = _PUBLISH_VERSION_SCAN_CACHE.get(cache_key)
        if cached is not None:
            return int(cached)
    versions, _ = list_geo_publish_versions()
    if versions:
        version = min(versions[-1] + 1, 999)
    else:
        version = 1
    if use_cache:
        _PUBLISH_VERSION_SCAN_CACHE[cache_key] = version
    return version


def cached_geo_version_toggle_numbers(*, max_age_s: float = 2.0) -> tuple[int, int]:
    import time

    now = time.monotonic()
    if now - float(_VERSION_TOGGLE_CACHE["mono"]) < max_age_s:
        return (
            int(_VERSION_TOGGLE_CACHE["current"]),
            int(_VERSION_TOGGLE_CACHE["next"]),
        )
    current_v = current_geo_version_from_scene(use_cache=True)
    next_v = next_geo_version_from_scene(use_cache=True)
    _VERSION_TOGGLE_CACHE["mono"] = now
    _VERSION_TOGGLE_CACHE["current"] = current_v
    _VERSION_TOGGLE_CACHE["next"] = next_v
    return current_v, next_v


def resolve_geo_publish_version_number(props) -> int:
    mode = str(getattr(props, "geo_usd_version_mode", "NEXT") or "NEXT")
    if mode == "MANUAL":
        manual = max(1, min(999, int(getattr(props, "geo_usd_manual_version", 1) or 1)))
        versions, _ = list_geo_publish_versions()
        if not versions:
            return 1
        if manual in versions:
            return manual
        return versions[-1]
    if mode == "CURRENT":
        return current_geo_version_from_scene()
    return next_geo_version_from_scene()


def build_geo_publish_usd_path(
    publish_root: Path,
    scene_path: Path,
    version_number: int,
) -> str:
    vname = publish_paths.version_folder_from_number(version_number)
    base = publish_paths.default_usd_basename_from_scene(scene_path)
    return str(publish_root / vname / f"{base}.usd")


def compute_geo_publish_usd_path(version_number: int) -> tuple[bool, str, str]:
    scene_path = scene_blend_path()
    if scene_path is None:
        return False, "", "Save the .blend file first."
    publish_root = geo_publish_root_for_scene(scene_path)
    if publish_root is None:
        return False, "", "Save .blend under 01_assets/.../01_modelling/<task>/..."
    return True, build_geo_publish_usd_path(publish_root, scene_path, version_number), ""


def populate_manual_version_pick_list(
    props,
    versions: list[int],
    *,
    select_version: int | None = None,
) -> None:
    items = props.geo_usd_manual_version_items
    items.clear()
    for version in versions:
        item = items.add()
        item.version_num = int(version)
        item.label = f"v{version:03d}"
    if select_version is not None and select_version in versions:
        pick_index = versions.index(select_version)
    else:
        pick_index = max(0, len(versions) - 1)
    props.geo_usd_manual_version_pick_index = pick_index


def picked_manual_version_number(props) -> int | None:
    items = props.geo_usd_manual_version_items
    index = int(getattr(props, "geo_usd_manual_version_pick_index", 0) or 0)
    if index < 0 or index >= len(items):
        return None
    return int(items[index].version_num)


def draw_geo_usd_version_toggles(layout: UILayout, props) -> None:
    manual_v = max(1, min(999, int(getattr(props, "geo_usd_manual_version", 1) or 1)))
    current_v, next_v = cached_geo_version_toggle_numbers()
    mode = str(getattr(props, "geo_usd_version_mode", "NEXT") or "NEXT")

    row = layout.row(align=True)
    ui_style.operator_row(
        row,
        "wm.mono_fx_pick_geo_publish_version",
        text=f"Manual (v{manual_v:03d})",
        depress=mode == "MANUAL",
    )
    op = ui_style.operator_row(
        row,
        "wm.mono_fx_set_geo_version_mode",
        text=f"Current (v{current_v:03d})",
        depress=mode == "CURRENT",
    )
    op.mode = "CURRENT"
    op = ui_style.operator_row(
        row,
        "wm.mono_fx_set_geo_version_mode",
        text=f"Next (v{next_v:03d})",
        depress=mode == "NEXT",
    )
    op.mode = "NEXT"


class GeoUsdManualVersionItem(PropertyGroup):
    version_num: IntProperty(name="Version", min=1, max=999, default=1)
    label: StringProperty(name="Label", default="")


class MONOFX_UL_geo_manual_publish_versions(UIList):
    bl_idname = "MONOFX_UL_geo_manual_publish_versions"

    def draw_item(
        self,
        context: Context,
        layout: UILayout,
        data,
        item: GeoUsdManualVersionItem,
        icon,
        active_data,
        active_propname,
        index: int,
    ) -> None:
        del context, data, icon, active_data, active_propname, index
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            layout.label(text=item.label, icon="FILE_FOLDER")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.label, icon="FILE_FOLDER")


class MONOFX_OT_set_geo_version_mode(Operator):
    bl_idname = "wm.mono_fx_set_geo_version_mode"
    bl_label = "Set Geo Version Mode"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        name="Mode",
        items=[
            ("CURRENT", "Current", "Latest existing publish folder"),
            ("NEXT", "Next", "Next publish folder after the latest"),
        ],
        default="NEXT",
    )

    def execute(self, context: Context) -> set[str]:
        import importlib

        props = context.scene.monofx_pipeline_blender_props
        props.geo_usd_version_mode = str(self.mode)
        root = importlib.import_module(__package__)
        root.sync_geo_publish_output(props)
        vname = publish_paths.version_folder_from_number(props.publish_version)
        self.report({"INFO"}, f"Version mode: {self.mode.lower()} ({vname})")
        return {"FINISHED"}


class MONOFX_OT_pick_geo_publish_version(Operator):
    bl_idname = "wm.mono_fx_pick_geo_publish_version"
    bl_label = "Pick Publish Version"
    bl_description = "Choose a publish version from existing folders"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context: Context, _event) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        versions, err = list_geo_publish_versions()
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        if not versions:
            self.report(
                {"WARNING"},
                "No publish folders yet — use Current or Next for the first publish.",
            )
            return {"CANCELLED"}
        props.geo_usd_version_mode = "MANUAL"
        manual = int(props.geo_usd_manual_version)
        if manual not in versions:
            manual = versions[-1]
        populate_manual_version_pick_list(props, versions, select_version=manual)
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context: Context) -> None:
        props = context.scene.monofx_pipeline_blender_props
        layout = self.layout
        layout.label(text="Publish version:", icon="FILE_FOLDER")
        item_count = len(props.geo_usd_manual_version_items)
        if item_count == 0:
            layout.label(text="No publish folders yet.", icon="INFO")
            return
        layout.template_list(
            "MONOFX_UL_geo_manual_publish_versions",
            "geo_manual_publish_versions",
            props,
            "geo_usd_manual_version_items",
            props,
            "geo_usd_manual_version_pick_index",
            rows=min(8, max(3, item_count)),
        )

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        versions, err = list_geo_publish_versions()
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        version = picked_manual_version_number(props)
        if version is None:
            self.report({"ERROR"}, "Select a publish version.")
            return {"CANCELLED"}
        if version not in versions:
            self.report({"ERROR"}, f"v{version:03d} is not an existing publish folder.")
            return {"CANCELLED"}
        props.geo_usd_version_mode = "MANUAL"
        props.geo_usd_manual_version = version
        import importlib

        root = importlib.import_module(__package__)
        root.sync_geo_publish_output(props)
        vname = publish_paths.version_folder_from_number(props.publish_version)
        self.report({"INFO"}, f"Manual version: {vname}")
        return {"FINISHED"}


GEO_USD_MANUAL_VERSION_PROPERTY_GROUP_CLASSES = (GeoUsdManualVersionItem,)
GEO_USD_MANUAL_VERSION_UI_LIST_CLASSES = (MONOFX_UL_geo_manual_publish_versions,)
GEO_USD_VERSION_OPERATOR_CLASSES = (
    MONOFX_OT_set_geo_version_mode,
    MONOFX_OT_pick_geo_publish_version,
)
