"""
Cached chain-target preview for the sine-chain UI (avoids heavy draw() work).
"""

from __future__ import annotations

from typing import List, Tuple

import bpy

from . import anim_sine_chain_bpy

_PreviewState = Tuple[List[Tuple[str, bool]], str, str]
_preview_cache: _PreviewState = ([], "", "")
_preview_signature: str | None = None
_preview_timer = None


def _build_signature(context: bpy.types.Context) -> str:
    props = context.scene.monofx_pipeline_blender_props
    parts = [
        str(context.mode),
        str(props.anim_sine_bone_mode),
        str(getattr(props, "anim_sine_multi_chain", True)),
        str(getattr(props, "anim_sine_mirror_chain", True)),
        str(props.anim_sine_channel),
        str(props.anim_sine_axis),
    ]
    if context.mode == "POSE":
        arm = context.active_object
        if arm is not None and arm.type == "ARMATURE":
            parts.append(arm.name)
            parts.extend(pb.name for pb in context.selected_pose_bones)
    elif context.mode == "OBJECT":
        active = context.active_object
        parts.append(active.name if active is not None else "")
        parts.extend(obj.name for obj in context.selected_objects)
    return "|".join(parts)


def _refresh_preview() -> None:
    global _preview_timer
    _preview_timer = None
    try:
        context = bpy.context
        if context is None or context.scene is None:
            return
        signature = _build_signature(context)
        rows, err = anim_sine_chain_bpy.preview_sine_chain_rows(context)
        summary = anim_sine_chain_bpy.summarize_sine_chain_rows(rows, err)
        set_preview_cache(signature, rows, err, summary)
    except Exception:
        pass


def schedule_preview_refresh() -> None:
    global _preview_timer
    if _preview_timer is not None:
        return

    def _run() -> None:
        _refresh_preview()
        return None

    _preview_timer = _run
    try:
        bpy.app.timers.register(_run, first_interval=0.15)
    except Exception:
        _preview_timer = None


def set_preview_cache(
    signature: str,
    rows: List[Tuple[str, bool]],
    err: str,
    summary: str,
) -> None:
    global _preview_cache, _preview_signature
    _preview_signature = signature
    _preview_cache = (rows, err, summary)


def get_preview_cache(context: bpy.types.Context) -> _PreviewState:
    signature = _build_signature(context)
    if signature != _preview_signature:
        schedule_preview_refresh()
    return _preview_cache
