"""Mesh writer authoring from numpy arrays. Needs pxr: runs in Blender's Python or with usd-core."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pxr = pytest.importorskip("pxr")

_WRITER_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/anim_usd_cache_mesh_writer.py"
)


def _writer_module():
    spec = importlib.util.spec_from_file_location("anim_usd_cache_mesh_writer", _WRITER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _new_mesh():
    stage = pxr.Usd.Stage.CreateInMemory()
    writer = _writer_module().UsdAnimCacheMeshWriter(stage)
    return writer, writer.define_mesh("/geo/mesh")


def test_compute_extent_is_min_and_max_per_axis():
    points = np.array([[1, -2, 3], [-4, 5, 0.5], [0, 0, -6]], dtype=np.float32)
    extent = _writer_module().UsdAnimCacheMeshWriter.compute_extent(points)
    assert [tuple(v) for v in extent] == [(-4.0, -2.0, -6.0), (1.0, 5.0, 3.0)]


def test_compute_extent_empty_is_two_zero_points():
    empty = np.empty((0, 3), dtype=np.float32)
    extent = _writer_module().UsdAnimCacheMeshWriter.compute_extent(empty)
    assert [tuple(v) for v in extent] == [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]


def test_write_frame_keeps_float32_values_exact():
    writer, mesh = _new_mesh()
    points = np.array([[0.1, 0.2, 0.3], [1e-7, -1e7, 3.3333333]], dtype=np.float32)
    writer.write_frame(mesh, points, 12.0)
    writer.finish()
    written = np.array(mesh.GetPointsAttr().Get(12.0), dtype=np.float32)
    assert written.tobytes() == points.tobytes()
    assert len(mesh.GetExtentAttr().Get(12.0)) == 2


def test_write_frame_empty_mesh():
    writer, mesh = _new_mesh()
    writer.write_frame(mesh, np.empty((0, 3), dtype=np.float32), 1.0)
    writer.finish()
    assert len(mesh.GetPointsAttr().Get(1.0)) == 0


def _points(value):
    return np.full((2, 3), value, dtype=np.float32)


def test_unchanged_mesh_gets_one_set_of_points_and_no_time_samples():
    writer, mesh = _new_mesh()
    for frame in (1.0, 2.0, 3.0):
        writer.write_frame(mesh, _points(5.0), frame)
    writer.finish()
    assert mesh.GetPointsAttr().GetTimeSamples() == []
    assert mesh.GetExtentAttr().GetTimeSamples() == []
    assert np.array(mesh.GetPointsAttr().Get(2.0)).tolist() == _points(5.0).tolist()
    assert len(mesh.GetExtentAttr().Get(2.0)) == 2


def test_mesh_that_starts_moving_late_has_every_frame_sampled():
    writer, mesh = _new_mesh()
    for frame, value in ((1.0, 5.0), (2.0, 5.0), (3.0, 6.0), (4.0, 6.0)):
        writer.write_frame(mesh, _points(value), frame)
    writer.finish()
    assert mesh.GetPointsAttr().GetTimeSamples() == [1.0, 2.0, 3.0, 4.0]
    assert mesh.GetExtentAttr().GetTimeSamples() == [1.0, 2.0, 3.0, 4.0]
    values = [float(mesh.GetPointsAttr().Get(f)[0][0]) for f in (1.0, 2.0, 3.0, 4.0)]
    assert values == [5.0, 5.0, 6.0, 6.0]


def test_change_in_vertex_count_counts_as_a_change():
    writer, mesh = _new_mesh()
    writer.write_frame(mesh, _points(5.0), 1.0)
    writer.write_frame(mesh, np.full((3, 3), 5.0, dtype=np.float32), 2.0)
    writer.finish()
    assert len(mesh.GetPointsAttr().Get(1.0)) == 2
    assert len(mesh.GetPointsAttr().Get(2.0)) == 3


def test_write_topology_from_int32_arrays():
    writer, mesh = _new_mesh()
    counts = np.array([4, 3], dtype=np.int32)
    indices = np.array([0, 1, 2, 3, 3, 2, 4], dtype=np.int32)
    writer.write_topology(mesh, counts, indices)
    assert list(mesh.GetFaceVertexCountsAttr().Get()) == [4, 3]
    assert list(mesh.GetFaceVertexIndicesAttr().Get()) == [0, 1, 2, 3, 3, 2, 4]
