"""Tests for work-file version description presets."""

from __future__ import annotations

from pathlib import Path

from monofx_pipeline_common import version_description_presets as presets


def test_detect_department_modelling():
    blend = Path(
        r"D:\proj\01_assets\_characters\char_A\01_modelling\02_retopo\blender\work\file.blend"
    )
    assert presets.detect_department_from_scene(blend) == "modelling"


def test_detect_department_rigging():
    blend = Path(
        r"D:\proj\01_assets\_characters\char_A\02_rigging\02_build_rig\blender\work\file.blend"
    )
    assert presets.detect_department_from_scene(blend) == "rigging"


def test_detect_department_anim():
    blend = Path(r"D:\proj\02_shots\sh002\01_anim\blender\work\char_anim_v001.blend")
    assert presets.detect_department_from_scene(blend) == "anim"


def test_detect_department_shot_fx():
    blend = Path(r"D:\proj\02_shots\sh002\02_fx\groom\blender\work\file.blend")
    assert presets.detect_department_from_scene(blend) == "shot_fx"


def test_detect_department_generic():
    blend = Path(r"D:\temp\my_scene.blend")
    assert presets.detect_department_from_scene(blend) == "generic"


def test_presets_filtered_by_department():
    anim_ids = {item[0] for item in presets.presets_for_department("anim")}
    modelling_ids = {item[0] for item in presets.presets_for_department("modelling")}
    assert "blockedCam" in anim_ids
    assert "blockedCam" not in modelling_ids
    assert "retopo" in modelling_ids
    for dept_id in presets.department_ids():
        assert len(presets.presets_for_department(dept_id)) == 10


def test_description_for_preset():
    assert presets.description_for_preset("anim", "blockedCam") == "blockedCam"
    assert presets.description_for_preset("anim", "NONE") == ""
    assert presets.description_for_preset("anim", "missing") is None


def test_match_preset_for_description():
    assert presets.match_preset_for_description("anim", "layoutPass") == "layoutPass"
    assert presets.match_preset_for_description("anim", "customNote") == "NONE"
    assert presets.match_preset_for_description("anim", "") == "NONE"
