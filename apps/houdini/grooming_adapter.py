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
PARM_DRAG_PREVIEW = "preview_ids"    # hidden: locks a slider is dragging, grown light; display only
PARM_STRANDS = "strand_ids"          # hidden: locks drawn as strands, not packed ("all": every lock)
STRANDS_ALL = "all"                  # set_strands(node, STRANDS_ALL): the whole groom as strands
PARM_FOCUS = "focus_ids"             # hidden: the panel's selection; the other locks are drawn see-through
PARM_DRAG_FACTOR = "drag_factor"     # hidden: strand fraction of the locks a slider drags (1 = real count)
PARM_XRAY = "xray_opacity"           # hidden: alpha per strand of the locks out of focus (the panel's X-ray)
PARM_COOK_ALL = "cook_all"           # hidden: 1 while publishing: every lock, hidden or isolated out
PARM_DISPLAY_EFF = "display_eff"     # hidden expression: the mode drawn (Display, or While playing)
PARM_PLAYING = "playing"             # hidden: 1 while the timeline plays (playbar callback, undo off)

# Parms whose value never reaches the per-lock hair cook (display, publish, deform, what the geometry
# already carries): left out of the cache key, so changing them recooks no lock.
_KEY_SKIP_PARMS = {config.DATA_PARM, PARM_REGIONS, PARM_DISPLAY, PARM_COLOR_BY, PARM_PREVIEW, "preview_max",
                   PARM_PUBLISH_PATH, PARM_PUBLISH_VERSION, PARM_ISOLATE, PARM_DRAG_PREVIEW, PARM_STRANDS,
                   PARM_FOCUS, PARM_DRAG_FACTOR, PARM_COOK_ALL, PARM_XRAY,
                   "shot_deform", "deform_active", "anim_wired",   # per lock: do_capture; deform_radius stays
                   PARM_DISPLAY_EFF, PARM_PLAYING, "play_display",
                   "rest_frame", "detect", "split_regions", "publish"}
# Spine prim attributes the hair loop does not read (display, filters, cache bookkeeping).
_KEY_SKIP_ATTRIBS = {"visible", "shown", "grows", "lock_cd", "group_cd", "lock_match", "cached", "cache_key",
                     "cache_mode", "disp", "row_display"}   # a lock's display reaches its key as its factor
_CACHE_ATTR = "_mono_grooming_hair_cache"
_PLAYBAR_ATTR = "_mono_grooming_playbar_callback"
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
    moved. `piece_groups[i]` is the group of `pieces[i]`; `report.matches` refer to `MeshPiece.index`.
    The first Detect (no locks yet) marks nothing "new": every lock would be, and a status on every row
    says nothing."""
    out = model.GroomData.from_json(data.to_json())
    if asset and not out.asset:
        out.asset = asset
    by_index = {p.index: (p, g) for p, g in zip(pieces, piece_groups)}
    old = {lk.id: lk for lk in out.locks}
    first = not old and not out.orphans
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
                                length=length, match="ok" if first else "new",
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
    if stale:
        n_new = sum(m.status == "new" for m in report.matches)
        parts = ([f"{n_new} new"] if n_new else []) + ([f"{len(report.orphaned)} missing"] if report.orphaned else [])
        out.mark_stale("Detect locks: " + (", ".join(parts) if parts else "roots or lengths moved"))
    if not out.orphans:
        # "new" asks for a decision only while a missing lock's settings could go to it: with none
        # missing, every lock Detect found is simply the groom
        for lk in out.locks:
            if lk.match == "new":
                lk.match = "ok"
    out.note_ids()
    return out


def lock_display_attribs(data: model.GroomData, lock_ids: Sequence[int]) -> dict[str, list]:
    """Per spine prim (lock id or -1): name, group, colours, visibility and every resolved setting.
    What the in-network "assign" Python SOP writes, kept here so it is testable."""
    out: dict[str, list] = {k: [] for k in ("name", "group", "lock_cd", "group_cd", "visible",
                                           "lock_match", "root_flip", "excluded", "row_display",
                                           *model.SETTING_KEYS)}
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
        # the row's own Display (lock, else its group), as an index of DISPLAY_MODES; -1 = the node's
        own = (lk.display if lk is not None else None) or (g.display if g is not None else None)
        out["row_display"].append(config.DISPLAY_MODES.index(own) if own in config.DISPLAY_MODES else -1)
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


def undo(node, redo: bool = False) -> str:
    """Houdini's undo (or redo) of the last step, from the panel: with the panel focused, Ctrl+Z never
    reaches Houdini's hotkeys. Returns the step's label, "" when there was none."""
    labels = hou.undos.redoLabels() if redo else hou.undos.undoLabels()
    if not labels:
        return ""
    if redo:
        hou.undos.performRedo()
    else:
        hou.undos.performUndo()
    return labels[0]


def write_data_live(node, data: model.GroomData) -> None:
    """Store `groom_data` with no undo step: the ticks of a slider drag. The drag's release writes the
    final value with write_data, after putting the value from before the drag back, so one undo returns
    to where the drag started."""
    with hou.undos.disabler():
        node.parm(config.DATA_PARM).set(data.to_json())


def lock_infos(node) -> list[LockInfo]:
    """From the cooked spines: id, name, group, root, length, width, thick, twist, strands, region area."""
    geo = _cooked(node, NODE_SPINES_LOCKS)
    scalp = _cooked(node, NODE_SCALP_REGIONS)
    area: dict[int, float] = {}   # a shared prim counts 1/share for each of its owners
    if scalp.findPrimAttrib(ATTR_LOCK_OWNERS) and scalp.findPrimAttrib("area_cm2"):
        # bulk reads: one attribValue call per scalp prim (24k on Helen) cost 2 s on every panel refresh
        for own, a in zip(scalp.primIntListAttribValues(ATTR_LOCK_OWNERS), scalp.primFloatAttribValues("area_cm2")):
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
    _status(f"{config.HDA_LABEL}: {len(pieces)} locks - ok {c['ok']}, to check {c['unsure']}, "
            f"new {c['new']}, missing {c['orphaned']}")
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
    data.clear_stale()
    with hou.undos.group(UNDO_PREFIX + "Update regions"):
        node.parm(PARM_REGIONS).set(frozen)
        node.parm(config.DATA_PARM).set(data.to_json())
    grown = {lid for own in owners for lid in own}
    shared = sum(1 for own in owners if len(own) > 1)
    _status(f"{config.HDA_LABEL}: regions updated for {len(grown)}/{len(roots)} locks, {len(centroids)} skin"
            f" prims, {shared} shared")


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


def deform_state(node) -> tuple[bool, bool]:
    """(an animated hair mesh is wired in, Shot deform is on)."""
    wired = len(node.inputs()) > 2 and node.inputs()[2] is not None
    p = node.parm("shot_deform")
    return wired, bool(p.eval()) if p is not None else True


def set_shot_deform(node, on: bool) -> None:
    """Shot deform on / off: a view choice, no undo step; a scene always opens with it off (OnLoaded)."""
    p = node.parm("shot_deform")
    if p is not None:
        with hou.undos.disabler():
            p.set(int(bool(on)))
        try:   # turned on or off mid-playback: the While playing display follows at once
            playing = hou.isUIAvailable() and hou.playbar.isPlaying()
        except (AttributeError, hou.Error):
            playing = False
        _set_playing(node, playing_flag(playing, _deforming(node)))


def set_drag_preview(node, lock_ids: Sequence[int] | None, factor: float = 1.0) -> None:
    """While a slider drags: these locks grow at `factor` of their strands (1: their real count,
    `logic.drag_factor`) with DRAG_SEGMENTS points a strand; the rest keep their display. None clears it
    (the release grows them in full). No undo step, never saved (OnLoaded clears it), never during
    publish. A node built before drag_factor grows them at the preview fraction."""
    p = node.parm(PARM_DRAG_PREVIEW)
    if p is None:
        return
    with hou.undos.disabler():
        p.set(format_isolate(lock_ids))
        f = node.parm(PARM_DRAG_FACTOR)
        if f is not None and abs(f.eval() - float(factor)) > 1e-9:
            f.set(float(factor))


def xray_opacity(node) -> float:
    """Alpha per strand of the locks out of focus (config.GHOST_ALPHA on an HDA without the parm)."""
    p = node.parm(PARM_XRAY)
    return float(p.eval()) if p is not None else config.GHOST_ALPHA


def set_xray_opacity(node, alpha: float) -> None:
    """The panel's X-ray strength: a view choice, no undo step, no lock regrows (a ghost copy per lock and
    alpha is made once and kept)."""
    p = node.parm(PARM_XRAY)
    if p is not None and abs(p.eval() - float(alpha)) > 1e-6:
        with hou.undos.disabler():
            p.set(float(alpha))


def set_focus(node, lock_ids: Sequence[int] | None) -> None:
    """The panel's selection: those locks keep their colour, the others are drawn see-through and grey
    (None: every lock in its colour). It replaces Houdini's selection highlight, which painted the
    selected lock over in one colour: the viewport selection of this node is cleared. A view state:
    no undo step, never saved (OnLoaded clears it), no lock recooks."""
    p = node.parm(PARM_FOCUS)
    if p is None:
        return
    text = format_isolate(lock_ids)
    with hou.undos.disabler():
        if p.eval() != text:
            p.set(text)
        viewer = _scene_viewer()
        try:
            sel = viewer.currentGeometrySelection() if viewer is not None else None
            if sel is not None and node in sel.nodes() and any(s.selectionString(node.geometry())
                                                               for s in sel.selections()):
                viewer.setCurrentGeometrySelection(hou.geometryType.Primitives, (node,), (
                    hou.Selection(hou.geometryType.Primitives),))
        except hou.Error:
            pass   # no active selector (a view state): nothing is highlighted there


def focus_ids(node) -> list[int]:
    """The locks in focus, [] when every lock is drawn in its colour."""
    p = node.parm(PARM_FOCUS)
    return parse_isolate(p.eval()) if p is not None else []


def set_strands(node, lock_ids: Sequence[int] | str | None) -> None:
    """Draw these locks as their strands (None: every lock packed; STRANDS_ALL: the whole groom). The
    viewport draws a packed lock's strands as a flat band of one width; unpacked, it draws each strand's
    width, thinning to the tip. A view state like isolate: no undo step, cleared when the scene is loaded
    again. It changes no lock's hair, only how `hair_packed` hands it to the viewport."""
    p = node.parm(PARM_STRANDS)
    if p is None:
        return
    if lock_ids == STRANDS_ALL:
        text = STRANDS_ALL
    else:
        text = format_isolate(sorted(set(int(i) for i in (lock_ids or ()))))
    if p.eval() != text:
        with hou.undos.disabler():
            p.set(text)


def strands_all(node) -> bool:
    """The whole groom is drawn as strands (set_strands(node, STRANDS_ALL))."""
    p = node.parm(PARM_STRANDS)
    return p is not None and p.eval().strip() == STRANDS_ALL


def cook_display(node) -> None:
    """Cook the node now when the viewport draws it, so the panel's loading line covers the wait (the
    viewport would cook it on its next draw anyway). A cook error stays on the node."""
    try:
        if node.isDisplayFlagSet() and node.parent().isDisplayFlagSet():
            node.cook()
    except hou.OperationFailed:
        pass


def strand_ids(node) -> list[int]:
    """The locks drawn as strands by id, [] when every lock is packed or all are (strands_all)."""
    p = node.parm(PARM_STRANDS)
    if p is None or p.eval().strip() == STRANDS_ALL:
        return []
    return parse_isolate(p.eval())


def _set_lock_flag(node, lock_ids: Iterable[int], field_name: str, value: bool, label: str) -> int:
    data = read_data(node)
    want = set(int(i) for i in lock_ids)
    names = []
    for lk in data.locks:
        if lk.id in want and getattr(lk, field_name) != bool(value):
            setattr(lk, field_name, bool(value))
            names.append(lk.name or f"lock {lk.id}")
    changed = len(names)
    if changed:
        # the lock's root moves, or it stops taking scalp: regions are out of date, never re-split silently
        who = names[0] if changed == 1 else f"{changed} locks"
        data.mark_stale(f"{who}: {label.lower()}")
        write_data(node, data, UNDO_PREFIX + label)
    return changed


def set_root_flip(node, lock_ids: Iterable[int], flip: bool) -> int:
    """Root at the mesh piece's other end (`flip`) or back at the end nearer the scalp, for these locks.
    One undo step; kept through re-Detect; marks regions out of date. Returns how many locks changed."""
    return _set_lock_flag(node, lock_ids, "root_flip", flip, "Root flipped" if flip else "Root back at the scalp end")


def set_excluded(node, lock_ids: Iterable[int], excluded: bool) -> int:
    """Leave these locks out of the hair (no strands, not published) or take them back. Mesh and guide
    still show them. One undo step; kept through re-Detect; marks regions out of date (Update regions gives
    their scalp to the other locks). Returns how many locks changed."""
    return _set_lock_flag(node, lock_ids, "excluded", excluded, "Excluded from hair" if excluded else "Grows hair again")


def _scene_viewer():
    if not hou.isUIAvailable():
        return None
    return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)


def _index_ranges(indices: Iterable[int]) -> str:
    """0 1 2 5 -> "0-2 5": a selection string Houdini resolves in C++, not one hou.Prim per item."""
    out, run = [], None
    for i in sorted(indices):
        if run and i == run[1] + 1:
            run[1] = i
        else:
            if run:
                out.append(f"{run[0]}-{run[1]}" if run[1] > run[0] else str(run[0]))
            run = [i, i]
    if run:
        out.append(f"{run[0]}-{run[1]}" if run[1] > run[0] else str(run[0]))
    return " ".join(out)


def _parse_ranges(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split():
        if "-" in part:
            lo, hi = part.split("-", 1)
            if lo.isdigit() and hi.isdigit():
                out.extend(range(int(lo), int(hi) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


_LOCK_OF_PRIM: dict[int, tuple] = {}   # node session id -> (cookCount, lock_id per prim, frozen output)


def _lock_of_prim(node) -> tuple[list[int], "hou.Geometry"] | None:
    """lock_id of each output prim, read again only after the node has cooked again. The panel polls
    the viewport selection while Houdini handles events in the middle of a cook (Anim on: ~1.4 s), and
    node.geometry() there cooks the node inside its own cook: "Infinite recursion in evaluation", and
    the cook fails. needsToCook() cannot tell (it stays true on this node)."""
    count = node.cookCount()
    hit = _LOCK_OF_PRIM.get(node.sessionId())
    if hit is not None and hit[0] == count:
        return hit[1], hit[2]
    geo = node.geometry()
    if geo.findPrimAttrib(config.ATTR_LOCK_ID) is None:
        return None
    ids = list(geo.primIntAttribValues(config.ATTR_LOCK_ID))
    frozen = geo.freeze(read_only=True)   # shares the cooked data; resolves selection strings later
    _LOCK_OF_PRIM[node.sessionId()] = (node.cookCount(), ids, frozen)
    return ids, frozen


def selected_lock_ids(node) -> list[int]:
    """Locks whose spines, strands or mesh pieces are selected in the viewport (empty when none).
    Bulk reads: the panel polls this, and one hou.Prim per selected strand made every tick lag."""
    viewer = _scene_viewer()
    if viewer is None:
        return []
    try:
        sel = viewer.currentGeometrySelection()
    except hou.Error:
        return []
    if sel is None or node not in sel.nodes():
        return []
    read = _lock_of_prim(node)
    if read is None:
        return []
    lock_of_prim, geo = read
    ids: set[int] = set()
    for s in sel.selections():
        if s.selectionType() == hou.geometryType.Primitives:
            ids.update(lock_of_prim[i] for i in _parse_ranges(s.selectionString(geo)) if i < len(lock_of_prim))
        else:   # points: few in practice, take their prims
            for pt in s.points(geo):
                ids.update(p.intAttribValue(config.ATTR_LOCK_ID) for p in pt.prims())
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
    # one bulk read and a range string: a hou.Prim per strand (116 k on Helen) made each selection lag
    picked = [i for i, lid in enumerate(geo.primIntAttribValues(config.ATTR_LOCK_ID)) if lid in want]
    try:
        # no undo step: Houdini records a viewport selection, and the panel selects again after an edit
        # (the prim numbers of locks drawn as strands change), so Ctrl+Z undid that, not the edit
        with hou.undos.disabler():
            node.setCurrent(True, clear_all_selected=True)
            viewer.setCurrentGeometrySelection(hou.geometryType.Primitives, (node,), (
                hou.Selection(geo, hou.geometryType.Primitives, _index_ranges(picked)),))
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
        return PublishResult(False, "", version or "", f"Cannot publish: {exc}")
    if os.path.exists(usd) or os.path.exists(tool_dir):
        return PublishResult(False, usd, version, f"{version} is already published, not overwritten: {usd}")

    exporter = _inner(node, NODE_PUBLISH_USD)
    old_mode = node.evalParm(PARM_DISPLAY)
    made = not os.path.isdir(os.path.dirname(usd))
    try:
        os.makedirs(tool_dir)
        with hou.undos.disabler():  # export settings are not an edit of the groom
            node.parm(PARM_PUBLISH_PATH).set(usd)
            node.parm(PARM_DISPLAY).set(config.DISPLAY_MODES.index("hair"))
            node.parm(PARM_COOK_ALL).set(1)   # hidden and isolated-out locks too (the display skips them)
            node.parm(PARM_PLAYING).set(0)    # the full hair, never the lighter playback display
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
        return PublishResult(False, usd, version, f"Publish {version} failed: {exc}")
    msg = f"Published {asset} {version}: {strands:,} strands, {len(data.locks)} locks"
    if data.regions_stale:
        msg += " (regions out of date)"
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
        _status(f"{config.HDA_LABEL}: {action} failed: {exc}", error=True)


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
    for key, default in (("visible", 1), ("root_flip", 0), ("excluded", 0), ("row_display", -1)):
        geo.addAttrib(hou.attribType.Prim, key, default)
        geo.setPrimIntAttribValues(key, attrs[key])
    for key in model.SETTING_KEYS:
        geo.addAttrib(hou.attribType.Prim, key, 0.0)
        geo.setPrimFloatAttribValues(key, attrs[key])
    missing = ids.count(-1)
    if missing:
        sop.addWarning(f"{missing} locks are not in the groom data yet: press Detect locks")


def on_loaded(node) -> None:
    """HDA OnLoaded: isolate is a temporary view, so a scene saved while isolated opens showing all;
    a scene saved while playing opens at its Display; a scene saved with Shot deform on opens at rest
    (grooming is the main mode: with the deform every lock is drawn as strands and focus cannot see
    through the others)."""
    with hou.undos.disabler():
        for name, empty in ((PARM_ISOLATE, ""), (PARM_DRAG_PREVIEW, ""), (PARM_STRANDS, ""), (PARM_FOCUS, ""),
                            (PARM_PLAYING, 0), ("shot_deform", 0)):
            p = node.parm(name)
            if p is not None and p.eval():
                p.set(empty)
    install_playbar_callback()


def playing_state(event_name: str) -> bool | None:
    """Pure: the `playing` value for a playbar event (by name), None when the event changes nothing."""
    if event_name == "Started":
        return True
    if event_name == "Stopped":
        return False
    return None


def playing_flag(playing: bool, deforming: bool) -> int:
    """Pure: the node's `playing` parm. Only a node with Shot deform on draws lighter while playing:
    without the deform nothing cooks per frame (Helen hair full plays at the 30 fps cap), so switching to
    Hair preview only recooked on Start and Stop, and regrew every lock's preview on the first play."""
    return int(playing and deforming)


def _deforming(node) -> bool:
    p = node.parm("deform_active")
    return bool(p.eval()) if p is not None else False


def _set_playing(node, value: int) -> None:
    p = node.parm(PARM_PLAYING)
    if p is not None and p.eval() != value:
        with hou.undos.disabler():
            p.set(value)


def _on_playbar(event_type, frame) -> None:
    state = playing_state(str(event_type).rsplit(".", 1)[-1])
    if state is None:
        return
    try:
        nodes = find_nodes()
    except hou.Error:
        return
    for n in nodes:
        _set_playing(n, playing_flag(state, _deforming(n)))


def install_playbar_callback() -> None:
    """Once per session (kept on `sys`, like the cache): while the timeline plays, every MONO Grooming
    node with Shot deform on draws its While playing mode (`display_eff`). Only with a UI; hython has
    no playbar."""
    if hou is None or not hou.isUIAvailable() or getattr(sys, _PLAYBAR_ATTR, False):
        return
    hou.playbar.addEventCallback(_on_playbar_trampoline)
    setattr(sys, _PLAYBAR_ATTR, True)


def _on_playbar_trampoline(event_type, frame) -> None:
    # registered once; looks the handler up again so a reloaded adapter's code runs
    from apps.houdini import grooming_adapter as current
    current._on_playbar(event_type, frame)


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
    mode = str(top.evalParm(PARM_DISPLAY_EFF))
    factor = preview.attribValue("factor") if preview.findGlobalAttrib("factor") else 1.0
    light = preview.attribValue("preview_factor") if preview.findGlobalAttrib("preview_factor") else factor
    publishing = bool(top.evalParm(PARM_COOK_ALL))
    wired = bool(top.evalParm("anim_wired")) if top.parm("anim_wired") is not None else False
    deforming = bool(top.evalParm("deform_active")) if top.parm("deform_active") is not None else False
    dragged = set(parse_isolate(top.evalParm(PARM_DRAG_PREVIEW))) \
        if top.parm(PARM_DRAG_PREVIEW) is not None and not top.evalParm(PARM_COOK_ALL) else set()
    # dragged locks: their real count (or the panel's fraction) with fewer points a strand; a node
    # built before drag_factor: the preview fraction
    drag_f = top.evalParm(PARM_DRAG_FACTOR) if top.parm(PARM_DRAG_FACTOR) is not None else light
    rk = preview.floatListAttribValue("region_keys") if preview.findGlobalAttrib("region_keys") else ()
    sk = surface.floatListAttribValue("surface_keys") if surface.findGlobalAttrib("surface_keys") else ()
    # the mode is per lock (its `disp`, lock_shown): only its strand factor reaches the hair, so the
    # node's mode is not in the key and a lock keeps its cache when the node's Display changes
    shared = lock_key([CACHE_NET_VERSION, _definition_stamp(top), _key_parms(top)])

    pattrs = [a for a in geo.pointAttribs() if a.dataType() == hou.attribData.Float]
    parrays = [np.frombuffer(geo.pointFloatAttribValuesAsString(a.name()), dtype=np.float32).reshape(-1, a.size())
               for a in pattrs]
    rattrs = sorted((a for a in geo.primAttribs() if a.name() not in _KEY_SKIP_ATTRIBS), key=lambda a: a.name())
    for name, default in (("cache_key", ""), ("cache_mode", ""), ("cached", 0), ("strand_factor", 1.0),
                          ("do_capture", 0), ("drag_seg", 0)):
        if geo.findPrimAttrib(name) is None:
            geo.addAttrib(hou.attribType.Prim, name, default)
    cache = hair_cache()
    for nid in cache.nodes():           # nodes deleted, or from a scene loaded before
        if hou.nodeBySessionId(nid) is None:
            cache.drop_node(nid)
    sid = top.sessionId()
    has_disp = geo.findPrimAttrib("disp") is not None
    preview_mode = config.DISPLAY_MODES.index("hair_preview")
    keys, flags, factors, modes, captures, drags = [], [], [], [], [], []
    for prim in geo.iterPrims():
        lid = prim.intAttribValue(config.ATTR_LOCK_ID)
        disp = prim.intAttribValue("disp") if has_disp else config.DISPLAY_MODES.index(mode) \
            if mode in config.DISPLAY_MODES else len(config.DISPLAY_MODES) - 1
        # hairgen's density x this (strand_factor): the preview fraction for a lock shown as preview or
        # being dragged, else full; publishing is always full
        f = light if disp == preview_mode else 1.0
        drag = lid in dragged and not publishing
        if drag:
            f = min(f, drag_f)
        if publishing:
            f = 1.0
        factors.append(f)
        drags.append(int(drag))
        # a dragged lock's strands are coarser (DRAG_SEGMENTS): kept apart from its full hair
        lock_mode = "drag" if drag else "hair" if f >= 1.0 else "hair_preview"
        modes.append(lock_mode)
        cap = int(wired and (deforming or f >= 1.0))   # publish (full) reuses these; it drops the capture
        captures.append(cap)
        piece = prim.intAttribValue("piece") if geo.findPrimAttrib("piece") else -1
        idx = [p.number() for p in prim.points()]
        parts: list[Any] = [shared, [(a.name(), prim.attribValue(a)) for a in rattrs]]
        parts.extend(arr[idx].tobytes() for arr in parrays)
        parts.append(tuple(rk[lid * 9:lid * 9 + 9]) if lid >= 0 else ())
        parts.append(tuple(sk[piece * 9:piece * 9 + 9]) if piece >= 0 else ())
        parts.append(f)
        parts.append(cap)
        parts.append(int(drag))
        key = lock_key(parts)
        keys.append(key)
        flags.append(int(cache.has(sid, lid, lock_mode, key)))
    geo.setPrimStringAttribValues("cache_key", keys)
    geo.setPrimStringAttribValues("cache_mode", modes)
    geo.setPrimFloatAttribValues("strand_factor", factors)
    geo.setPrimIntAttribValues("do_capture", captures)
    geo.setPrimIntAttribValues("drag_seg", drags)
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


def _cached_hair(sop, with_prim: bool = False):
    """(lock id, name, frozen strands) of every lock that grows, from the cache; input 1 = keyed spines.
    with_prim: (lock id, name, frozen strands, its keyed spine prim)."""
    keyed = sop.inputs()[1].geometry()
    cache = hair_cache()
    sid = sop.parent().sessionId()
    grows = keyed.findPrimAttrib("grows") is not None
    named = keyed.findPrimAttrib(config.ATTR_NAME) is not None
    missing = 0
    for p in keyed.iterPrims():
        if grows and p.intAttribValue("grows") == 0:
            continue
        lid = p.intAttribValue(config.ATTR_LOCK_ID)
        g = cache.get(sid, lid, p.stringAttribValue("cache_mode"), p.stringAttribValue("cache_key"))
        if g is None:
            missing += 1
        else:
            name = p.stringAttribValue(config.ATTR_NAME) if named else ""
            yield (lid, name, g, p) if with_prim else (lid, name, g)
    if missing:
        sop.addWarning(f"{missing} locks have no hair in the cache: change Display and back to cook them")


def geo_stats(node, lock_ids: Sequence[int] | None = None) -> dict:
    """What the hair of these locks (None: every lock that grows) holds as the node shows it now: locks,
    prims (one strand each), points, and the attribute names by class. Read from the per-lock cache
    (geometry intrinsics, no copy), so it costs nothing to ask on every selection."""
    packed = _HAIR_PACKED_PATHS.get(node.sessionId())
    sop = hou.node(packed) if packed else None
    if sop is None:
        sop = next((n for n in node.allSubChildren() if n.name() == "hair_packed"), None)
        if sop is None:
            return {}
        _HAIR_PACKED_PATHS[node.sessionId()] = sop.path()
    want = None if lock_ids is None else {int(i) for i in lock_ids}
    cache = hair_cache()
    sid = node.sessionId()
    keyed = sop.inputs()[1].geometry()
    if keyed is None or keyed.findPrimAttrib("cache_key") is None:
        return {}
    grows = keyed.findPrimAttrib("grows") is not None
    out = {"locks": 0, "prims": 0, "points": 0, "attribs": {}, "mode": ""}
    for p in keyed.iterPrims():
        lid = p.intAttribValue(config.ATTR_LOCK_ID)
        if (want is not None and lid not in want) or (grows and p.intAttribValue("grows") == 0):
            continue
        g = cache.get(sid, lid, p.stringAttribValue("cache_mode"), p.stringAttribValue("cache_key"))
        if g is None:
            continue
        out["locks"] += 1
        out["prims"] += g.intrinsicValue("primitivecount")
        out["points"] += g.intrinsicValue("pointcount")
        out["mode"] = out["mode"] or p.stringAttribValue("cache_mode")
        if not out["attribs"]:
            out["attribs"] = {
                "point": sorted(a.name() for a in g.pointAttribs()),
                "prim": sorted(a.name() for a in g.primAttribs()),
                "vertex": sorted(a.name() for a in g.vertexAttribs()),
                "detail": sorted(a.name() for a in g.globalAttribs()),
            }
    return out


_HAIR_PACKED_PATHS: dict[int, str] = {}


def cook_hair_cache(sop) -> None:
    """Python SOP "hair_cache": the strands of every lock that grows (shown, not excluded; every lock
    while publishing), from the cache, merged (publish and the shot deform read this). Input 0 is the
    per-lock loop (it stored the missing ones), input 1 the keyed spines."""
    geo = sop.geometry()
    geo.clear()
    for _lid, _name, g in _cached_hair(sop):
        geo.merge(g)


def cook_hair_packed(sop) -> None:
    """Python SOP "hair_packed": the display's hair, one packed primitive per lock embedding its cached
    strands (no copy). Merging 4 M points into one geometry made every edit and every hide re-upload the
    whole groom to the viewport; packed, the viewport keeps the locks that did not change.
    Locks in `strand_ids` are drawn as strands (the viewport draws no width ramp inside a packed prim):
    their packed prim stays, empty, so every lock keeps prim number = its place among the packed prims
    and a viewport selection of packed locks still means the same locks; their strands come after."""
    geo = sop.geometry()
    geo.clear()
    lid_attr = geo.addAttrib(hou.attribType.Prim, config.ATTR_LOCK_ID, -1)
    name_attr = geo.addAttrib(hou.attribType.Prim, config.ATTR_NAME, "")
    by_group = int(sop.parent().evalParm("color_by")) == 1
    cache = hair_cache()
    sid = sop.parent().sessionId()
    every = strands_all(sop.parent())
    strands = set(strand_ids(sop.parent()))
    focus = set(focus_ids(sop.parent()))
    alpha = round(xray_opacity(sop.parent()), 4)
    empty = hou.Geometry().freeze(read_only=True) if strands or every else None
    unpacked = []
    for lid, name, g, sp in _cached_hair(sop, with_prim=True):
        # The viewport does not tint embedded geometry with the packed prim's Cd (it drew Helen white):
        # the colour goes inside, on a copy of the lock's strands made once per colour and kept in the
        # cache, so a colour change copies, an edit copies one lock, and nothing regrows.
        cd = tuple(round(c, 4) for c in sp.attribValue("group_cd" if by_group else "lock_cd"))
        mode, key = sp.stringAttribValue("cache_mode") + "#cd", f"{sp.stringAttribValue('cache_key')}|{cd}"
        coloured = cache.get(sid, lid, mode, key)
        if coloured is None:
            tinted = hou.Geometry()
            tinted.merge(g)
            tinted.addAttrib(hou.attribType.Prim, "Cd", (1.0, 1.0, 1.0))
            tinted.setPrimFloatAttribValues("Cd", cd * len(tinted.iterPrims()))
            coloured = tinted.freeze(read_only=True)
            cache.put(sid, lid, mode, key, coloured)
        prim = geo.createPacked("PackedGeometry")
        if every or lid in strands:   # hair_packed_color gives them their colour, or the see-through grey
            prim.setEmbeddedGeometry(empty)
            unpacked.append(coloured)
        elif focus and lid not in focus:
            # out of focus: see-through grey, a copy made once per colour and kept like the coloured one
            gkey = f"{key}|ghost|{alpha}"
            ghost = cache.get(sid, lid, mode, gkey)
            if ghost is None:
                m = config.GHOST_MIX
                gcd = tuple(c * (1 - m) + t * m for c, t in zip(cd, config.GHOST_TINT))
                tinted = hou.Geometry()
                tinted.merge(g)
                tinted.addAttrib(hou.attribType.Prim, "Cd", (1.0, 1.0, 1.0))
                tinted.addAttrib(hou.attribType.Prim, "Alpha", 1.0)
                n = len(tinted.iterPrims())
                tinted.setPrimFloatAttribValues("Cd", gcd * n)
                tinted.setPrimFloatAttribValues("Alpha", (alpha,) * n)
                ghost = tinted.freeze(read_only=True)
                cache.put(sid, lid, mode, gkey, ghost)
            prim.setEmbeddedGeometry(ghost)
        else:
            prim.setEmbeddedGeometry(coloured)
        prim.setAttribValue(lid_attr, lid)
        prim.setAttribValue(name_attr, name)
    for g in unpacked:  # the cached strands carry lock_id and name
        geo.merge(g)


def cook_frozen_regions(sop) -> None:
    """Python SOP "frozen regions": the split stored on the node's `regions` parm, or nothing."""
    geo = sop.geometry()
    geo.clear()
    frozen = sop.parent().parm(PARM_REGIONS).evalAsGeometry()
    if frozen is not None:
        geo.merge(frozen)


__all__ = [
    "find_nodes", "create_node", "read_data", "write_data", "write_data_live", "lock_infos", "detect", "split_regions",
    "set_display", "display_state", "selected_lock_ids", "select_locks", "publish_context", "publish",
    "undo", "set_isolate", "isolate_ids", "set_strands", "strand_ids", "geo_stats", "strands_all", "STRANDS_ALL", "cook_display", "set_focus", "focus_ids", "xray_opacity", "set_xray_opacity", "set_drag_preview", "deform_state", "set_shot_deform", "set_root_flip",
    "set_excluded",
]
