"""
Write UsdGeom.Mesh deformation data via the OpenUSD Python API.
"""

from __future__ import annotations

import logging
from typing import Sequence

from pxr import Gf, Usd, UsdGeom

logger = logging.getLogger("monofx.anim_usd_cache")


class UsdAnimCacheMeshWriter:
    """Author mesh topology once and animated points/extent per frame."""

    def __init__(self, stage: Usd.Stage) -> None:
        self._stage = stage

    @staticmethod
    def compute_extent(points: Sequence[Gf.Vec3f]) -> list[Gf.Vec3f]:
        if not points:
            return [Gf.Vec3f(0.0), Gf.Vec3f(0.0)]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        zs = [p[2] for p in points]
        return [
            Gf.Vec3f(min(xs), min(ys), min(zs)),
            Gf.Vec3f(max(xs), max(ys), max(zs)),
        ]

    def define_mesh(self, prim_path: str) -> UsdGeom.Mesh:
        mesh = UsdGeom.Mesh.Define(self._stage, prim_path)
        logger.debug("Defined mesh prim: %s", prim_path)
        return mesh

    def write_topology(
        self,
        mesh: UsdGeom.Mesh,
        face_vertex_counts: Sequence[int],
        face_vertex_indices: Sequence[int],
    ) -> None:
        """Write static topology at default time only."""
        counts_attr = mesh.CreateFaceVertexCountsAttr()
        indices_attr = mesh.CreateFaceVertexIndicesAttr()
        counts_attr.Set(list(face_vertex_counts))
        indices_attr.Set(list(face_vertex_indices))
        logger.debug(
            "Wrote topology: %d faces, %d indices",
            len(face_vertex_counts),
            len(face_vertex_indices),
        )

    def write_frame(
        self,
        mesh: UsdGeom.Mesh,
        points: Sequence[Gf.Vec3f],
        frame: float,
    ) -> None:
        time_code = Usd.TimeCode(frame)
        mesh.GetPointsAttr().Set(list(points), time_code)
        extent = self.compute_extent(points)
        mesh.GetExtentAttr().Set(extent, time_code)
