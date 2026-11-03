"""
Path resolution and sync helpers for anim USD cache export.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Context, PropertyGroup, UIList, UILayout

from . import publish_paths


_PUBLISH_VERSION_SCAN_CACHE: dict[str, int] = {}
_VERSION_TOGGLE_CACHE: dict[str, float | int] = {"mono": 0.0, "current": 1, "next": 1}


def scene_blend_path() -> Optional[Path]:
    import bpy

    raw = str(getattr(bpy.data, "filepath", "") or "").strip()
    if not raw:
        return None
    try:
        return Path(raw)
    except Exception:
        return None


def anim_publish_root_for_scene(scene_path: Path) -> Optional[Path]:
    return publish_paths.resolve_anim_publish_root_from_scene(scene_path)


def ensure_usd_extension(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() not in (".usd", ".usda", ".usdc", ".usdz"):
        p = p.with_suffix(".usd")
    return str(p)


def build_anim_usd_path(
    publish_root: Path,
    scene_path: Path,
    version_number: int,
) -> str:
    vname = publish_paths.version_folder_from_number(version_number)
    base = publish_paths.default_anim_geo_usd_basename(scene_path)
    return ensure_usd_extension(str(publish_root / vname / f"{base}.usd"))


def compute_auto_anim_usd_path(version_number: int) -> tuple[bool, str, str]:
    scene_path = scene_blend_path()
    if scene_path is None:
        return False, "", "Save the .blend file first."
    publish_root = anim_publish_root_for_scene(scene_path)
    if publish_root is None:
        return (
            False,
            "",
            publish_paths.ANIM_PUBLISH_PATH_HINT,
        )
    return (
        True,
        build_anim_usd_path(publish_root, scene_path, version_number),
        "",
    )


def list_anim_publish_versions() -> tuple[list[int], str]:
    """Version numbers with existing folders under ``<NN_anim>/publish``."""
    scene_path = scene_blend_path()
    if scene_path is None:
        return [], "Save the .blend file first."
    publish_root = anim_publish_root_for_scene(scene_path)
    if publish_root is None:
        return [], publish_paths.ANIM_PUBLISH_PATH_HINT
    return publish_paths.list_version_numbers(publish_root), ""


def current_anim_version_from_scene(*, use_cache: bool = True) -> int:
    """Latest existing publish folder (same list as Manual), or ``1`` if none."""
    scene_path = scene_blend_path()
    if scene_path is None:
        return 1
    cache_key = f"current|{scene_path}"
    if use_cache:
        cached = _PUBLISH_VERSION_SCAN_CACHE.get(cache_key)
        if cached is not None:
            return int(cached)
    versions, _ = list_anim_publish_versions()
    version = versions[-1] if versions else 1
    if use_cache:
        _PUBLISH_VERSION_SCAN_CACHE[cache_key] = version
    return version


def next_anim_version_from_scene(*, use_cache: bool = True) -> int:
    """Next publish folder after the latest Manual list entry (or ``1`` if empty)."""
    scene_path = scene_blend_path()
    if scene_path is None:
        return 1
    cache_key = f"next|{scene_path}"
    if use_cache:
        cached = _PUBLISH_VERSION_SCAN_CACHE.get(cache_key)
        if cached is not None:
            return int(cached)
    versions, _ = list_anim_publish_versions()
    if versions:
        version = min(versions[-1] + 1, 999)
    else:
        version = 1
    if use_cache:
        _PUBLISH_VERSION_SCAN_CACHE[cache_key] = version
    return version


def auto_next_anim_version(*, use_cache: bool = True) -> int:
    return next_anim_version_from_scene(use_cache=use_cache)


def invalidate_publish_version_cache() -> None:
    _PUBLISH_VERSION_SCAN_CACHE.clear()
    _VERSION_TOGGLE_CACHE["mono"] = 0.0


def cached_version_toggle_numbers(*, max_age_s: float = 2.0) -> tuple[int, int]:
    """Throttle disk scans used by version toggle labels during panel draw."""
    import time

    now = time.monotonic()
    if now - float(_VERSION_TOGGLE_CACHE["mono"]) < max_age_s:
        return (
            int(_VERSION_TOGGLE_CACHE["current"]),
            int(_VERSION_TOGGLE_CACHE["next"]),
        )
    current_v = current_anim_version_from_scene(use_cache=True)
    next_v = next_anim_version_from_scene(use_cache=True)
    _VERSION_TOGGLE_CACHE["mono"] = now
    _VERSION_TOGGLE_CACHE["current"] = current_v
    _VERSION_TOGGLE_CACHE["next"] = next_v
    return current_v, next_v


def resolve_anim_publish_version_number(props) -> int:
    mode = str(getattr(props, "anim_usd_version_mode", "NEXT") or "NEXT")
    if mode == "MANUAL":
        manual = max(1, min(999, int(getattr(props, "anim_usd_manual_version", 1) or 1)))
        versions, _ = list_anim_publish_versions()
        if not versions:
            return 1
        if manual in versions:
            return manual
        return versions[-1]
    if mode == "CURRENT":
        return current_anim_version_from_scene()
    return next_anim_version_from_scene()


def sync_anim_publish_output(props) -> None:
    """Apply version mode to ``anim_usd_publish_version`` and output filepath."""
    from . import anim_usd_cache_ui as anim_ui

    invalidate_publish_version_cache()
    version = resolve_anim_publish_version_number(props)
    anim_ui._SYNCING_ANIM_USD_VERSION = True
    try:
        props.anim_usd_publish_version = version
    finally:
        anim_ui._SYNCING_ANIM_USD_VERSION = False
    ok, path, _ = compute_auto_anim_usd_path(version)
    if ok and path:
        anim_ui._SYNCING_ANIM_USD_FILEPATH = True
        try:
            props.anim_usd_output_filepath = path
        finally:
            anim_ui._SYNCING_ANIM_USD_FILEPATH = False


def describe_anim_publish_target(props) -> tuple[bool, str, str, str]:
    scene_path = scene_blend_path()
    if scene_path is None:
        return False, "", "", "Save the .blend file first."
    publish_root = anim_publish_root_for_scene(scene_path)
    if publish_root is None:
        return (
            False,
            "",
            "",
            publish_paths.ANIM_PUBLISH_PATH_HINT,
        )
    shot = publish_paths.detect_shot_from_scene_path(scene_path)
    parts = list(scene_path.parts)
    i_anim = publish_paths.find_anim_task_index(parts)
    if shot:
        context_label = shot
    elif i_anim is not None and i_anim > 0:
        context_label = parts[i_anim - 1]
    else:
        context_label = "?"
    version = resolve_anim_publish_version_number(props)
    vname = publish_paths.version_folder_from_number(version)
    usd_path = Path(build_anim_usd_path(publish_root, scene_path, version))
    mode = str(getattr(props, "anim_usd_version_mode", "NEXT") or "NEXT").casefold()
    summary = f"Will export {vname} · {context_label} · {mode}"
    rel = publish_paths.relative_anim_publish_display(scene_path, usd_path)
    return True, summary, rel, ""


def normalize_path(path: str) -> str:
    p = str(path or "").strip()
    if not p:
        return ""
    return os.path.normcase(os.path.normpath(p))


def paths_equal(a: str, b: str) -> bool:
    return normalize_path(a) == normalize_path(b)


def resolve_output_path(props) -> tuple[bool, str, str]:
    return compute_auto_anim_usd_path(resolve_anim_publish_version_number(props))


def resolve_anim_publish_folder(props) -> tuple[bool, Path, str]:
    """Publish version folder for the resolved anim USD output."""
    ok, filepath, err = resolve_output_path(props)
    if not ok:
        return False, Path(), err
    return True, Path(filepath).parent, ""


def sync_auto_anim_output(props) -> None:
    """Keep NEXT mode aligned with the latest publish folder scan."""
    if str(getattr(props, "anim_usd_version_mode", "NEXT") or "NEXT") != "NEXT":
        return
    sync_anim_publish_output(props)


def plan_anim_export_output_paths(context, props) -> list[Path]:
    """Absolute paths that enabled anim USD export targets will write."""
    from . import anim_usd_cache_asset_list as asset_list
    from .anim_usd_export_planner import resolve_export_output_dir

    paths: list[Path] = []
    jobs, _ = asset_list.plan_enabled_geo_export_jobs(context, props)
    for job in jobs:
        paths.append(Path(job.filepath))

    ok_dir, out_dir, _ = resolve_export_output_dir(props)
    if ok_dir:
        cam_path = asset_list.resolve_camera_output_filepath(context, props)
        if cam_path is not None:
            paths.append(cam_path)
        if paths:
            paths.append(out_dir / "publish_meta.json")

    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = normalize_path(str(path))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def existing_anim_export_paths(paths: list[Path]) -> list[Path]:
    """Subset of ``paths`` that already exist on disk."""
    from .anim_usd_cache_paths import existing_output_paths

    return existing_output_paths(paths)


def populate_manual_version_pick_list(
    props,
    versions: list[int],
    *,
    select_version: int | None = None,
) -> None:
    """Fill the manual publish-version picker list and set the active row."""
    items = props.anim_usd_manual_version_items
    items.clear()
    for version in versions:
        item = items.add()
        item.version_num = int(version)
        item.label = f"v{version:03d}"
    if select_version is not None and select_version in versions:
        pick_index = versions.index(select_version)
    else:
        pick_index = max(0, len(versions) - 1)
    props.anim_usd_manual_version_pick_index = pick_index


def picked_manual_version_number(props) -> int | None:
    items = props.anim_usd_manual_version_items
    index = int(getattr(props, "anim_usd_manual_version_pick_index", 0) or 0)
    if index < 0 or index >= len(items):
        return None
    return int(items[index].version_num)


class AnimUsdManualVersionItem(PropertyGroup):
    version_num: IntProperty(name="Version", min=1, max=999, default=1)
    label: StringProperty(name="Label", default="")


class MONOFX_UL_anim_manual_publish_versions(UIList):
    bl_idname = "MONOFX_UL_anim_manual_publish_versions"

    def draw_item(
        self,
        context: Context,
        layout: UILayout,
        data,
        item: AnimUsdManualVersionItem,
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


ANIM_USD_MANUAL_VERSION_PROPERTY_GROUP_CLASSES = (AnimUsdManualVersionItem,)
ANIM_USD_MANUAL_VERSION_UI_LIST_CLASSES = (MONOFX_UL_anim_manual_publish_versions,)
