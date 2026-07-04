"""
Material naming and assignment helpers (aligned with Houdini M_char_* rules).
"""

from __future__ import annotations

from typing import Iterable, List, Optional

import bpy

from . import config


def grp_base_name(empty_name: str) -> Optional[str]:
    if empty_name.endswith(config.GRP_SUFFIX_MIXED):
        return empty_name[: -len(config.GRP_SUFFIX_MIXED)]
    if empty_name.endswith(config.GRP_SUFFIX_LOWER):
        return empty_name[: -len(config.GRP_SUFFIX_LOWER)]
    return None


def material_name(prefix: str, base: str) -> str:
    return f"{prefix}{base}"


def ensure_mesh_geo_prefix(name: str, prefix: str) -> Optional[str]:
    """Return new name if prefix should be added, else None (already prefixed)."""
    if not prefix:
        return None
    low_name = name.casefold()
    low_pre = prefix.casefold()
    if low_name.startswith(low_pre):
        return None
    return prefix + name


def iter_meshes_under(obj: bpy.types.Object) -> Iterable[bpy.types.Object]:
    for sub in _iter_recursive(obj):
        if sub.type == "MESH":
            yield sub


def _iter_recursive(obj: bpy.types.Object):
    yield obj
    for c in obj.children:
        yield from _iter_recursive(c)


def clear_materials_on_objects(
    objects: Iterable[bpy.types.Object],
    *,
    purge_orphans: bool = False,
) -> int:
    cleared = 0
    mats_to_check: List[bpy.types.Material] = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            if slot.material is not None:
                mats_to_check.append(slot.material)
                slot.material = None
                cleared += 1
    if purge_orphans:
        for mat in mats_to_check:
            try:
                if mat.users == 0:
                    bpy.data.materials.remove(mat)
            except Exception:
                pass
    return cleared


def assign_materials_from_grp_tree(
    asset_root: bpy.types.Object,
    *,
    material_prefix: str,
) -> tuple[int, int]:
    """Create/reuse materials for each *_Grp and assign to descendant meshes."""
    created = 0
    assigned = 0
    prefix = material_prefix or config.DEFAULT_MATERIAL_PREFIX

    for sub in _iter_recursive(asset_root):
        if sub.type != "EMPTY":
            continue
        base = grp_base_name(sub.name)
        if base is None:
            continue
        mat_name = material_name(prefix, base)
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(mat_name)
            try:
                mat.use_nodes = True
            except Exception:
                pass
            created += 1
        for mesh_obj in iter_meshes_under(sub):
            if mesh_obj == sub:
                continue
            if not mesh_obj.data:
                continue
            if len(mesh_obj.material_slots) == 0:
                mesh_obj.data.materials.append(mat)
            else:
                mesh_obj.material_slots[0].material = mat
            assigned += 1
    return created, assigned
