"""
Path resolution and sync helpers for anim USD cache export.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from . import publish_paths


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
            "Save .blend under 02_shots/<shot>/01_anim/... to resolve publish path.",
        )
    return (
        True,
        build_anim_usd_path(publish_root, scene_path, version_number),
        "",
    )


def auto_next_anim_version() -> int:
    scene_path = scene_blend_path()
    if scene_path is None:
        return 1
    publish_root = anim_publish_root_for_scene(scene_path)
    if publish_root is None:
        return 1
    return publish_paths.auto_next_version_number(publish_root)


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
            "Save .blend under 02_shots/<shot>/01_anim/...",
        )
    shot = publish_paths.detect_shot_from_scene_path(scene_path) or "?"
    vname = publish_paths.version_folder_from_number(props.anim_usd_publish_version)
    usd_path = Path(
        build_anim_usd_path(publish_root, scene_path, props.anim_usd_publish_version)
    )
    preset_tag = "auto" if props.anim_usd_output_preset == "auto" else "custom"
    summary = f"Will export {vname} · {shot} · {preset_tag}"
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
    if props.anim_usd_output_preset == "custom":
        raw = str(props.anim_usd_output_filepath or "").strip()
        if not raw:
            return False, "", "Output USD file path is empty."
        return True, ensure_usd_extension(raw), ""
    return compute_auto_anim_usd_path(props.anim_usd_publish_version)


def resolve_anim_publish_folder(props) -> tuple[bool, Path, str]:
    """Version folder for auto preset, or output file parent for custom."""
    ok, filepath, err = resolve_output_path(props)
    if not ok:
        return False, Path(), err
    return True, Path(filepath).parent, ""


def sync_auto_anim_output(props) -> None:
    if props.anim_usd_output_preset != "auto":
        return
    scene_path = scene_blend_path()
    publish_root = anim_publish_root_for_scene(scene_path) if scene_path else None
    if scene_path is None or publish_root is None:
        return
    from . import anim_usd_cache_ui as anim_ui

    anim_ui._SYNCING_ANIM_USD_VERSION = True
    try:
        props.anim_usd_publish_version = auto_next_anim_version()
    finally:
        anim_ui._SYNCING_ANIM_USD_VERSION = False
    ok, path, _ = compute_auto_anim_usd_path(props.anim_usd_publish_version)
    if ok and path:
        anim_ui._SYNCING_ANIM_USD_FILEPATH = True
        try:
            props.anim_usd_output_filepath = path
        finally:
            anim_ui._SYNCING_ANIM_USD_FILEPATH = False
