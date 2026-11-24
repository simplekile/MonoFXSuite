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
absolute). One check id per "Done when" line B2 and B5 (q1, grooming-check) can check in hython; the lines of the viewer state
(B3), the panel (B4) and the user's own try, are listed with
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
  7. "The tip's turn" in a shot: the angle between the direction of the last tenth of an edited strand and of the
     unedited strand of the same id (median over strands), at rest and at the frame.
  8. "The lock's moving frame": accept_v02b_moving.MovingFrame (its unedited spine and offset copies deformed by v0.1's
     capture, outside the node); offset_change and own_noise as defined there.
  6. "Cooks as before" (r1 Helen at rest, s5 the shot scenes as saved): NO BUILD IS BYTE-STABLE FROM RUN TO RUN.
     The build before v0.2b differs from itself by up to 0.0022 cm on Helen at rest, 0.05 cm on sh020 and 0.084 cm
     on sh025 at frame 30 (t79, t84), so this build is held to that build's own spread: 20 of its runs (t84's second
     round: with 7 a new run failed by chance about one time in 8), made from the committed base (a git archive of
     --base-commit), kept on disk beside it (<base>_samples/) and reused; each new run within the largest difference
     between any two of them + 2 float32 steps (`against_base`). Byte-equal pairs are reported.
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
SHOT_POINTS = 0.03            # (v0.1's deform, before U4 changed) 2 cm move: length within 3 points of the unedited's
SHOT_LENGTH = 0.02            # U4 changed: an edited lock's strand length within 2 % of rest at every frame
TIP_TURN_DEG = 5.0            # U4 changed: the tip's turn against the unedited lock within this of its rest value
EDIT_CASES = ("move_2cm", "move_5cm", "turn_25deg")
OFFSET_CHANGE_CM = 0.25       # the manager, 2026-11-22: offset change in the moving frame, p95, graded on sh025
OFFSET_GRADED_SHOTS = ("sh025",)
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
NEAR_STILL = 5.0      # e1's near case: every handle but the root off by this many config.SPINE_STILL


def e1_identity():
    """Handles equal to the measured spine's: since t84 (minor 1) the adapter writes nothing for them, so this part
    passes by construction (no write, no undo step, the hair byte-equal). The case that can fail is the near one:
    every handle but the root moved NEAR_STILL x config.SPINE_STILL along the width axis (just past the network's
    "no edit" guard, which would otherwise leave the spine untouched): the network's spine must be
    logic.edited_spine of those handles within IDENTITY_CM (the manager's line, t84), the other locks byte-equal.
    The lock's own strand points are reported, not graded."""
    rows = {}
    ok = True
    snap = snap_fn()
    for name in (MOVE_LOCK, BACK_LOCK):
        lid = ID[name]
        row = ROW0[lid]
        h = ga.lock_handles(node, [lid])[lid]
        res, steps, _ = labels_after(lambda: set_frame(lid, h["frame"]))
        _s, d, _r = cook_all()
        now = hair()
        same = same_strands(HAIR0, now)
        ident = {"handles": h["count"], "written": res["locks"], "undo_steps": steps, "message": res["message"],
                 "hair_max_move_cm": same}
        ok = ok and res["locks"] == [] and steps == 0 and same == 0.0 and "nothing changed" in res["message"]
        H = np.array(h["frame"], dtype=float)
        off = NEAR_STILL * config.SPINE_STILL
        H[1:, 1] += off                                 # frame axis 1: the width axis
        res2 = set_frame(lid, H)
        cook_all()
        got = edited_row(lid)
        want = logic.edited_spine(row["P"], row["tangent"], row["axis"], H, snap)
        dp = float(np.linalg.norm(got["P"] - want.P, axis=1).max() * U)
        moved_from_measured = float(np.linalg.norm(got["P"] - row["P"], axis=1).max() * U)
        now = hair()
        moved = same_strands({lid: HAIR0[lid]}, now)
        others = same_strands({k: v for k, v in HAIR0.items() if k != lid}, now)
        mine = {sid: P for sid, P in now.get(lid, [])}
        dist = np.concatenate([np.linalg.norm(mine[sid] - P, axis=1) for sid, P in HAIR0[lid]
                               if sid in mine and mine[sid].shape == P.shape] or [np.zeros(1)])
        # reported, not graded: the lock's hair is grown again from the moved spine and the per-lock loop is chaotic
        # in the last bit (a spine moved 0.0005 cm moved some of hair_back_20's strand points 0.5 cm in t79 run10q)
        near = {"offset_cm": off * U, "stored": res2["locks"] == [lid], "spine_vs_logic_max_cm": float("%.3g" % dp),
                "spine_moved_from_measured_max_cm": float("%.3g" % moved_from_measured),
                "strand_points_move_cm": {"max": float("%.3g" % moved), "p99": float("%.3g" % np.percentile(dist, 99)),
                                          "p50": float("%.3g" % np.percentile(dist, 50)),
                                          "share_over_0.01cm": round(float((dist > 0.01).mean()), 4)},
                "other_locks_max_move_cm": others}
        ok = ok and res2["locks"] == [lid] and dp <= IDENTITY_CM and others == 0.0
        rows[name] = {"identity": ident, "near": near, "recooked_identity": d}
        restore()
    add("e1_handles_equal_to_measured_move_nothing", ok, rows, IDENTITY_CM,
          "handles equal to the measured spine's (lock_handles' frame, default count): nothing written, no undo step, "
          "the hair byte-equal (by construction since t84: the adapter writes nothing for a result within "
          "config.SPINE_STILL); and the near case that can fail: every handle but the root %g x SPINE_STILL off along "
          "the width axis, the network's spine = logic.edited_spine within the limit, the other locks byte-equal; how "
          "far the lock's own strand points move is reported (the lock grows again from the moved spine, and the "
          "per-lock loop is chaotic in the last bit)" % NEAR_STILL)


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


# ---------------------------------------------------------------------------
# The build before v0.2b's own spread (t84: r1 and s5 graded against it). NO BUILD IS BYTE-STABLE FROM RUN TO RUN:
# the per-lock loop is chaotic in the last bit, so two processes of the same build cooking the same scene differ.
# Measured in t79 / t84: Helen at rest (r1's scene) up to 0.0022 cm between runs of the old build (0.0024 cm in t68,
# v0.1); sh025 at frame 30 up to 0.084 cm in 10 locks (hair_back_03 / 06 / 11 / 18, hair_bang_09 / 10 / 19,
# hair_base_02 / 04 / 13), sh020 0.05 cm. So "cooks as before" means: as far from the old build as its own runs lie
# from each other. BASE_SAMPLES processes of the old build are kept on disk beside it (<base>_samples/<base key>/
# <scene key>/), keyed by the base build (--base-commit, else its HDA's sha1) and the scene file's sha1, and reused
# by later runs; only the missing ones are made. The limits themselves never move.
# ---------------------------------------------------------------------------
# t84 recheck (second round): 20 samples, not 7 (with 7 a new run is the largest of 8 about one time in 8: sh025
# failed so by chance); the grade is the largest difference between any two of them + 2 float32 steps. Made from the
# COMMITTED base (git archive of --base-commit), not a rebuilt HDA.
BASE_SAMPLES = 20


def _sha1_file(path, n=12):
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:n]


def base_key() -> str:
    given = _arg("--base-commit")
    return given or "hda-" + _sha1_file(BASE + "/otls/mono_grooming.hdalc")


def base_cache(scene: str) -> str:
    """The folder of the old build's samples of this scene (made on first use)."""
    d = "%s_samples/%s/%s_%s" % (BASE.rstrip("/"), base_key(), os.path.splitext(os.path.basename(scene))[0],
                                 _sha1_file(scene))
    os.makedirs(d, exist_ok=True)
    return d


def dump_to(folder, tag, suite, hip, *extra) -> dict:
    """accept_v02b_sub.py dump into `folder`/<tag>.json (+ .npz, _P.npy): its JSON, kept when it is there."""
    outf = folder + "/" + tag + ".json"
    if os.path.isfile(outf) and os.path.isfile(folder + "/" + tag + "_P.npy"):
        with open(outf, encoding="utf-8") as fh:
            got = json.load(fh)
        if "error" not in got:
            return got
    with open(folder + "/" + tag + ".log", "w", encoding="utf-8", errors="replace") as fh:
        subprocess.run([HYTHON, HERE + "/accept_v02b_sub.py", "dump", suite, hip, outf, HERE] + [str(e) for e in extra],
                       stdout=fh, stderr=subprocess.STDOUT, timeout=5400)
    if not os.path.isfile(outf):
        return {"error": "no file: see " + folder + "/" + tag + ".log"}
    with open(outf, encoding="utf-8") as fh:
        return json.load(fh)


def against_base(scene_tag, hip, cache, new_tags, *extra) -> dict:
    """BASE_SAMPLES dumps of the old build (from `cache`, made when missing) and one of this build per tag in
    `new_tags` (into OUT, each a new process, interleaved with the missing base ones). Returns the numbers both r1
    and s5 grade: per lock counts, the old build's own spread (every pair), each new run's distance to every
    sample, byte-equal pairs, and errors / warnings of the new runs."""
    base_tags = ["base_%d" % i for i in range(BASE_SAMPLES)]
    missing = [t for t in base_tags if not (os.path.isfile(cache + "/" + t + ".json")
                                            and os.path.isfile(cache + "/" + t + "_P.npy"))]
    got, made = {}, []
    queue = list(new_tags)
    while missing or queue:                     # interleaved: a base sample, a new run, ...
        if missing:
            t = missing.pop(0)
            got[t] = dump_to(cache, t, BASE, hip, *extra)
            made.append(t)
        if queue:
            t = queue.pop(0)
            got[t] = dump_to(OUT, "%s_%s" % (scene_tag, t), SUITE, hip, *extra)
    for t in base_tags:
        if t not in got:
            got[t] = dump_to(cache, t, BASE, hip, *extra)
    errs = {t: g["error"] for t, g in got.items() if "error" in g}
    if errs:
        return {"error": errs}
    where = {t: (cache + "/" + t) for t in base_tags} | {t: (OUT + "/%s_%s" % (scene_tag, t)) for t in new_tags}
    P = {t: np.load(p + "_P.npy", mmap_mode="r") for t, p in where.items()}
    lay = {t: np.load(p + ".npz") for t, p in where.items()}

    def same_layout(a, b):
        return all(np.array_equal(lay[a][k], lay[b][k]) for k in ("nv", "lock", "sid"))

    def gap(a, b):
        if same_layout(a, b):
            return float(np.abs(np.asarray(P[a]) - np.asarray(P[b])).max())
        return same_strands(_npz_strands(where[a] + ".npz"), _npz_strands(where[b] + ".npz"))
    b0 = got[base_tags[0]]
    base_pairs = {f"{a}_vs_{b}": gap(a, b) for i, a in enumerate(base_tags) for b in base_tags[i + 1:]}
    new_vs = {n: {b: gap(n, b) for b in base_tags} for n in new_tags}
    spread = max(base_pairs.values())
    ulp = float(np.spacing(np.float32(np.abs(np.asarray(P[base_tags[0]])).max())))
    return {"samples_of_the_old_build": BASE_SAMPLES, "made_this_run": made, "cache": cache, "base_key": base_key(),
            "counts_per_lock_equal": all(got[n]["strands"] == b0["strands"] for n in new_tags),
            "base_counts_per_lock_equal": all(got[b]["strands"] == b0["strands"] for b in base_tags),
            "same_points_a_strand": all(same_layout(n, base_tags[0]) for n in new_tags),
            "old_build_spread_cm": spread, "old_build_pairs_cm": base_pairs,
            "old_build_byte_equal_pairs": sorted(k for k, v in base_pairs.items() if v == 0.0),
            "new_vs_old_cm": new_vs, "new_worst_cm": {n: max(v.values()) for n, v in new_vs.items()},
            "new_byte_equal_to": {n: sorted(b for b, d in v.items() if d == 0.0) for n, v in new_vs.items()},
            "float32_step_cm": ulp, "limit_cm": spread + 2 * ulp,
            "cook_s": {t: g.get("cook_s") for t, g in got.items()},
            "errors": [e for n in new_tags for e in got[n]["errors"]],
            "new_warnings": sorted(set(w for n in new_tags for w in got[n]["warnings"]) - set(b0["warnings"])),
            "data_sha1_base": b0.get("data_sha1"), "strands": sum(b0["strands"].values())}


def _graded(r) -> bool:
    return "error" not in r and r["counts_per_lock_equal"] and r["base_counts_per_lock_equal"] \
        and max(r["new_worst_cm"].values()) <= r["limit_cm"] and not r["errors"] and not r["new_warnings"]


def r1_m1_base():
    if not BASE:
        add("r1_no_edit_is_the_groom_before_v02b", False, None, "--base <suite>", note="not run: no --base")
        return
    # the scene saved by the old build is made once and kept with its samples (a new save would be a new key)
    keep = "%s_samples/%s/saved_by_base_of_%s_%s" % (BASE.rstrip("/"), base_key(),
                                                     os.path.splitext(os.path.basename(SCENE))[0], _sha1_file(SCENE))
    os.makedirs(keep, exist_ok=True)
    hip = keep + "/saved_by_base.hiplc"
    if not os.path.isfile(hip):
        hython([HERE + "/accept_v02a_sub.py", "makeold", BASE, SCENE, keep + "/saved_by_base.json", HERE],
               "saved_by_base.log")
    r = against_base("r1", hip, base_cache(hip), ["new_0", "new_1", "new_2"])
    add("r1_no_edit_is_the_groom_before_v02b", _graded(r), r,
        {"counts": "equal per lock", "every_new_run_cm": "within the largest difference between any two of the old build's %d runs + 2 float32 steps" % BASE_SAMPLES},
        "a fresh groom made and saved by the build before v0.2b (--base), opened and cooked (output 1 at rest) by it "
        "(%d processes, kept on disk and reused) and by this build (3 processes): every lock's strand count equal, and "
        "each new run's points within the old build's own spread (every pair of its runs) + 2 float32 steps of every "
        "one of its runs; byte-equal pairs are reported, not required: NO BUILD IS BYTE-STABLE FROM RUN TO RUN (the old "
        "build's own runs differ by up to 0.0022 cm on Helen, t84 item 3)" % BASE_SAMPLES,
        evidence="r1_*.json, %s" % r.get("cache", ""))
    got = sub("edit6", SUITE, hip, "m1_schema6")
    base_sha = r.get("data_sha1_base")
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


QC_EDITED_LOCKS = {"moved": MOVE_LOCK, "rotated": "hair_bang_05", "redrawn": "hair_bang_15"}


def q1_qc_edited():
    """grooming-check (qc_metrics.py, limits as they are) on a groom with a moved, a rotated, a redrawn and a drawn
    lock: passes measured against the carried mesh, its limits are the ones of the groom with no edit (r2's report;
    the drawn lock adds its own two checks), the edited locks are listed with their mesh numbers and the drawn lock
    with "do not apply". The same groom against the modelled mesh is run beside it for the record (not a condition:
    an edited lock is bent away from its modelled mesh on purpose)."""
    lid = ID[MOVE_LOCK]
    set_frame(lid, alib.bend(ROW0[lid], default_k(lid), 2.0, U))
    lid = ID[QC_EDITED_LOCKS["rotated"]]
    ga.rotate_points(node, [lid], ga.lock_handles(node, [lid])[lid]["axes"][2], 25.0)
    lid = ID[QC_EDITED_LOCKS["redrawn"]]
    R = np.array(ga.lock_handles(node, [lid])[lid]["axes"])
    P = ROW0[lid]["P"]
    Q = logic.rotate_about_root(P, R[2], -20.0) + R[1] * (np.linspace(0, 1, len(P)) ** 2 * 2.0 / U)[:, None]
    redraw = ga.redraw_lock(node, lid, Q.tolist())
    _spot, stroke = _drawn_setup()
    drawn = ga.draw_lock(node, stroke, 2.0, 0.6, 0.3)
    cook_all()
    hip = OUT + "/q1_edited.hiplc"
    hou.hipFile.save(hip)
    reps = {}
    for mode in ("carried", "modelled"):
        out = OUT + "/qc_edited_" + mode
        hython([QC, SUITE, hip, out, "--mesh", mode] + (["--ref", REF] if REF else []), "qc_edited_%s.log" % mode)
        path = out + "/qc_report.json"
        reps[mode] = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else None
    rep = reps["carried"]
    if rep is None:
        add("q1_grooming_check_on_edited_groom", False, "no qc_report.json", note="see qc_edited_carried.log")
        return
    base_path = OUT + "/qc_noedit/qc_report.json"
    base = {c["check"]: c["limit"] for c in json.load(open(base_path, encoding="utf-8"))["checks"]}         if os.path.isfile(base_path) else None
    limits = {c["check"]: c["limit"] for c in rep["checks"]}
    moved_limits = None if base is None else {k: [limits.get(k), v] for k, v in base.items() if limits.get(k) != v}
    extra = sorted(set(limits) - set(base or limits))
    failed = [c["check"] for c in rep["checks"] if not c["pass"]]
    names = set(QC_EDITED_LOCKS.values())
    listed = {r["name"] for r in rep.get("edited_locks", [])}
    drawn_rows = rep.get("drawn_locks", [])
    drawn_ok = any(r["name"] == drawn["name"] and "do not apply" in r.get("mesh_checks", "") for r in drawn_rows)

    def edited_numbers(r):
        return None if r is None else {e["name"]: {k: r3(e.get(k)) for k in ("dmax_p95_cm", "dtip_p95_cm", "other_mean",
                                                                         "coverage", "width_tip", "tip_center_off",
                                                                         "outside_worst")}
                                     for e in r.get("edited_locks", []) if e["name"] in names}
    modelled = reps["modelled"]
    ok = rep["passed"] and not failed and moved_limits == {} and set(extra) <= {"drawn_root_skin_worst_cm",
                                                                               "drawn_width_off_worst"}         and names <= listed and drawn_ok and rep.get("mesh", "").startswith("carried")
    add("q1_grooming_check_on_edited_groom", ok,
        {"passed": rep["passed"], "failed": failed, "mesh": rep.get("mesh"), "limits_moved": moved_limits,
         "checks_added": extra, "edited_listed": sorted(listed), "drawn": drawn_rows,
         "edited_against_carried": edited_numbers(rep), "edited_against_modelled": edited_numbers(modelled),
         "modelled_failed": None if modelled is None else [c["check"] for c in modelled["checks"] if not c["pass"]],
         "redraw_gap_cm": r3(redraw.get("gap_cm")), "drawn_lock": drawn["name"]},
        "passed, limits as with no edit",
        "grooming-check on the groom with %s moved 2 cm at the tip, %s turned 25 deg about its root, %s redrawn and a "
        "lock drawn on bare skin: passes against the carried mesh with every limit equal the groom with no edit's "
        "(qc_noedit, r2; needs --t55), the drawn lock's mesh checks said not to apply; the modelled mesh run beside it "
        "for the record" % (MOVE_LOCK, QC_EDITED_LOCKS["rotated"], QC_EDITED_LOCKS["redrawn"]),
        evidence="qc_edited_carried/qc_report.json, qc_edited_modelled/qc_report.json",
        note="" if base is not None else "no qc_noedit report (run r2 first): limits not compared")
    restore()


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
    # sh020: t84's frames (10, 25, 75, 105, 135: hair_bang_05's piece bends there) and the earlier ones
    shots = [(tag, hip, frames) for tag, hip, frames in (("sh020", SH020, "10,25,30,60,75,90,105,120,135"),
                                                         ("sh025", SH025, "15,30,45")) if hip]
    if not shots:
        for item in ("s1_shot_edited_lock_follows", "s3_shot_drawn_lock_follows_the_scalp",
                     "s4_shot_drawn_lock_at_rest_without_the_scalp", "s5_three_inputs_cook_as_before"):
            add(item, False, None, "--sh020 / --sh025", note="not run: no shot scene given")
        return
    look = LOOK or OUT + "/look"
    os.makedirs(look, exist_ok=True)
    got = {tag: sub("shot", SUITE, hip, "shot_" + tag, frames, look) for tag, hip, frames in shots}
    rows1, rows1b, rows3, rows4 = {}, {}, {}, {}
    ok1 = ok3 = ok4 = True
    for tag, g in got.items():
        if "error" in g:
            rows1[tag] = rows3[tag] = rows4[tag] = {"error": g["error"]}
            ok1 = ok3 = ok4 = False
            continue
        rows1[tag] = g["edited"]
        # t84 B-3: hair_bang_05 moved 2 cm too (accept_v02b_shot.MORE_LOCKS), graded the same way
        locks = [(g["edited"], "")] + [(e, name + ":") for name, e in g.get("edited_more", {}).items()]
        for name, e in g.get("edited_more", {}).items():
            rows1[tag + "_" + name] = e
        for e, key in locks:
            for f, row in e["frames"].items():
                ok1 = ok1 and row["unedited"]["left_behind"] == 0
                for case in [c for c in row if c != "unedited"]:
                    c = row[case]
                    c["tip_turn_change_deg"] = r3(abs(c["tip_turn_frame_deg"] - c["tip_turn_rest_deg"]))
                    # the plan's line before U4 changed, for the record (t84 B-3 failed it at 3.66 points)
                    c["length_points_from_unedited"] = r3(abs(c["length_p50"] - row["unedited"]["length_p50"]))
                    # the plan (2026-11-23): the edited median within 2 % of the unedited lock's at that frame (the
                    # animation stretches the pieces); against rest it is in the row (length_p50)
                    c["length_vs_unedited"] = r3(c["length_p50"] / max(row["unedited"]["length_p50"], 1e-9))
                    ok1 = ok1 and c["left_behind"] == 0 and abs(c["length_vs_unedited"] - 1) <= SHOT_LENGTH \
                        and c["roots_p95_cm"] <= row["unedited"]["roots_p95_cm"] + SHOT_ROOT_CM \
                        and c["tip_turn_change_deg"] <= TIP_TURN_DEG
                    noise = row["unedited"]["own_noise"]["p95_cm"]
                    rows1b.setdefault(tag, {}).setdefault(f, {})[key + case] = {
                        "change_p95_cm": c["moving_frame"]["change_p95_cm"],
                        "change_max_cm": c["moving_frame"]["change_max_cm"], "unedited_own_noise_p95_cm": noise,
                        "ratio_to_noise": r3(c["moving_frame"]["change_p95_cm"] / max(noise, 1e-9))}
        rows3[tag] = g["drawn_wired"]
        ok3 = ok3 and g["drawn_wired"]["scalp_ok"] and all(
            abs(r["length_p50"] - 1) <= DRAWN_SHOT_LEN and r["roots_p95_cm"] <= DRAWN_SHOT_ROOT_CM
            for place in g["drawn_wired"]["places"].values() for r in place["frames"].values())
        rows4[tag] = g["drawn_unwired"]
        ok4 = ok4 and all(v["drawn_at_rest_max_cm"] == 0.0 and v["message"] and not v["errors"]
                          and v["mesh_locks_same_as_without_the_drawn_lock_cm"] == 0.0
                          for v in g["drawn_unwired"].values())
    add("s1_shot_edited_lock_keeps_its_shape", ok1, rows1,
        {"length": SHOT_LENGTH, "roots_cm": SHOT_ROOT_CM, "tip_turn_deg": TIP_TURN_DEG},
        "U4 as changed by the user (2026-11-22): %s moved 2 cm, 5 cm and turned 25 deg, and hair_bang_05 moved 2 cm "
        "(t84 B-3), in sh020 / sh025, output 1 per frame: no point left behind; strand length (median) within 2 %% of the "
        "unedited lock's at that frame (the plan, 2026-11-23; against rest reported); roots on the "
        "animated scalp within %s cm (p95) of the unedited lock's; the tip's turn against the unedited lock "
        "(DEFINITION 7) within %s deg of its rest value: no hook" % (MOVE_LOCK, SHOT_ROOT_CM, TIP_TURN_DEG),
        evidence="shot_*.json")
    # the manager's decision (2026-11-22, plan ade1093): no stretch wins over the same offset; the offset change is
    # graded on sh025 (the piece moves rigidly), on sh020 (the piece bends) reported per frame, not graded
    graded = {sh: rows for sh, rows in rows1b.items() if sh in OFFSET_GRADED_SHOTS}
    ok1b = bool(graded) and all(v["change_p95_cm"] is not None and v["change_p95_cm"] <= OFFSET_CHANGE_CM
                                for rows in graded.values() for cases in rows.values() for v in cases.values())
    add("s1b_shot_edited_offset_in_the_moving_frame", ok1b,
        {"graded": graded, "reported_not_graded": {sh: r for sh, r in rows1b.items() if sh not in OFFSET_GRADED_SHOTS}},
        {"change_p95_cm": OFFSET_CHANGE_CM, "graded_on": list(OFFSET_GRADED_SHOTS)},
        "the edited lock's offset from the unedited lock in the lock's moving frame (DEFINITION 8), its change from rest "
        "per frame, p95, for 2 cm, 5 cm and 25 deg: graded on sh025 (the fringe moves rigidly with the head), reported on "
        "sh020 where the piece bends (no stretch wins over the same offset there: the manager, 2026-11-22)",
        evidence="shot_*.json")
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
        if not BASE:
            break
        f = {"sh020": "60", "sh025": "30"}.get(tag, frames.split(",")[1])      # the frames s5 always used
        cache = base_cache(hip) + "/f" + f
        os.makedirs(cache, exist_ok=True)
        rows5[tag] = against_base("s5_" + tag, hip, cache, ["new_0", "new_1"], f)
        rows5[tag]["frame"] = f
        # the shot deform replaced v0.1's (the user's decision, 2026-11-22): a scene with three inputs still opens and
        # cooks the same strands, the same points a strand and no error; how far it moved from v0.1 is reported (s6
        # grades the deform itself); "within the old build's own spread" stays r1's, at rest
        r5 = rows5[tag]
        ok5 = ok5 and "error" not in r5 and r5["counts_per_lock_equal"] and r5["base_counts_per_lock_equal"] \
            and r5.get("same_points_a_strand", False) and not r5["errors"] and not r5["new_warnings"]
        r5["moved_from_v01_reported_cm"] = r5.get("new_worst_cm")
    add("s5_three_inputs_cook_as_before", ok5, rows5, "the same strands and points a strand, no error",
        "the shot scenes as saved (three inputs, the anim wired, Shot deform on, \"Fit lookup per lock\" off as an "
        "old scene opens), output 1 at a frame, %d processes of the build before v0.2b (kept on disk, reused) and 2 "
        "of this one: the same strands, the same points a strand, no error or new warning. The points moved by the "
        "shot deform that replaced v0.1's (the user's decision 2026-11-22; s6 grades it): their distance to v0.1 is "
        "reported, not graded (it was: within the old build's own spread + 2 float32 steps)" % BASE_SAMPLES,
        evidence="s5_*.json and the samples' folder")
    look_files = sorted(f for f in os.listdir(look) if f.endswith(".png")) if os.path.isdir(look) else []
    want = [f for f in look_files if f.startswith("shot_")]
    add("s2_shot_flipbooks_for_the_user", None if not want else True,
          {"dir": look, "pictures": want, "scenes": sorted(f for f in os.listdir(look) if f.endswith(".hiplc"))},
          "pictures exist", "flipbooks of the deformed frames of the lock moved 2 cm and 5 cm beside the unedited one "
          "(U4: the user judges them): the scenes are saved here, the pictures are made by the look step in the GUI "
          "(qc_capture.py); KNOWN until they exist")


# ---------------------------------------------------------------------------
# s6: the shot deform that replaces v0.1's (B-3 decided by the user, 2026-11-22; the plan's "The cause, and the
# deform that replaces v0.1's in shots"): accept_v02b_deform.py on this build and on the build before v0.2b (--base,
# v0.1's Point Deform), every lock of sh020 and sh025. Graded: 0 folds by the plan's rule (the hair against its own
# animated piece); unedited strand length p95 within 5 % where the piece itself does not fold; edited locks (tip 2 cm,
# turn 25 deg; every fringe lock of sh020, t84's 9 locks of sh025) median length within 2 % and tip turn within 5 deg
# of rest where the piece does not fold (reported where it does); roots off the animated scalp no further than v0.1's
# + SHOT_ROOT_CM; no point left behind; no node error. Reported: the move against v0.1 (p95 per lock-frame), the hair
# against its piece (now - rest), frame to frame against the piece, the frame cost against v0.1's.
# ---------------------------------------------------------------------------
# the graded frames, and every consecutive pair of the shot's playbar for the frame-to-frame line (the plan, 2026-11-23: a
# window of 5 frames a shot (73-77, 20-24) missed 41 pairs of sh020 over the line, worst 3.5 x; about 1 s a frame)
DEFORM_SHOTS = {"sh020": ("10,25,45,60,75,105,135", ",".join(str(f) for f in range(0, 121))),
                "sh025": ("5,20,25,30,40,50", ",".join(str(f) for f in range(0, 46)))}
DEFORM_SH025_LOCKS = ("hair_bang_05", "hair_bang_11", "hair_bang_17", "hair_back_05", "hair_back_20", "hair_back_01",
                      "hair_back_13", "hair_base_07", "hair_base_09")
DEFORM_LENGTH_P95 = 0.05     # unedited strand length within this of its piece's over its span, p95 (the plan, 2026-11-23)
DEFORM_ROOT_CM = 0.1         # roots off the animated scalp, p95 a lock-frame: the drawn lock's limit (the plan, 2026-11-23)
DEFORM_COST_PROBLEM_S = 1.5  # a frame of output 1 over this is reported as a problem (the plan)
DEFORM_JOINT_DEG = 30.0      # a lock's joint turn over rest in the root half, p95 of its strands (the plan, 2026-11-23),
                             # graded on sh025 (its 13 back locks read up to 58.6 before the root-zone rule); sh020
                             # reported: hair_bang_20's crumpling tip is over it in any variant
DEFORM_F2F = 1.4             # a lock's largest hair move from one frame to the next over its piece's (the plan, 2026-11-23)


def deform_run(suite, hip, tag, frames, edit, consec):
    outf = OUT + "/" + tag + ".json"
    if os.path.isfile(outf):
        os.remove(outf)
    hython([HERE + "/accept_v02b_deform.py", suite, hip, outf, frames, ",".join(edit), consec], tag + ".log",
           timeout=10800)
    if not os.path.isfile(outf):
        return {"error": "no file: see " + OUT + "/" + tag + ".log"}
    with open(outf, encoding="utf-8") as fh:
        return json.load(fh)


def s6_deform():
    shots = [(t, h) for t, h in (("sh020", SH020), ("sh025", SH025)) if h]
    if not shots or not BASE:
        add("s6_shot_deform_follows_each_lock_s_own_piece", False, None, "--sh020 / --sh025 and --base",
            note="not run: needs the shot scenes and the build before v0.2b")
        return
    rows, ok = {}, True
    for tag, hip in shots:
        frames, consec = DEFORM_SHOTS[tag]
        edit = sorted(n for n in NAMES.values() if n.startswith("hair_bang_")) if tag == "sh020" else \
            [n for n in DEFORM_SH025_LOCKS if n in ID]
        new = deform_run(SUITE, hip, "s6_%s_new" % tag, frames, edit, consec)
        old = deform_run(BASE, hip, "s6_%s_v01" % tag, frames, [], "")
        if "error" in new or "error" in old:
            rows[tag] = {"new": new.get("error"), "v01": old.get("error")}
            ok = False
            continue
        lf = [(n, f, r) for n, v in new["unedited"].items() for f, r in v.items()]
        ov = old["unedited"]
        folds = [(n, f) for n, f, r in lf if r["fold"]]
        v01_folds = [(n, f) for n, v in ov.items() for f, r in v.items() if r["fold"]]
        # the plan (2026-11-23): length against the piece's own over the strand's span; against rest reported
        stretch = [(n, f, round(r["len_vs_piece_p95_off"], 4), round(r["len_p95"], 4), round(r["piece_span_ratio_p50"], 4))
                   for n, f, r in lf if r["len_vs_piece_p95_off"] > DEFORM_LENGTH_P95]
        v01_stretch = sum(1 for n, f, r in lf if ov.get(n, {}).get(f, {}).get("len_vs_piece_p95_off", 0) > DEFORM_LENGTH_P95)
        # the tip zone (last 10 % of each strand) against the piece over its span: the same line (the plan, 2026-11-23)
        tip = [(n, f, round(r["tip_vs_piece_p95_off"], 4)) for n, f, r in lf if r["tip_vs_piece_p95_off"] > DEFORM_LENGTH_P95]
        # reported: the same line with the piece's surface under each strand as the reference
        surface = [(n, f, round(r["len_vs_surface_p95_off"], 4)) for n, f, r in lf
                   if r["len_vs_surface_p95_off"] > DEFORM_LENGTH_P95]
        vs_rest = {"new": sum(1 for n, f, r in lf if not r["piece_folds"] and r["len_p95"] > 1 + DEFORM_LENGTH_P95),
                   "v01": sum(1 for n, f, r in lf if not r["piece_folds"]
                              and ov.get(n, {}).get(f, {}).get("len_p95", 0) > 1 + DEFORM_LENGTH_P95)}
        # roots within the drawn lock's limit of the animated scalp; against v0.1 reported
        roots = [(n, f, round(r["roots_skin_p95_cm"], 4)) for n, f, r in lf
                 if r["roots_skin_p95_cm"] is not None and r["roots_skin_p95_cm"] > DEFORM_ROOT_CM]
        rdiff = np.array([r["roots_skin_p95_cm"] - ov[n][f]["roots_skin_p95_cm"] for n, f, r in lf
                          if n in ov and f in ov[n] and r["roots_skin_p95_cm"] is not None
                          and ov[n][f]["roots_skin_p95_cm"] is not None])
        rworst = max(((r["roots_skin_p95_cm"] or 0.0), n, f) for n, f, r in lf)
        v01_roots = sum(1 for v in ov.values() for r in v.values()
                        if r["roots_skin_p95_cm"] is not None and r["roots_skin_p95_cm"] > DEFORM_ROOT_CM)
        joint = [(n, f, round(r["joint_turn_p95_deg"], 1)) for n, f, r in lf if r["joint_turn_p95_deg"] > DEFORM_JOINT_DEG]
        left = sum(r["left_behind"] for _, _, r in lf)
        ed_fail, ed_report = [], []
        ed_rest = []
        for n, v in new["edited"].items():
            for case, fr in v.items():
                for f, r in fr.items():
                    # the plan (2026-11-23): median length within 2 % of the unedited lock's at the same frame
                    un = new["unedited"].get(n, {}).get(f, {}).get("len_p50", 1.0)
                    off = abs(r["len_p50"] / max(un, 1e-9) - 1)
                    bad = off > SHOT_LENGTH or r["tip_turn_change"] > TIP_TURN_DEG
                    if bad:
                        (ed_report if r["piece_folds"] else ed_fail).append(
                            (n, case, f, round(r["len_p50"], 4), round(un, 4), round(r["tip_turn_change"], 2)))
                    if abs(r["len_p50"] - 1) > SHOT_LENGTH:
                        ed_rest.append((n, case, f, round(r["len_p50"], 4)))
        # the move against v0.1, every 10th strand
        A = np.load(OUT + "/s6_%s_new_samples.npz" % tag)
        B = np.load(OUT + "/s6_%s_v01_samples.npz" % tag)
        mv = {}
        for k in A.files:
            if k in B.files and A[k].shape == B[k].shape:
                f, lid, _s = k.split("|")
                mv.setdefault((f, lid), []).append(np.linalg.norm(A[k] - B[k], axis=1))
        mvp = np.array([float(np.percentile(np.concatenate(v), 95)) for v in mv.values()])
        tp = np.array([r["to_piece_now_cm"] - r["to_piece_rest_cm"] for _, _, r in lf])
        cons = [(r["hair_max_cm"] / max(r["piece_max_cm"], 1e-6), n, f) for n, v in new["consecutive"].items()
                for f, r in v.items()]
        jumps = sorted([(round(a, 3), n, f) for a, n, f in cons if a > DEFORM_F2F], reverse=True)
        cost_new, cost_old = list(new["cost_s"].values()), list(old["cost_s"].values())
        good = not folds and not stretch and not tip and not jumps and not roots and not left and not ed_fail \
            and not new.get("errors") and not (joint and tag == "sh025")
        ok = ok and good
        rows[tag] = {
            "pass": good, "lock_frames": len(lf), "folds": folds, "v01_folds": len(v01_folds),
            "length_vs_piece_over": stretch, "v01_length_vs_piece_over": v01_stretch,
            "tip_zone_vs_piece_over": tip, "length_vs_surface_over_reported": surface,
            "frame_to_frame_over_%g" % DEFORM_F2F: jumps,
            "length_vs_rest_p95_over_reported": vs_rest,
            "roots_over_%gcm" % DEFORM_ROOT_CM: roots, "v01_roots_over": v01_roots,
            "joint_turn_over_%g" % DEFORM_JOINT_DEG: joint, "joint_turn_graded": tag == "sh025",
            "joint_turn_worst_deg": max(r["joint_turn_p95_deg"] for _, _, r in lf),
            "roots_worst": {"cm": rworst[0], "lock": rworst[1], "frame": rworst[2]},
            "roots_minus_v01_cm": {"median": float(np.median(rdiff)), "p95": float(np.percentile(rdiff, 95)),
                                   "max": float(rdiff.max())} if len(rdiff) else None, "left_behind": left,
            "edited_cases": sum(len(fr) for v in new["edited"].values() for fr in v.values()),
            "edited_failing": ed_fail, "edited_reported_piece_folds": ed_report,
            "edited_vs_rest_over_2pc_reported": ed_rest,
            "move_vs_v01_p95_cm": {"median": float(np.median(mvp)), "p95": float(np.percentile(mvp, 95)),
                                   "max": float(mvp.max())} if len(mvp) else None,
            "to_piece_now_minus_rest_cm": {"median": float(np.median(tp)), "max": float(tp.max())},
            "frame_to_frame_hair_over_piece": {"median": float(np.median([c[0] for c in cons])) if cons else None,
                                               "worst": sorted(cons, reverse=True)[:5]},
            "cost_s": {"new": cost_new, "v01": cost_old,
                       "over_%gs" % DEFORM_COST_PROBLEM_S: [c for c in cost_new if c > DEFORM_COST_PROBLEM_S]},
            "errors": new.get("errors"), "deform_problem": new.get("deform_problem")}
    add("s6_shot_deform_follows_each_lock_s_own_piece", ok, rows,
        {"folds": 0, "unedited_length_vs_piece_p95": DEFORM_LENGTH_P95, "tip_zone_vs_piece_p95": DEFORM_LENGTH_P95,
         "frame_to_frame_over_piece": DEFORM_F2F, "joint_turn_over_rest_sh025_deg": DEFORM_JOINT_DEG, "edited_length_vs_unedited": SHOT_LENGTH,
         "tip_turn_deg": TIP_TURN_DEG, "roots_cm": DEFORM_ROOT_CM, "left_behind": 0},
        "every lock of sh020 (frames %s) and sh025 (%s), this build against the build before v0.2b (v0.1's Point "
        "Deform): no fold of the hair against its own animated piece (turning over rest minus the piece's over 90 deg, "
        "or a new kink over 90 the piece does not have); the joint turn over rest in the root half (p95 of a lock's strands) "
        "under 30 deg on sh025 (sh020 reported); unedited: each strand's length ratio within %g %% (p95) of its "
        "piece's length ratio over the strand's span (the plan, 2026-11-23: the animation stretches the pieces; against "
        "rest reported), and the same for each strand's last 10 %%; the hair's largest move from one frame to the next "
        "within %g x its piece's on every consecutive pair of each shot's playbar; edited locks (tip 2 cm, turn 25 deg) median "
        "length within %g %% of the unedited lock's at the "
        "same frame and tip turn within %g deg of rest where the piece does not fold (reported where it does; against rest "
        "reported); roots within %g cm (p95) of the animated scalp (the drawn lock's limit; against v0.1 reported); "
        "nothing left behind. Reported: the move against v0.1, the hair against its piece, frame to frame against the "
        "piece, the frame cost (over %g s a problem)"
        % (DEFORM_SHOTS["sh020"][0], DEFORM_SHOTS["sh025"][0], DEFORM_LENGTH_P95 * 100, DEFORM_F2F, SHOT_LENGTH * 100,
           TIP_TURN_DEG, DEFORM_ROOT_CM, DEFORM_COST_PROBLEM_S), evidence="s6_*.json")


def v2_names_ids_strokes():
    """t84 recheck (second round), against the node: names with a backslash, a backtick, `$`, a quote and a newline
    stored and read back as given (a drawn lock's name and a density layer's name), the node cooking; a duplicate id
    counts once (rotate [L, L] 30 deg = rotate [L] 30 deg, scale [L, L] x 2 = x 2); a huge / tiny axis turns as
    (1, 1, 0); a stroke of 100,000 points is thinned to config.STROKE_POINTS_MAX and drawn in a few seconds."""
    lid = ID[MOVE_LOCK]
    names = ["c" + chr(92), "wip" + chr(92) + "old", "a`b`c", "cost $5", "a${HIP}b", 'q"uote', "new" + chr(10) + "line"]
    spot, stroke = _drawn_setup()
    rows, ok = {}, True
    for nm in names:
        r = {}
        try:
            d = ga.draw_lock(node, stroke, name=nm)
            lay = ga.mask_add(node, name=nm)
            cook_all()
            back = ga.read_data(node)
            r = {"drawn_name_back": back.lock(d["id"]).name == nm,
                 "layer_name_back": back.mask(lay).name == nm, "errors": lib.node_errors(node)}
            ga.delete_drawn_locks(node, [d["id"]])
            ga.mask_remove(node, lay)
        except Exception as e:      # noqa: BLE001
            r = {"raised": "%s: %s" % (type(e).__name__, e)}
        r["pass"] = r.get("drawn_name_back") is True and r.get("layer_name_back") is True and not r.get("errors")
        ok = ok and r["pass"]
        rows[repr(nm)] = r

    def spine_of(i):
        return np.array(ga.lock_handles(node, [i])[i]["frame"], dtype=float)
    ax = ga.lock_handles(node, [lid])[lid]["axes"][2]
    dup = {}
    for tag, once, twice in (("rotate_30", lambda: ga.rotate_points(node, [lid], ax, 30.0),
                              lambda: ga.rotate_points(node, [lid, lid, float(lid)], ax, 30.0)),
                             ("scale_2", lambda: ga.scale_points(node, [lid], 2.0),
                              lambda: ga.scale_points(node, [lid, lid], 2.0))):
        once()
        a = spine_of(lid)
        ga.reset_points(node, [lid])
        twice()
        b = spine_of(lid)
        ga.reset_points(node, [lid])
        dup[tag] = float(np.abs(a - b).max()) * U
    ok_dup = all(v <= 1e-9 for v in dup.values())
    axis = {}
    ga.rotate_points(node, [lid], (1.0, 1.0, 0.0), 30.0)
    ref = spine_of(lid)
    ga.reset_points(node, [lid])
    for tag, a in (("1e200", (1e200, 1e200, 0.0)), ("1e-160", (1e-160, 1e-160, 0.0))):
        ga.rotate_points(node, [lid], a, 30.0)
        axis[tag] = float(np.abs(spine_of(lid) - ref).max()) * U
        ga.reset_points(node, [lid])
    ok_axis = all(v <= 1e-6 for v in axis.values())
    S = np.asarray(stroke, dtype=float)
    k = np.linspace(0, len(S) - 1, 100000)          # the drawn stroke, 100,000 points along it
    big = np.stack([np.interp(k, np.arange(len(S)), S[:, c]) for c in range(3)], 1)
    t0 = time.perf_counter()
    d = ga.draw_lock(node, big.tolist())
    big_s = round(time.perf_counter() - t0, 3)
    cook_all()
    ga.delete_drawn_locks(node, [d["id"]])
    ok_big = big_s <= 5.0 and d["count"] <= config.HANDLES_MAX
    add("v2_names_ids_axis_strokes", ok and ok_dup and ok_axis and ok_big,
        {"names": rows, "duplicate_ids_cm": dup, "axis_scale_cm": axis,
         "stroke_100000_points": {"points": int(len(big)), "seconds": big_s, "handles": d["count"],
                                  "thinned_to": config.STROKE_POINTS_MAX}},
        "names back as given, duplicates = once (0 cm), huge / tiny axis = (1,1,0) within 1e-6 cm, 100,000-point "
        "stroke <= 5 s",
        "t84 recheck (second round): groom_data read raw, a drawn lock's and a density layer's name with a backslash, "
        "a backtick, $, a quote, a newline; one edit per lock a call; the rotate axis divided by its largest component "
        "first; a stroke over config.STROKE_POINTS_MAX points thinned before the fit")


def v1_bad_input():
    """t84 B-1 / B-2 / minors 1-3: every bad input the independent check found, against the node. Each must raise
    ValueError (or, for a result equal to what is there, change nothing) with groom_data's text and the undo list
    as they were, no `NaN` / `Infinity` in the text, and the node cooking without an error after."""
    lid, back = ID[MOVE_LOCK], ID[BACK_LOCK]
    h = ga.lock_handles(node, [lid])[lid]
    H = np.array(h["frame"], dtype=float)
    W = np.array(h["points"], dtype=float)
    axes = h["axes"]
    spot, stroke = _drawn_setup()
    drawn = ga.draw_lock(node, stroke)
    cook_all()
    d_id = drawn["id"]

    def bad(rows, i, j, v):
        X = rows.copy()
        X[i, j] = v
        return X.tolist()
    far = (np.asarray(stroke[0]) + np.asarray(ga.lock_handles(node, [d_id])[d_id]["axes"][0]) * 1e4).tolist()
    raises = {
        "set_points_nan_frame": lambda: set_frame(lid, bad(H, 2, 1, float("nan"))),
        "set_points_inf_points": lambda: ga.set_points(node, {lid: bad(W, 1, 0, float("inf"))}),
        "set_points_minus_inf_drawn": lambda: ga.set_points(node, {d_id: bad(np.array(
            ga.lock_handles(node, [d_id])[d_id]["points"]), 1, 2, -float("inf"))}),
        "set_points_100_handles": lambda: set_frame(lid, np.linspace(H[0], H[-1], 100).tolist()),
        "set_points_3_handles": lambda: set_frame(lid, H[:3].tolist()),
        "set_points_2_columns": lambda: set_frame(lid, H[:, :2].tolist()),
        "set_points_tip_10m_away": lambda: set_frame(lid, bad(H, len(H) - 1, 0, 1000.0 / U)),
        "set_points_good_then_nan": lambda: ga.set_points(node, {back: ga.lock_handles(node, [back])[back]["points"],
                                                                 lid: bad(W, 1, 0, float("nan"))}),
        "scale_1e9": lambda: ga.scale_points(node, [lid], 1e9),
        "scale_nan": lambda: ga.scale_points(node, [lid], float("nan")),
        "scale_8_on_the_back_lock": lambda: ga.scale_points(node, [back], 8.0),
        "rotate_nan_axis": lambda: ga.rotate_points(node, [lid], (float("nan"), 0, 0), 20.0),
        "rotate_inf_degrees": lambda: ga.rotate_points(node, [lid], axes[2], float("inf")),
        "handle_count_7_5": lambda: ga.set_handle_count(node, [lid], 7.5),
        "handle_count_text_7": lambda: ga.set_handle_count(node, [lid], "7"),
        "handle_count_13": lambda: ga.set_handle_count(node, [lid], 13),
        "draw_width_1e6": lambda: ga.draw_lock(node, stroke, width_cm=1e6),
        "draw_thickness_nan": lambda: ga.draw_lock(node, stroke, thick_cm=float("nan")),
        "draw_stroke_1e4_units_off_the_skin": lambda: ga.draw_lock(node, [far, (np.asarray(far) + 0.1).tolist()]),
        "draw_stroke_nan": lambda: ga.draw_lock(node, bad(np.array(stroke), 3, 1, float("nan"))),
        "draw_unknown_group": lambda: ga.draw_lock(node, stroke, group="nogroup"),
        "redraw_stroke_80cm_off": lambda: ga.redraw_lock(node, lid, (np.array(ROW0[lid]["P"]) + np.asarray(
            axes[2]) * 80.0 / U).tolist()),
        "set_drawn_width_1e6": lambda: ga.set_drawn(node, [d_id], width_cm=1e6),
        "set_drawn_taper_nan": lambda: ga.set_drawn(node, [d_id], taper=float("nan")),
        # t84 recheck (second round)
        "rotate_bool_id": lambda: ga.rotate_points(node, [True], axes[2], 20.0),
        "scale_id_31_5": lambda: ga.scale_points(node, [lid + 0.5], 2.0),
        "set_points_lock_twice": lambda: ga.set_points(node, {lid: W.tolist(), str(lid): W.tolist()}),
        "draw_tol_0": lambda: ga.draw_lock(node, stroke, tol_cm=0.0),
        "draw_tol_nan": lambda: ga.draw_lock(node, stroke, tol_cm=float("nan")),
        "redraw_tol_inf": lambda: ga.redraw_lock(node, lid, W.tolist(), tol_cm=float("inf")),
        "draw_zero_length_stroke": lambda: ga.draw_lock(node, [stroke[0]] * 4),
        "draw_name_of_another_lock": lambda: ga.draw_lock(node, stroke, name=MOVE_LOCK),
        "draw_name_not_text": lambda: ga.draw_lock(node, stroke, name=5),
        "draw_name_spaces": lambda: ga.draw_lock(node, stroke, name="   "),
        "set_drawn_taper_7": lambda: ga.set_drawn(node, [d_id], taper=7.0),
        "set_drawn_taper_minus": lambda: ga.set_drawn(node, [d_id], taper=-0.0001),
    }
    nothing = {
        "set_points_measured_handles": lambda: set_frame(lid, H.tolist()),
        "rotate_zero_axis": lambda: ga.rotate_points(node, [lid], (0, 0, 0), 20.0),
        "rotate_0_degrees": lambda: ga.rotate_points(node, [lid], axes[2], 0.0),
        "scale_1": lambda: ga.scale_points(node, [lid], 1.0),
    }
    rows = {}
    ok = True
    for tag, fn in list(raises.items()) + list(nothing.items()):
        text0, n0 = ga.data_text(node), len(hou.undos.undoLabels())
        try:
            res = fn()
            got = {"raised": None, "message": res.get("message") if isinstance(res, dict) else res}
        except ValueError as e:
            got = {"raised": str(e)}
        except Exception as e:      # any other exception is a failure too
            got = {"raised_other": "%s: %s" % (type(e).__name__, e)}
        text1 = ga.data_text(node)
        got.update(text_same=text1 == text0, undo_steps=len(hou.undos.undoLabels()) - n0,
                   nan_in_text="NaN" in text1 or "Infinity" in text1)
        if tag in raises:
            good = got.get("raised") is not None
        else:
            good = got.get("raised") is None and "nothing changed" in (got.get("message") or "")
        good = good and got["text_same"] and got["undo_steps"] == 0 and not got["nan_in_text"]
        got["pass"] = good
        rows[tag] = got
        ok = ok and good
    errs = lib.node_errors(node)
    cook_all()
    ok = ok and not lib.node_errors(node)
    add("v1_bad_input_refused", ok, {"cases": rows, "node_errors_after": errs}, "ValueError or nothing changed",
        "t84 B-1, B-2, minors 1-3, against the node: %d inputs that must raise ValueError naming what is wrong "
        "(non-finite handles, strokes, axes, factors; a handle count outside 4..12 or not whole; past the limits in "
        "config: LOCK_REACH_MAX_CM %g, STROKE_SKIN_MAX_CM %g, SCALE_RANGE %s, DRAWN_WIDTH_RANGE_CM %s, "
        "DRAWN_THICK_RANGE_CM %s; an unknown group; t84's second round: a bool or fractional lock id, a lock given "
        "twice, tol_cm 0 / NaN / inf, a zero-length stroke, a drawn lock's name another lock has, not text or "
        "spaces, a taper outside 0-1) and %d whose result equals what is there (\"nothing changed\"): "
        "groom_data's text the same, no undo step, no NaN in the text, the node cooking without an error after"
        % (len(raises), config.LOCK_REACH_MAX_CM, config.STROKE_SKIN_MAX_CM, config.SCALE_RANGE,
           config.DRAWN_WIDTH_RANGE_CM, config.DRAWN_THICK_RANGE_CM, len(nothing)))


# ---------------------------------------------------------------------------
def n_drawn():
    lid, stroke = n1_n2_drawn()
    n3_detect(lid, stroke)
    n4_delete_gives_skin_back()


# the drawn locks right after the edits of one lock: Draw's "only the locks that gave skin recook" is measured on
# states never cooked before (u2 draws at the same place)
def e6_roots_stay():
    """The plan (After 037b's recheck): an edit that leaves the root handle in place moves no strand root: per strand
    id the root equals the unedited lock's at rest. hair_base_07 (a wide cap: t84 found 78 % of its roots moved by id
    on a 25 deg turn, 16 % off its own root set), hair_back_05 and the fringe lock hair_bang_05, each turned 25 deg
    and its tip moved 2 cm. The root steps read the mesh as modelled, not the carried mesh."""
    rows, ok = {}, True
    for name in ("hair_base_07", "hair_back_05", "hair_bang_05"):
        lid = ID[name]
        row = ROW0[lid]
        K = ga.lock_handles(node, [lid])[lid]["count"]
        ga.reset_points(node, [lid])
        r0 = {sid: P[0] for sid, P in hair()[lid]}
        for tag, H in (("turn_25deg", alib.turn(row, K, 25.0)), ("tip_2cm", alib.bend(row, K, 2.0, U))):
            set_frame(lid, H.tolist())
            r1 = {sid: P[0] for sid, P in hair()[lid]}
            ids = sorted(set(r0) & set(r1))
            d = np.array([np.linalg.norm(r0[i] - r1[i]) for i in ids]) if ids else np.array([np.inf])
            got = {"strands": [len(r0), len(r1)], "same_ids": len(ids), "root_max_cm": float(d.max())}
            got["pass"] = len(r0) == len(r1) == len(ids) and got["root_max_cm"] <= config.ROOT_SAME_CM
            ok = ok and got["pass"]
            rows["%s_%s" % (name, tag)] = got
            ga.reset_points(node, [lid])
    add("e6_roots_stay_under_an_edit", ok, rows, "every strand's root within %g cm of its own (by id)" % config.ROOT_SAME_CM,
        "an edit that leaves the root handle in place (a 25 deg turn about the root, the tip moved 2 cm) on a wide cap, a "
        "back lock and a fringe lock: the same strands, and per strand id the root where the unedited lock had it")


order = [("e1", e1_identity), ("e0", e0_network_rule), ("e2", e2_speed), ("e3", e3_e4_follow), ("e5", e5_mesh_display),
         ("g1", g1_root), ("g2", g2_root_regions), ("u1", u1_undo), ("n", n_drawn), ("u2", u2_steps),
         ("u3", u3_several), ("d1", d1_redraw), ("d2", d2_reset), ("h1", h1_counts), ("h2", h2_resample),
         ("v1", v1_bad_input), ("v2", v2_names_ids_strokes), ("e6", e6_roots_stay)]
for tag, fn in order:
    if wanted(tag):
        C.run(tag + "_raised", fn)
        restore()
for tag, fn in (("p1", p1_survive), ("p2", p2_orphan), ("p3", p3_publish)):
    if wanted(tag):
        C.run(tag + "_raised", fn)
        restore()
for tag, fn in (("r1", r1_m1_base), ("r2", r2_qc), ("q1", q1_qc_edited), ("x1", x1_fullcook), ("s", s_shots),
                ("s6", s6_deform)):
    if wanted(tag):
        C.run(tag + "_raised", fn)
C.meta["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
C.write(done=True)
print("DONE", C.path)
sys.stdout.flush()
os._exit(0)
