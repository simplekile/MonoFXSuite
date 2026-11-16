"""Blender's static USD export leaves fps at 24; the exporter stamps the scene fps (needs pxr)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("pxr")
from pxr import Sdf  # noqa: E402

_MOD = (
    Path(__file__).resolve().parents[1]
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/usd_stage_fps.py"
)
_spec = importlib.util.spec_from_file_location("usd_stage_fps", _MOD)
fps_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fps_mod)

_USDA = """#usda 1.0
(
    defaultPrim = "Geo"
    timeCodesPerSecond = 24
    framesPerSecond = 24
)
def Xform "Geo"
{
}
"""


def _write(tmp_path, text=_USDA):
    path = tmp_path / "m.usda"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_stamps_time_codes_and_frames_per_second(tmp_path):
    path = _write(tmp_path)
    assert fps_mod.stamp_fps(path, 30.0) is True
    layer = Sdf.Layer.FindOrOpen(path)
    assert layer.timeCodesPerSecond == 30.0
    assert layer.framesPerSecond == 30.0


def test_same_fps_does_not_rewrite_the_file(tmp_path):
    path = _write(tmp_path)
    before = Path(path).read_text(encoding="utf-8")
    assert fps_mod.stamp_fps(path, 24.0) is False
    assert Path(path).read_text(encoding="utf-8") == before


def test_fractional_fps_is_kept(tmp_path):
    path = _write(tmp_path)
    fps_mod.stamp_fps(path, 29.97)
    assert Sdf.Layer.FindOrOpen(path).timeCodesPerSecond == pytest.approx(29.97)


def test_invalid_fps_or_path_changes_nothing(tmp_path):
    path = _write(tmp_path)
    assert fps_mod.stamp_fps(path, 0) is False
    assert fps_mod.stamp_fps(path, -5) is False
    assert fps_mod.stamp_fps(str(tmp_path / "missing.usda"), 30) is False
    assert Sdf.Layer.FindOrOpen(path).timeCodesPerSecond == 24.0


def test_file_overwritten_while_its_layer_is_open(tmp_path):
    # Something in the session still holds the layer from before the export rewrote the file
    # (same second, so the timestamp looks unchanged): the stamp must use the new file.
    path = tmp_path / "m.usda"
    path.write_text('#usda 1.0\n(\n    defaultPrim = "Old"\n)\ndef Xform "Old" {}\n', encoding="utf-8")
    held = Sdf.Layer.FindOrOpen(str(path))
    path.write_text('#usda 1.0\n(\n    defaultPrim = "Geo"\n)\ndef Xform "Geo" {}\n', encoding="utf-8")
    assert fps_mod.stamp_fps(str(path), 30.0) is True
    text = path.read_text(encoding="utf-8")
    assert '"Geo"' in text and '"Old"' not in text
    assert held is not None
