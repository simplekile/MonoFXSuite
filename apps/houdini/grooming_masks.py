"""
Density mask layers of MONO Grooming (v0.2a, docs/plans/grooming_v0_2.md): storage, the HDA's `mask_read`,
the brush and the layer functions of the adapter API. `grooming_adapter` re-exports what the panel uses.

Where things live: the layer list (name, on, mode, opacity, scope) in `groom_data` (`model.MaskLayer`), what
is painted in the node's hidden geometry parm `mask_layers`: one point per point of the fine scalp
(`SCALP_FINE`) with `P`, `uv` and per layer `mask_<id>_v` (value) and `mask_<id>_a` (coverage). Parms, so every
change is undoable and saved with the hip. A layer never painted has no attributes (coverage 0 everywhere).

In the network `mask_read` (Python SOP after the region split) blends the layers per scope set
(`logic.mask_scope_sets`) into point attributes `mask_<k>` and records, per lock, its set and a digest of the
factor on its own skin: the lock's cache key takes that digest, so a stroke regrows the locks under it only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Iterable, Sequence

try:
    import hou
except ImportError:
    hou = None  # type: ignore[assignment]

from tools.fx.grooming import config, logic, model

NODE_SCALP_FINE = "SCALP_FINE"
UNDO_PREFIX = "MONO Grooming: "
PUBLISH_MASK_FILE = "mask_layers.bgeo"     # next to grooming_data.json in vNNN/_grooming/
ATTR_SET_OF = "mask_set_of"       # detail int array by lock id: its scope set (-1: no layer reaches it)
ATTR_HASH_OF = "mask_hash_of"     # detail string array by lock id: digest of the factor on its skin
ATTR_SETS = "mask_sets"           # detail int: number of scope sets (0: no layer is on)
MOVED_TEXT = "Mask layers were painted on another scalp: moved over by UV, check them"
_ATTR_RE = re.compile(r"^mask_(\d+)_([va])$")


def _np():
    import numpy as np
    return np


# ---------------------------------------------------------------------------
# Pure helpers (no hou)
# ---------------------------------------------------------------------------

def values_digest(values) -> str:
    """Digest of one lock's mask values (a float32 array), "" when every one is exactly 1: that hair is the
    hair without a mask, so adding an empty layer, or painting elsewhere, regrows nothing."""
    np = _np()
    arr = np.ascontiguousarray(values, dtype=np.float32)
    if arr.size == 0 or bool((arr == 1.0).all()):
        return ""
    return hashlib.blake2b(arr.tobytes(), digest_size=8).hexdigest()


def points_by_lock(point_locks: Sequence[Sequence[int]]) -> dict[int, Any]:
    """Per lock id the scalp points of its region, ascending, from each point's lock list."""
    np = _np()
    out: dict[int, list[int]] = {}
    for i, locks in enumerate(point_locks):
        for lid in locks:
            out.setdefault(lid, []).append(i)
    return {lid: np.asarray(idx, dtype=np.int64) for lid, idx in out.items()}


def neighbour_table(neighbours: Sequence[Sequence[int]]):
    """(points, widest valence) int array of each point's neighbours, -1 where it has fewer."""
    np = _np()
    width = max((len(nb) for nb in neighbours), default=0)
    table = np.full((len(neighbours), max(width, 1)), -1, dtype=np.int64)
    for i, nb in enumerate(neighbours):
        table[i, :len(nb)] = nb
    return table


def shared_prim_neighbours(vertex_prim, vertex_point, points: int):
    """Neighbour table (`neighbour_table`'s shape) from two numbers per vertex, its prim and its point:
    two points are neighbours when one prim holds both. Plain numpy, any vertex order."""
    np = _np()
    vertex_prim = np.asarray(vertex_prim, dtype=np.int64)
    vertex_point = np.asarray(vertex_point, dtype=np.int64)
    if not len(vertex_prim):
        return np.full((points, 1), -1, dtype=np.int64)
    order = np.argsort(vertex_prim, kind="stable")
    vp = vertex_point[order]
    counts = np.bincount(vertex_prim)
    counts = counts[counts > 0]
    starts = np.concatenate(([0], np.cumsum(counts)[:-1]))
    a_all, b_all = [], []
    for j in range(int(counts.max())):
        for k in range(int(counts.max())):
            if j == k:
                continue
            ok = (counts > j) & (counts > k)
            a_all.append(vp[starts[ok] + j])
            b_all.append(vp[starts[ok] + k])
    pairs = np.unique(np.stack([np.concatenate(a_all), np.concatenate(b_all)], 1), axis=0)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    a, b = pairs[:, 0], pairs[:, 1]
    rank = np.arange(len(a)) - np.searchsorted(a, a)
    table = np.full((points, int(rank.max()) + 1 if len(rank) else 1), -1, dtype=np.int64)
    table[a, rank] = b
    return table


class ScalpBrush:
    """Which scalp points one dab reaches, and how strongly. Straight distance alone painted through thin
    parts (a dab by the ear reached the skin behind it): a dab takes the points inside its radius that face
    the way the skin under the cursor does (`config.BRUSH_FACING_DEG`) and are joined to it through such
    points. Plain numpy on P, N and the neighbour table; no hou."""

    def __init__(self, P, N, table):
        np = _np()
        self.P = np.asarray(P, dtype=np.float32)
        self.N = np.asarray(N, dtype=np.float32)
        self.table = table
        self.n = len(self.P)
        self.cos = float(np.cos(np.radians(config.BRUSH_FACING_DEG)))

    def reach(self, centre, radius: float, normal=None):
        """(point numbers, distance from the centre) of the points a dab at `centre` reaches. `normal`: the
        skin's normal under the cursor (None: that of the scalp point nearest the centre)."""
        np = _np()
        c = np.asarray(centre, dtype=np.float32)
        d2 = ((self.P - c) ** 2).sum(1)
        inside = d2 < radius * radius
        if not inside.any():
            return np.zeros(0, np.int64), np.zeros(0, np.float32)
        nearest = int(np.argmin(d2))
        nrm = self.N[nearest] if normal is None else np.asarray(normal, dtype=np.float32)
        length = float(np.sqrt((nrm ** 2).sum()))
        nrm = nrm / length if length > 1e-12 else self.N[nearest]
        ok = inside & ((self.N @ nrm) > self.cos)
        # seeds: the skin right under the cursor (a few points, so a seam of unshared points is crossed)
        seed_r2 = max(float(d2[nearest]) * 2.25, (0.3 * radius) ** 2)
        frontier = np.nonzero(ok & (d2 <= seed_r2))[0]
        reached = np.zeros(self.n, dtype=bool)
        reached[frontier] = True
        while frontier.size:
            nb = self.table[frontier].ravel()
            nb = nb[nb >= 0]
            nb = nb[ok[nb] & ~reached[nb]]
            if not nb.size:
                break
            frontier = np.unique(nb)
            reached[frontier] = True
        idx = np.nonzero(reached)[0]
        return idx, np.sqrt(d2[idx])


class MaskData:
    """What is painted, as numpy arrays on the current fine scalp: per layer id a value and a coverage per
    point. `moved`: it was painted on another scalp and brought over (`read_masks`)."""

    def __init__(self, P):
        np = _np()
        self.P = np.asarray(P, dtype=np.float32).reshape(-1, 3)
        self.n = len(self.P)
        self.v: dict[int, Any] = {}
        self.a: dict[int, Any] = {}
        self.moved = False

    def ensure(self, layer_id: int) -> None:
        np = _np()
        if layer_id not in self.v:
            self.v[layer_id] = np.ones(self.n, np.float32)
            self.a[layer_id] = np.zeros(self.n, np.float32)

    def drop(self, layer_id: int) -> None:
        self.v.pop(layer_id, None)
        self.a.pop(layer_id, None)

    def painted(self, layer_id: int) -> int:
        """Points of the layer with any coverage."""
        return int((self.a[layer_id] > 0).sum()) if layer_id in self.a else 0

    def factor(self, layers: Iterable[model.MaskLayer]):
        """The final factor per point through `layers` (bottom first; the ones that are off or never
        painted change nothing)."""
        np = _np()
        stack = [(m.mode, m.opacity, self.v[m.id], self.a[m.id]) for m in layers if m.on and m.id in self.v]
        return np.asarray(logic.mask_factor(stack, np.ones(self.n, np.float32)), dtype=np.float32)

    def dab(self, layer_id: int, idx, weight, value: float, erase: bool = False) -> None:
        self.ensure(layer_id)
        np = _np()
        paint = min(max(float(value), 0.0), config.MASK_VALUE_MAX)
        v, a = logic.mask_dab(self.v[layer_id][idx], self.a[layer_id][idx], np.asarray(weight, np.float32),
                              paint, erase)
        self.v[layer_id][idx] = v
        self.a[layer_id][idx] = a


def layers_for_view(masks: Sequence[model.MaskLayer], layer_id: int | None) -> list[model.MaskLayer]:
    """The layers whose blend the scalp shows while `layer_id` is painted: the "all locks" layers and the
    ones with the painted layer's own scope (what a lock in that scope gets). None: the "all locks" layers."""
    active = next((m for m in masks if m.id == layer_id), None)

    def same(m):
        return active is not None and (m.scope, m.group, m.locks) == (active.scope, active.group, active.locks)
    return [m for m in masks if m.scope == "all" or same(m)]


# ---------------------------------------------------------------------------
# hou: storage
# ---------------------------------------------------------------------------

def _read(node) -> model.GroomData:
    return model.GroomData.from_json(node.evalParm(config.DATA_PARM))


def _scalp(node):
    inner = node.node(NODE_SCALP_FINE)
    if inner is None:
        raise RuntimeError(f"{node.path()} has no {NODE_SCALP_FINE}: not a {config.HDA_LABEL} node of this version")
    return inner.geometry()


def _points(geo):
    np = _np()
    return np.frombuffer(geo.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3)


_DETAIL, _PRIM, _POINT, _VERTEX = 0, 1, 2, 3      # Attribute Promote's classes
_FIRST = 8                                         # ... and its "first match" method


def _promote(geo, name: str, from_class: int, to_class: int, method: int = _FIRST):
    """Attribute Promote as a SOP verb (no node is made; there is no wrangle verb): a copy of `geo` with
    `name` in the other class too."""
    verb = hou.sopNodeTypeCategory().nodeVerb("attribpromote")
    verb.setParms({"inname": name, "inclass": from_class, "outclass": to_class, "method": method, "deletein": 0})
    out = hou.Geometry()
    verb.execute(out, [geo])
    return out


def _vertex_tables(geo):
    """(prim number, point number) per vertex, read in bulk: one hou call per vertex of the fine scalp
    (97 k) took over a second."""
    np = _np()
    work = hou.Geometry(geo)
    n_pt, n_pr = work.intrinsicValue("pointcount"), work.intrinsicValue("primitivecount")
    work.addAttrib(hou.attribType.Point, "__pt", 0)
    work.setPointIntAttribValuesFromString("__pt", np.arange(n_pt, dtype=np.int32).tobytes())
    work.addAttrib(hou.attribType.Prim, "__pr", 0)
    work.setPrimIntAttribValuesFromString("__pr", np.arange(n_pr, dtype=np.int32).tobytes())
    work = _promote(_promote(work, "__pt", _POINT, _VERTEX), "__pr", _PRIM, _VERTEX)
    return (np.frombuffer(work.vertexIntAttribValuesAsString("__pr"), np.int32).astype(np.int64),
            np.frombuffer(work.vertexIntAttribValuesAsString("__pt"), np.int32).astype(np.int64))


def _point_uv(geo):
    """uv per point as (n, 3) float32, None when the geometry has none. A vertex uv gives each point the uv
    of its first vertex (a seam point has several; either side is as near in uv)."""
    np = _np()
    n = geo.intrinsicValue("pointcount")
    if geo.findPointAttrib("uv") is not None:
        raw = np.frombuffer(geo.pointFloatAttribValuesAsString("uv"), np.float32).reshape(n, -1)
    elif geo.findVertexAttrib("uv") is not None:
        work = hou.Geometry(geo)
        for attrib in work.pointAttribs():        # promote into a free name: only uv is wanted
            if attrib.name() not in ("P", "uv"):
                attrib.destroy()
        got = _promote(work, "uv", _VERTEX, _POINT)
        raw = np.frombuffer(got.pointFloatAttribValuesAsString("uv"), np.float32).reshape(n, -1)
    else:
        return None
    out = np.zeros((n, 3), np.float32)
    out[:, :min(raw.shape[1], 3)] = raw[:, :3]
    return out


def _cloud(positions):
    """Points only, at `positions` (n, 3)."""
    np = _np()
    geo = hou.Geometry()
    n = len(positions)
    if n:
        geo.createPoints(((0.0, 0.0, 0.0),) * n)
        geo.setPointFloatAttribValuesFromString("P", np.ascontiguousarray(positions, np.float32).tobytes())
    return geo


_NEAREST: dict[bytes, Any] = {}      # (digest of both point sets) -> indices; the last few transfers


def _nearest(to_positions, from_positions):
    """For each of `to_positions` the index of the nearest of `from_positions` (Houdini's point lookup).
    Kept by the two point sets: until the layers are stored on the new scalp, mask_read asks on every cook."""
    np = _np()
    a = np.ascontiguousarray(to_positions, np.float32)
    b = np.ascontiguousarray(from_positions, np.float32)
    key = hashlib.blake2b(a.tobytes() + b"|" + b.tobytes(), digest_size=16).digest()
    hit = _NEAREST.get(key)
    if hit is not None:
        return hit
    cloud = _cloud(b)
    src = np.fromiter((cloud.nearestPoint(hou.Vector3(float(p[0]), float(p[1]), float(p[2]))).number() for p in a),
                      dtype=np.int64, count=len(a))
    while len(_NEAREST) >= 4:
        del _NEAREST[next(iter(_NEAREST))]
    _NEAREST[key] = src
    return src


_BASE: dict[int, tuple[bytes, Any]] = {}     # node session id -> (digest of P, points with P and uv)


def _base(node, scalp):
    """The storage geometry without layers (points with P and uv of the fine scalp), kept per node while
    the scalp stays the same: a stroke's write copies it and adds the layers."""
    P = _points(scalp)
    key = hashlib.blake2b(P.tobytes(), digest_size=16).digest()
    hit = _BASE.get(node.sessionId())
    if hit is not None and hit[0] == key:
        return hit[1]
    geo = _cloud(P)
    uv = _point_uv(scalp)
    if uv is not None:
        geo.addAttrib(hou.attribType.Point, "uv", (0.0, 0.0, 0.0))
        geo.setPointFloatAttribValuesFromString("uv", uv.tobytes())
    geo = geo.freeze(read_only=True)
    _BASE[node.sessionId()] = (key, geo)
    return geo


def stored_layers(geo) -> dict[int, set[str]]:
    """Layer ids in a stored geometry with the parts each has ("v", "a")."""
    out: dict[int, set[str]] = {}
    if geo is None:
        return out
    for attrib in geo.pointAttribs():
        m = _ATTR_RE.match(attrib.name())
        if m:
            out.setdefault(int(m.group(1)), set()).add(m.group(2))
    return out


def read_masks(node, scalp=None, stored=None) -> MaskData:
    """What the node holds, on the current fine scalp. Stored on the same points it is read as it is; on
    another scalp (a new mesh version, another Region subdivisions) each point takes the stored point
    nearest in uv, or in space when either has no uv, and `moved` is set (`mask_problem` says it; the next
    write stores it on the new scalp)."""
    np = _np()
    scalp = scalp if scalp is not None else _scalp(node)
    md = MaskData(_points(scalp))
    if stored is None:
        parm = node.parm(config.MASK_PARM)
        stored = parm.evalAsGeometry() if parm is not None else None
    have = {i: p for i, p in stored_layers(stored).items() if p == {"v", "a"}}
    if not have:
        return md
    sn = stored.intrinsicValue("pointcount")
    sP = _points(stored)
    src = None
    if sn != md.n or not (np.array_equal(sP, md.P) or np.allclose(sP, md.P, atol=1e-6)):
        uv_new = _point_uv(scalp)
        uv_old = _point_uv(stored)
        src = _nearest(uv_new, uv_old) if uv_new is not None and uv_old is not None else _nearest(md.P, sP)
        md.moved = True
    for layer_id in have:
        v = np.frombuffer(stored.pointFloatAttribValuesAsString(config.MASK_VALUE_ATTR % layer_id), np.float32)
        a = np.frombuffer(stored.pointFloatAttribValuesAsString(config.MASK_COVER_ATTR % layer_id), np.float32)
        md.v[layer_id] = (v[src] if src is not None else v).copy()
        md.a[layer_id] = (a[src] if src is not None else a).copy()
    return md


def mask_geometry(node, md: MaskData, keep: Iterable[int] | None = None, scalp=None):
    """The geometry to store: the fine scalp's points with P, uv and each layer of `md` (only the ids in
    `keep` when given)."""
    np = _np()
    geo = hou.Geometry(_base(node, scalp if scalp is not None else _scalp(node)))
    want = None if keep is None else set(keep)
    for layer_id in sorted(md.v):
        if want is not None and layer_id not in want:
            continue
        for fmt, arr in ((config.MASK_VALUE_ATTR, md.v[layer_id]), (config.MASK_COVER_ATTR, md.a[layer_id])):
            geo.addAttrib(hou.attribType.Point, fmt % layer_id, 0.0)
            geo.setPointFloatAttribValuesFromString(fmt % layer_id, np.ascontiguousarray(arr, np.float32).tobytes())
    return geo


def _write(node, label: str, data: model.GroomData | None = None, md: MaskData | None = None) -> None:
    """One undo step: the layer list (`data`) and / or what is painted (`md`). Only what changed is set: a
    stroke leaves `groom_data` alone, so the spines do not recook."""
    with hou.undos.group(UNDO_PREFIX + label):
        if md is not None:
            keep = [m.id for m in (data or _read(node)).masks]
            node.parm(config.MASK_PARM).set(mask_geometry(node, md, keep))
        if data is not None:
            node.parm(config.DATA_PARM).set(data.to_json())


def _require_parm(node) -> None:
    if node.parm(config.MASK_PARM) is None:
        raise RuntimeError(f"{node.path()} was built before density masks: update MonoFX Suite's "
                           "mono_grooming.hdalc")


# ---------------------------------------------------------------------------
# hou: the HDA's mask_read
# ---------------------------------------------------------------------------

_REGION_POINTS: dict[int, tuple[bytes, dict]] = {}   # node session id -> (digest of the split, its tables)


def _region_tables(top, geo) -> dict:
    """Of the split on `geo`: "points" (per lock the scalp points of its region; a shared prim's points
    belong to each owner), "prims" (per lock its prims), "owners" (owners per prim), and the vertex tables
    ("vertex_prim", "vertex_point", "corners" per prim). Kept per node by a digest of the split
    (`lock_owner`, `share`, `owners_h` per prim): the split changes only on Update regions, the Python SOP
    cooks on every edit."""
    h = hashlib.blake2b(digest_size=16)
    for name in ("lock_owner", "share", "owners_h"):
        if geo.findPrimAttrib(name) is not None:
            h.update(geo.primIntAttribValuesAsString(name))
    h.update(str(geo.intrinsicValue("pointcount")).encode())
    key = h.digest()
    hit = _REGION_POINTS.get(top.sessionId())
    if hit is not None and hit[0] == key:
        return hit[1]
    np = _np()
    vertex_prim, vertex_point = _vertex_tables(geo)
    prims_of: dict[int, list[int]] = {}
    for pr, own in enumerate(geo.primIntListAttribValues("lock_owners")):
        for lock_id in own:
            prims_of.setdefault(lock_id, []).append(pr)
    by_lock = {}
    n_prims = geo.intrinsicValue("primitivecount")
    inside = np.zeros(n_prims, dtype=bool)
    owners = np.zeros(n_prims, dtype=np.float32)
    for lock_id, prims in prims_of.items():
        inside[:] = False
        inside[prims] = True
        owners[prims] += 1
        by_lock[lock_id] = np.unique(vertex_point[inside[vertex_prim]])
    tables = {"points": by_lock, "prims": {k: np.asarray(v, dtype=np.int64) for k, v in prims_of.items()},
              "owners": owners, "vertex_prim": vertex_prim, "vertex_point": vertex_point,
              "corners": np.maximum(np.bincount(vertex_prim, minlength=n_prims), 1).astype(np.float32)}
    _REGION_POINTS[top.sessionId()] = (key, tables)
    return tables


def cook_mask_read(sop) -> None:
    """Python SOP "mask_read", on the scalp with its split (after region_prims): per scope set the blended
    factor as point attribute `mask_<k>`, and the details `mask_sets`, `mask_set_of` (by lock id) and
    `mask_hash_of` (by lock id, a digest of the factor on that lock's own skin, "" where it is 1
    everywhere). With no layer on it adds nothing: the geometry, and so the groom, is v0.1's."""
    top = sop.parent()
    geo = sop.geometry()
    text = top.evalParm(config.DATA_PARM)
    parm = top.parm(config.MASK_PARM)
    if parm is None or not text or '"masks": []' in text:
        return
    data = model.GroomData.from_json(text)
    masks = [m for m in data.masks if m.on]
    if not masks:
        return
    stored = parm.evalAsGeometry()       # read even when nothing uses it: the node depends on the parm
    np = _np()
    md = read_masks(top, scalp=geo, stored=stored)
    if md.moved:
        sop.addWarning(MOVED_TEXT)
    sets, set_of = logic.mask_scope_sets(masks, [(lk.id, lk.group) for lk in data.locks])
    by_id = {m.id: m for m in masks}
    factors = []
    for k, ids in enumerate(sets):
        f = md.factor([by_id[i] for i in ids])
        factors.append(f)
        name = config.MASK_SET_ATTR % k
        if geo.findPointAttrib(name) is None:
            geo.addAttrib(hou.attribType.Point, name, 1.0)
        geo.setPointFloatAttribValuesFromString(name, f.tobytes())
    tables = _region_tables(top, geo)
    regions = tables["points"]
    top_id = max([lk.id for lk in data.locks] + [-1])
    set_list = [-1] * (top_id + 1)
    hash_list = [""] * (top_id + 1)
    for lock_id, k in set_of.items():
        if k < 0 or lock_id < 0:
            continue
        idx = regions.get(lock_id)
        digest = values_digest(factors[k][idx]) if idx is not None else ""
        if digest:      # a lock whose skin is all 1 reads no mask at all: the same hair, the same key
            set_list[lock_id] = k
            hash_list[lock_id] = digest
    # per prim the factor averaged over its owners (PREVIEW's expected strand count reads it)
    prim_mean = [np.bincount(tables["vertex_prim"], weights=f[tables["vertex_point"]],
                             minlength=len(tables["owners"])).astype(np.float32) / tables["corners"] for f in factors]
    mean = np.zeros(len(tables["owners"]), np.float32)
    for lock_id, prims in tables["prims"].items():
        k = set_list[lock_id] if 0 <= lock_id <= top_id else -1
        mean[prims] += prim_mean[k][prims] if k >= 0 else 1.0
    mean = np.where(tables["owners"] > 0, mean / np.maximum(tables["owners"], 1.0), 1.0).astype(np.float32)
    geo.addAttrib(hou.attribType.Prim, "mask_mean", 1.0)
    geo.setPrimFloatAttribValuesFromString("mask_mean", mean.tobytes())
    geo.addAttrib(hou.attribType.Global, ATTR_SETS, 0)
    geo.setGlobalAttribValue(ATTR_SETS, len(sets))
    geo.addArrayAttrib(hou.attribType.Global, ATTR_SET_OF, hou.attribData.Int)
    geo.setGlobalAttribValue(ATTR_SET_OF, set_list)
    geo.addArrayAttrib(hou.attribType.Global, ATTR_HASH_OF, hou.attribData.String)
    geo.setGlobalAttribValue(ATTR_HASH_OF, hash_list)


def lock_mask_shares(top, regions_geo) -> dict[int, float]:
    """Per lock id its masked skin area over its skin area (what its strand count is multiplied by), for the
    locks a layer reaches; `regions_geo` is SCALP_REGIONS. Empty when no layer is on."""
    if regions_geo is None or regions_geo.findGlobalAttrib(ATTR_SET_OF) is None:
        return {}
    np = _np()
    tables = _region_tables(top, regions_geo)
    set_of = regions_geo.intListAttribValue(ATTR_SET_OF)
    area = np.frombuffer(regions_geo.primFloatAttribValuesAsString("area_cm2"), np.float32)
    means: dict[int, Any] = {}
    out: dict[int, float] = {}
    for lock_id, prims in tables["prims"].items():
        k = set_of[lock_id] if 0 <= lock_id < len(set_of) else -1
        if k < 0 or not len(prims):
            continue
        if k not in means:
            f = np.frombuffer(regions_geo.pointFloatAttribValuesAsString(config.MASK_SET_ATTR % k), np.float32)
            means[k] = np.bincount(tables["vertex_prim"], weights=f[tables["vertex_point"]],
                                   minlength=len(area)) / tables["corners"]
        w = area[prims] / np.maximum(tables["owners"][prims], 1.0)
        out[lock_id] = float((means[k][prims] * w).sum() / max(float(w.sum()), 1e-12))
    return out


def lock_mask_keys(preview_geo) -> tuple[Sequence[int], Sequence[str]]:
    """(scope set by lock id, digest by lock id) as `mask_read` left them on the regions (PREVIEW passes
    the details on); empty when no layer is on."""
    if preview_geo is None or preview_geo.findGlobalAttrib(ATTR_SET_OF) is None:
        return (), ()
    return preview_geo.intListAttribValue(ATTR_SET_OF), preview_geo.stringListAttribValue(ATTR_HASH_OF)


# ---------------------------------------------------------------------------
# hou: the brush
# ---------------------------------------------------------------------------

_BRUSHES: dict[int, tuple[bytes, ScalpBrush]] = {}


def scalp_brush(node, scalp=None) -> ScalpBrush:
    """The brush data of the node's fine scalp (normals, neighbours), kept while the scalp stays the same."""
    np = _np()
    scalp = scalp if scalp is not None else _scalp(node)
    P = _points(scalp)
    key = hashlib.blake2b(P.tobytes(), digest_size=16).digest()
    hit = _BRUSHES.get(node.sessionId())
    if hit is not None and hit[0] == key:
        return hit[1]
    verb = hou.sopNodeTypeCategory().nodeVerb("normal")
    verb.setParms({"type": 0, "cuspangle": 180.0, "normalattrib": "N", "overridenormal": 1})   # point normals
    got = hou.Geometry()
    verb.execute(got, [scalp])
    N = np.frombuffer(got.pointFloatAttribValuesAsString("N"), np.float32).reshape(-1, 3)
    vertex_prim, vertex_point = _vertex_tables(scalp)
    brush = ScalpBrush(P, N, shared_prim_neighbours(vertex_prim, vertex_point, len(P)))
    _BRUSHES[node.sessionId()] = (key, brush)
    return brush


class PaintSession:
    """Painting one layer of one node: the layer data in numpy, dabs through the scalp's brush, one write
    (one undo step) a stroke. The viewer state and `mask_stroke` both paint through it, so a stroke made
    by a test is the stroke an artist makes."""

    def __init__(self, node, layer_id: int):
        _require_parm(node)
        self.node = node
        self.layer_id = int(layer_id)
        self.unit_cm = max(float(node.evalParm("unit_cm")), 1e-6)
        self.scalp = _scalp(node)
        self.brush = scalp_brush(node, self.scalp)
        self.reload()

    def reload(self) -> None:
        """What the node holds now (on entering, after an undo or any change from outside)."""
        self.data = _read(self.node)
        self.md = read_masks(self.node, self.scalp)
        self.dirty = False
        self._last = None

    def layer(self) -> model.MaskLayer | None:
        return self.data.mask(self.layer_id)

    def factor(self):
        """The factor the scalp shows while this layer is painted (`layers_for_view`)."""
        return self.md.factor(layers_for_view(self.data.masks, self.layer_id))

    def begin(self) -> None:
        self._last = None

    def dab(self, centre, normal=None, radius_cm: float = config.BRUSH_RADIUS_CM,
            value: float = config.BRUSH_VALUE, soft: float = config.BRUSH_SOFT, erase: bool = False) -> int:
        """One dab at `centre` (scene units, on the skin). Returns the points it reached."""
        radius = radius_cm / self.unit_cm
        idx, dist = self.brush.reach(centre, radius, normal)
        if len(idx):
            self.md.dab(self.layer_id, idx, logic.brush_weights(dist, radius, soft), value, erase)
            self.dirty = True
        return int(len(idx))

    def stroke_to(self, centre, normal=None, radius_cm: float = config.BRUSH_RADIUS_CM, **brush) -> int:
        """A dab at `centre` and, when the mouse moved far since the last one, dabs between (a quarter of
        the radius apart), so a fast drag leaves a line, not dots."""
        np = _np()
        c = np.asarray(centre, dtype=np.float64)
        hit = 0
        if self._last is not None:
            step = 0.25 * radius_cm / self.unit_cm
            gap = float(np.sqrt(((c - self._last) ** 2).sum()))
            n = int(gap / step) if step > 0 else 0
            for i in range(1, min(n, 200)):
                hit += self.dab(self._last + (c - self._last) * (i / n), normal, radius_cm, **brush)
        hit += self.dab(c, normal, radius_cm, **brush)
        self._last = c
        return hit

    def commit(self, label: str = "Paint mask") -> bool:
        """Store the stroke: one undo step. False when no dab landed (nothing is written)."""
        self._last = None
        if not self.dirty:
            return False
        _write(self.node, label, md=self.md)
        self.dirty = False
        return True


# ---------------------------------------------------------------------------
# Adapter API: layers (each one undo step)
# ---------------------------------------------------------------------------

def mask_add(node, name: str = "", mode: str = "multiply", opacity: float = 1.0, scope: str = "all",
             group: str = "", locks: Iterable[int] = ()) -> int:
    """A new layer on top of the stack, nothing painted. Returns its id."""
    _require_parm(node)
    if mode not in config.MASK_MODES or scope not in config.MASK_SCOPES:
        raise ValueError(f"mask layer mode {mode!r} / scope {scope!r}")
    data = _read(node)
    layer = data.add_mask(name, mode, opacity, scope, group, locks)
    _write(node, f"Add mask layer {layer.name}", data=data)
    return layer.id


def mask_remove(node, layer_id: int) -> bool:
    """Delete a layer and what is painted on it. False when there is no such layer."""
    data = _read(node)
    layer = data.mask(layer_id)
    if layer is None:
        return False
    data.remove_mask(layer_id)
    md = read_masks(node)
    md.drop(layer_id)
    _write(node, f"Delete mask layer {layer.name}", data=data, md=md)
    return True


def mask_move(node, layer_id: int, index: int) -> None:
    """Put a layer at place `index` of the stack (0 = bottom)."""
    data = _read(node)
    data.move_mask(layer_id, index)
    _write(node, "Reorder mask layers", data=data)


def mask_set(node, layer_id: int, name: str | None = None, on: bool | None = None, mode: str | None = None,
             opacity: float | None = None, scope: str | None = None, group: str | None = None,
             locks: Iterable[int] | None = None) -> bool:
    """Change a layer's row: any of name, on, mode, opacity, scope (with its group or locks). One undo
    step; False when nothing changed."""
    data = _read(node)
    layer = data.mask(layer_id)
    if layer is None:
        raise KeyError(layer_id)
    if mode is not None and mode not in config.MASK_MODES:
        raise ValueError(f"mask layer mode {mode!r}")
    if scope is not None and scope not in config.MASK_SCOPES:
        raise ValueError(f"mask layer scope {scope!r}")
    before = model.MaskLayer(**{**layer.__dict__, "locks": list(layer.locks)})
    if name is not None:
        layer.name = str(name)
    if on is not None:
        layer.on = bool(on)
    if mode is not None:
        layer.mode = mode
    if opacity is not None:
        layer.opacity = min(1.0, max(0.0, float(opacity)))
    if scope is not None:
        layer.scope = scope
    if group is not None:
        layer.group = str(group)
    if locks is not None:
        layer.locks = sorted({int(i) for i in locks})
    if layer == before:
        return False
    what = [k for k in ("name", "on", "mode", "opacity", "scope", "group", "locks")
            if getattr(layer, k) != getattr(before, k)]
    _write(node, f"Mask layer {layer.name}: {', '.join(what)}", data=data)
    return True


def mask_fill(node, layer_id: int, value: float = 1.0) -> None:
    """The whole layer painted `value` (coverage 1 everywhere)."""
    data = _read(node)
    layer = data.mask(layer_id)
    if layer is None:
        raise KeyError(layer_id)
    md = read_masks(node)
    md.ensure(layer_id)
    md.v[layer_id][:] = min(max(float(value), 0.0), config.MASK_VALUE_MAX)
    md.a[layer_id][:] = 1.0
    _write(node, f"Fill mask layer {layer.name}", md=md)


def mask_clear(node, layer_id: int) -> None:
    """Nothing painted on the layer any more (coverage 0 everywhere); the layer stays."""
    data = _read(node)
    layer = data.mask(layer_id)
    if layer is None:
        raise KeyError(layer_id)
    md = read_masks(node)
    md.drop(layer_id)
    _write(node, f"Clear mask layer {layer.name}", md=md)


def mask_values(node, layer_id: int):
    """(value, coverage) per fine-scalp point of a layer, as numpy arrays (ones / zeros when unpainted)."""
    md = read_masks(node)
    md.ensure(layer_id)
    return md.v[layer_id], md.a[layer_id]


def mask_factor(node, lock_id: int | None = None):
    """The final factor per fine-scalp point: for one lock (the layers that reach it), or of the "all
    locks" layers when `lock_id` is None."""
    data = _read(node)
    md = read_masks(node)
    if lock_id is None:
        return md.factor([m for m in data.masks if m.scope == "all"])
    lk = data.lock(lock_id)
    group = lk.group if lk is not None else ""
    return md.factor([m for m in data.masks if m.applies(lock_id, group)])


def mask_stroke(node, layer_id: int, points: Sequence[Sequence[float]], radius_cm: float = config.BRUSH_RADIUS_CM,
                value: float = config.BRUSH_VALUE, soft: float = config.BRUSH_SOFT, erase: bool = False,
                normals: Sequence[Sequence[float]] | None = None) -> int:
    """One stroke through `points` (on the skin, scene units) as the brush would paint it; one undo step.
    Returns the dabs that reached skin."""
    if _read(node).mask(layer_id) is None:
        raise KeyError(layer_id)
    session = PaintSession(node, layer_id)
    session.begin()
    landed = 0
    for i, p in enumerate(points):
        nrm = normals[i] if normals is not None else None
        landed += int(session.stroke_to(p, nrm, radius_cm, value=value, soft=soft, erase=erase) > 0)
    session.commit("Erase mask" if erase else "Paint mask")
    return landed


def mask_problem(node) -> str:
    """What the artist should know about the stored layers, "" when nothing: they were painted on another
    scalp and moved over. (A warning inside the locked HDA never reaches the node, so the panel asks.)"""
    parm = node.parm(config.MASK_PARM)
    if parm is None or parm.evalAsGeometry() is None:
        return ""
    return MOVED_TEXT if read_masks(node).moved else ""


def mask_rebake(node) -> bool:
    """Store layers that were moved over from another scalp on the current one (one undo step); False when
    they already are."""
    md = read_masks(node)
    if not md.moved:
        return False
    _write(node, "Move mask layers to the new scalp", md=md)
    return True


# ---------------------------------------------------------------------------
# Adapter API: Paint mode (the viewer state is apps/houdini/grooming_paint_state.py)
# ---------------------------------------------------------------------------

# The panel's hooks (set by its controller): "stroke"(node) after a stroke is stored, to cook inside the
# panel's loading line (None: the state cooks the node itself); "exit"() when Paint ends without the panel
HOOKS: dict[str, Any] = {"stroke": None, "exit": None}
BRUSH: dict[str, Any] = {"radius_cm": config.BRUSH_RADIUS_CM, "value": config.BRUSH_VALUE,
                         "soft": config.BRUSH_SOFT, "erase": False, "xray": False}
PAINT: dict[str, Any] = {"node": None, "layer": None}    # node path and layer id while Paint is on


def set_brush(radius_cm: float | None = None, value: float | None = None, soft: float | None = None,
              erase: bool | None = None, xray: bool | None = None) -> dict:
    """Brush settings of the session (not saved, no undo): radius in cm, the value painted (a factor on the
    automatic density), the soft share of the radius, erase, and the scalp's X-ray. Returns them all."""
    if radius_cm is not None:
        BRUSH["radius_cm"] = min(max(float(radius_cm), 0.05), 50.0)
    if value is not None:
        BRUSH["value"] = min(max(float(value), 0.0), config.MASK_VALUE_MAX)
    if soft is not None:
        BRUSH["soft"] = min(max(float(soft), 0.0), 1.0)
    if erase is not None:
        BRUSH["erase"] = bool(erase)
    if xray is not None:
        BRUSH["xray"] = bool(xray)
    if hou is not None and hou.isUIAvailable():
        from apps.houdini import grooming_paint_state
        grooming_paint_state.brush_changed()
    return dict(BRUSH)


def brush() -> dict:
    return dict(BRUSH)


def paint_layer(node) -> int | None:
    """The layer being painted on this node, None when Paint is off."""
    return PAINT["layer"] if node is not None and PAINT["node"] == node.path() else None


def paint_enter(node, layer_id: int) -> bool:
    """Paint on: the viewport's tool becomes the mask brush on this layer. False without a UI or a Scene
    Viewer (the layer functions and `mask_stroke` work without one)."""
    _require_parm(node)
    if _read(node).mask(layer_id) is None:
        raise KeyError(layer_id)
    PAINT["node"], PAINT["layer"] = node.path(), int(layer_id)
    if hou is None or not hou.isUIAvailable():
        return False
    from apps.houdini import grooming_paint_state
    return grooming_paint_state.enter(node)


def paint_exit(node=None) -> None:
    """Paint off: back to the tool the viewport had."""
    PAINT["node"], PAINT["layer"] = None, None
    if hou is not None and hou.isUIAvailable():
        from apps.houdini import grooming_paint_state
        grooming_paint_state.leave()


# ---------------------------------------------------------------------------
# Publish: the layers go with the tool data and can be read back
# ---------------------------------------------------------------------------

def publish_masks(node, staged, tool_dir: str) -> dict:
    """Stage what is painted next to grooming_data.json (`mask_layers.bgeo`); the record for publish.json.
    {} when the groom has no layer."""
    data = _read(node)
    if not data.masks:
        return {}
    md = read_masks(node)
    final = os.path.join(tool_dir, PUBLISH_MASK_FILE).replace("\\", "/")
    mask_geometry(node, md, [m.id for m in data.masks]).saveToFile(staged.stage(final))
    return {"file": PUBLISH_MASK_FILE, "layers": [m.id for m in data.masks], "points": md.n,
            "painted": {str(m.id): md.painted(m.id) for m in data.masks}}


def masks_from_publish(tool_dir: str) -> tuple[list[model.MaskLayer], Any]:
    """(layers, stored geometry or None) of a publish's `_grooming/` folder, read from its JSON records."""
    with open(os.path.join(tool_dir, "grooming_data.json"), encoding="utf-8") as fh:
        data = model.GroomData.from_json(fh.read())
    geo = None
    record_path = os.path.join(tool_dir, "publish.json")
    name = ""
    if os.path.isfile(record_path):
        with open(record_path, encoding="utf-8") as fh:
            name = (json.load(fh).get("masks") or {}).get("file", "")
    if name and os.path.isfile(os.path.join(tool_dir, name)):
        geo = hou.Geometry()
        geo.loadFromFile(os.path.join(tool_dir, name).replace("\\", "/"))
    return data.masks, geo


def import_masks(node, tool_dir: str) -> int:
    """Replace the node's layers by a publish's (its `_grooming/` folder). One undo step; returns how many
    layers came in. Painted on another scalp, they are moved over by uv."""
    _require_parm(node)
    layers, geo = masks_from_publish(tool_dir)
    data = _read(node)
    data.masks = layers
    data.mask_id_high = max([data.mask_id_high] + [m.id for m in layers])
    md = read_masks(node, stored=geo) if geo is not None else MaskData(_points(_scalp(node)))
    _write(node, "Mask layers from a publish", data=data, md=md)
    return len(layers)


__all__ = [
    "mask_add", "mask_remove", "mask_move", "mask_set", "mask_fill", "mask_clear", "mask_values", "mask_factor",
    "mask_stroke", "mask_problem", "mask_rebake", "set_brush", "brush", "paint_enter", "paint_exit",
    "paint_layer", "import_masks", "masks_from_publish",
]
