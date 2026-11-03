"""
Drag & drop of files from the OS file browser into Houdini.

Called by scripts/externaldragdrop.py (Houdini's hook for external drops). What a drop creates
depends on the Network Editor under the cursor:

- OBJ:  geo/abc/usd -> a geo node with a File / Alembic / USD Import SOP inside; .fbx -> FBX import.
- SOP:  geo/fbx -> File SOP, .abc -> Alembic SOP, .usd -> USD Import SOP.
- LOP:  geo/abc/usd -> Reference LOP; textures or a texture folder -> Auto Material.
- VOP (material library / builder): textures -> MaterialX Image with colour space set.
- COP:  images -> File COP.

Anything else (no Network Editor under the cursor, .hip files, unknown types) is left to
Houdini's own drop handling. The functions above handle_drop() do not need hou.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

try:
    import hou
except ImportError:
    hou = None  # type: ignore[assignment]

from tools.fx.auto_material.config import IMAGE_EXTENSIONS
from tools.fx.auto_material.logic import (
    MaterialGroup,
    auto_parse,
    group_by_prefix,
    read_publish_spaces,
    scan_and_group,
)

KIND_GEO = "geo"
KIND_ABC = "abc"
KIND_FBX = "fbx"
KIND_USD = "usd"
KIND_IMAGE = "image"
KIND_FOLDER = "folder"

# Longest first so ".bgeo.sc" wins over ".sc"
_GEO_EXTS = (".bgeo.sc", ".bgeo.gz", ".bgeo.lzma", ".bgeo", ".geo", ".obj", ".ply", ".stl", ".vdb", ".bhclassic")
_USD_EXTS = (".usd", ".usda", ".usdc", ".usdz")
_IMAGE_EXTS = tuple(sorted(IMAGE_EXTENSIONS))
# 8-bit formats are almost always sRGB colour when the name says nothing
_SRGB_EXTS = frozenset({".png", ".jpg", ".jpeg", ".tga", ".bmp"})

_SEQ_RE = re.compile(r"^(?P<base>.*?)(?P<sep>[._])(?P<num>\d{3,})$")
_NAME_BAD_RE = re.compile(r"[^A-Za-z0-9_]+")

NODE_SPACING = 1.2


def split_ext(path: str) -> tuple[str, str]:
    """(stem, ext) with multi-part extensions kept whole: a.bgeo.sc -> ("a", ".bgeo.sc")."""
    name = Path(path).name
    lower = name.lower()
    for ext in _GEO_EXTS:
        if lower.endswith(ext):
            return name[: -len(ext)], name[-len(ext):]
    p = Path(name)
    return p.stem, p.suffix


def classify(path: str) -> str | None:
    """Kind of a dropped path, None when the drop handler should leave it to Houdini."""
    if Path(path).is_dir():
        return KIND_FOLDER
    ext = split_ext(path)[1].lower()
    if ext in _GEO_EXTS:
        return KIND_GEO
    if ext == ".abc":
        return KIND_ABC
    if ext == ".fbx":
        return KIND_FBX
    if ext in _USD_EXTS:
        return KIND_USD
    if ext in IMAGE_EXTENSIONS:
        return KIND_IMAGE
    return None


def node_name_for(path: str) -> str:
    """Valid Houdini node name from a file name, frame / UDIM numbers and tokens removed."""
    stem = split_ext(path)[0]
    stem = re.sub(r"[._]?(\$F\d*|%\(UDIM\)d|<UDIM>)$", "", stem)
    m = _SEQ_RE.match(stem)
    if m:
        stem = m.group("base")
    name = _NAME_BAD_RE.sub("_", stem).strip("_") or "file"
    return f"_{name}" if name[0].isdigit() else name


def collapse_sequences(paths: list[str]) -> list[str]:
    """
    Files that differ only in a trailing number (name.1001.bgeo.sc, name.1002.bgeo.sc) become one
    path with $F<padding>. A single numbered file is kept as is. Order of first appearance is kept.
    """
    groups: "OrderedDict[tuple, list[str]]" = OrderedDict()
    for p in paths:
        stem, ext = split_ext(p)
        m = _SEQ_RE.match(stem)
        key = (str(Path(p).parent), m.group("base"), m.group("sep"), len(m.group("num")), ext.lower()) if m else (p,)
        groups.setdefault(key, []).append(p)
    out: list[str] = []
    for key, members in groups.items():
        if len(key) == 1 or len(members) < 2:
            out.extend(members)
            continue
        parent, base, sep, pad, _ = key
        ext = split_ext(members[0])[1]
        out.append((Path(parent) / f"{base}{sep}$F{pad}{ext}").as_posix())
    return out


def group_images(paths: list[str]) -> tuple[dict[str, MaterialGroup], list[str]]:
    """
    Dropped texture files -> material groups as Auto Material makes them (UDIM tiles become one
    slot), plus the files whose name gives no slot. A publish.json beside them fills colour spaces.
    """
    parsed, unmatched = [], []
    spaces_by_dir: dict[str, dict[str, str]] = {}
    for f in paths:
        r = auto_parse(f)
        if r is None:
            unmatched.append(f)
            continue
        if r.colorspace is None:
            d = str(Path(f).parent)
            if d not in spaces_by_dir:
                spaces_by_dir[d] = read_publish_spaces(d) or read_publish_spaces(Path(d).parent)
            r.colorspace = spaces_by_dir[d].get(r.slot)
        parsed.append(r)
    return group_by_prefix(parsed), unmatched


def collapse_udims(paths: list[str]) -> list[str]:
    """UDIM tiles (name.1001.exr ... name.1999.exr) become one path with %(UDIM)d."""
    out: "OrderedDict[str, None]" = OrderedDict()
    for p in paths:
        stem, ext = split_ext(p)
        m = re.match(r"^(.*)\.(\d{4})$", stem)
        if m and 1001 <= int(m.group(2)) <= 1999:
            p = Path(p).with_name(f"{m.group(1)}.%(UDIM)d{ext}").as_posix()
        out[p] = None
    return list(out)


# ---------------------------------------------------------------------------
# Houdini side
# ---------------------------------------------------------------------------

def handle_drop(file_list: list[str]) -> bool:
    """Entry point for externaldragdrop.dropAccept. True when the drop was handled here."""
    if hou is None or not file_list:
        return False
    pane = _network_editor_under_cursor()
    if pane is None:
        return False
    parent = pane.pwd()
    files = [Path(f).as_posix() for f in file_list if classify(f) is not None]
    if not files:
        return False

    category = parent.childTypeCategory().name()
    handler = _HANDLERS.get(category)
    if handler is None:
        return False

    # Selection inside the group too, so one Ctrl+Z takes the whole drop back
    with hou.undos.group("MonoFX: drop files"):
        created = handler(parent, files, pane.cursorPosition())
        for i, node in enumerate(created):
            node.setSelected(True, clear_all_selected=(i == 0))
    return bool(created)


def _network_editor_under_cursor() -> Any:
    try:
        pane = hou.ui.paneTabUnderCursor()
    except Exception:
        return None
    if pane is None or pane.type() != hou.paneTabType.NetworkEditor:
        return None
    return pane


def _create(parent: Any, type_name: str, path: str, pos: Any, index: int) -> Any:
    node = parent.createNode(type_name, node_name=node_name_for(path), force_valid_node_name=True)
    node.setPosition(hou.Vector2(pos[0] + index * NODE_SPACING * 2, pos[1]))
    return node


def _set_first(node: Any, parm_names: tuple[str, ...], value: str) -> None:
    for name in parm_names:
        parm = node.parm(name)
        if parm is not None:
            parm.set(value)
            return


def _sop_for(parent: Any, kind: str, path: str, pos: Any, index: int) -> Any:
    if kind == KIND_ABC:
        node = _create(parent, "alembic", path, pos, index)
        node.parm("fileName").set(path)
    elif kind == KIND_USD:
        node = _create(parent, "usdimport", path, pos, index)
        node.parm("filepath1").set(path)
    else:
        node = _create(parent, "file", path, pos, index)
        node.parm("file").set(path)
    return node


def _drop_obj(parent: Any, files: list[str], pos: Any) -> list[Any]:
    created = []
    for path in collapse_sequences(files):
        kind = classify(path.replace("$F", "0"))
        index = len(created)
        if kind == KIND_FBX:
            node = hou.hipFile.importFBX(path)[0]
            if node is not None:
                node.setPosition(hou.Vector2(pos[0] + index * NODE_SPACING * 2, pos[1]))
                created.append(node)
        elif kind in (KIND_GEO, KIND_ABC, KIND_USD):
            geo = _create(parent, "geo", path, pos, index)
            sop = _sop_for(geo, kind, path, (0, 0), 0)
            sop.setDisplayFlag(True)
            sop.setRenderFlag(True)
            created.append(geo)
    return created


def _drop_sop(parent: Any, files: list[str], pos: Any) -> list[Any]:
    created = []
    for path in collapse_sequences(files):
        kind = classify(path.replace("$F", "0"))
        if kind in (KIND_GEO, KIND_FBX, KIND_ABC, KIND_USD):
            created.append(_sop_for(parent, kind, path, pos, len(created)))
    return created


def _drop_lop(parent: Any, files: list[str], pos: Any) -> list[Any]:
    created = []
    for path in collapse_sequences([f for f in files if classify(f) != KIND_IMAGE]):
        kind = classify(path.replace("$F", "0"))
        if kind in (KIND_GEO, KIND_ABC, KIND_USD):
            node = _create(parent, "reference", path, pos, len(created))
            node.parm("filepath1").set(path)
            created.append(node)
        elif kind == KIND_FOLDER:
            groups, _ = scan_and_group(path, recursive=True)
            created += _build_materials(parent, groups)
    images = [f for f in files if classify(f) == KIND_IMAGE]
    if images:
        created += _build_materials(parent, group_images(images)[0])
    return created


def _build_materials(stage: Any, groups: dict[str, MaterialGroup]) -> list[Any]:
    """Auto Material for each group, in the Material Library after the selected LOP node."""
    if not groups:
        return []
    import apps.houdini.solaris_adapter as sa

    selected = next((n for n in hou.selectedNodes() if n.parent() == stage), None)
    created_names: list[str] = []
    mat_lib = None
    for prefix, group in groups.items():
        result = sa.build_material(stage=stage, material_name=prefix, slots=group.slots, selected_node=selected)
        if result is None:
            continue
        mat_lib = stage.node("materiallibrary1")
        if not result.updated:
            created_names.append(result.node_name)
        if result.notes:
            print("MonoFX drop:", "; ".join(f"{result.node_name}: {n}" for n in result.notes))
    if mat_lib is not None and created_names:
        sa.layout_material_library(mat_lib, new_names=created_names)
    return [mat_lib] if mat_lib is not None else []


def _drop_vop(parent: Any, files: list[str], pos: Any) -> list[Any]:
    if "mtlximage" not in parent.childTypeCategory().nodeTypes():
        return []
    import apps.houdini.solaris_adapter as sa

    created = []
    images = [f for f in files if classify(f) == KIND_IMAGE]
    groups, unmatched = group_images(images)
    entries = [(s, info.filepath, info.colorspace) for g in groups.values() for s, info in g.slots.items()]
    for path in collapse_udims(unmatched):
        ext = split_ext(path)[1].lower()
        entries.append(("", path, "sRGB" if ext in _SRGB_EXTS else None))
    for slot, path, colorspace in entries:
        node = sa.create_mtlx_image(parent, slot=slot, filepath=path, colorspace=colorspace)
        if node is None:
            continue
        node.setName(node_name_for(path), unique_name=True)
        node.setPosition(hou.Vector2(pos[0], pos[1] - len(created) * NODE_SPACING))
        created.append(node)
    return created


def _drop_cop(parent: Any, files: list[str], pos: Any) -> list[Any]:
    created = []
    for path in collapse_sequences([f for f in files if classify(f) == KIND_IMAGE]):
        node = _create(parent, "file", path, pos, len(created))
        _set_first(node, ("filename", "filename1", "file"), path)
        created.append(node)
    return created


_HANDLERS = {
    "Object": _drop_obj,
    "Sop": _drop_sop,
    "Lop": _drop_lop,
    "Vop": _drop_vop,
    "Cop": _drop_cop,
    "Cop2": _drop_cop,
}
