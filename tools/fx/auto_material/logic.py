"""
Auto Material logic — DCC-agnostic.
Scan folder for texture files, parse naming conventions, group into material sets.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from tools.fx.auto_material.config import (
    GENERIC_ALIAS_TO_SLOT,
    IMAGE_EXTENSIONS,
    PIPELINE_NAME_TO_SLOT,
    RESOLUTION_TOKENS,
    SUBSTANCE_COLORSPACE_WORDS,
    SUBSTANCE_INPUT_TO_SLOT,
    UDIM_REGEX,
)


@dataclass
class ParseResult:
    filepath: str
    prefix: str
    slot: str
    colorspace: str | None = None
    udim: bool = False
    parse_mode: str = "pipeline"


@dataclass
class SlotInfo:
    filepath: str
    colorspace: str | None = None
    udim: bool = False


@dataclass
class MaterialGroup:
    prefix: str
    slots: dict[str, SlotInfo] = field(default_factory=dict)
    parse_mode: str = "pipeline"


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

_VERSION_DIR_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)


def latest_publish_version(folder: str) -> Path | None:
    """Highest vNNN child of a Monos publish folder, None when *folder* has no such child."""
    root = Path(folder)
    if not root.is_dir():
        return None
    versions = [
        (int(m.group(1)), p)
        for p in root.iterdir()
        if p.is_dir() and (m := _VERSION_DIR_RE.match(p.name))
    ]
    return max(versions)[1] if versions else None


def resolve_scan_folder(folder: str) -> str:
    """
    Folder to scan: a Monos publish folder (children v001, v002...) gives only its latest
    version's textures/, so older publishes are not picked up. Any other folder is as given.
    """
    latest = latest_publish_version(folder)
    if latest is None:
        return folder
    textures = latest / "textures"
    return str(textures if textures.is_dir() else latest)


def read_publish_spaces(version_dir: str | Path) -> dict[str, str]:
    """
    Slot -> colour space word from a Monos vNNN/publish.json (cleaned.maps: [{name, space}...]).
    Used only for files whose name has no colour space; maps exported in several spaces are left out.
    """
    try:
        data = json.loads((Path(version_dir) / "publish.json").read_text(encoding="utf-8"))
        maps = data.get("cleaned", {}).get("maps", [])
    except (OSError, ValueError, AttributeError):
        return {}
    out: dict[str, str] = {}
    for m in maps if isinstance(maps, list) else []:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "")
        space = str(m.get("space") or "").strip()
        slot = PIPELINE_NAME_TO_SLOT.get(name) or GENERIC_ALIAS_TO_SLOT.get(name.lower())
        if slot and space and "," not in space:
            out[slot] = space
    return out


def scan_images(folder: str, recursive: bool = True) -> list[str]:
    root = Path(folder)
    if not root.is_dir():
        return []
    pattern = "**/*" if recursive else "*"
    return sorted(
        str(p)
        for p in root.glob(pattern)
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


# ---------------------------------------------------------------------------
# UDIM helpers
# ---------------------------------------------------------------------------

_UDIM_RE = re.compile(UDIM_REGEX)


def _strip_udim(stem: str) -> tuple[str, bool]:
    """Remove trailing .XXXX from stem. Returns (clean_stem, has_udim)."""
    m = re.search(r"\.(\d{4})$", stem)
    if m and int(m.group(1)) >= 1001:
        return stem[: m.start()], True
    return stem, False


def _make_udim_path(filepath: str) -> str:
    """Replace the UDIM tile number with %(UDIM)d token."""
    p = Path(filepath)
    stem = p.stem
    m = re.search(r"\.(\d{4})$", stem)
    if m and int(m.group(1)) >= 1001:
        new_stem = stem[: m.start()] + ".%(UDIM)d"
        return str(p.with_name(new_stem + p.suffix))
    return filepath


# ---------------------------------------------------------------------------
# Pipeline parse
# ---------------------------------------------------------------------------

def try_pipeline_parse(filepath: str) -> ParseResult | None:
    """
    Parse pipeline naming: {prefix}_{Slot}_{ColorSpace}.{UDIM}.{ext}
    Prefix may contain underscores. Slot is the first token that matches a known PascalCase name.
    """
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        return None

    stem = p.stem
    stem_clean, has_udim = _strip_udim(stem)

    parts = stem_clean.split("_")
    if len(parts) < 2:
        return None

    slot_idx: int | None = None
    slot_token: str | None = None
    for i, token in enumerate(parts):
        if token in PIPELINE_NAME_TO_SLOT:
            slot_idx = i
            slot_token = token
            break

    if slot_idx is None or slot_token is None:
        return None

    prefix = "_".join(parts[:slot_idx]) if slot_idx > 0 else parts[0]
    colorspace = "_".join(parts[slot_idx + 1 :]) if slot_idx + 1 < len(parts) else None
    slot_internal = PIPELINE_NAME_TO_SLOT[slot_token]

    return ParseResult(
        filepath=filepath,
        prefix=prefix,
        slot=slot_internal,
        colorspace=colorspace or None,
        udim=has_udim,
        parse_mode="pipeline",
    )


# ---------------------------------------------------------------------------
# Generic parse
# ---------------------------------------------------------------------------

def try_generic_parse(filepath: str) -> ParseResult | None:
    """
    Fallback: split all separators, scan tokens right-to-left for known keyword.
    """
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        return None

    stem = p.stem
    stem_clean, has_udim = _strip_udim(stem)

    tokens = re.split(r"[_\-.]", stem_clean)
    if not tokens:
        return None

    slot_idx = -1
    slot_internal: str | None = None

    for i in range(len(tokens) - 1, -1, -1):
        t_lower = tokens[i].lower()
        if t_lower in RESOLUTION_TOKENS:
            continue
        if t_lower in GENERIC_ALIAS_TO_SLOT:
            slot_idx = i
            slot_internal = GENERIC_ALIAS_TO_SLOT[t_lower]
            break

    if slot_internal is None or slot_idx < 0:
        return None

    prefix_tokens = [t for t in tokens[:slot_idx] if t.lower() not in RESOLUTION_TOKENS]
    prefix = "_".join(prefix_tokens) if prefix_tokens else p.parent.name

    if not prefix:
        prefix = "unnamed"

    return ParseResult(
        filepath=filepath,
        prefix=prefix,
        slot=slot_internal,
        colorspace=None,
        udim=has_udim,
        parse_mode="generic",
    )


# ---------------------------------------------------------------------------
# Auto parse
# ---------------------------------------------------------------------------

def auto_parse(filepath: str) -> ParseResult | None:
    return try_pipeline_parse(filepath) or try_generic_parse(filepath)


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------

def group_by_prefix(results: list[ParseResult]) -> dict[str, MaterialGroup]:
    groups: dict[str, MaterialGroup] = {}
    for r in results:
        if r.prefix not in groups:
            groups[r.prefix] = MaterialGroup(prefix=r.prefix, parse_mode=r.parse_mode)
        g = groups[r.prefix]
        if r.slot not in g.slots:
            path = _make_udim_path(r.filepath) if r.udim else r.filepath
            g.slots[r.slot] = SlotInfo(
                filepath=path,
                colorspace=r.colorspace,
                udim=r.udim,
            )
    return dict(sorted(groups.items()))


def group_by_subfolder(results: list[ParseResult]) -> dict[str, MaterialGroup]:
    groups: dict[str, MaterialGroup] = {}
    for r in results:
        folder_name = Path(r.filepath).parent.name or "root"
        if folder_name not in groups:
            groups[folder_name] = MaterialGroup(prefix=folder_name, parse_mode=r.parse_mode)
        g = groups[folder_name]
        if r.slot not in g.slots:
            path = _make_udim_path(r.filepath) if r.udim else r.filepath
            g.slots[r.slot] = SlotInfo(
                filepath=path,
                colorspace=r.colorspace,
                udim=r.udim,
            )
    return dict(sorted(groups.items()))


def scan_and_group(
    folder: str,
    recursive: bool = True,
) -> tuple[dict[str, MaterialGroup], list[str]]:
    """
    Full pipeline: scan → parse → group.
    Returns (groups, unmatched_files).
    """
    folder = resolve_scan_folder(folder)
    files = scan_images(folder, recursive=recursive)
    parsed: list[ParseResult] = []
    unmatched: list[str] = []
    # publish.json sits in vNNN/, next to textures/
    spaces = read_publish_spaces(folder) or read_publish_spaces(Path(folder).parent)

    for f in files:
        result = auto_parse(f)
        if result is not None:
            if result.colorspace is None:
                result.colorspace = spaces.get(result.slot)
            parsed.append(result)
        else:
            unmatched.append(f)

    groups = group_by_prefix(parsed)
    return groups, unmatched


# ---------------------------------------------------------------------------
# Substance Painter USD export
# ---------------------------------------------------------------------------

@dataclass
class SubstanceMaterial:
    """One Material prim of a Painter USD export, as the Houdini adapter read it."""
    name: str
    usd_path: str
    textures: dict[str, str]          # Painter asset input -> absolute texture path
    layers: list[str] = field(default_factory=list)  # layers that author the prim


@dataclass
class SubstanceSource:
    usd_path: str
    node_base: str
    geo_layers: list[str]
    assignments: dict[str, list[str]]  # material name -> bound prim paths


_PAINTER_UDIM_RE = re.compile(r"\.(<UDIM>|\d{4})(?=\.[^.]+$)")
_VERSION_TOKEN_RE = re.compile(r"_v\d+(?=_|$)", re.IGNORECASE)


def _substance_texture_slot(filepath: str) -> SlotInfo:
    """
    Painter writes <UDIM> for a set on several tiles and the first tile (.1001) for a set on one;
    both become the tool's .%(UDIM)d form. The colour space is the last name token when it is one
    Painter writes (ACEScg, Raw, sRGB, Linear); Painter's colorSpace metadata is always "raw".
    """
    name = Path(filepath).name
    folder = filepath[: len(filepath) - len(name)]
    m = _PAINTER_UDIM_RE.search(name)
    udim = bool(m) and (m.group(1) == "<UDIM>" or int(m.group(1)) >= 1001)
    if udim:
        stem = name[: m.start()]
        path = folder + stem + ".%(UDIM)d" + name[m.end():]
    else:
        stem = Path(name).stem
        path = filepath

    last = stem.rsplit("_", 1)[-1]
    colorspace = last if last.lower() in SUBSTANCE_COLORSPACE_WORDS else None
    return SlotInfo(filepath=path, colorspace=colorspace, udim=udim)


USD_EXTENSIONS: frozenset[str] = frozenset({".usd", ".usda", ".usdc"})
_FILE_VERSION_RE = re.compile(r"_v(\d+)(?=[_.]|$)", re.IGNORECASE)


def is_usd_path(path: str) -> bool:
    return Path(path).suffix.lower() in USD_EXTENSIONS and Path(path).is_file()


def find_painter_usd(folder: str) -> str | None:
    """
    Painter USD export in a publish folder: in its highest vNNN child (or the folder itself), the
    .usd* file with the highest _vNNN in its name. Painter's sublayer (*.material.usda) is skipped.
    None when there is no USD, so the folder is scanned for textures as before.
    """
    root = latest_publish_version(folder) or Path(folder)
    if not root.is_dir():
        return None
    exports = [
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in USD_EXTENSIONS and ".material." not in p.name.lower()
    ]
    if not exports:
        return None

    def version(p: Path) -> int:
        m = _FILE_VERSION_RE.search(p.stem)
        return int(m.group(1)) if m else -1

    return str(max(exports, key=lambda p: (version(p), p.name)))


def substance_node_base(usd_path: str) -> str:
    """LOP node name base from the export file, without its version, so v009 updates v008's nodes."""
    stem = Path(usd_path).name.split(".", 1)[0]
    stem = _VERSION_TOKEN_RE.sub("", stem)
    return re.sub(r"[^A-Za-z0-9_]", "_", stem) or "substance"


def substance_groups(
    materials: list[SubstanceMaterial],
) -> dict[str, MaterialGroup]:
    """Painter materials -> material groups, one slot per known texture input."""
    groups: dict[str, MaterialGroup] = {}
    for mat in materials:
        group = MaterialGroup(prefix=mat.name, parse_mode="substance")
        for usd_input, filepath in mat.textures.items():
            slot = SUBSTANCE_INPUT_TO_SLOT.get(usd_input)
            if slot and slot not in group.slots:
                group.slots[slot] = _substance_texture_slot(filepath)
        if group.slots:
            groups[mat.name] = group
    return dict(sorted(groups.items()))


def substance_geo_layers(
    usd_path: str,
    sublayers: list[str],
    materials: list[SubstanceMaterial],
) -> list[str]:
    """
    The export's sublayers that author none of Painter's materials: the geometry Painter was given
    (e.g. the UV publish), which may hold materials of its own. None of them -> the export itself.
    """
    def norm(p: str) -> str:
        return str(Path(p)).replace("\\", "/").lower()

    # Only Painter's materials (they carry texture inputs) mark a layer as not geometry.
    material_layers = {norm(layer) for mat in materials if mat.textures for layer in mat.layers}
    geo = [layer for layer in sublayers if norm(layer) not in material_layers]
    return geo or [usd_path]


def substance_source(
    usd_path: str,
    sublayers: list[str],
    materials: list[SubstanceMaterial],
    bindings: dict[str, list[str]],
) -> tuple[dict[str, MaterialGroup], SubstanceSource]:
    """
    Everything Create needs from a Painter export. bindings: Material prim path -> prims bound to
    it (material:binding). Materials without a known texture input are left out (the geometry
    file's own materials have none).
    """
    groups = substance_groups(materials)
    by_path = {mat.usd_path: mat.name for mat in materials if mat.name in groups}
    assignments: dict[str, list[str]] = {}
    for mat_path, prims in bindings.items():
        name = by_path.get(mat_path)
        if name:
            assignments.setdefault(name, []).extend(prims)
    source = SubstanceSource(
        usd_path=usd_path,
        node_base=substance_node_base(usd_path),
        geo_layers=substance_geo_layers(usd_path, sublayers, materials),
        assignments={k: sorted(set(v)) for k, v in sorted(assignments.items())},
    )
    return groups, source


def substance_assign_entries(
    source: SubstanceSource,
    material_paths: dict[str, str],
) -> list[tuple[str, str]]:
    """(prim pattern, material path) per material built, prims space-separated as Houdini takes them."""
    return [
        (" ".join(prims), material_paths[name])
        for name, prims in source.assignments.items()
        if name in material_paths and prims
    ]
