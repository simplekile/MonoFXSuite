"""Auto Material Version manager: Painter export versions, per-material versions, pins, scene record."""

from __future__ import annotations

from tools.fx.auto_material.logic import (
    STATUS_MISSING,
    STATUS_NEW,
    STATUS_OK,
    STATUS_PINNED,
    STATUS_UPDATE,
    MaterialGroup,
    MaterialRecord,
    PainterExport,
    asset_from_path,
    dump_record,
    list_painter_exports,
    material_status,
    parse_record,
    plan_changes,
    plan_materials,
    plan_summary,
    to_latest,
    version_from_path,
)


def _touch(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#usda 1.0\n", encoding="utf-8")


def _exports(**versions: list[str]) -> dict[str, dict[str, MaterialGroup]]:
    return {v: {n: MaterialGroup(prefix=n) for n in names} for v, names in versions.items()}


def test_version_from_texture_folder_and_file():
    assert version_from_path("D:/p/v001/char_Helen_texturing_v008_full_textures/M_Body_Color_ACEScg.%(UDIM)d.exr") == "v008"
    assert version_from_path("char_Helen_texturing_v009_full.usd") == "v009"
    assert version_from_path("D:/tex/body_color.png") is None


def test_asset_from_monos_layout():
    p = "D:/Job/proj/01_assets/_characters/char_Helen/03_surfacing/02_texturing/publish/v001/x.usd"
    assert asset_from_path(p) == ("_characters", "char_Helen")
    assert asset_from_path("D:\\Job\\proj\\01_Assets\\_props\\prop_Chair\\a.usd") == ("_props", "prop_Chair")
    assert asset_from_path("D:/elsewhere/x.usd") is None


def test_exports_of_one_family_across_publish_folders(tmp_path):
    for n in (6, 7, 8):
        _touch(tmp_path / "v001" / f"char_Helen_texturing_v{n:03d}_full.usd")
        _touch(tmp_path / "v001" / f"char_Helen_texturing_v{n:03d}_full.material.usda")
    _touch(tmp_path / "v002" / "char_Helen_texturing_v009_full.usd")
    _touch(tmp_path / "v002" / "char_Helen_texturing_v010_lite.usd")  # another family
    exports = list_painter_exports(str(tmp_path / "v001" / "char_Helen_texturing_v007_full.usd"))
    assert [e.version for e in exports] == ["v006", "v007", "v008", "v009"]
    assert exports[-1].usd_path.endswith("v002/char_Helen_texturing_v009_full.usd")


def test_plan_proposes_latest_and_keeps_pins():
    exports = _exports(
        v007=["Body", "Costume", "Accessory"],
        v008=["Body", "Costume", "Accessory", "Hair"],
        v009=["Body", "Costume", "Hair"],
    )
    scene = {
        "Body": MaterialRecord("v008"),
        "Costume": MaterialRecord("v008", pinned=True),
        "Accessory": MaterialRecord("v008"),
    }
    plans = {p.name: p for p in plan_materials(exports, scene)}
    assert [p.name for p in plan_materials(exports, scene)] == ["Body", "Costume", "Hair", "Accessory"]

    geo = set(exports["v009"])
    assert plans["Body"].chosen == "v009" and material_status(plans["Body"], geo) == STATUS_UPDATE
    assert plans["Costume"].chosen == "v008" and material_status(plans["Costume"], geo) == STATUS_PINNED
    assert plans["Hair"].chosen == "v009" and material_status(plans["Hair"], geo) == STATUS_NEW
    # Accessory is gone from v009: its latest is v008, and the geometry export does not have it.
    assert plans["Accessory"].chosen == "v008" and material_status(plans["Accessory"], geo) == STATUS_MISSING

    plans["Body"].chosen = "v008"
    assert material_status(plans["Body"], geo) == STATUS_OK and not plan_changes(plans["Body"])


def test_pin_change_alone_is_a_change_and_latest_skips_pins():
    exports = _exports(v008=["Body", "Head"], v009=["Body", "Head"])
    plans = {p.name: p for p in plan_materials(exports, {
        "Body": MaterialRecord("v008", pinned=True), "Head": MaterialRecord("v009"),
    })}
    assert not plan_changes(plans["Body"])  # pinned at v008, already built at v008
    plans["Body"].pinned = False             # unpin, version untouched
    assert plan_changes(plans["Body"])

    plans["Body"].pinned = True
    plans["Head"].chosen = "v008"
    to_latest(list(plans.values()))
    assert plans["Body"].chosen == "v008" and plans["Head"].chosen == "v009"


def test_summary_counts():
    exports = _exports(v008=["A", "B"], v009=["A", "B", "C", "D"])
    plans = {p.name: p for p in plan_materials(exports, {"A": MaterialRecord("v008"), "B": MaterialRecord("v009")})}
    plans["D"].enabled = False
    assert plan_summary(list(plans.values())) == {"new": 1, "update": 1, "unchanged": 1, "left_out": 1}


def test_record_round_trip_and_broken_text():
    text = dump_record(
        ("_characters", "char_Helen"),
        PainterExport("v009", "D:/p/char_Helen_texturing_v009_full.usd"),
        {"Body": MaterialRecord("v009"), "Costume": MaterialRecord("v008", pinned=True)},
    )
    meta, records = parse_record(text)
    assert meta == {"asset": "char_Helen", "group": "_characters",
                    "export": "D:/p/char_Helen_texturing_v009_full.usd", "version": "v009"}
    assert records["Costume"] == MaterialRecord("v008", True)
    assert parse_record("not json") == ({}, {})
    assert parse_record(None) == ({}, {})
