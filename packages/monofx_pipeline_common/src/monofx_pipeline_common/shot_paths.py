"""
Shot token detection from filesystem paths (no bpy).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .project_layout import find_project_root, is_project_root

_SHOT_RE = re.compile(r"^(sh\d{3,}[a-z0-9]*)$", re.IGNORECASE)

SHOT_CHILD_COLLECTIONS: tuple[str, ...] = (
    "Characters",
    "Cameras",
    "Props",
    "Environment",
    "Lighting",
)

# Blender collection color_tag identifiers (Outliner).
SHOT_ROOT_COLLECTION_COLOR = "COLOR_08"
SHOT_COLLECTION_COLORS: dict[str, str] = {
    "Characters": "COLOR_04",
    "Cameras": "COLOR_07",
    "Props": "COLOR_03",
    "Environment": "COLOR_06",
    "Lighting": "COLOR_02",
}


def detect_shot_from_path(path: Path) -> Optional[str]:
    """
    Detect a shot token like ``sh002`` or ``sh003a`` from path segments.
    Returns normalized lowercase or ``None``.
    """
    parts = [path.name] + [p.name for p in path.parents]
    for part in parts:
        m = _SHOT_RE.match(part)
        if m:
            return m.group(1).lower()
    return None


def shot_collection_root_name(shot: str) -> str:
    return f"Anim_{(shot or '').strip()}"


__all__ = [
    "SHOT_CHILD_COLLECTIONS",
    "SHOT_COLLECTION_COLORS",
    "SHOT_ROOT_COLLECTION_COLOR",
    "detect_shot_from_path",
    "find_project_root",
    "is_project_root",
    "shot_collection_root_name",
]
