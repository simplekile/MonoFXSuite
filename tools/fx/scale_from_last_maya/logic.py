"""Pure math for scaling transform positions around a pivot."""

from __future__ import annotations

from typing import Dict, Iterable, Tuple

Vec3 = Tuple[float, float, float]


def as_vec3(values: Iterable[float], default: Vec3 = (1.0, 1.0, 1.0)) -> Vec3:
    vals = list(values)
    if len(vals) != 3:
        return default
    try:
        return (float(vals[0]), float(vals[1]), float(vals[2]))
    except Exception:
        return default


def scale_point_from_pivot(point: Vec3, pivot: Vec3, scale_xyz: Vec3) -> Vec3:
    px, py, pz = point
    cx, cy, cz = pivot
    sx, sy, sz = scale_xyz
    return (
        cx + ((px - cx) * sx),
        cy + ((py - cy) * sy),
        cz + ((pz - cz) * sz),
    )


def scale_positions_from_pivot(
    initial_positions: Dict[str, Vec3],
    pivot: Vec3,
    scale_xyz: Vec3,
) -> Dict[str, Vec3]:
    return {
        node: scale_point_from_pivot(pos, pivot, scale_xyz)
        for node, pos in initial_positions.items()
    }
