"""
Anim geo USD basename helpers — mirrors Maya USD exporter naming (no bpy).
"""

from __future__ import annotations

import re
from typing import MutableSet, Optional

INVALID_FILENAME_CHARS = '<>:"/\\|?*'
_PUBLISH_SUFFIX_RE = re.compile(r"(?:_rig)?_publish$", re.IGNORECASE)


def sanitize_filename_component(name: str) -> str:
    s = name or ""
    for c in INVALID_FILENAME_CHARS:
        s = s.replace(c, "_")
    s = s.replace("|", "_").replace(":", "_")
    s = s.strip(". ")
    return s or "unnamed"


def norm_namespace_for_geo_filename(namespace: str) -> str:
    """Strip rig/publish tokens like Maya ``_norm_namespace``."""
    s = (namespace or "").strip()
    for old in ("Rig_", "_Publish", "_rig", "_publish"):
        s = s.replace(old, "")
    return sanitize_filename_component(s)


def geo_usd_basename_from_asset_folder(asset_folder: str) -> str:
    """``char_Kahlii`` → ``geo_char_Kahlii``."""
    folder = sanitize_filename_component((asset_folder or "").strip())
    if not folder:
        return "geo_unnamed"
    if folder.lower().startswith("geo_"):
        return folder
    return sanitize_filename_component(f"geo_{folder}")


def geo_usd_basename_from_publish_name(publish_name: str) -> str:
    """``CHAR_KAHLII_RIG_PUBLISH`` → ``geo_CHAR_KAHLII`` (fallback when asset path unknown)."""
    s = (publish_name or "").strip()
    s = _PUBLISH_SUFFIX_RE.sub("", s)
    body = norm_namespace_for_geo_filename(s)
    if body.lower().startswith("geo_"):
        return body
    return sanitize_filename_component(f"geo_{body}")


def alloc_unique_basename(base: str, used: MutableSet[str]) -> str:
    if base not in used:
        used.add(base)
        return base
    i = 2
    while True:
        cand = f"{base}_{i}"
        if cand not in used:
            used.add(cand)
            return cand
        i += 1


def resolve_geo_usd_basename(
    *,
    asset_folder: Optional[str] = None,
    publish_name: Optional[str] = None,
    used: Optional[MutableSet[str]] = None,
) -> str:
    if asset_folder:
        base = geo_usd_basename_from_asset_folder(asset_folder)
    elif publish_name:
        base = geo_usd_basename_from_publish_name(publish_name)
    else:
        base = "geo_unnamed"
    if used is None:
        return base
    return alloc_unique_basename(base, used)
