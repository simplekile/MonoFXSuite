"""
Anim Tools tab UI.
"""

from __future__ import annotations

import bpy
from bpy.types import Context, UILayout

from . import anim_camera
from . import anim_collections
from . import anim_transform
from . import preferences
from . import ui_style


def _draw_anim_shot_section(body: UILayout, _context: Context) -> None:
    shot = anim_collections.detect_shot_from_blend_filepath(bpy.data.filepath)
    if shot:
        body.label(text=f"Shot: {shot}", icon="FILE_FOLDER")
    elif bpy.data.filepath:
        row = body.row()
        row.alert = True
        row.label(text="No sh### in file path", icon="ERROR")
    else:
        row = body.row()
        row.alert = True
        row.label(text="Save .blend to detect shot", icon="ERROR")
    row = body.row(align=True)
    row.operator(
        "wm.mono_fx_anim_create_shot_collections",
        text="Create Shot Collections",
        icon="NEWFOLDER",
    )
    row.operator(
        "wm.mono_fx_anim_fix_shot_collections",
        text="Name Fixer",
        icon="SORTALPHA",
    )


def _draw_anim_selection_section(body: UILayout, _context: Context) -> None:
    body.operator(
        "wm.mono_fx_anim_select_chain",
        text="Select Chain",
        icon="LINKED",
    )
    body.operator(
        "wm.mono_fx_anim_select_keyed_objects",
        text="Select Keyed Objects",
        icon="KEY_HLT",
    )


def _draw_anim_transform_section(body: UILayout, context: Context) -> None:
    if anim_transform.has_world_transform_clipboard():
        source = anim_transform.clipboard_source_name()
        body.label(text=f"Copied: {source}", icon="COPYDOWN")
    else:
        row = body.row()
        row.enabled = False
        row.label(text="No transform copied", icon="INFO")

    row = body.row(align=True)
    row.operator(
        "wm.mono_fx_anim_copy_world_transform",
        text="Copy World Transform",
        icon="COPYDOWN",
    )
    paste = row.row(align=True)
    paste.enabled = anim_transform.can_paste_world_transform(context)
    paste.operator(
        "wm.mono_fx_anim_paste_world_transform",
        text="Paste World Transform",
        icon="PASTEDOWN",
    )


def _draw_anim_keys_section(body: UILayout, context: Context) -> None:
    props = context.scene.monofx_pipeline_blender_props
    ui_style.prop_checkbox(body, props, "anim_clean_single_key")
    ui_style.prop_checkbox(body, props, "anim_clean_static_key")
    body.operator(
        "wm.mono_fx_anim_clean_static_keys",
        text="Clean Static Keys",
        icon="BRUSH_DATA",
    )


def _draw_camera_motion_guide(
    parent: UILayout,
    context: Context,
    *,
    prefs,
) -> None:
    cam = anim_camera.resolve_active_rig_camera(context, props=context.scene.monofx_pipeline_blender_props)
    cam_token = cam.name if cam is not None else "cam_sh###"

    guide_body, guide_open = ui_style.collapsible_section(
        parent,
        "monofx_anim_camera_motion_guide",
        "Motion Guide",
        icon="INFO",
        default_closed=True,
        prefs=prefs,
    )
    if not guide_open or guide_body is None:
        return

    layers = guide_body.column(align=True)
    layers.label(text="Rig layers (Outliner):", icon="OUTLINER")
    layer_col = layers.column(align=True)
    layer_col.enabled = False
    for line in anim_camera.CAMERA_RIG_LAYERS:
        layer_col.label(text=line.format(cam=cam_token), icon="DOT")

    guide_body.separator()
    guide_body.label(text="On-set move → rig control:", icon="HAND")
    move_col = guide_body.column(align=True)
    move_col.enabled = False
    for control, on_set, rig in anim_camera.CAMERA_MOTION_GUIDE:
        move_col.label(text=f"{control} — {on_set}", icon="BLANK1")
        sub = move_col.row()
        sub.separator(factor=2.0)
        sub.label(text=rig.format(cam=cam_token))


def _camera_rig_ui_state(context: Context):
    props = context.scene.monofx_pipeline_blender_props
    active_cam = anim_camera.resolve_active_rig_camera(context, props=props)
    parts = anim_camera.find_camera_rig_parts(active_cam)
    return props, parts


def _draw_camera_rig_selector(layout: UILayout, context: Context) -> None:
    props = context.scene.monofx_pipeline_blender_props
    layout.prop(props, "anim_camera_active_rig", text="Rig")


def _draw_camera_setup_section(body: UILayout, context: Context, *, prefs) -> None:
    props, parts = _camera_rig_ui_state(context)
    has_rig = parts is not None
    cam_obj = parts.get("cam") if parts else None
    root_obj = parts.get("root") if parts else None
    aim_obj = parts.get("aim") if parts else None

    main, main_open = ui_style.collapsible_section(
        body,
        "monofx_anim_camera_setup",
        "Camera Setup",
        icon="TOOL_SETTINGS",
        default_closed=False,
        prefs=prefs,
    )
    if not main_open or main is None:
        return

    row = main.row(align=True)
    row.use_property_split = True
    if cam_obj is not None and cam_obj.data is not None:
        row.prop(cam_obj.data, "lens", text="Focal Length")
    else:
        row.prop(props, "anim_camera_focal_length", text="Focal Length")

    current_lens = float(props.anim_camera_focal_length)
    preset_row = main.row(align=True)
    for lens_mm, _label, _tooltip in anim_camera.CINEMATIC_FOCAL_LENGTH_PRESETS:
        text = f"{int(lens_mm)}" if lens_mm == int(lens_mm) else f"{lens_mm:g}"
        preset_row.operator(
            anim_camera.focal_preset_operator_id(lens_mm),
            text=text,
            depress=abs(current_lens - lens_mm) < 0.5,
        )

    dof_row = main.row(align=True)
    dof_row.use_property_split = True
    if cam_obj is not None and cam_obj.data is not None:
        ui_style.prop_checkbox(
            dof_row,
            cam_obj.data.dof,
            "use_dof",
            text="Depth of Field",
        )
    else:
        dof_row.enabled = False
        dof_row.label(text="Depth of Field", icon="INFO")

    vertigo_body, vertigo_open = ui_style.collapsible_section(
        main,
        "monofx_anim_camera_vertigo",
        "Vertigo",
        icon="OUTLINER_DATA_CAMERA",
        default_closed=False,
        prefs=prefs,
    )
    if vertigo_open and vertigo_body is not None:
        vertigo_col = vertigo_body.column(align=True)
        vertigo_col.enabled = has_rig
        ui_style.prop_checkbox(vertigo_col, props, "anim_camera_vertigo", text="Vertigo")
        if props.anim_camera_vertigo:
            target_row = vertigo_col.row(align=True)
            target_row.prop(props, "anim_camera_vertigo_target", expand=True)

    root_body, root_open = ui_style.collapsible_section(
        main,
        "monofx_anim_camera_root",
        "Root Setup",
        icon="EMPTY_AXIS",
        default_closed=False,
        prefs=prefs,
    )
    if root_open and root_body is not None:
        root_col = root_body.column(align=True)
        root_col.enabled = has_rig
        root_col.use_property_split = True
        ui_style.prop_checkbox(
            root_col,
            props,
            "anim_camera_root_to_cursor",
            text="Root to Cursor",
        )
        ui_style.prop_checkbox(
            root_col,
            props,
            "anim_camera_root_to_cursor_z",
            text="Enable Root Z",
        )
        for axis, label in ((0, "X"), (1, "Y"), (2, "Z")):
            ui_style.prop_object_channel(
                root_col,
                root_obj,
                "location",
                axis,
                text=label,
            )

    aim_body, aim_open = ui_style.collapsible_section(
        main,
        "monofx_anim_camera_aim",
        "Aim Setup",
        icon="PIVOT_CURSOR",
        default_closed=False,
        prefs=prefs,
    )
    if aim_open and aim_body is not None:
        aim_col = aim_body.column(align=True)
        aim_col.enabled = has_rig
        aim_col.use_property_split = True
        ui_style.prop_checkbox(
            aim_col,
            props,
            "anim_camera_aim_to_cursor",
            text="Aim to Cursor",
        )
        ui_style.prop_checkbox(
            aim_col,
            props,
            "anim_camera_aim_lock",
            text="Aim Lock",
        )
        for axis, label in ((0, "X"), (1, "Y"), (2, "Z")):
            ui_style.prop_object_channel(
                aim_col,
                aim_obj,
                "location",
                axis,
                text=label,
            )
        aim_col.prop(props, "anim_camera_aim_distance", text="Aim Distance")

    orbit_body, orbit_open = ui_style.collapsible_section(
        main,
        "monofx_anim_camera_orbit",
        "Orbit",
        icon="DRIVER_ROTATIONAL_DIFFERENCE",
        default_closed=False,
        prefs=prefs,
    )
    if orbit_open and orbit_body is not None:
        orbit_col = orbit_body.column(align=True)
        orbit_col.enabled = has_rig
        ui_style.prop_checkbox(
            orbit_col,
            props,
            "anim_camera_orbit_follow_aim",
            text="Enable Orbit",
        )
        snap_row = orbit_col.row(align=True)
        snap_row.operator(
            "wm.mono_fx_anim_orbit_to_aim",
            text="Orbit to Aim",
            icon="CON_TRANSFORM",
        )
        snap_row.operator(
            "wm.mono_fx_anim_orbit_to_cursor",
            text="Orbit to Cursor",
            icon="CURSOR",
        )
        constraint_row = orbit_col.row(align=True)
        ui_style.prop_checkbox(
            constraint_row,
            props,
            "anim_camera_body_orbit_constraint",
            text="Mount to Orbit",
        )

        display_body, display_open = ui_style.collapsible_section(
            orbit_body,
            "monofx_anim_camera_orbit_display",
            "Orbit Display",
            icon="MESH_CIRCLE",
            default_closed=False,
            prefs=prefs,
        )
        if display_open and display_body is not None:
            display_col = display_body.column(align=True)
            display_col.enabled = has_rig and bool(
                getattr(props, "anim_camera_orbit_follow_aim", False)
            )
            ui_style.prop_checkbox(
                display_col,
                props,
                "anim_camera_orbit_display_visible",
                text="Show Display",
            )
            display_col.prop(props, "anim_camera_orbit_arrow_size", text="Arrow Size")

    if not has_rig:
        hint = main.row()
        hint.enabled = False
        hint.label(text="Requires a camera rig", icon="INFO")


def _draw_camera_rig_tools_section(body: UILayout, context: Context, *, prefs) -> None:
    props, parts = _camera_rig_ui_state(context)
    has_rig = parts is not None
    cam_obj = parts.get("cam") if parts else None

    content = body.column(align=True)
    content.enabled = has_rig
    content.operator(
        "wm.mono_fx_anim_name_fixer",
        text="Cam Rig Fixer",
        icon="FONT_DATA",
    )
    locked = (
        anim_camera.is_rig_pose_locked(cam_obj)
        if cam_obj is not None
        else True
    )
    pose_row = content.row(align=True)
    pose_row.operator(
        "wm.mono_fx_anim_toggle_rig_pose_lock",
        text="Locked" if locked else "Unlocked",
        icon="LOCKED" if locked else "UNLOCKED",
        depress=locked,
    )
    viewport_row = pose_row.row(align=True)
    viewport_row.enabled = has_rig and not locked
    viewport_row.operator(
        "wm.mono_fx_anim_viewport_to_camera_rig",
        text="Viewport to Camera",
        icon="VIEW_CAMERA",
    )
    rig_select_row = content.row(align=True)
    rig_select_row.operator(
        "wm.mono_fx_anim_select_camera_rig",
        text="Select Camera Rig",
        icon="RESTRICT_SELECT_OFF",
    )
    rig_select_row.operator(
        "wm.mono_fx_anim_clean_camera_rig_keys",
        text="Clean Rig Keyframes",
        icon="BRUSH_DATA",
    )
    content.operator(
        "wm.mono_fx_anim_camera_motion_path_to_curve",
        text="Motion Path to Curve",
        icon="CURVE_PATH",
    )
    rig_row = content.row(align=True)
    rig_row.operator(
        "wm.mono_fx_anim_copy_camera_rig",
        text="Copy Rig",
        icon="COPYDOWN",
    )
    rig_row.operator(
        "wm.mono_fx_anim_duplicate_camera_rig",
        text="Duplicate Rig",
        icon="DUPLICATE",
    )
    rig_row.operator(
        "wm.mono_fx_anim_rename_camera_rig",
        text="Rename Rig",
        icon="SORTALPHA",
    )

    if not has_rig:
        hint = body.row()
        hint.enabled = False
        hint.label(text="Requires a camera rig", icon="INFO")


def _draw_camera_motion_section(body: UILayout, context: Context, *, prefs) -> None:
    props, parts = _camera_rig_ui_state(context)
    has_rig = parts is not None
    body_obj = parts.get("body") if parts else None
    look_obj = parts.get("look") if parts else None
    motion_obj = parts.get("motion") if parts else None
    orbit_obj = parts.get("orbit") if parts else None

    render_body, render_open = ui_style.collapsible_section(
        body,
        "monofx_anim_camera_motion_render",
        "Render",
        icon="RENDER_STILL",
        default_closed=False,
        prefs=prefs,
    )
    if render_open and render_body is not None:
        scene = context.scene
        if scene is not None:
            ui_style.prop_checkbox(
                render_body,
                scene.render,
                "use_motion_blur",
                text="Motion Blur",
            )

    main, main_open = ui_style.collapsible_section(
        body,
        "monofx_anim_camera_motion",
        "Camera Motion",
        icon="ORIENTATION_GIMBAL",
        default_closed=False,
        prefs=prefs,
    )
    if not main_open or main is None:
        if not has_rig:
            hint = body.row()
            hint.enabled = False
            hint.label(text="Requires a camera rig", icon="INFO")
        return

    main.enabled = has_rig

    mount_body, mount_open = ui_style.collapsible_section(
        main,
        "monofx_anim_camera_motion_mount",
        "Pedestal & Crane",
        icon="EMPTY_ARROWS",
        default_closed=False,
        prefs=prefs,
    )
    if mount_open and mount_body is not None:
        mount = mount_body.column(align=True)
        mount.enabled = has_rig
        mount.use_property_split = True
        ui_style.prop_checkbox(mount, props, "anim_camera_track_aim", text="Track Aim")
        ui_style.prop_object_channel(
            mount,
            body_obj,
            "location",
            2,
            text="Pedestal",
            fallback_data=props,
            fallback_prop="anim_camera_body_height",
        )
        ui_style.prop_object_channel(
            mount,
            look_obj,
            "location",
            2,
            text="Crane Boom",
            fallback_data=props,
            fallback_prop="anim_camera_crane_length",
        )
        ui_style.prop_object_channel(
            mount,
            body_obj,
            "rotation_euler",
            0,
            text="Crane Tilt",
            fallback_data=props,
            fallback_prop="anim_camera_crane_angle",
        )

    track_body, track_open = ui_style.collapsible_section(
        main,
        "monofx_anim_camera_motion_track",
        "Dolly Track",
        icon="MOD_ARMATURE",
        default_closed=True,
        prefs=prefs,
    )
    if track_open and track_body is not None:
        track = track_body.column(align=True)
        track.enabled = has_rig
        track.use_property_split = True
        ui_style.prop_object_channel(
            track,
            body_obj,
            "location",
            1,
            text="Track Dolly",
            fallback_data=props,
            fallback_prop="anim_camera_body_track_y",
        )
        ui_style.prop_object_channel(
            track,
            body_obj,
            "location",
            0,
            text="Track Truck",
            fallback_data=props,
            fallback_prop="anim_camera_body_track",
        )

    head_body, head_open = ui_style.collapsible_section(
        main,
        "monofx_anim_camera_motion_head",
        "Head",
        icon="OUTLINER_OB_CAMERA",
        default_closed=False,
        prefs=prefs,
    )
    if head_open and head_body is not None:
        head = head_body.column(align=True)
        head.enabled = has_rig
        head.use_property_split = True
        ui_style.prop_object_channel(
            head,
            motion_obj,
            "location",
            2,
            text="Dolly",
            fallback_data=props,
            fallback_prop="anim_camera_motion_dolly",
        )
        ui_style.prop_object_channel(
            head,
            motion_obj,
            "location",
            0,
            text="Truck",
            fallback_data=props,
            fallback_prop="anim_camera_motion_truck",
        )
        ui_style.prop_object_channel(
            head,
            motion_obj,
            "rotation_euler",
            1,
            text="Pan",
            fallback_data=props,
            fallback_prop="anim_camera_motion_pan",
        )
        ui_style.prop_object_channel(
            head,
            motion_obj,
            "rotation_euler",
            0,
            text="Tilt",
            fallback_data=props,
            fallback_prop="anim_camera_motion_tilt",
        )
        ui_style.prop_object_channel(
            head,
            motion_obj,
            "rotation_euler",
            2,
            text="Roll",
            fallback_data=props,
            fallback_prop="anim_camera_motion_roll",
        )

    orbit_body, orbit_open = ui_style.collapsible_section(
        main,
        "monofx_anim_camera_motion_orbit",
        "Orbit",
        icon="DRIVER_ROTATIONAL_DIFFERENCE",
        default_closed=True,
        prefs=prefs,
    )
    if orbit_open and orbit_body is not None:
        orbit_col = orbit_body.column(align=True)
        orbit_col.enabled = has_rig
        orbit_col.use_property_split = True
        ui_style.prop_object_channel(
            orbit_col,
            orbit_obj,
            "rotation_euler",
            2,
            text="Orbit",
            fallback_data=props,
            fallback_prop="anim_camera_orbit",
        )

    _draw_camera_motion_guide(main, context, prefs=prefs)

    if not has_rig:
        hint = body.row()
        hint.enabled = False
        hint.label(text="Requires a camera rig", icon="INFO")


def _draw_anim_camera_section(body: UILayout, context: Context, *, prefs) -> None:
    main, main_open = ui_style.collapsible_section(
        body,
        "monofx_anim_camera_tools",
        "Camera Tools",
        icon="OUTLINER_OB_CAMERA",
        default_closed=False,
        prefs=prefs,
    )
    if not main_open or main is None:
        return
    main.operator(
        "wm.mono_fx_anim_camera_from_view",
        text="Camera from View",
        icon="VIEW_CAMERA",
    )
    main.operator(
        "wm.mono_fx_anim_select_scene_camera",
        text="Select Scene Camera",
        icon="RESTRICT_SELECT_OFF",
    )
    main.operator(
        "wm.mono_fx_anim_setup_camera_rig",
        text="Setup Camera Rig",
        icon="ORIENTATION_GIMBAL",
    )


def draw_camera_tools_tab(layout: UILayout, context: Context) -> None:
    prefs = preferences.get_addon_prefs(context)
    if prefs is None:
        layout.label(text="Add-on preferences unavailable", icon="ERROR")
        return

    box = layout.box()
    _draw_camera_rig_selector(box, context)
    _tabs, body = ui_style.draw_vertical_tabs(box, prefs, "ui_camera_tools_section")
    section = prefs.ui_camera_tools_section
    if section == "CAMERA":
        _draw_anim_camera_section(body, context, prefs=prefs)
    elif section == "SETUP":
        _draw_camera_setup_section(body, context, prefs=prefs)
    elif section == "RIG":
        _draw_camera_rig_tools_section(body, context, prefs=prefs)
    elif section == "MOTION":
        _draw_camera_motion_section(body, context, prefs=prefs)


def draw_anim_tools_tab(layout: UILayout, context: Context) -> None:
    prefs = preferences.get_addon_prefs(context)
    if prefs is None:
        layout.label(text="Add-on preferences unavailable", icon="ERROR")
        return

    box = layout.box()
    _tabs, body = ui_style.draw_vertical_tabs(box, prefs, "ui_anim_tools_section")
    section = prefs.ui_anim_tools_section
    if section == "SELECTION":
        _draw_anim_selection_section(body, context)
    elif section == "TRANSFORM":
        _draw_anim_transform_section(body, context)
    elif section == "KEYS":
        _draw_anim_keys_section(body, context)
