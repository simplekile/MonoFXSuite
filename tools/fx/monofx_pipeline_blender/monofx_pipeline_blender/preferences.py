"""
Add-on preferences — workflow tab and section state persists across sessions.
"""

from __future__ import annotations

from typing import Optional

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import AddonPreferences, Context


class MonoFXPipelinePreferences(AddonPreferences):
    bl_idname = __package__

    pipeline_project_root: StringProperty(
        name="Pipeline Project Root",
        description="Last known pipeline project folder (01_assets + 02_shots); used when the .blend is outside the project tree",
        default="",
        subtype="DIR_PATH",
    )

    ui_model_tab: EnumProperty(
        name="Model Tab",
        items=[
            ("PREP", "Geo Prep", "Hierarchy, naming, cleanup, materials"),
            ("BAKE", "USD Bake", "Bake materials to USD-friendly textures"),
            ("USD", "Geo USD", "Geo USD publish"),
        ],
        default="PREP",
    )
    ui_anim_tab: EnumProperty(
        name="Anim Tab",
        items=[
            ("LINK", "Scene", "Shot setup, project rigs, and scene rig links"),
            ("CAMERA", "Camera Tools", "Camera and rig controls"),
            ("TOOLS", "Anim Tools", "Selection and keyframe cleanup"),
            ("USD", "Anim USD", "Animation USD publish"),
        ],
        default="LINK",
    )

    ui_prep_section: EnumProperty(
        name="Geo Prep Section",
        items=[
            ("HIERARCHY", "Tree", "Asset tree", "OUTLINER_COLLECTION", 0),
            ("NAMING", "Name", "Naming", "SYNTAX_ON", 1),
            ("TRANSFORMS", "Xform", "Transforms", "OBJECT_ORIGIN", 2),
            ("CLEANUP", "Clean", "Mesh cleanup", "BRUSH_DATA", 3),
            ("MATERIALS", "Mat", "Materials", "MATERIAL", 4),
            ("PRESET", "Preset", "Preset editor", "PRESET", 5),
        ],
        default="HIERARCHY",
    )
    ui_rig_section: EnumProperty(
        name="Scene Section",
        items=[
            ("LIBRARY", "Project Rig", "Published rig library", "LINKED", 0),
            ("SCENE", "Scene Rig", "Rigs linked in this scene", "OUTLINER_COLLECTION", 1),
            ("SHOT", "Shot", "Shot collections", "OUTLINER_COLLECTION", 2),
        ],
        default="LIBRARY",
    )
    ui_anim_tools_section: EnumProperty(
        name="Anim Tools Section",
        items=[
            ("SELECTION", "Select", "Selection tools", "RESTRICT_SELECT_OFF", 0),
            ("TRANSFORM", "Xform", "World transform copy/paste", "OBJECT_ORIGIN", 1),
            ("KEYS", "Keys", "Keyframe cleanup", "KEYINGSET", 2),
        ],
        default="SELECTION",
    )

    ui_camera_tools_section: EnumProperty(
        name="Camera Tools Section",
        items=[
            ("CAMERA", "Camera", "Camera rig creation", "OUTLINER_OB_CAMERA", 0),
            ("SETUP", "Setup", "Lens, vertigo, root/aim, orbit", "TOOL_SETTINGS", 1),
            ("RIG", "Rig", "Rig utilities and pose tools", "OUTLINER_OB_EMPTY", 2),
            ("MOTION", "Motion", "Pedestal, crane, track, head motion", "ORIENTATION_GIMBAL", 3),
        ],
        default="CAMERA",
    )
    ui_anim_usd_section: EnumProperty(
        name="Anim USD Section",
        items=[
            ("OUTPUT", "Output", "Output path", "FILE", 0),
            ("RANGE", "Range", "Frame range", "TIME", 1),
            ("ADVANCED", "Adv", "Advanced options", "PREFERENCES", 2),
            ("ASSETS", "Assets", "Scene export assets", "OUTLINER", 3),
        ],
        default="OUTPUT",
    )

    ui_sec_anim_camera_motion: BoolProperty(name="Camera Motion", default=True)
    ui_sec_anim_camera_rig_tools: BoolProperty(name="Rig Tools", default=True)
    ui_sec_anim_camera_setup: BoolProperty(name="Camera Setup", default=True)
    ui_sec_anim_camera_vertigo: BoolProperty(name="Vertigo", default=True)
    ui_sec_anim_camera_root: BoolProperty(name="Root Setup", default=True)
    ui_sec_anim_camera_aim: BoolProperty(name="Aim Setup", default=True)
    ui_sec_anim_camera_orbit: BoolProperty(name="Orbit", default=True)
    ui_sec_anim_camera_orbit_display: BoolProperty(name="Orbit Display", default=True)
    ui_sec_anim_camera_motion_render: BoolProperty(name="Render", default=True)
    ui_sec_anim_camera_motion_mount: BoolProperty(name="Pedestal & Crane", default=True)
    ui_sec_anim_camera_motion_track: BoolProperty(name="Dolly Track", default=False)
    ui_sec_anim_camera_motion_head: BoolProperty(name="Head", default=True)
    ui_sec_anim_camera_motion_orbit: BoolProperty(name="Orbit", default=False)
    ui_sec_anim_camera_motion_guide: BoolProperty(name="Motion Guide", default=False)
    ui_sec_anim_camera_tools: BoolProperty(name="Camera Tools", default=True)

    def draw(self, _context: Context) -> None:
        from . import addon_updater

        layout = self.layout
        layout.label(text="Sidebar UI state is saved automatically (tabs and sections).")
        layout.separator()
        layout.prop(self, "pipeline_project_root")
        layout.separator()
        addon_updater.draw_preferences(layout)


_SECTION_PROP_BY_PANEL_ID = {
    "monofx_anim_camera_setup": "ui_sec_anim_camera_setup",
    "monofx_anim_camera_vertigo": "ui_sec_anim_camera_vertigo",
    "monofx_anim_camera_root": "ui_sec_anim_camera_root",
    "monofx_anim_camera_aim": "ui_sec_anim_camera_aim",
    "monofx_anim_camera_orbit": "ui_sec_anim_camera_orbit",
    "monofx_anim_camera_orbit_display": "ui_sec_anim_camera_orbit_display",
    "monofx_anim_camera_motion": "ui_sec_anim_camera_motion",
    "monofx_anim_camera_motion_render": "ui_sec_anim_camera_motion_render",
    "monofx_anim_camera_motion_mount": "ui_sec_anim_camera_motion_mount",
    "monofx_anim_camera_motion_track": "ui_sec_anim_camera_motion_track",
    "monofx_anim_camera_motion_head": "ui_sec_anim_camera_motion_head",
    "monofx_anim_camera_motion_orbit": "ui_sec_anim_camera_motion_orbit",
    "monofx_anim_camera_motion_guide": "ui_sec_anim_camera_motion_guide",
    "monofx_anim_camera_rig_tools": "ui_sec_anim_camera_rig_tools",
    "monofx_anim_camera_tools": "ui_sec_anim_camera_tools",
}


def get_addon_prefs(context: Optional[Context] = None) -> Optional[MonoFXPipelinePreferences]:
    ctx = context or bpy.context
    try:
        mod = ctx.preferences.addons.get(__package__)
    except Exception:
        return None
    if mod is None:
        return None
    return mod.preferences


def section_prop_for_panel_id(panel_id: str) -> Optional[str]:
    return _SECTION_PROP_BY_PANEL_ID.get(panel_id)
