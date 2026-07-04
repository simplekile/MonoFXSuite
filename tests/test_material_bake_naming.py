"""Material bake naming and output path helpers (no Blender runtime)."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PKG_DIR = _ROOT / "tools/fx/monofx_pipeline_blender/monofx_pipeline_blender"

if "bpy" not in sys.modules:
    sys.modules["bpy"] = types.ModuleType("bpy")

_pkg = types.ModuleType("monofx_pipeline_blender")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules["monofx_pipeline_blender"] = _pkg

_config_spec = importlib.util.spec_from_file_location(
    "monofx_pipeline_blender.config",
    _PKG_DIR / "config.py",
)
assert _config_spec and _config_spec.loader
_config = importlib.util.module_from_spec(_config_spec)
sys.modules["monofx_pipeline_blender.config"] = _config
_config_spec.loader.exec_module(_config)

_mb_spec = importlib.util.spec_from_file_location(
    "monofx_pipeline_blender.material_bake",
    _PKG_DIR / "material_bake.py",
)
assert _mb_spec and _mb_spec.loader
_mb = importlib.util.module_from_spec(_mb_spec)
sys.modules["monofx_pipeline_blender.material_bake"] = _mb
_mb_spec.loader.exec_module(_mb)


def test_material_stem_strips_prefix():
    assert _mb.material_stem_from_name("M_char_Body") == "Body"
    assert _mb.material_stem_from_name("Body") == "Body"


def test_texture_filename_png():
    assert _mb.texture_filename("Body", "BaseColor", image_format="PNG") == "Body_BaseColor.png"
    assert _mb.texture_filename("Body", "Roughness", image_format="OPEN_EXR") == "Body_Roughness.exr"


def test_sanitize_mesh_suffix():
    assert _mb.sanitize_mesh_suffix("geo_body") == "geo_body"
    assert _mb.sanitize_mesh_suffix("namespace::geo_body") == "geo_body"


def test_resolve_texture_stem_material_mesh():
    assert (
        _mb.resolve_texture_stem("M_char_Body", "geo_head", mode="MATERIAL_MESH")
        == "Body_geo_head"
    )


def test_resolve_texture_stem_custom():
    assert (
        _mb.resolve_texture_stem(
            "M_char_Body",
            "geo_head",
            mode="CUSTOM",
            custom_template="{mesh}_{material_stem}",
        )
        == "geo_head_Body"
    )


def test_resolve_shader_name_source_texture():
    assert (
        _mb.resolve_shader_name(
            "M_char_Body",
            "geo_head",
            "Body_geo_head",
            mode="SOURCE_TEXTURE",
        )
        == "M_char_Body_Body_geo_head"
    )


def test_resolve_shader_name_texture_stem():
    assert (
        _mb.resolve_shader_name(
            "M_char_Body",
            "geo_head",
            "Body_geo_head",
            mode="TEXTURE_STEM",
        )
        == "Body_geo_head"
    )


def test_resolve_shader_name_material_mesh():
    assert (
        _mb.resolve_shader_name(
            "M_char_Body",
            "geo_head",
            "Body_geo_head",
            mode="MATERIAL_MESH",
        )
        == "Body_geo_head"
    )


def test_resolve_shader_name_mesh_material():
    assert (
        _mb.resolve_shader_name(
            "M_char_Body",
            "geo_head",
            "Body_geo_head",
            mode="MESH_MATERIAL",
        )
        == "geo_head_Body"
    )


def test_resolve_bake_output_dir_blend_textures():
    blend = Path(r"D:/project/01_modelling/02_retopo/blender/work/asset.blend")
    out = _mb.resolve_bake_output_dir(
        output_mode="BLEND_TEXTURES",
        blend_path=blend,
        publish_root=None,
        custom_dir="",
    )
    assert out == blend.parent / "textures"


def test_resolve_bake_output_dir_publish_textures():
    publish = Path(r"D:/project/01_modelling/02_retopo/publish")
    out = _mb.resolve_bake_output_dir(
        output_mode="PUBLISH_TEXTURES",
        blend_path=None,
        publish_root=publish,
        custom_dir="",
    )
    assert out == publish / "textures"


def test_promote_image_alpha_to_rgb():
    class _Img:
        size = (2, 1)
        pixels = [1.0, 0.0, 0.0, 0.25, 0.0, 1.0, 0.0, 0.75]

        def update(self) -> None:
            return None

    img = _Img()
    _mb.promote_image_alpha_to_rgb(img)
    assert img.pixels[:4] == [0.25, 0.25, 0.25, 0.25]
    assert img.pixels[4:8] == [0.75, 0.75, 0.75, 0.75]


def test_image_alpha_has_variation():
    class _Img:
        size = (2, 1)
        pixels = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

        def update(self) -> None:
            return None

    assert not _mb.image_alpha_has_variation(_Img())
    varied = _Img()
    varied.pixels = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.2]
    assert _mb.image_alpha_has_variation(varied)


def test_copy_image_alpha_to_opacity_map():
    class _Img:
        def __init__(self, pixels, size):
            self.pixels = pixels
            self.size = size

        def update(self) -> None:
            return None

    src = _Img([1.0, 0.0, 0.0, 0.2, 0.0, 1.0, 0.0, 0.8], (2, 1))
    dest = _Img([0.0] * 8, (2, 1))
    assert _mb.copy_image_alpha_to_opacity_map(src, dest)
    assert list(dest.pixels[:4]) == pytest.approx([0.2, 0.2, 0.2, 1.0])
    assert list(dest.pixels[4:8]) == pytest.approx([0.8, 0.8, 0.8, 1.0])


def test_strip_image_alpha_opaque():
    class _Img:
        size = (1, 1)
        pixels = [0.5, 0.5, 0.5, 0.25]

        def update(self) -> None:
            return None

    img = _Img()
    _mb.strip_image_alpha_opaque(img)
    assert img.pixels == [0.5, 0.5, 0.5, 1.0]


def test_merge_grayscale_bake_into_alpha_channel():
    class _Img:
        def __init__(self, pixels, size):
            self.pixels = pixels
            self.size = size

        def update(self) -> None:
            return None

    dest = _Img([0.1, 0.2, 0.3, 0.0, 0.4, 0.5, 0.6, 0.0], (2, 1))
    gray = _Img([0.25, 0.25, 0.25, 1.0, 0.75, 0.75, 0.75, 1.0], (2, 1))
    assert _mb.merge_grayscale_bake_into_alpha_channel(dest, gray)
    assert list(dest.pixels[:4]) == pytest.approx([0.1, 0.2, 0.3, 0.25])
    assert list(dest.pixels[4:8]) == pytest.approx([0.4, 0.5, 0.6, 0.75])


def test_expected_texture_filenames_with_opacity():
    names = _mb.expected_texture_filenames(
        "Body",
        pass_base_color=True,
        pass_roughness=True,
        pass_normal=False,
        pass_ao=False,
        pass_opacity=True,
        image_format="PNG",
    )
    assert names == ["Body_BaseColor.png", "Body_Roughness.png", "Body_Opacity.png"]


def test_count_baked_textures_on_disk(tmp_path):
    stem_dir = tmp_path
    (stem_dir / "Body_BaseColor.png").write_bytes(b"x")
    found, total = _mb.count_baked_textures_on_disk(
        stem_dir,
        "Body",
        pass_base_color=True,
        pass_roughness=True,
        pass_normal=False,
        pass_ao=False,
        pass_opacity=False,
        image_format="PNG",
    )
    assert found == 1
    assert total == 2


def test_resolve_bake_output_dir_custom():
    custom = Path(r"D:/textures_out")
    out = _mb.resolve_bake_output_dir(
        output_mode="CUSTOM",
        blend_path=None,
        publish_root=None,
        custom_dir=str(custom),
    )
    assert out == custom
