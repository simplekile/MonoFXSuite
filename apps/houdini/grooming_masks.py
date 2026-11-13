"""
Density layers of MONO Grooming (v0.2a, docs/plans/grooming_v0_2.md): storage, the HDA's `mask_read`, the
brush and the layer functions of the adapter API. `grooming_adapter` re-exports what the panel uses.

One kind of layer: a fill layer "= D strands / cm2" with a mask, and folders of them. Where things live: the
layer list (name, on, density, opacity, owner) in `groom_data` (`model.MaskLayer`), what is painted in the
node's hidden geometry parm `mask_layers`: one point per point of the fine scalp (`SCALP_FINE`) with `P`, `uv`
and per layer its mask `mask_<id>_a` (1 white: the layer applies, 0 black). Parms, so every change is undoable
and saved with the hip. A layer never painted has no attribute (a black mask; a folder: a white one).

In the network `mask_read` (Python SOP after the region split) composes the layers per scope set
(`logic.mask_scope_sets`) into two point attributes: `mask_keep_<k>` (how much of the automatic groom stays)
and `mask_add_<k>` (the density the layers put there), and records, per lock, its set and a digest of both on
its own skin: the lock's cache key takes that digest, so a stroke regrows the locks under it only.
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
ATTR_ADD_OF = "mask_add_of"       # detail float array by lock id: strands the layers scatter on its skin
ATTR_KEEP_OF = "mask_keep_of"     # detail float array by lock id: expected share of its automatic roots kept
ATTR_SETS = "mask_sets"           # detail int: number of scope sets (0: no layer is on)
MOVED_TEXT = "Mask layers were painted on another scalp: moved over by UV, check them"
_ATTR_RE = re.compile(r"^mask_(\d+)_a$")


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


def view_colours(view: str, mask=None, density=None, reference: float = 1.0, points: int = 0):
    """(n, 3) float32 colours of the scalp for a view (config.MASK_VIEWS), on arrays: the rules of
    logic.density_color / layer_color. "layer": `mask`, the painted layer's mask per point (white where it
    applies); "density": `density`, strands / cm2 per point, and `reference`, the density the ramp is
    centred on; "roots" is one plain colour (the dots carry it)."""
    np = _np()
    dark = np.array(logic.LAYER_UNPAINTED, np.float32)
    if view == "layer" and mask is not None:
        k = np.clip(np.asarray(mask, np.float32), 0.0, 1.0)[:, None]
        return (dark + (1.0 - dark) * k).astype(np.float32)
    if view == "density" and density is not None:
        ramp = np.array(logic.DENSITY_RAMP, np.float32)
        stops = np.array(logic.DENSITY_STOPS, np.float32)
        t = np.clip(np.asarray(density, np.float32) / max(reference, 1e-9), 0.0, stops[-1])
        i = np.clip(np.searchsorted(stops, t, side="right") - 1, 0, len(stops) - 2)
        f = ((t - stops[i]) / (stops[i + 1] - stops[i]))[:, None]
        return (ramp[i] + (ramp[i + 1] - ramp[i]) * f).astype(np.float32)
    n = points or len(mask if mask is not None else density if density is not None else ())
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
    """What is painted, as numpy arrays on the current fine scalp: per layer id its mask `a` (white 1: the
    layer applies; black 0). A layer with no array was never painted: a fill layer applies nowhere (black),
    a folder everywhere (it has no mask). `moved`: painted on another scalp and brought over (`read_masks`)."""

    def __init__(self, P):
        np = _np()
        self.P = np.asarray(P, dtype=np.float32).reshape(-1, 3)
        self.n = len(self.P)
        self.a: dict[int, Any] = {}
        self.moved = False

    def ensure(self, layer_id: int, kind: str = "fill") -> None:
        """An array for a layer about to be painted (a folder's mask starts white, a fill layer's black)."""
        np = _np()
        if layer_id not in self.a:
            self.a[layer_id] = (np.ones if kind == "folder" else np.zeros)(self.n, np.float32)

    def drop(self, layer_id: int) -> None:
        self.a.pop(layer_id, None)

    def painted(self, layer_id: int) -> int:
        """Points of the layer with any mask."""
        return int((self.a[layer_id] > 0).sum()) if layer_id in self.a else 0

    def mask(self, layer):
        """The layer's mask per point (see the class: black, or white for a folder, when never painted)."""
        np = _np()
        if layer.id in self.a:
            return self.a[layer.id]
        return (np.ones if layer.kind == "folder" else np.zeros)(self.n, np.float32)

    def compose(self, layers: Iterable[model.MaskLayer]):
        """(keep, add) per point through `layers` (bottom first, folders with their layers;
        `logic.mask_compose`): the share of the automatic groom that stays and the density the layers put
        there, strands / cm2. float32, keep inside 0..1."""
        np = _np()
        keep, add = logic.mask_compose([(m, self.mask(m)) for m in layers], np.ones(self.n, np.float32))
        return (np.clip(np.asarray(keep, dtype=np.float32), 0.0, 1.0),
                np.maximum(np.asarray(add, dtype=np.float32), 0.0))

    def dab(self, layer_id: int, idx, weight, erase: bool = False, kind: str = "fill", level: float = 1.0) -> None:
        """One dab: the layer's mask moves towards `level` (1 white, 0 black; erase paints black) by the
        brush weight."""
        self.ensure(layer_id, kind)
        np = _np()
        w = np.asarray(weight, np.float32)
        grey = 0.0 if erase else min(max(float(level), 0.0), 1.0)
        a = self.a[layer_id][idx]
        self.a[layer_id][idx] = a + (grey - a) * w


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


def stored_layers(geo) -> set[int]:
    """Layer ids with a mask in a stored geometry."""
    if geo is None:
        return set()
    return {int(m.group(1)) for m in (_ATTR_RE.match(a.name()) for a in geo.pointAttribs()) if m}


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
    have = stored_layers(stored)
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
        a = np.frombuffer(stored.pointFloatAttribValuesAsString(config.MASK_COVER_ATTR % layer_id), np.float32)
        md.a[layer_id] = (a[src] if src is not None else a).copy()
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
        name = config.MASK_COVER_ATTR % layer_id
        geo.addAttrib(hou.attribType.Point, name, 0.0)
        geo.setPointFloatAttribValuesFromString(name, np.ascontiguousarray(md.a[layer_id], np.float32).tobytes())
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
    """Python SOP "mask_read", on the scalp with its split (after region_prims): per scope set the point
    attributes `mask_keep_<k>` / `mask_add_<k>` (`logic.mask_compose`), the details `mask_sets`,
    `mask_set_of`, `mask_hash_of` (by lock id: its set, and a digest of keep and add on its own skin, "" where
    no layer covers it), `mask_add_of` (by lock id: the strands the layers scatter on its skin, the count the
    lock's second scatter is given) and the prim `mask_dens` (PREVIEW's expected strands / cm2). With no
    layer on it adds nothing: the geometry, and so the groom, is v0.1's."""
    top = sop.parent()
    geo = sop.geometry()
    text = top.evalParm(config.DATA_PARM)
    parm = top.parm(config.MASK_PARM)
    if parm is None or not text or '"masks": []' in text:
        return
    data = model.GroomData.from_json(text)
    masks = [m for m in data.masks if m.on and m.kind != "folder"]
    if not masks:
        return
    stored = parm.evalAsGeometry()       # read even when nothing uses it: the node depends on the parm
    np = _np()
    md = read_masks(top, scalp=geo, stored=stored)
    if md.moved:
        sop.addWarning(MOVED_TEXT)
    sets, set_of = logic.mask_scope_sets(data.masks, [(lk.id, lk.group) for lk in data.locks])
    by_id = {m.id: m for m in data.masks}
    keeps, adds = [], []
    for k, ids in enumerate(sets):
        keep, add = md.compose([by_id[i] for i in ids])
        keeps.append(keep)
        adds.append(add)
        for name, arr, default in ((config.MASK_KEEP_ATTR % k, keep, 1.0), (config.MASK_ADD_ATTR % k, add, 0.0)):
            if geo.findPointAttrib(name) is None:
                geo.addAttrib(hou.attribType.Point, name, default)
            geo.setPointFloatAttribValuesFromString(name, arr.tobytes())
    tables = _region_tables(top, geo)
    regions = tables["points"]
    n_prims = len(tables["owners"])
    area = np.frombuffer(geo.primFloatAttribValuesAsString("area_cm2"), np.float32)
    base = np.frombuffer(geo.primFloatAttribValuesAsString("density"), np.float32)
    share = np.maximum(tables["owners"], 1.0)

    def prim_mean(values):
        return np.bincount(tables["vertex_prim"], weights=values[tables["vertex_point"]],
                           minlength=n_prims) / tables["corners"]

    keep_prim = [prim_mean(k) for k in keeps]
    add_prim = [prim_mean(a) for a in adds]
    top_id = max([lk.id for lk in data.locks] + [-1])
    set_list = [-1] * (top_id + 1)
    hash_list = [""] * (top_id + 1)
    add_list = [0.0] * (top_id + 1)
    dens = np.zeros(n_prims, np.float64)       # per prim: what its owners grow together, strands / cm2
    for lock_id, prims in tables["prims"].items():
        k = set_of.get(lock_id, -1) if 0 <= lock_id <= top_id else -1
        idx = regions.get(lock_id)
        # keep and 1 + add on the lock's skin: all 1 = no layer covers it, the hair without layers, no set
        digest = values_digest(np.concatenate([keeps[k][idx], 1.0 + adds[k][idx]])) if k >= 0 and idx is not None else ""
        if not digest:
            dens[prims] += base[prims]
            continue
        set_list[lock_id] = k
        hash_list[lock_id] = digest
        add_list[lock_id] = float((add_prim[k][prims] * area[prims] / share[prims]).sum())
        dens[prims] += base[prims] * keep_prim[k][prims] + add_prim[k][prims]
    dens = np.where(tables["owners"] > 0, dens / share, base).astype(np.float32)
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
    """Per lock id a layer covers: (its prims on SCALP_REGIONS, keep per prim, the layers' density per prim in
    strands / cm2), the means of `mask_keep_<k>` / `mask_add_<k>` over each prim's corners for the lock's
    scope set. Empty when no layer is on. Shared by `lock_layer_counts` and grooming-check's skin check."""
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
            pair = []
            for fmt in (config.MASK_KEEP_ATTR, config.MASK_ADD_ATTR):
                f = np.frombuffer(regions_geo.pointFloatAttribValuesAsString(fmt % k), np.float32)
                pair.append(np.bincount(tables["vertex_prim"], weights=f[tables["vertex_point"]],
                                        minlength=n_prims) / tables["corners"])
            means[k] = (pair[0], pair[1])
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


def lock_layer_counts(top, regions_geo, locks: dict[int, dict]) -> dict[int, tuple[float, float]]:
    """Per lock id a layer covers: (the share of its automatic roots expected to stay, the strands the layers
    scatter on its skin). The second is the count the network's second scatter is given (`mask_add_of`),
    exact; the first follows the network's own steps on the region's prims (`kept_share`): hairgen spreads
    the lock's strands by area / share, the share `far_w` of the roots under floating mesh moves to a disc
    round the lock's root (root_pick: up to START_DENSITY_MAX x the lock's density, grown when it runs off
    the region), and each root stays by the keep where it ends up (mask_thin). Whorl roots are left out, as
    in `LockInfo.strands`.

    `locks`: per lock id {"strands": its automatic count, "root": its root (scene units), "foot": its
    footprint radius (scene units)}; `regions_geo`: SCALP_REGIONS with `owner_dist`."""
    cover = layer_cover(top, regions_geo)
    if not cover:
        return {}
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
        self.kind = "fill"
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
        self.kind = layer.kind if layer is not None else "fill"
        self.md = read_masks(self.node, self.scalp)
        self.dirty = False
        self._last = None

    def layer(self) -> model.MaskLayer | None:
        return self.data.mask(self.layer_id)

    def cover(self):
        """(keep, add) the scalp shows while this layer is painted (`layers_for_view`)."""
        return self.md.compose(layers_for_view(self.data.masks, self.layer_id))

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
        plus the layers' density. Before any count: the density asked (`logic.mask_density`)."""
        np = _np()
        base, _reference, _area = self.base_density()
        keep, add = self.cover()
        asked = logic.mask_density(base, keep, add)
        if getattr(self, "actual", None) is None:
            return asked.astype(np.float32)
        keep0, add0 = self.actual_cover
        # the automatic density there, from the count: what was not the layers', over what was kept of it
        auto = np.where(keep0 > 1e-3, np.maximum(self.actual - add0, 0.0) / np.maximum(keep0, 1e-3), base)
        return logic.mask_density(auto, keep, add).astype(np.float32)

    def colours(self, view: str):
        """The scalp's colours for a view (config.MASK_VIEWS). "layer": the painted layer's mask, white
        where it applies."""
        density = self.density() if view == "density" else None
        reference = self.base_density()[1] if view == "density" else 1.0
        layer = self.layer()
        mask = self.md.mask(layer) if layer is not None and view == "layer" else None
        return view_colours(view, mask, density, reference, points=self.md.n)

    def begin(self) -> None:
        self._last = None

    def dab(self, centre, normal=None, radius_cm: float = config.BRUSH_RADIUS_CM,
            soft: float = config.BRUSH_SOFT, erase: bool = False, level: float = 1.0) -> int:
        """One dab at `centre` (scene units, on the skin): the layer's mask is painted towards `level`
        (1 white, 0 black; erase = black). Returns the points it reached."""
        radius = radius_cm / self.unit_cm
        idx, dist = self.brush.reach(centre, radius, normal)
        if len(idx):
            self.md.dab(self.layer_id, idx, logic.brush_weights(dist, radius, soft), erase, self.kind, level)
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

def mask_add(node, name: str = "", value: float = config.MASK_DENSITY_DEFAULT, opacity: float = 1.0,
             scope: str = "all", group: str = "", locks: Iterable[int] = (), kind: str = "fill",
             parent: int | None = None) -> int:
    """A new layer on top of the stack. `kind` (config.MASK_KINDS): "fill", a layer "= `value` strands / cm2"
    with a black mask to paint white where it applies; "folder" holds layers (`parent`), with a mask and
    opacity over them all. `scope` is the layer's owner: every lock, a group, or chosen locks. Nothing
    changes in the hair until something is painted. Returns its id."""
    _require_parm(node)
    if scope not in config.MASK_SCOPES:
        raise ValueError(f"mask layer scope {scope!r}")
    if kind not in config.MASK_KINDS:
        raise ValueError(f"mask layer kind {kind!r}")
    data = _read(node)
    layer = data.add_mask(name, value, opacity, scope, group, locks, kind, parent)
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


def mask_set(node, layer_id: int, name: str | None = None, on: bool | None = None,
             opacity: float | None = None, scope: str | None = None, group: str | None = None,
             locks: Iterable[int] | None = None, value: float | None = None) -> bool:
    """Change a layer's row: any of name, on, opacity, owner (scope with its group or locks), a fill layer's
    density (strands / cm2). One undo step; False when nothing changed."""
    data = _read(node)
    layer = data.mask(layer_id)
    if layer is None:
        raise KeyError(layer_id)
    if scope is not None and scope not in config.MASK_SCOPES:
        raise ValueError(f"mask layer scope {scope!r}")
    before = model.MaskLayer(**{**layer.__dict__, "locks": list(layer.locks)})
    if name is not None:
        layer.name = str(name)
    if on is not None:
        layer.on = bool(on)
    if opacity is not None:
        layer.opacity = min(1.0, max(0.0, float(opacity)))
    if scope is not None:
        layer.scope = scope
    if group is not None:
        layer.group = str(group)
    if locks is not None:
        layer.locks = sorted({int(i) for i in locks})
    if value is not None:
        layer.value = min(config.MASK_DENSITY_MAX, max(0.0, float(value)))
    if layer == before:
        return False
    what = [k for k in ("name", "on", "opacity", "scope", "group", "locks", "value")
            if getattr(layer, k) != getattr(before, k)]
    _write(node, f"Mask layer {layer.name}: {', '.join(what)}", data=data)
    return True


def _layer_or_raise(data: model.GroomData, layer_id: int) -> model.MaskLayer:
    layer = data.mask(layer_id)
    if layer is None:
        raise KeyError(layer_id)
    return layer


def mask_fill(node, layer_id: int, value: float = 1.0) -> None:
    """The layer's (or folder's) whole mask at `value` (1 = a white mask: it applies everywhere)."""
    data = _read(node)
    layer = _layer_or_raise(data, layer_id)
    md = read_masks(node)
    md.ensure(layer_id, layer.kind)
    md.a[layer_id][:] = min(max(float(value), 0.0), 1.0)
    _write(node, f"Fill mask layer {layer.name}", md=md)


def mask_clear(node, layer_id: int) -> None:
    """Nothing painted on the layer any more; the layer stays. A fill layer then applies nowhere (a black
    mask), a folder everywhere (no mask)."""
    data = _read(node)
    layer = _layer_or_raise(data, layer_id)
    md = read_masks(node)
    md.drop(layer_id)
    _write(node, f"Clear mask layer {layer.name}", md=md)


def mask_invert(node, layer_id: int) -> None:
    """Invert the layer's mask (white <-> black)."""
    data = _read(node)
    layer = _layer_or_raise(data, layer_id)
    md = read_masks(node)
    md.ensure(layer_id, layer.kind)
    md.a[layer_id] = (1.0 - md.a[layer_id]).astype(md.a[layer_id].dtype)
    _write(node, f"Invert mask of {layer.name}", md=md)


def mask_values(node, layer_id: int):
    """The layer's mask per fine-scalp point (numpy float32: 1 white, 0 black)."""
    data = _read(node)
    layer = _layer_or_raise(data, layer_id)
    return read_masks(node).mask(layer)


def mask_cover(node, lock_id: int | None = None):
    """(keep, add) per fine-scalp point: the share of the automatic groom that stays and the density the
    layers put there (strands / cm2; `logic.mask_density`). For one lock (the layers that reach it), or of
    the "all locks" layers when `lock_id` is None."""
    data = _read(node)
    md = read_masks(node)
    if lock_id is None:
        return md.compose([m for m in data.masks if m.kind == "folder" or m.scope == "all"])
    lk = data.lock(lock_id)
    group = lk.group if lk is not None else ""
    return md.compose([m for m in data.masks if m.kind == "folder" or m.applies(lock_id, group)])


def mask_dropped(node) -> str:
    """What the artist is told about layers this version dropped on opening the scene (an older test
    build's blend modes, factor and paint layers), "" when none: for the panel's message line. The stored
    JSON keeps them until the next edit writes it."""
    return model.dropped_text(model.dropped_masks(node.evalParm(config.DATA_PARM)))


def mask_stroke(node, layer_id: int, points: Sequence[Sequence[float]], radius_cm: float = config.BRUSH_RADIUS_CM,
                soft: float = config.BRUSH_SOFT, erase: bool = False,
                normals: Sequence[Sequence[float]] | None = None, level: float = 1.0) -> int:
    """One stroke through `points` (on the skin, scene units) as the brush would paint it; one undo step.
    The layer's mask is painted `level` (1 white, 0 black). Returns the dabs that reached skin."""
    if _read(node).mask(layer_id) is None:
        raise KeyError(layer_id)
    session = PaintSession(node, layer_id)
    session.begin()
    landed = 0
    for i, p in enumerate(points):
        nrm = normals[i] if normals is not None else None
        landed += int(session.stroke_to(p, nrm, radius_cm, soft=soft, erase=erase, level=level) > 0)
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
BRUSH: dict[str, Any] = {"radius_cm": config.BRUSH_RADIUS_CM, "soft": config.BRUSH_SOFT, "erase": False,
                         "xray": False, "view": "density", "level": 1.0}
PAINT: dict[str, Any] = {"node": None, "layer": None}    # node path and layer id while Paint is on


def set_brush(radius_cm: float | None = None, soft: float | None = None, erase: bool | None = None,
              xray: bool | None = None, view: str | None = None, level: float | None = None) -> dict:
    """Brush settings of the session (not saved, no undo): radius in cm, the soft share of the radius, what
    the mask is painted (`level`: 1 white, 0 black; `erase` = black), the scalp's X-ray, and what the scalp
    shows (`view`, config.MASK_VIEWS: the density as it is, the painted layer's mask alone, or the roots as
    dots). Choosing "density" or "roots" counts the groom's roots, which grows the locks the cache does not
    hold in full. Returns them all."""
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
    md.a = {i: a for i, a in md.a.items() if data.mask(i) is not None}     # a dropped layer's mask stays behind
    _write(node, "Mask layers from a publish", data=data, md=md)
    return len(layers)


__all__ = [
    "mask_add", "mask_remove", "mask_move", "mask_set", "mask_fill", "mask_clear", "mask_invert", "mask_values",
    "mask_cover", "mask_dropped",
    "mask_stroke", "mask_problem", "mask_rebake", "set_brush", "brush", "paint_enter", "paint_exit",
    "paint_layer", "import_masks", "masks_from_publish",
]
