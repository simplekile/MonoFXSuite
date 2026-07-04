"""
MonoFX Pipeline Blender add-on constants and defaults.
"""

from __future__ import annotations

from pathlib import Path

# Asset hierarchy (collection Geo_<Asset>, object tree Geo -> *_Grp)
ASSET_ROOT_PREFIX = "Geo_"
INNER_GEO_NAME = "Geo"
GRP_SUFFIX_MIXED = "_Grp"
GRP_SUFFIX_LOWER = "_grp"

# Mesh naming (Preparing Asset)
MESH_GEO_PREFIX = "geo_"
DEFAULT_MATERIAL_PREFIX = "M_char_"

# USD exporter defaults (Blender wm.usd_export)
DEFAULT_CONVERT_ORIENTATION = True
DEFAULT_EXPORT_FORWARD = "NEGATIVE_Z"
DEFAULT_EXPORT_UP = "Y"
DEFAULT_CONVERT_SCENE_UNITS = "METERS"
DEFAULT_USD_ROOT_PRIM_PATH = "/"
DEFAULT_GENERATE_PREVIEW_SURFACE = False
DEFAULT_GENERATE_MATERIALX_NETWORK = True

# Material bake for USD
DEFAULT_MATERIAL_BAKE_SCOPE = "PER_MESH"
DEFAULT_MATERIAL_BAKE_RESOLUTION = "2048"
DEFAULT_MATERIAL_BAKE_OUTPUT_MODE = "BLEND_TEXTURES"
DEFAULT_MATERIAL_BAKE_IMAGE_FORMAT = "PNG"
DEFAULT_MATERIAL_BAKE_MARGIN = 16
DEFAULT_MATERIAL_BAKE_PACK_IMAGES = False
DEFAULT_MATERIAL_BAKE_SIMPLIFY_SHADER = True
DEFAULT_MATERIAL_BAKE_TEXTURE_STEM_MODE = "MATERIAL_MESH"
DEFAULT_MATERIAL_BAKE_SHADER_NAME_MODE = "MATERIAL_MESH"
DEFAULT_MATERIAL_BAKE_TEXTURE_STEM_TEMPLATE = "{material_stem}_{mesh}"
DEFAULT_MATERIAL_BAKE_SHADER_NAME_TEMPLATE = "{material}_{texture_stem}"

BAKE_SLOT_BASE_COLOR = "BaseColor"
BAKE_SLOT_ROUGHNESS = "Roughness"
BAKE_SLOT_NORMAL = "Normal"
BAKE_SLOT_AO = "AO"
BAKE_SLOT_OPACITY = "Opacity"

# Warn on save/load preset when a *leaf* uses only these vague single tokens (not used at match time).
BANNED_AUTO_KEYWORDS = frozenset({"hair", "belt", "dress", "arm", "shirt"})

COSTUME_GRP_NAME = "Costume_Grp"

# Global auto-parent leaf targets (empty name)
ACCESSORY_GRP_NAME = "Accessory_Grp"
BODY_GRP_NAME = "Body_Grp"

_ADDON_DIR = Path(__file__).resolve().parent
DEFAULT_PRESET_JSON = _ADDON_DIR / "presets" / "character_geo.json"
