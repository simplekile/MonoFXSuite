"""Tests for shot collection rename planning."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PC = (
    Path(__file__).resolve().parents[1]
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/pipeline_common"
)
_PKG = "monofx_pipeline_blender.pipeline_common"


def _load_module(name: str, filename: str):
    full_name = f"{_PKG}.{name}"
    spec = importlib.util.spec_from_file_location(
        full_name,
        _PC / filename,
        submodule_search_locations=[str(_PC)],
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = _PKG
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


_load_module("project_layout", "project_layout.py")
_load_module("shot_paths", "shot_paths.py")
_fix = _load_module("shot_collection_fix", "shot_collection_fix.py")

canonical_child_collection_name = _fix.canonical_child_collection_name
child_names_to_fix = _fix.child_names_to_fix
plan_shot_root_rename = _fix.plan_shot_root_rename


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
