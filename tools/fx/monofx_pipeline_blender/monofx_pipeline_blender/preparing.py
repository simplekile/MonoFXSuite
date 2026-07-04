"""
Preparing Asset operators logic: naming, auto-parent, floor, transforms, materials.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import bpy

from . import config
from .asset_hierarchy import (
    AssetHierarchy,
    collect_leaf_grp_empties,
    ensure_hierarchy_from_preset,
    move_objects_to_collection,
    move_selection_into_asset_collection,
    parent_meshes_under_empty,
    resolve_asset_hierarchy_from_object,
)
from .logic import (
    create_empty_object,
    ensure_collection_for_new_objects,
    is_descendant_of,
    iter_subobjects_recursive,
)
from .materials import (
    assign_materials_from_grp_tree,
    clear_materials_on_objects,
    ensure_mesh_geo_prefix,
)
from .preset import HierarchyPreset, parse_keywords, preset_from_scene_nodes


_TRAILING_DIGITS_RE = re.compile(r"_(\d+)$")


@dataclass
class AutoParentResult:
    assigned: List[str]
    skipped: List[str]
    ambiguous: List[str]
    unassigned: List[str]


def normalize_mesh_name_for_match(name: str, mesh_geo_prefix: str) -> str:
    n = name.lower()
    prefixes = []
    if mesh_geo_prefix:
        prefixes.append(mesh_geo_prefix.lower())
    prefixes.extend(("geo_", "geo"))
    seen: set[str] = set()
    for pre in prefixes:
        if not pre or pre in seen:
            continue
        seen.add(pre)
        if n.startswith(pre):
            n = n[len(pre) :]
            break
    n = _TRAILING_DIGITS_RE.sub("", n)
    return n


def global_auto_parent_leaf(normalized: str) -> Optional[str]:
    if "hair_mask" in normalized or "hair_ring" in normalized:
        return config.ACCESSORY_GRP_NAME
    if "_access" in normalized or normalized.endswith("_access"):
        return config.ACCESSORY_GRP_NAME
    if "arm_access" in normalized or "armextra_access" in normalized:
        return config.ACCESSORY_GRP_NAME
    if "arm_extra" in normalized or "armextra" in normalized:
        return config.BODY_GRP_NAME
    return None


def match_leaf_for_mesh(
    normalized: str,
    leaves: List[Tuple[object, bpy.types.Object]],
) -> Tuple[Optional[bpy.types.Object], Optional[str]]:
    forced = global_auto_parent_leaf(normalized)
    if forced:
        for node, obj in leaves:
            if node.name == forced:
                return obj, f"rule:{forced}"

    best_len = 0
    best_objs: List[bpy.types.Object] = []
    best_kw = ""

    for node, obj in leaves:
        for kw in parse_keywords(node.match_keywords):
            if kw in normalized:
                if len(kw) > best_len:
                    best_len = len(kw)
                    best_objs = [obj]
                    best_kw = kw
                elif len(kw) == best_len and best_len > 0:
                    if obj not in best_objs:
                        best_objs.append(obj)

    if best_len == 0:
        return None, None
    if len(best_objs) > 1:
        return None, f"ambiguous:{best_kw}"
    return best_objs[0], best_kw


def run_auto_parent(
    context: bpy.types.Context,
    *,
    props,
    selected_only: bool = True,
) -> AutoParentResult:
    preset = preset_from_scene_nodes(props)
    hierarchy: Optional[AssetHierarchy] = None
    if context.view_layer.objects.active:
        hierarchy = resolve_asset_hierarchy_from_object(context.view_layer.objects.active)
    if hierarchy is None:
        for obj in context.selected_objects or []:
            hierarchy = resolve_asset_hierarchy_from_object(obj)
            if hierarchy:
                break

    result = AutoParentResult([], [], [], [])
    if hierarchy is None:
        result.unassigned = [o.name for o in (context.selected_objects or [])]
        return result

    leaves = collect_leaf_grp_empties(hierarchy, preset)
    if not leaves:
        return result

    mesh_geo_prefix = getattr(props, "mesh_geo_prefix", config.MESH_GEO_PREFIX)

    candidates: List[bpy.types.Object] = []
    if selected_only:
        candidates = [o for o in context.selected_objects or [] if o.type == "MESH"]
    else:
        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            if is_descendant_of(obj, hierarchy.geo_container):
                continue
            candidates.append(obj)

    for mesh in candidates:
        norm = normalize_mesh_name_for_match(mesh.name, mesh_geo_prefix)
        target, info = match_leaf_for_mesh(norm, leaves)
        if info and info.startswith("ambiguous:"):
            result.ambiguous.append(mesh.name)
            continue
        if target is None:
            result.unassigned.append(mesh.name)
            continue
        if mesh.parent == target:
            result.skipped.append(mesh.name)
            continue
        parent_meshes_under_empty(mesh, target)
        result.assigned.append(mesh.name)

    return result


def _mesh_world_corners(mesh: bpy.types.Object, depsgraph) -> List:
    import mathutils

    try:
        eval_obj = mesh.evaluated_get(depsgraph)
        return [eval_obj.matrix_world @ mathutils.Vector(c) for c in eval_obj.bound_box]
    except Exception:
        return []


def _mesh_world_min_z(mesh: bpy.types.Object, depsgraph) -> Optional[float]:
    corners = _mesh_world_corners(mesh, depsgraph)
    if not corners:
        return None
    return min(co.z for co in corners)


def _union_bbox_bounds(
    meshes: Iterable[bpy.types.Object], depsgraph
) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    corners: List = []
    for mesh in meshes:
        corners.extend(_mesh_world_corners(mesh, depsgraph))
    if not corners:
        return None
    return (
        (min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)),
        (max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)),
    )


def _union_bbox_center(meshes: Iterable[bpy.types.Object], depsgraph) -> Optional[Tuple[float, float, float]]:
    bounds = _union_bbox_bounds(meshes, depsgraph)
    if bounds is None:
        return None
    mn, mx = bounds
    return (
        (mn[0] + mx[0]) * 0.5,
        (mn[1] + mx[1]) * 0.5,
        (mn[2] + mx[2]) * 0.5,
    )


def _bbox_axis_value(min_v: float, max_v: float, mode: str) -> float:
    key = (mode or "CENTER").upper()
    if key == "MIN":
        return min_v
    if key == "MAX":
        return max_v
    return (min_v + max_v) * 0.5


def _advanced_align_delta(
    meshes: Iterable[bpy.types.Object],
    depsgraph,
    *,
    axis_x: str,
    axis_y: str,
    axis_z: str,
    target: Tuple[float, float, float],
    enable_x: bool = True,
    enable_y: bool = True,
    enable_z: bool = True,
) -> Optional[Tuple[float, float, float]]:
    bounds = _union_bbox_bounds(meshes, depsgraph)
    if bounds is None:
        return None
    mn, mx = bounds
    modes = (axis_x, axis_y, axis_z)
    enables = (enable_x, enable_y, enable_z)
    delta: List[float] = []
    for i in range(3):
        if not enables[i]:
            delta.append(0.0)
            continue
        current = _bbox_axis_value(mn[i], mx[i], modes[i])
        delta.append(target[i] - current)
    return tuple(delta)


def _align_meshes_per_object(
    meshes: Iterable[bpy.types.Object],
    depsgraph,
    *,
    axis_x: str,
    axis_y: str,
    axis_z: str,
    target: Tuple[float, float, float],
    enable_x: bool = True,
    enable_y: bool = True,
    enable_z: bool = True,
) -> int:
    """Align each mesh independently; return how many were moved."""
    aligned = 0
    for mesh in meshes:
        delta = _advanced_align_delta(
            [mesh],
            depsgraph,
            axis_x=axis_x,
            axis_y=axis_y,
            axis_z=axis_z,
            target=target,
            enable_x=enable_x,
            enable_y=enable_y,
            enable_z=enable_z,
        )
        if delta is None:
            continue
        _apply_world_translation([mesh], delta)
        aligned += 1
    return aligned


def _apply_world_translation(
    objects: Iterable[bpy.types.Object], delta: Tuple[float, float, float]
) -> None:
    for obj in objects:
        if obj is None:
            continue
        mw = obj.matrix_world.copy()
        mw.translation.x += delta[0]
        mw.translation.y += delta[1]
        mw.translation.z += delta[2]
        obj.matrix_world = mw


def advanced_align_objects(
    objects: Iterable[bpy.types.Object],
    *,
    axis_x: str,
    axis_y: str,
    axis_z: str,
    target: Tuple[float, float, float],
    enable_x: bool = True,
    enable_y: bool = True,
    enable_z: bool = True,
    combined_bbox: bool = True,
) -> Tuple[bool, Tuple[float, float, float], int]:
    """Align mesh bbox min/center/max per axis to ``target`` in world space.

    When ``combined_bbox`` is True, use one union bbox and move every object in
    ``objects`` by the same offset. When False, align each mesh on its own bbox.
    """
    objs = [o for o in objects if o is not None]
    meshes = [o for o in objs if o.type == "MESH"]
    if not meshes:
        return False, (0.0, 0.0, 0.0), 0

    depsgraph = bpy.context.evaluated_depsgraph_get()
    if not combined_bbox:
        aligned = _align_meshes_per_object(
            meshes,
            depsgraph,
            axis_x=axis_x,
            axis_y=axis_y,
            axis_z=axis_z,
            target=target,
            enable_x=enable_x,
            enable_y=enable_y,
            enable_z=enable_z,
        )
        return aligned > 0, (0.0, 0.0, 0.0), aligned

    delta = _advanced_align_delta(
        meshes,
        depsgraph,
        axis_x=axis_x,
        axis_y=axis_y,
        axis_z=axis_z,
        target=target,
        enable_x=enable_x,
        enable_y=enable_y,
        enable_z=enable_z,
    )
    if delta is None:
        return False, (0.0, 0.0, 0.0), 0

    _apply_world_translation(objs, delta)
    return True, delta, len(meshes)


def advanced_align_tree(
    tree_root: bpy.types.Object,
    *,
    axis_x: str,
    axis_y: str,
    axis_z: str,
    target: Tuple[float, float, float],
    enable_x: bool = True,
    enable_y: bool = True,
    enable_z: bool = True,
    combined_bbox: bool = True,
) -> Tuple[bool, Tuple[float, float, float], int]:
    """Move Geo root or each subtree mesh so bbox aligns to ``target``."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    meshes = [sub for sub in iter_subobjects_recursive(tree_root) if sub.type == "MESH"]
    if not meshes:
        return False, (0.0, 0.0, 0.0), 0

    if not combined_bbox:
        aligned = _align_meshes_per_object(
            meshes,
            depsgraph,
            axis_x=axis_x,
            axis_y=axis_y,
            axis_z=axis_z,
            target=target,
            enable_x=enable_x,
            enable_y=enable_y,
            enable_z=enable_z,
        )
        return aligned > 0, (0.0, 0.0, 0.0), aligned

    delta = _advanced_align_delta(
        meshes,
        depsgraph,
        axis_x=axis_x,
        axis_y=axis_y,
        axis_z=axis_z,
        target=target,
        enable_x=enable_x,
        enable_y=enable_y,
        enable_z=enable_z,
    )
    if delta is None:
        return False, (0.0, 0.0, 0.0), 0

    _apply_world_translation([tree_root], delta)
    return True, delta, len(meshes)


def set_objects_on_floor(objects: Iterable[bpy.types.Object]) -> Tuple[bool, float]:
    """
    Union bbox (world) of mesh objects; apply the same Z translation to every object in ``objects``.
    """
    objs = [o for o in objects if o is not None]
    meshes = [o for o in objs if o.type == "MESH"]
    if not meshes:
        return False, 0.0

    depsgraph = bpy.context.evaluated_depsgraph_get()
    min_z: Optional[float] = None
    for mesh in meshes:
        z = _mesh_world_min_z(mesh, depsgraph)
        if z is None:
            continue
        if min_z is None or z < min_z:
            min_z = z
    if min_z is None:
        return False, 0.0

    delta = -min_z
    for obj in objs:
        mw = obj.matrix_world.copy()
        mw.translation.z += delta
        obj.matrix_world = mw
    return True, delta


def set_tree_on_floor(tree_root: bpy.types.Object) -> Tuple[bool, float]:
    """Move Geo root so the lowest mesh in the subtree sits on Z=0 (no selection fallback)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    min_z: Optional[float] = None
    for sub in iter_subobjects_recursive(tree_root):
        if sub.type != "MESH":
            continue
        z = _mesh_world_min_z(sub, depsgraph)
        if z is None:
            continue
        if min_z is None or z < min_z:
            min_z = z
    if min_z is None:
        return False, 0.0
    delta = -min_z
    mw = tree_root.matrix_world.copy()
    mw.translation.z += delta
    tree_root.matrix_world = mw
    return True, delta


def set_objects_center_to_origin(
    objects: Iterable[bpy.types.Object],
) -> Tuple[bool, Tuple[float, float, float]]:
    """
    Union bbox (world) of mesh objects; apply the same translation to every object in ``objects``.
    """
    objs = [o for o in objects if o is not None]
    meshes = [o for o in objs if o.type == "MESH"]
    if not meshes:
        return False, (0.0, 0.0, 0.0)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    center = _union_bbox_center(meshes, depsgraph)
    if center is None:
        return False, (0.0, 0.0, 0.0)

    delta = (-center[0], -center[1], -center[2])
    _apply_world_translation(objs, delta)
    return True, delta


def set_tree_center_to_origin(tree_root: bpy.types.Object) -> Tuple[bool, Tuple[float, float, float]]:
    """Move Geo root so the union mesh bbox center sits at world origin (no selection fallback)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    meshes = [sub for sub in iter_subobjects_recursive(tree_root) if sub.type == "MESH"]
    center = _union_bbox_center(meshes, depsgraph)
    if center is None:
        return False, (0.0, 0.0, 0.0)

    delta = (-center[0], -center[1], -center[2])
    _apply_world_translation([tree_root], delta)
    return True, delta


def collect_apply_transform_targets(
    *,
    scope: str,
    tree_root: Optional[bpy.types.Object],
    selected: Iterable[bpy.types.Object],
    allow_armature: bool,
) -> List[bpy.types.Object]:
    """Resolve mesh/armature objects for Advanced Apply Transform."""
    allowed_types = {"MESH", "ARMATURE"}
    targets: List[bpy.types.Object] = []
    seen: set[bpy.types.Object] = set()

    def _maybe_add(obj: bpy.types.Object) -> None:
        if obj is None or obj in seen:
            return
        if obj.type not in allowed_types:
            return
        if obj.type == "ARMATURE" and not allow_armature:
            return
        seen.add(obj)
        targets.append(obj)

    key = (scope or "PRODUCTION_TREE").upper()
    if key == "SELECTION":
        for obj in selected:
            if obj is None:
                continue
            for sub in iter_subobjects_recursive(obj):
                _maybe_add(sub)
        return targets

    if tree_root is None:
        return []
    for sub in iter_subobjects_recursive(tree_root):
        if sub == tree_root:
            continue
        _maybe_add(sub)
    return targets


def apply_transforms_to_objects(
    objects: Iterable[bpy.types.Object],
    *,
    location: bool = True,
    rotation: bool = True,
    scale: bool = True,
) -> Tuple[List[str], List[str]]:
    from .transform import _restore_selection, _with_single_selection

    if not location and not rotation and not scale:
        return [], []

    applied: List[str] = []
    failed: List[str] = []
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass

    for obj in objects:
        if obj is None:
            continue
        try:
            if getattr(obj, "library", None) is not None:
                failed.append(obj.name)
                continue
        except Exception:
            pass
        prev_active, prev_selected = _with_single_selection(obj)
        try:
            res = bpy.ops.object.transform_apply(
                location=location,
                rotation=rotation,
                scale=scale,
            )
            if "FINISHED" in set(res or []):
                applied.append(obj.name)
            else:
                failed.append(obj.name)
        except Exception:
            failed.append(obj.name)
        finally:
            _restore_selection(prev_active, prev_selected)
    return applied, failed


def apply_transforms_in_tree(
    tree_root: bpy.types.Object,
    *,
    allow_armature: bool = False,
) -> Tuple[List[str], List[str]]:
    """Backward-compatible wrapper for production-tree apply."""
    targets = collect_apply_transform_targets(
        scope="PRODUCTION_TREE",
        tree_root=tree_root,
        selected=[],
        allow_armature=allow_armature,
    )
    return apply_transforms_to_objects(
        targets,
        location=True,
        rotation=True,
        scale=True,
    )


def lowercase_selected_names(objects: Iterable[bpy.types.Object]) -> Tuple[int, int]:
    renamed = 0
    skipped = 0
    for obj in objects:
        if obj is None:
            continue
        low = obj.name.lower()
        if obj.name == low:
            skipped += 1
            continue
        obj.name = low
        renamed += 1
    return renamed, skipped


def collect_geo_meshes_in_hierarchy(hierarchy: AssetHierarchy) -> List[bpy.types.Object]:
    """Mesh objects under the Geo root (excludes empties / *_Grp)."""
    return [o for o in iter_subobjects_recursive(hierarchy.geo_container) if o.type == "MESH"]


def add_geo_prefix_to_selected(
    objects: Iterable[bpy.types.Object],
    prefix: str,
) -> Tuple[int, int]:
    renamed = 0
    skipped = 0
    for obj in objects:
        if obj is None:
            continue
        new_name = ensure_mesh_geo_prefix(obj.name, prefix)
        if new_name is None:
            skipped += 1
            continue
        obj.name = new_name
        renamed += 1
    return renamed, skipped


def create_hierarchy_from_scene_props(
    context: bpy.types.Context,
    *,
    props,
) -> tuple[bpy.types.Collection, int]:
    preset = preset_from_scene_nodes(props)
    slug = (props.asset_name or "").strip() or "Asset"
    anchor = context.view_layer.objects.active
    selected = list(context.selected_objects or [])
    col = None
    if anchor and anchor.users_collection:
        col = anchor.users_collection[0]
    elif context.collection:
        col = context.collection
    hierarchy = ensure_hierarchy_from_preset(
        asset_slug=slug,
        preset=preset,
        collection=col,
        anchor=anchor,
    )
    moved = move_selection_into_asset_collection(hierarchy, selected)
    return hierarchy.asset_collection, moved


def group_selected_objects_at_origin(
    context: bpy.types.Context,
    objects: Iterable[bpy.types.Object],
) -> Tuple[bool, str, Optional[bpy.types.Object]]:
    """
    Create an empty at world origin and parent selected root objects under it.

    Objects whose parent is also selected keep their internal hierarchy.
    """
    import mathutils

    selected = [o for o in objects if o is not None]
    if not selected:
        return False, "No objects selected.", None

    try:
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass

    for obj in selected:
        try:
            if getattr(obj, "library", None) is not None:
                return False, f"Cannot group linked object '{obj.name}'.", None
        except Exception:
            pass

    selected_set = set(selected)
    roots = [o for o in selected if o.parent is None or o.parent not in selected_set]

    active = context.view_layer.objects.active
    group_name = active.name if active is not None else selected[0].name

    collection = ensure_collection_for_new_objects(
        preferred_collection=context.collection,
        fallback_obj=selected[0],
    )
    empty = create_empty_object(
        name=group_name,
        parent=None,
        world_matrix=mathutils.Matrix.Identity(4),
        collection=collection,
    )

    for obj in roots:
        parent_meshes_under_empty(obj, empty)

    view_layer = context.view_layer
    for obj in view_layer.objects:
        obj.select_set(False)
    empty.select_set(True)
    view_layer.objects.active = empty

    return True, f"Grouped {len(selected)} object(s) under '{empty.name}' at origin.", empty


def _link_collection_under_parent(
    child: bpy.types.Collection,
    parent: bpy.types.Collection,
) -> None:
    if child.name in parent.children:
        return
    try:
        parent.children.link(child)
    except RuntimeError:
        pass


def _parent_collection_in_tree(col: bpy.types.Collection) -> Optional[bpy.types.Collection]:
    scene_col = bpy.context.scene.collection
    if col.name in scene_col.children:
        return scene_col
    for parent in bpy.data.collections:
        if parent is scene_col:
            continue
        if col.name in parent.children:
            return parent
    return None


def _collection_tree_depth(col: bpy.types.Collection) -> int:
    parent = _parent_collection_in_tree(col)
    if parent is None:
        return 0
    return 1 + _collection_tree_depth(parent)


def _direct_user_collections(obj: bpy.types.Object) -> List[bpy.types.Collection]:
    return [c for c in obj.users_collection if c is not None]


def _resolve_parent_collection_for_object(
    context: bpy.types.Context,
    obj: bpy.types.Object,
) -> bpy.types.Collection:
    """Innermost collection that directly contains *obj* (not an ancestor in the tree)."""
    user_cols = _direct_user_collections(obj)
    active = context.collection

    if active is not None and active in user_cols:
        return active

    if user_cols:
        return max(user_cols, key=_collection_tree_depth)

    if active is not None:
        return active
    return context.scene.collection


def _find_child_collection_by_name(
    parent: bpy.types.Collection,
    name: str,
) -> Optional[bpy.types.Collection]:
    for child in parent.children:
        if child.name == name:
            return child
    return None


def _ensure_object_named_collection(
    obj: bpy.types.Object,
    *,
    parent_col: bpy.types.Collection,
) -> Tuple[bpy.types.Collection, bool]:
    name = obj.name
    existing = _find_child_collection_by_name(parent_col, name)
    if existing is None:
        col = bpy.data.collections.new(name)
        created = True
    else:
        col = existing
        created = False
    _link_collection_under_parent(col, parent_col)
    return col, created


def collect_selected_into_named_collections(
    context: bpy.types.Context,
    objects: Iterable[bpy.types.Object],
) -> Tuple[bool, str, int, int]:
    """
    For each top-level selected object, move it and all descendants into a
    collection named after that object.
    """
    selected = [o for o in objects if o is not None]
    if not selected:
        return False, "No objects selected.", 0, 0

    try:
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass

    for obj in selected:
        try:
            if getattr(obj, "library", None) is not None:
                return False, f"Cannot collect linked object '{obj.name}'.", 0, 0
        except Exception:
            pass

    selected_set = set(selected)
    roots = [o for o in selected if o.parent is None or o.parent not in selected_set]

    collections_created = 0
    objects_moved = 0

    for root in roots:
        parent_col = _resolve_parent_collection_for_object(context, root)
        target_col, created = _ensure_object_named_collection(root, parent_col=parent_col)
        if created:
            collections_created += 1
        subtree = list(iter_subobjects_recursive(root))
        objects_moved += move_objects_to_collection(subtree, target_col)

    msg = (
        f"Collected {objects_moved} object(s) into "
        f"{len(roots)} collection(s) named after each root object."
    )
    return True, msg, collections_created, objects_moved
