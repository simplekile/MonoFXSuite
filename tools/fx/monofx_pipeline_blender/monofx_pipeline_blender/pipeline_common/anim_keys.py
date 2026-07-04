"""
Keyframe curve helpers (no bpy).
"""

from __future__ import annotations

from typing import Iterable, List, Sequence

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
