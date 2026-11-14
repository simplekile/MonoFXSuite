"""Acceptance of MONO Grooming v0.2a density layers, the core (docs/plans/grooming_v0_2.md, "Done when").

    hython accept_v02a.py <suite> <scene> <out_dir> [--v01 <v0.1 suite>] [--ref <approved groom.usd>]
                          [--t55 <qc_report.json of the v0.1 end-to-end test>] [--only id,id] [--strokes 30]

<scene> is a copy of the Helen grooming scene (it stays in the sandbox). Everything is written under <out_dir>:
accept.json ({item, pass, value, limit, evidence} per check, `passed`), accept_log.txt, and the files of the
checks that run in a process of their own (QC, full-cook timing, reopen). Hython's exit code is not reliable:
read the JSON. Run it with no other Houdini cooking: the speed limits are absolute.

The model (the user, 2026-11-15): density layers over the automatic groom, each with its own number D (strands /
cm2), opacity, owner (all locks, a group, a lock) and its own 0..1 mask (paint and fill layers, six blend modes):
density = below + (D - below) x mask x opacity. Every density check is graded on eight kinds of skin (whorl, top
of the head, a lock's start, the most stacked skin, skin under floating mesh, fringe, ordinary, the sliver band
by the ear), with the roots of ALL locks counted in the core of a painted disc and each lock held to the rule on
its own skin there; limits are the plan's, never tuned to a result.

Definitions this script makes on its own (each named DEFINITION where it is used, for the checker to judge):
  1. a lock asked under one root in a core (0 < N < 1) may hold at most 2 there (`_grade`);
  2. where a lock is asked no root, a strand rooted over 0.1 cm off the skin is listed, not counted (`_grade`);
  3. "= D" owned by all locks: every lock on that skin gives D together; by a group: the group's locks there
     together; by one lock: that lock alone on the skin it owns (`_sharing`, measured by o2)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback

SUITE, SCENE, OUT = (a.replace("\\", "/") for a in sys.argv[1:4])


def _arg(name, default=""):
    return sys.argv[sys.argv.index(name) + 1].replace("\\", "/") if name in sys.argv else default


V01, REF, T55 = _arg("--v01"), _arg("--ref"), _arg("--t55")
ONLY = [x for x in _arg("--only").split(",") if x]
STROKES = int(_arg("--strokes", "30"))
HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, SUITE)
sys.path.insert(0, HERE)
os.makedirs(OUT, exist_ok=True)

import hou  # noqa: E402
import numpy as np  # noqa: E402

import accept_lib as lib  # noqa: E402
from tools.fx.grooming import config, model  # noqa: E402

HYTHON = os.path.join(hou.expandString("$HFS"), "bin", "hython.exe" if os.name == "nt" else "hython").replace("\\", "/")
QC = SUITE + "/.claude/skills/grooming-check/scripts/qc_metrics.py"
DENSITIES = (0.0, 40.0, 120.0, 300.0)   # strands / cm2; every Helen lock's own Density is 150
EVEN_RISE = 0.05        # a lock's roots in a painted patch: clumped share on its own skin, over its no-layer value
OFF_SKIN_CM = 0.1       # a root farther than this from every scalp prim centre is not on the skin (prims: ~0.02 cm)
EVEN_SPACING = 0.45     # where every root is the layers': spacing ratio, grooming-check's root_spacing_low limit
UNDO_S = 0.1

C = lib.Checks(OUT, meta={"suite": SUITE, "scene": SCENE, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "argv": sys.argv[1:]})


def wanted(item: str) -> bool:
    return not ONLY or any(item.startswith(o) for o in ONLY)


def r3(x):
    return None if x is None else round(float(x), 3)


def hython(args, log_name, timeout=3600) -> str:
    """Run a script in a hython of its own; its output goes to <out>/<log_name>. Returns the output."""
    path = OUT + "/" + log_name
    with open(path, "w", encoding="utf-8", errors="replace") as fh:
        subprocess.run([HYTHON] + list(args), stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


ga, node = lib.open_scene(SUITE, SCENE)
C.meta["library"] = node.type().definition().libraryFilePath()
lib.fresh(ga, node)
G = lib.Groom(ga, node)
t0 = time.perf_counter()
node.cook()
C.meta["display_cold_s"] = r3(time.perf_counter() - t0)
G.rest.cook()
C.meta["anim_wired"] = bool(node.evalParm("anim_wired"))
C.meta["lookup_per_piece"] = int(node.evalParm("lookup_per_piece"))
CC = lib.CookCount(ga)
K = lib.Skin(G)
ROOTS0 = G.roots()
BASE = G.strands_by_lock()
C.meta["strands"] = sum(BASE.values())
Z = K.zones(ROOTS0)
DATA0 = ga.read_data(node)
DENS = {lk.id: float(DATA0.resolve(lk.id)["density"]) for lk in DATA0.locks}      # each lock's own Density setting
C.meta["zones"] = {k: [round(float(x), 2) for x in v] for k, v in Z.items()}
C.write()


def rest_points():
    """(P bytes of every rest point, lock id per strand) of output 1 at rest."""
    geo = G._roots.inputs()[0].geometry()
    return geo.pointFloatAttribValuesAsString("P"), np.frombuffer(geo.primIntAttribValuesAsString("lock_id"), np.int32).copy()


def cook_all():
    """Cook the display then the rest groom: (display seconds, locks the display grew, locks output 1 grew)."""
    CC.take()
    t = time.perf_counter()
    node.cook()
    s = time.perf_counter() - t
    d = CC.take()
    G.rest.cook()
    return s, d, CC.take()


def clear_layers():
    for m in ga.read_data(node).density_layers():
        ga.mask_remove(node, m.id)
    cook_all()


def speed_layer(name):
    """A density layer of 120 with an empty paint layer: (density layer id, paint layer id)."""
    d = ga.mask_add(node, name, density=120.0)
    return d, ga.mask_add(node, "paint", parent=d)




# ---------------------------------------------------------------------------
# speed first, in a young process (the limits are absolute)
# ---------------------------------------------------------------------------

def s1_stroke_speed():
    c, _n, _p = lib.densest_spot(ROOTS0[0], 1.0)
    top, lid = speed_layer("speed")
    cook_all()
    places = [("hair_base_12", None), ("crown_whorl", c), ("hair_back_06", None), ("hair_bang_08", None),
              ("hair_base_05", None), ("hair_back_14", None), ("hair_bang_17", None), ("hair_base_01", None)]
    rows = []
    for name, centre in places:
        for k in range(3):
            path = K.disc_path(K.snap(centre), 0.06 * k) if centre is not None else K.region_path(name, shift=0.06 * k)
            c0 = ga.mask_cover(node)
            ga.mask_stroke(node, lid, path, radius_cm=0.8, value=1.0)
            c1 = ga.mask_cover(node)
            s, locks, _r = cook_all()
            under = K.owners_of_changed(c0, c1)
            rows.append({"place": name, "repeat": k, "locks": len(locks), "display_s": r3(s),
                         "limit_s": round(0.2 * len(locks) + 0.1, 2), "only_under": locks == under,
                         "label": hou.undos.undoLabels()[0]})
    ga.mask_remove(node, top)
    cook_all()
    worst = max(rows, key=lambda r: r["display_s"] - r["limit_s"])
    C.add("s1_stroke_speed_8_places_x3", all(r["display_s"] <= r["limit_s"] and r["locks"] > 0 for r in rows),
          {"strokes": rows, "worst": worst, "failed": [r for r in rows if r["display_s"] > r["limit_s"]]},
          "every stroke: display cook <= 0.2 s x locks recooked + 0.1 s")
    C.add("s1_stroke_recooks_only_the_locks_under_it", all(r["only_under"] for r in rows),
          {"strokes_with_other_locks": [r for r in rows if not r["only_under"]], "strokes": len(rows)},
          "locks recooked (LockCache.put) == the locks owning skin whose cover changed")
    C.add("s1_one_undo_step_a_stroke", all(r["label"].endswith("Paint mask") for r in rows),
          sorted({r["label"] for r in rows}), "the top undo label after each stroke is the stroke's")


# ---------------------------------------------------------------------------
# undo: chains of strokes, the cache's memory
# ---------------------------------------------------------------------------

def _chain(place, n, radius=0.8, out1=None):
    """n strokes at one place, n undos, n redos. Each undo / redo: seconds for the undo and the display
    cook; locks grown for the display and for the rest groom (and captures made for the deformed output)."""
    top, lid = speed_layer(place)
    cook_all()
    use0 = ga.undo_cache_usage(node)
    states, strokes, peak = [], [], use0["bytes"]

    def read():
        if out1 is not None:
            out1.cook()
        CC.take()
        return CC.captures()

    read()
    for i in range(n):
        before = ga.undo_cache_usage(node)["bytes"]
        ga.mask_stroke(node, lid, K.disc_path(Z[place], 0.05 * i), radius_cm=radius, value=1.0 if i % 3 else 0.6)
        s, d, r = cook_all()
        caps = read()
        use = ga.undo_cache_usage(node)
        peak = max(peak, use["bytes"])
        strokes.append({"display_s": r3(s), "locks": len(d), "mb": round((use["bytes"] - before) / 1e6, 2),
                        "captures": len(caps)})
        states.append(G.strands_by_lock())

    def step(fn, want):
        CC.take()
        t = time.perf_counter()
        fn()
        node.cook()
        s = time.perf_counter() - t
        d = CC.take()
        G.rest.cook()
        r = CC.take()
        caps = read()
        return {"s": r3(s), "display": len(d), "rest": len(r), "captures": len(caps),
                "same": want is None or G.strands_by_lock() == want}

    undos = [step(hou.undos.performUndo, states[n - 2 - i] if n - 2 - i >= 0 else None) for i in range(n)]
    peak = max(peak, ga.undo_cache_usage(node)["bytes"])
    redos = [step(hou.undos.performRedo, states[i]) for i in range(n)]
    use = ga.undo_cache_usage(node)
    peak = max(peak, use["bytes"])
    ga.mask_remove(node, top)
    cook_all()
    held = [s["mb"] for s in strokes[:6] if s["mb"] > 0]        # the first strokes: before the cache may be full
    return {"strokes": n, "locks_a_stroke": [s["locks"] for s in strokes],
            "mb_a_stroke_median": r3(np.median(held)) if held else 0.0,
            "undo_s": [u["s"] for u in undos], "redo_s": [u["s"] for u in redos],
            "undo_worst_s": max(u["s"] for u in undos), "redo_worst_s": max(u["s"] for u in redos),
            "undo_locks_grown": [u["display"] + u["rest"] for u in undos],
            "redo_locks_grown": [u["display"] + u["rest"] for u in redos],
            "captures_made_again": [u["captures"] for u in undos],
            "every_state_right": all(u["same"] for u in undos + redos),
            "peak_mb": round(peak / 1e6, 1), "limit_mb": round(use["limit_bytes"] / 1e6, 1),
            "live_mb": round(use0["live_bytes"] / 1e6, 1), "dropped": use["dropped"],
            "capture_mb": round(use["capture_bytes"] / 1e6, 1)}


def _chain_ok(r, no_grow=True):
    return (r["undo_worst_s"] < UNDO_S and r["redo_worst_s"] < UNDO_S and r["every_state_right"]
            and r["peak_mb"] <= r["limit_mb"]
            and (not no_grow or (sum(r["undo_locks_grown"]) == 0 and sum(r["redo_locks_grown"]) == 0)))


def u1_undo_chain():
    node.parm(config.UNDO_CACHE_PARM).set(config.UNDO_CACHE_GB)
    r = _chain("ordinary_hair_back_06", STROKES)
    r["strokes_2gb_holds"] = int((r["limit_mb"] - r["live_mb"]) / max(r["mb_a_stroke_median"], 1e-6))
    C.add("u1_%d_strokes_%d_undos_%d_redos" % (STROKES, STROKES, STROKES), _chain_ok(r), r,
          "each undo and redo + display cook < 0.1 s, 0 locks grown for the display and for output 1 (anim "
          "wired), every state the stroke's, cache memory <= the node's limit (2 GB)")


def u2_undo_chain_whorl():
    # a whorl stroke regrows 24-35 locks (~55 MB a state): 2 GB holds about 28 of them, so 20 here
    n = min(STROKES, 20)
    r = _chain("crown_whorl", n)
    r["strokes_2gb_holds"] = int((r["limit_mb"] - r["live_mb"]) / max(r["mb_a_stroke_median"], 1e-6))
    C.add("u2_whorl_%d_strokes_undo_redo" % n, _chain_ok(r), r,
          "as u1, on the crown whorl (24-35 locks a stroke)")


def u3_low_limit():
    node.parm(config.UNDO_CACHE_PARM).set(0.3)          # under what the node shows: no undo state fits
    try:
        r = _chain("ordinary_hair_back_06", 6)
    finally:
        node.parm(config.UNDO_CACHE_PARM).set(config.UNDO_CACHE_GB)
    cook_all()
    C.add("u3_limit_very_low_undo_still_right", r["every_state_right"] and sum(r["undo_locks_grown"]) > 0, r,
          "limit 0.3 GB: every undo and redo gives the stroke's own state (strands per lock), the locks are "
          "grown again (slower, never wrong)")
    C.add("u3_changing_the_limit_regrows_nothing", cook_all()[1] == [], cook_all()[1], "0 locks")


def u4_deformed_output():
    out1 = node.parent().createNode("null", "accept_out1")
    out1.setInput(0, node, 1)
    try:
        t = time.perf_counter()
        out1.cook()
        first = time.perf_counter() - t
        r = _chain("ordinary_hair_back_06", 8, out1=out1)
        r["first_deformed_read_s"] = r3(first)
    finally:
        out1.destroy()
    ok = (r["every_state_right"] and sum(r["undo_locks_grown"]) == 0 and sum(r["redo_locks_grown"]) == 0
          and r["peak_mb"] <= r["limit_mb"])
    C.add("u4_undo_with_the_deformed_output_read", ok, r,
          "anim wired, the deformed output 1 read after every stroke, undo and redo: 0 locks grown; the "
          "captures made again are reported (800 B a point: one a lock, outside the limit's count)",
          note="undo + display seconds are graded in u1; here a capture of the stroke's locks follows each")


def u5_usage():
    use = ga.undo_cache_usage(node)
    keys = {"bytes", "live_bytes", "undo_bytes", "undo_states", "limit_bytes", "dropped", "gb", "limit_gb", "capture_bytes"}
    parm = node.parm(config.UNDO_CACHE_PARM)
    C.add("u5_undo_cache_parm_and_usage", keys <= set(use) and parm is not None and parm.eval() == 2.0
          and use["limit_bytes"] == 2 * 2 ** 30 and 0 < use["bytes"] <= use["limit_bytes"],
          {"usage": {k: (round(v / 1e6, 1) if "bytes" in k else v) for k, v in use.items()},
           "parm": parm.name() if parm else None, "label": parm.description() if parm else None,
           "default": parm.parmTemplate().defaultValue() if parm else None},
          "parm undo_cache_gb (\"Undo cache, GB\", default 2) on the node; undo_cache_usage(node) reads bytes in use")


# ---------------------------------------------------------------------------
# density layers: a layer of D painted white gives D; mask m gives below + (D - below) x m
# ---------------------------------------------------------------------------

GROUP_OF = {lk.id: lk.group for lk in DATA0.locks}
ALL = ("all",)


def _layer(D, zone=None, value=1.0, radius=1.3, name="", **kw):
    """A density layer of D (strands / cm2) with one paint layer in its mask, a disc painted `value` at `zone`
    (a zone's name or a centre in cm; None: nothing painted). Returns (density layer id, paint layer id)."""
    d = ga.mask_add(node, name or "= %g" % D, density=D, **kw)
    p = ga.mask_add(node, "paint", parent=d)
    if zone is not None:
        K.paint_disc(p, Z[zone] if isinstance(zone, str) else zone, radius, value=value)
    return d, p


def _core(lid, atol=1e-6):
    """Prims of the fine scalp a paint layer covers in full (coverage 1 at every corner), away from the edge."""
    return K.core(ga.mask_values(node, lid)[1], 1.0, atol=atol)


def _applies(scope, k):
    if scope[0] == "group":
        return GROUP_OF.get(k) == scope[1]
    if scope[0] == "locks":
        return k in scope[1]
    return True


def _sharing(scope, prim):
    """How many owners of a skin prim a layer's D is shared by, by the rule as the plan states it (written here
    apart from the tool's code): owned by all locks, every lock on that skin gives D together; by a group, the
    group's locks there together; by a lock, that lock alone."""
    return max(1, sum(1 for o in K.own[prim] if _applies(scope, o)))


def _want(core, stack):
    """Expected roots per lock on `core` under density layers, by the rule density = below + (D - below) x e.
    `stack`: [(D, e, scope)] in the order the layers apply (all locks, then group, then lock; inside one owner
    bottom first), e = mask x opacity, the same over the whole core; scope ("all",), ("group", id) or
    ("locks", (ids,)). A lock's roots = its automatic roots there x the product of (1 - e) of the layers that
    reach it + the sum over its prims of area x the layers' density (each D over `_sharing`).
    Returns ({lock: expected}, {lock: automatic roots}, {lock: share of its automatic roots kept})."""
    b = K.roots_in(core, ROOTS0)[0]
    by_lock = {}
    for p in core:
        for o in K.own[p]:
            by_lock.setdefault(o, []).append(p)
    out, kept = {}, {}
    for k in sorted(set(by_lock) | set(b)):
        mine = [(D, e, sc) for D, e, sc in stack if _applies(sc, k)]
        keep = 1.0
        for _D, e, _sc in mine:
            keep *= 1.0 - e
        add = 0.0
        for p in by_lock.get(k, ()):
            dens = 0.0
            for D, e, sc in mine:
                dens = dens * (1.0 - e) + D / _sharing(sc, p) * e
            add += dens * K.area[p]
        out[k] = b.get(k, 0) * keep + add
        kept[k] = keep
    return out, b, kept


def _grade(core, stack, evenness=True):
    """Roots on `core` against the rule (`_want`), for all locks together and for each lock on its own skin
    there; limit |measured / expected - 1| <= max(0.15, 2 / sqrt(N)).
    DEFINITION 1 (round 3's, kept): that limit has no meaning for a lock asked under one root there (0 < N < 1:
    a lock whose skin only touches the core); such a lock may hold at most 2 roots, and is listed.
    DEFINITION 2 (round 3's, kept): where a lock is asked no root at all (a layer of 0 painted white), a strand
    whose root floats over OFF_SKIN_CM off the skin is listed, not counted: v0.1 leaves a few start roots there
    (hair_base_20: 1 of 7,172, 0.24 cm up), and the tool judges a root where it lands on its lock's skin."""
    area = float(K.area[core].sum())
    want, b, kept = _want(core, stack)
    _b, rb, lb = K.roots_in(core, ROOTS0)
    a, ra, la = K.roots_in(core, G.roots())
    floating = {}
    if len(ra) and any(w <= 1e-9 for w in want.values()):
        up = np.sqrt(((ra[:, None, :] - K.cen[None, :, :]) ** 2).sum(-1).min(1))
        for k in np.unique(la[up > OFF_SKIN_CM]):
            if want.get(int(k), 0.0) > 1e-9:
                continue
            n = int(((la == k) & (up > OFF_SKIN_CM)).sum())
            floating[K.names[int(k)]] = {"roots": n, "off_the_skin_cm": round(float(up[la == k].max()), 3)}
            a[int(k)] -= n
    locks, bad = {}, []
    for k in sorted(set(want) | set(a)):
        w = want.get(k, 0.0)
        got = a.get(k, 0)
        lim = lib.density_limit(w, 1.0) if w >= 1.0 else 0.0
        if w <= 1e-9:
            ok = got == 0                                   # no root asked: none at all
        elif w < 1.0:
            ok = got <= 2
        else:
            ok = abs(got / w - 1) <= lim
        locks[K.names[k]] = {"skin_cm2": r3(K.lock_area_in(core, k)), "automatic": b.get(k, 0), "expected": r3(w),
                             "roots": got, "ratio": r3(got / w) if w >= 1.0 else None, "limit": r3(lim), "pass": ok}
        if not ok:
            bad.append(K.names[k])
    target = sum(want.values())
    got = sum(a.values())
    lim = lib.density_limit(target, 1.0) if target > 0 else 0.0
    row = {"core_cm2": r3(area), "automatic_per_cm2": r3(sum(b.values()) / area), "expected_per_cm2": r3(target / area),
           "measured_per_cm2": r3(got / area), "ratio": r3(got / target) if target > 0 else None, "limit": r3(lim),
           "locks_on_core": len(locks), "locks_outside_their_limit": bad, "locks": locks,
           "roots_floating_off_the_skin_not_counted": floating,
           "locks_asked_under_one_root": {k: v["roots"] for k, v in locks.items() if 0 < v["expected"] < 1.0 and v["roots"]},
           "worst_lock": max(locks.items(), key=lambda kv: abs((kv[1]["ratio"] or 1) - 1) / max(kv[1]["limit"], 1e-9))
           if locks else None,
           "pass": (got == 0 if target <= 0 else abs(got / target - 1) <= lim) and not bad}
    if evenness and got:
        ev0 = lib.lock_even(rb, lb, K, core)
        ev1 = lib.lock_even(ra, la, K, core)
        rises = {k: round(v.get("clumped", 0.0) - ev0.get(k, {}).get("clumped", 0.0), 3) for k, v in ev1.items()}
        layers_only = all(v <= 0 for v in kept.values())
        low = [k for k, v in ev1.items() if layers_only and v.get("spacing_ratio", 1.0) < EVEN_SPACING]
        row["even"] = {"clumped_now_worst": max([v.get("clumped", 0.0) for v in ev1.values()] + [0.0]),
                       "clumped_rise_worst": max(list(rises.values()) + [0.0]),
                       "spacing_ratio_lowest": min([v.get("spacing_ratio", 1.0) for v in ev1.values()] + [9.0]),
                       "locks_judged": len(ev1), "rise_per_lock": {k: v for k, v in rises.items() if v > 0},
                       "all_locks_together_clumped": r3(lib.spacing_stats(ra, area).get("clumped")),
                       "pass": all(v <= EVEN_RISE for v in rises.values()) and not low}
    return row


def _same_roots(roots_ref):
    r1, l1 = G.roots()
    return bool(r1.shape == roots_ref[0].shape and np.array_equal(l1, roots_ref[1])
                and float(np.abs(r1 - roots_ref[0]).max()) == 0.0)


def _all(rows, key="pass"):
    return all(r[key] for r in rows.values())


def _even(rows):
    return all(r["even"]["pass"] for r in rows.values() if "even" in r)


LIMIT = "|measured / expected - 1| <= max(0.15, 2 / sqrt(N)) for all locks together AND for each lock on its own skin there"
EVEN_LIMIT = ("each lock with >= 30 roots in the core: clumped share <= its no-layer value there + %s; where every root "
              "is a layer's, spacing ratio >= %s" % (EVEN_RISE, EVEN_SPACING))


def d1_density():
    ref = rest_points()
    for zname in Z:
        rows = {}
        for D in DENSITIES:
            d, p = _layer(D, zname)
            s, locks, _r = cook_all()
            rows["= %g" % D] = dict(_grade(_core(p), [(D, 1.0, ALL)]), display_s=r3(s), locks_recooked=len(locks))
            ga.mask_remove(node, d)
            cook_all()
        C.add("d1_a_layer_of_D_painted_white_gives_D_" + zname, _all(rows), rows,
              "a density layer of D = 0 / 40 / 120 / 300 strands / cm2 owned by all locks (every lock's own Density is "
              "150), its mask painted white on a disc; roots in its core: none for 0, else " + LIMIT +
              " (all locks together give D; each lock D x its share of the skin)")
        C.add("d1_roots_even_" + zname, _even(rows), {k: v.get("even") for k, v in rows.items()}, EVEN_LIMIT)
    C.add("d1_all_removed_is_the_automatic_groom", rest_points()[0] == ref[0] and G.strands_by_lock() == BASE,
          {"strands": G.strands(), "automatic": sum(BASE.values())},
          "after all those layers were deleted: every rest point as when the check began, byte for byte, and the "
          "strands of every lock as the first cook's")


def d2_black_and_erase():
    """Black in a mask = the layer does not apply there: the density below shows. Over the automatic groom that
    is the automatic groom itself, root for root; over a lower layer of 120 it is 120."""
    rows = {}
    ref = rest_points()
    roots_ref = G.roots()
    for zname in ("crown_whorl", "most_stacked", "under_floating_mesh", "ordinary_hair_back_06", "top_of_head"):
        c = Z[zname]
        d, p = _layer(300.0, zname)
        cook_all()
        core = _core(p)
        white = _grade(core, [(300.0, 1.0, ALL)], evenness=False)
        K.paint_disc(p, c, 1.3, value=0.0)                                       # black over the white
        cook_all()
        mask_black = float(ga.mask_values(node, d)[0].max())
        black = {"mask_max": mask_black, "roots_at_the_same_places": _same_roots(roots_ref),
                 "every_point_equal_bytes": rest_points()[0] == ref[0]}
        K.paint_disc(p, c, 1.3, value=1.0)                                       # white again, then the eraser
        cook_all()
        K.paint_disc(p, c, 2.0, dab_r=0.5, erase=True, label="Erase mask")       # wider than the paint
        s, locks, _r = cook_all()
        erased = {"coverage_left": float(ga.mask_values(node, p)[1].max()), "roots_at_the_same_places": _same_roots(roots_ref),
                  "every_point_equal_bytes": rest_points()[0] == ref[0], "locks_recooked": len(locks)}
        ga.mask_remove(node, d)
        cook_all()
        # over a lower layer: "= 120" on a wider disc, "= 300" on top painted white then black
        _low_d, low_p = _layer(120.0, zname, radius=1.6)
        top_d, top_p = _layer(300.0, zname)
        cook_all()
        inner = np.intersect1d(_core(top_p), _core(low_p))
        on_top = _grade(inner, [(120.0, 1.0, ALL), (300.0, 1.0, ALL)], evenness=False)
        K.paint_disc(top_p, c, 1.3, value=0.0)
        cook_all()
        below = _grade(inner, [(120.0, 1.0, ALL), (300.0, 0.0, ALL)], evenness=False)
        clear_layers()
        rows[zname] = {"white_300": {k: white[k] for k in ("ratio", "limit", "pass", "locks_outside_their_limit")},
                       "black_over_the_white": black, "erased": erased,
                       "white_300_over_a_layer_of_120": {k: on_top[k] for k in ("measured_per_cm2", "ratio", "limit", "pass",
                                                                                 "locks_outside_their_limit")},
                       "black_over_it_shows_the_120_below": {k: below[k] for k in ("measured_per_cm2", "expected_per_cm2", "ratio",
                                                                                     "limit", "pass", "locks_outside_their_limit")}}
    ok = all(r["white_300"]["pass"] and r["black_over_the_white"]["mask_max"] == 0.0
             and r["black_over_the_white"]["roots_at_the_same_places"] and r["black_over_the_white"]["every_point_equal_bytes"]
             and r["erased"]["coverage_left"] == 0.0 and r["erased"]["roots_at_the_same_places"]
             and r["erased"]["every_point_equal_bytes"] and r["white_300_over_a_layer_of_120"]["pass"]
             and r["black_over_it_shows_the_120_below"]["pass"] for r in rows.values())
    C.add("d2_black_returns_the_density_below_and_erase_removes_the_paint", ok, rows,
          "5 kinds of skin, a layer of 300 painted white: black painted over it gives a mask of 0 there and the "
          "automatic groom, every root where it was (difference 0) and every rest point byte for byte (black is not "
          "\"no hair\"); the eraser (wider than the disc) leaves no coverage and the same; over a lower layer of 120, "
          "white gives 300 and black gives the 120 below, " + LIMIT)


LAYER_ID0 = 10000000      # the layers' own strands are numbered from here (build_hda VEX_MASK_TAG)
TINY = 0.028


def d2_tiny():
    """A layer that applies 0.028 of the way (round 2: a leftover mask of 0.028 re-placed every root of two locks,
    points up to 20 mm away). Strands are followed by their id: a strand's number in its lock's automatic scatter."""
    rows = {}
    before = G.strands_by_id()
    for zname in ("ordinary_hair_back_06", "most_stacked", "crown_whorl"):
        d, _p = _layer(150.0, zname, opacity=TINY)
        s, locks, _r = cook_all()
        after = G.strands_by_id()
        total = kept = gone = new = strangers = 0
        root_move, tip_move = [], []
        for k in locks:
            id0, r0, t0 = before[k]
            id1, r1, t1 = after.get(k, (np.zeros(0, np.int32), np.zeros((0, 3)), np.zeros((0, 3))))
            total += len(id0)
            own = id1 < LAYER_ID0
            new += int((~own).sum())
            at0 = {int(i): n for n, i in enumerate(id0)}
            idx1 = np.nonzero(own)[0]
            match = np.array([at0.get(int(i), -1) for i in id1[idx1]], dtype=int)
            strangers += int((match < 0).sum())             # an automatic strand that was not there before
            ok = match >= 0
            kept += int(ok.sum())
            gone += len(id0) - int(ok.sum())
            if ok.any():
                root_move.append(np.sqrt(((r1[idx1[ok]] - r0[match[ok]]) ** 2).sum(1)))
                tip_move.append(np.sqrt(((t1[idx1[ok]] - t0[match[ok]]) ** 2).sum(1)))
        rm = np.concatenate(root_move) if root_move else np.zeros(1)
        tm = np.concatenate(tip_move) if tip_move else np.zeros(1)
        rows[zname] = {"locks": len(locks), "automatic_strands_before": total, "kept": kept, "gone": gone,
                       "share_gone": r3(gone / max(total, 1)), "the_layers_new_strands": new,
                       "automatic_strands_not_there_before": strangers,
                       "a_kept_root_moved_cm": {"max": round(float(rm.max()), 4), "p99": round(float(np.percentile(rm, 99)), 4)},
                       "a_kept_tip_moved_cm": {"max": round(float(tm.max()), 3), "p99": round(float(np.percentile(tm, 99)), 3),
                                               "median": round(float(np.median(tm)), 4)}}
        ga.mask_remove(node, d)
        cook_all()
    ok = all(r["locks"] > 0 and r["share_gone"] <= TINY + 0.02 and r["automatic_strands_not_there_before"] == 0
             and r["a_kept_root_moved_cm"]["max"] <= 0.05 for r in rows.values())
    C.add("d2_a_tiny_mask_moves_no_root", ok, rows,
          "a layer of 150 painted white at opacity 0.028 (ordinary skin, stacked skin, the whorl), strands followed by "
          "id: no automatic strand appears, at most 0.028 + 0.02 of them are gone, and every kept root is within 0.05 "
          "cm of where it was (round 2: every root of the locks re-placed, up to 2 cm)",
          note="tips are reported: a kept strand's place across its lock is its rank among the lock's strands, "
               "so it shifts a little when a neighbour goes")


def d3_partial():
    """A grey mask, or an opacity under 1: density = below + (D - below) x mask x opacity."""
    rows = {}
    cases = [(z, 300.0, m, 1.0) for z in Z for m in (0.5, 0.25)]
    cases += [(z, D, 0.5, 1.0) for z in BLEND_ZONES for D in (40.0, 0.0)]
    cases += [(z, 120.0, 1.0, o) for z in BLEND_ZONES for o in (0.25, 0.5, 0.75)]
    for zname, D, m, opacity in cases:
        d, p = _layer(D, zname, value=m, opacity=opacity)
        cook_all()
        rows["%s = %g mask %s opacity %s" % (zname, D, m, opacity)] = _grade(_core(p), [(D, m * opacity, ALL)])
        ga.mask_remove(node, d)
        cook_all()
    worst = max(rows.items(), key=lambda kv: abs((kv[1]["ratio"] or 1) - 1))
    C.add("d3_grey_mask_and_opacity_follow_the_rule", _all(rows), {"worst": worst, "rows": rows},
          "a layer of 300 with its mask painted 0.5 and 0.25 on the eight kinds of skin (D above the locks' own "
          "Density), 40 and 0 at 0.5 and 120 at opacity 0.25 / 0.5 / 0.75 on three: roots = automatic x (1 - e) + D x "
          "skin x e, e = mask x opacity; " + LIMIT)
    C.add("d3_partial_coverage_roots_even", _even(rows), {k: v.get("even") for k, v in rows.items()}, EVEN_LIMIT)


def d4_soft_edge():
    rows = {}
    for zname, D in (("ordinary_hair_back_06", 300.0), ("ordinary_hair_back_06", 40.0), ("crown_whorl", 150.0),
                     ("top_of_head", 0.0)):
        c = Z[zname]
        d, p = _layer(D)
        s = lib.gm_session(node, p)
        s.dab(c / G.unit, None, 1.5, 1.0, 1.0)          # one white dab, soft over the whole radius
        s.commit()
        cook_all()
        mask = ga.mask_values(node, d)[0].astype(float)
        lo, hi = K.prim_minmax(mask)
        dist = np.sqrt(((K.cen - c) ** 2).sum(1))
        r1 = G.roots()
        rings = []
        for a, b in ((0.0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 1.2), (1.2, 1.5)):
            prims = np.nonzero((dist >= a) & (dist < b) & (K.nown > 0))[0]
            area = float(K.area[prims].sum())
            if area <= 0:
                continue
            cov = float(((lo[prims] + hi[prims]) * 0.5 * K.area[prims]).sum() / area)
            auto = sum(K.roots_in(prims, ROOTS0)[0].values()) / area
            got = sum(K.roots_in(prims, r1)[0].values()) / area
            target = auto * (1.0 - cov) + D * cov
            lim = lib.density_limit(target * area, 1.0)
            rings.append({"ring_cm": [a, b], "mask": r3(cov), "automatic": r3(auto), "D": D, "target": r3(target),
                          "measured": r3(got), "limit": r3(lim), "pass": abs(got / max(target, 1e-9) - 1) <= lim})
        rows["%s = %g" % (zname, D)] = rings
        ga.mask_remove(node, d)
        cook_all()
    C.add("d4_soft_edge_follows_the_mask", all(r["pass"] for rs in rows.values() for r in rs), rows,
          "one soft white dab (radius 1.5 cm) on a layer of 300, 40, 150 or 0: in each 0.3 cm ring the density is "
          "automatic x (1 - mask) + D x mask within max(0.15, 2 / sqrt(N))",
          note="round 3 also asked that a ring lie between its two sides, each widened by the ring's own limit: "
               "dropped, a ring inside its limit of the target always does (the target lies between them)")


# ---------------------------------------------------------------------------
# owners: all locks, then group, then lock; what "= D" means for each
# ---------------------------------------------------------------------------

def _largest_owner(core):
    full = {}
    for p in core:
        for o in K.own[p]:
            full[o] = full.get(o, 0.0) + K.area[p]
    return max(full, key=full.get), full


def o1_owner_order():
    rows = {}
    for zname in ("under_floating_mesh", "most_stacked", "crown_whorl"):
        c = Z[zname]
        a_d, a_p = _layer(40.0, c, radius=1.1, name="all 40")
        s_a, locks_a, _r = cook_all()
        core = _core(a_p)
        L, _full = _largest_owner(core)
        grp = GROUP_OF[L]
        in_group = {k for k, g in GROUP_OF.items() if g == grp}
        g_d, g_p = _layer(120.0, c, radius=1.1, name="group 120", scope="group", group=grp)
        s_g, locks_g, _r = cook_all()
        l_d, l_p = _layer(300.0, c, radius=1.1, name="lock 300", scope="locks", locks=[L])
        s_l, locks_l, _r = cook_all()
        core = np.intersect1d(np.intersect1d(core, _core(g_p)), _core(l_p))
        stack = [(40.0, 1.0, ALL), (120.0, 1.0, ("group", grp)), (300.0, 1.0, ("locks", (L,)))]
        row = _grade(core, stack, evenness=False)
        on_core = {o for p in core for o in K.own[p]}
        full_L = float(sum(K.area[p] for p in core if L in K.own[p]))
        got_L = row["locks"][K.names[L]]["roots"]
        row.update({"lock": K.names[L], "group": grp, "locks_of_the_group_on_the_core": len(on_core & in_group),
                    "locks_of_other_groups_on_the_core": len(on_core - in_group),
                    "the_locks_own_per_cm2_of_its_skin": r3(got_L / max(full_L, 1e-9)),
                    "the_group_layer_recooked_only_its_locks": set(locks_g) <= in_group and len(locks_g) > 0,
                    "the_lock_layer_recooked_only_the_lock": locks_l == [L]})
        # the order is by owner, not by place in the list: the lock's layer moved under the others changes nothing
        cover0 = [x.copy() for x in ga.mask_cover(node, L)]
        ga.mask_move(node, l_d, 0)
        cover1 = ga.mask_cover(node, L)
        regrown = cook_all()[1]
        row["lock_layer_moved_to_the_bottom_of_the_list"] = {
            "cover_equal": bool(np.array_equal(cover0[0], cover1[0]) and np.array_equal(cover0[1], cover1[1])),
            "locks_regrown": len(regrown)}
        # inside one owner the upper layer wins: a second all-locks layer of 75 on top, then moved under the 40
        t_d, t_p = _layer(75.0, c, radius=1.1, name="all 75")
        cook_all()
        core2 = np.intersect1d(core, _core(t_p))
        upper = _grade(core2, [(40.0, 1.0, ALL), (75.0, 1.0, ALL), (120.0, 1.0, ("group", grp)),
                               (300.0, 1.0, ("locks", (L,)))], evenness=False)
        ga.mask_move(node, t_d, 0)
        cook_all()
        lower = _grade(core2, [(75.0, 1.0, ALL), (40.0, 1.0, ALL), (120.0, 1.0, ("group", grp)),
                               (300.0, 1.0, ("locks", (L,)))], evenness=False)
        row["a_second_all_locks_layer_75_on_top"] = {k: upper[k] for k in ("expected_per_cm2", "measured_per_cm2", "ratio",
                                                                           "limit", "pass", "locks_outside_their_limit")}
        row["the_same_layer_moved_under_the_40"] = {k: lower[k] for k in ("expected_per_cm2", "measured_per_cm2", "ratio",
                                                                           "limit", "pass", "locks_outside_their_limit")}
        row["pass"] = (row["pass"] and row["the_group_layer_recooked_only_its_locks"] and row["the_lock_layer_recooked_only_the_lock"]
                       and row["lock_layer_moved_to_the_bottom_of_the_list"]["cover_equal"] and not regrown
                       and upper["pass"] and lower["pass"])
        rows[zname] = row
        clear_layers()
    C.add("o1_owner_order_all_locks_then_group_then_lock", _all(rows), rows,
          "an all-locks layer of 40, a group layer of 120 and a lock layer of 300 painted white over the same skin "
          "(skin under floating mesh, the most stacked skin, the whorl): the lock gives 300 on its skin, the other "
          "locks of its group 120 together, the locks of other groups 40 with the group; " + LIMIT + "; the group's "
          "layer recooks only its locks, the lock's only the lock; the lock's layer moved to the bottom of the list "
          "changes nothing (0 locks regrown); a second all-locks layer on top wins over the first, and under it loses",
          note="where every lock on the core is in the group, the all-locks layer shows nowhere: see "
               "locks_of_other_groups_on_the_core")


def o2_what_d_means_for_one_lock():
    """THE DEFINITION MEASURED (the brief: settle by measuring): a layer of 120 owned by ONE lock, on the most
    stacked skin. Proposed: that lock alone gives 120 on its skin (every prim it owns, whole), the other locks
    there keep what they had."""
    c = Z["most_stacked"]
    d0, p0 = _layer(120.0, c, radius=1.3)
    core = _core(p0)
    ga.mask_remove(node, d0)
    cook_all()
    L0, full = _largest_owner(core)
    rows = {}
    for L in sorted(full, key=full.get, reverse=True)[:4]:
        d, p = _layer(120.0, c, radius=1.3, scope="locks", locks=[L])
        s, locks, _r = cook_all()
        row = _grade(core, [(120.0, 1.0, ("locks", (L,)))], evenness=False)
        a = K.roots_in(core, G.roots())[0]
        b = K.roots_in(core, ROOTS0)[0]
        got = a.get(L, 0)
        rows[K.names[L]] = {
            "its_skin_on_the_core_cm2": r3(full[L]), "of_which_its_share_when_divided_cm2": r3(K.lock_area_in(core, L)),
            "owners_on_that_skin_mean": r3(full[L] / max(K.lock_area_in(core, L), 1e-9)),
            "automatic_roots": b.get(L, 0), "roots": got, "per_cm2_of_its_skin": r3(got / max(full[L], 1e-9)),
            "ratio_to_120_alone": r3(got / max(120.0 * full[L], 1e-9)),
            "ratio_if_120_were_shared_with_the_other_locks": r3(got / max(120.0 * K.lock_area_in(core, L), 1e-9)),
            "limit": r3(lib.density_limit(120.0 * full[L], 1.0)),
            "other_locks_roots_unchanged": all(a.get(k, 0) == b.get(k, 0) for k in set(a) | set(b) if k != L),
            "locks_recooked": [K.names[k] for k in locks], "all_locks_on_the_core_per_cm2": row["measured_per_cm2"],
            "pass": row["pass"] and locks == [L]}
        ga.mask_remove(node, d)
        cook_all()
    C.add("o2_a_layer_owned_by_one_lock_that_lock_alone_gives_D", _all(rows), rows,
          "a layer of 120 owned by one lock, painted white on the most stacked skin (its four largest owners in "
          "turn): that lock's roots = 120 x the skin it owns there (whole prims, not divided among the owners) "
          "within max(0.15, 2 / sqrt(N)); every other lock's roots there as before; only that lock recooks")


# ---------------------------------------------------------------------------
# the mask of a density layer: blend modes, Multiply on top, fill layers, compose
# ---------------------------------------------------------------------------

BLEND_ZONES = ("crown_whorl", "top_of_head", "ordinary_hair_back_06")


def _formula(below, value, mode, effect=1.0):
    """The contract's own line, written here apart from logic.py: below + (blend - below) x effect, in 0..1."""
    blend = {"normal": value, "multiply": below * value, "add": below + value, "subtract": below - value,
             "min": min(below, value), "max": max(below, value)}[mode]
    return min(1.0, max(0.0, below + (blend - below) * effect))


def b1_blend_modes():
    """Each blend mode in a layer's mask: the mask against the formula, and the roots the layer then grows."""
    for zname in BLEND_ZONES:
        rows = {}
        for mode, below, value, opacity in (("normal", 0.5, 0.25, 1.0), ("multiply", 0.5, 0.5, 1.0), ("add", 0.5, 0.25, 1.0),
                                            ("add", 0.75, 0.75, 1.0), ("subtract", 0.75, 0.5, 1.0),
                                            ("subtract", 0.25, 0.5, 1.0), ("min", 0.75, 0.25, 1.0), ("min", 0.25, 0.75, 1.0),
                                            ("max", 0.25, 1.0, 1.0), ("max", 0.75, 0.5, 1.0), ("multiply", 1.0, 0.5, 0.5),
                                            ("add", 0.25, 0.5, 0.5)):
            d, a = _layer(300.0, zname, value=below)
            b = ga.mask_add(node, "top", parent=d, mode=mode, opacity=opacity)
            K.paint_disc(b, Z[zname], 1.3, value=value)
            cook_all()
            core = np.intersect1d(_core(a), _core(b))
            mask = ga.mask_values(node, d)[0]
            pts = np.unique(np.concatenate([K.S["prim_points"][p] for p in core]))
            want = _formula(below, value, mode, opacity)
            err = float(np.abs(mask[pts] - want).max())
            row = _grade(core, [(300.0, want, ALL)])
            row.update({"below": below, "value": value, "opacity": opacity, "formula_m": r3(want), "mask_error": err,
                        "pass": row["pass"] and err <= 1e-6})
            rows["%s %s over %s%s" % (mode, value, below, " at opacity %s" % opacity if opacity < 1 else "")] = row
            clear_layers()
        C.add("b1_blend_modes_in_a_mask_" + zname, _all(rows), rows,
              "in the mask of a layer of 300, a paint layer in each mode over a painted layer (12 cases): the mask "
              "there equals below + (blend(below, value) - below) x opacity clamped to 0..1 (error <= 1e-6), and the "
              "roots are automatic x (1 - m) + 300 x skin x m; " + LIMIT)
        C.add("b1_blend_modes_roots_even_" + zname, _even(rows), {k: v.get("even") for k, v in rows.items()}, EVEN_LIMIT)


def b3_multiply_bounds():
    """Multiply's use: the top layer of a mask, bounding the region. 0: the layer applies nowhere under it."""
    ref = rest_points()
    roots_ref = G.roots()
    for zname in Z:
        rows = {}
        for v in (0.0, 0.5, 1.0):
            d, a = _layer(300.0, zname)
            b = ga.mask_add(node, "bound", parent=d, mode="multiply")
            K.paint_disc(b, Z[zname], 1.3, value=v)
            cook_all()
            row = _grade(np.intersect1d(_core(a), _core(b)), [(300.0, v, ALL)])
            if v == 0.0:
                row["roots_at_the_same_places"] = _same_roots(roots_ref)
                row["every_point_equal_bytes"] = rest_points()[0] == ref[0]
                row["pass"] = row["pass"] and row["roots_at_the_same_places"] and row["every_point_equal_bytes"]
            rows["x %s over white" % v] = row
            clear_layers()
        if zname in BLEND_ZONES:
            # a region: the top Multiply layer is black everywhere and white on a smaller disc
            d, a = _layer(300.0, zname, radius=1.5)
            b = ga.mask_add(node, "region", parent=d, mode="multiply")
            ga.mask_fill(node, b, 0.0)
            K.paint_disc(b, Z[zname], 0.6, value=1.0)
            cook_all()
            mask = ga.mask_values(node, d)[0]
            inside = K.core(mask, 1.0)
            row = _grade(inside, [(300.0, 1.0, ALL)], evenness=False)
            dist = np.sqrt(((K.cen - Z[zname]) ** 2).sum(1))
            lo, hi = K.prim_minmax(mask.astype(float))
            ring = np.nonzero((dist > 1.05) & (dist < 1.35) & (hi <= 0.0) & (K.nown > 0))[0]
            b0, a0 = K.roots_in(ring, ROOTS0)[0], K.roots_in(ring, G.roots())[0]
            row["outside_the_region_but_under_the_white"] = {"prims": int(len(ring)), "automatic_roots": sum(b0.values()),
                                                             "roots": sum(a0.values()), "same_per_lock": a0 == b0}
            row["pass"] = row["pass"] and a0 == b0 and len(ring) > 0 and len(inside) > 0
            rows["a white region of 0.6 cm in a black Multiply layer over white"] = row
            clear_layers()
        C.add("b3_multiply_as_the_top_layer_of_a_mask_" + zname, _all(rows), rows,
              "over a mask painted white on a layer of 300, a Multiply paint layer at 0 / 0.5 / 1: the automatic groom "
              "byte for byte / automatic x 0.5 + 150 x skin / 300; on three kinds of skin also a Multiply layer filled "
              "black with a white region: 300 inside, the automatic roots outside it; " + LIMIT)
        C.add("b3_roots_even_" + zname, _even(rows), {k: v.get("even") for k, v in rows.items()}, EVEN_LIMIT)


def m1_compose():
    c = Z["ordinary_hair_back_06"]
    off = np.array([0.8, 0.0, 0.0])
    d1 = ga.mask_add(node, "40", density=40.0)
    a = ga.mask_add(node, "A 0.8", parent=d1)
    b = ga.mask_add(node, "B x0.5", parent=d1, mode="multiply", opacity=0.6)
    ga.mask_add(node, "G + 0.2", parent=d1, kind="fill", mode="add", value=0.2)
    e = ga.mask_add(node, "E off", parent=d1)
    d2 = ga.mask_add(node, "300", density=300.0, opacity=0.7)
    h = ga.mask_add(node, "H", parent=d2)
    for lid, centre, radius, soft, value in ((a, c, 1.2, 0.0, 0.8), (b, c + off, 1.2, 1.0, 0.5), (h, c - off, 1.0, 0.5, 1.0),
                                             (e, c, 2.0, 0.0, 1.0)):
        s = lib.gm_session(node, lid)
        s.dab(centre / G.unit, None, radius, value, soft)
        s.commit()
    ga.mask_set(node, e, on=False)
    (va, ca), (vb, cb), (vh, ch) = ((x.astype(np.float64) for x in ga.mask_values(node, i)) for i in (a, b, h))

    def mask1(order):
        m = np.zeros(len(va))
        for name in order:
            if name == "a":
                m = m + (va - m) * ca
            elif name == "b":
                m = m + (m * vb - m) * cb * 0.6
            elif name == "g":
                m = m + 0.2
            m = np.clip(m, 0.0, 1.0)
        return m

    def cover(order, o2=0.7, first="d1"):
        e1, e2 = mask1(order), (vh * ch) * o2
        if first == "d1":
            return (1 - e1) * (1 - e2), 40.0 * e1 * (1 - e2) + 300.0 * e2
        return (1 - e1) * (1 - e2), 300.0 * e2 * (1 - e1) + 40.0 * e1

    def error(want):
        keep, add = (x.astype(np.float64) for x in ga.mask_cover(node))
        return max(float(np.abs(keep - want[0]).max()), float(np.abs(add - want[1]).max()) / 300.0)

    err_mask = float(np.abs(ga.mask_values(node, d1)[0].astype(np.float64) - mask1("abg")).max())
    err = error(cover("abg"))
    before = [x.copy() for x in ga.mask_cover(node)]
    ga.mask_move(node, a, 9)                       # A to the top of its mask: Normal overrides what is below it there
    err_order = error(cover("bga"))
    changed = float(np.abs(ga.mask_cover(node)[1] - before[1]).max())
    ga.mask_move(node, a, 0)
    ga.mask_move(node, d2, 0)                      # the density layers swapped: the 40 now over the 300
    err_swap = error(cover("abg", first="d2"))
    ga.mask_move(node, d2, 9)
    ga.mask_set(node, d2, opacity=0.0)
    err_op = error(cover("abg", o2=0.0))
    try:
        ga.mask_remove(node, config.MASK_BASE_ID)
        base_kept = False
    except ValueError:
        base_kept = True
    try:
        ga.mask_move(node, config.MASK_BASE_ID, 3)
        base_fixed = False
    except ValueError:
        base_fixed = True
    first = ga.read_data(node).masks[0]
    clear_layers()
    ok = (max(err, err_order, err_swap, err_op) <= 1e-5 and err_mask <= 1e-6 and changed > 1.0 and base_kept and base_fixed
          and first.kind == "base" and ga.read_data(node).masks[0].kind == "base")
    C.add("m1_masks_and_density_layers_compose", ok,
          {"mask_error": err_mask, "cover_error": err, "mask_layer_reordered_error": err_order,
           "reorder_changed_the_density_by_up_to": r3(changed), "density_layers_swapped_error": err_swap,
           "opacity_0_error": err_op, "the_automatic_layer_cannot_be_deleted": base_kept,
           "the_automatic_layer_cannot_be_moved": base_fixed, "first_row": [first.kind, first.name]},
          "two density layers (40; 300 at opacity 0.7), the first's mask a Normal layer, a soft Multiply layer at "
          "opacity 0.6, an Add fill layer and a layer that is off, the second's a soft white dab: the first's mask and "
          "mask_cover (keep, add / 300) against arithmetic written here, also after a mask layer is reordered, the "
          "density layers are swapped, and an opacity is 0: max error <= 1e-5; the automatic layer is the first row "
          "and can be neither deleted nor moved")


def m2_fill():
    """A fill layer: one value over all the skin; with a lock as the density layer's owner, over that lock's."""
    ref = rest_points()
    lk = G.lock_id("hair_back_14")
    prims = G.region_prims(lk)
    full = float(K.area[prims].sum())
    d = ga.mask_add(node, "lock 40", density=40.0, scope="locks", locks=[lk])
    f = ga.mask_add(node, "fill", parent=d, kind="fill", value=1.0)
    s0, locks0, _r = cook_all()
    white = G.strands_by_lock().get(lk, 0)
    n0 = len(hou.undos.undoLabels())
    ga.mask_set(node, f, value=0.5)
    steps = len(hou.undos.undoLabels()) - n0
    label = hou.undos.undoLabels()[0]
    s, locks, _r = cook_all()
    half = G.strands_by_lock().get(lk, 0)
    t = time.perf_counter()
    hou.undos.performUndo()
    node.cook()
    us = time.perf_counter() - t
    ul = CC.take()
    G.rest.cook()
    back = G.strands_by_lock().get(lk, 0)
    others = all(G.strands_by_lock().get(k) == BASE.get(k) for k in BASE if k != lk)
    ga.mask_set(node, f, value=0.0)
    cook_all()
    black_equal = rest_points()[0] == ref[0]
    try:
        lib.gm_session(node, f)
        refused = False
    except ValueError:
        refused = True
    # a density layer whose mask was never painted applies nowhere: changing its rows regrows nothing
    empty_d, empty_p = _layer(300.0)
    cook_all()
    ga.mask_set(node, empty_d, density=75.0)
    ga.mask_set(node, empty_p, opacity=0.3)
    unpainted = cook_all()[1]
    clear_layers()
    # whorl roots are extra to a lock's count and not part of the scatter the layers replace: none on this lock
    want = 40.0 * full
    want_half = BASE.get(lk, 0) * 0.5 + 20.0 * full
    lim, lim_half = lib.density_limit(want, 1.0), lib.density_limit(want_half, 1.0)
    C.add("m2_fill_layer_one_value_over_its_owners_skin",
          locks0 == [lk] and locks == [lk] and abs(white / want - 1) <= lim and abs(half / want_half - 1) <= lim_half
          and black_equal and steps == 1 and us < UNDO_S and not ul and back == white and others and refused
          and unpainted == [] and s <= 0.2 * len(locks) + 0.1,
          {"lock": K.names[lk], "its_skin_cm2": r3(full), "automatic_strands": BASE.get(lk),
           "strands_white_and_half": [white, half], "expected_white_half": [r3(want), r3(want_half)],
           "limits": [r3(lim), r3(lim_half)], "fill_0_is_the_automatic_groom_byte_for_byte": black_equal,
           "locks_recooked": [K.names[k] for k in locks], "display_s": r3(s),
           "undo_steps": steps, "label": label, "undo_s": r3(us), "undo_locks": len(ul), "strands_after_undo": back,
           "other_locks_keep_their_strands": others, "painting_a_fill_layer_is_refused": refused,
           "rows_of_a_never_painted_layer_changed_recook": len(unpainted)},
          "a layer of 40 owned by one lock, its mask one fill layer: white gives 40 x the lock's skin, 0.5 gives "
          "automatic x 0.5 + 20 x skin (max(0.15, 2 / sqrt(N))), 0 the automatic groom byte for byte; only that lock "
          "recooks, within the speed limit; the value change is one undo step, undone < 0.1 s with 0 locks; the brush "
          "refuses a fill layer; a layer whose mask was never painted applies nowhere (its rows changed: 0 locks)")


# ---------------------------------------------------------------------------
# no layer = the automatic groom
# ---------------------------------------------------------------------------

def r1_states():
    rows = {}
    ref = rest_points()                # the groom without layers, as this check finds it
    rows["strands_as_the_first_cook"] = {"points_equal": G.strands_by_lock() == BASE}

    def same(tag, grown=None):
        P, L = rest_points()
        rows[tag] = {"points_equal": P == ref[0], "ids_equal": bool(np.array_equal(L, ref[1])),
                     "locks_grown": grown}
    lk = G.lock_id("hair_back_14")
    d1, p1 = _layer(300.0)
    same("a density layer with an empty paint layer added", len(cook_all()[1]))
    d2, p2 = _layer(0.0)
    d3 = ga.mask_add(node, "lock fill", density=40.0, scope="locks", locks=[lk])
    f3 = ga.mask_add(node, "fill", parent=d3, kind="fill", value=1.0)
    places = ((p1, "ordinary_hair_back_06"), (p2, "crown_whorl"))
    for lid, z in places:
        K.paint_disc(lid, Z[z], 1.3)
    cook_all()
    rows["painted"] = {"changed": rest_points()[0] != ref[0]}
    for lid in (d1, d2, d3):
        ga.mask_set(node, lid, on=False)
    cook_all()
    same("every density layer off")
    for lid in (d1, d2, d3):
        ga.mask_set(node, lid, on=True)
    for lid in (p1, p2, f3):
        ga.mask_set(node, lid, on=False)
    cook_all()
    same("every mask layer off (the density layers on)")
    for lid in (p1, p2, f3):
        ga.mask_set(node, lid, on=True)
    for lid in (d1, d2, d3):
        ga.mask_set(node, lid, opacity=0.0)
    cook_all()
    same("every density layer at opacity 0")
    for lid in (d1, d2, d3):
        ga.mask_set(node, lid, opacity=1.0)
    for lid in (p1, p2, f3):
        ga.mask_set(node, lid, opacity=0.0)
    cook_all()
    same("every mask layer at opacity 0")
    for lid in (p1, p2, f3):
        ga.mask_set(node, lid, opacity=1.0)
    cook_all()
    rows["back on"] = {"changed": rest_points()[0] != ref[0]}
    for lid, z in places:
        K.paint_disc(lid, Z[z], 1.3, value=0.0)                 # black over all of it (the same dabs as the white)
    ga.mask_set(node, f3, value=0.0)
    cook_all()
    same("every mask black")
    rows["every mask black"]["mask_max"] = max(float(ga.mask_values(node, x)[0].max()) for x in (d1, d2, d3))
    for lid, z in places:
        K.paint_disc(lid, Z[z], 1.3)
        K.paint_disc(lid, Z[z], 2.2, dab_r=0.5, erase=True, label="Erase mask")       # the eraser
    cook_all()
    same("every paint layer erased with the brush")
    rows["every paint layer erased with the brush"]["coverage_left_max"] = max(float(ga.mask_values(node, x)[1].max())
                                                                               for x in (p1, p2))
    for lid, z in places:
        K.paint_disc(lid, Z[z], 1.3)
    cook_all()
    for lid in (p1, p2):
        ga.mask_clear(node, lid)
    cook_all()
    same("mask_clear on every paint layer")
    clear_layers()
    same("every layer deleted")
    ok = rows["painted"]["changed"] and rows["back on"]["changed"] and \
        all(r.get("points_equal", True) and r.get("ids_equal", True) for r in rows.values())
    C.add("r1_black_off_opacity_0_erased_deleted_is_the_automatic_groom_byte_for_byte", ok, rows,
          "three density layers (300 and 0 painted white, 40 owned by a lock under a white fill layer), in one "
          "process, against the groom cooked before any layer: every rest point's bytes and every lock id with the "
          "density layers off, the mask layers off, either at opacity 0, every mask black, erased, cleared, deleted")


def r2_counts():
    if not T55 or not os.path.isfile(T55):
        C.add("r2_strand_counts_as_t55", False, T55, "--t55 <qc_report.json>", note="not run: no t55 report given")
        return
    with open(T55, encoding="utf-8") as fh:
        rep = json.load(fh)
    ref = {r["name"]: r["strands"] for r in rep["locks"]}
    now = {K.names[k]: v for k, v in G.strands_by_lock().items()}
    diff = {k: [ref.get(k), now.get(k)] for k in set(ref) | set(now) if ref.get(k) != now.get(k)}
    C.add("r2_strand_counts_as_t55", not diff and sum(now.values()) == rep["ours"]["strands"],
          {"strands": sum(now.values()), "t55": rep["ours"]["strands"], "locks": len(now), "different": diff},
          "strands per lock equal the v0.1 end-to-end test's (t55 qc_report.json)", evidence=T55)


def _qc(hip, tag, extra=()):
    out = OUT + "/qc_" + tag
    args = [QC, SUITE, hip, out] + (["--ref", REF] if REF else []) + list(extra)
    hython(args, "qc_%s.log" % tag)
    path = out + "/qc_report.json"
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _numbers(rep):
    return {c["check"]: c["value"] for c in rep["checks"]}


def r3_qc():
    hip = OUT + "/nolayer.hiplc"
    hou.hipFile.save(hip)
    rep = _qc(hip, "nolayer")
    if rep is None:
        C.add("r3_qc_without_layers", False, "no qc_report.json", note="see qc_nolayer.log")
        return
    failed = [c["check"] for c in rep["checks"] if not c["pass"]]
    row = {"passed": len(rep["checks"]) - len(failed), "of": len(rep["checks"]), "failed": failed}
    if T55 and os.path.isfile(T55):
        with open(T55, encoding="utf-8") as fh:
            ref = _numbers(json.load(fh))
        now = _numbers(rep)
        row["numbers_equal_t55"] = sum(now.get(k) == v for k, v in ref.items())
        row["numbers_different"] = {k: [now.get(k), v] for k, v in ref.items() if now.get(k) != v}
        row["largest_relative_difference"] = max([abs(now[k] - v) / max(abs(v), 1e-12) for k, v in ref.items()
                                                  if now.get(k) != v and isinstance(now.get(k), (int, float))] + [0.0])
    C.add("r3_qc_without_layers_27_of_27", not failed and len(rep["checks"]) >= 27, row,
          "grooming-check on the groom without layers: every check passes",
          evidence="qc_nolayer/qc_report.json",
          note="with \"Fit lookup per lock\" on (the default) 8 of the 27 numbers differ from t55's by up to 1 %: see r3b")
    # the same groom with v0.1's lookup: the numbers themselves
    node.parm("lookup_per_piece").set(0)
    cook_all()
    hip2 = OUT + "/nolayer_v01_lookup.hiplc"
    hou.hipFile.save(hip2)
    node.parm("lookup_per_piece").set(1)
    cook_all()
    rep2 = _qc(hip2, "nolayer_v01_lookup")
    if rep2 is None or not (T55 and os.path.isfile(T55)):
        C.add("r3b_qc_numbers_as_t55_with_v01_lookup", False, "no report or no --t55", note="see qc_nolayer_v01_lookup.log")
        return
    now = _numbers(rep2)
    diff = {k: [now.get(k), v] for k, v in ref.items() if now.get(k) != v}
    C.add("r3b_qc_numbers_as_t55_with_v01_lookup", not diff, {"numbers": len(ref), "different": diff},
          "\"Fit lookup per lock\" off: all 27 QC numbers equal t55's", evidence="qc_nolayer_v01_lookup/qc_report.json")


def r5_fullcook():
    if not V01:
        C.add("r5_full_cook_within_10pct_of_v01", False, None, "--v01 <suite>", note="not run: no v0.1 suite given")
        return
    runs = {"new": [], "v01": []}
    for i in range(3):                                   # interleaved, each in a new process
        for tag, suite in (("new", SUITE), ("v01", V01)):
            outf = OUT + "/fullcook_%s_%d.json" % (tag, i)
            hython([HERE + "/accept_v02a_sub.py", "fullcook", suite, SCENE, outf, HERE, "3"], "fullcook_%s_%d.log" % (tag, i))
            if os.path.isfile(outf):
                with open(outf, encoding="utf-8") as fh:
                    got = json.load(fh)
                if "median_s" in got:
                    runs[tag].append({"runs_s": got["runs_s"], "median_s": got["median_s"], "strands": got["strands"]})
    if len(runs["new"]) < 3 or len(runs["v01"]) < 3:
        C.add("r5_full_cook_within_10pct_of_v01", False, runs, note="a timing process failed: see fullcook_*.log")
        return
    new = float(np.median([r["median_s"] for r in runs["new"]]))
    old = float(np.median([r["median_s"] for r in runs["v01"]]))
    C.add("r5_full_cook_within_10pct_of_v01", new <= old * 1.10 and runs["new"][0]["strands"] == runs["v01"][0]["strands"],
          {"new_median_s": r3(new), "v01_median_s": r3(old), "ratio": r3(new / old), "runs": runs},
          "cold full cook of the rest groom, 3 processes each, interleaved: median <= 1.10 x v0.1's")


# ---------------------------------------------------------------------------
# a painted groom passes QC; a lock grown short fails it
# ---------------------------------------------------------------------------

def q1_painted_qc():
    spot = lib.densest_spot(ROOTS0[0], 1.0)[0]
    before = lib.disc_density(ROOTS0[0], spot, 1.0)
    # the crown down to v006's density: a layer of 5,104 painted white on the whorl's dense core (dabs of 0.3 cm
    # on the points within 0.9 cm: a disc of ~1.2 cm)
    a_d, a_p = _layer(5104.0, K.snap(spot), radius=0.9, name="Crown 5104")
    b_d, b_p = _layer(150.0, "under_floating_mesh", radius=2.0, name="Thin skin 150")
    cook_all()
    r = G.roots()
    thin = _grade(_core(b_p), [(150.0, 1.0, ALL)])
    crown_core = _grade(_core(a_p), [(5104.0, 1.0, ALL)], evenness=False)
    crown = lib.disc_density(r[0], spot, 1.0)
    infos = {i.id: i for i in ga.lock_infos(node)}
    now = G.strands_by_lock()
    hip = OUT + "/painted.hiplc"
    hou.hipFile.save(hip)
    clear_layers()
    row = {"crown_densest_1cm_disc_per_cm2": [r3(before), r3(crown)], "v006": 5104,
           "crown_core": {k: crown_core[k] for k in ("core_cm2", "measured_per_cm2", "ratio", "limit", "pass",
                                                     "locks_outside_their_limit", "locks_asked_under_one_root")},
           "thin_skin": thin, "strands": sum(now.values())}
    C.add("q1_crown_down_to_v006_and_thin_skin_up",
          abs(crown / 5104.0 - 1) <= 0.15 and thin["pass"] and thin["measured_per_cm2"] > thin["automatic_per_cm2"], row,
          "a layer of 5,104 painted white on the whorl's dense core: the 1 cm disc that was the densest within 15 % of "
          "5,104 / cm2; a layer of 150 painted white on skin under floating mesh: 150 there within max(0.15, 2 / "
          "sqrt(N)), above the automatic", note="crown_core (each lock on its own skin in the painted core) is reported")
    rep = _qc(hip, "painted")
    if rep is None:
        C.add("q1_painted_groom_passes_qc_27_of_27", False, "no qc_report.json", note="see qc_painted.log")
        return
    failed = [(c["check"], c["value"], c["limit"]) for c in rep["checks"] if not c["pass"]]
    nums = _numbers(rep)
    before_nums = {}
    path = OUT + "/qc_nolayer/qc_report.json"
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            before_nums = _numbers(json.load(fh))
    C.add("q1_painted_groom_passes_qc_27_of_27", not failed and len(rep["checks"]) >= 27,
          {"passed": len(rep["checks"]) - len(failed), "of": len(rep["checks"]), "failed": failed,
           "density_off_worst": nums.get("density_off_worst"), "painted_locks": len(rep.get("painted_locks", [])),
           "before_and_after": {k: [before_nums.get(k), v] for k, v in nums.items()}},
          "grooming-check on the groom with the crown painted to v006's density and thin skin painted to 150 "
          "(density_off_worst is two-sided: |strands / expected - 1| for every lock)",
          evidence="qc_painted/qc_report.json")
    worst = max((abs(i.strands - (now.get(i.id, 0))) / max(i.strands, 1) for i in infos.values() if i.layered), default=0)
    C.add("q1_lock_infos_expects_what_the_network_grows", True, {"locks_under_layers": sum(i.layered for i in infos.values()),
                                                               "worst_all_strands_vs_expected": r3(worst)},
          "reported; graded by QC's density_off_worst (whorl roots apart) above", note="strands here include whorl roots")
    out = OUT + "/qc_short"
    hython([HERE + "/qc_tamper.py", SUITE, hip, out] + (["--ref", REF] if REF else []) + ["--drop", "0.3"], "qc_short.log")
    path = out + "/qc_report.json"
    if not os.path.isfile(path):
        C.add("q2_a_painted_lock_30pct_short_fails_qc", False, "no qc_report.json", note="see qc_short.log")
        return
    with open(path, encoding="utf-8") as fh:
        rep2 = json.load(fh)
    with open(out + "/qc_tamper.json", encoding="utf-8") as fh:
        tam = json.load(fh)
    failed2 = [(c["check"], c["value"], c["limit"]) for c in rep2["checks"] if not c["pass"]]
    C.add("q2_a_painted_lock_30pct_short_fails_qc", any(f[0] == "density_off_worst" for f in failed2),
          {"lock": tam.get("lock"), "cut": tam.get("cut"), "failed": failed2},
          "the same groom with 30 % of one painted lock's strands removed while it cooks: density_off_worst fails",
          evidence="qc_short/qc_report.json")
    out = OUT + "/qc_long"
    hython([HERE + "/qc_tamper.py", SUITE, hip, out] + (["--ref", REF] if REF else []) + ["--drop", "-0.3"], "qc_long.log")
    path = out + "/qc_report.json"
    if os.path.isfile(path) and os.path.isfile(out + "/qc_tamper.json"):
        with open(path, encoding="utf-8") as fh:
            rep3 = json.load(fh)
        with open(out + "/qc_tamper.json", encoding="utf-8") as fh:
            tam3 = json.load(fh)
        failed3 = [(c["check"], c["value"], c["limit"]) for c in rep3["checks"] if not c["pass"]]
        C.add("q2_a_painted_lock_30pct_over_fails_qc", any(f[0] == "density_off_worst" for f in failed3),
              {"lock": tam3.get("lock"), "cut": tam3.get("cut"), "failed": failed3},
              "the same groom with 30 % MORE strands on one painted lock: density_off_worst fails (the check is two-sided)",
              evidence="qc_long/qc_report.json")
    else:
        C.add("q2_a_painted_lock_30pct_over_fails_qc", False, "no qc_report.json", note="see qc_long.log")


# ---------------------------------------------------------------------------
# persistence: Detect, Update regions, save / reopen, publish, migration, a missing lock
# ---------------------------------------------------------------------------

def _stack():
    lk = G.lock_id("hair_back_14")
    data = ga.read_data(node)
    _layer(120.0, "ordinary_hair_back_06", value=0.8, name="All 120")
    d2, p2 = _layer(300.0, None, name="Soft 300", opacity=0.7)
    s = lib.gm_session(node, p2)
    s.dab(Z["top_of_head"] / G.unit, None, 1.5, 0.3, 1.0)
    s.commit()
    ga.mask_add(node, "Bound", parent=d2, kind="fill", mode="multiply", value=0.9)
    o, _p = _layer(40.0, "crown_whorl", radius=1.0, name="Off")
    ga.mask_set(node, o, on=False)
    one, one_p = _layer(0.0, K.snap(K.cen[G.region_prims(lk)].mean(0)), radius=1.5, name="Lock B bare",
                        scope="locks", locks=[lk])
    group = data.lock(G.lock_id("hair_bang_08")).group
    g, _gp = _layer(75.0, next(k for k in Z if k.startswith("fringe_")), value=0.5, radius=1.0, name="Group 75",
                    scope="group", group=group, opacity=0.5)
    ga.mask_add(node, "Fringe fill", parent=g, kind="fill", mode="max", value=0.2)
    cook_all()
    return lk, one, one_p


def _snapshot():
    data = ga.read_data(node)
    return ([dict(m.__dict__) for m in data.masks],
            {(m.id, n): x for m in data.masks for n, x in zip("va", lib.mask_arrays(node, m.id))}, G.strands_by_lock())


def _same(a, b):
    masks = all((x is None) == (y is None) and (x is None or np.array_equal(x, y))
                for x, y in ((a[1].get(k), b[1].get(k)) for k in set(a[1]) | set(b[1])))
    return {"layers": a[0] == b[0], "masks": masks, "strands": a[2] == b[2]}


def p1_persist():
    lk, one, one_p = _stack()
    ref = _snapshot()
    rows = {"rows": len(ref[0]), "strands": sum(ref[2].values()), "automatic": sum(BASE.values())}
    ga.detect(node)
    cook_all()
    rows["detect"] = _same(_snapshot(), ref)
    ga.split_regions(node)
    K.reload()
    cook_all()
    rows["update_regions"] = _same(_snapshot(), ref)
    hip = OUT + "/layers.hiplc"
    hou.hipFile.save(hip)
    outf = OUT + "/reopen_layers.json"
    hython([HERE + "/accept_v02a_sub.py", "reopen", SUITE, hip, outf, HERE], "reopen_layers.log")
    got = json.load(open(outf, encoding="utf-8")) if os.path.isfile(outf) else {"error": "no file"}
    rows["reopen_in_a_new_process"] = {
        "layers": got.get("layers") == ref[0], "strands": got.get("strands") == {str(k): v for k, v in ref[2].items()},
        "stored_schema": got.get("stored_schema"), "errors": got.get("errors"), "error": got.get("error"),
        "undo_cache_gb": got.get("undo_cache_gb")}
    ok = all(all(v.values()) for k, v in rows.items() if k in ("detect", "update_regions")) and \
        rows["reopen_in_a_new_process"]["layers"] and rows["reopen_in_a_new_process"]["strands"] and \
        rows["reopen_in_a_new_process"]["stored_schema"] == model.SCHEMA and not got.get("errors") and \
        rows["strands"] != rows["automatic"]
    C.add("p1_layers_survive_detect_regions_save_reopen", ok, rows,
          "the automatic layer and 5 density layers with 7 mask layers (a grey paint, a soft dab under a Multiply fill "
          "at opacity 0.7, one off, a layer of 0 owned by a lock, a group's layer with a Max fill): the layer list, "
          "every paint layer's values and coverage (bytes) and the strands of every lock are the same after Detect, "
          "after Update regions, and in a new process after save / reopen (schema %d)" % model.SCHEMA)
    # publish, and its layers into another scene
    work = OUT + "/publish/char_Helen/04_grooming/work"
    os.makedirs(work, exist_ok=True)
    name = hou.hipFile.path()
    hou.hipFile.setName(work + "/char_Helen_grooming_v007.hiplc")
    res = ga.publish(node)
    hou.hipFile.setName(name)
    pub = {"ok": res.ok, "message": res.message}
    okp = bool(res.ok)
    if res.ok:
        tool = os.path.dirname(res.path) + "/" + config.TOOL_DATA_DIR
        rec = json.load(open(tool + "/publish.json", encoding="utf-8"))
        gd = json.load(open(tool + "/grooming_data.json", encoding="utf-8"))
        layers, mgeo = ga.masks_from_publish(tool)
        from pxr import Usd, UsdGeom
        stage = Usd.Stage.Open(res.path)
        usd = sum(len(UsdGeom.BasisCurves(p).GetCurveVertexCountsAttr().Get() or [])
                  for p in stage.Traverse() if p.IsA(UsdGeom.BasisCurves))
        pub.update({"publish_json_masks": rec.get("masks"), "grooming_data_schema": gd.get("schema"),
                    "read_back_layers_same": [dict(m.__dict__) for m in layers] == ref[0],
                    "read_back_masks_same": all(np.array_equal(np.frombuffer(mgeo.pointFloatAttribValuesAsString(
                        (config.MASK_VALUE_ATTR if n == "v" else config.MASK_COVER_ATTR) % k), np.float32), v)
                        for (k, n), v in ref[1].items() if v is not None) if mgeo is not None else False,
                    "usd_strands": usd, "usd_is_the_painted_groom": usd == sum(ref[2].values())})
        okp = pub["read_back_layers_same"] and pub["read_back_masks_same"] and pub["usd_is_the_painted_groom"] \
            and gd.get("schema") == model.SCHEMA
        clear_layers()
        n0 = len(hou.undos.undoLabels())
        came = ga.import_masks(node, tool)
        pub["import_undo_steps"] = len(hou.undos.undoLabels()) - n0
        cook_all()
        pub["import"] = dict(_same(_snapshot(), ref), layers_in=came)
        okp = okp and all(_same(_snapshot(), ref).values()) and pub["import_undo_steps"] == 1
    C.add("p2_publish_and_read_back", okp, pub,
          "publish.json names the layers and mask_layers.bgeo; the USD holds the painted groom; the layers read back "
          "from the publish, and imported into a scene without layers (one undo step), give the same masks and strands")
    return lk, one, one_p


def p3_orphan(lk, one, one_p):
    """A hair mesh version drops lock B and brings it back: the layer B owns follows it."""
    names = K.names
    src = node.inputs()[1]
    pieces = node.node("pieces").geometry()
    sp = node.node("SPINES").geometry()
    piece = sp.primIntAttribValues("piece")[list(sp.primIntAttribValues("lock_id")).index(lk)]
    pp = np.frombuffer(pieces.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3)
    pc = np.frombuffer(pieces.pointIntAttribValuesAsString("piece"), np.int32)
    want = {tuple(np.round(x, 5)) for x in pp[pc == piece]}
    gin = src.geometry()
    Pin = np.frombuffer(gin.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3)
    hit = np.array([tuple(np.round(x, 5)) in want for x in Pin])
    prims = sorted({pr.number() for pr in gin.prims() if hit[pr.vertices()[0].point().number()]})
    core = _core(one_p)
    row = {"lock": names[lk], "mesh_prims_dropped": len(prims),
           "its_roots_on_its_painted_skin_before": K.roots_in(core, G.roots())[0].get(lk, 0)}
    blast = node.parent().createNode("blast", "accept_v2_drop")
    blast.setInput(0, src)
    blast.parm("group").set(" ".join(str(x) for x in prims))
    blast.parm("grouptype").set(4)
    try:
        node.setInput(1, blast)
        ga.detect(node)
        d = ga.read_data(node)
        row["missing_after_the_new_version"] = [o.name for o in d.orphans]
        row["layer_still_names_it"] = d.mask(one).locks == [lk]
        row["its_mask_layer_is_still_there"] = d.mask(one_p) is not None and d.mask(one_p).parent == one
        cook_all()
        row["errors_new_version"] = lib.node_errors(node)
    finally:
        node.setInput(1, src)
    ga.detect(node)
    d = ga.read_data(node)
    back = [x for x in d.locks if x.match == "new"]
    row["back_as"] = [(x.id, x.name) for x in back]
    row["still_missing"] = [o.id for o in d.orphans]
    ok = len(back) == 1 and lk in row["still_missing"]
    if ok:
        new = back[0].id
        ga.split_regions(node)
        K.reload()
        cook_all()
        core = _core(one_p)
        row["roots_of_the_new_lock_on_the_painted_skin_before_reassign"] = K.roots_in(core, G.roots())[0].get(new, 0)
        d = ga.read_data(node)
        moved = d.reassign_orphan(lk, new)                      # what the panel's reassign does (controller.reassign_orphan)
        ga.write_data(node, d, "reassign orphan")
        cook_all()
        row["layers_moved"] = moved
        row["layer_now_owned_by"] = ga.read_data(node).mask(one).locks
        row["roots_of_the_new_lock_on_the_painted_skin_after_reassign"] = K.roots_in(core, G.roots())[0].get(new, 0)
        ok = (moved == ["Lock B bare"] and row["layer_now_owned_by"] == [new]
              and row["roots_of_the_new_lock_on_the_painted_skin_before_reassign"] > 0
              and row["roots_of_the_new_lock_on_the_painted_skin_after_reassign"] == 0
              and row["its_roots_on_its_painted_skin_before"] == 0 and row["layer_still_names_it"]
              and row["its_mask_layer_is_still_there"] and not row["errors_new_version"])
    blast.destroy()
    C.add("p3_a_missing_lock_keeps_its_layers_and_they_follow_it", ok, row,
          "the hair mesh loses lock B (missing: its layer of 0 and that layer's mask are kept), gets it back (a new "
          "lock id): until reassigned the new lock grows on the skin painted for B; after reassigning the missing lock "
          "to it, it grows none there")


def _as_old(schema, masks):
    """Store the node's groom_data as a file of an older schema would hold it: that schema number and layer rows."""
    raw = json.loads(node.evalParm(config.DATA_PARM))
    raw["mask_id_high"] = max([int(raw.get("mask_id_high", -1))] + [int(m["id"]) for m in masks])
    raw["schema"] = schema
    raw["masks"] = masks
    node.parm(config.DATA_PARM).set(json.dumps(raw))
    try:
        cook_all()
    except hou.Error as e:
        return str(e)
    return None


def _drop_values(ids):
    geo = hou.Geometry(node.parm(config.MASK_PARM).evalAsGeometry())
    for lid in ids:
        geo.findPointAttrib(config.MASK_VALUE_ATTR % lid).destroy()
    node.parm(config.MASK_PARM).set(geo)


def _reopen(tag):
    hip = OUT + "/%s.hiplc" % tag
    hou.hipFile.save(hip)
    outf = OUT + "/reopen_%s.json" % tag
    text = hython([HERE + "/accept_v02a_sub.py", "reopen", SUITE, hip, outf, HERE], "reopen_%s.log" % tag)
    got = json.load(open(outf, encoding="utf-8")) if os.path.isfile(outf) else {"error": "no file"}
    status = [ln for ln in text.splitlines() if "older test build" in ln]
    return {"stored_schema": got.get("stored_schema"), "rows": [(m["kind"], m["name"]) for m in got.get("layers", [])],
            "said": got.get("dropped"), "errors": got.get("errors"), "error": got.get("error"),
            "status_line": status[:1], "traceback_in_output": "Traceback (most recent call last)" in text}


def _reopen_ok(r, schema):
    return (r["stored_schema"] == schema and not r["errors"] and not r["error"] and bool(r["status_line"])
            and not r["traceback_in_output"])


def p4_migration():
    """Dev files of the earlier builds open: schema 3 (factor and strands / cm2 fill layers under a mask, paint
    layers, blend modes), schema 4 ("= D" layers, folders), schema 5 (one 0..1 mask x the lock's own Density)."""
    clear_layers()
    # ---- schema 3
    _d, keep = _layer(150.0, "ordinary_hair_back_06", value=0.5)
    _d, x = _layer(150.0, "top_of_head")
    _d, y = _layer(150.0, "crown_whorl", radius=1.0)
    _d, z = _layer(150.0, "most_stacked", radius=1.0)
    cook_all()
    core_keep, core_x, core_y, core_z = _core(keep), _core(x), _core(y), _core(z)
    _drop_values((x, y, z))                                   # a fill layer of schema 3 stored its mask only
    err = _as_old(3, [
        {"id": keep, "name": "Old paint", "kind": "paint", "mode": "replace", "unit": "factor"},
        {"id": x, "name": "Old x0.5", "kind": "fill", "mode": "multiply", "value": 0.5, "unit": "factor"},
        {"id": y, "name": "Old = 40", "kind": "fill", "mode": "replace", "value": 40.0, "unit": "density"},
        {"id": z, "name": "Old x2", "kind": "fill", "mode": "multiply", "value": 2.0, "unit": "factor"}])
    data = ga.read_data(node)
    said = ga.mask_dropped(node)
    rows3 = [(m.kind, m.name, m.parent is not None) for m in data.masks]
    dens3 = {m.name: m.density for m in data.density_layers()}
    paint = _grade(core_keep, [(150.0, 0.5, ALL)], evenness=False)     # painted 0.5: half way to the owner's Density
    forty = _grade(core_y, [(40.0, 1.0, ALL)], evenness=False)         # "= 40" under its mask: as it was
    auto_x = K.roots_in(core_x, G.roots())[0] == K.roots_in(core_x, ROOTS0)[0]     # Multiply over nothing: automatic
    auto_z = K.roots_in(core_z, G.roots())[0] == K.roots_in(core_z, ROOTS0)[0]     # dropped: automatic
    re3 = _reopen("schema3")
    ga.mask_set(node, keep, opacity=0.9)                      # the next edit writes the JSON at the current schema
    stored = json.loads(node.evalParm(config.DATA_PARM))
    row = {"rows": rows3, "densities": dens3, "said": said, "cook_error": err, "errors": lib.node_errors(node),
           "paint_layer_0.5": {k: paint[k] for k in ("ratio", "limit", "pass", "locks_outside_their_limit")},
           "strands_per_cm2_fill_40_under_its_mask": {k: forty[k] for k in ("ratio", "limit", "pass", "locks_outside_their_limit")},
           "multiply_factor_fill_over_nothing_is_the_automatic_roots": auto_x,
           "the_dropped_layer_changes_nothing": auto_z, "reopen": re3,
           "after_the_next_edit": {"schema": stored.get("schema"), "said": ga.mask_dropped(node)}}
    want_rows = [("base", "Automatic", False), ("density", "Density 1", False), ("paint", "Old paint", True),
                 ("paint", "Old x0.5", True), ("density", "Old = 40", False), ("paint", "Mask", True)]
    ok3 = (err is None and not row["errors"] and rows3 == want_rows and dens3 == {"Density 1": 150.0, "Old = 40": 40.0}
           and "Old x2" in said and "dropped" in said and "density below" in said and paint["pass"] and forty["pass"]
           and auto_x and auto_z and _reopen_ok(re3, 3) and stored.get("schema") == model.SCHEMA
           and row["after_the_next_edit"]["said"] == "")
    clear_layers()
    C.add("p4_schema_3_dev_file_opens", ok3, row,
          "a schema 3 groom_data: its paint layer and its factor fill 0..1 become the mask of one density layer of the "
          "owner's Density (painted 0.5 gives automatic x 0.5 + 75 x skin); a fill layer in strands / cm2 (Replace) "
          "becomes a density layer of that number under its mask (40 there); a factor of 2 is dropped and named "
          "(mask_dropped; OnLoaded's status line in a new process, no traceback) and changes nothing; the next edit "
          "stores schema %d" % model.SCHEMA)
    # ---- schema 4: the "= D strands / cm2" layers
    _d, a = _layer(150.0, "ordinary_hair_back_06")
    _d, b = _layer(150.0, "top_of_head")
    cook_all()
    core_a, core_b = _core(a), _core(b)
    _drop_values((a, b))
    folder = max(a, b) + 50
    err4 = _as_old(4, [{"id": a, "name": "= 120", "kind": "fill", "value": 120.0},
                       {"id": folder, "name": "Folder", "kind": "folder", "opacity": 0.5},
                       {"id": b, "name": "= 300 in a folder", "kind": "fill", "value": 300.0, "parent": folder}])
    data = ga.read_data(node)
    said4 = ga.mask_dropped(node)
    rows4 = [(m.kind, m.name) for m in data.masks]
    g120 = _grade(core_a, [(120.0, 1.0, ALL)], evenness=False)
    g300 = _grade(core_b, [(300.0, 0.5, ALL)], evenness=False)          # the folder's opacity
    re4 = _reopen("schema4")
    new = ga.mask_add(node, "after", density=10.0)
    row4 = {"rows": rows4, "said": said4, "cook_error": err4, "errors": lib.node_errors(node),
            "= 120": {k: g120[k] for k in ("ratio", "limit", "pass", "locks_outside_their_limit")},
            "= 300 in a folder at 0.5": {k: g300[k] for k in ("ratio", "limit", "pass", "locks_outside_their_limit")},
            "reopen": re4, "next_layer_id": new, "ids_before": [a, b, folder]}
    ok4 = (err4 is None and not row4["errors"] and g120["pass"] and g300["pass"] and _reopen_ok(re4, 4)
           and rows4 == [("base", "Automatic"), ("density", "= 120"), ("paint", "Mask"), ("density", "= 300 in a folder"),
                         ("paint", "Mask")] and new > folder + 2)
    clear_layers()
    C.add("p4_schema_4_dev_file_opens", ok4, row4,
          "a schema 4 groom_data (\"= 120\" under a mask; \"= 300\" under a mask in a folder at opacity 0.5): each "
          "becomes a density layer of its number whose mask is the stored mask: 120 where painted, automatic x 0.5 + "
          "150 x skin under the folder; said on the status line in a new process; a new layer takes no id in use")
    # ---- schema 5: one 0..1 mask x the lock's own Density
    _d, w = _layer(150.0, "ordinary_hair_back_06")
    _d, k = _layer(150.0, "top_of_head", value=0.0)
    cook_all()
    core_w, core_k = _core(w), _core(k)
    err5 = _as_old(5, [{"id": w, "name": "White", "kind": "paint", "mode": "normal"},
                       {"id": k, "name": "Black", "kind": "paint", "mode": "normal"},
                       {"id": k + 60, "name": "Bang half", "kind": "fill", "mode": "normal", "value": 0.5, "opacity": 0.0,
                        "scope": "group", "group": GROUP_OF[G.lock_id("hair_bang_08")]}])
    data = ga.read_data(node)
    said5 = ga.mask_dropped(node)
    rows5 = [(m.kind, m.name, m.scope) for m in data.masks]
    white = _grade(core_w, [(150.0, 1.0, ALL)], evenness=False)
    black_auto = K.roots_in(core_k, G.roots())[0] == K.roots_in(core_k, ROOTS0)[0]
    re5 = _reopen("schema5")
    row5 = {"rows": rows5, "said": said5, "cook_error": err5, "errors": lib.node_errors(node),
            "white_is_the_owners_density": {k_: white[k_] for k_ in ("ratio", "limit", "pass", "locks_outside_their_limit")},
            "black_now_shows_the_automatic_roots_below": black_auto, "reopen": re5}
    ok5 = (err5 is None and not row5["errors"] and white["pass"] and black_auto and _reopen_ok(re5, 5)
           and rows5 == [("base", "Automatic", "all"), ("density", "Density 1", "all"), ("paint", "White", "all"),
                         ("paint", "Black", "all"), ("density", "Density 2", "group"), ("fill", "Bang half", "all")]
           and "density below" in said5)
    clear_layers()
    C.add("p4_schema_5_dev_file_opens", ok5, row5,
          "a schema 5 groom_data (the 0..1 mask x the lock's own Density): the layers of one owner become the mask of "
          "one density layer of that owner's Density; white still gives 150; black, which meant no hair, now shows the "
          "automatic roots below, and the message says so")
    with open(OUT + "/schema99.txt", "w", encoding="utf-8") as fh:
        try:
            model.GroomData.from_json(json.dumps({"schema": 99}))
            fh.write("no error")
        except ValueError as e:
            fh.write(str(e))


STEPS = [("s1", s1_stroke_speed), ("u1", u1_undo_chain), ("u2", u2_undo_chain_whorl), ("u3", u3_low_limit),
         ("u4", u4_deformed_output), ("u5", u5_usage), ("d1", d1_density), ("d2", d2_black_and_erase), ("d2t", d2_tiny),
         ("d3", d3_partial), ("d4", d4_soft_edge), ("o1", o1_owner_order), ("o2", o2_what_d_means_for_one_lock),
         ("b1", b1_blend_modes), ("b3", b3_multiply_bounds), ("m1", m1_compose), ("m2", m2_fill),
         ("r1", r1_states), ("r2", r2_counts), ("r3", r3_qc), ("q1", q1_painted_qc),
         ("p4", p4_migration)]

for tag, fn in STEPS:
    if wanted(tag):
        C.log("---- " + tag)
        try:
            fn()
        except Exception:
            C.add(tag + "_raised", False, traceback.format_exc()[-2500:], note="the check raised")
            try:
                clear_layers()
            except Exception:
                pass
if wanted("p1") or wanted("p2") or wanted("p3"):
    C.log("---- p1 p2 p3")
    try:
        trio = p1_persist()
        p3_orphan(*trio)
    except Exception:
        C.add("p1_p3_raised", False, traceback.format_exc()[-2500:], note="the check raised")
if wanted("r5"):
    C.log("---- r5")
    try:
        r5_fullcook()
    except Exception:
        C.add("r5_raised", False, traceback.format_exc()[-2500:], note="the check raised")
errors = lib.node_errors(node)
C.add("z_no_error_on_the_node", not errors, errors, "no node of the HDA holds an error at the end")
C.meta["warnings"] = lib.node_warnings(node)
C.meta["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
C.write(done=True)
C.log("DONE", "passed" if all(i["pass"] for i in C.items) else "FAILED", len(C.items), "checks")
sys.stdout.flush()
os._exit(0)
