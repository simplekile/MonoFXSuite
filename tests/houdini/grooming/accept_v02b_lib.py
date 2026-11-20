"""Measures shared by accept_v02b.py and accept_v02b_shot.py (hython; not collected by pytest).

Everything here is written apart from the tool's code where it judges the tool: the carry rule a strand or a mesh
point is held to (`carry`), where a lock's strands lie across it (`spread`), the bend a check asks for (`bend`).
Places are in the node's space (scene units) unless a name says cm."""
from __future__ import annotations

import math

import hou
import numpy as np


def strands(geo, unit: float) -> dict[int, list[tuple[int, np.ndarray]]]:
    """{lock id: [(strand id, points cm (n, 3))]} of a strand geometry (GROOM_REST / GROOM)."""
    from apps.houdini import grooming_masks as gm
    P = np.frombuffer(geo.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(np.float64) * unit
    vp, vpt = gm._vertex_tables(geo)
    order = np.argsort(vp, kind="stable")
    lock = np.frombuffer(geo.primIntAttribValuesAsString("lock_id"), np.int32)
    sid = np.frombuffer(geo.primIntAttribValuesAsString("id"), np.int32) if geo.findPrimAttrib("id") \
        else np.arange(len(lock), dtype=np.int32)
    nv = np.bincount(vp, minlength=len(lock))
    s = np.concatenate([[0], np.cumsum(nv)])
    pts = P[vpt[order]]
    out: dict[int, list] = {}
    for k in range(len(lock)):
        out.setdefault(int(lock[k]), []).append((int(sid[k]), pts[s[k]:s[k + 1]]))
    return out


def rows(node, name: str) -> dict:
    """{lock id: P, tangent, axis} of an inner spine node (SPINES_MEASURED / SPINES), scene units."""
    from apps.houdini import grooming_adapter as ga
    n = node.node(name)
    n.cook()
    return ga._spine_rows(n.geometry())


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def frames_at(row: dict, u: np.ndarray):
    """(c, t, a, m) of a spine at parameters u (by point index, as VEX primuv on an open polyline): the frame made
    square (tangent, width axis, thickness axis)."""
    P, T, A = row["P"], row["tangent"], row["axis"]
    n = len(P)
    x = np.clip(np.asarray(u, dtype=float), 0, 1) * (n - 1)
    j = np.minimum(np.floor(x).astype(int), n - 2)
    f = (x - j)[:, None]
    c = P[j] * (1 - f) + P[j + 1] * f
    t = _unit(T[j] * (1 - f) + T[j + 1] * f)
    a = A[j] * (1 - f) + A[j + 1] * f
    a = _unit(a - t * np.sum(a * t, axis=1, keepdims=True))
    return c, t, a, np.cross(t, a)


def nearest_u(X: np.ndarray, P: np.ndarray) -> np.ndarray:
    """Each point's parameter (by point index) at its nearest place on polyline P."""
    a, b = P[:-1], P[1:]
    ab = b - a
    l2 = np.maximum((ab ** 2).sum(1), 1e-18)
    out = np.empty(len(X))
    for i in range(0, len(X), 4000):
        x = X[i:i + 4000]
        t = np.clip(((x[:, None, :] - a[None]) * ab[None]).sum(-1) / l2[None], 0, 1)
        d = np.linalg.norm(x[:, None, :] - (a[None] + t[..., None] * ab[None]), axis=-1)
        j = d.argmin(1)
        out[i:i + 4000] = (j + t[np.arange(len(j)), j]) / (len(P) - 1)
    return out


def carry(X: np.ndarray, u: np.ndarray, before: dict, after: dict) -> np.ndarray:
    """Points X lying at parameters u of the spine `before`, put on the spine `after` by the same offset in its
    frame: the "same bend carried" (the plan's carry rule)."""
    c0, t0, a0, m0 = frames_at(before, u)
    c1, t1, a1, m1 = frames_at(after, u)
    d = X - c0
    return c1 + t1 * np.sum(d * t0, 1, keepdims=True) + a1 * np.sum(d * a0, 1, keepdims=True) \
        + m1 * np.sum(d * m0, 1, keepdims=True)


def poly_dist(X: np.ndarray, C: np.ndarray) -> np.ndarray:
    a, b = C[:-1], C[1:]
    ab = b - a
    l2 = np.maximum((ab ** 2).sum(1), 1e-18)
    t = np.clip(((X[:, None, :] - a[None]) * ab[None]).sum(-1) / l2[None], 0, 1)
    return np.linalg.norm(X[:, None, :] - (a[None] + t[..., None] * ab[None]), axis=-1).min(1)


def follow(before: list, after: list, row0: dict, row1: dict, unit: float) -> dict:
    """How far the edited lock's strands (`after`, cm) lie from the unedited ones (`before`, cm) carried by the
    bend: each point's distance to the carried strand of the same id. cm."""
    old = {sid: P for sid, P in before}
    res = []
    for sid, P in after:
        if sid not in old:
            continue
        X = old[sid] / unit
        C = carry(X, nearest_u(X, row0["P"]), row0, row1) * unit
        res.append(poly_dist(P, C))
    d = np.concatenate(res) if res else np.zeros(0)
    q = (lambda p: float(np.percentile(d, p))) if len(d) else (lambda p: None)
    return {"strands": len(res), "points": int(len(d)), "p50_cm": q(50), "p95_cm": q(95), "max_cm": q(100)}


def spread(lock_strands: list, row: dict, unit: float, stations=(0.3, 0.5, 0.7, 0.9), band: float = 0.025) -> dict:
    """Where the lock's strand points lie across it at each station (a share of its spine): the standard
    deviation of their offsets along the width axis and along the thickness axis there, cm."""
    X = np.concatenate([P for _sid, P in lock_strands]) / unit
    u = nearest_u(X, row["P"])
    out = {}
    for s in stations:
        sel = np.abs(u - s) <= band
        if sel.sum() < 10:
            out[str(s)] = None
            continue
        c, t, a, m = frames_at(row, u[sel])
        d = X[sel] - c
        out[str(s)] = {"width_cm": float(np.std(np.sum(d * a, 1)) * unit),
                       "thick_cm": float(np.std(np.sum(d * m, 1)) * unit), "points": int(sel.sum())}
    return out


def extent(lock_strands: list, row: dict, unit: float, stations=(0.3, 0.5, 0.7, 0.9), band: float = 0.025) -> dict:
    """The hair's width and thickness at each station: the 2nd to the 98th percentile of the offsets across, cm."""
    X = np.concatenate([P for _sid, P in lock_strands]) / unit
    u = nearest_u(X, row["P"])
    out = {}
    for s in stations:
        sel = np.abs(u - s) <= band
        if sel.sum() < 10:
            out[str(s)] = None
            continue
        c, t, a, m = frames_at(row, u[sel])
        d = X[sel] - c
        w, th = np.sum(d * a, 1), np.sum(d * m, 1)
        out[str(s)] = {"width_cm": float((np.percentile(w, 98) - np.percentile(w, 2)) * unit),
                       "thick_cm": float((np.percentile(th, 98) - np.percentile(th, 2)) * unit)}
    return out


def measured_handles(row: dict, K: int) -> np.ndarray:
    """The measured spine's K handles in its root frame (what "no edit" would store), computed here."""
    P, T, A = row["P"], row["tangent"], row["axis"]
    S = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    s = np.linspace(0, S[-1], K)
    j = np.clip(np.searchsorted(S, s, side="right") - 1, 0, len(P) - 2)
    f = ((s - S[j]) / np.maximum(S[j + 1] - S[j], 1e-12))[:, None]
    marks = P[j] * (1 - f) + P[j + 1] * f
    t0 = _unit(T[0])
    a0 = _unit(A[0] - t0 * np.dot(A[0], t0))
    R = np.stack([t0, a0, np.cross(t0, a0)])
    H = (marks - P[0]) @ R.T
    H[0] = 0.0
    return H


def bend(row: dict, K: int, cm: float, unit: float) -> np.ndarray:
    """Handles (root frame) of the measured spine with its far part pushed `cm` along the width axis, growing as
    (k / (K - 1))^2: the tip moves `cm` (the spike's q3 bend)."""
    H = measured_handles(row, K)
    for k in range(1, K):
        H[k, 1] += cm / unit * (k / (K - 1)) ** 2
    return H


def turn(row: dict, K: int, degrees: float) -> np.ndarray:
    """Handles (root frame) of the measured spine turned about its root round the thickness axis."""
    H = measured_handles(row, K)
    a = math.radians(degrees)
    Rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    return H @ Rz.T


def to_skin_cm(points, scalp_geo, unit: float, limit: int = 400) -> np.ndarray:
    """Distance of (up to `limit` of) these points (node space) to a surface geometry, cm."""
    pts = np.asarray(points, dtype=float)
    step = max(1, len(pts) // limit)
    out = []
    for x in pts[::step]:
        pr, u, v, _ = scalp_geo.nearestPrim(hou.Vector3(*x))
        if pr is not None:
            out.append((hou.Vector3(*x) - pr.positionAtInterior(u, v)).length() * unit)
    return np.array(out)


def bare_spot(node, unit: float, group: str = "") -> tuple[np.ndarray, np.ndarray]:
    """(place on the rest scalp, its normal): the centre of the fine scalp prim farthest from every lock's root
    (prims under 0.001 cm2, Helen's sliver band by the ears, left out), the spike's rule for a drawn lock's place.
    `group`: only among the prims a lock of that group owns (the spike's lock lay on hair_back skin)."""
    from apps.houdini import grooming_masks as gm
    geo = node.node("SCALP_REGIONS").geometry()
    vp, vpt = gm._vertex_tables(geo)
    P = np.frombuffer(geo.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(np.float64)
    n = geo.intrinsicValue("primitivecount")
    cnt = np.bincount(vp, minlength=n)
    cen = np.stack([np.bincount(vp, weights=P[vpt, k], minlength=n) for k in range(3)], 1) / np.maximum(cnt, 1)[:, None]
    area = np.frombuffer(geo.primFloatAttribValuesAsString("area_cm2"), np.float32)
    sp = rows(node, "SPINES")
    roots = np.array([r["P"][0] for r in sp.values()])
    d = np.sqrt(((cen[:, None, :] - roots[None]) ** 2).sum(-1)).min(1)
    d[area < 0.001] = -1
    if group:
        from apps.houdini import grooming_adapter as ga
        mine = {lk.id for lk in ga.read_data(node).locks if lk.group == group}
        owners = geo.primIntListAttribValues("lock_owners")
        d[[not any(o in mine for o in own) for own in owners]] = -1
    k = int(np.argmax(d))
    scalp = node.node("IN_SCALP").geometry()
    pr, u, v, _ = scalp.nearestPrim(hou.Vector3(*cen[k]))
    return np.array(pr.positionAtInterior(u, v)), np.array(pr.normal())


def drawn_stroke(root, normal, length_cm: float, unit: float, n: int = 16) -> list:
    """A stroke from `root` out along the skin's normal and falling (gravity -y), about `length_cm` long."""
    nrm = _unit(np.asarray(normal, dtype=float))
    down = np.array([0.0, -1.0, 0.0])
    side = down - nrm * np.dot(down, nrm)
    pts = [np.asarray(root) + (nrm * 0.55 * s + _unit(side) * 0.85 * s * s) * length_cm / unit
           for s in np.linspace(0, 1, n)]
    return [list(map(float, p)) for p in pts]
