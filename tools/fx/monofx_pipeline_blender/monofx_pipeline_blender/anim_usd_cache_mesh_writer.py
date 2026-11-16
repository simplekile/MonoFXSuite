"""
Write UsdGeom.Mesh deformation data via the OpenUSD Python API.
"""

from __future__ import annotations

import logging
from typing import Sequence

import numpy as np
from pxr import Gf, Usd, UsdGeom, Vt

logger = logging.getLogger("monofx.anim_usd_cache")


class UsdAnimCacheMeshWriter:
    """Author mesh topology once and animated points/extent per frame."""

    def __init__(self, stage: Usd.Stage) -> None:
        self._stage = stage

    @staticmethod
    def compute_extent(points) -> list[Gf.Vec3f]:
        """Bounding box of ``points`` (``(N, 3)`` array or a sequence of vectors)."""
        arr = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        if arr.shape[0] == 0:
            return [Gf.Vec3f(0.0), Gf.Vec3f(0.0)]
        lo = arr.min(axis=0)
        hi = arr.max(axis=0)
        return [
            Gf.Vec3f(float(lo[0]), float(lo[1]), float(lo[2])),
            Gf.Vec3f(float(hi[0]), float(hi[1]), float(hi[2])),
        ]

    def define_mesh(self, prim_path: str) -> UsdGeom.Mesh:
        mesh = UsdGeom.Mesh.Define(self._stage, prim_path)
        logger.debug("Defined mesh prim: %s", prim_path)
        return mesh

    def write_subdivision_scheme(self, mesh: UsdGeom.Mesh, scheme: str) -> None:
        """Author ``subdivisionScheme`` at default time (USD's fallback is catmullClark)."""
        mesh.CreateSubdivisionSchemeAttr().Set(scheme)

    def write_topology(
        self,
        mesh: UsdGeom.Mesh,
        face_vertex_counts: Sequence[int],
        face_vertex_indices: Sequence[int],
    ) -> None:
        """Write static topology at default time only."""
        counts_attr = mesh.CreateFaceVertexCountsAttr()
        indices_attr = mesh.CreateFaceVertexIndicesAttr()
        counts_attr.Set(
            Vt.IntArray.FromNumpy(np.asarray(face_vertex_counts, dtype=np.int32))
        )
        indices_attr.Set(
            Vt.IntArray.FromNumpy(np.asarray(face_vertex_indices, dtype=np.int32))
        )
        logger.debug(
            "Wrote topology: %d faces, %d indices",
            len(face_vertex_counts),
            len(face_vertex_indices),
        )

    def write_frame(
        self,
        mesh: UsdGeom.Mesh,
        points,
        frame: float,
    ) -> None:
        """Author one points/extent time sample from an ``(N, 3)`` float32 array."""
        time_code = Usd.TimeCode(frame)
        arr = np.ascontiguousarray(points, dtype=np.float32).reshape(-1, 3)
        mesh.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(arr), time_code)
        mesh.GetExtentAttr().Set(self.compute_extent(arr), time_code)
