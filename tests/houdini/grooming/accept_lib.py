"""Shared by the MONO Grooming acceptance scripts (accept_v02a.py in hython, accept_v02a_gui.py in the GUI).

Nothing here is collected by pytest (no test_ name); it needs Houdini. The scene comes by argument and stays in
the sandbox; every file is written under the out folder given."""

from __future__ import annotations

import json
import os
import time
import traceback

import hou
import numpy as np


class Checks:
    """The acceptance record: one entry per check, written after each so a crash keeps what ran."""

    def __init__(self, out_dir: str, name: str = "accept.json", meta: dict | None = None):
        self.out_dir = out_dir
        self.path = os.path.join(out_dir, name).replace("\\", "/")
        self.items: list[dict] = []
        self.meta = dict(meta or {})
        self.log_path = os.path.splitext(self.path)[0] + "_log.txt"
        open(self.log_path, "w", encoding="utf-8").close()

    def log(self, *parts) -> None:
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(" ".join(str(p) for p in parts) + "\n")

    def add(self, item: str, passed, value=None, limit=None, evidence: str = "", note: str = "") -> bool:
        """`passed` None: a KNOWN, decided miss, reported with its numbers and counted neither as a pass nor as a
        fail (listed under "known")."""
        entry = {"item": item, "pass": None if passed is None else bool(passed), "value": value, "limit": limit,
                 "evidence": evidence or os.path.basename(self.path)}
        if note:
            entry["note"] = note
        self.items = [i for i in self.items if i["item"] != item] + [entry]
        word = "KNOWN" if passed is None else "PASS" if passed else "FAIL"
        self.log(word, item, json.dumps(value, default=str)[:300], "limit", limit, note)
        self.write()
        return bool(passed)

    def run(self, item: str, fn) -> None:
        """Run one check function; an exception is that check failing, with the traceback as its value."""
        try:
            fn()
        except Exception:
            self.add(item, False, traceback.format_exc()[-1500:], note="the check raised")

    def write(self, done: bool = False) -> None:
        data = dict(self.meta)
        data["checks"] = self.items
        data["passed"] = bool(self.items) and all(i["pass"] is not False for i in self.items)
        data["failed"] = [i["item"] for i in self.items if i["pass"] is False]
        data["known"] = [i["item"] for i in self.items if i["pass"] is None]
        data["done"] = done
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, default=str)


def open_scene(suite: str, scene: str):
    """Load `scene` with this suite's HDA (a hip names the library it was saved with, and Houdini prefers
    the newest file). Returns (adapter module, the MONO Grooming node)."""
    hou.hda.installFile(suite + "/otls/mono_grooming.hdalc")
    hou.hipFile.load(scene, suppress_save_prompt=True, ignore_load_warnings=True)
    hou.hda.installFile(suite + "/otls/mono_grooming.hdalc", force_use_assets=True)
    from apps.houdini import grooming_adapter as ga
    node = ga.find_nodes()[0]
    return ga, node


def node_errors(node) -> list[str]:
    out = [node.path() + ": " + " ".join(node.errors())] if node.errors() else []
    return out + [c.path() + ": " + " ".join(c.errors())[:300] for c in node.allSubChildren() if c.errors()]


def node_warnings(node) -> list[str]:
    return sorted({c.name() + ": " + " ".join(c.warnings())[:200] for c in node.allSubChildren() if c.warnings()})


class Groom:
    """Reads of one node the checks share: cooks with what they cost, roots, regions."""

    def __init__(self, ga, node):
        self.ga, self.node = ga, node
        self.unit = float(node.evalParm("unit_cm"))
        self.rest = node.node("GROOM_REST")           # output 1 at rest: every lock, full, whatever the view
        # read through an Object Merge: a node outside a locked HDA cannot be wired to one inside it
        merge = node.parent().createNode("object_merge", "accept_groom_rest")
        merge.parm("objpath1").set(self.rest.path())
        self._roots = node.parent().createNode("attribwrangle", "accept_roots")
        self._roots.setInput(0, merge)
        self._roots.parm("class").set(1)
        self._roots.parm("snippet").set('v@r = point(0, "P", primpoint(0, @primnum, 0));' + chr(10)
                                         + 'v@tip = point(0, "P", primpoint(0, @primnum, primvertexcount(0, @primnum) - 1));')
        self._scalp = None

    # ---- cooks ----
    def cook_display(self) -> dict:
        """Cook output 0 as the viewport would; the seconds and the locks that went through the loop."""
        t = time.perf_counter()
        self.node.cook()
        s = time.perf_counter() - t
        geo = self.node.node("to_cook").geometry()
        return {"s": s, "locks": sorted(geo.primIntAttribValues("lock_id")) if geo.findPrimAttrib("lock_id") else []}

    def cook_rest(self) -> dict:
        """Cook output 1's rest groom (its own loop through the same cache)."""
        t = time.perf_counter()
        self.rest.cook()
        s = time.perf_counter() - t
        geo = self.node.node("groom_to_cook").geometry()
        return {"s": s, "locks": sorted(geo.primIntAttribValues("lock_id")) if geo.findPrimAttrib("lock_id") else [],
                "strands": self.rest.geometry().intrinsicValue("primitivecount")}

    def strands(self) -> int:
        self.rest.cook()
        return self.rest.geometry().intrinsicValue("primitivecount")

    def strands_by_lock(self) -> dict[int, int]:
        self.rest.cook()
        ids = np.frombuffer(self.rest.geometry().primIntAttribValuesAsString("lock_id"), np.int32)
        u, c = np.unique(ids, return_counts=True)
        return {int(a): int(b) for a, b in zip(u, c)}

    def roots(self):
        """(root positions in cm (n, 3), lock id per root) of the rest groom."""
        geo = self._roots.geometry()
        r = np.frombuffer(geo.primFloatAttribValuesAsString("r"), np.float32).reshape(-1, 3) * self.unit
        return r.astype(np.float64), np.frombuffer(geo.primIntAttribValuesAsString("lock_id"), np.int32)

    def root_ids(self):
        """The strand `id` of each root, in the order of `roots()`: its number in the lock's automatic scatter;
        a layer's own root is numbered from LAYER_ROOT_ID."""
        return np.frombuffer(self._roots.geometry().primIntAttribValuesAsString("id"), np.int32)

    def strands_by_id(self) -> dict:
        """Per lock id: {strand id: (root cm, tip cm)} of the rest groom. A strand's `id` is its number in the
        lock's automatic scatter (the same from cook to cook); the layers' own strands are numbered from
        10,000,000."""
        geo = self._roots.geometry()
        r = np.frombuffer(geo.primFloatAttribValuesAsString("r"), np.float32).reshape(-1, 3) * self.unit
        t = np.frombuffer(geo.primFloatAttribValuesAsString("tip"), np.float32).reshape(-1, 3) * self.unit
        lock = np.frombuffer(geo.primIntAttribValuesAsString("lock_id"), np.int32)
        ids = np.frombuffer(geo.primIntAttribValuesAsString("id"), np.int32)
        out = {}
        for k in np.unique(lock):
            sel = lock == k
            out[int(k)] = (ids[sel].copy(), r[sel].astype(np.float64), t[sel].astype(np.float64))
        return out

    # ---- the skin ----
    def scalp(self) -> dict:
        """The fine scalp with its split, read once (the split does not change during a run unless a check
        asks for Update regions: call `forget()` then)."""
        if self._scalp is None:
            from apps.houdini import grooming_masks as gm
            geo = self.node.node("SCALP_REGIONS").geometry()
            vprim, vpoint = gm._vertex_tables(geo)
            P = np.frombuffer(geo.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(np.float64)
            n = geo.intrinsicValue("primitivecount")
            order = np.argsort(vprim, kind="stable")
            counts = np.bincount(vprim, minlength=n)
            cen = np.zeros((n, 3))
            for k in range(3):
                cen[:, k] = np.bincount(vprim, weights=P[vpoint, k], minlength=n) / np.maximum(counts, 1)
            by_prim = vpoint[order]        # once: indexed inside the list below it made 24 k copies (20 GB)
            self._scalp = {"P": P, "P_cm": P * self.unit, "cen_cm": cen * self.unit, "vprim": vprim, "vpoint": vpoint,
                           "owners": geo.primIntListAttribValues("lock_owners"),
                           "area": np.frombuffer(geo.primFloatAttribValuesAsString("area_cm2"), np.float32).astype(float),
                           "prim_points": [by_prim[s:s + c] for s, c in
                                           zip(np.concatenate(([0], np.cumsum(counts)[:-1])), counts)]}
        return self._scalp

    def forget(self) -> None:
        self._scalp = None

    def lock_id(self, name: str) -> int:
        return next(lk.id for lk in self.ga.read_data(self.node).locks if lk.name == name)

    def lock_names(self) -> dict[int, str]:
        return {lk.id: lk.name for lk in self.ga.read_data(self.node).locks}

    def region_prims(self, lock_id: int) -> np.ndarray:
        return np.array([i for i, own in enumerate(self.scalp()["owners"]) if lock_id in own], dtype=int)

    def prim_factor(self, factor) -> np.ndarray:
        """(lowest, highest) factor of each scalp prim's points, from a factor per point."""
        s = self.scalp()
        lo = np.full(len(s["area"]), np.inf)
        hi = np.full(len(s["area"]), -np.inf)
        np.minimum.at(lo, s["vprim"], factor[s["vpoint"]])
        np.maximum.at(hi, s["vprim"], factor[s["vpoint"]])
        return lo, hi

    def inner_prims(self, inside: np.ndarray, margin_cm: float) -> np.ndarray:
        """Of the prims flagged `inside` (bool per prim), those whose centre lies at least `margin_cm` from
        every prim that is not: counts are taken there, away from a zone's edge (hairgen relaxes its roots,
        and a root is given to the prim nearest it)."""
        cen = self.scalp()["cen_cm"]
        idx = np.nonzero(inside)[0]
        if not len(idx):
            return idx
        lo, hi = cen[idx].min(0) - margin_cm, cen[idx].max(0) + margin_cm
        near = np.nonzero(~inside & (cen >= lo).all(1) & (cen <= hi).all(1))[0]
        if not len(near):
            return idx
        keep = np.ones(len(idx), dtype=bool)
        for i in range(0, len(idx), 500):
            d = ((cen[idx[i:i + 500], None, :] - cen[None, near, :]) ** 2).sum(-1)
            keep[i:i + 500] = d.min(1) >= margin_cm * margin_cm
        return idx[keep]

    def roots_on(self, prims: np.ndarray, roots=None, lock_id: int | None = None, reach_cm: float = 0.5):
        """Roots (all locks, or one) whose nearest scalp prim centre is one of `prims`: (count, positions).
        Only roots within `reach_cm` of one of them are looked at."""
        r, lid = roots if roots is not None else self.roots()
        if lock_id is not None:
            r = r[lid == lock_id]
        cen = self.scalp()["cen_cm"]
        if not len(prims) or not len(r):
            return 0, r[:0]
        lo, hi = cen[prims].min(0) - reach_cm, cen[prims].max(0) + reach_cm
        r = r[(r >= lo).all(1) & (r <= hi).all(1)]
        hood = np.nonzero((cen >= lo - reach_cm).all(1) & (cen <= hi + reach_cm).all(1))[0]
        flag = np.isin(hood, prims)
        got = np.zeros(len(r), dtype=bool)
        for i in range(0, len(r), 500):
            d = ((r[i:i + 500, None, :] - cen[None, hood, :]) ** 2).sum(-1)
            j = d.argmin(1)
            got[i:i + 500] = flag[j] & (d[np.arange(len(j)), j] <= reach_cm * reach_cm)
        return int(got.sum()), r[got]

def fresh(ga, node) -> None:
    """The groom as v0.1's end-to-end test makes it (t55): every parm at its default (a scene keeps the
    values it was saved with), no layer, fresh Detect, Update regions, Hair, Shot deform off."""
    for p in node.parms():
        if p.name() not in ("groom_data", "regions", "mask_layers") and not p.isLocked():
            try:
                p.revertToDefaults()
            except hou.Error:
                pass
    node.parm("groom_data").set("")
    node.parm("regions").set(None)
    if node.parm("mask_layers") is not None:
        node.parm("mask_layers").set(None)
    ga.write_data(node, ga.model.GroomData(asset="char_Helen"), "fresh")
    ga.detect(node)
    ga.split_regions(node)
    ga.set_display(node, "hair", "lock")
    node.parm("shot_deform").set(0)
    node.setDisplayFlag(True)
    hou.setFrame(0)


def nn_dist(x: np.ndarray) -> np.ndarray:
    """Each point's distance to its nearest other point (grooming-check's root spacing measure)."""
    out = np.empty(len(x))
    for i in range(0, len(x), 2000):
        d = ((x[i:i + 2000, None, :] - x[None, :, :]) ** 2).sum(-1)
        rows = np.arange(i, min(i + 2000, len(x)))
        d[rows - i, rows] = np.inf
        out[i:i + 2000] = np.sqrt(d.min(1))
    return out


def spacing_stats(roots_cm: np.ndarray, area_cm2: float) -> dict:
    """grooming-check's root_spacing_low and root_clumped on one patch: the median nearest-root distance
    over the even spacing 1 / sqrt(roots / area), and the share of roots closer than 0.3 x that spacing."""
    n = len(roots_cm)
    if n < 5 or area_cm2 <= 0:
        return {"roots": n}
    spacing = 1.0 / np.sqrt(n / area_cm2)
    d = nn_dist(roots_cm)
    return {"roots": n, "per_cm2": n / area_cm2, "spacing_ratio": float(np.median(d) / spacing),
            "clumped": float(np.mean(d < 0.3 * spacing))}


def densest_spot(roots_cm: np.ndarray, radius: float = 1.0, sample: int = 1500):
    """grooming-check's whorl measure: the root with the most roots within `radius` cm.
    (centre, count there, roots / cm2 on that disc)."""
    if not len(roots_cm):
        return None, 0, 0.0
    cand = roots_cm[np.linspace(0, len(roots_cm) - 1, min(sample, len(roots_cm))).astype(int)]
    best, best_n = cand[0], -1
    for i in range(0, len(cand), 50):
        d = ((cand[i:i + 50, None, :] - roots_cm[None, :, :]) ** 2).sum(-1)
        n = (d <= radius * radius).sum(1)
        j = int(n.argmax())
        if n[j] > best_n:
            best, best_n = cand[i + j], int(n[j])
    return best, best_n, best_n / (np.pi * radius * radius)


def disc_density(roots_cm: np.ndarray, centre, radius: float = 1.0) -> float:
    """Roots / cm2 on the disc of `radius` cm round `centre`."""
    d = ((roots_cm - np.asarray(centre)) ** 2).sum(1)
    return float((d <= radius * radius).sum() / (np.pi * radius * radius))


def mask_arrays(node, layer_id: int):
    """(value, coverage) of a paint layer as stored on the node, copies; both None when it was never painted."""
    from tools.fx.grooming import config
    geo = node.parm(config.MASK_PARM).evalAsGeometry()
    if geo is None or geo.findPointAttrib(config.MASK_COVER_ATTR % layer_id) is None:
        return None, None
    value = None
    if geo.findPointAttrib(config.MASK_VALUE_ATTR % layer_id) is not None:
        value = np.frombuffer(geo.pointFloatAttribValuesAsString(config.MASK_VALUE_ATTR % layer_id), np.float32).copy()
    return value, np.frombuffer(geo.pointFloatAttribValuesAsString(config.MASK_COVER_ATTR % layer_id), np.float32).copy()


def same_arrays(a, b) -> bool:
    """Both (value, mask) pairs hold the same bytes (None = not stored)."""
    for x, y in zip(a, b):
        if (x is None) != (y is None) or (x is not None and not np.array_equal(x, y)):
            return False
    return True


# ---------------------------------------------------------------------------
# Places on the skin and counts there (v0.2a round 3: every check is graded at several kinds of skin)
# ---------------------------------------------------------------------------

class CookCount:
    """Locks really cooked: wraps LockCache.put (hair grown by the per-lock loop and stored), not `to_cook`.
    `captures`: locks whose Point Deform capture for output 1 was made again (`put_derived`, the capture
    slot): a capture from cached strands, no hair is grown for it."""

    def __init__(self, ga):
        self.cache = ga.hair_cache()
        self.puts: list[tuple[int, str]] = []
        self.caps: list[int] = []
        self._orig, self._orig_derived = self.cache.put, self.cache.put_derived
        capture = ga.GROOM_CAPTURE_MODE

        def put(node_id, lock_id, mode, key, value, *a, **kw):
            if lock_id >= 0:
                self.puts.append((int(lock_id), mode))
            return self._orig(node_id, lock_id, mode, key, value, *a, **kw)

        def put_derived(node_id, lock_id, mode, key, value, *a, **kw):
            if lock_id >= 0 and mode == capture:
                self.caps.append(int(lock_id))
            return self._orig_derived(node_id, lock_id, mode, key, value, *a, **kw)

        self.cache.put = put
        self.cache.put_derived = put_derived

    def take(self) -> list[int]:
        out = sorted({p[0] for p in self.puts})
        self.puts.clear()
        return out

    def captures(self) -> list[int]:
        out = sorted(set(self.caps))
        self.caps.clear()
        return out


class Skin:
    """The fine scalp of a fresh groom with helpers to pick places, paint discs through the real brush and
    count roots there. Everything in cm."""

    def __init__(self, G: Groom):
        self.G = G
        self.reload()

    def reload(self) -> None:
        self.G.forget()
        S = self.G.scalp()
        self.S = S
        self.own = S["owners"]
        self.area = S["area"]
        self.n = len(self.area)
        self.vp, self.vpt = S["vprim"], S["vpoint"]
        self.cen = S["cen_cm"]
        self.P = S["P_cm"]
        self.names = self.G.lock_names()
        self.nown = np.array([len(o) for o in self.own])
        # which lock owns which prim (`lock_owners`, whole prims: the HDA cuts a lock's region by them)
        ids = sorted({int(x) for o in self.own for x in o})
        self.owner_row = {k: i for i, k in enumerate(ids)}
        self.owns = np.zeros((len(ids) + 1, self.n), bool)       # last row: a lock that owns nothing here
        for p, o in enumerate(self.own):
            for x in o:
                self.owns[self.owner_row[int(x)], p] = True
        # every root assigned with its lock: how far it lies from its OWN lock's skin (t68, the check the
        # tie-break below could hide)
        self.own_checked, self.own_over, self.own_worst = 0, 0, 0.0

        # triangles of the skin (a fan a prim), for the distance from a root to the surface
        order = np.argsort(self.vp, kind="stable")
        pts = self.vpt[order]
        counts = np.bincount(self.vp, minlength=self.n)
        first = np.concatenate(([0], np.cumsum(counts)[:-1]))
        tri, tri_prim = [], []
        for k in range(1, int(counts.max()) - 1 if self.n else 0):
            has = np.nonzero(counts > k + 1)[0]
            tri.append(np.stack([pts[first[has]], pts[first[has] + k], pts[first[has] + k + 1]], 1))
            tri_prim.append(has)
        self.tri = np.concatenate(tri) if tri else np.zeros((0, 3), int)
        self.tri_prim = np.concatenate(tri_prim) if tri_prim else np.zeros(0, int)
        A, B, C = (self.P[self.tri[:, i]] for i in range(3))
        self.tcen = (A + B + C) / 3.0
        self.trad = np.sqrt(np.maximum(((A - self.tcen) ** 2).sum(1), np.maximum(((B - self.tcen) ** 2).sum(1),
                                                                               ((C - self.tcen) ** 2).sum(1))))

    def snap(self, c):
        return self.cen[((self.cen - np.asarray(c)) ** 2).sum(1).argmin()]

    TIE_CM = 1e-4     # two prims this close to a root are a tie: the root lies on their shared edge

    def assign(self, roots_cm, k: int = 16, lid=None):
        """(the skin prim nearest each root ON THE SURFACE, its distance to it in cm): the exact distance from
        the root to each of the nearest triangles (`closest_on_tri`), as the t64 checker counts. The nearest
        prim CENTRE gave a root on a large prim's edge to either prim and read roots of a curved prim as
        floating 0.3 cm off the skin (by the surface no root of Helen's groom is over 0.002 cm off it).
        With `lid` (each root's lock id): when a prim the root's own lock owns is within `TIE_CM` of the nearest,
        the root is given to it (t68: roots on an edge a lock's prim shares with a neighbour's went to the
        neighbour, and a lock read N = 0 with 1-2 roots), and each root's distance to its own lock's skin is
        counted (`own_checked` / `own_over` / `own_worst`)."""
        n = len(roots_cm)
        prim = np.full(n, -1)
        dist = np.full(n, np.inf)
        if not n or not len(self.tri):
            return prim, dist
        lo, hi = roots_cm.min(0) - 1.5, roots_cm.max(0) + 1.5
        hood = np.nonzero((self.tcen >= lo).all(1) & (self.tcen <= hi).all(1))[0]
        if not len(hood):
            return prim, dist
        tc, tr = self.tcen[hood], self.trad[hood]
        A, B, C = (self.P[self.tri[hood, i]] for i in range(3))
        kk = min(k, len(hood))
        for i in range(0, n, 256):
            r = roots_cm[i:i + 256]
            lb = np.sqrt(((r[:, None] - tc[None]) ** 2).sum(-1)) - tr[None]
            cand = np.argpartition(lb, kk - 1, axis=1)[:, :kk]
            q = closest_on_tri(r[:, None, :], A[cand], B[cand], C[cand])
            d = np.sqrt(((q - r[:, None, :]) ** 2).sum(-1))
            j = d.argmin(1)
            rows = np.arange(len(j))
            cp = self.tri_prim[hood[cand]]                  # the prim of each candidate triangle
            if lid is not None:
                own_row = np.array([self.owner_row.get(int(x), len(self.owns) - 1) for x in lid[i:i + 256]])
                mine = self.owns[own_row[:, None], cp]
                d_own = np.where(mine, d, np.inf)
                jo = d_own.argmin(1)
                od = d_own[rows, jo]
                tie = od <= d[rows, j] + self.TIE_CM
                j = np.where(tie, jo, j)
                self.own_checked += len(od)
                self.own_over += int((od > self.TIE_CM).sum())
                self.own_worst = max(self.own_worst, float(od.max()) if len(od) else 0.0)
            dist[i:i + 256] = d[rows, j]
            prim[i:i + 256] = cp[rows, j]
        return prim, dist

    def prim_minmax(self, f):
        lo = np.full(self.n, np.inf)
        hi = np.full(self.n, -np.inf)
        np.minimum.at(lo, self.vp, f[self.vpt])
        np.maximum.at(hi, self.vp, f[self.vpt])
        return lo, hi

    def core(self, mask, value: float = 1.0, margin: float = 0.35, atol: float = 1e-6) -> np.ndarray:
        """Prims all of whose corners hold `value` of the per-point array `mask`, their centre at least
        `margin` cm from any prim that does not."""
        lo, hi = self.prim_minmax(np.asarray(mask, float))
        inside = np.isclose(lo, value, atol=atol) & np.isclose(hi, value, atol=atol)
        return self.G.inner_prims(inside, margin)

    def roots_index(self, prims, roots):
        """(which roots have one of `prims` as the skin prim nearest them on the surface, all locks: their
        numbers in `roots`; each one's distance to the skin in cm). Every such root counts, however far off the
        skin."""
        r, _lid = roots
        if not len(prims) or not len(r):
            return np.zeros(0, int), np.zeros(0)
        lo, hi = self.cen[prims].min(0) - 1.0, self.cen[prims].max(0) + 1.0
        sel = np.nonzero((r >= lo).all(1) & (r <= hi).all(1))[0]
        prim, dist = self.assign(r[sel], lid=_lid[sel])
        inside = np.zeros(self.n, bool)
        inside[prims] = True
        got = (prim >= 0) & inside[np.maximum(prim, 0)]
        return sel[got], dist[got]

    def roots_in(self, prims, roots):
        """({lock id: roots}, positions, lock ids) of the roots whose nearest skin prim on the surface is one
        of `prims` (`assign`), all locks."""
        r, lid = roots
        keep, _dist = self.roots_index(prims, roots)
        ids, cnt = np.unique(lid[keep], return_counts=True)
        return {int(a): int(b) for a, b in zip(ids, cnt)}, r[keep], lid[keep]

    def lock_area_in(self, prims, lock_id: int) -> float:
        """The lock's own skin among `prims`, cm2 (a shared prim counts 1 / its owners)."""
        return float(sum(self.area[p] / len(self.own[p]) for p in prims if lock_id in self.own[p]))

    def paint_disc(self, layer_id: int, centre_cm, radius_cm: float, value: float = 1.0, soft: float = 0.0,
                   dab_r: float = 0.3, label: str = "Paint mask", erase: bool = False) -> dict:
        """A disc painted on a paint layer through the real brush (PaintSession): hard dabs of `dab_r` cm on the
        scalp points inside it (sub-sampled), the brush `value` (1 white, 0 black), or `erase`. One undo step."""
        from apps.houdini import grooming_masks as gm
        d = np.sqrt(((self.P - np.asarray(centre_cm)) ** 2).sum(1))
        pts = np.nonzero(d <= radius_cm)[0]
        step = max(1, len(pts) // 1500)
        s = gm.PaintSession(self.G.node, layer_id)
        landed = 0
        for i in pts[::step]:
            landed += int(s.dab(self.P[i] / self.G.unit, None, dab_r, value, soft, erase=erase) > 0)
        s.commit(label)
        return {"points_in_disc": int(len(pts)), "dabs": int(len(pts[::step])), "landed": landed}

    def owners_of_changed(self, c0, c1) -> list[int]:
        """Locks that grow and own skin where the cover (keep, add) changed between two reads of it."""
        changed = np.zeros(len(c0[0]), bool)
        for a, b in zip(c0, c1):
            changed |= np.abs(np.asarray(a, float) - np.asarray(b, float)) > 0
        touched = np.unique(self.vp[changed[self.vpt]])
        grows = {lk.id for lk in self.G.ga.read_data(self.G.node).locks if not lk.excluded}
        return sorted({o for p in touched for o in self.own[p]} & grows)

    def zones(self, roots) -> dict:
        """Eight kinds of skin (centres in cm), as the round 2 checker picked them: the crown whorl (densest
        1 cm disc), the top of the head, a lock's start (hair_base_12's root), the most stacked skin, skin
        under floating mesh with one owner, the widest fringe lock, ordinary skin (hair_back_06), and the
        sliver band by the ear."""
        G = self.G
        data = G.ga.read_data(G.node)
        owned = self.nown > 0
        big = owned & (self.area > 0.002)
        z = {}
        c, _n, _per = densest_spot(roots[0], 1.0)
        z["crown_whorl"] = self.snap(c)
        i = np.nonzero(big)[0][self.cen[big][:, 1].argmax()]
        z["top_of_head"] = self.cen[i]
        lk = next(x for x in data.locks if x.name == "hair_base_12")
        z["lock_start_hair_base_12"] = self.snap(np.array(lk.root) * G.unit)
        cand = np.nonzero(big)[0]
        best, bv = None, -1
        for i in cand[::max(1, len(cand) // 600)]:
            near = cand[((self.cen[cand] - self.cen[i]) ** 2).sum(1) <= 1.0]
            v = self.nown[near].mean()
            if v > bv:
                best, bv = i, v
        z["most_stacked"] = self.cen[best]
        geo = G.node.node("SCALP_REGIONS").geometry()
        dist = geo.primFloatListAttribValues("owner_dist")
        far = float(G.node.evalParm("root_far_cm")) * 1.5 * 1.2 / G.unit
        fl = np.nonzero(np.array([len(o) == 1 and len(d) == 1 and d[0] > far for o, d in zip(self.own, dist)]) & big)[0]
        best, bn = fl[0], -1
        for i in fl[::max(1, len(fl) // 300)]:
            k = int((((self.cen[fl] - self.cen[i]) ** 2).sum(1) <= 1.44).sum())
            if k > bn:
                best, bn = i, k
        z["under_floating_mesh"] = self.cen[best]
        bangs = [k for k, v in self.names.items() if "bang" in v]
        k = max(bangs, key=lambda b: len(G.region_prims(b)))
        z["fringe_" + self.names[k]] = self.snap(self.cen[G.region_prims(k)].mean(0))
        L = G.lock_id("hair_back_06")
        z["ordinary_hair_back_06"] = self.snap(self.cen[G.region_prims(L)].mean(0))
        tiny = np.nonzero(owned & (self.area < 0.001))[0]
        if len(tiny):
            z["ear_slivers"] = self.cen[tiny[len(tiny) // 2]]
        return z

    def region_path(self, name: str, n: int = 10, span: int = 40, shift: float = 0.0) -> list:
        """A stroke path (scene units) across a lock's region."""
        pr = self.G.region_prims(self.G.lock_id(name))
        cen = self.cen[pr]
        a = cen[len(cen) // 2]
        b = cen[min(len(cen) - 1, len(cen) // 2 + span)]
        off = np.array([shift, shift * 0.5, 0.0])
        return [(a + (b - a) * t + off) / self.G.unit for t in np.linspace(0, 1, n)]

    def disc_path(self, c, shift: float = 0.0, n: int = 8) -> list:
        return [(np.asarray(c) + np.array([dx + shift, shift * 0.5, 0.0])) / self.G.unit
                for dx in np.linspace(-0.6, 0.6, n)]


def gm_session(node, layer_id: int):
    """A PaintSession on a layer: dabs as the brush makes them, `commit()` stores the stroke (one undo step)."""
    from apps.houdini import grooming_masks as gm
    return gm.PaintSession(node, layer_id)


def density_limit(D: float, area_cm2: float) -> float:
    """The limit on |measured / D - 1| for a painted density: max(0.15, 2 / sqrt(N)), N = D x area (the
    round 2 checker's: 15 %, or two standard deviations of a count of N)."""
    n = max(D * area_cm2, 1e-9)
    return float(max(0.15, 2.0 / np.sqrt(n)))


LAYER_ROOT_ID = 10000000     # a layer's own root is numbered from here (build_hda VEX_MASK_TAG)
EVEN_BASE_CM = 0.1           # the automatic roots are counted within this of a root (its local density)
EVEN_LAYER_CM = 0.3          # ... the layers' own roots within this
EVEN_CLOSE = 0.3             # a root nearer its nearest neighbour than this share of the local spacing is clumped


def closest_on_tri(p, a, b, c):
    """The point of triangle (a, b, c) nearest p (Ericson, Real-Time Collision Detection 5.1.5), on arrays."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    bp = p - b
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    cp = p - c
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = va + vb + vc
    denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
    out = a + ab * (vb / denom)[..., None] + ac * (vc / denom)[..., None]       # inside the face
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.nan_to_num((d4 - d3) / ((d4 - d3) + (d5 - d6)))
        out = np.where(((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0))[..., None], b + (c - b) * t[..., None], out)
        t = np.nan_to_num(d2 / (d2 - d6))
        out = np.where(((vb <= 0) & (d2 >= 0) & (d6 <= 0))[..., None], a + ac * t[..., None], out)
        t = np.nan_to_num(d1 / (d1 - d3))
        out = np.where(((vc <= 0) & (d1 >= 0) & (d3 <= 0))[..., None], a + ab * t[..., None], out)
    out = np.where(((d6 >= 0) & (d5 <= d6))[..., None], c, out)
    out = np.where(((d3 >= 0) & (d4 <= d3))[..., None], b, out)
    out = np.where(((d1 <= 0) & (d2 <= 0))[..., None], a, out)
    return out


def _count_within(ref: np.ndarray, x: np.ndarray, radius: float) -> np.ndarray:
    """Per point of `x`: how many points of `ref` lie within `radius`."""
    out = np.zeros(len(x))
    if not len(ref):
        return out
    for i in range(0, len(x), 1000):
        out[i:i + 1000] = (((x[i:i + 1000, None, :] - ref[None, :, :]) ** 2).sum(-1) < radius * radius).sum(1)
    return out


def clumped_local(roots_cm: np.ndarray, density: np.ndarray):
    """The share of roots nearer their nearest neighbour than EVEN_CLOSE x the spacing asked where they stand
    (1 / sqrt(`density`), roots / cm2 per root); None for under 5 roots."""
    if len(roots_cm) < 5:
        return None
    return float(np.mean(nn_dist(roots_cm) < EVEN_CLOSE / np.sqrt(np.maximum(density, 1e-9))))


def lock_even_local(before_cm, before_lock, now_cm, now_lock, now_id, names: dict, least: int = 30) -> dict:
    """EVENNESS, the measure (the t64 checker's `even_local.py`; the plan's "Evenness"): per lock with at
    least `least` roots in the patch now, the clumped share of its roots against the spacing asked LOCALLY, and
    the same for its roots before any layer.
    The density asked at a root = the lock's roots before the layers within EVEN_BASE_CM of it, per cm2, x the
    share of them kept (its automatic roots now / before) + its layers' own roots within EVEN_LAYER_CM, per cm2.
    A root is clumped when its nearest neighbour (of the same lock) is nearer than EVEN_CLOSE x 1 / sqrt(that).
    Why local: a lock's automatic roots are several times denser at its start and at a whorl than on the rest
    of its skin, so one spacing for the lock on the patch called the same start grid clumped or not as the
    lock's mean density moved; a patch area (the lock's prims whole, or shared by their owners) read rises of
    0.06-0.38 where the roots stand evenly, or was blind on stacked skin (t64)."""
    out = {}
    disc = np.pi * EVEN_BASE_CM ** 2
    disc_l = np.pi * EVEN_LAYER_CM ** 2
    for k in np.unique(now_lock):
        sel = now_lock == k
        if sel.sum() < least:
            continue
        x, ids = now_cm[sel], now_id[sel]
        base = before_cm[before_lock == k]
        auto, lay = x[ids < LAYER_ROOT_ID], x[ids >= LAYER_ROOT_ID]
        keep = len(auto) / len(base) if len(base) else 0.0
        dens = _count_within(base, x, EVEN_BASE_CM) / disc * keep + _count_within(lay, x, EVEN_LAYER_CM) / disc_l
        was = clumped_local(base, _count_within(base, base, EVEN_BASE_CM) / disc)
        now = clumped_local(x, dens)
        out[names.get(int(k), str(k))] = {"roots": int(sel.sum()), "roots_before": int(len(base)), "keep": round(keep, 3),
                                         "layer_roots": int(len(lay)), "clumped": round(now, 3),
                                         "clumped_before": round(was, 3) if was is not None else None,
                                         "rise": round(now - (was or 0.0), 3)}
    return out


def lock_even(roots_cm, lock_ids, skin: "Skin", prims, least: int = 30) -> dict:
    """Per lock with at least `least` roots among `roots_cm`: spacing ratio and clumped share on the lock's
    own skin among `prims` (a lock holding a strip of a patch is judged on that strip, not on the patch)."""
    out = {}
    for k in np.unique(lock_ids):
        sel = lock_ids == k
        if sel.sum() >= least:
            st = spacing_stats(roots_cm[sel], skin.lock_area_in(prims, int(k)))
            st["on_patch"] = spacing_stats(roots_cm[sel], float(skin.area[prims].sum())).get("clumped")
            out[skin.names.get(int(k), str(k))] = {a: (round(b, 3) if isinstance(b, float) else b) for a, b in st.items()}
    return out
