"""
Control-bone chain resolution from armature hierarchy or naming (no bpy).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

_CONTROL_CHAIN_RE = re.compile(
    r"^(?P<base>c_.+?)(?P<idx>\d+)(?P<side>\.[lr])?$",
    re.IGNORECASE,
)


def parse_control_chain_bone(name: str) -> Optional[Tuple[str, int, str]]:
    """
    Parse a control bone name into ``(base, index, side_suffix)``.

    Examples:
        ``c_index1.l`` → ``("c_index", 1, ".l")``
        ``c_kilt_01_04.l`` → ``("c_kilt_01_", 4, ".l")``
    """
    m = _CONTROL_CHAIN_RE.match((name or "").strip())
    if not m:
        return None
    return m.group("base"), int(m.group("idx")), m.group("side") or ""


def chain_members_from_bone(name: str, all_bone_names: Iterable[str]) -> List[str]:
    """
    Return sorted control bones in the same numbered series as *name*.

    Only bones starting with ``c_`` are included. Non-control bones are ignored.
    """
    parsed = parse_control_chain_bone(name)
    if parsed is None or not name.startswith("c_"):
        return [name] if name in set(all_bone_names) else []

    base, _idx, side = parsed
    names_set = set(all_bone_names)
    members: List[Tuple[int, str]] = []

    for bone_name in all_bone_names:
        if not bone_name.startswith("c_"):
            continue
        other = parse_control_chain_bone(bone_name)
        if other is None:
            continue
        obase, oidx, oside = other
        if obase == base and oside == side:
            members.append((oidx, bone_name))

    if not members:
        return [name] if name in names_set else []

    members.sort(key=lambda pair: pair[0])
    return [bn for _, bn in members]


def _is_descendant_of(
    name: str,
    ancestor: str,
    parent_of: Mapping[str, Optional[str]],
) -> bool:
    cur = parent_of.get(name)
    while cur:
        if cur == ancestor:
            return True
        cur = parent_of.get(cur)
    return False


def _linear_tail_depth(name: str, children_of: Mapping[str, Sequence[str]]) -> int:
    depth = 0
    cur = name
    while True:
        kids = list(children_of.get(cur) or ())
        if len(kids) != 1:
            break
        cur = kids[0]
        depth += 1
    return depth


def _pick_chain_child(
    current: str,
    seed: str,
    children_of: Mapping[str, Sequence[str]],
    parent_of: Mapping[str, Optional[str]],
) -> Optional[str]:
    kids = list(children_of.get(current) or ())
    if not kids:
        return None
    if len(kids) == 1:
        return kids[0]
    for kid in kids:
        if kid == seed or _is_descendant_of(seed, kid, parent_of):
            return kid
    return max(kids, key=lambda k: _linear_tail_depth(k, children_of))


def chain_members_from_hierarchy(
    seed: str,
    parent_of: Mapping[str, Optional[str]],
    children_of: Mapping[str, Sequence[str]],
) -> List[str]:
    """
    Return bones on the parent→child chain through *seed* (root to leaf).

    Walks up to the chain root, then down following the branch that contains
    *seed* (same idea as Blender Select Grouped parent/child chain).
    """
    if not seed:
        return []

    known = set(parent_of) | set(children_of)
    if seed not in known:
        return [seed]

    ancestors: List[str] = []
    cur = parent_of.get(seed)
    while cur:
        ancestors.append(cur)
        cur = parent_of.get(cur)
    ancestors.reverse()

    root = ancestors[0] if ancestors else seed
    members: List[str] = []
    cur = root
    while cur:
        members.append(cur)
        nxt = _pick_chain_child(cur, seed, children_of, parent_of)
        if nxt is None or nxt in members:
            break
        cur = nxt

    return members
