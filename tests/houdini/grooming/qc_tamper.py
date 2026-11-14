"""Does grooming-check catch a painted lock that grew too few strands, or (a negative --drop) too many?

    hython qc_tamper.py <suite> <hip> <out_dir> [--ref <v006.usd>] --drop 0.3 [--lock <name>]

Runs the skill's qc_metrics.py unchanged on a groom whose hair is wrong on purpose: while the groom cooks,
one lock under density layers (the named one, else the layered lock with the most strands) loses the share
`--drop` of its strands right before they are stored in the cache, as a fault in the network would leave it.
What the lock is expected to grow (`lock_infos`) is not touched. Writes qc_tamper.json beside qc_metrics'
own qc_report.json. Needs Houdini; not collected by pytest."""
import json
import os
import runpy
import sys

SUITE, HIP, OUT = (a.replace("\\", "/") for a in sys.argv[1:4])
DROP = float(sys.argv[sys.argv.index("--drop") + 1])
WANT = sys.argv[sys.argv.index("--lock") + 1] if "--lock" in sys.argv else None
sys.path.insert(0, SUITE)
os.makedirs(OUT, exist_ok=True)

import hou  # noqa: E402

from apps.houdini import grooming_adapter as ga  # noqa: E402
from tools.fx.grooming import config, model  # noqa: E402

INFO = {"drop": DROP, "lock": WANT, "cut": []}
_store = ga.cook_cache_store
_target = {"id": None}


def pick(top):
    """The lock to cut: the named one, else the lock a layer owns skin of with the most strands."""
    if _target["id"] is not None:
        return _target["id"]
    data = model.GroomData.from_json(top.evalParm(config.DATA_PARM))
    regions = top.node("SCALP_REGIONS").geometry()
    sets = regions.intListAttribValue("mask_set_of") if regions.findGlobalAttrib("mask_set_of") is not None else ()
    layered = [lk for lk in data.locks if lk.id < len(sets) and sets[lk.id] >= 0]
    lock = next((lk for lk in layered if lk.name == WANT), None)
    if lock is None and layered and WANT is None:
        spines = top.node("lock_keys").geometry()
        adds = dict(zip(spines.primIntAttribValues("lock_id"), spines.primFloatAttribValues("mask_add_n")))
        lock = max(layered, key=lambda lk: adds.get(lk.id, 0.0))
    _target["id"] = lock.id if lock is not None else -1
    INFO["lock"] = lock.name if lock is not None else None
    INFO["layered_locks"] = len(layered)
    return _target["id"]


def tampered(sop):
    spine = sop.inputs()[1].geometry().prims()
    if spine and spine[0].intAttribValue("lock_id") == pick(sop.parent()):
        geo = sop.geometry()
        prims = geo.prims()
        cut = [p for i, p in enumerate(prims) if (i * 0.6180339887) % 1.0 < abs(DROP)]
        INFO["cut"].append({"strands": len(prims), "removed" if DROP >= 0 else "added": len(cut),
                            "mode": spine[0].stringAttribValue("cache_mode")})
        if DROP >= 0:
            geo.deletePrims(cut)
        else:                                   # a negative share: that many strands too many (copies of its own)
            more = hou.Geometry()
            more.merge(geo)
            chosen = {p.number() for p in cut}
            more.deletePrims([p for p in more.prims() if p.number() not in chosen])
            geo.merge(more)
        json.dump(INFO, open(OUT + "/qc_tamper.json", "w"), indent=1, default=str)   # qc_metrics exits by itself
    _store(sop)


ga.cook_cache_store = tampered
qc = SUITE + "/.claude/skills/grooming-check/scripts/qc_metrics.py"
skip = {"--drop", str(sys.argv[sys.argv.index("--drop") + 1]), "--lock", WANT}
sys.argv = [qc, SUITE, HIP, OUT] + [a for a in sys.argv[4:] if a not in skip]
try:
    runpy.run_path(qc, run_name="__main__")
except SystemExit:
    pass
finally:
    json.dump(INFO, open(OUT + "/qc_tamper.json", "w"), indent=1, default=str)
    os._exit(0)
