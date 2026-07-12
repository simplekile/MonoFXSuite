"""
Control-bone chain resolution from armature hierarchy or naming (no bpy).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

_CHAIN_PATTERNS = (
    re.compile(r"^(?P<base>c_.+_)(?P<idx>\d+)(?P<tail>\.[lr])$", re.IGNORECASE),
    re.compile(
        r"^(?P<base>c_.+?)(?P<idx>\d+)(?P<tail>_dupli_\d+\.[a-z])$",
        re.IGNORECASE,
    ),
    re.compile(r"^(?P<base>c_\D.+?)(?P<idx>\d+)(?P<tail>\.[lr])$", re.IGNORECASE),
)


def parse_control_chain_bone(name: str) -> Optional[Tuple[str, int, str]]:
    """
    Parse a control bone name into ``(base, index, tail_suffix)``.

    Examples:
        ``c_index1.l`` → ``("c_index", 1, ".l")``
        ``c_kilt_01_04.l`` → ``("c_kilt_01_", 4, ".l")``
        ``c_DressFront_00_dupli_002.x`` → ``("c_DressFront_", 0, "_dupli_002.x")``
    """
    text = (name or "").strip()
    for pattern in _CHAIN_PATTERNS:
        match = pattern.match(text)
        if match:
            return match.group("base"), int(match.group("idx")), match.group("tail")
    return None


def chain_members_from_bone(name: str, all_bone_names: Iterable[str]) -> List[str]:
    """
    Return sorted control bones in the same numbered series as *name*.

    Only bones starting with ``c_`` are included. Non-control bones are ignored.
    """
    parsed = parse_control_chain_bone(name)
    if parsed is None or not name.startswith("c_"):
        return [name] if name in set(all_bone_names) else []

    base, _idx, tail = parsed
    names_set = set(all_bone_names)
    members: List[Tuple[int, str]] = []

    for bone_name in all_bone_names:
        if not bone_name.startswith("c_"):
            continue
        other = parse_control_chain_bone(bone_name)
        if other is None:
            continue
        obase, oidx, otail = other
        if obase == base and otail == tail:
            members.append((oidx, bone_name))

    if not members:
        return [name] if name in names_set else []

    members.sort(key=lambda pair: pair[0])
    return [bn for _, bn in members]


def mirror_side_tail(tail: str) -> Optional[str]:
    """Return the opposite ``.l`` / ``.r`` suffix when present."""
    if len(tail) < 2:
        return None
    suffix = tail[-2:].lower()
    if suffix == ".l":
        return tail[:-2] + ".r"
    if suffix == ".r":
        return tail[:-2] + ".l"
    return None


def mirror_control_bone_name(name: str) -> Optional[str]:
    """Return the mirror-side control bone name, e.g. ``c_kilt_01_04.l`` → ``.r``."""
    parsed = parse_control_chain_bone(name)
    if parsed is None:
        return None
    _base, _idx, tail = parsed
    mirror_tail = mirror_side_tail(tail)
    if mirror_tail is None or not name.endswith(tail):
        return None
    return name[: -len(tail)] + mirror_tail


def parallel_chain_seeds(seed: str, all_bone_names: Iterable[str]) -> List[str]:
    """Return *seed* plus the mirror-side seed when that bone exists."""
    names_set = set(all_bone_names)
    seeds = [seed]
    mirror = mirror_control_bone_name(seed)
    if mirror and mirror in names_set and mirror not in seeds:
        seeds.append(mirror)
    return seeds


def partition_selection_chains(
    names: Sequence[str],
    parent_of: Mapping[str, Optional[str]],
    children_of: Mapping[str, Sequence[str]],
) -> List[List[str]]:
    """Split a manual selection into disjoint root→leaf chains."""
    names_set = set(names)
    roots = [name for name in names if parent_of.get(name) not in names_set]
    chains: List[List[str]] = []
    visited: set[str] = set()

    def walk(name: str, chain: List[str]) -> None:
        if name not in names_set or name in visited:
            return
        visited.add(name)
        chain.append(name)
        for child in children_of.get(name, ()):
            if child in names_set:
                walk(child, chain)

    for root in sorted(roots):
        chain: List[str] = []
        walk(root, chain)
        if chain:
            chains.append(chain)

    for name in names:
        if name not in visited:
            chains.append([name])

    return chains


def sort_chain_selection(
    names: Sequence[str],
    parent_of: Mapping[str, Optional[str]],
    children_of: Mapping[str, Sequence[str]],
) -> List[str]:
    """Order a manual multi-selection root → leaf along parent links."""
    names_set = set(names)
    ordered: List[str] = []

    def walk(name: str) -> None:
        if name in names_set and name not in ordered:
            ordered.append(name)
            for child in children_of.get(name, ()):
                if child in names_set:
                    walk(child)

    roots = [name for name in names if parent_of.get(name) not in names_set]
    for root in sorted(roots):
        walk(root)
    for name in names:
        if name not in ordered:
            ordered.append(name)
    return ordered


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


def chain_members_from_hierarchy_branch(
    seed: str,
    parent_of: Mapping[str, Optional[str]],
    children_of: Mapping[str, Sequence[str]],
) -> List[str]:
    """
    Return the local branch chain through *seed* (branch root → leaf).

    Walks up only until the parent sits under a fork, then down to the leaf.
    Skips the full rig path from the armature root when a strip is parented
    under a shared empty.
    """
    if not seed:
        return []

    known = set(parent_of) | set(children_of)
    if seed not in known:
        return [seed]

    ancestors: List[str] = []
    cur = parent_of.get(seed)
    while cur:
        ancestors.insert(0, cur)
        parent = parent_of.get(cur)
        if parent is None:
            break
        grandparent = parent_of.get(parent)
        if grandparent is not None and len(children_of.get(grandparent, [])) > 1:
            ancestors.insert(0, parent)
            break
        cur = parent

    members = list(ancestors)
    if seed not in members:
        members.append(seed)

    cur = seed
    while cur:
        nxt = _pick_chain_child(cur, seed, children_of, parent_of)
        if nxt is None or nxt in members:
            break
        members.append(nxt)
        cur = nxt

    return members


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
