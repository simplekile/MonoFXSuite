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

    def add(self, item: str, passed: bool, value=None, limit=None, evidence: str = "", note: str = "") -> bool:
        entry = {"item": item, "pass": bool(passed), "value": value, "limit": limit,
                 "evidence": evidence or os.path.basename(self.path)}
        if note:
            entry["note"] = note
        self.items = [i for i in self.items if i["item"] != item] + [entry]
        self.log("PASS" if passed else "FAIL", item, json.dumps(value, default=str)[:300], "limit", limit, note)
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
        data["passed"] = bool(self.items) and all(i["pass"] for i in self.items)
        data["failed"] = [i["item"] for i in self.items if not i["pass"]]
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
        self._roots.parm("snippet").set('v@r = point(0, "P", primpoint(0, @primnum, 0));')
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
            self._scalp = {"P": P, "P_cm": P * self.unit, "cen_cm": cen * self.unit, "vprim": vprim, "vpoint": vpoint,
                           "owners": geo.primIntListAttribValues("lock_owners"),
                           "area": np.frombuffer(geo.primFloatAttribValuesAsString("area_cm2"), np.float32).astype(float),
                           "prim_points": [vpoint[order][s:s + c] for s, c in
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

    def paint_prims(self, layer_id: int, prims: np.ndarray, value: float = 1.0, radius_cm: float = 0.5,
                    soft: float = 0.0, label: str = "Paint mask", level: float = 1.0) -> int:
        """Paint the skin of `prims` through the real brush (one dab a prim centre): one undo step. A paint
        layer takes `value`; a fill layer or a folder has its mask painted `level` (1 white, 0 black).
        Returns the dabs that reached skin."""
        from apps.houdini import grooming_masks as gm
        cen = self.scalp()["cen_cm"][prims] / self.unit
        session = gm.PaintSession(self.node, layer_id)
        step = max(1, int(len(prims) // 4000) + 1)
        landed = 0
        for c in cen[::step]:
            landed += int(session.dab(c, None, radius_cm, value, soft, level=level) > 0)
        session.commit(label)
        return landed


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
    """(value, mask) of a layer as stored on the node, copies. The mask (a paint layer's coverage) is None
    when the layer was never painted; the value is None unless it is a paint layer."""
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
