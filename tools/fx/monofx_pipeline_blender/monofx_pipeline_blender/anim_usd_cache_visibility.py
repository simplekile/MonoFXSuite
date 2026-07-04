"""
View-layer visibility checks for Anim USD export.
"""

from __future__ import annotations

from typing import Optional, Sequence

import bpy


def export_respects_view_visibility(context: Optional[bpy.types.Context]) -> bool:
    """Read scene property — when True, skip excluded/hidden export targets."""
    if context is None:
        return False
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    props = getattr(scene, "monofx_pipeline_blender_props", None)
    if props is None:
        return False
    return bool(getattr(props, "anim_usd_skip_view_hidden", False))


def resolve_export_visibility(
    context: Optional[bpy.types.Context] = None,
    *,
    view_layer: Optional[bpy.types.ViewLayer] = None,
    respect_visibility: Optional[bool] = None,
) -> tuple[Optional[bpy.types.ViewLayer], bool]:
    if respect_visibility is None:
        respect_visibility = export_respects_view_visibility(context)
    if view_layer is None and context is not None:
        view_layer = context.view_layer
    return view_layer, bool(respect_visibility)


def object_visible_for_export(
    obj: bpy.types.Object,
    view_layer: Optional[bpy.types.ViewLayer],
    *,
    respect_visibility: bool,
) -> bool:
    """False when excluded from the view layer or hidden for viewport/render."""
    if not respect_visibility or obj is None:
        return True
    if view_layer is None:
        return True
    try:
        if obj.name not in view_layer.objects:
            return False
    except Exception:
        return False
    try:
        if not obj.visible_get(viewport=True, view_layer=view_layer):
            return False
        if not obj.visible_get(viewport=False, view_layer=view_layer):
            return False
    except Exception:
        if getattr(obj, "hide_viewport", False) or getattr(obj, "hide_render", False):
            return False
    return True


def filter_objects_for_export(
    objects: Sequence[bpy.types.Object],
    view_layer: Optional[bpy.types.ViewLayer],
    *,
    respect_visibility: bool,
) -> list[bpy.types.Object]:
    if not respect_visibility:
        return list(objects)
    return [
        obj
        for obj in objects
        if object_visible_for_export(obj, view_layer, respect_visibility=True)
    ]


def filter_object_names_for_export(
    names: Sequence[str],
    view_layer: Optional[bpy.types.ViewLayer],
    *,
    respect_visibility: bool,
) -> tuple[str, ...]:
    if not respect_visibility:
        return tuple(names)
    kept: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        if not object_visible_for_export(obj, view_layer, respect_visibility=True):
            continue
        seen.add(name)
        kept.append(name)
    return tuple(kept)
