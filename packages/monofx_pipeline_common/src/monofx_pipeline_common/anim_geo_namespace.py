"""
Namespace helpers for publish geo mesh collection (no bpy).
"""

from __future__ import annotations

from typing import Iterable


def namespace_prefix_from_name(name: str) -> str:
    text = (name or "").strip()
    if "::" not in text:
        return ""
    return text.rsplit("::", 1)[0]


def is_namespace_geo_collection_name(name: str) -> bool:
    text = (name or "").strip()
    if "::" not in text:
        return False
    namespace, tail = text.rsplit("::", 1)
    return bool(namespace.strip()) and tail.casefold() == "geo"


def namespace_prefixes_from_geo_collections(names: Iterable[str]) -> tuple[str, ...]:
    prefixes: set[str] = set()
    for name in names:
        if not is_namespace_geo_collection_name(name):
            continue
        prefix = namespace_prefix_from_name(name)
        if prefix:
            prefixes.add(prefix)
    return tuple(sorted(prefixes, key=str.lower))


def mesh_names_matching_namespace_prefixes(
    mesh_names: Iterable[str],
    prefixes: Iterable[str],
) -> tuple[str, ...]:
    wanted = set(prefixes)
    if not wanted:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for name in mesh_names:
        text = (name or "").strip()
        if not text or text in seen:
            continue
        prefix = namespace_prefix_from_name(text)
        if prefix and prefix in wanted:
            seen.add(text)
            out.append(text)
    return tuple(sorted(out, key=str.lower))
