"""Tests for exact keyframe edit helpers."""

from __future__ import annotations

from monofx_pipeline_common import anim_exact_key as _exact


def test_fcurve_channel_label() -> None:
    assert _exact.fcurve_channel_label("location", 2) == "location [Z]"
    assert _exact.fcurve_channel_label('pose.bones["spine"].rotation_euler', 0) == (
        'pose.bones["spine"].rotation_euler [X]'
    )
    assert _exact.fcurve_channel_label(None, 4) == "<channel> [4]"


def test_apply_keyframe_value_delta() -> None:
    value, hl, hr = _exact.apply_keyframe_value_delta(89.4, 90.0, 88.0, 91.0)
    assert value == 90.0
    assert abs(hl - 88.6) < 1e-6
    assert abs(hr - 91.6) < 1e-6


def test_apply_keyframe_frame_delta() -> None:
    frame, hl, hr = _exact.apply_keyframe_frame_delta(24.0, 30.0, 20.0, 28.0)
    assert frame == 30.0
    assert hl == 26.0
    assert hr == 34.0
