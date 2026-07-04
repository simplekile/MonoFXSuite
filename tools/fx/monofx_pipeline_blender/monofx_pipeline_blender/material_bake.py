"""
Bake mesh materials to PBR image textures for USD-friendly Principled shaders.
"""

from __future__ import annotations

import array
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

import bpy

from . import config

_BAKE_PREP_NODE_LABEL = "MonoFX Bake Target"
_BAKE_PREP_UV_LABEL = "MonoFX Bake UV"
_DUMMY_BAKE_IMAGE_NAME = "mono_fx_bake_dummy_sink"
_MESH_SUFFIX_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\s]+')


@dataclass(frozen=True)
class BakePassSpec:
    key: str
    slot_name: str
    bake_type: str
    pass_filter: frozenset[str] = frozenset()
    non_color: bool = False


BAKE_PASS_SPECS: dict[str, BakePassSpec] = {
    "base_color": BakePassSpec(
        key="base_color",
        slot_name=config.BAKE_SLOT_BASE_COLOR,
        bake_type="DIFFUSE",
        pass_filter=frozenset({"COLOR"}),
    ),
    "roughness": BakePassSpec(
        key="roughness",
        slot_name=config.BAKE_SLOT_ROUGHNESS,
        bake_type="ROUGHNESS",
        non_color=True,
    ),
    "normal": BakePassSpec(
        key="normal",
        slot_name=config.BAKE_SLOT_NORMAL,
        bake_type="NORMAL",
        non_color=True,
    ),
    "ao": BakePassSpec(
        key="ao",
        slot_name=config.BAKE_SLOT_AO,
        bake_type="AO",
        non_color=True,
    ),
    "opacity": BakePassSpec(
        key="opacity",
        slot_name=config.BAKE_SLOT_OPACITY,
        bake_type="DIFFUSE",
        pass_filter=frozenset({"COLOR"}),
        non_color=True,
    ),
}


@dataclass
class BakeTarget:
    material: bpy.types.Material
    meshes: list[bpy.types.Object]
    file_stem: str


@dataclass
class MaterialBakeResult:
    ok: bool = False
    baked_targets: int = 0
    baked_passes: int = 0
    output_dir: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def summary(self) -> str:
        if self.error:
            return self.error
        if not self.ok:
            return "Material bake failed."
        return (
            f"Baked {self.baked_passes} pass(es) on {self.baked_targets} target(s) "
            f"→ {self.output_dir}"
        )


def material_stem_from_name(
    mat_name: str,
    *,
    material_prefix: str | None = None,
) -> str:
    name = (mat_name or "").strip()
    if material_prefix is None:
        prefix = config.DEFAULT_MATERIAL_PREFIX
    else:
        prefix = material_prefix
    if prefix and name.casefold().startswith(prefix.casefold()):
        return name[len(prefix) :].strip("_") or name
    return name


def sanitize_mesh_suffix(mesh_name: str) -> str:
    leaf = (mesh_name or "").strip().split(":")[-1]
    cleaned = _MESH_SUFFIX_INVALID.sub("_", leaf)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "mesh"


def sanitize_name_token(name: str, *, fallback: str = "material") -> str:
    cleaned = _MESH_SUFFIX_INVALID.sub("_", (name or "").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or fallback


def _apply_name_template(template: str, **tokens: str) -> str:
    out = template or ""
    for key, value in tokens.items():
        out = out.replace("{" + key + "}", value or "")
    return sanitize_name_token(out, fallback="material")


def resolve_texture_stem(
    material_name: str,
    mesh_name: str,
    *,
    mode: str = config.DEFAULT_MATERIAL_BAKE_TEXTURE_STEM_MODE,
    material_prefix: str = config.DEFAULT_MATERIAL_PREFIX,
    custom_template: str = config.DEFAULT_MATERIAL_BAKE_TEXTURE_STEM_TEMPLATE,
) -> str:
    """Build the texture file stem used before pass suffix (e.g. Body_geo_head)."""
    mat_stem = material_stem_from_name(material_name, material_prefix=material_prefix)
    mesh_suffix = sanitize_mesh_suffix(mesh_name)
    material_full = sanitize_name_token(material_name, fallback="material")
    key = (mode or config.DEFAULT_MATERIAL_BAKE_TEXTURE_STEM_MODE).upper()
    if key == "MATERIAL_STEM":
        return mat_stem or material_full
    if key == "MATERIAL_FULL":
        return material_full
    if key == "MESH":
        return mesh_suffix
    if key == "CUSTOM":
        return _apply_name_template(
            custom_template,
            material=material_name,
            material_stem=mat_stem,
            mesh=mesh_suffix,
            texture_stem=mat_stem or material_full,
        )
    if mat_stem:
        return f"{mat_stem}_{mesh_suffix}"
    return mesh_suffix


def resolve_shader_name(
    material_name: str,
    mesh_name: str,
    texture_stem: str,
    *,
    mode: str = config.DEFAULT_MATERIAL_BAKE_SHADER_NAME_MODE,
    material_prefix: str = config.DEFAULT_MATERIAL_PREFIX,
    custom_template: str = config.DEFAULT_MATERIAL_BAKE_SHADER_NAME_TEMPLATE,
) -> str:
    """Build the baked work-material name assigned on the mesh slot."""
    mat_stem = material_stem_from_name(material_name, material_prefix=material_prefix)
    mesh_suffix = sanitize_mesh_suffix(mesh_name)
    material_full = sanitize_name_token(material_name, fallback="material")
    stem = sanitize_name_token(texture_stem, fallback=mat_stem or material_full)
    key = (mode or config.DEFAULT_MATERIAL_BAKE_SHADER_NAME_MODE).upper()
    if key == "KEEP_SOURCE":
        return material_name
    if key == "MATERIAL_STEM":
        return mat_stem or material_full
    if key == "MATERIAL_MESH":
        if mat_stem:
            return f"{mat_stem}_{mesh_suffix}"
        return mesh_suffix
    if key == "MESH_MATERIAL":
        if mat_stem:
            return f"{mesh_suffix}_{mat_stem}"
        return mesh_suffix
    if key == "TEXTURE_STEM":
        return stem
    if key == "CUSTOM":
        return _apply_name_template(
            custom_template,
            material=material_name,
            material_stem=mat_stem,
            mesh=mesh_suffix,
            texture_stem=stem,
        )
    return f"{material_name}_{stem}"


def image_extension(image_format: str) -> str:
    key = (image_format or config.DEFAULT_MATERIAL_BAKE_IMAGE_FORMAT).upper()
    if key == "OPEN_EXR":
        return "exr"
    return "png"


def blender_image_format(image_format: str) -> str:
    key = (image_format or config.DEFAULT_MATERIAL_BAKE_IMAGE_FORMAT).upper()
    if key == "OPEN_EXR":
        return "OPEN_EXR"
    return "PNG"


def texture_filename(
    stem: str,
    slot: str,
    *,
    image_format: str = config.DEFAULT_MATERIAL_BAKE_IMAGE_FORMAT,
) -> str:
    ext = image_extension(image_format)
    safe_stem = (stem or "material").strip("_") or "material"
    safe_slot = (slot or "Pass").strip()
    return f"{safe_stem}_{safe_slot}.{ext}"


def resolve_bake_output_dir(
    *,
    output_mode: str,
    blend_path: Optional[Path],
    publish_root: Optional[Path],
    custom_dir: str,
) -> Optional[Path]:
    mode = (output_mode or config.DEFAULT_MATERIAL_BAKE_OUTPUT_MODE).upper()
    if mode == "CUSTOM":
        path = Path((custom_dir or "").strip())
        return path if str(path).strip() else None
    if mode == "PUBLISH_TEXTURES":
        if publish_root is None:
            return None
        return publish_root / "textures"
    if blend_path is None:
        return None
    return blend_path.parent / "textures"


_BAKE_OUTPUT_MODE_LABELS = {
    "BLEND_TEXTURES": "Blend Textures",
    "PUBLISH_TEXTURES": "Publish Textures",
    "CUSTOM": "Custom",
}


def describe_bake_output_target(
    *,
    output_mode: str,
    blend_path: Optional[Path],
    publish_root: Optional[Path],
    custom_dir: str,
) -> tuple[bool, str, str]:
    """Return ok, resolved path summary, and error message."""
    path = resolve_bake_output_dir(
        output_mode=output_mode,
        blend_path=blend_path,
        publish_root=publish_root,
        custom_dir=custom_dir,
    )
    if path is not None:
        mode_key = (output_mode or config.DEFAULT_MATERIAL_BAKE_OUTPUT_MODE).upper()
        mode_label = _BAKE_OUTPUT_MODE_LABELS.get(mode_key, "Output")
        return True, f"{mode_label}: {path}", ""
    mode_key = (output_mode or "").upper()
    if mode_key == "PUBLISH_TEXTURES":
        return (
            False,
            "",
            "Publish textures unavailable. Save under 01_modelling/<task>/ "
            "or choose Blend Textures / Custom.",
        )
    if mode_key == "CUSTOM":
        return False, "", "Set a custom output folder."
    return False, "", "Save the .blend file first or choose another output folder."


def _alpha_variation_tolerance() -> float:
    return 0.002


def _image_pixel_count(image: bpy.types.Image) -> int:
    width, height = image.size
    return max(0, width * height)


def _read_image_pixels(image: bpy.types.Image, *, count: Optional[int] = None) -> array.array:
    count = _image_pixel_count(image) if count is None else count
    length = count * 4
    buf = array.array("f", [0.0]) * length
    pixels = image.pixels
    if length <= 0:
        return buf
    if hasattr(pixels, "foreach_get"):
        pixels.foreach_get(buf)
        return buf
    for index, value in enumerate(pixels[:length]):
        buf[index] = value
    return buf


def _write_image_pixels(image: bpy.types.Image, buf: array.array) -> None:
    pixels = image.pixels
    if hasattr(pixels, "foreach_set"):
        pixels.foreach_set(buf)
        return
    image.pixels = list(buf)


def image_alpha_has_variation(image: bpy.types.Image, *, tolerance: Optional[float] = None) -> bool:
    tol = _alpha_variation_tolerance() if tolerance is None else tolerance
    if image is None:
        return False
    try:
        image.update()
    except Exception:
        pass
    count = _image_pixel_count(image)
    if count <= 0:
        return False
    pixels = image.pixels
    if len(pixels) < count * 4:
        return False
    min_alpha = 1.0
    max_alpha = 0.0
    for index in range(count):
        alpha = pixels[index * 4 + 3]
        if alpha < min_alpha:
            min_alpha = alpha
        if alpha > max_alpha:
            max_alpha = alpha
        if (max_alpha - min_alpha) > tol:
            return True
    return False


def image_grayscale_has_variation(image: bpy.types.Image, *, tolerance: Optional[float] = None) -> bool:
    tol = _alpha_variation_tolerance() if tolerance is None else tolerance
    if image is None:
        return False
    try:
        image.update()
    except Exception:
        pass
    count = _image_pixel_count(image)
    if count <= 0:
        return False
    pixels = image.pixels
    if len(pixels) < count * 4:
        return False
    min_value = 1.0
    max_value = 0.0
    for index in range(count):
        offset = index * 4
        value = (pixels[offset] + pixels[offset + 1] + pixels[offset + 2]) / 3.0
        if value < min_value:
            min_value = value
        if value > max_value:
            max_value = value
        if (max_value - min_value) > tol:
            return True
    return False


def promote_image_alpha_to_rgb(image: bpy.types.Image) -> None:
    """Copy the alpha channel into RGB so opacity maps are visible as grayscale."""
    try:
        image.update()
    except Exception:
        pass
    count = _image_pixel_count(image)
    if count <= 0:
        return
    pixels = _read_image_pixels(image, count=count)
    if len(pixels) < count * 4:
        return
    for index in range(count):
        alpha = pixels[index * 4 + 3]
        offset = index * 4
        pixels[offset] = alpha
        pixels[offset + 1] = alpha
        pixels[offset + 2] = alpha
        pixels[offset + 3] = alpha
    _write_image_pixels(image, pixels)
    try:
        image.update()
    except Exception:
        pass


def strip_image_alpha_opaque(image: bpy.types.Image) -> None:
    """Force the image alpha channel to 1.0 (opaque RGB texture)."""
    try:
        image.update()
    except Exception:
        pass
    count = _image_pixel_count(image)
    if count <= 0:
        return
    pixels = _read_image_pixels(image, count=count)
    if len(pixels) < count * 4:
        return
    for index in range(count):
        pixels[index * 4 + 3] = 1.0
    _write_image_pixels(image, pixels)
    try:
        image.update()
    except Exception:
        pass


def copy_image_alpha_to_opacity_map(
    source: bpy.types.Image,
    dest: bpy.types.Image,
) -> bool:
    """Copy source alpha into a dedicated grayscale opacity map image (single pass)."""
    try:
        source.update()
        dest.update()
    except Exception:
        pass
    if source.size != dest.size:
        return False
    count = _image_pixel_count(source)
    if count <= 0:
        return False
    src = _read_image_pixels(source, count=count)
    if len(src) < count * 4:
        return False
    tol = _alpha_variation_tolerance()
    out = array.array("f", [0.0]) * (count * 4)
    min_alpha = 1.0
    max_alpha = 0.0
    for index in range(count):
        alpha = src[index * 4 + 3]
        if alpha < min_alpha:
            min_alpha = alpha
        if alpha > max_alpha:
            max_alpha = alpha
        offset = index * 4
        out[offset] = alpha
        out[offset + 1] = alpha
        out[offset + 2] = alpha
        out[offset + 3] = 1.0
    if (max_alpha - min_alpha) <= tol:
        return False
    _write_image_pixels(dest, out)
    try:
        dest.update()
    except Exception:
        pass
    return True


def merge_grayscale_bake_into_alpha_channel(
    dest: bpy.types.Image,
    gray_bake: bpy.types.Image,
) -> bool:
    """Write an EMIT grayscale bake into dest alpha; keep dest RGB."""
    try:
        dest.update()
        gray_bake.update()
    except Exception:
        pass
    if dest.size != gray_bake.size:
        return False
    count = _image_pixel_count(dest)
    if count <= 0:
        return False
    dest_pixels = _read_image_pixels(dest, count=count)
    gray_pixels = _read_image_pixels(gray_bake, count=count)
    if len(dest_pixels) < count * 4 or len(gray_pixels) < count * 4:
        return False
    for index in range(count):
        dest_pixels[index * 4 + 3] = gray_pixels[index * 4]
    _write_image_pixels(dest, dest_pixels)
    try:
        dest.update()
    except Exception:
        pass
    return image_alpha_has_variation(dest)


def copy_source_alpha_into_image(
    source: bpy.types.Image,
    dest: bpy.types.Image,
) -> bool:
    """Copy source alpha into dest alpha channel; keep baked RGB in dest."""
    try:
        source.update()
        dest.update()
    except Exception:
        pass
    if not image_alpha_has_variation(source):
        return False
    sw, sh = source.size
    dw, dh = dest.size
    if sw <= 0 or sh <= 0 or dw <= 0 or dh <= 0:
        return False
    src = _read_image_pixels(source)
    dest_pixels = _read_image_pixels(dest, count=dw * dh)
    if len(dest_pixels) < dw * dh * 4:
        return False
    out = array.array("f", [0.0]) * (dw * dh * 4)
    for dy in range(dh):
        sy = min(int((dy + 0.5) * sh / dh), sh - 1)
        for dx in range(dw):
            sx = min(int((dx + 0.5) * sw / dw), sw - 1)
            alpha = src[(sy * sw + sx) * 4 + 3]
            offset = (dy * dw + dx) * 4
            out[offset] = dest_pixels[offset]
            out[offset + 1] = dest_pixels[offset + 1]
            out[offset + 2] = dest_pixels[offset + 2]
            out[offset + 3] = alpha
    _write_image_pixels(dest, out)
    try:
        dest.update()
    except Exception:
        pass
    return True


def _cleanup_bake_prep_nodes(mat: bpy.types.Material) -> None:
    """Remove temporary image/UV nodes added for a bake pass."""
    if not mat.use_nodes or mat.node_tree is None:
        return
    tree = mat.node_tree
    for node in list(tree.nodes):
        if node.label in (_BAKE_PREP_NODE_LABEL, _BAKE_PREP_UV_LABEL):
            try:
                tree.nodes.remove(node)
            except Exception:
                pass


def _cleanup_bake_prep_on_mesh(mesh: bpy.types.Object) -> None:
    for slot in mesh.material_slots:
        if slot.material is not None:
            _cleanup_bake_prep_nodes(slot.material)


def _dummy_bake_sink_image() -> bpy.types.Image:
    """Throwaway bake target for non-active materials (multi-material mesh quirk)."""
    existing = bpy.data.images.get(_DUMMY_BAKE_IMAGE_NAME)
    if existing is not None:
        return existing
    return bpy.data.images.new(_DUMMY_BAKE_IMAGE_NAME, 4, 4, alpha=True)


def _set_image_colorspace(image: bpy.types.Image, colorspace: str) -> None:
    if image is None:
        return
    settings = image.colorspace_settings
    if colorspace == "Non-Color":
        candidates = ("Non-Color", "Utility - Raw - Texture", "Linear")
    else:
        candidates = (colorspace, "sRGB", "Utility - sRGB - Texture")
    for name in candidates:
        try:
            settings.name = name
            return
        except Exception:
            continue


def _mesh_material_slot(mesh: bpy.types.Object, material: bpy.types.Material) -> Optional[int]:
    for index, slot in enumerate(mesh.material_slots):
        if slot.material == material:
            return index
    return None


def _mesh_has_uv(mesh: bpy.types.Object, uv_map_name: str) -> bool:
    data = getattr(mesh, "data", None)
    if data is None or not hasattr(data, "uv_layers"):
        return False
    layers = data.uv_layers
    if not layers:
        return False
    if not uv_map_name:
        return True
    return uv_map_name in layers


def _active_uv_name(mesh: bpy.types.Object, uv_map_name: str) -> str:
    if uv_map_name:
        return uv_map_name
    data = getattr(mesh, "data", None)
    if data is None or not getattr(data, "uv_layers", None):
        return ""
    active = data.uv_layers.active
    return active.name if active else ""


def _primary_material(mesh: bpy.types.Object) -> Optional[bpy.types.Material]:
    for slot in mesh.material_slots:
        if slot.material is not None:
            return slot.material
    return mesh.active_material


def collect_bake_targets(
    meshes: Iterable[bpy.types.Object],
    *,
    scope: str,
    material_prefix: str = config.DEFAULT_MATERIAL_PREFIX,
) -> list[BakeTarget]:
    mesh_list = [m for m in meshes if m is not None and m.type == "MESH"]
    if not mesh_list:
        return []

    scope_key = (scope or config.DEFAULT_MATERIAL_BAKE_SCOPE).upper()
    if scope_key == "PER_MESH":
        targets: list[BakeTarget] = []
        for mesh in mesh_list:
            mat = _primary_material(mesh)
            if mat is None:
                continue
            mat_stem = material_stem_from_name(mat.name, material_prefix=material_prefix)
            mesh_suffix = sanitize_mesh_suffix(mesh.name)
            file_stem = f"{mat_stem}_{mesh_suffix}" if mat_stem else mesh_suffix
            targets.append(BakeTarget(material=mat, meshes=[mesh], file_stem=file_stem))
        return targets

    by_material: dict[str, BakeTarget] = {}
    for mesh in mesh_list:
        for slot in mesh.material_slots:
            mat = slot.material
            if mat is None:
                continue
            if mat.name not in by_material:
                file_stem = material_stem_from_name(mat.name, material_prefix=material_prefix)
                by_material[mat.name] = BakeTarget(
                    material=mat,
                    meshes=[],
                    file_stem=file_stem or mat.name,
                )
            if mesh not in by_material[mat.name].meshes:
                by_material[mat.name].meshes.append(mesh)

    return [t for t in by_material.values() if t.meshes]


def _enabled_pass_specs(
    *,
    pass_base_color: bool,
    pass_roughness: bool,
    pass_normal: bool,
    pass_ao: bool,
    pass_opacity: bool,
) -> list[BakePassSpec]:
    flags = {
        "base_color": pass_base_color,
        "roughness": pass_roughness,
        "normal": pass_normal,
        "ao": pass_ao,
    }
    return [BAKE_PASS_SPECS[key] for key, enabled in flags.items() if enabled]


def expected_texture_filenames(
    file_stem: str,
    *,
    pass_base_color: bool = True,
    pass_roughness: bool = True,
    pass_normal: bool = True,
    pass_ao: bool = False,
    pass_opacity: bool = False,
    image_format: str = config.DEFAULT_MATERIAL_BAKE_IMAGE_FORMAT,
) -> list[str]:
    """Return texture basenames expected on disk for one bake target."""
    names: list[str] = []
    for spec in _enabled_pass_specs(
        pass_base_color=pass_base_color,
        pass_roughness=pass_roughness,
        pass_normal=pass_normal,
        pass_ao=pass_ao,
        pass_opacity=False,
    ):
        names.append(
            texture_filename(file_stem, spec.slot_name, image_format=image_format)
        )
    if pass_opacity and pass_base_color:
        names.append(
            texture_filename(
                file_stem,
                BAKE_PASS_SPECS["opacity"].slot_name,
                image_format=image_format,
            )
        )
    return names


def count_baked_textures_on_disk(
    output_dir: Path,
    file_stem: str,
    *,
    pass_base_color: bool = True,
    pass_roughness: bool = True,
    pass_normal: bool = True,
    pass_ao: bool = False,
    pass_opacity: bool = False,
    image_format: str = config.DEFAULT_MATERIAL_BAKE_IMAGE_FORMAT,
) -> tuple[int, int]:
    """Return (existing_count, expected_count) for baked texture files."""
    names = expected_texture_filenames(
        file_stem,
        pass_base_color=pass_base_color,
        pass_roughness=pass_roughness,
        pass_normal=pass_normal,
        pass_ao=pass_ao,
        pass_opacity=pass_opacity,
        image_format=image_format,
    )
    if not names:
        return 0, 0
    found = sum(1 for name in names if (output_dir / name).is_file())
    return found, len(names)


def _ensure_image(
    *,
    image_name: str,
    filepath: Path,
    resolution: int,
    image_format: str,
    with_alpha: bool = False,
) -> bpy.types.Image:
    existing = bpy.data.images.get(image_name)
    if existing is not None:
        try:
            bpy.data.images.remove(existing)
        except Exception:
            pass

    img = bpy.data.images.new(
        image_name,
        width=resolution,
        height=resolution,
        alpha=bool(with_alpha),
        float_buffer=image_format.upper() == "OPEN_EXR",
    )
    abs_path = str(filepath.resolve())
    img.filepath_raw = abs_path
    img.file_format = blender_image_format(image_format)
    return img


def _prepare_bake_nodes(
    mat: bpy.types.Material,
    *,
    image: bpy.types.Image,
    uv_map_name: str,
) -> tuple[bpy.types.ShaderNodeTexImage, Optional[bpy.types.ShaderNodeUVMap]]:
    mat.use_nodes = True
    tree = mat.node_tree
    assert tree is not None

    for node in tree.nodes:
        node.select = False
        if node.type == "TEX_IMAGE":
            node.select = False

    uv_node: Optional[bpy.types.ShaderNodeUVMap] = None
    if uv_map_name:
        uv_node = tree.nodes.new("ShaderNodeUVMap")
        uv_node.label = _BAKE_PREP_UV_LABEL
        uv_node.uv_map = uv_map_name
        uv_node.location = (-500, 0)

    img_node = tree.nodes.new("ShaderNodeTexImage")
    img_node.label = _BAKE_PREP_NODE_LABEL
    img_node.image = image
    img_node.select = True
    tree.nodes.active = img_node
    img_node.location = (-250, 0)
    if uv_node is not None:
        tree.links.new(uv_node.outputs["UV"], img_node.inputs["Vector"])
    return img_node, uv_node


def _activate_bake_targets_on_mesh(
    mesh: bpy.types.Object,
    work_mat: bpy.types.Material,
    *,
    target_image: bpy.types.Image,
    uv_map_name: str,
) -> None:
    """
    Blender bakes to the active Image Texture in every material on the mesh.
    Non-target materials get a dummy sink so source textures are not overwritten.
    """
    dummy = _dummy_bake_sink_image()
    for slot in mesh.material_slots:
        mat = slot.material
        if mat is None:
            continue
        _cleanup_bake_prep_nodes(mat)
        bake_image = target_image if mat == work_mat else dummy
        _prepare_bake_nodes(mat, image=bake_image, uv_map_name=uv_map_name)


def _configure_cycles_bake(scene: bpy.types.Scene, spec: BakePassSpec) -> dict[str, object]:
    prev: dict[str, object] = {}
    cycles = scene.cycles
    bake = scene.render.bake

    prev["cycles_bake_type"] = cycles.bake_type
    cycles.bake_type = spec.bake_type

    if hasattr(bake, "use_pass_direct"):
        prev["use_pass_direct"] = bake.use_pass_direct
        prev["use_pass_indirect"] = bake.use_pass_indirect
        prev["use_pass_color"] = bake.use_pass_color
        if spec.bake_type == "DIFFUSE":
            bake.use_pass_direct = False
            bake.use_pass_indirect = False
            bake.use_pass_color = True
    return prev


def _restore_cycles_bake(scene: bpy.types.Scene, prev: dict[str, object]) -> None:
    if not prev:
        return
    cycles = scene.cycles
    bake = scene.render.bake
    if "cycles_bake_type" in prev:
        cycles.bake_type = prev["cycles_bake_type"]
    if hasattr(bake, "use_pass_direct"):
        if "use_pass_direct" in prev:
            bake.use_pass_direct = prev["use_pass_direct"]
        if "use_pass_indirect" in prev:
            bake.use_pass_indirect = prev["use_pass_indirect"]
        if "use_pass_color" in prev:
            bake.use_pass_color = prev["use_pass_color"]


def _select_mesh_for_bake(
    context: bpy.types.Context,
    mesh: bpy.types.Object,
    work_mat: bpy.types.Material,
) -> None:
    view_layer = context.view_layer
    for obj in view_layer.objects:
        obj.select_set(False)
    mesh.select_set(True)
    view_layer.objects.active = mesh
    try:
        mesh.active_material_index = _mesh_material_slot(mesh, work_mat) or 0
    except Exception:
        pass


def _pin_bake_target_image(mat: bpy.types.Material) -> Optional[bpy.types.ShaderNodeTexImage]:
    """Re-select the MonoFX bake target; new nodes often steal nodes.active."""
    if not mat.use_nodes or mat.node_tree is None:
        return None
    tree = mat.node_tree
    target: Optional[bpy.types.ShaderNodeTexImage] = None
    for node in tree.nodes:
        if node.type == "TEX_IMAGE" and node.label == _BAKE_PREP_NODE_LABEL:
            target = node
            break
    if target is None:
        return None
    for node in tree.nodes:
        node.select = False
    target.select = True
    tree.nodes.active = target
    return target


def _pin_bake_targets_on_mesh(mesh: bpy.types.Object) -> None:
    for slot in mesh.material_slots:
        if slot.material is not None:
            _pin_bake_target_image(slot.material)


def _refresh_baked_image_pixels(image: bpy.types.Image) -> None:
    if image is None:
        return
    try:
        image.update()
    except Exception:
        pass
    try:
        if image.size[0] > 0 and image.size[1] > 0:
            _ = image.pixels[0]
    except Exception:
        pass


def _run_object_bake(
    spec: BakePassSpec,
    scene: bpy.types.Scene,
    *,
    bake_mat: Optional[bpy.types.Material] = None,
    bake_mesh: Optional[bpy.types.Object] = None,
    target_image: Optional[bpy.types.Image] = None,
) -> None:
    if bake_mesh is not None:
        _pin_bake_targets_on_mesh(bake_mesh)
    elif bake_mat is not None:
        _pin_bake_target_image(bake_mat)
    prev = _configure_cycles_bake(scene, spec)
    try:
        kwargs: dict = {"type": spec.bake_type}
        if spec.pass_filter:
            kwargs["pass_filter"] = set(spec.pass_filter)
        bpy.ops.object.bake(**kwargs)
    finally:
        _restore_cycles_bake(scene, prev)
    if target_image is not None:
        _refresh_baked_image_pixels(target_image)
    if bake_mesh is not None:
        _pin_bake_targets_on_mesh(bake_mesh)
    elif bake_mat is not None:
        _pin_bake_target_image(bake_mat)


def _sync_view_layer(context: bpy.types.Context) -> None:
    try:
        context.view_layer.update()
    except Exception:
        pass
    try:
        context.evaluated_depsgraph_get().update()
    except Exception:
        pass


@contextmanager
def _film_transparent(scene: Optional[bpy.types.Scene], enabled: bool = True):
    if scene is None or not hasattr(scene.render, "film_transparent"):
        yield
        return
    prev = bool(scene.render.film_transparent)
    scene.render.film_transparent = bool(enabled)
    try:
        yield
    finally:
        scene.render.film_transparent = prev


def _snapshot_bake_margin(scene: bpy.types.Scene) -> dict[str, object]:
    prev: dict[str, object] = {}
    bake = getattr(scene.render, "bake", None)
    if bake is not None and hasattr(bake, "margin"):
        prev["bake_margin"] = int(bake.margin)
        if hasattr(bake, "margin_type"):
            prev["bake_margin_type"] = bake.margin_type
    if hasattr(scene.render, "bake_margin"):
        prev["render_bake_margin"] = int(scene.render.bake_margin)
    if hasattr(scene.render, "bake_margin_type"):
        prev["render_bake_margin_type"] = scene.render.bake_margin_type
    return prev


def _apply_bake_margin(scene: bpy.types.Scene, margin: int) -> None:
    """Apply margin on both legacy and Blender 4.x+ bake settings."""
    margin_px = int(margin)
    bake = getattr(scene.render, "bake", None)
    if bake is not None and hasattr(bake, "margin"):
        bake.margin = margin_px
        if hasattr(bake, "margin_type"):
            try:
                bake.margin_type = "ADJACENT_FACES"
            except (TypeError, ValueError, AttributeError):
                pass
    if hasattr(scene.render, "bake_margin"):
        scene.render.bake_margin = margin_px
    if hasattr(scene.render, "bake_margin_type"):
        try:
            scene.render.bake_margin_type = "ADJACENT_FACES"
        except (TypeError, ValueError, AttributeError):
            pass


def _restore_bake_margin(scene: bpy.types.Scene, prev: dict[str, object]) -> None:
    if not prev:
        return
    bake = getattr(scene.render, "bake", None)
    if bake is not None and "bake_margin" in prev and hasattr(bake, "margin"):
        bake.margin = prev["bake_margin"]
    if bake is not None and "bake_margin_type" in prev and hasattr(bake, "margin_type"):
        bake.margin_type = prev["bake_margin_type"]
    if "render_bake_margin" in prev and hasattr(scene.render, "bake_margin"):
        scene.render.bake_margin = prev["render_bake_margin"]
    if "render_bake_margin_type" in prev and hasattr(scene.render, "bake_margin_type"):
        scene.render.bake_margin_type = prev["render_bake_margin_type"]


@contextmanager
def _temporary_bake_margin(scene: bpy.types.Scene, margin: int):
    prev = _snapshot_bake_margin(scene)
    _apply_bake_margin(scene, margin)
    try:
        yield
    finally:
        _restore_bake_margin(scene, prev)


def _finalize_baked_image(image: bpy.types.Image) -> bpy.types.Image:
    """Save baked pixels to disk once (no reload cycle)."""
    _save_image(image, pack=False)
    try:
        image.update()
    except Exception:
        pass
    return image


def _save_image(image: bpy.types.Image, *, pack: bool) -> None:
    if not image:
        return
    path = (image.filepath_raw or image.filepath or "").strip()
    if path:
        try:
            image.filepath_raw = bpy.path.abspath(path)
        except Exception:
            pass
    if pack:
        try:
            image.pack()
        except Exception:
            pass
    if path:
        try:
            image.save()
            image.update()
        except Exception:
            pass


def _find_principled_bsdf(
    tree: bpy.types.NodeTree,
) -> Optional[bpy.types.ShaderNodeBsdfPrincipled]:
    return next((node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"), None)


def _trace_upstream_nodes(start_socket: bpy.types.NodeSocket) -> list[bpy.types.Node]:
    if not start_socket.is_linked:
        return []
    stack = [start_socket.links[0].from_node]
    visited: set[int] = set()
    found: list[bpy.types.Node] = []
    while stack:
        node = stack.pop()
        node_id = id(node)
        if node_id in visited:
            continue
        visited.add(node_id)
        found.append(node)
        for sock in node.inputs:
            if sock.is_linked:
                stack.append(sock.links[0].from_node)
    return found


def _surface_shader_nodes(tree: bpy.types.NodeTree) -> list[bpy.types.Node]:
    output = next((node for node in tree.nodes if node.type == "OUTPUT_MATERIAL"), None)
    if output is None:
        return []
    surface = output.inputs.get("Surface")
    if surface is None or not surface.is_linked:
        return []
    return _trace_upstream_nodes(surface)


def _linked_shader_node(socket: bpy.types.NodeSocket) -> Optional[bpy.types.Node]:
    if not socket.is_linked:
        return None
    return socket.links[0].from_node


def _is_transparent_shader_node(node: bpy.types.Node) -> bool:
    return node.type in ("BSDF_TRANSPARENT", "HOLDOUT", "BSDF_GLASS")


def _mix_shader_inputs(mix_node: bpy.types.Node) -> list[bpy.types.NodeSocket]:
    sockets: list[bpy.types.NodeSocket] = []
    for name in ("Shader", "Shader_001"):
        sock = mix_node.inputs.get(name)
        if sock is not None and sock.type == "SHADER":
            sockets.append(sock)
    if len(sockets) < 2:
        sockets = [sock for sock in mix_node.inputs if sock.type == "SHADER"]
    return sockets[:2]


def _mix_shader_has_transparent_branch(mix_node: bpy.types.Node) -> bool:
    shader_inputs = _mix_shader_inputs(mix_node)
    for sock in shader_inputs:
        node = _linked_shader_node(sock)
        if node is not None and _is_transparent_shader_node(node):
            return True
    return False


def _opaque_mix_fac_default(mix_node: bpy.types.Node) -> float:
    """Pick the Mix Shader Fac that selects the non-transparent input."""
    shader_inputs = _mix_shader_inputs(mix_node)
    if len(shader_inputs) < 2:
        return 0.0
    first = _linked_shader_node(shader_inputs[0])
    second = _linked_shader_node(shader_inputs[1])
    first_trans = first is not None and _is_transparent_shader_node(first)
    second_trans = second is not None and _is_transparent_shader_node(second)
    if second_trans and not first_trans:
        return 0.0
    if first_trans and not second_trans:
        return 1.0
    return 0.0


@contextmanager
def _bake_without_shader_alpha(mat: bpy.types.Material):
    """
    Force an opaque surface for diffuse baking:
    - unplug Principled Alpha and image Alpha outputs
    - pin Mix Shader Fac (mask → transparent) to the opaque branch
    - set material blend mode opaque
    """
    if not mat.use_nodes or mat.node_tree is None:
        yield
        return

    tree = mat.node_tree
    saved_links: list[tuple[bpy.types.NodeSocket, bpy.types.NodeSocket]] = []
    saved_fac_defaults: list[tuple[bpy.types.Node, float]] = []
    prev_alpha_default: Optional[float] = None
    prev_blend_method: Optional[str] = None

    principled = _find_principled_bsdf(tree)
    if principled is not None:
        alpha_in = principled.inputs.get("Alpha")
        if alpha_in is not None:
            try:
                prev_alpha_default = float(alpha_in.default_value)
            except (TypeError, ValueError, AttributeError):
                prev_alpha_default = None
            try:
                alpha_in.default_value = 1.0
            except Exception:
                pass
            for link in list(alpha_in.links):
                saved_links.append((link.from_socket, link.to_socket))
                tree.links.remove(link)

    for node in tree.nodes:
        if node.type != "TEX_IMAGE":
            continue
        alpha_out = node.outputs.get("Alpha")
        if alpha_out is None:
            continue
        for link in list(alpha_out.links):
            saved_links.append((link.from_socket, link.to_socket))
            tree.links.remove(link)

    for node in _surface_shader_nodes(tree):
        if node.type != "MIX_SHADER":
            continue
        if not _mix_shader_has_transparent_branch(node):
            continue
        fac_in = node.inputs.get("Fac")
        if fac_in is None:
            continue
        try:
            saved_fac_defaults.append((node, float(fac_in.default_value)))
        except (TypeError, ValueError, AttributeError):
            saved_fac_defaults.append((node, 0.0))
        for link in list(fac_in.links):
            saved_links.append((link.from_socket, link.to_socket))
            tree.links.remove(link)
        try:
            fac_in.default_value = _opaque_mix_fac_default(node)
        except Exception:
            pass

    try:
        prev_blend_method = str(mat.blend_method)
        mat.blend_method = "OPAQUE"
    except Exception:
        prev_blend_method = None

    try:
        yield
    finally:
        for from_socket, to_socket in saved_links:
            try:
                tree.links.new(from_socket, to_socket)
            except (RuntimeError, ReferenceError):
                pass
        for mix_node, default_value in saved_fac_defaults:
            fac_in = mix_node.inputs.get("Fac")
            if fac_in is not None:
                try:
                    fac_in.default_value = default_value
                except Exception:
                    pass
        if principled is not None and prev_alpha_default is not None:
            alpha_in = principled.inputs.get("Alpha")
            if alpha_in is not None:
                try:
                    alpha_in.default_value = prev_alpha_default
                except Exception:
                    pass
        if prev_blend_method is not None:
            try:
                mat.blend_method = prev_blend_method
            except Exception:
                pass


def _bake_diffuse_zero_margin(
    context: bpy.types.Context,
    mesh: bpy.types.Object,
    work_mat: bpy.types.Material,
    scene: bpy.types.Scene,
    spec: BakePassSpec,
    *,
    target_image: bpy.types.Image,
    uv_map_name: str,
) -> None:
    """Second diffuse bake with margin 0 (separate Opacity file)."""
    _activate_bake_targets_on_mesh(
        mesh,
        work_mat,
        target_image=target_image,
        uv_map_name=uv_map_name,
    )
    _select_mesh_for_bake(context, mesh, work_mat)
    _sync_view_layer(context)
    with _temporary_bake_margin(scene, 0):
        _run_object_bake(
            spec,
            scene,
            bake_mat=work_mat,
            bake_mesh=mesh,
            target_image=target_image,
        )


def _bind_baked_image_to_node(
    img_node: bpy.types.ShaderNodeTexImage,
    image: bpy.types.Image,
    *,
    filepath: Optional[Path] = None,
) -> bpy.types.Image:
    """Assign a baked image to a texture node, reloading from disk when needed."""
    bound = image
    path = filepath or Path((image.filepath_raw or "").strip())
    if str(path).strip():
        abs_path = Path(bpy.path.abspath(str(path)))
        if abs_path.is_file():
            try:
                bound = bpy.data.images.load(str(abs_path), check_existing=True)
            except Exception:
                try:
                    image.reload()
                    bound = image
                except Exception:
                    bound = image
    img_node.image = bound
    return bound


def simplify_material_for_usd(
    mat: bpy.types.Material,
    baked_images: dict[str, bpy.types.Image],
    *,
    uv_map_name: str,
    texture_paths: Optional[dict[str, Path]] = None,
) -> None:
    mat.use_nodes = True
    tree = mat.node_tree
    assert tree is not None
    tree.nodes.clear()

    output = tree.nodes.new("ShaderNodeOutputMaterial")
    principled = tree.nodes.new("ShaderNodeBsdfPrincipled")
    output.location = (400, 0)
    principled.location = (100, 0)
    tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    uv = tree.nodes.new("ShaderNodeUVMap")
    uv.location = (-500, 0)
    if uv_map_name:
        uv.uv_map = uv_map_name

    y = 200
    paths = texture_paths or {}

    if config.BAKE_SLOT_BASE_COLOR in baked_images:
        img_node = tree.nodes.new("ShaderNodeTexImage")
        _bind_baked_image_to_node(
            img_node,
            baked_images[config.BAKE_SLOT_BASE_COLOR],
            filepath=paths.get(config.BAKE_SLOT_BASE_COLOR),
        )
        _set_image_colorspace(img_node.image, "sRGB")
        img_node.location = (-250, y)
        tree.links.new(uv.outputs["UV"], img_node.inputs["Vector"])
        tree.links.new(img_node.outputs["Color"], principled.inputs["Base Color"])
        y -= 200

    if config.BAKE_SLOT_ROUGHNESS in baked_images:
        img_node = tree.nodes.new("ShaderNodeTexImage")
        _bind_baked_image_to_node(
            img_node,
            baked_images[config.BAKE_SLOT_ROUGHNESS],
            filepath=paths.get(config.BAKE_SLOT_ROUGHNESS),
        )
        _set_image_colorspace(img_node.image, "Non-Color")
        img_node.location = (-250, y)
        tree.links.new(uv.outputs["UV"], img_node.inputs["Vector"])
        tree.links.new(img_node.outputs["Color"], principled.inputs["Roughness"])
        y -= 200

    if config.BAKE_SLOT_NORMAL in baked_images:
        img_node = tree.nodes.new("ShaderNodeTexImage")
        _bind_baked_image_to_node(
            img_node,
            baked_images[config.BAKE_SLOT_NORMAL],
            filepath=paths.get(config.BAKE_SLOT_NORMAL),
        )
        _set_image_colorspace(img_node.image, "Non-Color")
        img_node.location = (-250, y)
        normal_map = tree.nodes.new("ShaderNodeNormalMap")
        normal_map.location = (-50, y)
        tree.links.new(uv.outputs["UV"], img_node.inputs["Vector"])
        tree.links.new(img_node.outputs["Color"], normal_map.inputs["Color"])
        tree.links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])
        y -= 200

    if config.BAKE_SLOT_OPACITY in baked_images:
        img_node = tree.nodes.new("ShaderNodeTexImage")
        _bind_baked_image_to_node(
            img_node,
            baked_images[config.BAKE_SLOT_OPACITY],
            filepath=paths.get(config.BAKE_SLOT_OPACITY),
        )
        _set_image_colorspace(img_node.image, "sRGB")
        img_node.location = (-250, y)
        tree.links.new(uv.outputs["UV"], img_node.inputs["Vector"])
        alpha_out = img_node.outputs.get("Alpha")
        if alpha_out is not None:
            tree.links.new(alpha_out, principled.inputs["Alpha"])
            try:
                mat.blend_method = "HASHED"
            except Exception:
                pass
            try:
                principled.inputs["Alpha"].default_value = 1.0
            except Exception:
                pass


def bake_materials_for_usd(
    context: bpy.types.Context,
    meshes: Sequence[bpy.types.Object],
    *,
    scope: str = config.DEFAULT_MATERIAL_BAKE_SCOPE,
    material_prefix: str = config.DEFAULT_MATERIAL_PREFIX,
    targets: Optional[Sequence[BakeTarget]] = None,
    pass_base_color: bool = True,
    pass_roughness: bool = True,
    pass_normal: bool = True,
    pass_ao: bool = False,
    pass_opacity: bool = False,
    resolution: int = 2048,
    output_dir: Path,
    image_format: str = config.DEFAULT_MATERIAL_BAKE_IMAGE_FORMAT,
    uv_map_name: str = "",
    margin: int = config.DEFAULT_MATERIAL_BAKE_MARGIN,
    pack_images: bool = config.DEFAULT_MATERIAL_BAKE_PACK_IMAGES,
    simplify_shader: bool = config.DEFAULT_MATERIAL_BAKE_SIMPLIFY_SHADER,
    texture_stem_mode: str = config.DEFAULT_MATERIAL_BAKE_TEXTURE_STEM_MODE,
    shader_name_mode: str = config.DEFAULT_MATERIAL_BAKE_SHADER_NAME_MODE,
    texture_stem_template: str = config.DEFAULT_MATERIAL_BAKE_TEXTURE_STEM_TEMPLATE,
    shader_name_template: str = config.DEFAULT_MATERIAL_BAKE_SHADER_NAME_TEMPLATE,
) -> MaterialBakeResult:
    from .material_bake_session import MaterialBakeSession, run_material_bake_session

    session = MaterialBakeSession(
        context,
        meshes,
        scope=scope,
        material_prefix=material_prefix,
        targets=targets,
        pass_base_color=pass_base_color,
        pass_roughness=pass_roughness,
        pass_normal=pass_normal,
        pass_ao=pass_ao,
        pass_opacity=pass_opacity,
        resolution=resolution,
        output_dir=output_dir,
        image_format=image_format,
        uv_map_name=uv_map_name,
        margin=margin,
        pack_images=pack_images,
        simplify_shader=simplify_shader,
        texture_stem_mode=texture_stem_mode,
        shader_name_mode=shader_name_mode,
        texture_stem_template=texture_stem_template,
        shader_name_template=shader_name_template,
    )
    err = session.begin()
    if err:
        result = MaterialBakeResult()
        result.error = err
        return result

    wm = context.window_manager

    def _on_progress(active: MaterialBakeSession) -> None:
        if hasattr(wm, "progress_update"):
            wm.progress_update(active.current_step)

    if hasattr(wm, "progress_begin"):
        wm.progress_begin(0, session.total_steps)
    try:
        return run_material_bake_session(session, on_progress=_on_progress)
    finally:
        if hasattr(wm, "progress_end"):
            wm.progress_end()
