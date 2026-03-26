"""
Thin Houdini Solaris/LOP adapter — only place that imports hou for LOP operations.

Tool controllers use this to create Karma materials in Solaris.
Core and logic must never import hou.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

try:
    import hou
except ImportError:
    hou = None  # type: ignore[assignment]

from tools.fx.auto_material.config import (
    PUBLISH_TEXTURE_RELATIVE_PATH,
    SLOT_DEF_MAP,
    SURFACE_INPUT_MAP,
)


def is_available() -> bool:
    return hou is not None


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
            node.moveToGoodPosition()
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
        builder.moveToGoodPosition()
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
        node.moveToGoodPosition()
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
        node.moveToGoodPosition()

        file_parm = node.parm("file")
        if file_parm:
            file_parm.set(filepath)

        sig_parm = node.parm("signature")
        if sig_parm and sig != "color3":
            menu_val = _SIGNATURE_MENU_MAP.get(sig, sig)
            sig_parm.set(menu_val)

        token = _resolve_filecolorspace_token(colorspace)
        if not token and slot_def:
            token = _resolve_filecolorspace_token(slot_def.default_colorspace)
        if not token:
            token = "Raw"
        _set_filecolorspace_parm(node, token)

        return node
    except Exception:
        return None


def create_mtlx_normal_map(builder: Any) -> Any:
    if builder is None:
        return None
    try:
        node = builder.createNode("mtlxnormalmap", node_name="mtlxnormalmap")
        node.moveToGoodPosition()
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

        if slot == "normal" and normal_map_node is not None:
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
        collect.moveToGoodPosition()

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
            node.moveToGoodPosition()
        return node
    except Exception:
        return None


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
            node.moveToGoodPosition()

        # Set multiparm count (Houdini uses "Number of Materials")
        count_parm = (
            node.parm("nummaterials")
            or node.parm("num_materials")
            or node.parm("num_mats")
            or node.parm("numassignments")
        )
        if count_parm is not None:
            count_parm.set(len(assignments))

        # Fill each entry
        for i, (prim_pattern, material_path) in enumerate(assignments, 1):
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


def layout_material_library(mat_lib: Any) -> None:
    """
    Sort and arrange Karma Material Builder subnets inside the Material Library
    by name (alphabetically), then set positions in a vertical stack.
    """
    if mat_lib is None:
        return
    try:
        children = list(mat_lib.children())
        if not children:
            return
        children.sort(key=lambda n: n.name().lower())
        dx, dy = 0.0, -1.8
        base = children[0].position()
        for i, node in enumerate(children):
            node.setPosition((base[0] + dx * i, base[1] + dy * i))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# High-level: build full material from slot dict
# ---------------------------------------------------------------------------

def build_material(
    stage: Any,
    material_name: str,
    slots: dict,
    mat_lib_name: str = "materiallibrary1",
    selected_node: Any = None,
) -> str | None:
    """
    Create a complete Karma material from a slots dict.
    slots: { slot_name: SlotInfo } from logic.py.
    selected_node: if provided, Material Library is created after this node.
    Returns material USD path (e.g. /materials/costume) or None on failure.
    """
    mat_lib = get_or_create_material_library(
        stage, name=mat_lib_name, connect_after=selected_node,
    )
    if mat_lib is None:
        return None

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

        if slot_name == "normal":
            nrm = create_mtlx_normal_map(builder)
            connect_slot(surface, img, slot_name, normal_map_node=nrm)
        elif slot_name in SURFACE_INPUT_MAP:
            connect_slot(surface, img, slot_name)

    _ensure_surface_connected_to_output(builder, surface)
    layout_nodes(builder)

    return f"/materials/{material_name}"
