"""Auto Material: Substance Painter USD export -> material groups, geometry layers, bindings."""

from __future__ import annotations

from tools.fx.auto_material.logic import (
    SubstanceMaterial,
    _substance_texture_slot,
    find_painter_usd,
    is_usd_path,
    substance_assign_entries,
    substance_geo_layers,
    substance_node_base,
    substance_source,
)

TEX = "D:/job/publish/v001/char_Helen_texturing_v008_full_textures"
EXPORT = "D:/job/publish/v001/char_Helen_texturing_v008_full.usd"
MATERIAL_LAYER = "D:/job/publish/v001/char_Helen_texturing_v008_full.material.usda"
GEO_LAYER = "D:/job/uv/publish/v005/char_Helen_uv_publish_Hi.usd"


def _body() -> SubstanceMaterial:
    return SubstanceMaterial(
        name="M_char_Body",
        usd_path="/Geo/material/M_char_Body",
        textures={
            "baseColorTexture": f"{TEX}/M_char_Body_Color_ACEScg.1007.exr",
            "compositedNormalGLTexture": f"{TEX}/M_char_Body_Normal_Raw.1007.exr",
            "coatNormalTexture": f"{TEX}/M_char_Body_CoatNormal_Raw.1007.exr",
            "subsurfaceRadiusScaleTexture": f"{TEX}/M_char_Body_SSSRadiusScale_Raw.1007.exr",
            "someFutureTexture": f"{TEX}/M_char_Body_Future_Raw.1007.exr",
        },
        layers=[MATERIAL_LAYER],
    )


def _hair() -> SubstanceMaterial:
    return SubstanceMaterial(
        name="M_char_HairDriver",
        usd_path="/Geo/material/M_char_HairDriver",
        textures={"baseColorTexture": f"{TEX}/M_char_HairDriver_Color_ACEScg.<UDIM>.exr"},
        layers=[MATERIAL_LAYER],
    )


def _geo_own_material() -> SubstanceMaterial:
    # The UV publish brings materials of its own, with no Painter texture input.
    return SubstanceMaterial("M_char_Body", "/_materials/M_char_Body", {}, [GEO_LAYER])


def test_texture_udim_tag_from_painter_becomes_tool_token():
    slot = _substance_texture_slot(f"{TEX}/M_char_HairDriver_Color_ACEScg.<UDIM>.exr")
    assert slot.filepath == f"{TEX}/M_char_HairDriver_Color_ACEScg.%(UDIM)d.exr"
    assert slot.udim
    assert slot.colorspace == "ACEScg"


def test_texture_single_tile_becomes_udim_token():
    slot = _substance_texture_slot(f"{TEX}/M_char_Body_Normal_Raw.1007.exr")
    assert slot.filepath == f"{TEX}/M_char_Body_Normal_Raw.%(UDIM)d.exr"
    assert slot.udim
    assert slot.colorspace == "Raw"


def test_texture_without_udim_or_colorspace_word():
    slot = _substance_texture_slot("D:/tex/v1.2/body_color.png")
    assert slot.filepath == "D:/tex/v1.2/body_color.png"
    assert not slot.udim
    assert slot.colorspace is None


def test_node_base_drops_version():
    assert substance_node_base(EXPORT) == "char_Helen_texturing_full"
    assert substance_node_base("D:/x/prop-chair v3.usda") == "prop_chair_v3"


def test_source_maps_inputs_to_slots_and_skips_unknown_and_geo_materials():
    groups, source = substance_source(
        EXPORT,
        [MATERIAL_LAYER, GEO_LAYER],
        [_hair(), _body(), _geo_own_material()],
        {},
    )
    assert list(groups) == ["M_char_Body", "M_char_HairDriver"]
    body = groups["M_char_Body"]
    assert set(body.slots) == {"base_color", "normal", "coat_normal", "subsurface_radius"}
    assert body.parse_mode == "substance"
    assert source.geo_layers == [GEO_LAYER]


def test_geo_layers_fall_back_to_export_when_every_sublayer_has_painter_materials():
    assert substance_geo_layers(EXPORT, [MATERIAL_LAYER], [_body()]) == [EXPORT]


def test_geo_layer_match_ignores_case_and_slashes():
    painter = SubstanceMaterial(
        "m", "/m", {"baseColorTexture": f"{TEX}/m_Color_sRGB.png"}, [MATERIAL_LAYER.upper().replace("/", "\\")],
    )
    layers = substance_geo_layers(EXPORT, [MATERIAL_LAYER, GEO_LAYER], [painter])
    assert layers == [GEO_LAYER]


def test_bindings_go_to_built_materials_only():
    bindings = {
        "/Geo/material/M_char_Body": ["/Geo/Base_grp/Body_grp/Geo_Body"],
        "/Geo/material/M_char_HairDriver": [
            "/Geo/Groom_grp/HairDriver_grp/Geo_HairBase",
            "/Geo/Groom_grp/HairDriver_grp/Geo_HairBang",
        ],
        "/_materials/M_char_Body": ["/Geo/Base_grp/Body_grp/Geo_Body"],  # geometry file's own binding
    }
    _, source = substance_source(EXPORT, [MATERIAL_LAYER, GEO_LAYER], [_body(), _hair(), _geo_own_material()], bindings)
    assert source.assignments == {
        "M_char_Body": ["/Geo/Base_grp/Body_grp/Geo_Body"],
        "M_char_HairDriver": [
            "/Geo/Groom_grp/HairDriver_grp/Geo_HairBang",
            "/Geo/Groom_grp/HairDriver_grp/Geo_HairBase",
        ],
    }

    # Only M_char_Body was built (the user removed the hair from the list).
    entries = substance_assign_entries(source, {"M_char_Body": "/materials/M_char_Body"})
    assert entries == [("/Geo/Base_grp/Body_grp/Geo_Body", "/materials/M_char_Body")]


def _touch(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#usda 1.0\n", encoding="utf-8")


def test_publish_finds_latest_painter_export_in_latest_version(tmp_path):
    # Painter re-exports into the same publish version: v006, v007, v008 next to each other.
    v001 = tmp_path / "v001"
    for n in (6, 7, 8):
        _touch(v001 / f"char_Helen_texturing_v{n:03d}_full.usd")
        _touch(v001 / f"char_Helen_texturing_v{n:03d}_full.material.usda")
    _touch(tmp_path / "v000" / "char_Helen_texturing_v999_full.usd")  # older publish version
    found = find_painter_usd(str(tmp_path))
    assert found == str(v001 / "char_Helen_texturing_v008_full.usd")
    assert is_usd_path(found)


def test_publish_without_usd_keeps_texture_folder(tmp_path):
    (tmp_path / "v002" / "textures").mkdir(parents=True)
    (tmp_path / "v002" / "textures" / "body_BaseColor_sRGB.1001.exr").write_bytes(b"")
    assert find_painter_usd(str(tmp_path)) is None
    assert not is_usd_path(str(tmp_path))
