"""
Write UsdGeom.Mesh deformation data via the OpenUSD Python API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from pxr import Usd, UsdGeom, Vt

logger = logging.getLogger("monofx.anim_usd_cache")


def _vec3f_array(values: np.ndarray) -> Vt.Vec3fArray:
    """``values`` is float32, shape (N, 3)."""
    if not len(values):
        return Vt.Vec3fArray()
    return Vt.Vec3fArray.FromNumpy(values)


@dataclass
class _HeldPoints:
    """A mesh's points while every frame so far matches the first; ``None`` once it has changed."""

    mesh: UsdGeom.Mesh
    points: Optional[np.ndarray]
    frames: list[float] = field(default_factory=list)


class UsdAnimCacheMeshWriter:
    """Author mesh topology once and points/extent per frame, only for meshes that change."""

    def __init__(self, stage: Usd.Stage) -> None:
        self._stage = stage
        self._held: dict[str, _HeldPoints] = {}

    @staticmethod
    def compute_extent(points: np.ndarray) -> Vt.Vec3fArray:
        if not len(points):
            return Vt.Vec3fArray(2)
        return Vt.Vec3fArray.FromNumpy(
            np.stack((points.min(axis=0), points.max(axis=0)))
        )

    def define_mesh(self, prim_path: str) -> UsdGeom.Mesh:
        mesh = UsdGeom.Mesh.Define(self._stage, prim_path)
        logger.debug("Defined mesh prim: %s", prim_path)
        return mesh

    def write_topology(
        self,
        mesh: UsdGeom.Mesh,
        face_vertex_counts: np.ndarray,
        face_vertex_indices: np.ndarray,
    ) -> None:
        """Write static topology at default time only (int32 arrays)."""
        counts_attr = mesh.CreateFaceVertexCountsAttr()
        indices_attr = mesh.CreateFaceVertexIndicesAttr()
        counts_attr.Set(Vt.IntArray.FromNumpy(face_vertex_counts))
        indices_attr.Set(Vt.IntArray.FromNumpy(face_vertex_indices))
        logger.debug(
            "Wrote topology: %d faces, %d indices",
            len(face_vertex_counts),
            len(face_vertex_indices),
        )

    def _author_points(
        self,
        mesh: UsdGeom.Mesh,
        points: np.ndarray,
        time_code: Usd.TimeCode,
    ) -> None:
        mesh.GetPointsAttr().Set(_vec3f_array(points), time_code)
        mesh.GetExtentAttr().Set(self.compute_extent(points), time_code)

    def write_frame(
        self,
        mesh: UsdGeom.Mesh,
        points: np.ndarray,
        frame: float,
    ) -> None:
        """
        ``points`` is float32, shape (N, 3). Compares evaluated data, so drivers, shape keys and
        constraints count too. The first change also authors the frames held until then.
        """
        key = str(mesh.GetPath())
        held = self._held.get(key)
        if held is None:
            self._held[key] = _HeldPoints(mesh, points, [frame])
            return
        if held.points is not None:
            if np.array_equal(points, held.points):
                held.frames.append(frame)
                return
            for held_frame in held.frames:
                self._author_points(mesh, held.points, Usd.TimeCode(held_frame))
            held.points = None
            held.frames = []
        self._author_points(mesh, points, Usd.TimeCode(frame))

    def finish(self) -> None:
        """Meshes that never changed get one set of points and one extent, at default time."""
        for held in self._held.values():
            if held.points is not None:
                self._author_points(held.mesh, held.points, Usd.TimeCode.Default())
        self._held = {}
