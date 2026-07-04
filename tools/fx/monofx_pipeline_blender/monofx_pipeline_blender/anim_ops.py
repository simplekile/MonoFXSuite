"""
Animation tool operators.
"""

from __future__ import annotations

import bpy
from bpy.types import Context, Operator

from . import anim_camera
from . import anim_pose
from . import anim_transform
from .anim_camera import resolve_view3d
from . import anim_collections
from . import anim_keys_bpy
from .pipeline_common.anim_chains import chain_members_from_hierarchy
from bpy.props import EnumProperty, StringProperty


def _pipeline_props(context: Context):
    return context.scene.monofx_pipeline_blender_props


class MONOFX_OT_anim_toggle_aim_to_cursor(Operator):
    bl_idname = "wm.mono_fx_anim_toggle_aim_to_cursor"
    bl_label = "Aim to Cursor"
    bl_description = "Toggle live aim sync to 3D cursor"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        props.anim_camera_aim_to_cursor = not bool(props.anim_camera_aim_to_cursor)
        return {"FINISHED"}


class MONOFX_OT_anim_toggle_root_to_cursor(Operator):
    bl_idname = "wm.mono_fx_anim_toggle_root_to_cursor"
    bl_label = "Root to Cursor"
    bl_description = "Toggle live root sync to 3D cursor ({cam}_root)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        props.anim_camera_root_to_cursor = not bool(props.anim_camera_root_to_cursor)
        return {"FINISHED"}


class MONOFX_OT_anim_toggle_enable_orbit(Operator):
    bl_idname = "wm.mono_fx_anim_toggle_enable_orbit"
    bl_label = "Enable Orbit"
    bl_description = (
        "Enable orbit pivot, orbit display, and Mount to Orbit; "
        "creates missing orbit / viz parts when turned on"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        return anim_camera.active_rig_parts(context) is not None

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        props.anim_camera_orbit_follow_aim = not bool(props.anim_camera_orbit_follow_aim)
        return {"FINISHED"}


class MONOFX_OT_anim_toggle_body_orbit_constraint(Operator):
    bl_idname = "wm.mono_fx_anim_toggle_body_orbit_constraint"
    bl_label = "Mount to Orbit"
    bl_description = "Toggle Child Of mount → orbit pivot (set inverse when enabled)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        return anim_camera.active_rig_parts(context) is not None

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        props.anim_camera_body_orbit_constraint = not bool(
            props.anim_camera_body_orbit_constraint
        )
        return {"FINISHED"}


class MONOFX_OT_anim_create_shot_collections(Operator):
    bl_idname = "wm.mono_fx_anim_create_shot_collections"
    bl_label = "Create Shot Collections"
    bl_description = "Create Anim_<shot> with Characters, Cameras, Props, Environment, Lighting"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        if not bpy.data.filepath:
            self.report(
                {"ERROR"},
                "Save the .blend under a shot path (e.g. .../02_shots/sh001/01_anim/...).",
            )
            return {"CANCELLED"}

        shot = anim_collections.detect_shot_from_blend_filepath(bpy.data.filepath)
        if not shot:
            self.report(
                {"ERROR"},
                "Could not detect shot token (sh###) in file path.",
            )
            return {"CANCELLED"}

        ok, msg, _root = anim_collections.create_shot_collections(context.scene, shot)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_fix_shot_collections(Operator):
    bl_idname = "wm.mono_fx_anim_fix_shot_collections"
    bl_label = "Name Fixer"
    bl_description = "Rename Anim_<shot> root and child collections to match the file path shot"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        if not bpy.data.filepath:
            self.report(
                {"ERROR"},
                "Save the .blend under a shot path (e.g. .../02_shots/sh001/01_anim/...).",
            )
            return {"CANCELLED"}

        shot = anim_collections.detect_shot_from_blend_filepath(bpy.data.filepath)
        if not shot:
            self.report(
                {"ERROR"},
                "Could not detect shot token (sh###) in file path.",
            )
            return {"CANCELLED"}

        ok, msg = anim_collections.fix_shot_collection_names(context.scene, shot)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


def _bone_hierarchy_maps(arm: bpy.types.Object) -> tuple[dict[str, str | None], dict[str, list[str]]]:
    parent_of: dict[str, str | None] = {}
    children_of: dict[str, list[str]] = {}
    for pb in arm.pose.bones:
        parent_of[pb.name] = pb.parent.name if pb.parent else None
        children_of.setdefault(pb.name, [])
    for pb in arm.pose.bones:
        if pb.parent is not None:
            children_of.setdefault(pb.parent.name, []).append(pb.name)
    return parent_of, children_of


class MONOFX_OT_anim_select_chain(Operator):
    bl_idname = "wm.mono_fx_anim_select_chain"
    bl_label = "Select Chain"
    bl_description = "Select all connected parent and child bones in the same hierarchy chain"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        obj = context.active_object
        return (
            obj is not None
            and obj.type == "ARMATURE"
            and context.mode == "POSE"
            and bool(context.selected_pose_bones)
        )

    def execute(self, context: Context) -> set[str]:
        arm = context.active_object
        selected = list(context.selected_pose_bones)
        if not selected:
            self.report({"WARNING"}, "No pose bones selected.")
            return {"CANCELLED"}

        seed = selected[-1].name
        parent_of, children_of = _bone_hierarchy_maps(arm)
        members = chain_members_from_hierarchy(seed, parent_of, children_of)
        if not members:
            self.report({"WARNING"}, f"No chain found for {seed}.")
            return {"CANCELLED"}

        anim_pose.deselect_all_pose_bones(arm)
        anim_pose.select_pose_bones_by_name(arm, members)

        if members:
            active_pb = arm.pose.bones.get(members[0])
            anim_pose.set_active_pose_bone(context, arm, active_pb)

        self.report({"INFO"}, f"Selected chain: {len(members)} bone(s).")
        return {"FINISHED"}


class MONOFX_OT_anim_select_keyed_objects(Operator):
    bl_idname = "wm.mono_fx_anim_select_keyed_objects"
    bl_label = "Select Keyed Objects"
    bl_description = "Select all objects in the scene that have keyframes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        keyed = anim_keys_bpy.iter_scene_keyed_objects()
        bpy.ops.object.select_all(action="DESELECT")
        view_layer = context.view_layer
        selected_count = 0
        for obj in keyed:
            try:
                obj.select_set(True)
                selected_count += 1
            except Exception:
                pass

        if keyed:
            try:
                view_layer.objects.active = keyed[0]
            except Exception:
                pass

        self.report({"INFO"}, f"Selected {selected_count} keyed object(s).")
        return {"FINISHED"}


class MONOFX_OT_anim_copy_world_transform(Operator):
    bl_idname = "wm.mono_fx_anim_copy_world_transform"
    bl_label = "Copy World Transform"
    bl_description = (
        "Copy world transform from the active pose bone (Pose Mode) "
        "or active object (Object Mode); constraints included"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        if context.mode == "POSE":
            return (
                context.active_pose_bone is not None
                and context.active_object is not None
                and context.active_object.type == "ARMATURE"
            )
        return context.active_object is not None

    def execute(self, context: Context) -> set[str]:
        ok, msg = anim_transform.copy_world_transform(context)
        if not ok:
            self.report({"WARNING"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_paste_world_transform(Operator):
    bl_idname = "wm.mono_fx_anim_paste_world_transform"
    bl_label = "Paste World Transform"
    bl_description = (
        "Paste copied world transform onto selected pose bones (Pose Mode) "
        "or selected object(s) (Object Mode)"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        return anim_transform.can_paste_world_transform(context)

    def execute(self, context: Context) -> set[str]:
        ok, msg, _count = anim_transform.paste_world_transform(context)
        if not ok:
            self.report({"WARNING"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_clean_static_keys(Operator):
    bl_idname = "wm.mono_fx_anim_clean_static_keys"
    bl_label = "Clean Static Keys"
    bl_description = "Remove single-key or static fcurves on selected objects"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        return bool(context.selected_objects)

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        removed, affected = anim_keys_bpy.clean_static_keys_on_objects(
            context.selected_objects,
            clean_single=bool(props.anim_clean_single_key),
            clean_static=bool(props.anim_clean_static_key),
        )
        self.report({"INFO"}, f"Removed {removed} fcurve(s) from {affected} object(s).")
        return {"FINISHED"}


class MONOFX_OT_anim_camera_from_view(Operator):
    bl_idname = "wm.mono_fx_anim_camera_from_view"
    bl_label = "Camera from View"
    bl_description = "Create a camera from the active 3D View and name it cam_sh###"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        _area, region, space = resolve_view3d(context)
        return region is not None and space is not None

    def execute(self, context: Context) -> set[str]:
        ok, msg, _cam = anim_camera.create_camera_from_view(context)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_name_fixer(Operator):
    bl_idname = "wm.mono_fx_anim_name_fixer"
    bl_label = "Cam Rig Fixer"
    bl_description = (
        "Fix the camera rig selected in Setup: rename to cam_sh###, "
        "repair rig empty names and missing parts (orbit viz, track aim, …)"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return anim_camera.resolve_active_rig_camera(context, props=props) is not None

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        if cam is None or cam.type != "CAMERA":
            self.report({"ERROR"}, "Select a camera rig in Setup.")
            return {"CANCELLED"}

        shot = anim_camera.resolve_shot_for_camera(context)
        anim_collections.fix_shot_collection_names(context.scene, shot)
        new_name, names_changed, repairs = anim_camera.fix_camera_rig(cam, shot, context)
        anim_camera.link_camera_to_shot_collection(context.scene, cam, shot)
        anim_camera.set_active_camera_rig(context, cam)
        detail_parts: list[str] = []
        if names_changed:
            detail_parts.append("names")
        if repairs:
            detail_parts.append(", ".join(repairs))
        if detail_parts:
            self.report({"INFO"}, f"Cam rig fixer: {new_name} ({'; '.join(detail_parts)})")
        else:
            self.report({"INFO"}, f"Cam rig fixer: {new_name} (ok)")
        return {"FINISHED"}


class MONOFX_OT_anim_copy_camera_rig(Operator):
    bl_idname = "wm.mono_fx_anim_copy_camera_rig"
    bl_label = "Copy Rig"
    bl_description = (
        "Copy the full camera rig hierarchy to clipboard (Ctrl+C), "
        "including orbit viz / arrow objects that are not selectable"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return anim_camera.resolve_active_rig_camera(context, props=props) is not None

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        if cam is None:
            self.report({"ERROR"}, "Select a camera rig in Setup.")
            return {"CANCELLED"}
        ok, msg = anim_camera.copy_camera_rig_to_clipboard(context, cam)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_duplicate_camera_rig(Operator):
    bl_idname = "wm.mono_fx_anim_duplicate_camera_rig"
    bl_label = "Duplicate Rig"
    bl_description = (
        "Duplicate the camera rig selected in Setup in place; "
        "assigns the next cam_sh###_## name"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return anim_camera.resolve_active_rig_camera(context, props=props) is not None

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        if cam is None:
            self.report({"ERROR"}, "Select a camera rig in Setup.")
            return {"CANCELLED"}
        ok, msg, _new_cam = anim_camera.duplicate_camera_rig(context, cam)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_rename_camera_rig(Operator):
    bl_idname = "wm.mono_fx_anim_rename_camera_rig"
    bl_label = "Rename Rig"
    bl_description = (
        "Rename the camera rig selected in Setup and matching rig empties "
        "(cam_sh010, cam_sh010_02, cam_shot_2 → cam_shot_02, …)"
    )
    bl_options = {"REGISTER", "UNDO"}

    new_camera_name: StringProperty(
        name="Camera Name",
        description="New camera object name",
        default="cam_sh010",
    )

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return anim_camera.resolve_active_rig_camera(context, props=props) is not None

    def invoke(self, context: Context, event) -> set[str]:
        cam = anim_camera.resolve_active_rig_camera(
            context,
            props=context.scene.monofx_pipeline_blender_props,
        )
        if cam is not None:
            self.new_camera_name = cam.name
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context: Context) -> None:
        self.layout.prop(self, "new_camera_name", text="Camera Name")

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        if cam is None:
            self.report({"ERROR"}, "Select a camera rig in Setup.")
            return {"CANCELLED"}
        ok, msg = anim_camera.rename_camera_rig(context, cam, self.new_camera_name)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, f"Renamed rig: {msg}")
        return {"FINISHED"}


class MONOFX_OT_anim_select_scene_camera(Operator):
    bl_idname = "wm.mono_fx_anim_select_scene_camera"
    bl_label = "Select Scene Camera"
    bl_description = "Select the active scene camera"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        return context.scene.camera is not None

    def execute(self, context: Context) -> set[str]:
        ok, msg, _cam = anim_camera.select_scene_camera(context)
        if not ok:
            self.report({"WARNING"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_select_camera_rig(Operator):
    bl_idname = "wm.mono_fx_anim_select_camera_rig"
    bl_label = "Select Camera Rig"
    bl_description = (
        "Select the full camera rig hierarchy for the rig chosen in Setup "
        "(root, mount, head, camera, aim, orbit viz, …)"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return anim_camera.resolve_active_rig_camera(context, props=props) is not None

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        if cam is None:
            self.report({"ERROR"}, "Select a camera rig in Setup.")
            return {"CANCELLED"}
        ok, msg, _cam = anim_camera.select_camera_rig(context, cam)
        if not ok:
            self.report({"WARNING"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_clean_camera_rig_keys(Operator):
    bl_idname = "wm.mono_fx_anim_clean_camera_rig_keys"
    bl_label = "Clean Rig Keyframes"
    bl_description = (
        "Remove all keyframes on every object in the camera rig selected in Setup "
        "(root, mount, head, camera, aim, orbit viz, focal length on camera data, …)"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return anim_camera.resolve_active_rig_camera(context, props=props) is not None

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        if cam is None:
            self.report({"ERROR"}, "Select a camera rig in Setup.")
            return {"CANCELLED"}
        ok, msg, _counts = anim_camera.clean_camera_rig_keyframes(cam)
        if not ok:
            self.report({"WARNING"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_setup_camera_rig(Operator):
    bl_idname = "wm.mono_fx_anim_setup_camera_rig"
    bl_label = "Setup Camera Rig"
    bl_description = (
        "Build camera rig; if no camera exists, creates one at the current view, "
        "3D cursor, or origin first"
    )
    bl_options = {"REGISTER", "UNDO"}

    create_camera_location: EnumProperty(
        name="Create Camera At",
        items=[
            ("VIEW", "Current View", "Create camera from the active 3D View"),
            ("CURSOR", "3D Cursor", "Create camera at the 3D cursor"),
            ("ORIGIN", "Origin", "Create camera at world origin (0,0,0)"),
        ],
        default="VIEW",
    )

    @classmethod
    def poll(cls, context: Context) -> bool:
        return context.scene is not None

    def invoke(self, context: Context, event) -> set[str]:
        obj = context.active_object
        cam = obj if (obj is not None and obj.type == "CAMERA") else context.scene.camera
        if cam is None:
            return context.window_manager.invoke_props_dialog(self)
        return self.execute(context)

    def execute(self, context: Context) -> set[str]:
        obj = context.active_object
        cam = obj if (obj is not None and obj.type == "CAMERA") else context.scene.camera
        if cam is None:
            if self.create_camera_location == "VIEW":
                ok, msg, cam = anim_camera.create_camera_from_view(context)
            else:
                ok, msg, cam = anim_camera.create_camera_at_cursor_or_origin(
                    context,
                    at_cursor=(self.create_camera_location == "CURSOR"),
                )
            if not ok or cam is None:
                self.report({"ERROR"}, msg)
                return {"CANCELLED"}

        ok, msg, _rig = anim_camera.setup_camera_rig(cam)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_toggle_rig_pose_lock(Operator):
    bl_idname = "wm.mono_fx_anim_toggle_rig_pose_lock"
    bl_label = "Locked / Unlocked"
    bl_description = (
        "Toggle camera lock. Unlocked: adjust the camera or use Viewport to Camera. "
        "Locked: bake the pose onto the rig and lock the camera object"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return anim_camera.resolve_active_rig_camera(context, props=props) is not None

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        ok, msg, _obj = anim_camera.toggle_rig_pose_lock(context, cam)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_bake_rig_pose(Operator):
    bl_idname = "wm.mono_fx_anim_bake_rig_pose"
    bl_label = "Locked"
    bl_description = "Bake the camera pose onto the rig and lock the camera object"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        return cam is not None and not anim_camera.is_rig_pose_locked(cam)

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        ok, msg, _body = anim_camera.bake_rig_pose(context, cam)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_viewport_to_camera_rig(Operator):
    bl_idname = "wm.mono_fx_anim_viewport_to_camera_rig"
    bl_label = "Viewport to Camera"
    bl_description = (
        "Match the camera rig selected in Setup to the active 3D View: "
        "position, rotation, focal length, clip range, and film gate shift. "
        "Available while the rig pose is unlocked"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        if cam is None:
            return False
        if anim_camera.is_rig_pose_locked(cam):
            return False
        _area, region, space = resolve_view3d(context)
        return region is not None and space is not None

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        if cam is None:
            self.report({"ERROR"}, "Select a camera rig in Setup.")
            return {"CANCELLED"}
        ok, msg, _body = anim_camera.copy_viewport_to_camera_rig(context, cam)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_orbit_to_cursor(Operator):
    bl_idname = "wm.mono_fx_anim_orbit_to_cursor"
    bl_label = "Orbit to Cursor"
    bl_description = "Snap orbit pivot to the 3D cursor"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        if anim_camera.active_rig_parts(context) is not None:
            return True
        return anim_camera.find_camera_rig_parts(context.active_object) is not None

    def execute(self, context: Context) -> set[str]:
        ok, msg, _orbit = anim_camera.orbit_to_cursor(context, context.active_object)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_orbit_to_aim(Operator):
    bl_idname = "wm.mono_fx_anim_orbit_to_aim"
    bl_label = "Orbit to Aim"
    bl_description = "Snap orbit pivot to aim (used as orbit pivot for mount Child Of)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        return anim_camera.find_camera_rig_parts(context.active_object) is not None

    def execute(self, context: Context) -> set[str]:
        ok, msg, _orbit = anim_camera.orbit_to_aim(context, context.active_object)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_anim_camera_motion_path_to_curve(Operator):
    bl_idname = "wm.mono_fx_anim_camera_motion_path_to_curve"
    bl_label = "Motion Path to Curve"
    bl_description = (
        "Sample the camera world path over the scene playback range and "
        "create or update a poly curve named {cam}_motion_path"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return anim_camera.resolve_active_rig_camera(context, props=props) is not None

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        cam = anim_camera.resolve_active_rig_camera(context, props=props)
        if cam is None:
            self.report({"ERROR"}, "No camera available.")
            return {"CANCELLED"}
        ok, msg, _path = anim_camera.camera_motion_path_to_curve(context, cam)
        if not ok:
            self.report({"ERROR"}, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


def _make_focal_preset_operator(lens_mm: float, label: str, tooltip: str) -> type[Operator]:
    lens_value = float(lens_mm)
    short_label = (label or "").strip()
    tooltip_text = (tooltip or short_label).strip()
    op_id = anim_camera.focal_preset_operator_id(lens_value)
    button_text = (
        f"{int(lens_value)}"
        if abs(lens_value - round(lens_value)) < 1e-6
        else f"{lens_value:g}"
    )

    class Op(Operator):
        bl_idname = op_id
        bl_label = f"{button_text} mm"
        bl_description = tooltip_text
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context: Context) -> set[str]:
            anim_camera.apply_focal_length_mm(context, lens_value)
            if short_label:
                self.report({"INFO"}, f"Focal length: {lens_value:g} mm — {short_label}")
            else:
                self.report({"INFO"}, f"Focal length: {lens_value:g} mm")
            return {"FINISHED"}

    Op.__name__ = f"MONOFX_OT_anim_focal_{button_text.replace('.', '_')}"
    return Op


FOCAL_PRESET_OPERATOR_CLASSES = tuple(
    _make_focal_preset_operator(lens_mm, label, tooltip)
    for lens_mm, label, tooltip in anim_camera.CINEMATIC_FOCAL_LENGTH_PRESETS
)


ANIM_OPERATOR_CLASSES = (
    MONOFX_OT_anim_toggle_aim_to_cursor,
    MONOFX_OT_anim_toggle_root_to_cursor,
    MONOFX_OT_anim_toggle_enable_orbit,
    MONOFX_OT_anim_toggle_body_orbit_constraint,
    MONOFX_OT_anim_create_shot_collections,
    MONOFX_OT_anim_fix_shot_collections,
    MONOFX_OT_anim_select_chain,
    MONOFX_OT_anim_select_keyed_objects,
    MONOFX_OT_anim_copy_world_transform,
    MONOFX_OT_anim_paste_world_transform,
    MONOFX_OT_anim_clean_static_keys,
    MONOFX_OT_anim_camera_from_view,
    MONOFX_OT_anim_name_fixer,
    MONOFX_OT_anim_copy_camera_rig,
    MONOFX_OT_anim_duplicate_camera_rig,
    MONOFX_OT_anim_rename_camera_rig,
    MONOFX_OT_anim_select_scene_camera,
    MONOFX_OT_anim_select_camera_rig,
    MONOFX_OT_anim_clean_camera_rig_keys,
    MONOFX_OT_anim_setup_camera_rig,
    MONOFX_OT_anim_toggle_rig_pose_lock,
    MONOFX_OT_anim_bake_rig_pose,
    MONOFX_OT_anim_viewport_to_camera_rig,
    MONOFX_OT_anim_camera_motion_path_to_curve,
    MONOFX_OT_anim_orbit_to_aim,
    MONOFX_OT_anim_orbit_to_cursor,
    *FOCAL_PRESET_OPERATOR_CLASSES,
)
