"""Acceptance of MONO Grooming v0.2b B2, the network and the adapter of lock control points and drawn locks
(docs/plans/grooming_v0_2.md, "v0.2b", "Done when").

    hython accept_v02b.py <suite> <scene> <out_dir> --base <suite before v0.2b> [--t55 <qc_report.json of t55>]
                          [--ref <approved groom.usd>] [--sh020 <shot scene>] [--sh025 <shot scene>]
                          [--look <dir of the look step's pictures>]
                          [--only id,id]

<scene> is a copy of the Helen grooming scene; the shot scenes copies of the ones t56 / t76 used; all stay in the
sandbox. Everything is written under <out_dir>: accept.json ({item, pass, value, limit, evidence} per check,
`passed`), accept_log.txt, and the files of the checks run in a process of their own (accept_v02b_sub.py: the
build before v0.2b against this one, a schema 6 scene, save / reopen, the shots; accept_v02a_sub.py: full-cook
timing). Hython's exit code is not reliable: read the JSON. Run it with no other Houdini cooking (speed limits are
absolute). One check id per "Done when" line this task (B2) can check in hython; the lines of the viewer state
(B3), the panel (B4) and grooming-check on the carried mesh (B5), and the user's own try, are listed with
`"pass": "not_here"` and the task that owns them.

Definitions this script makes on its own (for the checker to judge):
  1. "The same bend carried" (`accept_v02b_lib.carry`): a point at parameter u of the measured spine (its nearest
     place on it), with its offset in the spine's frame there, put at the same u and offset on the edited spine.
     A strand point is held to the carried strand of the same strand id (its distance to that polyline).
  2. "Spread across the width / thickness" (`accept_v02b_lib.spread`): the standard deviation of the strand points'
     offsets along the width axis / the thickness axis, the points within 0.025 of the station along the spine.
  3. "Hair width" of a drawn lock (`accept_v02b_lib.extent`): the 2nd to 98th percentile of the offsets across.
  4. "A root on the skin": its distance to the rest scalp's surface (nearestPrim), cm.
  5. "Strand length within N points" in a shot: the median of the lock's strands' length at the frame over their
     length at rest, edited against unedited (absolute difference of the two ratios).
  6. "Cooks as before" for a shot scene as saved: the build before v0.2b is not byte-identical with itself there
     (0.05 cm between its own runs, measured in t79), so this build is held to that spread (s5).
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback

SUITE, SCENE, OUT = (a.replace("\\", "/") for a in sys.argv[1:4])


def _arg(name, default=""):
    return sys.argv[sys.argv.index(name) + 1].replace("\\", "/") if name in sys.argv else default


BASE, T55, SH020, SH025, LOOK = _arg("--base"), _arg("--t55"), _arg("--sh020"), _arg("--sh025"), _arg("--look")
REF = _arg("--ref")   # the approved groom (v006) grooming-check grades against, as t55 and accept_v02a do
ONLY = [x for x in _arg("--only").split(",") if x]
HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, SUITE)
sys.path.insert(0, HERE)
os.makedirs(OUT, exist_ok=True)

import hou  # noqa: E402
import numpy as np  # noqa: E402

import accept_lib as lib  # noqa: E402
import accept_v02b_lib as alib  # noqa: E402
from tools.fx.grooming import config, logic, model  # noqa: E402

HYTHON = os.path.join(hou.expandString("$HFS"), "bin", "hython.exe" if os.name == "nt" else "hython").replace("\\", "/")
QC = SUITE + "/.claude/skills/grooming-check/scripts/qc_metrics.py"
# limits: the plan's "Done when" lines (docs/plans/grooming_v0_2.md v0.2b), never tuned to a result
IDENTITY_CM = 0.001
NETWORK_CM = 0.001            # the network's spine against logic.edited_spine
LOCK_S, PLUS_S = 0.2, 0.1     # an edit: 0.2 s a lock it recooks + 0.1 s
FOLLOW_MOVE_CM, FOLLOW_TURN_CM = 0.3, 0.5
SPREAD_SHARE = 0.10
MESH_CM = 0.01
ROOT_SKIN_CM = 0.001
UNDO_S = 0.1
REDRAW_CM = config.STROKE_TOL_CM          # 0.25
RESAMPLE_CM = config.RESAMPLE_TOL_CM      # 0.25
DRAWN_COUNT_SHARE, DRAWN_WIDTH_SHARE = 0.15, 0.20
GAP_CM = 0.0025               # a root on the skin (accept_v02a's z_roots_on_the_skin: the scalp quads are not planar)
READ_BACK_CM = 0.003
SHOT_POINTS = 0.03            # 2 cm move: strand length within 3 points of the unedited lock's
SHOT_ROOT_CM = 0.01           # roots: within this of the unedited lock's roots off the animated scalp (p95)
DRAWN_SHOT_LEN, DRAWN_SHOT_ROOT_CM = 0.02, 0.1
OLD_SCENE_CM = 0.003          # a groom v0.1 made and saved, v0.1 against itself (t68, 10 runs: 0.0024 cm)
OLD_SCENE_HELEN_CM = 0.015    # Helen as v0.1 saved it, "Fit lookup per lock" off: v0.1's own run-to-run (t68)
MOVE_LOCK, BACK_LOCK, BASE_LOCK = "hair_bang_11", "hair_back_20", "hair_base_20"

C = lib.Checks(OUT, meta={"suite": SUITE, "scene": SCENE, "base": BASE, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "argv": sys.argv[1:]})


def add(item, passed, value=None, limit=None, what="", evidence="", note=""):
    """One check: `what` (what is checked and how) goes to the entry's note, `evidence` names the files."""
    return C.add(item, passed, value, limit, evidence=evidence or "accept.json",
                 note=(what + ("; " + note if note else "")) if what else note)


def wanted(item: str) -> bool:
    return not ONLY or any(item.startswith(o) for o in ONLY)


def r3(x):
    return None if x is None else round(float(x), 4)


def hython(args, log_name, timeout=5400) -> str:
    path = OUT + "/" + log_name
    with open(path, "w", encoding="utf-8", errors="replace") as fh:
        subprocess.run([HYTHON] + list(args), stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def sub(mode, suite, hip, tag, *extra):
    """accept_v02b_sub.py <mode> in a new process: its JSON (and <tag>.npz for dump)."""
    outf = OUT + "/" + tag + ".json"
    if os.path.isfile(outf):
        os.remove(outf)
    hython([HERE + "/accept_v02b_sub.py", mode, suite, hip, outf, HERE] + [str(e) for e in extra], tag + ".log")
    if not os.path.isfile(outf):
        return {"error": "no file: see " + tag + ".log"}
    with open(outf, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# the scene: a fresh groom as v0.1's end-to-end test makes it
# ---------------------------------------------------------------------------
ga, node = lib.open_scene(SUITE, SCENE)
C.meta["library"] = node.type().definition().libraryFilePath()
lib.fresh(ga, node)
G = lib.Groom(ga, node)
U = G.unit
t0 = time.perf_counter()
node.cook()
C.meta["display_cold_s"] = r3(time.perf_counter() - t0)
G.rest.cook()
CC = lib.CookCount(ga)
NAMES = G.lock_names()
ID = {v: k for k, v in NAMES.items()}
D0 = node.evalParm(config.DATA_PARM)
REG0 = hou.Geometry(node.parm("regions").evalAsGeometry())
ROW0 = alib.rows(node, ga.NODE_SPINES_MEASURED)
HAIR0 = alib.strands(G.rest.geometry(), U)
WARN0 = lib.node_warnings(node)
C.meta.update({"strands": sum(len(v) for v in HAIR0.values()), "locks": len(NAMES), "warnings_fresh": WARN0,
               "lookup_per_piece": int(node.evalParm("lookup_per_piece"))})
C.write()


def cook_all():
    """Cook the display then output 1 at rest: (display seconds, locks the display grew, locks output 1 grew)."""
    CC.take()
    t = time.perf_counter()
    node.cook()
    s = time.perf_counter() - t
    d = CC.take()
    G.rest.cook()
    return s, d, CC.take()


def restore():
    """Back to the fresh groom (data and regions), undo off; the hair comes from the cache."""
    with hou.undos.disabler():
        node.parm(config.DATA_PARM).set(D0)
        node.parm("regions").set(REG0)
    cook_all()


def hair():
    G.rest.cook()
    return alib.strands(G.rest.geometry(), U)


def edited_row(lid):
    return alib.rows(node, ga.NODE_SPINES)[lid]


def set_frame(lid, H, step="move"):
    return ga.set_points(node, {lid: [list(map(float, h)) for h in H]}, space="frame", step=step)


def default_k(lid):
    return ga.lock_handles(node, [lid])[lid]["count"]


def same_strands(a, b):
    """Max point distance (cm) between two {lock: [(sid, P)]} for the locks of `a`, strand by strand id; inf when
    a strand or a count differs."""
    worst = 0.0
    for lid, rows_a in a.items():
        rb = {sid: P for sid, P in b.get(lid, [])}
        if len(rb) != len(rows_a):
            return float("inf")
        for sid, P in rows_a:
            Q = rb.get(sid)
            if Q is None or Q.shape != P.shape:
                return float("inf")
            worst = max(worst, float(np.abs(Q - P).max()) if len(P) else 0.0)
    return worst


def snap_fn():
    scalp = node.node("IN_SCALP").geometry()

    def snap(p):
        pr, u, v, _ = scalp.nearestPrim(hou.Vector3(*[float(c) for c in p]))
        return np.array(pr.positionAtInterior(u, v))
    return snap


def labels_after(fn):
    n0 = len(hou.undos.undoLabels())
    out = fn()
    labels = hou.undos.undoLabels()
    return out, len(labels) - n0, (labels[0] if labels else "")


# ---------------------------------------------------------------------------
# lines owned by other tasks: listed, never left out
# ---------------------------------------------------------------------------
NOT_HERE = {
    "q1_grooming_check_on_edited_groom": ("B5", "grooming-check passes, limits unchanged, on a groom with a moved, a "
                                          "rotated and a redrawn lock: its mesh checks read the carried mesh (B5, "
                                          "qc_metrics.py; the mesh is MESH_CARRIED here)"),
    "g1b_root_on_skin_at_every_event_of_the_drag": ("B3", "the root handle on the skin at every event of a drag "
                                                    "(viewer state, accept_v02b_gui.py); after the cook: g1 here"),
    "k1_control_points_and_paint": ("B3", "entering one ends the other; Esc, another node, deleting the node, "
                                    "File > New leave the tool without a traceback"),
    "k2_gui_scripted_gestures_with_flipbooks": ("B3", "a fringe lock moved, one rotated, one redrawn, one drawn on "
                                                "bare skin by scripted events in the GUI, flipbooks before and after"),
    "k3_panel_edited_and_reset": ("B4", "the panel shows \"edited\" on the row and offers Reset (mockup pick, grabs, "
                                  "contrast check)"),
    "k4_users_own_try": ("User look gate", "the user's own try with a mouse or pen"),
}
for item, (owner, what) in NOT_HERE.items():
    if wanted(item):
        C.items.append({"item": item, "pass": "not_here", "value": None, "limit": None, "evidence": owner,
                        "note": what})
C.write()


# ---------------------------------------------------------------------------
# e: the edit itself on Helen
# ---------------------------------------------------------------------------
def e1_identity():
    rows = {}
    ok = True
    for name in (MOVE_LOCK, BACK_LOCK):
        lid = ID[name]
        h = ga.lock_handles(node, [lid])[lid]
        res, steps, _ = labels_after(lambda: set_frame(lid, h["frame"]))
        _s, d, _r = cook_all()
        now = hair()
        moved = same_strands({lid: HAIR0[lid]}, now)
        others = same_strands({k: v for k, v in HAIR0.items() if k != lid}, now)
        rows[name] = {"handles": h["count"], "stored": res["locks"] == [lid], "max_point_move_cm": float("%.3g" % moved),
                      "other_locks_max_move_cm": others, "recooked": d}
        ok = ok and moved <= IDENTITY_CM and others == 0.0 and res["locks"] == [lid]
        restore()
    add("e1_handles_equal_to_measured_move_nothing", ok, rows, IDENTITY_CM,
          "handles stored equal to the measured spine's (lock_handles' frame, default count): no strand point of the "
          "lock moves more than the limit; the other locks are byte-equal")


def e0_network_rule():
    lid = ID[MOVE_LOCK]
    row = ROW0[lid]
    K = default_k(lid)
    snap = snap_fn()
    cases = {"tip_2cm": alib.bend(row, K, 2.0, U), "turn_25deg": alib.turn(row, K, 25.0)}
    H = alib.measured_handles(row, K)
    H[0] = (0.0, 1.0 / U, 0.0)          # the root slid 1 cm across the lock (then onto the skin)
    cases["root_slid_1cm"] = H
    out = {}
    ok = True
    for tag, H in cases.items():
        set_frame(lid, H)
        cook_all()
        got = edited_row(lid)
        want = logic.edited_spine(row["P"], row["tangent"], row["axis"], H, snap)
        dp = float(np.linalg.norm(got["P"] - want.P, axis=1).max() * U)
        da = float(np.degrees(np.arccos(np.clip(np.abs(np.sum(alib._unit(got["axis"]) * want.axis, 1)), -1, 1))).max())
        out[tag] = {"max_point_cm": float("%.3g" % dp), "axis_max_deg": round(da, 4)}
        ok = ok and dp <= NETWORK_CM
        restore()
    add("e0_network_equals_logic_edited_spine", ok, out, NETWORK_CM,
          "SPINES after the edit against logic.edited_spine on SPINES_MEASURED's spine with the same handles (the moved "
          "root snapped by the rest scalp's nearest surface point), cm")


def e2_speed():
    lid_base, lid_back = ID[BASE_LOCK], ID[BACK_LOCK]
    fringe = [ID[n] for n in sorted(NAMES.values()) if n.startswith("hair_bang_")][:5]
    rows = {}
    ok = True
    for tag, lids in ((BASE_LOCK, [lid_base]), (BACK_LOCK, [lid_back]), ("five_fringe_locks", fringe)):
        limit = LOCK_S * len(lids) + PLUS_S
        runs = []
        for cm in (1.0, 2.0, 3.0):
            pts = {}
            for lid in lids:
                K = default_k(lid)
                H = alib.measured_handles(ROW0[lid], K)
                H[K // 2, 1] += cm / U          # one control point moved (a mid handle)
                pts[lid] = H.tolist()
            ga.set_points(node, pts, space="frame")
            s, d, _r = cook_all()
            runs.append({"cm": cm, "display_s": r3(s), "recooked": d})
            ok = ok and s <= limit and d == sorted(lids)
        restore()
        rows[tag] = {"locks": [NAMES[i] for i in lids], "limit_s": limit, "runs": runs,
                     "worst_s": max(r["display_s"] for r in runs)}
    add("e2_one_handle_recooks_only_its_locks_in_time", ok, rows, "0.2 s a lock + 0.1 s",
          "one control point moved (three different moves each): the display cook right after, the locks the per-lock "
          "loop grew (LockCache.put): only the edited ones, every run inside the limit (graded on the worst)")


def _bend_cases(lid):
    row = ROW0[lid]
    K = default_k(lid)
    return {"tip_2cm": (alib.bend(row, K, 2.0, U), FOLLOW_MOVE_CM), "turn_25deg": (alib.turn(row, K, 25.0), FOLLOW_TURN_CM)}


def e3_e4_follow():
    lid = ID[MOVE_LOCK]
    out3, out4 = {}, {}
    ok3 = ok4 = True
    before_spread = alib.spread(HAIR0[lid], ROW0[lid], U)
    for tag, (H, limit) in _bend_cases(lid).items():
        set_frame(lid, H)
        cook_all()
        now = hair()[lid]
        row1 = edited_row(lid)
        f = alib.follow(HAIR0[lid], now, ROW0[lid], row1, U)
        out3[tag] = dict(f, limit_cm=limit)
        ok3 = ok3 and f["p95_cm"] is not None and f["p95_cm"] <= limit
        after = alib.spread(now, row1, U)
        ratios = {}
        for st, b in before_spread.items():
            a = after.get(st)
            if b is None or a is None:
                ratios[st] = None
                ok4 = False
                continue
            ratios[st] = {"width": r3(a["width_cm"] / b["width_cm"]), "thick": r3(a["thick_cm"] / b["thick_cm"]),
                          "before_cm": [r3(b["width_cm"]), r3(b["thick_cm"])], "after_cm": [r3(a["width_cm"]), r3(a["thick_cm"])]}
            ok4 = ok4 and abs(ratios[st]["width"] - 1) <= SPREAD_SHARE and abs(ratios[st]["thick"] - 1) <= SPREAD_SHARE
        out4[tag] = ratios
        restore()
    add("e3_strands_follow_the_bend", ok3, out3, {"tip_2cm": FOLLOW_MOVE_CM, "turn_25deg": FOLLOW_TURN_CM},
          "%s: each strand point of the edited lock against the same strand of the unedited lock carried by the bend "
          "(DEFINITION 1), p95 cm" % MOVE_LOCK)
    add("e4_cross_section_kept", ok4, out4, SPREAD_SHARE,
          "spread across the width and the thickness at 0.3 / 0.5 / 0.7 / 0.9 of the lock (DEFINITION 2), after / "
          "before, within 10 %")


def e5_mesh_display():
    lid = ID[MOVE_LOCK]
    pieces = node.node("pieces").geometry()
    Pm = np.frombuffer(pieces.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(np.float64)
    pc = np.frombuffer(pieces.pointIntAttribValuesAsString("piece"), np.int32)
    mp = node.node("mesh_pu").geometry()
    pu = np.frombuffer(mp.pointFloatAttribValuesAsString("pu"), np.float32).astype(np.float64)
    sp = node.node(ga.NODE_SPINES).geometry()
    piece = list(sp.primIntAttribValues("piece"))[list(sp.primIntAttribValues("lock_id")).index(lid)]
    flip = ga.read_data(node).lock(lid).root_flip
    sel = (pc == piece) & (pu >= 0)
    out = {}
    ok = True
    for tag, (H, _l) in _bend_cases(lid).items():
        set_frame(lid, H)
        ga.set_display(node, "mesh", "lock")
        node.cook()
        u = 1 - pu[sel] if flip else pu[sel]
        want = alib.carry(Pm[sel], u, ROW0[lid], edited_row(lid))
        disp = node.node("OUT").geometry()
        lids = np.frombuffer(disp.primIntAttribValuesAsString("lock_id"), np.int32)
        from apps.houdini import grooming_masks as gm
        vp, vpt = gm._vertex_tables(disp)
        DP = np.frombuffer(disp.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(np.float64)
        mine = DP[np.unique(vpt[lids[vp] == lid])]
        carried = node.node(ga.NODE_MESH_CARRIED).geometry()
        CP = np.frombuffer(carried.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(np.float64)

        def nn(a, b):
            d = np.empty(len(a))
            for i in range(0, len(a), 2000):
                d[i:i + 2000] = np.sqrt(((a[i:i + 2000, None] - b[None]) ** 2).sum(-1)).min(1)
            return d
        a_b = nn(mine, want).max() * U if len(mine) else float("inf")
        b_a = nn(want, mine).max() * U if len(mine) else float("inf")
        c_w = float(np.linalg.norm(CP[sel] - want, axis=1).max() * U)
        moved = float(np.linalg.norm(want - Pm[sel], axis=1).max() * U)
        out[tag] = {"mesh_points": int(sel.sum()), "display_points": int(len(mine)),
                    "display_to_rule_max_cm": float("%.3g" % a_b), "rule_to_display_max_cm": float("%.3g" % b_a),
                    "MESH_CARRIED_to_rule_max_cm": float("%.3g" % c_w), "mesh_moved_max_cm": r3(moved)}
        ok = ok and max(a_b, b_a, c_w) <= MESH_CM and moved > 1.0
        ga.set_display(node, "hair", "lock")
        restore()
    add("e5_mesh_display_on_the_edited_spine", ok, out, MESH_CM,
          "the display in Mesh: the edited lock's mesh points (output 0) against its mesh carried by the bend (the "
          "carry rule, DEFINITION 1, computed here from `pieces`, `pu`, SPINES_MEASURED and SPINES), both ways, and "
          "MESH_CARRIED point by point; the mesh did move (over 1 cm)")


# ---------------------------------------------------------------------------
# g: the root; u: undo steps; d: redraw and reset; h: handle counts
# ---------------------------------------------------------------------------
def g1_root():
    lid = ID[MOVE_LOCK]
    h = ga.lock_handles(node, [lid])[lid]
    pts = np.array(h["points"])
    scalp = node.node("IN_SCALP").geometry()
    pr, u, v, _ = scalp.nearestPrim(hou.Vector3(*pts[0]))
    nrm = np.array(pr.normal())
    pts[0] = pts[0] + nrm * 1.0 / U + np.array(h["axes"][1]) * 0.8 / U       # dragged 1 cm off the skin, 0.8 across
    ga.set_points(node, {lid: pts.tolist()})
    cook_all()
    root = edited_row(lid)["P"][0]
    off = float(alib.to_skin_cm([root], scalp, U)[0])
    handle_root = np.array(ga.lock_handles(node, [lid])[lid]["points"][0])
    restore()
    # a root never moved: a tip moved only
    K = default_k(lid)
    set_frame(lid, alib.bend(ROW0[lid], K, 2.0, U))
    cook_all()
    same = float(np.linalg.norm(edited_row(lid)["P"][0] - ROW0[lid]["P"][0]) * U)
    restore()
    ok = off <= ROOT_SKIN_CM and same == 0.0 and float(np.linalg.norm(handle_root - root) * U) < 1e-4
    add("g1_root_on_the_skin_after_the_cook", ok,
          {"moved_root_off_skin_cm": float("%.3g" % off), "handle_reports_that_root": bool(np.linalg.norm(handle_root - root) * U < 1e-4),
           "unmoved_root_from_measured_cm": same}, {"on_skin_cm": ROOT_SKIN_CM, "unmoved_cm": 0.0},
          "a root handle given 1 cm off the skin: the cooked spine's root on the skin; a lock with only its tip moved "
          "keeps the measured root exactly (the drag itself is B3's: g1b)")


def g2_root_regions():
    lid = ID[MOVE_LOCK]
    h = ga.lock_handles(node, [lid])[lid]
    pts = np.array(h["points"])
    pts[0] = pts[0] + np.array(h["axes"][1]) * 1.5 / U          # slid 1.5 cm across the lock
    res = ga.set_points(node, {lid: pts.tolist()})
    data = ga.read_data(node)
    why = list(data.stale_why)
    cook_all()
    new_root = edited_row(lid)["P"][0]
    ga.split_regions(node)
    G.forget()
    frozen = node.parm("regions").evalAsGeometry()
    P = np.frombuffer(frozen.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(np.float64)
    owners = frozen.pointIntListAttribValues("lock_owners")
    lw = node.node(ga.NODE_SPINES_LOCKS).geometry()
    prim = lw.prims()[list(lw.primIntAttribValues("lock_id")).index(lid)]
    pts0 = prim.points()
    width = max(p.floatAttribValue("lock_width") for p in pts0[:max(2, len(pts0) // 10)])
    radius = config.REGION_FOOTPRINT * width
    centre = P[np.argmin(((P - new_root) ** 2).sum(1))]          # split_regions' root on the skin
    inside = np.nonzero(np.linalg.norm(P - centre, axis=1) <= radius)[0]
    owned = sum(1 for i in inside if lid in owners[i])
    old_centre = P[np.argmin(((P - ROW0[lid]["P"][0]) ** 2).sum(1))]
    old_only = [i for i in np.nonzero(np.linalg.norm(P - old_centre, axis=1) <= radius * 0.5)[0]
                if np.linalg.norm(P[i] - centre) > radius]
    ok = data.regions_stale and any("a root moved" in w for w in why) and len(inside) > 0 and owned == len(inside)
    add("g2_moved_root_regions_out_of_date_then_footprint", ok,
          {"stale": data.regions_stale, "why": why, "message": res["message"], "footprint_prims": int(len(inside)),
           "owned_by_the_lock": owned, "footprint_radius_cm": r3(radius * U),
           "old_footprint_core_prims_away_from_the_new": len(old_only),
           "of_those_still_the_lock": sum(1 for i in old_only if lid in owners[i])},
          "all footprint prims owned", "a root slid 1.5 cm: regions out of date with the reason; after Update regions "
          "every frozen region point within the footprint (REGION_FOOTPRINT x the head width) of the new root is the lock's")
    restore()
    G.forget()


def u1_undo():
    lid = ID[MOVE_LOCK]
    H = alib.bend(ROW0[lid], default_k(lid), 2.0, U)
    before = node.evalParm(config.DATA_PARM)
    _res, steps, label = labels_after(lambda: set_frame(lid, H))
    cook_all()
    after = node.evalParm(config.DATA_PARM)
    CC.take()
    t = time.perf_counter()
    hou.undos.performUndo()
    node.cook()                         # the display, as the viewport draws it after an undo
    undo_s = time.perf_counter() - t
    d1 = CC.take()
    t = time.perf_counter()
    G.rest.cook()
    rest_undo_s = time.perf_counter() - t
    r1 = CC.take()
    back = node.evalParm(config.DATA_PARM) == before
    t = time.perf_counter()
    hou.undos.performRedo()
    node.cook()
    redo_s = time.perf_counter() - t
    d2 = CC.take()
    G.rest.cook()
    r2 = CC.take()
    again = node.evalParm(config.DATA_PARM) == after
    ok = steps == 1 and label == config.UNDO_SPINE["move"] and back and again and undo_s < UNDO_S and not d1 \
        and not r1 and not d2 and not r2
    add("u1_one_edit_one_undo_step", ok,
          {"undo_steps": steps, "label": label, "undo_and_display_cook_s": r3(undo_s), "redo_and_display_cook_s": r3(redo_s),
           "output1_after_undo_s": r3(rest_undo_s),
           "data_back": back, "data_again": again, "regrown_undo": d1 + r1, "regrown_redo": d2 + r2},
          UNDO_S, "one set_points (what a drag writes on release) is one undo step; one undo returns the data in under "
          "0.1 s with no lock grown again (display and output 1), redo returns the edit (the drag itself is B3's)")
    restore()


def u2_steps():
    lid, back = ID[MOVE_LOCK], ID[BACK_LOCK]
    rows = {}
    spot, nrm = alib.bare_spot(node, U)
    stroke = alib.drawn_stroke(spot, nrm, 12.0, U)
    axes = np.array(ga.lock_handles(node, [lid])[lid]["axes"])
    redrawn = ROW0[lid]["P"] + axes[1] * np.linspace(0, 1.5 / U, len(ROW0[lid]["P"]))[:, None]
    ops = [
        ("rotate", lambda: ga.rotate_points(node, [lid], axes[2], 20.0)),
        ("scale", lambda: ga.scale_points(node, [lid], 1.2)),
        ("redraw", lambda: ga.redraw_lock(node, lid, redrawn.tolist())),
        ("handles", lambda: ga.set_handle_count(node, [back], 7)),
        ("draw", lambda: ga.draw_lock(node, stroke)),
    ]
    ok = True
    for step, fn in ops:
        before = node.evalParm(config.DATA_PARM)
        reg = node.parm("regions").evalAsGeometry().pointFloatAttribValuesAsString("P")
        res, steps, label = labels_after(fn)
        hou.undos.performUndo()
        back_ok = node.evalParm(config.DATA_PARM) == before
        rows[step] = {"undo_steps": steps, "label": label, "data_back_after_one_undo": back_ok}
        ok = ok and steps == 1 and label == config.UNDO_SPINE[step] and back_ok
        hou.undos.performRedo()
        if step == "draw":
            drawn_id = res["id"]
    # reset (of the edits above) and delete (of the drawn lock)
    for step, fn in (("reset", lambda: ga.reset_points(node, [lid])),
                     ("delete", lambda: ga.delete_drawn_locks(node, [drawn_id]))):
        before = node.evalParm(config.DATA_PARM)
        res, steps, label = labels_after(fn)
        hou.undos.performUndo()
        back_ok = node.evalParm(config.DATA_PARM) == before
        rows[step] = {"undo_steps": steps, "label": label, "data_back_after_one_undo": back_ok}
        ok = ok and steps == 1 and label == config.UNDO_SPINE[step] and back_ok
        hou.undos.performRedo()
    cook_all()
    add("u2_each_gesture_one_undo_step", ok, rows, "1 step each, labels of config.UNDO_SPINE",
          "rotate, scale, redraw, handle count, draw, reset, delete a drawn lock: each one undo step with its label; "
          "one undo puts the data back as it was before it")
    restore()


def u3_several():
    fringe = [ID[n] for n in sorted(NAMES.values()) if n.startswith("hair_bang_")][:5]
    hs = ga.lock_handles(node, fringe)
    pts = {}
    for lid in fringe:
        P = np.array(hs[lid]["points"])
        P[-1] = P[-1] + np.array(hs[lid]["axes"][1]) * 1.0 / U
        pts[lid] = P.tolist()
    before = node.evalParm(config.DATA_PARM)
    res, steps, label = labels_after(lambda: ga.set_points(node, pts))
    s, d, _r = cook_all()
    moved = {}
    for lid in fringe:
        moved[NAMES[lid]] = r3(np.linalg.norm(edited_row(lid)["P"][-1] - ROW0[lid]["P"][-1]) * U)
    hou.undos.performUndo()
    back = node.evalParm(config.DATA_PARM) == before
    ok = steps == 1 and res["locks"] == sorted(fringe) and back and d == sorted(fringe) \
        and all(abs(m - 1.0) < 0.05 for m in moved.values())
    add("u3_several_locks_one_undo_step", ok,
          {"locks": [NAMES[i] for i in fringe], "undo_steps": steps, "tips_moved_cm": moved, "recooked": d,
           "display_s": r3(s), "all_back_after_one_undo": back},
          "one step", "the same handle (the tip) of five fringe locks moved 1 cm in one set_points: one undo step, the "
          "five recook, one undo takes all five back (choosing the handles is B3's)")
    restore()


def d1_redraw():
    lid = ID[MOVE_LOCK]
    row = ROW0[lid]
    h = ga.lock_handles(node, [lid])[lid]
    # the stroke: the lock turned 20 deg about its root (round the thickness axis) and bent 1.5 cm at the tip
    X = alib.turn(row, len(row["P"]), 0.0)
    origin, R = np.array(h["origin"]), np.array(h["axes"])
    Q = logic.frame_to_world(X, origin, R)
    Q = logic.rotate_about_root(Q, R[2], 20.0) + R[1] * (np.linspace(0, 1, len(Q)) ** 2 * 1.5 / U)[:, None]
    Q[0] = row["P"][0]
    res, steps, _ = labels_after(lambda: ga.redraw_lock(node, lid, Q.tolist()))
    cook_all()
    gap = logic.curve_gap(edited_row(lid)["P"], Q) * U
    add("d1_redrawn_spine_within_the_stroke", gap <= REDRAW_CM and steps == 1,
          {"gap_cm": r3(gap), "function_gap_cm": r3(res["gap_cm"]), "handles": res["count"], "undo_steps": steps},
          REDRAW_CM, "a stroke (the lock turned 20 deg and bent 1.5 cm at the tip, from its root) redrawn: the cooked "
          "spine against the stroke, the farthest they lie apart both ways (logic.curve_gap), cm")
    restore()


def d2_reset():
    lid = ID[MOVE_LOCK]
    set_frame(lid, alib.bend(ROW0[lid], default_k(lid), 2.0, U))
    cook_all()
    res = ga.reset_points(node, [lid])
    s, d, r = cook_all()
    now = hair()
    same = same_strands({lid: HAIR0[lid]}, now)
    spine = float(np.abs(edited_row(lid)["P"] - ROW0[lid]["P"]).max() * U)
    ok = res["locks"] == [lid] and same == 0.0 and spine == 0.0 and not d and not r
    add("d2_reset_exact_from_the_cache", ok, {"reset": res["locks"], "strand_points_max_cm": same,
                                                "spine_max_cm": spine, "regrown": d + r, "display_s": r3(s)},
          0.0, "Reset after a 2 cm move: the lock's spine and every strand point equal the measured / unedited ones "
          "exactly, from the cache (no lock grown)")
    restore()


def h1_counts():
    hs = ga.lock_handles(node)
    wrong = {}
    for lid, h in hs.items():
        want = min(config.HANDLES_MAX, max(config.HANDLES_MIN, int(math.ceil(h["length_cm"] / 8.0 - 1e-9)) + 1))
        if h["count"] != want:
            wrong[NAMES[lid]] = [h["count"], want]
    counts = sorted({h["count"] for h in hs.values()})
    lid = ID[BACK_LOCK]
    ga.set_handle_count(node, [lid], 7)
    set_now = ga.lock_handles(node, [lid])[lid]["count"]
    hip = OUT + "/h1_counts.hiplc"
    hou.hipFile.save(hip)
    got = sub("dump", SUITE, hip, "h1_reopen")
    reopened = got.get("handles", {}).get(str(lid))
    ga.detect(node)
    after_detect = ga.read_data(node).lock(lid).handles
    ok = not wrong and set_now == 7 and reopened == 7 and after_detect == 7
    add("h1_default_handle_count_then_the_set_one_kept", ok,
          {"locks": len(hs), "not_by_length": wrong, "counts_seen": counts, "set": set_now, "after_reopen": reopened,
           "after_detect": after_detect, "errors_reopen": got.get("errors"), "error": got.get("error")},
          "ceil(cm / 8) + 1 in 4..12", "every lock shows the default count for its length (computed here); a count of "
          "7 set on %s is kept through save / reopen (a new process) and Detect" % BACK_LOCK)
    restore()


def h2_resample():
    """5 -> 8 -> 5 handles after a 2 cm tip move and after a 25 deg turn (each step's cooked spine against the
    edited spine as made, within RESAMPLE_TOL_CM), and one 12 -> 4 with a local bend, whose message must give the
    true distance (the farthest a cooked spine point moved, within 0.01 cm)."""
    rows = {}
    ok = True
    lid = ID[MOVE_LOCK]
    for tag, make in (("tip_2cm", lambda K: alib.bend(ROW0[lid], K, 2.0, U)),
                      ("turn_25deg", lambda K: alib.turn(ROW0[lid], K, 25.0))):
        ga.set_handle_count(node, [lid], 5)
        set_frame(lid, make(5))
        cook_all()
        made = edited_row(lid)["P"]
        steps = []
        for K in (8, 5):
            res = ga.set_handle_count(node, [lid], K)
            cook_all()
            gap = logic.curve_gap(edited_row(lid)["P"], made) * U
            count = ga.lock_handles(node, [lid])[lid]["count"]
            steps.append({"to": K, "count": count, "gap_from_as_made_cm": r3(gap),
                          "reported_step_cm": r3(res["gap_cm"].get(lid)), "message": res["message"]})
            ok = ok and gap <= RESAMPLE_CM and count == K
        rows[f"{MOVE_LOCK}_{tag}_5_8_5"] = steps
        restore()
    lid = ID[BACK_LOCK]
    K = default_k(lid)
    H = alib.measured_handles(ROW0[lid], K)
    H[K // 2, 1] += 3.0 / U
    set_frame(lid, H)
    cook_all()
    before = edited_row(lid)["P"]
    res = ga.set_handle_count(node, [lid], 4)
    cook_all()
    gap = logic.curve_gap(edited_row(lid)["P"], before) * U
    pointwise = float(np.linalg.norm(edited_row(lid)["P"] - before, axis=1).max() * U)
    reported = res["gap_cm"].get(lid, -1)
    said = ("%.2f cm" % reported) in res["message"]
    rows["%s_local_bend_%d_to_4" % (BACK_LOCK, K)] = {"gap_cm": r3(gap), "reported_cm": r3(reported),
                                                     "pointwise_cooked_cm": r3(pointwise),
                                                     "message": res["message"], "message_says_how_far": said,
                                                     "count": ga.lock_handles(node, [lid])[lid]["count"]}
    ok = ok and K == 12 and ga.lock_handles(node, [lid])[lid]["count"] == 4 and (gap <= RESAMPLE_CM or said) \
        and abs(pointwise - reported) < 0.01
    add("h2_handle_count_change_keeps_the_shape", ok, rows, RESAMPLE_CM,
        "%s with 5 handles, moved 2 cm at the tip, then turned 25 deg: 5 -> 8 -> 5, each step's cooked spine "
        "within config.RESAMPLE_TOL_CM of the edited spine as made (curve_gap); %s with 12 handles and a 3 cm "
        "local bend set to 4: the change made and the message giving the true distance (the farthest a cooked "
        "spine point moved, within 0.01 cm)" % (MOVE_LOCK, BACK_LOCK))
    restore()


# ---------------------------------------------------------------------------
# n: drawn locks
# ---------------------------------------------------------------------------
def _drawn_setup():
    spot, nrm = alib.bare_spot(node, U)
    stroke = alib.drawn_stroke(spot, nrm, 12.0, U)
    return spot, stroke


def n1_n2_drawn():
    spot, stroke = _drawn_setup()
    hair_before = hair()
    before = node.evalParm(config.DATA_PARM)
    reg_before = node.parm("regions").evalAsGeometry().pointIntListAttribValues("lock_owners")
    CC.take()
    res, steps, label = labels_after(lambda: ga.draw_lock(node, stroke, 2.0, 0.6, 0.3))
    reg_after = node.parm("regions").evalAsGeometry().pointIntListAttribValues("lock_owners")

    def reg_before_sel(new_id):        # the owners before the draw of the points the new lock took
        return [reg_before[i] for i, own in enumerate(reg_after) if list(own) == [new_id]]
    s, d, r = cook_all()
    lid = res["id"]
    now = hair()
    mine = now.get(lid, [])
    G.forget()
    sk = G.scalp()
    area = sum(a / len(o) for a, o in zip(sk["area"], sk["owners"]) if lid in o)
    spine = edited_row(lid)
    nodes_sp = node.node(ga.NODE_SPINES).geometry()
    k = list(nodes_sp.primIntAttribValues("lock_id")).index(lid)
    widths = [p.floatAttribValue("lock_width") for p in nodes_sp.prims()[k].points()]
    thicks = [p.floatAttribValue("lock_thick") for p in nodes_sp.prims()[k].points()]
    section = logic.section_cm2(max(widths), max(thicks), U)
    dens = float(ga.read_data(node).resolve(lid)["density"])
    want = dens * max(area, section)
    roots = np.array([P[0] for _sid, P in mine]) / U if mine else np.zeros((0, 3))
    off = alib.to_skin_cm(roots, node.node("IN_SCALP").geometry(), U, limit=10000) if len(roots) else np.array([9.9])
    ext = alib.extent(mine, spine, U) if mine else {}
    lk = ga.read_data(node).lock(lid)
    wrows = {}
    wok = bool(ext)
    for st, e in ext.items():
        wset, tset = logic.drawn_profile([float(st)], lk.width_cm, lk.thick_cm, lk.taper)
        ratio = None if e is None else e["width_cm"] / float(wset[0])
        wrows[st] = {"hair_width_cm": None if e is None else r3(e["width_cm"]), "set_cm": r3(wset[0]),
                     "ratio": r3(ratio), "hair_thick_cm": None if e is None else r3(e["thick_cm"]), "set_thick_cm": r3(tset[0])}
        wok = wok and ratio is not None and abs(ratio - 1) <= DRAWN_WIDTH_SHARE
    errs = lib.node_errors(node)
    warns = [w for w in lib.node_warnings(node) if w not in WARN0]
    count_ok = len(mine) > 0 and abs(len(mine) / want - 1) <= DRAWN_COUNT_SHARE
    # the user's 2026-11-20: named drawn_NN, in the group of the lock that gave it most skin (computed here)
    gave_w: dict = {}
    for own in reg_before_sel(res["id"]):
        for o in own:
            gave_w[o] = gave_w.get(o, 0.0) + 1.0 / max(len(own), 1)
    top = min(gave_w, key=lambda k: (-gave_w[k], k)) if gave_w else None
    want_group = ga.read_data(node).lock(top).group if top is not None else None
    named = res["name"].startswith("drawn_") and res["name"][6:].isdigit()
    grouped = want_group is not None and lk.group == want_group
    ok1 = count_ok and float(off.max()) <= GAP_CM and wok and not errs and not warns and named and grouped
    add("n1_drawn_lock_grows_on_bare_skin", ok1,
          {"lock": res["name"], "named_drawn_nn": named, "group": lk.group, "group_of_most_skin_given": want_group,
           "skin_given_by": {NAMES.get(k, k): r3(v) for k, v in gave_w.items()},
           "strands": len(mine), "expected": r3(want), "ratio": r3(len(mine) / max(want, 1e-9)),
           "skin_cm2": r3(area), "cross_section_cm2": r3(section), "density": dens,
           "roots_off_skin_max_cm": float("%.3g" % off.max()), "width_at_stations": wrows, "errors": errs,
           "new_warnings": warns, "stroke_cm": r3(logic.arc_lengths(np.array(stroke))[-1] * U)},
          {"count_share": DRAWN_COUNT_SHARE, "width_share": DRAWN_WIDTH_SHARE, "roots_cm": GAP_CM},
          "a lock drawn on the skin farthest from every lock's root (a 12 cm stroke, width 2, thickness 0.6, taper 0.3): "
          "strands = density x max(its skin, its cross-section) within 15 %, every root on the skin, hair width "
          "(DEFINITION 3) within 20 % of the set width at 0.3 / 0.5 / 0.7 / 0.9, no error and no new warning on the node")
    gave = set(res["gave_ids"])
    changed = [k for k in hair_before if k != lid and same_strands({k: hair_before[k]}, now) != 0.0]
    names_said = all(NAMES[i] in res["message"] for i in gave)
    hou.undos.performUndo()
    s2, d2, r2 = cook_all()
    back = node.evalParm(config.DATA_PARM) == before and \
        node.parm("regions").evalAsGeometry().pointIntListAttribValues("lock_owners") == reg_before
    hair_back = same_strands(hair_before, hair())
    # only the new lock and those that gave skin recook (a state cooked before comes from the cache: a subset)
    ok2 = steps == 1 and label == config.UNDO_SPINE["draw"] and len(mine) > 0 and set(d) <= gave | {lid} and lid in d \
        and set(changed) <= gave and names_said and back and hair_back == 0.0 and not d2 and not r2 and gave
    add("n2_draw_one_step_with_its_footprint", ok2,
          {"undo_steps": steps, "label": label, "gave": res["gave"], "recooked": d, "locks_whose_hair_changed": [NAMES[i] for i in changed],
           "message": res["message"], "names_in_message": names_said, "display_s": r3(s),
           "undo_data_and_regions_back": back, "undo_hair_max_cm": hair_back, "regrown_on_undo": d2 + r2},
          "one step", "Draw: one undo step that also gives the footprint: hair at once, only the new lock and those that "
          "gave skin recook, the message names them; one undo takes the lock and the region change back, hair from the "
          "cache")
    hou.undos.performRedo()
    cook_all()
    return lid, stroke


def n4_delete_gives_skin_back():
    """Delete a drawn lock: one undo step, its skin to its neighbours (the rule of Update regions on that skin),
    the message naming them, only they recook; one undo takes it all back."""
    spot, stroke = _drawn_setup()
    reg0 = node.parm("regions").evalAsGeometry().pointIntListAttribValues("lock_owners")
    d = ga.draw_lock(node, stroke)
    cook_all()
    lid = d["id"]
    before = node.evalParm(config.DATA_PARM)
    reg1 = node.parm("regions").evalAsGeometry().pointIntListAttribValues("lock_owners")
    hair1 = hair()
    CC.take()
    res, steps, label = labels_after(lambda: ga.delete_drawn_locks(node, [lid]))
    s, dc, rc = cook_all()
    reg2 = node.parm("regions").evalAsGeometry().pointIntListAttribValues("lock_owners")
    freed = [i for i, own in enumerate(reg1) if list(own) == [lid]]
    left_bare = [i for i in freed if not list(reg2[i])]
    still_named = sum(1 for own in reg2 if lid in own)
    back_as_before = sum(1 for i in freed if sorted(reg2[i]) == sorted(reg0[i]))
    took = set(res["took_ids"])
    named_all = all(NAMES[i] in res["message"] for i in took)
    # its neighbours: locks that owned skin within 3 cm of its root before it was drawn
    fz = node.parm("regions").evalAsGeometry()
    FP = np.frombuffer(fz.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(np.float64)
    close = np.linalg.norm(FP - np.asarray(stroke[0]), axis=1) * U <= 3.0
    neighbours = {o for i in np.nonzero(close)[0] for o in reg0[i]}
    now = hair()
    changed = [k for k in hair1 if k != lid and k in now and same_strands({k: hair1[k]}, now) != 0.0]
    hou.undos.performUndo()
    back = node.evalParm(config.DATA_PARM) == before and \
        node.parm("regions").evalAsGeometry().pointIntListAttribValues("lock_owners") == reg1
    ok = steps == 1 and label == config.UNDO_SPINE["delete"] and freed and not left_bare and still_named == 0 \
        and took and took <= neighbours and named_all and set(dc) <= took and set(changed) <= took and back
    add("n4_delete_gives_skin_back", ok,
        {"deleted": d["name"], "undo_steps": steps, "label": label, "freed_prims": len(freed),
         "left_bare": len(left_bare), "prims_still_naming_it": still_named,
         "neighbours_within_3cm": sorted(NAMES[i] for i in neighbours if i in NAMES),
         "freed_prims_owned_as_before_the_draw": back_as_before, "took": res["took"], "message": res["message"],
         "recooked": dc, "locks_whose_hair_changed": [NAMES[i] for i in changed], "display_s": r3(s),
         "one_undo_puts_lock_and_regions_back": back},
        "one step",
        "a lock drawn on bare skin, then deleted: one undo step that gives every region point it owned alone to the "
        "locks the rule of Update regions gives it there (none left bare, none naming it), the message names those "
        "locks, only they recook; one undo puts the lock and the regions back")
    restore()


def n3_detect(lid, stroke):
    report = ga.detect(node)
    d = ga.read_data(node)
    lk = d.lock(lid)
    kept = lk is not None and lk.drawn and lk.match == "ok" and all(o.id != lid for o in d.orphans)
    counts = report.counts
    res = ga.delete_drawn_locks(node, [lid])
    gone = ga.read_data(node).lock(lid) is None
    again = ga.draw_lock(node, stroke)
    errs = lib.node_errors(node)
    ok = kept and counts["new"] == 0 and counts["orphaned"] == 0 and gone and again["id"] > lid and not errs
    add("n3_detect_leaves_a_drawn_lock_delete_never_reuses", ok,
          {"after_detect": {"there": lk is not None, "drawn": lk.drawn if lk else None, "match": lk.match if lk else None,
                            "counts": counts}, "deleted": res, "gone": gone, "drawn_again_id": again["id"],
           "deleted_id": lid, "id_high": ga.read_data(node).id_high, "errors": errs},
          "", "Detect: the drawn lock is neither missing nor new; deleted it leaves the data; a lock drawn after it gets "
          "a higher id")
    restore()


# ---------------------------------------------------------------------------
# p: persistence
# ---------------------------------------------------------------------------
def _edited_state():
    lid, back = ID[MOVE_LOCK], ID[BACK_LOCK]
    set_frame(lid, alib.bend(ROW0[lid], default_k(lid), 2.0, U))
    set_frame(back, alib.turn(ROW0[back], default_k(back), 25.0))
    spot, stroke = _drawn_setup()
    drawn = ga.draw_lock(node, stroke)
    ga.set_handle_count(node, [ID[BASE_LOCK]], 6)
    cook_all()
    return drawn["id"]


def _fields(d):
    return {lk.id: (lk.spine, lk.handles, lk.curve, lk.width_cm, lk.thick_cm, lk.taper, lk.source) for lk in d.locks}


def p1_survive():
    drawn = _edited_state()
    f0 = _fields(ga.read_data(node))
    h0 = hair()
    rows = {}
    hou.undos.performUndo()
    hou.undos.performRedo()
    cook_all()
    rows["undo_redo"] = {"data_same": _fields(ga.read_data(node)) == f0, "hair_max_cm": same_strands(h0, hair())}
    hip = OUT + "/p1_edited.hiplc"
    hou.hipFile.save(hip)
    got = sub("dump", SUITE, hip, "p1_reopen")
    if "error" not in got:
        reopened = _npz_strands(OUT + "/p1_reopen.npz")
        rows["save_reopen"] = {"hair_max_cm": float("%.3g" % same_strands(h0, reopened)), "schema": got.get("stored_schema"),
                               "edited": got.get("edited"), "drawn": got.get("drawn"), "errors": got.get("errors")}
    else:
        rows["save_reopen"] = {"error": got["error"]}
    ga.detect(node)
    cook_all()
    rows["detect"] = {"data_same": _fields(ga.read_data(node)) == f0, "hair_max_cm": same_strands(h0, hair())}
    ga.split_regions(node)
    cook_all()
    G.forget()
    now = hair()
    rows["update_regions"] = {"data_same": _fields(ga.read_data(node)) == f0, "drawn_strands": len(now.get(drawn, [])),
                              "edited_strands": {NAMES[i]: len(now.get(i, [])) for i in (ID[MOVE_LOCK], ID[BACK_LOCK])}}
    sr = rows["save_reopen"]
    ok = rows["undo_redo"]["data_same"] and rows["undo_redo"]["hair_max_cm"] == 0.0 and "error" not in sr \
        and sr["hair_max_cm"] <= READ_BACK_CM and sr["schema"] == model.SCHEMA and not sr["errors"] \
        and rows["detect"]["data_same"] and rows["detect"]["hair_max_cm"] == 0.0 \
        and rows["update_regions"]["data_same"] and rows["update_regions"]["drawn_strands"] > 0 \
        and all(v > 0 for v in rows["update_regions"]["edited_strands"].values())
    add("p1_edits_and_drawn_locks_survive", ok, rows, READ_BACK_CM,
          "a 2 cm move, a 25 deg turn, a drawn lock and a handle count: the same data and hair after undo / redo, save / "
          "reopen (a new process, %s cm), Detect; after Update regions the data the same and the drawn and edited locks "
          "grow hair" % READ_BACK_CM)
    restore()
    G.forget()


def p2_orphan():
    lid = ID[MOVE_LOCK]
    H = alib.bend(ROW0[lid], default_k(lid), 2.0, U)
    set_frame(lid, H)
    want = ga.read_data(node).lock(lid).spine
    src = node.inputs()[1]
    pieces = node.node("pieces").geometry()
    sp = node.node(ga.NODE_SPINES).geometry()
    piece = sp.primIntAttribValues("piece")[list(sp.primIntAttribValues("lock_id")).index(lid)]
    pp = np.frombuffer(pieces.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3)
    pc = np.frombuffer(pieces.pointIntAttribValuesAsString("piece"), np.int32)
    keys = {tuple(np.round(x, 5)) for x in pp[pc == piece]}
    gin = src.geometry()
    Pin = np.frombuffer(gin.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3)
    hit = np.array([tuple(np.round(x, 5)) in keys for x in Pin])
    prims = sorted({pr.number() for pr in gin.prims() if hit[pr.vertices()[0].point().number()]})
    blast = node.parent().createNode("blast", "accept_v2b_drop")
    blast.setInput(0, src)
    blast.parm("group").set(" ".join(str(x) for x in prims))
    blast.parm("grouptype").set(4)
    row = {"mesh_prims_dropped": len(prims)}
    try:
        node.setInput(1, blast)
        ga.detect(node)
        d = ga.read_data(node)
        orphan = next((o for o in d.orphans if o.id == lid), None)
        row["missing_keeps_its_edit"] = orphan is not None and orphan.spine == want
    finally:
        node.setInput(1, src)
        blast.destroy()
    ga.detect(node)
    d = ga.read_data(node)
    back = [x for x in d.locks if x.match == "new"]
    row["back_as"] = [(x.id, x.name) for x in back]
    if back:
        d.reassign_orphan(lid, back[0].id)
        ga.write_data(node, d, "accept: reassign")
        got = ga.read_data(node).lock(back[0].id)
        row["reassigned_edit"] = got.spine == want
        cook_all()
        row["errors"] = lib.node_errors(node)
    ok = row.get("missing_keeps_its_edit") and row.get("reassigned_edit") and not row.get("errors")
    add("p2_missing_lock_keeps_its_edit", bool(ok), row, "",
          "a hair mesh version without the edited lock's piece: Detect makes it missing with its control points "
          "(Orphan.from_lock); the piece back is a new lock, reassign_orphan gives it the edit")
    restore()


def p3_publish():
    drawn = _edited_state()
    ga.split_regions(node)
    cook_all()
    h0 = hair()
    work = OUT + "/publish/char_Helen/04_grooming/work"
    os.makedirs(work, exist_ok=True)
    pub_root = OUT + "/publish/char_Helen/04_grooming/publish"
    if os.path.isdir(pub_root):
        shutil.rmtree(pub_root)
    name = hou.hipFile.path()
    hou.hipFile.setName(work + "/char_Helen_grooming_v007.hiplc")
    res = ga.publish(node)
    hou.hipFile.setName(name)
    row = {"ok": res.ok, "message": res.message}
    ok = bool(res.ok)
    if res.ok:
        tool = os.path.dirname(res.path) + "/" + config.TOOL_DATA_DIR
        rec = json.load(open(tool + "/publish.json", encoding="utf-8"))
        gd = model.GroomData.from_json(open(tool + "/grooming_data.json", encoding="utf-8").read())
        row["publish_json_spines"] = rec.get("spines")
        row["grooming_data"] = {"schema": gd.schema, "edited": gd.edited_locks(),
                                "drawn": [lk.id for lk in gd.locks if lk.drawn]}
        # a fresh node on the same inputs: Detect, the publish's edits and drawn locks, Update regions
        fresh = node.parent().createNode(config.HDA_TYPE, "accept_read_back")
        for i, src in enumerate(node.inputs()):
            if src is not None:
                fresh.setInput(i, src)
        for p in fresh.parms():
            if p.name() in ("lookup_per_piece",):
                p.set(node.parm(p.name()).eval())
        ga.write_data(fresh, model.GroomData(asset="char_Helen"), "fresh")
        ga.detect(fresh)
        got = ga.import_spines(fresh, tool)
        ga.split_regions(fresh)
        rest = fresh.node("GROOM_REST")
        rest.cook()
        h1 = alib.strands(rest.geometry(), U)
        diff = same_strands(h0, h1)
        row["read_back"] = {"imported": got, "hair_max_cm": float("%.3g" % diff), "strands": sum(len(v) for v in h1.values()),
                            "strands_published_node": sum(len(v) for v in h0.values()), "errors": lib.node_errors(fresh)}
        ok = ok and rec.get("spines", {}).get("drawn") and rec["spines"].get("edited") and gd.schema == model.SCHEMA \
            and drawn in row["grooming_data"]["drawn"] and diff <= READ_BACK_CM and not row["read_back"]["errors"]
        fresh.destroy()
    add("p3_publish_and_read_back", bool(ok), row, READ_BACK_CM,
          "publish.json names the edited and drawn locks, grooming_data.json holds them (schema 7); read back into a "
          "fresh node (Detect, import_spines, Update regions) the hair is the published node's within the limit, cm")
    restore()
    G.forget()


# ---------------------------------------------------------------------------
# r / m / x: the build before v0.2b, a schema 6 scene, the full cook; s: shots (processes of their own)
# ---------------------------------------------------------------------------
def _npz_strands(path):
    """{lock: [(strand id, points cm)]} of a dump (accept_v02b_sub.py): the points are mapped from <tag>_P.npy and
    copied strand by strand (one 96 MB array failed to allocate in this long-running process, twice)."""
    z = np.load(path)
    P = np.load(os.path.splitext(path)[0] + "_P.npy", mmap_mode="r")
    out = {}
    st = np.concatenate([[0], np.cumsum(z["nv"])])
    for k in range(len(z["lock"])):
        out.setdefault(int(z["lock"][k]), []).append((int(z["sid"][k]), np.array(P[st[k]:st[k + 1]], dtype=np.float64)))
    return out


def r1_m1_base():
    if not BASE:
        add("r1_no_edit_is_the_groom_before_v02b", False, None, "--base <suite>", note="not run: no --base")
        return
    made = OUT + "/saved_by_base.json"
    hython([HERE + "/accept_v02a_sub.py", "makeold", BASE, SCENE, made, HERE], "saved_by_base.log")
    hip = OUT + "/saved_by_base.hiplc"
    tags = [("base_%d" % i, BASE) for i in range(3)] + [("new_%d" % i, SUITE) for i in range(3)]
    order = [tags[0], tags[3], tags[1], tags[4], tags[2], tags[5]]          # interleaved, each a new process
    runs = {tag: sub("dump", suite, hip, "r1_" + tag) for tag, suite in order}
    if any("error" in v for v in runs.values()):
        add("r1_no_edit_is_the_groom_before_v02b", False, {k: v.get("error") for k, v in runs.items()})
    else:
        hair_of = {t: _npz_strands(OUT + "/r1_%s.npz" % t) for t, _s in tags}
        bases = [t for t, _s in tags[:3]]
        news = [t for t, _s in tags[3:]]
        pairs = {f"{n}_vs_{b}": same_strands(hair_of[b], hair_of[n]) for n in news for b in bases}
        base_pairs = {f"{a}_vs_{b}": same_strands(hair_of[a], hair_of[b]) for i, a in enumerate(bases) for b in bases[i + 1:]}
        hair_of.clear()
        counts = all(runs[n]["strands"] == runs[bases[0]]["strands"] for n in news)
        new_warn = sorted(set(w for n in news for w in runs[n]["warnings"]) - set(runs[bases[0]]["warnings"]))
        errors = [e for n in news for e in runs[n]["errors"]]
        equal_runs = sorted({p.split("_vs_")[0] for p, d in pairs.items() if d == 0.0})
        ok = counts and bool(equal_runs) and max(pairs.values()) <= OLD_SCENE_CM and not errors and not new_warn
        add("r1_no_edit_is_the_groom_before_v02b", ok,
            {"strands": sum(runs[news[0]]["strands"].values()), "counts_per_lock_equal": counts,
             "new_runs_byte_equal_to_a_base_run": equal_runs, "points_max_cm_new_vs_base": pairs,
             "points_max_cm_base_vs_base": base_pairs, "errors": errors, "new_warnings": new_warn},
            {"equal": "counts, and a new run byte for byte", "every_pair_cm": OLD_SCENE_CM},
            "a fresh groom made and saved by the build before v0.2b (ed7d0de, main + the plan), opened and cooked "
            "(output 1 at rest) by it and by this build, 3 processes each, interleaved: every lock's strand count "
            "equal; points byte-equal in at least one pair, and every pair within v0.1's own run-to-run difference "
            "(the per-lock loop is not byte-identical from process to process: t68, 0.0024 cm; here a 2-strand "
            "difference in one lock in 1 of 4 runs of this build)", evidence="r1_*.json / .npz")
    got = sub("edit6", SUITE, hip, "m1_schema6")
    base_sha = runs["base_0"].get("data_sha1")
    import hashlib  # noqa: F401
    ok = got.get("schema_as_opened") == 6 and got.get("text_sha1_as_opened") == base_sha \
        and got.get("schema_after_cook") == 6 and got.get("schema_after_edit") == model.SCHEMA and not got.get("errors")
    add("m1_schema6_opens_unchanged_written_7_by_the_next_edit", ok,
          {k: got.get(k) for k in ("schema_as_opened", "schema_after_cook", "schema_after_edit", "undo_label", "errors",
                                   "error")} | {"text_same_as_saved": got.get("text_sha1_as_opened") == base_sha},
          "6, then 7", "a scene saved by the build before v0.2b: opened and cooked its groom_data is the text it was "
          "saved with (schema 6); the next edit writes schema 7")


def r2_qc():
    if not T55 or not os.path.isfile(T55):
        add("r2_qc_numbers_are_t55s", False, T55, "--t55 <qc_report.json>", note="not run: no --t55")
        return
    node.parm("lookup_per_piece").set(0)
    cook_all()
    hip = OUT + "/noedit_v01_lookup.hiplc"
    hou.hipFile.save(hip)
    node.parm("lookup_per_piece").set(1)
    cook_all()
    out = OUT + "/qc_noedit"
    hython([QC, SUITE, hip, out] + (["--ref", REF] if REF else []), "qc_noedit.log")
    path = out + "/qc_report.json"
    if not os.path.isfile(path):
        add("r2_qc_numbers_are_t55s", False, "no qc_report.json", note="see qc_noedit.log")
        return
    rep = json.load(open(path, encoding="utf-8"))
    ref = {c["check"]: c["value"] for c in json.load(open(T55, encoding="utf-8"))["checks"]}
    now = {c["check"]: c["value"] for c in rep["checks"]}
    diff = {k: [now.get(k), v] for k, v in ref.items() if now.get(k) != v}
    failed = [c["check"] for c in rep["checks"] if not c["pass"]]
    add("r2_qc_numbers_are_t55s", not diff and not failed, {"numbers": len(ref), "different": diff, "failed": failed},
          "equal", "grooming-check on the groom with no edit and no drawn lock, \"Fit lookup per lock\" off (the numbers "
          "t55 measured; on, 8 of them move by up to 1 %%, accept_v02a r3): every number equal t55's",
          evidence="qc_noedit/qc_report.json")


def x1_fullcook():
    if not BASE:
        add("x1_full_cook_within_10pct", False, None, "--base <suite>", note="not run: no --base")
        return
    runs = {"new": [], "base": []}
    for i in range(3):
        for tag, suite in (("new", SUITE), ("base", BASE)):
            outf = OUT + "/fullcook_%s_%d.json" % (tag, i)
            hython([HERE + "/accept_v02a_sub.py", "fullcook", suite, SCENE, outf, HERE, "3"], "fullcook_%s_%d.log" % (tag, i))
            if os.path.isfile(outf):
                got = json.load(open(outf, encoding="utf-8"))
                if "median_s" in got:
                    runs[tag].append({"runs_s": got["runs_s"], "median_s": got["median_s"], "strands": got["strands"]})
    if min(len(v) for v in runs.values()) < 3:
        add("x1_full_cook_within_10pct", False, runs, note="a timing process failed: see fullcook_*.log")
        return
    new = float(np.median([r["median_s"] for r in runs["new"]]))
    old = float(np.median([r["median_s"] for r in runs["base"]]))
    add("x1_full_cook_within_10pct", new <= old * 1.10 and runs["new"][0]["strands"] == runs["base"][0]["strands"],
          {"new_median_s": r3(new), "base_median_s": r3(old), "ratio": r3(new / old), "runs": runs}, 1.10,
          "cold full cook of the rest groom, 3 processes each, interleaved (accept_v02a_sub fullcook): median <= 1.10 x "
          "the build before v0.2b's")


def s_shots():
    shots = [(tag, hip, frames) for tag, hip, frames in (("sh020", SH020, "30,60,90,120"), ("sh025", SH025, "15,30,45"))
             if hip]
    if not shots:
        for item in ("s1_shot_edited_lock_follows", "s3_shot_drawn_lock_follows_the_scalp",
                     "s4_shot_drawn_lock_at_rest_without_the_scalp", "s5_three_inputs_cook_as_before"):
            add(item, False, None, "--sh020 / --sh025", note="not run: no shot scene given")
        return
    look = LOOK or OUT + "/look"
    os.makedirs(look, exist_ok=True)
    got = {tag: sub("shot", SUITE, hip, "shot_" + tag, frames, look) for tag, hip, frames in shots}
    rows1, rows3, rows4 = {}, {}, {}
    ok1 = ok3 = ok4 = True
    for tag, g in got.items():
        if "error" in g:
            rows1[tag] = rows3[tag] = rows4[tag] = {"error": g["error"]}
            ok1 = ok3 = ok4 = False
            continue
        rows1[tag] = g["edited"]
        for f, row in g["edited"]["frames"].items():
            for case in ("move_2cm", "move_5cm"):
                c = row[case]
                c["length_points_from_unedited"] = r3(abs(c["length_p50"] - row["unedited"]["length_p50"]))
            c2 = row["move_2cm"]
            ok1 = ok1 and row["unedited"]["left_behind"] == 0 and c2["left_behind"] == 0 \
                and row["move_5cm"]["left_behind"] == 0 \
                and c2["length_points_from_unedited"] <= SHOT_POINTS \
                and c2["roots_p95_cm"] <= row["unedited"]["roots_p95_cm"] + SHOT_ROOT_CM
        rows3[tag] = g["drawn_wired"]
        ok3 = ok3 and g["drawn_wired"]["scalp_ok"] and all(
            abs(r["length_p50"] - 1) <= DRAWN_SHOT_LEN and r["roots_p95_cm"] <= DRAWN_SHOT_ROOT_CM
            for place in g["drawn_wired"]["places"].values() for r in place["frames"].values())
        rows4[tag] = g["drawn_unwired"]
        ok4 = ok4 and all(v["drawn_at_rest_max_cm"] == 0.0 and v["message"] and not v["errors"]
                          and v["mesh_locks_same_as_without_the_drawn_lock_cm"] == 0.0
                          for v in g["drawn_unwired"].values())
    add("s1_shot_edited_lock_follows", ok1, rows1, {"length_points": SHOT_POINTS, "roots_cm": SHOT_ROOT_CM},
          "%s moved 2 cm (and 5 cm, for the pictures) in sh020 / sh025, output 1 per frame: no point left behind, roots "
          "on the animated scalp within %s cm (p95) of the unedited lock's, strand length (DEFINITION 5) within 3 points "
          "of the unedited lock's at every frame (2 cm)" % (MOVE_LOCK, SHOT_ROOT_CM), evidence="shot_*.json")
    add("s3_shot_drawn_lock_follows_the_scalp", ok3, rows3, {"length": DRAWN_SHOT_LEN, "roots_cm": DRAWN_SHOT_ROOT_CM},
          "two drawn locks (on the bare skin farthest from every root, Helen's fringe; on the hair_back skin farthest "
          "from the roots, where the spike drew) with the animated scalp wired (the rest scalp's cut of the shot's "
          "head): strand length (median) within 2 % and roots within 0.1 cm (p95) of the animated skin at every "
          "frame", evidence="shot_*.json")
    add("s4_shot_drawn_lock_at_rest_without_the_scalp", ok4, rows4, "0.0 cm",
          "the animated scalp not wired, and wired with another point count: the drawn lock's strands are at rest, "
          "animated_scalp gives the panel's line, no error on the node, the mesh locks' deformed points equal what they "
          "are with no drawn lock (a lock that gave no skin)", evidence="shot_*.json")
    # s5: a scene with three inputs (every scene before v0.2b) opens and cooks as before
    rows5 = {}
    ok5 = bool(BASE)
    for tag, hip, frames in shots:
        f = frames.split(",")[1]
        if not BASE:
            break
        runs = [("base_0", BASE), ("new_0", SUITE), ("base_1", BASE), ("new_1", SUITE), ("base_2", BASE)]
        got = {t: sub("dump", su, hip, "s5_%s_%s" % (tag, t), f) for t, su in runs}
        if any("error" in g for g in got.values()):
            rows5[tag] = {"error": [g.get("error") for g in got.values() if "error" in g][0]}
            ok5 = False
            continue
        P = {t: np.load(OUT + "/s5_%s_%s_P.npy" % (tag, t), mmap_mode="r") for t, _su in runs}
        same_layout = all(np.array_equal(np.load(OUT + "/s5_%s_%s.npz" % (tag, t))["nv"],
                                         np.load(OUT + "/s5_%s_base_0.npz" % tag)["nv"]) for t, _su in runs)

        def gap(x, y):
            return float(np.abs(np.asarray(P[x]) - np.asarray(P[y])).max())
        bases, news = ["base_0", "base_1", "base_2"], ["new_0", "new_1"]
        base_spread = max(gap(x, y) for i, x in enumerate(bases) for y in bases[i + 1:])
        new_vs = {f"{n}_vs_{x}": gap(n, x) for n in news for x in bases}
        ulp = float(np.spacing(np.float32(np.abs(np.asarray(P["base_0"])).max())))
        limit = base_spread + 2 * ulp
        b0 = got["base_0"]
        rows5[tag] = {"frame": f, "strands_equal": all(g["strands"] == b0["strands"] for g in got.values()),
                      "same_points_a_strand": same_layout, "base_vs_base_max_cm": base_spread,
                      "new_vs_base_cm": new_vs, "float32_step_cm": ulp, "limit_cm": limit,
                      "errors": [e for n in news for e in got[n]["errors"]],
                      "new_warnings": sorted(set(w for n in news for w in got[n]["warnings"]) - set(b0["warnings"]))}
        ok5 = ok5 and rows5[tag]["strands_equal"] and same_layout and max(new_vs.values()) <= limit             and not rows5[tag]["errors"] and not rows5[tag]["new_warnings"]
    add("s5_three_inputs_cook_as_before", ok5, rows5, "the build before v0.2b's own spread + 2 float32 steps",
        "the shot scenes as saved (three inputs, the anim wired, Shot deform on, \"Fit lookup per lock\" off as an "
        "old scene opens), output 1 at a frame, 3 processes of the build before v0.2b and 2 of this one, "
        "interleaved: the same strands and points a strand, and this build's points as far from the old build's as "
        "the old build's runs lie from each other (DEFINITION 6: that spread + 2 float32 steps at the largest "
        "coordinate; the scenes sit ~330 m from the origin, a float32 step is 0.004 cm there)", evidence="s5_*.json")
    look_files = sorted(f for f in os.listdir(look) if f.endswith(".png")) if os.path.isdir(look) else []
    want = [f for f in look_files if f.startswith("shot_")]
    add("s2_shot_flipbooks_for_the_user", None if not want else True,
          {"dir": look, "pictures": want, "scenes": sorted(f for f in os.listdir(look) if f.endswith(".hiplc"))},
          "pictures exist", "flipbooks of the deformed frames of the lock moved 2 cm and 5 cm beside the unedited one "
          "(U4: the user judges them): the scenes are saved here, the pictures are made by the look step in the GUI "
          "(qc_capture.py); KNOWN until they exist")


# ---------------------------------------------------------------------------
def n_drawn():
    lid, stroke = n1_n2_drawn()
    n3_detect(lid, stroke)
    n4_delete_gives_skin_back()


# the drawn locks right after the edits of one lock: Draw's "only the locks that gave skin recook" is measured on
# states never cooked before (u2 draws at the same place)
order = [("e1", e1_identity), ("e0", e0_network_rule), ("e2", e2_speed), ("e3", e3_e4_follow), ("e5", e5_mesh_display),
         ("g1", g1_root), ("g2", g2_root_regions), ("u1", u1_undo), ("n", n_drawn), ("u2", u2_steps),
         ("u3", u3_several), ("d1", d1_redraw), ("d2", d2_reset), ("h1", h1_counts), ("h2", h2_resample)]
for tag, fn in order:
    if wanted(tag):
        C.run(tag + "_raised", fn)
        restore()
for tag, fn in (("p1", p1_survive), ("p2", p2_orphan), ("p3", p3_publish)):
    if wanted(tag):
        C.run(tag + "_raised", fn)
        restore()
for tag, fn in (("r1", r1_m1_base), ("r2", r2_qc), ("x1", x1_fullcook), ("s", s_shots)):
    if wanted(tag):
        C.run(tag + "_raised", fn)
C.meta["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
C.write(done=True)
print("DONE", C.path)
sys.stdout.flush()
os._exit(0)
