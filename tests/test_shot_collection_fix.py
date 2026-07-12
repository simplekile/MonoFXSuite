"""Tests for shot collection rename planning."""

from __future__ import annotations

from monofx_pipeline_common.shot_collection_fix import (
    canonical_child_collection_name,
    child_names_to_fix,
    plan_shot_root_rename,
)


def test_plan_shot_root_rename_single_wrong_shot() -> None:
    plan = plan_shot_root_rename("sh010", ["Anim_sh001"])
    assert plan == ("Anim_sh001", "Anim_sh010")


def test_plan_shot_root_rename_case_only() -> None:
    plan = plan_shot_root_rename("sh010", ["Anim_SH010", "Anim_sh010"])
    assert plan == ("Anim_SH010", "Anim_sh010")


def test_plan_shot_root_rename_already_correct() -> None:
    assert plan_shot_root_rename("sh010", ["Anim_sh010"]) is None


def test_plan_shot_root_rename_ambiguous() -> None:
    assert plan_shot_root_rename("sh010", ["Anim_sh001", "Anim_sh002"]) is None


def test_child_names_to_fix() -> None:
    fixes = child_names_to_fix(["cameras", "Characters", "Props"])
    assert ("cameras", "Cameras") in fixes
    assert canonical_child_collection_name("LIGHTING") == "Lighting"
