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
    """Replace the UDIM tile number with the <UDIM> token (MaterialX / USD; Houdini's %(UDIM)d is not)."""
    p = Path(filepath)
    stem = p.stem
    m = re.search(r"\.(\d{4})$", stem)
    if m and int(m.group(1)) >= 1001:
        new_stem = stem[: m.start()] + ".<UDIM>"
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
    both become .<UDIM>. The colour space is the last name token when it is one
    Painter writes (ACEScg, Raw, sRGB, Linear); Painter's colorSpace metadata is always "raw".
    """
    name = Path(filepath).name
    folder = filepath[: len(filepath) - len(name)]
    m = _PAINTER_UDIM_RE.search(name)
    udim = bool(m) and (m.group(1) == "<UDIM>" or int(m.group(1)) >= 1001)
    if udim:
        stem = name[: m.start()]
        path = folder + stem + ".<UDIM>" + name[m.end():]
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


def export_family(usd_path: str) -> tuple[str, str]:
    """(name before _vNNN, what follows it): char_Helen_texturing_v008_full -> (char_Helen_texturing, _full)."""
    stem = Path(usd_path).name.split(".", 1)[0]
    m = None
    for m in _VERSION_TOKEN_RE.finditer(stem):
        pass
    if m is None:
        return stem.casefold(), ""
    return stem[: m.start()].casefold(), stem[m.end():].casefold()


def same_family(a: str, b: str) -> bool:
    """
    Exports of one asset: same name before the version, and the same suffix, or one of them has none
    (char_v008_full then char_v010: the suffix was dropped). char_v008_full and char_v010_lite differ.
    """
    (pa, sa_), (pb, sb) = export_family(a), export_family(b)
    return pa == pb and (sa_ == sb or not sa_ or not sb)


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


# ---------------------------------------------------------------------------
# Painter export versions: the Version manager
# ---------------------------------------------------------------------------
# Each Painter export (…_v008_full.usd) carries every texture set of the asset, with its textures in
# its own folder (…_v008_full_textures). The scene remembers, on the asset's Material Library, which
# export each material was built from and whether it is pinned there (see dump_record / parse_record).

_PATH_VERSION_RE = re.compile(r"_v(\d+)(?=[_./\\]|$)", re.IGNORECASE)

# Material status in the Version manager, in the order the chips show them.
STATUS_OK = "ok"            # scene already at the chosen version
STATUS_UPDATE = "update"    # Create moves it to the chosen version
STATUS_NEW = "new"          # not in the scene yet
STATUS_PINNED = "pinned"    # held at a version by hand
STATUS_MISSING = "missing"  # not in the export the geometry comes from


@dataclass
class PainterExport:
    version: str   # "v008", from the file name
    usd_path: str


@dataclass
class MaterialRecord:
    version: str             # "" when it was left out before ever being built
    pinned: bool = False
    left_out: bool = False   # unticked in the Version manager: stays off next time


@dataclass
class MaterialPlan:
    """One material of an asset in the Version manager: what exists, what the scene has, what to build."""
    name: str
    versions: list[str]          # exports that have this material, oldest first
    scene: str | None = None     # version built in the scene, None when not built yet
    chosen: str = ""
    pinned: bool = False
    scene_pinned: bool = False
    enabled: bool = True
    scene_left_out: bool = False


def version_number(version: str) -> int:
    m = re.search(r"(\d+)", version or "")
    return int(m.group(1)) if m else -1


def version_from_path(path: str) -> str | None:
    """Export version in a path (folder or file name): the last _vNNN, e.g. …_v008_full_textures -> v008."""
    matches = _PATH_VERSION_RE.findall(path.replace("%(UDIM)d", "").replace("<UDIM>", ""))
    return f"v{matches[-1]}" if matches else None


def asset_from_path(path: str) -> tuple[str, str] | None:
    """(group, asset) from …/01_assets/<group>/<asset>/…, the Monos project layout; None elsewhere."""
    parts = Path(path.replace("\\", "/")).parts
    for i, name in enumerate(parts):
        if name.casefold() == "01_assets" and i + 2 < len(parts):
            return parts[i + 1], parts[i + 2]
    return None


def asset_kind(group: str | None) -> str:
    """character / environment / prop from the asset group folder (_characters, _environments, _props)."""
    g = (group or "").lower()
    if "char" in g:
        return "character"
    if "env" in g or "set" in g:
        return "environment"
    return "prop"


def painter_publish_root(usd_path: str) -> Path:
    """The publish folder an export sits in: above its vNNN folder when there is one."""
    parent = Path(usd_path).parent
    return parent.parent if _VERSION_DIR_RE.match(parent.name) else parent


def list_painter_exports(usd_path: str) -> list[PainterExport]:
    """
    Every export of the same family as *usd_path* (same name without its _vNNN), in the publish
    folder and its vNNN children, oldest first. *usd_path* itself is always in the list.
    """
    root = painter_publish_root(usd_path)
    folders = [root] + sorted(
        (p for p in root.iterdir() if p.is_dir() and _VERSION_DIR_RE.match(p.name)),
        key=lambda p: version_number(p.name),
    ) if root.is_dir() else []
    found: dict[str, str] = {}
    for folder in folders:
        for p in folder.iterdir():
            if (
                p.is_file()
                and p.suffix.lower() in USD_EXTENSIONS
                and ".material." not in p.name.lower()
                and same_family(str(p), usd_path)
            ):
                version = version_from_path(p.name)
                if version:
                    found[version] = str(p).replace("\\", "/")  # a later publish folder wins
    own = version_from_path(Path(usd_path).name) or "v000"
    found.setdefault(own, str(usd_path).replace("\\", "/"))
    return [PainterExport(v, found[v]) for v in sorted(found, key=version_number)]


def plan_materials(
    exports: dict[str, dict[str, MaterialGroup]],
    scene: dict[str, MaterialRecord],
) -> list[MaterialPlan]:
    """
    One plan per material found in any export (version -> material groups). The chosen version is
    the latest export that has the material, unless the scene pins it to one that still exists.
    The latest export's materials come first, by name; older-only materials after them.
    """
    order = sorted(exports, key=version_number)
    latest = order[-1] if order else ""
    names = sorted(exports.get(latest, {})) + sorted(
        {n for v in order for n in exports[v]} - set(exports.get(latest, {}))
    )
    plans: list[MaterialPlan] = []
    for name in names:
        versions = [v for v in order if name in exports[v]]
        record = scene.get(name)
        plan = MaterialPlan(name=name, versions=versions, chosen=versions[-1])
        if record is not None:
            plan.scene = record.version or None
            if record.pinned and record.version in versions:
                plan.pinned = plan.scene_pinned = True
                plan.chosen = record.version
            if record.left_out:
                plan.enabled = False
                plan.scene_left_out = True
        plans.append(plan)
    return plans


def material_status(plan: MaterialPlan, geometry_materials: set[str] | frozenset[str]) -> str:
    """Chip of a material: see the STATUS_* constants. geometry_materials: the geometry export's."""
    if plan.name not in geometry_materials:
        return STATUS_MISSING
    if plan.pinned:
        return STATUS_PINNED
    if plan.scene is None:
        return STATUS_NEW
    return STATUS_OK if plan.scene == plan.chosen else STATUS_UPDATE


def plan_changes(plan: MaterialPlan) -> bool:
    """Whether Create has something to do: build, switch version, or save a pin or a tick."""
    if (not plan.enabled) != plan.scene_left_out:
        return True
    return plan.enabled and (
        plan.scene is None or plan.scene != plan.chosen or plan.pinned != plan.scene_pinned
    )


def to_latest(plans: list[MaterialPlan]) -> None:
    """All to latest: every unpinned material to the newest export that has it."""
    for plan in plans:
        if not plan.pinned:
            plan.chosen = plan.versions[-1]


def plan_summary(plans: list[MaterialPlan]) -> dict[str, int]:
    """
    Counts for the footer: new, update (incl. pin changes), unchanged, left out, and choices to save
    (a tick changed with nothing to build).
    """
    out = {"new": 0, "update": 0, "unchanged": 0, "left_out": 0, "save": 0}
    for plan in plans:
        if not plan.enabled:
            out["left_out"] += 1
            out["save"] += plan_changes(plan)
        elif plan.scene is None:
            out["new"] += 1
        elif plan_changes(plan):
            out["update"] += 1
        else:
            out["unchanged"] += 1
    return out


DEFAULT_LIBRARY = "materiallibrary1"
NEW_LIBRARY_SUFFIX = "_materials"


def texture_version(path: str) -> tuple[str | None, str | None]:
    """
    (publish folder, version) of a texture: …/publish/v006/textures/x.png -> (…/publish, "v006").
    Outside a Monos publish there is no publish folder; the version is the name's _vNNN, if any.
    """
    parts = Path(path.replace("\\", "/")).parts
    for i in range(len(parts) - 2, 0, -1):
        if _VERSION_DIR_RE.match(parts[i]):
            return Path(*parts[:i]).as_posix(), parts[i].lower()
    return None, version_from_path(path)


def group_version(group: MaterialGroup) -> str:
    """Version of a scanned material: its oldest map's, "" when no map has one."""
    versions = [v for v in (texture_version(s.filepath)[1] for s in group.slots.values()) if v]
    return min(versions, key=version_number) if versions else ""


@dataclass
class FolderLibrary:
    """A Material Library the tool built from texture folders, read back from its image nodes."""
    name: str
    path: str
    publish: str | None                       # publish folder most of its textures come from
    versions: dict[str, str]                  # material -> oldest texture version ("" unknown)

    @property
    def version(self) -> str:
        known = [v for v in self.versions.values() if v]
        return min(known, key=version_number) if known else ""


def folder_library(name: str, path: str, files: dict[str, list[str]]) -> FolderLibrary | None:
    """*files*: material -> texture paths the tool set. None when no material has one."""
    versions: dict[str, str] = {}
    publishes: dict[str, int] = {}
    for material, paths in files.items():
        if not paths:
            continue
        found = [texture_version(p) for p in paths]
        known = [v for _p, v in found if v]
        versions[material] = min(known, key=version_number) if known else ""
        for publish, _v in found:
            if publish:
                publishes[publish] = publishes.get(publish, 0) + 1
    if not versions:
        return None
    publish = max(publishes, key=publishes.get) if publishes else None
    return FolderLibrary(name, path, publish, versions)


def new_library_name(folder: str) -> str:
    """Name for a new library: {asset}_materials for a Monos asset, else materiallibrary1."""
    found = asset_from_path(folder)
    return found[1] + NEW_LIBRARY_SUFFIX if found else DEFAULT_LIBRARY


def pick_library(
    libraries: dict[str, dict[str, str]], names: list[str], selected: str | None = None, new_name: str = DEFAULT_LIBRARY,
) -> tuple[str, str]:
    """
    Material Library a texture folder goes into, and why: ("selection") the library selected in the
    scene, ("holds") the one already holding the most of *names* (so they update, not get a second
    copy), else ("new") *new_name*. *libraries*: name -> {material: version}, in network order.
    """
    if selected and selected in libraries:
        return selected, "selection"
    wanted = set(names)
    best, hits = None, 0
    for lib, materials in libraries.items():
        n = len(wanted & set(materials))
        if n > hits:
            best, hits = lib, n
    if best is not None:
        return best, "holds"
    return new_name, "new"


def folder_status(scene_version: str | None, version: str) -> str:
    """Chip status of a scanned material against a library: None = not in it."""
    if scene_version is None:
        return STATUS_NEW
    if scene_version and version and version_number(scene_version) >= version_number(version):
        return STATUS_OK
    return STATUS_UPDATE


def merge_node_versions(records: dict[str, MaterialRecord], versions: dict[str, str]) -> dict[str, MaterialRecord]:
    """
    The record with each material's version as its nodes have it: a material pasted or changed by
    hand (v008 into a v010 library) shows what the scene really has. Pins and left-out stay.
    *versions*: material -> version read from its image files ("" = cannot tell, record kept).
    """
    out = dict(records)
    for name, version in versions.items():
        if not version:
            continue
        old = out.get(name)
        if old is None:
            out[name] = MaterialRecord(version)
        elif old.version != version:
            out[name] = MaterialRecord(version, old.pinned, old.left_out)
    return out


def oldest_version(records: dict[str, MaterialRecord]) -> str:
    known = [r.version for r in records.values() if r.version and not r.left_out]
    return min(known, key=version_number) if known else ""


RECORD_KEY = "monofx_substance"


def dump_record(
    asset: tuple[str, str] | None,
    export: PainterExport,
    materials: dict[str, MaterialRecord],
) -> str:
    """What the scene remembers on the asset's Material Library (JSON in its user data)."""
    group, name = asset or ("", "")
    return json.dumps({
        "asset": name,
        "group": group,
        "export": export.usd_path,
        "version": export.version,
        "materials": {
            k: {"version": r.version, "pinned": r.pinned, **({"left_out": True} if r.left_out else {})}
            for k, r in sorted(materials.items())
        },
    }, indent=1)


def parse_record(text: str | None) -> tuple[dict, dict[str, MaterialRecord]]:
    """(asset/export fields, material records) from dump_record's JSON; empty when missing or broken."""
    try:
        data = json.loads(text or "")
        mats = data.get("materials", {})
        records = {
            str(k): MaterialRecord(str(v.get("version", "")), bool(v.get("pinned", False)),
                                   bool(v.get("left_out", False)))
            for k, v in mats.items() if isinstance(v, dict)
        }
        return {k: data.get(k) for k in ("asset", "group", "export", "version")}, records
    except (ValueError, AttributeError, TypeError):
        return {}, {}
