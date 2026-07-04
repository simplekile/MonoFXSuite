"""Tests for shared rig_library with Blender .blend paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.common.rig_library import (
    BLENDER_EXTENSIONS,
    DEFAULT_BLENDER_WORK_SUBPATH,
    matching_rig_versions_for_scene_path,
    newer_rig_version_for_scene_path,
    rig_paths_equivalent,
    scan_rigs,
    version_display_token_from_path,
)


@pytest.fixture()
def fake_project_blend(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "01_assets").mkdir(parents=True)
    (root / "02_shots").mkdir(parents=True)
    ch = root / "01_assets" / "_characters" / "char_Errol"
    pub = ch / "02_rigging" / "02_build_rig" / "publish"
    (pub / "V001").mkdir(parents=True)
    (pub / "v002").mkdir(parents=True)
    (pub / "V001" / "char_Errol_rig_Publish.mb").write_text("maya", encoding="utf-8")
    (pub / "V001" / "char_Errol_rig_Publish.blend").write_text("blend1", encoding="utf-8")
    (pub / "v002" / "char_Errol_rig_Publish.mb").write_text("maya2", encoding="utf-8")
    (pub / "v002" / "char_Errol_rig_Publish.blend").write_text("blend2", encoding="utf-8")
    work = ch / "02_rigging" / "02_build_rig" / "blender" / "work"
    work.mkdir(parents=True)
    (work / "char_Errol_rig_v001.blend").write_text("w1", encoding="utf-8")
    (work / "char_Errol_rig_v003.blend").write_text("w3", encoding="utf-8")
    return root


def test_scan_blender_publish_only_blend(fake_project_blend: Path) -> None:
    offers = scan_rigs(
        fake_project_blend,
        "_characters",
        "publish",
        extensions=BLENDER_EXTENSIONS,
    )
    assert len(offers) == 1
    offer = offers[0]
    assert offer.asset_folder_name == "char_Errol"
    assert len(offer.versions) == 2
    assert all(Path(v.path).suffix.lower() == ".blend" for v in offer.versions)
    assert offer.versions[-1].path.endswith("char_Errol_rig_Publish.blend")
    assert "v002" in offer.versions[-1].path.replace("\\", "/")


def test_scan_blender_work(fake_project_blend: Path) -> None:
    offers = scan_rigs(
        fake_project_blend,
        "_characters",
        "work",
        work_subpath=DEFAULT_BLENDER_WORK_SUBPATH,
        extensions=BLENDER_EXTENSIONS,
    )
    assert len(offers) == 1
    assert len(offers[0].versions) == 2
    assert offers[0].versions[-1].path.endswith("char_Errol_rig_v003.blend")


def test_blender_version_tokens(fake_project_blend: Path) -> None:
    pub_path = (
        fake_project_blend
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "v002"
        / "char_Errol_rig_Publish.blend"
    )
    assert version_display_token_from_path(str(pub_path), "publish") == "v002"


def test_matching_blender_versions_shared_publish(fake_project_blend: Path) -> None:
    v1 = (
        fake_project_blend
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "V001"
        / "char_Errol_rig_Publish.blend"
    )
    entries = matching_rig_versions_for_scene_path(
        str(v1),
        fake_project_blend,
        "publish",
        extensions=BLENDER_EXTENSIONS,
    )
    assert len(entries) == 2
    assert entries[0].path.replace("\\", "/").endswith("V001/char_Errol_rig_Publish.blend")
    assert entries[-1].path.replace("\\", "/").endswith("v002/char_Errol_rig_Publish.blend")


def test_newer_blender_version(fake_project_blend: Path) -> None:
    v1 = (
        fake_project_blend
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "V001"
        / "char_Errol_rig_Publish.blend"
    )
    newer = newer_rig_version_for_scene_path(
        str(v1),
        fake_project_blend,
        "publish",
        extensions=BLENDER_EXTENSIONS,
    )
    assert newer is not None
    assert rig_paths_equivalent(newer.path, str(
        fake_project_blend
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "v002"
        / "char_Errol_rig_Publish.blend"
    ))
