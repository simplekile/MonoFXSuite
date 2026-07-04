"""Tests for keyframe curve helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD = (
    Path(__file__).resolve().parents[1]
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/pipeline_common/anim_keys.py"
)
_spec = importlib.util.spec_from_file_location("monofx_anim_keys", _MOD)
assert _spec and _spec.loader
_keys = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_keys)


def test_is_static_values() -> None:
    assert _keys.is_static_values([1.0, 1.0, 1.0])
    assert not _keys.is_static_values([1.0, 2.0])
    assert not _keys.is_static_values([1.0])


def test_should_remove_single_key() -> None:
    assert _keys.should_remove_fcurve(1, [0.5], clean_single=True, clean_static=True)
    assert not _keys.should_remove_fcurve(2, [0.5, 1.0], clean_single=True, clean_static=True)


def test_should_remove_static_curve() -> None:
    assert _keys.should_remove_fcurve(3, [2.0, 2.0, 2.0], clean_single=True, clean_static=True)
    assert not _keys.should_remove_fcurve(0, [], clean_single=True, clean_static=True)
