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


def view_colours(view: str, factor, value=None, coverage=None, density=None, reference: float = 1.0):
    """(n, 3) float32 colours of the scalp for a view (config.MASK_VIEWS), on arrays: the rules of
    logic.mask_color / density_color / layer_color. `factor`: the final factor per point; `value`,
    `coverage`: the painted layer's ("layer"); `density`: strands / cm2 per point and `reference` the
    density the ramp is centred on ("density"); "roots" is one plain colour (the dots carry it)."""
    np = _np()

    def by_factor(m):
        m = np.asarray(m, np.float32)
        lo = np.clip(1.0 - m, 0.0, 1.0)[:, None]
        hi = np.clip(m - 1.0, 0.0, 1.0)[:, None]
        one = np.array(logic.MASK_COLOR_ONE, np.float32)
        return one + (np.array(logic.MASK_COLOR_ZERO, np.float32) - one) * lo \
            + (np.array(logic.MASK_COLOR_MORE, np.float32) - one) * hi

    if view == "roots":
        return np.tile(np.array(logic.LAYER_UNPAINTED, np.float32) * 2.0, (len(factor), 1)).astype(np.float32)
    if view == "layer" and coverage is not None:
        k = np.clip(np.asarray(coverage, np.float32), 0.0, 1.0)[:, None]
        dark = np.array(logic.LAYER_UNPAINTED, np.float32)
        top = by_factor(value) if value is not None else np.ones(3, np.float32)     # a mask: white
        return (dark + (top - dark) * k).astype(np.float32)
    if view == "density" and density is not None:
        ramp = np.array(logic.DENSITY_RAMP, np.float32)
        stops = np.array(logic.DENSITY_STOPS, np.float32)
        t = np.clip(np.asarray(density, np.float32) / max(reference, 1e-9), 0.0, stops[-1])
        i = np.clip(np.searchsorted(stops, t, side="right") - 1, 0, len(stops) - 2)
        f = ((t - stops[i]) / (stops[i + 1] - stops[i]))[:, None]
        return (ramp[i] + (ramp[i + 1] - ramp[i]) * f).astype(np.float32)
    return by_factor(factor).astype(np.float32)


def root_density(points, point_area_cm2, roots, cell: float):
    """Pure: roots / cm2 at each scalp point, counted over the skin round it: roots and skin area are
    summed in boxes of 3 x 3 x 3 cells of `cell` (scene units), and the density at a point is the roots over
    the skin area of its box. Counting both in the same box keeps it right on curved skin, at the scalp's
    edge and on slivers. `points`, `roots`: (n, 3) in scene units; `point_area_cm2`: each point's share of
    the skin."""
    np = _np()
    P = np.asarray(points, np.float64).reshape(-1, 3)
    if not len(P):
        return np.zeros(0, np.float32)
    lo = P.min(0) - cell
    shape = (np.ceil((P.max(0) + cell - lo) / cell).astype(int) + 1)

    def cells(x):
        return tuple(np.clip(np.floor((x - lo) / cell).astype(int), 0, shape - 1).T)

    area = np.zeros(shape)
    np.add.at(area, cells(P), np.asarray(point_area_cm2, np.float64))
    count = np.zeros(shape)
    R = np.asarray(roots, np.float64).reshape(-1, 3)
    if len(R):
        R = R[((R >= lo) & (R < lo + shape * cell)).all(1)]
        np.add.at(count, cells(R), 1.0)

    def box(a):
        p = np.pad(a, 1)
        out = np.zeros_like(a)
        for i in range(3):
            for j in range(3):
                for k in range(3):
                    out += p[i:i + a.shape[0], j:j + a.shape[1], k:k + a.shape[2]]
        return out

    dens = box(count) / np.maximum(box(area), 1e-9)
    return dens[cells(P)].astype(np.float32)


class MaskData:
    """What is painted, as numpy arrays on the current fine scalp. Per layer id `a`: its mask (a fill layer
    or a folder: where it applies, white 1 / black 0) or its coverage (a paint layer); `v`: a paint layer's
    value per point. A layer with no array was never painted: a fill or paint layer applies nowhere (black),
    a folder everywhere (it has no mask). `moved`: painted on another scalp and brought over (`read_masks`)."""

    def __init__(self, P):
        np = _np()
        self.P = np.asarray(P, dtype=np.float32).reshape(-1, 3)
        self.n = len(self.P)
        self.v: dict[int, Any] = {}
        self.a: dict[int, Any] = {}
        self.moved = False

    def ensure(self, layer_id: int, kind: str = "paint") -> None:
        """Arrays for a layer about to be painted (a folder's mask starts white, the others' black)."""
        np = _np()
        if layer_id not in self.a:
            self.a[layer_id] = (np.ones if kind == "folder" else np.zeros)(self.n, np.float32)
        if kind == "paint" and layer_id not in self.v:
            self.v[layer_id] = np.ones(self.n, np.float32)

    def drop(self, layer_id: int) -> None:
        self.v.pop(layer_id, None)
        self.a.pop(layer_id, None)

    def painted(self, layer_id: int) -> int:
        """Points of the layer with any mask / coverage."""
        return int((self.a[layer_id] > 0).sum()) if layer_id in self.a else 0

    def mask(self, layer):
        """The layer's mask per point (see the class: black, or white for a folder, when never painted)."""
        np = _np()
        if layer.id in self.a:
            return self.a[layer.id]
        return (np.ones if layer.kind == "folder" else np.zeros)(self.n, np.float32)

    def factor(self, layers: Iterable[model.MaskLayer], density: float | None = None):
        """The final factor per point through `layers` (bottom first, folders with their layers;
        `logic.mask_compose`). `density`: the density of the lock it is for, which a fill layer in
        strands / cm2 is divided by (`logic.mask_layer_value`)."""
        np = _np()
        rows = []
        for m in layers:
            if m.kind == "paint":
                value = self.v.get(m.id, 1.0)
            else:
                value = logic.mask_layer_value(m, density)
            rows.append((m, value, self.mask(m)))
        return np.asarray(logic.mask_compose(rows, np.ones(self.n, np.float32)), dtype=np.float32)

    def dab(self, layer_id: int, idx, weight, value: float, erase: bool = False, kind: str = "paint",
            level: float = 1.0) -> None:
        """One dab. A paint layer: `logic.mask_dab` with the brush `value`. A fill layer or a folder: its
        mask moves towards `level` (1 white, 0 black; erase paints black) by the brush weight."""
        self.ensure(layer_id, kind)
        np = _np()
        w = np.asarray(weight, np.float32)
        if kind != "paint":
            grey = 0.0 if erase else min(max(float(level), 0.0), 1.0)
            a = self.a[layer_id][idx]
            self.a[layer_id][idx] = a + (grey - a) * w
            return
        paint = min(max(float(value), 0.0), config.MASK_VALUE_MAX)
        v, a = logic.mask_dab(self.v[layer_id][idx], self.a[layer_id][idx], w, paint, erase)
        self.v[layer_id][idx] = v
        self.a[layer_id][idx] = a


def layers_for_view(masks: Sequence[model.MaskLayer], layer_id: int | None) -> list[model.MaskLayer]:
    """The layers whose blend the scalp shows while `layer_id` is painted: the "all locks" layers, the ones
    with the painted layer's own scope (what a lock in that scope gets) and the folders. None: the "all
    locks" layers and the folders."""
    active = next((m for m in masks if m.id == layer_id), None)

    def same(m):
        return active is not None and (m.scope, m.group, m.locks) == (active.scope, active.group, active.locks)
    return [m for m in masks if m.kind == "folder" or m.scope == "all" or same(m)]


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
    have = {i: p for i, p in stored_layers(stored).items() if "a" in p}
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
    for layer_id, parts in have.items():
        a = np.frombuffer(stored.pointFloatAttribValuesAsString(config.MASK_COVER_ATTR % layer_id), np.float32)
        md.a[layer_id] = (a[src] if src is not None else a).copy()
        if "v" in parts:
            v = np.frombuffer(stored.pointFloatAttribValuesAsString(config.MASK_VALUE_ATTR % layer_id), np.float32)
            md.v[layer_id] = (v[src] if src is not None else v).copy()
    return md


def mask_geometry(node, md: MaskData, keep: Iterable[int] | None = None, scalp=None):
    """The geometry to store: the fine scalp's points with P, uv and each layer of `md` (only the ids in
    `keep` when given)."""
    np = _np()
    geo = hou.Geometry(_base(node, scalp if scalp is not None else _scalp(node)))
    want = None if keep is None else set(keep)
    for layer_id in sorted(md.a):
        if want is not None and layer_id not in want:
            continue
        parts = [(config.MASK_COVER_ATTR, md.a[layer_id])]
        if layer_id in md.v:
            parts.insert(0, (config.MASK_VALUE_ATTR, md.v[layer_id]))
        for fmt, arr in parts:
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
    sets, set_of = logic.mask_scope_keys(
        data.masks, [(lk.id, lk.group, data.resolve(lk.id)["density"]) for lk in data.locks])
    by_id = {m.id: m for m in data.masks}
    factors = []
    for k, (ids, density) in enumerate(sets):
        f = md.factor([by_id[i] for i in ids], density)
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


def strand_roots(points, strands: int):
    """Pure: the root of each strand (its first point) from a lock's points, (strands, 3). Every strand of
    one lock has the same number of points and they are stored strand after strand; None when they are not."""
    np = _np()
    pts = np.asarray(points, np.float32).reshape(-1, 3)
    if strands <= 0 or len(pts) % strands:
        return None
    return pts[::len(pts) // strands]


def display_roots(node, cook: bool = True):
    """(root positions (n, 3) of the groom at full density, whether every lock that grows was there).
    Read from the per-lock cache (no copy of the strands): a lock the display holds as full hair is taken
    from there; for the others (Guides, Mesh, Hair preview, hidden) output 1's rest groom is used, and with
    `cook` it is cooked first, which grows them once (v0.1: about 0.2 s a lock). Without `cook` nothing
    cooks: locks whose hair is not in the cache are left out and the answer says the set is not whole."""
    np = _np()
    from apps.houdini import grooming_adapter as ga
    cache = ga.hair_cache()
    sid = node.sessionId()

    def rows(name, cooked=True):
        sop = node.node(name)
        if sop is None:
            return {}
        if not cooked and sop.needsToCook():
            return None
        geo = sop.geometry()
        if geo is None or geo.findPrimAttrib("cache_key") is None:
            return {}
        grows = geo.primIntAttribValues("grows") if geo.findPrimAttrib("grows") is not None else None
        factor = geo.primFloatAttribValues("strand_factor")
        return {lock_id: (mode, key, grows is None or bool(grows[i]), factor[i] >= 1.0) for i, (lock_id, mode, key) in
                enumerate(zip(geo.primIntAttribValues(config.ATTR_LOCK_ID), geo.primStringAttribValues("cache_mode"),
                              geo.primStringAttribValues("cache_key")))}

    def held(where):
        return where is not None and cache.get(sid, lock_id, where[0], where[1]) is not None

    shown = {k: v for k, v in (rows("lock_keys") or {}).items() if v[2] and v[3]}
    rest = node.node("GROOM_REST")
    if rest is not None and cook:
        rest.cook()                       # grows what the display does not hold in full
    full = rows("groom_keys", cooked=cook) if rest is not None else {}
    if full is None:                      # output 1's keys are out of date and we may not cook: only the display's
        full, whole = {}, False
    else:
        whole = True
    out = []
    wanted = {k for k, v in full.items() if v[2]} or set(shown)
    for lock_id in wanted:
        where = shown.get(lock_id)
        if not held(where):
            where = full.get(lock_id)
        if not held(where):
            whole = False
            continue
        geo = cache.get(sid, lock_id, where[0], where[1])
        roots = strand_roots(np.frombuffer(geo.pointFloatAttribValuesAsString("P"), np.float32),
                             geo.intrinsicValue("primitivecount"))
        if roots is not None:
            out.append(roots)
    return (np.concatenate(out) if out else np.zeros((0, 3), np.float32)), bool(whole and wanted)


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
        self.kind = "paint"
        self.scalp = _scalp(node)
        self.brush = scalp_brush(node, self.scalp)
        self.roots = _np().zeros((0, 3), _np().float32)
        self.actual = None
        self.whole = False
        self.reload()

    def reload(self) -> None:
        """What the node holds now (on entering, after an undo or any change from outside)."""
        self.data = _read(self.node)
        layer = self.data.mask(self.layer_id)
        self.kind = layer.kind if layer is not None else "paint"
        self.md = read_masks(self.node, self.scalp)
        self.dirty = False
        self._last = None

    def layer(self) -> model.MaskLayer | None:
        return self.data.mask(self.layer_id)

    def factor(self):
        """The factor the scalp shows while this layer is painted (`layers_for_view`)."""
        reference = float(self.data.defaults.get("density", model.BUILTIN_DEFAULTS["density"]))
        return self.md.factor(layers_for_view(self.data.masks, self.layer_id), reference)

    def base_density(self):
        """(automatic density per scalp point in strands / cm2, the groom's default density, each point's
        share of the skin in cm2). From the split's prims (`density`: the mean of a prim's owners;
        `area_cm2`), spread onto the points; read once a session, a settings edit while painting is not
        followed."""
        if getattr(self, "_base", None) is None:
            np = _np()
            regions = self.node.node("SCALP_REGIONS").geometry()
            dens = np.frombuffer(regions.primFloatAttribValuesAsString("density"), np.float32)
            area = np.frombuffer(regions.primFloatAttribValuesAsString("area_cm2"), np.float32)
            vertex_prim, vertex_point = _vertex_tables(regions)
            n = len(self.md.P)
            corners = np.maximum(np.bincount(vertex_prim, minlength=len(area)), 1)
            total = np.bincount(vertex_point, weights=dens[vertex_prim], minlength=n)
            count = np.maximum(np.bincount(vertex_point, minlength=n), 1)
            point_area = np.bincount(vertex_point, weights=(area / corners)[vertex_prim], minlength=n)
            reference = float(self.data.defaults.get("density", model.BUILTIN_DEFAULTS["density"]))
            self._base = ((total / count).astype(np.float32), reference, point_area.astype(np.float32))
        return self._base

    def measure(self, cook: bool) -> bool:
        """Count the groom's roots: `roots` (their positions), `actual` (roots / cm2 per scalp point) and
        the factor they were grown with. With `cook` the locks whose full hair is not in the cache are
        grown first (output 1); without it they are left out, and when any is missing nothing is kept
        (`actual` None: the density view then shows what is asked). True when the whole groom was counted."""
        roots, whole = display_roots(self.node, cook=cook)
        self.roots = roots
        self.whole = whole
        if not whole:
            self.actual = None
            return False
        _base, _reference, point_area = self.base_density()
        self.actual = root_density(self.md.P, point_area, roots, config.ROOT_DENSITY_CELL_CM / self.unit_cm)
        self.actual_factor = self.factor().copy()
        return True

    def density(self):
        """Strands / cm2 per scalp point for the "density" view: the roots as counted (`measure`), times
        how far the factor has moved since (a stroke in progress shows at once what it asks of the hair it
        is over); the density asked where no roots are known or the factor was 0."""
        np = _np()
        base, _reference, _area = self.base_density()
        factor = self.factor()
        asked = base * factor
        if getattr(self, "actual", None) is None:
            return asked
        was = self.actual_factor
        return np.where(was > 1e-6, self.actual * factor / np.maximum(was, 1e-6), asked).astype(np.float32)

    def colours(self, view: str):
        """The scalp's colours for a view (config.MASK_VIEWS). "layer": a paint layer shows its values where
        it has coverage; a fill layer or a folder its mask, white where it applies."""
        density = self.density() if view == "density" else None
        reference = self.base_density()[1] if view == "density" else 1.0
        layer = self.layer()
        mask = self.md.mask(layer) if layer is not None else None
        value = self.md.v.get(self.layer_id) if self.kind == "paint" else None
        return view_colours(view, self.factor(), value, mask, density, reference)

    def begin(self) -> None:
        self._last = None

    def dab(self, centre, normal=None, radius_cm: float = config.BRUSH_RADIUS_CM,
            value: float = config.BRUSH_VALUE, soft: float = config.BRUSH_SOFT, erase: bool = False,
            level: float = 1.0) -> int:
        """One dab at `centre` (scene units, on the skin). A paint layer takes the brush `value`; a fill
        layer or a folder has its mask painted towards `level` (1 white, 0 black; erase = black). Returns
        the points it reached."""
        radius = radius_cm / self.unit_cm
        idx, dist = self.brush.reach(centre, radius, normal)
        if len(idx):
            self.md.dab(self.layer_id, idx, logic.brush_weights(dist, radius, soft), value, erase, self.kind, level)
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
             group: str = "", locks: Iterable[int] = (), kind: str = "fill", value: float = 1.0,
             unit: str = "factor", parent: int | None = None) -> int:
    """A new layer on top of the stack. `kind` (config.MASK_KINDS): "fill" one `value` (a factor, or with
    `unit` "density" strands / cm2) and a black mask to paint white where it applies; "paint" a value
    painted per point; "folder" holds layers (`parent`), with a mask and opacity over them all. Nothing
    changes in the hair until something is painted. Returns its id."""
    _require_parm(node)
    if mode not in config.MASK_MODES or scope not in config.MASK_SCOPES:
        raise ValueError(f"mask layer mode {mode!r} / scope {scope!r}")
    if kind not in config.MASK_KINDS or unit not in config.MASK_UNITS:
        raise ValueError(f"mask layer kind {kind!r} / unit {unit!r}")
    data = _read(node)
    layer = data.add_mask(name, mode, opacity, scope, group, locks, kind, value, unit, parent)
    _write(node, f"Add mask {'folder' if kind == 'folder' else 'layer'} {layer.name}", data=data)
    return layer.id


def mask_remove(node, layer_id: int) -> bool:
    """Delete a layer and what is painted on it; a folder's layers stay, out of it. False when there is no
    such layer."""
    data = _read(node)
    layer = data.mask(layer_id)
    if layer is None:
        return False
    data.remove_mask(layer_id)
    md = read_masks(node)
    md.drop(layer_id)
    _write(node, f"Delete mask layer {layer.name}", data=data, md=md)
    return True


def mask_move(node, layer_id: int, index: int, parent: int | None | str = "keep") -> None:
    """Put a layer at place `index` of the stack (0 = bottom) and, when `parent` is given, into that
    folder (None: out of any)."""
    data = _read(node)
    data.move_mask(layer_id, index)
    if parent != "keep":
        data.set_mask_parent(layer_id, parent)
    _write(node, "Reorder mask layers", data=data)


def mask_set(node, layer_id: int, name: str | None = None, on: bool | None = None, mode: str | None = None,
             opacity: float | None = None, scope: str | None = None, group: str | None = None,
             locks: Iterable[int] | None = None, value: float | None = None, unit: str | None = None) -> bool:
    """Change a layer's row: any of name, on, mode, opacity, scope (with its group or locks), a fill
    layer's value and unit. One undo step; False when nothing changed."""
    data = _read(node)
    layer = data.mask(layer_id)
    if layer is None:
        raise KeyError(layer_id)
    if mode is not None and mode not in config.MASK_MODES:
        raise ValueError(f"mask layer mode {mode!r}")
    if scope is not None and scope not in config.MASK_SCOPES:
        raise ValueError(f"mask layer scope {scope!r}")
    if unit is not None and unit not in config.MASK_UNITS:
        raise ValueError(f"mask layer unit {unit!r}")
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
    if value is not None:
        layer.value = max(0.0, float(value))
    if unit is not None:
        layer.unit = unit
    if layer == before:
        return False
    what = [k for k in ("name", "on", "mode", "opacity", "scope", "group", "locks", "value", "unit")
            if getattr(layer, k) != getattr(before, k)]
    _write(node, f"Mask layer {layer.name}: {', '.join(what)}", data=data)
    return True


def _layer_or_raise(data: model.GroomData, layer_id: int) -> model.MaskLayer:
    layer = data.mask(layer_id)
    if layer is None:
        raise KeyError(layer_id)
    return layer


def mask_fill(node, layer_id: int, value: float = 1.0) -> None:
    """A fill layer or a folder: its whole mask at `value` (1 = a white mask: it applies everywhere).
    A paint layer: the whole layer painted `value`, coverage 1."""
    data = _read(node)
    layer = _layer_or_raise(data, layer_id)
    md = read_masks(node)
    md.ensure(layer_id, layer.kind)
    if layer.kind == "paint":
        md.v[layer_id][:] = min(max(float(value), 0.0), config.MASK_VALUE_MAX)
        md.a[layer_id][:] = 1.0
    else:
        md.a[layer_id][:] = min(max(float(value), 0.0), 1.0)
    _write(node, f"Fill mask layer {layer.name}", md=md)


def mask_clear(node, layer_id: int) -> None:
    """Nothing painted on the layer any more; the layer stays. A fill or paint layer then applies nowhere
    (a black mask), a folder everywhere (no mask)."""
    data = _read(node)
    layer = _layer_or_raise(data, layer_id)
    md = read_masks(node)
    md.drop(layer_id)
    _write(node, f"Clear mask layer {layer.name}", md=md)


def mask_invert(node, layer_id: int) -> None:
    """Invert the layer's mask (white <-> black; a paint layer's coverage)."""
    data = _read(node)
    layer = _layer_or_raise(data, layer_id)
    md = read_masks(node)
    md.ensure(layer_id, layer.kind)
    md.a[layer_id] = (1.0 - md.a[layer_id]).astype(md.a[layer_id].dtype)
    _write(node, f"Invert mask of {layer.name}", md=md)


def mask_values(node, layer_id: int):
    """(value, mask) per fine-scalp point of a layer, as numpy arrays. A fill layer's value is its one
    number (as a factor at the groom's default density when it is in strands / cm2), a folder's is 1."""
    np = _np()
    data = _read(node)
    layer = _layer_or_raise(data, layer_id)
    md = read_masks(node)
    if layer.kind == "paint":
        return md.v.get(layer_id, np.ones(md.n, np.float32)), md.mask(layer)
    reference = float(data.defaults.get("density", model.BUILTIN_DEFAULTS["density"]))
    number = 1.0 if layer.kind == "folder" else logic.mask_layer_value(layer, reference)
    return np.full(md.n, number, np.float32), md.mask(layer)


def mask_factor(node, lock_id: int | None = None):
    """The final factor per fine-scalp point: for one lock (the layers that reach it, at its density), or
    of the "all locks" layers at the groom's default density when `lock_id` is None."""
    data = _read(node)
    md = read_masks(node)
    if lock_id is None:
        reference = float(data.defaults.get("density", model.BUILTIN_DEFAULTS["density"]))
        return md.factor([m for m in data.masks if m.kind == "folder" or m.scope == "all"], reference)
    lk = data.lock(lock_id)
    group = lk.group if lk is not None else ""
    density = data.resolve(lock_id)["density"] if lk is not None else None
    return md.factor([m for m in data.masks if m.kind == "folder" or m.applies(lock_id, group)], density)


def mask_stroke(node, layer_id: int, points: Sequence[Sequence[float]], radius_cm: float = config.BRUSH_RADIUS_CM,
                value: float = config.BRUSH_VALUE, soft: float = config.BRUSH_SOFT, erase: bool = False,
                normals: Sequence[Sequence[float]] | None = None, level: float = 1.0) -> int:
    """One stroke through `points` (on the skin, scene units) as the brush would paint it; one undo step.
    A paint layer takes `value`; a fill layer or a folder has its mask painted `level` (1 white, 0 black).
    Returns the dabs that reached skin."""
    if _read(node).mask(layer_id) is None:
        raise KeyError(layer_id)
    session = PaintSession(node, layer_id)
    session.begin()
    landed = 0
    for i, p in enumerate(points):
        nrm = normals[i] if normals is not None else None
        landed += int(session.stroke_to(p, nrm, radius_cm, value=value, soft=soft, erase=erase, level=level) > 0)
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
                         "soft": config.BRUSH_SOFT, "erase": False, "xray": False, "view": "density", "level": 1.0}
PAINT: dict[str, Any] = {"node": None, "layer": None}    # node path and layer id while Paint is on


def set_brush(radius_cm: float | None = None, value: float | None = None, soft: float | None = None,
              erase: bool | None = None, xray: bool | None = None, view: str | None = None,
              level: float | None = None) -> dict:
    """Brush settings of the session (not saved, no undo): radius in cm, the value painted (a factor on the
    automatic density), the soft share of the radius, erase, the scalp's X-ray, and what the scalp shows
    (`view`, config.MASK_VIEWS: the density as it is, the final factor, the painted layer alone, or the
    roots as dots). Choosing "density" or "roots" counts the groom's roots, which grows the locks the cache
    does not hold in full. Returns them all."""
    if view is not None:
        if view not in config.MASK_VIEWS:
            raise ValueError(f"mask view {view!r}")
        BRUSH["view"] = view
        BRUSH["count_roots"] = view in ("density", "roots")     # asked for by hand: the state may cook
    if radius_cm is not None:
        BRUSH["radius_cm"] = min(max(float(radius_cm), 0.05), 50.0)
    if value is not None:
        BRUSH["value"] = min(max(float(value), 0.0), config.MASK_VALUE_MAX)
    if soft is not None:
        BRUSH["soft"] = min(max(float(soft), 0.0), 1.0)
    if erase is not None:
        BRUSH["erase"] = bool(erase)
    if level is not None:       # what a mask is painted: 1 white (the layer applies), 0 black
        BRUSH["level"] = min(max(float(level), 0.0), 1.0)
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
    "mask_add", "mask_remove", "mask_move", "mask_set", "mask_fill", "mask_clear", "mask_invert", "mask_values",
    "mask_factor",
    "mask_stroke", "mask_problem", "mask_rebake", "set_brush", "brush", "paint_enter", "paint_exit",
    "paint_layer", "import_masks", "masks_from_publish",
]
