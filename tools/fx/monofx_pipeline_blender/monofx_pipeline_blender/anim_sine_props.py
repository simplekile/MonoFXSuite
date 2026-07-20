"""
RNA property groups for per-axis sine chain settings.

Each axis uses its own PropertyGroup subclass so Blender keeps separate RNA storage.
"""

from bpy.props import BoolProperty, EnumProperty, FloatProperty
from bpy.types import PropertyGroup

from . import anim_sine_ramp_bpy as _sine_ramp

_on_rot_x_ramp_settings = _sine_ramp.make_sine_ramp_settings_update("ROTATION", "X")
_on_rot_y_ramp_settings = _sine_ramp.make_sine_ramp_settings_update("ROTATION", "Y")
_on_rot_z_ramp_settings = _sine_ramp.make_sine_ramp_settings_update("ROTATION", "Z")
_on_loc_x_ramp_settings = _sine_ramp.make_sine_ramp_settings_update("LOCATION", "X")
_on_loc_y_ramp_settings = _sine_ramp.make_sine_ramp_settings_update("LOCATION", "Y")
_on_loc_z_ramp_settings = _sine_ramp.make_sine_ramp_settings_update("LOCATION", "Z")


class AnimSineRotXParams(PropertyGroup):
    enabled: BoolProperty(
        name="Enable",
        description="Include this axis when applying sine chain drivers",
        default=False,
    )
    chain_offset: FloatProperty(
        name="Chain Offset",
        description="Random phase offset range per chain (degrees); reroll on apply",
        default=180.0,
        min=0.0,
        soft_max=360.0,
        update=_on_rot_x_ramp_settings,
    )
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
        update=_on_rot_x_ramp_settings,
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_rot_x_ramp_settings,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_rot_x_ramp_settings,
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
    enabled: BoolProperty(
        name="Enable",
        description="Include this axis when applying sine chain drivers",
        default=False,
    )
    chain_offset: FloatProperty(
        name="Chain Offset",
        description="Random phase offset range per chain (degrees); reroll on apply",
        default=180.0,
        min=0.0,
        soft_max=360.0,
        update=_on_rot_y_ramp_settings,
    )
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
        update=_on_rot_y_ramp_settings,
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_rot_y_ramp_settings,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_rot_y_ramp_settings,
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
    enabled: BoolProperty(
        name="Enable",
        description="Include this axis when applying sine chain drivers",
        default=True,
    )
    chain_offset: FloatProperty(
        name="Chain Offset",
        description="Random phase offset range per chain (degrees); reroll on apply",
        default=180.0,
        min=0.0,
        soft_max=360.0,
        update=_on_rot_z_ramp_settings,
    )
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
        update=_on_rot_z_ramp_settings,
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_rot_z_ramp_settings,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_rot_z_ramp_settings,
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
    enabled: BoolProperty(
        name="Enable",
        description="Include this axis when applying sine chain drivers",
        default=False,
    )
    chain_offset: FloatProperty(
        name="Chain Offset",
        description="Random phase offset range per chain (degrees); reroll on apply",
        default=180.0,
        min=0.0,
        soft_max=360.0,
        update=_on_loc_x_ramp_settings,
    )
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
        update=_on_loc_x_ramp_settings,
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_loc_x_ramp_settings,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_loc_x_ramp_settings,
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
    enabled: BoolProperty(
        name="Enable",
        description="Include this axis when applying sine chain drivers",
        default=False,
    )
    chain_offset: FloatProperty(
        name="Chain Offset",
        description="Random phase offset range per chain (degrees); reroll on apply",
        default=180.0,
        min=0.0,
        soft_max=360.0,
        update=_on_loc_y_ramp_settings,
    )
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
        update=_on_loc_y_ramp_settings,
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_loc_y_ramp_settings,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_loc_y_ramp_settings,
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
    enabled: BoolProperty(
        name="Enable",
        description="Include this axis when applying sine chain drivers",
        default=False,
    )
    chain_offset: FloatProperty(
        name="Chain Offset",
        description="Random phase offset range per chain (degrees); reroll on apply",
        default=180.0,
        min=0.0,
        soft_max=360.0,
        update=_on_loc_z_ramp_settings,
    )
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
        update=_on_loc_z_ramp_settings,
    )
    amp_root: FloatProperty(
        name="Amp Root",
        description="Sine amplitude at chain root",
        default=0.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_loc_z_ramp_settings,
    )
    amp_tip: FloatProperty(
        name="Amp Tip",
        description="Sine amplitude at chain tip",
        default=1.0,
        soft_min=-180.0,
        soft_max=180.0,
        update=_on_loc_z_ramp_settings,
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
