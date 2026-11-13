"""Acceptance of MONO Grooming v0.2a density layers, the core (docs/plans/grooming_v0_2.md, "Done when").

    hython accept_v02a.py <suite> <scene> <out_dir> [--v01 <v0.1 suite>] [--ref <approved groom.usd>]
                          [--t55 <qc_report.json of the v0.1 end-to-end test>] [--only id,id] [--strokes 30]

<scene> is a copy of the Helen grooming scene (it stays in the sandbox). Everything is written under <out_dir>:
accept.json ({item, pass, value, limit, evidence} per check, `passed`), accept_log.txt, and the files of the
checks that run in a process of their own (QC, full-cook timing, reopen). Hython's exit code is not reliable:
read the JSON. Run it with no other Houdini cooking: the speed limits are absolute.

Round 3, the final model: one density mask per skin point, 0..1, blended from a stack of layers (paint, fill,
folders; six blend modes); a lock grows mask x its own Density. Every density check is graded on several kinds
of skin (whorl, top of the head, a lock's start, the most stacked skin, skin under floating mesh, fringe,
ordinary, the sliver band by the ear) at white / 0.5 / 0.25 / black, with the roots of ALL locks counted in
the core of a painted disc and each lock held to the rule on its own skin there; limits are the plan's, never
tuned to a result."""
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
VALUES = (1.0, 0.5, 0.25, 0.0)
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
    for m in list(ga.read_data(node).masks):
        ga.mask_remove(node, m.id)
    cook_all()




# ---------------------------------------------------------------------------
# speed first, in a young process (the limits are absolute)
# ---------------------------------------------------------------------------

def s1_stroke_speed():
    c, _n, _p = lib.densest_spot(ROOTS0[0], 1.0)
    lid = ga.mask_add(node, "speed")
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
    ga.mask_remove(node, lid)
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
    lid = ga.mask_add(node, place)
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
    ga.mask_remove(node, lid)
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
# the mask: painted m gives m x the lock's density
# ---------------------------------------------------------------------------

def _core(lid, atol=1e-6):
    """Prims of the fine scalp the layer covers in full (coverage 1 at every corner), away from the edge."""
    return K.core(ga.mask_values(node, lid)[1], 1.0, atol=atol)


def _grade(core, keep, add, evenness=True):
    """Roots on `core` against the rule, for all locks together and for each lock on its own skin there:
    a lock's roots = its automatic roots x keep + add x its Density x its skin. keep, add: the cover there.
    The limit max(0.15, 2 / sqrt(N)) has no meaning for a lock asked under one root there (N < 1: a lock whose
    skin only touches the core, a root counted to the core from the prim beside it): such a lock may hold at
    most 2 roots, and is listed. Where no root is asked (black), a strand whose root floats over OFF_SKIN_CM
    off the skin is listed, not counted: v0.1 leaves a few start roots there (hair_base_20: 1 of 7,172, 0.24 cm
    up), and the tool judges a root where it lands on its lock's skin, which for that one is the disc's rim."""
    area = float(K.area[core].sum())
    b, rb, lb = K.roots_in(core, ROOTS0)
    a, ra, la = K.roots_in(core, G.roots())
    floating = {}
    if keep <= 0 and add <= 0 and len(ra):
        up = np.sqrt(((ra[:, None, :] - K.cen[None, :, :]) ** 2).sum(-1).min(1))
        for k in np.unique(la[up > OFF_SKIN_CM]):
            n = int(((la == k) & (up > OFF_SKIN_CM)).sum())
            floating[K.names[int(k)]] = {"roots": n, "off_the_skin_cm": round(float(up[la == k].max()), 3)}
            a[int(k)] -= n
    locks, bad = {}, []
    target = 0.0
    for k in sorted(set(b) | set(a)):
        skin = K.lock_area_in(core, k)
        want = b.get(k, 0) * keep + add * DENS[k] * skin
        target += want
        got = a.get(k, 0)
        lim = lib.density_limit(want, 1.0) if want >= 1.0 else 0.0
        if keep <= 0 and add <= 0:
            ok = got == 0                                   # black, or bounded to nothing: no root at all
        elif want < 1.0:
            ok = got <= 2
        else:
            ok = abs(got / want - 1) <= lim
        locks[K.names[k]] = {"skin_cm2": r3(skin), "automatic": b.get(k, 0), "expected": r3(want), "roots": got,
                             "ratio": r3(got / want) if want >= 1.0 else None, "limit": r3(lim), "pass": ok}
        if not ok:
            bad.append(K.names[k])
    got = sum(a.values())
    lim = lib.density_limit(target, 1.0) if target > 0 else 0.0
    row = {"core_cm2": r3(area), "automatic_per_cm2": r3(sum(b.values()) / area), "expected_per_cm2": r3(target / area),
           "measured_per_cm2": r3(got / area), "ratio": r3(got / target) if target > 0 else None, "limit": r3(lim),
           "locks_on_core": len(locks), "locks_outside_their_limit": bad, "locks": locks,
           "roots_floating_off_the_skin_not_counted": floating,
           "locks_asked_under_one_root": {k: v["roots"] for k, v in locks.items() if v["expected"] < 1.0 and v["roots"]},
           "worst_lock": max(locks.items(), key=lambda kv: abs((kv[1]["ratio"] or 1) - 1) / max(kv[1]["limit"], 1e-9))
           if locks else None,
           "pass": (got == 0 if target <= 0 else abs(got / target - 1) <= lim) and not bad}
    if evenness and got:
        ev0 = lib.lock_even(rb, lb, K, core)
        ev1 = lib.lock_even(ra, la, K, core)
        rises = {k: round(v.get("clumped", 0.0) - ev0.get(k, {}).get("clumped", 0.0), 3) for k, v in ev1.items()}
        low = [k for k, v in ev1.items() if keep <= 0 and v.get("spacing_ratio", 1.0) < EVEN_SPACING]
        row["even"] = {"clumped_now_worst": max([v.get("clumped", 0.0) for v in ev1.values()] + [0.0]),
                       "clumped_rise_worst": max(list(rises.values()) + [0.0]),
                       "spacing_ratio_lowest": min([v.get("spacing_ratio", 1.0) for v in ev1.values()] + [9.0]),
                       "locks_judged": len(ev1), "rise_per_lock": {k: v for k, v in rises.items() if v > 0},
                       "all_locks_together_clumped": r3(lib.spacing_stats(ra, area).get("clumped")),
                       "pass": all(v <= EVEN_RISE for v in rises.values()) and not low}
    return row


def _on_skin(core):
    """(roots on the core's skin, roots counted to the core that float over OFF_SKIN_CM off the skin)."""
    _a, ra, _la = K.roots_in(core, G.roots())
    if not len(ra):
        return 0, 0
    up = np.sqrt(((ra[:, None, :] - K.cen[None, :, :]) ** 2).sum(-1).min(1))
    return int((up <= OFF_SKIN_CM).sum()), int((up > OFF_SKIN_CM).sum())


def _paint(name, zone, value=1.0, radius=1.3, **kw):
    lid = ga.mask_add(node, name, **kw)
    K.paint_disc(lid, Z[zone] if isinstance(zone, str) else zone, radius, value=value)
    return lid


def _all(rows, key="pass"):
    return all(r[key] for r in rows.values())


def _even(rows):
    return all(r["even"]["pass"] for r in rows.values() if "even" in r)


def d1_density():
    ref = rest_points()
    for zname in Z:
        rows = {}
        for m in VALUES:
            lid = _paint("paint %s" % m, zname, m)
            s, locks, _r = cook_all()
            rows["painted %s" % m] = dict(_grade(_core(lid), 0.0, m), display_s=r3(s), locks_recooked=len(locks))
            ga.mask_remove(node, lid)
            cook_all()
        C.add("d1_painted_m_gives_m_x_lock_density_" + zname, _all(rows), rows,
              "a paint layer (Normal) painted white / 0.5 / 0.25 / black on a disc; roots in its core: 0 for black, else "
              "|measured / (m x lock density x skin) - 1| <= max(0.15, 2 / sqrt(N)) for all locks together AND for each "
              "lock on its own skin there")
        C.add("d1_roots_even_" + zname, _even(rows), {k: v.get("even") for k, v in rows.items()},
              "each lock with >= 30 roots in the core: clumped share <= its no-layer value there + %s; spacing ratio >= %s"
              % (EVEN_RISE, EVEN_SPACING))
    C.add("d1_all_removed_is_the_automatic_groom", rest_points()[0] == ref[0] and G.strands_by_lock() == BASE,
          {"strands": G.strands(), "automatic": sum(BASE.values())},
          "after all those layers were deleted: every rest point as when the check began, byte for byte, and the "
          "strands of every lock as the first cook's")


def d2_erase():
    """White on a disc, black painted over it (black overrides: no hair), then the eraser: the automatic groom."""
    rows = {}
    ref = rest_points()
    roots_ref = G.roots()
    for zname in ("crown_whorl", "most_stacked", "under_floating_mesh", "ordinary_hair_back_06", "top_of_head"):
        c = Z[zname]
        lid = _paint("white, black, erased", zname, 1.0)
        cook_all()
        core = _core(lid)
        white = sum(K.roots_in(core, G.roots())[0].values())
        K.paint_disc(lid, c, 1.3, value=0.0)                                     # black over the white
        cook_all()
        black, floating = _on_skin(core)
        value_black = float(ga.mask_values(node, lid)[0][ga.mask_values(node, lid)[1] >= 1.0].max())
        K.paint_disc(lid, c, 2.0, dab_r=0.5, erase=True, label="Erase mask")     # the eraser, wider than the paint
        s, locks, _r = cook_all()
        left = float(ga.mask_values(node, lid)[1].max())
        P, L = rest_points()
        r1, l1 = G.roots()
        same_roots = bool(r1.shape == roots_ref[0].shape and np.array_equal(l1, roots_ref[1])
                          and float(np.abs(r1 - roots_ref[0]).max()) == 0.0)
        rows[zname] = {"roots_in_the_core_white": white, "after_black_over_it": black,
                       "roots_floating_off_the_skin_not_counted": floating, "value_where_painted_black": value_black,
                       "coverage_left_after_erase": left, "roots_at_the_same_places": same_roots,
                       "every_point_equal_bytes": P == ref[0], "lock_ids_equal": bool(np.array_equal(L, ref[1])),
                       "locks_recooked_by_erase": len(locks)}
        ga.mask_remove(node, lid)
        cook_all()
    C.add("d2_black_overrides_and_erase_returns_the_automatic_groom",
          all(r["roots_in_the_core_white"] > 0 and r["after_black_over_it"] == 0 and r["value_where_painted_black"] == 0.0
              and r["coverage_left_after_erase"] == 0.0 and r["roots_at_the_same_places"] and r["every_point_equal_bytes"]
              and r["lock_ids_equal"] for r in rows.values()), rows,
          "5 kinds of skin: black painted over a white disc leaves no root on its core's skin (black is a value, not an "
          "eraser; a v0.1 start root floating over 0.1 cm off the skin is listed, not counted); after the eraser (wider than the disc) the layer has no coverage, every root is where the automatic "
          "groom has it (difference 0) and every rest point is equal byte for byte")


LAYER_ID0 = 10000000      # the layers' own strands are numbered from here (build_hda VEX_MASK_TAG)
TINY = 0.028


def d2_tiny():
    """A layer that covers 0.028 of the way (round 2: a leftover mask of 0.028 re-placed every root of two locks,
    points up to 20 mm away). Strands are followed by their id: a strand's number in its lock's automatic scatter."""
    rows = {}
    before = G.strands_by_id()
    for zname in ("ordinary_hair_back_06", "most_stacked", "crown_whorl"):
        lid = _paint("tiny", zname, 1.0, opacity=TINY)
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
        ga.mask_remove(node, lid)
        cook_all()
    ok = all(r["locks"] > 0 and r["share_gone"] <= TINY + 0.02 and r["automatic_strands_not_there_before"] == 0
             and r["a_kept_root_moved_cm"]["max"] <= 0.05 for r in rows.values())
    C.add("d2_a_tiny_mask_moves_no_root", ok, rows,
          "a white disc at opacity 0.028 (ordinary skin, stacked skin, the whorl), strands followed by id: no "
          "automatic strand appears, at most 0.028 + 0.02 of them are gone, and every kept root is within 0.05 cm of "
          "where it was (round 2: every root of the locks re-placed, up to 2 cm)",
          note="tips are reported: a kept strand's place across its lock is its rank among the lock's strands, "
               "so it shifts a little when a neighbour goes")


def d3_partial():
    """Partial coverage blends the automatic groom with the mask: density = automatic x (1 - e) + m x lock
    density x e, e = coverage x opacity (of the layer, or of the folder it is in)."""
    rows = {}
    for zname in ("ordinary_hair_back_06", "crown_whorl", "top_of_head"):
        for m in (1.0, 0.25):
            for e, how in ((0.25, "opacity"), (0.5, "opacity"), (0.75, "opacity"), (0.5, "folder opacity")):
                folder = ga.mask_add(node, "F", kind="folder", opacity=e) if how.startswith("folder") else None
                lid = _paint("part", zname, m, opacity=1.0 if folder is not None else e, parent=folder)
                cook_all()
                rows["%s m %s %s %.2f" % (zname, m, how, e)] = _grade(_core(lid), 1.0 - e, m * e)
                clear_layers()
    worst = max(rows.items(), key=lambda kv: abs((kv[1]["ratio"] or 1) - 1))
    C.add("d3_partial_coverage_follows_the_rule", _all(rows), {"worst": worst, "rows": rows},
          "ordinary skin, the whorl, the top of the head; white and 0.25; opacity 0.25 / 0.5 / 0.75 and a folder at "
          "0.5: |measured / (automatic x (1 - e) + m x lock density x e) - 1| <= max(0.15, 2 / sqrt(N)), all locks "
          "together and each lock")
    C.add("d3_partial_coverage_roots_even", _even(rows), {k: v.get("even") for k, v in rows.items()},
          "each lock with >= 30 roots in the core: clumped share <= its no-layer value there + %s" % EVEN_RISE)


def d4_soft_edge():
    rows = {}
    for zname, m in (("ordinary_hair_back_06", 1.0), ("ordinary_hair_back_06", 0.25), ("crown_whorl", 1.0),
                     ("top_of_head", 0.0)):
        c = Z[zname]
        lid = ga.mask_add(node, "soft")
        s = lib.gm_session(node, lid)
        s.dab(c / G.unit, None, 1.5, m, 1.0)          # one dab, soft over the whole radius
        s.commit()
        cook_all()
        cover = ga.mask_values(node, lid)[1].astype(float)
        lo, hi = K.prim_minmax(cover)
        d = np.sqrt(((K.cen - c) ** 2).sum(1))
        r1 = G.roots()
        rings = []
        for a, b in ((0.0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 1.2), (1.2, 1.5)):
            prims = np.nonzero((d >= a) & (d < b) & (K.nown > 0))[0]
            area = float(K.area[prims].sum())
            if area <= 0:
                continue
            cov = float(((lo[prims] + hi[prims]) * 0.5 * K.area[prims]).sum() / area)
            before = K.roots_in(prims, ROOTS0)[0]
            auto = sum(before.values()) / area
            got = sum(K.roots_in(prims, r1)[0].values()) / area
            full = m * sum(DENS[k] * K.lock_area_in(prims, k) for k in before) / area
            target = auto * (1.0 - cov) + full * cov
            lim = lib.density_limit(target * area, 1.0)
            rings.append({"ring_cm": [a, b], "coverage": r3(cov), "automatic": r3(auto), "m_x_lock_density": r3(full),
                          "target": r3(target), "measured": r3(got), "limit": r3(lim),
                          "pass": abs(got / max(target, 1e-9) - 1) <= lim,
                          "between": min(auto, full) * (1 - lim) - 1e-9 <= got <= max(auto, full) * (1 + lim)})
        rows["%s m %s" % (zname, m)] = rings
        ga.mask_remove(node, lid)
        cook_all()
    C.add("d4_soft_edge_follows_the_coverage", all(r["pass"] and r["between"] for rs in rows.values() for r in rs), rows,
          "one soft dab (radius 1.5 cm) of white, 0.25 or black: in each 0.3 cm ring the density is automatic x (1 - "
          "coverage) + m x lock density x coverage within max(0.15, 2 / sqrt(N)), and lies between the two sides (each "
          "widened by that same limit)")


# ---------------------------------------------------------------------------
# the layer model: blend modes, order, opacity, folders, fill layers, owners
# ---------------------------------------------------------------------------

BLEND_ZONES = ("crown_whorl", "top_of_head", "ordinary_hair_back_06")


def _formula(below, value, mode, effect=1.0):
    """The contract's own line, written here apart from logic.py: below + (blend - below) x effect, in 0..1."""
    blend = {"normal": value, "multiply": below * value, "add": below + value, "subtract": below - value,
             "min": min(below, value), "max": max(below, value)}[mode]
    return min(1.0, max(0.0, below + (blend - below) * effect))


def b1_blend_modes():
    """Each blend mode over painted skin: the cover against the formula, and the roots it grows."""
    for zname in BLEND_ZONES:
        rows = {}
        for mode, below, value, opacity in (("normal", 0.5, 0.25, 1.0), ("multiply", 0.5, 0.5, 1.0), ("add", 0.5, 0.25, 1.0),
                                            ("add", 0.75, 0.75, 1.0), ("subtract", 0.75, 0.5, 1.0),
                                            ("subtract", 0.25, 0.5, 1.0), ("min", 0.75, 0.25, 1.0), ("min", 0.25, 0.75, 1.0),
                                            ("max", 0.25, 1.0, 1.0), ("max", 0.75, 0.5, 1.0), ("multiply", 1.0, 0.5, 0.5),
                                            ("add", 0.25, 0.5, 0.5)):
            a = _paint("below", zname, below)
            b = _paint("top", zname, value, mode=mode, opacity=opacity)
            cook_all()
            core = np.intersect1d(_core(a), _core(b))
            keep, add = ga.mask_cover(node)
            pts = np.unique(np.concatenate([K.S["prim_points"][p] for p in core]))
            want = _formula(below, value, mode, opacity)
            err = max(float(np.abs(keep[pts]).max()), float(np.abs(add[pts] - want).max()))
            row = _grade(core, 0.0, want)
            row.update({"below": below, "value": value, "opacity": opacity, "formula_m": r3(want), "cover_error": err,
                        "pass": row["pass"] and err <= 1e-6})
            rows["%s %s over %s%s" % (mode, value, below, " at opacity %s" % opacity if opacity < 1 else "")] = row
            clear_layers()
        C.add("b1_blend_modes_over_painted_skin_" + zname, _all(rows), rows,
              "a paint layer in each mode over a painted layer (12 cases): the cover there equals below + (blend(below, "
              "value) - below) x opacity clamped to 0..1 (error <= 1e-6, no automatic root kept), and the roots are "
              "that m x lock density within max(0.15, 2 / sqrt(N)), all locks together and each lock")
        C.add("b1_blend_modes_roots_even_" + zname, _even(rows), {k: v.get("even") for k, v in rows.items()},
              "each lock with >= 30 roots in the core: clumped share <= its no-layer value there + %s" % EVEN_RISE)


def b2_modes_over_the_automatic_groom():
    """A layer over skin no lower layer covers: the automatic groom counts as 1. Multiply, Subtract and Min thin
    it (evenly); Add and Max cannot raise it and leave it as it is."""
    ref = rest_points()
    roots_ref = G.roots()
    for zname in BLEND_ZONES:
        rows = {}
        for mode, value, keep in (("subtract", 0.4, 0.6), ("min", 0.25, 0.25), ("multiply", 0.5, 0.5)):
            lid = _paint(mode, zname, value, mode=mode)
            cook_all()
            row = _grade(_core(lid), keep, 0.0)
            row["automatic_kept"] = keep
            rows["%s %s" % (mode, value)] = row
            clear_layers()
        same = {}
        for mode, value in (("add", 0.4), ("max", 0.4), ("multiply", 1.0), ("min", 1.0), ("subtract", 0.0)):
            lid = _paint(mode, zname, value, mode=mode)
            s, locks, _r = cook_all()
            r1, l1 = G.roots()
            same["%s %s" % (mode, value)] = {
                "roots_at_the_same_places": bool(r1.shape == roots_ref[0].shape and np.array_equal(l1, roots_ref[1])
                                                 and float(np.abs(r1 - roots_ref[0]).max()) == 0.0),
                "every_point_equal_bytes": rest_points()[0] == ref[0]}
            clear_layers()
        ok = _all(rows) and all(r["roots_at_the_same_places"] and r["every_point_equal_bytes"] for r in same.values())
        C.add("b2_modes_over_unpainted_skin_" + zname, ok, {"thinned": rows, "left_as_it_is": same},
              "Subtract 0.4, Min 0.25, Multiply 0.5 over the automatic groom: its roots x 0.6 / 0.25 / 0.5 within "
              "max(0.15, 2 / sqrt(N)), all locks together and each lock; Add 0.4, Max 0.4, Multiply 1, Min 1, "
              "Subtract 0: the automatic groom by root positions and byte for byte")
        C.add("b2_thinned_roots_even_" + zname, _even(rows), {k: v.get("even") for k, v in rows.items()},
              "each lock with >= 30 roots in the core: clumped share <= its no-layer value there + %s" % EVEN_RISE)


def b3_multiply_bounds():
    """Multiply's use: a top layer that bounds the region. 0 removes the hair, 1 keeps what is below."""
    ref = rest_points()
    roots_ref = G.roots()
    for zname in Z:
        rows = {}
        over_paint = zname in BLEND_ZONES or zname.startswith(("most_stacked", "lock_start"))
        for v in (0.0, 0.25, 0.5, 1.0):
            if over_paint and v != 0.25:
                a = _paint("painted white", zname, 1.0)
                b = _paint("bound", zname, v, mode="multiply")
                cook_all()
                rows["x %s over painted white" % v] = _grade(np.intersect1d(_core(a), _core(b)), 0.0, v)
                clear_layers()
            lid = _paint("bound", zname, v, mode="multiply")
            cook_all()
            row = _grade(_core(lid), v, 0.0)
            if v == 1.0:
                r1, l1 = G.roots()
                row["roots_at_the_same_places"] = bool(r1.shape == roots_ref[0].shape and np.array_equal(l1, roots_ref[1])
                                                       and float(np.abs(r1 - roots_ref[0]).max()) == 0.0)
                row["every_point_equal_bytes"] = rest_points()[0] == ref[0]
                row["pass"] = row["pass"] and row["roots_at_the_same_places"] and row["every_point_equal_bytes"]
            rows["x %s over unpainted skin" % v] = row
            clear_layers()
        C.add("b3_multiply_as_the_top_layer_" + zname, _all(rows), rows,
              "a Multiply paint layer at 0 / 0.5 / 1 over skin painted white (m x lock density: none, half, all) and at "
              "0 / 0.25 / 0.5 / 1 over unpainted skin (the automatic roots x that; at 1 the automatic groom byte for "
              "byte): within max(0.15, 2 / sqrt(N)), all locks together and each lock")
        C.add("b3_multiply_thins_evenly_" + zname, _even(rows), {k: v.get("even") for k, v in rows.items()},
              "each lock with >= 30 roots in the core: clumped share <= its no-layer value there + %s (rounds 1 and 2 "
              "measured 0.014 -> 0.616 at x 0.5 on the top of the head)" % EVEN_RISE)


def m1_compose():
    c = Z["ordinary_hair_back_06"]
    off = np.array([0.8, 0.0, 0.0])
    a = ga.mask_add(node, "A 0.3")
    b = ga.mask_add(node, "B x0.5", mode="multiply", opacity=0.6)
    f = ga.mask_add(node, "F", kind="folder", opacity=0.7)
    d = ga.mask_add(node, "D black", parent=f)
    ga.mask_add(node, "G + 0.2", mode="add", kind="fill", value=0.2, parent=f)
    e = ga.mask_add(node, "E off")
    for lid, centre, radius, soft, value in ((a, c, 1.2, 0.0, 0.3), (b, c + off, 1.2, 1.0, 0.5), (d, c - off, 1.0, 0.5, 0.0),
                                             (e, c, 2.0, 0.0, 1.0)):
        s = lib.gm_session(node, lid)
        s.dab(centre / G.unit, None, radius, value, soft)
        s.commit()
    ga.mask_set(node, e, on=False)
    keep, add = (x.astype(np.float64) for x in ga.mask_cover(node))
    (va, ca), (vb, cb), (vd, cd) = ((x.astype(np.float64) for x in ga.mask_values(node, i)) for i in (a, b, d))

    def stack(order, a_opacity=1.0):
        """The mask's value t (the automatic groom counts as 1) and the automatic share kept, bottom to top."""
        t = np.ones(len(va))
        k = np.ones(len(va))
        for name in order:
            if name == "a":
                e_ = ca * a_opacity
                t, k = t + (va - t) * e_, k * (1 - e_)
            elif name == "b":
                e_ = cb * 0.6
                t, k = t + (t * vb - t) * e_, k * (1 - e_ + e_ * vb)
            elif name == "f":
                ti = t + (vd - t) * cd                    # D, Normal
                ki = k * (1 - cd)
                ti = np.clip(ti + 0.2, 0.0, 1.0)          # G, a fill layer in Add: over all skin
                t, k = t + (ti - t) * 0.7, k + (ki - k) * 0.7
            t = np.clip(t, 0.0, 1.0)
        return t, k

    t, k = stack("abf")
    err = max(float(np.abs(keep + add - t).max()), float(np.abs(keep - k).max()))
    ga.mask_move(node, a, 5)                      # A to the top: Normal overrides what is below where it is painted
    keep2, add2 = (x.astype(np.float64) for x in ga.mask_cover(node))
    t2, k2 = stack("bfa")
    top = ca >= 1.0
    order_ok = bool(np.allclose(add2[top], 0.3, atol=1e-6) and np.allclose(keep2[top], 0.0, atol=1e-6)
                    and float(np.abs(keep2 + add2 - (keep + add)).max()) > 0.05
                    and max(float(np.abs(keep2 + add2 - t2).max()), float(np.abs(keep2 - k2).max())) <= 1e-5)
    ga.mask_set(node, a, opacity=0.0)
    keep3, add3 = (x.astype(np.float64) for x in ga.mask_cover(node))
    t3, k3 = stack("bf")
    op_err = max(float(np.abs(keep3 + add3 - t3).max()), float(np.abs(keep3 - k3).max()))
    clear_layers()
    C.add("m1_layers_order_opacity_folder_compose", err <= 1e-5 and order_ok and op_err <= 1e-5,
          {"max_error": err, "reorder_changes_the_result_and_the_top_normal_layer_wins": order_ok, "opacity_0_error": op_err,
           "points_covered": int((keep < 1).sum()), "points": len(keep)},
          "mask_cover (keep, add) of a Normal layer, a soft Multiply layer at opacity 0.6, a folder at 0.7 holding a "
          "soft black layer and an Add fill layer, and a layer that is off, against arithmetic written here (the "
          "mask's value by the contract's formula, the automatic share kept): max error <= 1e-5")


def m2_fill():
    """A fill layer: one value over all the skin of its owner; its value is changed without painting."""
    lk = G.lock_id("hair_back_14")
    prims = G.region_prims(lk)
    skin = K.lock_area_in(prims, lk)
    lid = ga.mask_add(node, "fill", kind="fill", value=1.0, scope="locks", locks=[lk])
    s0, locks0, _r = cook_all()
    white = G.strands_by_lock().get(lk, 0)
    n0 = len(hou.undos.undoLabels())
    ga.mask_set(node, lid, value=0.5)
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
    ga.mask_set(node, lid, value=0.0)
    cook_all()
    none = G.strands_by_lock().get(lk, 0)
    try:
        lib.gm_session(node, lid)
        refused = False
    except ValueError:
        refused = True
    # a paint layer never painted is transparent: changing its row regrows nothing
    empty = ga.mask_add(node, "never painted", mode="multiply")
    cook_all()
    ga.mask_set(node, empty, opacity=0.3)
    unpainted = cook_all()[1]
    clear_layers()
    want = DENS[lk] * skin
    lim, lim_half = lib.density_limit(want, 1.0), lib.density_limit(want * 0.5, 1.0)
    C.add("m2_fill_layer_one_value_over_its_owners_skin",
          locks0 == [lk] and locks == [lk] and abs(white / want - 1) <= lim and abs(half / (want * 0.5) - 1) <= lim_half
          and none == 0 and steps == 1 and us < UNDO_S and not ul and back == white and others and refused
          and unpainted == [] and s <= 0.2 * len(locks) + 0.1,
          {"lock": K.names[lk], "skin_cm2": r3(skin), "density": DENS[lk], "automatic_strands": BASE.get(lk),
           "strands_white_half_black": [white, half, none], "expected_white_half": [r3(want), r3(want * 0.5)],
           "limits": [r3(lim), r3(lim_half)], "locks_recooked": [K.names[k] for k in locks], "display_s": r3(s),
           "undo_steps": steps, "label": label, "undo_s": r3(us), "undo_locks": len(ul), "strands_after_undo": back,
           "other_locks_keep_their_strands": others, "painting_a_fill_layer_is_refused": refused,
           "a_never_painted_layers_row_change_recooks": len(unpainted)},
          "a fill layer owned by one lock: white gives that lock's Density x its skin, 0.5 half of it, black none "
          "(max(0.15, 2 / sqrt(N))); only that lock recooks, within the speed limit; the value change is one undo "
          "step, undone < 0.1 s with 0 locks; the brush refuses a fill layer; a paint layer never painted is transparent")


def m3_folder():
    ref = rest_points()
    lk = G.lock_id("hair_back_14")
    c = K.snap(K.cen[G.region_prims(lk)].mean(0))
    folder = ga.mask_add(node, "Folder", kind="folder")
    inner = _paint("0.5", c, 0.5, parent=folder)
    cook_all()
    core = _core(inner)
    full = _grade(core, 0.0, 0.5)
    strands_full = G.strands_by_lock()
    ga.mask_set(node, folder, opacity=0.5)
    cook_all()
    half = _grade(core, 0.5, 0.25)
    ga.mask_set(node, folder, opacity=0.0)
    cook_all()
    zero_equal = rest_points()[0] == ref[0]
    ga.mask_set(node, folder, opacity=1.0)
    ga.mask_set(node, folder, on=False)
    cook_all()
    off_equal = rest_points()[0] == ref[0]
    ga.mask_set(node, folder, on=True)
    cook_all()
    bytes_before = [x.tobytes() for x in ga.mask_values(node, inner)]
    ga.mask_remove(node, folder)
    data = ga.read_data(node)
    kept = (data.mask(inner) is not None and data.mask(inner).parent is None
            and [x.tobytes() for x in ga.mask_values(node, inner)] == bytes_before)
    cook_all()
    after_delete = G.strands_by_lock() == strands_full
    clear_layers()
    C.add("m3_folder_opacity_off_delete",
          full["pass"] and half["pass"] and zero_equal and off_equal and kept and after_delete,
          {"place": "hair_back_14", "in_a_folder_at_1": full, "folder_opacity_0.5": half,
           "folder_opacity_0_is_the_automatic_groom": zero_equal, "folder_off_is_the_automatic_groom": off_equal,
           "deleting_the_folder_keeps_its_layer_and_paint": kept, "and_the_layer_then_applies_as_before": after_delete},
          "a layer painted 0.5 in a folder on hair_back_14's skin gives 0.5 x lock density (round 2: 0.81 of the "
          "target); the folder at opacity 0.5: automatic x 0.5 + 0.25 x lock density; at 0, or off: the automatic "
          "groom byte for byte; deleting it keeps the layer")


def m4_owner():
    # the most stacked skin: one of its locks owns a black layer; a group owns a white one
    c = Z["most_stacked"]
    names = K.names
    pr = int(((K.cen - c) ** 2).sum(1).argmin())
    owners = list(K.own[pr])
    mine = owners[0]
    one = _paint("one lock bare", c, 0.0, radius=1.1, scope="locks", locks=[mine])   # a disc no other check paints
    s, locks, _r = cook_all()
    core = _core(one)
    b = K.roots_in(core, ROOTS0)[0]
    a = K.roots_in(core, G.roots())[0]
    others_same = all(G.strands_by_lock().get(k) == BASE.get(k) for k in BASE if k != mine)
    row1 = {"lock": names[mine], "its_roots_on_the_patch": [b.get(mine, 0), a.get(mine, 0)],
            "locks_recooked": [names[k] for k in locks], "other_locks_keep_their_strands": others_same}
    ok1 = a.get(mine, 0) == 0 and b.get(mine, 0) > 0 and locks == [mine] and others_same
    ga.mask_remove(node, one)
    cook_all()
    data = ga.read_data(node)
    group = data.lock(mine).group
    grp = _paint("group white", "ordinary_hair_back_06", 1.0, scope="group", group=group)
    s, locks, _r = cook_all()
    in_group = {lk.id for lk in data.locks if lk.group == group}
    core2 = _core(grp)
    area2 = float(K.area[core2].sum())
    b2 = K.roots_in(core2, ROOTS0)[0]
    a2 = K.roots_in(core2, G.roots())[0]
    on_patch = set(a2) | set(b2)
    want = sum(DENS[k] * K.lock_area_in(core2, k) for k in on_patch & in_group)
    got = sum(v for k, v in a2.items() if k in in_group)
    lim = lib.density_limit(want, 1.0)
    ok2 = (set(locks) <= in_group and all(a2.get(k, 0) == b2.get(k, 0) for k in on_patch - in_group)
           and abs(got / max(want, 1e-9) - 1) <= lim)
    row2 = {"group": group, "locks_recooked_in_the_group": set(locks) <= in_group, "group_roots": got, "expected": r3(want),
            "limit": r3(lim), "core_cm2": r3(area2), "locks_of_other_groups_on_the_patch": len(on_patch - in_group)}
    clear_layers()
    C.add("m4_a_layer_owned_by_a_lock_or_a_group", ok1 and ok2, {"lock": row1, "group": row2},
          "on stacked skin a black layer owned by one lock removes that lock's roots there and recooks it alone; a "
          "white layer owned by a group recooks only that group's locks, gives them their density on their skin and "
          "leaves the roots of other groups' locks as they were")


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
    a = ga.mask_add(node, "empty")
    same("a paint layer added, nothing painted", len(cook_all()[1]))
    b = ga.mask_add(node, "b", mode="multiply")
    f = ga.mask_add(node, "f", kind="folder")
    d = ga.mask_add(node, "d", parent=f)
    g = ga.mask_add(node, "g", kind="fill", value=0.5, parent=f)
    cook_all()
    ga.mask_set(node, g, on=False)
    for lid, z, v in ((a, "ordinary_hair_back_06", 1.0), (b, "crown_whorl", 0.5), (d, "top_of_head", 0.0)):
        K.paint_disc(lid, Z[z], 1.3, value=v)
    cook_all()
    rows["painted"] = {"changed": rest_points()[0] != ref[0]}
    for lid in (a, b, d):
        ga.mask_set(node, lid, on=False)
    cook_all()
    same("3 painted layers and a fill layer, all off")
    for lid in (a, b, d, g):
        ga.mask_set(node, lid, on=True)
    ga.mask_set(node, f, on=False)
    ga.mask_set(node, a, on=False)
    ga.mask_set(node, b, on=False)
    cook_all()
    same("the folder off (its paint and fill layers on)")
    ga.mask_set(node, g, on=False)
    for lid in (a, b, f):
        ga.mask_set(node, lid, on=True)
    for lid in (a, b, d):
        ga.mask_set(node, lid, opacity=0.0)
    cook_all()
    same("every layer at opacity 0")
    for lid in (a, b, d):
        ga.mask_set(node, lid, opacity=1.0)
    for lid, z in ((a, "ordinary_hair_back_06"), (b, "crown_whorl"), (d, "top_of_head")):
        K.paint_disc(lid, Z[z], 2.0, dab_r=0.5, erase=True, label="Erase mask")       # the eraser
    cook_all()
    same("every layer erased with the brush")
    rows["every layer erased with the brush"]["coverage_left_max"] = max(float(ga.mask_values(node, x)[1].max()) for x in (a, b, d))
    for lid, z in ((a, "ordinary_hair_back_06"), (b, "crown_whorl")):
        K.paint_disc(lid, Z[z], 1.3)
    cook_all()
    for lid in (a, b, d):
        ga.mask_clear(node, lid)
    cook_all()
    same("mask_clear on every layer")
    clear_layers()
    same("every layer deleted")
    ok = rows["painted"]["changed"] and all(r.get("points_equal", True) and r.get("ids_equal", True) for r in rows.values())
    C.add("r1_no_layer_off_unpainted_is_the_automatic_groom_byte_for_byte", ok, rows,
          "in one process, against the groom cooked before any layer: every rest point's bytes and every lock id",
          note="black is a value now (no hair), so \"all black\" of the first brief is \"nothing painted / erased\" here")


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
    factor = round(5104.0 / before, 3)
    a = ga.mask_add(node, "Crown x %s" % factor, mode="multiply")
    K.paint_disc(a, Z["crown_whorl"], 2.0, value=factor)
    b = ga.mask_add(node, "Thin skin white")
    K.paint_disc(b, Z["under_floating_mesh"], 2.0)
    cook_all()
    r = G.roots()
    thin = _grade(_core(b), 0.0, 1.0)
    crown = lib.disc_density(r[0], spot, 1.0)
    infos = {i.id: i for i in ga.lock_infos(node)}
    now = G.strands_by_lock()
    hip = OUT + "/painted.hiplc"
    hou.hipFile.save(hip)
    clear_layers()
    row = {"crown_densest_1cm_disc_per_cm2": [r3(before), r3(crown)], "v006": 5104, "multiply": factor,
           "thin_skin": thin, "strands": sum(now.values())}
    C.add("q1_crown_down_to_v006_and_thin_skin_up",
          abs(crown / 5104.0 - 1) <= 0.15 and thin["pass"] and thin["measured_per_cm2"] > thin["automatic_per_cm2"], row,
          "Multiply 5104 / automatic on the crown whorl: the densest 1 cm disc within 15 % of 5,104 / cm2; white on "
          "skin under floating mesh: the locks' own density there within max(0.15, 2 / sqrt(N)), above the automatic")
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
          "grooming-check on the groom with the crown thinned to v006's density and thin skin painted white",
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


# ---------------------------------------------------------------------------
# persistence: Detect, Update regions, save / reopen, publish, migration, a missing lock
# ---------------------------------------------------------------------------

def _stack():
    lk = G.lock_id("hair_back_14")
    data = ga.read_data(node)
    _paint("All 0.8", "ordinary_hair_back_06", 0.8)
    f = ga.mask_add(node, "Folder", kind="folder", opacity=0.7)
    b = ga.mask_add(node, "Soft 0.3", parent=f)
    s = lib.gm_session(node, b)
    s.dab(Z["top_of_head"] / G.unit, None, 1.5, 0.3, 1.0)
    s.commit()
    o = _paint("Off", "crown_whorl", 1.0, radius=1.0)
    ga.mask_set(node, o, on=False)
    one = _paint("Lock B bare", K.snap(K.cen[G.region_prims(lk)].mean(0)), 0.0, radius=1.5, scope="locks", locks=[lk])
    group = data.lock(G.lock_id("hair_bang_08")).group
    _paint("Group x0.5", next(k for k in Z if k.startswith("fringe_")), 0.5, radius=1.0, mode="multiply", scope="group",
           group=group, opacity=0.5)
    ga.mask_add(node, "Fringe fill", kind="fill", mode="min", value=0.9, scope="group", group=group)
    cook_all()
    return lk, one


def _snapshot():
    data = ga.read_data(node)
    return ([dict(m.__dict__) for m in data.masks],
            {(m.id, n): x for m in data.masks for n, x in zip("va", lib.mask_arrays(node, m.id))}, G.strands_by_lock())


def _same(a, b):
    masks = all((x is None) == (y is None) and (x is None or np.array_equal(x, y))
                for x, y in ((a[1].get(k), b[1].get(k)) for k in set(a[1]) | set(b[1])))
    return {"layers": a[0] == b[0], "masks": masks, "strands": a[2] == b[2]}


def p1_persist():
    lk, one = _stack()
    ref = _snapshot()
    rows = {"layers": len(ref[0]), "strands": sum(ref[2].values())}
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
        rows["reopen_in_a_new_process"]["stored_schema"] == model.SCHEMA and not got.get("errors")
    C.add("p1_layers_survive_detect_regions_save_reopen", ok, rows,
          "7 layers (a folder with opacity, a soft painted layer, a layer off, one owned by a lock, a Multiply layer and a "
          "Min fill layer owned by a group): the layer "
          "list, every layer's painted values and coverage (bytes) and the strands of every lock are the same after Detect, after Update regions, and "
          "in a new process after save / reopen (schema %d)" % model.SCHEMA)
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
    return lk, one


def p3_orphan(lk, one):
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
    core = _core(one)
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
        core = _core(one)
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
              and row["its_roots_on_its_painted_skin_before"] == 0 and row["layer_still_names_it"])
    blast.destroy()
    C.add("p3_a_layer_owned_by_a_lock_follows_it_through_a_mesh_version", ok, row,
          "the hair mesh loses lock B (missing, its layer kept), gets it back (a new lock id): until reassigned the new "
          "lock grows on the skin painted black for B; after reassigning the missing lock to it, it grows none there")


def p4_migration():
    """Dev files of the earlier builds: schema 3 (blend modes, factor and density fill layers under a mask, paint
    layers) and schema 4 (\"= D\" layers)."""
    clear_layers()
    keep = _paint("Old paint", "ordinary_hair_back_06", 0.5)
    x = _paint("Old x0.5", "top_of_head", 1.0)
    y = _paint("Old + 40", "crown_whorl", 1.0, radius=1.0)
    z = _paint("Old x2", "most_stacked", 1.0, radius=1.0)
    cook_all()
    core_keep, core_x = _core(keep), _core(x)
    geo = hou.Geometry(node.parm(config.MASK_PARM).evalAsGeometry())
    for lid in (x, y, z):                                     # a fill layer of schema 3 stored its mask only
        geo.findPointAttrib(config.MASK_VALUE_ATTR % lid).destroy()
    node.parm(config.MASK_PARM).set(geo)
    raw = json.loads(node.evalParm(config.DATA_PARM))
    raw["schema"] = 3
    for m in raw["masks"]:
        m["unit"] = "factor"
        if m["id"] == keep:
            m.update(kind="paint", mode="replace")
        elif m["id"] == x:
            m.update(kind="fill", mode="multiply", value=0.5)
        elif m["id"] == y:
            m.update(kind="fill", mode="add", unit="density", value=40.0)
        else:
            m.update(kind="fill", mode="multiply", value=2.0)
    node.parm(config.DATA_PARM).set(json.dumps(raw))
    err = None
    try:
        cook_all()
    except hou.Error as e:
        err = str(e)
    data = ga.read_data(node)
    said = ga.mask_dropped(node)
    kept = [(m.name, m.kind, m.mode, m.value) for m in data.masks]
    paint = _grade(core_keep, 0.0, 0.5, evenness=False)       # the paint layer: its painted 0.5, Normal
    half = _grade(core_x, 0.5, 0.0, evenness=False)           # the factor fill 0.5 under its mask: Multiply 0.5 there
    # the dropped layers no longer change the hair
    ring = np.nonzero(np.sqrt(((K.cen - Z["crown_whorl"]) ** 2).sum(1)) < 0.8)[0]
    crown_roots = sum(K.roots_in(ring, G.roots())[0].values())
    crown_auto = sum(K.roots_in(ring, ROOTS0)[0].values())
    hip = OUT + "/schema3.hiplc"
    hou.hipFile.save(hip)
    outf = OUT + "/reopen_schema3.json"
    text = hython([HERE + "/accept_v02a_sub.py", "reopen", SUITE, hip, outf, HERE], "reopen_schema3.log")
    got2 = json.load(open(outf, encoding="utf-8")) if os.path.isfile(outf) else {"error": "no file"}
    status = [ln for ln in text.splitlines() if "density layer" in ln and "dropped" in ln]
    ga.mask_set(node, keep, opacity=0.9)                      # the next edit writes the JSON at the current schema
    stored = json.loads(node.evalParm(config.DATA_PARM))
    names = ["Old paint", "Old x0.5"]
    row = {"layers_kept": kept, "said": said, "cook_error": err, "errors": lib.node_errors(node),
           "paint_layer_0.5": paint, "factor_0.5_fill_is_multiply_0.5_under_its_mask": half,
           "dropped_layers_change_nothing_on_the_crown": [crown_auto, crown_roots],
           "reopen": {"stored_schema": got2.get("stored_schema"), "layers": [m["name"] for m in got2.get("layers", [])],
                      "dropped": got2.get("dropped"), "errors": got2.get("errors"), "error": got2.get("error"),
                      "status_line": status[:1], "traceback_in_output": "Traceback (most recent call last)" in text},
           "after_the_next_edit": {"schema": stored.get("schema"), "layers": [m["name"] for m in stored["masks"]],
                                   "said": ga.mask_dropped(node)}}
    ok = (err is None and not row["errors"] and [k[0] for k in kept] == names
          and kept[0][1:3] == ("paint", "normal") and kept[1][1:] == ("paint", "multiply", 0.5)
          and "2 density layers" in said and "Old + 40" in said and "Old x2" in said and paint["pass"] and half["pass"]
          and crown_roots == crown_auto
          and got2.get("stored_schema") == 3 and row["reopen"]["layers"] == names and not got2.get("errors")
          and not got2.get("error") and bool(status) and not row["reopen"]["traceback_in_output"]
          and stored.get("schema") == model.SCHEMA and row["after_the_next_edit"]["layers"] == names
          and row["after_the_next_edit"]["said"] == "")
    clear_layers()
    C.add("p4_schema_3_dev_file_migrates", ok, row,
          "a schema 3 groom_data: a paint layer in \"replace\" stays (Normal, its painted 0.5 gives 0.5 x lock density); "
          "a fill layer of factor 0.5 in Multiply becomes a paint layer of 0.5 under its mask (the automatic roots x "
          "0.5 there); a fill layer in strands / cm2 and one of factor 2 are dropped and named (mask_dropped; OnLoaded's "
          "status line in a new process, no traceback) and change nothing; the next edit stores schema %d" % model.SCHEMA)
    # schema 4: the "= D strands / cm2" layers of the build before this one
    a = _paint("= 120", "ordinary_hair_back_06", 1.0)
    f = ga.mask_add(node, "Kept folder", kind="folder", opacity=0.5)
    cook_all()
    raw = json.loads(node.evalParm(config.DATA_PARM))
    raw["schema"] = 4
    for m in raw["masks"]:
        m.pop("mode", None)
        if m["id"] == a:
            m.update(kind="fill", value=120.0)
    node.parm(config.DATA_PARM).set(json.dumps(raw))
    err4 = None
    try:
        cook_all()
    except hou.Error as e:
        err4 = str(e)
    data = ga.read_data(node)
    said4 = ga.mask_dropped(node)
    r1, l1 = G.roots()
    auto = bool(r1.shape == ROOTS0[0].shape and np.array_equal(l1, ROOTS0[1]) and float(np.abs(r1 - ROOTS0[0]).max()) == 0.0)
    new = ga.mask_add(node, "after")
    row4 = {"layers_kept": [(m.name, m.kind) for m in data.masks if m.id != new], "said": said4, "cook_error": err4,
            "errors": lib.node_errors(node), "the_groom_is_the_automatic_one": auto, "next_layer_id": new,
            "dropped_id": a}
    clear_layers()
    C.add("p4_schema_4_dev_file_drops_its_density_layers",
          err4 is None and not row4["errors"] and row4["layers_kept"] == [("Kept folder", "folder")] and "= 120" in said4
          and auto and new > max(a, f), row4,
          "a schema 4 groom_data (\"= 120 strands / cm2\" under a mask, a folder): the density layer is dropped and "
          "named, the folder stays, the groom is the automatic one by root positions, and a new layer never takes the "
          "dropped layer's id")
    with open(OUT + "/schema99.txt", "w", encoding="utf-8") as fh:
        try:
            model.GroomData.from_json(json.dumps({"schema": 99}))
            fh.write("no error")
        except ValueError as e:
            fh.write(str(e))


STEPS = [("s1", s1_stroke_speed), ("u1", u1_undo_chain), ("u2", u2_undo_chain_whorl), ("u3", u3_low_limit),
         ("u4", u4_deformed_output), ("u5", u5_usage), ("d1", d1_density), ("d2", d2_erase), ("d2t", d2_tiny),
         ("d3", d3_partial), ("d4", d4_soft_edge), ("b1", b1_blend_modes), ("b2", b2_modes_over_the_automatic_groom),
         ("b3", b3_multiply_bounds), ("m1", m1_compose), ("m2", m2_fill), ("m3", m3_folder),
         ("m4", m4_owner), ("r1", r1_states), ("r2", r2_counts), ("r3", r3_qc), ("q1", q1_painted_qc),
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
        pair = p1_persist()
        p3_orphan(*pair)
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
