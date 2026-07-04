"""Tests for position_scale_maya.logic (no Maya)."""

from __future__ import annotations

from tools.fx.position_scale_maya.logic import (
    as_vec3,
    scale_point_from_pivot,
    scale_positions_from_pivot,
)


def test_as_vec3_converts_values() -> None:
    assert as_vec3([1, "2", 3.5]) == (1.0, 2.0, 3.5)


def test_scale_point_from_pivot_uniform() -> None:
    assert scale_point_from_pivot((2.0, 0.0, 0.0), (1.0, 0.0, 0.0), (3.0, 3.0, 3.0)) == (
        4.0,
        0.0,
        0.0,
    )


def test_scale_positions_from_pivot_non_uniform() -> None:
    result = scale_positions_from_pivot(
        {
            "|A": (2.0, 4.0, 6.0),
            "|B": (0.0, 1.0, 2.0),
        },
        (1.0, 1.0, 1.0),
        (2.0, 3.0, 4.0),
    )
    assert result == {
        "|A": (3.0, 10.0, 21.0),
        "|B": (-1.0, 1.0, 5.0),
    }
