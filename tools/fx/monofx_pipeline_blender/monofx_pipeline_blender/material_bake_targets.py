"""
Bake target list for USD material bake (auto-refresh, Geo USD–style workflow).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Context, PropertyGroup, UIList, UILayout

from . import config
from .asset_hierarchy import (
    asset_collection_name_for,
    get_asset_hierarchy_from_collection,
    resolve_asset_hierarchy_from_object,
)
from .logic import iter_subobjects_recursive
from .material_bake import (
    BakeTarget,
    collect_bake_targets,
    count_baked_textures_on_disk,
    resolve_shader_name,
    resolve_texture_stem,
)
from .preparing import collect_geo_meshes_in_hierarchy

_logger = logging.getLogger("monofx.material_bake")

_STATUS_ITEMS = (
    ("PENDING", "Pending", "Textures not found on disk"),
    ("PARTIAL", "Partial", "Some expected textures exist"),
    ("DONE", "Done", "All expected textures exist on disk"),
    ("MISSING", "Missing", "Mesh or material no longer in the scene"),
)

_STATUS_ICONS = {
    "PENDING": "TIME",
    "PARTIAL": "SORTTIME",
    "DONE": "CHECKMARK",
    "MISSING": "CANCEL",
}

_material_bake_refresh_timer = None
_material_bake_refresh_scene_name: Optional[str] = None
_material_bake_refresh_pending = False


def _mesh_object_poll(_self, obj: bpy.types.Object) -> bool:
    return obj is not None and obj.type == "MESH"


def target_row_id(mesh_name: str, material_name: str, file_stem: str) -> str:
    return f"{mesh_name}|{material_name}|{file_stem}"


class MaterialBakeTargetItem(PropertyGroup):
    target_id: StringProperty(name="Target ID", default="")
    mesh: PointerProperty(name="Mesh", type=bpy.types.Object, poll=_mesh_object_poll)
    material_name: StringProperty(name="Material", default="")
    file_stem: StringProperty(name="Texture Stem", default="")
    shader_name: StringProperty(name="Shader Name", default="")
    display_name: StringProperty(name="Name", default="")
    detail: StringProperty(name="Detail", default="")
    output_preview: StringProperty(name="Output Preview", default="")
    enabled: BoolProperty(
        name="Enabled",
        description="Include this target when baking",
        default=True,
    )
    status: EnumProperty(
        name="Status",
        items=_STATUS_ITEMS,
        default="PENDING",
    )
    status_detail: StringProperty(name="Status Detail", default="")
    bake_restorable: BoolProperty(
        name="Can Restore Source",
        description="Per-mesh bake replaced the slot material; source can be reassigned",
        default=False,
    )
    restore_slot_index: IntProperty(
        name="Restore Slot",
        default=-1,
        min=-1,
    )
    baked_material_name: StringProperty(
        name="Baked Material",
        default="",
    )


@dataclass(frozen=True)
class MaterialBakeRestoreRecord:
    mesh_name: str
    slot_index: int
    source_material_name: str
    baked_material_name: str


def _status_display(item: MaterialBakeTargetItem) -> str:
    if item.status == "PENDING":
        return item.output_preview or "—"
    if item.status == "PARTIAL":
        return item.status_detail or "Partial"
    if item.status == "DONE":
        return "Done"
    if item.status == "MISSING":
        return "Missing"
    return item.status_detail or "—"


def _update_item_display_fields(item: MaterialBakeTargetItem) -> None:
    item.display_name = item.mesh.name if item.mesh else "?"
    tex = f"{item.file_stem}_*" if item.file_stem else ""
    shd = item.shader_name or item.material_name or ""
    parts = [part for part in (tex, shd) if part]
    item.detail = " · ".join(parts)
    item.output_preview = f"{item.file_stem}_BaseColor.png" if item.file_stem else ""


def collect_meshes_from_selection(
    selected: Sequence[bpy.types.Object],
) -> list[bpy.types.Object]:
    """Meshes from selection: direct mesh picks plus mesh descendants of other objects."""
    out: list[bpy.types.Object] = []
    seen: set[str] = set()

    def add_mesh(mesh: bpy.types.Object) -> None:
        if mesh is None or mesh.type != "MESH":
            return
        if mesh.name in seen:
            return
        seen.add(mesh.name)
        out.append(mesh)

    for obj in selected or []:
        if obj is None:
            continue
        if obj.type == "MESH":
            add_mesh(obj)
            continue
        for sub in iter_subobjects_recursive(obj):
            if sub.type == "MESH":
                add_mesh(sub)

    return out


def collect_geo_meshes_for_bake(
    context: Context,
    props,
) -> tuple[bool, list[bpy.types.Object], str]:
    hierarchy = None
    active = context.view_layer.objects.active
    if active is not None:
        hierarchy = resolve_asset_hierarchy_from_object(active)
    if hierarchy is None:
        for obj in context.selected_objects or []:
            hierarchy = resolve_asset_hierarchy_from_object(obj)
            if hierarchy is not None:
                break
    if hierarchy is None:
        slug = (props.asset_name or "Asset").strip()
        col = bpy.data.collections.get(asset_collection_name_for(slug))
        if col is not None:
            hierarchy = get_asset_hierarchy_from_collection(col)
    if hierarchy is None:
        return False, [], "No Geo_<Asset> collection found. Run Create Asset Tree first."
    meshes = collect_geo_meshes_in_hierarchy(hierarchy)
    if not meshes:
        return False, [], "No mesh objects in asset tree."
    return True, meshes, ""


def collect_meshes_by_name_keyword(
    context: Context,
    keyword: str,
) -> tuple[list[bpy.types.Object], str]:
    """Meshes in the view layer whose names match *keyword* (not limited to Geo tree)."""
    token = (keyword or "").strip().lower()
    label = token or "all"
    meshes: list[bpy.types.Object] = []
    seen: set[str] = set()
    for obj in context.view_layer.objects:
        if obj.type != "MESH" or obj.name in seen:
            continue
        if token and token not in obj.name.lower():
            continue
        seen.add(obj.name)
        meshes.append(obj)
    if not meshes:
        if token:
            return [], f"No meshes matching '{label}' in the scene."
        return [], "No mesh objects in the scene."
    return meshes, ""


def plan_material_bake_meshes(
    context: Context,
    props,
) -> tuple[list[bpy.types.Object], str]:
    if props.material_bake_selected_only:
        meshes = collect_meshes_from_selection(context.selected_objects or [])
        if not meshes:
            return [], "No mesh objects in selection."
        return meshes, ""

    if props.material_bake_keyword_filter:
        meshes, err = collect_meshes_by_name_keyword(
            context,
            props.material_bake_mesh_keyword,
        )
        if err:
            return [], err
        return meshes, ""

    if not props.material_bake_use_geo_tree:
        return [], "Enable Geo Asset Tree or choose Selected / Keyword Filter."

    ok, meshes, err = collect_geo_meshes_for_bake(context, props)
    if not ok:
        return [], err
    return meshes, ""


def compute_material_bake_signature(context: Context, props) -> str:
    """Lightweight scene signature for deferred bake-target refresh."""
    meshes, _ = plan_material_bake_meshes(context, props)
    mesh_part = "|".join(
        sorted(f"{mesh.name}:{_mesh_primary_material_name(mesh)}" for mesh in meshes)
    )
    sel = ",".join(
        sorted(obj.name for obj in (context.selected_objects or []) if obj.type == "MESH")
    )
    active = context.view_layer.objects.active
    active_name = active.name if active is not None else ""
    return (
        f"asset={props.asset_name}#"
        f"tree={int(props.material_bake_use_geo_tree)}#"
        f"selonly={int(props.material_bake_selected_only)}#"
        f"kwmode={int(props.material_bake_keyword_filter)}#"
        f"kw={props.material_bake_mesh_keyword}#"
        f"scope={props.material_bake_scope}#"
        f"objs={sel}#act={active_name}#"
        f"{mesh_part}#"
        f"tex={props.material_bake_texture_stem_mode}:{props.material_bake_texture_stem_template}#"
        f"shd={props.material_bake_shader_name_mode}:{props.material_bake_shader_name_template}#"
        f"bc={int(props.material_bake_pass_base_color)}"
        f"r={int(props.material_bake_pass_roughness)}"
        f"n={int(props.material_bake_pass_normal)}"
        f"ao={int(props.material_bake_pass_ao)}"
        f"op={int(props.material_bake_pass_opacity)}#"
        f"fmt={props.material_bake_image_format}#"
        f"out={props.material_bake_output_mode}:{props.material_bake_output_dir}"
    )


def _mesh_primary_material_name(mesh: bpy.types.Object) -> str:
    for slot in mesh.material_slots:
        if slot.material is not None:
            return slot.material.name
    mat = mesh.active_material
    return mat.name if mat is not None else "-"


def _tag_material_bake_panel_redraw(context: Optional[Context] = None) -> None:
    if context is not None and getattr(context, "area", None) is not None:
        context.area.tag_redraw()
        return
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            for region in area.regions:
                if region.type == "UI":
                    region.tag_redraw()


def refresh_target_item_names(item: MaterialBakeTargetItem, props) -> None:
    mesh = item.mesh
    mat_name = (item.material_name or "").strip()
    if mesh is None or mesh.type != "MESH" or not mat_name:
        return
    item.file_stem = resolve_texture_stem(
        mat_name,
        mesh.name,
        mode=props.material_bake_texture_stem_mode,
        material_prefix="",
        custom_template=props.material_bake_texture_stem_template,
    )
    item.shader_name = resolve_shader_name(
        mat_name,
        mesh.name,
        item.file_stem,
        mode=props.material_bake_shader_name_mode,
        material_prefix="",
        custom_template=props.material_bake_shader_name_template,
    )
    item.target_id = target_row_id(mesh.name, mat_name, item.file_stem)
    _update_item_display_fields(item)


def refresh_all_target_item_names(props) -> None:
    for item in props.material_bake_targets:
        refresh_target_item_names(item, props)


def _resolve_material(material_name: str) -> Optional[bpy.types.Material]:
    name = (material_name or "").strip()
    if not name:
        return None
    return bpy.data.materials.get(name)


def item_to_bake_target(item: MaterialBakeTargetItem) -> Optional[BakeTarget]:
    mesh = item.mesh
    if mesh is None or mesh.type != "MESH":
        return None
    mat = _resolve_material(item.material_name)
    if mat is None:
        return None
    stem = (item.file_stem or "").strip() or mat.name
    return BakeTarget(material=mat, meshes=[mesh], file_stem=stem)


def enabled_bake_targets(props) -> list[BakeTarget]:
    targets: list[BakeTarget] = []
    for item in props.material_bake_targets:
        if not item.enabled:
            continue
        target = item_to_bake_target(item)
        if target is not None:
            targets.append(target)
    return targets


def enabled_bake_target_count(props) -> int:
    return sum(1 for item in props.material_bake_targets if item.enabled)


def restorable_bake_target_count(props) -> int:
    return sum(1 for item in props.material_bake_targets if item.bake_restorable)


def apply_bake_restore_records(
    props,
    records: Sequence[MaterialBakeRestoreRecord],
) -> None:
    by_key = {
        (record.mesh_name, record.source_material_name): record for record in records
    }
    for item in props.material_bake_targets:
        mesh = item.mesh
        if mesh is None:
            continue
        record = by_key.get((mesh.name, item.material_name))
        if record is None:
            continue
        item.bake_restorable = True
        item.restore_slot_index = record.slot_index
        item.baked_material_name = record.baked_material_name


def restore_source_materials(props) -> tuple[int, list[str]]:
    """Reassign baked mesh slots back to source materials. Returns count and warnings."""
    restored = 0
    warnings: list[str] = []
    for item in props.material_bake_targets:
        if not item.bake_restorable:
            continue
        mesh = item.mesh
        if mesh is None or mesh.type != "MESH":
            item.bake_restorable = False
            warnings.append(f"{item.display_name or '?'}: mesh missing.")
            continue
        source = bpy.data.materials.get((item.material_name or "").strip())
        if source is None:
            warnings.append(f"{mesh.name}: source material '{item.material_name}' not found.")
            continue
        slot_index = int(item.restore_slot_index)
        if slot_index < 0 or slot_index >= len(mesh.material_slots):
            warnings.append(f"{mesh.name}: material slot {slot_index} unavailable.")
            continue
        baked_mat = mesh.material_slots[slot_index].material
        mesh.material_slots[slot_index].material = source
        baked_name = (item.baked_material_name or "").strip()
        if baked_mat is not None and baked_mat != source:
            if baked_name and baked_mat.name != baked_name:
                pass
            elif baked_mat.users == 0:
                try:
                    bpy.data.materials.remove(baked_mat)
                except Exception:
                    pass
        item.bake_restorable = False
        item.baked_material_name = ""
        item.restore_slot_index = -1
        restored += 1
    return restored, warnings


def material_bake_action_label(props) -> str:
    total = len(props.material_bake_targets)
    count = enabled_bake_target_count(props)
    if count <= 0:
        if total <= 0:
            return "Bake Enabled Targets"
        return f"Bake (0/{total} enabled)"
    if count == 1:
        item = next(i for i in props.material_bake_targets if i.enabled)
        return f"Bake «{item.display_name or item.file_stem or 'target'}»"
    return f"Bake {count} Targets"


def material_bake_run_plan(props) -> dict[str, object]:
    """Bake workload summary for confirmation UI."""
    target_count = enabled_bake_target_count(props)
    pass_labels: list[str] = []
    steps_per_target = 0
    if props.material_bake_pass_base_color:
        pass_labels.append("Base Color")
        steps_per_target += 1
    if props.material_bake_pass_roughness:
        pass_labels.append("Roughness")
        steps_per_target += 1
    if props.material_bake_pass_normal:
        pass_labels.append("Normal")
        steps_per_target += 1
    if props.material_bake_pass_ao:
        pass_labels.append("AO")
        steps_per_target += 1
    if props.material_bake_pass_opacity:
        pass_labels.append("Opacity")
        if props.material_bake_pass_base_color:
            steps_per_target += 1
    return {
        "target_count": target_count,
        "pass_labels": pass_labels,
        "steps_per_target": steps_per_target,
        "total_steps": target_count * steps_per_target,
        "resolution": props.material_bake_resolution,
    }


def _snapshot_list_state(props) -> dict[str, dict[str, object]]:
    return {
        item.target_id: {
            "enabled": bool(item.enabled),
            "status": item.status,
            "status_detail": item.status_detail,
            "bake_restorable": bool(item.bake_restorable),
            "restore_slot_index": int(item.restore_slot_index),
            "baked_material_name": item.baked_material_name or "",
        }
        for item in props.material_bake_targets
        if item.target_id
    }


def _add_target_item(
    props,
    target: BakeTarget,
    *,
    prev_state: dict[str, dict[str, object]],
) -> MaterialBakeTargetItem:
    mesh = target.meshes[0]
    item = props.material_bake_targets.add()
    item.mesh = mesh
    item.material_name = target.material.name
    refresh_target_item_names(item, props)
    prev = prev_state.get(item.target_id)
    if prev is not None:
        item.enabled = bool(prev.get("enabled", True))
        item.status = str(prev.get("status", "PENDING"))
        item.status_detail = str(prev.get("status_detail", ""))
        item.bake_restorable = bool(prev.get("bake_restorable", False))
        item.restore_slot_index = int(prev.get("restore_slot_index", -1))
        item.baked_material_name = str(prev.get("baked_material_name", ""))
    else:
        item.enabled = True
        item.status = "PENDING"
        item.status_detail = ""
        item.bake_restorable = False
        item.restore_slot_index = -1
        item.baked_material_name = ""
    return item


def _existing_target_ids(props) -> set[str]:
    return {item.target_id for item in props.material_bake_targets if item.target_id}


def add_selected_meshes_to_list(context: Context, props) -> tuple[int, str]:
    meshes = collect_meshes_from_selection(context.selected_objects or [])
    if not meshes:
        return 0, "No mesh objects in selection."

    existing = _existing_target_ids(props)
    prev_state = _snapshot_list_state(props)
    added = 0
    targets = collect_bake_targets(
        meshes,
        scope=props.material_bake_scope,
        material_prefix="",
    )
    for target in targets:
        mesh = target.meshes[0]
        stem = resolve_texture_stem(
            target.material.name,
            mesh.name,
            mode=props.material_bake_texture_stem_mode,
            material_prefix="",
            custom_template=props.material_bake_texture_stem_template,
        )
        row_id = target_row_id(mesh.name, target.material.name, stem)
        if row_id in existing:
            continue
        _add_target_item(props, target, prev_state=prev_state)
        existing.add(row_id)
        added += 1
    if added <= 0:
        return 0, "Selected mesh(es) are already in the list or have no material."
    return added, ""


def remove_material_bake_targets(props, indices: Sequence[int]) -> int:
    removed = 0
    for index in sorted({int(i) for i in indices}, reverse=True):
        if index < 0 or index >= len(props.material_bake_targets):
            continue
        props.material_bake_targets.remove(index)
        removed += 1
    props.material_bake_target_index = min(
        props.material_bake_target_index,
        max(0, len(props.material_bake_targets) - 1),
    )
    return removed


def _refresh_material_bake_targets_impl(
    context: Context,
    props,
    *,
    output_dir: Optional[Path] = None,
    force: bool = False,
) -> None:
    signature = compute_material_bake_signature(context, props)
    if not force and signature == props.material_bake_targets_signature:
        return

    props.material_bake_targets_signature = signature
    prev_state = _snapshot_list_state(props)
    mesh_filter = (
        props.material_bake_selected_only or props.material_bake_keyword_filter
    )
    extra_rows = [
        (
            item.target_id,
            item.mesh.name if item.mesh else "",
            item.material_name,
            bool(item.enabled),
        )
        for item in props.material_bake_targets
        if item.target_id
    ]

    meshes, err = plan_material_bake_meshes(context, props)
    props.material_bake_list_error = err
    props.material_bake_targets.clear()
    props.material_bake_target_index = 0

    planned_ids: set[str] = set()
    if meshes:
        targets = collect_bake_targets(
            meshes,
            scope=props.material_bake_scope,
            material_prefix="",
        )
        for target in targets:
            item = _add_target_item(props, target, prev_state=prev_state)
            if item.target_id:
                planned_ids.add(item.target_id)

    if not mesh_filter:
        for row_id, mesh_name, mat_name, enabled in extra_rows:
            if row_id in planned_ids:
                continue
            mesh = bpy.data.objects.get(mesh_name)
            mat = bpy.data.materials.get(mat_name)
            if mesh is None or mesh.type != "MESH" or mat is None:
                continue
            target = BakeTarget(material=mat, meshes=[mesh], file_stem="")
            item = _add_target_item(props, target, prev_state=prev_state)
            item.enabled = enabled
            if item.target_id:
                planned_ids.add(item.target_id)

    if output_dir is not None:
        for item in props.material_bake_targets:
            update_item_bake_status(
                item,
                output_dir,
                pass_base_color=props.material_bake_pass_base_color,
                pass_roughness=props.material_bake_pass_roughness,
                pass_normal=props.material_bake_pass_normal,
                pass_ao=props.material_bake_pass_ao,
                pass_opacity=props.material_bake_pass_opacity,
                image_format=props.material_bake_image_format,
            )
            _update_item_display_fields(item)


def schedule_material_bake_targets_refresh(context: Context) -> None:
    global _material_bake_refresh_timer, _material_bake_refresh_scene_name, _material_bake_refresh_pending

    if _material_bake_refresh_pending:
        return

    _material_bake_refresh_scene_name = context.scene.name
    _material_bake_refresh_pending = True

    def _run() -> None:
        global _material_bake_refresh_timer, _material_bake_refresh_pending
        _material_bake_refresh_timer = None
        _material_bake_refresh_pending = False
        scene = bpy.data.scenes.get(_material_bake_refresh_scene_name or "")
        if scene is None:
            return None
        props = getattr(scene, "monofx_pipeline_blender_props", None)
        if props is None:
            return None
        try:
            _refresh_material_bake_targets_impl(bpy.context, props)
        except Exception as exc:
            _logger.exception("material bake targets refresh failed: %s", exc)
        _tag_material_bake_panel_redraw(bpy.context)
        return None

    if _material_bake_refresh_timer is not None:
        try:
            bpy.app.timers.unregister(_material_bake_refresh_timer)
        except Exception:
            pass
    _material_bake_refresh_timer = bpy.app.timers.register(_run, first_interval=0.15)


def ensure_material_bake_targets_refresh(context: Context, props) -> None:
    """Read-only in draw: schedule refresh when geo targets changed."""
    if props.material_bake_list_locked or props.material_bake_running:
        return
    signature = compute_material_bake_signature(context, props)
    if signature == props.material_bake_targets_signature:
        return
    schedule_material_bake_targets_refresh(context)


def refresh_material_bake_targets(
    context: Context,
    props,
    *,
    output_dir: Optional[Path] = None,
    force: bool = False,
) -> None:
    """Immediate refresh — use from operators, not panel draw()."""
    _refresh_material_bake_targets_impl(context, props, output_dir=output_dir, force=force)


def invalidate_material_bake_targets_signature(props) -> None:
    props.material_bake_targets_signature = ""


def update_item_bake_status(
    item: MaterialBakeTargetItem,
    output_dir: Optional[Path],
    *,
    pass_base_color: bool,
    pass_roughness: bool,
    pass_normal: bool,
    pass_ao: bool,
    pass_opacity: bool,
    image_format: str,
) -> None:
    if item.mesh is None or item.mesh.type != "MESH":
        item.status = "MISSING"
        item.status_detail = "Mesh missing"
        return
    if _resolve_material(item.material_name) is None:
        item.status = "MISSING"
        item.status_detail = "Material missing"
        return
    if output_dir is None or not str(output_dir).strip():
        item.status = "PENDING"
        item.status_detail = ""
        return

    stem = (item.file_stem or "").strip() or item.material_name
    found, total = count_baked_textures_on_disk(
        output_dir,
        stem,
        pass_base_color=pass_base_color,
        pass_roughness=pass_roughness,
        pass_normal=pass_normal,
        pass_ao=pass_ao,
        pass_opacity=pass_opacity,
        image_format=image_format,
    )
    if total <= 0:
        item.status = "PENDING"
        item.status_detail = ""
    elif found >= total:
        item.status = "DONE"
        item.status_detail = f"{found}/{total}"
    elif found > 0:
        item.status = "PARTIAL"
        item.status_detail = f"{found}/{total}"
    else:
        item.status = "PENDING"
        item.status_detail = ""


def update_all_bake_statuses(
    props,
    output_dir: Optional[Path],
    *,
    pass_base_color: bool,
    pass_roughness: bool,
    pass_normal: bool,
    pass_ao: bool,
    pass_opacity: bool,
    image_format: str,
) -> None:
    refresh_all_target_item_names(props)
    for item in props.material_bake_targets:
        update_item_bake_status(
            item,
            output_dir,
            pass_base_color=pass_base_color,
            pass_roughness=pass_roughness,
            pass_normal=pass_normal,
            pass_ao=pass_ao,
            pass_opacity=pass_opacity,
            image_format=image_format,
        )
        _update_item_display_fields(item)


class MONOFX_UL_material_bake_targets(UIList):
    bl_idname = "MONOFX_UL_material_bake_targets"

    def draw_item(
        self,
        context: Context,
        layout: UILayout,
        data,
        item: MaterialBakeTargetItem,
        icon,
        active_data,
        active_propname,
        index: int,
    ) -> None:
        del context, data, icon, active_data, active_propname, index
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.prop(item, "enabled", text="")
            body = row.row(align=True)
            body.enabled = item.enabled
            left = body.split(factor=0.58, align=True)
            left_col = left.column(align=True)
            left_col.label(text=item.display_name or "?", icon="OUTLINER_OB_MESH")
            if item.detail:
                detail_row = left_col.row()
                detail_row.scale_y = 0.9
                detail_row.label(text=item.detail)

            right = body.row(align=True)
            right.alignment = "RIGHT"
            status_icon = _STATUS_ICONS.get(item.status, "DOT")
            right.label(text=_status_display(item), icon=status_icon)
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.display_name or "?", icon="OUTLINER_OB_MESH")


MATERIAL_BAKE_TARGET_PROPERTY_GROUP_CLASSES = (MaterialBakeTargetItem,)
MATERIAL_BAKE_TARGET_UI_LIST_CLASSES = (MONOFX_UL_material_bake_targets,)


class MONOFX_OT_refresh_material_bake_list(bpy.types.Operator):
    """Refresh the bake target list from the current scene and options."""

    bl_idname = "wm.mono_fx_refresh_material_bake_list"
    bl_label = "Refresh Bake List"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        refresh_material_bake_targets(context, props, force=True)
        enabled = enabled_bake_target_count(props)
        total = len(props.material_bake_targets)
        if props.material_bake_list_error and total == 0:
            self.report({"WARNING"}, props.material_bake_list_error)
        else:
            self.report({"INFO"}, f"Bake list: {enabled}/{total} target(s) enabled.")
        return {"FINISHED"}


class MONOFX_OT_material_bake_add_selected(bpy.types.Operator):
    """Add selected mesh(es) to the bake target list."""

    bl_idname = "wm.mono_fx_material_bake_add_selected"
    bl_label = "Add Selected"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        added, err = add_selected_meshes_to_list(context, props)
        if added <= 0:
            self.report({"WARNING"}, err or "Nothing added.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Added {added} target(s).")
        return {"FINISHED"}


class MONOFX_OT_material_bake_remove(bpy.types.Operator):
    """Remove the active row from the bake target list."""

    bl_idname = "wm.mono_fx_material_bake_remove"
    bl_label = "Remove"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return len(props.material_bake_targets) > 0

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        removed = remove_material_bake_targets(props, [props.material_bake_target_index])
        if removed <= 0:
            self.report({"WARNING"}, "No rows to remove.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Removed {removed} target(s).")
        return {"FINISHED"}


class MONOFX_OT_material_bake_restore_sources(bpy.types.Operator):
    """Reassign mesh slots to source materials from before the last per-mesh bake."""

    bl_idname = "wm.mono_fx_material_bake_restore_sources"
    bl_label = "Restore Source Materials"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        props = context.scene.monofx_pipeline_blender_props
        return restorable_bake_target_count(props) > 0 and not props.material_bake_running

    @classmethod
    def description(cls, context, properties) -> str:
        return cls.__doc__ or cls.bl_label

    def execute(self, context: Context) -> set[str]:
        props = context.scene.monofx_pipeline_blender_props
        restored, warnings = restore_source_materials(props)
        if restored <= 0:
            self.report(
                {"ERROR"},
                warnings[0] if warnings else "Nothing to restore.",
            )
            return {"CANCELLED"}
        if warnings:
            self.report({"WARNING"}, "; ".join(warnings[:3]))
        self.report({"INFO"}, f"Restored source material on {restored} mesh slot(s).")
        return {"FINISHED"}


MATERIAL_BAKE_TARGET_OPERATOR_CLASSES = (
    MONOFX_OT_refresh_material_bake_list,
    MONOFX_OT_material_bake_add_selected,
    MONOFX_OT_material_bake_remove,
    MONOFX_OT_material_bake_restore_sources,
)
