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
import hashlib
import json
import math
import os
import re
import sys
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
PARM_ISOLATE = "isolate_ids"         # hidden: locks shown alone ("" = none); display only, never undone
PARM_COOK_ALL = "cook_all"           # hidden: 1 while publishing: every lock, hidden or isolated out

# Parms whose value never reaches the per-lock hair cook (display, publish, deform, what the geometry
# already carries): left out of the cache key, so changing them recooks no lock.
_KEY_SKIP_PARMS = {config.DATA_PARM, PARM_REGIONS, PARM_DISPLAY, PARM_COLOR_BY, PARM_PREVIEW, "preview_max",
                   PARM_PUBLISH_PATH, PARM_PUBLISH_VERSION, PARM_ISOLATE, PARM_COOK_ALL, "deform_radius",
                   "rest_frame", "detect", "split_regions", "publish"}
# Spine prim attributes the hair loop does not read (display, filters, cache bookkeeping).
_KEY_SKIP_ATTRIBS = {"visible", "shown", "grows", "lock_cd", "group_cd", "lock_match", "cached", "cache_key",
                     "cache_mode"}
_CACHE_ATTR = "_mono_grooming_hair_cache"
CACHE_NET_VERSION = "partial-1"      # bump when the per-lock network changes what it makes

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
    """Density factor for "hair_preview": `fraction` of the strands, at most `max_strands` of them.

    Capped factors snap down to a step of PREVIEW_FACTOR_STEP (0.8^k), the same as the HDA's PREVIEW:
    the factor is part of every lock's cache key, and an exact cap / total moved with any density edit
    and recooked every lock."""
    f = max(0.0, min(1.0, float(fraction)))
    if expected_strands > 0 and expected_strands * f > max_strands:
        f = max_strands / float(expected_strands)
        if f > 0:
            step = config.PREVIEW_FACTOR_STEP
            f = step ** math.ceil(math.log(f) / math.log(step) - 1e-6)
    return f


def parse_isolate(text: str | None) -> list[int]:
    """Lock ids of the `isolate_ids` parm ("3 17 20"); empty = nothing isolated."""
    out = []
    for tok in (text or "").replace(",", " ").split():
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return sorted(set(out))


def format_isolate(lock_ids: Iterable[int] | None) -> str:
    return " ".join(str(i) for i in sorted(set(int(i) for i in (lock_ids or ()))))


def lock_key(parts: Iterable[Any]) -> str:
    """Cache key of one lock's hair: a digest of everything its per-lock cook reads."""
    h = hashlib.blake2b(digest_size=16)
    for p in parts:
        h.update(p if isinstance(p, (bytes, bytearray, memoryview)) else repr(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class LockCache:
    """Hair of each lock, cooked once per input state (`lock_key`), per MONO Grooming node and display
    mode. Pure Python: the values are whatever the adapter stores (frozen hou.Geometry in Houdini).

    Per (node, lock, mode) the last KEEP keys are kept, most recently used last: an undo of an edit goes
    back to the previous key and finds it. Entries of the key in use are never dropped by a store of
    another lock, so what `lock_keys` saw as cached is still there when `hair_cache` merges it."""

    KEEP = 2

    def __init__(self) -> None:
        self._d: dict[tuple[int, int, str], dict[str, Any]] = {}

    def has(self, node_id: int, lock_id: int, mode: str, key: str) -> bool:
        return key in self._d.get((node_id, lock_id, mode), {})

    def get(self, node_id: int, lock_id: int, mode: str, key: str) -> Any:
        slot = self._d.get((node_id, lock_id, mode))
        if slot is None or key not in slot:
            return None
        slot[key] = slot.pop(key)  # most recently used last
        return slot[key]

    def put(self, node_id: int, lock_id: int, mode: str, key: str, value: Any) -> None:
        slot = self._d.setdefault((node_id, lock_id, mode), {})
        slot.pop(key, None)
        slot[key] = value
        while len(slot) > self.KEEP:
            del slot[next(iter(slot))]

    def nodes(self) -> set[int]:
        return {k[0] for k in self._d}

    def drop_node(self, node_id: int) -> None:
        for k in [k for k in self._d if k[0] == node_id]:
            del self._d[k]

    def __len__(self) -> int:
        return sum(len(s) for s in self._d.values())


def hair_cache() -> LockCache:
    """The session's one LockCache. Kept on `sys`, not in this module: reloading the adapter (or
    hou.session code) must not lose it while lock_keys still says a lock is cached."""
    cache = getattr(sys, _CACHE_ATTR, None)
    if cache is None:
        cache = LockCache()
        setattr(sys, _CACHE_ATTR, cache)
    return cache


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
        # stored unrounded: match_locks' "unchanged" rule compares within 1e-5 x length, and rounding to
        # 6 decimals would already exceed that for a 2 cm lock in a metre scene
        root = tuple(float(c) for c in piece.root)
        length = float(piece.length)
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
        out.orphans.append(model.Orphan(id=lk.id, name=lk.name, group=lk.group, overrides=dict(lk.overrides),
                                        root_flip=lk.root_flip, excluded=lk.excluded))
        stale = True
    out.locks = sorted(locks, key=lambda lk: lk.id)
    have = {g.id for g in out.groups}
    for lk in out.locks:
        if lk.group not in have:
            out.groups.append(model.Group(id=lk.group, name=lk.group, color=group_color(len(out.groups))))
            have.add(lk.group)
    out.regions_stale = out.regions_stale or stale
    out.note_ids()
    return out


def lock_display_attribs(data: model.GroomData, lock_ids: Sequence[int]) -> dict[str, list]:
    """Per spine prim (lock id or -1): name, group, colours, visibility and every resolved setting.
    What the in-network "assign" Python SOP writes, kept here so it is testable."""
    out: dict[str, list] = {k: [] for k in ("name", "group", "lock_cd", "group_cd", "visible",
                                           "lock_match", "root_flip", "excluded", *model.SETTING_KEYS)}
    for lid in lock_ids:
        lk = data.lock(lid) if lid >= 0 else None
        g = data.group(lk.group) if lk is not None else None
        settings = data.resolve(lid) if lk is not None else dict(model.BUILTIN_DEFAULTS)
        out["name"].append(lk.name if lk else "")
        out["group"].append(lk.group if lk else "")
        out["lock_cd"].append(lock_color(lid))
        out["group_cd"].append(tuple(g.color) if g else UNDETECTED_COLOR)
        out["visible"].append(int(lk is not None and lk.shown(g)))
        out["lock_match"].append(lk.match if lk else "undetected")
        out["root_flip"].append(int(lk is not None and lk.root_flip))
        out["excluded"].append(int(lk is not None and lk.excluded))
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
    if _node_type() is None:  # checked first: nothing is created when the HDA is missing
        raise RuntimeError(f"{config.HDA_LABEL} ({config.HDA_TYPE}) is not installed: otls/mono_grooming.hdalc "
                           "is missing from the MonoFX Suite folder")
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
        # the widest band anywhere: same rule as the HDA's region_frame
        section = logic.section_cm2(max(widths, default=0.0), max(thicks, default=0.0), node.evalParm("unit_cm"))
        infos.append(LockInfo(
            id=lid, name=prim.stringAttribValue(config.ATTR_NAME), group=prim.stringAttribValue(config.ATTR_GROUP),
            root=tuple(prim.attribValue("root")), length=prim.floatAttribValue("length"),  # type: ignore[arg-type]
            width=sum(widths) / max(len(widths), 1), thick=sum(thicks) / max(len(thicks), 1),
            twist=pts[-1].floatAttribValue(config.ATTR_LOCK_TWIST) if pts else 0.0,
            strands=logic.lock_strands(prim.floatAttribValue("density"), a, section), region_area_cm2=a,
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
    excluded = {lk.id for lk in data.locks if lk.excluded}   # grows no hair: takes no scalp from another lock
    for prim in spines.iterPrims():
        lid = prim.intAttribValue(config.ATTR_LOCK_ID)
        if lid < 0 or lid in excluded:
            continue
        roots[lid] = tuple(prim.attribValue("root"))  # type: ignore[assignment]
        # The root band of a lock is often tapered to almost nothing, so the footprint takes the widest
        # section near the root (first 10 % of the spine). Not further: Helen's hair_base caps widen
        # to 20 cm a little up, and a 10 cm footprint grew a cone of strands converging on the lock.
        pts0 = prim.points()
        head = pts0[:max(2, len(pts0) // 10)]
        width = max((p.floatAttribValue(config.ATTR_LOCK_WIDTH) for p in head), default=0.0)
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


def set_isolate(node, lock_ids: Sequence[int] | None) -> None:
    """Show only `lock_ids` (None or empty: back to every shown lock). A temporary view: no undo step,
    cleared when the scene is loaded again (the HDA's OnLoaded), the eyes underneath stay as they are.
    Only those locks cook; isolated locks are drawn even when their eye is off."""
    with hou.undos.disabler():
        node.parm(PARM_ISOLATE).set(format_isolate(lock_ids))


def isolate_ids(node) -> list[int]:
    """The isolated locks, [] when nothing is isolated."""
    return parse_isolate(node.evalParm(PARM_ISOLATE))


def _set_lock_flag(node, lock_ids: Iterable[int], field_name: str, value: bool, label: str) -> int:
    data = read_data(node)
    want = set(int(i) for i in lock_ids)
    changed = 0
    for lk in data.locks:
        if lk.id in want and getattr(lk, field_name) != bool(value):
            setattr(lk, field_name, bool(value))
            changed += 1
    if changed:
        # the lock's root moves, or it stops taking scalp: regions are out of date, never re-split silently
        data.regions_stale = True
        write_data(node, data, UNDO_PREFIX + label)
    return changed


def set_root_flip(node, lock_ids: Iterable[int], flip: bool) -> int:
    """Root at the mesh piece's other end (`flip`) or back at the end nearer the scalp, for these locks.
    One undo step; kept through re-Detect; marks regions out of date. Returns how many locks changed."""
    return _set_lock_flag(node, lock_ids, "root_flip", flip, "Đổi đầu gốc" if flip else "Gốc mặc định")


def set_excluded(node, lock_ids: Iterable[int], excluded: bool) -> int:
    """Leave these locks out of the hair (no strands, not published) or take them back. Mesh and guide
    still show them. One undo step; kept through re-Detect; marks regions out of date (Chia vùng gives
    their scalp to the other locks). Returns how many locks changed."""
    return _set_lock_flag(node, lock_ids, "excluded", excluded, "Bỏ khỏi tóc" if excluded else "Mọc tóc lại")


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
    # Geometry selection exists only while the viewer shows the node's own network (inside the geo
    # object); at /obj level Houdini refuses it, so the panel's selection simply is not mirrored there.
    if viewer.pwd() != node.parent():
        return
    want = set(ids)
    geo = node.geometry()
    if geo.findPrimAttrib(config.ATTR_LOCK_ID) is None:
        return
    prims = [p for p in geo.iterPrims() if p.intAttribValue(config.ATTR_LOCK_ID) in want]
    try:
        node.setCurrent(True, clear_all_selected=True)
        viewer.setCurrentGeometrySelection(hou.geometryType.Primitives, (node,), (hou.Selection(prims),))
    except hou.Error:
        # The viewer has no active selector (view state, not a select state): Houdini refuses with
        # "Not available in this context / no active selector found". The panel's selection simply is
        # not mirrored there; that is not an error the user has to see.
        pass


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
        version = os.path.basename(os.path.dirname(usd))  # the normalised spelling (v7 -> v007)
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
            node.parm(PARM_COOK_ALL).set(1)   # hidden and isolated-out locks too (the display skips them)
            try:
                hair = _cooked(node, NODE_HAIR)
                strands = len(hair.iterPrims())
                exporter.parm("execute").pressButton()
            finally:
                node.parm(PARM_COOK_ALL).set(0)
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
    for key, default in (("visible", 1), ("root_flip", 0), ("excluded", 0)):
        geo.addAttrib(hou.attribType.Prim, key, default)
        geo.setPrimIntAttribValues(key, attrs[key])
    for key in model.SETTING_KEYS:
        geo.addAttrib(hou.attribType.Prim, key, 0.0)
        geo.setPrimFloatAttribValues(key, attrs[key])
    missing = ids.count(-1)
    if missing:
        sop.addWarning(f"{missing} lọn chưa có trong dữ liệu: bấm Detect")


def on_loaded(node) -> None:
    """HDA OnLoaded: isolate is a temporary view, so a scene saved while isolated opens showing all."""
    p = node.parm(PARM_ISOLATE)
    if p is not None and p.eval():
        with hou.undos.disabler():
            p.set("")


def _definition_stamp(top) -> str:
    try:
        d = top.type().definition()
        return f"{d.libraryFilePath()}@{d.modificationTime()}" if d is not None else ""
    except hou.Error:
        return ""


def _key_parms(top) -> list[tuple[str, str]]:
    out = []
    for p in top.parms():
        name = p.name()
        if name in _KEY_SKIP_PARMS:
            continue
        try:
            out.append((name, p.evalAsString()))
        except hou.Error:
            continue
    return out


def cook_lock_keys(sop) -> None:
    """Python SOP "lock_keys", hair modes only: per spine `cache_key` (a digest of everything the
    per-lock hair loop reads for that lock: its spine and settings, its region, its mesh piece, the
    parms the loop uses, the display mode and preview factor) and `cached` (its hair is in the cache).

    Inputs: 0 the shown spines (`grows`), 1 PREVIEW (detail `factor`, `region_keys`: per lock id 9
    floats summing its region prims), 2 SURFACE_KEYS (detail `surface_keys`: per piece 9 floats of its
    lookup cloud)."""
    import numpy as np

    top = sop.parent()
    geo = sop.geometry()
    ins = sop.inputs()
    preview = ins[1].geometry()
    surface = ins[2].geometry()
    mode = str(top.evalParm(PARM_DISPLAY))
    factor = preview.attribValue("factor") if preview.findGlobalAttrib("factor") else 1.0
    rk = preview.floatListAttribValue("region_keys") if preview.findGlobalAttrib("region_keys") else ()
    sk = surface.floatListAttribValue("surface_keys") if surface.findGlobalAttrib("surface_keys") else ()
    shared = lock_key([CACHE_NET_VERSION, mode, factor, _definition_stamp(top), _key_parms(top)])

    pattrs = [a for a in geo.pointAttribs() if a.dataType() == hou.attribData.Float]
    parrays = [np.frombuffer(geo.pointFloatAttribValuesAsString(a.name()), dtype=np.float32).reshape(-1, a.size())
               for a in pattrs]
    rattrs = sorted((a for a in geo.primAttribs() if a.name() not in _KEY_SKIP_ATTRIBS), key=lambda a: a.name())
    for name, default in (("cache_key", ""), ("cache_mode", ""), ("cached", 0)):
        if geo.findPrimAttrib(name) is None:
            geo.addAttrib(hou.attribType.Prim, name, default)
    cache = hair_cache()
    for nid in cache.nodes():           # nodes deleted, or from a scene loaded before
        if hou.nodeBySessionId(nid) is None:
            cache.drop_node(nid)
    sid = top.sessionId()
    keys, flags = [], []
    for prim in geo.iterPrims():
        lid = prim.intAttribValue(config.ATTR_LOCK_ID)
        piece = prim.intAttribValue("piece") if geo.findPrimAttrib("piece") else -1
        idx = [p.number() for p in prim.points()]
        parts: list[Any] = [shared, [(a.name(), prim.attribValue(a)) for a in rattrs]]
        parts.extend(arr[idx].tobytes() for arr in parrays)
        parts.append(tuple(rk[lid * 9:lid * 9 + 9]) if lid >= 0 else ())
        parts.append(tuple(sk[piece * 9:piece * 9 + 9]) if piece >= 0 else ())
        key = lock_key(parts)
        keys.append(key)
        flags.append(int(cache.has(sid, lid, mode, key)))
    geo.setPrimStringAttribValues("cache_key", keys)
    geo.setPrimStringAttribValues("cache_mode", [mode] * len(keys))
    geo.setPrimIntAttribValues("cached", flags)


def cook_cache_store(sop) -> None:
    """Python SOP "cache_store", last node of the per-lock loop: keep this lock's strands under its
    key, then output nothing (the merge is hair_cache's, so the strands are copied once)."""
    geo = sop.geometry()
    spine = sop.inputs()[1].geometry()
    prims = spine.prims()
    if prims:
        p = prims[0]
        hair_cache().put(sop.parent().sessionId(), p.intAttribValue(config.ATTR_LOCK_ID),
                         p.stringAttribValue("cache_mode"), p.stringAttribValue("cache_key"),
                         geo.freeze(read_only=True))
    geo.clear()


def cook_hair_cache(sop) -> None:
    """Python SOP "hair_cache": the strands of every lock that grows (shown, not excluded; every lock
    while publishing), from the cache. Input 0 is the per-lock loop (it stored the missing ones),
    input 1 the keyed spines."""
    geo = sop.geometry()
    geo.clear()
    keyed = sop.inputs()[1].geometry()
    cache = hair_cache()
    sid = sop.parent().sessionId()
    missing = 0
    grows = keyed.findPrimAttrib("grows") is not None
    for p in keyed.iterPrims():
        if grows and p.intAttribValue("grows") == 0:
            continue
        g = cache.get(sid, p.intAttribValue(config.ATTR_LOCK_ID), p.stringAttribValue("cache_mode"),
                      p.stringAttribValue("cache_key"))
        if g is None:
            missing += 1
        else:
            geo.merge(g)
    if missing:
        sop.addWarning(f"{missing} lọn chưa có tóc trong cache: đổi Display rồi đổi lại để nấu lại")


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
    "set_isolate", "isolate_ids", "set_root_flip", "set_excluded",
]
