"""
Rig hierarchy name prefix helpers (no DCC imports).
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Optional

from apps.common.rig_library import display_name_from_asset_folder

_BLENDER_NAME_MAX = 63
RIG_NAMESPACE_SEPARATOR = "::"
LEGACY_RIG_NAMESPACE_SEPARATOR = "_"
_BLENDER_DUPLICATE_SUFFIX_RE = re.compile(r"\.\d{3}$")


def rig_prefix_base_from_asset_folder(asset_folder: str) -> str:
    """``char_Kahlli`` → ``kahllirig`` (lowercase display slug + ``rig``)."""
    display = display_name_from_asset_folder((asset_folder or "").strip())
    slug = re.sub(r"[^a-zA-Z0-9]", "", display).lower()
    if not slug:
        slug = re.sub(r"[^a-zA-Z0-9]", "", (asset_folder or "rig").strip()).lower() or "rig"
    return f"{slug}rig"


def iter_rig_hierarchy_prefix_candidates(base: str):
    """``kahllirig::``, ``kahllirig2::``, ``kahllirig3::``, …"""
    yield f"{base}{RIG_NAMESPACE_SEPARATOR}"
    n = 2
    while n < 9999:
        yield f"{base}{n}{RIG_NAMESPACE_SEPARATOR}"
        n += 1


def iter_legacy_rig_hierarchy_prefix_candidates(base: str):
    """Legacy ``kahllirig_`` prefixes (detect/reapply on older links)."""
    yield f"{base}{LEGACY_RIG_NAMESPACE_SEPARATOR}"
    n = 2
    while n < 9999:
        yield f"{base}{n}{LEGACY_RIG_NAMESPACE_SEPARATOR}"
        n += 1


def iter_all_rig_hierarchy_prefix_candidates(base: str):
    """New ``::`` candidates first, then legacy ``_`` for detection."""
    yield from iter_rig_hierarchy_prefix_candidates(base)
    yield from iter_legacy_rig_hierarchy_prefix_candidates(base)


def unique_rig_hierarchy_prefix(
    asset_folder: str,
    is_prefix_in_use: Callable[[str], bool],
) -> str:
    """
    First link: ``kahllirig::``; duplicates: ``kahllirig2::``, ``kahllirig3::``, …
    """
    base = rig_prefix_base_from_asset_folder(asset_folder)
    for candidate in iter_rig_hierarchy_prefix_candidates(base):
        if not is_prefix_in_use(candidate):
            return candidate
    return f"{base}9999{RIG_NAMESPACE_SEPARATOR}"


def prefixed_name(current: str, prefix: str) -> str:
    name = (current or "").strip()
    if not name or name.startswith(prefix):
        return name[:_BLENDER_NAME_MAX]
    return (prefix + name)[:_BLENDER_NAME_MAX]


def legacy_prefix_from_canonical(prefix: str, asset_folder: str) -> Optional[str]:
    """``tachirig::`` → ``tachirig_`` (same duplicate index)."""
    base = rig_prefix_base_from_asset_folder(asset_folder)
    if not prefix.startswith(base):
        return None
    if prefix.endswith(RIG_NAMESPACE_SEPARATOR):
        suffix = prefix[len(base) : -len(RIG_NAMESPACE_SEPARATOR)]
        return f"{base}{suffix}{LEGACY_RIG_NAMESPACE_SEPARATOR}"
    return None


def migrate_prefix_to_canonical(prefix: str, asset_folder: str) -> str:
    """``tachirig_`` → ``tachirig::`` (keep duplicate index)."""
    base = rig_prefix_base_from_asset_folder(asset_folder)
    if prefix.endswith(RIG_NAMESPACE_SEPARATOR):
        return prefix
    if prefix.startswith(base) and prefix.endswith(LEGACY_RIG_NAMESPACE_SEPARATOR):
        suffix = prefix[len(base) : -len(LEGACY_RIG_NAMESPACE_SEPARATOR)]
        return f"{base}{suffix}{RIG_NAMESPACE_SEPARATOR}"
    return prefix


def strip_known_rig_prefix(name: str, asset_folder: str) -> str:
    """Remove ``tachirig::`` / ``tachirig_`` style namespace from a datablock name."""
    text = (name or "").strip()
    if not text:
        return text
    base = rig_prefix_base_from_asset_folder(asset_folder)
    for candidate in iter_all_rig_hierarchy_prefix_candidates(base):
        if text.startswith(candidate):
            return text[len(candidate) :]
    return text


def strip_blender_duplicate_suffix(name: str) -> str:
    """``Geo.001`` → ``Geo`` (Blender auto-rename on link/reload collision)."""
    text = (name or "").strip()
    if not text:
        return text
    return _BLENDER_DUPLICATE_SUFFIX_RE.sub("", text)


def link_bare_name(
    current: str,
    asset_folder: str,
    *,
    library_source_name: Optional[str] = None,
) -> str:
    """
    Bare datablock name aligned with the linked library source (ignores namespace).

    Prefers *library_source_name* from ``override_library.reference`` when set.
    """
    source = (library_source_name or "").strip()
    if source:
        return source
    bare = strip_known_rig_prefix(current, asset_folder)
    return strip_blender_duplicate_suffix(bare)


def namespace_prefixed_name(
    current: str,
    prefix: str,
    asset_folder: str,
    *,
    library_source_name: Optional[str] = None,
) -> str:
    """Strip rig prefix / ``.001`` suffix, align to link source, apply *prefix*."""
    bare = link_bare_name(
        current,
        asset_folder,
        library_source_name=library_source_name,
    )
    return prefixed_name(bare, prefix)


def iter_prefix_equivalent_forms(prefix: str, asset_folder: str) -> Iterable[str]:
    """Canonical and legacy prefix strings that refer to the same namespace slot."""
    seen: set[str] = set()
    for form in (
        prefix,
        migrate_prefix_to_canonical(prefix, asset_folder),
        legacy_prefix_from_canonical(migrate_prefix_to_canonical(prefix, asset_folder), asset_folder),
    ):
        if form and form not in seen:
            seen.add(form)
            yield form


def detect_rig_hierarchy_prefix_from_pairs(names: Iterable[str]) -> Optional[str]:
    """
    Infer prefix when both prefixed and source names coexist
    (e.g. ``tachirig::Geo_Body`` and ``Geo_Body``).
    """
    names_set = {(n or "").strip() for n in names if (n or "").strip()}
    if len(names_set) < 2:
        return None

    candidates: dict[str, int] = {}
    for name in names_set:
        for base in names_set:
            if base == name or len(name) <= len(base):
                continue
            if not name.endswith(base):
                continue
            prefix = name[: len(name) - len(base)]
            if not prefix or base.startswith(prefix):
                continue
            candidates[prefix] = candidates.get(prefix, 0) + 1

    if not candidates:
        return None
    best_prefix, _best_count = max(candidates.items(), key=lambda kv: (kv[1], len(kv[0])))
    return best_prefix


def detect_rig_hierarchy_prefix_from_names(
    names: Iterable[str],
    asset_folder: str,
) -> Optional[str]:
    """
    Return the rig hierarchy prefix already in use inside a linked rig override.

    After a library reload some object names revert to the source file while
    overridden names keep the prefix; this picks the prefix to re-apply.
    """
    names_list = [(n or "").strip() for n in names]
    names_list = [n for n in names_list if n]
    if not names_list:
        return None

    base = rig_prefix_base_from_asset_folder(asset_folder)
    best: Optional[str] = None
    best_count = 0
    for candidate in iter_all_rig_hierarchy_prefix_candidates(base):
        count = sum(1 for n in names_list if n.startswith(candidate))
        if count > best_count:
            best_count = count
            best = candidate
    if best_count > 0 and best is not None:
        return migrate_prefix_to_canonical(best, asset_folder)

    detected = detect_rig_hierarchy_prefix_from_pairs(names_list)
    if detected:
        return migrate_prefix_to_canonical(detected, asset_folder)
    return None
