"""
Blender sine-chain drivers on pose bones or object hierarchies.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Sequence, Tuple

import bpy

from monofx_pipeline_common.anim_chains import (
    chain_members_from_bone,
    chain_members_from_hierarchy,
    chain_members_from_hierarchy_branch,
    multi_chain_seeds_from_selection,
    partition_selection_chains,
    sort_chain_selection,
)
from monofx_pipeline_common.anim_sine_chain import (
    SINE_BASE_PROP,
    SINE_RAMP_PROP,
    SINE_RAMP_MODE_PROP,
    SINE_RNA_PROP,
    build_sine_driver_expression,
    channel_data_path,
    decode_sine_rna,
    encode_sine_rna,
    resolve_sine_axis_settings,
    scene_sine_curve_amp_prop_paths,
    scene_sine_root_tip_prop_paths,
    scene_sine_wave_prop_paths,
    sine_axis_key,
)
from . import anim_sine_ramp_bpy


_EULER_ROTATION_MODES = frozenset({"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"})


@dataclass(frozen=True)
class SineChainTarget:
    id_block: bpy.types.ID
    label: str
    base_data_path: str


def _bone_hierarchy_maps(
    arm: bpy.types.Object,
) -> tuple[dict[str, str | None], dict[str, list[str]]]:
    parent_of: dict[str, str | None] = {}
    children_of: dict[str, list[str]] = {}
    for pb in arm.pose.bones:
        parent_of[pb.name] = pb.parent.name if pb.parent else None
        children_of.setdefault(pb.name, [])
    for pb in arm.pose.bones:
        if pb.parent is not None:
            children_of.setdefault(pb.parent.name, []).append(pb.name)
    return parent_of, children_of


def resolve_bone_chain_members(
    arm: bpy.types.Object,
    seed: str,
    *,
    bone_mode: str = "AUTO",
    selected_names: Sequence[str] | None = None,
) -> List[str]:
    all_names = [pb.name for pb in arm.pose.bones]
    parent_of, children_of = _bone_hierarchy_maps(arm)
    mode = (bone_mode or "AUTO").upper()

    if mode == "SELECTION":
        names = list(selected_names or [])
        if not names:
            return []
        return sort_chain_selection(names, parent_of, children_of)

    if mode == "NAMING":
        return chain_members_from_bone(seed, all_names)

    named = chain_members_from_bone(seed, all_names)
    if len(named) > 1:
        return named

    if mode == "HIERARCHY":
        return chain_members_from_hierarchy_branch(seed, parent_of, children_of)

    branch = chain_members_from_hierarchy_branch(seed, parent_of, children_of)
    if len(branch) > 1:
        return branch

    return chain_members_from_hierarchy(seed, parent_of, children_of)


def _object_linear_tail_depth(obj: bpy.types.Object) -> int:
    depth = 0
    cur = obj
    while len(cur.children) == 1:
        cur = cur.children[0]
        depth += 1
    return depth


def _object_chain_maps_local(
    seed_obj: bpy.types.Object,
) -> tuple[dict[str, str | None], dict[str, list[str]]]:
    """Build hierarchy maps for only the object chain through *seed_obj*."""
    parent_of: dict[str, str | None] = {}
    children_of: dict[str, list[str]] = {}

    ancestors: list[bpy.types.Object] = []
    cur = seed_obj.parent
    while cur is not None:
        ancestors.insert(0, cur)
        parent_of[cur.name] = cur.parent.name if cur.parent else None
        cur = cur.parent

    parent_of[seed_obj.name] = seed_obj.parent.name if seed_obj.parent else None

    for obj in ancestors + [seed_obj]:
        children_of[obj.name] = [child.name for child in obj.children]

    tail = seed_obj
    while tail.children:
        kids = list(tail.children)
        nxt = kids[0] if len(kids) == 1 else max(kids, key=_object_linear_tail_depth)
        parent_of[nxt.name] = tail.name
        children_of.setdefault(tail.name, [child.name for child in tail.children])
        children_of[nxt.name] = [child.name for child in nxt.children]
        tail = nxt

    return parent_of, children_of


def resolve_object_chain_members_branch(seed_obj: bpy.types.Object) -> List[str]:
    parent_of, children_of = _object_chain_maps_local(seed_obj)
    return chain_members_from_hierarchy_branch(seed_obj.name, parent_of, children_of)


def resolve_object_chain_members(seed_obj: bpy.types.Object) -> List[str]:
    parent_of, children_of = _object_chain_maps_local(seed_obj)
    return chain_members_from_hierarchy(seed_obj.name, parent_of, children_of)


def _selected_object_chain_members(context: bpy.types.Context) -> List[str]:
    selected = [obj for obj in context.selected_objects if obj is not None]
    if not selected:
        return []
    names = [obj.name for obj in selected]
    names_set = set(names)
    parent_of = {
        obj.name: obj.parent.name if obj.parent is not None and obj.parent.name in names_set else None
        for obj in selected
    }
    children_of: dict[str, list[str]] = {name: [] for name in names}
    for obj in selected:
        if obj.parent is not None and obj.parent.name in names_set:
            children_of.setdefault(obj.parent.name, []).append(obj.name)
    return sort_chain_selection(names, parent_of, children_of)


def _targets_from_member_names(
    arm: bpy.types.Object,
    members: Sequence[str],
) -> List[SineChainTarget]:
    return [
        SineChainTarget(
            id_block=arm,
            label=f"{arm.name}/{name}",
            base_data_path=f'pose.bones["{name}"]',
        )
        for name in members
    ]


def _targets_from_object_names(members: Sequence[str]) -> List[SineChainTarget]:
    return [
        SineChainTarget(
            id_block=bpy.data.objects.get(name),
            label=name,
            base_data_path="",
        )
        for name in members
        if bpy.data.objects.get(name) is not None
    ]


def _bone_chain_name_lists(
    arm: bpy.types.Object,
    *,
    chain_mode: str,
    seed: str,
    selected_names: Sequence[str],
    multi_chain: bool,
) -> List[List[str]]:
    parent_of, children_of = _bone_hierarchy_maps(arm)
    mode = (chain_mode or "AUTO").upper()

    if mode == "SELECTION":
        names = list(selected_names)
        if not names:
            return []
        if multi_chain:
            return partition_selection_chains(names, parent_of, children_of)
        return [sort_chain_selection(names, parent_of, children_of)]

    seeds = (
        multi_chain_seeds_from_selection(selected_names, parent_of, children_of)
        if multi_chain
        else [seed]
    )
    chain_lists: List[List[str]] = []
    seen: set[tuple[str, ...]] = set()
    for chain_seed in seeds:
        members = resolve_bone_chain_members(
            arm,
            chain_seed,
            bone_mode=mode,
            selected_names=selected_names,
        )
        key = tuple(members)
        if members and key not in seen:
            seen.add(key)
            chain_lists.append(members)
    return chain_lists


def _object_chain_name_lists(
    context: bpy.types.Context,
    *,
    chain_mode: str,
    seed_obj: bpy.types.Object | None,
    multi_chain: bool,
) -> List[List[str]]:
    mode = (chain_mode or "AUTO").upper()

    if mode == "SELECTION":
        selected = [obj for obj in context.selected_objects if obj is not None]
        if not selected:
            return []
        names = [obj.name for obj in selected]
        if not multi_chain:
            return [_selected_object_chain_members(context)]

        names_set = set(names)
        parent_of = {
            obj.name: (
                obj.parent.name
                if obj.parent is not None and obj.parent.name in names_set
                else None
            )
            for obj in selected
        }
        children_of: dict[str, list[str]] = {name: [] for name in names}
        for obj in selected:
            if obj.parent is not None and obj.parent.name in names_set:
                children_of.setdefault(obj.parent.name, []).append(obj.name)
        return partition_selection_chains(names, parent_of, children_of)

    if seed_obj is None:
        return []

    selected = [obj for obj in context.selected_objects if obj is not None]
    if multi_chain and len(selected) > 1:
        names = [obj.name for obj in selected]
        names_set = set(names)
        parent_of = {
            obj.name: (
                obj.parent.name
                if obj.parent is not None and obj.parent.name in names_set
                else None
            )
            for obj in selected
        }
        children_of: dict[str, list[str]] = {name: [] for name in names}
        for obj in selected:
            if obj.parent is not None and obj.parent.name in names_set:
                children_of.setdefault(obj.parent.name, []).append(obj.name)
        seed_names = multi_chain_seeds_from_selection(names, parent_of, children_of)
        seed_objects = [
            obj
            for name in seed_names
            if (obj := bpy.data.objects.get(name)) is not None
        ]
    else:
        seed_objects = [seed_obj]
    chain_lists: List[List[str]] = []
    seen: set[tuple[str, ...]] = set()
    for obj in seed_objects:
        if mode == "HIERARCHY":
            members = resolve_object_chain_members_branch(obj)
        else:
            members = resolve_object_chain_members_branch(obj)
            if len(members) <= 1:
                members = resolve_object_chain_members(obj)
        key = tuple(members)
        if members and key not in seen:
            seen.add(key)
            chain_lists.append(members)
    return chain_lists


def resolve_sine_chain_groups(
    context: bpy.types.Context,
) -> Tuple[List[List[SineChainTarget]], str]:
    props = context.scene.monofx_pipeline_blender_props
    chain_mode = str(props.anim_sine_bone_mode)
    multi_chain = bool(getattr(props, "anim_sine_multi_chain", True))

    if context.mode == "POSE":
        arm = context.active_object
        if arm is None or arm.type != "ARMATURE":
            return [], "No active armature."
        selected = list(context.selected_pose_bones)
        if not selected:
            return [], "Select at least one pose bone."

        chain_lists = _bone_chain_name_lists(
            arm,
            chain_mode=chain_mode,
            seed=selected[-1].name,
            selected_names=[pb.name for pb in selected],
            multi_chain=multi_chain,
        )
        if not chain_lists:
            return [], "No bones in chain."
        return [_targets_from_member_names(arm, members) for members in chain_lists], ""

    if context.mode == "OBJECT":
        seed_obj = context.active_object
        chain_lists = _object_chain_name_lists(
            context,
            chain_mode=chain_mode,
            seed_obj=seed_obj,
            multi_chain=multi_chain,
        )
        if not chain_lists:
            if chain_mode == "SELECTION":
                return [], "Select objects for the chain."
            return [], f"No object chain found for {seed_obj.name if seed_obj else 'selection'}."
        return [_targets_from_object_names(members) for members in chain_lists], ""

    return [], "Switch to Pose Mode or Object Mode."


def resolve_sine_chain_targets(context: bpy.types.Context) -> Tuple[List[SineChainTarget], str]:
    groups, err = resolve_sine_chain_groups(context)
    if err:
        return [], err
    targets: List[SineChainTarget] = []
    for group in groups:
        targets.extend(group)
    return targets, ""


def _driver_add_single(id_block: bpy.types.ID, prop_path: str, index: int | None = None):
    try:
        if index is None:
            result = id_block.driver_add(prop_path)
        else:
            result = id_block.driver_add(prop_path, index)
    except TypeError:
        result = id_block.driver_add(prop_path)
    if isinstance(result, list):
        if index is None:
            return result[0]
        return result[index] if index < len(result) else result[0]
    return result


def _pose_bone_driver_path(bone_name: str, prop_path: str) -> str:
    return f'pose.bones["{bone_name}"].{prop_path}'


def _bone_name_from_base_path(base_data_path: str) -> str | None:
    match = re.match(r'^pose\.bones\["(.+)"\]$', base_data_path or "")
    return match.group(1) if match else None


def _driver_remove_channel(id_block: bpy.types.ID, prop_path: str, index: int | None) -> None:
    try:
        if index is None:
            id_block.driver_remove(prop_path)
        else:
            id_block.driver_remove(prop_path, index)
    except Exception:
        try:
            id_block.driver_remove(prop_path)
        except Exception:
            pass


def _remove_channel_driver(target: SineChainTarget, prop_path: str, index: int) -> None:
    if target.base_data_path:
        bone_name = _bone_name_from_base_path(target.base_data_path)
        if bone_name is None:
            return
        driver_path = _pose_bone_driver_path(bone_name, prop_path)
        _driver_remove_channel(target.id_block, driver_path, index)
        return
    _driver_remove_channel(target.id_block, prop_path, index)


def _read_channel_value(
    id_block: bpy.types.ID,
    prop_path: str,
    index: int,
    *,
    base_data_path: str,
) -> float:
    if base_data_path:
        pb = id_block.path_resolve(base_data_path)
        values = getattr(pb, prop_path)
    else:
        values = getattr(id_block, prop_path)
    return float(values[index])


def _custom_prop_owner(id_block: bpy.types.ID, base_data_path: str):
    if base_data_path:
        return id_block.path_resolve(base_data_path)
    return id_block


def preview_sine_chain_rows(
    context: bpy.types.Context,
) -> Tuple[List[Tuple[str, bool]], str]:
    """Return ``[(label, has_sine_driver), ...]`` for UI display."""
    groups, err = resolve_sine_chain_groups(context)
    if err:
        return [], err
    rows: List[Tuple[str, bool]] = []
    for group_index, group in enumerate(groups):
        if group_index > 0:
            rows.append((f"— chain {group_index + 1} —", False))
        for member_index, target in enumerate(group):
            has_driver = False
            if target.id_block is not None:
                owner = _custom_prop_owner(target.id_block, target.base_data_path)
                has_driver = SINE_BASE_PROP in owner or SINE_RNA_PROP in owner
            rows.append((f"{member_index}: {target.label}", has_driver))
    return rows, ""


def _ensure_rotation_euler_target(target: SineChainTarget, channel: str) -> None:
    if (channel or "").upper() != "ROTATION":
        return
    owner = _custom_prop_owner(target.id_block, target.base_data_path)
    if getattr(owner, "rotation_mode", None) not in _EULER_ROTATION_MODES:
        owner.rotation_mode = "XYZ"


def _sync_root_tip_amplitude(axis_props) -> None:
    if str(axis_props.amp_ramp_mode) != "ROOT_TIP":
        return
    amp = float(axis_props.amplitude)
    if abs(amp) <= 1e-6:
        return
    if abs(float(axis_props.amp_tip) - 1.0) < 1e-3:
        axis_props.amp_tip = amp


def apply_sine_chain_groups(
    context: bpy.types.Context,
    groups: Sequence[Sequence[SineChainTarget]],
    *,
    channel: str,
    axis: str,
) -> Tuple[int, List[str]]:
    applied = 0
    warnings: List[str] = []
    for group in groups:
        count, group_warnings = apply_sine_chain_drivers(
            context,
            group,
            channel=channel,
            axis=axis,
        )
        applied += count
        warnings.extend(group_warnings)
    return applied, warnings


def _base_custom_path(base_data_path: str) -> str:
    if base_data_path:
        return f'{base_data_path}["{SINE_BASE_PROP}"]'
    return f'["{SINE_BASE_PROP}"]'


def _wire_sine_driver(
    driver: bpy.types.Driver,
    *,
    scene: bpy.types.Scene,
    id_block: bpy.types.ID,
    base_data_path: str,
    channel: str,
    axis: str,
    ramp_mode: str,
) -> None:
    driver.type = "SCRIPTED"
    while driver.variables:
        driver.variables.remove(driver.variables[0])

    base_var = driver.variables.new()
    base_var.name = "base"
    base_var.type = "SINGLE_PROP"
    base_target = base_var.targets[0]
    base_target.id_type = "OBJECT"
    base_target.id = id_block
    base_target.data_path = _base_custom_path(base_data_path)

    if (ramp_mode or "CURVE").upper() == "ROOT_TIP":
        amp_paths = scene_sine_root_tip_prop_paths(channel, axis)
    else:
        amp_paths = scene_sine_curve_amp_prop_paths(channel, axis)

    for var_name, data_path in amp_paths.items():
        var = driver.variables.new()
        var.name = var_name
        var.type = "SINGLE_PROP"
        target = var.targets[0]
        target.id_type = "SCENE"
        target.id = scene
        target.data_path = data_path

    for var_name, data_path in scene_sine_wave_prop_paths(channel, axis).items():
        var = driver.variables.new()
        var.name = var_name
        var.type = "SINGLE_PROP"
        target = var.targets[0]
        target.id_type = "SCENE"
        target.id = scene
        target.data_path = data_path


def apply_sine_chain_drivers(
    context: bpy.types.Context,
    targets: Sequence[SineChainTarget],
    *,
    channel: str,
    axis: str,
) -> Tuple[int, List[str]]:
    scene = context.scene
    prop_path, index = channel_data_path(channel, axis)
    applied = 0
    warnings: List[str] = []
    member_count = len(targets)
    axis_key = sine_axis_key(channel, axis)
    axis_props = resolve_sine_axis_settings(scene.monofx_pipeline_blender_props, channel, axis)
    ramp_mode = str(axis_props.amp_ramp_mode)
    _sync_root_tip_amplitude(axis_props)
    mapping = anim_sine_ramp_bpy.get_amp_ramp_mapping(channel, axis)
    if mapping is not None:
        anim_sine_ramp_bpy.ensure_amp_ramp_curve(mapping)

    for member_index, target in enumerate(targets):
        if target.id_block is None:
            continue
        _ensure_rotation_euler_target(target, channel)
        owner = _custom_prop_owner(target.id_block, target.base_data_path)
        try:
            current = _read_channel_value(
                target.id_block,
                prop_path,
                index,
                base_data_path=target.base_data_path,
            )
        except Exception:
            warnings.append(f"Could not read channel for {target.label}.")
            continue

        _remove_existing_sine_driver(target)
        owner[SINE_BASE_PROP] = current
        owner[SINE_RNA_PROP] = encode_sine_rna(prop_path, index)
        ramp_factor = anim_sine_ramp_bpy.ramp_factor_for_member(
            channel,
            axis,
            member_index,
            member_count,
        )
        owner[SINE_RAMP_PROP] = ramp_factor
        owner[SINE_RAMP_MODE_PROP] = ramp_mode
        anim_sine_ramp_bpy.store_sine_chain_metadata(
            owner,
            axis_key=axis_key,
            member_index=member_index,
            member_count=member_count,
        )

        if target.base_data_path:
            bone_name = _bone_name_from_base_path(target.base_data_path)
            if bone_name is None:
                warnings.append(f"Invalid pose bone path for {target.label}.")
                continue
            driver_path = _pose_bone_driver_path(bone_name, prop_path)
            fcurve = _driver_add_single(target.id_block, driver_path, index)
            base_id = target.id_block
        else:
            fcurve = _driver_add_single(target.id_block, prop_path, index)
            base_id = target.id_block

        driver = fcurve.driver
        driver.expression = build_sine_driver_expression(
            member_index,
            member_count,
            ramp_mode=ramp_mode,
            ramp_factor=ramp_factor if ramp_mode == "CURVE" else None,
        )
        _wire_sine_driver(
            driver,
            scene=scene,
            id_block=base_id,
            base_data_path=target.base_data_path,
            channel=channel,
            axis=axis,
            ramp_mode=ramp_mode,
        )
        applied += 1

    return applied, warnings


def _remove_existing_sine_driver(target: SineChainTarget) -> None:
    owner = _custom_prop_owner(target.id_block, target.base_data_path)
    encoded = owner.get(SINE_RNA_PROP)
    if encoded:
        decoded = decode_sine_rna(str(encoded))
        if decoded is not None:
            prop_path, index = decoded
            _remove_channel_driver(target, prop_path, index)
    anim_sine_ramp_bpy.clear_sine_chain_metadata(owner)


def clear_sine_chain_drivers(targets: Sequence[SineChainTarget]) -> int:
    cleared = 0
    for target in targets:
        owner = _custom_prop_owner(target.id_block, target.base_data_path)
        if SINE_BASE_PROP not in owner and SINE_RNA_PROP not in owner:
            continue

        encoded = owner.get(SINE_RNA_PROP)
        if encoded:
            decoded = decode_sine_rna(str(encoded))
            if decoded is not None:
                prop_path, index = decoded
                _remove_channel_driver(target, prop_path, index)

        for key in (SINE_BASE_PROP, SINE_RAMP_PROP, SINE_RAMP_MODE_PROP, SINE_RNA_PROP):
            if key in owner:
                try:
                    del owner[key]
                except Exception:
                    pass
        anim_sine_ramp_bpy.clear_sine_chain_metadata(owner)
        cleared += 1
    return cleared


def targets_with_sine_drivers(targets: Sequence[SineChainTarget]) -> List[SineChainTarget]:
    result: List[SineChainTarget] = []
    for target in targets:
        owner = _custom_prop_owner(target.id_block, target.base_data_path)
        if SINE_BASE_PROP in owner or SINE_RNA_PROP in owner:
            result.append(target)
    return result


def _read_evaluated_channel_value(
    context: bpy.types.Context,
    target: SineChainTarget,
    prop_path: str,
    index: int,
) -> float:
    depsgraph = context.evaluated_depsgraph_get()
    id_eval = target.id_block.evaluated_get(depsgraph)
    if target.base_data_path:
        pb = id_eval.path_resolve(target.base_data_path)
        values = getattr(pb, prop_path)
    else:
        values = getattr(id_eval, prop_path)
    return float(values[index])


def _keyframe_channel_value(
    target: SineChainTarget,
    prop_path: str,
    index: int,
    frame: int,
) -> None:
    if target.base_data_path:
        pb = target.id_block.path_resolve(target.base_data_path)
        pb.keyframe_insert(data_path=prop_path, index=index, frame=frame)
        return
    target.id_block.keyframe_insert(data_path=prop_path, index=index, frame=frame)


def _write_channel_value(
    id_block: bpy.types.ID,
    prop_path: str,
    index: int,
    value: float,
    *,
    base_data_path: str,
) -> None:
    if base_data_path:
        pb = id_block.path_resolve(base_data_path)
        channel = getattr(pb, prop_path)
        channel[index] = value
        setattr(pb, prop_path, channel)
    else:
        channel = getattr(id_block, prop_path)
        channel[index] = value
        setattr(id_block, prop_path, channel)


def _bake_target_key(
    target: SineChainTarget,
    prop_path: str,
    index: int,
) -> tuple[int, str, str, int]:
    return (id(target.id_block), target.base_data_path, prop_path, index)


def bake_sine_chain_drivers(
    context: bpy.types.Context,
    targets: Sequence[SineChainTarget],
    frame_start: int,
    frame_end: int,
    *,
    clear_drivers: bool = True,
) -> Tuple[int, int]:
    """Sample driven channels to keyframes over a frame range."""
    if frame_end < frame_start:
        frame_start, frame_end = frame_end, frame_start

    bake_items: List[tuple[SineChainTarget, str, int]] = []
    for target in targets:
        if target.id_block is None:
            continue
        owner = _custom_prop_owner(target.id_block, target.base_data_path)
        encoded = owner.get(SINE_RNA_PROP)
        if not encoded:
            continue
        decoded = decode_sine_rna(str(encoded))
        if decoded is None:
            continue
        prop_path, index = decoded
        bake_items.append((target, prop_path, index))

    if not bake_items:
        return 0, 0

    scene = context.scene
    original_frame = int(scene.frame_current)
    samples: dict[tuple[int, str, str, int], list[tuple[int, float]]] = {}

    try:
        for frame in range(int(frame_start), int(frame_end) + 1):
            scene.frame_set(frame)
            context.view_layer.update()
            for target, prop_path, index in bake_items:
                value = _read_evaluated_channel_value(
                    context,
                    target,
                    prop_path,
                    index,
                )
                sample_key = _bake_target_key(target, prop_path, index)
                samples.setdefault(sample_key, []).append((frame, value))
    finally:
        scene.frame_set(original_frame)

    baked_targets = list({target for target, _, _ in bake_items})
    if clear_drivers:
        clear_sine_chain_drivers(baked_targets)
    else:
        for target in baked_targets:
            _remove_existing_sine_driver(target)

    key_count = 0
    target_by_key = {
        _bake_target_key(target, prop_path, index): target
        for target, prop_path, index in bake_items
    }
    for sample_key, frame_values in samples.items():
        target = target_by_key[sample_key]
        _, _, prop_path, index = sample_key
        for frame, value in frame_values:
            _write_channel_value(
                target.id_block,
                prop_path,
                index,
                value,
                base_data_path=target.base_data_path,
            )
            _keyframe_channel_value(target, prop_path, index, frame)
            key_count += 1

    return key_count, len(baked_targets)
