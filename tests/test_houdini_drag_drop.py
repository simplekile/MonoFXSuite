"""Tests for the Houdini drag & drop helpers that do not require hou."""

from __future__ import annotations

from pathlib import Path

from apps.houdini import drag_drop as dd


def test_classify_by_extension(tmp_path: Path) -> None:
    assert dd.classify("C:/a/rock.bgeo.sc") == dd.KIND_GEO
    assert dd.classify("C:/a/rock.OBJ") == dd.KIND_GEO
    assert dd.classify("C:/a/anim.abc") == dd.KIND_ABC
    assert dd.classify("C:/a/char.fbx") == dd.KIND_FBX
    assert dd.classify("C:/a/layout.usdc") == dd.KIND_USD
    assert dd.classify("C:/a/wood_BaseColor_sRGB.1001.exr") == dd.KIND_IMAGE
    assert dd.classify(str(tmp_path)) == dd.KIND_FOLDER
    assert dd.classify("C:/a/scene.hip") is None
    assert dd.classify("C:/a/notes.txt") is None


def test_is_houdini_file() -> None:
    assert dd.is_houdini_file("C:/a/shot.hipnc")
    assert dd.is_houdini_file("C:/a/tool.HDA")
    assert not dd.is_houdini_file("C:/a/render.0009.exr")
    assert not dd.is_houdini_file("C:/a/notes.txt")


def test_split_ext_keeps_multi_part() -> None:
    assert dd.split_ext("C:/a/rock.1001.bgeo.sc") == ("rock.1001", ".bgeo.sc")
    assert dd.split_ext("C:/a/rock.obj") == ("rock", ".obj")


def test_node_name_for() -> None:
    assert dd.node_name_for("C:/a/rock.bgeo.sc") == "rock"
    assert dd.node_name_for("C:/a/fx-smoke v2.0012.vdb") == "fx_smoke_v2"
    assert dd.node_name_for("C:/a/sim.$F4.bgeo.sc") == "sim"
    assert dd.node_name_for("C:/a/wood_BaseColor.%(UDIM)d.exr") == "wood_BaseColor"
    assert dd.node_name_for("C:/a/123.abc") == "_123"


def test_collapse_sequences() -> None:
    files = ["C:/c/sim.0001.bgeo.sc", "C:/c/sim.0002.bgeo.sc", "C:/c/rock.obj", "C:/c/one.0005.vdb"]
    out = dd.collapse_sequences(files)
    assert [Path(p).name for p in out] == ["sim.$F4.bgeo.sc", "rock.obj", "one.0005.vdb"]


def test_collapse_udims() -> None:
    files = ["C:/t/tile.1001.exr", "C:/t/tile.1002.exr", "C:/t/photo.jpg"]
    assert [Path(p).name for p in dd.collapse_udims(files)] == ["tile.<UDIM>.exr", "photo.jpg"]


def test_group_images_monos_names() -> None:
    files = [
        "C:/t/wood_BaseColor_sRGB.1001.exr",
        "C:/t/wood_BaseColor_sRGB.1002.exr",
        "C:/t/wood_Roughness_Raw.1001.exr",
        "C:/t/random_photo.jpg",
    ]
    groups, unmatched = dd.group_images(files)
    assert list(groups) == ["wood"]
    slots = groups["wood"].slots
    assert set(slots) == {"base_color", "roughness"}
    assert slots["base_color"].colorspace == "sRGB"
    assert "<UDIM>" in slots["base_color"].filepath
    assert unmatched == ["C:/t/random_photo.jpg"]


def test_base_color_groups_for_unreadable_names() -> None:
    files = [
        "C:/r/char_Ata_lookdev_v002.0009.exr",
        "C:/r/photo.jpg",
        "C:/r/tile.1001.exr",
        "C:/r/tile.1002.exr",
        "C:/r/wood.png",
    ]
    groups = dd.base_color_groups(files, taken={"wood": object()})
    assert list(groups) == ["char_Ata_lookdev_v002", "photo", "tile"]
    render = groups["char_Ata_lookdev_v002"].slots["base_color"]
    assert render.colorspace == "Linear" and not render.udim
    assert groups["photo"].slots["base_color"].colorspace == "sRGB"
    tile = groups["tile"].slots["base_color"]
    assert tile.udim and tile.filepath.endswith("tile.<UDIM>.exr")
