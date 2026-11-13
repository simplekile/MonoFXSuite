"""Acceptance of MONO Grooming v0.2a density layers, the core (docs/plans/grooming_v0_2.md, "Done when").

    hython accept_v02a.py <suite> <scene> <out_dir> [--v01 <v0.1 suite>] [--ref <approved groom.usd>]
                          [--t55 <qc_report.json of the v0.1 end-to-end test>] [--only id,id] [--strokes 30]

<scene> is a copy of the Helen grooming scene (it stays in the sandbox). Everything is written under <out_dir>:
accept.json ({item, pass, value, limit, evidence} per check, `passed`), accept_log.txt, and the files of the
checks that run in a process of their own (QC, full-cook timing, reopen). Hython's exit code is not reliable:
read the JSON. Run it with no other Houdini cooking: the speed limits are absolute.

Round 3: one kind of layer, "= D strands / cm2". Every density check is graded on several kinds of skin
(whorl, top of the head, a lock's start, the most stacked skin, skin under floating mesh, fringe, ordinary,
the sliver band by the ear) at D = 0, 40, 120, 300, with roots of ALL locks counted in the core of a painted
disc; limits are the plan's, never tuned to a result."""
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
from tools.fx.grooming import config, logic, model  # noqa: E402

HYTHON = os.path.join(hou.expandString("$HFS"), "bin", "hython.exe" if os.name == "nt" else "hython").replace("\\", "/")
QC = SUITE + "/.claude/skills/grooming-check/scripts/qc_metrics.py"
DENSITIES = (0.0, 40.0, 120.0, 300.0)
EVEN_CLUMPED = 0.10     # a lock's roots in a painted patch: clumped share on its own skin (a random pattern: 0.25)
EVEN_SPACING = 0.45     # ... and spacing ratio, grooming-check's root_spacing_low limit
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
    lid = ga.mask_add(node, "speed", value=120.0)
    cook_all()
    places = [("hair_base_12", None), ("crown_whorl", c), ("hair_back_06", None), ("hair_bang_08", None),
              ("hair_base_05", None), ("hair_back_14", None), ("hair_bang_17", None), ("hair_base_01", None)]
    rows = []
    for name, centre in places:
        for k in range(3):
            path = K.disc_path(K.snap(centre), 0.06 * k) if centre is not None else K.region_path(name, shift=0.06 * k)
            c0 = ga.mask_cover(node)
            ga.mask_stroke(node, lid, path, radius_cm=0.8, level=1.0)
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
    lid = ga.mask_add(node, place, value=120.0)
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
        ga.mask_stroke(node, lid, K.disc_path(Z[place], 0.05 * i), radius_cm=radius, level=1.0 if i % 3 else 0.6)
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
# painted D gives D
# ---------------------------------------------------------------------------

def _patch(lid, level=1.0, atol=1e-6):
    """(core prims, area, {lock: roots before}, after: counts, positions, lock ids) of the painted disc."""
    core = K.core(ga.mask_values(node, lid), level, atol=atol)
    area = float(K.area[core].sum())
    b = K.roots_in(core, ROOTS0)[0]
    a, ra, la = K.roots_in(core, G.roots())
    return core, area, b, a, ra, la


def d1_density():
    ref = rest_points()
    for zname, c in Z.items():
        rows, even = {}, {}
        for D in DENSITIES:
            lid = ga.mask_add(node, "= %d" % D, value=D)
            K.paint_disc(lid, c, 1.3)
            s, locks, _r = cook_all()
            core, area, b, a, ra, la = _patch(lid)
            tb, ta = sum(b.values()), sum(a.values())
            lim = lib.density_limit(D, area) if D else 0.0
            ratio = ta / area / D if D else None
            rows["= %d" % D] = {"core_cm2": r3(area), "before_per_cm2": r3(tb / area), "after_per_cm2": r3(ta / area),
                                "measured_over_D": r3(ratio), "limit": r3(lim), "locks_on_core": len(set(b) | set(a)),
                                "pass": (ta == 0) if not D else abs(ratio - 1) <= lim,
                                "display_s": r3(s), "locks": len(locks)}
            if D:
                per = lib.lock_even(ra, la, K, core)
                even["= %d" % D] = {"all_locks": {k: r3(v) for k, v in lib.spacing_stats(ra, area).items()}, "per_lock": per,
                                    "pass": all(v.get("clumped", 0) <= EVEN_CLUMPED and v.get("spacing_ratio", 1) >= EVEN_SPACING
                                                for v in per.values())}
            ga.mask_remove(node, lid)
            cook_all()
        C.add("d1_painted_D_gives_D_" + zname, all(r["pass"] for r in rows.values()), rows,
              "roots of all locks / cm2 in the disc's core: 0 for D = 0, else |measured / D - 1| <= max(0.15, 2 / sqrt(D x area))")
        C.add("d1_roots_even_" + zname, all(r["pass"] for r in even.values()), even,
              "each lock with >= 30 roots in the core: clumped share <= %s and spacing ratio >= %s on its own skin there"
              % (EVEN_CLUMPED, EVEN_SPACING),
              note="all locks together on stacked skin are near a random pattern (0.25), as the automatic groom is there")
    C.add("d1_all_removed_is_the_automatic_groom", rest_points()[0] == ref[0] and G.strands_by_lock() == BASE,
          {"strands": G.strands(), "automatic": sum(BASE.values())},
          "after all those layers were deleted: every rest point as when the check began, byte for byte, and the "
          "strands of every lock as the first cook's")


def d2_black():
    """White "= 300" on a disc, then black painted over it with the brush: the automatic groom by root positions."""
    rows = {}
    ref = rest_points()
    roots_ref = G.roots()
    for zname in ("crown_whorl", "most_stacked", "under_floating_mesh", "ordinary_hair_back_06", "top_of_head"):
        c = Z[zname]
        lid = ga.mask_add(node, "white then black", value=300.0)
        K.paint_disc(lid, c, 1.3)
        cook_all()
        changed = rest_points()[0] != ref[0]
        K.paint_disc(lid, c, 2.0, level=0.0, dab_r=0.5, label="Paint mask")          # black, wider than the white
        s, locks, _r = cook_all()
        left = float(ga.mask_values(node, lid).max())
        P, L = rest_points()
        r1, l1 = G.roots()
        same_roots = bool(r1.shape == roots_ref[0].shape and np.array_equal(l1, roots_ref[1])
                          and float(np.abs(r1 - roots_ref[0]).max()) == 0.0)
        rows[zname] = {"white_changed_the_groom": changed, "mask_left_max": left, "roots_at_the_same_places": same_roots,
                       "every_point_equal_bytes": P == ref[0], "lock_ids_equal": bool(np.array_equal(L, ref[1])),
                       "locks_recooked_by_black": len(locks)}
        ga.mask_remove(node, lid)
        cook_all()
    C.add("d2_black_paint_returns_the_automatic_groom", all(r["white_changed_the_groom"] and r["roots_at_the_same_places"]
                                                         and r["every_point_equal_bytes"] and r["lock_ids_equal"]
                                                         for r in rows.values()), rows,
          "5 kinds of skin: after black is painted over the white disc with the brush (soft, wider than the disc), "
          "every root is where the automatic groom has it (difference 0), and every rest point byte for byte")


def _nearest(a, b):
    """For each of `a` (n, 3) the distance to the nearest of `b` (m, 3); inf when `b` is empty."""
    if not len(b):
        return np.full(len(a), np.inf)
    out = np.empty(len(a))
    for i in range(0, len(a), 400):
        out[i:i + 400] = np.sqrt(((a[i:i + 400, None, :] - b[None, :, :]) ** 2).sum(-1).min(1))
    return out


def d2_tiny():
    """A leftover mask of 0.028 (round 2: it re-placed every root of two locks, points up to 20 mm away)."""
    rows = {}
    r0, l0 = G.roots()
    counts0 = G.strands_by_lock()
    for zname in ("ordinary_hair_back_06", "most_stacked", "crown_whorl"):
        lid = ga.mask_add(node, "tiny", value=300.0)
        K.paint_disc(lid, Z[zname], 1.3, level=0.028)
        s, locks, _r = cook_all()
        r1, l1 = G.roots()
        kept = gone = new = 0
        far = 0.0
        for k in locks:
            a, b = r0[l0 == k], r1[l1 == k]
            near = _nearest(a, b)
            here = near <= 0.01                         # cm: the same root (a root's own float noise is 0.002)
            kept += int(here.sum())
            gone += int((~here).sum())
            new += int((_nearest(b, a) > 0.01).sum())
            far = max(far, float(near[here].max()) if here.any() else 0.0)
        total0 = int(sum((l0 == k).sum() for k in locks))
        now = G.strands_by_lock()
        rows[zname] = {"locks": len(locks), "roots_before": total0, "roots_at_the_same_place": kept, "roots_gone": gone,
                       "roots_new_the_layers": new, "share_gone": r3(gone / max(total0, 1)),
                       "a_kept_root_moved_at_most_cm": round(far, 5),
                       "strands": [int(sum(counts0[k] for k in locks)), int(sum(now.get(k, 0) for k in locks))]}
        ga.mask_remove(node, lid)
        cook_all()
    ok = all(r["share_gone"] <= 0.028 + 0.02 and r["roots_at_the_same_place"] + r["roots_gone"] == r["roots_before"]
             and r["a_kept_root_moved_at_most_cm"] <= 0.01 for r in rows.values())
    C.add("d2_a_tiny_mask_moves_no_root", ok, rows,
          "mask 0.028 of a \"= 300\" layer on a disc (ordinary skin, stacked skin, the whorl): every root of the locks "
          "under it is at its place (within 0.01 cm) or gone, at most 0.028 + 0.02 of them gone; the new roots are "
          "the layer's own")


def d3_grey():
    rows = {}
    for zname in ("ordinary_hair_back_06", "crown_whorl", "top_of_head"):
        for D in (40.0, 300.0):
            for cov, how in ((0.25, "mask"), (0.5, "mask"), (0.75, "mask"), (0.5, "opacity")):
                lid = ga.mask_add(node, "grey", value=D, opacity=cov if how == "opacity" else 1.0)
                level = 1.0 if how == "opacity" else cov
                K.paint_disc(lid, Z[zname], 1.3, level=level)
                cook_all()
                core, area, b, a, _ra, _la = _patch(lid, level, atol=1e-4)
                auto = sum(b.values()) / area
                target = auto + (D - auto) * cov
                got = sum(a.values()) / area
                lim = lib.density_limit(target, area)
                rows["%s = %d %s %.2f" % (zname, D, how, cov)] = {
                    "automatic": r3(auto), "target": r3(target), "measured": r3(got), "ratio": r3(got / target),
                    "limit": r3(lim), "pass": abs(got / target - 1) <= lim}
                ga.mask_remove(node, lid)
                cook_all()
    C.add("d3_grey_mask_or_opacity_follows_the_rule", all(r["pass"] for r in rows.values()),
          {"worst": max(rows.items(), key=lambda kv: abs(kv[1]["ratio"] - 1)), "rows": rows},
          "ordinary skin, the whorl, the top of the head; D = 40, 300; mask 0.25 / 0.5 / 0.75 and opacity 0.5: "
          "|measured / (automatic + (D - automatic) x coverage) - 1| <= max(0.15, 2 / sqrt(N))")


def d4_soft_edge():
    rows = {}
    for zname, D in (("ordinary_hair_back_06", 40.0), ("ordinary_hair_back_06", 300.0), ("crown_whorl", 40.0)):
        c = Z[zname]
        lid = ga.mask_add(node, "soft", value=D)
        s = lib.gm_session(node, lid)
        s.dab(c / G.unit, None, 1.5, 1.0, level=1.0)          # one dab, soft over the whole radius
        s.commit()
        cook_all()
        mask = ga.mask_values(node, lid).astype(float)
        lo, hi = K.prim_minmax(mask)
        d = np.sqrt(((K.cen - c) ** 2).sum(1))
        r1 = G.roots()
        rings = []
        for a, b in ((0.0, 0.3), (0.3, 0.6), (0.6, 0.9), (0.9, 1.2), (1.2, 1.5)):
            prims = np.nonzero((d >= a) & (d < b) & (K.nown > 0))[0]
            area = float(K.area[prims].sum())
            if area <= 0:
                continue
            cov = float(((lo[prims] + hi[prims]) * 0.5 * K.area[prims]).sum() / area)
            auto = sum(K.roots_in(prims, ROOTS0)[0].values()) / area
            got = sum(K.roots_in(prims, r1)[0].values()) / area
            target = auto + (D - auto) * cov
            lim = lib.density_limit(target, area)
            rings.append({"ring_cm": [a, b], "coverage": r3(cov), "automatic": r3(auto), "target": r3(target),
                          "measured": r3(got), "limit": r3(lim), "pass": abs(got / max(target, 1e-9) - 1) <= lim,
                          "between": min(auto, D) * 0.85 <= got <= max(auto, D) * 1.15})
        rows["%s = %d" % (zname, D)] = rings
        ga.mask_remove(node, lid)
        cook_all()
    C.add("d4_soft_edge_follows_the_mask", all(r["pass"] and r["between"] for rs in rows.values() for r in rs), rows,
          "one soft dab (radius 1.5 cm): in each 0.3 cm ring the density is automatic + (D - automatic) x the ring's "
          "coverage within max(0.15, 2 / sqrt(N)), and lies between the two sides")


# ---------------------------------------------------------------------------
# the layer model: order, opacity, folders, owners, a layer's number
# ---------------------------------------------------------------------------

def m1_compose():
    c = Z["ordinary_hair_back_06"]
    off = np.array([0.8, 0.0, 0.0])
    a = ga.mask_add(node, "A = 40", value=40.0)
    b = ga.mask_add(node, "B = 300", value=300.0, opacity=0.6)
    f = ga.mask_add(node, "F", kind="folder", opacity=0.7)
    d = ga.mask_add(node, "D = 0", value=0.0, parent=f)
    e = ga.mask_add(node, "E off", value=999.0)
    for lid, centre, radius, soft in ((a, c, 1.2, 0.0), (b, c + off, 1.2, 1.0), (d, c - off, 1.0, 0.5), (e, c, 2.0, 0.0),
                                      (f, c - off, 0.7, 1.0)):
        s = lib.gm_session(node, lid)
        s.dab(centre / G.unit, None, radius, soft, level=0.0 if lid == f else 1.0)
        s.commit()
    ga.mask_set(node, e, on=False)
    keep, add = ga.mask_cover(node)
    ma, mb, md, mf = (ga.mask_values(node, x).astype(np.float64) for x in (a, b, d, f))
    # our own arithmetic, bottom to top: A, then B at 0.6, then the folder (D inside) through its mask x 0.7
    k = 1.0 - ma
    ad = 40.0 * ma
    eb = mb * 0.6
    k, ad = k * (1 - eb), ad * (1 - eb) + 300.0 * eb
    ki, ai = k * (1 - md), ad * (1 - md) + 0.0 * md
    ef = mf * 0.7
    k, ad = k + (ki - k) * ef, ad + (ai - ad) * ef
    err = max(float(np.abs(keep - k).max()), float(np.abs(add - ad).max() / 300.0))
    ga.mask_move(node, a, 4)                      # A to the top: it wins where it is white
    keep2, add2 = ga.mask_cover(node)
    top = ma >= 1.0
    order_ok = bool(np.allclose(add2[top], 40.0, atol=1e-3) and np.allclose(keep2[top], 0.0, atol=1e-6)
                    and float(np.abs(add2 - add).max()) > 1.0)
    ga.mask_set(node, a, opacity=0.0)
    keep3, add3 = ga.mask_cover(node)
    k0 = (1 - eb)
    a0 = 300.0 * eb
    ki, ai = k0 * (1 - md), a0 * (1 - md)
    k0, a0 = k0 + (ki - k0) * ef, a0 + (ai - a0) * ef
    op_err = max(float(np.abs(keep3 - k0).max()), float(np.abs(add3 - a0).max() / 300.0))
    clear_layers()
    C.add("m1_layers_order_opacity_folder_compose", err <= 1e-5 and order_ok and op_err <= 1e-5,
          {"max_error": err, "reorder_changes_the_result_and_the_top_layer_wins": order_ok, "opacity_0_error": op_err,
           "points_covered": int((keep < 1).sum())},
          "mask_cover (keep, add) of 3 layers + a folder with its own soft mask and opacity + a layer that is off, "
          "against arithmetic written here: max error <= 1e-5")


def m2_value():
    c = Z["ordinary_hair_back_06"]
    lid = ga.mask_add(node, "number", value=123.0)
    K.paint_disc(lid, c, 1.3)
    cook_all()
    core, area, b, a, _ra, _la = _patch(lid)
    before = sum(a.values()) / area
    under = sorted(set(a) | set(b))
    n0 = len(hou.undos.undoLabels())
    c0 = ga.mask_cover(node)
    ga.mask_set(node, lid, value=317.0)        # a density no other check paints here (the cache would hold it)
    steps = len(hou.undos.undoLabels()) - n0
    label = hou.undos.undoLabels()[0]
    c1 = ga.mask_cover(node)
    s, locks, _r = cook_all()
    after = sum(K.roots_in(core, G.roots())[0].values()) / area
    owners = K.owners_of_changed(c0, c1)
    t = time.perf_counter()
    hou.undos.performUndo()
    node.cook()
    us = time.perf_counter() - t
    ul = CC.take()
    G.rest.cook()
    back = sum(K.roots_in(core, G.roots())[0].values()) / area
    # a layer whose mask is black: changing its number regrows nothing
    black = ga.mask_add(node, "black", value=50.0)
    cook_all()
    ga.mask_set(node, black, value=500.0)
    none = cook_all()[1]
    clear_layers()
    lim = lib.density_limit(317.0, area)
    C.add("m2_a_layers_density_is_changed_without_painting",
          steps == 1 and locks == owners and abs(after / 317.0 - 1) <= lim and us < UNDO_S and not ul
          and abs(back - before) < 1e-9 and none == [] and s <= 0.2 * len(locks) + 0.1,
          {"undo_steps": steps, "label": label, "per_cm2": [r3(before), r3(after), r3(back)], "limit": r3(lim),
           "locks_recooked": len(locks), "locks_owning_skin_under_the_mask": len(owners), "display_s": r3(s),
           "limit_s": round(0.2 * len(locks) + 0.1, 2), "undo_s": r3(us), "undo_locks": len(ul),
           "black_mask_value_change_recooks": len(none), "locks_on_core": len(under)},
          "120 -> 317 on a painted layer: one undo step, only the locks under its mask recook (within the speed "
          "limit), the density follows, undo < 0.1 s with 0 locks and the density back; a black mask: 0 locks")


def m3_folder():
    ref = rest_points()
    lk = G.lock_id("hair_back_14")
    c = K.snap(K.cen[G.region_prims(lk)].mean(0))
    folder = ga.mask_add(node, "Folder", kind="folder")
    inner = ga.mask_add(node, "= 40", value=40.0, parent=folder)
    K.paint_disc(inner, c, 1.3)
    cook_all()
    core, area, b, a, ra, la = _patch(inner)
    white = sum(a.values()) / area
    lim = lib.density_limit(40.0, area)
    strands_white = G.strands_by_lock()
    ga.mask_set(node, folder, opacity=0.5)
    cook_all()
    half = sum(K.roots_in(core, G.roots())[0].values()) / area
    auto = sum(b.values()) / area
    target = auto + (40.0 - auto) * 0.5
    lim_half = lib.density_limit(target, area)
    ga.mask_set(node, folder, opacity=1.0)
    K.paint_disc(folder, c, 2.2, level=0.0, dab_r=0.5)          # the folder's own mask black over the patch
    cook_all()
    black_equal = rest_points()[0] == ref[0]
    ga.mask_clear(node, folder)                                  # no folder mask again: white
    cook_all()
    ga.mask_set(node, folder, on=False)
    cook_all()
    off_equal = rest_points()[0] == ref[0]
    ga.mask_set(node, folder, on=True)
    cook_all()
    bytes_before = ga.mask_values(node, inner).tobytes()
    ga.mask_remove(node, folder)
    data = ga.read_data(node)
    kept = (data.mask(inner) is not None and data.mask(inner).parent is None
            and ga.mask_values(node, inner).tobytes() == bytes_before)
    cook_all()
    after_delete = G.strands_by_lock() == strands_white
    clear_layers()
    C.add("m3_folder_mask_opacity_off_delete",
          abs(white / 40.0 - 1) <= lim and abs(half / target - 1) <= lim_half and black_equal and off_equal and kept
          and after_delete,
          {"place": "hair_back_14", "core_cm2": r3(area), "locks_on_core": len(set(a) | set(b)),
           "in_a_white_folder_per_cm2": r3(white), "over_D": r3(white / 40.0), "limit": r3(lim),
           "folder_opacity_0.5": {"automatic": r3(auto), "target": r3(target), "measured": r3(half), "limit": r3(lim_half)},
           "folder_mask_black_is_the_automatic_groom": black_equal, "folder_off_is_the_automatic_groom": off_equal,
           "deleting_the_folder_keeps_its_layer_and_mask": kept, "and_the_layer_then_applies_as_before": after_delete},
          "\"= 40\" in a white folder on hair_back_14's skin gives 40 (round 2: 0.81); the folder at opacity 0.5 the rule; "
          "its mask black, or the folder off: the automatic groom byte for byte; deleting it keeps the layer")


def m4_owner():
    # the most stacked skin: one of its locks owns a layer "= 0", a group owns "= 300"
    c = Z["most_stacked"]
    names = K.names
    pr = int(((K.cen - c) ** 2).sum(1).argmin())
    owners = list(K.own[pr])
    mine = owners[0]
    one = ga.mask_add(node, "one lock = 0", value=0.0, scope="locks", locks=[mine])
    K.paint_disc(one, c, 1.3)
    s, locks, _r = cook_all()
    core, area, b, a, _ra, _la = _patch(one)
    others_same = all(G.strands_by_lock().get(k) == BASE.get(k) for k in BASE if k != mine)
    row1 = {"lock": names[mine], "its_roots_on_the_patch": [b.get(mine, 0), a.get(mine, 0)], "locks_recooked": [names[k] for k in locks],
            "other_locks_keep_their_strands": others_same}
    ok1 = a.get(mine, 0) == 0 and b.get(mine, 0) > 0 and locks == [mine] and others_same
    ga.mask_remove(node, one)
    cook_all()
    data = ga.read_data(node)
    group = data.lock(mine).group
    grp = ga.mask_add(node, "group = 300", value=300.0, scope="group", group=group)
    K.paint_disc(grp, Z["ordinary_hair_back_06"], 1.3)
    s, locks, _r = cook_all()
    in_group = {lk.id for lk in data.locks if lk.group == group}
    core2, area2, b2, a2, _ra, _la = _patch(grp)
    on_patch = {k for k in set(a2) | set(b2)}
    got = sum(v for k, v in a2.items() if k in in_group) / area2
    lim = lib.density_limit(300.0, area2)
    ok2 = set(locks) <= in_group and all(a2.get(k, 0) == b2.get(k, 0) for k in on_patch - in_group)
    row2 = {"group": group, "locks_recooked_in_the_group": set(locks) <= in_group, "group_roots_per_cm2": r3(got),
            "limit": r3(lim), "locks_of_other_groups_on_the_patch": len(on_patch - in_group)}
    if not (on_patch - in_group):
        ok2 = ok2 and abs(got / 300.0 - 1) <= lim
    clear_layers()
    C.add("m4_a_layer_owned_by_a_lock_or_a_group", ok1 and ok2, {"lock": row1, "group": row2},
          "on stacked skin a layer \"= 0\" owned by one lock removes that lock's roots there and recooks it alone; a "
          "layer owned by a group recooks only that group's locks (and gives D where they hold the skin alone)")


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
    c = Z["ordinary_hair_back_06"]
    a = ga.mask_add(node, "empty", value=300.0)
    same("a layer added, mask black", len(cook_all()[1]))
    b = ga.mask_add(node, "b", value=0.0)
    f = ga.mask_add(node, "f", kind="folder")
    d = ga.mask_add(node, "d", value=40.0, parent=f)
    for lid, z in ((a, "ordinary_hair_back_06"), (b, "crown_whorl"), (d, "top_of_head")):
        K.paint_disc(lid, Z[z], 1.3)
    cook_all()
    rows["painted"] = {"changed": rest_points()[0] != ref[0]}
    for lid in (a, b, d):
        ga.mask_set(node, lid, on=False)
    cook_all()
    same("3 painted layers, all off")
    for lid in (a, b, d):
        ga.mask_set(node, lid, on=True)
    ga.mask_set(node, f, on=False)
    ga.mask_set(node, a, on=False)
    ga.mask_set(node, b, on=False)
    cook_all()
    same("the folder off (its layer on)")
    for lid in (a, b, f):
        ga.mask_set(node, lid, on=True)
    for lid, z in ((a, "ordinary_hair_back_06"), (b, "crown_whorl"), (d, "top_of_head")):
        K.paint_disc(lid, Z[z], 2.0, level=0.0, dab_r=0.5)         # black with the brush
    cook_all()
    same("every mask painted black with the brush")
    rows["every mask painted black with the brush"]["mask_left_max"] = max(float(ga.mask_values(node, x).max()) for x in (a, b, d))
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
    C.add("r1_no_layer_off_black_is_the_automatic_groom_byte_for_byte", ok, rows,
          "in one process, against the groom cooked before any layer: every rest point's bytes and every lock id")


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
    a = ga.mask_add(node, "Crown = 5104", value=5104.0)
    K.paint_disc(a, Z["crown_whorl"], 2.0)
    b = ga.mask_add(node, "Thin skin = 150", value=150.0)
    K.paint_disc(b, Z["under_floating_mesh"], 2.0)
    cook_all()
    r = G.roots()
    core = K.core(ga.mask_values(node, b), 1.0)
    area = float(K.area[core].sum())
    thin0 = sum(K.roots_in(core, ROOTS0)[0].values()) / area
    thin1 = sum(K.roots_in(core, r)[0].values()) / area
    crown = lib.disc_density(r[0], spot, 1.0)
    infos = {i.id: i for i in ga.lock_infos(node)}
    now = G.strands_by_lock()
    hip = OUT + "/painted.hiplc"
    hou.hipFile.save(hip)
    clear_layers()
    row = {"crown_densest_1cm_disc_per_cm2": [r3(before), r3(crown)], "v006": 5104,
           "thin_skin_per_cm2": [r3(thin0), r3(thin1)], "painted": 150, "thin_core_cm2": r3(area),
           "strands": sum(now.values())}
    lim = lib.density_limit(150.0, area)
    C.add("q1_crown_down_to_v006_and_thin_skin_up", abs(crown / 5104.0 - 1) <= 0.15 and abs(thin1 / 150.0 - 1) <= lim, row,
          "\"= 5104\" on the crown whorl: the densest 1 cm disc within 15 % of 5,104 / cm2; \"= 150\" on skin under "
          "floating mesh: within max(0.15, 2 / sqrt(N)) of 150")
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
          "grooming-check on the groom painted \"= 5104\" on the crown and \"= 150\" on thin skin",
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
    c = Z["ordinary_hair_back_06"]
    data = ga.read_data(node)
    a = ga.mask_add(node, "All = 120", value=120.0)
    K.paint_disc(a, c, 1.3)
    f = ga.mask_add(node, "Folder", kind="folder", opacity=0.7)
    b = ga.mask_add(node, "Soft = 40", value=40.0, parent=f)
    s = lib.gm_session(node, b)
    s.dab(Z["top_of_head"] / G.unit, None, 1.5, 1.0)
    s.commit()
    o = ga.mask_add(node, "Off = 999", value=999.0)
    K.paint_disc(o, Z["crown_whorl"], 1.0)
    ga.mask_set(node, o, on=False)
    one = ga.mask_add(node, "Lock B = 0", value=0.0, scope="locks", locks=[lk])
    K.paint_disc(one, K.snap(K.cen[G.region_prims(lk)].mean(0)), 1.5)
    grp = ga.mask_add(node, "Group = 200", value=200.0, scope="group", group=data.lock(G.lock_id("hair_bang_08")).group, opacity=0.5)
    K.paint_disc(grp, Z[next(k for k in Z if k.startswith("fringe_"))], 1.0)
    cook_all()
    return lk, one


def _snapshot():
    data = ga.read_data(node)
    return ([dict(m.__dict__) for m in data.masks],
            {m.id: lib.mask_arrays(node, m.id)[1] for m in data.masks}, G.strands_by_lock())


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
          "6 layers (a folder with opacity, a soft mask, a layer off, one owned by a lock, one by a group): the layer "
          "list, every mask's bytes and the strands of every lock are the same after Detect, after Update regions, and "
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
                    "read_back_masks_same": all(np.array_equal(
                        np.frombuffer(mgeo.pointFloatAttribValuesAsString(config.MASK_COVER_ATTR % k), np.float32), v)
                        for k, v in ref[1].items() if v is not None) if mgeo is not None else False,
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
    core = K.core(ga.mask_values(node, one), 1.0)
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
        core = K.core(ga.mask_values(node, one), 1.0)
        row["roots_of_the_new_lock_on_the_painted_skin_before_reassign"] = K.roots_in(core, G.roots())[0].get(new, 0)
        d = ga.read_data(node)
        moved = d.reassign_orphan(lk, new)                      # what the panel's reassign does (controller.reassign_orphan)
        ga.write_data(node, d, "reassign orphan")
        cook_all()
        row["layers_moved"] = moved
        row["layer_now_owned_by"] = ga.read_data(node).mask(one).locks
        row["roots_of_the_new_lock_on_the_painted_skin_after_reassign"] = K.roots_in(core, G.roots())[0].get(new, 0)
        ok = (moved == ["Lock B = 0"] and row["layer_now_owned_by"] == [new]
              and row["roots_of_the_new_lock_on_the_painted_skin_before_reassign"] > 0
              and row["roots_of_the_new_lock_on_the_painted_skin_after_reassign"] == 0
              and row["its_roots_on_its_painted_skin_before"] == 0 and row["layer_still_names_it"])
    blast.destroy()
    C.add("p3_a_layer_owned_by_a_lock_follows_it_through_a_mesh_version", ok, row,
          "the hair mesh loses lock B (missing, its layer kept), gets it back (a new lock id): until reassigned the new "
          "lock grows on the skin painted \"= 0\" for B; after reassigning the missing lock to it, it grows none there")


def p4_migration():
    """A dev file of the earlier builds (schema 3, blend modes, factor and paint layers)."""
    clear_layers()
    c = Z["ordinary_hair_back_06"]
    keep = ga.mask_add(node, "Keep = 80", value=80.0)
    K.paint_disc(keep, c, 1.3)
    x = ga.mask_add(node, "Old x0.5", value=1.0)
    K.paint_disc(x, Z["top_of_head"], 1.3)
    y = ga.mask_add(node, "Old + 40", value=40.0)
    K.paint_disc(y, Z["crown_whorl"], 1.0)
    cook_all()
    want = None
    raw = json.loads(node.evalParm(config.DATA_PARM))
    raw["schema"] = 3
    for m in raw["masks"]:
        if m["id"] == keep:
            m.update(mode="replace", unit="density")
        elif m["id"] == x:
            m.update(mode="multiply", unit="factor", value=0.5)
        else:
            m.update(mode="add", unit="density")
    raw["masks"].append({"id": 77, "name": "Old paint", "kind": "paint", "mode": "max", "value": 1.0, "unit": "factor",
                         "on": True, "opacity": 1.0, "scope": "all", "group": "", "locks": [], "parent": None})
    node.parm(config.DATA_PARM).set(json.dumps(raw))
    err = None
    try:
        cook_all()
    except hou.Error as e:
        err = str(e)
    data = ga.read_data(node)
    said = ga.mask_dropped(node)
    core, area, b, a, _ra, _la = _patch(keep)
    got = sum(a.values()) / area
    lim = lib.density_limit(80.0, area)
    # the dropped layers no longer change the hair: only the kept layer's locks differ from the automatic groom
    P, L = rest_points()
    crown_roots = sum(K.roots_in(np.nonzero(np.sqrt(((K.cen - Z["crown_whorl"]) ** 2).sum(1)) < 0.8)[0], G.roots())[0].values())
    crown_auto = sum(K.roots_in(np.nonzero(np.sqrt(((K.cen - Z["crown_whorl"]) ** 2).sum(1)) < 0.8)[0], ROOTS0)[0].values())
    hip = OUT + "/schema3.hiplc"
    hou.hipFile.save(hip)
    outf = OUT + "/reopen_schema3.json"
    text = hython([HERE + "/accept_v02a_sub.py", "reopen", SUITE, hip, outf, HERE], "reopen_schema3.log")
    got2 = json.load(open(outf, encoding="utf-8")) if os.path.isfile(outf) else {"error": "no file"}
    status = [ln for ln in text.splitlines() if "density layer" in ln and "dropped" in ln]
    n0 = len(hou.undos.undoLabels())
    ga.mask_set(node, keep, value=81.0)                       # the next edit writes the JSON at the current schema
    stored = json.loads(node.evalParm(config.DATA_PARM))
    row = {"layers_kept": [m.name for m in data.masks], "said": said, "cook_error": err, "errors": lib.node_errors(node),
           "kept_layer_per_cm2": r3(got), "painted": 80, "limit": r3(lim),
           "dropped_layers_change_nothing_on_the_crown": [crown_auto, crown_roots],
           "reopen": {"stored_schema": got2.get("stored_schema"), "layers": [m["name"] for m in got2.get("layers", [])],
                      "dropped": got2.get("dropped"), "errors": got2.get("errors"), "error": got2.get("error"),
                      "status_line": status[:1], "traceback_in_output": "Traceback (most recent call last)" in text},
           "after_the_next_edit": {"schema": stored.get("schema"), "layers": [m["name"] for m in stored["masks"]],
                                   "said": ga.mask_dropped(node)}}
    ok = (err is None and not row["errors"] and row["layers_kept"] == ["Keep = 80"] and "3 density layers" in said
          and "Old x0.5" in said and abs(got / 80.0 - 1) <= lim and crown_roots == crown_auto
          and got2.get("stored_schema") == 3 and row["reopen"]["layers"] == ["Keep = 80"] and not got2.get("errors")
          and not got2.get("error") and bool(status) and not row["reopen"]["traceback_in_output"]
          and stored.get("schema") == model.SCHEMA and row["after_the_next_edit"]["layers"] == ["Keep = 80"]
          and row["after_the_next_edit"]["said"] == "")
    clear_layers()
    C.add("p4_dev_file_with_removed_layer_kinds_opens", ok, row,
          "a schema 3 groom_data with a multiply, an add and a paint layer beside a \"= 80\" layer: it cooks without an "
          "error, the three are dropped and named (mask_dropped; OnLoaded's status line in a new process, no traceback), "
          "the \"= 80\" layer still gives 80, and the next edit stores schema %d" % model.SCHEMA)
    with open(OUT + "/schema99.txt", "w", encoding="utf-8") as fh:
        try:
            model.GroomData.from_json(json.dumps({"schema": 99}))
            fh.write("no error")
        except ValueError as e:
            fh.write(str(e))


STEPS = [("s1", s1_stroke_speed), ("u1", u1_undo_chain), ("u2", u2_undo_chain_whorl), ("u3", u3_low_limit),
         ("u4", u4_deformed_output), ("u5", u5_usage), ("d1", d1_density), ("d2", d2_black), ("d2t", d2_tiny),
         ("d3", d3_grey), ("d4", d4_soft_edge), ("m1", m1_compose), ("m2", m2_value), ("m3", m3_folder),
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
