"""
Config for Auto Material Builder.
"""

from __future__ import annotations

WINDOW_TITLE = "Auto Material Builder"

IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
    ".rat", ".tex", ".hdr", ".bmp", ".tga",
})

UDIM_REGEX = r"\.(\d{4})\."

RESOLUTION_TOKENS: frozenset[str] = frozenset({
    "1k", "2k", "4k", "8k", "16k",
})

PUBLISH_TEXTURE_RELATIVE_PATH = "../../../03_surfacing/02_texturing/publish"


class SlotDef:
    __slots__ = ("internal", "pipeline_names", "generic_aliases", "default_colorspace", "signature")

    def __init__(
        self,
        internal: str,
        pipeline_names: tuple[str, ...],
        generic_aliases: tuple[str, ...],
        default_colorspace: str,
        signature: str = "color3",
    ) -> None:
        self.internal = internal
        self.pipeline_names = pipeline_names
        self.generic_aliases = generic_aliases
        self.default_colorspace = default_colorspace
        self.signature = signature


SLOT_DEFS: tuple[SlotDef, ...] = (
    SlotDef("base_color",      ("BaseColor",),                   ("diffuse", "diff", "albedo", "color", "col", "basecolor", "d"),   "sRGB",  "color3"),
    SlotDef("roughness",       ("Roughness",),                   ("rough", "rgh", "roughness"),                                      "RAW",   "float"),
    SlotDef("metallic",        ("Metallic", "Metalness"),         ("metal", "mtl", "metallic", "metalness"),                          "RAW",   "float"),
    SlotDef("normal",          ("Normal",),                       ("normal", "nrm", "norm", "nor"),                                   "RAW",   "vector3"),
    SlotDef("opacity",         ("Opacity",),                      ("opacity", "alpha", "mask"),                                       "RAW",   "float"),
    SlotDef("emission_color",  ("EmissionColor",),                ("emissive", "emission", "emit"),                                   "sRGB",  "color3"),
    SlotDef("displacement",    ("Displacement",),                 ("displacement", "disp", "height", "bump"),                         "RAW",   "float"),
    SlotDef("ao",              ("AO", "AmbientOcclusion"),        ("ao", "occlusion", "ambientocclusion"),                            "RAW",   "float"),
    SlotDef("specular",        ("Specular",),                     ("specular", "spec", "refl"),                                       "RAW",   "float"),
    SlotDef("translucency",    ("Translucency",),                 ("translucency", "transmission", "trans"),                         "RAW",   "float"),
)

PIPELINE_NAME_TO_SLOT: dict[str, str] = {}
for _sd in SLOT_DEFS:
    for _pn in _sd.pipeline_names:
        PIPELINE_NAME_TO_SLOT[_pn] = _sd.internal

GENERIC_ALIAS_TO_SLOT: dict[str, str] = {}
for _sd in SLOT_DEFS:
    for _ga in _sd.generic_aliases:
        GENERIC_ALIAS_TO_SLOT[_ga.lower()] = _sd.internal

SLOT_DEF_MAP: dict[str, SlotDef] = {sd.internal: sd for sd in SLOT_DEFS}

SURFACE_INPUT_MAP: dict[str, str] = {
    "base_color":     "base_color",
    "roughness":      "specular_roughness",
    "metallic":       "metalness",
    "normal":         "normal",
    "opacity":        "opacity",
    "emission_color": "emission_color",
    "specular":       "specular",
    "translucency":   "transmission",
}
