"""
The density layers of MONO Grooming (v0.2a, docs/plans/grooming_v0_2.md): storage, the HDA's `mask_read`, the
brush and the layer functions of the adapter API. `grooming_adapter` re-exports what the panel uses.

The model (config.MASK_MODES): density layers over the automatic groom, each with its own number D (strands /
cm2), an opacity, an owner and a mask (a stack of paint and fill layers, 0..1, from black):
density = below + (D - below) x mask x opacity. Where things live: the layer list (`model.MaskLayer`: the base,
the density layers, their mask layers) in `groom_data`, what paint layers hold in the node's hidden geometry
parm `mask_layers`: one point per point of the fine scalp (`SCALP_FINE`) with `P`, `uv` and per paint layer
`mask_<id>_v` (value) and `mask_<id>_a` (coverage). Parms, so every change is undoable and saved with the hip.
A paint layer never painted has no attributes (coverage 0 everywhere: transparent).

In the network `mask_read` (Python SOP after the region split) composes the density layers per scope set
(`logic.mask_scope_sets`) into `mask_keep_<k>` (point: how much of the automatic groom stays) and
`mask_add_<k>` (vertex: the density the layers ask of one lock there, strands / cm2), and records, per lock, its
set and a digest of both on its own skin: the lock's cache key takes that digest, so a stroke regrows the locks
under it only.
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
ATTR_HASH_OF = "mask_hash_of"     # detail string array by lock id: digest of keep and add on its skin
ATTR_ADD_OF = "mask_add_of"       # detail float array by lock id: strands the layers ask on its skin
ATTR_KEEP_OF = "mask_keep_of"     # detail float array by lock id: expected share of its automatic roots kept
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


def view_colours(view: str, value=None, coverage=None, density=None, reference: float = 1.0, points: int = 0):
    """(n, 3) float32 colours of the scalp for a view (config.MASK_VIEWS), on arrays: the rules of
    logic.density_color / layer_color. "layer": the painted layer alone, its `value` as a grey where it has
    `coverage`; "density": `density`, strands / cm2 per point, and `reference`, the density the ramp is
    centred on; "roots" is one plain colour (the dots carry it)."""
    np = _np()
    dark = np.array(logic.LAYER_UNPAINTED, np.float32)
    if view == "layer" and coverage is not None:
        k = np.clip(np.asarray(coverage, np.float32), 0.0, 1.0)[:, None]
        v = np.clip(np.asarray(value if value is not None else 1.0, np.float32), 0.0, 1.0)
        v = (np.zeros(len(k), np.float32) + v)[:, None]
        return (dark + (v - dark) * k).astype(np.float32)
    if view == "density" and density is not None:
        ramp = np.array(logic.DENSITY_RAMP, np.float32)
        stops = np.array(logic.DENSITY_STOPS, np.float32)
        t = np.clip(np.asarray(density, np.float32) / max(reference, 1e-9), 0.0, stops[-1])
        i = np.clip(np.searchsorted(stops, t, side="right") - 1, 0, len(stops) - 2)
        f = ((t - stops[i]) / (stops[i + 1] - stops[i]))[:, None]
        return (ramp[i] + (ramp[i + 1] - ramp[i]) * f).astype(np.float32)
    n = points or len(coverage if coverage is not None else density if density is not None else ())
    return np.tile(dark * 2.0, (n, 1)).astype(np.float32)


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
    """What is painted, as numpy arrays on the current fine scalp. Per paint layer id `v` (its value per
    point, 0..1) and `a` (its coverage: 0 not painted, 1 painted). A paint layer with no array was never
    painted (transparent); one with coverage only (a layer carried over from an older file) has its row's
    one value under that coverage. A fill layer holds nothing here: its value covers all skin. `moved`:
    painted on another scalp and brought over (`read_masks`)."""

    def __init__(self, P):
        np = _np()
        self.P = np.asarray(P, dtype=np.float32).reshape(-1, 3)
        self.n = len(self.P)
        self.v: dict[int, Any] = {}
        self.a: dict[int, Any] = {}
        self.moved = False

    def ensure(self, layer_id: int, value: float = 1.0) -> None:
        """Arrays for a paint layer about to be painted."""
        np = _np()
        if layer_id not in self.a:
            self.a[layer_id] = np.zeros(self.n, np.float32)
        if layer_id not in self.v:
            self.v[layer_id] = np.full(self.n, min(max(float(value), 0.0), 1.0), np.float32)

    def drop(self, layer_id: int) -> None:
        self.v.pop(layer_id, None)
        self.a.pop(layer_id, None)

    def painted(self, layer_id: int) -> int:
        """Points of the layer with any coverage."""
        return int((self.a[layer_id] > 0).sum()) if layer_id in self.a else 0

    def value(self, layer):
        """The layer's value per point: a paint layer's painted values (its row's value where only coverage
        is stored), a fill layer's one value."""
        np = _np()
        if layer.kind == "paint" and layer.id in self.v:
            return self.v[layer.id]
        return np.full(self.n, layer.value, np.float32)

    def coverage(self, layer):
        """The layer's coverage per point: a paint layer's paint, all skin for a fill layer."""
        np = _np()
        if layer.kind == "paint":
            return self.a.get(layer.id, np.zeros(self.n, np.float32))
        return np.ones(self.n, np.float32)

    def mask_of(self, data: model.GroomData, density_id: int):
        """The mask of a density layer, 0..1 per point (`logic.mask_stack` over its paint and fill layers, from
        black). float64."""
        np = _np()
        layer = data.mask(density_id)
        if layer is not None and layer.legacy:      # what it takes of the density below: 1 - its keep
            return 1.0 - self.parts_of(data, layer)[0]
        rows = [(m, self.value(m), self.coverage(m)) for m in data.mask_layers(density_id)]
        return logic.mask_stack(rows, np.zeros(self.n, np.float64))

    def parts_of(self, data: model.GroomData, layer: model.MaskLayer):
        """(keep', add') of one density layer at opacity 1, per point: over (keep, add) below, the layer gives
        keep x keep' and add x keep' + D x add'. A density layer: (1 - mask, mask). A layer of an older test
        build (`legacy`): its 0..1 mask read by that build's rule (`logic.legacy_mask`: Multiply and Min thin
        what is below, black is no hair, white the owner's Density)."""
        np = _np()
        if layer.legacy:
            rows = [(m, self.value(m), self.coverage(m)) for m in data.mask_layers(layer.id)]
            return logic.legacy_mask(rows, np.ones(self.n, np.float64))
        m = self.mask_of(data, layer.id)
        return 1.0 - m, m

    def weights(self, data: model.GroomData, layers: Sequence[model.MaskLayer], masks: dict | None = None):
        """(keep, [w per layer]) per point through density `layers` (in the order they apply, bottom first):
        keep = the product of (1 - e), e = mask x opacity; w of a layer = its e x the (1 - e) of every layer
        over it, so the layers' density is the sum of D x w and density = automatic x keep + that sum. (A
        `legacy` layer takes 1 - keep' of what is below and adds D x add': `parts_of`.)
        `masks`: a dict that keeps each layer's parts (a layer is in several scope sets)."""
        np = _np()
        masks = masks if masks is not None else {}
        parts = []
        for layer in layers:
            if layer.id not in masks:
                masks[layer.id] = self.parts_of(data, layer)
            k, a = masks[layer.id]
            parts.append((1.0 - (1.0 - k) * layer.opacity, a * layer.opacity))
        keep = np.ones(self.n, np.float64)
        ws = [None] * len(layers)
        for i in range(len(layers) - 1, -1, -1):
            ws[i] = parts[i][1] * keep
            keep = keep * parts[i][0]
        return keep, ws

    def compose(self, data: model.GroomData, layers: Sequence[model.MaskLayer]):
        """(keep, add) per point through density `layers` (bottom first): density = automatic x keep + add,
        add in strands / cm2 with each layer's D as it is set (not divided among the locks sharing the skin).
        float32."""
        np = _np()
        keep, ws = self.weights(data, layers)
        add = np.zeros(self.n, np.float64)
        for layer, w in zip(layers, ws):
            add += layer.density * w
        return np.asarray(keep, dtype=np.float32), np.asarray(add, dtype=np.float32)

    def dab(self, layer_id: int, idx, weight, value: float = 1.0, erase: bool = False) -> None:
        """One dab on a paint layer (`logic.mask_dab`): the brush `value` (0..1) with its coverage, or, erasing,
        the layer's own paint taken away."""
        self.ensure(layer_id)
        np = _np()
        paint = min(max(float(value), 0.0), 1.0)
        v, a = logic.mask_dab(self.v[layer_id][idx], self.a[layer_id][idx], np.asarray(weight, np.float32), paint, erase)
        self.v[layer_id][idx] = v
        self.a[layer_id][idx] = a


def layers_for_view(masks: Sequence[model.MaskLayer], layer_id: int | None) -> list[model.MaskLayer]:
    """The density layers whose result the scalp shows while mask layer `layer_id` is painted, in the order they
    apply: the "all locks" layers and the ones with the owner of the painted layer's density layer (what a lock
    under that owner gets, bar layers owned by a more specific row). None: the "all locks" layers."""
    active = next((m for m in masks if m.id == layer_id), None)
    if active is not None and active.kind in ("paint", "fill"):
        active = next((m for m in masks if m.id == active.parent), None)
    owner = active.owner() if active is not None else ("all",)
    shown = [m for m in masks if m.kind == "density" and m.on and (m.scope == "all" or m.owner() == owner)]
    return sorted(shown, key=lambda m: {"all": 0, "group": 1, "locks": 2}.get(m.scope, 0))


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
        md.a[layer_id] = np.clip(a[src] if src is not None else a, 0.0, 1.0)
        if "v" in parts:        # values of an older file were factors up to 8: a value is 0..1
            v = np.frombuffer(stored.pointFloatAttribValuesAsString(config.MASK_VALUE_ATTR % layer_id), np.float32)
            md.v[layer_id] = np.clip(v[src] if src is not None else v, 0.0, 1.0)
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
            keep = [m.id for m in (data or _read(node)).masks if m.kind == "paint"]
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
    belong to each owner), "prims" (per lock its prims), "verts" (per lock the vertices of its prims),
    "owners" (owners per prim), and the vertex tables
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
    by_lock, verts = {}, {}
    n_prims = geo.intrinsicValue("primitivecount")
    inside = np.zeros(n_prims, dtype=bool)
    owners = np.zeros(n_prims, dtype=np.float32)
    for lock_id, prims in prims_of.items():
        inside[:] = False
        inside[prims] = True
        owners[prims] += 1
        verts[lock_id] = np.nonzero(inside[vertex_prim])[0]
        by_lock[lock_id] = np.unique(vertex_point[verts[lock_id]])
    tables = {"points": by_lock, "verts": verts, "prims": {k: np.asarray(v, dtype=np.int64) for k, v in prims_of.items()},
              "owners": owners, "vertex_prim": vertex_prim, "vertex_point": vertex_point,
              "corners": np.maximum(np.bincount(vertex_prim, minlength=n_prims), 1).astype(np.float32)}
    _REGION_POINTS[top.sessionId()] = (key, tables)
    return tables


_REGION_KEYS: dict[int, tuple[bytes, dict]] = {}     # node session id -> (digest of the split and the skin, keys)


def region_keys(top, geo) -> dict[int, tuple]:
    """Per lock id a fingerprint of its region on SCALP_REGIONS, for the lock's cache key: 9 sums over its
    prims of what the per-lock loop reads of them (count, area / share, share, centre, centre x a weight
    by prim number, so a moved or swapped prim changes it). Kept per node by a digest of the split and the
    skin: a detail wrangle summed this on every edit of the groom's data, 39 ms of an undo."""
    np = _np()
    h = hashlib.blake2b(digest_size=16)
    h.update(geo.pointFloatAttribValuesAsString("P"))
    for name, read in (("area_cm2", geo.primFloatAttribValuesAsString), ("lock_owner", geo.primIntAttribValuesAsString),
                       ("share", geo.primIntAttribValuesAsString), ("owners_h", geo.primIntAttribValuesAsString)):
        if geo.findPrimAttrib(name) is not None:
            h.update(read(name))
    key = h.digest()
    hit = _REGION_KEYS.get(top.sessionId())
    if hit is not None and hit[0] == key:
        return hit[1]
    tables = _region_tables(top, geo)
    n = len(tables["owners"])
    P = _points(geo).astype(np.float64)
    cen = np.stack([np.bincount(tables["vertex_prim"], weights=P[tables["vertex_point"], k], minlength=n)
                    for k in range(3)], 1) / tables["corners"][:, None]
    area = np.frombuffer(geo.primFloatAttribValuesAsString("area_cm2"), np.float32).astype(np.float64)
    share = np.maximum(tables["owners"].astype(np.float64), 1.0)
    weight = 1.0 + (np.arange(n) % 13) * 0.37
    out = {}
    for lock_id, prims in tables["prims"].items():
        c = cen[prims]
        out[lock_id] = (len(prims), float((area[prims] / share[prims]).sum()), float(share[prims].sum()),
                        *(float(x) for x in c.sum(0)), *(float(x) for x in (c * weight[prims][:, None]).sum(0)))
    _REGION_KEYS[top.sessionId()] = (key, out)
    return out


def layer_divisor(tables: dict, layer: model.MaskLayer, data: model.GroomData):
    """Per prim of the split: how many of its owners a density layer's D is shared by (`logic.owners_sharing`:
    the owners the layer is owned for), at least 1. "= D" owned by all locks: every owner, so all the locks on
    that skin give D together; owned by a lock: 1 on its skin, the lock alone gives D."""
    np = _np()
    div = np.zeros(len(tables["owners"]), np.float32)
    for lk in data.locks:
        prims = tables["prims"].get(lk.id)
        if prims is not None and layer.applies(lk.id, lk.group):
            div[prims] += 1.0
    return np.maximum(div, 1.0)


def cook_mask_read(sop) -> None:
    """Python SOP "mask_read", on the scalp with its split (after region_prims): per scope set the point
    attribute `mask_keep_<k>` and the vertex attribute `mask_add_<k>` (density of a lock = automatic x keep +
    add; add is one lock's part, each layer's D divided by `layer_divisor`), the details `mask_sets`,
    `mask_set_of`, `mask_hash_of` (by lock id: its set, and a digest of keep and add on its own skin, "" where
    no layer changes it), `mask_add_of` (by lock id: the strands the layers ask on its skin = the sum of add x
    area over its prims, the count the lock's second scatter is given) and the prim `mask_dens` (PREVIEW's
    expected strands / cm2). With no density layer on it adds nothing: the geometry, and so the groom, is
    v0.1's."""
    top = sop.parent()
    geo = sop.geometry()
    text = top.evalParm(config.DATA_PARM)
    parm = top.parm(config.MASK_PARM)
    # a file of this schema without a density layer (the usual groom): nothing to read, not even the JSON. An
    # older file is always read: its layers become density layers on reading (model.migrate)
    if parm is None or not text or ('"schema": %d' % model.SCHEMA in text and '"kind": "density"' not in text):
        return
    data = model.GroomData.from_json(text)
    if not any(m.on for m in data.density_layers()):
        return
    stored = parm.evalAsGeometry()       # read even when nothing uses it: the node depends on the parm
    np = _np()
    md = read_masks(top, scalp=geo, stored=stored)
    if md.moved:
        sop.addWarning(MOVED_TEXT)
    sets, set_of = logic.mask_scope_sets(data.masks, [(lk.id, lk.group) for lk in data.locks])
    by_id = {m.id: m for m in data.masks}
    tables = _region_tables(top, geo)
    regions = tables["points"]
    n_prims = len(tables["owners"])
    vertex_prim, vertex_point = tables["vertex_prim"], tables["vertex_point"]
    area = np.frombuffer(geo.primFloatAttribValuesAsString("area_cm2"), np.float32)
    base = np.frombuffer(geo.primFloatAttribValuesAsString("density"), np.float32)
    share = np.maximum(tables["owners"], 1.0)
    masks: dict[int, Any] = {}
    divisors: dict[int, Any] = {}
    keeps, vadds, keep_prim, add_prim = [], [], [], []
    for k, ids in enumerate(sets):
        layers = [by_id[i] for i in ids]
        keep, ws = md.weights(data, layers, masks)
        vadd = np.zeros(len(vertex_prim), np.float64)
        for layer, w in zip(layers, ws):
            if layer.density <= 0:
                continue
            if layer.id not in divisors:
                divisors[layer.id] = layer_divisor(tables, layer, data)
            vadd += (layer.density / divisors[layer.id])[vertex_prim] * w[vertex_point]
        keep = keep.astype(np.float32)
        vadd = vadd.astype(np.float32)
        keeps.append(keep)
        vadds.append(vadd)
        name = config.MASK_KEEP_ATTR % k
        if geo.findPointAttrib(name) is None:
            geo.addAttrib(hou.attribType.Point, name, 1.0)
        geo.setPointFloatAttribValuesFromString(name, keep.tobytes())
        name = config.MASK_ADD_ATTR % k
        if geo.findVertexAttrib(name) is None:
            geo.addAttrib(hou.attribType.Vertex, name, 0.0)
        geo.setVertexFloatAttribValuesFromString(name, vadd.tobytes())
        keep_prim.append(np.bincount(vertex_prim, weights=keep[vertex_point], minlength=n_prims) / tables["corners"])
        add_prim.append(np.bincount(vertex_prim, weights=vadd, minlength=n_prims) / tables["corners"])
    top_id = max([lk.id for lk in data.locks] + [-1])
    set_list = [-1] * (top_id + 1)
    hash_list = [""] * (top_id + 1)
    add_list = [0.0] * (top_id + 1)
    auto = np.zeros(n_prims, np.float64)       # per prim: the automatic part its owners keep, summed
    dens = np.zeros(n_prims, np.float64)       # per prim: what the layers ask of its owners, strands / cm2
    for lock_id, prims in tables["prims"].items():
        k = set_of.get(lock_id, -1) if 0 <= lock_id <= top_id else -1
        idx = regions.get(lock_id)
        # keep and 1 + add on the lock's skin: all 1 = no layer covers it, the hair without layers, no set
        digest = (values_digest(np.concatenate([keeps[k][idx], 1.0 + vadds[k][tables["verts"][lock_id]]]))
                  if k >= 0 and idx is not None else "")
        if not digest:
            auto[prims] += base[prims]
            continue
        set_list[lock_id] = k
        hash_list[lock_id] = digest
        add_list[lock_id] = float((add_prim[k][prims] * area[prims]).sum())
        auto[prims] += base[prims] * keep_prim[k][prims]
        dens[prims] += add_prim[k][prims]
    dens = np.where(tables["owners"] > 0, auto / share + dens, base).astype(np.float32)
    geo.addAttrib(hou.attribType.Prim, "mask_dens", 0.0)
    geo.setPrimFloatAttribValuesFromString("mask_dens", dens.tobytes())
    geo.addAttrib(hou.attribType.Global, ATTR_SETS, 0)
    geo.setGlobalAttribValue(ATTR_SETS, len(sets))
    geo.addArrayAttrib(hou.attribType.Global, ATTR_SET_OF, hou.attribData.Int)
    geo.setGlobalAttribValue(ATTR_SET_OF, set_list)
    geo.addArrayAttrib(hou.attribType.Global, ATTR_HASH_OF, hou.attribData.String)
    geo.setGlobalAttribValue(ATTR_HASH_OF, hash_list)
    geo.addArrayAttrib(hou.attribType.Global, ATTR_ADD_OF, hou.attribData.Float)
    geo.setGlobalAttribValue(ATTR_ADD_OF, add_list)


def layer_cover(top, regions_geo) -> dict[int, tuple[Any, Any, Any]]:
    """Per lock id a layer changes: (its prims on SCALP_REGIONS, keep per prim, the density the layers ask of
    that lock per prim in strands / cm2), from the means of `mask_keep_<k>` / `mask_add_<k>` over each prim's
    corners for the lock's scope set. The lock's density on a prim is its automatic one x keep + that density.
    Empty when no layer is on. Shared by `lock_layer_counts` and grooming-check's skin check."""
    if regions_geo is None or regions_geo.findGlobalAttrib(ATTR_SET_OF) is None:
        return {}
    np = _np()
    tables = _region_tables(top, regions_geo)
    set_of = regions_geo.intListAttribValue(ATTR_SET_OF)
    n_prims = len(tables["owners"])
    means: dict[int, tuple[Any, Any]] = {}
    out = {}
    for lock_id, prims in tables["prims"].items():
        k = set_of[lock_id] if 0 <= lock_id < len(set_of) else -1
        if k < 0 or not len(prims):
            continue
        if k not in means:
            f = np.frombuffer(regions_geo.pointFloatAttribValuesAsString(config.MASK_KEEP_ATTR % k), np.float32)
            a = np.frombuffer(regions_geo.vertexFloatAttribValuesAsString(config.MASK_ADD_ATTR % k), np.float32)
            means[k] = (np.bincount(tables["vertex_prim"], weights=f[tables["vertex_point"]],
                                    minlength=n_prims) / tables["corners"],
                        np.bincount(tables["vertex_prim"], weights=a, minlength=n_prims) / tables["corners"])
        out[lock_id] = (prims, means[k][0][prims], means[k][1][prims])
    return out


def kept_share(prim_strands, far_w, keep, landing_keep: float) -> float:
    """Pure: the share of a lock's automatic roots (whorl roots apart) expected to stay under layers.
    `prim_strands`: the roots hairgen scatters on each of the lock's prims; `far_w`: the share of them the
    tool moves to the lock's start (skin under floating mesh); `keep`: the layers' keep on each prim;
    `landing_keep`: the keep where the moved roots land. A root is kept by the keep where it ends up."""
    np = _np()
    n = np.asarray(prim_strands, np.float64)
    fw = np.clip(np.asarray(far_w, np.float64), 0.0, 1.0)
    total = float(n.sum())
    if total <= 0:
        return 1.0
    stay = float((n * (1.0 - fw) * np.asarray(keep, np.float64)).sum())
    return (stay + float((n * fw).sum()) * landing_keep) / total


def root_landings(auto_geo):
    """(where each automatic root of a lock ends up (n, 3), which of them are whorl roots) from the lock's
    cached automatic roots (root_pick's output: one strand a root, `start_root` / `whorl_root` flags and
    `start_pos` for the roots it laid out round the lock's start). A root not relocated ends up where
    hairgen scattered it. None when the geometry is not such roots."""
    np = _np()
    n = auto_geo.intrinsicValue("primitivecount")
    if n <= 0:
        return np.zeros((0, 3), np.float32), np.zeros(0, bool)
    roots = strand_roots(np.frombuffer(auto_geo.pointFloatAttribValuesAsString("P"), np.float32), n)
    if roots is None:
        return None
    roots = roots.copy()
    whorl = np.zeros(n, bool)
    if auto_geo.findPrimAttrib("start_root") is not None and auto_geo.findPrimAttrib("start_pos") is not None:
        start = np.frombuffer(auto_geo.primIntAttribValuesAsString("start_root"), np.int32) > 0
        if auto_geo.findPrimAttrib("whorl_root") is not None:
            whorl = np.frombuffer(auto_geo.primIntAttribValuesAsString("whorl_root"), np.int32) > 0
        pos = np.frombuffer(auto_geo.primFloatAttribValuesAsString("start_pos"), np.float32).reshape(-1, 3)
        moved = start & ~whorl
        roots[moved] = pos[moved]
    return roots, whorl


def keep_at(regions_geo, set_index: int, positions):
    """The layers' keep of one scope set at `positions` (n, 3): the value of the nearest scalp point
    (Attribute Transfer as a verb, one sample)."""
    np = _np()
    if not len(positions):
        return np.zeros(0, np.float32)
    name = config.MASK_KEEP_ATTR % set_index
    src = hou.Geometry()
    src.merge(_cloud(_points(regions_geo)))
    src.addAttrib(hou.attribType.Point, name, 1.0)
    src.setPointFloatAttribValuesFromString(name, regions_geo.pointFloatAttribValuesAsString(name))
    cloud = _cloud(positions)
    cloud.addAttrib(hou.attribType.Point, name, 1.0)
    verb = hou.sopNodeTypeCategory().nodeVerb("attribtransfer")
    verb.setParms({"primitiveattribs": 0, "pointattribs": 1, "pointattriblist": name, "kernel": "uniform",
                   "kernelradius": 1e9, "maxsamplecount": 1, "threshold": 0})
    out = hou.Geometry()
    verb.execute(out, [cloud, src])
    return np.frombuffer(out.pointFloatAttribValuesAsString(name), np.float32).copy()


def lock_layer_counts(top, regions_geo, locks: dict[int, dict], auto_roots=None) -> dict[int, tuple[float, float]]:
    """Per lock id a layer covers: (the share of its automatic roots expected to stay, the strands the layers
    scatter on its skin). The second is the count the network's second scatter is given (`mask_add_of`),
    exact; the first follows the network's own steps on the region's prims (`kept_share`): hairgen spreads
    the lock's strands by area / share, the share `far_w` of the roots under floating mesh moves to a disc
    round the lock's root (root_pick: up to START_DENSITY_MAX x the lock's density, grown when it runs off
    the region), and each root stays by the keep where it ends up (mask_thin). Whorl roots are left out, as
    in `LockInfo.strands`.

    `locks`: per lock id {"strands": its automatic count, "root": its root (scene units), "foot": its
    footprint radius (scene units)}; `regions_geo`: SCALP_REGIONS with `owner_dist`.

    `auto_roots(lock_id)`: the lock's cached automatic roots (the cache's "auto:" entry), None when it was
    never cooked. With them the share is not an estimate: it is the mean keep where each of the lock's
    automatic roots ends up (`root_landings`, `keep_at`), which is exactly the chance mask_thin draws
    against, so the expected count is right to the scatter of a coin per root."""
    cover = layer_cover(top, regions_geo)
    if not cover:
        return {}
    exact = {}
    if auto_roots is not None:
        np = _np()
        set_of = regions_geo.intListAttribValue(ATTR_SET_OF)
        adds_exact = regions_geo.floatListAttribValue(ATTR_ADD_OF)
        for lock_id in cover:
            geo = auto_roots(lock_id)
            got = root_landings(geo) if geo is not None else None
            if got is None:
                continue
            landing, whorl = got
            own = landing[~whorl]
            share = float(keep_at(regions_geo, set_of[lock_id], own).mean()) if len(own) else 1.0
            exact[lock_id] = (share, float(adds_exact[lock_id]) if lock_id < len(adds_exact) else 0.0)
        if len(exact) == len(cover):
            return exact
    np = _np()
    tables = _region_tables(top, regions_geo)
    adds = regions_geo.floatListAttribValue(ATTR_ADD_OF)
    area = np.frombuffer(regions_geo.primFloatAttribValuesAsString("area_cm2"), np.float32).astype(np.float64)
    unit = max(float(top.evalParm("unit_cm")), 1e-6)
    far = float(top.evalParm("root_far_cm")) if top.parm("root_far_cm") is not None else config.ROOT_FAR_CM
    n_prims = len(area)
    P = _points(regions_geo).astype(np.float64)
    cen = np.stack([np.bincount(tables["vertex_prim"], weights=P[tables["vertex_point"], k], minlength=n_prims)
                    for k in range(3)], 1) / tables["corners"][:, None]
    owners = dists = None
    if regions_geo.findPrimAttrib("owner_dist") is not None and far > 0:
        owners = regions_geo.primIntListAttribValues("lock_owners")
        dists = regions_geo.primFloatListAttribValues("owner_dist")
    out = {}
    for lock_id, (prims, keep, _add) in cover.items():
        info = locks.get(lock_id)
        add_n = float(adds[lock_id]) if lock_id < len(adds) else 0.0
        if info is None or not len(prims):
            out[lock_id] = (1.0, add_n)
            continue
        w = area[prims] / np.maximum(tables["owners"][prims], 1.0)
        lock_area = max(float(w.sum()), 1e-9)
        per_prim = float(info["strands"]) * w / lock_area
        c = cen[prims]
        root = np.asarray(info["root"], np.float64)
        d_root = np.sqrt(((c - root) ** 2).sum(1))
        centre = c[int(d_root.argmin())]                   # the root moved onto the skin (region_frame fp_c)
        d_c = np.sqrt(((c - centre) ** 2).sum(1))
        fw = np.zeros(len(prims))
        if dists is not None:
            for j, pr in enumerate(prims):
                own, dd = owners[pr], dists[pr]
                at = own.index(lock_id) if lock_id in own else -1
                if 0 <= at < len(dd) and dd[at] >= 0 and d_c[j] > float(info.get("foot", 0.0)):
                    fw[j] = logic.falloff(dd[at] * unit, far, config.ROOT_FAR_SOFT)
        moved = float((per_prim * fw).sum())
        landing = 1.0
        if moved > 0:
            # root_pick's disc: `moved` places at START_DENSITY_MAX x the lock's density, grown (at most 3x)
            # until the region under it holds them
            rho = max(float(info["strands"]) / lock_area, 1e-9) * config.START_DENSITY_MAX     # places / cm2
            rad = np.sqrt(moved / (np.pi * rho)) / unit
            r_max = 3.0 * max(rad, float(info.get("foot", 0.0)))
            r = rad
            for _ in range(8):
                inside = d_c <= r
                places = float(area[prims][inside].sum()) * rho
                if places >= moved or r >= r_max:
                    break
                r = min(r_max, r * np.sqrt(moved / max(places, 1e-9)) * 1.1)
            inside = d_c <= r
            if not inside.any():
                inside = d_c <= d_c.min() + 1e-9
            landing = float((keep[inside] * area[prims][inside]).sum() / max(float(area[prims][inside].sum()), 1e-12))
        out[lock_id] = (kept_share(per_prim, fw, keep, landing), add_n)
    out.update(exact)
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
    whole = True
    if full is None:
        # output 1's keys are out of date and we may not cook: the display's hair is the whole groom when
        # it grows every lock that is not excluded at full density (Display Hair, nothing hidden)
        full = {}
        keyed = node.node("lock_keys").geometry() if node.node("lock_keys") is not None else None
        if keyed is None or keyed.findPrimAttrib(config.ATTR_LOCK_ID) is None:
            whole = False
        else:
            ids = keyed.primIntAttribValues(config.ATTR_LOCK_ID)
            out_of = keyed.primIntAttribValues("excluded") if keyed.findPrimAttrib("excluded") is not None else [0] * len(ids)
            whole = all(i in shown for i, ex in zip(ids, out_of) if i >= 0 and not ex)
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


def lock_mask_keys(preview_geo) -> tuple[Sequence[int], Sequence[str], Sequence[float]]:
    """(scope set by lock id, digest by lock id, strands the layers add by lock id) as `mask_read` left them
    on the regions (PREVIEW passes the details on); empty when no layer is on."""
    if preview_geo is None or preview_geo.findGlobalAttrib(ATTR_SET_OF) is None:
        return (), (), ()
    return (preview_geo.intListAttribValue(ATTR_SET_OF), preview_geo.stringListAttribValue(ATTR_HASH_OF),
            preview_geo.floatListAttribValue(ATTR_ADD_OF))


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
        self.counted = False        # the groom's roots were counted at least once this session
        self.reload()

    def reload(self) -> None:
        """What the node holds now (on entering, after an undo or any change from outside)."""
        self.data = _read(self.node)
        layer = self.data.mask(self.layer_id)
        self.kind = layer.kind if layer is not None else "paint"
        if layer is not None and layer.kind != "paint":
            raise ValueError(f"layer {layer.name!r} is a {layer.kind} layer: only a paint layer of a mask is painted")
        self.md = read_masks(self.node, self.scalp)
        self.dirty = False
        self._last = None

    def layer(self) -> model.MaskLayer | None:
        return self.data.mask(self.layer_id)

    def cover(self):
        """(keep, add) the scalp shows while this layer is painted (`layers_for_view`): density = automatic x
        keep + add, add in strands / cm2."""
        return self.md.compose(self.data, layers_for_view(self.data.masks, self.layer_id))

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
        grown first (output 1). Without it nothing cooks: when a lock's hair is missing the last count is
        kept, and `density` goes on from it by the factor's change (a prediction; nothing is counted until
        the hair is there again). True when the whole groom was counted now."""
        roots, whole = display_roots(self.node, cook=cook)
        self.whole = whole
        if not whole:
            return False
        self.roots = roots
        _base, _reference, point_area = self.base_density()
        self.actual = root_density(self.md.P, point_area, roots, config.ROOT_DENSITY_CELL_CM / self.unit_cm)
        self.actual_cover = tuple(x.copy() for x in self.cover())
        self.counted = True
        return True

    def density(self):
        """Strands / cm2 per scalp point for the "density" view, the final density map: the roots as counted
        (`measure`), moved by what the layers ask now against what they asked when counted (a stroke in
        progress shows at once what it asks of the hair it is over): the automatic part of the count x keep,
        plus the layers' own density. Before any count: the density asked (`logic.layer_density`)."""
        np = _np()
        base, _reference, _area = self.base_density()
        keep, add = self.cover()
        if getattr(self, "actual", None) is None:
            return logic.layer_density(base, keep, add).astype(np.float32)
        keep0, add0 = self.actual_cover
        # the automatic density there, from the count: what was not the layers', over what was kept of it
        auto = np.where(keep0 > 1e-3, np.maximum(self.actual - add0, 0.0) / np.maximum(keep0, 1e-3), base)
        return logic.layer_density(auto, keep, add).astype(np.float32)

    def colours(self, view: str):
        """The scalp's colours for a view (config.MASK_VIEWS). "layer": the painted layer alone, its value
        as a grey where it has coverage."""
        density = self.density() if view == "density" else None
        reference = self.base_density()[1] if view == "density" else 1.0
        layer = self.layer()
        show = layer is not None and view == "layer"
        return view_colours(view, self.md.value(layer) if show else None, self.md.coverage(layer) if show else None,
                            density, reference, points=self.md.n)

    def begin(self) -> None:
        self._last = None

    def dab(self, centre, normal=None, radius_cm: float = config.BRUSH_RADIUS_CM,
            value: float = config.BRUSH_VALUE, soft: float = config.BRUSH_SOFT, erase: bool = False) -> int:
        """One dab at `centre` (scene units, on the skin): the brush `value` (1 white: the density layer
        applies; 0 black: it does not) with its coverage; `erase` takes the layer's own paint away there.
        Returns the points it reached."""
        radius = radius_cm / self.unit_cm
        idx, dist = self.brush.reach(centre, radius, normal)
        if len(idx):
            layer = self.layer()
            self.md.ensure(self.layer_id, layer.value if layer is not None else 1.0)
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

def mask_add(node, name: str = "", mode: str = "normal", opacity: float = 1.0, scope: str = "all",
             group: str = "", locks: Iterable[int] = (), kind: str | None = None, value: float = 1.0,
             parent: int | None = None, density: float = config.MASK_DENSITY_DEFAULT) -> int:
    """A new layer; returns its id. `kind` (None: "density" without a `parent`, "paint" with one):
    "density": a density layer on top of the stack: `density` (D, strands / cm2), `opacity`, and its owner
    (`scope`: every lock, a `group`, or `locks`). Its mask is black until a mask layer is added and painted, so
    a new density layer changes nothing.
    "paint" / "fill": a layer on top of density layer `parent`'s mask: "paint" is painted with the brush (a
    value 0..1 and a coverage per skin point; transparent until painted), "fill" is one `value` (0..1) over all
    the skin; `mode` (config.MASK_MODES) is how it blends with the mask below it, `opacity` how much."""
    _require_parm(node)
    kind = kind or ("density" if parent is None else "paint")
    if mode not in config.MASK_MODES or scope not in config.MASK_SCOPES:
        raise ValueError(f"layer mode {mode!r} / scope {scope!r}")
    if kind not in ("density", "paint", "fill"):
        raise ValueError(f"layer kind {kind!r}")
    data = _read(node)
    layer = data.add_mask(name, mode, opacity, scope, group, locks, kind, value, parent, density)
    _write(node, f"Add {'density' if kind == 'density' else 'mask'} layer {layer.name}", data=data)
    return layer.id


def mask_remove(node, layer_id: int) -> bool:
    """Delete a layer and what is painted on it; a density layer goes with its mask layers. False when there
    is no such layer; the automatic layer cannot be deleted (ValueError)."""
    data = _read(node)
    layer = data.mask(layer_id)
    if layer is None:
        return False
    gone = data.remove_mask(layer_id)
    md = read_masks(node)
    for i in gone:
        md.drop(i)
    _write(node, f"Delete {'density' if layer.kind == 'density' else 'mask'} layer {layer.name}", data=data, md=md)
    return True


def mask_move(node, layer_id: int, index: int, parent: int | None | str = "keep") -> None:
    """Put a layer at place `index` among its like (0 = bottom): a density layer among the density layers (the
    automatic layer stays under them all and cannot be moved), a mask layer inside its density layer's mask
    or, with `parent`, into another density layer's mask."""
    data = _read(node)
    data.move_mask(layer_id, index, parent)
    _write(node, "Reorder layers", data=data)


def mask_set(node, layer_id: int, name: str | None = None, on: bool | None = None, mode: str | None = None,
             opacity: float | None = None, scope: str | None = None, group: str | None = None,
             locks: Iterable[int] | None = None, value: float | None = None, density: float | None = None) -> bool:
    """Change a layer's row: any of name, on, opacity; a density layer's `density` (strands / cm2) and owner
    (scope with its group or locks); a mask layer's blend `mode` and a fill layer's `value` (0..1). One undo
    step; False when nothing changed. The automatic layer has no settings of its own (ValueError): its density
    is each lock's Density setting."""
    data = _read(node)
    layer = data.mask(layer_id)
    if layer is None:
        raise KeyError(layer_id)
    if layer.kind == "base":
        raise ValueError("the automatic layer has no settings of its own: its density is each lock's Density")
    if mode is not None and mode not in config.MASK_MODES:
        raise ValueError(f"layer mode {mode!r}")
    if scope is not None and scope not in config.MASK_SCOPES:
        raise ValueError(f"layer scope {scope!r}")
    before = model.MaskLayer(**{**layer.__dict__, "locks": list(layer.locks)})
    if name is not None:
        layer.name = str(name)
    if on is not None:
        layer.on = bool(on)
    if opacity is not None:
        layer.opacity = min(1.0, max(0.0, float(opacity)))
    if layer.kind == "density":
        if scope is not None:
            layer.scope = scope
        if group is not None:
            layer.group = str(group)
        if locks is not None:
            layer.locks = sorted({int(i) for i in locks})
        if density is not None:
            layer.density = min(config.MASK_DENSITY_MAX, max(0.0, float(density)))
    else:
        if mode is not None:
            layer.mode = mode
        if value is not None:
            layer.value = min(1.0, max(0.0, float(value)))
    if layer == before:
        return False
    what = [k for k in ("name", "on", "mode", "opacity", "scope", "group", "locks", "value", "density")
            if getattr(layer, k) != getattr(before, k)]
    _write(node, f"Layer {layer.name}: {', '.join(what)}", data=data)
    return True


def _layer_or_raise(data: model.GroomData, layer_id: int) -> model.MaskLayer:
    layer = data.mask(layer_id)
    if layer is None:
        raise KeyError(layer_id)
    return layer


def _paint_layer(data: model.GroomData, layer_id: int) -> model.MaskLayer:
    layer = _layer_or_raise(data, layer_id)
    if layer.kind != "paint":
        raise ValueError(f"layer {layer.name!r} is a {layer.kind} layer: only a paint layer of a mask holds paint")
    return layer


def mask_fill(node, layer_id: int, value: float = 1.0) -> None:
    """A paint layer painted `value` (0..1) on every skin point, full coverage."""
    data = _read(node)
    layer = _paint_layer(data, layer_id)
    md = read_masks(node)
    md.ensure(layer_id)
    md.v[layer_id][:] = min(max(float(value), 0.0), 1.0)
    md.a[layer_id][:] = 1.0
    _write(node, f"Fill mask layer {layer.name}", md=md)


def mask_clear(node, layer_id: int) -> None:
    """Nothing painted on the paint layer any more (transparent everywhere); the layer stays."""
    data = _read(node)
    layer = _paint_layer(data, layer_id)
    md = read_masks(node)
    md.drop(layer_id)
    _write(node, f"Clear mask layer {layer.name}", md=md)


def mask_invert(node, layer_id: int) -> None:
    """Invert a paint layer's values where it is painted (white <-> black); its coverage stays."""
    data = _read(node)
    layer = _paint_layer(data, layer_id)
    md = read_masks(node)
    md.ensure(layer_id, layer.value)
    md.v[layer_id] = (1.0 - md.v[layer_id]).astype(md.v[layer_id].dtype)
    _write(node, f"Invert mask layer {layer.name}", md=md)


def mask_values(node, layer_id: int):
    """Two arrays per fine-scalp point, numpy float32. A mask layer: (value, coverage), a paint layer's paint or
    a fill layer's one value with coverage 1. A density layer: (its mask, its mask x its opacity), the mask
    being its mask layers blended from black (`logic.mask_stack`)."""
    np = _np()
    data = _read(node)
    layer = _layer_or_raise(data, layer_id)
    md = read_masks(node)
    if layer.kind == "density":
        m = md.mask_of(data, layer_id)
        return m.astype(np.float32), (m * layer.opacity).astype(np.float32)
    if layer.kind == "base":
        return np.ones(md.n, np.float32), np.ones(md.n, np.float32)
    return md.value(layer), md.coverage(layer)


def mask_cover(node, lock_id: int | None = None):
    """(keep, add) per fine-scalp point: density = automatic x keep + add (`logic.layer_density`), add in
    strands / cm2 with each layer's D as it is set. For one lock (the density layers that reach it, in the
    order they apply), or of the "all locks" layers when `lock_id` is None. Where several locks share the
    skin, a layer's D is what the locks it is owned for give there together (`layer_divisor`)."""
    data = _read(node)
    md = read_masks(node)
    if lock_id is None:
        return md.compose(data, [m for m in data.density_layers() if m.on and m.scope == "all"])
    lk = data.lock(lock_id)
    return md.compose(data, logic.density_order(data.masks, lock_id, lk.group if lk is not None else ""))


def mask_dropped(node) -> str:
    """What the artist is told about a scene of an older test build: the layers this version dropped on
    opening it and the ones it now reads as density layers, "" when none: for the panel's message line. The
    stored JSON keeps them until the next edit writes it."""
    text = node.evalParm(config.DATA_PARM)
    return model.dropped_text(model.dropped_masks(text), model.converted_masks(text))


def mask_stroke(node, layer_id: int, points: Sequence[Sequence[float]], radius_cm: float = config.BRUSH_RADIUS_CM,
                value: float = config.BRUSH_VALUE, soft: float = config.BRUSH_SOFT, erase: bool = False,
                normals: Sequence[Sequence[float]] | None = None) -> int:
    """One stroke through `points` (on the skin, scene units) on a paint layer of a density layer's mask, as
    the brush would paint it; one undo step. `value`: what is painted (1 white: the density layer applies
    there; 0 black: it does not); `erase` removes the layer's paint instead.
    Returns the dabs that reached skin."""
    _paint_layer(_read(node), layer_id)
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
# panel's loading line (None: the state cooks the node itself); "exit"() when Paint ends without the panel;
# "brush"() after the brush was changed in the viewport (the state's bar, wheel, drag, F, menu): the panel
# shows the new values (a change made in the panel does not call it back: no loop)
HOOKS: dict[str, Any] = {"stroke": None, "exit": None, "brush": None}
BRUSH: dict[str, Any] = {"radius_cm": config.BRUSH_RADIUS_CM, "value": config.BRUSH_VALUE,
                         "soft": config.BRUSH_SOFT, "erase": False, "xray": False, "view": "density"}
PAINT: dict[str, Any] = {"node": None, "layer": None}    # node path and layer id while Paint is on


def set_brush(radius_cm: float | None = None, value: float | None = None, soft: float | None = None,
              erase: bool | None = None, xray: bool | None = None, view: str | None = None,
              source: str = "panel") -> dict:
    """Brush settings of the session (not saved, no undo): radius in cm, the `value` painted into the mask
    (0..1: 1 white, the density layer applies; 0 black, it does not), the soft share of the radius, `erase` (take the layer's paint
    away), the scalp's X-ray, and what the scalp shows (`view`, config.MASK_VIEWS: the density as it is, the
    painted layer alone, or the roots as dots). Choosing "density" or "roots" counts the groom's roots, which
    grows the locks the cache does not hold in full. Returns them all.

    One source for the panel's Properties and the Paint state's bar and hints (v0.2a last task): the state
    is told of every change (its bar and hints follow); the panel's "brush" hook only of a change whose
    `source` is not "panel" (the viewport's bar, wheel, Ctrl+Shift drag, F, right-click menu), so neither side
    calls the other back. View state: no undo step, no cook (choosing a view may count roots, as before)."""
    if view is not None:
        if view not in config.MASK_VIEWS:
            raise ValueError(f"mask view {view!r}")
        BRUSH["view"] = view
        BRUSH["count_roots"] = view in ("density", "roots")     # asked for by hand: the state may cook
    if radius_cm is not None:
        BRUSH["radius_cm"] = min(max(float(radius_cm), 0.05), 50.0)
    if soft is not None:
        BRUSH["soft"] = min(max(float(soft), 0.0), 1.0)
    if erase is not None:
        BRUSH["erase"] = bool(erase)
    if value is not None:
        BRUSH["value"] = min(max(float(value), 0.0), 1.0)
    if xray is not None:
        BRUSH["xray"] = bool(xray)
    if hou is not None and hou.isUIAvailable():
        from apps.houdini import grooming_paint_state
        grooming_paint_state.brush_changed()
    if source != "panel":
        hook = HOOKS.get("brush")
        if hook is not None:
            hook()
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
    _paint_layer(_read(node), layer_id)
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
    if not data.has_layers():
        return {}
    md = read_masks(node)
    final = os.path.join(tool_dir, PUBLISH_MASK_FILE).replace("\\", "/")
    ids = [m.id for m in data.masks if m.kind != "base"]
    mask_geometry(node, md, ids).saveToFile(staged.stage(final))
    return {"file": PUBLISH_MASK_FILE, "layers": ids, "points": md.n,
            "painted": {str(m.id): md.painted(m.id) for m in data.masks if m.kind == "paint"}}


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
    md.a = {i: a for i, a in md.a.items() if data.mask(i) is not None}     # a dropped layer's paint stays behind
    md.v = {i: v for i, v in md.v.items() if data.mask(i) is not None}
    _write(node, "Layers from a publish", data=data, md=md)
    return len([m for m in layers if m.kind != "base"])


__all__ = [
    "mask_add", "mask_remove", "mask_move", "mask_set", "mask_fill", "mask_clear", "mask_invert", "mask_values",
    "mask_cover", "mask_dropped",
    "mask_stroke", "mask_problem", "mask_rebake", "set_brush", "brush", "paint_enter", "paint_exit",
    "paint_layer", "import_masks", "masks_from_publish",
]
