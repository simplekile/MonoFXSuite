"""
Amp ramp curve helpers for sine-chain drivers.

Blender cannot store CurveMapping on RNA PropertyGroups, so each ramp lives on a
hidden Float Curve node in a dot-prefixed node group.
"""

from __future__ import annotations

from typing import Iterator, Tuple

import bpy
from bpy.app.handlers import persistent

from monofx_pipeline_common.anim_sine_chain import (
    SINE_AXIS_KEY_PROP,
    SINE_BASE_PROP,
    SINE_CHAIN_PHASE_PROP,
    SINE_MEMBER_COUNT_PROP,
    SINE_MEMBER_INDEX_PROP,
    SINE_RAMP_MODE_PROP,
    SINE_RAMP_PROP,
    SINE_RNA_PROP,
    build_sine_driver_expression,
    chain_amp_t,
    decode_sine_rna,
    list_sine_axis_keys,
    owner_has_sine_driver,
    read_axis_float,
    resolve_sine_axis_settings,
    sine_axis_key,
    sine_owner_prop,
)

RAMP_NODE_TREE_NAME = ".MonoFX_SineRamp"
RAMP_NODE_TYPE = "ShaderNodeFloatCurve"

_SINE_RAMP_CHANNELS = (
    ("ROTATION", "X"),
    ("ROTATION", "Y"),
    ("ROTATION", "Z"),
    ("LOCATION", "X"),
    ("LOCATION", "Y"),
    ("LOCATION", "Z"),
)

_AXIS_NAMES = {0: "x", 1: "y", 2: "z"}


def ramp_node_name(channel: str, axis: str) -> str:
    return f"ramp_{sine_axis_key(channel, axis)}"


def _node_groups():
    data = bpy.data
    groups = getattr(data, "node_groups", None)
    if groups is None:
        raise RuntimeError("bpy.data.node_groups is unavailable in the current Blender context")
    return groups


def ensure_ramp_node_tree() -> bpy.types.ShaderNodeTree | None:
    try:
        node_groups = _node_groups()
    except RuntimeError:
        return None
    node_tree = node_groups.get(RAMP_NODE_TREE_NAME)
    if node_tree is None:
        node_tree = node_groups.new(RAMP_NODE_TREE_NAME, "ShaderNodeTree")
        node_tree.use_fake_user = True
    return node_tree


def get_amp_ramp_node(channel: str, axis: str, *, create: bool = True) -> bpy.types.Node | None:
    name = ramp_node_name(channel, axis)
    try:
        node_tree = _node_groups().get(RAMP_NODE_TREE_NAME)
    except RuntimeError:
        return None

    if node_tree is None:
        if not create:
            return None
        node_tree = ensure_ramp_node_tree()
        if node_tree is None:
            return None

    node = node_tree.nodes.get(name)
    if node is not None and node.bl_idname != RAMP_NODE_TYPE:
        if not create:
            return None
        node_tree.nodes.remove(node)
        node = None

    if node is None and create:
        node = node_tree.nodes.new(RAMP_NODE_TYPE)
        node.name = name
        node.label = name
        ensure_amp_ramp_curve(node.mapping)
    return node


def ensure_amp_ramp_node(channel: str, axis: str) -> bpy.types.Node | None:
    """Create or return the ramp node. Must not be called from UI ``draw()`` handlers."""
    return get_amp_ramp_node(channel, axis, create=True)


def schedule_amp_ramp_node_ensure(channel: str, axis: str) -> None:
    """Deferred ramp-node init safe outside UI draw handlers."""
    channel = str(channel)
    axis = str(axis)

    def _run() -> None:
        ensure_amp_ramp_node(channel, axis)
        return None

    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except Exception:
        pass


def schedule_sine_axis_driver_refresh(channel: str, axis: str) -> None:
    """Re-wire existing sine drivers after ramp mode or root/tip edits."""
    channel = str(channel)
    axis = str(axis)

    def _run() -> None:
        try:
            context = bpy.context
            if context is None or context.scene is None:
                return None
            refresh_sine_ramp_drivers(context, channel=channel, axis=axis)
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except Exception:
        pass


def make_sine_ramp_settings_update(channel: str, axis: str):
    """RNA update callback for per-axis amp ramp settings."""

    def _update(self, _context) -> None:
        if getattr(self, "amp_ramp_mode", None) == "ROOT_TIP":
            amp = read_axis_float(self, "amplitude", 0.0)
            if abs(amp) > 1e-6 and abs(read_axis_float(self, "amp_tip", 1.0) - 1.0) < 1e-3:
                self.amp_tip = amp
        schedule_sine_axis_driver_refresh(channel, axis)

    return _update


def get_amp_ramp_mapping(channel: str, axis: str, *, create: bool = True) -> bpy.types.CurveMapping | None:
    node = get_amp_ramp_node(channel, axis, create=create)
    if node is None:
        return None
    return node.mapping


_ramp_refresh_timer = None
_RAMP_MSGBUS_OWNER = object()


def _on_ramp_curve_changed(*_args) -> None:
    _schedule_ramp_refresh()


def _subscribe_ramp_curve_msgbus() -> None:
    bpy.msgbus.clear_by_owner(_RAMP_MSGBUS_OWNER)
    try:
        node_tree = _node_groups().get(RAMP_NODE_TREE_NAME)
    except RuntimeError:
        return
    if node_tree is None:
        return
    for node in node_tree.nodes:
        if node.bl_idname != RAMP_NODE_TYPE:
            continue
        mapping = node.mapping
        if mapping is None or not mapping.curves:
            continue
        for spline in mapping.curves:
            for point in spline.points:
                try:
                    bpy.msgbus.subscribe_rna(
                        key=(point, "location"),
                        owner=_RAMP_MSGBUS_OWNER,
                        args=(),
                        notify=_on_ramp_curve_changed,
                        options={"PERSISTENT"},
                    )
                except Exception:
                    pass


def deferred_init_ramp_nodes() -> None:
    try:
        for channel, axis in _SINE_RAMP_CHANNELS:
            get_amp_ramp_node(channel, axis)
        _subscribe_ramp_curve_msgbus()
    except Exception:
        pass


def _deferred_init_ramp_nodes_timer() -> None:
    deferred_init_ramp_nodes()
    return None


def ensure_amp_ramp_curve(curve: bpy.types.CurveMapping | None) -> None:
    """Initialize ramp defaults. Must not run from UI draw handlers."""
    if curve is None:
        return
    try:
        curve.use_clip = True
        curve.clip_min_x = 0.0
        curve.clip_max_x = 1.0
        curve.clip_min_y = 0.0
        curve.clip_max_y = 1.0
        if not curve.curves:
            return
        spline = curve.curves[0]
        if len(spline.points) < 2:
            while spline.points:
                spline.points.remove(spline.points[0])
            spline.points.new(0.0, 1.0)
            spline.points.new(1.0, 1.0)
    except AttributeError:
        return


def _prepare_curve_mapping(curve: bpy.types.CurveMapping) -> None:
    if hasattr(curve, "update"):
        curve.update()
    if hasattr(curve, "initialize"):
        curve.initialize()


def _linear_curve_eval(spline: bpy.types.CurveMap, t: float) -> float:
    points = sorted((float(p.location[0]), float(p.location[1])) for p in spline.points)
    if not points:
        return 1.0
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for index in range(len(points) - 1):
        x0, y0 = points[index]
        x1, y1 = points[index + 1]
        if x0 <= t <= x1:
            if x1 == x0:
                return y0
            blend = (t - x0) / (x1 - x0)
            return y0 + (y1 - y0) * blend
    return points[-1][1]


def eval_amp_ramp_curve(curve: bpy.types.CurveMapping | None, t: float) -> float:
    t = max(0.0, min(1.0, float(t)))
    if curve is None or not curve.curves:
        return 1.0
    spline = curve.curves[0]
    if len(spline.points) < 2:
        return 1.0
    try:
        _prepare_curve_mapping(curve)
        return float(curve.evaluate(spline, t))
    except Exception:
        return _linear_curve_eval(spline, t)


def ramp_factor_for_member(
    channel: str,
    axis: str,
    member_index: int,
    member_count: int,
) -> float:
    t = chain_amp_t(member_index, member_count)
    mapping = get_amp_ramp_mapping(channel, axis, create=False)
    if mapping is None:
        mapping = get_amp_ramp_mapping(channel, axis, create=True)
    return eval_amp_ramp_curve(mapping, t)


def _owner_axis_key(owner, prop_path: str, channel_index: int) -> str:
    stored = str(owner.get(SINE_AXIS_KEY_PROP, ""))
    if stored:
        return stored
    ch = "rot" if prop_path == "rotation_euler" else "loc"
    ax = _AXIS_NAMES.get(channel_index, "z")
    return f"{ch}_{ax}"


def _apply_ramp_to_driver(
    driver: bpy.types.Driver,
    *,
    context: bpy.types.Context,
    id_block: bpy.types.ID,
    base_data_path: str,
    channel: str,
    axis: str,
    member_index: int,
    member_count: int,
    ramp_mode: str,
    ramp_factor: float,
    chain_phase: float = 0.0,
    wave_mode: str = "SINE",
) -> None:
    from .anim_sine_chain_bpy import _wire_sine_driver

    driver.expression = build_sine_driver_expression(
        member_index,
        member_count,
        ramp_mode=ramp_mode,
        ramp_factor=ramp_factor if ramp_mode == "CURVE" else None,
        chain_phase=chain_phase,
        wave_mode=wave_mode,
        channel=channel,
    )
    _wire_sine_driver(
        driver,
        scene=context.scene,
        id_block=id_block,
        base_data_path=base_data_path,
        channel=channel,
        axis=axis,
        ramp_mode=ramp_mode,
    )


def store_sine_chain_metadata(
    owner,
    *,
    axis_key: str,
    member_index: int,
    member_count: int,
) -> None:
    # Per-axis metadata (multi-axis safe).
    owner[sine_owner_prop(SINE_AXIS_KEY_PROP, axis_key)] = axis_key
    owner[sine_owner_prop(SINE_MEMBER_INDEX_PROP, axis_key)] = int(member_index)
    owner[sine_owner_prop(SINE_MEMBER_COUNT_PROP, axis_key)] = int(member_count)
    # Keep legacy single-slot mirrors for older refresh paths / migration.
    owner[SINE_AXIS_KEY_PROP] = axis_key
    owner[SINE_MEMBER_INDEX_PROP] = int(member_index)
    owner[SINE_MEMBER_COUNT_PROP] = int(member_count)


def clear_sine_chain_metadata(owner, *, axis_key: str | None = None) -> None:
    keys = [axis_key] if axis_key else list_sine_axis_keys(owner)
    if axis_key:
        for base in (SINE_AXIS_KEY_PROP, SINE_MEMBER_INDEX_PROP, SINE_MEMBER_COUNT_PROP):
            prop = sine_owner_prop(base, axis_key)
            if prop in owner:
                try:
                    del owner[prop]
                except Exception:
                    pass
        # Clear legacy mirrors only if they still point at this axis.
        if str(owner.get(SINE_AXIS_KEY_PROP, "") or "") == axis_key:
            for key in (SINE_AXIS_KEY_PROP, SINE_MEMBER_INDEX_PROP, SINE_MEMBER_COUNT_PROP):
                if key in owner:
                    try:
                        del owner[key]
                    except Exception:
                        pass
        return

    for key in keys:
        clear_sine_chain_metadata(owner, axis_key=key)
    for key in (SINE_AXIS_KEY_PROP, SINE_MEMBER_INDEX_PROP, SINE_MEMBER_COUNT_PROP):
        if key in owner:
            try:
                del owner[key]
            except Exception:
                pass


def _find_driver_fcurve(
    id_block: bpy.types.ID,
    driver_path: str,
    channel_index: int,
):
    anim = getattr(id_block, "animation_data", None)
    if anim is None or anim.drivers is None:
        return None
    for fcurve in anim.drivers:
        if fcurve.data_path == driver_path and fcurve.array_index == channel_index:
            return fcurve
    return None


def iter_sine_driver_owners() -> Iterator[Tuple[bpy.types.ID, str, object]]:
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            for pose_bone in obj.pose.bones:
                owner = pose_bone
                if owner_has_sine_driver(owner):
                    yield obj, pose_bone.name, owner
        if owner_has_sine_driver(obj):
            yield obj, "", obj


def refresh_sine_ramp_drivers(
    context: bpy.types.Context,
    *,
    channel: str,
    axis: str,
) -> int:
    target_key = sine_axis_key(channel, axis)
    axis_props = resolve_sine_axis_settings(
        context.scene.monofx_pipeline_blender_props,
        channel,
        axis,
    )
    ramp_mode = str(axis_props.amp_ramp_mode)
    if ramp_mode == "CURVE" and get_amp_ramp_mapping(channel, axis, create=False) is None:
        return 0
    wave_mode = str(
        getattr(context.scene.monofx_pipeline_blender_props, "anim_sine_wave_mode", "SINE")
    )
    updated = 0

    for id_block, bone_name, owner in iter_sine_driver_owners():
        axis_keys = list_sine_axis_keys(owner)
        if target_key not in axis_keys and str(owner.get(SINE_AXIS_KEY_PROP, "")) != target_key:
            continue

        rna_name = sine_owner_prop(SINE_RNA_PROP, target_key)
        encoded = owner.get(rna_name)
        if encoded is None and str(owner.get(SINE_AXIS_KEY_PROP, "")) == target_key:
            encoded = owner.get(SINE_RNA_PROP)
        if not encoded:
            continue

        decoded = decode_sine_rna(str(encoded))
        if decoded is None:
            continue
        prop_path, channel_index = decoded

        member_index = int(
            owner.get(
                sine_owner_prop(SINE_MEMBER_INDEX_PROP, target_key),
                owner.get(SINE_MEMBER_INDEX_PROP, 0),
            )
        )
        member_count = int(
            owner.get(
                sine_owner_prop(SINE_MEMBER_COUNT_PROP, target_key),
                owner.get(SINE_MEMBER_COUNT_PROP, 1),
            )
        )
        ramp_factor = ramp_factor_for_member(channel, axis, member_index, member_count)
        owner[sine_owner_prop(SINE_RAMP_PROP, target_key)] = ramp_factor
        owner[sine_owner_prop(SINE_RAMP_MODE_PROP, target_key)] = ramp_mode
        chain_phase = float(
            owner.get(
                sine_owner_prop(SINE_CHAIN_PHASE_PROP, target_key),
                owner.get(SINE_CHAIN_PHASE_PROP, 0.0),
            )
        )

        if bone_name:
            driver_path = f'pose.bones["{bone_name}"].{prop_path}'
            base_data_path = f'pose.bones["{bone_name}"]'
        else:
            driver_path = prop_path
            base_data_path = ""

        fcurve = _find_driver_fcurve(id_block, driver_path, channel_index)
        if fcurve is None or fcurve.driver is None:
            continue

        _apply_ramp_to_driver(
            fcurve.driver,
            context=context,
            id_block=id_block,
            base_data_path=base_data_path,
            channel=channel,
            axis=axis,
            member_index=member_index,
            member_count=member_count,
            ramp_mode=ramp_mode,
            ramp_factor=ramp_factor,
            chain_phase=chain_phase,
            wave_mode=wave_mode,
        )
        id_block.update_tag(refresh={"DATA"})
        updated += 1

    return updated


def refresh_all_sine_ramp_drivers(context: bpy.types.Context) -> int:
    updated = 0
    for channel, axis in _SINE_RAMP_CHANNELS:
        updated += refresh_sine_ramp_drivers(context, channel=channel, axis=axis)
    return updated


def _run_ramp_refresh() -> None:
    global _ramp_refresh_timer
    _ramp_refresh_timer = None
    try:
        context = bpy.context
        if context.scene is None:
            return None
        refresh_all_sine_ramp_drivers(context)
    except Exception:
        pass
    return None


def _schedule_ramp_refresh() -> None:
    global _ramp_refresh_timer
    if _ramp_refresh_timer is not None:
        return
    _ramp_refresh_timer = _run_ramp_refresh
    bpy.app.timers.register(_run_ramp_refresh, first_interval=0.2)


@persistent
def _on_depsgraph_update_ramp(_scene, depsgraph) -> None:
    for update in depsgraph.updates:
        id_block = update.id
        if isinstance(id_block, bpy.types.NodeTree) and id_block.name == RAMP_NODE_TREE_NAME:
            _schedule_ramp_refresh()
            return
        if isinstance(id_block, bpy.types.Node):
            node_tree = getattr(id_block, "id_data", None)
            if isinstance(node_tree, bpy.types.NodeTree) and node_tree.name == RAMP_NODE_TREE_NAME:
                _schedule_ramp_refresh()
                return


def register_ramp_listeners() -> None:
    if _on_depsgraph_update_ramp not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update_ramp)


def unregister_ramp_listeners() -> None:
    global _ramp_refresh_timer
    bpy.msgbus.clear_by_owner(_RAMP_MSGBUS_OWNER)
    if _on_depsgraph_update_ramp in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update_ramp)
    if _ramp_refresh_timer is not None:
        try:
            bpy.app.timers.unregister(_ramp_refresh_timer)
        except Exception:
            pass
        _ramp_refresh_timer = None
