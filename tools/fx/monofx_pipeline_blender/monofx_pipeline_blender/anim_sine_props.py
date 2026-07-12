"""
RNA property groups for per-axis sine chain settings.

Each axis uses its own PropertyGroup subclass so Blender keeps separate RNA storage.
"""

from __future__ import annotations

from bpy.props import EnumProperty, FloatProperty
from bpy.types import PropertyGroup


class AnimSineRotXParams(PropertyGroup):
    amplitude: FloatProperty(
        name="Amplitude",
        description="Sine amplitude for rotation X (degrees)",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_ramp_mode: EnumProperty(
        name="Amp Ramp Mode",
        items=[
            ("ROOT_TIP", "Amp Root/Tip", "Linear amplitude from chain root to tip"),
            ("CURVE", "Curve Map", "Curve ramp multiplied by main Amplitude"),
        ],
        default="CURVE",
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    frequency: FloatProperty(
        name="Frequency",
        description="Phase offset per chain link (degrees); higher = denser wave along the chain",
        default=25.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    speed: FloatProperty(
        name="Speed",
        description="Oscillation speed; sine cycles per 24 frames",
        default=1.0,
        min=0.0,
        soft_max=10.0,
    )
    phase: FloatProperty(
        name="Phase",
        description="Global phase offset of the main sine wave (degrees)",
        default=0.0,
        soft_min=-360.0,
        soft_max=360.0,
    )


class AnimSineRotYParams(PropertyGroup):
    amplitude: FloatProperty(
        name="Amplitude",
        description="Sine amplitude for rotation Y (degrees)",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_ramp_mode: EnumProperty(
        name="Amp Ramp Mode",
        items=[
            ("ROOT_TIP", "Amp Root/Tip", "Linear amplitude from chain root to tip"),
            ("CURVE", "Curve Map", "Curve ramp multiplied by main Amplitude"),
        ],
        default="CURVE",
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    frequency: FloatProperty(
        name="Frequency",
        description="Phase offset per chain link (degrees); higher = denser wave along the chain",
        default=25.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    speed: FloatProperty(
        name="Speed",
        description="Oscillation speed; sine cycles per 24 frames",
        default=1.0,
        min=0.0,
        soft_max=10.0,
    )
    phase: FloatProperty(
        name="Phase",
        description="Global phase offset of the main sine wave (degrees)",
        default=0.0,
        soft_min=-360.0,
        soft_max=360.0,
    )


class AnimSineRotZParams(PropertyGroup):
    amplitude: FloatProperty(
        name="Amplitude",
        description="Sine amplitude for rotation Z (degrees)",
        default=15.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_ramp_mode: EnumProperty(
        name="Amp Ramp Mode",
        items=[
            ("ROOT_TIP", "Amp Root/Tip", "Linear amplitude from chain root to tip"),
            ("CURVE", "Curve Map", "Curve ramp multiplied by main Amplitude"),
        ],
        default="CURVE",
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    frequency: FloatProperty(
        name="Frequency",
        description="Phase offset per chain link (degrees); higher = denser wave along the chain",
        default=25.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    speed: FloatProperty(
        name="Speed",
        description="Oscillation speed; sine cycles per 24 frames",
        default=1.0,
        min=0.0,
        soft_max=10.0,
    )
    phase: FloatProperty(
        name="Phase",
        description="Global phase offset of the main sine wave (degrees)",
        default=0.0,
        soft_min=-360.0,
        soft_max=360.0,
    )


class AnimSineLocXParams(PropertyGroup):
    amplitude: FloatProperty(
        name="Amplitude",
        description="Sine amplitude for location X (BU)",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_ramp_mode: EnumProperty(
        name="Amp Ramp Mode",
        items=[
            ("ROOT_TIP", "Amp Root/Tip", "Linear amplitude from chain root to tip"),
            ("CURVE", "Curve Map", "Curve ramp multiplied by main Amplitude"),
        ],
        default="CURVE",
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    frequency: FloatProperty(
        name="Frequency",
        description="Phase offset per chain link (degrees); higher = denser wave along the chain",
        default=25.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    speed: FloatProperty(
        name="Speed",
        description="Oscillation speed; sine cycles per 24 frames",
        default=1.0,
        min=0.0,
        soft_max=10.0,
    )
    phase: FloatProperty(
        name="Phase",
        description="Global phase offset of the main sine wave (degrees)",
        default=0.0,
        soft_min=-360.0,
        soft_max=360.0,
    )


class AnimSineLocYParams(PropertyGroup):
    amplitude: FloatProperty(
        name="Amplitude",
        description="Sine amplitude for location Y (BU)",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_ramp_mode: EnumProperty(
        name="Amp Ramp Mode",
        items=[
            ("ROOT_TIP", "Amp Root/Tip", "Linear amplitude from chain root to tip"),
            ("CURVE", "Curve Map", "Curve ramp multiplied by main Amplitude"),
        ],
        default="CURVE",
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    frequency: FloatProperty(
        name="Frequency",
        description="Phase offset per chain link (degrees); higher = denser wave along the chain",
        default=25.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    speed: FloatProperty(
        name="Speed",
        description="Oscillation speed; sine cycles per 24 frames",
        default=1.0,
        min=0.0,
        soft_max=10.0,
    )
    phase: FloatProperty(
        name="Phase",
        description="Global phase offset of the main sine wave (degrees)",
        default=0.0,
        soft_min=-360.0,
        soft_max=360.0,
    )


class AnimSineLocZParams(PropertyGroup):
    amplitude: FloatProperty(
        name="Amplitude",
        description="Sine amplitude for location Z (BU)",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_ramp_mode: EnumProperty(
        name="Amp Ramp Mode",
        items=[
            ("ROOT_TIP", "Amp Root/Tip", "Linear amplitude from chain root to tip"),
            ("CURVE", "Curve Map", "Curve ramp multiplied by main Amplitude"),
        ],
        default="CURVE",
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    frequency: FloatProperty(
        name="Frequency",
        description="Phase offset per chain link (degrees); higher = denser wave along the chain",
        default=25.0,
        soft_min=-180.0,
        soft_max=180.0,
    )
    speed: FloatProperty(
        name="Speed",
        description="Oscillation speed; sine cycles per 24 frames",
        default=1.0,
        min=0.0,
        soft_max=10.0,
    )
    phase: FloatProperty(
        name="Phase",
        description="Global phase offset of the main sine wave (degrees)",
        default=0.0,
        soft_min=-360.0,
        soft_max=360.0,
    )


SINE_AXIS_PROPERTY_GROUPS = (
    AnimSineRotXParams,
    AnimSineRotYParams,
    AnimSineRotZParams,
    AnimSineLocXParams,
    AnimSineLocYParams,
    AnimSineLocZParams,
)
