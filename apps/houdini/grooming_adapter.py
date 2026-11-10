"""
Houdini side of MONO Grooming: the only place that touches `hou` for the tool.

The panel's controller talks to this module only (spec: docs/plans/grooming_v0_1.md, "Adapter API").
Every public function runs on Houdini's main thread. The helpers marked "pure" take plain data and
are tested without Houdini (tests/test_grooming_adapter.py). The HDA network itself is built by
tools/fx/grooming/build_hda.py; its two Python SOPs call `cook_assign` and `cook_frozen_regions`.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import json
import math
import os
import re
from typing import Any, Iterable, Sequence

try:
    import hou
except ImportError:
    hou = None  # type: ignore[assignment]

from tools.fx.grooming import config, logic, model
from tools.fx.grooming.logic import DetectReport, LockInfo, MeshPiece, PublishResult

# Internal nodes of the HDA the adapter reads (names fixed by build_hda.py).
NODE_SPINES_RAW = "SPINES_RAW"       # one spine per hair-mesh piece, measured, no lock ids yet
NODE_SPINES_LOCKS = "SPINES_LOCKS"   # spines with lock_id / name / group and resolved settings
NODE_SPINES = "SPINES"               # spines after settings (width_mult, twist_add ...)
NODE_SCALP_FINE = "SCALP_FINE"       # scalp after the bilinear subdivision used for regions
NODE_SCALP_REGIONS = "SCALP_REGIONS" # scalp prims with lock_owners (shared when stacked), share, density, area_cm2
ATTR_LOCK_OWNERS = "lock_owners"     # int array: every lock growing hair on a scalp prim
NODE_HAIR = "HAIR"                   # strands at the current density (preview or full)
NODE_PUBLISH_USD = "PUBLISH_USD"     # usdexport SOP fed by the full hair

PARM_REGIONS = "regions"             # hidden geometry data parm: the frozen region split
PARM_DISPLAY = "display_mode"
PARM_COLOR_BY = "color_by"
PARM_PREVIEW = "preview_fraction"
PARM_PUBLISH_PATH = "publish_path"   # hidden, read by PUBLISH_USD
PARM_PUBLISH_VERSION = "publish_version"

DEFAULT_GROUP = "main"
UNDO_PREFIX = "MONO Grooming: "

_GROUP_PALETTE = (
    (0.90, 0.45, 0.30), (0.30, 0.62, 0.90), (0.45, 0.80, 0.40), (0.85, 0.70, 0.25),
    (0.70, 0.45, 0.85), (0.30, 0.80, 0.75), (0.90, 0.40, 0.60), (0.60, 0.60, 0.60),
)
UNDETECTED_COLOR = (0.25, 0.25, 0.25)


# ---------------------------------------------------------------------------
# Pure helpers (no hou)
# ---------------------------------------------------------------------------

def lock_color(lock_id: int) -> tuple[float, float, float]:
    """Display colour of a lock (logic.lock_color, the panel's colour too); grey before Detect."""
    if lock_id < 0:
        return UNDETECTED_COLOR
    return logic.lock_color(lock_id)


def group_color(index: int) -> tuple[float, float, float]:
    return _GROUP_PALETTE[index % len(_GROUP_PALETTE)]


def group_id_from_mesh_name(name: str) -> str:
    """"Geo_HairBang" -> "hair_bang"; "" -> DEFAULT_GROUP. A mesh name shared by several pieces is a
    region of the groom (Helen's Geo_HairBang, Geo_HairBack), so it gives the group, not the lock name."""
    base = re.sub(r"^(geo|msh|mesh)_", "", (name or "").strip().split("/")[-1], flags=re.IGNORECASE)
    base = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", base)
    base = re.sub(r"[^0-9a-zA-Z]+", "_", base).strip("_").lower()
    return base or DEFAULT_GROUP


def unique_names(mesh_names: Sequence[str]) -> list[str]:
    """Per piece: its mesh name when no other piece has it (then it names the lock), else ""."""
    counts: dict[str, int] = {}
    for n in mesh_names:
        counts[n] = counts.get(n, 0) + 1
    return [n if n and counts[n] == 1 else "" for n in mesh_names]


def asset_from_scene(scene_name: str) -> str:
    """"char_Helen_grooming_v007.hiplc" -> "char_Helen"; a name without "_grooming" loses its _vNNN."""
    base = os.path.splitext(os.path.basename(scene_name or ""))[0]
    m = re.match(r"^(.*?)_grooming(?:$|[._])", base, flags=re.IGNORECASE)
    if m and m.group(1):
        return m.group(1)
    return re.sub(r"[._]v\d+$", "", base, flags=re.IGNORECASE) or "asset"


def preview_factor(expected_strands: float, fraction: float = config.PREVIEW_FRACTION,
                   max_strands: int = config.PREVIEW_MAX_STRANDS) -> float:
    """Density factor for "hair_preview": `fraction` of the strands, at most `max_strands` of them."""
    f = max(0.0, min(1.0, float(fraction)))
    if expected_strands > 0 and expected_strands * f > max_strands:
        f = max_strands / float(expected_strands)
    return f


def classify_inputs(cands: Sequence[tuple[str, int]]) -> tuple[int, int] | None:
    """(scalp index, hair index) among selected SOPs given as (node name, primitive count), or None
    when it cannot tell. Names decide first ("scalp", "skin", "head" / "hair", "lock", "driver"), then a
    hair mesh with at least twice the primitives of the other."""
    if len(cands) != 2:
        return None
    scalp_words = ("scalp", "skin", "head")
    hair_words = ("hair", "lock", "driver", "groom")

    def kind(name: str) -> str | None:
        low = name.lower()
        s = any(w in low for w in scalp_words)
        h = any(w in low for w in hair_words)
        return "scalp" if s and not h else "hair" if h and not s else None

    k0, k1 = kind(cands[0][0]), kind(cands[1][0])
    if {k0, k1} == {"scalp", "hair"}:
        return (0, 1) if k0 == "scalp" else (1, 0)
    if k0 == "scalp" or k1 == "hair":
        return 0, 1
    if k1 == "scalp" or k0 == "hair":
        return 1, 0
    n0, n1 = cands[0][1], cands[1][1]
    if n1 >= 2 * max(n0, 1):
        return 0, 1
    if n0 >= 2 * max(n1, 1):
        return 1, 0
    return None


def assign_pieces(pieces: Sequence[tuple[str, tuple[float, float, float], float]],
                  locks: Sequence[model.Lock]) -> list[int]:
    """Lock id per cooked spine, from what Detect stored: (unique mesh name or "", root, length).

    Same name first, else the nearest stored root within 5 % of the lock length (Detect stores the
    root it measured, so an unchanged mesh matches exactly). Each lock is used once; a piece the JSON
    does not know (mesh changed since Detect) gets -1 and grows no hair until Detect runs again."""
    out = [-1] * len(pieces)
    free = {lk.id: lk for lk in locks}
    by_name = {lk.name: lk for lk in locks if lk.name}
    for i, (name, _root, _length) in enumerate(pieces):
        lk = by_name.get(name) if name else None
        if lk is not None and lk.id in free:
            out[i] = lk.id
            del free[lk.id]
    cands = []
    for i, (_name, root, length) in enumerate(pieces):
        if out[i] >= 0:
            continue
        for lk in free.values():
            d = math.dist(root, lk.root)
            if d <= 0.05 * max(length, lk.length, 1e-6):
                cands.append((d, i, lk.id))
    for _d, i, lid in sorted(cands):
        if out[i] < 0 and lid in free:
            out[i] = lid
            del free[lid]
    return out


def apply_detect(data: model.GroomData, pieces: Sequence[MeshPiece], piece_groups: Sequence[str],
                 report: DetectReport, asset: str = "") -> model.GroomData:
    """New GroomData after Detect: matched locks keep id and settings and take the new root / length,
    new pieces become locks (name from the mesh, else `logic.lock_name` of the group), locks with no
    piece move to `orphans` with their settings. Regions go stale whenever a lock is added, removed or
    moved. `piece_groups[i]` is the group of `pieces[i]`; `report.matches` refer to `MeshPiece.index`."""
    out = model.GroomData.from_json(data.to_json())
    if asset and not out.asset:
        out.asset = asset
    by_index = {p.index: (p, g) for p, g in zip(pieces, piece_groups)}
    old = {lk.id: lk for lk in out.locks}
    taken = [lk.name for lk in out.locks] + [o.name for o in out.orphans]
    locks: list[model.Lock] = []
    stale = False
    for m in report.matches:
        piece, group = by_index[m.piece]
        root = tuple(round(c, 6) for c in piece.root)
        length = round(piece.length, 6)
        lk = old.get(m.lock_id)
        if lk is not None and m.status != "new":
            if math.dist(lk.root, root) > 1e-5 or abs(lk.length - length) > 1e-5:
                stale = True
            lk.root, lk.length, lk.match = root, length, m.status  # type: ignore[assignment]
            lk.direction = tuple(round(c, 6) for c in piece.direction)  # type: ignore[assignment]
            locks.append(lk)
            continue
        name = piece.name or logic.lock_name(group, taken)
        taken.append(name)
        locks.append(model.Lock(id=m.lock_id, name=name, group=group, root=root,  # type: ignore[arg-type]
                                length=length, match="new",
                                direction=tuple(round(c, 6) for c in piece.direction)))  # type: ignore[arg-type]
        stale = True
    for lid in report.orphaned:
        lk = old[lid]
        out.orphans.append(model.Orphan(id=lk.id, name=lk.name, group=lk.group, overrides=dict(lk.overrides)))
        stale = True
    out.locks = sorted(locks, key=lambda lk: lk.id)
    have = {g.id for g in out.groups}
    for lk in out.locks:
        if lk.group not in have:
            out.groups.append(model.Group(id=lk.group, name=lk.group, color=group_color(len(out.groups))))
            have.add(lk.group)
    out.regions_stale = out.regions_stale or stale
    return out


def lock_display_attribs(data: model.GroomData, lock_ids: Sequence[int]) -> dict[str, list]:
    """Per spine prim (lock id or -1): name, group, colours, visibility and every resolved setting.
    What the in-network "assign" Python SOP writes, kept here so it is testable."""
    out: dict[str, list] = {k: [] for k in ("name", "group", "lock_cd", "group_cd", "visible",
                                           "lock_match", *model.SETTING_KEYS)}
    for lid in lock_ids:
        lk = data.lock(lid) if lid >= 0 else None
        g = data.group(lk.group) if lk is not None else None
        settings = data.resolve(lid) if lk is not None else dict(model.BUILTIN_DEFAULTS)
        out["name"].append(lk.name if lk else "")
        out["group"].append(lk.group if lk else "")
        out["lock_cd"].append(lock_color(lid))
        out["group_cd"].append(tuple(g.color) if g else UNDETECTED_COLOR)
        out["visible"].append(int(lk is not None and lk.visible and (g is None or g.visible)))
        out["lock_match"].append(lk.match if lk else "undetected")
        for k in model.SETTING_KEYS:
            out[k].append(float(settings[k]))
    return out


def publish_record(asset: str, version: str, usd: str, scene: str, data: model.GroomData,
                   strands: int, node_path: str, houdini: str = "") -> dict[str, Any]:
    """What publish.json holds next to grooming_data.json."""
    return {
        "asset": asset, "version": version, "department": "grooming", "usd": usd, "scene": scene,
        "node": node_path, "houdini": houdini, "user": getpass.getuser(),
        "date": _dt.datetime.now().isoformat(timespec="seconds"),
        "locks": len(data.locks), "groups": len(data.groups), "strands": strands,
        "regions_stale": data.regions_stale, "schema": data.schema,
    }


# ---------------------------------------------------------------------------
# hou helpers
# ---------------------------------------------------------------------------

def _require_hou() -> None:
    if hou is None:
        raise RuntimeError("MONO Grooming adapter needs Houdini (hou)")


def _node_type():
    return hou.nodeType(hou.sopNodeTypeCategory(), config.HDA_TYPE)


def _inner(node, name: str):
    inner = node.node(name)
    if inner is None:
        raise RuntimeError(f"{node.path()} has no {name}: not a {config.HDA_LABEL} node of this version")
    return inner


def _cooked(node, name: str):
    inner = _inner(node, name)
    inner.cook()
    return inner.geometry()


def _status(text: str, error: bool = False) -> None:
    if hou is not None and hou.isUIAvailable():
        sev = hou.severityType.Error if error else hou.severityType.Message
        hou.ui.setStatusMessage(text, severity=sev)
    else:
        print(("ERROR: " if error else "") + text)


def _place_new(node) -> None:
    node.moveToGoodPosition(move_inputs=False, move_outputs=False, move_unconnected=False)


def _prim_values(geo, name: str, kind: str) -> list:
    if geo.findPrimAttrib(name) is None:
        return []
    if kind == "s":
        return list(geo.primStringAttribValues(name))
    if kind == "i":
        return list(geo.primIntAttribValues(name))
    if kind == "f":
        return list(geo.primFloatAttribValues(name))
    size = geo.findPrimAttrib(name).size()
    flat = geo.primFloatAttribValues(name)
    return [tuple(flat[i:i + size]) for i in range(0, len(flat), size)]


# ---------------------------------------------------------------------------
# Adapter API
# ---------------------------------------------------------------------------

def find_nodes() -> list:
    """MONO Grooming nodes in the scene, selected ones first."""
    _require_hou()
    nt = _node_type()
    if nt is None:
        return []
    nodes = list(nt.instances())
    return sorted(nodes, key=lambda n: (not n.isSelected(), n.path()))


def create_node(parent=None):
    """New node wired to a selected scalp + hair mesh when it can tell which is which, else unwired."""
    _require_hou()
    sel = [n for n in hou.selectedNodes() if n.type().category() == hou.sopNodeTypeCategory()]
    if parent is None:
        parent = sel[0].parent() if sel else None
    with hou.undos.group(UNDO_PREFIX + "Create"):
        if parent is None:
            parent = hou.node("/obj").createNode("geo", "grooming")
            _place_new(parent)
        node = parent.createNode(config.HDA_TYPE, "mono_grooming")
        same = [n for n in sel if n.parent() == parent]
        if len(same) == 2:
            counts = []
            for n in same:
                try:
                    counts.append((n.name(), len(n.geometry().iterPrims())))
                except hou.Error:
                    counts.append((n.name(), 0))
            pick = classify_inputs(counts)
            if pick is not None:
                node.setInput(0, same[pick[0]])
                node.setInput(1, same[pick[1]])
        _place_new(node)
        node.setDisplayFlag(True)
        node.setRenderFlag(True)
        node.setSelected(True, clear_all_selected=True)
    return node


def read_data(node) -> model.GroomData:
    return model.GroomData.from_json(node.evalParm(config.DATA_PARM))


def write_data(node, data: model.GroomData, label: str) -> None:
    """Store `groom_data`; one undo step named `label`."""
    with hou.undos.group(label):
        node.parm(config.DATA_PARM).set(data.to_json())


def lock_infos(node) -> list[LockInfo]:
    """From the cooked spines: id, name, group, root, length, width, thick, twist, strands, region area."""
    geo = _cooked(node, NODE_SPINES_LOCKS)
    scalp = _cooked(node, NODE_SCALP_REGIONS)
    area: dict[int, float] = {}   # a shared prim counts 1/share for each of its owners
    for prim in scalp.iterPrims():
        own = prim.attribValue(ATTR_LOCK_OWNERS) if scalp.findPrimAttrib(ATTR_LOCK_OWNERS) else ()
        a = prim.floatAttribValue("area_cm2")
        for lid in own:
            area[lid] = area.get(lid, 0.0) + a / len(own)
    infos = []
    for prim in geo.iterPrims():
        lid = prim.intAttribValue(config.ATTR_LOCK_ID)
        if lid < 0:
            continue
        pts = prim.points()
        widths = [p.floatAttribValue(config.ATTR_LOCK_WIDTH) for p in pts]
        thicks = [p.floatAttribValue(config.ATTR_LOCK_THICK) for p in pts]
        a = area.get(lid, 0.0)
        infos.append(LockInfo(
            id=lid, name=prim.stringAttribValue(config.ATTR_NAME), group=prim.stringAttribValue(config.ATTR_GROUP),
            root=tuple(prim.attribValue("root")), length=prim.floatAttribValue("length"),  # type: ignore[arg-type]
            width=sum(widths) / max(len(widths), 1), thick=sum(thicks) / max(len(thicks), 1),
            twist=pts[-1].floatAttribValue(config.ATTR_LOCK_TWIST) if pts else 0.0,
            strands=int(round(prim.floatAttribValue("density") * a)), region_area_cm2=a,
        ))
    return sorted(infos, key=lambda i: i.id)


def _pieces(node) -> tuple[list[MeshPiece], list[str]]:
    geo = _cooked(node, NODE_SPINES_RAW)
    mesh_names = _prim_values(geo, "mesh_name", "s") or [""] * len(geo.iterPrims())
    names = unique_names(mesh_names)
    roots = _prim_values(geo, "root", "v")
    lengths = _prim_values(geo, "length", "f")
    dirs = _prim_values(geo, "direction", "v")
    idx = _prim_values(geo, "piece", "i")
    pieces = [MeshPiece(index=idx[i], name=names[i], root=roots[i], length=lengths[i], direction=dirs[i])
              for i in range(len(idx))]
    groups = [group_id_from_mesh_name(mesh_names[i]) if mesh_names[i] and not names[i] else DEFAULT_GROUP
              for i in range(len(idx))]
    return pieces, groups


def detect(node) -> DetectReport:
    """Detect locks from the hair mesh, match ids against the JSON (logic.match_locks), write the JSON."""
    pieces, groups = _pieces(node)
    data = read_data(node)
    report = logic.match_locks(pieces, data.locks, data.next_lock_id())
    asset = asset_from_scene(hou.hipFile.basename())
    new = apply_detect(data, pieces, groups, report, asset=asset)
    write_data(node, new, UNDO_PREFIX + "Detect")
    c = report.counts
    _status(f"{config.HDA_LABEL}: {len(pieces)} lọn - ok {c['ok']}, chưa chắc {c['unsure']}, "
            f"mới {c['new']}, mất {c['orphaned']}")
    return report


def split_regions(node) -> None:
    """Recompute and freeze the growth regions, clear `regions_stale`. One undo step.

    Per prim of the subdivided scalp (`SCALP_FINE`), at its centroid: the locks whose footprint covers
    it (logic.region_owners: radius = REGION_FOOTPRINT x the lock's measured root width), else the
    nearest lock; stacked locks share. Frozen as one point per prim with `lock_owners` (int array)."""
    data = read_data(node)
    spines = _cooked(node, NODE_SPINES_LOCKS)
    scalp = _cooked(node, NODE_SCALP_FINE)
    roots: dict[int, tuple[float, float, float]] = {}
    radii: dict[int, float] = {}
    for prim in spines.iterPrims():
        lid = prim.intAttribValue(config.ATTR_LOCK_ID)
        if lid < 0:
            continue
        roots[lid] = tuple(prim.attribValue("root"))  # type: ignore[assignment]
        pts0 = prim.points()
        width = pts0[0].floatAttribValue(config.ATTR_LOCK_WIDTH) if pts0 else 0.0
        radii[lid] = config.REGION_FOOTPRINT * width
    has_group = scalp.findPointAttrib(config.ATTR_GROUP) is not None
    centroids: list[tuple[float, float, float]] = []
    prim_groups: list[str] = []
    for prim in scalp.iterPrims():
        pp = prim.points()
        n = max(len(pp), 1)
        c = [0.0, 0.0, 0.0]
        for p in pp:
            pos = p.position()
            c[0] += pos[0]; c[1] += pos[1]; c[2] += pos[2]
        centroids.append((c[0] / n, c[1] / n, c[2] / n))
        prim_groups.append(pp[0].stringAttribValue(config.ATTR_GROUP) if has_group and pp else "")
    if has_group:
        groups_of = {lk.id: lk.group for lk in data.locks}
    else:  # scalp without regions: every prim may grow any lock
        groups_of = {lid: "" for lid in roots}
    owners = logic.region_owners(centroids, roots, radii, groups_of, prim_groups)
    frozen = hou.Geometry()
    frozen.createPoints(centroids)
    frozen.addArrayAttrib(hou.attribType.Point, ATTR_LOCK_OWNERS, hou.attribData.Int)
    frozen.addAttrib(hou.attribType.Point, config.ATTR_LOCK_OWNER, config.NO_OWNER)
    for pt, own in zip(frozen.points(), owners):
        pt.setAttribValue(ATTR_LOCK_OWNERS, own)
        pt.setAttribValue(config.ATTR_LOCK_OWNER, own[0] if own else config.NO_OWNER)
    data.regions_stale = False
    with hou.undos.group(UNDO_PREFIX + "Chia vùng"):
        node.parm(PARM_REGIONS).set(frozen)
        node.parm(config.DATA_PARM).set(data.to_json())
    grown = {lid for own in owners for lid in own}
    shared = sum(1 for own in owners if len(own) > 1)
    _status(f"{config.HDA_LABEL}: chia vùng cho {len(grown)}/{len(roots)} lọn, {len(centroids)} prim da, "
            f"{shared} prim dùng chung")


def set_display(node, mode: str, color_by: str, preview: float = config.PREVIEW_FRACTION) -> None:
    """`mode` in mesh/guide/hair_preview/hair; `color_by` in lock/group; `preview` = hair_preview fraction."""
    if mode not in config.DISPLAY_MODES or color_by not in config.COLOR_BY:
        raise ValueError(f"display {mode!r} / colour by {color_by!r}")
    with hou.undos.group(UNDO_PREFIX + "Display"):
        node.parm(PARM_DISPLAY).set(config.DISPLAY_MODES.index(mode))
        node.parm(PARM_COLOR_BY).set(config.COLOR_BY.index(color_by))
        node.parm(PARM_PREVIEW).set(float(preview))


def _scene_viewer():
    if not hou.isUIAvailable():
        return None
    return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)


def selected_lock_ids(node) -> list[int]:
    """Locks whose spines, strands or mesh pieces are selected in the viewport (empty when none)."""
    viewer = _scene_viewer()
    if viewer is None:
        return []
    try:
        sel = viewer.currentGeometrySelection()
    except hou.Error:
        return []
    if sel is None or node not in sel.nodes():
        return []
    geo = node.geometry()
    if geo.findPrimAttrib(config.ATTR_LOCK_ID) is None:
        return []
    ids: set[int] = set()
    for s in sel.selections():
        prims = list(s.prims(geo))
        for pt in s.points(geo):
            prims.extend(pt.prims())
        ids.update(p.intAttribValue(config.ATTR_LOCK_ID) for p in prims)
    return sorted(i for i in ids if i >= 0)


def select_locks(node, ids: Iterable[int]) -> None:
    """Select those locks' primitives in the viewport (nothing without a UI)."""
    viewer = _scene_viewer()
    if viewer is None:
        return
    want = set(ids)
    geo = node.geometry()
    if geo.findPrimAttrib(config.ATTR_LOCK_ID) is None:
        return
    prims = [p for p in geo.iterPrims() if p.intAttribValue(config.ATTR_LOCK_ID) in want]
    node.setCurrent(True, clear_all_selected=True)
    viewer.setCurrentGeometrySelection(hou.geometryType.Primitives, (node,), (hou.Selection(prims),))


def display_state(node) -> tuple[str, str]:
    """The node's own display mode and colour-by, for the panel to show on open."""
    return (config.DISPLAY_MODES[node.evalParm(PARM_DISPLAY)], config.COLOR_BY[node.evalParm(PARM_COLOR_BY)])


def _existing_versions(hip_dir: str, asset: str) -> list[str]:
    usd0, _ = logic.publish_paths(hip_dir, asset, "v001")
    pub_dir = os.path.dirname(os.path.dirname(usd0))
    return sorted(os.listdir(pub_dir)) if os.path.isdir(pub_dir) else []


def publish_context(node) -> tuple[str, list[str]]:
    """(scene name without extension, versions already published) for logic.publish_version."""
    data = read_data(node)
    scene = hou.hipFile.basename()
    asset = data.asset or asset_from_scene(scene)
    return os.path.splitext(scene)[0], _existing_versions(os.path.dirname(hou.hipFile.path()), asset)


def publish(node, version: str | None = None) -> PublishResult:
    """Write the asset groom USD and `vNNN/_grooming/` (grooming_data.json, publish.json); never overwrite."""
    data = read_data(node)
    scene = hou.hipFile.basename()
    asset = data.asset or asset_from_scene(scene)
    hip_dir = os.path.dirname(hou.hipFile.path())
    try:
        if not version:
            version, _note = logic.publish_version(os.path.splitext(scene)[0], _existing_versions(hip_dir, asset))
        usd, tool_dir = logic.publish_paths(hip_dir, asset, version)
    except ValueError as exc:
        return PublishResult(False, "", version or "", f"Không publish được: {exc}")
    if os.path.exists(usd) or os.path.exists(tool_dir):
        return PublishResult(False, usd, version, f"{version} đã có bản publish, không ghi đè: {usd}")

    exporter = _inner(node, NODE_PUBLISH_USD)
    old_mode = node.evalParm(PARM_DISPLAY)
    made = not os.path.isdir(os.path.dirname(usd))
    try:
        os.makedirs(tool_dir)
        with hou.undos.disabler():  # export settings are not an edit of the groom
            node.parm(PARM_PUBLISH_PATH).set(usd)
            node.parm(PARM_DISPLAY).set(config.DISPLAY_MODES.index("hair"))
            try:
                hair = _cooked(node, NODE_HAIR)
                strands = len(hair.iterPrims())
                exporter.parm("execute").pressButton()
            finally:
                node.parm(PARM_DISPLAY).set(old_mode)
                node.parm(PARM_PUBLISH_PATH).set("")
        errors = exporter.errors()
        if errors or not os.path.isfile(usd):
            raise RuntimeError("; ".join(errors) or "USD export wrote no file")
        with open(os.path.join(tool_dir, "grooming_data.json"), "w", encoding="utf-8") as fh:
            fh.write(data.to_json())
        record = publish_record(asset, version, usd, hou.hipFile.path(), data, strands, node.path(),
                                hou.applicationVersionString())
        with open(os.path.join(tool_dir, "publish.json"), "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=1)
    except Exception as exc:  # noqa: BLE001 - reported to the panel, never a dialog
        _remove_partial(usd, tool_dir, made)
        return PublishResult(False, usd, version, f"Publish {version} lỗi: {exc}")
    msg = f"Đã publish {asset} {version}: {strands} sợi, {len(data.locks)} lọn"
    if data.regions_stale:
        msg += " (vùng mọc chưa chia lại)"
    _status(f"{config.HDA_LABEL}: {msg}")
    return PublishResult(True, usd, version, msg)


def _remove_partial(usd: str, tool_dir: str, made_version_dir: bool) -> None:
    """Undo a failed publish: only what this publish created."""
    for path in (os.path.join(tool_dir, "publish.json"), os.path.join(tool_dir, "grooming_data.json"), usd):
        if os.path.isfile(path):
            os.remove(path)
    for d in (tool_dir, os.path.dirname(usd) if made_version_dir else ""):
        if d and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)


# ---------------------------------------------------------------------------
# Called from inside the HDA
# ---------------------------------------------------------------------------

def on_button(node, action: str) -> None:
    """Parm button callbacks of the HDA: results go to the status bar, never a dialog."""
    try:
        if action == "detect":
            detect(node)
        elif action == "split_regions":
            split_regions(node)
        elif action == "publish":
            res = publish(node, node.evalParm(PARM_PUBLISH_VERSION).strip() or None)
            _status(f"{config.HDA_LABEL}: {res.message}", error=not res.ok)
    except Exception as exc:  # noqa: BLE001
        _status(f"{config.HDA_LABEL}: {action} lỗi: {exc}", error=True)


def cook_assign(sop) -> None:
    """Python SOP "assign": lock_id, name, group, colours, visibility and resolved settings per spine."""
    top = sop.parent()
    geo = sop.geometry()
    data = read_data(top)
    names = _prim_values(geo, "mesh_name", "s") or [""] * len(geo.iterPrims())
    uniq = unique_names(names)
    pieces = list(zip(uniq, _prim_values(geo, "root", "v"), _prim_values(geo, "length", "f")))
    ids = assign_pieces(pieces, data.locks)
    attrs = lock_display_attribs(data, ids)
    geo.addAttrib(hou.attribType.Prim, config.ATTR_LOCK_ID, -1)
    geo.setPrimIntAttribValues(config.ATTR_LOCK_ID, ids)
    for key in ("name", "group", "lock_match"):
        geo.addAttrib(hou.attribType.Prim, key, "")
        geo.setPrimStringAttribValues(key, attrs[key])
    for key in ("lock_cd", "group_cd"):
        geo.addAttrib(hou.attribType.Prim, key, (0.0, 0.0, 0.0))
        geo.setPrimFloatAttribValues(key, [c for rgb in attrs[key] for c in rgb])
    geo.addAttrib(hou.attribType.Prim, "visible", 1)
    geo.setPrimIntAttribValues("visible", attrs["visible"])
    for key in model.SETTING_KEYS:
        geo.addAttrib(hou.attribType.Prim, key, 0.0)
        geo.setPrimFloatAttribValues(key, attrs[key])
    missing = ids.count(-1)
    if missing:
        sop.addWarning(f"{missing} lọn chưa có trong dữ liệu: bấm Detect")


def cook_frozen_regions(sop) -> None:
    """Python SOP "frozen regions": the split stored on the node's `regions` parm, or nothing."""
    geo = sop.geometry()
    geo.clear()
    frozen = sop.parent().parm(PARM_REGIONS).evalAsGeometry()
    if frozen is not None:
        geo.merge(frozen)


__all__ = [
    "find_nodes", "create_node", "read_data", "write_data", "lock_infos", "detect", "split_regions",
    "set_display", "display_state", "selected_lock_ids", "select_locks", "publish_context", "publish",
]
