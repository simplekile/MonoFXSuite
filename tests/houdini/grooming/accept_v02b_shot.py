"""The shot part of accept_v02b.py, run by accept_v02b_sub.py `shot` in a hython of its own (not collected by pytest).

On a copy of a shot scene (the anim wired into input 3, as t56 / t76 had it): the groom made fresh (the scene's rest
frame kept), an animated scalp built the way the spike's q3 did (the rest scalp's cut of the shot's head: the scene's
own `head` / `scalp` blasts copied onto the shot's anim USD, whose head is `Geo_Head_LOCDUP`), then per frame output 1
(GROOM) against output 1 at rest (GROOM_REST):
  left_behind   strand points the deform did not move at all
  length_p50    median of the strands' length at the frame over at rest
  roots_p95_cm  the strands' roots off the ANIMATED scalp (they stand on the skin at rest)
for the fringe lock hair_bang_11 unedited, moved 2 cm and 5 cm (the spike's bend), and for a lock drawn on bare skin
with the animated scalp wired, not wired, and wired with another point count. The edited and drawn scenes are saved
into the look folder for the pictures (qc_capture.py, GUI)."""
from __future__ import annotations

import os

import hou
import numpy as np

import accept_lib as lib
import accept_v02b_lib as alib

LOCK = "hair_bang_11"


def _lengths(strands):
    return {sid: float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum()) for sid, P in strands}


def _measure(rest, frame_strands, scalp_geo, unit):
    rp = {sid: P for sid, P in rest}
    moved_min = 1e-6
    left = 0
    ratios = []
    L0 = _lengths(rest)
    L1 = _lengths(frame_strands)
    roots = []
    for sid, P in frame_strands:
        Q = rp.get(sid)
        if Q is None or Q.shape != P.shape:
            continue
        left += int((np.linalg.norm(P - Q, axis=1) < moved_min).sum())
        ratios.append(L1[sid] / max(L0[sid], 1e-9))
        roots.append(P[0] / unit)
    d = alib.to_skin_cm(roots, scalp_geo, unit, limit=300)
    return {"strands": len(ratios), "left_behind": left, "length_p50": round(float(np.median(ratios)), 4),
            "length_p5": round(float(np.percentile(ratios, 5)), 4), "length_p95": round(float(np.percentile(ratios, 95)), 4),
            "roots_p95_cm": round(float(np.percentile(d, 95)), 4) if len(d) else None}


def run(ga, node, frames_text, look, unit):
    frames = [int(f) for f in frames_text.split(",")]
    shot = os.path.splitext(os.path.basename(hou.hipFile.path()))[0].split("_")[0]
    os.makedirs(look, exist_ok=True)
    rest_frame = node.evalParm("rest_frame")
    lib.fresh(ga, node)
    node.parm("rest_frame").set(rest_frame)
    net = node.parent()
    a_head, a_scalp = hou.copyNodesTo([net.node("head"), net.node("scalp")], net)
    a_head.setInput(0, net.node("shot_keep_P_name"))
    a_scalp.setInput(0, a_head)
    a_head.parm("group").set("@name=Geo_Head @name=Geo_Head_LOCDUP")
    a_head.setName("accept_anim_head", unique_name=True)
    a_scalp.setName("accept_anim_scalp", unique_name=True)
    rest, groom = node.node("GROOM_REST"), node.node("GROOM")
    ids = {lk.name: lk.id for lk in ga.read_data(node).locks}
    lid = ids[LOCK]
    out = {"shot": shot, "frames": frames, "rest_frame": rest_frame, "anim_wired": node.evalParm("anim_wired"),
           "deform_problem": ga.deform_problem(node)}

    def strands_of(geo_node, which):
        geo_node.cook()
        return alib.strands(geo_node.geometry(), unit).get(which, [])

    # ---- an edited lock (moved 2 cm, 5 cm) against the unedited one ----
    hou.setFrame(rest_frame)
    row = alib.rows(node, ga.NODE_SPINES_MEASURED)[lid]
    K = ga.lock_handles(node, [lid])[lid]["count"]
    cases = {"unedited": None, "move_2cm": alib.bend(row, K, 2.0, unit), "move_5cm": alib.bend(row, K, 5.0, unit)}
    edited = {"lock": LOCK, "handles": K, "frames": {str(f): {} for f in frames}}
    for case, H in cases.items():
        hou.setFrame(rest_frame)
        if H is None:
            ga.reset_points(node, [lid])
        else:
            ga.set_points(node, {lid: H.tolist()}, space="frame")
        R0 = strands_of(rest, lid)
        hou.hipFile.save(f"{look}/{shot}_{case}.hiplc")
        for f in frames:
            hou.setFrame(f)
            edited["frames"][str(f)][case] = _measure(R0, strands_of(groom, lid), a_scalp.geometry(), unit)
        edited.setdefault("errors", {})[case] = lib.node_errors(node)
    out["edited"] = edited
    hou.setFrame(rest_frame)
    ga.reset_points(node, [lid])

    # ---- drawn locks: one on the bare skin farthest from every root (the fringe on Helen), one on the hair_back skin
    # farthest from the roots (where the spike drew its lock) ----
    f1 = frames[min(1, len(frames) - 1)]
    hou.setFrame(f1)
    groom.cook()
    before_draw = alib.strands(groom.geometry(), unit)
    hou.setFrame(rest_frame)
    drawn = {}
    for place, group in (("fringe", ""), ("back", "hair_back")):
        spot, nrm = alib.bare_spot(node, unit, group)
        res = ga.draw_lock(node, alib.drawn_stroke(spot, nrm, 12.0, unit))
        drawn[place] = res
    gave = {i for r in drawn.values() for i in r["gave_ids"]}
    ids_d = {r["id"] for r in drawn.values()}
    ref = next(k for k in sorted(before_draw) if k not in gave and k not in ids_d)
    R0 = {place: strands_of(rest, r["id"]) for place, r in drawn.items()}
    unwired = {}
    blast = net.createNode("blast", "accept_scalp_fewer")
    blast.setInput(0, a_scalp)
    blast.parm("group").set("0-3")
    blast.parm("grouptype").set(4)
    for tag, src in (("not_wired", None), ("other_point_count", blast)):
        node.setInput(3, src)
        hou.setFrame(f1)
        groom.cook()
        geo = alib.strands(groom.geometry(), unit)
        rest_d = 0.0
        n_d = 0
        for place, r in drawn.items():
            mine = {sid: P for sid, P in geo.get(r["id"], [])}
            n_d += len(mine)
            rest_d = max([rest_d] + [float(np.abs(mine[sid] - P).max()) if sid in mine else float("inf")
                                     for sid, P in R0[place]])
        ref_d = max((float(np.abs(Q - P).max()) for (s1, P), (s2, Q) in zip(before_draw[ref], geo.get(ref, []))
                     if s1 == s2 and P.shape == Q.shape), default=float("inf"))
        st = ga.animated_scalp(node)
        unwired[tag] = {"drawn_strands": n_d, "drawn_at_rest_max_cm": rest_d, "message": st["message"],
                        "scalp": {k: st[k] for k in ("wired", "ok", "anim_points", "rest_points")},
                        "errors": lib.node_errors(node), "mesh_lock": ref,
                        "mesh_locks_same_as_without_the_drawn_lock_cm": ref_d}
    out["drawn_unwired"] = unwired
    node.setInput(3, a_scalp)
    hou.setFrame(rest_frame)
    hou.hipFile.save(f"{look}/{shot}_drawn.hiplc")
    st = ga.animated_scalp(node)
    wired = {"scalp_ok": st["ok"], "message": st["message"], "places": {}}
    for place, r in drawn.items():
        row = {"lock": r["name"], "gave": r["gave"], "frames": {}}
        for f in frames:
            hou.setFrame(f)
            row["frames"][str(f)] = _measure(R0[place], strands_of(groom, r["id"]), a_scalp.geometry(), unit)
        wired["places"][place] = row
    wired["errors"] = lib.node_errors(node)
    out["drawn_wired"] = wired
    return out
