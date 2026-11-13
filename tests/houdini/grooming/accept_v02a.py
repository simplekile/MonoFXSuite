"""Acceptance of MONO Grooming v0.2a (density masks), the part hython can check.

    hython accept_v02a.py <suite> <scene.hiplc> <out_dir>
           [--v01-qc <qc_report.json of v0.1>]      strand counts v0.1 grew on this scene (t55)
           [--qc-now <qc_report.json>]              grooming-check on this suite's groom without a layer
           [--v01-time <fullcook.json>]             this script run with --time-only on the v0.1 suite
           [--time-only]                            only time the full cook (works on a v0.1 suite too)

It turns the plan's "Done when" list of v0.2a (docs/plans/grooming_v0_2.md) and rungs 2, 3, 5, 6 of the test
ladder into checks and writes `<out_dir>/accept.json`: {item, pass, value, limit, evidence} per check and
`passed`. Hython's exit code is not reliable (it segfaults on exit): read the JSON. The scene is loaded, never
saved over; the groom is made fresh first (every parm at its default, Detect, Update regions), since a scene
keeps the parm values it was saved with. Rung 7 (the brush in the viewport) is accept_v02a_gui.py.

Check ids: dw1..dw5 are the "Done when" items in the plan's order, ns1..ns5 its "Not sure yet" items, r2..r6
the ladder's rungs, api_* the adapter functions, fl_* the fill layers, masks and folders of the Substance
Painter model (the dw / ns checks paint "paint" layers, the first build's kind, which stays)."""

from __future__ import annotations

import json
import os
import sys
import time

SUITE, SCENE, OUT = (a.replace("\\", "/") for a in sys.argv[1:4])
sys.path.insert(0, SUITE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _opt(name: str) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


os.makedirs(OUT, exist_ok=True)
if os.path.isfile(OUT + "/accept_crash.txt"):
    os.remove(OUT + "/accept_crash.txt")

import hou  # noqa: E402
import numpy as np  # noqa: E402

import accept_lib as lib  # noqa: E402

SPEED_PER_LOCK_S, SPEED_BASE_S = 0.2, 0.1      # the plan: at most 0.2 s per lock recooked, plus 0.1 s
UNDO_LIMIT_S = 0.1
FULL_COOK_OVER_V01 = 1.10
SPACING_LOW, CLUMPED_HIGH = 0.45, 0.05         # grooming-check's root_spacing_low / root_clumped limits
ZONE_LOCK = "hair_back_06"                     # a lock whose roots sit on the skin (t57)
V006_CROWN = 5104.0                            # roots / cm2 on the approved groom's densest 1 cm disc


def time_full_cook(ga, node, runs: int = 3) -> dict:
    """Cold cook of the whole groom (output 1 at rest, every lock through the loop), `runs` times."""
    rest = node.node("GROOM_REST")
    keys = node.node("groom_keys")
    times = []
    for _ in range(runs):
        ga.hair_cache().drop_node(node.sessionId())
        t = time.perf_counter()
        keys.cook(force=True)          # the keys again: every lock now misses the cache
        rest.cook()
        times.append(time.perf_counter() - t)
        if len(node.node("groom_to_cook").geometry().iterPrims()) < 2:
            raise RuntimeError("the full cook did not go through the loop")
    return {"runs_s": [round(t, 3) for t in times], "min_s": round(min(times), 3),
            "median_s": round(sorted(times)[len(times) // 2], 3),
            "strands": rest.geometry().intrinsicValue("primitivecount")}


def main() -> None:
    ga, node = lib.open_scene(SUITE, SCENE)
    lib.fresh(ga, node)
    if "--time-only" in sys.argv:
        res = time_full_cook(ga, node, runs=5)
        res.update(suite=SUITE, scene=SCENE, lib=node.type().definition().libraryFilePath())
        with open(OUT + "/fullcook.json", "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        return

    from apps.houdini import grooming_masks as gm
    from tools.fx.grooming import config, logic

    C = lib.Checks(OUT, "accept.json", {"suite": SUITE, "scene": SCENE, "part": "v0.2a",
                                        "lib": node.type().definition().libraryFilePath(),
                                        "houdini": hou.applicationVersionString(),
                                        "args": sys.argv[4:]})
    G = lib.Groom(ga, node)
    S: dict = {"G": G}

    def data():
        return ga.read_data(node)

    def cook_both():
        d = S["G"].cook_display()
        r = S["G"].cook_rest()
        return d, r

    def clear_layers():
        for m in list(data().masks):
            ga.mask_remove(node, m.id)

    # ------------------------------------------------------------------ rung 2 / regression: no layer
    def no_layer():
        cold_d = G.cook_display()
        cold_r = G.cook_rest()
        S["cold"] = {"display_s": round(cold_d["s"], 2), "rest_s": round(cold_r["s"], 2)}
        errs = lib.node_errors(node)
        C.add("r2_node_no_errors", not errs, {"errors": errs[:5], "warnings": lib.node_warnings(node), **S["cold"]},
              "no error on the node or inside it", note="cold cook of 61 locks, display then output 1")
        S["base_by_lock"] = G.strands_by_lock()
        S["base_strands"] = cold_r["strands"]
        qc = _opt("--v01-qc")
        if qc and os.path.isfile(qc):
            ref = json.load(open(qc, encoding="utf-8"))
            names = G.lock_names()
            ours = {names[k]: v for k, v in S["base_by_lock"].items()}
            theirs = {r["name"]: r["strands"] for r in ref["locks"]}
            diff = {n: (ours.get(n), theirs.get(n)) for n in sorted(set(ours) | set(theirs)) if ours.get(n) != theirs.get(n)}
            C.add("dw4_no_layer_strands_as_v01", cold_r["strands"] == ref["ours"]["strands"] and not diff,
                  {"strands": cold_r["strands"], "v01_strands": ref["ours"]["strands"], "locks": len(ours),
                   "locks_that_differ": diff}, "equal, lock by lock", evidence=qc)
        else:
            C.add("dw4_no_layer_strands_as_v01", False, None, "needs --v01-qc <qc_report.json of v0.1>")
        now = _opt("--qc-now")
        if qc and now and os.path.isfile(qc) and os.path.isfile(now):
            a = {c["check"]: c for c in json.load(open(now, encoding="utf-8"))["checks"]}
            b = {c["check"]: c for c in json.load(open(qc, encoding="utf-8"))["checks"]}
            off = {}
            for k in sorted(b):
                va, vb = a.get(k, {}).get("value"), b[k]["value"]
                # two cooks of the same lock differ by up to 0.1 mm, so the numbers move a little
                if va is None or abs(va - vb) > max(0.1 * abs(vb), 0.02):
                    off[k] = (va, vb)
            passed_now = json.load(open(now, encoding="utf-8"))["passed"]
            C.add("r3_qc_numbers_as_v01", not off and passed_now,
                  {"checks": len(b), "off": off, "qc_passed": passed_now}, "each within 10 % or 0.02 of v0.1's",
                  evidence=now)
        else:
            C.add("r3_qc_numbers_as_v01", False, None, "needs --qc-now and --v01-qc")
        # an empty layer, and a painted layer switched off, are still the v0.1 groom and regrow nothing
        lid = ga.mask_add(node, kind="paint", name="empty")
        d, r = cook_both()
        ok = not d["locks"] and not r["locks"] and r["strands"] == S["base_strands"]
        prims = G.region_prims(G.lock_id(ZONE_LOCK))[:400]
        G.paint_prims(lid, prims, 0.0)
        ga.mask_set(node, lid, on=False)
        d2, r2 = cook_both()
        C.add("dw4_empty_or_off_layer_changes_nothing",
              ok and r2["strands"] == S["base_strands"] and G.strands_by_lock() == S["base_by_lock"],
              {"after_add": {"display_locks": d["locks"], "rest_locks": r["locks"], "strands": r["strands"]},
               "painted_then_off": {"strands": r2["strands"]}}, "0 locks regrown by the add; strand counts as before")
        clear_layers()
        cook_both()

    # ------------------------------------------------------------------ dw1: 0 removes, 2 doubles, even
    def zones():
        L = G.lock_id(ZONE_LOCK)
        s = G.scalp()
        prims = G.region_prims(L)
        cen = s["cen_cm"][prims]
        c0 = cen.mean(0)
        axis = np.linalg.svd(cen - c0, full_matrices=False)[2][0]
        proj = (cen - c0) @ axis
        half_a, half_b = prims[proj < np.median(proj)], prims[proj >= np.median(proj)]
        # the half with more skin is the one painted (Helen's other half is a patch of tiny polygons)
        if s["area"][half_a].sum() > s["area"][half_b].sum():
            half_a, half_b = half_b, half_a
        S["zone"] = {"L": L, "a": half_a, "b": half_b}
        roots0 = G.roots()
        lid = ga.mask_add(node, kind="paint", name="zones")
        S["zone_layer"] = lid

        def inner(value):
            lo, hi = G.prim_factor(ga.mask_factor(node).astype(float))
            return G.inner_prims((lo == value) & (hi == value), 0.3)

        def own_area(pr):
            return float(sum(s["area"][p] / max(len(s["owners"][p]), 1) for p in pr))

        # ---- painted 0: every root under it is gone, of every lock
        G.paint_prims(lid, half_b, 0.0)
        d, r = cook_both()
        in_a = inner(0.0)
        before, _ = G.roots_on(in_a, roots0)
        after, _ = G.roots_on(in_a)
        C.add("dw1_painted_0_removes_every_root", after == 0 and before > 100,
              {"roots_before": before, "roots_after": after, "prims": len(in_a),
               "area_cm2": round(float(s["area"][in_a].sum()), 2), "locks_recooked": len(d["locks"]),
               "cook_s": round(d["s"], 2)}, "0 roots left (all locks), where there were over 100")
        hou.undos.performUndo()
        # ---- painted 2: twice the roots, still even
        G.paint_prims(lid, half_b, 2.0)
        cook_both()
        in_b = inner(2.0)
        b_all, _ = G.roots_on(in_b, roots0)
        a_all, _ = G.roots_on(in_b)
        b_own, rb = G.roots_on(in_b, roots0, lock_id=L)
        a_own, ra = G.roots_on(in_b, lock_id=L)
        ratio = a_own / max(b_own, 1)
        C.add("dw1_painted_2_doubles_the_roots", 1.85 <= ratio <= 2.15 and b_own > 100,
              {"lock": ZONE_LOCK, "roots_before": b_own, "roots_after": a_own, "ratio": round(ratio, 3),
               "all_locks_before": b_all, "all_locks_after": a_all, "all_locks_ratio": round(a_all / max(b_all, 1), 3),
               "prims": len(in_b)}, "ratio 1.85 - 2.15 on a lock whose roots sit on the skin",
              note="all locks on that skin are reported beside it: a lock floating over it follows ns1's rule")
        st2 = lib.spacing_stats(ra, own_area(in_b))
        st0 = lib.spacing_stats(rb, own_area(in_b))
        C.add("dw1_roots_even_where_painted_2",
              st2.get("spacing_ratio", 0) >= SPACING_LOW and st2.get("clumped", 1) <= CLUMPED_HIGH,
              {"painted_2": st2, "before": st0}, f"spacing >= {SPACING_LOW}, clumped <= {CLUMPED_HIGH} (grooming-check)")
        hou.undos.performUndo()
        # ---- painted 0.5: half of them, evenly (not in patches)
        G.paint_prims(lid, half_b, 0.5)
        cook_both()
        in_h = inner(0.5)
        b_own, _ = G.roots_on(in_h, roots0, lock_id=L)
        a_own, rh = G.roots_on(in_h, lock_id=L)
        sth = lib.spacing_stats(rh, own_area(in_h))
        ratio = a_own / max(b_own, 1)
        C.add("dw1_painted_half_halves_evenly",
              0.42 <= ratio <= 0.58 and sth.get("spacing_ratio", 0) >= SPACING_LOW and sth.get("clumped", 1) <= CLUMPED_HIGH,
              {"roots_before": b_own, "roots_after": a_own, "ratio": round(ratio, 3), "painted_half": sth},
              f"ratio 0.42 - 0.58, spacing >= {SPACING_LOW}, clumped <= {CLUMPED_HIGH}")
        hou.undos.performUndo()
        # ---- a soft dab: the roots follow the brush's falloff (the relax does not flatten its edge)
        mid = s["cen_cm"][half_b[len(half_b) // 2]]
        ga.mask_stroke(node, lid, [mid / G.unit], radius_cm=1.5, value=0.0, soft=1.0)
        cook_both()
        f = ga.mask_factor(node).astype(float)
        r0, l0 = roots0
        r1, l1 = G.roots()
        d0 = np.sqrt(((r0[l0 == L] - mid) ** 2).sum(1))
        d1 = np.sqrt(((r1[l1 == L] - mid) ** 2).sum(1))
        dp = np.sqrt(((s["P_cm"] - mid) ** 2).sum(1))
        rings, worst = [], 0.0
        for lo, hi in ((0, 0.5), (0.5, 0.9), (0.9, 1.2), (1.2, 1.5), (1.5, 2.2)):
            n0, n1 = int(((d0 >= lo) & (d0 < hi)).sum()), int(((d1 >= lo) & (d1 < hi)).sum())
            sel = (dp >= lo) & (dp < hi)
            mean = float(f[sel].mean()) if sel.any() else 1.0
            rings.append({"ring_cm": [lo, hi], "roots_before": n0, "roots_after": n1,
                          "ratio": round(n1 / max(n0, 1), 3), "mask_mean": round(mean, 3)})
            if n0 >= 30:
                worst = max(worst, abs(n1 / n0 - mean))
        C.add("dw1_soft_edge_is_followed", worst <= 0.2, {"rings": rings, "worst_off": round(worst, 3)},
              "roots per ring / before within 0.2 of the factor's mean on the ring")
        hou.undos.performUndo()
        cook_both()

    # ------------------------------------------------------------------ dw3: a stroke, its cost, its undo
    def strokes():
        lid = S["zone_layer"]
        s = G.scalp()
        names = G.lock_names()
        grows = {lk.id for lk in data().locks if not lk.excluded}
        rows, ok_set, ok_speed = [], True, True
        picks = [ZONE_LOCK, "hair_bang_08", "hair_base_05", "hair_back_14", "hair_base_12", "hair_bang_17"]
        picks = [p for p in picks if p in names.values()]
        for i, name in enumerate(picks):
            pr = G.region_prims(G.lock_id(name))
            cen = s["cen_cm"][pr]
            start = cen[len(cen) // 2]
            end = cen[min(len(cen) - 1, len(cen) // 2 + 40)]
            path = [(start + (end - start) * t) / G.unit for t in np.linspace(0, 1, 10)]
            f0 = ga.mask_factor(node)
            t = time.perf_counter()
            ga.mask_stroke(node, lid, path, radius_cm=(1.0, 0.5, 1.5)[i % 3], value=(0.0, 2.0, 0.5)[i % 3])
            write_s = time.perf_counter() - t
            f1 = ga.mask_factor(node)
            changed = np.zeros(len(f0), dtype=bool)
            changed[f0 != f1] = True
            touched = np.unique(s["vprim"][changed[s["vpoint"]]])
            under = sorted({o for p in touched for o in s["owners"][p]} & grows)
            d = G.cook_display()
            limit = SPEED_PER_LOCK_S * len(d["locks"]) + SPEED_BASE_S
            rows.append({"on": name, "points_changed": int(changed.sum()), "locks_under": len(under),
                         "locks_recooked": len(d["locks"]), "same_locks": d["locks"] == under,
                         "write_s": round(write_s, 3), "cook_s": round(d["s"], 3), "limit_s": round(limit, 2)})
            ok_set &= d["locks"] == under and len(under) > 0
            ok_speed &= d["s"] <= limit
        S["stroke_rows"] = rows
        C.add("dw3_stroke_recooks_only_the_locks_under_it", ok_set and len(rows) >= 4,
              {"strokes": rows}, "locks through the loop == locks owning skin whose factor changed")
        C.add("dw3_stroke_speed", ok_speed, {"strokes": [{k: r[k] for k in ("on", "locks_recooked", "cook_s", "limit_s")}
                                                          for r in rows]},
              f"display cook <= {SPEED_PER_LOCK_S} s x locks + {SPEED_BASE_S} s (rung 5)")
        # ---- undo: exactly that stroke, fast, nothing regrown
        G.cook_rest()
        pr = G.region_prims(G.lock_id(ZONE_LOCK))
        p0 = s["cen_cm"][pr[len(pr) // 3]] / G.unit
        before = lib.mask_arrays(node, lid)
        ga.mask_stroke(node, lid, [p0, p0 + 0.004], radius_cm=1.0, value=0.0)
        after = lib.mask_arrays(node, lid)
        d = G.cook_display()
        times, exact, regrown = [], True, []
        for _ in range(3):
            t = time.perf_counter()
            hou.undos.performUndo()
            du = G.cook_display()
            times.append(time.perf_counter() - t)
            exact &= lib.same_arrays(lib.mask_arrays(node, lid), before)
            regrown += du["locks"]
            hou.undos.performRedo()
            dr = G.cook_display()
            exact &= lib.same_arrays(lib.mask_arrays(node, lid), after)
            regrown += dr["locks"]
        C.add("dw3_undo_removes_exactly_the_stroke", exact and not lib.same_arrays(before, after),
              {"undo_equals_before_bit_for_bit": exact, "stroke_changed_points": int((before[1] != after[1]).sum())
               if before[1] is not None else int((after[1] > 0).sum()), "label": hou.undos.undoLabels()[0]},
              "the parm after undo == the parm before the stroke; redo == after it (3 times)")
        C.add("dw3_undo_fast_no_lock_recooked", max(times) < UNDO_LIMIT_S and not regrown,
              {"undo_and_cook_s": [round(t, 3) for t in times], "locks_regrown": regrown,
               "stroke_cook": {"locks": len(d["locks"]), "s": round(d["s"], 3)}},
              f"undo + display cook < {UNDO_LIMIT_S} s, 0 locks")
        # ---- the same with an anim wired and something reading output 1 (the v0.1 fault, Not sure 6)
        wired = bool(node.evalParm("anim_wired"))
        reader = node.parent().createNode("null", "accept_reads_output1")
        reader.setInput(0, node, 1)
        reader.cook()
        ga.mask_stroke(node, lid, [p0 + 0.008, p0 + 0.012], radius_cm=1.0, value=2.0)
        d = G.cook_display()
        reader.cook()
        g_locks = sorted(node.node("groom_to_cook").geometry().primIntAttribValues("lock_id"))
        t = time.perf_counter()
        hou.undos.performUndo()
        du = G.cook_display()
        undo_s = time.perf_counter() - t
        t = time.perf_counter()
        reader.cook()
        read_s = time.perf_counter() - t
        gu = sorted(node.node("groom_to_cook").geometry().primIntAttribValues("lock_id"))
        C.add("dw3_undo_with_anim_wired_and_output1_read",
              wired and undo_s < UNDO_LIMIT_S and not du["locks"] and not gu and len(d["locks"]) > 0,
              {"anim_wired": wired, "stroke": {"display_locks": len(d["locks"]), "output1_locks": len(g_locks)},
               "undo_and_display_cook_s": round(undo_s, 3), "display_locks_regrown": du["locks"],
               "output1_locks_regrown": gu, "output1_read_after_undo_s": round(read_s, 3)},
              f"undo + display cook < {UNDO_LIMIT_S} s; 0 locks regrown for the display and for output 1",
              note="reading output 1 after the undo also deforms its 4 M points by the wired anim (v0.1: about 1.1 s "
                   "whenever it is read, Shot deform or not); that read is timed apart, no lock is in it")
        reader.destroy()
        clear_layers()
        cook_both()

    # ------------------------------------------------------------------ ns1: skin under floating mesh, up
    def thin_skin():
        s = G.scalp()
        geo = node.node("SCALP_REGIONS").geometry()
        dist = geo.primFloatListAttribValues("owner_dist")
        dens = np.frombuffer(geo.primFloatAttribValuesAsString("density"), np.float32)
        far = float(node.evalParm("root_far_cm"))
        hi = far * (1 + config.ROOT_FAR_SOFT) / G.unit          # over this every root moves (far_w 1)
        floating = np.array([len(o) == 1 and len(dd) == 1 and dd[0] > hi * 1.2 for o, dd in zip(s["owners"], dist)])
        idx = np.nonzero(floating)[0]
        # the floating prim with the most floating skin within 1.2 cm, and that skin
        cen = s["cen_cm"]
        best, best_n = idx[0], -1
        for i in idx[::max(1, len(idx) // 300)]:
            n = int((((cen[idx] - cen[i]) ** 2).sum(1) <= 1.44).sum())
            if n > best_n:
                best, best_n = i, n
        patch = idx[((cen[idx] - cen[best]) ** 2).sum(1) <= 1.44]
        lock = s["owners"][best][0]
        patch = np.array([p for p in patch if s["owners"][p] == (lock,)])
        area = float(s["area"][patch].sum())
        asked = float((dens[patch] * s["area"][patch]).sum())
        roots0 = G.roots()
        n0, _ = G.roots_on(patch, roots0)
        S["thin_patch"] = patch
        lock_before = int((roots0[1] == lock).sum())
        lid = ga.mask_add(node, kind="paint", name="thin skin")
        G.paint_prims(lid, patch, 2.0)
        d, r = cook_both()
        lo, hi2 = G.prim_factor(ga.mask_factor(node).astype(float))
        inner = G.inner_prims((lo == 2.0) & (hi2 == 2.0), 0.3)
        inner = np.array([p for p in inner if p in set(patch.tolist())])
        asked_in = float((dens[inner] * s["area"][inner]).sum())
        b_in, _ = G.roots_on(inner, roots0)
        a_in, ra = G.roots_on(inner)
        r1 = G.roots()
        lock_after = int((r1[1] == lock).sum())
        st = lib.spacing_stats(ra, float(s["area"][inner].sum()))
        S["thin"] = {"lock": G.lock_names()[lock], "patch_cm2": round(area, 2), "patch_prims": len(patch)}
        fill = a_in / max(asked_in, 1e-9)
        C.add("ns1_thin_skin_painted_up_fills", 0.8 <= fill <= 1.25 and b_in / max(asked_in, 1e-9) < 0.25,
              {"lock": G.lock_names()[lock], "patch_cm2": round(area, 2), "painted": 2.0,
               "roots_asked_by_the_set_density": round(asked_in, 1), "roots_before": b_in, "roots_after": a_in,
               "density_before_over_set": round(b_in / max(asked_in, 1e-9), 3), "density_after_over_set": round(fill, 3),
               "whole_patch_before": n0, "lock_strands_before": lock_before, "lock_strands_after": lock_after,
               "lock_strands_added": lock_after - lock_before, "even": st,
               "locks_recooked": len(d["locks"]), "cook_s": round(d["s"], 2)},
              "skin with far_w 1 painted 2: (2 - 1) x the set density, 0.8 - 1.25 of it; under 0.25 before",
              note="decided for Not sure 1: the automatic share still starts the lock (far_w / max(mask, 1)), what "
                   "the mask adds above 1 stays on the skin")
        n1, _ = G.roots_on(patch)
        elsewhere = (lock_after - lock_before) - (n1 - n0)
        C.add("ns1_lock_start_keeps_its_roots", -0.01 * lock_before <= elsewhere <= 0.05 * lock_before,
              {"lock_strands_before": lock_before, "lock_strands_added": lock_after - lock_before,
               "roots_added_on_the_painted_skin": n1 - n0, "change_elsewhere_on_the_lock": elsewhere,
               "change_elsewhere_share": round(elsewhere / max(lock_before, 1), 4),
               "roots_asked_on_the_patch": round(asked, 1)},
              "the lock's roots elsewhere (its start) lose none and gain under 5 % of the lock's strands",
              note="a lock whose strand count is floored by its cross-section grows by more than the skin painted "
                   "asks (count x masked area / area); the surplus roots start the lock")
        clear_layers()
        cook_both()

    # ------------------------------------------------------------------ ns5 / dw2: the crown
    def crown():
        roots0 = G.roots()
        centre, n, per = lib.densest_spot(roots0[0], 1.0)
        S["crown"] = {"centre_cm": [round(float(c), 2) for c in centre], "v01_per_cm2": round(per, 1)}
        s = G.scalp()
        d2 = ((s["cen_cm"] - centre) ** 2).sum(1)
        lid = ga.mask_add(node, kind="paint", name="crown")
        # ---- painted 0: whorl roots and start roots are gone too (they are placed by the tool, not hairgen)
        G.paint_prims(lid, np.nonzero(d2 <= 1.6 ** 2)[0], 0.0)
        cook_both()
        lo, hi = G.prim_factor(ga.mask_factor(node).astype(float))
        inner = G.inner_prims((lo == 0.0) & (hi == 0.0), 0.3)
        before, _ = G.roots_on(inner, roots0)
        after, _ = G.roots_on(inner)
        C.add("ns5_whorl_and_start_roots_read_the_mask", after == 0 and before > 1000,
              {"roots_before": before, "roots_after": after, "prims": len(inner),
               "area_cm2": round(float(s["area"][inner].sum()), 2)},
              "0 roots on the crown painted 0 (whorl roots and the locks' start roots included)")
        hou.undos.performUndo()
        # ---- painted down to the approved groom's density
        value = round(V006_CROWN / per, 3)
        G.paint_prims(lid, np.nonzero(d2 <= 2.0 ** 2)[0], value)
        d, r = cook_both()
        r1 = G.roots()
        c1, n1, per1 = lib.densest_spot(r1[0], 1.0)
        same = lib.disc_density(r1[0], centre, 1.0)
        C.add("dw2_crown_painted_down_to_v006_hython", abs(per1 / V006_CROWN - 1) <= 0.12,
              {"painted": value, "densest_1cm_before_per_cm2": round(per, 1), "densest_1cm_after_per_cm2": round(per1, 1),
               "same_disc_after_per_cm2": round(same, 1), "v006_per_cm2": V006_CROWN,
               "strands_before": len(roots0[0]), "strands_after": len(r1[0]),
               "locks_recooked": len(d["locks"]), "cook_s": round(d["s"], 2)},
              "densest 1 cm disc within 12 % of v006's 5,104 / cm2",
              note="the same strokes by the brush in the viewport are accept_v02a_gui.py's dw2 checks")
        clear_layers()
        cook_both()

    # ------------------------------------------------------------------ ns2: scope
    def scope():
        s = G.scalp()
        L = G.lock_id(ZONE_LOCK)
        d0 = data()
        group = d0.lock(L).group
        base = G.strands_by_lock()
        prims = G.region_prims(L)[::2][:600]
        lid = ga.mask_add(node, kind="paint", name="group only", scope="group", group=group)
        G.paint_prims(lid, prims, 0.0)
        d, r = cook_both()
        now = G.strands_by_lock()
        in_group = {lk.id for lk in d0.locks if lk.group == group}
        changed = {k for k in base if base[k] != now.get(k, 0)}
        C.add("ns2_scope_group_reaches_only_its_locks",
              bool(changed) and changed <= in_group and set(d["locks"]) <= in_group and L in changed,
              {"group": group, "locks_in_group": len(in_group), "locks_changed": sorted(changed),
               "locks_recooked": d["locks"]}, "locks that changed and locks recooked are all of that group")
        ga.mask_remove(node, lid)
        # chosen locks: skin shared by stacked locks, the layer on one of them
        shared = next(((p, o) for p, o in enumerate(s["owners"]) if len(o) >= 2), None)
        a, b = shared[1][0], shared[1][1]
        both = np.array([p for p, o in enumerate(s["owners"]) if a in o and b in o])
        lid = ga.mask_add(node, kind="paint", name="one lock", scope="locks", locks=[a])
        G.paint_prims(lid, both, 0.0)
        d, r = cook_both()
        now = G.strands_by_lock()
        lo, hi = G.prim_factor(ga.mask_factor(node, a).astype(float))
        inner = G.inner_prims((lo == 0.0) & (hi == 0.0), 0.2)
        a_left, _ = G.roots_on(inner, lock_id=a, reach_cm=0.3)
        C.add("ns2_scope_locks_reaches_only_the_chosen_lock",
              d["locks"] == [a] and now.get(b) == base.get(b) and now.get(a, 0) < base[a] and a_left == 0,
              {"locks": [G.lock_names()[a], G.lock_names()[b]], "shared_prims": len(both),
               "chosen": {"before": base[a], "after": now.get(a, 0), "roots_left_on_painted_skin": a_left},
               "other": {"before": base[b], "after": now.get(b)}, "locks_recooked": d["locks"],
               "scope_sets": node.node("SCALP_REGIONS").geometry().attribValue("mask_sets")},
              "only the chosen lock is recooked and loses its roots there; the lock sharing that skin keeps its count",
              note="decided for Not sure 2: one blended factor per distinct set of layers (logic.mask_scope_sets), "
                   "each lock reads its own")
        clear_layers()
        cook_both()

    # ------------------------------------------------------------------ ns3: the digest sees a move inside a region
    def digest():
        s = G.scalp()
        L = G.lock_id(ZONE_LOCK)
        own = np.array([p for p in G.region_prims(L) if s["owners"][p] == (L,)])
        a, b = own[:120], own[-120:]
        lid = ga.mask_add(node, kind="paint", name="moves")
        G.paint_prims(lid, a, 0.5)
        G.cook_display()
        k1 = _key(L)
        hou.undos.performUndo()
        G.paint_prims(lid, b, 0.5)
        d = G.cook_display()
        k2 = _key(L)
        C.add("ns3_key_changes_when_density_moves_inside_a_region", k1 != k2 and L in d["locks"],
              {"key_a": k1, "key_b": k2, "locks_recooked": d["locks"]},
              "the same paint on another part of the lock's own skin gives another key and regrows it")
        clear_layers()
        cook_both()

    def _key(lock_id):
        geo = node.node("lock_keys").geometry()
        ids = geo.primIntAttribValues("lock_id")
        return geo.primStringAttribValues("cache_key")[ids.index(lock_id)]

    # ------------------------------------------------------------------ ns4: the brush stays on its side
    def brush_side():
        brush = gm.scalp_brush(node)
        P, N = brush.P.astype(float), brush.N.astype(float)
        r = 1.0 / G.unit
        found = None
        for i in range(0, len(P), 7):
            d2 = ((P - P[i]) ** 2).sum(1)
            near = np.nonzero((d2 < (0.8 * r) ** 2) & ((N @ N[i]) < -0.2))[0]
            if len(near) >= 5:
                found = (i, near)
                break
        if found is None:
            idx, _ = brush.reach(P[0], r)
            C.add("ns4_brush_stays_on_joined_skin_facing_the_same_way", len(idx) > 20,
                  {"helen": "no scalp point has skin facing away within 0.8 cm", "dab_points": int(len(idx))},
                  "a dab reaches skin; the rule itself is unit-tested (test_brush_reaches_only_joined_skin...)")
            return
        i, near = found
        idx, _ = brush.reach(P[i], r)
        straight = int((((P - P[i]) ** 2).sum(1) < r * r).sum())
        C.add("ns4_brush_stays_on_joined_skin_facing_the_same_way",
              not set(near.tolist()) & set(idx.tolist()) and len(idx) > 10,
              {"at_point": int(i), "skin_facing_away_within_0.8cm": int(len(near)), "reached_of_it": int(len(set(near.tolist()) & set(idx.tolist()))),
               "dab_points": int(len(idx)), "points_within_the_radius": straight},
              "none of the skin facing away is reached by a 1 cm dab")

    # ------------------------------------------------------------------ blend modes on the node
    def modes():
        s = G.scalp()
        L = G.lock_id(ZONE_LOCK)
        prims = G.region_prims(L)
        l0 = ga.mask_add(node, kind="paint", name="bottom", mode="multiply")
        l1 = ga.mask_add(node, kind="paint", name="top", mode="multiply", opacity=0.6)
        G.paint_prims(l0, prims[:800], 0.4, radius_cm=0.6, soft=0.5)
        G.paint_prims(l1, prims[400:1400], 1.7, radius_cm=0.6, soft=0.5)
        v0, a0 = lib.mask_arrays(node, l0)
        v1, a1 = lib.mask_arrays(node, l1)
        m = 1.0 + (1.0 * v0 - 1.0) * a0          # the bottom layer, multiply, written out here on purpose
        table = {"multiply": lambda: m * v1, "add": lambda: m + v1, "subtract": lambda: m - v1,
                 "replace": lambda: v1, "min": lambda: np.minimum(m, v1), "max": lambda: np.maximum(m, v1)}
        worst, rows = 0.0, {}
        for mode in config.MASK_MODES:
            ga.mask_set(node, l1, mode=mode)
            geo = node.node("SCALP_REGIONS").geometry()
            got = np.frombuffer(geo.pointFloatAttribValuesAsString("mask_0"), np.float32)
            want = np.maximum(m + (table[mode]() - m) * a1 * 0.6, 0.0)
            err = float(np.abs(got - want).max())
            rows[mode] = {"max_error": err, "min": float(got.min()), "max": float(got.max())}
            worst = max(worst, err)
        C.add("modes_on_the_node_match_the_rule", worst < 1e-5 and len(rows) == 6, rows,
              "mask_read's factor == m + (blend(m, v) - m) x coverage x opacity for the 6 modes, max error < 1e-5")
        clear_layers()

    # ------------------------------------------------------------------ adapter API: one undo step each
    def api():
        prims = G.region_prims(G.lock_id(ZONE_LOCK))
        p = G.scalp()["cen_cm"][prims[50]] / G.unit
        first = ga.mask_add(node, kind="paint", name="first")
        state = {}

        def snap():
            d = data()
            return (json.dumps([m.__dict__ for m in d.masks], sort_keys=True),
                    tuple(tuple(None if x is None else x.tobytes() for x in a)
                          for a in (lib.mask_arrays(node, i) for i in range(d.mask_id_high + 1))))

        ops = [
            ("mask_add", lambda: state.update(lid=ga.mask_add(node, kind="paint", name="second", mode="add", opacity=0.5))),
            ("mask_stroke paint", lambda: ga.mask_stroke(node, state["lid"], [p, p + 0.004], radius_cm=1.0, value=1.5)),
            ("mask_stroke erase", lambda: ga.mask_stroke(node, state["lid"], [p], radius_cm=0.5, erase=True)),
            ("mask_set mode", lambda: ga.mask_set(node, state["lid"], mode="max")),
            ("mask_set opacity", lambda: ga.mask_set(node, state["lid"], opacity=0.25)),
            ("mask_set on", lambda: ga.mask_set(node, state["lid"], on=False)),
            ("mask_set name", lambda: ga.mask_set(node, state["lid"], name="renamed")),
            ("mask_set scope", lambda: ga.mask_set(node, state["lid"], scope="locks", locks=[3, 1])),
            ("mask_move", lambda: ga.mask_move(node, state["lid"], 0)),
            ("mask_fill", lambda: ga.mask_fill(node, first, 0.8)),
            ("mask_invert", lambda: ga.mask_invert(node, first)),
            ("mask_clear", lambda: ga.mask_clear(node, first)),
            ("mask_add fill", lambda: state.update(fill=ga.mask_add(node, "fill", mode="replace", value=80, unit="density"))),
            ("mask_stroke white", lambda: ga.mask_stroke(node, state["fill"], [p, p + 0.004], radius_cm=1.0, level=1.0)),
            ("mask_stroke black", lambda: ga.mask_stroke(node, state["fill"], [p], radius_cm=0.5, level=0.0)),
            ("mask_set value", lambda: ga.mask_set(node, state["fill"], value=60.0)),
            ("mask_set unit", lambda: ga.mask_set(node, state["fill"], unit="factor")),
            ("mask_add folder", lambda: state.update(folder=ga.mask_add(node, kind="folder"))),
            ("mask_move into folder", lambda: ga.mask_move(node, state["fill"], 99, parent=state["folder"])),
            ("mask_stroke folder black", lambda: ga.mask_stroke(node, state["folder"], [p], radius_cm=0.5, level=0.0)),
            ("mask_remove folder", lambda: ga.mask_remove(node, state["folder"])),
            ("mask_remove", lambda: ga.mask_remove(node, state["lid"])),
        ]
        rows, ok = {}, True
        for name, fn in ops:
            before = snap()
            n0 = len(hou.undos.undoLabels())
            fn()
            labels = hou.undos.undoLabels()
            after = snap()
            hou.undos.performUndo()
            undone = snap() == before
            hou.undos.performRedo()
            redone = snap() == after
            one = len(labels) == n0 + 1 and labels[0].startswith("MONO Grooming: ")
            rows[name] = {"label": labels[0], "one_step": one, "changed": before != after, "undo": undone, "redo": redone}
            ok &= one and undone and redone and before != after
        C.add("api_every_layer_function_is_one_undo_step", ok, rows,
              "one new undo step, named MONO Grooming: ..., undo puts everything back, redo puts it again")
        # no change = no undo step; a bad mode is refused
        n0 = len(hou.undos.undoLabels())
        same = ga.mask_set(node, first, name="first")
        bad = False
        try:
            ga.mask_set(node, first, mode="screen")
        except ValueError:
            bad = True
        # Paint mode without a viewport: the layer functions and mask_stroke are what works
        entered = ga.paint_enter(node, first)
        layer = ga.paint_layer(node)
        b = ga.set_brush(radius_cm=2.0, value=0.3, erase=True)
        ga.paint_exit(node)
        ga.set_brush(radius_cm=config.BRUSH_RADIUS_CM, value=config.BRUSH_VALUE, erase=False)
        C.add("api_paint_mode_and_refusals",
              same is False and bad and len(hou.undos.undoLabels()) == n0 and (entered is False or hou.isUIAvailable())
              and layer == first and ga.paint_layer(node) is None and b["radius_cm"] == 2.0 and b["erase"] is True,
              {"no_change_no_step": same is False, "bad_mode_refused": bad, "paint_enter_without_ui": entered,
               "paint_layer_while_on": layer, "paint_layer_after_exit": ga.paint_layer(node), "brush": b},
              "an unchanged row writes nothing, a wrong mode raises, Paint keeps its layer and brush")
        clear_layers()

    # ------------------------------------------------------------------ fill layers, masks, folders
    def fill_layers():
        s = G.scalp()
        L = S["zone"]["L"]
        zone = S["zone"]["b"]
        dens = data().resolve(L)["density"]
        roots0 = G.roots()
        base = G.strands_by_lock()

        def inner_white(layer_id):
            v, a = lib.mask_arrays(node, layer_id)
            lo = np.full(len(s["area"]), np.inf)
            np.minimum.at(lo, s["vprim"], a[s["vpoint"]])
            return G.inner_prims(lo >= 1.0, 0.3)

        def ratio(prims):
            b, _ = G.roots_on(prims, roots0, lock_id=L)
            a, _ = G.roots_on(prims, lock_id=L)
            return a / max(b, 1), b, a

        # ---- "= 80 strands / cm2": one number on the layer, the brush only paints the mask white
        lid = ga.mask_add(node, "thin skin", mode="replace", value=80.0, unit="density")
        d, r = cook_both()
        nothing = not d["locks"] and r["strands"] == S["base_strands"]
        G.paint_prims(lid, zone, level=1.0)
        d, r = cook_both()
        v, a = lib.mask_arrays(node, lid)
        rt, b, aft = ratio(inner_white(lid))
        C.add("fl_fill_layer_sets_a_density_where_its_mask_is_white",
              nothing and v is None and abs(rt - 80.0 / dens) <= 0.06 and b > 100,
              {"layer": "replace, 80 strands / cm2", "lock_density": dens, "roots_before": b, "roots_after": aft,
               "ratio": round(rt, 3), "asked_ratio": round(80.0 / dens, 3), "new_layer_changed_nothing": nothing,
               "stored": "mask only" if v is None else "value and mask", "locks_recooked": len(d["locks"])},
              "roots of the lock on the white skin x 80 / its density, within 0.06; a new layer (black mask) "
              "changes nothing; only the mask is stored")
        # ---- the number is the layer's: changing it is one undo step and regrows the locks under the mask
        n0 = len(hou.undos.undoLabels())
        ga.mask_set(node, lid, mode="add", value=40.0)
        one = len(hou.undos.undoLabels()) == n0 + 1
        d2, _ = cook_both()
        rt2, b2, a2 = ratio(inner_white(lid))
        hou.undos.performUndo()
        d3, _ = cook_both()
        rt3, _b, _a = ratio(inner_white(lid))
        C.add("fl_layer_value_is_changed_without_painting",
              one and abs(rt2 - (1 + 40.0 / dens)) <= 0.08 and set(d2["locks"]) == set(d["locks"]) and not d3["locks"]
              and abs(rt3 - rt) < 1e-9,
              {"layer": "add, 40 strands / cm2", "ratio": round(rt2, 3), "asked_ratio": round(1 + 40.0 / dens, 3),
               "one_undo_step": one, "same_locks_recooked_as_the_paint": set(d2["locks"]) == set(d["locks"]),
               "undo_locks_regrown": d3["locks"], "ratio_after_undo": round(rt3, 3)},
              "+ 40 / cm2 gives x (1 + 40 / density) within 0.08; one undo step; undo regrows nothing")
        # ---- black paint, invert, white / black mask
        half = zone[: len(zone) // 2]
        G.paint_prims(lid, half, level=0.0)
        v, a1 = lib.mask_arrays(node, lid)
        ga.mask_invert(node, lid)
        v, a2m = lib.mask_arrays(node, lid)
        inverted = bool(np.allclose(a2m, 1.0 - a1, atol=1e-6))
        hou.undos.performUndo()
        ga.mask_fill(node, lid, 1.0)
        white = bool((lib.mask_arrays(node, lid)[1] == 1.0).all())
        d, r = cook_both()
        all_lock = r["strands"]
        ga.mask_clear(node, lid)
        black = lib.mask_arrays(node, lid)[1] is None
        d, r = cook_both()
        C.add("fl_mask_black_paint_invert_white_and_black_mask",
              int((a1 < 0.5).sum()) > 100 and inverted and white and black and r["strands"] == S["base_strands"]
              and all_lock < S["base_strands"],
              {"points_painted_black": int((a1 < 0.5).sum()), "invert_is_one_minus": inverted, "white_mask_everywhere": white,
               "strands_with_white_mask": all_lock, "strands_with_black_mask": r["strands"], "no_layer_strands": S["base_strands"]},
              "black paint lowers the mask, invert = 1 - mask, a white mask applies the layer everywhere, a black "
              "one nowhere (the v0.1 strand count again)")
        ga.mask_remove(node, lid)
        # ---- a folder: its mask and opacity over all its layers
        folder = ga.mask_add(node, "crown", kind="folder")
        child = ga.mask_add(node, "less", mode="multiply", value=0.5, parent=folder)
        G.paint_prims(child, zone, level=1.0)
        cook_both()
        full, bf, af = ratio(inner_white(child))
        G.paint_prims(folder, half, level=0.0)                 # the folder's mask: black on half the zone
        d, r = cook_both()
        v, fa = lib.mask_arrays(node, folder)
        lo = np.full(len(s["area"]), np.inf)
        hi = np.full(len(s["area"]), -np.inf)
        np.minimum.at(lo, s["vprim"], fa[s["vpoint"]])
        np.maximum.at(hi, s["vprim"], fa[s["vpoint"]])
        in_white = np.intersect1d(G.inner_prims(lo >= 1.0, 0.3), inner_white(child))
        in_black = np.intersect1d(G.inner_prims(hi <= 0.0, 0.3), inner_white(child))
        r_white, _b, _a = ratio(in_white)
        r_black, _b, _a = ratio(in_black)
        ga.mask_set(node, folder, opacity=0.5)
        cook_both()
        r_half, _b, _a = ratio(in_white)
        ga.mask_set(node, folder, opacity=1.0, on=False)
        d, r = cook_both()
        off = r["strands"] == S["base_strands"]
        C.add("fl_folder_mask_applies_to_all_its_layers",
              abs(full - 0.5) <= 0.06 and abs(r_white - 0.5) <= 0.06 and abs(r_black - 1.0) <= 0.06
              and abs(r_half - 0.75) <= 0.07 and off and len(in_white) > 50 and len(in_black) > 50,
              {"layer_in_folder": "multiply 0.5, mask white on the zone", "no_folder_mask_ratio": round(full, 3),
               "folder_mask_white_ratio": round(r_white, 3), "folder_mask_black_ratio": round(r_black, 3),
               "folder_opacity_0.5_ratio": round(r_half, 3), "folder_off_is_the_v01_count": off,
               "prims_counted": [int(len(in_white)), int(len(in_black))]},
              "x 0.5 where the folder's mask is white, x 1 where it is black, x 0.75 at folder opacity 0.5, "
              "nothing with the folder off (each within 0.06 - 0.07)",
              note="one level of folders; deleting a folder keeps its layers")
        clear_layers()
        cook_both()

    # ------------------------------------------------------------------ "= D": the painted density is the final one
    def absolute():
        s = G.scalp()
        D = 120.0
        roots0 = G.roots()
        crown = np.asarray(S["crown"]["centre_cm"])
        places = [("skin under floating mesh", S["thin_patch"]),
                  ("crown (whorl, lock starts)", np.nonzero(((s["cen_cm"] - crown) ** 2).sum(1) <= 2.0 ** 2)[0]),
                  ("skin with roots on it", S["zone"]["b"])]
        rows, ok = [], True
        for name, prims in places:
            lid = ga.mask_add(node, name, mode="replace", value=D, unit="density")
            G.paint_prims(lid, prims, level=1.0)
            d, r = cook_both()
            v, a = lib.mask_arrays(node, lid)
            lo = np.full(len(s["area"]), np.inf)
            np.minimum.at(lo, s["vprim"], a[s["vpoint"]])
            inner = G.inner_prims(lo >= 1.0, 0.3)
            area = float(s["area"][inner].sum())
            before, _ = G.roots_on(inner, roots0)
            after, _ = G.roots_on(inner)
            got = after / max(area, 1e-9)
            rows.append({"where": name, "area_cm2": round(area, 2), "before_per_cm2": round(before / max(area, 1e-9), 1),
                         "after_per_cm2": round(got, 1), "painted": D, "after_over_painted": round(got / D, 3),
                         "locks_recooked": len(d["locks"]), "cook_s": round(d["s"], 2)})
            ok &= 0.8 <= got / D <= 1.25 and area > 0.5
            ga.mask_remove(node, lid)
        d, r = cook_both()
        C.add("fl_painted_density_is_the_final_density", ok and r["strands"] == S["base_strands"],
              {"places": rows, "strands_after_removing_the_layers": r["strands"]},
              "a fill layer '= 120 strands / cm2' with a white mask leaves 120 roots / cm2 (all locks, 0.8 - 1.25) "
              "on skin that had none (floating mesh), on the crown (thousands) and on ordinary skin",
              note="under such a layer the tool does not move roots away or lay relocated roots (lock starts, "
                   "whorls) on that skin, and counts without the cross-section floor")

    # ------------------------------------------------------------------ rung 6 / dw5: persistence
    def persistence():
        nonlocal_G = S["G"]
        s = nonlocal_G.scalp()
        L = nonlocal_G.lock_id(ZONE_LOCK)
        prims = nonlocal_G.region_prims(L)
        l0 = ga.mask_add(node, kind="paint", name="keep all")
        l1 = ga.mask_add(node, kind="paint", name="keep locks", mode="add", opacity=0.7, scope="locks", locks=[L])
        nonlocal_G.paint_prims(l0, prims[:900], 0.3, radius_cm=0.6, soft=0.5)
        nonlocal_G.paint_prims(l1, prims[900:1500], 1.0, radius_cm=0.6, soft=0.5)
        # a folder with a fill layer in it, both masks painted
        fo = ga.mask_add(node, "keep folder", kind="folder")
        l3 = ga.mask_add(node, "keep fill", mode="multiply", value=0.6, parent=fo)
        nonlocal_G.paint_prims(l3, prims[1500:2100], radius_cm=0.6, soft=0.5, level=1.0)
        nonlocal_G.paint_prims(fo, prims[1800:2000], radius_cm=0.4, soft=0.5, level=0.0)
        cook_both()

        def snap(g=None, n=None):
            g, n = g or nonlocal_G, n or node
            d = ga.read_data(n)
            return {"masks": [dict(m.__dict__) for m in d.masks],
                    "arrays": [lib.mask_arrays(n, m.id) for m in d.masks], "strands": g.strands_by_lock()}

        def same(a, b):
            return (a["masks"] == b["masks"] and all(lib.same_arrays(x, y) for x, y in zip(a["arrays"], b["arrays"]))
                    and a["strands"] == b["strands"])

        ref = snap()
        total = sum(ref["strands"].values())
        ga.detect(node)
        after = snap()
        C.add("dw5_layers_survive_detect", same(ref, after) and total < S["base_strands"],
              {"layers": len(after["masks"]), "strands": sum(after["strands"].values()), "no_layer_strands": S["base_strands"],
               "kinds": [m["kind"] for m in after["masks"]],
               "painted_points": [int((a[1] > 0).sum()) for a in after["arrays"]]},
              "layer list, painted bytes and every lock's strand count as before Detect")
        ga.split_regions(node)
        nonlocal_G.forget()
        after = snap()
        C.add("dw5_layers_survive_update_regions", same(ref, after),
              {"strands": sum(after["strands"].values()), "regions_stale": data().regions_stale},
              "layer list, painted bytes and every lock's strand count as before Update regions")
        # ---- save and reopen
        hip = OUT + "/accept_v02a_painted.hiplc"
        hou.hipFile.save(hip)
        ga2, node2 = lib.open_scene(SUITE, hip)
        ga2.set_display(node2, "hair", "lock")
        G2 = lib.Groom(ga2, node2)
        after = snap(G2, node2)
        C.add("dw5_layers_survive_save_and_reopen", same(ref, after) and not lib.node_errors(node2),
              {"hip": hip, "hip_mb": round(os.path.getsize(hip) / 1e6, 1), "strands": sum(after["strands"].values()),
               "schema": ga2.read_data(node2).schema}, "the same after loading the saved hip", evidence=hip)
        # ---- publish, and read the layers back from the publish's JSON records
        run = OUT + "/publish_%s/char_Helen/04_grooming/work" % time.strftime("%Y%m%d_%H%M%S")
        os.makedirs(run)
        hou.hipFile.setName(run + "/char_Helen_grooming_v007.hiplc")
        res = ga2.publish(node2)
        info = {"ok": res.ok, "message": res.message, "usd": res.path}
        ok = res.ok
        if res.ok:
            tool = os.path.dirname(res.path) + "/" + config.TOOL_DATA_DIR
            record = json.load(open(tool + "/publish.json", encoding="utf-8"))
            layers, geo = ga2.masks_from_publish(tool)
            from pxr import Usd, UsdGeom
            stage = Usd.Stage.Open(res.path)
            usd_strands = sum(len(UsdGeom.BasisCurves(p).GetCurveVertexCountsAttr().Get() or [])
                              for p in stage.Traverse() if p.IsA(UsdGeom.BasisCurves))
            for m in list(ga2.read_data(node2).masks):
                ga2.mask_remove(node2, m.id)
            wiped = sum(G2.strands_by_lock().values())
            n_in = ga2.import_masks(node2, tool)
            back = snap(G2, node2)
            info.update(record_masks=record.get("masks"), files=sorted(os.listdir(tool)), usd_strands=usd_strands,
                        layers_in_json=[m.name for m in layers], strands_after_wipe=wiped,
                        layers_read_back=n_in, strands_after_read_back=sum(back["strands"].values()),
                        record_schema=record.get("schema"))
            ok = (same(ref, back) and usd_strands == total and wiped == S["base_strands"] and n_in == 4
                  and record["masks"].get("file") == gm.PUBLISH_MASK_FILE and geo is not None)
        C.add("dw5_layers_survive_publish_and_read_back", ok, info,
              "the published USD holds the masked groom; layers removed from the node and read back from the "
              "publish (grooming_data.json + publish.json -> mask_layers.bgeo) give the same layers and hair",
              evidence=res.path)
        S["G"], S["node2"], S["ga2"] = G2, node2, ga2

    # ------------------------------------------------------------------ a new scalp topology: by uv
    def uv_transfer():
        ga2, node2, G2 = S["ga2"], S["node2"], S["G"]
        old = gm.read_masks(node2)
        layers = ga2.read_data(node2).masks
        f_old = old.factor([m for m in layers if m.scope == "all"])
        P_old = old.P.astype(float)
        has_uv = gm._point_uv(node2.node("SCALP_FINE").geometry()) is not None
        node2.parm("region_subdiv").set(1)          # another fine scalp: 4x fewer points
        node2.node("SCALP_REGIONS").cook()
        new = gm.read_masks(node2)
        problem = ga2.mask_problem(node2)
        f_new = new.factor([m for m in layers if m.scope == "all"])
        P_new = new.P.astype(float)
        want = np.empty(len(P_new))
        for i in range(0, len(P_new), 500):
            want[i:i + 500] = f_old[((P_new[i:i + 500, None, :] - P_old[None, :, :]) ** 2).sum(-1).argmin(1)]
        off = np.abs(f_new - want)
        warn = [w for w in lib.node_warnings(node2) if "mask" in w.lower()]
        rebaked = ga2.mask_rebake(node2)
        still = gm.read_masks(node2).moved
        hou.undos.performUndo()
        node2.parm("region_subdiv").set(2)
        node2.node("SCALP_REGIONS").cook()
        back = gm.read_masks(node2)
        C.add("uv_transfer_to_a_new_scalp",
              new.moved and problem == gm.MOVED_TEXT and float((off > 0.25).mean()) < 0.02 and rebaked and not still
              and not back.moved and old.n != new.n,
              {"points_old": old.n, "points_new": new.n, "scalp_has_uv": has_uv, "moved": new.moved, "problem": problem,
               "mean_abs_diff": round(float(off.mean()), 4), "share_off_by_over_0.25": round(float((off > 0.25).mean()), 4),
               "inner_warning": warn, "rebake_stores_on_the_new_scalp": rebaked and not still,
               "back_on_the_old_scalp_unmoved": not back.moved},
              "on another Region subdivisions the factor is the old one at the nearest old point (under 2 % of points "
              "off by over 0.25), mask_problem says so, mask_rebake stores it")

    # ------------------------------------------------------------------ rung 5: the full cook against v0.1
    def full_cook():
        ga2, node2 = S["ga2"], S["node2"]
        for m in list(ga2.read_data(node2).masks):
            ga2.mask_remove(node2, m.id)
        now = time_full_cook(ga2, node2, runs=5)
        ref_path = _opt("--v01-time")
        if not ref_path or not os.path.isfile(ref_path):
            C.add("r5_full_cook_within_10pct_of_v01", False, now, "needs --v01-time <fullcook.json of the v0.1 suite>")
            return
        ref = json.load(open(ref_path, encoding="utf-8"))
        ratio = now["median_s"] / ref["median_s"]
        C.add("r5_full_cook_within_10pct_of_v01", ratio <= FULL_COOK_OVER_V01 and now["strands"] == ref["strands"],
              {"now": now, "v01": {k: ref[k] for k in ("runs_s", "min_s", "median_s", "strands", "lib")},
               "ratio_of_median": round(ratio, 3), "ratio_of_min": round(now["min_s"] / ref["min_s"], 3)},
              f"median of 5 cold cooks <= {FULL_COOK_OVER_V01} x v0.1's, the same strand count (single cooks swing "
              "by 20 % on this machine, so not the fastest one)", evidence=ref_path,
              note="no layer on; both timed by this script (--time-only on the v0.1 suite), one process each")

    for name, fn in (("no_layer", no_layer), ("zones", zones), ("strokes", strokes), ("thin_skin", thin_skin),
                     ("crown", crown), ("scope", scope), ("digest", digest), ("brush_side", brush_side),
                     ("modes", modes), ("api", api), ("fill_layers", fill_layers), ("absolute", absolute),
                     ("persistence", persistence),
                     ("uv_transfer", uv_transfer),
                     ("full_cook", full_cook)):
        C.log("==", name)
        t = time.perf_counter()
        C.run("section_" + name, fn)
        C.log("   %.1f s" % (time.perf_counter() - t))
    C.meta["seconds"] = round(time.perf_counter() - T0, 1)
    C.write(done=True)


T0 = time.perf_counter()
try:
    main()
except Exception:
    import traceback
    with open(OUT + "/accept_crash.txt", "w", encoding="utf-8") as fh:
        fh.write(traceback.format_exc())
os._exit(0)
