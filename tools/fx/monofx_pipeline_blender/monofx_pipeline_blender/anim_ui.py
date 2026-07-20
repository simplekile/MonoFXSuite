"""
Anim Tools tab UI.
"""

from __future__ import annotations

import bpy
from bpy.types import Context, Panel, UILayout

from . import anim_camera
from . import anim_collections
from . import anim_sine_chain_bpy
from . import anim_sine_ramp_bpy
from . import anim_transform
from . import preferences
from . import ui_style
from monofx_pipeline_common.anim_sine_chain import resolve_apply_sine_axes, resolve_sine_axis_settings


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
        body.label(text=f"Clipboard ← {source}", icon="COPYDOWN")
    else:
        row = body.row()
        row.enabled = False
        row.label(text="Clipboard empty", icon="COPYDOWN")

    row = body.row(align=True)
    row.operator(
        "wm.mono_fx_anim_copy_world_transform",
        text="Copy",
        icon="COPYDOWN",
    )
    paste = row.row(align=True)
    paste.enabled = anim_transform.can_paste_world_transform(context)
    paste.operator(
        "wm.mono_fx_anim_paste_world_transform",
        text="Paste",
        icon="PASTEDOWN",
    )


def _draw_anim_keys_section(body: UILayout, context: Context) -> None:
    props = context.scene.monofx_pipeline_blender_props
    body.operator(
        "wm.mono_fx_anim_edit_exact_key",
        text="Edit Exact Keyframe",
        icon="KEYFRAME",
    )
    ui_style.prop_checkbox(body, props, "anim_clean_single_key")
    ui_style.prop_checkbox(body, props, "anim_clean_static_key")
    body.operator(
        "wm.mono_fx_anim_clean_static_keys",
        text="Clean Static Keys",
        icon="BRUSH_DATA",
    )


def draw_sine_amp_ramp_popover(
    layout: UILayout,
    context: Context,
    *,
    channel: str,
    axis: str,
) -> None:
    props = context.scene.monofx_pipeline_blender_props
    axis_props = resolve_sine_axis_settings(props, channel, axis)
    layout.label(
        text=f"{channel.title()} {axis} — Amplitude Ramp",
        icon="GRAPH",
    )
    ui_style.draw_panel_tabs(layout, axis_props, "amp_ramp_mode")
    body = layout.column()
    if axis_props.amp_ramp_mode == "ROOT_TIP":
        body.prop(axis_props, "amp_root")
        body.prop(axis_props, "amp_tip")
        body.label(text="Linear amplitude from root → tip", icon="INFO")
    else:
        body.label(text="Y multiplies main Amplitude; X is root → tip", icon="INFO")
        ramp_node = anim_sine_ramp_bpy.get_amp_ramp_node(channel, axis, create=False)
        if ramp_node is None:
            anim_sine_ramp_bpy.schedule_amp_ramp_node_ensure(channel, axis)
            row = body.row()
            row.enabled = False
            row.label(text="Ramp curve loading…", icon="INFO")
        else:
            body.template_curve_mapping(ramp_node, "mapping", type="NONE")
    row = body.row()
    refresh = row.operator(
        "wm.mono_fx_anim_refresh_sine_ramp",
        text="Refresh Ramp",
        icon="FILE_REFRESH",
    )
    refresh.channel = channel
    refresh.axis = axis


class MONOFX_PT_sine_amp_ramp(Panel):
    bl_label = "Amplitude Ramp"
    bl_idname = "MONOFX_PT_sine_amp_ramp"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_ui_units_x = 20

    def draw(self, context: Context) -> None:
        props = context.scene.monofx_pipeline_blender_props
        channel = str(props.anim_sine_channel)
        axis = str(props.anim_sine_axis).upper()
        if axis not in {"X", "Y", "Z"}:
            axis = "Z"
        draw_sine_amp_ramp_popover(self.layout, context, channel=channel, axis=axis)


def _axis_has_rna_property(axis_props, prop_name: str) -> bool:
    rna_props = getattr(getattr(axis_props, "bl_rna", None), "properties", None)
    return rna_props is not None and prop_name in rna_props



def _draw_sine_axis_params(body: UILayout, props, *, channel: str, axis: str) -> None:
    axis_props = resolve_sine_axis_settings(props, channel, axis)
    if _axis_has_rna_property(axis_props, "enabled"):
        row = body.row(align=True)
        ui_style.prop_checkbox(row, axis_props, "enabled", text=f"Enable {axis}")

    params = body.column(align=True)
    params.use_property_split = True
    params.prop(axis_props, "amplitude")
    params.prop(axis_props, "speed")
    params.prop(axis_props, "frequency")
    row = params.row(align=True)
    row.use_property_split = False
    split = row.split(factor=0.82, align=True)
    split.prop(axis_props, "phase")
    op = split.operator(
        "wm.mono_fx_anim_randomize_sine_phase",
        text="",
        icon="FILE_REFRESH",
    )
    op.channel = channel
    op.axis = axis
    if _axis_has_rna_property(axis_props, "chain_offset"):
        params.prop(axis_props, "chain_offset")

    ramp_row = body.row(align=True)
    anim_sine_ramp_bpy.schedule_amp_ramp_node_ensure(channel, axis)
    ramp_row.popover(
        panel="MONOFX_PT_sine_amp_ramp",
        text="Amplitude Ramp",
        icon="GRAPH",
    )
    refresh = ramp_row.operator(
        "wm.mono_fx_anim_refresh_sine_ramp",
        text="",
        icon="FILE_REFRESH",
    )
    refresh.channel = channel
    refresh.axis = axis


def _draw_sine_amp_ramp_inline(body: UILayout, context: Context, *, channel: str, axis: str) -> None:
    axis_props = resolve_sine_axis_settings(
        context.scene.monofx_pipeline_blender_props,
        channel,
        axis,
    )
    ramp_body, ramp_open = ui_style.collapsible_section(
        body,
        f"monofx_anim_sine_ramp_{channel.lower()}_{axis.lower()}",
        "Amplitude Ramp",
        icon="GRAPH",
        default_closed=False,
    )
    if not ramp_open or ramp_body is None:
        return
    draw_sine_amp_ramp_popover(ramp_body, context, channel=channel, axis=axis)


def _draw_anim_chain_section(body: UILayout, context: Context, *, prefs) -> None:
    props = context.scene.monofx_pipeline_blender_props
    scene = context.scene
    rows, chain_err = anim_sine_chain_bpy.preview_sine_chain_rows(context)
    chain_title = (
        f"Chain Targets ({len(rows)})" if rows else "Chain Targets"
    )

    header = body.row(align=True)
    header.label(text="Chain Animator", icon="FORCE_CURVE")
    wave_row = body.row(align=True)
    wave_row.prop(props, "anim_sine_wave_mode", expand=True)

    bake_body, bake_open = ui_style.collapsible_section(
        body,
        "monofx_anim_sine_bake_range",
        "Bake Frame Range",
        icon="TIME",
        default_closed=True,
        prefs=prefs,
    )
    if bake_open and bake_body is not None:
        bake_col = bake_body.column(align=True)
        ui_style.prop_checkbox(
            bake_col,
            props,
            "anim_sine_bake_use_scene_range",
            text="Use Scene Range",
        )
        range_row = bake_col.row(align=True)
        range_row.enabled = not bool(props.anim_sine_bake_use_scene_range)
        range_row.prop(props, "anim_sine_bake_frame_start", text="Start")
        range_row.prop(props, "anim_sine_bake_frame_end", text="End")
        if props.anim_sine_bake_use_scene_range and scene is not None:
            hint = bake_col.row()
            hint.enabled = False
            hint.label(
                text=f"Scene: {int(scene.frame_start)} – {int(scene.frame_end)}",
                icon="INFO",
            )

    action_row = body.row(align=True)
    action_row.operator(
        "wm.mono_fx_anim_select_chain",
        text="Select Chain",
        icon="LINKED",
    )
    action_row.operator(
        "wm.mono_fx_anim_reset_sine_chain",
        text="Reset",
        icon="LOOP_BACK",
    )

    ui_style.draw_panel_tabs(body, props, "anim_sine_channel")
    channel = str(props.anim_sine_channel)
    _tabs, tab_body = ui_style.draw_vertical_tabs(body, props, "anim_sine_axis", factor=0.18)
    axis = str(props.anim_sine_axis).upper()
    if axis not in {"X", "Y", "Z"}:
        axis = "Z"
    _draw_sine_axis_params(tab_body, props, channel=channel, axis=axis)
    _draw_sine_amp_ramp_inline(body, context, channel=channel, axis=axis)

    enabled_axes = resolve_apply_sine_axes(props, channel, str(props.anim_sine_axis))
    if enabled_axes:
        hint = body.row()
        hint.enabled = False
        hint.label(
            text=f"Apply uses: {', '.join(enabled_axes)}",
            icon="INFO",
        )
    else:
        hint = body.row()
        hint.alert = True
        hint.label(text="Enable at least one axis", icon="ERROR")

    settings_body, settings_open = ui_style.collapsible_section(
        body,
        "monofx_anim_sine_chain_settings",
        "Chain Resolution",
        icon="OUTLINER",
        default_closed=True,
        prefs=prefs,
    )
    if settings_open and settings_body is not None:
        settings_body.prop(props, "anim_sine_bone_mode", text="Chain Mode")
        settings_body.prop(props, "anim_sine_multi_chain", text="Multi Chains")
        if props.anim_sine_multi_chain:
            hint = settings_body.row()
            hint.enabled = False
            hint.label(
                text="Select one bone/object per chain; params apply to all chains",
                icon="INFO",
            )
        if props.anim_sine_bone_mode == "SELECTION":
            hint = settings_body.row()
            hint.enabled = False
            if context.mode == "POSE":
                hint.label(text="Select pose bones for the chain", icon="INFO")
            elif context.mode == "OBJECT":
                hint.label(text="Select objects for the chain", icon="INFO")

    row = body.row(align=True)
    apply_row = row.row(align=True)
    apply_row.enabled = bool(enabled_axes)
    apply_row.operator(
        "wm.mono_fx_anim_apply_sine_chain",
        text="Apply Drivers",
        icon="FORCE_CURVE",
    )
    row.operator(
        "wm.mono_fx_anim_clear_sine_chain",
        text="Clear",
        icon="X",
    )
    row = body.row(align=True)
    row.operator(
        "wm.mono_fx_anim_bake_sine_chain",
        text="Bake Motion",
        icon="REC",
    )
    row.prop(props, "anim_sine_bake_clear_drivers", text="Clear Drivers")

    preview_hint = body.row()
    preview_hint.enabled = False
    preview_hint.label(
        text="Drivers update live while scrubbing the timeline",
        icon="PLAY",
    )

    list_body, list_open = ui_style.collapsible_section(
        body,
        "monofx_anim_chain_targets",
        chain_title,
        icon="OUTLINER",
        default_closed=False,
        prefs=prefs,
    )
    if list_open and list_body is not None:
        if chain_err:
            hint = list_body.row()
            hint.enabled = False
            hint.label(text=chain_err, icon="INFO")
        elif not rows:
            hint = list_body.row()
            hint.enabled = False
            hint.label(text="No chain resolved", icon="INFO")
        else:
            col = list_body.column(align=True)
            col.enabled = False
            for label, has_driver in rows:
                col.label(
                    text=label,
                    icon="DRIVER" if has_driver else "DOT",
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
    elif section == "CHAIN":
        _draw_anim_chain_section(body, context, prefs=prefs)
