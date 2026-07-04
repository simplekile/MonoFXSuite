"""
Strip DCC-import extras from mesh objects (shape keys, groups, attributes, UVs).
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterable, Iterator, List, Optional, Sequence

import bpy

from .logic import iter_subobjects_recursive

_COLOR_ATTRIBUTE_TYPES = frozenset(
    {
        "FLOAT_COLOR",
        "BYTE_COLOR",
        "SHORT",
        "INT8",
    }
)
_UV_ATTRIBUTE_DATA_TYPES = frozenset({"FLOAT2"})
_UV_ATTRIBUTE_DOMAINS = frozenset({"CORNER", "FACE"})


@dataclass
class MeshCleanupOptions:
    apply_modifiers: bool = False
    apply_shape_keys: bool = True
    clean_vertex_groups: bool = True
    clean_color_attributes: bool = True
    clean_custom_attributes: bool = True
    clean_uv_maps: bool = True


@dataclass
class MeshCleanupResult:
    meshes_processed: int = 0
    modifiers_applied: int = 0
    shape_keys_removed: int = 0
    vertex_groups_cleared: int = 0
    color_attributes_removed: int = 0
    attributes_removed: int = 0
    uv_layers_removed: int = 0
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.meshes_processed} mesh(es)"]
        if self.modifiers_applied:
            parts.append(f"modifiers {self.modifiers_applied}")
        if self.shape_keys_removed:
            parts.append(f"shape keys {self.shape_keys_removed}")
        if self.vertex_groups_cleared:
            parts.append(f"vertex groups {self.vertex_groups_cleared}")
        if self.color_attributes_removed:
            parts.append(f"color attrs {self.color_attributes_removed}")
        if self.attributes_removed:
            parts.append(f"attrs {self.attributes_removed}")
        if self.uv_layers_removed:
            parts.append(f"UV layers {self.uv_layers_removed}")
        if self.skipped:
            parts.append(f"skipped {len(self.skipped)}")
        if self.errors:
            parts.append(f"errors {len(self.errors)}")
        return ", ".join(parts)


def _ensure_object_mode() -> None:
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass


def _is_linked_mesh(obj: bpy.types.Object) -> bool:
    try:
        data = obj.data
        return data is not None and getattr(data, "library", None) is not None
    except Exception:
        return False


def _is_removable_mesh_attribute(attr: bpy.types.Attribute) -> bool:
    if getattr(attr, "is_builtin", False):
        return False
    name = (attr.name or "").strip()
    if not name or name.startswith("."):
        return False
    return True


def _is_uv_mesh_attribute(attr: bpy.types.Attribute, mesh: bpy.types.Mesh) -> bool:
    """UV stored as mesh attributes (Blender 4+) — only removed when Clean UV Maps is on."""
    name = (attr.name or "").strip()
    low = name.casefold()
    if low in {"uv", "uvmap"} or low.startswith("uv"):
        return True
    dtype = str(getattr(attr, "data_type", "") or "")
    domain = str(getattr(attr, "domain", "") or "")
    if dtype in _UV_ATTRIBUTE_DATA_TYPES and domain in _UV_ATTRIBUTE_DOMAINS:
        return True
    layers = getattr(mesh, "uv_layers", None)
    if layers and name:
        for layer in layers:
            if layer.name == name:
                return True
    return False


@contextmanager
def _with_active_mesh(obj: bpy.types.Object) -> Iterator[bpy.types.Object]:
    from .transform import _restore_selection, _with_single_selection

    prev_active, prev_selected = _with_single_selection(obj)
    try:
        yield obj
    finally:
        _restore_selection(prev_active, prev_selected)


def _apply_mesh_modifiers(obj: bpy.types.Object) -> int:
    count = 0
    for mod in list(obj.modifiers):
        if mod.type == "ARMATURE":
            continue
        try:
            res = bpy.ops.object.modifier_apply(modifier=mod.name)
            if "FINISHED" in set(res or []):
                count += 1
        except Exception:
            pass
    return count


def _remove_shape_keys(obj: bpy.types.Object) -> int:
    data = obj.data
    if not data or not getattr(data, "shape_keys", None):
        return 0
    key_count = len(data.shape_keys.key_blocks)
    if key_count <= 0:
        return 0
    try:
        bpy.ops.object.shape_key_remove(all=True, apply_mix=True)
    except TypeError:
        try:
            bpy.ops.object.shape_key_remove(all=True)
        except Exception:
            return 0
    except Exception:
        return 0
    return key_count


def _clear_vertex_groups(obj: bpy.types.Object) -> int:
    data = obj.data
    if not data or not getattr(data, "vertex_groups", None):
        return 0
    n = len(data.vertex_groups)
    if n <= 0:
        return 0
    data.vertex_groups.clear()
    return n


def _remove_mesh_attributes(
    mesh: bpy.types.Mesh,
    *,
    color_only: bool,
) -> int:
    attrs = getattr(mesh, "attributes", None)
    if attrs is None:
        return 0
    to_remove: List[str] = []
    for attr in attrs:
        if not _is_removable_mesh_attribute(attr):
            continue
        if _is_uv_mesh_attribute(attr, mesh):
            continue
        dtype = str(getattr(attr, "data_type", "") or "")
        is_color = dtype in _COLOR_ATTRIBUTE_TYPES
        if color_only and not is_color:
            continue
        if not color_only and is_color:
            continue
        to_remove.append(attr.name)
    removed = 0
    for name in to_remove:
        try:
            attrs.remove(attrs[name])
            removed += 1
        except Exception:
            pass
    return removed


def _clean_uv_layers(mesh: bpy.types.Mesh) -> int:
    layers = getattr(mesh, "uv_layers", None)
    if layers is None or len(layers) == 0:
        return 0
    active = layers.active
    keep_name = active.name if active else layers[0].name
    removed = 0
    for layer in list(layers):
        if layer.name == keep_name:
            continue
        try:
            layers.remove(layer)
            removed += 1
        except Exception:
            pass
    return removed


def _clean_single_mesh(obj: bpy.types.Object, opts: MeshCleanupOptions, result: MeshCleanupResult) -> None:
    if obj.type != "MESH" or obj.data is None:
        return
    if _is_linked_mesh(obj):
        result.skipped.append(obj.name)
        return

    _ensure_object_mode()
    with _with_active_mesh(obj):
        mesh = obj.data
        if opts.apply_modifiers:
            result.modifiers_applied += _apply_mesh_modifiers(obj)
        if opts.apply_shape_keys:
            result.shape_keys_removed += _remove_shape_keys(obj)
        if opts.clean_vertex_groups:
            result.vertex_groups_cleared += _clear_vertex_groups(obj)
        if opts.clean_color_attributes:
            result.color_attributes_removed += _remove_mesh_attributes(mesh, color_only=True)
        if opts.clean_custom_attributes:
            result.attributes_removed += _remove_mesh_attributes(mesh, color_only=False)
        if opts.clean_uv_maps:
            result.uv_layers_removed += _clean_uv_layers(mesh)

    result.meshes_processed += 1


def collect_meshes_for_cleanup(
    *,
    selected: Sequence[bpy.types.Object],
    tree_root: Optional[bpy.types.Object] = None,
) -> List[bpy.types.Object]:
    meshes = [o for o in selected if o is not None and o.type == "MESH"]
    if meshes:
        return meshes
    if tree_root is None:
        return []
    out: List[bpy.types.Object] = []
    seen: set[int] = set()
    for sub in iter_subobjects_recursive(tree_root):
        if sub.type != "MESH" or id(sub) in seen:
            continue
        seen.add(id(sub))
        out.append(sub)
    return out


def run_mesh_cleanup(
    meshes: Iterable[bpy.types.Object],
    opts: MeshCleanupOptions,
) -> MeshCleanupResult:
    result = MeshCleanupResult()
    if not any(
        (
            opts.apply_modifiers,
            opts.apply_shape_keys,
            opts.clean_vertex_groups,
            opts.clean_color_attributes,
            opts.clean_custom_attributes,
            opts.clean_uv_maps,
        )
    ):
        result.errors.append("No cleanup options enabled.")
        return result

    for obj in meshes:
        if obj is None:
            continue
        try:
            _clean_single_mesh(obj, opts, result)
        except Exception as ex:
            result.errors.append(f"{obj.name}: {ex}")

    return result
