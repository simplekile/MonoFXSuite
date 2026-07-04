"""Publish path resolution for MonoFX Pipeline Blender."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PUBLISH_PATHS = (
    Path(__file__).resolve().parents[1]
    / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender/publish_paths.py"
)
_spec = importlib.util.spec_from_file_location("monofx_publish_paths", _PUBLISH_PATHS)
assert _spec and _spec.loader
_pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pp)


def test_retopo_blend_resolves_to_retopo_publish():
    blend = Path(
        r"D:\Dropbox\Job\260425_grn_vp94\01_assets\_characters\char_Kahlii"
        r"\01_modelling\02_retopo\blender\work\char_Kahlii_retopo_v001.blend"
    )
    assert _pp.modelling_task_folder_from_scene(blend) == "02_retopo"
    root = _pp.resolve_publish_root_from_scene(blend)
    assert root is not None
    assert root.parts[-2:] == ("02_retopo", "publish")
    assert "char_Kahlii_retopo_publish" in _pp.default_usd_basename_from_scene(blend)
    usd = root / "v001" / f"{_pp.default_usd_basename_from_scene(blend)}.usd"
    rel = _pp.relative_publish_display(blend, usd)
    assert "02_retopo/publish/v001" in rel
    assert rel.endswith("char_Kahlii_retopo_publish.usd")


def test_uv_blend_resolves_to_uv_publish():
    blend = Path(
        r"D:\proj\01_assets\_characters\char_A"
        r"\01_modelling\03_uv\blender\work\scene.blend"
    )
    assert _pp.modelling_task_folder_from_scene(blend) == "03_uv"
    root = _pp.resolve_publish_root_from_scene(blend)
    assert root is not None
    assert root.parts[-2:] == ("03_uv", "publish")


def test_collection_publish_usd_basename_inserts_collection_slug():
    blend = Path(
        r"D:\proj\01_assets\_environments\env_House"
        r"\01_modelling\03_uv\blender\work\env_House_uv_v001.blend"
    )
    assert _pp.default_usd_basename_from_scene(blend) == "env_House_uv_publish"
    assert _pp.collection_publish_usd_basename(blend, "house1") == "env_House_uv_house1_publish"
    assert _pp.collection_publish_usd_basename(blend, "house _2") == "env_House_uv_house_2_publish"
    assert _pp.sanitize_collection_slug("  House _2  ") == "house_2"


def test_asset_name_from_retopo_blend_filename():
    blend = Path(
        r"D:\Dropbox\Job\260425_grn_vp94\01_assets\_characters\char_Kahlii"
        r"\01_modelling\02_retopo\blender\work\char_Kahlii_retopo_v005.blend"
    )
    assert _pp.asset_name_from_scene(blend) == "char_Kahlii"
    assert _pp.asset_name_from_blend_stem("char_Kahlii_retopo_v005", "retopo") == "char_Kahlii"
    assert _pp.asset_name_from_blend_stem("char_Kahlii_retopo_v005") == "char_Kahlii"


def test_asset_name_from_stem_without_pipeline_path():
    assert _pp.asset_name_from_blend_stem("prop_Table_uv_v002", "uv") == "prop_Table"
    assert _pp.asset_name_from_scene(Path(r"C:\temp\prop_Table_uv_v002.blend")) == "prop_Table"


def test_version_folder_and_auto_next():
    root = Path(r"D:\proj\01_assets\_characters\char_A\01_modelling\02_retopo\publish")
    assert _pp.version_folder_from_number(3) == "v003"
    assert _pp.auto_next_version_number(root) == 1


def test_blend_base_stem_strips_version_suffix():
    assert _pp.blend_base_stem("char_Kahlii_retopo_v005") == "char_Kahlii_retopo"
    assert _pp.blend_base_stem("char_Kahlii_retopo_v005_layout") == "char_Kahlii_retopo"
    assert _pp.blend_base_stem("char_Kahlii_retopo") == "char_Kahlii_retopo"
    assert _pp.version_number_from_blend_stem("char_Kahlii_retopo_v005") == 5
    assert _pp.version_number_from_blend_stem("char_Kahlii_retopo_v005_layout") == 5
    assert _pp.description_from_blend_stem("char_Kahlii_retopo_v005_layout") == "layout"
    assert _pp.version_number_from_blend_stem("char_Kahlii_retopo") is None


def test_build_blend_save_filename_with_description():
    assert _pp.build_blend_save_filename("char_Anim", 4, "layout pass") == "char_Anim_v004_layout_pass.blend"
    assert _pp.build_blend_save_filename("char_Anim", 4, "") == "char_Anim_v004.blend"


def test_preview_next_blend_version_uses_latest_in_folder(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    current = work / "char_Zephys_anim_v002.blend"
    current.write_text("blend", encoding="utf-8")
    (work / "char_Zephys_anim_v001.blend").write_text("old", encoding="utf-8")
    (work / "char_Zephys_anim_v004_layout.blend").write_text("other", encoding="utf-8")

    ok, num, err = _pp.preview_next_blend_version(current)
    assert ok, err
    assert num == 5


def test_version_number_taken_ignores_description(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "char_Zephys_anim_v004_noteA.blend").write_text("a", encoding="utf-8")
    current = work / "char_Zephys_anim_v003.blend"
    current.write_text("blend", encoding="utf-8")
    assert _pp.version_number_taken(work, "char_Zephys_anim", 4)
    assert not _pp.version_number_taken(work, "char_Zephys_anim", 5)


def test_next_blend_save_path_with_description(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    current = work / "char_Zephys_anim.blend"
    current.write_text("blend", encoding="utf-8")

    ok, path, err = _pp.next_blend_save_path(current, "blockedCam")
    assert ok, err
    assert path.endswith("char_Zephys_anim_v001_blockedCam.blend")


def test_next_blend_save_path_increments_in_work_folder(tmp_path):
    work = tmp_path / "blender" / "work"
    work.mkdir(parents=True)
    current = work / "char_Zephys_anim_v002.blend"
    current.write_text("blend", encoding="utf-8")
    (work / "char_Zephys_anim_v001.blend").write_text("old", encoding="utf-8")

    ok, path, err = _pp.next_blend_save_path(current)
    assert ok, err
    assert path.endswith("char_Zephys_anim_v003.blend")


def test_next_blend_save_path_first_version(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    current = work / "char_Zephys_anim.blend"
    current.write_text("blend", encoding="utf-8")

    ok, path, err = _pp.next_blend_save_path(current)
    assert ok, err
    assert path.endswith("char_Zephys_anim_v001.blend")


def test_next_blend_save_path_requires_saved_file():
    ok, path, err = _pp.next_blend_save_path(Path(""))
    assert not ok
    assert not path
    assert err
