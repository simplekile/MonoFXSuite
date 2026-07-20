"""
Sine-chain driver expression helpers (no bpy).
"""

from __future__ import annotations

from typing import Dict, Tuple

SINE_BASE_PROP = "monofx_sine_base"
SINE_RAMP_PROP = "monofx_sine_ramp"
SINE_RAMP_MODE_PROP = "monofx_sine_ramp_mode"
SINE_RNA_PROP = "monofx_sine_rna"
SINE_AXIS_KEY_PROP = "monofx_sine_axis_key"
SINE_MEMBER_INDEX_PROP = "monofx_sine_member_index"
SINE_MEMBER_COUNT_PROP = "monofx_sine_member_count"
SINE_CHAIN_PHASE_PROP = "monofx_sine_chain_phase"
# Comma-separated axis keys with active sine drivers on this owner (e.g. "rot_x,rot_z").
SINE_SLOTS_PROP = "monofx_sine_slots"


def sine_owner_prop(base: str, axis_key: str) -> str:
    """Per-axis custom property name (keeps multi-axis drivers from overwriting)."""
    key = (axis_key or "").strip().lower()
    if not key:
        return base
    return f"{base}_{key}"


def parse_sine_slots(value) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [part for part in (p.strip() for p in text.split(",")) if part]


def encode_sine_slots(axis_keys: list[str] | tuple[str, ...] | set[str]) -> str:
    return ",".join(sorted({str(k).strip() for k in axis_keys if str(k).strip()}))


def list_sine_axis_keys(owner) -> list[str]:
    """Axis keys that currently have sine metadata on *owner*."""
    if owner is None:
        return []
    slots = parse_sine_slots(owner.get(SINE_SLOTS_PROP, ""))
    if slots:
        return slots
    # Legacy single-slot owners (pre multi-axis).
    if SINE_RNA_PROP in owner or SINE_BASE_PROP in owner:
        legacy = str(owner.get(SINE_AXIS_KEY_PROP, "") or "").strip()
        if legacy:
            return [legacy]
        encoded = owner.get(SINE_RNA_PROP)
        decoded = decode_sine_rna(str(encoded)) if encoded else None
        if decoded is not None:
            prop_path, index = decoded
            ch = "rot" if prop_path == "rotation_euler" else "loc"
            ax = {0: "x", 1: "y", 2: "z"}.get(index, "z")
            return [f"{ch}_{ax}"]
    return []


def owner_has_sine_driver(owner) -> bool:
    if owner is None:
        return False
    if list_sine_axis_keys(owner):
        return True
    return SINE_RNA_PROP in owner or SINE_BASE_PROP in owner

DEFAULT_SINE_CYCLE_FRAMES = 24

_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}

SINE_AXIS_POINTER_NAMES = {
    ("ROTATION", "X"): "anim_sine_rot_x",
    ("ROTATION", "Y"): "anim_sine_rot_y",
    ("ROTATION", "Z"): "anim_sine_rot_z",
    ("LOCATION", "X"): "anim_sine_loc_x",
    ("LOCATION", "Y"): "anim_sine_loc_y",
    ("LOCATION", "Z"): "anim_sine_loc_z",
}


def channel_data_path(channel: str, axis: str) -> Tuple[str, int]:
    """Return ``(rna_path, array_index)`` for ``driver_add``."""
    idx = _AXIS_INDEX[(axis or "Z").upper()]
    if (channel or "ROTATION").upper() == "LOCATION":
        return "location", idx
    return "rotation_euler", idx


def encode_sine_rna(prop_path: str, index: int) -> str:
    return f"{prop_path}|{index}"


def decode_sine_rna(value: str) -> Tuple[str, int] | None:
    if not value or "|" not in value:
        return None
    prop_path, idx_text = value.rsplit("|", 1)
    try:
        return prop_path, int(idx_text)
    except ValueError:
        return None


def chain_amp_t(member_index: int, member_count: int) -> float:
    if member_count <= 1:
        return 0.0
    return float(member_index) / float(member_count - 1)


def sine_axis_key(channel: str, axis: str) -> str:
    ch = "rot" if (channel or "ROTATION").upper() == "ROTATION" else "loc"
    return f"{ch}_{(axis or 'Z').lower()}"


def build_sine_driver_expression(
    member_index: int,
    member_count: int = 1,
    *,
    ramp_mode: str = "CURVE",
    ramp_factor: float | None = None,
    chain_phase: float = 0.0,
    wave_mode: str = "SINE",
    channel: str = "ROTATION",
) -> str:
    """Scripted driver expression with baked chain index and amp ramp."""
    phase_term = f"phase + {float(chain_phase):.6g}"
    angle = f"radians(-freq * {int(member_index)} + {phase_term})"
    time_term = f"frame / {DEFAULT_SINE_CYCLE_FRAMES} * 2 * pi * speed"
    if (wave_mode or "SINE").upper() == "NOISE":
        wave = (
            f"(sin({angle} + {time_term}) "
            f"+ sin({angle} * 2.17 + 1.73 + {time_term} * 1.31) "
            f"+ sin({angle} * 4.53 + 3.11 + {time_term} * 0.87)) / 3"
        )
    else:
        wave = f"sin({angle} + {time_term})"
    if (ramp_mode or "CURVE").upper() == "ROOT_TIP":
        chain_t = chain_amp_t(member_index, member_count)
        if member_count <= 1:
            amp_expr = "amp_root"
        else:
            amp_expr = f"(amp_root + (amp_tip - amp_root) * {chain_t:.6g})"
    else:
        if ramp_factor is None:
            ramp_factor = chain_amp_t(member_index, member_count)
        amp_expr = f"(amp * {float(ramp_factor):.6g})"
    # Rotation UI amplitude is degrees; Blender euler drivers use radians.
    if (channel or "ROTATION").upper() == "ROTATION":
        amp_expr = f"radians({amp_expr})"
    return f"base + {amp_expr} * {wave}"


def resolve_enabled_sine_axes(props, channel: str) -> list[str]:
    """Return enabled X/Y/Z axes for the given transform channel."""
    axes: list[str] = []
    for axis in ("X", "Y", "Z"):
        settings = resolve_sine_axis_settings(props, channel, axis)
        if read_axis_bool(
            settings,
            "enabled",
            default=(axis == "Z" and str(channel).upper() == "ROTATION"),
        ):
            axes.append(axis)
    return axes


def resolve_apply_sine_axes(props, channel: str, active_axis: str | None = None) -> list[str]:
    """Axes to apply: enabled, active tab, and any axis with non-zero amplitude."""
    axes = resolve_enabled_sine_axes(props, channel)
    active = (active_axis or getattr(props, "anim_sine_axis", "Z") or "Z")
    active = str(active).upper()
    if active in {"X", "Y", "Z"} and active not in axes:
        axes = list(axes) + [active]
    # Amplitude set on a tab should apply even if Enable was left unchecked.
    for axis in ("X", "Y", "Z"):
        if axis in axes:
            continue
        settings = resolve_sine_axis_settings(props, channel, axis)
        if abs(read_axis_float(settings, "amplitude", 0.0)) > 1e-6:
            axes.append(axis)
        elif str(getattr(settings, "amp_ramp_mode", "CURVE")).upper() == "ROOT_TIP":
            if (
                abs(read_axis_float(settings, "amp_root", 0.0)) > 1e-6
                or abs(read_axis_float(settings, "amp_tip", 0.0)) > 1e-6
            ):
                axes.append(axis)
    order = {"X": 0, "Y": 1, "Z": 2}
    axes = sorted(set(axes), key=lambda a: order.get(a, 9))
    if active in axes:
        axes = [a for a in axes if a != active] + [active]
    return axes


def scene_sine_wave_prop_paths(channel: str, axis: str) -> Dict[str, str]:
    """Shared driver variables for the sine wave."""
    group = sine_axis_prop_prefix(channel, axis)
    rna_prefix = "monofx_pipeline_blender_props"
    return {
        "freq": f"{rna_prefix}.{group}.frequency",
        "speed": f"{rna_prefix}.{group}.speed",
        "phase": f"{rna_prefix}.{group}.phase",
    }


def scene_sine_curve_amp_prop_paths(channel: str, axis: str) -> Dict[str, str]:
    group = sine_axis_prop_prefix(channel, axis)
    rna_prefix = "monofx_pipeline_blender_props"
    return {"amp": f"{rna_prefix}.{group}.amplitude"}


def scene_sine_root_tip_prop_paths(channel: str, axis: str) -> Dict[str, str]:
    group = sine_axis_prop_prefix(channel, axis)
    rna_prefix = "monofx_pipeline_blender_props"
    return {
        "amp_root": f"{rna_prefix}.{group}.amp_root",
        "amp_tip": f"{rna_prefix}.{group}.amp_tip",
    }


def scene_sine_prop_paths(channel: str, axis: str) -> Dict[str, str]:
    """Driver variable data paths on ``scene.monofx_pipeline_blender_props``."""
    paths = dict(scene_sine_wave_prop_paths(channel, axis))
    paths.update(scene_sine_curve_amp_prop_paths(channel, axis))
    return paths


def sine_axis_prop_prefix(channel: str, axis: str) -> str:
    ch = (channel or "ROTATION").upper()
    ax = (axis or "Z").upper()
    name = SINE_AXIS_POINTER_NAMES.get((ch, ax))
    if name is None:
        ch_key = "rot" if ch == "ROTATION" else "loc"
        name = f"anim_sine_{ch_key}_{ax.lower()}"
    return name


def resolve_sine_axis_settings(props, channel: str, axis: str):
    pointer_name = sine_axis_prop_prefix(channel, axis)
    return getattr(props, pointer_name)


def _is_property_deferred(value) -> bool:
    cls_name = type(value).__name__
    return cls_name == "_PropertyDeferred" or cls_name.endswith("PropertyDeferred")


def read_axis_float(axis_props, prop_name: str, default: float = 0.0) -> float:
    """Read a float RNA field, avoiding unresolved PropertyGroup descriptors."""
    if axis_props is None:
        return default
    rna_props = getattr(getattr(axis_props, "bl_rna", None), "properties", None)
    if rna_props is not None and prop_name not in rna_props:
        return default
    try:
        return float(getattr(axis_props, prop_name))
    except (AttributeError, TypeError, ValueError):
        if rna_props is not None and prop_name in rna_props:
            try:
                return float(rna_props[prop_name].default)
            except (AttributeError, TypeError, ValueError):
                pass
        return default


def read_axis_bool(axis_props, prop_name: str, default: bool = False) -> bool:
    """Read a bool RNA field, avoiding unresolved PropertyGroup descriptors."""
    if axis_props is None:
        return default
    rna_props = getattr(getattr(axis_props, "bl_rna", None), "properties", None)
    if rna_props is not None and prop_name not in rna_props:
        return default
    try:
        return bool(getattr(axis_props, prop_name))
    except (AttributeError, TypeError, ValueError):
        if rna_props is not None and prop_name in rna_props:
            try:
                return bool(rna_props[prop_name].default)
            except (AttributeError, TypeError, ValueError):
                pass
        return default

