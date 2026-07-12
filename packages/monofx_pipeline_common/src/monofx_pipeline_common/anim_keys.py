"""
Keyframe curve helpers (no bpy).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

_POSE_BONE_PATH_RE = re.compile(r'^pose\.bones\["((?:[^"\\]|\\.)+)"\]')

DEFAULT_KEY_EPSILON = 1e-6


def is_static_values(values: Sequence[float], *, epsilon: float = DEFAULT_KEY_EPSILON) -> bool:
    """True when all values are equal within *epsilon*."""
    if len(values) < 2:
        return False
    first = float(values[0])
    return all(abs(float(v) - first) <= epsilon for v in values[1:])


def should_remove_fcurve(
    num_keys: int,
    values: Sequence[float],
    *,
    clean_single: bool = True,
    clean_static: bool = True,
    epsilon: float = DEFAULT_KEY_EPSILON,
) -> bool:
    """Whether an fcurve should be removed as non-animating."""
    if num_keys <= 0:
        return False
    if clean_single and num_keys <= 1:
        return True
    if clean_static and num_keys >= 2 and is_static_values(values, epsilon=epsilon):
        return True
    return False


def values_from_keyframe_ys(keyframe_ys: Iterable[float]) -> List[float]:
    return [float(y) for y in keyframe_ys]


def pose_bone_name_from_fcurve_data_path(data_path: Optional[str]) -> Optional[str]:
    """Return pose-bone name when *data_path* targets ``pose.bones["…"]``."""
    if not data_path:
        return None
    match = _POSE_BONE_PATH_RE.search(data_path)
    if match is None:
        return None
    return match.group(1).replace('\\"', '"')


def is_constraint_fcurve_data_path(data_path: Optional[str]) -> bool:
    """True when *data_path* keys or drives a constraint property."""
    if not data_path:
        return False
    if data_path.startswith('constraints["'):
        return True
    return '.constraints["' in data_path
