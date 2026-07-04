"""
USD prim path helpers for animation cache export (no bpy).
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_]")


def strip_blender_namespace(name: str) -> str:
    """``rig:char:geo_Body`` / ``tachirig::Geo_Body`` → ``geo_Body`` / ``Geo_Body``."""
    text = (name or "").strip()
    if not text:
        return ""
    if "::" in text:
        return text.rsplit("::", 1)[-1]
    return text.split(":")[-1]


def namespace_prefix_from_name(name: str) -> str:
    """``tachirig::Geo_Body`` → ``tachirig``."""
    text = (name or "").strip()
    if "::" not in text:
        return ""
    return text.rsplit("::", 1)[0]


def sanitize_namespace_segment(namespace: str) -> str:
    """USD path segment for a linked rig namespace prefix."""
    safe = _SANITIZE_RE.sub("_", (namespace or "").strip()).strip("_")
    return safe or "rig"


_CAMERA_COLLECTION_NAMES = frozenset({"cameras", "camera", "cam"})


def is_camera_collection_name(name: str) -> bool:
    """
    True for shot camera collections named ``Cameras``, ``camera``, ``cam``, etc.

    Also accepts namespace tails like ``shot::Cameras``.
    """
    text = (name or "").strip()
    if not text:
        return False
    if "::" in text:
        _, tail = text.rsplit("::", 1)
        return tail.casefold() in _CAMERA_COLLECTION_NAMES
    return text.casefold() in _CAMERA_COLLECTION_NAMES


def is_publish_collection_name(name: str) -> bool:
    """True when collection name contains ``publish`` (case-insensitive)."""
    return "publish" in (name or "").casefold()


def is_namespace_geo_name(name: str) -> bool:
    """
    True for linked rig geo roots like ``tachirig::Geo`` or ``tachirig::geo``.

    The segment before ``::`` is the namespace; the tail must be exactly ``Geo``.
    """
    text = (name or "").strip()
    if "::" not in text:
        return False
    namespace, tail = text.rsplit("::", 1)
    return bool(namespace.strip()) and tail.casefold() == "geo"


def sanitize_prim_segment(name: str) -> str:
    """Make a single USD path segment from a Blender object name."""
    base = strip_blender_namespace(name)
    safe = _SANITIZE_RE.sub("_", base).strip("_")
    return safe or "Prim"


def dedupe_sibling_segment(segment: str, used: set[str]) -> str:
    """Ensure unique sibling prim name (``Body``, ``Body_2``, …)."""
    key = segment.casefold()
    if key not in used:
        used.add(key)
        return segment
    n = 2
    while True:
        candidate = f"{segment}_{n}"
        ck = candidate.casefold()
        if ck not in used:
            used.add(ck)
            return candidate
        n += 1


def build_prim_path_segments(
    object_names: Iterable[str],
    *,
    root_override: str = "",
) -> list[str]:
    """
    Build sanitized path segments for a single Blender parent chain (root → leaf).

    *root_override* replaces the top segment when set (without leading slash).
    """
    names = list(object_names)
    if not names:
        return []
    segments: list[str] = []
    used_at_level: dict[int, set[str]] = {}
    for depth, raw_name in enumerate(names):
        seg = sanitize_prim_segment(raw_name)
        used = used_at_level.setdefault(depth, set())
        seg = dedupe_sibling_segment(seg, used)
        segments.append(seg)
    if root_override.strip():
        segments[0] = sanitize_prim_segment(root_override.strip())
    return segments


def segments_to_prim_path(segments: Iterable[str]) -> str:
    parts = [p for p in segments if p]
    if not parts:
        return "/Root"
    return "/" + "/".join(parts)


def multi_instance_root_path(
    root_obj_name: str,
    *,
    multi_instance: bool,
    used_siblings: dict[str, set[str]],
) -> str:
    """
    When multiple linked instances are merged into one USD, prefix each tree with
    its rig namespace (``/tachirig``, ``/tachirig2``) so ``Geo`` paths do not collide.

    Single-instance export returns ``""`` so paths match lookdev (``/Geo/...``).
    """
    if not multi_instance:
        return ""
    ns = namespace_prefix_from_name(root_obj_name)
    if not ns:
        return ""
    ns_seg = sanitize_namespace_segment(ns)
    sibling_key = "/"
    used = used_siblings.setdefault(sibling_key, set())
    ns_seg = dedupe_sibling_segment(ns_seg, used)
    return segments_to_prim_path([ns_seg])


def prim_path_from_object_chain(
    object_names: Iterable[str],
    *,
    root_override: str = "",
) -> str:
    return segments_to_prim_path(
        build_prim_path_segments(object_names, root_override=root_override)
    )


__all__ = [
    "build_prim_path_segments",
    "dedupe_sibling_segment",
    "is_camera_collection_name",
    "is_namespace_geo_name",
    "is_publish_collection_name",
    "multi_instance_root_path",
    "namespace_prefix_from_name",
    "prim_path_from_object_chain",
    "sanitize_namespace_segment",
    "sanitize_prim_segment",
    "segments_to_prim_path",
    "strip_blender_namespace",
]
