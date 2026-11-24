"""How an edited lock rides a shot (U4 as changed by the user, 2026-11-22): measured apart from the tool's code.

The lock's MOVING FRAME: its unedited spine (SPINES_MEASURED) and two copies of it offset along its width and
thickness axes, deformed by v0.1's Point Deform (captured on the rest hair mesh, deformed by the animated hair mesh,
the node's deform_radius), outside the node. At a parameter u of the spine: origin P'(u), axes from the offset
copies made square (tangent, width, thickness). At rest the same with the rest spine.

  offset_change  the edited strands' offset from the unedited strands of the same strand id, at 10 shares of each
                 strand, in the moving frame at the unedited point's place on the spine: |frame - rest| (cm)
  own_noise      the unedited lock's own points in its moving frame: |offset from the spine at the frame - at rest|
                 (cm): what the frame does not describe of the unedited lock itself (the limit is set from it)
Everything in scene units in, cm out."""
from __future__ import annotations

import hou
import numpy as np

import accept_v02b_lib as alib

SHARES = np.linspace(0.1, 1.0, 10)


class MovingFrame:
    """The deformed unedited spine of one lock and two offset copies (outside the node)."""

    def __init__(self, node, lock_id: int, unit: float, tag: str = "mf"):
        net = node.parent()
        self.unit = unit
        rows = alib.rows(node, "SPINES_MEASURED")
        self.rest = rows[lock_id]
        eps = 0.5 / unit
        P, T, A = self.rest["P"], self.rest["tangent"], self.rest["axis"]
        t = alib._unit(T)
        a = alib._unit(A - t * np.sum(A * t, 1, keepdims=True))
        m = np.cross(t, a)
        self.rest_axes = (t, a, m)
        geo = hou.Geometry()
        for k, Q in enumerate((P, P + a * eps, P + m * eps)):
            pts = geo.createPoints([tuple(map(float, q)) for q in Q])
            poly = geo.createPolygon(is_closed=False)
            for pt in pts:
                poly.addVertex(pt)
        self.stash = net.createNode("stash", tag + "_spine")
        self.stash.parm("stash").set(geo)
        om_rest = net.createNode("object_merge", tag + "_rest_hair")
        om_rest.parm("objpath1").set(node.node("IN_HAIR").path())
        om_anim = net.createNode("object_merge", tag + "_anim_hair")
        om_anim.parm("objpath1").set(node.node("ANIM_HAIR").path())
        rad = node.evalParm("deform_radius")
        cap = net.createNode("pointdeform", tag + "_cap")
        cap.setInput(0, self.stash)
        cap.setInput(1, om_rest)
        cap.parm("mode").set("capture")
        cap.parm("radius").set(rad)
        self.dfm = net.createNode("pointdeform", tag + "_def")
        self.dfm.setInput(0, cap)
        self.dfm.setInput(1, om_rest)
        self.dfm.setInput(2, om_anim)
        self.dfm.parm("mode").set("deform")
        self.dfm.parm("radius").set(rad)
        self.eps = eps
        self.n = len(P)

    def at(self, u, now: bool):
        """(origin, R rows t/a/m) at parameters u (by point index), rest or at the current frame."""
        if not now:
            c, t, a, m = alib.frames_at(self.rest, u)
            return c, np.stack([t, a, m], 1)
        self.dfm.cook(force=True)
        Q = np.frombuffer(self.dfm.geometry().pointFloatAttribValuesAsString("P"), np.float32).reshape(3, self.n, 3)
        x = np.clip(np.asarray(u, float), 0, 1) * (self.n - 1)
        j = np.minimum(np.floor(x).astype(int), self.n - 2)
        f = (x - j)[:, None]
        lerp = lambda Z: Z[j] * (1 - f) + Z[j + 1] * f  # noqa: E731
        c, ca, cm = lerp(Q[0].astype(float)), lerp(Q[1].astype(float)), lerp(Q[2].astype(float))
        a = alib._unit(ca - c)
        mm = alib._unit(cm - c)
        t = alib._unit(np.cross(a, mm))
        a = alib._unit(a - t * np.sum(a * t, 1, keepdims=True))
        return c, np.stack([t, a, np.cross(t, a)], 1)


def sample(strands: list, unit: float):
    """{strand id: points (cm) at SHARES of its length}."""
    out = {}
    for sid, P in strands:
        L = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
        if L[-1] <= 0:
            continue
        out[sid] = np.stack([np.interp(SHARES * L[-1], L, P[:, k]) for k in range(3)], 1)
    return out


def local(mf: MovingFrame, X_cm, now: bool, u=None):
    """Points (cm) in the moving frame: (local coords cm, u)."""
    X = np.asarray(X_cm) / mf.unit
    if u is None:
        u = alib.nearest_u(X, mf.rest["P"]) if not now else None
    c, R = mf.at(u, now)
    return np.einsum("nij,nj->ni", R, X - c) * mf.unit, u


def offsets(mf: MovingFrame, rest_u: dict, rest_e: dict, now_u: dict, now_e: dict) -> dict:
    """offset_change of an edited lock against the unedited one (both at rest and at the frame, by strand id)."""
    ids = [s for s in rest_u if s in rest_e and s in now_u and s in now_e]
    if not ids:
        return {"strands": 0}
    U0 = np.concatenate([rest_u[s] for s in ids])
    E0 = np.concatenate([rest_e[s] for s in ids])
    U1 = np.concatenate([now_u[s] for s in ids])
    E1 = np.concatenate([now_e[s] for s in ids])
    u = alib.nearest_u(U0 / mf.unit, mf.rest["P"])
    _c0, R0 = mf.at(u, False)
    _c1, R1 = mf.at(u, True)
    d0 = np.einsum("nij,nj->ni", R0, E0 - U0)
    d1 = np.einsum("nij,nj->ni", R1, E1 - U1)
    err = np.linalg.norm(d1 - d0, axis=1)
    share = np.tile(SHARES, len(ids))
    tip = share >= 0.85
    q = lambda v, p: round(float(np.percentile(v, p)), 4)  # noqa: E731
    return {"strands": len(ids), "rest_offset_p50_cm": q(np.linalg.norm(d0, axis=1), 50),
            "rest_offset_max_cm": q(np.linalg.norm(d0, axis=1), 100),
            "change_p50_cm": q(err, 50), "change_p95_cm": q(err, 95), "change_max_cm": q(err, 100),
            "tip_change_p95_cm": q(err[tip], 95) if tip.any() else None,
            "by_share_p95_cm": {str(round(float(s), 2)): q(err[np.isclose(share, s)], 95) for s in SHARES}}


def own_noise(mf: MovingFrame, rest_u: dict, now_u: dict) -> dict:
    """own_noise of the unedited lock: its points' offset from its spine in the moving frame, frame against rest."""
    ids = [s for s in rest_u if s in now_u]
    U0 = np.concatenate([rest_u[s] for s in ids])
    U1 = np.concatenate([now_u[s] for s in ids])
    u = alib.nearest_u(U0 / mf.unit, mf.rest["P"])
    c0, R0 = mf.at(u, False)
    c1, R1 = mf.at(u, True)
    l0 = np.einsum("nij,nj->ni", R0, U0 / mf.unit - c0) * mf.unit
    l1 = np.einsum("nij,nj->ni", R1, U1 / mf.unit - c1) * mf.unit
    err = np.linalg.norm(l1 - l0, axis=1)
    q = lambda v, p: round(float(np.percentile(v, p)), 4)  # noqa: E731
    return {"p50_cm": q(err, 50), "p95_cm": q(err, 95), "max_cm": q(err, 100)}
