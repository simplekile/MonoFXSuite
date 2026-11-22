"""MONO Grooming v0.2b acceptance, the shot deform (B-3 decided by the user, 2026-11-22; docs/plans/grooming_v0_2.md
"The cause, and the deform that replaces v0.1's in shots"): hython, one suite, one shot scene.

    hython accept_v02b_deform.py <suite> <hip> <out.json> <frames> <edited locks, comma> [consecutive frames, comma]

A fresh groom (as accept_v02b_shot makes it), output 1 (GROOM) read at each frame. Per lock and frame:
  fold            the hair's centreline turning over rest minus its own animated piece's turning over rest > 90 deg,
                  or a new kink over 90 deg the piece does not have (the plan's rule; centreline = the strands resampled
                  by length and averaged, 32 points; the piece's = its points binned by `pu`, 24 bins)
  piece_folds     the piece itself: turning +90 over rest or a new kink over 90
  len_p50/p95     strand length at the frame / at rest (reported)
  len_vs_piece    each strand's length ratio / its piece's over the strand's span (48 bins of `pu`); graded:
                  p95 of |x - 1| (the plan, 2026-11-23: the animation stretches the pieces)
  roots_skin_p95  the roots off the animated scalp (the scene's head through its own scalp nodes, as accept_v02b_shot)
  left_behind     strand points still where they were at rest
  to_piece        the hair centreline's median distance to its piece's centreline, frame and rest
  piece_len_ratio its piece's centreline length, frame / rest (the animation's own stretch)
and the points of every 10th strand (by id), so another run (the other build) can be compared point for point.
Edited locks (tip 2 cm, turn 25 deg): median length (frame / its own rest) and the tip turn against the unedited lock
(accept_v02b_shot's measure: per strand P[-1] - P[-4], median angle, frame minus rest). Consecutive frames: the hair's
largest point move from one frame to the next against its piece's. The frame cost: output 1 cooked at a frame
(after the first frame, the capture made)."""
import json
import os
import sys
import time

SUITE, HIP, OUT = sys.argv[1:4]
FRAMES = [int(f) for f in sys.argv[4].split(",")]
EDIT = [n for n in (sys.argv[5] if len(sys.argv) > 5 else "").split(",") if n]
CONSEC = [int(f) for f in sys.argv[6].split(",")] if len(sys.argv) > 6 and sys.argv[6] else []
sys.path.insert(0, SUITE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hou  # noqa: E402
import numpy as np  # noqa: E402
import accept_lib as lib  # noqa: E402
import accept_v02b_lib as alib  # noqa: E402

ga, node = lib.open_scene(SUITE, HIP)
rest_frame = node.evalParm("rest_frame")
lib.fresh(ga, node)
node.parm("rest_frame").set(rest_frame)
U = float(node.evalParm("unit_cm"))
net = node.parent()
a_head, a_scalp = hou.copyNodesTo([net.node("head"), net.node("scalp")], net)
a_head.setInput(0, net.node("shot_keep_P_name"))
a_scalp.setInput(0, a_head)
a_head.parm("group").set("@name=Geo_Head @name=Geo_Head_LOCDUP")
groom, rest = node.node("GROOM"), node.node("GROOM_REST")
hou.setFrame(rest_frame)
groom.cook()
inner = {n.name(): n for n in node.allSubChildren()}
mesh = inner["mesh_pu"].geometry()
anim = node.node("ANIM_HAIR")
piece_pt = np.frombuffer(mesh.pointIntAttribValuesAsString("piece"), np.int32)
pu_pt = np.frombuffer(mesh.pointFloatAttribValuesAsString("pu"), np.float32)
P_mesh = np.frombuffer(mesh.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(float) * U
NAME = {lk.id: lk.name for lk in ga.read_data(node).locks}
ID = {v: k for k, v in NAME.items()}
PIECE = {int(p.attribValue("lock_id")): int(p.attribValue("piece")) for p in node.node("SPINES").geometry().prims()}


def pts(g):
    return np.frombuffer(g.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(float) * U


def by_lock(geo_node):
    geo_node.cook()
    return {lid: dict(v) for lid, v in alib.strands(geo_node.geometry(), U).items()}


def centreline(strs, n=32):
    acc = np.zeros((n, 3))
    for S in strs:
        L = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(S, axis=0), axis=1))])
        t = np.linspace(0, L[-1], n)
        acc += np.stack([np.interp(t, L, S[:, k]) for k in range(3)], 1)
    return acc / max(len(strs), 1)


def turning(C):
    t = np.diff(C, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
    a = np.degrees(np.arccos(np.clip((t[1:] * t[:-1]).sum(1), -1, 1)))
    return float(a.sum()), (float(a.max()) if len(a) else 0.0)


def piece_line(P, pc, n=24):
    m = piece_pt == pc
    u, X = pu_pt[m], P[m]
    b = np.clip((u * n).astype(int), 0, n - 1)
    return np.array([X[b == k].mean(0) for k in range(n) if (b == k).any()])


def span_ratio(rest_strand, L0, L1):
    """The piece's length ratio (frame / rest) over the strand's span along it: the piece's centreline (48 bins of `pu`)
    between the bins nearest the strand's rest points, widened to 3 bins when shorter."""
    k = np.argmin(((rest_strand[:, None, :] - L0[None, :, :]) ** 2).sum(-1), axis=1)
    lo, hi = int(k.min()), int(k.max())
    if hi - lo < 2:
        lo, hi = max(0, lo - 1), min(len(L0) - 1, hi + 1)
    a = np.linalg.norm(np.diff(L0[lo:hi + 1], axis=0), axis=1).sum()
    b = np.linalg.norm(np.diff(L1[lo:hi + 1], axis=0), axis=1).sum()
    return b / max(a, 1e-9)


def lens(d):
    return {s: float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum()) for s, P in d.items()}


def gap(hair_c, line):
    return float(np.median([np.min(np.linalg.norm(line - x, axis=1)) for x in hair_c]))


REST = by_lock(rest)
R_LEN = {lid: lens(d) for lid, d in REST.items()}
R_LINE = {lid: centreline(list(d.values())) for lid, d in REST.items()}
R_TURN = {lid: turning(c) for lid, c in R_LINE.items()}
P_LINE = {lid: piece_line(P_mesh, pc) for lid, pc in PIECE.items() if pc >= 0}
P_TURN = {lid: turning(c) for lid, c in P_LINE.items()}
P_LINE48 = {lid: piece_line(P_mesh, pc, 48) for lid, pc in PIECE.items() if pc >= 0}
out = {"suite": SUITE, "hip": HIP, "frames": FRAMES, "rest_frame": rest_frame, "unedited": {}, "cost_s": {},
       "edited": {}, "consecutive": {}, "deform_problem": ga.deform_problem(node)}
samples = {}
for i, f in enumerate(FRAMES):
    hou.setFrame(f)
    t0 = time.perf_counter()
    groom.cook(force=True)
    if i:                               # the first frame also makes every lock's capture
        out["cost_s"][str(f)] = round(time.perf_counter() - t0, 3)
    NEW = by_lock(groom)
    PA = pts(anim.geometry())
    for lid, d in NEW.items():
        pc = PIECE.get(lid, -1)
        if pc < 0 or lid not in REST:
            continue
        L1 = lens(d)
        sids = [s for s in d if s in R_LEN[lid]]
        r = np.array([L1[s] / max(R_LEN[lid][s], 1e-9) for s in sids])
        # the plan (2026-11-23): each strand's length ratio against its piece's over the strand's span
        pl48 = piece_line(PA, pc, 48)
        pr = np.array([span_ratio(REST[lid][s], P_LINE48[lid], pl48) for s in sids])
        rel = r / np.maximum(pr, 1e-9)
        t1, k1 = turning(centreline(list(d.values())))
        pl1 = piece_line(PA, pc)
        pt1, pk1 = turning(pl1)
        t0_, k0_ = R_TURN[lid]
        pt0, pk0 = P_TURN[lid]
        roots = np.array([P[0] for P in d.values()])[:: max(1, len(d) // 40)]
        skin = alib.to_skin_cm(roots / U, a_scalp.geometry(), U, limit=40)
        left = sum(int((np.linalg.norm(d[s] - REST[lid][s], axis=1) < 1e-6).sum()) for s in d
                   if s in REST[lid] and REST[lid][s].shape == d[s].shape)
        out["unedited"].setdefault(NAME[lid], {})[str(f)] = {
            "fold": bool(((t1 - t0_) - (pt1 - pt0) > 90) or (k1 > 90 and k0_ <= 90 and pk1 <= 90)),
            "piece_folds": bool((pt1 - pt0 > 90) or (pk1 > 90 and pk0 <= 90)),
            "hair_turn_change": t1 - t0_, "piece_turn_change": pt1 - pt0, "hair_kink": k1, "piece_kink": pk1,
            "len_p50": float(np.median(r)), "len_p95": float(np.percentile(r, 95)),
            "len_vs_piece_p95_off": float(np.percentile(np.abs(rel - 1), 95)), "len_vs_piece_p50": float(np.median(rel)),
            "piece_span_ratio_p50": float(np.median(pr)),
            "roots_skin_p95_cm": float(np.percentile(skin, 95)) if len(skin) else None, "left_behind": left,
            "to_piece_rest_cm": gap(R_LINE[lid], P_LINE[lid]), "to_piece_now_cm": gap(centreline(list(d.values())), pl1),
            "piece_len_ratio": float(np.linalg.norm(np.diff(pl1, axis=0), axis=1).sum()
                                     / max(np.linalg.norm(np.diff(P_LINE[lid], axis=0), axis=1).sum(), 1e-9))}
        for s in sorted(d)[::10]:
            samples["%s|%d|%d" % (f, lid, s)] = d[s].astype(np.float32)
    print("frame", f, "folds", sum(v[str(f)]["fold"] for v in out["unedited"].values()), flush=True)
np.savez_compressed(os.path.splitext(OUT)[0] + "_samples.npz", **samples)
if CONSEC:
    prev = None
    for f in CONSEC:
        hou.setFrame(f)
        NEW, PA = by_lock(groom), pts(anim.geometry())
        if prev is not None:
            for lid, d in NEW.items():
                pc = PIECE.get(lid, -1)
                if pc < 0:
                    continue
                hm = max(float(np.linalg.norm(d[s] - prev[0][lid][s], axis=1).max()) for s in d if s in prev[0][lid])
                m = piece_pt == pc
                out["consecutive"].setdefault(NAME[lid], {})[str(f)] = {
                    "hair_max_cm": hm, "piece_max_cm": float(np.linalg.norm(PA[m] - prev[1][m], axis=1).max())}
        prev = (NEW, PA)
for name in EDIT:
    lid = ID[name]
    hou.setFrame(rest_frame)
    row = alib.rows(node, "SPINES_MEASURED")[lid]
    K = ga.lock_handles(node, [lid])[lid]["count"]
    ga.reset_points(node, [lid])
    UR = by_lock(rest)[lid]
    UF = {}
    for f in FRAMES:
        hou.setFrame(f)
        UF[f] = by_lock(groom)[lid]
    res = {}
    for tag, H in (("tip_2cm", alib.bend(row, K, 2.0, U)), ("turn_25deg", alib.turn(row, K, 25.0))):
        hou.setFrame(rest_frame)
        ga.set_points(node, {lid: H.tolist()}, space="frame")
        ER = by_lock(rest)[lid]
        eL0 = lens(ER)
        for f in FRAMES:
            hou.setFrame(f)
            EF = by_lock(groom)[lid]
            L1 = lens(EF)
            r = np.array([L1[s] / max(eL0[s], 1e-9) for s in EF if s in eL0])

            def tipd(st):
                return {s: alib._unit(P[-1] - P[-4]) for s, P in st.items()}
            a0u, a0e, a1u, a1e = tipd(UR), tipd(ER), tipd(UF[f]), tipd(EF)
            ids = [x for x in a0e if x in a0u and x in a1u and x in a1e]

            def ang(A, B):
                return np.degrees(np.arccos(np.clip([np.dot(A[x], B[x]) for x in ids], -1, 1)))
            tr, tf = float(np.median(ang(a0u, a0e))), float(np.median(ang(a1u, a1e)))
            res.setdefault(tag, {})[str(f)] = {
                "len_p50": float(np.median(r)), "len_p95": float(np.percentile(r, 95)), "tip_turn_rest": tr,
                "tip_turn_frame": tf, "tip_turn_change": abs(tf - tr),
                "piece_folds": out["unedited"].get(name, {}).get(str(f), {}).get("piece_folds")}
        hou.setFrame(rest_frame)
        ga.reset_points(node, [lid])
    out["edited"][name] = res
    print(name, "done", flush=True)
out["errors"] = lib.node_errors(node)
json.dump(out, open(OUT, "w"), indent=1)
print("DONE", OUT, flush=True)
sys.stdout.flush()
os._exit(0)
