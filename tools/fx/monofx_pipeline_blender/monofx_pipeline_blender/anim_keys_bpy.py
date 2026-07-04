"""
Keyframe selection and cleanup (bpy).

Compatible with Blender 4.x (legacy ``action.fcurves``) and 5.x (slotted actions).
"""

from __future__ import annotations

from typing import Iterable, Iterator, List, Set, Tuple

import bpy

from .pipeline_common.anim_keys import should_remove_fcurve

def _legacy_action_fcurves(action: bpy.types.Action):
    return getattr(action, "fcurves", None)


def _iter_action_fcurve_pairs(action: bpy.types.Action) -> Iterator[Tuple[bpy.types.FCurve, object]]:
    """Yield ``(fcurve, fcurves_container)`` for every F-Curve in *action*."""
    if action is None:
        return

    legacy = _legacy_action_fcurves(action)
    if legacy is not None:
        for fcu in list(legacy):
            yield fcu, legacy
        return

    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            channelbag_fn = getattr(strip, "channelbag", None)
            if channelbag_fn is None:
                continue
            for slot in getattr(action, "slots", ()):
                try:
                    channelbag = channelbag_fn(slot)
                except (AttributeError, RuntimeError, TypeError):
                    channelbag = None
                if channelbag is None:
                    continue
                fcurves = getattr(channelbag, "fcurves", None)
                if fcurves is None:
                    continue
                for fcu in list(fcurves):
                    yield fcu, fcurves


def _iter_anim_data_fcurve_pairs(
    anim_data: bpy.types.AnimData,
) -> Iterator[Tuple[bpy.types.FCurve, object]]:
    """F-Curves in *anim_data*'s assigned action (object slot when available)."""
    if anim_data is None or anim_data.action is None:
        return

    action = anim_data.action
    legacy = _legacy_action_fcurves(action)
    if legacy is not None:
        for fcu in list(legacy):
            yield fcu, legacy
        return

    slot = getattr(anim_data, "action_slot", None)
    if slot is not None:
        try:
            from bpy_extras import anim_utils

            channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
            if channelbag is not None:
                fcurves = getattr(channelbag, "fcurves", None)
                if fcurves is not None:
                    for fcu in list(fcurves):
                        yield fcu, fcurves
                    return
        except (ImportError, AttributeError, RuntimeError, TypeError):
            pass

    yield from _iter_action_fcurve_pairs(action)


def _iter_object_fcurve_pairs(obj: bpy.types.Object) -> Iterator[Tuple[bpy.types.FCurve, object]]:
    """F-Curves driving *obj* (assigned action slot when available)."""
    anim = obj.animation_data
    if anim is None:
        return
    yield from _iter_anim_data_fcurve_pairs(anim)


def _keyframe_anim_owners(obj: bpy.types.Object) -> List[bpy.types.ID]:
    """Object plus data-block owners that may hold rig keys (e.g. camera lens on Camera data)."""
    owners: List[bpy.types.ID] = [obj]
    if obj.type == "CAMERA" and obj.data is not None:
        owners.append(obj.data)
    return owners


def _fcurve_has_keys(fcu: bpy.types.FCurve) -> bool:
    try:
        return bool(fcu.keyframe_points) and len(fcu.keyframe_points) > 0
    except Exception:
        return False


def _action_has_keyed_fcurves(action: bpy.types.Action) -> bool:
    if action is None:
        return False
    for fcu, _ in _iter_action_fcurve_pairs(action):
        if _fcurve_has_keys(fcu):
            return True
    return False


def _nla_has_keyed_strips(anim_data: bpy.types.AnimData) -> bool:
    if anim_data is None or anim_data.nla_tracks is None:
        return False
    for track in anim_data.nla_tracks:
        for strip in track.strips:
            if strip.action is not None and _action_has_keyed_fcurves(strip.action):
                return True
    return False


def object_has_keyframes(obj: bpy.types.Object) -> bool:
    anim = obj.animation_data
    if anim is None:
        return False
    for fcu, _ in _iter_object_fcurve_pairs(obj):
        if _fcurve_has_keys(fcu):
            return True
    if _nla_has_keyed_strips(anim):
        return True
    return False


def iter_scene_keyed_objects() -> List[bpy.types.Object]:
    out: List[bpy.types.Object] = []
    for obj in bpy.data.objects:
        if object_has_keyframes(obj):
            out.append(obj)
    return out


def _fcurve_y_values(fcu: bpy.types.FCurve) -> List[float]:
    return [float(kp.co[1]) for kp in fcu.keyframe_points]


def _iter_removable_fcurves_on_object(
    obj: bpy.types.Object,
    *,
    clean_single: bool,
    clean_static: bool,
) -> List[Tuple[bpy.types.FCurve, object]]:
    removable: List[Tuple[bpy.types.FCurve, object]] = []
    for fcu, container in _iter_object_fcurve_pairs(obj):
        n = len(fcu.keyframe_points)
        values = _fcurve_y_values(fcu)
        if should_remove_fcurve(
            n,
            values,
            clean_single=clean_single,
            clean_static=clean_static,
        ):
            removable.append((fcu, container))
    return removable


def _object_has_any_fcurves(obj: bpy.types.Object) -> bool:
    for _fcu, _container in _iter_object_fcurve_pairs(obj):
        return True
    return False


def _clear_action_fcurves(anim_data: bpy.types.AnimData) -> int:
    """Remove every keyed fcurve from *anim_data*'s action; returns removed count."""
    if anim_data is None or anim_data.action is None:
        return 0

    removed = 0
    for fcu, container in list(_iter_anim_data_fcurve_pairs(anim_data)):
        if not _fcurve_has_keys(fcu):
            continue
        try:
            container.remove(fcu)
            removed += 1
        except Exception:
            pass

    if (
        anim_data.action is not None
        and not _anim_data_has_any_fcurves(anim_data)
        and not _nla_has_keyed_strips(anim_data)
    ):
        try:
            anim_data.action = None
        except Exception:
            pass

    return removed


def _anim_data_has_any_fcurves(anim_data: bpy.types.AnimData) -> bool:
    for _fcu, _container in _iter_anim_data_fcurve_pairs(anim_data):
        return True
    return False


def clear_all_keys_on_objects(objects: Iterable[bpy.types.Object]) -> Tuple[int, int]:
    """
    Remove all keyed fcurves on the given objects (and camera data blocks).
    Shared actions are processed once. Returns ``(removed_fcurves, affected_objects)``.
    """
    removed = 0
    affected: Set[str] = set()
    processed_actions: Set[int] = set()

    for obj in objects:
        obj_removed = 0
        for owner in _keyframe_anim_owners(obj):
            anim = getattr(owner, "animation_data", None)
            if anim is None or anim.action is None:
                continue
            action_id = id(anim.action)
            if action_id in processed_actions:
                continue
            processed_actions.add(action_id)
            count = _clear_action_fcurves(anim)
            if count:
                obj_removed += count

        if obj_removed:
            removed += obj_removed
            affected.add(obj.name)

    return removed, len(affected)


def clean_static_keys_on_objects(
    objects: Iterable[bpy.types.Object],
    *,
    clean_single: bool = True,
    clean_static: bool = True,
) -> Tuple[int, int]:
    """
    Remove static / single-key fcurves on the given objects' actions.
    Returns ``(removed_fcurves, affected_objects)``.
    """
    removed = 0
    affected: Set[str] = set()

    for obj in objects:
        anim = obj.animation_data
        if anim is None or anim.action is None:
            continue

        to_remove = _iter_removable_fcurves_on_object(
            obj,
            clean_single=clean_single,
            clean_static=clean_static,
        )
        if not to_remove:
            continue

        for fcu, container in to_remove:
            try:
                container.remove(fcu)
                removed += 1
            except Exception:
                pass

        if to_remove:
            affected.add(obj.name)

        if (
            anim.action is not None
            and not _object_has_any_fcurves(obj)
            and not _nla_has_keyed_strips(anim)
        ):
            try:
                anim.action = None
            except Exception:
                pass

    return removed, len(affected)
