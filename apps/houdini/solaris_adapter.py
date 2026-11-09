"""
Thin Houdini Solaris/LOP adapter — only place that imports hou for LOP operations.

Tool controllers use this to create Karma materials in Solaris.
Core and logic must never import hou.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

try:
    import hou
except ImportError:
    hou = None  # type: ignore[assignment]

from tools.fx.auto_material.config import (
    NORMAL_MAP_SLOTS,
    PUBLISH_TEXTURE_RELATIVE_PATH,
    SLOT_DEF_MAP,
    SURFACE_INPUT_MAP,
)


def is_available() -> bool:
    return hou is not None


def _place_new(node: Any) -> None:
    """Find a free spot for a new node without moving the nodes already there (Houdini's default does)."""
    node.moveToGoodPosition(move_inputs=False, move_outputs=False, move_unconnected=False)


@contextmanager
def manual_update() -> Iterator[None]:
    """
    Houdini updates set to Manual for the block, then put back. While a Material Library cooks
    on changes, each node created in it re-translates every material in the library, so building
    16 materials took ~110 s instead of ~1 s (Houdini 22.0).
    """
    if hou is None:
        yield
        return
    old = hou.updateModeSetting()
    hou.setUpdateMode(hou.updateMode.Manual)
    try:
        yield
    finally:
        hou.setUpdateMode(old)


@contextmanager
def undo_group(label: str) -> Iterator[None]:
    """Everything done in the block is one undo step (one Ctrl+Z takes back a whole Create)."""
    if hou is None:
        yield
        return
    with hou.undos.group(label):
        yield


# ---------------------------------------------------------------------------
# HIP / Publish path
# ---------------------------------------------------------------------------

def get_hip_dir() -> str | None:
    if not is_available():
        return None
    try:
        hip = hou.hipFile.path()
        if hip:
            return str(Path(hip).parent)
    except Exception:
        pass
    return None


def resolve_publish_texture_folder() -> str | None:
    hip_dir = get_hip_dir()
    if hip_dir is None:
        return None
    publish = Path(hip_dir) / PUBLISH_TEXTURE_RELATIVE_PATH
    resolved = publish.resolve()
    return str(resolved) if resolved.is_dir() else None


# ---------------------------------------------------------------------------
# LOP context
# ---------------------------------------------------------------------------

def is_lop_context_available() -> bool:
    if not is_available():
        return False
    try:
        return hou.node("/stage") is not None
    except Exception:
        return False


def get_selected_lop_node() -> Any:
    """Return the first selected LOP node, or None."""
    if not is_available():
        return None
    try:
        for n in hou.selectedNodes():
            if n.type().category() == hou.lopNodeTypeCategory():
                return n
    except Exception:
        pass
    return None


def get_stage_context() -> Any:
    """Return the /stage network (parent for creating LOP nodes)."""
    if not is_available():
        return None
    try:
        return hou.node("/stage")
    except Exception:
        return None


def get_main_qt_window() -> Any:
    if not is_available():
        return None
    try:
        return hou.ui.mainQtWindow()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Material Library
# ---------------------------------------------------------------------------

def get_or_create_material_library(
    parent: Any,
    name: str = "materiallibrary1",
    connect_after: Any = None,
) -> Any:
    """
    Find or create a Material Library LOP inside parent.
    connect_after: if provided (a LOP node), place the new Material Library
    after that node (set input and position below it).
    """
    if parent is None:
        return None
    try:
        existing = parent.node(name)
        if existing is not None:
            return existing
        node = parent.createNode("materiallibrary", node_name=name)
        if connect_after is not None:
            node.setInput(0, connect_after)
            pos = connect_after.position()
            node.setPosition((pos[0], pos[1] - 1.5))
        else:
            _place_new(node)
        return node
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Karma Material Builder
# ---------------------------------------------------------------------------

def create_karma_material_builder(mat_lib: Any, name: str) -> Any:
    """
    Create a Karma Material Builder subnet inside a Material Library LOP.
    Uses voptoolutils when available (H20+), falls back to manual subnet creation.
    """
    if mat_lib is None:
        return None
    try:
        import voptoolutils
        mask = voptoolutils.KARMAMTLX_TAB_MASK
        builder = voptoolutils._setupMtlXBuilderSubnet(
            destination_node=mat_lib,
            name=name,
            mask=mask,
            folder_label="Karma Material Builder",
        )
        return builder
    except Exception:
        pass

    try:
        builder = mat_lib.createNode("subnet", node_name=name)
        _place_new(builder)
        return builder
    except Exception:
        return None


# ---------------------------------------------------------------------------
# VOP nodes inside Karma Material Builder
# ---------------------------------------------------------------------------

def get_or_create_mtlx_standard_surface(builder: Any) -> Any:
    """Find existing mtlxstandard_surface inside builder, or create one if missing."""
    if builder is None:
        return None
    try:
        for child in builder.children():
            if child.type().name() == "mtlxstandard_surface":
                return child
        node = builder.createNode("mtlxstandard_surface", node_name="mtlxstandard_surface")
        _place_new(node)
        return node
    except Exception:
        return None


_SIGNATURE_MENU_MAP: dict[str, str] = {
    "color3": "default",
    "float": "float",
    "vector3": "vector3",
    "vector2": "vector2",
}

# filecolorspace parm: menu token -> label (as in Houdini mtlximage)
FILE_COLORSPACE_MENU: list[tuple[str, str]] = [
    ("srgb_texture", "sRGB - Texture"),
    ("srgb_tx", "sRGB - Texture (tx)"),
    ("srgb_displayp3", "sRGB DisplayP3"),
    ("ACEScg", "ACEScg"),
    ("acescg", "acescg (lin_ap1)"),
    ("lin_rec709", "Linear Rec.709 (sRGB)"),
    ("lin_displayp3", "Linear DisplayP3"),
    ("g22_ap1", "G22 AP1"),
    ("g22_rec709", "G22 Rec.709"),
    ("g18_rec709", "G18 Rec.709"),
    ("rec709_display", "Rec.709 Display"),
    ("Raw", "Raw"),
]

# Map pipeline/detected colorspace string -> filecolorspace token
_COLORSPACE_TO_TOKEN: dict[str, str] = {
    "srgb": "srgb_texture",
    "srgb texture": "srgb_texture",
    "srgb - texture": "srgb_texture",
    "raw": "Raw",
    "utility - raw": "Raw",
    "utility raw": "Raw",
    "utility-raw": "Raw",
    "acescg": "ACEScg",
    "aces - acescg": "ACEScg",
    "aces acescg": "ACEScg",
    "lin_ap1": "acescg",
    # Monos Painter publishes write "Linear" for float colour maps without OCIO (linear sRGB primaries).
    "linear": "lin_rec709",
    "scene_linear": "lin_rec709",
    "linear rec.709": "lin_rec709",
    "lin rec709": "lin_rec709",
    "linear displayp3": "lin_displayp3",
    "lin displayp3": "lin_displayp3",
    "g22 ap1": "g22_ap1",
    "g22 rec709": "g22_rec709",
    "g18 rec709": "g18_rec709",
    "rec709 display": "rec709_display",
    "srgb displayp3": "srgb_displayp3",
}


def _resolve_filecolorspace_token(colorspace: str | None) -> str | None:
    """Resolve pipeline/detected colorspace string to filecolorspace menu token."""
    if not colorspace or not colorspace.strip():
        return None
    key = colorspace.strip().lower().replace("-", " ").replace("  ", " ").strip()
    if key in _COLORSPACE_TO_TOKEN:
        return _COLORSPACE_TO_TOKEN[key]
    key_compact = key.replace(" ", "")
    for k, token in _COLORSPACE_TO_TOKEN.items():
        if k.replace(" ", "") == key_compact:
            return token
    tokens_lower = {t[0].lower(): t[0] for t in FILE_COLORSPACE_MENU}
    if key in tokens_lower:
        return tokens_lower[key]
    return None


def colorspace_token_for_slot(slot: str, colorspace: str | None) -> str:
    """
    filecolorspace token for a texture: the colour space its file name says (Monos writes the
    space Painter really exported: sRGB, Linear, ACEScg, Raw), else the slot's default.
    """
    token = _resolve_filecolorspace_token(colorspace)
    slot_def = SLOT_DEF_MAP.get(slot)
    if not token and slot_def:
        token = _resolve_filecolorspace_token(slot_def.default_colorspace)
    return token or "Raw"


def _set_filecolorspace_parm(node: Any, token: str) -> bool:
    """Set filecolorspace on mtlximage node. Tries common parm names and menu index."""
    if node is None or not token:
        return False

    def try_set(pname: str) -> bool:
        parm = node.parm(pname)
        if parm is None:
            return False
        try:
            node.setParms({pname: token})
            return True
        except Exception:
            pass
        try:
            parm.set(token)
            return True
        except Exception:
            pass
        try:
            menu_items = parm.menuItems()
            if menu_items:
                if token in menu_items:
                    parm.set(menu_items.index(token))
                    return True
                for i, item in enumerate(menu_items):
                    if isinstance(item, tuple) and item[0] == token:
                        parm.set(i)
                        return True
                    if item == token:
                        parm.set(i)
                        return True
        except Exception:
            pass
        return False

    for parm_name in ("filecolorspace", "fileColorSpace", "colorspace", "file_colorspace", "color_space"):
        if try_set(parm_name):
            return True
    try:
        for parm in node.parms():
            name = parm.name().lower()
            if "color" in name and "space" in name and try_set(parm.name()):
                return True
    except Exception:
        pass
    return False


def create_mtlx_image(
    builder: Any,
    slot: str,
    filepath: str,
    colorspace: str | None = None,
    udim: bool = False,
) -> Any:
    if builder is None:
        return None
    try:
        slot_def = SLOT_DEF_MAP.get(slot)
        sig = slot_def.signature if slot_def else "color3"

        node = builder.createNode("mtlximage", node_name=f"tex_{slot}")
        _place_new(node)

        file_parm = node.parm("file")
        if file_parm:
            file_parm.set(filepath)

        sig_parm = node.parm("signature")
        if sig_parm and sig != "color3":
            menu_val = _SIGNATURE_MENU_MAP.get(sig, sig)
            sig_parm.set(menu_val)

        token = colorspace_token_for_slot(slot, colorspace)
        _set_filecolorspace_parm(node, token)
        _tag_image(node, slot, filepath, _get_filecolorspace(node) or token)

        return node
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Update: image nodes remember what the tool set (user data), so a later run
# changes only what the user has not changed by hand.
# ---------------------------------------------------------------------------

SLOT_TAG = "monofx_slot"
FILE_TAG = "monofx_file"
COLORSPACE_TAG = "monofx_colorspace"

_COLORSPACE_PARM_NAMES = ("filecolorspace", "fileColorSpace", "colorspace", "file_colorspace", "color_space")


def _get_filecolorspace(node: Any) -> str | None:
    for name in _COLORSPACE_PARM_NAMES:
        parm = node.parm(name)
        if parm is not None:
            try:
                return parm.evalAsString()
            except Exception:
                return None
    return None


def _user_data(node: Any, key: str) -> str | None:
    try:
        return node.userData(key)
    except Exception:
        return None


def _tag_image(node: Any, slot: str, filepath: str, token: str | None) -> None:
    try:
        node.setUserData(SLOT_TAG, slot)
        node.setUserData(FILE_TAG, filepath)
        if token:
            node.setUserData(COLORSPACE_TAG, token)
    except Exception:
        pass


def _wired_image(builder: Any, slot: str) -> Any:
    """
    The untagged mtlximage feeding the surface input of *slot* (directly, or through a normal map):
    how a material built by another tool (e.g. SideFX's Painter-to-Karma) is updated in place.
    """
    surface = _find_surface(builder)
    input_name = SURFACE_INPUT_MAP.get(slot)
    if surface is None or input_name is None:
        return None
    try:
        idx = surface.inputIndex(input_name)
        node = surface.input(idx) if idx >= 0 else None
        for _hop in range(3):
            if node is None:
                return None
            if node.type().name() == "mtlximage":
                return None if _user_data(node, SLOT_TAG) else node
            node = node.input(0)
    except Exception:
        return None
    return None


def find_image_node(builder: Any, slot: str) -> Any:
    """
    The image node for *slot*: tagged by the tool's user data, else (older builds) named tex_<slot>,
    else (another tool's material) the untagged image wired into the slot's surface input.
    """
    legacy = None
    for child in builder.children():
        if _user_data(child, SLOT_TAG) == slot:
            return child
        if legacy is None and child.name() == f"tex_{slot}" and child.type().name() == "mtlximage":
            legacy = child
    return legacy if legacy is not None else _wired_image(builder, slot)


def _image_slots(builder: Any) -> dict[str, Any]:
    """slot -> image node for every image node the tool made in *builder*, or another tool wired in."""
    out: dict[str, Any] = {}
    for child in builder.children():
        slot = _user_data(child, SLOT_TAG)
        if not slot and child.name().startswith("tex_") and child.type().name() == "mtlximage":
            slot = child.name()[4:]
        if slot in SLOT_DEF_MAP and slot not in out:
            out[slot] = child
    if _find_surface(builder) is not None:
        for slot in SURFACE_INPUT_MAP:
            if slot not in out:
                img = _wired_image(builder, slot)
                if img is not None and img not in out.values():
                    out[slot] = img
    return out


def update_mtlx_image(node: Any, slot: str, filepath: str, colorspace: str | None, notes: list[str]) -> None:
    """
    Point an existing image node at the new publish. The file and colour space change only
    while they are still what the tool set last time; a value the user changed is kept.
    """
    file_parm = node.parm("file")
    current_file = file_parm.unexpandedString() if file_parm is not None else ""
    recorded_file = _user_data(node, FILE_TAG)
    if file_parm is not None and (recorded_file is None or current_file == recorded_file):
        if current_file != filepath:
            file_parm.set(filepath)
        new_file = filepath
    else:
        new_file = recorded_file or filepath
        notes.append(f"{slot}: kept the file set by hand ({current_file})")

    token = colorspace_token_for_slot(slot, colorspace)
    current_cs = _get_filecolorspace(node)
    recorded_cs = _user_data(node, COLORSPACE_TAG)
    if recorded_cs is None:
        # Built before the tool tagged its nodes: the space it would have set for the old file.
        from tools.fx.auto_material.logic import try_pipeline_parse

        old = try_pipeline_parse(current_file) if current_file else None
        recorded_cs = colorspace_token_for_slot(slot, old.colorspace if old else None)
    if current_cs is None or current_cs in (recorded_cs, token):
        if current_cs != token:
            _set_filecolorspace_parm(node, token)
        new_cs = token
    else:
        new_cs = recorded_cs
        notes.append(f"{slot}: kept the colour space set by hand ({current_cs})")

    _tag_image(node, slot, new_file, new_cs)


def _find_surface(builder: Any) -> Any:
    for child in builder.children():
        if child.type().name() == "mtlxstandard_surface":
            return child
    return None


def _input_is_free(node: Any, input_name: str) -> bool:
    idx = node.inputIndex(input_name)
    return idx >= 0 and node.input(idx) is None


def _set_value_note(node: Any, input_name: str) -> str | None:
    """'base_color: the map replaces the value (0.3, ...)' when the input's parm was set by hand."""
    try:
        pt = node.parmTuple(input_name)
        if pt is not None and not pt.isAtDefault():
            values = ", ".join(f"{v:g}" if isinstance(v, float) else str(v) for v in pt.eval())
            return f"{input_name}: the map replaces the value ({values})"
    except Exception:
        pass
    return None


# Lobes whose maps show nothing while the lobe's weight is 0: weight slot -> (weight map name, label, other slots).
_LOBE_WEIGHTS: dict[str, tuple[str, str, frozenset[str]]] = {
    "subsurface": ("SubsurfaceWeight", "SSS", frozenset({"subsurface_color", "subsurface_radius"})),
    "coat": ("CoatWeight", "the coat", frozenset({"coat_color", "coat_roughness", "coat_anisotropy", "coat_normal"})),
}


# Lobes whose weight is set to 1 when their maps come without a weight map (a 0 weight hides them).
_AUTO_WEIGHTS: dict[str, frozenset[str]] = {
    "subsurface": frozenset({"subsurface_color", "subsurface_radius"}),
    "emission": frozenset({"emission_color"}),
}


def _weight_notes(surface: Any, slots: dict) -> list[str]:
    """
    SSS and emission maps without a weight map: their weight is set to 1, while it is free and 0.
    Other lobes (coat) are reported instead: their maps show nothing while the weight is 0.
    """
    notes: list[str] = []
    for weight, others in _AUTO_WEIGHTS.items():
        if weight in slots or not (others & set(slots)):
            continue
        try:
            parm = surface.parm(weight) if surface is not None and _input_is_free(surface, weight) else None
            if parm is not None and parm.eval() == 0:
                parm.set(1.0)
                notes.append(f"{weight}: set to 1, its maps came without a weight map")
        except Exception:
            continue
    for weight, (map_name, label, others) in _LOBE_WEIGHTS.items():
        if weight in _AUTO_WEIGHTS:
            continue
        if weight in slots or not (others & set(slots)):
            continue
        try:
            if surface is None or not _input_is_free(surface, weight):
                continue
            parm = surface.parm(weight)
            if parm is not None and parm.eval() > 0:
                continue
        except Exception:
            continue
        notes.append(f"{weight}: no {map_name} map and {weight} is 0, so {label} does not show; set it on the surface")
    return notes


def update_material(builder: Any, slots: dict, notes: list[str]) -> None:
    """
    Update a material built earlier, keeping the user's edits: image nodes get the new files,
    new maps get an image node wired only into a free surface input, and nothing is deleted
    or re-wired.
    """
    surface = _find_surface(builder)
    existing = _image_slots(builder)

    for slot_name, slot_info in slots.items():
        img = find_image_node(builder, slot_name)
        if img is not None:
            update_mtlx_image(img, slot_name, slot_info.filepath, slot_info.colorspace, notes)
            continue

        img = create_mtlx_image(
            builder,
            slot=slot_name,
            filepath=slot_info.filepath,
            colorspace=slot_info.colorspace,
            udim=slot_info.udim,
        )
        if img is None:
            notes.append(f"{slot_name}: could not create the image node")
            continue

        input_name = SURFACE_INPUT_MAP.get(slot_name)
        if input_name is None:
            notes.append(f"{slot_name}: new map, image node added (no surface input to wire)")
        elif surface is None:
            notes.append(f"{slot_name}: new map, image node added, not wired (no mtlxstandard_surface)")
        elif not _input_is_free(surface, input_name):
            notes.append(f"{slot_name}: new map, image node added, not wired ({input_name} is already connected)")
        else:
            value_note = _set_value_note(surface, input_name)
            nrm = create_mtlx_normal_map(builder, slot_name) if slot_name in NORMAL_MAP_SLOTS else None
            connect_slot(surface, img, slot_name, normal_map_node=nrm)
            notes.append(f"{slot_name}: new map, wired to {input_name}")
            if value_note:
                notes.append(value_note)

    for slot_name in sorted(set(existing) - set(slots)):
        notes.append(f"{slot_name}: not in this publish, node kept")

    notes += _weight_notes(surface, slots)


def create_mtlx_normal_map(builder: Any, slot: str = "normal") -> Any:
    if builder is None:
        return None
    try:
        name = "mtlxnormalmap" if slot == "normal" else f"mtlxnormalmap_{slot}"
        node = builder.createNode("mtlxnormalmap", node_name=name)
        _place_new(node)
        return node
    except Exception:
        return None


def connect_slot(
    surface_node: Any,
    image_node: Any,
    slot: str,
    normal_map_node: Any = None,
) -> bool:
    """Connect image VOP output to surface VOP input by name."""
    if surface_node is None or image_node is None:
        return False
    try:
        input_name = SURFACE_INPUT_MAP.get(slot)
        if input_name is None:
            return False

        if slot in NORMAL_MAP_SLOTS and normal_map_node is not None:
            normal_map_node.setNamedInput("in", image_node, "out")
            surface_node.setNamedInput(input_name, normal_map_node, "out")
        else:
            surface_node.setNamedInput(input_name, image_node, "out")
        return True
    except Exception:
        return False


def _ensure_surface_connected_to_output(builder: Any, surface_node: Any) -> None:
    """
    Ensure surface is wired to the builder's output structure.
    If builder was created by voptoolutils, surface is already connected
    to a Collect/Material_Outputs node — skip in that case.
    Only wire manually if surface has no output connections.
    """
    if builder is None or surface_node is None:
        return
    try:
        if surface_node.outputs():
            return

        for child in builder.children():
            type_name = child.type().name()
            if type_name in ("collect", "material_builder_outputs"):
                child.setNextInput(surface_node)
                return

        collect = builder.createNode("collect", node_name="collect")
        collect.setNextInput(surface_node)
        _place_new(collect)

        for child in builder.children():
            if child.type().name() == "suboutput":
                child.setInput(0, collect, 0)
                break
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Assign Material
# ---------------------------------------------------------------------------

def create_assign_material(
    parent: Any,
    material_path: str,
    prim_pattern: str,
    connect_after: Any = None,
    node_name: str = "assign_material",
) -> Any:
    if parent is None:
        return None
    try:
        node = parent.createNode("assignmaterial", node_name=node_name)
        node.parm("primpattern1").set(prim_pattern)
        node.parm("matspecpath1").set(material_path)
        if connect_after is not None:
            node.setInput(0, connect_after)
            pos = connect_after.position()
            node.setPosition((pos[0], pos[1] - 1.5))
        else:
            _place_new(node)
        return node
    except Exception:
        return None


def _assign_count_parm(node: Any) -> Any:
    # Multiparm count (Houdini uses "Number of Materials"); the name varies across versions.
    return (
        node.parm("nummaterials")
        or node.parm("num_materials")
        or node.parm("num_mats")
        or node.parm("numassignments")
    )


def _set_assign_count(node: Any, count: int) -> None:
    count_parm = _assign_count_parm(node)
    if count_parm is not None:
        count_parm.set(count)


def _set_assign_entry(node: Any, i: int, prim_pattern: str, material_path: str) -> None:
    pp = node.parm(f"primpattern{i}")
    mp = node.parm(f"matspecpath{i}")
    if pp is not None:
        pp.set(prim_pattern)
    if mp is not None:
        mp.set(material_path)

    # Force explicit path mode when such a parm exists on this build
    # (parm names vary slightly across versions).
    for candidate in (f"specifymat{i}", f"specifymaterial{i}", f"specifymatusing{i}"):
        p = node.parm(candidate)
        if p is not None:
            try:
                p.set(0)
            except Exception:
                pass
            break


def merge_assign_material(node: Any, assignments: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    Add to an existing Assign Material LOP the (prim_pattern, material_path) pairs whose prim
    pattern it does not list yet. Entries already there, edited by hand or not, are kept.
    Returns the pairs added.
    """
    count_parm = _assign_count_parm(node)
    if count_parm is None:
        return []
    count = int(count_parm.eval())
    listed = set()
    for i in range(1, count + 1):
        pp = node.parm(f"primpattern{i}")
        if pp is not None:
            listed.add(pp.unexpandedString().strip())
    added = [(prim, mat) for prim, mat in assignments if prim not in listed]
    if added:
        count_parm.set(count + len(added))
        for i, (prim, mat) in enumerate(added, count + 1):
            _set_assign_entry(node, i, prim, mat)
    return added


def create_assign_material_bulk(
    parent: Any,
    assignments: list[tuple[str, str]],
    connect_after: Any = None,
    node_name: str = "assign_material_auto",
) -> Any:
    """
    Create a single Assign Material LOP and fill multiple assignments.
    assignments: list of (prim_pattern, material_path).
    """
    if parent is None:
        return None
    if not assignments:
        return None
    try:
        node = parent.createNode("assignmaterial", node_name=node_name)

        # Connect and position
        if connect_after is not None:
            node.setInput(0, connect_after)
            pos = connect_after.position()
            node.setPosition((pos[0], pos[1] - 1.5))
        else:
            _place_new(node)

        _set_assign_count(node, len(assignments))
        for i, (prim_pattern, material_path) in enumerate(assignments, 1):
            _set_assign_entry(node, i, prim_pattern, material_path)

        return node
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Auto assign: match *_grp / *_Grp prims with M_char_* materials
# ---------------------------------------------------------------------------

MATERIALS_SCOPE = "/materials"
M_CHAR_PREFIX = "M_char_"
GRP_SUFFIX_LOWER = "_grp"
GRP_SUFFIX_MIXED = "_Grp"


def get_stage_from_lop_node(lop_node: Any) -> Any:
    """Return the USD stage from the given LOP node, or None."""
    if not is_available() or lop_node is None:
        return None
    try:
        if lop_node.type().category() != hou.lopNodeTypeCategory():
            return None
        return lop_node.stage()
    except Exception:
        return None


def find_grp_prim_paths_and_names(stage: Any) -> list[tuple[str, str]]:
    """
    Traverse stage and collect prims whose name ends with _grp or _Grp.
    Returns list of (prim_path, base_name) where base_name is the name without suffix.
    """
    if stage is None:
        return []
    out: list[tuple[str, str]] = []
    try:
        for prim in stage.Traverse():
            name = prim.GetName()
            if name.endswith(GRP_SUFFIX_LOWER):
                base = name[: -len(GRP_SUFFIX_LOWER)]
                out.append((str(prim.GetPath()), base))
            elif name.endswith(GRP_SUFFIX_MIXED):
                base = name[: -len(GRP_SUFFIX_MIXED)]
                out.append((str(prim.GetPath()), base))
    except Exception:
        pass
    return out


def get_material_names_under_scope(
    stage: Any,
    scope_path: str = MATERIALS_SCOPE,
    material_prefix: str = M_CHAR_PREFIX,
) -> dict[str, str]:
    """
    List materials under scope (e.g. /materials) with names like M_char_<Name>.
    Returns dict: base_name -> material_prim_path (e.g. "Body" -> "/materials/M_char_Body").
    """
    if stage is None:
        return {}
    result: dict[str, str] = {}
    try:
        scope_prim = stage.GetPrimAtPath(scope_path)
        if not scope_prim or not scope_prim.IsValid():
            return {}
        prefix_len = len(material_prefix)
        for child in scope_prim.GetChildren():
            name = child.GetName()
            if name.startswith(material_prefix):
                base_name = name[prefix_len:]
                if base_name:
                    result[base_name] = f"{scope_path}/{name}"
    except Exception:
        pass
    return result


def run_auto_assign(
    stage_node: Any,
    selected_lop_node: Any,
) -> tuple[int, str]:
    """
    From selected LOP node's stage: find *_grp/*_Grp prims, match with
    M_char_* materials under /materials, create Assign Material LOPs.
    Matching is case-insensitive (Body_Grp matches M_char_Body or M_char_body).
    Returns (created_count, message).
    """
    if stage_node is None or selected_lop_node is None:
        return 0, "No stage or no LOP node selected."

    stage = get_stage_from_lop_node(selected_lop_node)
    if stage is None:
        return 0, "Could not get stage from selected node."

    grp_prims = find_grp_prim_paths_and_names(stage)
    materials = get_material_names_under_scope(stage)

    if not materials:
        return 0, "No M_char_* materials found under /materials. Create materials first or check scope path."

    # Case-insensitive lookup: lower(base_name) -> material_path
    materials_by_lower: dict[str, str] = {}
    for base_name, path in materials.items():
        materials_by_lower[base_name.lower()] = path

    matched: list[tuple[str, str]] = []
    for prim_path, base_name in grp_prims:
        material_path = materials.get(base_name) or materials_by_lower.get(base_name.lower())
        if material_path:
            matched.append((prim_path, material_path))

    # A run before made assign_material_auto: add the new prims to it instead of a second node.
    existing = stage_node.node("assign_material_auto")
    if matched and existing is not None and existing.type().name() == "assignmaterial":
        added = merge_assign_material(existing, matched)
        kept = len(matched) - len(added)
        return len(matched), (
            f"Updated {existing.name()}: added {len(added)} assignment(s), "
            f"kept {kept} already there."
        )

    # Prefer one Assign Material node with multiple entries
    if matched:
        bulk = create_assign_material_bulk(
            stage_node,
            assignments=matched,
            connect_after=selected_lop_node,
            node_name="assign_material_auto",
        )
        if bulk is not None:
            return len(matched), f"Assigned {len(matched)} material(s) via a single Assign Material LOP."

    # Fallback: chain nodes (older/odd builds where multiparm can't be set reliably)
    created = 0
    connect_after = selected_lop_node
    for prim_path, material_path in matched:
        node = create_assign_material(
            stage_node,
            material_path=material_path,
            prim_pattern=prim_path,
            connect_after=connect_after,
            node_name="assign_material_auto",
        )
        if node is not None:
            created += 1
            connect_after = node

    if created == 0:
        grp_names = sorted({b for _, b in grp_prims})
        mat_names = sorted(materials.keys())
        if len(grp_prims) == 0:
            return 0, (
                f"No prims named *_grp / *_Grp in this stage ({len(materials)} materials found under /materials). "
                "The selected node may output only materials. Select a LOP node that has both geometry and materials "
                "in its output (e.g. the Merge LOP that combines geometry + Material Library, or the final output node)."
            )
        detail = (
            f"Found {len(grp_prims)} _grp prim(s) ({', '.join(grp_names[:8])}{'…' if len(grp_names) > 8 else ''}) "
            f"and {len(materials)} material(s) ({', '.join(mat_names[:8])}{'…' if len(mat_names) > 8 else ''}). "
        )
        return 0, (
            detail + "No name match. Select a LOP node whose output includes both geometry and /materials (e.g. merge node)."
        )
    return created, f"Assigned {created} material(s) to matching _grp prims."


def create_assign_for_all_materials(
    stage_node: Any,
    selected_lop_node: Any,
    default_prim_pattern: str = "/world/geo/*",
) -> int:
    """
    Create one Assign Material LOP per M_char_* material with the given prim pattern.
    Used when no *_grp prims were found so user can assign manually later.
    Returns number of Assign Material LOPs created.
    """
    if stage_node is None or selected_lop_node is None:
        return 0
    stage = get_stage_from_lop_node(selected_lop_node)
    materials = get_material_names_under_scope(stage)
    if not materials:
        return 0
    created = 0
    connect_after = selected_lop_node
    for base_name, material_path in sorted(materials.items(), key=lambda kv: kv[0].lower()):
        safe_name = base_name.replace(" ", "_").replace("/", "_")
        node = create_assign_material(
            stage_node,
            material_path=material_path,
            prim_pattern=default_prim_pattern,
            connect_after=connect_after,
            node_name=f"assign_material_{safe_name}",
        )
        if node is not None:
            created += 1
            connect_after = node
    return created


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def layout_nodes(parent: Any) -> None:
    if parent is None:
        return
    try:
        parent.layoutChildren()
    except Exception:
        pass


def layout_material_library(mat_lib: Any, new_names: list[str] | None = None) -> None:
    """
    Arrange Karma Material Builder subnets inside the Material Library in a vertical stack,
    sorted by name. With *new_names*, only those builders are placed, below the ones already
    there, so builders the user has placed stay where they are.
    """
    if mat_lib is None:
        return
    try:
        children = list(mat_lib.children())
        if not children:
            return
        dx, dy = 0.0, -1.8
        if new_names is not None:
            new = sorted((n for n in children if n.name() in new_names), key=lambda n: n.name().lower())
            old = [n for n in children if n.name() not in new_names]
            if old:
                lowest = min(old, key=lambda n: n.position()[1]).position()
                for i, node in enumerate(new, 1):
                    node.setPosition((lowest[0] + dx * i, lowest[1] + dy * i))
                return
            children = new
        children.sort(key=lambda n: n.name().lower())
        base = children[0].position()
        for i, node in enumerate(children):
            node.setPosition((base[0] + dx * i, base[1] + dy * i))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# High-level: build full material from slot dict
# ---------------------------------------------------------------------------

class BuildResult:
    __slots__ = ("path", "node_name", "updated", "notes")

    def __init__(self, path: str, node_name: str, updated: bool, notes: list[str]) -> None:
        self.path = path
        self.node_name = node_name
        self.updated = updated
        self.notes = notes


def build_material(
    stage: Any,
    material_name: str,
    slots: dict,
    mat_lib_name: str = "materiallibrary1",
    selected_node: Any = None,
) -> BuildResult | None:
    """
    Create a complete Karma material from a slots dict, or update the one built earlier
    under the same name (see update_material: the user's edits are kept).
    slots: { slot_name: SlotInfo } from logic.py.
    selected_node: if provided, Material Library is created after this node.
    Returns the material USD path (e.g. /materials/costume) and what was done, or None on failure.
    """
    mat_lib = get_or_create_material_library(
        stage, name=mat_lib_name, connect_after=selected_node,
    )
    if mat_lib is None:
        return None

    notes: list[str] = []
    existing = mat_lib.node(material_name)
    if existing is not None:
        update_material(existing, slots, notes)
        return BuildResult(f"/materials/{existing.name()}", existing.name(), True, notes)

    builder = create_karma_material_builder(mat_lib, material_name)
    if builder is None:
        return None

    surface = get_or_create_mtlx_standard_surface(builder)
    if surface is None:
        return None

    for slot_name, slot_info in slots.items():
        img = create_mtlx_image(
            builder,
            slot=slot_name,
            filepath=slot_info.filepath,
            colorspace=slot_info.colorspace,
            udim=slot_info.udim,
        )
        if img is None:
            continue

        if slot_name in NORMAL_MAP_SLOTS:
            nrm = create_mtlx_normal_map(builder, slot_name)
            connect_slot(surface, img, slot_name, normal_map_node=nrm)
        elif slot_name in SURFACE_INPUT_MAP:
            connect_slot(surface, img, slot_name)

    _ensure_surface_connected_to_output(builder, surface)
    layout_nodes(builder)

    notes += _weight_notes(surface, slots)

    return BuildResult(f"/materials/{builder.name()}", builder.name(), False, notes)


# ---------------------------------------------------------------------------
# Substance Painter USD export: read it, load its geometry, bind its materials
# ---------------------------------------------------------------------------

def _texture_abs_path(attr: Any) -> str | None:
    """Absolute path of a Painter asset input. A <UDIM> path does not resolve, so it is anchored
    to the folder of the layer that authors it."""
    import os

    value = attr.Get()
    if not value:
        return None
    authored = getattr(value, "authoredPath", None) or value.path
    if not authored:
        return None
    path = value.resolvedPath
    if not path:
        path = authored
        if not os.path.isabs(authored):
            layer = attr.GetPropertyStack()[0].layer
            path = os.path.join(os.path.dirname(layer.realPath), authored)
    return os.path.normpath(path).replace("\\", "/")


def read_substance_usd(usd_path: str) -> tuple[list[str], list[Any], dict[str, list[str]]]:
    """
    Read a Painter USD export with pxr (opened on its own, not on a LOP stage).
    Returns (sublayers, materials, bindings): the root layer's sublayers as absolute paths,
    a logic.SubstanceMaterial per Material prim, and Material prim path -> prims bound to it.
    """
    import os

    from pxr import Usd, UsdShade

    from tools.fx.auto_material.config import SUBSTANCE_INPUT_TO_SLOT
    from tools.fx.auto_material.logic import SubstanceMaterial

    stage = Usd.Stage.Open(usd_path)
    if stage is None:
        raise RuntimeError(f"Cannot open USD: {usd_path}")

    root = stage.GetRootLayer()
    sublayers = [
        os.path.normpath(root.ComputeAbsolutePath(p)).replace("\\", "/") for p in root.subLayerPaths
    ]

    materials: list[SubstanceMaterial] = []
    bindings: dict[str, list[str]] = {}
    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Material):
            mat = UsdShade.Material(prim)
            textures: dict[str, str] = {}
            for usd_input in SUBSTANCE_INPUT_TO_SLOT:
                inp = mat.GetInput(usd_input)
                path = _texture_abs_path(inp.GetAttr()) if inp else None
                if path:
                    textures[usd_input] = path
            layers = [s.layer.realPath for s in prim.GetPrimStack() if s.layer.realPath]
            materials.append(SubstanceMaterial(prim.GetName(), str(prim.GetPath()), textures, layers))
            continue
        rel = UsdShade.MaterialBindingAPI(prim).GetDirectBindingRel()
        if rel:
            for target in rel.GetTargets():
                bindings.setdefault(str(target), []).append(str(prim.GetPath()))
    return sublayers, materials, bindings


def get_or_create_substance_sublayer(stage_node: Any, name: str, layers: list[str]) -> Any:
    """Sublayer LOP loading the export's geometry. A run before made it: its files are set again
    (a newer export may point at a newer geometry publish); the node is not moved."""
    if stage_node is None or not layers:
        return None
    try:
        node = stage_node.node(name)
        if node is None or node.type().name() != "sublayer":
            node = stage_node.createNode("sublayer", node_name=name)
            _place_new(node)
        if len(layers) == 1:
            from apps.houdini.lop_usd_helpers import configure_single_file_sublayer

            configure_single_file_sublayer(node, layers[0])
        else:
            node.parm("num_files").set(len(layers))
            for i, layer in enumerate(layers, 1):
                node.parm(f"filepath{i}").set(layer)
        return node
    except Exception:
        return None


def assign_substance_materials(
    stage_node: Any,
    mat_lib: Any,
    name: str,
    assignments: list[tuple[str, str]],
) -> tuple[Any, int]:
    """
    One Assign Material LOP after the Material Library with Painter's bindings. A run before made
    it: only prim patterns it does not list yet are added (see merge_assign_material).
    Returns (node, entries added).
    """
    if stage_node is None or not assignments:
        return None, 0
    existing = stage_node.node(name)
    if existing is not None and existing.type().name() == "assignmaterial":
        return existing, len(merge_assign_material(existing, assignments))
    node = create_assign_material_bulk(
        stage_node, assignments=assignments, connect_after=mat_lib, node_name=name,
    )
    if node is None:
        return None, 0
    node.setDisplayFlag(True)
    return node, len(assignments)


# ---------------------------------------------------------------------------
# Version manager: Painter exports per version, and what the scene remembers per asset
# ---------------------------------------------------------------------------

class ExportData:
    """One Painter export read from disk: its material groups and what Create needs from it."""
    __slots__ = ("export", "groups", "source")

    def __init__(self, export: Any, groups: dict, source: Any) -> None:
        self.export = export
        self.groups = groups
        self.source = source


def read_painter_exports(exports: list) -> dict[str, ExportData]:
    """version -> ExportData for each logic.PainterExport (each read with pxr, ~0.5 s)."""
    from tools.fx.auto_material.logic import substance_source

    out: dict[str, ExportData] = {}
    for export in exports:
        sublayers, materials, bindings = read_substance_usd(export.usd_path)
        groups, source = substance_source(export.usd_path, sublayers, materials, bindings)
        out[export.version] = ExportData(export, groups, source)
    return out


def _infer_record(mat_lib: Any) -> str | None:
    """
    Record for a library with none: built before the tool kept one, pasted, or made by another tool
    from a Painter export (SideFX's Painter-to-Karma). Each material's version is the _vNNN in the
    folder of its textures, and the export is the .usd next to that folder.
    """
    from tools.fx.auto_material.logic import (
        MaterialRecord,
        PainterExport,
        asset_from_path,
        dump_record,
        version_from_path,
        version_number,
    )

    materials: dict[str, Any] = {}
    export_path = ""
    for builder in mat_lib.children():
        files = _builder_files(builder)
        found = [v for v in (version_from_path(f) for f in files) if v]
        if not found:
            continue
        version = min(found, key=version_number)
        materials[builder.name()] = MaterialRecord(version)
        folder = Path(files[0]).parent
        candidate = folder.with_name(folder.name.removesuffix("_textures") + ".usd")
        newer = version_number(version_from_path(candidate.name) or "") >= version_number(
            version_from_path(export_path) or "")
        if candidate.is_file() and newer:
            export_path = str(candidate).replace("\\", "/")
    if not materials or not export_path:
        return None
    export = PainterExport(version_from_path(export_path) or "", export_path)
    return dump_record(asset_from_path(export_path), export, materials)


def substance_libraries(stage_node: Any) -> list[tuple[Any, str]]:
    """(Material Library, record JSON) for every library Create made from a Painter export."""
    from tools.fx.auto_material.logic import RECORD_KEY

    out: list[tuple[Any, str]] = []
    if stage_node is None:
        return out
    for node in stage_node.children():
        try:
            if node.type().name() != "materiallibrary":
                continue
        except Exception:
            continue
        record = _user_data(node, RECORD_KEY) or _infer_record(node)
        if record:
            out.append((node, record))
    return out


def _library_nodes(stage_node: Any) -> list[Any]:
    out = []
    for node in stage_node.children() if stage_node is not None else ():
        try:
            if node.type().name() == "materiallibrary":
                out.append(node)
        except Exception:
            continue
    return out


def _builder_files(builder: Any) -> list[str]:
    """
    Texture paths on *builder*'s images: the ones the tool set and that are still there, and on
    another tool's images (untagged), their file. A file the user changed on the tool's image is the
    user's: its version says nothing of the publish.
    """
    out = []
    for img in _image_slots(builder).values():
        recorded = _user_data(img, FILE_TAG)
        parm = img.parm("file")
        current = parm.unexpandedString() if parm is not None else ""
        if recorded and (parm is None or current == recorded):
            out.append(recorded)
        elif not recorded and current:
            out.append(current)
    return out


def painter_versions(mat_lib: Any) -> dict[str, str]:
    """Material -> export version its textures come from (…_v008_full_textures/… -> v008), "" unknown."""
    from tools.fx.auto_material.logic import version_from_path, version_number

    out: dict[str, str] = {}
    for builder in mat_lib.children():
        found = [v for v in (version_from_path(f) for f in _builder_files(builder)) if v]
        out[builder.name()] = min(found, key=version_number) if found else ""
    return out


def library_record(mat_lib: Any, text: str) -> tuple[dict, dict]:
    """(record fields, MaterialRecords) of a Painter library, versions as its nodes really have them."""
    from tools.fx.auto_material.logic import merge_node_versions, oldest_version, parse_record

    meta, records = parse_record(text)
    records = merge_node_versions(records, painter_versions(mat_lib))
    meta["version"] = oldest_version(records) or meta.get("version") or ""
    return meta, records


def material_libraries(stage_node: Any) -> dict[str, dict[str, str]]:
    """
    Name -> {material builder: texture version} for every Material Library in *stage_node*, in
    network order. The version is "" for a material the tool did not build or with no version.
    """
    from tools.fx.auto_material.logic import folder_library

    out: dict[str, dict[str, str]] = {}
    for lib in _library_nodes(stage_node):
        files = {b.name(): _builder_files(b) for b in lib.children()}
        info = folder_library(lib.name(), lib.path(), files)
        out[lib.name()] = {name: (info.versions.get(name, "") if info else "") for name in files}
    return out


def folder_libraries(stage_node: Any) -> list[Any]:
    """logic.FolderLibrary for every library the tool built from texture folders (not Painter exports)."""
    from tools.fx.auto_material.logic import folder_library

    painter = {lib.path() for lib, _record in substance_libraries(stage_node)}
    out = []
    for lib in _library_nodes(stage_node):
        if lib.path() in painter:
            continue
        info = folder_library(lib.name(), lib.path(), {b.name(): _builder_files(b) for b in lib.children()})
        if info is not None and info.publish:
            out.append(info)
    return out


def update_folder_library(
    stage_node: Any, lib_name: str, groups: dict, names: list[str] | None = None, cancelled: Any = None,
) -> "ApplyResult":
    """
    Move the materials already in *lib_name* to *groups* (a folder scan). Only materials whose
    version changes (or that still use Houdini's %(UDIM)d) are touched; none is created.
    *names*: only these materials. cancelled: optional callable, checked between materials.
    """
    from tools.fx.auto_material.logic import folder_status, group_version

    result = ApplyResult()
    lib = stage_node.node(lib_name) if stage_node is not None else None
    if lib is None:
        return result
    have = material_libraries(stage_node).get(lib_name, {})
    with manual_update():
        for name, group in groups.items():
            if name not in have or (names is not None and name not in names):
                continue
            if cancelled is not None and cancelled():
                break
            builder = lib.node(name)
            if folder_status(have[name], group_version(group)) != "update" and not _uses_houdini_udim(builder):
                continue
            notes: list[str] = []
            update_material(builder, group.slots, notes)
            result.updated.append(name)
            result.notes += [f"{name}: {n}" for n in notes]
    return result


def write_record(mat_lib: Any, record: str) -> None:
    from tools.fx.auto_material.logic import RECORD_KEY

    try:
        mat_lib.setUserData(RECORD_KEY, record)
    except Exception:
        pass


def branch_library(selected: Any, libraries: list[Any]) -> Any:
    """The library among *libraries* in the selected node's branch (it or an upstream node), if any."""
    if selected is None:
        return None
    wanted = {lib.path() for lib in libraries}
    seen: set[str] = set()
    todo = [selected]
    while todo and len(seen) < 500:
        node = todo.pop()
        if node is None or node.path() in seen:
            continue
        seen.add(node.path())
        if node.path() in wanted:
            return node
        todo.extend(i for i in node.inputs() if i is not None)
    return None


def _uses_houdini_udim(builder: Any) -> bool:
    """Whether the tool set a file with Houdini's %(UDIM)d on any image of *builder* (before <UDIM>)."""
    return any("%(UDIM)d" in (_user_data(img, FILE_TAG) or "") for img in _image_slots(builder).values())


class ApplyResult:
    __slots__ = ("created", "updated", "notes")

    def __init__(self) -> None:
        self.created: list[str] = []
        self.updated: list[str] = []
        self.notes: list[str] = []


def apply_painter_plan(
    stage_node: Any,
    data: dict[str, ExportData],
    plans: list,
    previous: dict,
    cancelled: Any = None,
    library: str | None = None,
) -> ApplyResult:
    """
    Build the Version manager's plan into the scene. The newest export gives the geometry and the
    node names: {base}_geo (Sublayer) -> {base}_materials (Material Library) -> {base}_assign.
    A material is (re)built only when it is new or its version changes; a pin change alone only
    goes into the record. *previous*: the scene's MaterialRecords, kept for materials left out.
    cancelled: optional callable, checked between materials.
    *library*: another Material Library of the asset (a copy, or one another tool made): only its
    materials are updated there; the geometry and the assignment stay as they are.
    """
    from tools.fx.auto_material import config
    from tools.fx.auto_material.logic import (
        MaterialRecord,
        asset_from_path,
        dump_record,
        version_number,
    )

    result = ApplyResult()
    latest = data[max(data, key=version_number)]
    base = latest.source.node_base
    default_lib = base + config.SUBSTANCE_MATLIB_NODE_SUFFIX
    in_place = library is not None and library != default_lib
    if in_place:
        sublayer = stage_node.node(library)
        if sublayer is None:
            result.notes.append(f"{library}: not in the scene.")
            return result
    else:
        sublayer = get_or_create_substance_sublayer(
            stage_node, base + config.SUBSTANCE_GEO_NODE_SUFFIX, latest.source.geo_layers,
        )
        if sublayer is None:
            result.notes.append("Cannot create the Sublayer for the Substance geometry.")
            return result
    mat_lib_name = library if in_place else default_lib

    records = dict(previous)
    paths: dict[str, str] = {}
    with manual_update():
        for plan in plans:
            if not plan.enabled:
                # Remembered as left out; what the scene already has of it stays as it is.
                old = records.get(plan.name)
                records[plan.name] = MaterialRecord(old.version if old else "", old.pinned if old else False, True)
                continue
            if cancelled is not None and cancelled():
                break
            if plan.scene is None or plan.scene != plan.chosen:
                group = data[plan.chosen].groups.get(plan.name)
                if group is None:
                    continue
                built = build_material(
                    stage=stage_node, material_name=plan.name, slots=group.slots,
                    mat_lib_name=mat_lib_name, selected_node=sublayer,
                )
                if built is None:
                    continue
                (result.updated if built.updated else result.created).append(built.node_name)
                result.notes += [f"{built.node_name}: {n}" for n in built.notes]
                paths[plan.name] = built.path
            else:
                paths[plan.name] = f"/materials/{plan.name}"
                # Same version, but built when the tool still wrote Houdini's %(UDIM)d: move it to
                # <UDIM> (update_material keeps paths changed by hand). Not counted as an update.
                lib = stage_node.node(mat_lib_name)
                builder = lib.node(plan.name) if lib is not None else None
                group = data[plan.chosen].groups.get(plan.name)
                if builder is not None and group is not None and _uses_houdini_udim(builder):
                    update_material(builder, group.slots, [])
            records[plan.name] = MaterialRecord(plan.chosen, plan.pinned)

        mat_lib = stage_node.node(mat_lib_name)
        if mat_lib is None:
            return result
        if result.created:
            layout_material_library(mat_lib, new_names=result.created)
        if in_place:
            write_record(mat_lib, dump_record(asset_from_path(latest.export.usd_path), latest.export, records))
            return result

        # Prims per material: the geometry export's bindings, else the chosen export's.
        entries = []
        for plan in plans:
            if plan.name not in paths:
                continue
            prims = latest.source.assignments.get(plan.name) or data[plan.chosen].source.assignments.get(plan.name)
            if prims:
                entries.append((" ".join(prims), paths[plan.name]))
        assign, added = assign_substance_materials(
            stage_node, mat_lib, base + config.SUBSTANCE_ASSIGN_NODE_SUFFIX, entries,
        )
        if assign is not None and added:
            result.notes.append(f"{assign.name()}: {added} binding(s) added.")

    write_record(mat_lib, dump_record(asset_from_path(latest.export.usd_path), latest.export, records))
    return result
