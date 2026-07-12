"""
Blender rig link adapter (bpy) for the MonoFX Pipeline add-on.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import bpy

from . import rig_naming
from monofx_pipeline_common.project_layout import find_project_root, parse_asset_from_project_path
from monofx_pipeline_common.rig_library import suggest_namespace_from_asset

ASSET_ROOT_PREFIX = "Geo_"


def asset_collection_name_for(asset_slug: str) -> str:
    slug = (asset_slug or "Asset").strip()
    if slug.startswith(ASSET_ROOT_PREFIX):
        return slug
    return f"{ASSET_ROOT_PREFIX}{slug}"


def is_available() -> bool:
    return True


def get_scene_path() -> Optional[str]:
    p = str(getattr(bpy.data, "filepath", "") or "").strip()
    if not p:
        return None
    try:
        return os.path.normpath(os.path.realpath(p))
    except OSError:
        return os.path.normpath(p)


def scene_is_modified() -> bool:
    return bool(bpy.data.is_dirty)


def open_scene_path(path: str, *, force: bool = False) -> None:
    del force
    bpy.ops.wm.open_mainfile(filepath=os.path.normpath(path), load_ui=True)


def open_scene_path_new_session(path: str) -> None:
    """Open a .blend file in a new Blender process (leave the current session untouched)."""
    fp = os.path.normpath(path)
    if not os.path.isfile(fp):
        raise RuntimeError(f"File not found: {fp}")
    exe = str(getattr(bpy.app, "binary_path", "") or "").strip()
    if not exe:
        raise RuntimeError("Could not resolve Blender executable path.")
    kwargs: dict = {}
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0)
        if creationflags:
            kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([exe, fp], **kwargs)


def _abs_path(path: str) -> str:
    try:
        return os.path.normpath(bpy.path.abspath(path))
    except Exception:
        return os.path.normpath(os.path.abspath(path))


def _file_exists(path: str) -> bool:
    if not path:
        return False
    try:
        return os.path.isfile(_abs_path(path))
    except OSError:
        return False


def _file_path_in_project_root(resolved: str, project_root_norm: str) -> bool:
    try:
        r = os.path.normcase(os.path.normpath(os.path.realpath(resolved)))
        p = os.path.normcase(os.path.normpath(project_root_norm))
        return r == p or r.startswith(p + os.sep)
    except OSError:
        r = os.path.normcase(os.path.normpath(resolved))
        p = os.path.normcase(os.path.normpath(project_root_norm))
        return r == p or r.startswith(p + os.sep)


def _ref_id_for_library(lib: bpy.types.Library) -> str:
    return f"lib::{lib.name}"


def _ref_id_for_override(ov_coll: bpy.types.Collection, lib: bpy.types.Library) -> str:
    return f"lib::{lib.name}::ov::{ov_coll.name}"


def _parse_ref_id(ref_id: str) -> Tuple[str, str, str]:
    """Return ``(library_name, legacy_collection_name, override_root_name)``."""
    raw = str(ref_id or "").strip()
    if raw.startswith("lib::"):
        tail = raw[5:]
        parts = [p for p in tail.split("::") if p != ""]
        if not parts:
            return "", "", ""
        lib_name = parts[0].strip()
        if len(parts) >= 3 and parts[1] == "ov":
            return lib_name, "", parts[2].strip()
        if len(parts) >= 2:
            return lib_name, parts[1].strip(), ""
        return lib_name, "", ""
    if "::" in raw:
        lib_name, coll_name = raw.split("::", 1)
        return lib_name.strip(), coll_name.strip(), ""
    return raw, "", ""


def _collection_in_any_view_layer(coll: bpy.types.Collection) -> bool:
    if coll is None:
        return False
    name = coll.name
    for scene in bpy.data.scenes:
        for layer in scene.view_layers:
            try:
                if name in layer.layer_collection.collection.children_recursive:
                    return True
            except Exception:
                pass
            if layer.layer_collection.collection == coll:
                return True
    for scene in bpy.data.scenes:
        try:
            if coll.name in {c.name for c in scene.collection.children_recursive}:
                return True
        except Exception:
            pass
        if scene.collection == coll:
            return True
    return coll.users > 0


def _is_rig_library_path(resolved: str) -> bool:
    if not resolved or not resolved.lower().endswith(".blend"):
        return False
    low = resolved.replace("\\", "/").lower()
    return "/02_rigging/" in low or "_rig_" in low


def _is_rig_library(lib: bpy.types.Library) -> bool:
    unresolved = str(lib.filepath or "")
    resolved = _abs_path(unresolved) if unresolved else ""
    return _is_rig_library_path(resolved)


def _source_library_for_collection(coll: bpy.types.Collection) -> Optional[bpy.types.Library]:
    if coll.library is not None:
        return coll.library
    if coll.override_library is not None:
        ref: Any = coll.override_library.reference
        seen: Set[int] = set()
        while ref is not None and id(ref) not in seen:
            seen.add(id(ref))
            if getattr(ref, "library", None) is not None:
                return ref.library
            ov = getattr(ref, "override_library", None)
            ref = ov.reference if ov is not None else None
    return None


def _collection_rig_paths(coll: bpy.types.Collection) -> Tuple[str, str]:
    lib = _source_library_for_collection(coll)
    if lib is None:
        return "", ""
    unresolved = str(lib.filepath or "")
    resolved = _abs_path(unresolved) if unresolved else ""
    return unresolved, resolved


def _collections_for_library(lib: bpy.types.Library) -> List[bpy.types.Collection]:
    out: List[bpy.types.Collection] = []
    for coll in bpy.data.collections:
        if coll.library == lib or _source_library_for_collection(coll) == lib:
            out.append(coll)
    return out


def _library_is_loaded(lib: bpy.types.Library) -> bool:
    for coll in _collections_for_library(lib):
        if not _collection_in_any_view_layer(coll):
            continue
        if not coll.hide_viewport:
            return True
    for obj in bpy.data.objects:
        if obj.library != lib:
            continue
        if obj.override_library is not None or obj.library == lib:
            if not obj.hide_viewport:
                return True
    return False


def _display_name_for_library(lib: bpy.types.Library, resolved: str) -> str:
    if resolved:
        return Path(resolved).stem
    return lib.name


def _row_from_library(lib: bpy.types.Library, project_root: Optional[str]) -> Dict[str, Any]:
    unresolved = str(lib.filepath or "")
    resolved = _abs_path(unresolved) if unresolved else ""
    exists = _file_exists(resolved) if resolved else False
    in_proj: Optional[bool] = None
    if project_root and resolved:
        in_proj = _file_path_in_project_root(resolved, project_root)
    ref_id = _ref_id_for_library(lib)
    has_override = any(c.override_library is not None for c in _collections_for_library(lib))
    return {
        "ref_id": ref_id,
        "ref_node_long": ref_id,
        "ref_node_short": ref_id,
        "namespace": _display_name_for_library(lib, resolved),
        "collection_name": "",
        "library_name": lib.name,
        "is_override": has_override,
        "unresolved_path": unresolved,
        "resolved_path": resolved,
        "is_loaded": _library_is_loaded(lib),
        "exists_on_disk": exists,
        "in_project": in_proj,
    }


def _row_from_override(
    ov_coll: bpy.types.Collection,
    lib: bpy.types.Library,
    project_root: Optional[str],
) -> Dict[str, Any]:
    unresolved = str(lib.filepath or "")
    resolved = _abs_path(unresolved) if unresolved else ""
    exists = _file_exists(resolved) if resolved else False
    in_proj: Optional[bool] = None
    if project_root and resolved:
        in_proj = _file_path_in_project_root(resolved, project_root)
    ref_id = _ref_id_for_override(ov_coll, lib)
    loaded = _collection_in_any_view_layer(ov_coll) and not ov_coll.hide_viewport
    return {
        "ref_id": ref_id,
        "ref_node_long": ref_id,
        "ref_node_short": ref_id,
        "namespace": ov_coll.name,
        "collection_name": ov_coll.name,
        "library_name": lib.name,
        "is_override": True,
        "unresolved_path": unresolved,
        "resolved_path": resolved,
        "is_loaded": loaded,
        "exists_on_disk": exists,
        "in_project": in_proj,
    }


def _is_override_hierarchy_root(coll: bpy.types.Collection) -> bool:
    ov = coll.override_library
    if ov is None:
        return False
    root = getattr(ov, "hierarchy_root", None)
    return root is None or root == coll


def _parent_collections(coll: bpy.types.Collection) -> List[bpy.types.Collection]:
    parents: List[bpy.types.Collection] = []
    name = coll.name
    for parent in bpy.data.collections:
        if parent == coll:
            continue
        try:
            if name in parent.children:
                parents.append(parent)
        except Exception:
            pass
    for scene in bpy.data.scenes:
        try:
            if name in scene.collection.children:
                parents.append(scene.collection)
        except Exception:
            pass
    return parents


def _unhide_collection_chain(coll: bpy.types.Collection) -> None:
    """Unhide *coll* and every ancestor collection (hidden parents hide children)."""
    if coll is None:
        return
    seen: Set[int] = set()
    stack = [coll]
    while stack:
        current = stack.pop()
        key = id(current)
        if key in seen:
            continue
        seen.add(key)
        try:
            current.hide_viewport = False
            current.hide_render = False
        except Exception:
            pass
        for parent in _parent_collections(current):
            stack.append(parent)


def _unhide_rig_subtree(rig_coll: bpy.types.Collection) -> None:
    _unhide_collection_chain(rig_coll)
    for child in _iter_child_collections_recursive(rig_coll):
        try:
            child.hide_viewport = False
            child.hide_render = False
        except Exception:
            pass
    for obj in rig_coll.all_objects:
        try:
            obj.hide_viewport = False
            obj.hide_render = False
        except Exception:
            pass


def _ensure_rig_in_view_layer(
    rig_coll: bpy.types.Collection,
    parent_col: bpy.types.Collection,
) -> None:
    view_layer = bpy.context.view_layer
    if view_layer is not None and _collection_in_view_layer(rig_coll, view_layer):
        return
    scene_col = bpy.context.scene.collection if bpy.context.scene else None
    if parent_col is not None and parent_col != rig_coll:
        if _ensure_collection_parent(rig_coll, parent_col):
            if view_layer is None or _collection_in_view_layer(rig_coll, view_layer):
                return
    if scene_col is not None:
        _unlink_collection_from_hierarchy(rig_coll)
        _ensure_collection_parent(rig_coll, scene_col)


def _ensure_rig_visible(
    rig_coll: bpy.types.Collection,
    parent_col: Optional[bpy.types.Collection] = None,
) -> None:
    if parent_col is not None:
        _ensure_rig_in_view_layer(rig_coll, parent_col)
    else:
        scene_col = bpy.context.scene.collection if bpy.context.scene else None
        if scene_col is not None:
            _ensure_rig_in_view_layer(rig_coll, scene_col)
    _unhide_rig_subtree(rig_coll)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


def _is_publish_override_name(name: str) -> bool:
    return "_publish" in (name or "").lower()


def _override_roots_for_scene_list() -> List[Tuple[bpy.types.Collection, bpy.types.Library]]:
    """Override roots shown in Scene Links (skip orphan Geo/Rig rows when publish exists)."""
    all_roots = _override_roots_for_rig_libraries()
    libs_with_publish: Set[int] = set()
    for coll, lib in all_roots:
        if _is_publish_override_name(coll.name):
            libs_with_publish.add(id(lib))

    filtered: List[Tuple[bpy.types.Collection, bpy.types.Library]] = []
    for coll, lib in all_roots:
        if _is_publish_override_name(coll.name):
            filtered.append((coll, lib))
        elif id(lib) not in libs_with_publish:
            filtered.append((coll, lib))
    return filtered


def _override_roots_for_rig_libraries() -> List[Tuple[bpy.types.Collection, bpy.types.Library]]:
    out: List[Tuple[bpy.types.Collection, bpy.types.Library]] = []
    seen: Set[int] = set()
    for coll in bpy.data.collections:
        if not _is_override_hierarchy_root(coll):
            continue
        lib = _source_library_for_collection(coll)
        if lib is None or not _is_rig_library(lib):
            continue
        key = id(coll)
        if key in seen:
            continue
        seen.add(key)
        out.append((coll, lib))
    return sorted(out, key=lambda pair: pair[0].name.lower())


def _rig_libraries_in_scene() -> List[bpy.types.Library]:
    """One entry per rig ``.blend`` library (Blender File > Libraries)."""
    by_path: Dict[str, bpy.types.Library] = {}
    for lib in bpy.data.libraries:
        if not _is_rig_library(lib):
            continue
        resolved = _abs_path(lib.filepath)
        key = os.path.normcase(resolved)
        current = by_path.get(key)
        if current is None or lib.users > current.users:
            by_path[key] = lib
    return sorted(by_path.values(), key=lambda lib: _abs_path(lib.filepath).lower())


def collect_file_references(project_root: Optional[str] = None) -> List[Dict[str, Any]]:
    pr_norm: Optional[str] = None
    if project_root and str(project_root).strip():
        try:
            pr_norm = os.path.normpath(os.path.realpath(str(project_root)))
        except OSError:
            pr_norm = os.path.normpath(str(project_root))

    rows = [_row_from_override(ov_coll, lib, pr_norm) for ov_coll, lib in _override_roots_for_scene_list()]
    if rows:
        return rows

    return [_row_from_library(lib, pr_norm) for lib in _rig_libraries_in_scene()]


def _override_for_ref(ref_id: str) -> Optional[bpy.types.Collection]:
    lib_name, _legacy_coll, ov_name = _parse_ref_id(ref_id)
    if not ov_name:
        return None
    coll = bpy.data.collections.get(ov_name)
    if coll is None or coll.override_library is None:
        return None
    if lib_name:
        lib = _source_library_for_collection(coll)
        if lib is not None and lib.name != lib_name:
            return None
    return coll


def _library_for_ref(ref_id: str) -> bpy.types.Library:
    ov_coll = _override_for_ref(ref_id)
    if ov_coll is not None:
        lib = _source_library_for_collection(ov_coll)
        if lib is not None and _is_rig_library(lib):
            return lib

    lib_name, _legacy_coll, _ov_name = _parse_ref_id(ref_id)
    if lib_name and lib_name in bpy.data.libraries:
        lib = bpy.data.libraries[lib_name]
        if _is_rig_library(lib):
            return lib
    for lib in _rig_libraries_in_scene():
        if _ref_id_for_library(lib) == ref_id:
            return lib
        if lib_name and lib.name == lib_name:
            return lib
    raise RuntimeError(f"Rig library not found: {ref_id}")


def _iter_child_collections_recursive(coll: bpy.types.Collection):
    for child in coll.children:
        yield child
        yield from _iter_child_collections_recursive(child)


def _library_source_name(id_block: bpy.types.ID) -> Optional[str]:
    """Linked source datablock name from a library override (no namespace)."""
    ov = getattr(id_block, "override_library", None)
    if ov is None:
        return None
    ref = getattr(ov, "reference", None)
    if ref is None:
        return None
    name = str(getattr(ref, "name", "") or "").strip()
    return name or None


def _target_prefixed_name_for_reload(
    id_block: bpy.types.ID,
    prefix: str,
    asset_folder: str,
) -> str:
    return rig_naming.namespace_prefixed_name(
        id_block.name,
        prefix,
        asset_folder,
        library_source_name=_library_source_name(id_block),
    )


def _object_in_override_tree(obj: bpy.types.Object, ov_coll: bpy.types.Collection) -> bool:
    try:
        return obj.name in {o.name for o in ov_coll.all_objects}
    except Exception:
        return False


def _collection_in_override_tree(
    coll: bpy.types.Collection,
    ov_coll: bpy.types.Collection,
) -> bool:
    if coll == ov_coll:
        return True
    try:
        names = {c.name for c in _iter_child_collections_recursive(ov_coll)}
        names.add(ov_coll.name)
        return coll.name in names
    except Exception:
        return False


def _name_externally_taken(
    target_name: str,
    ov_coll: bpy.types.Collection,
) -> bool:
    if not target_name:
        return False
    obj = bpy.data.objects.get(target_name)
    if obj is not None and not _object_in_override_tree(obj, ov_coll):
        return True
    coll = bpy.data.collections.get(target_name)
    if coll is not None and not _collection_in_override_tree(coll, ov_coll):
        return True
    return False


def _planned_reload_targets(
    ov_coll: bpy.types.Collection,
    prefix: str,
    asset_folder: str,
) -> list[str]:
    targets: list[str] = []
    for obj in ov_coll.all_objects:
        if obj.type == "ARMATURE":
            continue
        targets.append(_target_prefixed_name_for_reload(obj, prefix, asset_folder))
    for coll in _iter_child_collections_recursive(ov_coll):
        targets.append(_target_prefixed_name_for_reload(coll, prefix, asset_folder))
    return targets


def _resolve_reload_prefix(
    ov_coll: bpy.types.Collection,
    initial_prefix: str,
    asset_folder: str,
) -> str:
    """
    Pick a namespace prefix whose planned reload names do not collide outside this rig.

    Bumps ``tachirig::`` → ``tachirig2::`` when another scene datablock already owns a target name.
    """
    base = rig_naming.rig_prefix_base_from_asset_folder(asset_folder)
    canonical = rig_naming.migrate_prefix_to_canonical(initial_prefix, asset_folder)
    tried: set[str] = set()
    candidates = (canonical, *rig_naming.iter_rig_hierarchy_prefix_candidates(base))
    for candidate in candidates:
        prefix = rig_naming.migrate_prefix_to_canonical(candidate, asset_folder)
        if prefix in tried:
            continue
        tried.add(prefix)
        if not any(
            _name_externally_taken(target, ov_coll)
            for target in _planned_reload_targets(ov_coll, prefix, asset_folder)
        ):
            return prefix
    return canonical


def _rename_id_with_prefix(
    id_block: bpy.types.ID,
    prefix: str,
    asset_folder: str,
) -> bool:
    if not isinstance(id_block, (bpy.types.Object, bpy.types.Collection)):
        return False
    new_name = _target_prefixed_name_for_reload(id_block, prefix, asset_folder)
    if not new_name or new_name == id_block.name:
        return False

    ov = getattr(id_block, "override_library", None)
    if getattr(id_block, "library", None) is not None and ov is None:
        return False

    try:
        id_block.name = new_name
    except Exception:
        try:
            rename_fn = getattr(id_block, "rename", None)
            if callable(rename_fn):
                rename_fn(new_name)
            else:
                return False
        except Exception:
            return False

    return id_block.name == new_name


def _sync_rig_prefix_overrides(ov_coll: bpy.types.Collection) -> None:
    """Persist override renames with one update on the rig root (not per mesh)."""
    ov = getattr(ov_coll, "override_library", None)
    if ov is None:
        return
    try:
        ov.operations_update()
    except Exception:
        pass


def _list_collections_in_blend(filepath: str) -> List[str]:
    fp = os.path.normpath(filepath)
    try:
        with bpy.data.libraries.load(fp, link=False) as (data_from, _data_to):
            return list(data_from.collections)
    except Exception:
        return []


def _rig_collection_name_for_asset(asset_folder: str) -> str:
    slug = (asset_folder or "").strip() or "Asset"
    if slug.lower().startswith("rig_"):
        return slug
    return f"Rig_{slug}"


def _pick_collection_name(filepath: str, namespace: str) -> str:
    names = _list_collections_in_blend(filepath)
    if not names:
        raise RuntimeError(f"No collections found in rig file: {filepath}")

    publish_names = [n for n in names if "_publish" in n.lower()]
    if not publish_names:
        raise RuntimeError(
            f"No *_publish* collection found in rig file: {filepath}. "
            f"Available collections: {', '.join(names)}"
        )
    if len(publish_names) == 1:
        return publish_names[0]

    preferred = _rig_collection_name_for_asset(namespace)
    for n in publish_names:
        if n == preferred:
            return n
    for n in publish_names:
        if n.lower().startswith("rig_"):
            return n

    p = Path(filepath)
    parsed_asset: Optional[str] = None
    try:
        m = re.match(r"(.+)_rig_", p.stem, re.IGNORECASE)
        if m:
            parsed_asset = m.group(1)
    except Exception:
        parsed_asset = None
    if parsed_asset:
        cand = _rig_collection_name_for_asset(parsed_asset)
        for n in publish_names:
            if n == cand:
                return n

    publish_names.sort(key=lambda s: s.lower())
    return publish_names[0]


def _find_layer_collection_for_collection(
    layer_coll: bpy.types.LayerCollection,
    collection: bpy.types.Collection,
) -> Optional[bpy.types.LayerCollection]:
    if layer_coll.collection == collection:
        return layer_coll
    for child in layer_coll.children:
        found = _find_layer_collection_for_collection(child, collection)
        if found is not None:
            return found
    return None


def _collection_in_view_layer(coll: bpy.types.Collection, view_layer: bpy.types.ViewLayer) -> bool:
    if coll is None or view_layer is None:
        return False
    return _find_layer_collection_for_collection(view_layer.layer_collection, coll) is not None


def _object_in_view_layer(obj: bpy.types.Object, view_layer: bpy.types.ViewLayer) -> bool:
    if obj is None or view_layer is None:
        return False
    try:
        return obj.name in view_layer.objects
    except Exception:
        return False


def _set_active_layer_collection_for(parent_col: bpy.types.Collection) -> bool:
    view_layer = bpy.context.view_layer
    if view_layer is None:
        return False
    layer_coll = _find_layer_collection_for_collection(view_layer.layer_collection, parent_col)
    if layer_coll is None:
        return False
    view_layer.active_layer_collection = layer_coll
    return True


def _resolve_target_parent_collection(filepath: str, namespace: str) -> bpy.types.Collection:
    """Prefer the active layer collection; fall back to Geo_<Asset> in view layer, else scene root."""
    view_layer = bpy.context.view_layer
    scene_col = bpy.context.scene.collection
    if view_layer is not None and view_layer.active_layer_collection is not None:
        active_col = view_layer.active_layer_collection.collection
        if active_col is not None:
            return active_col

    asset_col_name: Optional[str] = None
    scene_path = get_scene_path()
    if scene_path:
        root = find_project_root(Path(scene_path))
        if root:
            parsed = parse_asset_from_project_path(Path(filepath), root)
            if parsed:
                _, asset_folder = parsed
                asset_col_name = asset_collection_name_for(asset_folder)
    if not asset_col_name and namespace:
        asset_col_name = asset_collection_name_for(namespace)
    if asset_col_name and asset_col_name in bpy.data.collections:
        asset_col = bpy.data.collections[asset_col_name]
        if view_layer is None or _collection_in_view_layer(asset_col, view_layer):
            return asset_col
    return scene_col


def _unlink_collection_from_hierarchy(coll: bpy.types.Collection) -> None:
    for scene in bpy.data.scenes:
        try:
            if coll.name in scene.collection.children:
                scene.collection.children.unlink(coll)
        except RuntimeError:
            pass
    for parent in bpy.data.collections:
        if parent == coll:
            continue
        try:
            if coll.name in parent.children:
                parent.children.unlink(coll)
        except RuntimeError:
            pass


def _ensure_collection_parent(coll: bpy.types.Collection, parent_col: bpy.types.Collection) -> bool:
    if coll == parent_col:
        return True
    if coll.name in parent_col.children:
        return True
    try:
        parent_col.children.link(coll)
        return coll.name in parent_col.children
    except RuntimeError:
        return coll.name in parent_col.children


def _find_library_by_filepath(filepath: str) -> Optional[bpy.types.Library]:
    fp_key = os.path.normcase(os.path.normpath(filepath))
    for lib in bpy.data.libraries:
        if os.path.normcase(_abs_path(lib.filepath)) == fp_key:
            return lib
    return None


def _find_plain_linked_collection(
    lib: bpy.types.Library,
    coll_name: str,
) -> Optional[bpy.types.Collection]:
    """Linked source collection from a library (not a local override copy)."""
    for coll in bpy.data.collections:
        if coll.library == lib and coll.name == coll_name:
            return coll
    return None


def _all_overrides_for_linked(linked: bpy.types.Collection) -> List[bpy.types.Collection]:
    out: List[bpy.types.Collection] = []
    for coll in bpy.data.collections:
        ov = coll.override_library
        if ov is not None and ov.reference == linked:
            out.append(coll)
    return out


def _make_library_override(linked: bpy.types.Collection) -> bpy.types.Collection:
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    if scene is None or view_layer is None:
        raise RuntimeError("No active scene/view layer for library override")

    if linked.library is None:
        raise RuntimeError("Expected a linked collection to create a library override")

    before_ids = {id(coll) for coll in _all_overrides_for_linked(linked)}

    try:
        result = linked.override_hierarchy_create(
            scene=scene,
            view_layer=view_layer,
            do_fully_editable=False,
        )
    except Exception as e:
        raise RuntimeError(f"Could not create library override: {e}") from e

    if isinstance(result, bpy.types.Collection) and id(result) not in before_ids:
        return result

    for coll in _all_overrides_for_linked(linked):
        if id(coll) not in before_ids:
            return coll

    raise RuntimeError("Library override was not created")


def _consolidate_rig_hierarchy(
    linked: bpy.types.Collection,
    override_coll: bpy.types.Collection,
    parent_col: bpy.types.Collection,
) -> bpy.types.Collection:
    """
    Keep a single rig collection under *parent_col*.

    ``override_hierarchy_create`` may leave the plain link in the active collection
    and spawn the override at scene root — remove the duplicate link tree.
    """
    if linked != override_coll:
        _unlink_collection_from_hierarchy(linked)

    _unlink_collection_from_hierarchy(override_coll)
    scene_col = bpy.context.scene.collection if bpy.context.scene else None
    if not _ensure_collection_parent(override_coll, parent_col) and scene_col is not None:
        _ensure_collection_parent(override_coll, scene_col)
    return override_coll


def _asset_folder_for_link(filepath: str, namespace: str) -> str:
    scene_path = get_scene_path()
    if scene_path:
        root = find_project_root(Path(scene_path))
        if root:
            parsed = parse_asset_from_project_path(Path(filepath), root)
            if parsed:
                return parsed[1]
    return (namespace or Path(filepath).stem).strip()


def _hierarchy_prefix_in_use(
    prefix: str,
    scope: Optional[bpy.types.Collection] = None,
    asset_folder: Optional[str] = None,
) -> bool:
    forms = (
        list(rig_naming.iter_prefix_equivalent_forms(prefix, asset_folder))
        if asset_folder
        else [prefix]
    )

    def _matches(name: str) -> bool:
        return any(name.startswith(form) for form in forms)

    if scope is not None:
        for obj in scope.all_objects:
            if _matches(obj.name):
                return True
        for coll in _iter_child_collections_recursive(scope):
            if _matches(coll.name):
                return True
        return False
    for obj in bpy.data.objects:
        if _matches(obj.name):
            return True
    for coll in bpy.data.collections:
        if _matches(coll.name):
            return True
    return False


def _set_override_user_editable(id_block: bpy.types.ID) -> None:
    ov = getattr(id_block, "override_library", None)
    if ov is None:
        return
    try:
        ov.is_system_override = False
    except Exception:
        pass


def _prepare_rig_prefix_renames(
    rig_coll: bpy.types.Collection,
    prefix: str,
    asset_folder: str,
) -> None:
    for obj in rig_coll.all_objects:
        if obj.type == "ARMATURE":
            continue
        if _target_prefixed_name_for_reload(obj, prefix, asset_folder) != obj.name:
            _set_override_user_editable(obj)
    for coll in _iter_child_collections_recursive(rig_coll):
        if _target_prefixed_name_for_reload(coll, prefix, asset_folder) != coll.name:
            _set_override_user_editable(coll)


def _ensure_rig_armature_editable(rig_coll: bpy.types.Collection) -> None:
    for obj in rig_coll.all_objects:
        if obj.type == "ARMATURE":
            _set_override_user_editable(obj)
            return


def _allocate_rig_hierarchy_prefix(
    asset_folder: str,
    scope: Optional[bpy.types.Collection] = None,
) -> str:
    return rig_naming.unique_rig_hierarchy_prefix(
        asset_folder,
        lambda prefix: _hierarchy_prefix_in_use(prefix, scope, asset_folder),
    )


def _apply_rig_hierarchy_prefix(
    rig_coll: bpy.types.Collection,
    prefix: str,
    asset_folder: str,
) -> int:
    """Prefix non-armature object and collection names inside a linked rig."""
    renamed = 0
    objects = sorted(rig_coll.all_objects, key=lambda o: len(o.name), reverse=True)
    for obj in objects:
        if obj.type == "ARMATURE":
            continue
        if _rename_id_with_prefix(obj, prefix, asset_folder):
            renamed += 1

    child_cols = sorted(
        list(_iter_child_collections_recursive(rig_coll)),
        key=lambda c: len(c.name),
        reverse=True,
    )
    for child in child_cols:
        if _rename_id_with_prefix(child, prefix, asset_folder):
            renamed += 1
    _sync_rig_prefix_overrides(rig_coll)
    return renamed


def _rig_hierarchy_prefix_for_override(ov_coll: bpy.types.Collection) -> Optional[str]:
    lib = _source_library_for_collection(ov_coll)
    if lib is None:
        return None
    resolved = _abs_path(lib.filepath) if lib.filepath else ""
    asset_folder = _asset_folder_for_link(resolved, ov_coll.name)
    names = [obj.name for obj in ov_coll.all_objects if obj.type != "ARMATURE"]
    names.extend(child.name for child in _iter_child_collections_recursive(ov_coll))
    if ov_coll.name:
        names.append(ov_coll.name)
    prefix = rig_naming.detect_rig_hierarchy_prefix_from_names(names, asset_folder)
    if prefix:
        return prefix
    base = rig_naming.rig_prefix_base_from_asset_folder(asset_folder)
    for candidate in rig_naming.iter_all_rig_hierarchy_prefix_candidates(base):
        if _hierarchy_prefix_in_use(candidate, ov_coll, asset_folder):
            return rig_naming.migrate_prefix_to_canonical(candidate, asset_folder)
    return rig_naming.unique_rig_hierarchy_prefix(
        asset_folder,
        lambda p: _hierarchy_prefix_in_use(p, ov_coll, asset_folder),
    )


def _reapply_rig_hierarchy_prefix_for_ref(ref_node_short: str) -> int:
    ov_coll = _override_for_ref(ref_node_short)
    if ov_coll is None:
        return 0
    lib = _source_library_for_collection(ov_coll)
    if lib is None:
        return 0
    resolved = _abs_path(lib.filepath) if lib.filepath else ""
    asset_folder = _asset_folder_for_link(resolved, ov_coll.name)
    prefix = _rig_hierarchy_prefix_for_override(ov_coll)
    if not prefix:
        return 0
    prefix = _resolve_reload_prefix(ov_coll, prefix, asset_folder)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    ov_coll = _override_for_ref(ref_node_short) or ov_coll
    _prepare_rig_prefix_renames(ov_coll, prefix, asset_folder)
    return _apply_rig_hierarchy_prefix(ov_coll, prefix, asset_folder)


def _ensure_plain_linked_collection(
    filepath: str,
    coll_name: str,
    parent_col: bpy.types.Collection,
) -> bpy.types.Collection:
    """
    Return the plain linked source collection for *coll_name*.

    When the same rig file is already linked, re-use that datablock instead of
    calling ``wm.link`` again (which would move the existing link).
    """
    fp = os.path.normpath(filepath)
    lib = _find_library_by_filepath(fp)
    if lib is not None:
        linked = _find_plain_linked_collection(lib, coll_name)
        if linked is not None:
            return linked

    _set_active_layer_collection_for(parent_col)
    directory = fp + "/Collection/"
    try:
        bpy.ops.wm.link(
            filepath=os.path.join(directory, coll_name),
            directory=directory,
            filename=coll_name,
            instance_collections=False,
            active_collection=True,
        )
    except Exception as e:
        raise RuntimeError(f"Could not link rig collection: {e}") from e

    lib = _find_library_by_filepath(fp)
    if lib is None:
        raise RuntimeError(f"Rig library not found after link: {fp}")
    linked = _find_plain_linked_collection(lib, coll_name)
    if linked is None:
        raise RuntimeError(f"Linked collection not found after link: {coll_name}")
    return linked


def create_file_reference(path: str, namespace: str) -> str:
    fp = os.path.normpath(path)
    if not os.path.isfile(fp):
        raise RuntimeError(f"Rig file not found: {fp}")

    ns = suggest_namespace_from_asset(namespace or Path(fp).stem)
    coll_name = _pick_collection_name(fp, ns)
    parent_col = _resolve_target_parent_collection(fp, ns)

    linked = _ensure_plain_linked_collection(fp, coll_name, parent_col)
    override_coll = _make_library_override(linked)
    rig_coll = _consolidate_rig_hierarchy(linked, override_coll, parent_col)
    asset_folder = _asset_folder_for_link(fp, ns)
    prefix = _allocate_rig_hierarchy_prefix(asset_folder, parent_col)
    _prepare_rig_prefix_renames(rig_coll, prefix, asset_folder)
    _apply_rig_hierarchy_prefix(rig_coll, prefix, asset_folder)
    _ensure_rig_armature_editable(rig_coll)
    _ensure_rig_visible(rig_coll, parent_col)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    _set_active_layer_collection_for(parent_col)
    lib = _source_library_for_collection(rig_coll)
    if lib is None:
        raise RuntimeError("Linked rig library not found after link")
    return _ref_id_for_override(rig_coll, lib)


def _library_has_override_usage(lib: bpy.types.Library) -> bool:
    for coll in bpy.data.collections:
        if coll.override_library is None:
            continue
        if _source_library_for_collection(coll) == lib:
            return True
    return False


def load_reference_node(ref_node_short: str) -> None:
    ov_coll = _override_for_ref(ref_node_short)
    if ov_coll is not None:
        _ensure_rig_visible(ov_coll)
        return

    lib = _library_for_ref(ref_node_short)
    for coll in _collections_for_library(lib):
        if not _collection_in_any_view_layer(coll):
            continue
        _unhide_rig_subtree(coll)


def unload_reference_node(ref_node_short: str) -> None:
    ov_coll = _override_for_ref(ref_node_short)
    if ov_coll is not None:
        ov_coll.hide_viewport = True
        ov_coll.hide_render = True
        return

    lib = _library_for_ref(ref_node_short)
    for coll in _collections_for_library(lib):
        coll.hide_viewport = True
        coll.hide_render = True


class RigPrefixReapplySession:
    """Incrementally re-apply rig namespace prefixes after a library reload."""

    def __init__(self, ref_id: str) -> None:
        self.ref_id = ref_id
        self._queue: List[Tuple[str, str]] = []
        self._prefix = ""
        self._asset_folder = ""
        self._ov_coll_name = ""
        self._index = 0
        self._renamed = 0

    @property
    def total(self) -> int:
        return len(self._queue)

    @property
    def current(self) -> int:
        return self._index

    @property
    def done(self) -> bool:
        return self._index >= len(self._queue)

    def prepare(self) -> Optional[str]:
        ov_coll = _override_for_ref(self.ref_id)
        if ov_coll is None:
            return None
        lib = _source_library_for_collection(ov_coll)
        if lib is None:
            return None
        resolved = _abs_path(lib.filepath) if lib.filepath else ""
        asset_folder = _asset_folder_for_link(resolved, ov_coll.name)
        prefix = _rig_hierarchy_prefix_for_override(ov_coll)
        if not prefix:
            return None
        self._prefix = _resolve_reload_prefix(ov_coll, prefix, asset_folder)
        self._asset_folder = asset_folder
        self._ov_coll_name = ov_coll.name
        self._queue.clear()
        self._index = 0
        self._renamed = 0

        objects = sorted(ov_coll.all_objects, key=lambda o: len(o.name), reverse=True)
        for obj in objects:
            if obj.type == "ARMATURE":
                continue
            if _target_prefixed_name_for_reload(obj, self._prefix, asset_folder) != obj.name:
                self._queue.append(("object", obj.name))

        child_cols = sorted(
            list(_iter_child_collections_recursive(ov_coll)),
            key=lambda c: len(c.name),
            reverse=True,
        )
        for coll in child_cols:
            if _target_prefixed_name_for_reload(coll, self._prefix, asset_folder) != coll.name:
                self._queue.append(("collection", coll.name))
        return None

    def step(self, batch_size: int = 4) -> None:
        end = min(self._index + batch_size, len(self._queue))
        for i in range(self._index, end):
            kind, name = self._queue[i]
            if kind == "object":
                block = bpy.data.objects.get(name)
            else:
                block = bpy.data.collections.get(name)
            if block is None:
                continue
            _set_override_user_editable(block)
            if _rename_id_with_prefix(block, self._prefix, self._asset_folder):
                self._renamed += 1
        self._index = end

    def finalize(self) -> int:
        ov_coll = bpy.data.collections.get(self._ov_coll_name)
        if ov_coll is not None:
            _sync_rig_prefix_overrides(ov_coll)
        return self._renamed


class RigLibraryRefreshSession:
    """Modal rig reload / version switch: library reload then batched prefix reapply."""

    def __init__(self, ref_id: str, new_path: Optional[str] = None) -> None:
        self.ref_id = ref_id
        self.new_path = new_path
        self._state = "start"
        self._prefix: Optional[RigPrefixReapplySession] = None
        self.renamed = 0

    @property
    def done(self) -> bool:
        return self._state == "done"

    def progress(self) -> Tuple[int, int]:
        if self._state == "start":
            return (0, 1)
        if self._prefix is not None:
            total = max(self._prefix.total, 1)
            return (self._prefix.current, total)
        return (1, 1)

    def tick(self, prefix_batch: int = 4) -> Optional[str]:
        if self._state == "done":
            return None
        if self._state == "start":
            err = self._reload_library()
            if err:
                return err
            self._prefix = RigPrefixReapplySession(self.ref_id)
            prep_err = self._prefix.prepare()
            if prep_err:
                return prep_err
            if self._prefix.total == 0:
                self.renamed = self._prefix.finalize()
                self._state = "done"
            else:
                self._state = "prefix"
            return None
        if self._prefix is not None:
            self._prefix.step(prefix_batch)
            if self._prefix.done:
                self.renamed = self._prefix.finalize()
                self._state = "done"
        return None

    def _reload_library(self) -> Optional[str]:
        try:
            lib = _library_for_ref(self.ref_id)
            if self.new_path:
                np = os.path.normpath(self.new_path)
                if not os.path.isfile(np):
                    return f"Rig file not found: {np}"
                lib.filepath = np
            lib.reload()
        except Exception as e:
            return str(e)
        return None


def reload_reference_node(ref_node_short: str) -> int:
    lib = _library_for_ref(ref_node_short)
    lib.reload()
    return _reapply_rig_hierarchy_prefix_for_ref(ref_node_short)


def replace_reference_path(ref_node_short: str, new_path: str) -> int:
    lib = _library_for_ref(ref_node_short)
    np = os.path.normpath(new_path)
    if not os.path.isfile(np):
        raise RuntimeError(f"Rig file not found: {np}")
    lib.filepath = np
    lib.reload()
    return _reapply_rig_hierarchy_prefix_for_ref(ref_node_short)


def _remove_override_hierarchy(ov_root: bpy.types.Collection) -> None:
    _unlink_collection_from_hierarchy(ov_root)
    try:
        bpy.data.collections.remove(ov_root)
    except Exception:
        pass


def remove_file_reference(
    ref_node_short: str,
    *,
    exists_on_disk: bool = True,
    is_loaded: bool = True,
) -> None:
    del exists_on_disk, is_loaded

    ov_coll = _override_for_ref(ref_node_short)
    if ov_coll is not None:
        lib = _source_library_for_collection(ov_coll)
        _remove_override_hierarchy(ov_coll)
        if lib is not None and not _library_has_override_usage(lib):
            lib_name = lib.name
            if lib_name in bpy.data.libraries:
                try:
                    bpy.data.libraries.remove(bpy.data.libraries[lib_name])
                except Exception:
                    pass
        return

    lib = _library_for_ref(ref_node_short)
    lib_name = lib.name

    for coll in list(_collections_for_library(lib)):
        _unlink_collection_from_hierarchy(coll)
        if coll.override_library is not None or coll.library == lib:
            try:
                bpy.data.collections.remove(coll)
            except Exception:
                pass

    if lib_name in bpy.data.libraries:
        try:
            bpy.data.libraries.remove(bpy.data.libraries[lib_name])
        except Exception:
            pass


def iter_rig_objects(ref_id: str) -> List[bpy.types.Object]:
    """All objects belonging to a linked rig reference."""
    ov_coll = _override_for_ref(ref_id)
    if ov_coll is not None:
        return list(ov_coll.all_objects)

    try:
        lib = _library_for_ref(ref_id)
    except RuntimeError:
        return []

    out: List[bpy.types.Object] = []
    seen: Set[int] = set()
    for coll in _collections_for_library(lib):
        for obj in coll.all_objects:
            key = id(obj)
            if key in seen:
                continue
            seen.add(key)
            out.append(obj)
    for obj in bpy.data.objects:
        if obj.library == lib and id(obj) not in seen:
            out.append(obj)
    return out


def find_rig_armature(
    ref_id: str,
    *,
    view_layer: Optional[bpy.types.ViewLayer] = None,
) -> Optional[bpy.types.Object]:
    """First armature object belonging to a linked rig reference."""
    candidates: List[bpy.types.Object] = []
    ov_coll = _override_for_ref(ref_id)
    if ov_coll is not None:
        for obj in ov_coll.all_objects:
            if obj.type == "ARMATURE":
                candidates.append(obj)
    else:
        try:
            lib = _library_for_ref(ref_id)
        except RuntimeError:
            return None

        seen: Set[int] = set()
        for coll in _collections_for_library(lib):
            for obj in coll.all_objects:
                if obj.type != "ARMATURE":
                    continue
                key = id(obj)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(obj)
        for obj in bpy.data.objects:
            if obj.library == lib and obj.type == "ARMATURE" and id(obj) not in seen:
                candidates.append(obj)

    if not candidates:
        return None
    if view_layer is not None:
        for obj in candidates:
            if _object_in_view_layer(obj, view_layer):
                return obj
    return candidates[0]


def rename_reference_namespace(ref_node_short: str, new_namespace: str) -> str:
    del new_namespace
    ov_coll = _override_for_ref(ref_node_short)
    lib = _library_for_ref(ref_node_short)
    if ov_coll is not None:
        return _ref_id_for_override(ov_coll, lib)
    return _ref_id_for_library(lib)
