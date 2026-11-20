"""Helpers of accept_v02b.py that run in a hython of their own (not collected by pytest).

    hython accept_v02b_sub.py dump <suite> <hip> <out.json> <accept_lib dir> [frame]
        open a saved scene as it is and cook output 1 (GROOM, deformed when an anim is wired; at `frame` if given):
        <out>.npz with its points (cm), the points a strand, lock ids and strand ids; the stored groom_data's schema
        and text digest, strands per lock, handle counts, drawn and edited ids, errors and warnings of the node.
    hython accept_v02b_sub.py edit6 <suite> <hip> <out.json> <accept_lib dir>
        open a scene saved by a suite before v0.2b (schema 6): the data on the node as opened (text and schema),
        then one control-point edit and the schema the data is written in after it.
    hython accept_v02b_sub.py shot <suite> <hip> <out.json> <accept_lib dir> <frames> <look dir>
        the shot checks on a copy of a shot scene (sh020 / sh025): an edited fringe lock (moved 2 cm, 5 cm)
        against the unedited one, a drawn lock with the animated scalp wired, not wired and with another point
        count; per frame what the deform did. Saves the scenes the look step shoots into <look dir>.
"""
import hashlib
import json
import os
import sys
import time
import traceback

MODE, SUITE, HIP, OUTF, LIB = (a.replace("\\", "/") for a in sys.argv[1:6])
sys.path.insert(0, SUITE)
sys.path.insert(0, LIB)

import hou  # noqa: E402
import numpy as np  # noqa: E402

import accept_lib as lib  # noqa: E402

R = {"mode": MODE, "suite": SUITE, "hip": HIP}


def strands(geo, unit):
    """(P cm (n, 3), points per strand, lock id per strand, strand id per strand) of a strand geometry."""
    from apps.houdini import grooming_masks as gm
    P = np.frombuffer(geo.pointFloatAttribValuesAsString("P"), np.float32).reshape(-1, 3).astype(np.float64) * unit
    vp, vpt = gm._vertex_tables(geo)
    order = np.argsort(vp, kind="stable")
    lock = np.frombuffer(geo.primIntAttribValuesAsString("lock_id"), np.int32).copy()
    sid = np.frombuffer(geo.primIntAttribValuesAsString("id"), np.int32).copy() if geo.findPrimAttrib("id") \
        else np.arange(len(lock), dtype=np.int32)
    nv = np.bincount(vp, minlength=len(lock))
    return P[vpt[order]], nv, lock, sid


def split(P, nv):
    s = np.concatenate([[0], np.cumsum(nv)])
    return [P[a:b] for a, b in zip(s[:-1], s[1:])]


def lengths(P, nv):
    return np.array([np.linalg.norm(np.diff(x, axis=0), axis=1).sum() for x in split(P, nv)])


try:
    ga, node = lib.open_scene(SUITE, HIP)
    R["library"] = node.type().definition().libraryFilePath()
    unit = float(node.evalParm("unit_cm"))
    if MODE == "dump":
        if len(sys.argv) > 6:
            hou.setFrame(float(sys.argv[6]))
        text = node.evalParm("groom_data")
        R["stored_schema"] = json.loads(text).get("schema", 1) if text.strip() else None
        R["data_sha1"] = hashlib.sha1(text.encode("utf-8")).hexdigest()
        groom = node.node("GROOM")
        groom.cook()
        P, nv, lock, sid = strands(groom.geometry(), unit)
        np.savez(os.path.splitext(OUTF)[0] + ".npz", P=P, nv=nv, lock=lock, sid=sid)
        u, c = np.unique(lock, return_counts=True)
        R["strands"] = {str(int(a)): int(b) for a, b in zip(u, c)}
        R["sha1_points"] = hashlib.sha1(P.tobytes()).hexdigest()
        try:
            data = ga.read_data(node)
            R["handles"] = {str(lk.id): lk.handles for lk in data.locks if lk.handles is not None}
            R["edited"] = data.edited_locks()
            R["drawn"] = [lk.id for lk in data.locks if lk.drawn]
            R["spines"] = {str(lk.id): lk.spine for lk in data.locks if lk.spine}
            R["curves"] = {str(lk.id): lk.curve for lk in data.locks if lk.drawn}
        except Exception:      # a suite before v0.2b
            pass
        R["errors"] = lib.node_errors(node)
        R["warnings"] = lib.node_warnings(node)
        R["frame"] = hou.frame()
    elif MODE == "edit6":
        from tools.fx.grooming import config
        text = node.evalParm("groom_data")
        R["schema_as_opened"] = json.loads(text).get("schema") if text.strip() else None
        R["text_sha1_as_opened"] = hashlib.sha1(text.encode("utf-8")).hexdigest()
        node.node("GROOM_REST").cook()
        R["schema_after_cook"] = json.loads(node.evalParm("groom_data")).get("schema")
        R["errors"] = lib.node_errors(node)
        lid = ga.read_data(node).locks[0].id
        h = ga.lock_handles(node, [lid])[lid]
        res = ga.set_points(node, {lid: h["points"]})
        R["edit"] = res
        R["schema_after_edit"] = json.loads(node.evalParm("groom_data")).get("schema")
        R["undo_label"] = hou.undos.undoLabels()[0] if hou.undos.undoLabels() else ""
        R["expected_label"] = config.UNDO_SPINE["move"]
    elif MODE == "shot":
        R.update(__import__("accept_v02b_shot").run(ga, node, sys.argv[6], sys.argv[7], unit))
    else:
        raise ValueError(MODE)
except Exception:
    R["error"] = traceback.format_exc()[-3000:]
with open(OUTF, "w", encoding="utf-8") as fh:
    json.dump(R, fh, indent=1, default=str)
sys.stdout.flush()
os._exit(0)
