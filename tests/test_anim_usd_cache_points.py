"""Tests for skipping unchanged per-frame mesh points in anim USD export."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
_path = (
    _ROOT
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/anim_usd_cache_points.py"
)
_spec = importlib.util.spec_from_file_location("anim_usd_cache_points", _path)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
PointSampleFilter = _mod.PointSampleFilter


def _pts(v: float) -> np.ndarray:
    return np.full((4, 3), v, dtype=np.float32)


def _run(values: list[float], first_frame: int = 0):
    f = PointSampleFilter()
    written: list[tuple[float, float]] = []
    for i, v in enumerate(values):
        for frame, pts in f.push(float(first_frame + i), _pts(v)):
            written.append((frame, float(pts[0, 0])))
    for frame, pts in f.flush():
        written.append((frame, float(pts[0, 0])))
    return written


def test_static_mesh_writes_only_first_and_last_frame():
    assert _run([1.0] * 46) == [(0.0, 1.0), (45.0, 1.0)]


def test_single_frame_writes_one_sample():
    assert _run([2.0]) == [(0.0, 2.0)]


def test_every_frame_changing_writes_every_frame():
    out = _run([1.0, 2.0, 3.0, 4.0])
    assert out == [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0)]


def test_hold_then_move_keeps_held_value_until_change():
    # Frames 0-4 equal, move at 5: need the last held frame (4) so frames 1-3
    # do not interpolate toward the new value.
    out = _run([1.0, 1.0, 1.0, 1.0, 1.0, 9.0, 9.0, 9.0])
    assert out == [(0.0, 1.0), (4.0, 1.0), (5.0, 9.0), (7.0, 9.0)]


def test_move_then_hold_writes_end_of_hold():
    out = _run([1.0, 2.0, 2.0, 2.0])
    assert out == [(0.0, 1.0), (1.0, 2.0), (3.0, 2.0)]


def test_expanding_samples_reproduces_every_frame():
    values = [1, 1, 1, 5, 5, 6, 6, 6, 6, 2]
    out = _run([float(v) for v in values])
    samples = dict(out)
    frames = sorted(samples)
    for i, expected in enumerate(values):
        lo = max(f for f in frames if f <= i)
        hi = min(f for f in frames if f >= i)
        if lo == hi:
            got = samples[lo]
        else:
            t = (i - lo) / (hi - lo)
            got = samples[lo] * (1 - t) + samples[hi] * t
        assert abs(got - expected) < 1e-6, (i, got, expected)
