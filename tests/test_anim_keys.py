"""Tests for keyframe curve helpers."""

from __future__ import annotations

from monofx_pipeline_common import anim_keys as _keys


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


def test_pose_bone_name_from_fcurve_data_path() -> None:
    assert _keys.pose_bone_name_from_fcurve_data_path('pose.bones["spine"]') == "spine"
    assert (
        _keys.pose_bone_name_from_fcurve_data_path('pose.bones["spine"].location')
        == "spine"
    )
    assert (
        _keys.pose_bone_name_from_fcurve_data_path(
            'pose.bones["hand.L"].constraints["IK"].influence'
        )
        == "hand.L"
    )
    assert _keys.pose_bone_name_from_fcurve_data_path("location") is None
    assert _keys.pose_bone_name_from_fcurve_data_path(None) is None


def test_is_constraint_fcurve_data_path() -> None:
    assert _keys.is_constraint_fcurve_data_path('constraints["Copy Location"].influence')
    assert _keys.is_constraint_fcurve_data_path(
        'pose.bones["spine"].constraints["Stretch To"].influence'
    )
    assert not _keys.is_constraint_fcurve_data_path('pose.bones["spine"].location')
