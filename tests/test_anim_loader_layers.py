"""Sublayer / Reference LOPs that read a publish: parse, versions, status, patterns moved under a loader's prim."""

from __future__ import annotations

from tests.anim_loader_tree import make
from tools.fx.anim_loader.logic import (
    STATUS_MISSING,
    STATUS_NEWER,
    STATUS_OK,
    parse_publish_path,
    ref_status,
    ref_versions,
    root_patterns_moved,
)

CLIFF = "01_assets/_props/prop_Cliff01"


def test_parse_asset_and_shot_paths(tmp_path):
    r = parse_publish_path(r"D:\Job\proj\01_assets\_props\prop_Cliff01\05_lookdev\publish\v001"
                           "\\prop_Cliff01_lookdev_publish.usdc")  # Windows separators, as the env scene has them
    assert (r.root, r.kind, r.entity, r.dept, r.version, r.file, r.part) == (
        "D:/Job/proj", "asset", "prop_Cliff01", "05_lookdev", "v001", "prop_Cliff01_lookdev_publish.usdc", "lookdev")
    uv = parse_publish_path("D:/Job/proj/01_assets/_props/prop_M/01_modelling/03_uv/publish/v003/prop_M_uv_v003.usdc")
    assert (uv.dept, uv.part, uv.word, uv.file_in("v004")) == ("01_modelling/03_uv", "anim", "model",
                                                              "prop_M_uv_v004.usdc")
    shot = parse_publish_path("D:/Job/proj/02_shots/sh025/01_anim/publish/v005/geo_char_Helen.usd")
    assert (shot.kind, shot.entity, shot.word) == ("shot", "sh025", "anim")
    assert parse_publish_path("$HIP/geo.usd") is None and parse_publish_path("D:/stuff/a.usd") is None


def test_versions_and_status_follow_the_file(tmp_path):
    root = make(tmp_path, [f"{CLIFF}/05_lookdev/publish/v001/prop_Cliff01_lookdev_publish.usdc",
                           f"{CLIFF}/05_lookdev/publish/v002/prop_Cliff01_lookdev_publish.usdc",
                           f"{CLIFF}/05_lookdev/publish/v003/other.usd"])
    r = parse_publish_path(f"{root.as_posix()}/{CLIFF}/05_lookdev/publish/v001/prop_Cliff01_lookdev_publish.usdc")
    assert ref_versions(r) == ["v001", "v002"]               # v003 lacks the file
    assert ref_status(r) == (STATUS_NEWER, "v002")
    assert r.path_in("v002").endswith("v002/prop_Cliff01_lookdev_publish.usdc")
    gone = parse_publish_path(f"{root.as_posix()}/{CLIFF}/05_lookdev/publish/v009/prop_Cliff01_lookdev_publish.usdc")
    assert ref_status(gone) == (STATUS_MISSING, None)
    latest = parse_publish_path(f"{root.as_posix()}/{CLIFF}/05_lookdev/publish/v002/prop_Cliff01_lookdev_publish.usdc")
    assert ref_status(latest) == (STATUS_OK, None)


def test_patterns_move_under_the_loader_prim():
    roots = ["Cliff01_Low", "_materials", "SeaGrass"]
    assert root_patterns_moved("/Cliff01_Low /_materials /SeaGrass/** /Other %type:Mesh", roots, "Cliff01") == \
        "/Cliff01/Cliff01_Low /Cliff01/_materials /Cliff01/SeaGrass/** /Other %type:Mesh"


def test_only_uv_models_and_lookdevs_become_loaders():
    """char_Mermaid_texturing_geo (the user's report, 2026-11-20): a Sublayer of the texturing geo was upgraded to a
    loader looking for the file in 03_uv, "missing". It is a texturing publish and stays a Sublayer."""
    base = "D:/Job/proj/01_assets/_characters/char_Mermaid"
    tex = parse_publish_path(f"{base}/03_surfacing/02_texturing/publish/v001/char_Mermaid_texturing_v001.usd")
    uv = parse_publish_path(f"{base}/01_modelling/03_uv/publish/v002/char_Mermaid_uv_publish.usd")
    ld = parse_publish_path(f"{base}/05_lookdev/publish/V001/char_Mermaid_lookdev_publish.usd")
    shot = parse_publish_path("D:/Job/proj/02_shots/sh011/01_anim/publish/v003/geo_char_Mermaid.usd")
    assert (tex.word, tex.loader_reads) == ("texturing", False)
    assert (uv.word, uv.loader_reads) == ("model", True) and (ld.word, ld.loader_reads) == ("lookdev", True)
    assert (shot.word, shot.loader_reads) == ("anim", False)
