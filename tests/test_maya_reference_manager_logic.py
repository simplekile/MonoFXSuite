"""Tests for maya_reference_manager.logic (no Maya)."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.common.project_layout import find_project_root, list_asset_groups, list_publish_version_dirs
from tools.fx.maya_reference_manager.logic import (
    display_name_from_asset_folder,
    library_location_for_file,
    matching_rig_versions_for_scene_path,
    newer_rig_version_for_scene_path,
    rig_paths_equivalent,
    rig_version_index_for_scene_path,
    scan_rigs,
    scene_ref_version_display,
    thumb_path_for_asset,
    thumb_path_for_reference_file,
    version_display_token_from_path,
)


@pytest.fixture()
def fake_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "01_assets").mkdir(parents=True)
    (root / "02_shots").mkdir(parents=True)
    ch = root / "01_assets" / "_characters" / "char_Errol"
    pub = ch / "02_rigging" / "02_build_rig" / "publish"
    (pub / "V001").mkdir(parents=True)
    (pub / "v002").mkdir(parents=True)
    (pub / "V001" / "char_Errol_rig_Publish.mb").write_text("x", encoding="utf-8")
    (pub / "v002" / "char_Errol_rig_Publish.mb").write_text("y", encoding="utf-8")
    work = ch / "02_rigging" / "02_build_rig" / "maya" / "work"
    work.mkdir(parents=True)
    (work / "char_Errol_rig_v003.ma").write_text("z", encoding="utf-8")
    (work / "char_Errol_rig_v001.ma").write_text("a", encoding="utf-8")
    meta = ch / ".meta"
    meta.mkdir(parents=True)
    (meta / "thumb_rig.user.png").write_bytes(b"\x89PNG\r\n")
    return root


def test_find_project_root(fake_project: Path) -> None:
    assert find_project_root(fake_project / "01_assets" / "_characters" / "char_Errol") == fake_project


def test_list_asset_groups(fake_project: Path) -> None:
    assert list_asset_groups(fake_project) == ["_characters"]


def test_list_publish_version_dirs(fake_project: Path) -> None:
    pub = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
    )
    dirs = list_publish_version_dirs(pub)
    assert [d.name for d in dirs] == ["V001", "v002"]


def test_scan_rigs_publish(fake_project: Path) -> None:
    offers = scan_rigs(fake_project, "_characters", "publish")
    assert len(offers) == 1
    o = offers[0]
    assert o.asset_folder_name == "char_Errol"
    assert o.display_name == "Errol"
    assert len(o.versions) == 2
    assert o.versions[o.default_index].label.startswith("v002")


def test_scan_rigs_work(fake_project: Path) -> None:
    offers = scan_rigs(fake_project, "_characters", "work")
    assert len(offers) == 1
    o = offers[0]
    assert len(o.versions) == 2
    labels = [v.label for v in o.versions]
    assert "char_Errol_rig_v001.ma" in labels and "char_Errol_rig_v003.ma" in labels
    assert o.versions[o.default_index].label == "char_Errol_rig_v003.ma"


def test_thumb_path(fake_project: Path) -> None:
    ar = fake_project / "01_assets" / "_characters" / "char_Errol"
    tp = thumb_path_for_asset(ar)
    assert tp.name == "thumb_rig.user.png"
    assert tp.is_file()


def test_display_name() -> None:
    assert display_name_from_asset_folder("char_Errol") == "Errol"


def test_library_location_for_file(fake_project: Path) -> None:
    f = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "V001"
        / "char_Errol_rig_Publish.mb"
    )
    loc = library_location_for_file(str(f), fake_project)
    assert loc == ("_characters", "char_Errol")


def test_thumb_path_for_reference_file(fake_project: Path) -> None:
    f = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "V001"
        / "char_Errol_rig_Publish.mb"
    )
    tp = thumb_path_for_reference_file(str(f), fake_project)
    assert tp is not None
    assert tp.name == "thumb_rig.user.png"


def test_thumb_path_for_reference_file_outside_project(fake_project: Path) -> None:
    assert thumb_path_for_reference_file(r"C:\outside\file.ma", fake_project) is None


def test_newer_rig_version_publish(fake_project: Path) -> None:
    v1 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "V001"
        / "char_Errol_rig_Publish.mb"
    )
    ent = newer_rig_version_for_scene_path(str(v1), fake_project, "publish")
    assert ent is not None
    assert "v002" in ent.label.lower()
    assert ent.path.endswith("char_Errol_rig_Publish.mb")

    v2 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "v002"
        / "char_Errol_rig_Publish.mb"
    )
    assert newer_rig_version_for_scene_path(str(v2), fake_project, "publish") is None


def test_version_display_token_publish(fake_project: Path) -> None:
    v1 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "V001"
        / "char_Errol_rig_Publish.mb"
    )
    assert version_display_token_from_path(str(v1), "publish") == "v001"
    v2 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "v002"
        / "char_Errol_rig_Publish.mb"
    )
    assert version_display_token_from_path(str(v2), "publish") == "v002"


def test_version_display_token_work(fake_project: Path) -> None:
    w3 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "maya"
        / "work"
        / "char_Errol_rig_v003.ma"
    )
    assert version_display_token_from_path(str(w3), "work") == "v003"


def test_scene_ref_version_display_behind_and_newest(fake_project: Path) -> None:
    v1 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "V001"
        / "char_Errol_rig_Publish.mb"
    )
    v2 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "v002"
        / "char_Errol_rig_Publish.mb"
    )
    d_behind = scene_ref_version_display(str(v1), fake_project, "publish")
    assert d_behind is not None
    assert d_behind.has_scan_match
    assert not d_behind.is_on_newest
    assert d_behind.current_token == "v001"
    assert d_behind.newest_token == "v002"

    d_ok = scene_ref_version_display(str(v2), fake_project, "publish")
    assert d_ok is not None
    assert d_ok.is_on_newest
    assert d_ok.newest_token == "v002"


def test_matching_rig_versions_publish_lists_all(fake_project: Path) -> None:
    v1 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "V001"
        / "char_Errol_rig_Publish.mb"
    )
    ents = matching_rig_versions_for_scene_path(str(v1), fake_project, "publish")
    assert len(ents) == 2
    assert ents[0].label.lower().startswith("v001")
    assert ents[-1].label.lower().startswith("v002")


def test_rig_version_index_for_scene_path(fake_project: Path) -> None:
    v1 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "V001"
        / "char_Errol_rig_Publish.mb"
    )
    v2 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "publish"
        / "v002"
        / "char_Errol_rig_Publish.mb"
    )
    ents = matching_rig_versions_for_scene_path(str(v1), fake_project, "publish")
    assert rig_version_index_for_scene_path(str(v1), ents) == 0
    assert rig_version_index_for_scene_path(str(v2), ents) == 1


def test_rig_paths_equivalent(fake_project: Path) -> None:
    a = fake_project / "01_assets" / "_characters" / "char_Errol"
    b = a.resolve()
    assert rig_paths_equivalent(str(a), str(b))


def test_newer_rig_version_work(fake_project: Path) -> None:
    w1 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "maya"
        / "work"
        / "char_Errol_rig_v001.ma"
    )
    ent = newer_rig_version_for_scene_path(str(w1), fake_project, "work")
    assert ent is not None
    assert "v003" in ent.label
    w3 = (
        fake_project
        / "01_assets"
        / "_characters"
        / "char_Errol"
        / "02_rigging"
        / "02_build_rig"
        / "maya"
        / "work"
        / "char_Errol_rig_v003.ma"
    )
    assert newer_rig_version_for_scene_path(str(w3), fake_project, "work") is None
