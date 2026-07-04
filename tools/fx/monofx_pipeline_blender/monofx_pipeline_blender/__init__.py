"""
MonoFX Blender add-on: Model, Rig, and Anim sidebar panels with workflow tabs.

Install from repo ``releases/*.zip`` (root folder ``monofx_pipeline_blender/`` inside the ZIP).
UI language: English only.

Smoke test (manual):
  1. Create Hierarchy -> collection Geo_<Asset> / Geo / *_Grp
  2. Lowercase -> Add Geo Prefix -> Auto-Parent (Belt_Access -> Accessory_Grp)
  3. Set on Floor, Assign Materials, Publish USD
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Context, Menu, Operator, Panel

from . import config
from .asset_hierarchy import (
    AssetHierarchy,
    asset_collection_name_for,
    find_collections_for_keyword_export,
    find_collections_for_selected_export,
    get_asset_hierarchy_from_collection,
    iter_hierarchy_objects,
    resolve_asset_for_publish,
    resolve_asset_hierarchy_from_object,
    objects_in_collection_for_export,
)
from .logic import iter_subobjects_recursive
from .preset import (
    MONOFX_UL_preset_nodes,
    MonoFXPresetNodeItem,
    apply_preset_to_scene_nodes,
    init_scene_preset_if_empty,
    default_preset_json_path,
    load_default_character_preset,
    load_preset_from_json,
    preset_from_scene_nodes,
    reload_default_character_preset,
    save_preset_to_json,
)
from .preparing import (
    add_geo_prefix_to_selected,
    advanced_align_objects,
    advanced_align_tree,
    apply_transforms_to_objects,
    collect_apply_transform_targets,
    create_hierarchy_from_scene_props,
    collect_selected_into_named_collections,
    group_selected_objects_at_origin,
    lowercase_selected_names,
    collect_geo_meshes_in_hierarchy,
    run_auto_parent,
    set_objects_center_to_origin,
    set_objects_on_floor,
    set_tree_center_to_origin,
    set_tree_on_floor,
)
from .materials import assign_materials_from_grp_tree, clear_materials_on_objects
from .material_bake import (
    bake_materials_for_usd,
    resolve_bake_output_dir,
    resolve_shader_name,
    resolve_texture_stem,
)
from .material_bake_session import MaterialBakeSession, tag_redraw_ui
from .material_bake_targets import (
    MATERIAL_BAKE_TARGET_OPERATOR_CLASSES,
    MATERIAL_BAKE_TARGET_PROPERTY_GROUP_CLASSES,
    MATERIAL_BAKE_TARGET_UI_LIST_CLASSES,
    MaterialBakeTargetItem,
    apply_bake_restore_records,
    enabled_bake_targets,
    invalidate_material_bake_targets_signature,
    material_bake_run_plan,
    refresh_material_bake_targets,
    restorable_bake_target_count,
)
from . import material_bake_ui
from .mesh_cleanup import MeshCleanupOptions, collect_meshes_for_cleanup, run_mesh_cleanup
from .transform import usd_export
from . import ui_style
from . import publish_paths
from . import preferences
from . import rig_linking
from . import rig_ui
from . import anim_ui
from . import anim_ops
from . import anim_usd_cache_ui
from . import anim_usd_cache_ops
from . import anim_usd_cache_asset_list
from . import geo_usd_publish_list
from . import anim_camera
from . import scene_version
from . import keymaps
from . import addon_updater


bl_info = {
    "name": "MonoFX Pipeline Blender",
    "author": "MonoFXSuite",
    "version": (0, 9, 86),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > MonoFX",
    "description": (
        "Pipeline tools for character assets: Geo hierarchy, naming, auto-parent, "
        "materials, transforms; USD publish; rig linking from pipeline library."
    ),
    "category": "Object",
}

def _scene_blend_path() -> Optional[Path]:
    p = str(getattr(bpy.data, "filepath", "") or "").strip()
    if not p:
        return None
    try:
        return Path(p)
    except Exception:
        return None


_modelling_task_folder_from_scene = publish_paths.modelling_task_folder_from_scene
_resolve_publish_root_from_scene = publish_paths.resolve_publish_root_from_scene
_resolve_uv_publish_root_from_scene = _resolve_publish_root_from_scene


def _publish_root_for_props(props) -> tuple[Optional[Path], Optional[Path]]:
    scene_path = _scene_blend_path()
    if scene_path is None:
        return None, None
    return scene_path, _resolve_publish_root_from_scene(scene_path)


def _version_folder(props) -> str:
    return publish_paths.version_folder_from_number(props.publish_version)


def _build_publish_usd_path(props, publish_root: Path, scene_path: Path) -> str:
    vname = _version_folder(props)
    base = _default_usd_basename_from_scene_uv(scene_path)
    return str(publish_root / vname / f"{base}.usd")


def _auto_publish_version_number(publish_root: Path) -> int:
    return publish_paths.auto_next_version_number(publish_root)


def _describe_publish_target(props) -> tuple[bool, str, str, str]:
    """Returns ok, summary_line (version/task), relative_usd_path, error."""
    scene_path, publish_root = _publish_root_for_props(props)
    if scene_path is None:
        return False, "", "", "Save the .blend file first."
    if publish_root is None:
        return (
            False,
            "",
            "",
            "Save .blend under 01_assets/.../01_modelling/<task>/...",
        )
    task_folder = _modelling_task_folder_from_scene(scene_path) or "?"
    vname = _version_folder(props)
    usd_path = Path(_build_publish_usd_path(props, publish_root, scene_path))
    preset_tag = "auto" if props.output_preset == "uv" else "custom"
    summary = f"Will publish {vname} · {task_folder} · {preset_tag}"
    rel = publish_paths.relative_publish_display(scene_path, usd_path)
    return True, summary, rel, ""


_default_usd_basename_from_scene_uv = publish_paths.default_usd_basename_from_scene
_asset_name_from_scene = publish_paths.asset_name_from_scene


def _selected_objects(context: Context) -> List[bpy.types.Object]:
    return list(getattr(context, "selected_objects", []) or [])


def _report_error(op: Operator, message: str) -> None:
    op.report({"ERROR"}, message)


def _ensure_export_filepath(output_filepath: str) -> Path:
    p = Path(output_filepath)
    if p.suffix.lower() not in (".usd", ".usda", ".usdc", ".usdz"):
        p = p.with_suffix(".usd")
    return p


def _pipeline_props(context: Context):
    return context.scene.monofx_pipeline_blender_props


def _compute_auto_publish_usd_path(props) -> tuple[bool, str, str]:
    """Path for auto preset: next version number from publish folder."""
    scene_path, publish_root = _publish_root_for_props(props)
    if scene_path is None:
        return False, "", "Scene is not saved. Save the .blend file first so the publish path can be resolved."
    if publish_root is None:
        return (
            False,
            "",
            "Could not resolve publish path. Save .blend under 01_assets/.../01_modelling/<task>/...",
        )
    auto_num = _auto_publish_version_number(publish_root)
    vname = publish_paths.version_folder_from_number(auto_num)
    base = _default_usd_basename_from_scene_uv(scene_path)
    return True, str(publish_root / vname / f"{base}.usd"), ""


def _compute_uv_export_usd_path(props) -> tuple[bool, str, str]:
    """USD path for Asset (Auto Path): always from the Version field in the UI."""
    scene_path, publish_root = _publish_root_for_props(props)
    if scene_path is None:
        return False, "", "Scene is not saved. Save the .blend file first so the publish path can be resolved."
    if publish_root is None:
        return (
            False,
            "",
            "Could not resolve publish path. Save .blend under 01_assets/.../01_modelling/<task>/...",
        )
    path = _build_publish_usd_path(props, publish_root, scene_path)
    return True, str(_ensure_export_filepath(path)), ""


def _resolve_publish_folder_path(props) -> tuple[bool, Path, str]:
    """Folder to open in Explorer: version dir (uv) or output parent (custom). Does not create folders."""
    if props.output_preset == "custom":
        raw = str(props.output_filepath or "").strip()
        if not raw:
            return False, Path(), "Output path empty."
        return True, Path(_ensure_export_filepath(raw)).parent, ""
    ok, usd_path, err = _compute_uv_export_usd_path(props)
    if not ok:
        return False, Path(), err
    return True, Path(usd_path).parent, ""


_SYNCING_OUTPUT_FILEPATH: bool = False
_SYNCING_PUBLISH_VERSION: bool = False


def _normalize_publish_path(path: str) -> str:
    p = str(path or "").strip()
    if not p:
        return ""
    return os.path.normcase(os.path.normpath(p))


def _filepath_equals(a: str, b: str) -> bool:
    return _normalize_publish_path(a) == _normalize_publish_path(b)


def _apply_publish_filepath_from_version(props) -> None:
    global _SYNCING_OUTPUT_FILEPATH
    scene_path, publish_root = _publish_root_for_props(props)
    if scene_path is None or publish_root is None:
        return
    path = _build_publish_usd_path(props, publish_root, scene_path)
    _SYNCING_OUTPUT_FILEPATH = True
    try:
        props.output_filepath = path
    finally:
        _SYNCING_OUTPUT_FILEPATH = False


def sync_asset_name_from_scene(props) -> None:
    """Fill Asset Name from saved .blend path / filename."""
    scene_path = _scene_blend_path()
    if scene_path is None:
        return
    props.asset_name = _asset_name_from_scene(scene_path)


def sync_auto_publish_output(props) -> None:
    """Auto preset: next version number + matching USD path."""
    global _SYNCING_OUTPUT_FILEPATH, _SYNCING_PUBLISH_VERSION
    if props.output_preset != "uv":
        return
    scene_path, publish_root = _publish_root_for_props(props)
    if scene_path is None or publish_root is None:
        return
    auto_num = _auto_publish_version_number(publish_root)
    _SYNCING_PUBLISH_VERSION = True
    try:
        props.publish_version = auto_num
    finally:
        _SYNCING_PUBLISH_VERSION = False
    ok, path, _ = _compute_auto_publish_usd_path(props)
    _SYNCING_OUTPUT_FILEPATH = True
    try:
        if ok and path:
            props.output_filepath = path
        elif not ok:
            props.output_filepath = ""
    finally:
        _SYNCING_OUTPUT_FILEPATH = False


def _mono_fx_on_publish_version(self, _context: Context) -> None:
    if _SYNCING_PUBLISH_VERSION:
        return
    scene_path, publish_root = _publish_root_for_props(self)
    if scene_path is None or publish_root is None:
        return
    if self.output_preset == "uv":
        self.output_preset = "custom"
    _apply_publish_filepath_from_version(self)


def _mono_fx_on_output_filepath(self, _context: Context) -> None:
    if _SYNCING_OUTPUT_FILEPATH:
        return
    if self.output_preset != "uv":
        return
    ok, auto_path, _ = _compute_uv_export_usd_path(self)
    if not ok:
        return
    if not _filepath_equals(self.output_filepath, auto_path):
        self.output_preset = "custom"


def _mono_fx_on_rig_scene_index(self, context: Context) -> None:
    from . import rig_focus
    from . import rig_linking

    if rig_focus.is_suppressed():
        return
    if not rig_focus.should_apply(self):
        return
    item = rig_linking._selected_scene_item(self)
    if item is None or not item.ref_id:
        return
    rig_focus.apply_rig_focus(context, item.ref_id, self)


def _mono_fx_on_output_preset(self, _context: Context) -> None:
    if self.output_preset == "uv":
        sync_auto_publish_output(self)


def _mono_fx_on_publish_export_options_changed(self, context: Context) -> None:
    geo_usd_publish_list.invalidate_publish_export_list_signature(self)
    if context is not None and not self.geo_usd_publish_list_locked:
        geo_usd_publish_list.refresh_publish_export_list(context, self, force=True)


def _mono_fx_on_export_collections_by_keyword(self, context: Context) -> None:
    if self.export_collections_by_keyword:
        self.export_selected_collection = False
    _mono_fx_on_publish_export_options_changed(self, context)


def _mono_fx_on_export_selected_collection(self, context: Context) -> None:
    if self.export_selected_collection:
        self.export_collections_by_keyword = False
    _mono_fx_on_publish_export_options_changed(self, context)


_USD_AXIS_ITEMS = [
    ("X", "X", "Positive X axis"),
    ("Y", "Y", "Positive Y axis"),
    ("Z", "Z", "Positive Z axis"),
    ("NEGATIVE_X", "-X", "Negative X axis"),
    ("NEGATIVE_Y", "-Y", "Negative Y axis"),
    ("NEGATIVE_Z", "-Z", "Negative Z axis"),
]

_USD_SCENE_UNITS_ITEMS = [
    ("METERS", "Meters", "Stage meters per unit = 1.0"),
    ("KILOMETERS", "Kilometers", "Stage meters per unit = 1000.0"),
    ("CENTIMETERS", "Centimeters", "Stage meters per unit = 0.01"),
    ("MILLIMETERS", "Millimeters", "Stage meters per unit = 0.001"),
    ("INCHES", "Inches", "Stage meters per unit = 0.0254"),
    ("FEET", "Feet", "Stage meters per unit = 0.3048"),
    ("YARDS", "Yards", "Stage meters per unit = 0.9144"),
]

_APPLY_TRANSFORM_SCOPE_ITEMS = [
    (
        "PRODUCTION_TREE",
        "Production Tree",
        "Apply to mesh and armature objects under the Geo asset root",
    ),
    (
        "SELECTION",
        "Selection Hierarchy",
        "Apply to each selected object and its descendants",
    ),
]


_BBOX_ALIGN_AXIS_ITEMS = [
    ("MIN", "Min", "Align bbox minimum on this axis"),
    ("CENTER", "Center", "Align bbox center on this axis"),
    ("MAX", "Max", "Align bbox maximum on this axis"),
]

_MATERIAL_BAKE_SCOPE_ITEMS = [
    (
        "UNIQUE_MATERIAL",
        "Per Material",
        "One texture set per material name; first mesh with that material is baked",
    ),
    (
        "PER_MESH",
        "Per Mesh",
        "One texture set per mesh; uses the mesh first non-empty material slot",
    ),
]

_MATERIAL_BAKE_RESOLUTION_ITEMS = [
    ("512", "512", "512 x 512"),
    ("1024", "1024", "1024 x 1024"),
    ("2048", "2048", "2048 x 2048"),
    ("4096", "4096", "4096 x 4096"),
]

_MATERIAL_BAKE_OUTPUT_MODE_ITEMS = [
    ("BLEND_TEXTURES", "Blend Textures", "Save next to the .blend file under textures/"),
    ("PUBLISH_TEXTURES", "Publish Textures", "Save under modelling task publish/textures/"),
    ("CUSTOM", "Custom", "Save to a custom folder"),
]

_MATERIAL_BAKE_IMAGE_FORMAT_ITEMS = [
    ("PNG", "PNG", "8-bit PNG textures"),
    ("OPEN_EXR", "OpenEXR", "32-bit float OpenEXR textures"),
]

_MATERIAL_BAKE_TEXTURE_STEM_ITEMS = [
    ("MATERIAL_MESH", "Material + Mesh", "Material stem and mesh name, e.g. Body_geo_head"),
    ("MATERIAL_STEM", "Material", "Material stem after prefix strip, e.g. Body"),
    ("MATERIAL_FULL", "Material (full)", "Full material datablock name"),
    ("MESH", "Mesh", "Mesh object name only"),
    ("CUSTOM", "Custom", "Custom template for texture file stem"),
]

_MATERIAL_BAKE_SHADER_NAME_ITEMS = [
    ("SOURCE_TEXTURE", "Source + Texture", "Source material and texture stem"),
    ("MATERIAL_MESH", "Material + Mesh", "Material stem and mesh name, e.g. Body_geo_head"),
    ("MESH_MATERIAL", "Mesh + Material", "Mesh name and material stem, e.g. geo_head_Body"),
    (
        "TEXTURE_STEM",
        "Match Texture",
        "Same as texture file stem (differs when Texture Files uses mesh)",
    ),
    (
        "MATERIAL_STEM",
        "Material Stem",
        "Material datablock name (legacy label; same as Keep Source without prefix strip)",
    ),
    (
        "KEEP_SOURCE",
        "Keep Source",
        "Original material datablock name (same as stem if no prefix)",
    ),
    ("CUSTOM", "Custom", "Custom template for baked shader name"),
]


def _on_material_bake_list_invalidate(props, _context: Context) -> None:
    invalidate_material_bake_targets_signature(props)


def _mono_fx_on_advanced_align_to_origin(self, _context: Context) -> None:
    if self.advanced_align_to_origin:
        self.advanced_align_to_cursor = False


def _mono_fx_on_advanced_align_to_cursor(self, _context: Context) -> None:
    if self.advanced_align_to_cursor:
        self.advanced_align_to_origin = False


class MonoFXProperties(bpy.types.PropertyGroup):
    asset_name: StringProperty(
        name="Asset Name",
        description="Auto-filled from .blend filename (or asset folder under 01_assets); used for Geo_<Asset>",
        default="Asset",
    )
    material_prefix: StringProperty(
        name="Material Prefix",
        description="Prefix for materials created by Assign from Groups (Geo Prep)",
        default=config.DEFAULT_MATERIAL_PREFIX,
    )
    mesh_geo_prefix: StringProperty(
        name="Mesh Geo Prefix",
        default=config.MESH_GEO_PREFIX,
    )
    preset_nodes: CollectionProperty(type=MonoFXPresetNodeItem)
    preset_index: IntProperty(name="Preset Index", default=0)
    preset_json_path: StringProperty(
        name="Preset JSON",
        default="",
        subtype="FILE_PATH",
    )
    purge_orphan_materials: BoolProperty(
        name="Purge Orphan Materials",
        default=False,
    )
    material_bake_scope: EnumProperty(
        name="Bake Grouping",
        description="One texture set per material, or per mesh object",
        items=_MATERIAL_BAKE_SCOPE_ITEMS,
        default=config.DEFAULT_MATERIAL_BAKE_SCOPE,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_pass_base_color: BoolProperty(
        name="Base Color",
        description="Bake diffuse color pass",
        default=True,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_pass_roughness: BoolProperty(
        name="Roughness",
        description="Bake roughness pass",
        default=True,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_pass_normal: BoolProperty(
        name="Normal",
        description="Bake tangent-space normal pass",
        default=True,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_pass_ao: BoolProperty(
        name="Ambient Occlusion",
        description="Bake ambient occlusion pass",
        default=False,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_pass_opacity: BoolProperty(
        name="Opacity",
        description=(
            "Also diffuse-bake Opacity.png (margin 0) and wire its Alpha to Principled "
            "Alpha; requires Base Color pass"
        ),
        default=False,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_resolution: EnumProperty(
        name="Resolution",
        items=_MATERIAL_BAKE_RESOLUTION_ITEMS,
        default=config.DEFAULT_MATERIAL_BAKE_RESOLUTION,
    )
    material_bake_output_mode: EnumProperty(
        name="Output Folder",
        items=_MATERIAL_BAKE_OUTPUT_MODE_ITEMS,
        default=config.DEFAULT_MATERIAL_BAKE_OUTPUT_MODE,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_output_dir: StringProperty(
        name="Custom Output",
        description="Folder for baked textures when Output Folder is Custom",
        default="",
        subtype="DIR_PATH",
        update=_on_material_bake_list_invalidate,
    )
    material_bake_image_format: EnumProperty(
        name="Format",
        items=_MATERIAL_BAKE_IMAGE_FORMAT_ITEMS,
        default=config.DEFAULT_MATERIAL_BAKE_IMAGE_FORMAT,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_uv_map: StringProperty(
        name="UV Map",
        description="UV layer to bake (empty = active UV)",
        default="",
    )
    material_bake_margin: IntProperty(
        name="Margin",
        description="Bake margin in pixels",
        default=config.DEFAULT_MATERIAL_BAKE_MARGIN,
        min=0,
        max=64,
    )
    material_bake_pack_images: BoolProperty(
        name="Pack into .blend",
        description="Pack baked images into the .blend after saving (slower; blocks UI longer)",
        default=config.DEFAULT_MATERIAL_BAKE_PACK_IMAGES,
    )
    material_bake_simplify_shader: BoolProperty(
        name="Simplify for USD Export",
        description="Replace the material node tree with Principled BSDF and baked textures",
        default=config.DEFAULT_MATERIAL_BAKE_SIMPLIFY_SHADER,
    )
    material_bake_texture_stem_mode: EnumProperty(
        name="Texture Names",
        description="How baked texture file stems are built (before _BaseColor, _Roughness, …)",
        items=_MATERIAL_BAKE_TEXTURE_STEM_ITEMS,
        default=config.DEFAULT_MATERIAL_BAKE_TEXTURE_STEM_MODE,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_texture_stem_template: StringProperty(
        name="Texture Template",
        description="Tokens: {material}, {material_stem}, {mesh}, {texture_stem}",
        default=config.DEFAULT_MATERIAL_BAKE_TEXTURE_STEM_TEMPLATE,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_shader_name_mode: EnumProperty(
        name="Shader Names",
        description="Material datablock name assigned on the mesh after bake",
        items=_MATERIAL_BAKE_SHADER_NAME_ITEMS,
        default=config.DEFAULT_MATERIAL_BAKE_SHADER_NAME_MODE,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_shader_name_template: StringProperty(
        name="Shader Template",
        description="Tokens: {material}, {material_stem}, {mesh}, {texture_stem}",
        default=config.DEFAULT_MATERIAL_BAKE_SHADER_NAME_TEMPLATE,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_use_geo_tree: BoolProperty(
        name="Geo Asset Tree",
        description="List all meshes under the Geo asset tree",
        default=True,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_selected_only: BoolProperty(
        name="Selected Meshes",
        description="List only mesh objects in the current selection",
        default=False,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_keyword_filter: BoolProperty(
        name="Keyword Filter",
        description="List meshes in the scene whose names contain the keyword",
        default=False,
        update=_on_material_bake_list_invalidate,
    )
    material_bake_mesh_keyword: StringProperty(
        name="Keyword",
        description="Substring matched against mesh names in the scene (case-insensitive)",
        default="",
        update=_on_material_bake_list_invalidate,
    )
    material_bake_list_locked: BoolProperty(
        name="Lock List",
        description="Stop auto-updating the bake target list from scene changes",
        default=False,
    )
    material_bake_list_error: StringProperty(
        name="Bake List Error",
        default="",
    )
    material_bake_targets_signature: StringProperty(
        name="Bake Targets Signature",
        default="",
    )
    material_bake_report: StringProperty(default="")
    material_bake_running: BoolProperty(
        name="Bake Running",
        description="True while material bake modal is active",
        default=False,
    )
    material_bake_targets: CollectionProperty(type=MaterialBakeTargetItem)
    material_bake_target_index: IntProperty(name="Bake Target Index", default=0)
    auto_parent_report: StringProperty(default="")
    clean_apply_modifiers: BoolProperty(
        name="Apply Modifiers",
        description="Apply all mesh modifiers (except Armature) before other cleanup",
        default=False,
    )
    clean_apply_shape_keys: BoolProperty(
        name="Apply Shape Keys",
        description="Apply mix and remove all shape keys",
        default=True,
    )
    clean_vertex_groups: BoolProperty(
        name="Clean Vertex Groups",
        description="Remove all vertex groups on target meshes",
        default=True,
    )
    clean_color_attributes: BoolProperty(
        name="Clean Color Attributes",
        description="Remove mesh color attributes (vertex colors, etc.)",
        default=True,
    )
    clean_custom_attributes: BoolProperty(
        name="Clean Attributes",
        description="Remove other custom mesh attributes from DCC import",
        default=True,
    )
    clean_uv_maps: BoolProperty(
        name="Clean UV Maps",
        description="Keep active UV layer only; remove extra UV maps",
        default=True,
    )
    clean_mesh_report: StringProperty(default="")
    publish_status_report: StringProperty(
        name="Publish Status",
        description="Last successful publish message shown in the UI",
        default="",
    )
    geo_usd_publish_objects: CollectionProperty(type=geo_usd_publish_list.GeoUsdPublishObjectItem)
    geo_usd_publish_object_index: IntProperty(
        name="Export Object Index",
        default=0,
        min=0,
    )
    geo_usd_publish_objects_signature: StringProperty(
        name="Export Objects Signature",
        default="",
    )
    geo_usd_publish_list_error: StringProperty(
        name="Export List Error",
        default="",
    )
    geo_usd_publish_list_locked: BoolProperty(
        name="Lock List",
        description="Stop auto-updating the export collection list from scene changes",
        default=False,
    )
    save_version_report: StringProperty(
        name="Save Version Status",
        description="Last successful save-version message shown in the UI",
        default="",
    )
    save_version_description: StringProperty(
        name="Description",
        description="Optional note appended to the version filename (e.g. layoutPass)",
        default="",
    )
    save_version_preview_num: IntProperty(
        name="Next Version",
        description="Cached next save-version number for the UI button label",
        default=0,
        min=0,
        max=999,
    )

    output_filepath: StringProperty(
        name="Publish File",
        description="Output .usd path; editing away from auto path switches preset to Custom",
        default="",
        subtype="FILE_PATH",
        update=_mono_fx_on_output_filepath,
    )
    output_preset: EnumProperty(
        name="Output Preset",
        items=[
            ("uv", "Asset (Auto Path)", "Resolve publish folder from the saved .blend path"),
            ("custom", "Custom", "Use Publish File path as-is"),
        ],
        default="uv",
        update=_mono_fx_on_output_preset,
    )
    publish_version: IntProperty(
        name="Version",
        description="Publish version number (folder v001–v999)",
        default=1,
        min=1,
        max=999,
        update=_mono_fx_on_publish_version,
    )
    select_hierarchy: BoolProperty(
        name="Full Asset Tree",
        description=(
            "Fill the export list from Geo_<Asset> and include the full object tree. "
            "When off, only the current selection under the asset is used"
        ),
        default=True,
        update=_mono_fx_on_publish_export_options_changed,
    )
    export_collections_by_keyword: BoolProperty(
        name="Keyword Filter",
        description="Fill the export list from collections whose names match the keyword",
        default=False,
        update=_mono_fx_on_export_collections_by_keyword,
    )
    export_selected_collection: BoolProperty(
        name="Selected Collections",
        description=(
            "Fill the export list from collection(s) selected in the Outliner "
            "(or the active collection when none are selected)"
        ),
        default=False,
        update=_mono_fx_on_export_selected_collection,
    )
    export_collection_keyword: StringProperty(
        name="Collection Keyword",
        description="Match collection names (case-insensitive). Leave empty to export every collection that has objects",
        default="publish",
        update=_mono_fx_on_publish_export_options_changed,
    )
    allow_apply_on_armature: BoolProperty(
        name="Allow Apply on Armature",
        description="Advanced Apply Transform may include armature objects",
        default=False,
    )
    apply_transform_scope: EnumProperty(
        name="Apply Objects",
        description="Which objects receive applied transforms",
        items=_APPLY_TRANSFORM_SCOPE_ITEMS,
        default="PRODUCTION_TREE",
    )
    apply_transform_location: BoolProperty(
        name="Location",
        description="Apply object location",
        default=True,
    )
    apply_transform_rotation: BoolProperty(
        name="Rotation",
        description="Apply object rotation",
        default=True,
    )
    apply_transform_scale: BoolProperty(
        name="Scale",
        description="Apply object scale",
        default=True,
    )
    advanced_align_enable_x: BoolProperty(
        name="Align X",
        description="Align bbox on the X axis",
        default=True,
    )
    advanced_align_enable_y: BoolProperty(
        name="Align Y",
        description="Align bbox on the Y axis",
        default=True,
    )
    advanced_align_enable_z: BoolProperty(
        name="Align Z",
        description="Align bbox on the Z axis",
        default=True,
    )
    advanced_align_axis_x: EnumProperty(
        name="X",
        description="BBox point on X used for alignment",
        items=_BBOX_ALIGN_AXIS_ITEMS,
        default="CENTER",
    )
    advanced_align_axis_y: EnumProperty(
        name="Y",
        description="BBox point on Y used for alignment",
        items=_BBOX_ALIGN_AXIS_ITEMS,
        default="CENTER",
    )
    advanced_align_axis_z: EnumProperty(
        name="Z",
        description="BBox point on Z used for alignment",
        items=_BBOX_ALIGN_AXIS_ITEMS,
        default="MIN",
    )
    advanced_align_to_origin: BoolProperty(
        name="Align to Origin",
        description="Align bbox to world origin (0, 0, 0)",
        default=True,
        update=_mono_fx_on_advanced_align_to_origin,
    )
    advanced_align_to_cursor: BoolProperty(
        name="Align to Cursor",
        description="Align bbox to the 3D cursor location",
        default=False,
        update=_mono_fx_on_advanced_align_to_cursor,
    )
    advanced_align_combined_bbox: BoolProperty(
        name="Combined Bbox",
        description=(
            "Use one bounding box for all meshes and move them together. "
            "Disable to align each mesh using its own bbox"
        ),
        default=True,
    )
    convert_orientation: BoolProperty(
        name="Convert Orientation",
        description="Convert orientation axis during USD export (Blender wm.usd_export)",
        default=config.DEFAULT_CONVERT_ORIENTATION,
    )
    export_forward_axis: EnumProperty(
        name="Forward Axis",
        items=_USD_AXIS_ITEMS,
        default=config.DEFAULT_EXPORT_FORWARD,
    )
    export_up_axis: EnumProperty(
        name="Up Axis",
        items=_USD_AXIS_ITEMS,
        default=config.DEFAULT_EXPORT_UP,
    )
    convert_scene_units: EnumProperty(
        name="Units",
        items=_USD_SCENE_UNITS_ITEMS,
        default=config.DEFAULT_CONVERT_SCENE_UNITS,
    )
    usd_root_prim_path: StringProperty(
        name="Root Prim Path",
        description="USD root prim path for wm.usd_export (e.g. / or /Asset)",
        default=config.DEFAULT_USD_ROOT_PRIM_PATH,
    )
    export_uvmaps: BoolProperty(default=True)
    export_normals: BoolProperty(default=True)
    export_materials: BoolProperty(default=True)
    generate_preview_surface: BoolProperty(
        name="USD Preview Surface Network",
        description=(
            "Generate an approximate USD Preview Surface shader from Principled BSDF "
            "(Blender wm.usd_export generate_preview_surface)"
        ),
        default=config.DEFAULT_GENERATE_PREVIEW_SURFACE,
    )
    generate_materialx_network: BoolProperty(
        name="MaterialX Network",
        description=(
            "Generate a MaterialX network representation of materials "
            "(Blender wm.usd_export generate_materialx_network)"
        ),
        default=config.DEFAULT_GENERATE_MATERIALX_NETWORK,
    )
    export_lights: BoolProperty(default=False)
    export_cameras: BoolProperty(default=False)

    rig_project_name: StringProperty(name="Project", default="")
    pipeline_project_root: StringProperty(
        name="Project Root",
        description="Pipeline project folder (01_assets + 02_shots); saved in this .blend when the file is outside the project tree",
        default="",
        subtype="DIR_PATH",
    )
    rig_asset_group_list: StringProperty(name="Asset Groups", default="")
    rig_asset_group: StringProperty(
        name="Asset Group",
        description="Asset group under 01_assets (e.g. _characters)",
        default="_none",
    )
    rig_mode: EnumProperty(
        name="Rig Source",
        items=[
            ("PUBLISH", "Published", "Published rig files under 02_rigging/.../publish"),
            ("WORK", "Work", "Work-in-progress rig .blend files"),
        ],
        default="PUBLISH",
    )
    rig_search: StringProperty(name="Search", description="Filter library by name", default="")
    rig_library_index: IntProperty(name="Library Index", default=0, min=0)
    rig_scene_index: IntProperty(
        name="Scene Index",
        default=0,
        min=0,
        update=_mono_fx_on_rig_scene_index,
    )
    rig_library_cache: CollectionProperty(type=rig_linking.MonoFXRigLibraryItem)
    rig_scene_cache: CollectionProperty(type=rig_linking.MonoFXRigSceneItem)
    rig_auto_focus: BoolProperty(
        name="Auto Focus Rig",
        description="Frame the rig in the 3D View when linking or selecting a scene link",
        default=True,
    )
    rig_bone_pick_1: BoolProperty(
        name="Bone 1",
        description="Select this pose bone after link or scene selection",
        default=False,
    )
    rig_bone_pick_1_name: StringProperty(
        name="Bone 1 Name",
        description="Exact pose bone name for slot 1",
        default="",
    )
    rig_bone_pick_2: BoolProperty(
        name="Bone 2",
        description="Select this pose bone after link or scene selection",
        default=False,
    )
    rig_bone_pick_2_name: StringProperty(
        name="Bone 2 Name",
        description="Exact pose bone name for slot 2",
        default="",
    )
    rig_bone_pick_contains: BoolProperty(
        name="Contains",
        description="Select all pose bones whose names contain the text below",
        default=False,
    )
    rig_bone_pick_contains_text: StringProperty(
        name="Name Contains",
        description="Substring matched against all pose bone names",
        default="",
    )
    rig_manual_link_path: StringProperty(
        name="Rig File",
        description="Path to a rig .blend for manual link into the scene",
        default="",
        subtype="FILE_PATH",
    )
    rig_manual_namespace: StringProperty(
        name="Namespace",
        description="Optional asset folder name for prefix/namespace; empty = auto from project path or filename",
        default="",
    )

    anim_clean_single_key: BoolProperty(
        name="Clean Single-Key Curves",
        description="Remove fcurves with only one keyframe",
        default=True,
    )
    anim_clean_static_key: BoolProperty(
        name="Clean Static Curves",
        description="Remove fcurves where all key values are identical",
        default=True,
    )
    anim_camera_active_rig: EnumProperty(
        name="Camera Rig",
        description="Active camera rig for Camera Tools controls",
        items=anim_camera.anim_camera_rig_enum_items,
        default=0,
        update=anim_camera.on_active_rig_changed,
    )
    anim_camera_focal_length_stored: FloatProperty(
        name="Focal Length Stored",
        default=50.0,
        min=1.0,
        max=5000.0,
        options={"HIDDEN"},
    )
    anim_camera_focal_length: FloatProperty(
        name="Focal Length",
        description="Scene camera focal length in mm; default for Camera from View when no scene camera",
        min=1.0,
        max=5000.0,
        soft_min=14.0,
        soft_max=200.0,
        precision=2,
        default=50.0,
        get=anim_camera.anim_camera_focal_length_get,
        set=anim_camera.anim_camera_focal_length_set,
    )
    anim_camera_vertigo: BoolProperty(
        name="Vertigo",
        description=(
            "When focal length changes, dolly the rig so focus-distance framing "
            "stays consistent (dolly zoom / vertigo effect)"
        ),
        default=False,
    )
    anim_camera_vertigo_target: EnumProperty(
        name="Vertigo Dolly",
        description="Which rig control receives the vertigo dolly (aim stays on root)",
        items=[
            (
                "BODY",
                "Mount",
                "Vertigo dolly on mount toward aim (straight line to look target)",
            ),
            (
                "MOTION",
                "Head",
                "Vertigo dolly on head local Z (along view axis; finer layer)",
            ),
        ],
        default="MOTION",
    )
    anim_camera_body_track_stored: FloatProperty(
        name="Track Truck Stored",
        default=0.0,
        options={"HIDDEN"},
    )
    anim_camera_body_track: FloatProperty(
        name="Track Truck",
        description=(
            "On set: crab left/right on floor dolly track. "
            "Rig: {cam}_mount · location X. Stage move — not Head Truck"
        ),
        default=0.0,
        soft_min=-100.0,
        soft_max=100.0,
        precision=3,
        get=anim_camera.anim_camera_body_track_get,
        set=anim_camera.anim_camera_body_track_set,
    )
    anim_camera_body_track_y_stored: FloatProperty(
        name="Track Dolly Stored",
        default=0.0,
        options={"HIDDEN"},
    )
    anim_camera_body_track_y: FloatProperty(
        name="Track Dolly",
        description=(
            "On set: dolly in/out on floor rails. "
            "Rig: {cam}_mount · location Y. Stage move — not Head Dolly"
        ),
        default=0.0,
        soft_min=-100.0,
        soft_max=100.0,
        precision=3,
        get=anim_camera.anim_camera_body_track_y_get,
        set=anim_camera.anim_camera_body_track_y_set,
    )
    anim_camera_body_height_stored: FloatProperty(
        name="Pedestal Stored",
        default=0.0,
        options={"HIDDEN"},
    )
    anim_camera_body_height: FloatProperty(
        name="Pedestal",
        description=(
            "On set: pedestal up/down — raise/lower column (vertical translate). "
            "Rig: {cam}_mount · location Z. With Track Aim, boom keeps look-at on {cam}_aim"
        ),
        default=0.0,
        soft_min=-100.0,
        soft_max=100.0,
        precision=3,
        get=anim_camera.anim_camera_body_height_get,
        set=anim_camera.anim_camera_body_height_set,
    )
    anim_camera_crane_angle_stored: FloatProperty(
        name="Crane Tilt Stored",
        default=0.0,
        options={"HIDDEN"},
    )
    anim_camera_crane_angle: FloatProperty(
        name="Crane Tilt",
        description=(
            "On set: tilt jib arm up/down (changes framing). "
            "Rig: {cam}_mount · rotation X — not Head Tilt or Orbit"
        ),
        default=0.0,
        subtype="ANGLE",
        get=anim_camera.anim_camera_crane_angle_get,
        set=anim_camera.anim_camera_crane_angle_set,
    )
    anim_camera_crane_length_stored: FloatProperty(
        name="Crane Boom Stored",
        default=0.0,
        options={"HIDDEN"},
    )
    anim_camera_crane_length: FloatProperty(
        name="Crane Boom",
        description=(
            "On set: extend/retract jib reach toward subject. "
            "Rig: {cam}_boom · location Z (Track Aim keeps look-at when enabled)"
        ),
        default=0.0,
        soft_min=-100.0,
        soft_max=100.0,
        precision=3,
        get=anim_camera.anim_camera_crane_length_get,
        set=anim_camera.anim_camera_crane_length_set,
    )
    anim_camera_motion_dolly_stored: FloatProperty(
        name="Dolly Stored",
        default=0.0,
        options={"HIDDEN"},
    )
    anim_camera_motion_dolly: FloatProperty(
        name="Dolly",
        description=(
            "On set: lens push in/out along view axis. "
            "Rig: {cam}_head · location Z — not Track Dolly on mount"
        ),
        default=0.0,
        soft_min=-100.0,
        soft_max=100.0,
        precision=3,
        get=anim_camera.anim_camera_motion_dolly_get,
        set=anim_camera.anim_camera_motion_dolly_set,
    )
    anim_camera_motion_truck_stored: FloatProperty(
        name="Truck Stored",
        default=0.0,
        options={"HIDDEN"},
    )
    anim_camera_motion_truck: FloatProperty(
        name="Truck",
        description=(
            "On set: slide left/right in frame (fluid head crab). "
            "Rig: {cam}_head · location X — not Track Truck on mount"
        ),
        default=0.0,
        soft_min=-100.0,
        soft_max=100.0,
        precision=3,
        get=anim_camera.anim_camera_motion_truck_get,
        set=anim_camera.anim_camera_motion_truck_set,
    )
    anim_camera_motion_roll_stored: FloatProperty(
        name="Head Roll Stored",
        default=0.0,
        options={"HIDDEN"},
    )
    anim_camera_motion_tilt_stored: FloatProperty(
        name="Head Tilt Stored",
        default=0.0,
        options={"HIDDEN"},
    )
    anim_camera_motion_pan_stored: FloatProperty(
        name="Head Pan Stored",
        default=0.0,
        options={"HIDDEN"},
    )
    anim_camera_motion_pan: FloatProperty(
        name="Pan",
        description=(
            "On set: pan fluid head left/right (yaw). "
            "Rig: {cam}_head · rotation Y — not Orbit on aim"
        ),
        default=0.0,
        soft_min=-3.14159,
        soft_max=3.14159,
        subtype="ANGLE",
        get=anim_camera.anim_camera_motion_pan_get,
        set=anim_camera.anim_camera_motion_pan_set,
    )
    anim_camera_motion_tilt: FloatProperty(
        name="Tilt",
        description=(
            "On set: pitch fluid head up/down. "
            "Rig: {cam}_head · rotation X — not Crane Tilt on mount"
        ),
        default=0.0,
        soft_min=-1.5708,
        soft_max=1.5708,
        subtype="ANGLE",
        get=anim_camera.anim_camera_motion_tilt_get,
        set=anim_camera.anim_camera_motion_tilt_set,
    )
    anim_camera_motion_roll: FloatProperty(
        name="Roll",
        description="On set: dutch angle. Rig: {cam}_head · rotation Z",
        default=0.0,
        soft_min=-3.14159,
        soft_max=3.14159,
        subtype="ANGLE",
        get=anim_camera.anim_camera_motion_roll_get,
        set=anim_camera.anim_camera_motion_roll_set,
    )
    anim_camera_orbit_stored: FloatProperty(
        name="Orbit Stored",
        default=0.0,
        options={"HIDDEN"},
    )
    anim_camera_orbit: FloatProperty(
        name="Orbit",
        description=(
            "On set: yaw rig around orbit pivot — not Head Pan. "
            "Rig: {cam}_orbit · rotation Z"
        ),
        default=0.0,
        soft_min=-3.14159,
        soft_max=3.14159,
        subtype="ANGLE",
        get=anim_camera.anim_camera_orbit_get,
        set=anim_camera.anim_camera_orbit_set,
    )
    anim_camera_orbit_follow_aim: BoolProperty(
        name="Enable Orbit",
        description=(
            "Create orbit pivot, orbit display, and Mount to Orbit; "
            "repairs missing orbit / viz parts when enabled"
        ),
        default=False,
        update=anim_camera.on_orbit_follow_aim_changed,
    )
    anim_camera_orbit_display_visible: BoolProperty(
        name="Show Orbit Display",
        description="Show or hide {cam}_orbit sphere, ring, and direction arrows in viewport",
        default=True,
        update=anim_camera.on_orbit_display_visible_changed,
    )
    anim_camera_orbit_arrow_size: FloatProperty(
        name="Arrow Size",
        description="Scale for orbit direction arrow markers ({cam}_orbit_viz_arrow_*)",
        default=0.5,
        min=0.01,
        soft_max=5.0,
        update=anim_camera.on_orbit_arrow_size_changed,
    )
    anim_camera_body_orbit_constraint: BoolProperty(
        name="Mount to Orbit",
        description=(
            "On set: mount rides orbit pivot. Rig: {cam}_mount · Child Of → {cam}_orbit. "
            "Sets inverse when enabled so mount does not jump"
        ),
        default=False,
        update=anim_camera.on_body_orbit_constraint_changed,
    )
    anim_camera_track_aim: BoolProperty(
        name="Track Aim",
        description=(
            "On set: boom auto-look-at during pedestal / track / boom moves. "
            "Rig: {cam}_boom · Track Aim → {cam}_aim. "
            "Sets inverse when enabled (aim snaps to boom look axis)"
        ),
        default=True,
        update=anim_camera.on_track_aim_changed,
    )
    anim_camera_aim_to_cursor: BoolProperty(
        name="Aim to Cursor",
        description=(
            "Live-sync look target. Rig: {cam}_aim · location "
            "(Shift+Right Click to move cursor). With Aim Lock, only depth along view axis"
        ),
        default=False,
        update=anim_camera.on_aim_to_cursor_changed,
    )
    anim_camera_aim_lock: BoolProperty(
        name="Aim Lock",
        description=(
            "When enabled, Aim to Cursor only adjusts focus distance along the camera "
            "view axis (depth). XY aim offset stays manual"
        ),
        default=False,
        update=anim_camera.on_aim_lock_changed,
    )
    anim_camera_aim_distance_stored: FloatProperty(
        name="Aim Distance Stored",
        default=10.0,
        options={"HIDDEN"},
    )
    anim_camera_aim_distance: FloatProperty(
        name="Aim Distance",
        description=(
            "Focus distance along camera view axis. Rig: {cam}_aim · depth from {cam}"
        ),
        default=10.0,
        min=0.1,
        soft_max=100.0,
        precision=3,
        get=anim_camera.anim_camera_aim_distance_get,
        set=anim_camera.anim_camera_aim_distance_set,
    )
    anim_camera_root_to_cursor: BoolProperty(
        name="Root to Cursor",
        description="Live-sync rig root. Rig: {cam}_root · world XY",
        default=False,
        update=anim_camera.on_root_to_cursor_changed,
    )
    anim_camera_root_to_cursor_z: BoolProperty(
        name="Enable Root Z",
        description="When enabled, Root to Cursor follows the 3D cursor Z axis",
        default=False,
    )

    anim_usd_output_filepath: StringProperty(
        name="Output File",
        description="Anim cache .usd output path",
        default="",
        subtype="FILE_PATH",
        update=anim_usd_cache_ui._on_anim_usd_output_filepath,
    )
    anim_usd_output_preset: EnumProperty(
        name="Output Preset",
        items=[
            ("auto", "Shot (Auto Path)", "Resolve 01_anim/publish from saved .blend path"),
            ("custom", "Custom", "Use Output File path as-is"),
        ],
        default="auto",
        update=anim_usd_cache_ui._on_anim_usd_output_preset,
    )
    anim_usd_publish_version: IntProperty(
        name="Version",
        description="Publish version folder v001–v999",
        default=1,
        min=1,
        max=999,
        update=anim_usd_cache_ui._on_anim_usd_publish_version,
    )
    anim_usd_use_scene_range: BoolProperty(
        name="Use Scene Range",
        description="Export scene.frame_start through scene.frame_end",
        default=True,
    )
    anim_usd_frame_start: IntProperty(name="Start", default=1)
    anim_usd_frame_end: IntProperty(name="End", default=250)
    anim_usd_root_prim: StringProperty(
        name="Root Prim",
        description="Optional root prim name override (e.g. Char). Leave empty to use Blender root object name",
        default="",
    )
    anim_usd_merge_by_link: BoolProperty(
        name="Merge Same Link",
        description=(
            "Combine linked rig instances that share the same library .blend into "
            "one geo USD file under a single root prim"
        ),
        default=False,
        update=anim_usd_cache_ui._on_anim_usd_merge_by_link,
    )
    anim_usd_skip_view_hidden: BoolProperty(
        name="Skip Hidden / Excluded",
        description=(
            "Do not export objects excluded from the active view layer, or hidden "
            "or disabled in the viewport or render"
        ),
        default=True,
        update=anim_usd_cache_ui._on_anim_usd_export_options_changed,
    )
    anim_usd_status_report: StringProperty(
        name="Export Status",
        default="",
    )
    anim_usd_export_running: BoolProperty(
        name="Export Running",
        description="True while anim USD cache export modal is active",
        default=False,
    )
    anim_usd_export_assets_signature: StringProperty(
        name="Export Assets Signature",
        default="",
    )
    anim_usd_export_assets_index: IntProperty(
        name="Export Assets Index",
        default=0,
        min=0,
    )
    anim_usd_export_assets: CollectionProperty(
        type=anim_usd_cache_asset_list.AnimUsdExportAssetItem,
    )


def _collect_publish_context(context: Context) -> tuple[bool, Optional[AssetHierarchy], list, str]:
    props = _pipeline_props(context)
    selected = _selected_objects(context)
    return resolve_asset_for_publish(
        active=context.view_layer.objects.active,
        selected=selected,
        select_hierarchy=props.select_hierarchy,
    )


def _resolve_output_path(context: Context) -> tuple[bool, str, str]:
    props = _pipeline_props(context)
    if props.output_preset == "custom":
        if not props.output_filepath.strip():
            return False, "", "Output USD file path is empty."
        return True, str(_ensure_export_filepath(props.output_filepath)), ""
    return _compute_uv_export_usd_path(props)


def _resolve_publish_output_dir(props) -> tuple[bool, Path, str]:
    if props.output_preset == "custom":
        raw = str(props.output_filepath or "").strip()
        if not raw:
            return False, Path(), "Output USD file path is empty."
        return True, Path(_ensure_export_filepath(raw)).parent, ""
    scene_path, publish_root = _publish_root_for_props(props)
    if scene_path is None:
        return False, Path(), "Scene is not saved. Save the .blend file first so the publish path can be resolved."
    if publish_root is None:
        return (
            False,
            Path(),
            "Could not resolve publish path. Save .blend under 01_assets/.../01_modelling/<task>/...",
        )
    vname = _version_folder(props)
    return True, publish_root / vname, ""


@dataclass(frozen=True)
class _CollectionPublishJob:
    output_path: str
    objects: list
    collection_name: str


def _plan_collections_publish_jobs(
    props,
    collections: list,
    *,
    empty_message: str,
) -> tuple[bool, list[_CollectionPublishJob], str]:
    if not collections:
        return False, [], empty_message

    ok_dir, out_dir, err_dir = _resolve_publish_output_dir(props)
    if not ok_dir:
        return False, [], err_dir

    scene_path, _ = _publish_root_for_props(props)
    if scene_path is None:
        return False, [], "Scene is not saved. Save the .blend file first."

    jobs: list[_CollectionPublishJob] = []
    for col in collections:
        objs = objects_in_collection_for_export(col)
        if not objs:
            continue
        base = publish_paths.collection_publish_usd_basename(scene_path, col.name)
        jobs.append(
            _CollectionPublishJob(
                output_path=str(out_dir / f"{base}.usd"),
                objects=objs,
                collection_name=col.name,
            )
        )
    if not jobs:
        return False, [], "No exportable objects found in matching collections."
    return True, jobs, ""


def _plan_collection_publish_jobs(props) -> tuple[bool, list[_CollectionPublishJob], str]:
    keyword = str(props.export_collection_keyword or "")
    label = keyword.strip() or "all"
    cols = find_collections_for_keyword_export(keyword)
    if not cols:
        return False, [], f"No collections with objects matching '{label}'."
    return _plan_collections_publish_jobs(
        props,
        cols,
        empty_message=f"No collections with objects matching '{label}'.",
    )


def _plan_selected_collection_publish_jobs(
    context: Context,
    props,
) -> tuple[bool, list[_CollectionPublishJob], str]:
    cols = find_collections_for_selected_export(context)
    return _plan_collections_publish_jobs(
        props,
        cols,
        empty_message=(
            "No collection selected. Select one or more collections in the Outliner, "
            "or activate a collection in the hierarchy."
        ),
    )


def _run_usd_export(props, objs: list, out_path: str) -> None:
    usd_export(
        output_filepath=str(out_path),
        export_animation=False,
        export_uvmaps=props.export_uvmaps,
        export_normals=props.export_normals,
        export_materials=props.export_materials,
        generate_preview_surface=props.generate_preview_surface,
        generate_materialx_network=props.generate_materialx_network,
        export_lights=props.export_lights,
        export_cameras=props.export_cameras,
        export_objects=objs,
        convert_orientation=props.convert_orientation,
        export_global_forward_selection=props.export_forward_axis,
        export_global_up_selection=props.export_up_axis,
        convert_scene_units=props.convert_scene_units,
        root_prim_path=str(props.usd_root_prim_path or config.DEFAULT_USD_ROOT_PRIM_PATH),
    )


def _gather_publish_export(context: Context) -> tuple[bool, list, str, str]:
    props = _pipeline_props(context)
    ok_path, out_path, err_path = _resolve_output_path(context)
    if not ok_path:
        return False, [], err_path, ""

    ok, hierarchy, objs, err = _collect_publish_context(context)
    if not ok or hierarchy is None:
        return False, [], err, ""
    if not objs:
        return False, [], "No objects to export.", out_path
    return True, objs, "", out_path


def _objects_for_publish_collection_item(
    context: Context,
    props,
    collection_name: str,
) -> tuple[bool, list, str]:
    selected = list(getattr(context, "selected_objects", []) or [])
    ok, hierarchy, objs, err = resolve_asset_for_publish(
        active=context.view_layer.objects.active,
        selected=selected,
        select_hierarchy=props.select_hierarchy,
    )
    if (
        ok
        and hierarchy is not None
        and hierarchy.asset_collection.name == collection_name
        and objs
    ):
        return True, list(objs), ""

    col = bpy.data.collections.get(collection_name)
    if col is None:
        return False, [], f"Collection not found: {collection_name}"
    objs = objects_in_collection_for_export(col)
    if not objs:
        return False, [], f"No exportable objects in collection: {collection_name}"
    return True, objs, ""


def _plan_publish_jobs_from_list(
    context: Context,
    props,
) -> tuple[bool, Optional[list[_CollectionPublishJob]], Optional[list], Optional[str], str]:
    enabled_items = geo_usd_publish_list.enabled_publish_items(props)
    if not enabled_items:
        if geo_usd_publish_list.publish_export_object_count(props) > 0:
            return False, None, None, None, "No enabled collections in export list."
        return False, None, None, None, ""

    collection_export = (
        props.export_collections_by_keyword or props.export_selected_collection
    )
    single_asset = len(enabled_items) == 1 and not collection_export

    if single_asset:
        item = enabled_items[0]
        ok_objs, objs, err_objs = _objects_for_publish_collection_item(
            context,
            props,
            item.object_name,
        )
        if not ok_objs:
            return False, None, None, None, err_objs
        ok_path, out_path, err_path = _resolve_output_path(context)
        if not ok_path:
            return False, None, None, None, err_path
        return True, None, objs, out_path, ""

    ok_dir, out_dir, err_dir = _resolve_publish_output_dir(props)
    if not ok_dir:
        return False, None, None, None, err_dir

    scene_path, _ = _publish_root_for_props(props)
    if scene_path is None:
        return False, None, None, None, "Scene is not saved. Save the .blend file first."

    jobs: list[_CollectionPublishJob] = []
    for item in enabled_items:
        ok_objs, objs, err_objs = _objects_for_publish_collection_item(
            context,
            props,
            item.object_name,
        )
        if not ok_objs:
            return False, None, None, None, err_objs
        base = publish_paths.collection_publish_usd_basename(scene_path, item.object_name)
        jobs.append(
            _CollectionPublishJob(
                output_path=str(out_dir / f"{base}.usd"),
                objects=objs,
                collection_name=item.object_name,
            )
        )
    if not jobs:
        return False, None, None, None, "No exportable objects in enabled collections."
    return True, jobs, None, None, ""


def _resolve_hierarchy_for_prep(context: Context) -> tuple[bool, Optional[AssetHierarchy], str]:
    props = _pipeline_props(context)
    active = context.view_layer.objects.active
    hierarchy = resolve_asset_hierarchy_from_object(active) if active else None
    if hierarchy is None:
        for o in context.selected_objects or []:
            hierarchy = resolve_asset_hierarchy_from_object(o)
            if hierarchy:
                break
    if hierarchy is None:
        slug = (props.asset_name or "Asset").strip()
        col = bpy.data.collections.get(asset_collection_name_for(slug))
        if col is not None:
            hierarchy = get_asset_hierarchy_from_collection(col)
    if hierarchy is None:
        return False, None, "No Geo_<Asset> collection found. Run Create Asset Tree first."
    return True, hierarchy, ""


# ---------------------------------------------------------------------------
# Preparing operators
# ---------------------------------------------------------------------------


class MONOFX_OT_create_hierarchy(Operator):
    """Create Geo_<Asset> collection and asset tree from the preset."""
    bl_idname = "wm.mono_fx_create_hierarchy"
    bl_label = "Create Asset Tree"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        init_scene_preset_if_empty(props)
        asset_col, moved = create_hierarchy_from_scene_props(context, props=props)
        msg = f"Asset tree ready in collection '{asset_col.name}'."
        if moved:
            msg += f" Moved {moved} selected object(s) into it."
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_auto_parent(Operator):
    """Parent selected meshes under matching *_Grp empties using naming rules."""
    bl_idname = "wm.mono_fx_auto_parent_selected"
    bl_label = "Auto-Parent Selected"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        if not context.selected_objects:
            _report_error(self, "Select mesh objects to auto-parent.")
            return {"CANCELLED"}
        result = run_auto_parent(context, props=props, selected_only=True)
        parts = [
            f"assigned={len(result.assigned)}",
            f"skipped={len(result.skipped)}",
            f"ambiguous={len(result.ambiguous)}",
            f"unassigned={len(result.unassigned)}",
        ]
        props.auto_parent_report = "; ".join(parts)
        if result.ambiguous:
            self.report({"WARNING"}, f"Ambiguous: {', '.join(result.ambiguous[:8])}")
        if result.unassigned:
            self.report({"WARNING"}, f"Unassigned: {', '.join(result.unassigned[:8])}")
        self.report({"INFO"}, props.auto_parent_report)
        return {"FINISHED"}


class MONOFX_OT_select_hierarchy_tree(Operator):
    """Select all mesh objects under the Geo asset root."""
    bl_idname = "wm.mono_fx_select_hierarchy_tree"
    bl_label = "Select All Geo in Asset Tree"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        ok, hierarchy, err = _resolve_hierarchy_for_prep(context)
        if not ok or hierarchy is None:
            _report_error(self, err)
            return {"CANCELLED"}
        try:
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        meshes = collect_geo_meshes_in_hierarchy(hierarchy)
        if not meshes:
            _report_error(self, "No mesh geo objects under Geo root.")
            return {"CANCELLED"}
        view_layer = context.view_layer
        for o in view_layer.objects:
            o.select_set(False)
        for obj in meshes:
            try:
                obj.select_set(True)
            except RuntimeError:
                pass
        view_layer.objects.active = meshes[0]
        self.report({"INFO"}, f"Selected {len(meshes)} geo mesh(es).")
        return {"FINISHED"}


class MONOFX_OT_group_objects(Operator):
    """Parent selected objects under a new empty at world origin."""
    bl_idname = "wm.mono_fx_group_objects"
    bl_label = "Group Objects"
    bl_description = "Parent selected objects under a new empty at world origin"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_description or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        selected = list(context.selected_objects or [])
        if not selected:
            _report_error(self, "No objects selected.")
            return {"CANCELLED"}
        ok, msg, _empty = group_selected_objects_at_origin(context, selected)
        if not ok:
            _report_error(self, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_collect_objects_to_collections(Operator):
    """Put each selected object and its children into a collection named after the object."""
    bl_idname = "wm.mono_fx_collect_objects_to_collections"
    bl_label = "Collect Objects"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        selected = list(context.selected_objects or [])
        ok, msg, _created, _moved = collect_selected_into_named_collections(context, selected)
        if not ok:
            _report_error(self, msg)
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class MONOFX_OT_lowercase_selected(Operator):
    bl_idname = "wm.mono_fx_lowercase_selected"
    bl_label = "Lowercase Selected"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        sel = _selected_objects(context)
        if not sel:
            _report_error(self, "No objects selected.")
            return {"CANCELLED"}
        renamed, skipped = lowercase_selected_names(sel)
        self.report({"INFO"}, f"Lowercased {renamed}, skipped {skipped}.")
        return {"FINISHED"}


class MONOFX_OT_add_geo_prefix(Operator):
    bl_idname = "wm.mono_fx_add_geo_prefix"
    bl_label = "Add Geo Prefix"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        sel = _selected_objects(context)
        if not sel:
            _report_error(self, "No objects selected.")
            return {"CANCELLED"}
        prefix = (props.mesh_geo_prefix or "").strip()
        if not prefix:
            _report_error(self, "Mesh geo prefix is empty.")
            return {"CANCELLED"}
        renamed, skipped = add_geo_prefix_to_selected(sel, prefix)
        self.report({"INFO"}, f"Prefixed {renamed}, skipped {skipped}.")
        return {"FINISHED"}


class MONOFX_OT_set_on_floor(Operator):
    """Move selection or asset Geo tree so mesh bbox minimum sits on Z=0."""
    bl_idname = "wm.mono_fx_set_on_floor"
    bl_label = "Set on Floor"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        selected = list(context.selected_objects or [])
        if selected:
            done, delta = set_objects_on_floor(selected)
            if not done:
                _report_error(self, "No mesh bounds in selection. Select mesh objects.")
                return {"CANCELLED"}
            n = len(selected)
            self.report({"INFO"}, f"Moved {n} selected object(s) by Z={delta:.4f}.")
            return {"FINISHED"}

        ok, hierarchy, err = _resolve_hierarchy_for_prep(context)
        if not ok or hierarchy is None:
            _report_error(self, err)
            return {"CANCELLED"}
        done, delta = set_tree_on_floor(hierarchy.geo_container)
        if not done:
            _report_error(self, "No mesh bounds found under Geo root.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Moved asset tree by Z={delta:.4f} (nothing selected).")
        return {"FINISHED"}


class MONOFX_OT_center_to_origin(Operator):
    """Move selection or asset Geo tree so mesh bbox center sits at world origin."""
    bl_idname = "wm.mono_fx_center_to_origin"
    bl_label = "Center to Origin"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        selected = list(context.selected_objects or [])
        if selected:
            done, delta = set_objects_center_to_origin(selected)
            if not done:
                _report_error(self, "No mesh bounds in selection. Select mesh objects.")
                return {"CANCELLED"}
            n = len(selected)
            self.report(
                {"INFO"},
                f"Centered {n} selected object(s) by "
                f"X={delta[0]:.4f}, Y={delta[1]:.4f}, Z={delta[2]:.4f}.",
            )
            return {"FINISHED"}

        ok, hierarchy, err = _resolve_hierarchy_for_prep(context)
        if not ok or hierarchy is None:
            _report_error(self, err)
            return {"CANCELLED"}
        done, delta = set_tree_center_to_origin(hierarchy.geo_container)
        if not done:
            _report_error(self, "No mesh bounds found under Geo root.")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Centered asset tree by X={delta[0]:.4f}, Y={delta[1]:.4f}, Z={delta[2]:.4f} "
            "(nothing selected).",
        )
        return {"FINISHED"}


def _draw_advanced_align_settings(layout: bpy.types.UILayout, props: MonoFXProperties) -> None:
    layout.label(text="BBox Point")

    row_x = layout.row(align=True)
    ui_style.prop_checkbox(row_x, props, "advanced_align_enable_x", text="X")
    axis_x = row_x.row(align=True)
    axis_x.enabled = props.advanced_align_enable_x
    axis_x.prop(props, "advanced_align_axis_x", text="")

    row_y = layout.row(align=True)
    ui_style.prop_checkbox(row_y, props, "advanced_align_enable_y", text="Y")
    axis_y = row_y.row(align=True)
    axis_y.enabled = props.advanced_align_enable_y
    axis_y.prop(props, "advanced_align_axis_y", text="")

    row_z = layout.row(align=True)
    ui_style.prop_checkbox(row_z, props, "advanced_align_enable_z", text="Z")
    axis_z = row_z.row(align=True)
    axis_z.enabled = props.advanced_align_enable_z
    axis_z.prop(props, "advanced_align_axis_z", text="")

    layout.separator()
    layout.label(text="BBox Scope")
    ui_style.prop_checkbox(layout, props, "advanced_align_combined_bbox", text="Combined Bbox")
    layout.separator()
    layout.label(text="Align To")
    ui_style.prop_checkbox(layout, props, "advanced_align_to_origin", text="Origin")
    ui_style.prop_checkbox(layout, props, "advanced_align_to_cursor", text="Cursor")


class MONOFX_OT_advanced_align_settings(Operator):
    """Advanced Align options (bbox point, scope, and target)."""
    bl_idname = "wm.mono_fx_advanced_align_settings"
    bl_label = "Advanced Align Settings"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def invoke(self, context: Context, event) -> set[str]:
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context: Context) -> None:
        _draw_advanced_align_settings(self.layout, _pipeline_props(context))

    def execute(self, context: Context) -> set[str]:
        return {"FINISHED"}


class MONOFX_OT_advanced_align(Operator):
    """Align mesh bbox min/center/max per axis to world origin or the 3D cursor."""
    bl_idname = "wm.mono_fx_advanced_align"
    bl_label = "Advanced Align"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        if not props.advanced_align_to_origin and not props.advanced_align_to_cursor:
            _report_error(self, "Enable Align to Origin or Align to Cursor.")
            return {"CANCELLED"}
        if not (
            props.advanced_align_enable_x
            or props.advanced_align_enable_y
            or props.advanced_align_enable_z
        ):
            _report_error(self, "Enable at least one axis: X, Y, or Z.")
            return {"CANCELLED"}

        if props.advanced_align_to_cursor:
            cursor = context.scene.cursor.location
            target = (float(cursor.x), float(cursor.y), float(cursor.z))
            target_label = "3D cursor"
        else:
            target = (0.0, 0.0, 0.0)
            target_label = "origin"

        align_kwargs = dict(
            axis_x=props.advanced_align_axis_x,
            axis_y=props.advanced_align_axis_y,
            axis_z=props.advanced_align_axis_z,
            enable_x=props.advanced_align_enable_x,
            enable_y=props.advanced_align_enable_y,
            enable_z=props.advanced_align_enable_z,
            target=target,
            combined_bbox=props.advanced_align_combined_bbox,
        )

        selected = list(context.selected_objects or [])
        if selected:
            done, delta, aligned_count = advanced_align_objects(selected, **align_kwargs)
            if not done:
                _report_error(self, "No mesh bounds in selection. Select mesh objects.")
                return {"CANCELLED"}
            n = len(selected)
            if props.advanced_align_combined_bbox:
                self.report(
                    {"INFO"},
                    f"Aligned {n} selected object(s) to {target_label} by "
                    f"X={delta[0]:.4f}, Y={delta[1]:.4f}, Z={delta[2]:.4f}.",
                )
            else:
                self.report(
                    {"INFO"},
                    f"Aligned {aligned_count} mesh(es) individually to {target_label}.",
                )
            return {"FINISHED"}

        ok, hierarchy, err = _resolve_hierarchy_for_prep(context)
        if not ok or hierarchy is None:
            _report_error(self, err)
            return {"CANCELLED"}
        done, delta, aligned_count = advanced_align_tree(hierarchy.geo_container, **align_kwargs)
        if not done:
            _report_error(self, "No mesh bounds found under Geo root.")
            return {"CANCELLED"}
        if props.advanced_align_combined_bbox:
            self.report(
                {"INFO"},
                f"Aligned asset tree to {target_label} by "
                f"X={delta[0]:.4f}, Y={delta[1]:.4f}, Z={delta[2]:.4f} (nothing selected).",
            )
        else:
            self.report(
                {"INFO"},
                f"Aligned {aligned_count} mesh(es) individually to {target_label} "
                f"(nothing selected).",
            )
        return {"FINISHED"}


class MONOFX_OT_advanced_apply_transform(Operator):
    """Apply object transforms with production-tree or selection scope and channel options."""
    bl_idname = "wm.mono_fx_advanced_apply_transform"
    bl_label = "Advanced Apply Transform"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def invoke(self, context: Context, event) -> set[str]:
        return context.window_manager.invoke_props_dialog(self, width=320, confirm_text="APPLY!")

    def draw(self, context: Context) -> None:
        props = _pipeline_props(context)
        layout = self.layout
        ui_style.prop_checkbox(layout, props, "allow_apply_on_armature")
        layout.separator()
        layout.label(text="Apply Objects")
        layout.prop(props, "apply_transform_scope", expand=True)
        layout.separator()
        layout.label(text="Channels")
        col = layout.column(align=True)
        ui_style.prop_checkbox(col, props, "apply_transform_location", text="Location")
        ui_style.prop_checkbox(col, props, "apply_transform_rotation", text="Rotation")
        ui_style.prop_checkbox(col, props, "apply_transform_scale", text="Scale")

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        if not (
            props.apply_transform_location
            or props.apply_transform_rotation
            or props.apply_transform_scale
        ):
            _report_error(self, "Enable at least one channel: Location, Rotation, or Scale.")
            return {"CANCELLED"}

        selected = list(context.selected_objects or [])
        tree_root = None
        scope = props.apply_transform_scope

        if scope == "PRODUCTION_TREE":
            ok, hierarchy, err = _resolve_hierarchy_for_prep(context)
            if not ok or hierarchy is None:
                _report_error(self, err)
                return {"CANCELLED"}
            tree_root = hierarchy.geo_container
        elif not selected:
            _report_error(self, "Select object(s) for Selection Hierarchy scope.")
            return {"CANCELLED"}

        targets = collect_apply_transform_targets(
            scope=scope,
            tree_root=tree_root,
            selected=selected,
            allow_armature=props.allow_apply_on_armature,
        )
        if not targets:
            _report_error(self, "No mesh or armature objects found for the chosen scope.")
            return {"CANCELLED"}

        applied, failed = apply_transforms_to_objects(
            targets,
            location=props.apply_transform_location,
            rotation=props.apply_transform_rotation,
            scale=props.apply_transform_scale,
        )
        self.report({"INFO"}, f"Applied {len(applied)}, failed {len(failed)}.")
        return {"FINISHED"}


class MONOFX_OT_clean_mesh(Operator):
    bl_idname = "wm.mono_fx_clean_mesh"
    bl_label = "Clean Mesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        selected = _selected_objects(context)
        tree_root = None
        if not any(o.type == "MESH" for o in selected):
            ok, hierarchy, err = _resolve_hierarchy_for_prep(context)
            if not ok or hierarchy is None:
                _report_error(self, err or "Select mesh object(s) or create Geo_<Asset> hierarchy.")
                return {"CANCELLED"}
            tree_root = hierarchy.geo_container
        meshes = collect_meshes_for_cleanup(selected=selected, tree_root=tree_root)
        if not meshes:
            _report_error(self, "No mesh objects in selection or asset tree.")
            return {"CANCELLED"}

        opts = MeshCleanupOptions(
            apply_modifiers=props.clean_apply_modifiers,
            apply_shape_keys=props.clean_apply_shape_keys,
            clean_vertex_groups=props.clean_vertex_groups,
            clean_color_attributes=props.clean_color_attributes,
            clean_custom_attributes=props.clean_custom_attributes,
            clean_uv_maps=props.clean_uv_maps,
        )
        result = run_mesh_cleanup(meshes, opts)
        props.clean_mesh_report = result.summary()
        if result.errors:
            self.report({"WARNING"}, "; ".join(result.errors[:4]))
        if result.meshes_processed == 0 and not result.errors:
            _report_error(self, "Nothing cleaned (linked meshes may be skipped).")
            return {"CANCELLED"}
        self.report({"INFO"}, props.clean_mesh_report)
        return {"FINISHED"}


class MONOFX_OT_clear_materials(Operator):
    bl_idname = "wm.mono_fx_clear_materials_tree"
    bl_label = "Clear Materials (Tree)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        ok, hierarchy, err = _resolve_hierarchy_for_prep(context)
        if not ok or hierarchy is None:
            _report_error(self, err)
            return {"CANCELLED"}
        meshes = [o for o in iter_hierarchy_objects(hierarchy) if o.type == "MESH"]
        n = clear_materials_on_objects(meshes, purge_orphans=props.purge_orphan_materials)
        self.report({"INFO"}, f"Cleared {n} material slot(s).")
        return {"FINISHED"}


class MONOFX_OT_assign_materials(Operator):
    bl_idname = "wm.mono_fx_assign_materials_from_groups"
    bl_label = "Assign Materials from Groups"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        ok, hierarchy, err = _resolve_hierarchy_for_prep(context)
        if not ok or hierarchy is None:
            _report_error(self, err)
            return {"CANCELLED"}
        created, assigned = assign_materials_from_grp_tree(
            hierarchy.geo_container, material_prefix=props.material_prefix
        )
        invalidate_material_bake_targets_signature(props)
        self.report({"INFO"}, f"Materials created {created}, slots set {assigned}.")
        return {"FINISHED"}


def _resolve_material_bake_output_dir(
    props: MonoFXProperties,
) -> tuple[Optional[Path], Optional[str]]:
    blend_path = _scene_blend_path()
    publish_root = _resolve_publish_root_from_scene(blend_path) if blend_path else None
    output_dir = resolve_bake_output_dir(
        output_mode=props.material_bake_output_mode,
        blend_path=blend_path,
        publish_root=publish_root,
        custom_dir=props.material_bake_output_dir,
    )
    if output_dir is not None:
        return output_dir, None
    mode = (props.material_bake_output_mode or "").upper()
    if mode == "PUBLISH_TEXTURES":
        return None, (
            "Publish textures folder unavailable. Save under 01_modelling/<task>/ "
            "or choose Blend Textures / Custom."
        )
    if mode == "CUSTOM":
        return None, "Set a custom output folder in bake settings."
    return None, "Save the .blend file first or choose another output folder."


def _update_material_bake_statuses(context: Context, props: MonoFXProperties) -> None:
    output_dir, _ = _resolve_material_bake_output_dir(props)
    refresh_material_bake_targets(context, props, output_dir=output_dir, force=True)


def _material_bake_preflight(
    props: MonoFXProperties,
) -> tuple[Optional[list], Optional[Path], Optional[str]]:
    """Return enabled bake targets, output dir, and error message."""
    if not (
        props.material_bake_pass_base_color
        or props.material_bake_pass_roughness
        or props.material_bake_pass_normal
        or props.material_bake_pass_ao
        or props.material_bake_pass_opacity
    ):
        return None, None, "Enable at least one bake pass in settings."

    targets = enabled_bake_targets(props)
    if not targets:
        if len(props.material_bake_targets) == 0:
            return (
                None,
                None,
                "No bake targets in Geo tree. Create hierarchy and assign materials.",
            )
        return None, None, "Enable at least one target in the bake list."

    output_dir, err = _resolve_material_bake_output_dir(props)
    if output_dir is None:
        return None, None, err or "Output folder unavailable."
    return targets, output_dir, None


def _draw_material_bake_confirm(layout: bpy.types.UILayout, props: MonoFXProperties) -> None:
    plan = material_bake_run_plan(props)
    warn = layout.box()
    warn.alert = True
    warn.label(text="Blender will freeze until baking finishes.", icon="TIME")
    warn.label(text="Large targets or high resolution can take several minutes.", icon="BLANK1")

    layout.separator()
    layout.label(text="Bake Plan", icon="RENDER_STILL")
    col = layout.column(align=True)
    col.scale_y = 0.9
    target_count = int(plan["target_count"])
    col.label(text=f"Targets: {target_count}", icon="OUTLINER_OB_MESH")
    pass_labels = plan["pass_labels"]
    if pass_labels:
        col.label(
            text=f"Passes: {', '.join(pass_labels)}",
            icon="RENDERLAYERS",
        )
    col.label(text=f"Resolution: {plan['resolution']} px", icon="IMAGE_DATA")
    total_steps = int(plan["total_steps"])
    if total_steps > 0:
        col.label(text=f"Bake steps: ~{total_steps}", icon="LINENUMBERS_ON")

    _, output_dir, _ = _material_bake_preflight(props)
    if output_dir is not None:
        layout.separator()
        out_row = layout.row()
        out_row.scale_y = 0.85
        out_row.label(text=f"Output: {output_dir}", icon="FILE_FOLDER")


def _draw_material_bake_usd_settings(
    layout: bpy.types.UILayout,
    context: Context,
    props: MonoFXProperties,
) -> None:
    layout.label(text="Bake Grouping", icon="MATERIAL")
    grouping_row = layout.row(align=True)
    grouping_row.prop(props, "material_bake_scope", expand=True)
    hint = layout.column(align=True)
    hint.scale_y = 0.85
    if (props.material_bake_scope or "").upper() == "PER_MESH":
        hint.label(text="One texture set per mesh object", icon="DOT")
    else:
        hint.label(text="One texture set per material (bakes on first mesh)", icon="DOT")
    layout.separator()
    layout.label(text="Passes")
    col = layout.column(align=True)
    ui_style.prop_checkbox(col, props, "material_bake_pass_base_color", text="Base Color")
    ui_style.prop_checkbox(col, props, "material_bake_pass_roughness", text="Roughness")
    ui_style.prop_checkbox(col, props, "material_bake_pass_normal", text="Normal")
    ui_style.prop_checkbox(col, props, "material_bake_pass_ao", text="AO")
    ui_style.prop_checkbox(col, props, "material_bake_pass_opacity", text="Opacity")
    hint = col.column(align=True)
    hint.enabled = props.material_bake_pass_opacity
    hint.scale_y = 0.85
    hint.label(text="Extra diffuse pass → Opacity.png (margin 0)", icon="DOT")
    layout.separator()
    layout.label(text="Naming")
    layout.prop(props, "material_bake_texture_stem_mode", text="Texture Files")
    tex_custom = layout.row()
    tex_custom.enabled = props.material_bake_texture_stem_mode == "CUSTOM"
    tex_custom.prop(props, "material_bake_texture_stem_template", text="Template")
    layout.prop(props, "material_bake_shader_name_mode", text="Shader")
    shader_custom = layout.row()
    shader_custom.enabled = props.material_bake_shader_name_mode == "CUSTOM"
    shader_custom.prop(props, "material_bake_shader_name_template", text="Template")
    preview = layout.column(align=True)
    preview.scale_y = 0.85
    example_stem = resolve_texture_stem(
        "M_char_Body",
        "geo_head",
        mode=props.material_bake_texture_stem_mode,
        material_prefix="",
        custom_template=props.material_bake_texture_stem_template,
    )
    example_shader = resolve_shader_name(
        "M_char_Body",
        "geo_head",
        example_stem,
        mode=props.material_bake_shader_name_mode,
        material_prefix="",
        custom_template=props.material_bake_shader_name_template,
    )
    preview.label(text=f"Texture: {example_stem}_BaseColor.png", icon="IMAGE_DATA")
    preview.label(text=f"Shader: {example_shader}", icon="MATERIAL")
    lib_material = "Atlas.012"
    lib_mesh = "geo_mesh"
    lib_stem = resolve_texture_stem(
        lib_material,
        lib_mesh,
        mode=props.material_bake_texture_stem_mode,
        material_prefix="",
        custom_template=props.material_bake_texture_stem_template,
    )
    lib_shader_names = {
        resolve_shader_name(
            lib_material,
            lib_mesh,
            lib_stem,
            mode=mode,
            material_prefix="",
            custom_template=props.material_bake_shader_name_template,
        )
        for mode in ("TEXTURE_STEM", "MATERIAL_STEM", "KEEP_SOURCE")
    }
    if len(lib_shader_names) == 1:
        note = preview.box()
        note.label(
            text=(
                f"Match Texture / Material Stem / Keep Source all → "
                f"«{next(iter(lib_shader_names))}» for materials without prefix "
                f"(e.g. {lib_material})"
            ),
            icon="INFO",
        )
        note.label(
            text="Use Material + Mesh, Mesh + Material, or Source + Texture to differ.",
            icon="BLANK1",
        )
    layout.separator()
    layout.label(text="Output")
    layout.prop(props, "material_bake_resolution")
    layout.prop(props, "material_bake_output_mode")
    custom_row = layout.row()
    custom_row.enabled = props.material_bake_output_mode == "CUSTOM"
    custom_row.prop(props, "material_bake_output_dir", text="Folder")
    layout.prop(props, "material_bake_image_format")
    layout.prop(props, "material_bake_uv_map", text="UV Map")
    layout.prop(props, "material_bake_margin")
    ui_style.prop_checkbox(layout, props, "material_bake_pack_images", text="Pack into .blend")
    ui_style.prop_checkbox(
        layout,
        props,
        "material_bake_simplify_shader",
        text="Simplify for USD Export",
    )
    layout.separator()
    note = layout.column(align=True)
    note.scale_y = 0.85
    note.label(text="Bake blocks the UI until all passes finish.", icon="TIME")


def _create_material_bake_session(
    context: Context,
    props: MonoFXProperties,
    targets: list,
    output_dir: Path,
) -> MaterialBakeSession:
    meshes = [t.meshes[0] for t in targets]
    try:
        resolution = int(props.material_bake_resolution)
    except (TypeError, ValueError):
        resolution = 2048
    return MaterialBakeSession(
        context,
        meshes,
        scope=props.material_bake_scope,
        material_prefix="",
        targets=targets,
        pass_base_color=props.material_bake_pass_base_color,
        pass_roughness=props.material_bake_pass_roughness,
        pass_normal=props.material_bake_pass_normal,
        pass_ao=props.material_bake_pass_ao,
        pass_opacity=props.material_bake_pass_opacity,
        resolution=resolution,
        output_dir=output_dir,
        image_format=props.material_bake_image_format,
        uv_map_name=props.material_bake_uv_map,
        margin=props.material_bake_margin,
        pack_images=props.material_bake_pack_images,
        simplify_shader=props.material_bake_simplify_shader,
        texture_stem_mode=props.material_bake_texture_stem_mode,
        shader_name_mode=props.material_bake_shader_name_mode,
        texture_stem_template=props.material_bake_texture_stem_template,
        shader_name_template=props.material_bake_shader_name_template,
    )


class MONOFX_OT_bake_materials_usd_settings(Operator):
    """Passes, resolution, output folder, and bake target rules for Bake for USD."""
    bl_idname = "wm.mono_fx_bake_materials_usd_settings"
    bl_label = "Bake for USD Settings"
    bl_options = {"REGISTER"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def invoke(self, context: Context, event) -> set[str]:
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context: Context) -> None:
        _draw_material_bake_usd_settings(self.layout, context, _pipeline_props(context))

    def execute(self, context: Context) -> set[str]:
        return {"FINISHED"}


class MONOFX_OT_bake_materials_usd(Operator):
    """Bake checked rows in the target list to PBR textures with live progress."""
    bl_idname = "wm.mono_fx_bake_materials_usd"
    bl_label = "Bake Enabled Targets"
    bl_options = {"REGISTER", "UNDO"}

    _session: Optional[MaterialBakeSession] = None
    _timer = None

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def invoke(self, context: Context, event) -> set[str]:
        props = _pipeline_props(context)
        if props.material_bake_running:
            _report_error(self, "Material bake already running.")
            return {"CANCELLED"}
        _, _, err = _material_bake_preflight(props)
        if err:
            _report_error(self, err)
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self,
            width=420,
            confirm_text="Bake",
        )

    def draw(self, context: Context) -> None:
        _draw_material_bake_confirm(self.layout, _pipeline_props(context))

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        targets, output_dir, err = _material_bake_preflight(props)
        if err:
            _report_error(self, err)
            return {"CANCELLED"}

        session = _create_material_bake_session(context, props, targets, output_dir)
        err = session.begin()
        if err:
            _report_error(self, err)
            return {"CANCELLED"}

        self._session = session
        props.material_bake_running = True
        props.material_bake_report = "Baking…"
        context.window.cursor_set("WAIT")
        wm = context.window_manager
        wm.progress_begin(0, session.total_steps)
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        tag_redraw_ui()
        return {"RUNNING_MODAL"}

    def modal(self, context: Context, event) -> set[str]:
        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        session = self._session
        if session is None:
            return self._finish_material_bake(context)

        if not session.done:
            session.step()
            props = _pipeline_props(context)
            total = max(session.total_steps, 1)
            props.material_bake_report = (
                f"Baking… {session.current_step}/{total} · {session.status_label}"
            )
            context.window_manager.progress_update(session.current_step)
            tag_redraw_ui()

        if session.done:
            return self._finish_material_bake(context)
        return {"RUNNING_MODAL"}

    def _finish_material_bake(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        session = self._session
        result = session.finish() if session is not None else None

        wm = context.window_manager
        if hasattr(wm, "progress_end"):
            wm.progress_end()
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        context.window.cursor_set("DEFAULT")
        props.material_bake_running = False
        self._session = None

        if result is None:
            return {"CANCELLED"}

        if session.restore_records:
            apply_bake_restore_records(props, session.restore_records)

        _update_material_bake_statuses(context, props)
        props.material_bake_report = result.summary()
        tag_redraw_ui()

        if result.warnings:
            self.report({"WARNING"}, "; ".join(result.warnings[:4]))
        if not result.ok:
            _report_error(self, result.error or props.material_bake_report)
            return {"CANCELLED"}
        self.report({"INFO"}, props.material_bake_report)
        return {"FINISHED"}


class MONOFX_OT_material_bake_open_output_folder(Operator):
    """Open the baked texture output folder in the file browser."""
    bl_idname = "wm.mono_fx_material_bake_open_output_folder"
    bl_label = "Open Texture Folder"
    bl_options = {"REGISTER"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        output_dir, err = _resolve_material_bake_output_dir(props)
        if output_dir is None:
            _report_error(self, err or "Output folder unavailable.")
            return {"CANCELLED"}
        target = output_dir.resolve()
        if not target.is_dir():
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                _report_error(self, f"Cannot open texture folder: {exc}")
                return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=str(target))
        return {"FINISHED"}


class MONOFX_OT_preset_load_default(Operator):
    bl_idname = "wm.mono_fx_preset_load_default"
    bl_label = "Load Default Preset"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = (
        "Load presets/character_geo.json into the list, overwrite the default file on disk, "
        "and set Preset JSON path to that file"
    )

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        path = default_preset_json_path()
        if not path.is_file():
            _report_error(self, f"Default preset not found: {path}")
            return {"CANCELLED"}
        try:
            path = reload_default_character_preset(props)
        except json.JSONDecodeError as exc:
            _report_error(self, f"Invalid default preset JSON: {exc}")
            return {"CANCELLED"}
        except OSError as exc:
            _report_error(self, f"Could not read/write default preset: {exc}")
            return {"CANCELLED"}
        props.preset_json_path = str(path)
        self.report({"INFO"}, f"Loaded and saved default preset ({path.name}).")
        return {"FINISHED"}


class MONOFX_OT_preset_load_json(Operator):
    bl_idname = "wm.mono_fx_preset_load_json"
    bl_label = "Load Preset JSON"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        path = Path(props.preset_json_path.strip())
        if not path.is_file():
            _report_error(self, f"File not found: {path}")
            return {"CANCELLED"}
        apply_preset_to_scene_nodes(props, load_preset_from_json(path))
        self.report({"INFO"}, f"Loaded preset from {path.name}.")
        return {"FINISHED"}


class MONOFX_OT_preset_save_json(Operator):
    bl_idname = "wm.mono_fx_preset_save_json"
    bl_label = "Save Preset JSON"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        path = Path(props.preset_json_path.strip())
        if not path:
            _report_error(self, "Set Preset JSON path first.")
            return {"CANCELLED"}
        save_preset_to_json(preset_from_scene_nodes(props), path)
        self.report({"INFO"}, f"Saved preset to {path}.")
        return {"FINISHED"}


class MONOFX_OT_preset_add_node(Operator):
    bl_idname = "wm.mono_fx_preset_add_node"
    bl_label = "Add Preset Node"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        item = props.preset_nodes.add()
        item.empty_name = "New_Grp"
        item.parent_name = config.INNER_GEO_NAME
        item.is_leaf = True
        props.preset_index = len(props.preset_nodes) - 1
        return {"FINISHED"}


class MONOFX_OT_preset_remove_node(Operator):
    bl_idname = "wm.mono_fx_preset_remove_node"
    bl_label = "Remove Preset Node"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        if not props.preset_nodes:
            return {"CANCELLED"}
        props.preset_nodes.remove(props.preset_index)
        props.preset_index = min(props.preset_index, max(0, len(props.preset_nodes) - 1))
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# USD publish operators (legacy idnames kept for scripts / old .blend)
# ---------------------------------------------------------------------------


def _finish_collection_publish_jobs(
    op: Operator,
    props,
    jobs: list[_CollectionPublishJob],
) -> set[str]:
    try:
        for job in jobs:
            out_dir = os.path.dirname(job.output_path)
            if out_dir:
                Path(out_dir).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _report_error(op, f"Failed to create output folder: {e}")
        return {"CANCELLED"}
    published_version = _version_folder(props)
    for job in jobs:
        _run_usd_export(props, job.objects, job.output_path)
    props.publish_status_report = f"Created version {published_version} · {len(jobs)} file(s)"
    if props.output_preset == "uv":
        sync_auto_publish_output(props)
    names = ", ".join(Path(j.output_path).name for j in jobs[:4])
    if len(jobs) > 4:
        names += f", +{len(jobs) - 4} more"
    op.report({"INFO"}, f"Published {len(jobs)} USD file(s): {names}")
    return {"FINISHED"}


def _format_publish_plan_lines(
    props,
    *,
    jobs: Optional[list[_CollectionPublishJob]] = None,
    objs: Optional[list] = None,
    out_path: Optional[str] = None,
) -> list[str]:
    lines: list[str] = [f"Version: {_version_folder(props)}"]
    if jobs is not None:
        lines.append(f"Files: {len(jobs)} USD")
        for job in jobs[:6]:
            lines.append(
                f"  {Path(job.output_path).name}  "
                f"({job.collection_name}, {len(job.objects)} obj)"
            )
        if len(jobs) > 6:
            lines.append(f"  +{len(jobs) - 6} more")
        return lines
    if out_path:
        lines.append(f"File: {Path(out_path).name}")
        if objs is not None:
            lines.append(f"Objects: {len(objs)}")
        scene_path = _scene_blend_path()
        if scene_path is not None:
            lines.append(publish_paths.relative_publish_display(scene_path, Path(out_path)))
    return lines


def _summarize_publish_plan(context: Context, props) -> tuple[bool, list[str], str]:
    ok_list, jobs, objs, out_path, err_list = _plan_publish_jobs_from_list(context, props)
    if ok_list:
        if jobs is not None:
            return True, _format_publish_plan_lines(props, jobs=jobs), ""
        return True, _format_publish_plan_lines(props, objs=objs, out_path=out_path), ""

    if err_list:
        return False, [], err_list

    if props.export_selected_collection:
        ok, jobs, err = _plan_selected_collection_publish_jobs(context, props)
        if not ok:
            return False, [], err
        return True, _format_publish_plan_lines(props, jobs=jobs), ""

    if props.export_collections_by_keyword:
        ok, jobs, err = _plan_collection_publish_jobs(props)
        if not ok:
            return False, [], err
        return True, _format_publish_plan_lines(props, jobs=jobs), ""

    ok, objs, err, out_path = _gather_publish_export(context)
    if not ok:
        return False, [], err
    return True, _format_publish_plan_lines(props, objs=objs, out_path=out_path), ""


def _draw_publish_confirm_dialog(layout: bpy.types.UILayout, context: Context) -> None:
    props = _pipeline_props(context)
    ok, lines, err = _summarize_publish_plan(context, props)
    col = layout.column(align=True)
    if not ok:
        col.label(text=err or "Nothing to publish.", icon="ERROR")
        return
    col.label(text="Publish the following USD file(s)?", icon="QUESTION")
    col.separator()
    for line in lines:
        row = col.row()
        if line.startswith("  "):
            row.scale_y = 0.9
        row.label(text=line.strip())


def _execute_publish_usd(op: Operator, context: Context) -> set[str]:
    props = _pipeline_props(context)

    ok_list, jobs, objs, out_path, err_list = _plan_publish_jobs_from_list(context, props)
    if ok_list:
        if jobs is not None:
            return _finish_collection_publish_jobs(op, props, jobs)
        try:
            out_dir = os.path.dirname(str(out_path))
            if out_dir:
                Path(out_dir).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            _report_error(op, f"Failed to create output folder: {e}")
            return {"CANCELLED"}
        published_version = _version_folder(props)
        _run_usd_export(props, objs, out_path)
        props.publish_status_report = f"Created version {published_version}"
        if props.output_preset == "uv":
            sync_auto_publish_output(props)
        op.report({"INFO"}, f"Published USD: {out_path}")
        return {"FINISHED"}

    if err_list:
        _report_error(op, err_list)
        return {"CANCELLED"}

    if props.export_selected_collection:
        ok, jobs, err = _plan_selected_collection_publish_jobs(context, props)
        if not ok:
            _report_error(op, err)
            return {"CANCELLED"}
        return _finish_collection_publish_jobs(op, props, jobs)

    if props.export_collections_by_keyword:
        ok, jobs, err = _plan_collection_publish_jobs(props)
        if not ok:
            _report_error(op, err)
            return {"CANCELLED"}
        return _finish_collection_publish_jobs(op, props, jobs)

    ok, objs, err, out_path = _gather_publish_export(context)
    if not ok:
        _report_error(op, err)
        return {"CANCELLED"}

    try:
        out_dir = os.path.dirname(str(out_path))
        if out_dir:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _report_error(op, f"Failed to create output folder: {e}")
        return {"CANCELLED"}

    published_version = _version_folder(props)
    _run_usd_export(props, objs, out_path)
    props.publish_status_report = f"Created version {published_version}"
    if props.output_preset == "uv":
        sync_auto_publish_output(props)
    op.report({"INFO"}, f"Published USD: {out_path}")
    return {"FINISHED"}


class MONOFX_OT_prepare_transform(Operator):
    """Deprecated alias → Publish Asset."""

    bl_idname = "wm.mono_fx_usd_prepare_transform"
    bl_label = "Prepare Publish Transform (deprecated)"
    bl_options = {"REGISTER"}

    def execute(self, context: Context) -> set[str]:
        return bpy.ops.wm.mono_fx_usd_publish()  # type: ignore[return-value]


class MONOFX_OT_export_usd(Operator):
    """Deprecated alias → Publish Asset (hidden from UI)."""

    bl_idname = "wm.mono_fx_usd_export_only"
    bl_label = "Export USD File"
    bl_options = {"REGISTER"}

    def execute(self, context: Context) -> set[str]:
        return _execute_publish_usd(self, context)


class MONOFX_OT_restore(Operator):
    """Deprecated: publish no longer modifies the scene."""

    bl_idname = "wm.mono_fx_usd_restore"
    bl_label = "Restore (deprecated)"
    bl_options = {"REGISTER"}

    def execute(self, _context: Context) -> set[str]:
        self.report({"INFO"}, "Nothing to restore.")
        return {"FINISHED"}


class MONOFX_OT_publish_usd(Operator):
    bl_idname = "wm.mono_fx_usd_publish"
    bl_label = "Publish Asset"
    bl_options = {"REGISTER"}

    @classmethod
    def description(cls, context, properties) -> str:
        return "Publish enabled export collections to USD"

    def invoke(self, context: Context, event) -> set[str]:
        props = _pipeline_props(context)
        ok, _lines, err = _summarize_publish_plan(context, props)
        if not ok:
            _report_error(self, err or "Nothing to publish.")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self,
            width=440,
            confirm_text="Publish",
        )

    def draw(self, context: Context) -> None:
        _draw_publish_confirm_dialog(self.layout, context)

    def execute(self, context: Context) -> set[str]:
        return _execute_publish_usd(self, context)


class MONOFX_OT_open_publish_folder(Operator):
    bl_idname = "wm.mono_fx_usd_open_publish_folder"
    bl_label = "Open Publish Folder"
    bl_options = {"REGISTER"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        ok, folder, err = _resolve_publish_folder_path(props)
        if not ok:
            _report_error(self, err)
            return {"CANCELLED"}
        target = folder.resolve()
        if not target.is_dir():
            publish_root = target.parent
            if publish_root.is_dir():
                target = publish_root.resolve()
                self.report(
                    {"INFO"},
                    f"Version folder not created yet; opened publish root: {target}",
                )
            else:
                _report_error(self, f"Folder does not exist: {folder}")
                return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=str(target))
        return {"FINISHED"}


class MONOFX_OT_setup_legacy(Operator):
    """Backward-compatible alias for Create Asset Tree."""

    bl_idname = "wm.mono_fx_usd_setup_standard_hierarchy"
    bl_label = "Create Asset Tree"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        return bpy.ops.wm.mono_fx_create_hierarchy()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Publish version menu
# ---------------------------------------------------------------------------


class MONOFX_OT_set_publish_version(Operator):
    bl_idname = "wm.mono_fx_set_publish_version"
    bl_label = "Set Publish Version"
    bl_options = {"REGISTER", "UNDO"}

    version_num: IntProperty(name="Version", min=1, max=999, default=1)

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        props.publish_version = int(self.version_num)
        return {"FINISHED"}


class MONOFX_OT_refresh_publish_version(Operator):
    bl_idname = "wm.mono_fx_refresh_publish_version"
    bl_label = "Refresh Version"
    bl_description = "Re-scan publish folder and set the next version number"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Context) -> set[str]:
        props = _pipeline_props(context)
        scene_path, publish_root = _publish_root_for_props(props)
        if scene_path is None:
            _report_error(self, "Save the .blend file first.")
            return {"CANCELLED"}
        if publish_root is None:
            _report_error(
                self,
                "Save .blend under 01_assets/.../01_modelling/<task>/...",
            )
            return {"CANCELLED"}
        if props.output_preset == "uv":
            sync_auto_publish_output(props)
        else:
            global _SYNCING_PUBLISH_VERSION
            auto_num = _auto_publish_version_number(publish_root)
            _SYNCING_PUBLISH_VERSION = True
            try:
                props.publish_version = auto_num
            finally:
                _SYNCING_PUBLISH_VERSION = False
            _apply_publish_filepath_from_version(props)
        self.report({"INFO"}, f"Version set to {_version_folder(props)}")
        return {"FINISHED"}


class MONOFX_MT_publish_versions(Menu):
    bl_label = "Existing Versions"

    def draw(self, context: Context) -> None:
        layout = self.layout
        props = _pipeline_props(context)
        scene_path, publish_root = _publish_root_for_props(props)
        if scene_path is None:
            layout.label(text="Save .blend first")
            return
        if publish_root is None:
            layout.label(text="Invalid .blend path")
            return
        for num in publish_paths.list_version_numbers(publish_root):
            op = layout.operator(
                "wm.mono_fx_set_publish_version",
                text=f"v{num:03d}",
            )
            op.version_num = num
        nxt = _auto_publish_version_number(publish_root)
        op = layout.operator(
            "wm.mono_fx_set_publish_version",
            text=f"v{nxt:03d} (next)",
        )
        op.version_num = nxt


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------


def _draw_preparing(layout, context: Context) -> None:
    prefs = preferences.get_addon_prefs(context)
    if prefs is None:
        return
    props = _pipeline_props(context)

    box = layout.box()
    _tabs, body = ui_style.draw_vertical_tabs(box, prefs, "ui_prep_section")
    section = prefs.ui_prep_section

    if section == "HIERARCHY":
        body.prop(props, "asset_name", icon="OUTLINER_COLLECTION")
        ui_style.operator_row(
            body, "wm.mono_fx_create_hierarchy", text="Create Asset Tree", icon=ui_style.ICON_HIERARCHY
        )
        ui_style.operator_row(
            body, "wm.mono_fx_auto_parent_selected", text="Auto-Parent Selected", icon="LINKED"
        )
        pair = body.row(align=True)
        pair.operator(
            "wm.mono_fx_group_objects",
            text="Group Objects",
            icon="OUTLINER_OB_EMPTY",
        )
        pair.operator(
            "wm.mono_fx_collect_objects_to_collections",
            text="Collect Objects",
            icon="OUTLINER_COLLECTION",
        )
        ui_style.operator_row(
            body,
            "wm.mono_fx_select_hierarchy_tree",
            text="Select All Geo in Asset Tree",
            icon="OUTLINER_OB_MESH",
        )
    elif section == "NAMING":
        body.prop(props, "mesh_geo_prefix", icon="FONT_DATA")
        row = body.row(align=True)
        row.operator("wm.mono_fx_lowercase_selected", text="Lowercase", icon="SYNTAX_ON")
        row.operator("wm.mono_fx_add_geo_prefix", text="Geo Prefix", icon="OUTLINER_OB_MESH")
        if props.auto_parent_report:
            ui_style.status_label(body, props.auto_parent_report, ok=None)
    elif section == "TRANSFORMS":
        row = body.row(align=True)
        row.operator("wm.mono_fx_set_on_floor", text="Set on Floor", icon="SNAP_GRID")
        row.operator("wm.mono_fx_center_to_origin", text="Center to Origin", icon="PIVOT_CURSOR")
        align_row = body.row(align=True)
        align_row.operator(
            "wm.mono_fx_advanced_align",
            text="Advanced Align",
            icon="ORIENTATION_CURSOR",
        )
        align_row.operator(
            "wm.mono_fx_advanced_align_settings",
            text="",
            icon="PREFERENCES",
        )
        ui_style.operator_row(
            body,
            "wm.mono_fx_advanced_apply_transform",
            text="Advanced Apply Transform",
            icon="OBJECT_ORIGIN",
        )
    elif section == "CLEANUP":
        ui_style.prop_checkbox(body, props, "clean_apply_modifiers", text="Apply Modifiers")
        ui_style.prop_checkbox(body, props, "clean_apply_shape_keys", text="Apply Shape Keys")
        ui_style.prop_checkbox(body, props, "clean_vertex_groups", text="Clean Vertex Groups")
        ui_style.prop_checkbox(body, props, "clean_color_attributes", text="Clean Color Attributes")
        ui_style.prop_checkbox(body, props, "clean_custom_attributes", text="Clean Attributes")
        ui_style.prop_checkbox(body, props, "clean_uv_maps", text="Clean UV Maps")
        ui_style.operator_row(
            body, "wm.mono_fx_clean_mesh", text="Clean", icon="BRUSH_DATA", scale_y=1.15
        )
        if props.clean_mesh_report:
            ui_style.status_label(body, props.clean_mesh_report, ok=True)
    elif section == "MATERIALS":
        body.prop(props, "material_prefix", icon="MATERIAL")
        ui_style.prop_checkbox(body, props, "purge_orphan_materials")
        ui_style.operator_row(
            body, "wm.mono_fx_clear_materials_tree", text="Clear Materials", icon="MATERIAL_DATA"
        )
        ui_style.operator_row(
            body,
            "wm.mono_fx_assign_materials_from_groups",
            text="Assign from Groups",
            icon="NODE_MATERIAL",
        )
    elif section == "PRESET":
        body.template_list(
            "MONOFX_UL_preset_nodes",
            "",
            props,
            "preset_nodes",
            props,
            "preset_index",
        )
        row = body.row(align=True)
        row.operator("wm.mono_fx_preset_add_node", icon="ADD", text="")
        row.operator("wm.mono_fx_preset_remove_node", icon="REMOVE", text="")
        node = props.preset_nodes[props.preset_index] if props.preset_nodes else None
        if node:
            col = body.column(align=True)
            col.prop(node, "empty_name", icon="OUTLINER_OB_EMPTY")
            col.prop(node, "parent_name", icon="OUTLINER")
            col.prop(node, "match_keywords", icon="FILTER")
            ui_style.prop_checkbox(col, node, "is_leaf")
        body.prop(props, "preset_json_path", icon="FILE")
        row2 = body.row(align=True)
        row2.operator("wm.mono_fx_preset_load_default", text="Default", icon="PRESET")
        row2.operator("wm.mono_fx_preset_load_json", text="Load JSON", icon="IMPORT")
        ui_style.operator_row(body, "wm.mono_fx_preset_save_json", text="Save JSON", icon="FILE_TICK")


def _draw_geo_usd_publish_settings(layout: bpy.types.UILayout, props: MonoFXProperties) -> None:
    layout.label(text="Orientation", icon="WORLD")
    ui_style.prop_checkbox(layout, props, "convert_orientation")
    sub = layout.column(align=True)
    sub.enabled = props.convert_orientation
    sub.prop(props, "export_forward_axis", icon="ORIENTATION_GIMBAL")
    sub.prop(props, "export_up_axis", icon="ORIENTATION_GIMBAL")
    layout.prop(props, "convert_scene_units", icon="WORLD")
    layout.prop(props, "usd_root_prim_path", text="Root Prim Path")
    layout.separator()
    layout.label(text="Export Includes", icon="MESH_DATA")
    ui_style.prop_checkbox(layout, props, "export_uvmaps")
    ui_style.prop_checkbox(layout, props, "export_normals")
    ui_style.prop_checkbox(layout, props, "export_materials")
    mat_sub = layout.column(align=True)
    mat_sub.enabled = props.export_materials
    ui_style.prop_checkbox(mat_sub, props, "generate_preview_surface")
    ui_style.prop_checkbox(mat_sub, props, "generate_materialx_network")
    if props.export_materials:
        layout.label(
            text="Complex shaders? Bake in Model → USD Bake first.",
            icon="INFO",
        )
    ui_style.prop_checkbox(layout, props, "export_lights")
    ui_style.prop_checkbox(layout, props, "export_cameras")


class MONOFX_OT_geo_usd_publish_settings(Operator):
    """USD orientation and export include options for Geo USD publish."""

    bl_idname = "wm.mono_fx_geo_usd_publish_settings"
    bl_label = "Geo USD Settings"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def invoke(self, context: Context, event) -> set[str]:
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context: Context) -> None:
        _draw_geo_usd_publish_settings(self.layout, _pipeline_props(context))

    def execute(self, context: Context) -> set[str]:
        return {"FINISHED"}


def _draw_asset_publish(layout, context: Context) -> None:
    props = _pipeline_props(context)

    box = layout.box()
    body = box.column(align=True)

    body.prop(props, "output_preset", icon="FILE_HIDDEN")
    ver_row = body.row(align=True)
    ver_row.operator(
        "wm.mono_fx_refresh_publish_version",
        text="",
        icon="FILE_REFRESH",
    )
    ver_row.prop(props, "publish_version", text="Version")
    ver_row.menu("MONOFX_MT_publish_versions", text="", icon="TRIA_DOWN")
    body.prop(props, "output_filepath", icon="FILE")

    body.separator()

    collection_export = (
        props.export_collections_by_keyword or props.export_selected_collection
    )
    tree_row = body.row()
    tree_row.enabled = not collection_export
    ui_style.prop_checkbox(tree_row, props, "select_hierarchy")
    ui_style.prop_checkbox(body, props, "export_selected_collection")
    ui_style.prop_checkbox(body, props, "export_collections_by_keyword")
    kw_row = body.row()
    kw_row.enabled = props.export_collections_by_keyword
    kw_row.prop(props, "export_collection_keyword", text="Keyword")

    body.separator()
    geo_usd_publish_list.ensure_publish_export_refresh(context, props)
    enabled_count = geo_usd_publish_list.publish_export_enabled_count(props)
    total_count = geo_usd_publish_list.publish_export_object_count(props)
    if total_count == 0:
        pending_sig = (
            geo_usd_publish_list.compute_publish_export_signature(context, props)
            != props.geo_usd_publish_objects_signature
        )
        if pending_sig and not props.geo_usd_publish_list_locked:
            body.label(text="Updating export list…", icon="FILE_REFRESH")
    list_header = body.row(align=True)
    list_header.label(
        text=f"Export Collections ({enabled_count}/{total_count})",
        icon="OUTLINER_COLLECTION",
    )
    lock_row = list_header.row(align=True)
    lock_row.prop(
        props,
        "geo_usd_publish_list_locked",
        text="",
        icon="LOCKED" if props.geo_usd_publish_list_locked else "UNLOCKED",
        toggle=True,
        emboss=True,
    )
    list_header.operator(
        "wm.mono_fx_refresh_geo_usd_publish_list",
        text="",
        icon="FILE_REFRESH",
    )
    body.template_list(
        "MONOFX_UL_geo_usd_publish_objects",
        "",
        props,
        "geo_usd_publish_objects",
        props,
        "geo_usd_publish_object_index",
        rows=4,
    )
    list_ops = body.row(align=True)
    list_ops.operator(
        "wm.mono_fx_geo_usd_publish_list_add_selected",
        text="Add Selected",
        icon="ADD",
    )
    list_ops.operator(
        "wm.mono_fx_geo_usd_publish_list_remove",
        text="Remove",
        icon="REMOVE",
    )
    if props.geo_usd_publish_list_error:
        err_row = body.row()
        err_row.alert = True
        err_row.label(text=props.geo_usd_publish_list_error, icon="ERROR")
    elif enabled_count == 0:
        hint = body.row()
        hint.alert = True
        hint.label(
            text="Enable at least one collection to publish.",
            icon="ERROR",
        )
    elif total_count == 0:
        hint = body.row()
        hint.alert = True
        hint.label(text="No collections to export with current options.", icon="ERROR")

    if props.publish_status_report:
        ui_style.status_label(layout, props.publish_status_report, ok=True)
    ok_plan, summary, _rel_path, err_plan = _describe_publish_target(props)
    if ok_plan:
        layout.label(text=summary, icon="FILE_TICK")
    else:
        ui_style.status_label(layout, err_plan or "Path unavailable", ok=False)

    layout.separator()
    pub_row = layout.row(align=True)
    pub_row.scale_y = 1.55
    pub_main = pub_row.row(align=True)
    pub_main.enabled = enabled_count > 0 and not props.geo_usd_publish_list_error
    pub_main.operator(
        "wm.mono_fx_usd_publish",
        text="PUBLISH ASSET",
        icon=ui_style.ICON_PUBLISH,
    )
    pub_row.operator(
        "wm.mono_fx_usd_open_publish_folder",
        text="",
        icon=ui_style.ICON_FOLDER,
    )
    pub_settings = pub_row.row(align=True)
    pub_settings.scale_x = 1.15
    pub_settings.operator(
        "wm.mono_fx_geo_usd_publish_settings",
        text="",
        icon="PREFERENCES",
    )


def _draw_anim_publish(layout, context: Context) -> None:
    anim_usd_cache_ui.draw_anim_usd_cache_tab(layout, context)


class MONOFX_PT_model(Panel):
    bl_label = "Model"
    bl_idname = "MONOFX_PT_model"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MonoFX"
    bl_order = 0
    bl_description = "Geo preparation, USD bake, and Geo USD publish"

    def draw(self, context: Context) -> None:
        prefs = preferences.get_addon_prefs(context)
        if prefs is None:
            return
        layout = self.layout
        ui_style.draw_panel_tabs(layout, prefs, "ui_model_tab")
        layout.separator()
        if prefs.ui_model_tab == "PREP":
            _draw_preparing(layout, context)
        elif prefs.ui_model_tab == "BAKE":
            material_bake_ui.draw_material_bake_tab(layout, context)
        else:
            _draw_asset_publish(layout, context)


class MONOFX_PT_anim(Panel):
    bl_label = "Anim"
    bl_idname = "MONOFX_PT_anim"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MonoFX"
    bl_order = 1
    bl_description = "Animation tools, rig linking, and USD publish"

    def draw(self, context: Context) -> None:
        prefs = preferences.get_addon_prefs(context)
        if prefs is None:
            return
        layout = self.layout
        ui_style.draw_panel_tabs(layout, prefs, "ui_anim_tab")
        layout.separator()
        if prefs.ui_anim_tab == "TOOLS":
            anim_ui.draw_anim_tools_tab(layout, context)
        elif prefs.ui_anim_tab == "CAMERA":
            anim_ui.draw_camera_tools_tab(layout, context)
        elif prefs.ui_anim_tab == "LINK":
            rig_ui.draw_rig_link_tab(layout, context)
        elif prefs.ui_anim_tab == "USD":
            _draw_anim_publish(layout, context)


classes = (
    preferences.MonoFXPipelinePreferences,
    MonoFXPresetNodeItem,
    *rig_linking.RIG_PROPERTY_GROUP_CLASSES,
    MONOFX_UL_preset_nodes,
    *rig_linking.RIG_UI_LIST_CLASSES,
    *anim_usd_cache_asset_list.ANIM_USD_ASSET_PROPERTY_GROUP_CLASSES,
    *anim_usd_cache_asset_list.ANIM_USD_ASSET_UI_LIST_CLASSES,
    *geo_usd_publish_list.GEO_USD_PUBLISH_PROPERTY_GROUP_CLASSES,
    *geo_usd_publish_list.GEO_USD_PUBLISH_UI_LIST_CLASSES,
    *MATERIAL_BAKE_TARGET_PROPERTY_GROUP_CLASSES,
    *MATERIAL_BAKE_TARGET_UI_LIST_CLASSES,
    *MATERIAL_BAKE_TARGET_OPERATOR_CLASSES,
    MonoFXProperties,
    MONOFX_OT_create_hierarchy,
    MONOFX_OT_auto_parent,
    MONOFX_OT_select_hierarchy_tree,
    MONOFX_OT_group_objects,
    MONOFX_OT_collect_objects_to_collections,
    MONOFX_OT_lowercase_selected,
    MONOFX_OT_add_geo_prefix,
    MONOFX_OT_set_on_floor,
    MONOFX_OT_center_to_origin,
    MONOFX_OT_advanced_align_settings,
    MONOFX_OT_advanced_align,
    MONOFX_OT_advanced_apply_transform,
    MONOFX_OT_clean_mesh,
    MONOFX_OT_clear_materials,
    MONOFX_OT_assign_materials,
    MONOFX_OT_bake_materials_usd_settings,
    MONOFX_OT_bake_materials_usd,
    MONOFX_OT_material_bake_open_output_folder,
    MONOFX_OT_preset_load_default,
    MONOFX_OT_preset_load_json,
    MONOFX_OT_preset_save_json,
    MONOFX_OT_preset_add_node,
    MONOFX_OT_preset_remove_node,
    MONOFX_OT_set_publish_version,
    MONOFX_OT_refresh_publish_version,
    MONOFX_MT_publish_versions,
    MONOFX_OT_prepare_transform,
    MONOFX_OT_export_usd,
    MONOFX_OT_restore,
    MONOFX_OT_publish_usd,
    MONOFX_OT_geo_usd_publish_settings,
    *geo_usd_publish_list.GEO_USD_PUBLISH_OPERATOR_CLASSES,
    MONOFX_OT_open_publish_folder,
    MONOFX_OT_setup_legacy,
    *scene_version.SCENE_VERSION_CLASSES,
    *anim_usd_cache_ops.ANIM_USD_OPERATOR_CLASSES,
    *anim_ops.ANIM_OPERATOR_CLASSES,
    MONOFX_PT_model,
    MONOFX_PT_anim,
    *rig_linking.RIG_OPERATOR_CLASSES,
    *rig_ui.RIG_UI_CLASSES,
    *addon_updater.ADDON_UPDATER_OPERATOR_CLASSES,
)


def _iter_scenes_safe() -> List[bpy.types.Scene]:
    """During add-on enable/install bpy.data may be _RestrictData without .scenes."""
    try:
        return list(bpy.data.scenes)
    except (AttributeError, TypeError, RuntimeError):
        return []


def _mono_fx_sync_publish_from_scene(scenes: Optional[List[bpy.types.Scene]] = None) -> None:
    from . import anim_usd_cache_paths_ui as anim_path_ui

    for scene in scenes or _iter_scenes_safe():
        p = getattr(scene, "monofx_pipeline_blender_props", None)
        if p is None:
            continue
        sync_asset_name_from_scene(p)
        if p.output_preset == "uv":
            sync_auto_publish_output(p)
        if p.anim_usd_output_preset == "auto":
            anim_path_ui.sync_auto_anim_output(p)


def _mono_fx_sync_rig_cache(scenes: Optional[List[bpy.types.Scene]] = None) -> None:
    for scene in scenes or _iter_scenes_safe():
        p = getattr(scene, "monofx_pipeline_blender_props", None)
        if p is None:
            continue
        try:
            rig_linking.refresh_rig_cache(p)
        except Exception:
            pass


@persistent
def _mono_fx_on_load_post(_dummy=None) -> None:
    scenes = _iter_scenes_safe()
    if not scenes:
        return
    _sync_legacy_scene_props(scenes)
    _mono_fx_sync_publish_from_scene(scenes)
    _mono_fx_sync_rig_cache(scenes)


@persistent
def _mono_fx_on_save_post(_dummy=None) -> None:
    """Refresh publish paths on save; do not copy legacy props (stale tab defaults)."""
    _mono_fx_sync_publish_from_scene()
    _mono_fx_sync_rig_cache()


def _mono_fx_deferred_init(_dummy=None):
    scenes = _iter_scenes_safe()
    if not scenes:
        return None
    for scene in scenes:
        p = getattr(scene, "monofx_pipeline_blender_props", None)
        if p is not None:
            init_scene_preset_if_empty(p)
            sync_asset_name_from_scene(p)
    _mono_fx_on_load_post()
    return None


_LEGACY_SCENE_PROP_IDS = (
    "mono_fx_usd_export_props",
    "mono_fx_props",
)


def _sync_legacy_scene_props(scenes: Optional[List[bpy.types.Scene]] = None) -> None:
    """Copy settings from older RNA property ids into monofx_pipeline_blender_props."""
    for scene in scenes or _iter_scenes_safe():
        try:
            target = scene.monofx_pipeline_blender_props
        except (AttributeError, TypeError, RuntimeError):
            continue
        for legacy_id in _LEGACY_SCENE_PROP_IDS:
            legacy = getattr(scene, legacy_id, None)
            if legacy is None:
                continue
            for attr in (
                "output_filepath",
                "output_preset",
                "publish_version",
                "select_hierarchy",
                "allow_apply_on_armature",
                "convert_orientation",
                "export_forward_axis",
                "export_up_axis",
                "convert_scene_units",
                "export_uvmaps",
                "export_normals",
                "export_materials",
                "generate_preview_surface",
                "generate_materialx_network",
                "export_lights",
                "export_cameras",
                "material_prefix",
                "mesh_geo_prefix",
                "asset_name",
            ):
                if not hasattr(legacy, attr) or not hasattr(target, attr):
                    continue
                try:
                    val = getattr(legacy, attr)
                    if attr == "output_filepath" and getattr(target, attr, "") and not val:
                        continue
                    setattr(target, attr, val)
                except Exception:
                    pass


def _safe_register_class(cls) -> None:
    """Register RNA class; tolerate stale registration after add-on reload."""
    try:
        bpy.utils.unregister_class(cls)
    except RuntimeError:
        pass
    bpy.utils.register_class(cls)


def register() -> None:
    rig_ui.init_previews()
    for cls in classes:
        _safe_register_class(cls)
    bpy.types.VIEW3D_MT_object_context_menu.append(rig_ui.draw_rig_context_menu)
    bpy.types.Scene.monofx_pipeline_blender_props = PointerProperty(type=MonoFXProperties)
    # Legacy ids for .blend files from older add-on folder / property names.
    bpy.types.Scene.mono_fx_props = PointerProperty(type=MonoFXProperties)
    bpy.types.Scene.mono_fx_usd_export_props = PointerProperty(type=MonoFXProperties)
    if _mono_fx_on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_mono_fx_on_load_post)
    if _mono_fx_on_save_post not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_mono_fx_on_save_post)
    try:
        bpy.app.timers.register(_mono_fx_deferred_init, first_interval=0.01)
    except Exception:
        pass
    rig_linking.register_rig_listeners()
    geo_usd_publish_list.register_publish_list_listeners()
    anim_camera.register_aim_to_cursor_listeners()
    scene_version.register_scene_version_handlers()
    keymaps.register_keymaps(classes)
    keymaps.register_legacy_aliases(classes)


def unregister() -> None:
    keymaps.unregister_legacy_aliases()
    keymaps.unregister_keymaps()
    scene_version.unregister_scene_version_handlers()
    anim_camera.unregister_aim_to_cursor_listeners()
    geo_usd_publish_list.unregister_publish_list_listeners()
    rig_linking.unregister_rig_listeners()
    try:
        bpy.types.VIEW3D_MT_object_context_menu.remove(rig_ui.draw_rig_context_menu)
    except Exception:
        pass
    rig_ui.clear_previews()
    for handler, event in (
        (_mono_fx_on_load_post, bpy.app.handlers.load_post),
        (_mono_fx_on_save_post, bpy.app.handlers.save_post),
    ):
        if handler in event:
            event.remove(handler)
    for prop_id in (
        "monofx_pipeline_blender_props",
        "mono_fx_props",
        "mono_fx_usd_export_props",
    ):
        if hasattr(bpy.types.Scene, prop_id):
            delattr(bpy.types.Scene, prop_id)
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
