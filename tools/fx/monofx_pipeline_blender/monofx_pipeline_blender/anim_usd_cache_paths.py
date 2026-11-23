"""
USD prim path helpers for animation cache export (no bpy).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional, Sequence

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_]")


def _valid_identifier(safe: str) -> str:
    """A USD prim name cannot start with a digit; Blender's USD export prefixes ``_``."""
    if safe and safe[0].isdigit():
        return "_" + safe
    return safe


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
    return _valid_identifier(safe) or "rig"


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


def is_namespace_geo_branch_name(name: str) -> bool:
    """
    True for geo roots and sub-branches like ``tachirig::Geo`` or ``tachirig::Geo_Proxy``.

    The tail must be exactly ``Geo`` or start with ``Geo_`` (case-insensitive).
    """
    text = (name or "").strip()
    if "::" not in text:
        return False
    namespace, tail = text.rsplit("::", 1)
    if not namespace.strip():
        return False
    t = tail.casefold()
    return t == "geo" or t.startswith("geo_")


def sanitize_prim_segment(name: str) -> str:
    """
    Make a single USD path segment from a Blender object name.

    A name starting with a digit gets ``_`` in front (``01_Pipe`` -> ``_01_Pipe``),
    as Blender's own USD export names it in the lookdev / UV publish.
    """
    base = strip_blender_namespace(name)
    safe = _SANITIZE_RE.sub("_", base).strip("_")
    return _valid_identifier(safe) or "Prim"


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


def sibling_prim_segments(siblings: Sequence[tuple[str, str]]) -> list[str]:
    """
    Prim names of objects under one parent, from ``(object name, rig source name)``.

    The source name is the object's name in the rig it is linked from (``""`` for an
    object that is no library override). It wins, because lookdev binds to it and Blender
    adds ``.001`` to an override whose name is taken in the shot. When siblings share one
    source (a copied mesh), one keeps it and the others keep their own name, as objects
    without a source do.
    """
    own = [sanitize_prim_segment(name) for name, _source in siblings]
    wanted = [
        sanitize_prim_segment(source) if source else own[i]
        for i, (_name, source) in enumerate(siblings)
    ]
    holders: dict[str, int] = {}
    for i, segment in enumerate(wanted):
        key = segment.casefold()
        held = holders.get(key)
        if held is None or (own[held].casefold() != key and own[i].casefold() == key):
            holders[key] = i
    used = set(holders)
    return [
        segment
        if holders[segment.casefold()] == i
        else dedupe_sibling_segment(own[i], used)
        for i, segment in enumerate(wanted)
    ]


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


def single_top_level_prim_name(prim_paths: Iterable[str]) -> str:
    """
    Name of the one top-level prim shared by all ``prim_paths`` (``/Geo/...`` → ``Geo``).

    Returns ``""`` when there is no top-level prim or more than one (multi-instance
    export), because a USD layer can declare only a single ``defaultPrim``.
    """
    names: set[str] = set()
    for path in prim_paths:
        parts = [p for p in (path or "").strip().split("/") if p]
        if parts:
            names.add(parts[0])
    if len(names) == 1:
        return next(iter(names))
    return ""


def existing_output_paths(paths: Iterable[str | Path]) -> list[Path]:
    """Subset of ``paths`` that already exist on disk."""
    found: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        candidate = Path(path)
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            found.append(candidate)
    return found


def uv_primvar_names(uv_names: Sequence[str], active_render: int) -> list[str]:
    """USD primvar name for each Blender UV map, as Blender's own USD export names them.

    The render-active map becomes ``st`` (what lookdev reads); the others keep their name,
    made a valid identifier and never a second ``st``.
    """
    out: list[str] = []
    used: set[str] = set()
    if 0 <= active_render < len(uv_names):
        used.add("st")
    for i, raw in enumerate(uv_names):
        if i == active_render:
            out.append("st")
            continue
        base = _valid_identifier(_SANITIZE_RE.sub("_", (raw or "").strip()).strip("_")) or "uv"
        name = base
        n = 1
        while name in used:
            name = f"{base}_{n}"
            n += 1
        used.add(name)
        out.append(name)
    return out


__all__ = [
    "build_prim_path_segments",
    "dedupe_sibling_segment",
    "existing_output_paths",
    "is_camera_collection_name",
    "is_namespace_geo_branch_name",
    "is_namespace_geo_name",
    "is_publish_collection_name",
    "multi_instance_root_path",
    "namespace_prefix_from_name",
    "prim_path_from_object_chain",
    "sanitize_namespace_segment",
    "sanitize_prim_segment",
    "segments_to_prim_path",
    "sibling_prim_segments",
    "single_top_level_prim_name",
    "strip_blender_namespace",
    "uv_primvar_names",
]
