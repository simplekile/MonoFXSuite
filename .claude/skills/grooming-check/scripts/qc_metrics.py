"""MONO Grooming hair quality check: per-strand shape and fit numbers, per lock and overall, against the
approved reference groom. Headless, never saves the scene.

    hython qc_metrics.py <suite> <hip> <out_dir> [--ref <groom.usd>] [--fresh]

<suite>  the MonoFXSuite checkout whose otls/ and code to use
<hip>    a scene with one MONO Grooming node (its input 0 scalp, 1 hair mesh)
--ref    an approved groom USD (curves) to compare with; without it only the absolute limits apply
--fresh  empty the groom data, Detect and Split regions before measuring (after a root/region change)

Writes <out_dir>/qc_report.json and qc_report.md; exit code 1 when a check fails.
Everything is measured at rest (input 2, the shot deform, is ignored): the hair mesh is the target.
"""

import json
import os
import sys
import time

import numpy as np

import hou

SUITE = HIP = OUT = REF = None
FRESH = False

# Per strand, over its polyline (prim wrangle). Input 1 = the hair mesh with `piece`, input 2 = the
# spines (lock_id -> piece). Angles in degrees, lengths in scene units (metres).
VEX_STRAND = r"""
int pts[] = primpoints(0, @primnum);
int n = len(pts);
if (n < 3) { i@qc_short = 1; return; }
int own = -1;
if (haspointattrib(0, "P") && hasprimattrib(0, "lock_id") && npoints(2) > 0) {
    int sp = findattribval(2, "prim", "lock_id", i@lock_id);
    if (sp >= 0) own = prim(2, "piece", sp);
}
vector P[];
foreach (int p; pts) { vector q = point(0, "P", p); append(P, q); }
float total = 0, maxseg = 0, maxang = 0;
int sharp = 0, rev = 0, bends = 0;
vector pc = {0, 0, 0};
for (int i = 1; i < n; i++) {
    float sl = distance(P[i], P[i - 1]);
    total += sl;
    maxseg = max(maxseg, sl);
    if (i < n - 1) {
        vector d0 = normalize(P[i] - P[i - 1]), d1 = normalize(P[i + 1] - P[i]);
        float ang = degrees(acos(clamp(dot(d0, d1), -1, 1)));
        maxang = max(maxang, ang);
        if (ang > 30) sharp++;
        if (ang > 4) {                      // a real bend: does it turn back the other way?
            vector c = normalize(cross(d0, d1));
            if (bends > 0 && dot(c, pc) < -0.5) rev++;
            pc = c;
            bends++;
        }
    }
}
float dmax = 0, dsum = 0, dtip = 0;
int other = 0;
for (int i = 0; i < n; i++) {
    int hp; vector uv;
    float d = xyzdist(1, P[i], hp, uv);
    if (own >= 0 && prim(1, "piece", hp) != own) {
        float dself = xyzdist(1, "@piece=" + itoa(own), P[i], hp, uv);
        if (dself > d + 0.005) other++;      // nearer another lock's mesh by more than 5 mm
        d = dself;
    }
    dmax = max(dmax, d);
    dsum += d;
    if (i == n - 1) dtip = d;
}
f@qc_len = total;
f@qc_maxseg = maxseg;
f@qc_seg_ratio = maxseg / max(total / (n - 1), 1e-6);   // 1 = even segments
f@qc_maxang = maxang;
f@qc_sharp = float(sharp) / (n - 2);
f@qc_rev = float(rev) / max(n - 2, 1);                    // zigzag: turn reversals per segment
f@qc_dmax = dmax;
f@qc_dmean = dsum / n;
f@qc_dtip = dtip;
f@qc_other = float(other) / n;
i@qc_npts = n;
"""

# Per strand point: where along the strand (0 root .. 1 tip), distance to its own lock's mesh, corner angle.
VEX_POINT = r"""
int pr = pointprims(0, @ptnum)[0];
int pts[] = primpoints(0, pr);
int n = len(pts), i = vertexprimindex(0, pointvertex(0, @ptnum));
f@qc_u = n > 1 ? float(i) / (n - 1) : 0.0;
int own = -1;
int lid = prim(0, "lock_id", pr);        // typed: an untyped prim() picks the wrong overload
int sp = findattribval(2, "prim", "lock_id", lid);
if (sp >= 0) own = prim(2, "piece", sp);
int hp; vector uv;
float d = xyzdist(1, @P, hp, uv);
if (own >= 0 && prim(1, "piece", hp) != own) d = xyzdist(1, "@piece=" + itoa(own), @P, hp, uv);
f@qc_d = d;
f@qc_ang = 0;
if (i > 0 && i < n - 1) {
    vector a = normalize(@P - point(0, "P", pts[i - 1])), b = normalize(point(0, "P", pts[i + 1]) - @P);
    f@qc_ang = degrees(acos(clamp(dot(a, b), -1, 1)));
}
"""

# Per hair-mesh point: is there a strand within COVER_MM? Bald or see-through patches show as uncovered.
COVER_MM = 6.0
VEX_COVER = r"""
int hp; vector huv;
xyzdist(1, @P, hp, huv, %(r)s);          // the strand curves, not their points (2 cm apart)
i@qc_cov = hp >= 0;
""" % {"r": COVER_MM / 1000.0}

ATTRS = ("qc_len", "qc_maxseg", "qc_seg_ratio", "qc_maxang", "qc_sharp", "qc_rev", "qc_dmax", "qc_dmean",
         "qc_dtip", "qc_other")

# Limits. Absolute ones always apply; `ref_x` = at most x times the reference groom's value when a
# reference is given (the approved groom is what "not messy" means for this asset).
LIMITS = {
    "kink_p95_deg": {"abs": 35.0, "ref_x": 1.5, "why": "sharp corners along a strand (zigzag, lightning)"},
    "zigzag_p95": {"abs": 0.15, "ref_x": 1.5, "why": "bends that turn back the other way, per segment"},
    "sharp_mean": {"abs": 0.02, "ref_x": 2.0, "why": "share of strand joints bent over 30 deg"},
    "maxseg_p95_cm": {"abs": 2.0, "ref_x": 1.5, "why": "long straight segments that cut across curves"},
    "dmax_p95_cm": {"abs": 2.0, "ref_x": 1.5, "why": "strand points far from their own lock's mesh"},
    "dtip_p95_cm": {"abs": 2.0, "ref_x": 1.5, "why": "tips flaring off the mesh (brush ends)"},
    "other_mean": {"abs": 0.02, "ref_x": None, "why": "strand points sitting on another lock's mesh"},
    "uncovered": {"abs": 0.10, "ref_x": 1.5, "why": "hair mesh with no strand within 6 mm: bald, see-through"},
    "lock_uncovered_worst": {"abs": 0.35, "ref_x": None, "why": "the barest lock"},
    "lock_width_ratio_worst": {"abs": None, "min": 0.7, "ref_x": None,
                               "why": "a lock's hair much narrower than its mesh (collapsed, twisted)"},
    "lock_dmax_p95_worst_cm": {"abs": 3.0, "ref_x": None, "why": "the worst lock's far points"},
    "lock_kink_p95_worst_deg": {"abs": 50.0, "ref_x": None, "why": "the worst lock's corners"},
}


def log(*a):
    print(*a, flush=True)


def measure(geo_node, mesh_node, spines_node, label):
    """Run VEX_STRAND on geo_node's curves; returns {attr: np.array} plus lock ids."""
    parent = geo_node.parent()
    w = parent.createNode("attribwrangle", f"qc_{label}")
    w.setInput(0, geo_node)
    w.setInput(1, mesh_node)
    if spines_node is not None:
        w.setInput(2, spines_node)
    w.parm("class").set(1)
    w.parm("snippet").set(VEX_STRAND)
    t = time.time()
    w.cook(force=True)
    if w.errors():
        raise RuntimeError(f"{label}: {w.errors()}")
    g = w.geometry()
    out = {a: np.array(g.primFloatAttribValues(a)) for a in ATTRS}
    out["lock_id"] = (np.array(g.primIntAttribValues("lock_id")) if g.findPrimAttrib("lock_id")
                      else np.full(len(out["qc_len"]), -1))
    names = g.findPrimAttrib("name")
    out["name"] = list(g.primStringAttribValues("name")) if names else [""] * len(out["qc_len"])
    log(f"{label}: {len(out['qc_len'])} strands measured in {time.time() - t:.1f}s")
    w.destroy()
    return out


def profile(hair, mesh, spines, bins=10):
    """Root-to-tip profile: per tenth of the strand, own-mesh distance and corner angle."""
    w = hair.parent().createNode("attribwrangle", "qc_points")
    for k, n in enumerate((hair, mesh, spines)):
        w.setInput(k, n)
    w.parm("class").set(2)
    w.parm("snippet").set(VEX_POINT)
    g = w.geometry()
    if g is None:
        raise RuntimeError(f"qc_points: {w.errors()}")
    u = np.array(g.pointFloatAttribValues("qc_u"))
    d = np.array(g.pointFloatAttribValues("qc_d")) * 100
    a = np.array(g.pointFloatAttribValues("qc_ang"))
    rows = []
    for b in range(bins):
        sel = (u >= b / bins) & ((u < (b + 1) / bins) if b < bins - 1 else (u <= 1))
        if sel.any():
            rows.append({"u": f"{b / bins:.1f}-{(b + 1) / bins:.1f}", "dist_p50_cm": float(np.median(d[sel])),
                         "dist_p95_cm": float(np.percentile(d[sel], 95)),
                         "far_over_2cm": float(np.mean(d[sel] > 2)),
                         "angle_p95_deg": float(np.percentile(a[sel], 95)), "bent_over_60": float(np.mean(a[sel] > 60))})
    w.destroy()
    return rows


def coverage(mesh, hair_node):
    """Share of the hair mesh's points with a strand point within COVER_MM, overall and per piece."""
    w = mesh.parent().createNode("attribwrangle", "qc_cover")
    w.setInput(0, mesh)
    w.setInput(1, hair_node)
    w.parm("class").set(2)
    w.parm("snippet").set(VEX_COVER)
    g = w.geometry()
    if g is None:
        raise RuntimeError(f"qc_cover: {w.errors()}")
    cov = np.array(g.pointIntAttribValues("qc_cov"))
    if g.findPointAttrib("piece"):
        piece = np.array(g.pointIntAttribValues("piece"))
    else:
        piece = np.zeros(len(cov), int)
        log("qc_cover: the mesh has no point attribute `piece`, coverage per lock unknown")
    per = {int(p): float(cov[piece == p].mean()) for p in np.unique(piece)}
    w.destroy()
    return float(cov.mean()), per


def width_ratios(hair_geo, mesh_geo, spine_geo):
    """Per lock: the hair's spread over the mesh's along its 2nd principal axis (its width). Strands
    fill a lock while mesh points sit on its surface, so a good lock is ~0.85-1.0; a lock whose hair
    collapsed or twisted inside its mesh (Helen's crown caps) is far below."""
    mp = np.array(mesh_geo.pointFloatAttribValues("P")).reshape(-1, 3)
    mpc = np.array(mesh_geo.pointIntAttribValues("piece"))
    hp = np.array(hair_geo.pointFloatAttribValues("P")).reshape(-1, 3)
    counts = np.array([p.numVertices() for p in hair_geo.prims()])
    hl = np.repeat(np.array(hair_geo.primIntAttribValues("lock_id")), counts)

    def spread(x):
        x = x - x.mean(0)
        return np.sqrt(np.maximum(np.sort(np.linalg.eigvalsh(np.cov(x.T)))[::-1], 0))
    out = {}
    for p in spine_geo.prims():
        m, h = mp[mpc == p.attribValue("piece")], hp[hl == p.attribValue("lock_id")]
        if len(m) > 10 and len(h) > 10:
            out[int(p.attribValue("lock_id"))] = float(spread(h)[1] / max(spread(m)[1], 1e-9))
    return out


def summary(m):
    ok = m["qc_len"] > 0
    pc = lambda a, q: float(np.percentile(a[ok], q)) if ok.any() else 0.0  # noqa: E731
    return {
        "strands": int(ok.sum()),
        "kink_p95_deg": pc(m["qc_maxang"], 95),
        "kink_p50_deg": pc(m["qc_maxang"], 50),
        "zigzag_p95": pc(m["qc_rev"], 95),
        "sharp_mean": float(m["qc_sharp"][ok].mean()) if ok.any() else 0.0,
        "maxseg_p95_cm": pc(m["qc_maxseg"], 95) * 100,
        "dmax_p95_cm": pc(m["qc_dmax"], 95) * 100,
        "dmean_p50_cm": pc(m["qc_dmean"], 50) * 100,
        "dtip_p95_cm": pc(m["qc_dtip"], 95) * 100,
        "other_mean": float(m["qc_other"][ok].mean()) if ok.any() else 0.0,
    }


def per_lock(m, lock_names):
    rows = []
    for lid in sorted(set(m["lock_id"].tolist())):
        sel = (m["lock_id"] == lid) & (m["qc_len"] > 0)
        if not sel.any():
            continue
        rows.append({
            "lock_id": int(lid), "name": lock_names.get(int(lid), str(lid)), "strands": int(sel.sum()),
            "kink_p95_deg": float(np.percentile(m["qc_maxang"][sel], 95)),
            "zigzag_p95": float(np.percentile(m["qc_rev"][sel], 95)),
            "maxseg_p95_cm": float(np.percentile(m["qc_maxseg"][sel], 95)) * 100,
            "dmax_p95_cm": float(np.percentile(m["qc_dmax"][sel], 95)) * 100,
            "dtip_p95_cm": float(np.percentile(m["qc_dtip"][sel], 95)) * 100,
            "other_mean": float(m["qc_other"][sel].mean()),
        })
    return rows


def badness(r):
    """One number to rank locks for close-ups: each measure over its limit, summed."""
    return (r["kink_p95_deg"] / LIMITS["kink_p95_deg"]["abs"] + r["zigzag_p95"] / LIMITS["zigzag_p95"]["abs"]
            + r["dmax_p95_cm"] / LIMITS["dmax_p95_cm"]["abs"] + r["dtip_p95_cm"] / LIMITS["dtip_p95_cm"]["abs"]
            + r["maxseg_p95_cm"] / LIMITS["maxseg_p95_cm"]["abs"] + r["other_mean"] / LIMITS["other_mean"]["abs"]
            + 4 * max(0.0, 0.9 - r.get("coverage", 1.0)) / 0.1
            + 4 * max(0.0, 0.8 - r.get("width_ratio", 1.0)) / 0.1)


def ref_txt(c):
    return "" if c["ref"] is None else f"{c['ref']:.3g}"


def main():
    global SUITE, HIP, OUT, REF, FRESH
    SUITE, HIP, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
    REF = sys.argv[sys.argv.index("--ref") + 1] if "--ref" in sys.argv else None
    FRESH = "--fresh" in sys.argv
    sys.path.insert(0, SUITE)
    os.makedirs(OUT, exist_ok=True)
    hou.hda.installFile(SUITE + "/otls/mono_grooming.hdalc")
    hou.hipFile.load(HIP, suppress_save_prompt=True, ignore_load_warnings=True)
    # the scene may name another checkout's library, newer on disk: this suite's is the one checked
    hou.hda.installFile(SUITE + "/otls/mono_grooming.hdalc", force_use_assets=True)
    from apps.houdini import grooming_adapter as ga
    node = ga.find_nodes()[0]
    if node.parm("cook_all") is not None:   # hidden and isolated-out locks are not cooked for display
        with hou.undos.disabler():
            node.parm("cook_all").set(1)
    geo = node.parent()
    if FRESH:
        node.parm("groom_data").set("")
        node.parm("regions").set(None)
        ga.write_data(node, ga.model.GroomData(asset=ga.read_data(node).asset or "asset"), "qc fresh")
        ga.detect(node)
        ga.split_regions(node)

    def merge(path, name):
        om = geo.createNode("object_merge", name)
        om.parm("objpath1").set(path)
        return om

    hair = merge(node.path() + "/HAIR", "qc_hair")          # the full groom, rest pose, hidden locks too
    mesh = geo.createNode("attribpromote", "qc_mesh")      # the hair mesh, `piece` on its prims
    mesh.setInput(0, merge(node.path() + "/pieces", "qc_pieces"))
    mesh.parm("inname").set("piece")
    mesh.parm("inclass").set(2)       # point
    mesh.parm("outclass").set(1)      # primitive
    mesh.parm("method").set(1)        # minimum: a prim's points are all one piece
    mesh.parm("deletein").set(0)       # coverage reads `piece` per point
    spines = merge(node.path() + "/SPINES", "qc_spines")    # lock_id -> piece
    t = time.time()
    hair.cook(force=True)
    cook_s = time.time() - t
    sg = spines.geometry()
    lock_names = {int(p.attribValue("lock_id")): p.attribValue("name") for p in sg.prims()
                  if sg.findPrimAttrib("name")}

    ours = measure(hair, mesh, spines, "ours")
    report = {"hip": HIP, "suite": SUITE, "cook_full_s": round(cook_s, 2), "ours": summary(ours)}
    ref = None
    if REF:
        imp = geo.createNode("usdimport", "qc_ref")
        imp.parm("filepath1").set(REF)
        for k, v in (("input_unpack", 1), ("unpack_geomtype", 1)):
            if imp.parm(k):
                imp.parm(k).set(v)
        ref = measure(imp, mesh, None, "ref")
        report["ref"] = summary(ref)
        report["ref"]["coverage"] = coverage(mesh, imp)[0]
        report["ref_file"] = REF

    report["profile"] = profile(hair, mesh, spines)
    cov_all, cov_piece = coverage(mesh, hair)
    report["ours"]["coverage"] = cov_all
    piece_of = {int(p.attribValue("lock_id")): int(p.attribValue("piece")) for p in sg.prims()}
    locks = per_lock(ours, lock_names)
    wr = width_ratios(hair.geometry(), node.node("pieces").geometry(), sg)
    for r in locks:
        r["width_ratio"] = wr.get(r["lock_id"], 1.0)
        r["coverage"] = cov_piece.get(piece_of.get(r["lock_id"], -1), 0.0)
        r["badness"] = round(badness(r), 2)
    locks.sort(key=lambda r: -r["badness"])
    s = dict(report["ours"])
    s["lock_dmax_p95_worst_cm"] = max((r["dmax_p95_cm"] for r in locks), default=0.0)
    s["uncovered"] = 1 - report["ours"]["coverage"]
    s["lock_width_ratio_worst"] = min((r["width_ratio"] for r in locks), default=1.0)
    s["lock_uncovered_worst"] = max((1 - r["coverage"] for r in locks), default=0.0)
    if ref is not None:
        report["ref"]["uncovered"] = 1 - report["ref"]["coverage"]
    s["lock_kink_p95_worst_deg"] = max((r["kink_p95_deg"] for r in locks), default=0.0)

    checks = []
    for key, lim in LIMITS.items():
        if lim.get("min") is not None:           # a floor, not a ceiling
            val = s.get(key, 1.0)
            checks.append({"check": key, "value": round(val, 4), "limit": lim["min"], "ref": None,
                           "pass": val >= lim["min"], "why": lim["why"] + " (at least)"})
            continue
        limit = lim["abs"]
        if ref is not None and lim["ref_x"] and key in report["ref"]:
            limit = max(limit, report["ref"][key] * lim["ref_x"]) if key != "other_mean" else limit
            limit = min(limit, max(report["ref"][key] * lim["ref_x"], lim["abs"]))
        val = s.get(key, 0.0)
        checks.append({"check": key, "value": round(val, 4), "limit": round(limit, 4),
                       "ref": round(report["ref"][key], 4) if ref is not None and key in report["ref"] else None,
                       "pass": val <= limit, "why": lim["why"]})
    report["checks"] = checks
    report["passed"] = all(c["pass"] for c in checks)
    report["worst_locks"] = locks[:8]
    report["locks"] = locks

    with open(os.path.join(OUT, "qc_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
    lines = [f"# Hair QC: {'PASS' if report['passed'] else 'FAIL'}", "",
             f"Scene `{HIP}`, {s['strands']} strands, full cook {cook_s:.2f}s"
             + (f", reference `{os.path.basename(REF)}` ({report['ref']['strands']} strands)" if REF else ""),
             "", "| check | ours | reference | limit | | what it catches |", "|---|---|---|---|---|---|"]
    for c in checks:
        lines.append(f"| {c['check']} | {c['value']:.3g} | {ref_txt(c)} "
                     f"| {c['limit']:.3g} | {'ok' if c['pass'] else '**FAIL**'} | {c['why']} |")
    lines += ["", "## Worst locks", "", "| lock | strands | kink p95 | zigzag p95 | seg p95 cm | far p95 cm "
              "| tip p95 cm | on other lock | covered | width / mesh |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in locks[:8]:
        lines.append(f"| {r['name']} | {r['strands']} | {r['kink_p95_deg']:.1f} | {r['zigzag_p95']:.3f} "
                     f"| {r['maxseg_p95_cm']:.2f} | {r['dmax_p95_cm']:.2f} | {r['dtip_p95_cm']:.2f} "
                     f"| {r['other_mean']:.1%} | {r['coverage']:.0%} | {r['width_ratio']:.2f} |")
    lines += ["", "## Along the strand (root -> tip)", "", "| u | dist p50 cm | dist p95 cm | over 2 cm "
              "| angle p95 | bent > 60 |", "|---|---|---|---|---|---|"]
    for r in report["profile"]:
        lines.append(f"| {r['u']} | {r['dist_p50_cm']:.2f} | {r['dist_p95_cm']:.2f} | {r['far_over_2cm']:.1%} "
                     f"| {r['angle_p95_deg']:.0f} | {r['bent_over_60']:.1%} |")
    with open(os.path.join(OUT, "qc_report.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    log("\n".join(lines))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)   # hython's normal exit can hang with Qt modules loaded
