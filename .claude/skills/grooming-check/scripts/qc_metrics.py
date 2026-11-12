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
                               "why": "a lock's hair much narrower than its mesh (collapsed, twisted), the hair's own mass"},
    "lock_start_share_worst": {"abs": None, "min": 0.5, "ref_x": None,
                               "why": "hair in the first 3/10 of a lock over the mesh's share there: a bare, thin start"},
    "lock_dmax_p95_worst_cm": {"abs": 3.0, "ref_x": None, "why": "the worst lock's far points"},
    "lock_kink_p95_worst_deg": {"abs": 50.0, "ref_x": None, "why": "the worst lock's corners"},
    # roots and density (ours only: the reference has no lock ids)
    "density_off_worst": {"abs": 0.15, "ref_x": None,
                          "why": "a lock's strand count off what density x its area asks (|actual/expected - 1|)"},
    "root_clumped": {"abs": 0.05, "ref_x": None,
                     "why": "roots closer than 0.3x the even spacing 1/sqrt(density): brush-like root bunches"},
    "root_spacing_low": {"abs": None, "min": 0.45, "ref_x": None,
                         "why": "median nearest-root distance over the even spacing (random ~0.5, even ~0.9-1.1)"},
    # the lock's shape against its mesh, along its length
    "width_start_off_worst": {"abs": 0.5, "ref_x": None,
                              "why": "hair width over mesh width in tenths 2-3 of the lock, worst (|ratio - 1|): a fan at the start"},
    "width_bulge_worst": {"abs": None, "max": 1.4, "ref_x": None,
                          "why": "widest tenth 2-9 of a lock over its mesh: a fin or fan along the lock"},
    "width_mid_off_worst": {"abs": 0.45, "ref_x": None,
                            "why": "hair width over mesh width, middle of the lock, worst lock (|ratio - 1|)"},
    "tip_width_off_worst": {"abs": 0.6, "ref_x": None,
                            "why": "hair width over mesh width in the last tenth: the end narrows (or flares) unlike its mesh"},
    "tip_center_off_worst": {"abs": 0.5, "ref_x": None,
                             "why": "hair centre off the mesh centre in the last tenth, in mesh widths"},
    "fold_share": {"abs": 0.01, "ref_x": None,
                   "why": "strand points turned over 60 deg from the mesh's direction there (folds, hooks)"},
    "lock_fold_worst": {"abs": 0.05, "ref_x": None, "why": "the worst lock's folded share"},
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


def mesh_point_area(mesh_geo):
    """Per mesh point: the face area it stands for (each face's area shared by its points). Meshes are
    tessellated unevenly (Helen's caps: 23 % of a cap's points in its first tenth, 5 % of its area), so
    shares and spreads of the mesh weigh its points by this, not by count."""
    w = np.zeros(len(mesh_geo.iterPoints()))
    for pr in mesh_geo.prims():
        pts = [v.point().number() for v in pr.vertices()]
        if pts:
            w[pts] += pr.intrinsicValue("measuredarea") / len(pts)
    return w


def width_ratios(hair_geo, mesh_geo, spine_geo):
    """Per lock: the hair's spread over the mesh's along its 2nd principal axis (its width). Strands
    fill a lock while mesh points sit on its surface, so a good lock is ~0.85-1.0; a lock whose hair
    collapsed or twisted inside its mesh (Helen's crown caps) is far below."""
    mp = np.array(mesh_geo.pointFloatAttribValues("P")).reshape(-1, 3)
    mpc = np.array(mesh_geo.pointIntAttribValues("piece"))
    mwt = mesh_point_area(mesh_geo)
    hp = np.array(hair_geo.pointFloatAttribValues("P")).reshape(-1, 3)
    counts = np.array([p.numVertices() for p in hair_geo.prims()])
    hl = np.repeat(np.array(hair_geo.primIntAttribValues("lock_id")), counts)
    # each hair point weighs the length of strand it stands for: every strand has the same point count,
    # so strands that join their lock part way along (root spread) packed their points toward the tip
    # and the unweighted spread of a curved cap read 0.43 while every tenth of it read 0.65-1.0
    seg = np.linalg.norm(np.diff(hp, axis=0), axis=1)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    wgt = np.zeros(len(hp))
    wgt[:-1] += 0.5 * seg
    wgt[1:] += 0.5 * seg
    wgt[starts[1:] - 1] -= 0.5 * seg[starts[1:] - 1]   # no segment from one strand's tip to the next root
    wgt[starts[1:]] -= 0.5 * seg[starts[1:] - 1]

    def spread(x, w=None):
        w = np.ones(len(x)) if w is None else np.maximum(w, 0)
        x = x - np.average(x, axis=0, weights=w)
        cov = (x * w[:, None]).T @ x / max(w.sum(), 1e-12)
        return np.sqrt(np.maximum(np.sort(np.linalg.eigvalsh(cov))[::-1], 0))
    out, raw, start = {}, {}, {}
    for p in spine_geo.prims():
        sel = hl == p.attribValue("lock_id")
        msel = mpc == p.attribValue("piece")
        m, mw, h = mp[msel], mwt[msel], hp[sel]
        if len(m) > 10 and len(h) > 10:
            lid = int(p.attribValue("lock_id"))
            raw[lid] = float(spread(h, wgt[sel])[1] / max(spread(m, mw)[1], 1e-9))
            # the hair's mass along the lock is matched to the mesh's (tenths of the spine, nearest spine
            # point): strands that join a lock part way along leave less hair at its start, which the
            # coverage checks measure; this one is about width (Helen's crown caps: every tenth 0.7-1.0,
            # the whole lock 0.6 before matching, with 2 % of the hair on a start holding 18 % of the mesh)
            sp = np.array([v.point().position() for v in p.vertices()])
            if len(sp) > 1:
                hb = np.minimum((nearest(h, sp) / (len(sp) - 1) * 10).astype(int), 9)
                mb = np.minimum((nearest(m, sp) / (len(sp) - 1) * 10).astype(int), 9)
                hw = wgt[sel]
                hmass = np.bincount(hb, weights=hw, minlength=10)
                mshare = np.bincount(mb, weights=mw, minlength=10) / max(mw.sum(), 1e-12)
                scale = np.where(hmass > 0, mshare / np.maximum(hmass, 1e-12), 0.0)
                out[lid] = float(spread(h, hw * scale[hb])[1] / max(spread(m, mw)[1], 1e-9))
                start[lid] = float(hmass[:3].sum() / max(hmass.sum(), 1e-12) / max(mshare[:3].sum(), 1e-12))
            else:
                out[lid] = raw[lid]
    # the check is the hair's own mass (raw); the mass-matched one is printed beside it only
    width_ratios.matched = out
    width_ratios.start_share = start
    return raw


def hair_arrays(geo):
    """Points (n, 3), per point: strand index, lock id, u along the strand (0 root, 1 tip). The cached
    strands are contiguous (each strand's points in order), checked on the first ones."""
    pos = np.array(geo.pointFloatAttribValues("P")).reshape(-1, 3)
    counts = np.array([p.numVertices() for p in geo.prims()])
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    if len(pos) != counts.sum():
        raise RuntimeError("strands share points: cannot read them as contiguous runs")
    strand = np.repeat(np.arange(len(counts)), counts)
    lock = np.repeat(np.array(geo.primIntAttribValues("lock_id")), counts)
    u = (np.arange(len(pos)) - np.repeat(starts, counts)) / np.maximum(np.repeat(counts, counts) - 1, 1)
    return pos, strand, lock, u, starts, counts


def spine_arrays(sg):
    """lock id -> (points (k, 3), curveu (k,), tangents (k, 3), piece)."""
    out = {}
    for p in sg.prims():
        pts = p.points()
        P = np.array([q.position() for q in pts])
        cu = np.array([q.attribValue("curveu") for q in pts])
        t = np.gradient(P, axis=0)
        t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
        out[int(p.attribValue("lock_id"))] = (P, cu, t, int(p.attribValue("piece")))
    return out


def nearest(a, b, chunk=20000):
    """Index in b of the nearest point to each of a (brute force in chunks; b is a spine, ~50 points)."""
    idx = np.empty(len(a), int)
    for i in range(0, len(a), chunk):
        d = ((a[i:i + chunk, None, :] - b[None, :, :]) ** 2).sum(-1)
        idx[i:i + chunk] = d.argmin(1)
    return idx


def nn_dist(x):
    """Each point's distance to its nearest other point (x: (n, 3), n up to a few thousand)."""
    out = np.empty(len(x))
    for i in range(0, len(x), 2000):
        d = ((x[i:i + 2000, None, :] - x[None, :, :]) ** 2).sum(-1)
        rows = np.arange(i, min(i + 2000, len(x)))
        d[rows - i, rows] = np.inf
        out[i:i + 2000] = np.sqrt(d.min(1))
    return out


def densest_spot(roots_cm, radius=1.0, sample=1500):
    """The densest spot of a groom's roots (a whorl): the root with the most roots within `radius` cm.
    Returns (centre, count there, roots / cm2 on that disc)."""
    if not len(roots_cm):
        return None, 0, 0.0
    cand = roots_cm[np.linspace(0, len(roots_cm) - 1, min(sample, len(roots_cm))).astype(int)]
    best, best_n = cand[0], -1
    for i in range(0, len(cand), 50):
        d = ((cand[i:i + 50, None, :] - roots_cm[None, :, :]) ** 2).sum(-1)
        n = (d <= radius * radius).sum(1)
        j = int(n.argmax())
        if n[j] > best_n:
            best, best_n = cand[i + j], int(n[j])
    return best, best_n, best_n / (np.pi * radius * radius)


def roots_and_density(pos, starts, counts, lock_of_strand, infos, unit_cm, whorl=None):
    """Per lock: strands against density x area (`logic.lock_strands`, what the tool means to grow), and
    how the roots spread: median nearest-root distance over the even spacing 1/sqrt(actual density on the
    lock's area), and the share of roots closer than 0.3x that spacing (bunched roots). Whorl roots
    (`whorl_root`, extra strands the tool packs at a whorl on purpose) are left out of all three and
    counted apart. A lock's start roots (`start_root` without `whorl_root`: its own strands, laid out
    round its root) are counted and measured like any other."""
    roots = pos[starts]
    whorl = np.zeros(len(roots), dtype=bool) if whorl is None else whorl
    out = {}
    for info in infos:
        own = lock_of_strand == info.id
        sel = own & ~whorl
        n = int(sel.sum())
        if n < 3:
            continue
        area = max(info.region_area_cm2, 1e-6)
        spacing = 1.0 / np.sqrt(n / area)                    # cm, if the roots sat evenly on the area
        d = nn_dist(roots[sel]) * unit_cm
        out[info.id] = {"strands": n, "expected": int(info.strands), "density_ratio": n / max(info.strands, 1),
                        "spacing_ratio": float(np.median(d) / spacing), "clumped": float(np.mean(d < 0.3 * spacing)),
                        "area_cm2": area}
    return out


def shape_along(pos, lock, u, mesh_pos, mesh_piece, spines, bins=10):
    """Per lock and tenth of its spine: hair width / mesh width (spread across the lock, perpendicular
    to the spine), hair centre off the mesh centre (in mesh widths), and the share of strand points whose
    direction turns over 60 deg from the spine's there. Hair and mesh points take the curveu of their
    nearest spine point, so both are binned the same way, independent of the tool's own measurement."""
    tang = np.zeros_like(pos)
    tang[1:] = pos[1:] - pos[:-1]
    first = np.concatenate([[True], (lock[1:] != lock[:-1]) | (u[1:] == 0)])
    tang[first] = 0
    nxt = np.zeros_like(pos)
    nxt[:-1] = pos[1:] - pos[:-1]
    tang[first] = nxt[first]
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-12)

    def width(x, t):
        """Width of a point cloud across direction t: sqrt(12 var) of its widest perpendicular axis
        (a uniform spread of width w has var w^2 / 12), and its centre."""
        if len(x) < 6:
            return None, None
        c = x.mean(0)
        y = x - c
        y = y - np.outer(y @ t, t)
        ev = np.linalg.eigvalsh(np.cov(y.T))
        return float(np.sqrt(12 * max(ev[-1], 0))), c

    out = {}
    for lid, (sp, cu, st, piece) in spines.items():
        hs = lock == lid
        ms = mesh_piece == piece
        if hs.sum() < 50 or ms.sum() < 20:
            continue
        hp, mp = pos[hs], mesh_pos[ms]
        hi, mi = nearest(hp, sp), nearest(mp, sp)
        hb, mb = np.minimum((cu[hi] * bins).astype(int), bins - 1), np.minimum((cu[mi] * bins).astype(int), bins - 1)
        cosang = np.abs(np.einsum("ij,ij->i", tang[hs], st[hi]))
        fold = float(np.mean(cosang < np.cos(np.radians(60))))
        rows = []
        for b in range(bins):
            t = st[min(int((b + 0.5) / bins * (len(sp) - 1)), len(sp) - 1)]
            hw, hc = width(hp[hb == b], t)
            mw, mc = width(mp[mb == b], t)
            if hw is None or mw is None or mw <= 1e-6:
                rows.append(None)
                continue
            off = hc - mc
            off = off - (off @ t) * t
            rows.append({"ratio": hw / mw, "center_off": float(np.linalg.norm(off) / mw)})
        out[lid] = {"bins": rows, "fold": fold}
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
        r["width_ratio_matched"] = width_ratios.matched.get(r["lock_id"], 1.0)
        r["start_share"] = width_ratios.start_share.get(r["lock_id"], 1.0)
        r["coverage"] = cov_piece.get(piece_of.get(r["lock_id"], -1), 0.0)
        r["badness"] = round(badness(r), 2)
    locks.sort(key=lambda r: -r["badness"])
    s = dict(report["ours"])
    s["lock_dmax_p95_worst_cm"] = max((r["dmax_p95_cm"] for r in locks), default=0.0)
    s["uncovered"] = 1 - report["ours"]["coverage"]
    s["lock_width_ratio_worst"] = min((r["width_ratio"] for r in locks), default=1.0)
    report["lock_width_ratio_matched_worst"] = min((r["width_ratio_matched"] for r in locks), default=1.0)
    s["lock_start_share_worst"] = min((r["start_share"] for r in locks), default=1.0)
    s["lock_uncovered_worst"] = max((1 - r["coverage"] for r in locks), default=0.0)
    if ref is not None:
        report["ref"]["uncovered"] = 1 - report["ref"]["coverage"]
    s["lock_kink_p95_worst_deg"] = max((r["kink_p95_deg"] for r in locks), default=0.0)

    # roots / density, width profile, folds (numpy over the full hair; ~1 min on Helen)
    t = time.time()
    hgeo = hair.geometry()
    pos, strand, lock, u, starts, counts = hair_arrays(hgeo)
    lock_of_strand = np.array(hgeo.primIntAttribValues("lock_id"))
    unit_cm = float(node.evalParm("unit_cm")) if node.parm("unit_cm") else 100.0
    whorl = (np.array(hgeo.primIntAttribValues("whorl_root")) > 0) if hgeo.findPrimAttrib("whorl_root")         else np.zeros(len(starts), dtype=bool)
    startr = (np.array(hgeo.primIntAttribValues("start_root")) > 0) if hgeo.findPrimAttrib("start_root")         else np.zeros(len(starts), dtype=bool)
    report["start_roots"] = int((startr & ~whorl).sum())
    dens = roots_and_density(pos, starts, counts, lock_of_strand, ga.lock_infos(node), unit_cm, whorl)
    # the whorl: ours (roots the tool packed there) and the densest 1 cm disc of ours and the reference
    _c, n_ours, d_ours = densest_spot(pos[starts] * unit_cm)
    report["whorl"] = {"ours_whorl_roots": int(whorl.sum()), "ours_whorl_share": float(whorl.mean()) if len(whorl) else 0.0,
                       "ours_densest_1cm": n_ours, "ours_densest_1cm_share": n_ours / max(len(starts), 1),
                       "ours_densest_per_cm2": d_ours}
    if REF:
        rg = imp.geometry()
        rroots = np.array([pr.vertices()[0].point().position() for pr in rg.prims()]) * unit_cm
        _c, n_ref, d_ref = densest_spot(rroots)
        report["whorl"].update({"ref_densest_1cm": n_ref, "ref_densest_1cm_share": n_ref / max(len(rroots), 1),
                                "ref_densest_per_cm2": d_ref})
    pg = node.node("pieces").geometry()
    mesh_pos = np.array(pg.pointFloatAttribValues("P")).reshape(-1, 3)
    mesh_piece = np.array(pg.pointIntAttribValues("piece"))
    shape = shape_along(pos, lock, u, mesh_pos, mesh_piece, spine_arrays(sg))
    log(f"roots, width profile, folds: {time.time() - t:.1f}s")
    for r in locks:
        d, sh = dens.get(r["lock_id"]), shape.get(r["lock_id"])
        if d:
            r.update({"density_ratio": d["density_ratio"], "expected": d["expected"],
                      "spacing_ratio": d["spacing_ratio"], "clumped": d["clumped"]})
        if sh:
            mids = [b["ratio"] for b in sh["bins"][3:7] if b]
            tip = sh["bins"][-1]
            r.update({"width_mid": float(np.median(mids)) if mids else 1.0,
                      "width_tip": tip["ratio"] if tip else 1.0, "tip_center_off": tip["center_off"] if tip else 0.0,
                      "fold": sh["fold"], "width_profile": [round(b["ratio"], 2) if b else None for b in sh["bins"]]})
    have = [r for r in locks if "density_ratio" in r]
    s["density_off_worst"] = max((abs(r["density_ratio"] - 1) for r in have), default=0.0)
    s["root_clumped"] = float(np.mean([r["clumped"] for r in have])) if have else 0.0
    s["root_spacing_low"] = float(np.median([r["spacing_ratio"] for r in have])) if have else 1.0
    shp = [r for r in locks if "width_mid" in r]
    s["width_mid_off_worst"] = max((abs(r["width_mid"] - 1) for r in shp), default=0.0)
    prof = [r["width_profile"] for r in shp]
    s["width_start_off_worst"] = max((abs(v - 1) for p in prof for v in p[1:3] if v is not None), default=0.0)
    s["width_bulge_worst"] = max((v for p in prof for v in p[1:9] if v is not None), default=1.0)
    s["tip_width_off_worst"] = max((abs(r["width_tip"] - 1) for r in shp), default=0.0)
    s["tip_center_off_worst"] = max((r["tip_center_off"] for r in shp), default=0.0)
    total_pts = sum(r["strands"] for r in shp) or 1
    s["fold_share"] = float(sum(r["fold"] * r["strands"] for r in shp) / total_pts)
    s["lock_fold_worst"] = max((r["fold"] for r in shp), default=0.0)
    report["along_lock"] = {
        "width_ratio_p50_by_tenth": [round(float(np.median([r["width_profile"][b] for r in shp
                                                             if r["width_profile"][b] is not None])), 2)
                                     for b in range(10)] if shp else [],
    }

    checks = []
    for key, lim in LIMITS.items():
        if lim.get("max") is not None:           # a plain ceiling with no reference
            val = s.get(key, 0.0)
            checks.append({"check": key, "value": round(val, 4), "limit": lim["max"], "ref": None,
                           "pass": val <= lim["max"], "why": lim["why"]})
            continue
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
    if "lock_width_ratio_matched_worst" in report:
        lines += ["", f"For information only (not a check): lock_width_ratio_worst with the hair's mass along the lock "
                      f"matched to the mesh's: {report['lock_width_ratio_matched_worst']:.3g}"]
    w = report.get("whorl", {})
    if w:
        lines += ["", "## Whorl (roots packed on purpose; not in the root checks above)", "",
                  f"Ours: {w['ours_whorl_roots']} whorl roots ({w['ours_whorl_share']:.1%} of all); densest 1 cm disc "
                  f"{w['ours_densest_1cm']} roots ({w['ours_densest_1cm_share']:.1%}), {w['ours_densest_per_cm2']:.0f} / cm2."
                  + (f" Reference: densest 1 cm disc {w['ref_densest_1cm']} roots ({w['ref_densest_1cm_share']:.1%}), "
                     f"{w['ref_densest_per_cm2']:.0f} / cm2." if "ref_densest_1cm" in w else "")]
    lines += ["", "## Worst locks", "", "| lock | strands | kink p95 | zigzag p95 | seg p95 cm | far p95 cm "
              "| tip p95 cm | on other lock | covered | width / mesh |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in locks[:8]:
        lines.append(f"| {r['name']} | {r['strands']} | {r['kink_p95_deg']:.1f} | {r['zigzag_p95']:.3f} "
                     f"| {r['maxseg_p95_cm']:.2f} | {r['dmax_p95_cm']:.2f} | {r['dtip_p95_cm']:.2f} "
                     f"| {r['other_mean']:.1%} | {r['coverage']:.0%} | {r['width_ratio']:.2f} |")
    lines += ["", "## Roots and shape per lock (sorted by the biggest miss)", "",
              "| lock | strands / expected | root spacing | roots bunched | width mid | width tip | tip off centre"
              " | folded | width along the lock (root -> tip) |", "|---|---|---|---|---|---|---|---|---|"]
    miss = lambda r: max(abs(r.get("density_ratio", 1) - 1) / 0.15, abs(r.get("width_tip", 1) - 1) / 0.6,  # noqa: E731
                         abs(r.get("width_mid", 1) - 1) / 0.45, r.get("tip_center_off", 0) / 0.5, r.get("fold", 0) / 0.05,
                         r.get("clumped", 0) / 0.05)
    for r in sorted(locks, key=lambda r: -miss(r))[:12]:
        if "density_ratio" not in r or "width_mid" not in r:
            continue
        lines.append(f"| {r['name']} | {r['strands']} / {r['expected']} ({r['density_ratio']:.2f}) | {r['spacing_ratio']:.2f} "
                     f"| {r['clumped']:.1%} | {r['width_mid']:.2f} | {r['width_tip']:.2f} | {r['tip_center_off']:.2f} "
                     f"| {r['fold']:.2%} | {' '.join('-' if v is None else f'{v:.2f}' for v in r['width_profile'])} |")
    if report.get("along_lock", {}).get("width_ratio_p50_by_tenth"):
        lines += ["", "Hair width / mesh width by tenth of the lock, median over locks: "
                  + " ".join(f"{v:.2f}" for v in report["along_lock"]["width_ratio_p50_by_tenth"])]
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
