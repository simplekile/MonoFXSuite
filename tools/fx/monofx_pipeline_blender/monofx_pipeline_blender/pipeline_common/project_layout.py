"""
Project folder layout shared by pipeline tools (Maya, Houdini, etc.).

Pure pathlib — no Maya / hou imports.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

_ASSETS = "01_assets"
_SHOTS = "02_shots"
_VERSION_DIR_RE = re.compile(r"^[vV](\d+)$", re.IGNORECASE)
_WORK_VERSION_IN_STEM_RE = re.compile(r"_v(\d+)(?:\.|_|$)", re.IGNORECASE)


def is_project_root(candidate: Path) -> bool:
    try:
        return (candidate / _ASSETS).is_dir() and (candidate / _SHOTS).is_dir()
    except OSError:
        return False


def find_project_root(start: Path) -> Optional[Path]:
    """
    Walk upwards from a file or directory path to find the project root.
    Root = folder containing both ``01_assets`` and ``02_shots``.
    """
    cur = start if start.is_dir() else start.parent
    for p in (cur, *cur.parents):
        try:
            if is_project_root(p):
                return p
        except OSError:
            continue
    return None


def list_asset_groups(project_root: Path, *, prefix: str = "_") -> List[str]:
    """
    Direct child directories of ``01_assets`` whose names start with ``prefix``
    (default: underscore, e.g. ``_characters``).
    """
    assets = project_root / _ASSETS
    if not assets.is_dir():
        return []
    out: List[str] = []
    try:
        for child in assets.iterdir():
            if child.is_dir() and child.name.startswith(prefix):
                out.append(child.name)
    except OSError:
        return []
    out.sort(key=lambda s: s.lower())
    return out


def version_dir_sort_key(name: str) -> int:
    m = _VERSION_DIR_RE.match(name.strip())
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    m2 = re.search(r"(\d+)", name)
    return int(m2.group(1)) if m2 else -1


def list_publish_version_dirs(publish_parent: Path) -> List[Path]:
    """Subfolders named v001 / V001 etc., sorted by numeric version."""
    if not publish_parent.is_dir():
        return []
    pairs: List[Tuple[int, Path]] = []
    try:
        for child in publish_parent.iterdir():
            if not child.is_dir():
                continue
            k = version_dir_sort_key(child.name)
            if k >= 0:
                pairs.append((k, child))
    except OSError:
        return []
    pairs.sort(key=lambda x: x[0])
    return [p for _, p in pairs]


def path_is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def parse_asset_from_project_path(
    resolved_file: Path,
    project_root: Path,
) -> Optional[Tuple[str, str]]:
    """
    If ``resolved_file`` is under ``project_root/01_assets/<group>/<asset>/...``,
    return ``(group, asset_folder_name)``; else ``None``.

    Uses strict ``relative_to`` first, then a loose scan for a ``01_assets`` segment
    (case-insensitive) so Maya / Windows paths still match when ``resolve()`` differs.
    """
    assets_dir = project_root / _ASSETS
    try:
        f = resolved_file
        try:
            f = resolved_file.resolve()
        except OSError:
            f = Path(os.path.normpath(str(resolved_file)))
        a = assets_dir
        try:
            a = assets_dir.resolve()
        except OSError:
            a = Path(os.path.normpath(str(assets_dir)))
        rel = f.relative_to(a)
        parts = rel.parts
        if len(parts) >= 2:
            return (parts[0], parts[1])
    except (ValueError, OSError):
        pass

    norm_file = os.path.normpath(str(resolved_file).replace("/", os.sep))
    parts = Path(norm_file).parts
    for i, name in enumerate(parts):
        if name.casefold() != "01_assets":
            continue
        if i + 2 >= len(parts):
            continue
        group, asset_name = parts[i + 1], parts[i + 2]
        candidate = project_root / _ASSETS / group / asset_name
        try:
            if candidate.is_dir():
                return (group, asset_name)
        except OSError:
            continue
        try:
            if candidate.resolve().is_dir():
                return (group, asset_name)
        except OSError:
            continue
    return None
