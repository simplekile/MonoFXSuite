"""
Skip unchanged per-frame mesh points when authoring anim USD caches (no bpy).

A static mesh exported over N frames needs only a first and a last sample, not N.
Samples are still authored right before and at every change, so linear
interpolation between consecutive USD time samples reproduces every frame exactly.
"""

from __future__ import annotations

from typing import Optional

import numpy as np


class PointSampleFilter:
    """Decide which (frame, points) samples must be written for one mesh."""

    def __init__(self) -> None:
        self._last_points: Optional[np.ndarray] = None
        self._last_frame: float = 0.0
        self._last_written_frame: Optional[float] = None

    def push(self, frame: float, points: np.ndarray) -> list[tuple[float, np.ndarray]]:
        """Return the samples to write now for ``points`` evaluated at ``frame``."""
        if self._last_points is None:
            self._remember(frame, points, written=True)
            return [(frame, points)]
        if points.shape == self._last_points.shape and np.array_equal(
            points, self._last_points
        ):
            self._last_frame = frame
            return []
        out: list[tuple[float, np.ndarray]] = []
        if self._last_written_frame != self._last_frame:
            # Close the hold so earlier frames do not interpolate toward the change.
            out.append((self._last_frame, self._last_points))
        out.append((frame, points))
        self._remember(frame, points, written=True)
        return out

    def flush(self) -> list[tuple[float, np.ndarray]]:
        """Samples still owed at the end (the last held frame)."""
        if (
            self._last_points is not None
            and self._last_written_frame != self._last_frame
        ):
            self._last_written_frame = self._last_frame
            return [(self._last_frame, self._last_points)]
        return []

    def _remember(self, frame: float, points: np.ndarray, *, written: bool) -> None:
        self._last_points = points
        self._last_frame = frame
        if written:
            self._last_written_frame = frame


def degenerate_points_reason(points: np.ndarray) -> Optional[str]:
    """Why an evaluated mesh's points are unusable, or None when they look fine.

    Catches a modifier that collapses a mesh (all points at the origin, e.g. a Geometry Nodes
    setup with no source object), an empty result, and NaN/inf points.
    """
    arr = np.asarray(points)
    if arr.shape[0] == 0:
        return "no points"
    if not np.isfinite(arr).all():
        return "non-finite (NaN/inf) points"
    if arr.shape[0] > 1 and not arr.any():
        return f"all {arr.shape[0]} points are at the origin (0,0,0)"
    return None


__all__ = ["PointSampleFilter", "degenerate_points_reason"]
