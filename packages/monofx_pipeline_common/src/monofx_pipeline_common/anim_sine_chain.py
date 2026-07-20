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
    cycle_frames: int | None = None,
) -> str:
    """Scripted driver expression with baked chain index and amp ramp."""
    cycle_expr = "cycle" if cycle_frames is None else f"{max(1, int(cycle_frames))}"
    wave = (
        f"sin(radians(-freq * {int(member_index)} + phase) "
        f"+ frame / {cycle_expr} * 2 * pi * speed)"
    )
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
    return f"base + {amp_expr} * {wave}"


def scene_sine_wave_prop_paths(channel: str, axis: str) -> Dict[str, str]:
    """Shared driver variables for the sine wave."""
    group = sine_axis_prop_prefix(channel, axis)
    rna_prefix = "monofx_pipeline_blender_props"
    return {
        "freq": f"{rna_prefix}.{group}.frequency",
        "speed": f"{rna_prefix}.{group}.speed",
        "phase": f"{rna_prefix}.{group}.phase",
        "cycle": f"{rna_prefix}.anim_sine_cycle_frames",
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

