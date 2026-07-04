"""
Shared Blender object helpers for MonoFX add-on.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

import bpy

from . import config


def validate_assets_same_direct_parent(
    asset_objs: Iterable[bpy.types.Object],
) -> Tuple[bool, Optional[bpy.types.Object]]:
    objs = [o for o in asset_objs if o is not None]
    if not objs:
        return False, None
    parents = {o.parent for o in objs}
    if len(parents) != 1:
        return False, None
    return True, objs[0].parent


def is_expected_name(actual: str, expected: str) -> bool:
    if actual == expected:
        return True
    if actual.startswith(expected + "."):
        return True
    return False


# Backward-compatible alias used by asset_hierarchy
_is_expected_name = is_expected_name


def ensure_collection_for_new_objects(
    *,
    preferred_collection: Optional[bpy.types.Collection],
    fallback_obj: Optional[bpy.types.Object],
) -> bpy.types.Collection:
    if preferred_collection:
        return preferred_collection
    if fallback_obj and fallback_obj.users_collection:
        return fallback_obj.users_collection[0]
    return bpy.context.scene.collection


_ensure_collection_for_new_objects = ensure_collection_for_new_objects


def create_empty_object(
    *,
    name: str,
    parent: Optional[bpy.types.Object],
    world_matrix: Optional[bpy.types.Matrix],
    collection: bpy.types.Collection,
) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "PLAIN_AXES"
    collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    if world_matrix is not None:
        obj.matrix_world = world_matrix
    return obj


_create_empty_object = create_empty_object


def find_child_by_expected_name(parent: bpy.types.Object, expected: str) -> Optional[bpy.types.Object]:
    for c in parent.children:
        if is_expected_name(c.name, expected):
            return c
    return None


_find_child_by_expected_name = find_child_by_expected_name


def iter_subobjects_recursive(obj: bpy.types.Object) -> Iterable[bpy.types.Object]:
    yield obj
    for c in obj.children:
        yield from iter_subobjects_recursive(c)


def is_descendant_of(obj: bpy.types.Object, ancestor: bpy.types.Object) -> bool:
    p = obj.parent
    while p is not None:
        if p == ancestor:
            return True
        p = p.parent
    return False


def find_armature_any(obj_list: Iterable[bpy.types.Object]) -> Optional[bpy.types.Object]:
    for o in obj_list:
        for sub in iter_subobjects_recursive(o):
            if sub.type == "ARMATURE":
                return sub
    return None
