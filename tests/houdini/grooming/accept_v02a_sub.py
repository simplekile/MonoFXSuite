"""Helpers of accept_v02a.py that must run in a process of their own (hython; not collected by pytest).

    hython accept_v02a_sub.py fullcook <suite> <scene> <out.json> <accept_lib dir> [repeats]
        a cold full cook of the rest groom (output 1's own loop, every lock), `repeats` times in THIS new
        process: the fresh no-layer groom, the node's cache dropped before each. Works on a v0.1 suite too.
    hython accept_v02a_sub.py reopen <suite> <hip> <out.json> <accept_lib dir>
        open a saved scene as it is: layers, each mask's digest, strands per lock, what was dropped, errors.
    hython accept_v02a_sub.py asopened <suite> <hip> <out.json> <accept_lib dir> [on]
        open a saved scene as it is and cook the rest groom: "Fit lookup per lock" as the node holds it after
        opening (None on a suite without the parm), and <out>.npz with the groom's points, the points a strand
        and the lock ids. `on`: the toggle switched on before the cook. Works on a v0.1 suite too.
    hython accept_v02a_sub.py makeold <suite> <scene> <out.json> <accept_lib dir>
        the scene with a fresh groom made and saved by <suite> as <out>.hiplc (with the v0.1 suite: a v0.1 scene).
    fullcook takes a 7th argument `lookup_off`: the toggle off before the cooks.
"""
import hashlib
import json
import os
import sys
import time
import traceback

MODE, SUITE, SCENE, OUTF, LIB = (a.replace("\\", "/") for a in sys.argv[1:6])
sys.path.insert(0, SUITE)
sys.path.insert(0, LIB)

import hou  # noqa: E402
import numpy as np  # noqa: E402

import accept_lib as lib  # noqa: E402

R = {"mode": MODE, "suite": SUITE}
try:
    ga, node = lib.open_scene(SUITE, SCENE)
    R["library"] = node.type().definition().libraryFilePath()
    if MODE == "fullcook":
        repeats = int(sys.argv[6]) if len(sys.argv) > 6 else 3
        lib.fresh(ga, node)
        if len(sys.argv) > 7 and sys.argv[7] == "lookup_off" and node.parm("lookup_per_piece") is not None:
            node.parm("lookup_per_piece").set(0)
        R["lookup_per_piece"] = int(node.evalParm("lookup_per_piece")) if node.parm("lookup_per_piece") is not None else None
        rest, keys = node.node("GROOM_REST"), node.node("groom_keys")
        rest.cook()
        times = []
        for _ in range(repeats):
            ga.hair_cache().drop_node(node.sessionId())
            t = time.perf_counter()
            keys.cook(force=True)
            rest.cook()
            times.append(round(time.perf_counter() - t, 3))
            if len(node.node("groom_to_cook").geometry().iterPrims()) < 2:
                raise RuntimeError("no lock went through the loop")
        R["runs_s"] = times
        R["median_s"] = float(np.median(times))
        R["strands"] = rest.geometry().intrinsicValue("primitivecount")
        R["anim_wired"] = bool(node.evalParm("anim_wired"))
    elif MODE == "reopen":
        from tools.fx.grooming import config, model
        text = node.evalParm(config.DATA_PARM)
        R["stored_schema"] = json.loads(text).get("schema") if text.strip() else None
        data = ga.read_data(node)
        R["layers"] = [dict(m.__dict__) for m in data.masks]
        R["dropped"] = ga.mask_dropped(node)
        G = lib.Groom(ga, node)
        R["strands"] = {str(k): v for k, v in G.strands_by_lock().items()}
        geo = node.parm(config.MASK_PARM).evalAsGeometry()
        R["masks"] = {a.name(): hashlib.sha1(geo.pointFloatAttribValuesAsString(a.name())).hexdigest()
                      for a in geo.pointAttribs() if a.name().startswith("mask_")} if geo is not None else {}
        R["errors"] = lib.node_errors(node)
        R["undo_cache_gb"] = node.evalParm(config.UNDO_CACHE_PARM) if node.parm(config.UNDO_CACHE_PARM) else None
    elif MODE == "makeold":
        # a scene as THIS suite saves it (run with the v0.1 suite: a v0.1 scene): fresh groom, cooked, saved
        lib.fresh(ga, node)
        node.node("GROOM_REST").cook()
        text = node.evalParm("groom_data")
        R["stored_schema"] = json.loads(text).get("schema", 1) if text.strip() else None
        R["has_lookup_parm"] = node.parm("lookup_per_piece") is not None
        hou.hipFile.save(os.path.splitext(OUTF)[0] + ".hiplc")
    elif MODE == "asopened":
        p = node.parm("lookup_per_piece")
        R["lookup_as_opened"] = int(p.eval()) if p is not None else None
        R["note"] = node.userData("monofx_fit_lookup")
        text = node.evalParm("groom_data")
        R["stored_schema"] = json.loads(text).get("schema", 1) if text.strip() else None
        if len(sys.argv) > 6 and sys.argv[6] == "on" and p is not None:
            p.set(1)
        R["lookup_cooked"] = int(p.eval()) if p is not None else None
        rest = node.node("GROOM_REST")
        rest.cook()
        geo = rest.geometry()
        P = np.frombuffer(geo.pointFloatAttribValuesAsString("P"), np.float32)
        lock = np.frombuffer(geo.primIntAttribValuesAsString("lock_id"), np.int32)
        counts = np.array([pr.numVertices() for pr in geo.prims()], np.int32)
        R["strands"] = int(len(lock))
        R["points"] = int(len(P) // 3)
        R["unit_cm"] = float(node.evalParm("unit_cm"))
        R["sha1_points"] = hashlib.sha1(P.tobytes()).hexdigest()
        R["sha1_lock_ids"] = hashlib.sha1(lock.tobytes()).hexdigest()
        np.savez(os.path.splitext(OUTF)[0] + ".npz", P=P, lock=lock, counts=counts)
        R["errors"] = lib.node_errors(node)
    else:
        raise ValueError(MODE)
except Exception:
    R["error"] = traceback.format_exc()[-3000:]
with open(OUTF, "w", encoding="utf-8") as fh:
    json.dump(R, fh, indent=1, default=str)
sys.stdout.flush()
os._exit(0)
