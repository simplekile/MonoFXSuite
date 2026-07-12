"""
Edit exact keyframe values in Graph / Dope Sheet without moving the playhead.
"""

from __future__ import annotations

from typing import Iterator, List, Optional, Tuple

import bpy
from bpy.types import Context, Operator

from monofx_pipeline_common.anim_exact_key import (
    apply_keyframe_frame_delta,
    apply_keyframe_value_delta,
    fcurve_channel_label,
)

KeyframeTarget = Tuple[bpy.types.FCurve, int, bpy.types.Keyframe]
CachedKeyframeRef = Tuple[str, str, int, float]

_EXACT_KEY_EDITOR_TYPES = frozenset(
    {"GRAPH_EDITOR", "DOPESHEET_EDITOR", "TIMELINE"}
)

_FRAME_MATCH_EPSILON = 1e-4

_multi_keyframe_cache: List[CachedKeyframeRef] = []


def _iter_editable_fcurves(context: Context) -> Iterator[bpy.types.FCurve]:
    for attr in (
        "selected_editable_fcurves",
        "selected_visible_fcurves",
        "visible_fcurves",
    ):
        fcurves = getattr(context, attr, None)
        if fcurves:
            yield from fcurves
            return


def iter_selected_keyframe_targets(context: Context) -> List[KeyframeTarget]:
    """Selected control points in the active animation editor."""
    selected = getattr(context, "selected_editable_keyframes", None)
    if selected:
        out: List[KeyframeTarget] = []
        for item in selected:
            fcu = getattr(item, "fcurve", None)
            index = getattr(item, "keyframe_index", None)
            if fcu is None or index is None:
                continue
            try:
                kp = fcu.keyframe_points[int(index)]
            except (AttributeError, IndexError, TypeError, ValueError):
                continue
            out.append((fcu, int(index), kp))
        if out:
            return out

    out = []
    for fcu in _iter_editable_fcurves(context):
        for index, kp in enumerate(fcu.keyframe_points):
            if kp.select_control_point:
                out.append((fcu, index, kp))
    return out


def _target_cache_ref(target: KeyframeTarget) -> CachedKeyframeRef:
    fcu, _index, kp = target
    id_data = fcu.id_data
    return (
        str(id_data.name),
        str(fcu.data_path),
        int(fcu.array_index),
        float(kp.co[0]),
    )


def _refresh_multi_keyframe_cache(context: Context) -> None:
    global _multi_keyframe_cache
    area = context.area
    if area is None or area.type not in _EXACT_KEY_EDITOR_TYPES:
        return
    targets = iter_selected_keyframe_targets(context)
    if len(targets) >= 2:
        _multi_keyframe_cache = [_target_cache_ref(target) for target in targets]


def _id_data_by_name(name: str) -> Optional[bpy.types.ID]:
    block = bpy.data.objects.get(name)
    if block is not None:
        return block
    for collection in (
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.armatures,
    ):
        block = collection.get(name)
        if block is not None:
            return block
    return None


def _find_fcurve_on_id_data(
    id_data: bpy.types.ID,
    data_path: str,
    array_index: int,
) -> Optional[bpy.types.FCurve]:
    from . import anim_keys_bpy

    anim = getattr(id_data, "animation_data", None)
    if anim is None:
        return None

    action = getattr(anim, "action", None)
    legacy = getattr(action, "fcurves", None) if action is not None else None
    if legacy is not None:
        return legacy.find(data_path, index=array_index)

    for fcu, _container in anim_keys_bpy._iter_anim_data_fcurve_pairs(anim):
        if fcu.data_path == data_path and int(fcu.array_index) == int(array_index):
            return fcu
    return None


def _resolve_keyframe_ref(ref: CachedKeyframeRef) -> Optional[KeyframeTarget]:
    id_name, data_path, array_index, frame = ref
    id_data = _id_data_by_name(id_name)
    if id_data is None:
        return None

    fcu = _find_fcurve_on_id_data(id_data, data_path, array_index)
    if fcu is None:
        return None

    best_index: Optional[int] = None
    best_dist = _FRAME_MATCH_EPSILON
    for index, kp in enumerate(fcu.keyframe_points):
        dist = abs(float(kp.co[0]) - float(frame))
        if dist < best_dist:
            best_dist = dist
            best_index = index

    if best_index is None:
        return None
    return fcu, best_index, fcu.keyframe_points[best_index]


def resolve_cached_keyframe_targets() -> List[KeyframeTarget]:
    out: List[KeyframeTarget] = []
    for ref in _multi_keyframe_cache:
        target = _resolve_keyframe_ref(ref)
        if target is not None:
            out.append(target)
    return out


def _distance_sq(ax: float, ay: float, bx: float, by: float) -> float:
    dx = float(ax) - float(bx)
    dy = float(ay) - float(by)
    return dx * dx + dy * dy


def pick_keyframe_near_mouse(
    context: Context,
    event,
    *,
    max_distance_px: float = 14.0,
    select_result: bool = True,
) -> List[KeyframeTarget]:
    """Find the nearest keyframe control point to the mouse in region space."""
    region = context.region
    if region is None or getattr(region, "type", "") != "WINDOW":
        return []

    view2d = region.view2d
    mouse_x = float(event.mouse_region_x)
    mouse_y = float(event.mouse_region_y)
    max_dist_sq = float(max_distance_px) ** 2

    best: Optional[KeyframeTarget] = None
    best_dist = max_dist_sq

    for fcu in _iter_editable_fcurves(context):
        for index, kp in enumerate(fcu.keyframe_points):
            kx, ky = view2d.view_to_region(float(kp.co[0]), float(kp.co[1]))
            dist = _distance_sq(mouse_x, mouse_y, kx, ky)
            if dist <= best_dist:
                best_dist = dist
                best = (fcu, index, kp)

    if best is None:
        return []

    if select_result:
        _select_single_keyframe_target(context, best)
    return [best]


def _select_single_keyframe_target(context: Context, target: KeyframeTarget) -> None:
    fcu, _index, kp = target
    for editable in _iter_editable_fcurves(context):
        editable.select = editable == fcu
        for point in editable.keyframe_points:
            point.select_control_point = False
            point.select_left_handle = False
            point.select_right_handle = False

    fcu.select = True
    kp.select_control_point = True


def _resolve_invoke_targets(context: Context, event) -> List[KeyframeTarget]:
    """Single-key vs multi-key invoke paths."""
    if bool(getattr(event, "shift", False)):
        cached = resolve_cached_keyframe_targets()
        if len(cached) >= 2:
            return cached
        current = iter_selected_keyframe_targets(context)
        if len(current) >= 2:
            return current
        return []

    current = iter_selected_keyframe_targets(context)
    if len(current) == 1:
        return current
    if len(current) > 1:
        picked = pick_keyframe_near_mouse(context, event, select_result=False)
        if picked:
            _select_single_keyframe_target(context, picked[0])
            return picked
    return pick_keyframe_near_mouse(context, event)


def label_for_fcurve(fcu: bpy.types.FCurve) -> str:
    return fcurve_channel_label(fcu.data_path, int(fcu.array_index))


def _set_keyframe_value(kp: bpy.types.Keyframe, new_value: float) -> None:
    old_value = float(kp.co[1])
    value, hl_y, hr_y = apply_keyframe_value_delta(
        old_value,
        float(new_value),
        float(kp.handle_left[1]),
        float(kp.handle_right[1]),
    )
    kp.co[1] = value
    kp.handle_left[1] = hl_y
    kp.handle_right[1] = hr_y


def _set_keyframe_frame(kp: bpy.types.Keyframe, new_frame: float) -> None:
    old_frame = float(kp.co[0])
    frame, hl_x, hr_x = apply_keyframe_frame_delta(
        old_frame,
        float(new_frame),
        float(kp.handle_left[0]),
        float(kp.handle_right[0]),
    )
    kp.co[0] = frame
    kp.handle_left[0] = hl_x
    kp.handle_right[0] = hr_x


def apply_exact_keyframe_edit(
    targets: List[KeyframeTarget],
    *,
    frame: float,
    value: float,
    edit_frame: bool,
) -> int:
    """Apply frame/value edits and refresh affected F-Curves. Returns count edited."""
    touched_fcurves: set[int] = set()
    edited = 0

    for fcu, _index, kp in targets:
        if edit_frame:
            _set_keyframe_frame(kp, frame)
        _set_keyframe_value(kp, value)
        touched_fcurves.add(id(fcu))
        edited += 1

    for fcu_id in touched_fcurves:
        for fcu, _index, _kp in targets:
            if id(fcu) == fcu_id:
                try:
                    fcu.update()
                except Exception:
                    pass
                break

    return edited


class MONOFX_OT_anim_edit_exact_key(Operator):
    bl_idname = "wm.mono_fx_anim_edit_exact_key"
    bl_label = "Edit Exact Keyframe"
    bl_description = (
        "Type the exact frame and value for the selected keyframe without moving "
        "the playhead. Double-click one key to edit it; Shift+double-click to edit "
        "all keys from the previous multi-selection."
    )
    bl_options = {"REGISTER", "UNDO"}

    frame: bpy.props.FloatProperty(
        name="Frame",
        description="Keyframe frame",
        default=1.0,
        precision=3,
    )
    value: bpy.props.FloatProperty(
        name="Value",
        description="Keyframe value",
        default=0.0,
        precision=6,
    )
    channel: bpy.props.StringProperty(
        name="Channel",
        default="",
        options={"HIDDEN"},
    )
    multi_count: bpy.props.IntProperty(
        name="Selection Count",
        default=0,
        min=0,
        options={"HIDDEN"},
    )

    edit_multi: bpy.props.BoolProperty(
        name="Edit Multiple",
        default=False,
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context: Context) -> bool:
        _refresh_multi_keyframe_cache(context)
        if iter_selected_keyframe_targets(context):
            return True
        if len(_multi_keyframe_cache) >= 2:
            return True
        area = context.area
        return area is not None and area.type in _EXACT_KEY_EDITOR_TYPES

    def invoke(self, context: Context, event) -> set[str]:
        has_mouse = getattr(event, "mouse_region_x", None) is not None
        if has_mouse and bool(getattr(event, "shift", False)):
            targets = _resolve_invoke_targets(context, event)
            self.edit_multi = True
        elif has_mouse:
            targets = _resolve_invoke_targets(context, event)
            self.edit_multi = False
        else:
            targets = iter_selected_keyframe_targets(context)
            self.edit_multi = len(targets) > 1

        if self.edit_multi and len(targets) < 2:
            self.report(
                {"WARNING"},
                "Shift+double-click needs at least two keyframes in the cached selection.",
            )
            return {"CANCELLED"}
        if not targets:
            self.report({"WARNING"}, "No keyframe under the cursor or in the selection.")
            return {"CANCELLED"}

        self._edit_targets = targets
        self.multi_count = len(targets)
        fcu, _index, kp = targets[0]
        self.frame = float(kp.co[0])
        self.value = float(kp.co[1])
        self.channel = label_for_fcurve(fcu)
        if self.multi_count > 1:
            self.channel = f"{self.channel} (+{self.multi_count - 1} more)"

        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context: Context) -> None:
        layout = self.layout
        if self.channel:
            layout.label(text=self.channel, icon="GRAPH")
        row = layout.row(align=True)
        frame_row = row.row(align=True)
        frame_row.enabled = self.multi_count <= 1
        frame_row.prop(self, "frame")
        row.prop(self, "value")
        if self.multi_count > 1:
            layout.label(
                text=f"Value applies to all {self.multi_count} selected keys; "
                "frame edits require a single selection.",
                icon="INFO",
            )
            if self.edit_multi:
                layout.label(
                    text="Shift+double-click keeps the previous multi-selection.",
                    icon="NONE",
                )

    def execute(self, context: Context) -> set[str]:
        targets = getattr(self, "_edit_targets", None) or iter_selected_keyframe_targets(context)
        if not targets:
            self.report({"WARNING"}, "No keyframe selected.")
            return {"CANCELLED"}

        edit_frame = self.multi_count <= 1
        edited = apply_exact_keyframe_edit(
            targets,
            frame=self.frame,
            value=self.value,
            edit_frame=edit_frame,
        )
        if edited <= 0:
            self.report({"WARNING"}, "No keyframes were updated.")
            return {"CANCELLED"}

        if edited == 1:
            self.report({"INFO"}, f"Keyframe set to frame {self.frame:g}, value {self.value:g}")
        else:
            self.report({"INFO"}, f"Updated value on {edited} keyframes.")
        return {"FINISHED"}


EXACT_KEY_OPERATOR_CLASSES = (MONOFX_OT_anim_edit_exact_key,)
