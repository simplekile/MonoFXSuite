"""
Shot animation collection rename / merge planning (no bpy).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple

from .shot_paths import SHOT_CHILD_COLLECTIONS, shot_collection_root_name

_ANIM_ROOT_RE = re.compile(r"^Anim_(.+)$", re.IGNORECASE)


def parse_anim_root_shot_token(collection_name: str) -> Optional[str]:
    m = _ANIM_ROOT_RE.match((collection_name or "").strip())
    if not m:
        return None
    return m.group(1).strip().lower()


def is_shot_collection_root_name(name: str) -> bool:
    return parse_anim_root_shot_token(name) is not None


def canonical_child_collection_name(name: str) -> Optional[str]:
    token = (name or "").strip()
    if not token:
        return None
    for std in SHOT_CHILD_COLLECTIONS:
        if std.casefold() == token.casefold():
            return std
    return None


def plan_shot_root_rename(
    detected_shot: str,
    existing_root_names: Iterable[str],
) -> Optional[Tuple[str, str]]:
    """
    Return ``(from_name, to_name)`` when a single shot root should be renamed.

    ``None`` when no rename is needed or the situation is ambiguous.
    """
    shot = (detected_shot or "").strip().lower()
    if not shot:
        return None

    target = shot_collection_root_name(shot)
    roots = [n for n in existing_root_names if is_shot_collection_root_name(n)]
    if not roots:
        return None

    if target in roots:
        for name in roots:
            if name != target and name.casefold() == target.casefold():
                return name, target
        return None

    wrong = [n for n in roots if n.casefold() != target.casefold()]
    if len(wrong) == 1:
        return wrong[0], target
    return None


def child_names_to_fix(child_names: Iterable[str]) -> List[Tuple[str, str]]:
    """Return ``(from_name, to_name)`` pairs for direct child collections."""
    fixes: List[Tuple[str, str]] = []
    seen_canonical: set[str] = set()
    for name in child_names:
        canonical = canonical_child_collection_name(name)
        if canonical is None or canonical == name:
            if canonical is not None:
                seen_canonical.add(canonical)
            continue
        if canonical in seen_canonical:
            continue
        fixes.append((name, canonical))
        seen_canonical.add(canonical)
    return fixes
