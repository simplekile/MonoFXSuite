"""
Camera from viewport and camera rig setup.
"""

from __future__ import annotations

import math
from mathutils import Matrix, Vector
from typing import Dict, List, Optional, Tuple

import bpy

from . import anim_collections
from . import anim_keys_bpy
from monofx_pipeline_common.camera_naming import (
    _CAMERA_RIG_PART_KEYS,
    camera_name_from_rig_part,
    camera_rig_names,
    iter_camera_rig_object_names,
    iter_rig_part_name_candidates,
    next_camera_name,
    normalize_shot_token,
    normalize_camera_rename_name,
    resolve_name_fixer_camera_name,
    rig_part_suffix_matches,
)
from .pipeline_common.camera_rig_pose import compute_head_rotation_euler_from_camera

AIM_ROTATION_MODE = "ZXY"
TRACK_AIM_CONSTRAINT_NAME = "Track Aim"
ORBIT_PIVOT_DISPLAY_SIZE = 0.2
ORBIT_VIZ_NAME_SUFFIX = "_viz"
ORBIT_VIZ_ARROW_SUFFIX = "_arrow"
ORBIT_VIZ_ARROW_COUNT = 8
ORBIT_VIZ_CIRCLE_DISPLAY_SIZE = 1.0
ORBIT_VIZ_ARROW_RADIUS_FACTOR = 1.1
ORBIT_VIZ_ARROW_MAIN_SIZE = 0.08
ORBIT_VIZ_ARROW_SEC_SIZE = 0.05
_DEFAULT_CAMERA_FORWARD = Vector((0.0, -1.0, 0.0))


def _deselect_all_objects(view_layer: Optional[bpy.types.ViewLayer]) -> None:
    """Deselect without bpy.ops — safe from sidebar / UI region context."""
    if view_layer is None:
        return
    for obj in view_layer.objects:
        try:
            obj.select_set(False)
        except RuntimeError:
            pass


# Motion Guide + tooltips: (UI control, on-set move, rig empty · channel)
CAMERA_RIG_LAYERS: Tuple[str, ...] = (
    "Root · {cam}_root — floor position (world XY)",
    "Aim · {cam}_aim — look target position",
    "Orbit pivot · {cam}_orbit — orbit yaw (+ {cam}_orbit_viz ring)",
    "Mount · {cam}_mount — pedestal, floor track, crane tilt",
    "Boom · {cam}_boom — jib reach; Track Aim constraint → aim",
    "Head · {cam}_head — fluid-head layer (dolly / truck / pan / tilt / roll)",
    "Camera · {cam} — lens body",
)

CAMERA_MOTION_GUIDE: Tuple[Tuple[str, str, str], ...] = (
    (
        "Track Aim",
        "Boom keeps camera locked on aim during pedestal / track / boom",
        "{cam}_boom · constraint Track Aim → {cam}_aim",
    ),
    (
        "Pedestal",
        "Pedestal up / down — vertical column (translate, not tilt)",
        "{cam}_mount · location Z",
    ),
    (
        "Crane Boom",
        "Extend / retract jib arm toward subject",
        "{cam}_boom · location Z",
    ),
    (
        "Crane Tilt",
        "Tilt jib arm up / down — changes framing (not pedestal)",
        "{cam}_mount · rotation X",
    ),
    (
        "Track Dolly",
        "Dolly in / out on floor rails (stage move)",
        "{cam}_mount · location Y",
    ),
    (
        "Track Truck",
        "Crab left / right on floor track (stage move)",
        "{cam}_mount · location X",
    ),
    (
        "Dolly",
        "Lens push in / out along view axis (head move)",
        "{cam}_head · location Z",
    ),
    (
        "Truck",
        "Slide left / right in frame (head move)",
        "{cam}_head · location X",
    ),
    (
        "Pan",
        "Pan fluid head left / right (yaw on head)",
        "{cam}_head · rotation Y",
    ),
    (
        "Tilt",
        "Pitch camera head up / down (fluid head)",
        "{cam}_head · rotation X",
    ),
    (
        "Roll",
        "Dutch angle — roll head left / right",
        "{cam}_head · rotation Z",
    ),
    (
        "Orbit",
        "Yaw rig around orbit pivot (not Head Pan)",
        "{cam}_orbit · rotation Z",
    ),
    (
        "Mount to Orbit",
        "Mount rides orbit pivot (Child Of)",
        "{cam}_mount · Child Of → {cam}_orbit",
    ),
    (
        "Root to Cursor",
        "Move rig root on floor plane",
        "{cam}_root · world XY",
    ),
    (
        "Aim to Cursor",
        "Move look target only",
        "{cam}_aim · location",
    ),
)

# Full-frame spherical mm (Blender default sensor). (mm, short label, tooltip)
CINEMATIC_FOCAL_LENGTH_PRESETS: Tuple[Tuple[float, str, str], ...] = (
    (
        14.0,
        "Ultra wide",
        "14 mm ultra wide. Epic landscapes, cramped interiors, strong environmental scale. "
        "High edge distortion — use for impact, not subtle dialogue.",
    ),
    (
        18.0,
        "Wide",
        "18 mm wide. Classic establishing lens — opens the scene and shows context "
        "while keeping subjects readable. Common for location masters and steadicam.",
    ),
    (
        24.0,
        "Wide classic",
        "24 mm wide classic. Balances environment and character; versatile narrative coverage. "
        "Natural for two-shots, walk-and-talk, and handheld story beats.",
    ),
    (
        35.0,
        "Standard wide",
        "35 mm standard wide. Industry default for dialogue, walk-and-talk, and general coverage. "
        "Present and cinematic without obvious wide distortion.",
    ),
    (
        50.0,
        "Normal",
        "50 mm normal lens. Closest to human eye perspective — neutral, observational framing. "
        "Good for interviews, balanced singles, and understated composition.",
    ),
    (
        85.0,
        "Portrait",
        "85 mm portrait / short tele. Flattering close-ups with gentle background compression "
        "and subject separation. Classic for CU, singles, and emotional beats.",
    ),
    (
        135.0,
        "Telephoto",
        "135 mm telephoto. Strong compression, isolated subject, distant vantage. "
        "Detail shots, voyeur POV, stacked backgrounds, and shallow depth.",
    ),
)


def focal_preset_operator_id(lens_mm: float) -> str:
    if abs(lens_mm - round(lens_mm)) < 1e-6:
        return f"wm.mono_fx_anim_focal_{int(round(lens_mm))}"
    token = f"{lens_mm:g}".replace(".", "_")
    return f"wm.mono_fx_anim_focal_{token}"


def default_shot_camera_rotation_euler() -> Tuple[float, float, float]:
    """Horizontal camera facing -Y; avoids Blender default (0,0,0) looking straight down."""
    return _DEFAULT_CAMERA_FORWARD.to_track_quat("-Z", "Y").to_euler("XYZ")


def existing_camera_object_names() -> List[str]:
    return [obj.name for obj in bpy.data.objects if obj.type == "CAMERA"]


def scene_camera_object(scene: Optional[bpy.types.Scene]) -> Optional[bpy.types.Object]:
    cam = scene.camera if scene is not None else None
    if cam is not None and cam.type == "CAMERA":
        return cam
    return None


_syncing_active_rig = False


def _scene_pipeline_props(
    scene: Optional[bpy.types.Scene],
) -> Optional[bpy.types.PropertyGroup]:
    if scene is None:
        return None
    return getattr(scene, "monofx_pipeline_blender_props", None)


def list_scene_camera_rigs(
    context: Optional[bpy.types.Context] = None,
) -> List[bpy.types.Object]:
    ctx = context or bpy.context
    scene = ctx.scene if ctx else None
    if scene is None:
        return []
    rigs: List[bpy.types.Object] = []
    seen: set[str] = set()
    for obj in scene.objects:
        if obj.type != "CAMERA" or obj.name in seen:
            continue
        if find_camera_rig_parts(obj) is None:
            continue
        seen.add(obj.name)
        rigs.append(obj)
    rigs.sort(key=lambda item: item.name.lower())
    return rigs


def anim_camera_rig_enum_items(
    _self,
    context: bpy.types.Context,
) -> List[Tuple[str, str, str, str, int]]:
    items: List[Tuple[str, str, str, str, int]] = [
        ("NONE", "None", "No camera rig selected", "CAMERA_DATA", 0),
    ]
    if context is None:
        return items
    for index, cam in enumerate(list_scene_camera_rigs(context), start=1):
        items.append(
            (cam.name, cam.name, f"Camera rig {cam.name}", "OUTLINER_OB_CAMERA", index)
        )
    return items


def resolve_active_rig_camera(
    context: Optional[bpy.types.Context] = None,
    *,
    props: Optional[bpy.types.PropertyGroup] = None,
    scene: Optional[bpy.types.Scene] = None,
) -> Optional[bpy.types.Object]:
    sc = scene
    if sc is None and context is not None:
        sc = context.scene
    if props is None:
        props = _scene_pipeline_props(sc)
    if props is None:
        return None
    rig_id = str(getattr(props, "anim_camera_active_rig", "NONE") or "NONE")
    if rig_id == "NONE":
        return None
    cam = bpy.data.objects.get(rig_id)
    if cam is None or cam.type != "CAMERA":
        return None
    if find_camera_rig_parts(cam) is None:
        return None
    if sc is not None and cam.name not in sc.objects:
        return None
    return cam


def active_rig_parts(
    context: Optional[bpy.types.Context] = None,
) -> Optional[Dict[str, bpy.types.Object]]:
    return _rig_parts_for_scene_camera(context)


def reset_anim_camera_props_to_defaults(props: bpy.types.PropertyGroup) -> None:
    global _syncing_active_rig
    _syncing_active_rig = True
    try:
        props.anim_camera_focal_length_stored = 50.0
        props.anim_camera_body_track_stored = 0.0
        props.anim_camera_body_track_y_stored = 0.0
        props.anim_camera_body_height_stored = 0.0
        props.anim_camera_crane_angle_stored = 0.0
        props.anim_camera_crane_length_stored = 0.0
        props.anim_camera_motion_dolly_stored = 0.0
        props.anim_camera_motion_truck_stored = 0.0
        props.anim_camera_motion_pan_stored = 0.0
        props.anim_camera_motion_tilt_stored = 0.0
        props.anim_camera_motion_roll_stored = 0.0
        props.anim_camera_orbit_stored = 0.0
        props.anim_camera_vertigo = False
        props.anim_camera_vertigo_target = "BODY"
        props.anim_camera_track_aim = True
        props.anim_camera_orbit_follow_aim = False
        props.anim_camera_orbit_display_visible = True
        props.anim_camera_orbit_arrow_size = 0.5
        props.anim_camera_body_orbit_constraint = False
        props.anim_camera_aim_to_cursor = False
        props.anim_camera_aim_lock = False
        props.anim_camera_aim_distance_stored = 10.0
        props.anim_camera_root_to_cursor = False
        props.anim_camera_root_to_cursor_z = False
    finally:
        _syncing_active_rig = False


def _rig_track_aim_enabled(look: bpy.types.Object) -> bool:
    for constraint in look.constraints:
        if constraint.type != "TRACK_TO":
            continue
        if constraint.name != TRACK_AIM_CONSTRAINT_NAME and len(look.constraints) > 1:
            continue
        return not bool(getattr(constraint, "mute", False)) and float(constraint.influence) > 0.5
    for constraint in look.constraints:
        if constraint.type == "TRACK_TO":
            return not bool(getattr(constraint, "mute", False)) and float(constraint.influence) > 0.5
    return True


def _rig_body_orbit_constraint_enabled(
    body: bpy.types.Object,
    orbit: bpy.types.Object,
) -> bool:
    for constraint in body.constraints:
        if constraint.type != "CHILD_OF" or constraint.target != orbit:
            continue
        return not bool(getattr(constraint, "mute", False)) and float(constraint.influence) > 0.5
    return False


def sync_anim_camera_props_from_rig(
    props: bpy.types.PropertyGroup,
    parts: Dict[str, bpy.types.Object],
) -> None:
    global _syncing_active_rig
    cam = parts["cam"]
    body = parts["body"]
    look = parts["look"]
    motion = parts["motion"]
    orbit = parts.get("orbit")

    _syncing_active_rig = True
    try:
        if cam.data is not None:
            props.anim_camera_focal_length_stored = float(cam.data.lens)
        props.anim_camera_body_track_stored = float(body.location.x)
        props.anim_camera_body_track_y_stored = float(body.location.y)
        props.anim_camera_body_height_stored = float(body.location.z)
        _ensure_euler_xyz(body)
        props.anim_camera_crane_angle_stored = float(body.rotation_euler.x)
        props.anim_camera_crane_length_stored = float(look.location.z)
        _ensure_euler_xyz(motion)
        props.anim_camera_motion_truck_stored = float(motion.location.x)
        props.anim_camera_motion_dolly_stored = float(motion.location.z)
        props.anim_camera_motion_pan_stored = float(motion.rotation_euler.y)
        props.anim_camera_motion_tilt_stored = float(motion.rotation_euler.x)
        props.anim_camera_motion_roll_stored = float(motion.rotation_euler.z)
        props.anim_camera_orbit_stored = _read_orbit_yaw(parts, stored=0.0)
        aim = parts.get("aim")
        if aim is not None:
            props.anim_camera_aim_distance_stored = _read_aim_distance(cam, aim)
        props.anim_camera_track_aim = _rig_track_aim_enabled(look)
        props.anim_camera_orbit_follow_aim = orbit is not None
        props.anim_camera_body_orbit_constraint = (
            orbit is not None and _rig_body_orbit_constraint_enabled(body, orbit)
        )
        if orbit is not None:
            props.anim_camera_orbit_display_visible = not bool(orbit.hide_viewport)
        ensure_rig_pose_lock_default(parts)
        if is_rig_pose_locked(cam):
            lock_rig_pose_transforms(parts)
    finally:
        _syncing_active_rig = False


def _set_scene_camera(
    context: bpy.types.Context,
    cam: bpy.types.Object,
) -> None:
    scene = context.scene
    if scene is None or cam is None or cam.type != "CAMERA":
        return
    if scene.camera != cam:
        scene.camera = cam


def set_active_camera_rig(
    context: bpy.types.Context,
    cam: bpy.types.Object,
) -> bool:
    parts = find_camera_rig_parts(cam)
    if parts is None or context.scene is None:
        return False
    props = context.scene.monofx_pipeline_blender_props
    global _syncing_active_rig
    _syncing_active_rig = True
    try:
        props.anim_camera_active_rig = cam.name
    finally:
        _syncing_active_rig = False
    _set_scene_camera(context, cam)
    sync_anim_camera_props_from_rig(props, parts)
    return True


def on_active_rig_changed(
    props: bpy.types.PropertyGroup,
    context: Optional[bpy.types.Context],
) -> None:
    global _syncing_active_rig
    if context is None or _syncing_active_rig:
        return
    cam = resolve_active_rig_camera(context, props=props)
    if cam is None:
        rig_id = str(getattr(props, "anim_camera_active_rig", "NONE") or "NONE")
        if rig_id != "NONE":
            _syncing_active_rig = True
            try:
                props.anim_camera_active_rig = "NONE"
            finally:
                _syncing_active_rig = False
        reset_anim_camera_props_to_defaults(props)
        return
    parts = find_camera_rig_parts(cam)
    if parts is None:
        reset_anim_camera_props_to_defaults(props)
        return
    _set_scene_camera(context, cam)
    sync_anim_camera_props_from_rig(props, parts)


def _auto_key_enabled(context: Optional[bpy.types.Context] = None) -> bool:
    ctx = context or bpy.context
    ts = getattr(ctx, "tool_settings", None)
    if ts is None:
        return False
    return bool(getattr(ts, "use_keyframe_insert_auto", False))


def _keyframe_object_location(
    obj: bpy.types.Object,
    *,
    context: Optional[bpy.types.Context] = None,
) -> None:
    if not _auto_key_enabled(context):
        return
    scene = (context or bpy.context).scene
    if scene is None:
        return
    try:
        obj.keyframe_insert(data_path="location", frame=int(scene.frame_current))
    except RuntimeError:
        pass


def _keyframe_camera_lens(
    cam: bpy.types.Object,
    *,
    context: Optional[bpy.types.Context] = None,
) -> None:
    if not _auto_key_enabled(context):
        return
    if cam.data is None:
        return
    scene = (context or bpy.context).scene
    if scene is None:
        return
    try:
        cam.data.keyframe_insert(data_path="lens", frame=int(scene.frame_current))
    except RuntimeError:
        pass


def _keyframe_object_rotation_euler_z(
    obj: bpy.types.Object,
    *,
    context: Optional[bpy.types.Context] = None,
) -> None:
    _keyframe_object_rotation_euler_index(obj, 2, context=context)


def _ensure_object_rotation_order(obj: bpy.types.Object) -> None:
    if obj.name.casefold().endswith("_aim"):
        _ensure_aim_rotation_order(obj)
    else:
        _ensure_euler_xyz(obj)


def _keyframe_object_rotation_euler_index(
    obj: bpy.types.Object,
    axis_index: int,
    *,
    context: Optional[bpy.types.Context] = None,
) -> None:
    if not _auto_key_enabled(context):
        return
    scene = (context or bpy.context).scene
    if scene is None:
        return
    _ensure_object_rotation_order(obj)
    try:
        obj.keyframe_insert(
            data_path="rotation_euler",
            index=int(axis_index),
            frame=int(scene.frame_current),
        )
    except RuntimeError:
        pass


def _keyframe_object_location_index(
    obj: bpy.types.Object,
    axis_index: int,
    *,
    context: Optional[bpy.types.Context] = None,
) -> None:
    if not _auto_key_enabled(context):
        return
    scene = (context or bpy.context).scene
    if scene is None:
        return
    try:
        obj.keyframe_insert(
            data_path="location",
            index=int(axis_index),
            frame=int(scene.frame_current),
        )
    except RuntimeError:
        pass


def _keyframe_object_rotation_euler(
    obj: bpy.types.Object,
    *,
    context: Optional[bpy.types.Context] = None,
) -> None:
    if not _auto_key_enabled(context):
        return
    if obj.name.casefold().endswith("_aim"):
        _ensure_aim_rotation_order(obj)
    else:
        _ensure_euler_xyz(obj)
    for axis_index in range(3):
        _keyframe_object_rotation_euler_index(obj, axis_index, context=context)


def _ensure_euler_xyz(obj: bpy.types.Object) -> None:
    if obj.rotation_mode != "XYZ":
        obj.rotation_mode = "XYZ"


def _ensure_aim_rotation_order(aim: bpy.types.Object) -> None:
    if aim.rotation_mode != AIM_ROTATION_MODE:
        aim.rotation_mode = AIM_ROTATION_MODE


def _reset_aim_transform(aim: bpy.types.Object) -> None:
    _ensure_aim_rotation_order(aim)
    aim.location = (0.0, 0.0, 0.0)
    aim.rotation_euler = (0.0, 0.0, 0.0)
    aim.scale = (1.0, 1.0, 1.0)


def _legacy_orbit_pivot(body: bpy.types.Object, root: bpy.types.Object) -> Optional[bpy.types.Object]:
    parent = body.parent
    if parent is None or parent == root:
        return None
    if parent.name.casefold().endswith("_orbit") or rig_part_suffix_matches(parent.name, "orbit"):
        return parent
    return None


def _resolve_orbit_empty(root: bpy.types.Object, orbit_name: str) -> Optional[bpy.types.Object]:
    obj = bpy.data.objects.get(orbit_name)
    if obj is not None:
        return obj
    for child in root.children:
        if rig_part_suffix_matches(child.name, "orbit"):
            return child
    return None


def _configure_rig_rotation_orders(parts: Dict[str, bpy.types.Object]) -> None:
    """
    Assign Euler orders / locks so motion UI maps to dedicated local axes.

    - mount (body): track truck ``location.x``, track dolly ``location.y``, pedestal ``location.z``, crane tilt ``rotation_euler.x``
    - aim: look target position only (rotation locked)
    - orbit: orbit yaw ``rotation_euler.z``
    - boom (look): crane boom ``location.z`` (TRACK_TO handles aim)
    - head (motion): truck ``location.x``, dolly ``location.z``, pan ``rotation_euler.y``, tilt ``rotation_euler.x``, roll ``rotation_euler.z``
    """
    root = parts.get("root")
    if root is not None:
        _ensure_euler_xyz(root)
        root.rotation_euler = (0.0, 0.0, 0.0)

    aim = parts.get("aim")
    if aim is not None:
        _configure_aim_empty(aim)
        _ensure_aim_rotation_order(aim)
        aim.lock_rotation = (True, True, True)

    orbit = parts.get("orbit")
    if orbit is not None:
        _ensure_orbit_pivot_locks(orbit)

    body = parts.get("body")
    if body is not None:
        _ensure_euler_xyz(body)
        body.lock_rotation = (False, True, True)

    look = parts.get("look")
    if look is not None:
        _ensure_euler_xyz(look)

    motion = parts.get("motion")
    if motion is not None:
        _ensure_euler_xyz(motion)
        motion.lock_rotation = (False, False, False)


def _ensure_motion_head_locks(parts: Optional[Dict[str, bpy.types.Object]]) -> None:
    """Unlock head pan / tilt / roll on rigs created before head pan existed."""
    motion = _rig_motion_object(parts, "motion")
    if motion is None:
        return
    want = (False, False, False)
    if tuple(motion.lock_rotation) != want:
        motion.lock_rotation = want


_TRANSFORM_LOCK_ALL = (True, True, True)
_TRANSFORM_UNLOCK_ALL = (False, False, False)
RIG_POSE_LOCKED_PROP = "monofx_rig_pose_locked"


def is_rig_pose_locked(cam: Optional[bpy.types.Object]) -> bool:
    """True when the rig is in baked / locked pose mode (camera not free to adjust)."""
    if cam is None:
        return True
    if RIG_POSE_LOCKED_PROP in cam:
        return bool(cam[RIG_POSE_LOCKED_PROP])
    return (
        all(cam.lock_location)
        and all(cam.lock_rotation)
        and all(cam.lock_scale)
    )


def _set_rig_pose_locked_flag(cam: bpy.types.Object, locked: bool) -> None:
    cam[RIG_POSE_LOCKED_PROP] = locked


def lock_rig_pose_transforms(parts: Dict[str, bpy.types.Object]) -> None:
    """Lock location, rotation, and scale on the rig camera object only."""
    cam = parts.get("cam")
    if cam is None:
        return
    cam.lock_location = _TRANSFORM_LOCK_ALL
    cam.lock_rotation = _TRANSFORM_LOCK_ALL
    cam.lock_scale = _TRANSFORM_LOCK_ALL
    _set_rig_pose_locked_flag(cam, True)


def unlock_rig_pose_transforms(
    parts: Dict[str, bpy.types.Object],
    *,
    context: Optional[bpy.types.Context] = None,
) -> Optional[bpy.types.Object]:
    """Unlock only the camera object so the artist can adjust framing before baking."""
    cam = parts.get("cam")
    if cam is None:
        return None
    cam.lock_location = _TRANSFORM_UNLOCK_ALL
    cam.lock_rotation = _TRANSFORM_UNLOCK_ALL
    cam.lock_scale = _TRANSFORM_UNLOCK_ALL
    _set_rig_pose_locked_flag(cam, False)
    ctx = context or bpy.context
    view_layer = ctx.view_layer
    try:
        _deselect_all_objects(view_layer)
        cam.select_set(True)
        if view_layer is not None:
            view_layer.objects.active = cam
    except Exception:
        pass
    return cam


def ensure_rig_pose_lock_default(parts: Dict[str, bpy.types.Object]) -> None:
    """Migrate legacy rigs: default to locked pose until explicitly unlocked."""
    cam = parts.get("cam")
    if cam is None:
        return
    if RIG_POSE_LOCKED_PROP not in cam:
        lock_rig_pose_transforms(parts)


def _ensure_orbit_pivot_locks(orbit: bpy.types.Object) -> None:
    _ensure_euler_xyz(orbit)
    want = (True, True, False)
    if tuple(orbit.lock_rotation) != want:
        orbit.lock_rotation = want


def _migrate_orbit_yaw_from_aim(parts: Optional[Dict[str, bpy.types.Object]]) -> None:
    """Move legacy orbit yaw keyed on aim → orbit pivot."""
    if parts is None:
        return
    aim = parts.get("aim")
    orbit = parts.get("orbit")
    if aim is None or orbit is None:
        return
    _ensure_aim_rotation_order(aim)
    _ensure_orbit_pivot_locks(orbit)
    aim_z = float(aim.rotation_euler[2])
    orbit_z = float(orbit.rotation_euler[2])
    if abs(aim_z) > 1e-8 and abs(orbit_z - aim_z) > 1e-6:
        orbit.rotation_euler[2] = aim_z
    if abs(float(aim.rotation_euler[2])) > 1e-8:
        aim.rotation_euler[2] = 0.0
    aim.lock_rotation = (True, True, True)


def _read_orbit_yaw(
    parts: Optional[Dict[str, bpy.types.Object]],
    *,
    stored: float = 0.0,
) -> float:
    """Read orbit yaw without mutating rig objects (safe in RNA getters)."""
    if parts is None:
        return float(stored)
    orbit = parts.get("orbit")
    if orbit is not None:
        orbit_z = float(orbit.rotation_euler[2])
        aim = parts.get("aim")
        if aim is not None and abs(orbit_z) < 1e-8:
            aim_z = float(aim.rotation_euler[2])
            if abs(aim_z) > 1e-8:
                return aim_z
        return orbit_z
    aim = parts.get("aim")
    if aim is not None:
        return float(aim.rotation_euler[2])
    return float(stored)


def _orient_aim_toward_camera(
    aim: bpy.types.Object,
    cam: bpy.types.Object,
    *,
    context: Optional[bpy.types.Context] = None,
) -> bool:
    """Point aim empty -Z at the scene camera (same axis as look TRACK_TO)."""
    direction = cam.matrix_world.translation - aim.matrix_world.translation
    if direction.length <= 1e-8:
        return False
    _ensure_aim_rotation_order(aim)
    aim.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler(AIM_ROTATION_MODE)
    _keyframe_object_rotation_euler(aim, context=context)
    return True


def _get_body_child_of(body: bpy.types.Object) -> Optional[bpy.types.ChildOfConstraint]:
    for constraint in body.constraints:
        if constraint.type == "CHILD_OF":
            return constraint
    return None


def _childof_set_inverse(
    context: bpy.types.Context,
    owner: bpy.types.Object,
    constraint: bpy.types.Constraint,
) -> None:
    view_layer = context.view_layer
    saved_active = view_layer.objects.active
    saved_selected = list(context.selected_objects)
    try:
        _deselect_all_objects(view_layer)
        owner.select_set(True)
        view_layer.objects.active = owner
        try:
            bpy.ops.constraint.childof_set_inverse(
                constraint=constraint.name,
                owner="OBJECT",
            )
        except TypeError:
            bpy.ops.constraint.childof_set_inverse(
                constraint=constraint.name,
                owner=owner.name,
            )
    except Exception:
        target = getattr(constraint, "target", None)
        if target is not None:
            constraint.inverse_matrix = (
                target.matrix_world.inverted() @ owner.matrix_world
            ).inverted()
    finally:
        _deselect_all_objects(view_layer)
        for obj in saved_selected:
            try:
                obj.select_set(True)
            except Exception:
                pass
        if saved_active is not None:
            try:
                view_layer.objects.active = saved_active
            except Exception:
                pass


def _ensure_body_child_of(
    body: bpy.types.Object,
    orbit: bpy.types.Object,
    context: bpy.types.Context,
    *,
    enabled: bool,
) -> bpy.types.ChildOfConstraint:
    child = _get_body_child_of(body)
    if child is None:
        child = body.constraints.new(type="CHILD_OF")
        child.name = "Mount to Orbit"
        child.target = orbit
    else:
        child.target = orbit
    child.influence = 1.0
    child.enabled = bool(enabled)
    if enabled:
        _childof_set_inverse(context, body, child)
    return child


def _migrate_legacy_orbit_pivot(
    parts: Dict[str, bpy.types.Object],
    context: bpy.types.Context,
) -> None:
    """Reparent body to root and remove obsolete ``*_orbit`` pivot empties."""
    root = parts.get("root")
    body = parts.get("body")
    if root is None or body is None:
        return
    orbit = _legacy_orbit_pivot(body, root)
    if orbit is None:
        return
    body_mw = body.matrix_world.copy()
    for constraint in list(orbit.constraints):
        if constraint.type == "CHILD_OF":
            orbit.constraints.remove(constraint)
    body.parent = root
    body.matrix_world = body_mw
    try:
        bpy.data.objects.remove(orbit, do_unlink=True)
    except Exception:
        pass


def _sync_orbit_empty_visibility(
    orbit: bpy.types.Object,
    *,
    visible: bool,
) -> None:
    show = bool(visible)
    orbit.hide_viewport = not show
    orbit.hide_select = False
    viz = _find_orbit_viz(orbit)
    if viz is not None:
        viz.hide_viewport = not show
        viz.hide_select = True
        if hasattr(viz, "show_in_front"):
            viz.show_in_front = show
        for arrow in _iter_orbit_viz_arrows(viz):
            arrow.hide_viewport = not show
            arrow.hide_select = True
            if hasattr(arrow, "show_in_front"):
                arrow.show_in_front = show


def _orbit_viz_object_name(orbit_name: str) -> str:
    return f"{orbit_name}{ORBIT_VIZ_NAME_SUFFIX}"


def _find_orbit_viz(orbit: bpy.types.Object) -> Optional[bpy.types.Object]:
    expected = _orbit_viz_object_name(orbit.name)
    obj = bpy.data.objects.get(expected)
    if obj is not None and obj.parent == orbit:
        return obj
    suffix = ORBIT_VIZ_NAME_SUFFIX.casefold()
    for child in orbit.children:
        if child.name.casefold().endswith(suffix):
            return child
    return None


def _orbit_viz_arrow_object_name(viz_name: str, index: int) -> str:
    return f"{viz_name}{ORBIT_VIZ_ARROW_SUFFIX}_{index:02d}"


def _iter_orbit_viz_arrows(viz: bpy.types.Object) -> List[bpy.types.Object]:
    prefix = f"{viz.name}{ORBIT_VIZ_ARROW_SUFFIX}_"
    arrows: List[bpy.types.Object] = []
    for child in viz.children:
        if child.name.startswith(prefix):
            arrows.append(child)
    arrows.sort(key=lambda obj: obj.name)
    return arrows


def _remove_orphan_orbit_viz_arrows(viz: bpy.types.Object) -> None:
    expected = {
        _orbit_viz_arrow_object_name(viz.name, index)
        for index in range(ORBIT_VIZ_ARROW_COUNT)
    }
    prefix = f"{viz.name}{ORBIT_VIZ_ARROW_SUFFIX}_"
    for child in list(viz.children):
        if not child.name.startswith(prefix):
            continue
        if child.name in expected:
            continue
        try:
            bpy.data.objects.remove(child, do_unlink=True)
        except Exception:
            pass


def _orbit_arrow_size_from_context(context: Optional[bpy.types.Context]) -> float:
    if context is None:
        return 1.0
    props = getattr(context.scene, "monofx_pipeline_blender_props", None)
    if props is None:
        return 1.0
    return max(float(getattr(props, "anim_camera_orbit_arrow_size", 0.5)), 0.01)


def _orbit_display_visible_from_context(context: Optional[bpy.types.Context]) -> bool:
    if context is None:
        return True
    props = getattr(context.scene, "monofx_pipeline_blender_props", None)
    if props is None:
        return True
    return bool(getattr(props, "anim_camera_orbit_display_visible", True))


def refresh_orbit_display(
    context: bpy.types.Context,
    *,
    props: Optional[bpy.types.PropertyGroup] = None,
) -> None:
    parts = _rig_parts_for_scene_camera(context)
    if parts is None:
        return
    orbit = parts.get("orbit")
    body = parts.get("body")
    if orbit is None or body is None:
        return
    coll = _orbit_rig_collection(parts, context)
    _ensure_orbit_viz_empty(orbit, body, coll, context=context)
    if props is None:
        props = context.scene.monofx_pipeline_blender_props
    visible = bool(getattr(props, "anim_camera_orbit_display_visible", True))
    _sync_orbit_empty_visibility(orbit, visible=visible)


def _orbit_viz_arrow_rotation(angle: float) -> Tuple[float, float, float]:
    """Orient cone +Z outward in viz local XZ (ring plane)."""
    radial = Vector((math.cos(angle), 0.0, math.sin(angle)))
    if radial.length < 1e-8:
        return (0.0, 0.0, 0.0)
    radial.normalize()
    tangent = Vector((-math.sin(angle), 0.0, math.cos(angle)))
    y = radial.cross(tangent)
    if y.length < 1e-8:
        y = Vector((0.0, 1.0, 0.0))
    else:
        y.normalize()
    rot_mat = Matrix(
        (
            (tangent.x, y.x, radial.x),
            (tangent.y, y.y, radial.y),
            (tangent.z, y.z, radial.z),
        )
    )
    extra_x = Matrix.Rotation(math.pi / 2.0, 3, "X")
    return (rot_mat @ extra_x).to_euler("XYZ")


def _ensure_orbit_viz_arrows(
    viz: bpy.types.Object,
    target_coll: bpy.types.Collection,
    *,
    arrow_size: float = 1.0,
) -> None:
    """Eight radial cone markers just outside the orbit ring (4 main + 4 secondary)."""
    size_scale = max(float(arrow_size), 0.01)
    main_size = ORBIT_VIZ_ARROW_MAIN_SIZE * size_scale
    sec_size = ORBIT_VIZ_ARROW_SEC_SIZE * size_scale
    radius = ORBIT_VIZ_ARROW_RADIUS_FACTOR
    _remove_orphan_orbit_viz_arrows(viz)
    for index in range(ORBIT_VIZ_ARROW_COUNT):
        name = _orbit_viz_arrow_object_name(viz.name, index)
        arrow = bpy.data.objects.get(name)
        if arrow is None:
            arrow = bpy.data.objects.new(name, None)
            _link_object_to_collection(arrow, target_coll)
        elif arrow.name != name:
            arrow.name = name
        arrow.parent = viz
        is_main = index % 2 == 0
        angle = index * (math.pi / 4.0)
        arrow.empty_display_type = "CONE"
        arrow.empty_display_size = main_size if is_main else sec_size
        # Viz circle default is local XY; parent Rx(90°) puts the ring in local XZ.
        arrow.location = (
            math.cos(angle) * radius,
            0.0,
            math.sin(angle) * radius,
        )
        arrow.rotation_mode = "XYZ"
        arrow.rotation_euler = _orbit_viz_arrow_rotation(angle)
        arrow.scale = (1.0, 1.0, 0.0)
        arrow.hide_render = False
        arrow.hide_select = True
        if hasattr(arrow, "show_in_front"):
            arrow.show_in_front = True


def _configure_aim_empty(aim: bpy.types.Object) -> None:
    aim.empty_display_type = "PLAIN_AXES"
    aim.empty_display_size = 0.2


def _configure_orbit_pivot_empty(orbit: bpy.types.Object) -> None:
    orbit.empty_display_type = "SPHERE"
    orbit.empty_display_size = ORBIT_PIVOT_DISPLAY_SIZE
    orbit.hide_render = False
    orbit.hide_select = False
    try:
        orbit.driver_remove("empty_display_size")
    except Exception:
        pass


def _orbit_viz_distance(body: bpy.types.Object, orbit: bpy.types.Object) -> float:
    return max(
        float((body.matrix_world.translation - orbit.matrix_world.translation).length),
        0.1,
    )


def _setup_orbit_viz_scale_driver(
    viz: bpy.types.Object,
    body: bpy.types.Object,
    orbit: bpy.types.Object,
) -> None:
    try:
        viz.driver_remove("empty_display_size")
    except Exception:
        pass
    for index in range(3):
        try:
            viz.driver_remove("scale", index)
        except Exception:
            pass
    dist = _orbit_viz_distance(body, orbit)
    viz.scale = (dist, dist, dist)
    for index in range(3):
        try:
            result = viz.driver_add("scale", index)
        except TypeError:
            result = viz.driver_add("scale")
        if isinstance(result, list):
            fcurve = result[index] if index < len(result) else result[0]
        else:
            fcurve = result
        driver = fcurve.driver
        driver.type = "SCRIPTED"
        driver.expression = "max(dist, 0.1)"
        var = driver.variables.new()
        var.name = "dist"
        var.type = "LOC_DIFF"
        var.targets[0].id = body
        var.targets[1].id = orbit


def _ensure_orbit_viz_empty(
    orbit: bpy.types.Object,
    body: bpy.types.Object,
    target_coll: bpy.types.Collection,
    *,
    context: Optional[bpy.types.Context] = None,
    arrow_size: Optional[float] = None,
) -> bpy.types.Object:
    viz = _find_orbit_viz(orbit)
    target_name = _orbit_viz_object_name(orbit.name)
    if viz is None:
        viz = bpy.data.objects.new(target_name, None)
        viz.empty_display_type = "CIRCLE"
        _link_object_to_collection(viz, target_coll)
    elif viz.name != target_name:
        viz.name = target_name
    viz.parent = orbit
    viz.location = (0.0, 0.0, 0.0)
    viz.rotation_mode = "XYZ"
    viz.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
    viz.empty_display_size = ORBIT_VIZ_CIRCLE_DISPLAY_SIZE
    viz.hide_render = False
    viz.hide_select = True
    if hasattr(viz, "show_in_front"):
        viz.show_in_front = True
    _setup_orbit_viz_scale_driver(viz, body, orbit)
    if arrow_size is None:
        arrow_size = _orbit_arrow_size_from_context(context)
    _ensure_orbit_viz_arrows(viz, target_coll, arrow_size=arrow_size)
    return viz


def _apply_orbit_rig_state(
    parts: Dict[str, bpy.types.Object],
    context: bpy.types.Context,
    target_coll: bpy.types.Collection,
    *,
    enable_orbit: bool,
    body_constraint: bool,
    display_visible: Optional[bool] = None,
) -> None:
    body = parts.get("body")
    aim = parts.get("aim")
    orbit = parts.get("orbit")
    cam = parts.get("cam")
    root = parts.get("root")
    if body is None or aim is None or root is None:
        return
    if display_visible is None:
        display_visible = _orbit_display_visible_from_context(context)
    if enable_orbit:
        names = camera_rig_names(cam.name if cam is not None else "cam_shot")
        orbit = _ensure_orbit_empty(root, body, names["orbit"], target_coll)
        parts["orbit"] = orbit
        _ensure_orbit_viz_empty(orbit, body, target_coll, context=context)
        _configure_orbit_pivot_empty(orbit)
        _ensure_orbit_pivot_locks(orbit)
        _migrate_orbit_yaw_from_aim(parts)
        _ensure_body_child_of(body, orbit, context, enabled=body_constraint)
        _sync_orbit_empty_visibility(orbit, visible=display_visible)
    elif orbit is not None:
        _sync_orbit_empty_visibility(orbit, visible=display_visible)


_syncing_orbit_from_enable = False


def _finalize_camera_body_rig(
    context: bpy.types.Context,
    parts: Dict[str, bpy.types.Object],
    cam: bpy.types.Object,
    target_coll: bpy.types.Collection,
    *,
    enable_orbit: bool,
    body_orbit_constraint: bool,
) -> None:
    _migrate_legacy_orbit_pivot(parts, context)
    root = parts["root"]
    body = parts["body"]
    if body.parent != root:
        body_mw = body.matrix_world.copy()
        body.parent = root
        body.matrix_world = body_mw
    _configure_rig_rotation_orders(parts)
    _apply_orbit_rig_state(
        parts,
        context,
        target_coll,
        enable_orbit=enable_orbit,
        body_constraint=body_orbit_constraint,
    )


def _driver_add_single(obj: bpy.types.ID, prop_path: str):
    """Add a driver FCurve; Blender 5.x scalars reject an array index."""
    try:
        result = obj.driver_add(prop_path)
    except TypeError:
        result = obj.driver_add(prop_path, 0)
    if isinstance(result, list):
        return result[0]
    return result


def _snap_orbit_to_aim(
    orbit: bpy.types.Object,
    aim: bpy.types.Object,
    *,
    context: Optional[bpy.types.Context] = None,
) -> None:
    """Snap orbit pivot position to aim; keep orbit yaw unchanged."""
    orbit.location = aim.location
    _keyframe_object_location(orbit, context=context)


def _snap_orbit_to_cursor(
    orbit: bpy.types.Object,
    root: bpy.types.Object,
    scene: bpy.types.Scene,
    *,
    context: Optional[bpy.types.Context] = None,
) -> None:
    """Snap orbit pivot position to the 3D cursor (root local space)."""
    orbit.location = root.matrix_world.inverted() @ scene.cursor.location
    _keyframe_object_location(orbit, context=context)


def _ensure_orbit_empty(
    root: bpy.types.Object,
    body: bpy.types.Object,
    orbit_name: str,
    target_coll: bpy.types.Collection,
) -> bpy.types.Object:
    orbit = _resolve_orbit_empty(root, orbit_name)
    if orbit is None:
        orbit = bpy.data.objects.new(orbit_name, None)
        _link_object_to_collection(orbit, target_coll)
    orbit.parent = root
    orbit.hide_select = False
    _configure_orbit_pivot_empty(orbit)
    _ensure_orbit_pivot_locks(orbit)
    _ensure_orbit_viz_empty(orbit, body, target_coll)
    return orbit


def _orbit_rig_collection(
    parts: Dict[str, bpy.types.Object],
    context: bpy.types.Context,
) -> bpy.types.Collection:
    cam = parts.get("cam")
    if cam is not None and cam.users_collection:
        return cam.users_collection[0]
    return context.scene.collection


def set_enable_orbit(
    parts: Dict[str, bpy.types.Object],
    context: bpy.types.Context,
    enabled: bool,
    *,
    props: Optional[bpy.types.PropertyGroup] = None,
) -> None:
    global _syncing_orbit_from_enable
    coll = _orbit_rig_collection(parts, context)
    enabled = bool(enabled)
    if props is not None:
        _syncing_orbit_from_enable = True
        try:
            props.anim_camera_orbit_display_visible = enabled
            props.anim_camera_body_orbit_constraint = enabled
        finally:
            _syncing_orbit_from_enable = False
    _apply_orbit_rig_state(
        parts,
        context,
        coll,
        enable_orbit=enabled,
        body_constraint=enabled,
        display_visible=enabled,
    )


def set_body_orbit_constraint(
    parts: Dict[str, bpy.types.Object],
    context: bpy.types.Context,
    enabled: bool,
) -> None:
    coll = _orbit_rig_collection(parts, context)
    props = context.scene.monofx_pipeline_blender_props
    enable_orbit = bool(getattr(props, "anim_camera_orbit_follow_aim", False))
    _apply_orbit_rig_state(
        parts,
        context,
        coll,
        enable_orbit=enable_orbit,
        body_constraint=bool(enabled),
    )


def set_orbit_follow_aim(
    parts: Dict[str, bpy.types.Object],
    context: bpy.types.Context,
    enabled: bool,
    *,
    props: Optional[bpy.types.PropertyGroup] = None,
) -> None:
    """Backward-compatible alias for :func:`set_enable_orbit`."""
    set_enable_orbit(parts, context, enabled, props=props)


def orbit_to_aim(
    context: bpy.types.Context,
    obj: Optional[bpy.types.Object],
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """Snap orbit empty to aim (sibling of aim under root)."""
    parts = find_camera_rig_parts(obj)
    if parts is None:
        return False, "No camera rig found for the active object.", None
    aim = parts.get("aim")
    orbit = parts.get("orbit")
    root = parts.get("root")
    body = parts.get("body")
    cam = parts.get("cam")
    if aim is None or root is None or body is None or cam is None:
        return False, "Rig is missing aim/root/body.", None
    coll = cam.users_collection[0] if cam.users_collection else context.scene.collection
    if orbit is None:
        names = camera_rig_names(cam.name)
        orbit = _ensure_orbit_empty(root, body, names["orbit"], coll)
        parts["orbit"] = orbit
        props = context.scene.monofx_pipeline_blender_props
        _ensure_orbit_viz_empty(orbit, body, coll, context=context)
        visible = bool(getattr(props, "anim_camera_orbit_display_visible", True))
        _sync_orbit_empty_visibility(orbit, visible=visible)
    _snap_orbit_to_aim(orbit, aim, context=context)
    return True, f"Snapped {orbit.name} to {aim.name}", orbit


def orbit_to_cursor(
    context: bpy.types.Context,
    obj: Optional[bpy.types.Object] = None,
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """Snap orbit empty to the scene 3D cursor."""
    parts = _rig_parts_for_scene_camera(context)
    if parts is None:
        parts = find_camera_rig_parts(obj)
    if parts is None:
        return False, "No camera rig found for the active object.", None
    orbit = parts.get("orbit")
    root = parts.get("root")
    body = parts.get("body")
    cam = parts.get("cam")
    if root is None or body is None or cam is None:
        return False, "Rig is missing root/body.", None
    coll = cam.users_collection[0] if cam.users_collection else context.scene.collection
    if orbit is None:
        names = camera_rig_names(cam.name)
        orbit = _ensure_orbit_empty(root, body, names["orbit"], coll)
        parts["orbit"] = orbit
        props = context.scene.monofx_pipeline_blender_props
        _ensure_orbit_viz_empty(orbit, body, coll, context=context)
        visible = bool(getattr(props, "anim_camera_orbit_display_visible", True))
        _sync_orbit_empty_visibility(orbit, visible=visible)
    _snap_orbit_to_cursor(orbit, root, context.scene, context=context)
    return True, f"Snapped {orbit.name} to 3D cursor", orbit


def on_orbit_follow_aim_changed(props, context: Optional[bpy.types.Context]) -> None:
    if context is None or _syncing_active_rig:
        return
    parts = _rig_parts_for_scene_camera(context)
    if parts is None:
        return
    set_enable_orbit(parts, context, bool(props.anim_camera_orbit_follow_aim), props=props)


def on_orbit_display_visible_changed(props, context: Optional[bpy.types.Context]) -> None:
    if context is None or _syncing_active_rig:
        return
    parts = _rig_parts_for_scene_camera(context)
    if parts is None:
        return
    orbit = parts.get("orbit")
    if orbit is None:
        return
    _sync_orbit_empty_visibility(
        orbit,
        visible=bool(props.anim_camera_orbit_display_visible),
    )


def on_orbit_arrow_size_changed(props, context: Optional[bpy.types.Context]) -> None:
    if context is None:
        return
    refresh_orbit_display(context, props=props)


def on_body_orbit_constraint_changed(props, context: Optional[bpy.types.Context]) -> None:
    global _syncing_orbit_from_enable
    if context is None or _syncing_orbit_from_enable or _syncing_active_rig:
        return
    parts = _rig_parts_for_scene_camera(context)
    if parts is None:
        return
    set_body_orbit_constraint(parts, context, bool(props.anim_camera_body_orbit_constraint))


def _rig_motion_object(
    parts: Optional[Dict[str, bpy.types.Object]],
    part_key: str,
) -> Optional[bpy.types.Object]:
    if parts is None:
        return None
    return parts.get(part_key)


def _make_rig_channel_get(part_key: str, channel: str, axis_index: int, stored_attr: str):
    def getter(props: bpy.types.PropertyGroup) -> float:
        parts = _rig_parts_for_scene_camera()
        obj = _rig_motion_object(parts, part_key)
        if obj is not None:
            if channel == "loc":
                return float(obj.location[axis_index])
            _ensure_euler_xyz(obj)
            return float(obj.rotation_euler[axis_index])
        return float(getattr(props, stored_attr, 0.0))

    return getter


def _make_rig_channel_set(
    part_key: str,
    channel: str,
    axis_index: int,
    stored_attr: str,
):
    def setter(props: bpy.types.PropertyGroup, value: float) -> None:
        val = float(value)
        context = bpy.context
        parts = _rig_parts_for_scene_camera(context)
        obj = _rig_motion_object(parts, part_key)
        if obj is not None:
            if channel == "loc":
                obj.location[axis_index] = val
                _keyframe_object_location_index(obj, axis_index, context=context)
            else:
                _ensure_euler_xyz(obj)
                obj.rotation_euler[axis_index] = val
                _keyframe_object_rotation_euler_index(obj, axis_index, context=context)
        setattr(props, stored_attr, val)

    return setter


anim_camera_body_track_get = _make_rig_channel_get("body", "loc", 0, "anim_camera_body_track_stored")
anim_camera_body_track_set = _make_rig_channel_set("body", "loc", 0, "anim_camera_body_track_stored")
anim_camera_body_track_y_get = _make_rig_channel_get("body", "loc", 1, "anim_camera_body_track_y_stored")
anim_camera_body_track_y_set = _make_rig_channel_set("body", "loc", 1, "anim_camera_body_track_y_stored")
anim_camera_body_height_get = _make_rig_channel_get("body", "loc", 2, "anim_camera_body_height_stored")
anim_camera_body_height_set = _make_rig_channel_set("body", "loc", 2, "anim_camera_body_height_stored")
anim_camera_crane_angle_get = _make_rig_channel_get("body", "rot", 0, "anim_camera_crane_angle_stored")
anim_camera_crane_angle_set = _make_rig_channel_set("body", "rot", 0, "anim_camera_crane_angle_stored")
anim_camera_crane_length_get = _make_rig_channel_get("look", "loc", 2, "anim_camera_crane_length_stored")
anim_camera_crane_length_set = _make_rig_channel_set("look", "loc", 2, "anim_camera_crane_length_stored")
anim_camera_motion_dolly_get = _make_rig_channel_get("motion", "loc", 2, "anim_camera_motion_dolly_stored")
anim_camera_motion_dolly_set = _make_rig_channel_set("motion", "loc", 2, "anim_camera_motion_dolly_stored")
anim_camera_motion_truck_get = _make_rig_channel_get("motion", "loc", 0, "anim_camera_motion_truck_stored")
anim_camera_motion_truck_set = _make_rig_channel_set("motion", "loc", 0, "anim_camera_motion_truck_stored")


def anim_camera_motion_pan_get(props: bpy.types.PropertyGroup) -> float:
    parts = _rig_parts_for_scene_camera()
    _ensure_motion_head_locks(parts)
    obj = _rig_motion_object(parts, "motion")
    if obj is not None:
        _ensure_euler_xyz(obj)
        return float(obj.rotation_euler[1])
    return float(getattr(props, "anim_camera_motion_pan_stored", 0.0))


def anim_camera_motion_pan_set(props: bpy.types.PropertyGroup, value: float) -> None:
    val = float(value)
    context = bpy.context
    parts = _rig_parts_for_scene_camera(context)
    _ensure_motion_head_locks(parts)
    obj = _rig_motion_object(parts, "motion")
    if obj is not None:
        _ensure_euler_xyz(obj)
        obj.rotation_euler[1] = val
        _keyframe_object_rotation_euler_index(obj, 1, context=context)
    props.anim_camera_motion_pan_stored = val


def anim_camera_motion_tilt_get(props: bpy.types.PropertyGroup) -> float:
    parts = _rig_parts_for_scene_camera()
    _ensure_motion_head_locks(parts)
    obj = _rig_motion_object(parts, "motion")
    if obj is not None:
        _ensure_euler_xyz(obj)
        return float(obj.rotation_euler[0])
    return float(getattr(props, "anim_camera_motion_tilt_stored", 0.0))


def anim_camera_motion_tilt_set(props: bpy.types.PropertyGroup, value: float) -> None:
    val = float(value)
    context = bpy.context
    parts = _rig_parts_for_scene_camera(context)
    _ensure_motion_head_locks(parts)
    obj = _rig_motion_object(parts, "motion")
    if obj is not None:
        _ensure_euler_xyz(obj)
        obj.rotation_euler[0] = val
        _keyframe_object_rotation_euler_index(obj, 0, context=context)
    props.anim_camera_motion_tilt_stored = val


def anim_camera_motion_roll_get(props: bpy.types.PropertyGroup) -> float:
    parts = _rig_parts_for_scene_camera()
    _ensure_motion_head_locks(parts)
    obj = _rig_motion_object(parts, "motion")
    if obj is not None:
        _ensure_euler_xyz(obj)
        return float(obj.rotation_euler[2])
    return float(getattr(props, "anim_camera_motion_roll_stored", 0.0))


def anim_camera_motion_roll_set(props: bpy.types.PropertyGroup, value: float) -> None:
    val = float(value)
    context = bpy.context
    parts = _rig_parts_for_scene_camera(context)
    _ensure_motion_head_locks(parts)
    obj = _rig_motion_object(parts, "motion")
    if obj is not None:
        _ensure_euler_xyz(obj)
        obj.rotation_euler[2] = val
        _keyframe_object_rotation_euler_index(obj, 2, context=context)
    props.anim_camera_motion_roll_stored = val


def anim_camera_orbit_get(props: bpy.types.PropertyGroup) -> float:
    parts = _rig_parts_for_scene_camera()
    return _read_orbit_yaw(
        parts,
        stored=float(getattr(props, "anim_camera_orbit_stored", 0.0)),
    )


def anim_camera_orbit_set(props: bpy.types.PropertyGroup, value: float) -> None:
    val = float(value)
    context = bpy.context
    parts = _rig_parts_for_scene_camera(context)
    _migrate_orbit_yaw_from_aim(parts)
    orbit = _rig_motion_object(parts, "orbit")
    if orbit is not None:
        _ensure_orbit_pivot_locks(orbit)
        _ensure_euler_xyz(orbit)
        orbit.rotation_euler[2] = val
        _keyframe_object_rotation_euler_index(orbit, 2, context=context)
    props.anim_camera_orbit_stored = val


def _camera_view_forward(cam: bpy.types.Object) -> Vector:
    forward = cam.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
    if forward.length < 1e-8:
        return Vector((0.0, -1.0, 0.0))
    return forward.normalized()


def _read_aim_distance(cam: bpy.types.Object, aim: bpy.types.Object) -> float:
    offset = aim.matrix_world.translation - cam.matrix_world.translation
    depth = offset.dot(_camera_view_forward(cam))
    if depth >= 0.1:
        return float(depth)
    dist = offset.length
    if dist >= 0.1:
        return float(dist)
    return 10.0


def _set_aim_distance_on_parts(
    parts: Dict[str, bpy.types.Object],
    distance: float,
    *,
    context: Optional[bpy.types.Context] = None,
) -> None:
    cam = parts["cam"]
    aim = parts["aim"]
    root = parts["root"]
    dist = max(float(distance), 0.1)
    aim_world = cam.matrix_world.translation + _camera_view_forward(cam) * dist
    aim.location = root.matrix_world.inverted() @ aim_world
    _keyframe_object_location(aim, context=context)


def _cursor_depth_on_camera(cam: bpy.types.Object, cursor_loc: Vector) -> float:
    return float((cursor_loc - cam.matrix_world.translation).dot(_camera_view_forward(cam)))


def anim_camera_aim_distance_get(props: bpy.types.PropertyGroup) -> float:
    parts = _rig_parts_for_scene_camera()
    if parts is not None:
        return _read_aim_distance(parts["cam"], parts["aim"])
    return float(getattr(props, "anim_camera_aim_distance_stored", 10.0))


def anim_camera_aim_distance_set(props: bpy.types.PropertyGroup, value: float) -> None:
    val = max(float(value), 0.1)
    context = bpy.context
    parts = _rig_parts_for_scene_camera(context)
    if parts is not None:
        _set_aim_distance_on_parts(parts, val, context=context)
    props.anim_camera_aim_distance_stored = val


def _rig_parts_for_scene_camera(
    context: Optional[bpy.types.Context] = None,
) -> Optional[Dict[str, bpy.types.Object]]:
    ctx = context or bpy.context
    cam = resolve_active_rig_camera(ctx)
    if cam is None:
        return None
    return find_camera_rig_parts(cam)


def anim_camera_focal_length_get(props: bpy.types.PropertyGroup) -> float:
    cam = resolve_active_rig_camera(bpy.context, props=props)
    if cam is not None and cam.data is not None:
        return float(cam.data.lens)
    return float(getattr(props, "anim_camera_focal_length_stored", 50.0))


def anim_camera_focal_length_set(props: bpy.types.PropertyGroup, value: float) -> None:
    lens = float(value)
    old_lens = float(getattr(props, "anim_camera_focal_length_stored", lens))
    context = bpy.context
    cam = resolve_active_rig_camera(context, props=props)
    if cam is not None and cam.data is not None:
        if (
            bool(getattr(props, "anim_camera_vertigo", False))
            and old_lens > 1e-6
            and abs(lens - old_lens) > 1e-6
        ):
            target = str(getattr(props, "anim_camera_vertigo_target", "BODY"))
            _apply_vertigo_dolly(cam, old_lens, lens, target, context=context)
        cam.data.lens = lens
        _keyframe_camera_lens(cam, context=context)
    props.anim_camera_focal_length_stored = lens


def stored_camera_focal_length_mm(context: bpy.types.Context) -> float:
    props = context.scene.monofx_pipeline_blender_props
    return float(getattr(props, "anim_camera_focal_length_stored", 50.0))


def apply_focal_length_mm(context: bpy.types.Context, lens_mm: float) -> None:
    props = context.scene.monofx_pipeline_blender_props
    anim_camera_focal_length_set(props, float(lens_mm))


def resolve_shot_for_camera(context: bpy.types.Context) -> str:
    shot = anim_collections.detect_shot_from_blend_filepath(bpy.data.filepath)
    if shot:
        return normalize_shot_token(shot)
    return "shot"


def resolve_view3d(
    context: bpy.types.Context,
) -> Tuple[Optional[bpy.types.Area], Optional[bpy.types.Region], Optional[bpy.types.SpaceView3D]]:
    """
    Resolve a 3D View area/region/space.

    Sidebar operators run in the UI region — fall back to any VIEW_3D on screen.
    """
    if context.area is not None and context.area.type == "VIEW_3D":
        area = context.area
        space = context.space_data
        if space is None or space.type != "VIEW_3D":
            space = area.spaces.active
        region = context.region
        if region is None or region.type != "WINDOW":
            region = None
            for reg in area.regions:
                if reg.type == "WINDOW":
                    region = reg
                    break
        if space is not None and space.type == "VIEW_3D" and region is not None:
            return area, region, space

    window = context.window
    if window is None:
        return None, None, None
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        if space is None or space.type != "VIEW_3D":
            continue
        for region in area.regions:
            if region.type == "WINDOW":
                return area, region, space
    return None, None, None


def assign_standard_camera_name(cam_obj: bpy.types.Object, shot: str) -> str:
    existing = [n for n in existing_camera_object_names() if n != cam_obj.name]
    new_name = next_camera_name(shot, existing)
    cam_obj.name = new_name
    if cam_obj.data and cam_obj.data.name.startswith("Camera"):
        cam_obj.data.name = new_name
    return new_name


def _rig_aim_from_hierarchy(
    root: bpy.types.Object,
    body: bpy.types.Object,
    look: bpy.types.Object,
) -> Optional[bpy.types.Object]:
    for constraint in look.constraints:
        if constraint.type == "TRACK_TO" and constraint.target is not None:
            return constraint.target
    skip = {body}
    for child in root.children:
        if child in skip or child is None:
            continue
        if rig_part_suffix_matches(child.name, "aim"):
            return child
        if rig_part_suffix_matches(child.name, "orbit"):
            skip.add(child)
    for child in root.children:
        if child not in skip:
            return child
    return None


def discover_camera_rig_parts_from_hierarchy(
    cam: bpy.types.Object,
) -> Optional[Dict[str, bpy.types.Object]]:
    """
    Resolve rig empties from parent chain when object names are stale.

    Expected: root → body → look → motion → cam; aim is child of root.
    """
    if cam is None or cam.type != "CAMERA":
        return None

    motion = cam.parent
    if motion is None or motion.type != "EMPTY":
        return None
    look = motion.parent
    if look is None or look.type != "EMPTY":
        return None
    body = look.parent
    if body is None or body.type != "EMPTY":
        return None

    parent = body.parent
    if parent is not None and rig_part_suffix_matches(parent.name, "orbit"):
        root = parent.parent
        orbit = parent
    else:
        root = parent
        orbit = None

    if root is None or root.type != "EMPTY":
        return None

    aim = _rig_aim_from_hierarchy(root, body, look)
    if aim is None:
        return None
    if orbit is None:
        names = camera_rig_names(cam.name)
        orbit = _resolve_orbit_empty(root, names["orbit"])

    return {
        "root": root,
        "body": body,
        "look": look,
        "motion": motion,
        "aim": aim,
        "orbit": orbit,
        "cam": cam,
    }


def _repair_camera_rig_integrity(
    parts: Dict[str, bpy.types.Object],
    context: bpy.types.Context,
    *,
    enable_orbit: bool,
    body_orbit_constraint: bool,
    orbit_display_visible: bool,
    track_aim: bool,
) -> List[str]:
    """Ensure rotation orders, constraints, and orbit viz exist. Returns repair labels."""
    actions: List[str] = []
    cam = parts.get("cam")
    if cam is None:
        return actions

    _migrate_legacy_orbit_pivot(parts, context)
    root = parts.get("root")
    body = parts.get("body")
    if root is not None and body is not None and body.parent != root:
        body_mw = body.matrix_world.copy()
        body.parent = root
        body.matrix_world = body_mw
        actions.append("mount parent")

    _configure_rig_rotation_orders(parts)
    _ensure_motion_head_locks(parts)

    look = parts.get("look")
    motion = parts.get("motion")
    aim = parts.get("aim")
    if look is not None and motion is not None and aim is not None:
        had_track = _get_boom_track_aim_constraint(look) is not None
        _apply_camera_rig_constraints(look, motion, aim, track_aim=track_aim)
        if track_aim and not had_track:
            actions.append("track aim")

    if aim is not None:
        _configure_aim_empty(aim)

    coll = _orbit_rig_collection(parts, context)
    orbit = parts.get("orbit")
    if enable_orbit and root is not None and body is not None:
        if orbit is None:
            actions.append("orbit pivot")
        _apply_orbit_rig_state(
            parts,
            context,
            coll,
            enable_orbit=True,
            body_constraint=body_orbit_constraint,
            display_visible=orbit_display_visible,
        )
        orbit = parts.get("orbit")
    elif orbit is not None and body is not None:
        viz_before = _find_orbit_viz(orbit)
        arrow_count_before = (
            len(_iter_orbit_viz_arrows(viz_before)) if viz_before is not None else 0
        )
        _configure_orbit_pivot_empty(orbit)
        _ensure_orbit_viz_empty(orbit, body, coll, context=context)
        viz = _find_orbit_viz(orbit)
        if viz_before is None and viz is not None:
            actions.append("orbit viz")
        elif (
            viz is not None
            and len(_iter_orbit_viz_arrows(viz)) >= ORBIT_VIZ_ARROW_COUNT
            and arrow_count_before < ORBIT_VIZ_ARROW_COUNT
        ):
            actions.append("orbit viz arrows")
        _sync_orbit_empty_visibility(orbit, visible=orbit_display_visible)

    missing = [
        key
        for key in _CAMERA_RIG_PART_KEYS
        if key != "orbit" and parts.get(key) is None
    ]
    if missing:
        actions.append(f"missing {', '.join(missing)}")

    ensure_rig_pose_lock_default(parts)
    if is_rig_pose_locked(cam):
        lock_rig_pose_transforms(parts)

    return actions


def _iter_rig_hierarchy_objects(parts: Dict[str, bpy.types.Object]) -> List[bpy.types.Object]:
    """Root-first hierarchy including orbit viz and arrow children."""
    root = parts.get("root")
    if root is None:
        return []
    ordered: List[bpy.types.Object] = []
    seen: set[int] = set()
    queue: List[bpy.types.Object] = [root]
    while queue:
        obj = queue.pop(0)
        if obj is None or id(obj) in seen:
            continue
        seen.add(id(obj))
        ordered.append(obj)
        queue.extend(list(obj.children))
    return ordered


def _duplicate_rig_object_shell(
    src: bpy.types.Object,
    name: str,
    target_coll: bpy.types.Collection,
) -> bpy.types.Object:
    if src.type == "CAMERA" and src.data is not None:
        new_data = src.data.copy()
        new_data.name = name
        new_obj = bpy.data.objects.new(name, new_data)
    else:
        new_obj = bpy.data.objects.new(name, None)
    new_obj.rotation_mode = src.rotation_mode
    new_obj.empty_display_type = src.empty_display_type
    new_obj.empty_display_size = src.empty_display_size
    new_obj.hide_viewport = src.hide_viewport
    new_obj.hide_select = src.hide_select
    new_obj.hide_render = src.hide_render
    if hasattr(new_obj, "show_in_front") and hasattr(src, "show_in_front"):
        new_obj.show_in_front = src.show_in_front
    new_obj.lock_location = src.lock_location[:]
    new_obj.lock_rotation = src.lock_rotation[:]
    new_obj.lock_scale = src.lock_scale[:]
    _link_object_to_collection(new_obj, target_coll)
    return new_obj


def _copy_object_animation(
    src: bpy.types.Object,
    dst: bpy.types.Object,
) -> None:
    if src.animation_data is None or src.animation_data.action is None:
        return
    dst.animation_data_create()
    dst.animation_data.action = src.animation_data.action.copy()


def _copy_object_constraints(
    src: bpy.types.Object,
    dst: bpy.types.Object,
    obj_map: Dict[bpy.types.Object, bpy.types.Object],
) -> None:
    for con in src.constraints:
        new_con = dst.constraints.new(type=con.type)
        for prop in con.bl_rna.properties:
            if prop.is_readonly:
                continue
            ident = prop.identifier
            if ident in {"rna_type", "type"}:
                continue
            try:
                value = getattr(con, ident)
            except AttributeError:
                continue
            if ident == "target" and value in obj_map:
                value = obj_map[value]
            try:
                setattr(new_con, ident, value)
            except (AttributeError, TypeError):
                pass
        new_con.name = con.name


def _find_orbit_in_parts(
    parts: Dict[str, bpy.types.Object],
) -> Optional[bpy.types.Object]:
    orbit = parts.get("orbit")
    if orbit is not None:
        return orbit
    root = parts.get("root")
    cam = parts.get("cam")
    if root is None:
        return None
    for child in root.children:
        if rig_part_suffix_matches(child.name, "orbit"):
            return child
    if cam is not None:
        return _resolve_orbit_empty(root, camera_rig_names(cam.name)["orbit"])
    return None


def _object_role_in_rig(
    obj: bpy.types.Object,
    parts: Dict[str, bpy.types.Object],
) -> Optional[str]:
    cam = parts.get("cam")
    if cam is not None and obj == cam:
        return "cam"
    for key in _CAMERA_RIG_PART_KEYS:
        part = parts.get(key)
        if part is not None and obj == part:
            return key
    orbit = _find_orbit_in_parts(parts)
    if orbit is not None:
        if obj == orbit:
            return "orbit"
        viz = _find_orbit_viz(orbit)
        if viz is not None and obj == viz:
            return "orbit_viz"
        if viz is not None:
            for index, arrow in enumerate(_iter_orbit_viz_arrows(viz)):
                if obj == arrow:
                    return f"orbit_arrow:{index}"
    for key in _CAMERA_RIG_PART_KEYS:
        if rig_part_suffix_matches(obj.name, key):
            return key
    if orbit is not None and obj.parent == orbit:
        suffix = ORBIT_VIZ_NAME_SUFFIX.casefold()
        if obj.name.casefold().endswith(suffix):
            return "orbit_viz"
    parent = obj.parent
    if parent is not None:
        viz = _find_orbit_viz(parent) if rig_part_suffix_matches(parent.name, "orbit") else None
        if viz is None and parent.name.casefold().endswith(ORBIT_VIZ_NAME_SUFFIX.casefold()):
            viz = parent
        if viz is not None and obj.parent == viz:
            for index, arrow in enumerate(_iter_orbit_viz_arrows(viz)):
                if obj == arrow:
                    return f"orbit_arrow:{index}"
    return None


def _target_name_for_rig_role(
    role: str,
    new_cam_name: str,
    new_names: Dict[str, str],
) -> Optional[str]:
    if role == "cam":
        return new_cam_name
    if role in _CAMERA_RIG_PART_KEYS:
        return new_names[role]
    if role == "orbit_viz":
        return _orbit_viz_object_name(new_names["orbit"])
    if role.startswith("orbit_arrow:"):
        index = int(role.split(":", 1)[1])
        viz_name = _orbit_viz_object_name(new_names["orbit"])
        return _orbit_viz_arrow_object_name(viz_name, index)
    return None


def _apply_object_renames(
    assignments: List[Tuple[bpy.types.Object, str]],
) -> bool:
    pending: List[Tuple[bpy.types.Object, str]] = []
    seen: set[int] = set()
    for obj, target in assignments:
        obj_id = id(obj)
        if obj_id in seen:
            continue
        seen.add(obj_id)
        if obj.name != target:
            pending.append((obj, target))
    if not pending:
        return False
    for index, (obj, _target) in enumerate(pending):
        obj.name = f"__mono_ren_{index:04d}__"
    for obj, target in pending:
        obj.name = target
    return True


def _build_rig_rename_assignments(
    parts: Dict[str, bpy.types.Object],
    new_cam_name: str,
    *,
    objects: Optional[List[bpy.types.Object]] = None,
) -> List[Tuple[bpy.types.Object, str]]:
    new_names = camera_rig_names(new_cam_name)
    if objects is None:
        objects = _iter_rig_hierarchy_objects(parts)
    assignments: List[Tuple[bpy.types.Object, str]] = []
    seen: set[int] = set()
    for obj in objects:
        obj_id = id(obj)
        if obj_id in seen:
            continue
        role = _object_role_in_rig(obj, parts)
        if role is None:
            continue
        target = _target_name_for_rig_role(role, new_cam_name, new_names)
        if target is None:
            continue
        seen.add(obj_id)
        assignments.append((obj, target))
    return assignments


def _sync_parts_from_hierarchy(parts: Dict[str, bpy.types.Object]) -> None:
    cam = parts.get("cam")
    if cam is None:
        return
    discovered = discover_camera_rig_parts_from_hierarchy(cam)
    if discovered is None:
        orbit = _find_orbit_in_parts(parts)
        if orbit is not None:
            parts["orbit"] = orbit
        return
    parts.update(discovered)


def _remove_temp_rig_objects(root: bpy.types.Object) -> int:
    """Remove leftover ``__mono_*`` temp objects from failed clone/rename passes."""
    removed = 0
    for obj in list(_iter_rig_hierarchy_objects({"root": root})):
        if not (obj.name.startswith("__mono_dup_") or obj.name.startswith("__mono_ren_")):
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
        except Exception:
            pass
    return removed


def _rename_camera_rig_objects(
    parts: Dict[str, bpy.types.Object],
    new_cam_name: str,
) -> bool:
    root = parts.get("root")
    if root is not None:
        _remove_temp_rig_objects(root)
    _sync_parts_from_hierarchy(parts)
    assignments = _build_rig_rename_assignments(parts, new_cam_name)
    changed = _apply_object_renames(assignments)
    cam = parts["cam"]
    if cam.name != new_cam_name:
        cam.name = new_cam_name
        changed = True
    if cam.data is not None and cam.data.name != new_cam_name:
        cam.data.name = new_cam_name
        changed = True
    _sync_parts_from_hierarchy(parts)
    if root is not None:
        _remove_temp_rig_objects(root)
    return changed


def _rig_repair_props_from_context(
    context: bpy.types.Context,
) -> Tuple[bool, bool, bool, bool]:
    props = getattr(context.scene, "monofx_pipeline_blender_props", None)
    if props is None:
        return False, False, True, True
    return (
        bool(getattr(props, "anim_camera_orbit_follow_aim", False)),
        bool(getattr(props, "anim_camera_body_orbit_constraint", False)),
        bool(getattr(props, "anim_camera_orbit_display_visible", True)),
        bool(getattr(props, "anim_camera_track_aim", True)),
    )


def _finalize_duplicated_camera_rig(
    context: bpy.types.Context,
    parts: Dict[str, bpy.types.Object],
    shot: str,
) -> None:
    enable_orbit, body_orbit_constraint, orbit_display_visible, track_aim = (
        _rig_repair_props_from_context(context)
    )
    _repair_camera_rig_integrity(
        parts,
        context,
        enable_orbit=enable_orbit,
        body_orbit_constraint=body_orbit_constraint,
        orbit_display_visible=orbit_display_visible,
        track_aim=track_aim,
    )
    cam = parts["cam"]
    link_camera_to_shot_collection(context.scene, cam, shot)
    set_active_camera_rig(context, cam)


def _apply_clone_world_translation(
    obj_map: Dict[bpy.types.Object, bpy.types.Object],
    root: bpy.types.Object,
    target_root_world: Vector,
) -> None:
    delta = target_root_world - obj_map[root].matrix_world.translation
    for dst in obj_map.values():
        mw = dst.matrix_world.copy()
        mw.translation += delta
        dst.matrix_world = mw


def _clone_camera_rig(
    context: bpy.types.Context,
    cam: bpy.types.Object,
    *,
    root_world_translation: Optional[Vector] = None,
    root_world_delta: Optional[Vector] = None,
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """Clone a full camera rig; allocates the next ``cam_{shot}_##`` name."""
    parts = find_camera_rig_parts(cam)
    if parts is None:
        return False, "No camera rig found.", None
    root = parts.get("root")
    if root is None:
        return False, "Rig has no root empty.", None

    shot = resolve_shot_for_camera(context)
    new_cam_name = next_camera_name(shot, existing_camera_object_names())
    coll = (
        cam.users_collection[0]
        if cam.users_collection
        else context.scene.collection
    )

    ordered = _iter_rig_hierarchy_objects(parts)
    obj_map: Dict[bpy.types.Object, bpy.types.Object] = {}
    for src in ordered:
        tmp_name = f"__mono_dup_{len(obj_map):03d}__"
        obj_map[src] = _duplicate_rig_object_shell(src, tmp_name, coll)

    for src in ordered:
        dst = obj_map[src]
        parent = src.parent
        if parent is not None and parent in obj_map:
            dst.parent = obj_map[parent]
        dst.matrix_world = src.matrix_world.copy()

    if root_world_translation is not None:
        _apply_clone_world_translation(obj_map, root, root_world_translation)
    elif root_world_delta is not None:
        _apply_clone_world_translation(
            obj_map,
            root,
            obj_map[root].matrix_world.translation + root_world_delta,
        )

    for src in ordered:
        dst = obj_map[src]
        _copy_object_constraints(src, dst, obj_map)
        _copy_object_animation(src, dst)

    rename_assignments: List[Tuple[bpy.types.Object, str]] = []
    new_names = camera_rig_names(new_cam_name)
    seen_dst: set[int] = set()
    for src in ordered:
        dst = obj_map[src]
        if id(dst) in seen_dst:
            continue
        role = _object_role_in_rig(src, parts)
        if role is None:
            continue
        target = _target_name_for_rig_role(role, new_cam_name, new_names)
        if target is None:
            continue
        seen_dst.add(id(dst))
        rename_assignments.append((dst, target))

    _apply_object_renames(rename_assignments)
    new_cam = obj_map[cam]
    new_cam.name = new_cam_name
    if new_cam.data is not None:
        new_cam.data.name = new_cam_name

    new_parts = find_camera_rig_parts(new_cam)
    if new_parts is None:
        new_parts = {"cam": new_cam}
        for key in _CAMERA_RIG_PART_KEYS:
            src = parts.get(key)
            if src is not None and src in obj_map:
                new_parts[key] = obj_map[src]
        _sync_parts_from_hierarchy(new_parts)

    new_root = new_parts.get("root")
    if new_root is not None:
        _remove_temp_rig_objects(new_root)

    _finalize_duplicated_camera_rig(context, new_parts, shot)
    return True, new_cam_name, new_parts["cam"]


def _run_object_copy_op(context: bpy.types.Context) -> None:
    area, region, _space = resolve_view3d(context)
    window = context.window
    if area is not None and region is not None and window is not None:
        with context.temp_override(
            window=window,
            area=area,
            region=region,
            scene=context.scene,
        ):
            bpy.ops.object.copy()
        return
    bpy.ops.object.copy()


def copy_camera_rig_to_clipboard(
    context: bpy.types.Context,
    cam: bpy.types.Object,
) -> Tuple[bool, str]:
    """Copy full rig hierarchy to Blender clipboard (like Ctrl+C), including hide_select objects."""
    parts = find_camera_rig_parts(cam)
    if parts is None:
        return False, "No camera rig found."
    root = parts.get("root")
    if root is None:
        return False, "Rig has no root empty."

    ordered = _iter_rig_hierarchy_objects(parts)
    if not ordered:
        return False, "Rig hierarchy is empty."

    view_layer = context.view_layer
    saved_active = view_layer.objects.active
    saved_selected = list(context.selected_objects)
    saved_hide_select = {obj: bool(obj.hide_select) for obj in ordered}

    try:
        _deselect_all_objects(view_layer)
        for obj in ordered:
            obj.hide_select = False
            obj.select_set(True)
        view_layer.objects.active = root
        _run_object_copy_op(context)
    except Exception as exc:
        return False, f"Copy failed: {exc}"
    finally:
        for obj, hide in saved_hide_select.items():
            obj.hide_select = hide
        _deselect_all_objects(view_layer)
        for obj in saved_selected:
            try:
                obj.select_set(True)
            except RuntimeError:
                pass
        if saved_active is not None:
            try:
                view_layer.objects.active = saved_active
            except RuntimeError:
                pass

    return True, f"Copied {len(ordered)} rig objects to clipboard"


def duplicate_camera_rig(
    context: bpy.types.Context,
    cam: bpy.types.Object,
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """Duplicate rig in place; allocates the next ``cam_{shot}_##`` name."""
    ok, new_name, new_cam = _clone_camera_rig(context, cam)
    if not ok or new_cam is None:
        return False, new_name, None
    return True, f"Duplicated rig: {new_name}", new_cam


def copy_camera_rig(
    context: bpy.types.Context,
    cam: bpy.types.Object,
) -> Tuple[bool, str]:
    """Backward-compatible alias for :func:`copy_camera_rig_to_clipboard`."""
    return copy_camera_rig_to_clipboard(context, cam)


def rename_camera_rig(
    context: bpy.types.Context,
    cam: bpy.types.Object,
    new_cam_name: str,
) -> Tuple[bool, str]:
    """Rename camera + all rig empties to match *new_cam_name*."""
    raw_name = (new_cam_name or "").strip()
    if not raw_name:
        return False, "Empty camera name."
    new_name = normalize_camera_rename_name(raw_name)
    if new_name is None:
        return False, "Use cam_sh010, cam_sh010_02, or cam_shot_2 (→ cam_shot_02)."
    existing = bpy.data.objects.get(new_name)
    if existing is not None and existing != cam:
        return False, f"Object {new_name} already exists."
    parts = find_camera_rig_parts(cam)
    if parts is None:
        return False, "No camera rig found."
    _rename_camera_rig_objects(parts, new_name)
    shot = resolve_shot_for_camera(context)
    link_camera_to_shot_collection(context.scene, cam, shot)
    set_active_camera_rig(context, cam)
    return True, new_name

def fix_camera_rig(
    cam_obj: bpy.types.Object,
    shot: str,
    context: Optional[bpy.types.Context] = None,
) -> Tuple[str, bool, List[str]]:
    """
    Cam rig fixer: rename *cam_obj* to ``cam_sh###``, fix rig empty names,
    and repair missing orbit viz / constraints when a rig exists.

    Returns ``(new_camera_name, names_changed, repair_actions)``.
    """
    ctx = context or bpy.context
    parts = find_camera_rig_parts(cam_obj)
    cam = parts["cam"] if parts is not None else cam_obj

    existing = [n for n in existing_camera_object_names() if n != cam.name]
    new_name = resolve_name_fixer_camera_name(cam.name, shot, existing)

    if parts is not None:
        names_changed = _rename_camera_rig_objects(parts, new_name)

        props = getattr(ctx.scene, "monofx_pipeline_blender_props", None)
        enable_orbit = bool(getattr(props, "anim_camera_orbit_follow_aim", False))
        body_orbit_constraint = bool(
            getattr(props, "anim_camera_body_orbit_constraint", False)
        )
        orbit_display_visible = bool(
            getattr(props, "anim_camera_orbit_display_visible", True)
        )
        track_aim = bool(getattr(props, "anim_camera_track_aim", True))
        repairs = _repair_camera_rig_integrity(
            parts,
            ctx,
            enable_orbit=enable_orbit,
            body_orbit_constraint=body_orbit_constraint,
            orbit_display_visible=orbit_display_visible,
            track_aim=track_aim,
        )
        root = parts.get("root")
        if root is not None:
            _remove_temp_rig_objects(root)
        return new_name, names_changed, repairs

    assign_standard_camera_name(cam, shot)
    return cam.name, False, []


def fix_camera_names(cam_obj: bpy.types.Object, shot: str) -> Tuple[str, bool]:
    """Backward-compatible wrapper for :func:`fix_camera_rig`."""
    new_name, names_changed, _repairs = fix_camera_rig(cam_obj, shot)
    return new_name, names_changed


def _link_object_to_collection(obj: bpy.types.Object, coll: bpy.types.Collection) -> None:
    if coll not in obj.users_collection:
        try:
            coll.objects.link(obj)
        except RuntimeError:
            pass


def _unlink_from_other_collections(obj: bpy.types.Object, keep: bpy.types.Collection) -> None:
    for coll in list(obj.users_collection):
        if coll != keep:
            try:
                coll.objects.unlink(obj)
            except RuntimeError:
                pass


def link_camera_to_shot_collection(
    scene: bpy.types.Scene,
    cam_obj: bpy.types.Object,
    shot: str,
) -> None:
    try:
        cameras_coll = anim_collections.ensure_cameras_collection(scene, shot, cam_obj=cam_obj)
    except RuntimeError:
        cameras_coll = None
    target = cameras_coll if cameras_coll is not None else scene.collection
    _link_object_to_collection(cam_obj, target)
    if cameras_coll is not None:
        _unlink_from_other_collections(cam_obj, cameras_coll)


def copy_view_settings_to_camera(
    space: bpy.types.SpaceView3D,
    cam_data: bpy.types.Camera,
) -> None:
    cam_data.lens = float(space.lens)
    cam_data.clip_start = float(space.clip_start)
    cam_data.clip_end = float(space.clip_end)
    if hasattr(space, "camera_offset"):
        try:
            cam_data.shift_x = float(space.camera_offset[0])
            cam_data.shift_y = float(space.camera_offset[1])
        except (TypeError, AttributeError, IndexError):
            pass


def apply_default_camera_display(cam_data: bpy.types.Camera) -> None:
    """Enable full passepartout mask on new shot cameras."""
    if hasattr(cam_data, "show_passepartout"):
        cam_data.show_passepartout = True
    if hasattr(cam_data, "passepartout_alpha"):
        cam_data.passepartout_alpha = 1.0
    display = getattr(cam_data, "display", None)
    if display is not None:
        if hasattr(display, "passepartout_alpha"):
            display.passepartout_alpha = 1.0
        if hasattr(display, "show_passepartout"):
            display.show_passepartout = True


def select_scene_camera(context: bpy.types.Context) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    cam = context.scene.camera
    if cam is None:
        return False, "No active scene camera.", None
    view_layer = context.view_layer
    try:
        _deselect_all_objects(view_layer)
        cam.select_set(True)
        view_layer.objects.active = cam
    except Exception as exc:
        return False, f"Could not select camera: {exc}", None
    if find_camera_rig_parts(cam) is not None:
        set_active_camera_rig(context, cam)
    return True, f"Selected {cam.name}", cam


def select_camera_rig(
    context: bpy.types.Context,
    cam: bpy.types.Object,
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """Select the full camera rig hierarchy for *cam* (root, empties, camera, viz)."""
    parts = find_camera_rig_parts(cam)
    if parts is None:
        return False, "No camera rig found.", None
    ordered = _iter_rig_hierarchy_objects(parts)
    if not ordered:
        return False, "Rig hierarchy is empty.", None

    view_layer = context.view_layer
    saved_hide_select = {obj: bool(obj.hide_select) for obj in ordered}
    try:
        _deselect_all_objects(view_layer)
        for obj in ordered:
            obj.hide_select = False
            obj.select_set(True)
        view_layer.objects.active = cam
        set_active_camera_rig(context, cam)
    except Exception as exc:
        return False, f"Could not select rig: {exc}", None
    finally:
        for obj, hide in saved_hide_select.items():
            obj.hide_select = hide

    return True, f"Selected {len(ordered)} rig object(s)", cam


def clean_camera_rig_keyframes(
    cam: bpy.types.Object,
) -> Tuple[bool, str, Tuple[int, int]]:
    """Remove all keyed fcurves on every object in the camera rig (incl. lens on camera data)."""
    parts = find_camera_rig_parts(cam)
    if parts is None:
        return False, "No camera rig found.", (0, 0)
    objects = _iter_rig_hierarchy_objects(parts)
    removed, affected = anim_keys_bpy.clear_all_keys_on_objects(objects)
    return (
        True,
        f"Cleared {removed} fcurve(s) from {affected} rig object(s).",
        (removed, affected),
    )


def create_camera_from_view(context: bpy.types.Context) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    _area, region, space = resolve_view3d(context)
    if region is None or space is None:
        return False, "No 3D View found.", None

    rv3d = region.data
    if rv3d is None:
        return False, "No 3D View region data.", None

    shot = resolve_shot_for_camera(context)
    cam_name = next_camera_name(shot, existing_camera_object_names())

    try:
        view_matrix = rv3d.view_matrix.inverted()
    except Exception as exc:
        return False, f"Could not read viewport matrix: {exc}", None

    cam_data = bpy.data.cameras.new(cam_name)
    cam_obj = bpy.data.objects.new(cam_name, cam_data)
    cam_obj.matrix_world = view_matrix

    copy_view_settings_to_camera(space, cam_data)
    cam_data.lens = stored_camera_focal_length_mm(context)
    apply_default_camera_display(cam_data)
    link_camera_to_shot_collection(context.scene, cam_obj, shot)
    context.scene.camera = cam_obj

    try:
        context.view_layer.objects.active = cam_obj
        cam_obj.select_set(True)
    except Exception:
        pass

    return True, f"Created camera {cam_obj.name}", cam_obj


def create_camera_at_cursor_or_origin(
    context: bpy.types.Context,
    *,
    at_cursor: bool,
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """
    Create a new shot camera when none exists.

    - at_cursor=True: place at 3D cursor
    - at_cursor=False: place at world origin
    """
    if context.scene is None:
        return False, "No active scene.", None

    shot = resolve_shot_for_camera(context)
    cam_name = next_camera_name(shot, existing_camera_object_names())

    cam_data = bpy.data.cameras.new(cam_name)
    cam_obj = bpy.data.objects.new(cam_name, cam_data)

    loc = context.scene.cursor.location if at_cursor else Vector((0.0, 0.0, 0.0))
    cam_obj.location = (float(loc.x), float(loc.y), float(loc.z))
    cam_obj.rotation_euler = default_shot_camera_rotation_euler()

    cam_data.lens = stored_camera_focal_length_mm(context)
    apply_default_camera_display(cam_data)

    link_camera_to_shot_collection(context.scene, cam_obj, shot)
    context.scene.camera = cam_obj
    try:
        context.view_layer.objects.active = cam_obj
        cam_obj.select_set(True)
    except Exception:
        pass

    return True, f"Created camera {cam_obj.name}", cam_obj


def _object_by_name(name: str) -> Optional[bpy.types.Object]:
    return bpy.data.objects.get(name)


def _reset_local_transform(obj: bpy.types.Object) -> None:
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)


def _clear_object_constraints(obj: bpy.types.Object) -> None:
    for constraint in list(obj.constraints):
        obj.constraints.remove(constraint)


def _set_constraint_enabled(constraint: bpy.types.Constraint, enabled: bool) -> None:
    constraint.enabled = bool(enabled)
    if hasattr(constraint, "mute"):
        constraint.mute = not bool(enabled)


def _get_boom_track_aim_constraint(
    look: bpy.types.Object,
) -> Optional[bpy.types.Constraint]:
    for constraint in look.constraints:
        if constraint.type == "TRACK_TO":
            return constraint
    return None


def _ensure_boom_track_aim(
    look: bpy.types.Object,
    aim: bpy.types.Object,
    *,
    enabled: bool,
    reset_constraints: bool = False,
) -> None:
    if reset_constraints:
        _clear_object_constraints(look)
    track = _get_boom_track_aim_constraint(look)
    if track is None:
        track = look.constraints.new(type="TRACK_TO")
        track.name = TRACK_AIM_CONSTRAINT_NAME
        track.target = aim
        track.track_axis = "TRACK_NEGATIVE_Z"
        track.up_axis = "UP_Y"
    elif track.target != aim:
        track.target = aim
    _set_constraint_enabled(track, enabled)


def _snap_aim_to_boom_look(
    look: bpy.types.Object,
    aim: bpy.types.Object,
    root: bpy.types.Object,
    *,
    context: Optional[bpy.types.Context] = None,
) -> None:
    """Move aim onto boom -Z so enabling TRACK_TO keeps boom orientation (Track Aim inverse)."""
    look_mw = look.matrix_world
    forward = look_mw.to_3x3() @ Vector((0.0, 0.0, -1.0))
    if forward.length < 1e-8:
        return
    forward.normalize()
    dist = (aim.matrix_world.translation - look_mw.translation).length
    if dist < 0.1:
        dist = 10.0
    aim_world = look_mw.translation + forward * dist
    aim.location = root.matrix_world.inverted() @ aim_world
    _keyframe_object_location(aim, context=context)


def set_track_aim(
    parts: Optional[Dict[str, bpy.types.Object]],
    context: bpy.types.Context,
    enabled: bool,
) -> None:
    look = _rig_motion_object(parts, "look")
    aim = _rig_motion_object(parts, "aim")
    root = _rig_motion_object(parts, "root")
    if look is None or aim is None:
        return
    if enabled and root is not None:
        _snap_aim_to_boom_look(look, aim, root, context=context)
    _ensure_boom_track_aim(look, aim, enabled=enabled)
    try:
        context.view_layer.update()
    except Exception:
        pass


def on_track_aim_changed(props, context: Optional[bpy.types.Context]) -> None:
    if context is None or _syncing_active_rig:
        return
    parts = _rig_parts_for_scene_camera(context)
    if parts is None:
        return
    set_track_aim(parts, context, bool(getattr(props, "anim_camera_track_aim", True)))


def resolve_camera_rig_part_object(
    cam_name: str,
    part_key: str,
) -> Optional[bpy.types.Object]:
    for name in iter_rig_part_name_candidates(cam_name, part_key):
        obj = _object_by_name(name)
        if obj is not None:
            return obj
    return None


def _apply_camera_rig_constraints(
    look: bpy.types.Object,
    motion: bpy.types.Object,
    aim: bpy.types.Object,
    *,
    track_aim: bool = True,
) -> None:
    """Boom TRACK_TO aim (optional). Head stays manual (roll, shake, bump, …)."""
    _clear_object_constraints(motion)
    _ensure_boom_track_aim(look, aim, enabled=track_aim, reset_constraints=True)


def _apply_rig_pose_from_camera(
    root: bpy.types.Object,
    body: bpy.types.Object,
    aim: bpy.types.Object,
    cam_mw: Matrix,
    focus_distance: float,
    *,
    look: Optional[bpy.types.Object] = None,
    motion: Optional[bpy.types.Object] = None,
    track_aim: bool = True,
) -> None:
    """
    Decompose camera pose onto root, mount, aim, and head layers.

    - root: world XY translation, no rotation
    - body: pedestal (local Z only); crane tilt stays manual
    - aim: focus position only (identity rotation)
    - head (motion): pan / tilt / roll when *motion* is provided
    """
    loc, rot, _scale = cam_mw.decompose()
    dist = max(float(focus_distance), 0.1)

    forward = rot.to_matrix() @ Vector((0.0, 0.0, -1.0))
    if forward.length < 1e-8:
        forward = Vector((0.0, 0.0, -1.0))
    else:
        forward.normalize()

    root_mw = Matrix.Translation(Vector((loc.x, loc.y, 0.0)))
    root.matrix_world = root_mw

    body.parent = root
    body.location = root_mw.inverted() @ loc
    body.rotation_mode = "XYZ"
    body.rotation_euler = (0.0, 0.0, 0.0)

    aim_world = loc + forward * dist
    aim.parent = root
    _reset_aim_transform(aim)
    aim.location = root_mw.inverted() @ aim_world

    if motion is not None:
        _ensure_euler_xyz(motion)
        tilt, pan, roll = compute_head_rotation_euler_from_camera(
            loc,
            rot,
            aim_world,
            track_aim=track_aim,
        )
        motion.rotation_euler = (tilt, pan, roll)
    if look is not None:
        look.rotation_mode = "XYZ"
        look.rotation_euler = (0.0, 0.0, 0.0)


def setup_camera_rig(cam_obj: bpy.types.Object) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """
    Build a film-style camera rig around *cam_obj*.

    Hierarchy (Outliner suffixes)::

        {cam}_root         — Stage: floor position (world XY)
          ├ {cam}_aim      — Aim target (focus / look-at)
          ├ {cam}_orbit   — Orbit pivot (aim yaw; Child Of mount when enabled)
          └ {cam}_mount    — Mount: pedestal, dolly track, crane tilt
              └ {cam}_boom — Boom: crane reach + TRACK_TO aim
                  └ {cam}_head — Head: dolly, truck, tilt, roll
                      └ {cam}

    Legacy suffixes ``_body``, ``_look``, ``_motion``, ``_orbit`` still resolve.
    Cam rig fixer renames them to the canonical names above.
    """
    if cam_obj is None or cam_obj.type != "CAMERA":
        return False, "Active object is not a camera.", None

    if any(_object_by_name(n) is not None for n in iter_camera_rig_object_names(cam_obj.name)):
        return False, f"Camera rig already exists for {cam_obj.name}.", None

    names = camera_rig_names(cam_obj.name)

    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    cam_mw = cam_obj.matrix_world.copy()

    focus_distance = 10.0
    if cam_obj.data and cam_obj.data.dof.use_dof:
        focus_distance = max(float(cam_obj.data.dof.focus_distance), 0.1)

    root = bpy.data.objects.new(names["root"], None)
    root.empty_display_type = "CUBE"
    root.empty_display_size = 0.15

    body = bpy.data.objects.new(names["body"], None)
    body.empty_display_type = "PLAIN_AXES"
    body.empty_display_size = 0.5

    look = bpy.data.objects.new(names["look"], None)
    look.empty_display_type = "SINGLE_ARROW"
    look.empty_display_size = 0.35

    motion = bpy.data.objects.new(names["motion"], None)
    motion.empty_display_type = "CIRCLE"
    motion.empty_display_size = 0.25

    aim = bpy.data.objects.new(names["aim"], None)
    _configure_aim_empty(aim)
    aim.rotation_mode = AIM_ROTATION_MODE

    target_coll = cam_obj.users_collection[0] if cam_obj.users_collection else bpy.context.scene.collection
    for obj in (root, body, look, motion, aim):
        _link_object_to_collection(obj, target_coll)

    context = bpy.context
    _deselect_all_objects(context.view_layer)

    _clear_object_constraints(cam_obj)
    cam_obj.parent = None
    cam_obj.matrix_world = cam_mw

    body.parent = root
    look.parent = body
    _reset_local_transform(look)

    motion.parent = look
    _reset_local_transform(motion)

    _apply_rig_pose_from_camera(
        root,
        body,
        aim,
        cam_mw,
        focus_distance,
        look=look,
        motion=motion,
        track_aim=True,
    )

    cam_obj.parent = motion
    _reset_local_transform(cam_obj)

    parts = {
        "root": root,
        "body": body,
        "look": look,
        "motion": motion,
        "aim": aim,
        "cam": cam_obj,
    }
    props = context.scene.monofx_pipeline_blender_props
    props.anim_camera_orbit_follow_aim = False
    props.anim_camera_orbit_display_visible = True
    props.anim_camera_body_orbit_constraint = False
    props.anim_camera_track_aim = True
    _finalize_camera_body_rig(
        context,
        parts,
        cam_obj,
        target_coll,
        enable_orbit=False,
        body_orbit_constraint=False,
    )

    _apply_camera_rig_constraints(
        look,
        motion,
        aim,
        track_aim=bool(getattr(props, "anim_camera_track_aim", True)),
    )

    body.select_set(True)
    context.view_layer.objects.active = body

    set_active_camera_rig(context, cam_obj)

    lock_rig_pose_transforms(parts)

    return True, f"Camera rig created: {names['root']}", body


def resolve_rig_camera_object(obj: Optional[bpy.types.Object]) -> Optional[bpy.types.Object]:
    """Camera object from a rig camera or any of its rig empties."""
    if obj is None:
        return None
    if obj.type == "CAMERA":
        return obj
    base = camera_name_from_rig_part(obj.name)
    if base:
        cam = _object_by_name(base)
        if cam is not None and cam.type == "CAMERA":
            return cam
    cur: Optional[bpy.types.Object] = obj
    while cur is not None:
        if cur.type == "CAMERA":
            return cur
        cur = cur.parent
    return None


def find_camera_rig_parts(
    obj: Optional[bpy.types.Object],
) -> Optional[Dict[str, bpy.types.Object]]:
    cam = resolve_rig_camera_object(obj)
    if cam is None:
        return None
    parts = {
        key: resolve_camera_rig_part_object(cam.name, key) for key in _CAMERA_RIG_PART_KEYS
    }
    parts["cam"] = cam
    if all(parts[key] is not None for key in _CAMERA_RIG_PART_KEYS):
        return parts
    return discover_camera_rig_parts_from_hierarchy(cam)


def vertigo_dolly_delta_distance(subject_distance: float, old_lens: float, new_lens: float) -> float:
    """World-space dolly along view axis to preserve subject scale (dolly zoom)."""
    if old_lens < 1e-6:
        return 0.0
    return float(subject_distance) * (float(new_lens) / float(old_lens) - 1.0)


def _vertigo_subject_distance(cam: bpy.types.Object) -> float:
    parts = find_camera_rig_parts(cam)
    if parts is not None:
        aim = parts.get("aim")
        if aim is not None:
            dist = (aim.matrix_world.translation - cam.matrix_world.translation).length
            if dist >= 0.1:
                return dist
    cam_data = cam.data
    if cam_data is not None and cam_data.dof.use_dof:
        return max(float(cam_data.dof.focus_distance), 0.1)
    return 10.0


def _vertigo_dolly_axis(cam: bpy.types.Object, parts: Optional[Dict[str, bpy.types.Object]]) -> Optional[Vector]:
    if parts is not None:
        aim = parts.get("aim")
        if aim is not None:
            axis = aim.matrix_world.translation - cam.matrix_world.translation
            if axis.length >= 1e-8:
                return axis.normalized()
    forward = cam.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
    if forward.length < 1e-8:
        return None
    return forward.normalized()


def _apply_vertigo_dolly(
    cam: bpy.types.Object,
    old_lens: float,
    new_lens: float,
    target: str,
    *,
    context: Optional[bpy.types.Context] = None,
) -> None:
    """
    Dolly to preserve subject scale when focal length changes.

    ``BODY`` — translate body in world space toward aim (aim stays on root).
    ``MOTION`` — translate motion local Z (along rig view axis; aim stays fixed).
    """
    delta = vertigo_dolly_delta_distance(_vertigo_subject_distance(cam), old_lens, new_lens)
    if abs(delta) < 1e-8:
        return

    parts = find_camera_rig_parts(cam)
    if parts is None:
        axis = _vertigo_dolly_axis(cam, None)
        if axis is None:
            return
        cam.matrix_world.translation -= axis * delta
        _keyframe_object_location(cam, context=context)
        return

    if target == "MOTION":
        motion = parts["motion"]
        motion.location.z += delta
        _keyframe_object_location(motion, context=context)
        return

    axis = _vertigo_dolly_axis(cam, parts)
    if axis is None:
        return
    parts["body"].matrix_world.translation -= axis * delta
    _keyframe_object_location(parts["body"], context=context)


def _aim_focus_distance(
    cam_loc: Vector,
    aim: bpy.types.Object,
    cam_data: Optional[bpy.types.Camera],
) -> float:
    dist = (aim.matrix_world.translation - cam_loc).length
    if dist >= 0.1:
        return dist
    if cam_data is not None and cam_data.dof.use_dof:
        return max(float(cam_data.dof.focus_distance), 0.1)
    return 10.0


def _rebuild_rig_pose_from_camera_matrix(
    context: bpy.types.Context,
    parts: Dict[str, bpy.types.Object],
    cam_w: Matrix,
    focus_distance: float,
) -> bpy.types.Object:
    """Reset rig locals and decompose *cam_w* onto root, mount, aim, and head."""
    root = parts["root"]
    body = parts["body"]
    look = parts["look"]
    motion = parts["motion"]
    aim = parts["aim"]
    cam = parts["cam"]

    _reset_local_transform(body)
    _reset_local_transform(look)
    _reset_local_transform(motion)
    _clear_object_constraints(cam)
    _reset_local_transform(cam)

    props = context.scene.monofx_pipeline_blender_props
    track_aim = bool(getattr(props, "anim_camera_track_aim", True))
    _apply_rig_pose_from_camera(
        root,
        body,
        aim,
        cam_w,
        focus_distance,
        look=look,
        motion=motion,
        track_aim=track_aim,
    )

    enable_orbit = bool(getattr(props, "anim_camera_orbit_follow_aim", False))
    body_constraint = bool(getattr(props, "anim_camera_body_orbit_constraint", False))
    coll = (
        cam.users_collection[0]
        if cam.users_collection
        else context.scene.collection
    )
    _finalize_camera_body_rig(
        context,
        parts,
        cam,
        coll,
        enable_orbit=enable_orbit,
        body_orbit_constraint=body_constraint,
    )

    _apply_camera_rig_constraints(
        look,
        motion,
        aim,
        track_aim=track_aim,
    )

    try:
        context.view_layer.update()
    except Exception:
        pass

    sync_anim_camera_props_from_rig(props, parts)
    return body


def unlock_rig_pose(
    context: bpy.types.Context,
    obj: Optional[bpy.types.Object],
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """Unlock the rig camera for direct framing adjustments."""
    parts = find_camera_rig_parts(obj)
    if parts is None:
        return False, "No camera rig found for the active object.", None
    if not is_rig_pose_locked(parts["cam"]):
        return True, "Camera rig is already unlocked.", parts["cam"]
    cam = unlock_rig_pose_transforms(parts, context=context)
    return True, f"Unlocked {parts['cam'].name} for adjustment", cam


def toggle_rig_pose_lock(
    context: bpy.types.Context,
    obj: Optional[bpy.types.Object],
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """Unlock for adjustment, or lock by baking the evaluated camera pose onto the rig."""
    parts = find_camera_rig_parts(obj)
    if parts is None:
        return False, "No camera rig found for the active object.", None
    if is_rig_pose_locked(parts["cam"]):
        return unlock_rig_pose(context, obj)
    return bake_rig_pose(context, obj)


def bake_rig_pose(
    context: bpy.types.Context,
    obj: Optional[bpy.types.Object],
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """
    Bake evaluated camera onto root (XY), mount (Z), aim (focus), and head rotation.

    Resets look / motion / cam locals, writes head pan / tilt / roll, reapplies
    boom Track Aim when enabled, then locks the camera object transforms.
    """
    parts = find_camera_rig_parts(obj)
    if parts is None:
        return False, "No camera rig found for the active object.", None

    cam = parts["cam"]
    aim = parts["aim"]

    depsgraph = context.evaluated_depsgraph_get()
    cam_w = cam.evaluated_get(depsgraph).matrix_world.copy()
    cam_loc = cam_w.to_translation()
    focus_distance = _aim_focus_distance(cam_loc, aim, cam.data)

    body = _rebuild_rig_pose_from_camera_matrix(
        context,
        parts,
        cam_w,
        focus_distance,
    )

    try:
        _deselect_all_objects(context.view_layer)
        body.select_set(True)
        context.view_layer.objects.active = body
    except Exception:
        pass

    lock_rig_pose_transforms(parts)

    return True, f"Locked {cam.name} rig pose", body


def copy_viewport_to_camera_rig(
    context: bpy.types.Context,
    cam: bpy.types.Object,
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """
    Match the camera rig to the active 3D View (navigation / walk camera).

    Copies world pose, focal length, clip range, and film gate shift from the viewport.
    Preserves the current aim focus distance on the rig.
    """
    _area, region, space = resolve_view3d(context)
    if region is None or space is None:
        return False, "No 3D View found.", None

    rv3d = region.data
    if rv3d is None:
        return False, "No 3D View region data.", None

    parts = find_camera_rig_parts(cam)
    if parts is None:
        return False, "No camera rig found.", None

    try:
        view_mw = rv3d.view_matrix.inverted()
    except Exception as exc:
        return False, f"Could not read viewport matrix: {exc}", None

    cam_obj = parts["cam"]
    aim = parts["aim"]
    props = context.scene.monofx_pipeline_blender_props

    focus_distance = _read_aim_distance(cam_obj, aim)
    if focus_distance < 0.1:
        focus_distance = max(
            float(getattr(props, "anim_camera_aim_distance_stored", 10.0)),
            0.1,
        )

    body = _rebuild_rig_pose_from_camera_matrix(
        context,
        parts,
        view_mw,
        focus_distance,
    )

    if cam_obj.data is not None:
        copy_view_settings_to_camera(space, cam_obj.data)
        sync_anim_camera_props_from_rig(props, parts)

    _set_scene_camera(context, cam_obj)

    return True, f"Matched {cam_obj.name} to viewport", body


def _motion_path_curve_name(cam: bpy.types.Object) -> str:
    return f"{cam.name}_motion_path"


def _sample_camera_world_positions(
    context: bpy.types.Context,
    cam: bpy.types.Object,
    *,
    frame_start: int,
    frame_end: int,
    step: int = 1,
) -> List[Vector]:
    scene = context.scene
    if scene is None:
        return []
    step = max(1, int(step))
    prev_frame = int(scene.frame_current)
    depsgraph = context.evaluated_depsgraph_get()
    positions: List[Vector] = []
    try:
        for frame in range(int(frame_start), int(frame_end) + 1, step):
            scene.frame_set(frame)
            depsgraph.update()
            eval_cam = cam.evaluated_get(depsgraph)
            positions.append(eval_cam.matrix_world.translation.copy())
    finally:
        scene.frame_set(prev_frame)
        depsgraph.update()
    return positions


def _apply_polyline_to_curve_data(
    curve_data: bpy.types.Curve,
    positions: List[Vector],
) -> None:
    while curve_data.splines:
        curve_data.splines.remove(curve_data.splines[0])
    spline = curve_data.splines.new("POLY")
    spline.points.add(len(positions) - 1)
    for index, co in enumerate(positions):
        spline.points[index].co = (float(co.x), float(co.y), float(co.z), 1.0)
    curve_data.dimensions = "3D"
    curve_data.use_path = True


def camera_motion_path_to_curve(
    context: bpy.types.Context,
    cam: bpy.types.Object,
    *,
    frame_start: Optional[int] = None,
    frame_end: Optional[int] = None,
    step: int = 1,
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """
    Sample evaluated camera world positions over a frame range and build/update
    a poly curve named ``{cam}_motion_path``.
    """
    if cam is None or cam.type != "CAMERA":
        return False, "Active object is not a camera.", None

    scene = context.scene
    if scene is None:
        return False, "No active scene.", None

    f0 = int(frame_start if frame_start is not None else scene.frame_start)
    f1 = int(frame_end if frame_end is not None else scene.frame_end)
    if f1 <= f0:
        return False, "Frame range must span at least 2 frames.", None

    positions = _sample_camera_world_positions(
        context,
        cam,
        frame_start=f0,
        frame_end=f1,
        step=step,
    )
    if len(positions) < 2:
        return False, "Not enough samples to build a motion path curve.", None

    curve_name = _motion_path_curve_name(cam)
    path_obj = bpy.data.objects.get(curve_name)
    if path_obj is not None and path_obj.type != "CURVE":
        path_obj = None

    if path_obj is None:
        curve_data = bpy.data.curves.new(curve_name, type="CURVE")
        _apply_polyline_to_curve_data(curve_data, positions)
        path_obj = bpy.data.objects.new(curve_name, curve_data)
        path_obj.matrix_world = Matrix.Identity(4)
        target_coll = (
            cam.users_collection[0]
            if cam.users_collection
            else scene.collection
        )
        _link_object_to_collection(path_obj, target_coll)
    else:
        _apply_polyline_to_curve_data(path_obj.data, positions)
        path_obj.matrix_world = Matrix.Identity(4)

    view_layer = context.view_layer
    try:
        _deselect_all_objects(view_layer)
        path_obj.select_set(True)
        if view_layer is not None:
            view_layer.objects.active = path_obj
    except Exception:
        pass

    return (
        True,
        f"Created {curve_name} ({len(positions)} points, frames {f0}–{f1})",
        path_obj,
    )


def bake_to_body(
    context: bpy.types.Context,
    obj: Optional[bpy.types.Object],
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """Backward-compatible alias for :func:`bake_rig_pose`."""
    return bake_rig_pose(context, obj)


def snap_body_to_camera(
    context: bpy.types.Context,
    obj: Optional[bpy.types.Object],
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """Backward-compatible alias for :func:`bake_rig_pose`."""
    return bake_rig_pose(context, obj)


def snap_root_to_camera(
    context: bpy.types.Context,
    obj: Optional[bpy.types.Object],
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """Backward-compatible alias for :func:`bake_rig_pose`."""
    return bake_rig_pose(context, obj)


# ---------------------------------------------------------------------------
# Aim to 3D cursor (live rig aim sync)
# ---------------------------------------------------------------------------

_AIM_CURSOR_MSGBUS_OWNER = object()
_aim_cursor_timer = None


def _scene_props(scene: bpy.types.Scene):
    return getattr(scene, "monofx_pipeline_blender_props", None)


def _iter_scenes_safe():
    try:
        return list(bpy.data.scenes)
    except (AttributeError, TypeError, RuntimeError):
        return []


def any_scene_cursor_sync_enabled() -> bool:
    for scene in _iter_scenes_safe():
        props = _scene_props(scene)
        if props is None:
            continue
        if bool(getattr(props, "anim_camera_aim_to_cursor", False)):
            return True
        if bool(getattr(props, "anim_camera_root_to_cursor", False)):
            return True
    return False


def sync_aim_to_cursor(
    scene: bpy.types.Scene,
    *,
    context: Optional[bpy.types.Context] = None,
) -> bool:
    """Move rig *aim* to the scene 3D cursor. Returns True when aim was updated."""
    props = _scene_props(scene)
    if props is None or not props.anim_camera_aim_to_cursor:
        return False
    cam = resolve_active_rig_camera(context or bpy.context, props=props, scene=scene)
    if cam is None:
        return False
    parts = find_camera_rig_parts(cam)
    if parts is None:
        return False

    aim = parts["aim"]
    root = parts["root"]
    aim_lock = bool(getattr(props, "anim_camera_aim_lock", False))
    if aim_lock:
        depth = max(_cursor_depth_on_camera(cam, scene.cursor.location), 0.1)
        current = _read_aim_distance(cam, aim)
        if abs(depth - current) <= 1e-6:
            return False
        _set_aim_distance_on_parts(parts, depth, context=context)
        props.anim_camera_aim_distance_stored = depth
        return True

    target_local = root.matrix_world.inverted() @ scene.cursor.location
    if (aim.location - target_local).length <= 1e-6:
        return False
    aim.location = target_local
    _keyframe_object_location(aim, context=context)
    props.anim_camera_aim_distance_stored = _read_aim_distance(cam, aim)
    return True


def sync_root_to_cursor(
    scene: bpy.types.Scene,
    *,
    context: Optional[bpy.types.Context] = None,
) -> bool:
    """Move rig *root* XY to the scene 3D cursor. Keeps Z at 0. Returns True when root was updated."""
    props = _scene_props(scene)
    if props is None or not bool(getattr(props, "anim_camera_root_to_cursor", False)):
        return False
    cam = resolve_active_rig_camera(context or bpy.context, props=props, scene=scene)
    if cam is None:
        return False
    parts = find_camera_rig_parts(cam)
    if parts is None:
        return False
    root = parts["root"]
    cur = scene.cursor.location
    include_z = bool(getattr(props, "anim_camera_root_to_cursor_z", False))
    target = Vector((cur.x, cur.y, cur.z if include_z else 0.0))
    if (root.matrix_world.translation - target).length <= 1e-6:
        return False
    root.matrix_world.translation = target
    _keyframe_object_location(root, context=context)
    return True


def _sync_all_aims_to_cursor() -> None:
    ctx = bpy.context
    for scene in _iter_scenes_safe():
        sync_aim_to_cursor(scene, context=ctx)


def _sync_all_roots_to_cursor() -> None:
    ctx = bpy.context
    for scene in _iter_scenes_safe():
        sync_root_to_cursor(scene, context=ctx)


def _stop_aim_to_cursor_timer() -> None:
    global _aim_cursor_timer
    if _aim_cursor_timer is None:
        return
    try:
        bpy.app.timers.unregister(_aim_cursor_timer)
    except Exception:
        pass
    _aim_cursor_timer = None


def _aim_to_cursor_timer_tick() -> Optional[float]:
    if not any_scene_cursor_sync_enabled():
        _stop_aim_to_cursor_timer()
        return None
    _sync_all_aims_to_cursor()
    _sync_all_roots_to_cursor()
    return 0.016


def _ensure_aim_to_cursor_timer() -> None:
    global _aim_cursor_timer
    if not any_scene_cursor_sync_enabled():
        _stop_aim_to_cursor_timer()
        return
    if _aim_cursor_timer is not None:
        return
    _aim_cursor_timer = bpy.app.timers.register(
        _aim_to_cursor_timer_tick,
        first_interval=0.0,
        persistent=True,
    )


def _on_cursor_location_changed(*_args) -> None:
    if not any_scene_cursor_sync_enabled():
        return
    _sync_all_aims_to_cursor()
    _sync_all_roots_to_cursor()


def on_aim_to_cursor_changed(props, context: Optional[bpy.types.Context]) -> None:
    if context is None or context.scene is None:
        return
    if props.anim_camera_aim_to_cursor:
        sync_aim_to_cursor(context.scene, context=context)
        _ensure_aim_to_cursor_timer()
    elif not any_scene_cursor_sync_enabled():
        _stop_aim_to_cursor_timer()


def on_aim_lock_changed(props, context: Optional[bpy.types.Context]) -> None:
    if context is None or context.scene is None:
        return
    if props.anim_camera_aim_to_cursor:
        sync_aim_to_cursor(context.scene, context=context)


def on_root_to_cursor_changed(props, context: Optional[bpy.types.Context]) -> None:
    if context is None or context.scene is None:
        return
    if bool(getattr(props, "anim_camera_root_to_cursor", False)):
        sync_root_to_cursor(context.scene, context=context)
        _ensure_aim_to_cursor_timer()
    elif not any_scene_cursor_sync_enabled():
        _stop_aim_to_cursor_timer()


def register_aim_to_cursor_listeners() -> None:
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.View3DCursor, "location"),
        owner=_AIM_CURSOR_MSGBUS_OWNER,
        args=(),
        notify=_on_cursor_location_changed,
        options={"PERSISTENT"},
    )
    if any_scene_cursor_sync_enabled():
        _ensure_aim_to_cursor_timer()


def unregister_aim_to_cursor_listeners() -> None:
    bpy.msgbus.clear_by_owner(_AIM_CURSOR_MSGBUS_OWNER)
    _stop_aim_to_cursor_timer()
