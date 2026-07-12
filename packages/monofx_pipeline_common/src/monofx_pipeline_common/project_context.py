"""
Resolve pipeline project root from scene path and saved overrides (no bpy).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, Tuple

from .project_layout import find_project_root, is_project_root

ProjectRootSource = Literal["scene", "stored", "fallback", ""]


def valid_project_root(path: Optional[str]) -> Optional[Path]:
    if not path or not str(path).strip():
        return None
    candidate = Path(str(path).strip())
    try:
        if is_project_root(candidate):
            return candidate
    except OSError:
        return None
    try:
        resolved = candidate.resolve()
        if is_project_root(resolved):
            return resolved
    except OSError:
        return None
    return None


def resolve_project_root(
    scene_path: Optional[str],
    stored_project_root: Optional[str] = None,
    fallback_project_root: Optional[str] = None,
) -> Tuple[Optional[Path], ProjectRootSource]:
    """
    Pick project root in priority order:

    1. Walk up from the saved .blend path
    2. Scene / file override (``stored_project_root``)
    3. Add-on or session fallback (``fallback_project_root``)
    """
    if scene_path and str(scene_path).strip():
        from_scene = find_project_root(Path(scene_path))
        if from_scene is not None:
            return from_scene, "scene"

    stored = valid_project_root(stored_project_root)
    if stored is not None:
        return stored, "stored"

    fallback = valid_project_root(fallback_project_root)
    if fallback is not None:
        return fallback, "fallback"

    return None, ""


def project_context_error(
    scene_path: Optional[str],
    *,
    has_stored: bool = False,
    has_fallback: bool = False,
) -> str:
    if not scene_path or not str(scene_path).strip():
        if has_stored or has_fallback:
            return "Saved project path is invalid (need 01_assets and 02_shots)."
        return "Save the .blend file or set pipeline project root."
    if has_stored or has_fallback:
        return "Saved project path is invalid (need 01_assets and 02_shots)."
    return "Could not find project root. Set project folder (01_assets + 02_shots)."
