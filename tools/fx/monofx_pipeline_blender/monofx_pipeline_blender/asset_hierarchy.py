"""
Asset hierarchy: collection Geo_<Asset> -> object tree Geo -> *_Grp.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import bpy

from . import config
from .logic import (
    _create_empty_object,
    _find_child_by_expected_name,
    _is_expected_name,
    iter_subobjects_recursive,
)
from .preset import HierarchyPreset, HierarchyPresetNode


@dataclass(frozen=True)
class AssetHierarchy:
    asset_collection: bpy.types.Collection
    geo_container: bpy.types.Object


def is_asset_collection_name(name: str) -> bool:
    return name.startswith(config.ASSET_ROOT_PREFIX) or name.startswith(
        config.ASSET_ROOT_PREFIX.lower()
    )


# Backward-compatible aliases
is_asset_root_name = is_asset_collection_name


def asset_collection_name_for(asset_slug: str) -> str:
    slug = (asset_slug or "Asset").strip()
    if slug.startswith(config.ASSET_ROOT_PREFIX):
        return slug
    return f"{config.ASSET_ROOT_PREFIX}{slug}"


asset_root_name_for = asset_collection_name_for


def _link_object_to_collection(obj: bpy.types.Object, col: bpy.types.Collection) -> None:
    if col not in obj.users_collection:
        col.objects.link(obj)


def _ensure_collection_child(parent: bpy.types.Collection, child: bpy.types.Collection) -> None:
    if child.name in parent.children:
        return
    try:
        parent.children.link(child)
    except RuntimeError:
        pass


def _find_geo_in_collection(col: bpy.types.Collection) -> Optional[bpy.types.Object]:
    root_geo: Optional[bpy.types.Object] = None
    any_geo: Optional[bpy.types.Object] = None
    col_objects = set(col.all_objects)
    for obj in col.all_objects:
        if not _is_expected_name(obj.name, config.INNER_GEO_NAME):
            continue
        any_geo = obj
        parent = obj.parent
        if parent is None or parent not in col_objects:
            root_geo = obj
            break
    return root_geo or any_geo


def get_asset_hierarchy_from_collection(
    col: bpy.types.Collection,
) -> Optional[AssetHierarchy]:
    if col is None or not is_asset_collection_name(col.name):
        return None
    geo = _find_geo_in_collection(col)
    if geo is None:
        return None
    return AssetHierarchy(asset_collection=col, geo_container=geo)


def get_asset_hierarchy_legacy_empty(
    root_empty: bpy.types.Object,
) -> Optional[AssetHierarchy]:
    if root_empty is None or root_empty.type != "EMPTY":
        return None
    if not is_asset_collection_name(root_empty.name):
        return None
    geo = _find_child_by_expected_name(root_empty, config.INNER_GEO_NAME)
    if geo is None:
        return None
    col = bpy.data.collections.get(root_empty.name)
    if col is None:
        col = bpy.data.collections.new(root_empty.name)
        if root_empty.users_collection:
            _ensure_collection_child(root_empty.users_collection[0], col)
        else:
            _ensure_collection_child(bpy.context.scene.collection, col)
    return AssetHierarchy(asset_collection=col, geo_container=geo)


def get_asset_hierarchy(asset_root_or_collection: object) -> Optional[AssetHierarchy]:
    if isinstance(asset_root_or_collection, bpy.types.Collection):
        return get_asset_hierarchy_from_collection(asset_root_or_collection)
    if isinstance(asset_root_or_collection, bpy.types.Object):
        legacy = get_asset_hierarchy_legacy_empty(asset_root_or_collection)
        if legacy is not None:
            return legacy
    return None


def find_geo_container_from_object(obj: bpy.types.Object) -> Optional[bpy.types.Object]:
    if obj is None:
        return None
    cur = obj
    for _ in range(128):
        if _is_expected_name(cur.name, config.INNER_GEO_NAME):
            return cur
        if cur.parent is None:
            break
        cur = cur.parent
    return None


def resolve_asset_hierarchy_from_object(
    obj: bpy.types.Object,
) -> Optional[AssetHierarchy]:
    if obj is None:
        return None

    for col in obj.users_collection:
        if not is_asset_collection_name(col.name):
            continue
        hierarchy = get_asset_hierarchy_from_collection(col)
        if hierarchy is not None:
            return hierarchy

    cur = obj
    found_geo: Optional[bpy.types.Object] = None
    for _ in range(128):
        if _is_expected_name(cur.name, config.INNER_GEO_NAME):
            found_geo = cur
        if cur.type == "EMPTY" and is_asset_collection_name(cur.name):
            return get_asset_hierarchy_legacy_empty(cur)
        if cur.parent is None:
            break
        cur = cur.parent

    if found_geo is not None:
        for col in found_geo.users_collection:
            if is_asset_collection_name(col.name):
                return get_asset_hierarchy_from_collection(col)
        if found_geo.parent and is_asset_collection_name(found_geo.parent.name):
            return get_asset_hierarchy_legacy_empty(found_geo.parent)
    return None


def resolve_asset_root_from_object(obj: bpy.types.Object) -> Optional[bpy.types.Object]:
    """Legacy helper: returns Geo container object for the asset hierarchy."""
    hierarchy = resolve_asset_hierarchy_from_object(obj)
    return hierarchy.geo_container if hierarchy else None


def find_asset_hierarchies_in_scene() -> List[AssetHierarchy]:
    found: List[AssetHierarchy] = []
    seen_geo: set[str] = set()

    for col in bpy.data.collections:
        if not is_asset_collection_name(col.name):
            continue
        hierarchy = get_asset_hierarchy_from_collection(col)
        if hierarchy is None:
            continue
        key = hierarchy.geo_container.name
        if key in seen_geo:
            continue
        seen_geo.add(key)
        found.append(hierarchy)

    for obj in bpy.data.objects:
        if obj.type != "EMPTY" or not is_asset_collection_name(obj.name):
            continue
        hierarchy = get_asset_hierarchy_legacy_empty(obj)
        if hierarchy is None:
            continue
        key = hierarchy.geo_container.name
        if key in seen_geo:
            continue
        seen_geo.add(key)
        found.append(hierarchy)
    return found


find_asset_roots_in_scene = find_asset_hierarchies_in_scene


def move_objects_to_collection(
    objects: Iterable[bpy.types.Object],
    target_col: bpy.types.Collection,
    *,
    exclude_names: Optional[set[str]] = None,
) -> int:
    """Link selected objects into ``target_col`` and remove them from other collections."""
    excluded = exclude_names or set()
    moved = 0
    for obj in objects:
        if obj is None or obj.name in excluded:
            continue
        try:
            if getattr(obj, "library", None) is not None:
                continue
        except Exception:
            pass
        try:
            if target_col not in obj.users_collection:
                target_col.objects.link(obj)
            for uc in list(obj.users_collection):
                if uc != target_col:
                    uc.objects.unlink(obj)
            moved += 1
        except RuntimeError:
            continue
    return moved


def iter_hierarchy_objects(hierarchy: AssetHierarchy) -> Iterable[bpy.types.Object]:
    seen: set[str] = set()
    for obj in iter_subobjects_recursive(hierarchy.geo_container):
        seen.add(obj.name)
        yield obj
    for obj in hierarchy.asset_collection.all_objects:
        if obj.name not in seen:
            yield obj


def resolve_asset_for_publish(
    *,
    active: Optional[bpy.types.Object],
    selected: List[bpy.types.Object],
    select_hierarchy: bool,
) -> Tuple[bool, Optional[AssetHierarchy], List[bpy.types.Object], str]:
    if selected:
        obj = active or selected[0]
        hierarchy = resolve_asset_hierarchy_from_object(obj)
        if hierarchy is None:
            geo = find_geo_container_from_object(obj)
            if geo is not None:
                hierarchy = resolve_asset_hierarchy_from_object(geo)
        if hierarchy is None:
            return (
                False,
                None,
                [],
                "Selection must be under collection Geo_<Asset> / Geo hierarchy.",
            )
        if select_hierarchy:
            return True, hierarchy, list(iter_hierarchy_objects(hierarchy)), ""
        return True, hierarchy, list(selected), ""

    hierarchies = find_asset_hierarchies_in_scene()
    if len(hierarchies) == 0:
        return (
            False,
            None,
            [],
            "No selection and no Geo_<Asset> collection with Geo found in scene.",
        )
    if len(hierarchies) > 1:
        names = ", ".join(h.asset_collection.name for h in hierarchies[:5])
        return (
            False,
            None,
            [],
            f"Multiple asset collections ({len(hierarchies)}): {names}. Select one or set active.",
        )
    hierarchy = hierarchies[0]
    if select_hierarchy:
        objs = list(iter_hierarchy_objects(hierarchy))
    else:
        objs = [hierarchy.geo_container]
    return True, hierarchy, objs, ""


def _is_collection_nested_under(
    child: bpy.types.Collection,
    ancestor: bpy.types.Collection,
) -> bool:
    if child == ancestor:
        return True
    for sub in ancestor.children:
        if _is_collection_nested_under(child, sub):
            return True
    return False


def find_collections_for_keyword_export(keyword: str) -> List[bpy.types.Collection]:
    """
    Collections to export one USD each.

    When *keyword* is empty, include every collection that contains objects.
    Otherwise match collection names (case-insensitive substring).
    Parent collections are skipped when a nested child collection is also included.
    """
    token = (keyword or "").strip().lower()
    candidates: List[bpy.types.Collection] = []
    for col in bpy.data.collections:
        if not col.all_objects:
            continue
        if token and token not in col.name.lower():
            continue
        candidates.append(col)

    if not candidates:
        return []

    deepest: List[bpy.types.Collection] = []
    for col in candidates:
        has_nested_candidate = any(
            other is not col and _is_collection_nested_under(other, col)
            for other in candidates
        )
        if not has_nested_candidate:
            deepest.append(col)
    return sorted(deepest, key=lambda c: c.name.lower())


def _iter_outliner_contexts(context: bpy.types.Context):
    wm = getattr(context, "window_manager", None) or getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "OUTLINER":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None:
                continue
            yield window, screen, area, region


def _collection_from_outliner_id(item) -> Optional[bpy.types.Collection]:
    if isinstance(item, bpy.types.Collection):
        return item
    layer_coll = getattr(item, "collection", None)
    if isinstance(layer_coll, bpy.types.Collection):
        return layer_coll
    return None


def _outliner_selected_collections(context: bpy.types.Context) -> List[bpy.types.Collection]:
    """Read multi-select from Outliner; requires temp_override per area."""
    best: List[bpy.types.Collection] = []
    for window, screen, area, region in _iter_outliner_contexts(context):
        try:
            with context.temp_override(
                window=window,
                screen=screen,
                area=area,
                region=region,
                space_data=area.spaces.active,
            ):
                ids = tuple(context.selected_ids or ())
        except (AttributeError, TypeError, RuntimeError):
            continue

        cols: List[bpy.types.Collection] = []
        seen: set[str] = set()
        for item in ids:
            col = _collection_from_outliner_id(item)
            if col is None or col.name in seen:
                continue
            seen.add(col.name)
            cols.append(col)
        if len(cols) > len(best):
            best = cols
    return best


def find_collections_for_selected_export(
    context: bpy.types.Context,
) -> List[bpy.types.Collection]:
    """
    Collections chosen for one-USD-each publish.

    Prefer Outliner multi-selection; otherwise use the active layer collection.
    """
    selected = _outliner_selected_collections(context)
    if selected:
        return sorted(selected, key=lambda c: c.name.lower())

    view_layer = getattr(context, "view_layer", None)
    layer_coll = (
        view_layer.active_layer_collection if view_layer is not None else None
    )
    if layer_coll is not None and layer_coll.collection is not None:
        return [layer_coll.collection]
    return []


def objects_in_collection_for_export(col: bpy.types.Collection) -> List[bpy.types.Object]:
    """Unique objects under a collection (includes nested collection contents)."""
    seen: set[str] = set()
    found: List[bpy.types.Object] = []
    for obj in col.all_objects:
        if obj is None or obj.name in seen:
            continue
        seen.add(obj.name)
        found.append(obj)
    return found


def collect_objects_in_collections_by_keyword(keyword: str) -> List[bpy.types.Object]:
    """All unique objects from :func:`find_collections_for_keyword_export` (legacy helper)."""
    seen: set[str] = set()
    found: List[bpy.types.Object] = []
    for col in find_collections_for_keyword_export(keyword):
        for obj in objects_in_collection_for_export(col):
            if obj.name in seen:
                continue
            seen.add(obj.name)
            found.append(obj)
    return found


def _resolve_parent_object(
    node: HierarchyPresetNode,
    *,
    name_map: dict[str, bpy.types.Object],
) -> Optional[bpy.types.Object]:
    if not node.parent:
        return None
    return name_map.get(node.parent)


def _migrate_legacy_root_empty_to_collection(
    legacy_root: bpy.types.Object,
    asset_col: bpy.types.Collection,
) -> None:
    geo = _find_child_by_expected_name(legacy_root, config.INNER_GEO_NAME)
    if geo is None:
        return
    geo.parent = None
    for sub in iter_subobjects_recursive(geo):
        _link_object_to_collection(sub, asset_col)
    try:
        bpy.data.objects.remove(legacy_root, do_unlink=True)
    except Exception:
        pass


def _find_top_level_in_collection(
    col: bpy.types.Collection,
    expected: str,
) -> Optional[bpy.types.Object]:
    for obj in col.objects:
        if obj.parent is not None:
            continue
        if _is_expected_name(obj.name, expected):
            return obj
    for obj in col.all_objects:
        if _is_expected_name(obj.name, expected) and (
            obj.parent is None or obj.parent not in col.all_objects
        ):
            return obj
    return None


def ensure_hierarchy_from_preset(
    *,
    asset_slug: str,
    preset: HierarchyPreset,
    collection: Optional[bpy.types.Collection],
    anchor: Optional[bpy.types.Object] = None,
) -> AssetHierarchy:
    from .logic import _ensure_collection_for_new_objects

    parent_col = _ensure_collection_for_new_objects(
        preferred_collection=collection,
        fallback_obj=anchor,
    )
    col_name = asset_collection_name_for(asset_slug)
    asset_col = bpy.data.collections.get(col_name)
    if asset_col is None:
        asset_col = bpy.data.collections.new(col_name)
    _ensure_collection_child(parent_col, asset_col)

    legacy_root = bpy.data.objects.get(col_name)
    if legacy_root is not None and legacy_root.type == "EMPTY":
        _migrate_legacy_root_empty_to_collection(legacy_root, asset_col)

    name_map: dict[str, bpy.types.Object] = {}
    for node in preset.nodes:
        parent_obj = _resolve_parent_object(node, name_map=name_map)
        existing: Optional[bpy.types.Object] = None
        if parent_obj is not None:
            existing = _find_child_by_expected_name(parent_obj, node.name)
        else:
            existing = _find_top_level_in_collection(asset_col, node.name)

        if existing is None:
            existing = _create_empty_object(
                name=node.name,
                parent=parent_obj,
                world_matrix=None,
                collection=asset_col,
            )
        else:
            _link_object_to_collection(existing, asset_col)
            if parent_obj is not None and existing.parent != parent_obj:
                mw = existing.matrix_world.copy()
                existing.parent = parent_obj
                existing.matrix_world = mw

        name_map[node.name] = existing

    hierarchy = get_asset_hierarchy_from_collection(asset_col)
    if hierarchy is None:
        raise RuntimeError("Failed to build asset hierarchy.")
    return hierarchy


def move_selection_into_asset_collection(
    hierarchy: AssetHierarchy,
    selected: Iterable[bpy.types.Object],
) -> int:
    exclude = {o.name for o in iter_hierarchy_objects(hierarchy)}
    return move_objects_to_collection(selected, hierarchy.asset_collection, exclude_names=exclude)


def parent_meshes_under_empty(
    mesh_obj: bpy.types.Object,
    parent_empty: bpy.types.Object,
) -> None:
    mw = mesh_obj.matrix_world.copy()
    mesh_obj.parent = parent_empty
    mesh_obj.matrix_world = mw


def collect_leaf_grp_empties(
    hierarchy: AssetHierarchy,
    preset: HierarchyPreset,
) -> List[Tuple[HierarchyPresetNode, bpy.types.Object]]:
    asset_root = hierarchy.geo_container
    out: List[Tuple[HierarchyPresetNode, bpy.types.Object]] = []
    empties = [sub for sub in iter_subobjects_recursive(asset_root) if sub.type == "EMPTY"]
    for node in preset.nodes:
        if not node.is_leaf:
            continue
        obj = None
        for sub in empties:
            if _is_expected_name(sub.name, node.name):
                obj = sub
                break
        if obj is not None:
            out.append((node, obj))
    return out
