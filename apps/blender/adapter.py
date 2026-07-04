"""
Thin Blender adapter — only place that imports bpy for rig linking (repo/dev).

The installable add-on uses ``monofx_pipeline_blender.rig_adapter`` instead.
"""

from __future__ import annotations

try:
    from tools.fx.monofx_pipeline_blender.monofx_pipeline_blender import rig_adapter as _impl
except ImportError:
    _impl = None  # type: ignore[assignment]

from typing import Any, Dict, List, Optional


def is_available() -> bool:
    return _impl is not None


def _require():
    if _impl is None:
        raise RuntimeError("Blender rig adapter not available (run inside Blender with add-on)")
    return _impl


def get_scene_path() -> Optional[str]:
    return _require().get_scene_path() if is_available() else None


def scene_is_modified() -> bool:
    return _require().scene_is_modified() if is_available() else False


def open_scene_path(path: str, *, force: bool = False) -> None:
    _require().open_scene_path(path, force=force)


def collect_file_references(project_root: Optional[str] = None) -> List[Dict[str, Any]]:
    if not is_available():
        return []
    return _require().collect_file_references(project_root)


def create_file_reference(path: str, namespace: str) -> str:
    return _require().create_file_reference(path, namespace)


def load_reference_node(ref_node_short: str) -> None:
    _require().load_reference_node(ref_node_short)


def unload_reference_node(ref_node_short: str) -> None:
    _require().unload_reference_node(ref_node_short)


def reload_reference_node(ref_node_short: str) -> None:
    _require().reload_reference_node(ref_node_short)


def replace_reference_path(ref_node_short: str, new_path: str) -> None:
    _require().replace_reference_path(ref_node_short, new_path)


def remove_file_reference(
    ref_node_short: str,
    *,
    exists_on_disk: bool = True,
    is_loaded: bool = True,
) -> None:
    _require().remove_file_reference(
        ref_node_short,
        exists_on_disk=exists_on_disk,
        is_loaded=is_loaded,
    )


def rename_reference_namespace(ref_node_short: str, new_namespace: str) -> str:
    return _require().rename_reference_namespace(ref_node_short, new_namespace)
