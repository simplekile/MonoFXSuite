"""
Build the MONO Grooming SOP HDA (`mono::grooming::0.1`) from code into `otls/mono_grooming.hdalc`.

    hython tools/fx/grooming/build_hda.py [output.hdalc]

The network follows the fixed processing order of docs/plans/grooming_v0_1.md:

  hair mesh -> pieces -> spine + measure -> lock ids from the JSON (root flip) -> settings -> frozen
  regions -> cache keys -> For-Each lock_id that grows and is not cached { region, hairgen, fit to the
  lock, clump, length, frizz, store } -> every growing lock from the cache -> display
  -> point deform by input 3 (optional) -> output

Partial cook: each lock's hair is cooked once per state of what it reads (`lock_keys`, a digest per
lock) and kept in grooming_adapter.LockCache. Hidden locks (eye off, group hidden, isolated out) do
not enter the loop; publish sets `cook_all`. So an edit recooks the locks it changes, hiding cooks
nothing and showing a lock cooked before only merges it back.

Spine and measure (`spine_build`): a lock is cut into `spine_points` bands by the distance from its
root measured along the mesh surface (distancealonggeometry from the points nearest the scalp), not
by projecting onto a straight axis. Along-surface distance follows a strongly bent or folded ribbon,
so every band is one cross-section of the lock. The spine point of a band is the centroid of its
points; the cross-section is a 2D principal-axis fit of the band in the plane normal to the spine
(a parallel-transported frame, so it does not flip): width = extent along the major axis, thickness
= extent along the minor one (about 0 for a flat ribbon, which the fit handles the same way), twist =
angle of the major axis in that frame, unwrapped by pi from band to band. The spine is then resampled
to equal steps, which gives `curveu`.

Hair per lock (`fit_to_lock`): hairgen only scatters the roots on the lock's own region at the
lock's density; every strand is then placed in the lock's measured cross-section, at the spot its
root has in the region (region principal axes mapped onto the lock's width and thickness axes), and
blended from its root on the scalp into that shape over the first `root_blend` of its length.

Only `hou`; no Houdini GUI needed. Indie licence -> .hdalc.
"""

from __future__ import annotations

import glob
import os
import sys

import hou

SUITE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if SUITE not in sys.path:
    sys.path.insert(0, SUITE)

from tools.fx.grooming import config  # noqa: E402

DEFAULT_OUT = os.path.join(SUITE, "otls", "mono_grooming.hdalc")

# ---------------------------------------------------------------------------
# VEX
# ---------------------------------------------------------------------------

VEX_SCALP_DIST = """// distance of each hair-mesh point to the scalp
f@scalpdist = nprimitives(1) > 0 ? xyzdist(1, @P) : @P.y;
"""

# The root of a lock is one END of its ribbon, found along the surface: from the point nearest the
# scalp go to the farthest point A, from A to the farthest point B; A and B are the two ends and the
# one nearer the scalp is the root. "Every point near the scalp" (the first rule) took whole ribbons
# lying on the scalp (Helen's hair_base) as root, so bands ran along the lock and a 4 cm ribbon
# measured 20 cm wide.

def _per_piece_pick(attrib: str, best: str, group: str) -> str:
    """Detail VEX: per piece, the point with the lowest/highest `attrib` goes to `group`."""
    better = "<" if best == "min" else ">"
    start = "1e30" if best == "min" else "-1e30"
    return f"""// per piece: the point with the {best} {attrib} -> group {group}
int np = npoints(0);
int npc = 0;
for (int i = 0; i < np; i++) npc = max(npc, point(0, "piece", i) + 1);
float bv[]; int bp[];
resize(bv, npc); resize(bp, npc);
for (int k = 0; k < npc; k++) {{ bv[k] = {start}; bp[k] = -1; }}
for (int i = 0; i < np; i++) {{
    int k = point(0, "piece", i);
    float v = point(0, "{attrib}", i);
    if (v < 0 && "{attrib}" != "scalpdist") continue;   // not reached by the distance pass
    if (v {better} bv[k]) {{ bv[k] = v; bp[k] = i; }}
}}
for (int k = 0; k < npc; k++) if (bp[k] >= 0) setpointgroup(0, "{group}", bp[k], 1);
"""


VEX_SEED_NEAREST = _per_piece_pick("scalpdist", "min", "s0")
VEX_END_A = _per_piece_pick("d0", "max", "end_a")

VEX_ROOT_END = """// per piece: B = farthest from A; the root end is whichever of A, B is nearer the scalp
int np = npoints(0);
int npc = 0;
for (int i = 0; i < np; i++) npc = max(npc, point(0, "piece", i) + 1);
float bd[]; int bb[], aa[];
resize(bd, npc); resize(bb, npc); resize(aa, npc);
for (int k = 0; k < npc; k++) { bd[k] = -1; bb[k] = -1; aa[k] = -1; }
for (int i = 0; i < np; i++) {
    int k = point(0, "piece", i);
    if (inpointgroup(0, "end_a", i)) aa[k] = i;
    float v = point(0, "dA", i);
    if (v > bd[k]) { bd[k] = v; bb[k] = i; }
}
for (int k = 0; k < npc; k++) {
    int a = aa[k], b = bb[k];
    if (a < 0 && b < 0) continue;
    float sa = a >= 0 ? point(0, "scalpdist", a) : 1e30;   // typed: point() is ambiguous inside '<'
    float sb = b >= 0 ? point(0, "scalpdist", b) : 1e30;
    int r = sb < sa ? b : a;
    setpointgroup(0, "root_end", r, 1);
}
"""

VEX_ROOT_SEEDS = """// root of every piece: its points within root_tolerance of the lock's length from the root end
int np = npoints(0);
int npc = 0;
for (int i = 0; i < np; i++) npc = max(npc, point(0, "piece", i) + 1);
float mx[];
resize(mx, npc);
for (int i = 0; i < np; i++) {
    int k = point(0, "piece", i);
    mx[k] = max(mx[k], point(0, "dR", i));
}
float tol = chf("../root_tolerance");
for (int i = 0; i < np; i++) {
    int k = point(0, "piece", i);
    float d = point(0, "dR", i);
    setpointgroup(0, "root", i, d >= 0 && d <= tol * mx[k] ? 1 : 0);
}
"""

VEX_MEASURE_SAMPLES = """// points spread evenly over each piece's faces, for spine_build's cross-sections: a band is fitted
// to the points inside it, and a low-res lock had ~5 (Helen hair_base_03: 254 mesh points, 48 bands),
// which measured 1.6 cm across a 4 cm cap and twisted its hair. At least measure_samples points per
// piece, by face area; dist comes from the faces. The mesh stays (spine_build reads its names).
int target = max(chi("../measure_samples"), 0);
if (target == 0) return;
int npr = nprimitives(0);
float area[]; int pcs[]; resize(area, npr); resize(pcs, npr);
float tot[];
for (int pr = 0; pr < npr; pr++) {
    area[pr] = primintrinsic(0, "measuredarea", pr);
    pcs[pr] = point(0, "piece", primpoint(0, pr, 0));
    if (pcs[pr] >= len(tot)) resize(tot, pcs[pr] + 1);
    tot[pcs[pr]] += area[pr];
}
for (int pr = 0; pr < npr; pr++) {
    if (tot[pcs[pr]] <= 0) continue;
    int k = int(ceil(target * area[pr] / tot[pcs[pr]]));
    for (int j = 0; j < k; j++) {
        vector uv = set(rand(set(pr, j, 0.17)), rand(set(pr, j, 0.71)), 0);
        vector p = primuv(0, "P", pr, uv);          // typed: untyped primuv() is ambiguous here
        float d = primuv(0, "dist", pr, uv);
        int pt = addpoint(0, p);
        setpointattrib(0, "piece", pt, pcs[pr]);
        setpointattrib(0, "dist", pt, d);
    }
}
"""

VEX_SPINE_BUILD = """// one spine per piece: band centroids by along-surface distance, cross-section fit per band
int N = max(chi("../spine_points"), 3);
int np = npoints(1);
int npc = 0;
for (int i = 0; i < np; i++) npc = max(npc, point(1, "piece", i) + 1);
float maxd[]; resize(maxd, npc);
vector rsum[]; resize(rsum, npc); int rcnt[]; resize(rcnt, npc);
vector csum[]; resize(csum, npc * N); int ccnt[]; resize(ccnt, npc * N);
int band[]; resize(band, np);
for (int i = 0; i < np; i++) {
    int k = point(1, "piece", i);
    maxd[k] = max(maxd[k], point(1, "dist", i));
}
for (int i = 0; i < np; i++) {
    int k = point(1, "piece", i);
    float d = point(1, "dist", i);
    vector p = point(1, "P", i);
    if (d <= 1e-9) { rsum[k] += p; rcnt[k] += 1; }
    int b = maxd[k] > 0 ? clamp(int(floor(d / maxd[k] * N)), 0, N - 1) : 0;
    band[i] = b;
    csum[k * N + b] += p; ccnt[k * N + b] += 1;
}
string names[]; resize(names, npc);
if (hasprimattrib(1, "name")) {
    for (int pr = 0; pr < nprimitives(1); pr++) {
        int k = point(1, "piece", primpoint(1, pr, 0));
        if (names[k] == "") names[k] = prim(1, "name", pr);
    }
}
// spine points: root centroid + N band centroids (empty bands interpolated)
int M = N + 1;
vector C[]; resize(C, npc * M);
for (int k = 0; k < npc; k++) {
    C[k * M] = rcnt[k] > 0 ? rsum[k] / rcnt[k] : csum[k * N] / max(ccnt[k * N], 1);
    for (int b = 0; b < N; b++) {
        if (ccnt[k * N + b] > 0) { C[k * M + b + 1] = csum[k * N + b] / ccnt[k * N + b]; continue; }
        int lo = b - 1, hi = b + 1;
        while (lo >= 0 && ccnt[k * N + lo] == 0) lo--;
        while (hi < N && ccnt[k * N + hi] == 0) hi++;
        vector a = lo >= 0 ? csum[k * N + lo] / ccnt[k * N + lo] : C[k * M];
        vector c = hi < N ? csum[k * N + hi] / ccnt[k * N + hi] : a;
        float t = (hi < N && hi != lo) ? float(b - lo) / float(hi - lo) : 0.0;
        C[k * M + b + 1] = lerp(a, c, t);
    }
}
// parallel-transported frame per spine point
vector T[], F1[], F2[]; resize(T, npc * M); resize(F1, npc * M); resize(F2, npc * M);
for (int k = 0; k < npc; k++) {
    for (int j = 0; j < M; j++) {
        vector t = C[k * M + min(j + 1, M - 1)] - C[k * M + max(j - 1, 0)];
        T[k * M + j] = length(t) > 1e-12 ? normalize(t) : {0, -1, 0};
    }
    vector t0 = T[k * M];
    vector n = cross(t0, abs(t0.y) < 0.9 ? {0, 1, 0} : {1, 0, 0});
    n = normalize(n);
    for (int j = 0; j < M; j++) {
        vector t = T[k * M + j];
        n = n - t * dot(n, t);
        n = length(n) > 1e-12 ? normalize(n) : normalize(cross(t, {1, 0, 0}));
        F1[k * M + j] = n;
        F2[k * M + j] = cross(t, n);
    }
}
// pass 2: 2D covariance of each band in its frame
float sxx[], syy[], sxy[]; resize(sxx, npc * M); resize(syy, npc * M); resize(sxy, npc * M);
for (int i = 0; i < np; i++) {
    int k = point(1, "piece", i);
    int j = k * M + band[i] + 1;
    vector dp = point(1, "P", i) - C[j];
    float x = dot(dp, F1[j]), y = dot(dp, F2[j]);
    sxx[j] += x * x; syy[j] += y * y; sxy[j] += x * y;
}
float TH[]; resize(TH, npc * M);
vector A[], B[]; resize(A, npc * M); resize(B, npc * M);
for (int k = 0; k < npc; k++) {
    for (int j = 1; j < M; j++) {
        int q = k * M + j;
        float th = 0.5 * atan2(2 * sxy[q], sxx[q] - syy[q]);
        // a round cross-section has no major axis: keep the previous band's angle there
        float aniso = sqrt(pow(sxx[q] - syy[q], 2) + 4 * sxy[q] * sxy[q]) / max(sxx[q] + syy[q], 1e-20);
        if (j > 1 && aniso < chf("../round_section")) th = TH[q - 1];
        if (j > 1) {
            float prev = TH[q - 1];
            while (th - prev > M_PI / 2) th -= M_PI;
            while (th - prev < -M_PI / 2) th += M_PI;
        }
        TH[q] = th;
    }
    TH[k * M] = TH[k * M + 1];
    for (int j = 0; j < M; j++) {
        int q = k * M + j;
        A[q] = cos(TH[q]) * F1[q] + sin(TH[q]) * F2[q];
        B[q] = cross(T[q], A[q]);
    }
}
// pass 3: extents along the major / minor axes
float amin[], amax[], bmin[], bmax[];
resize(amin, npc * M); resize(amax, npc * M); resize(bmin, npc * M); resize(bmax, npc * M);
for (int q = 0; q < npc * M; q++) { amin[q] = 1e30; amax[q] = -1e30; bmin[q] = 1e30; bmax[q] = -1e30; }
for (int i = 0; i < np; i++) {
    int k = point(1, "piece", i);
    int q = k * M + band[i] + 1;
    vector dp = point(1, "P", i) - C[q];
    float a = dot(dp, A[q]), b = dot(dp, B[q]);
    amin[q] = min(amin[q], a); amax[q] = max(amax[q], a);
    bmin[q] = min(bmin[q], b); bmax[q] = max(bmax[q], b);
}
for (int k = 0; k < npc; k++) {
    if (maxd[k] <= 0) continue;
    int pr = addprim(0, "polyline");
    float len = 0;
    for (int j = 0; j < M; j++) {
        int q = k * M + j;
        int qq = j == 0 ? q + 1 : q;   // the root takes the first band's cross-section
        int pt = addpoint(0, C[q]);
        addvertex(0, pr, pt);
        if (j > 0) len += distance(C[q], C[q - 1]);
        setpointattrib(0, "lock_width", pt, amax[qq] > amin[qq] ? amax[qq] - amin[qq] : 0.0);
        setpointattrib(0, "lock_thick", pt, bmax[qq] > bmin[qq] ? bmax[qq] - bmin[qq] : 0.0);
        setpointattrib(0, "lock_twist", pt, TH[q] - TH[k * M + 1]);
        setpointattrib(0, "lock_axis", pt, A[q]);
        setpointattrib(0, "lock_minor", pt, B[q]);
    }
    setprimattrib(0, "piece", pr, k);
    setprimattrib(0, "mesh_name", pr, names[k]);
    setprimattrib(0, "root", pr, C[k * M]);
    setprimattrib(0, "length", pr, len);
    setprimattrib(0, "direction", pr, normalize(C[k * M + M - 1] - C[k * M]));
}
"""

VEX_SPINE_ATTRIBS = """// declare spine attributes so they exist even with no piece
addpointattrib(0, "lock_width", 0.0);
addpointattrib(0, "lock_thick", 0.0);
addpointattrib(0, "lock_twist", 0.0);
addpointattrib(0, "lock_axis", {0, 0, 0});
addpointattrib(0, "lock_minor", {0, 0, 0});
addprimattrib(0, "piece", 0);
addprimattrib(0, "mesh_name", "");
addprimattrib(0, "root", {0, 0, 0});
addprimattrib(0, "length", 0.0);
addprimattrib(0, "direction", {0, 0, 0});
"""

VEX_APPLY_SETTINGS = """// measured shape x settings: width_mult, thick_mult, + twist_add along the lock
int pr = pointprims(0, @ptnum)[0];
float u = f@curveu;
f@lock_width *= prim(0, "width_mult", pr);
f@lock_thick *= prim(0, "thick_mult", pr);
float add = prim(0, "twist_add", pr) * u;
f@lock_twist += add;
vector t = v@tangentu;
vector a = normalize(v@lock_axis - t * dot(v@lock_axis, t));
vector4 q = quaternion(add, t);
v@lock_axis = qrotate(q, a);
v@lock_minor = cross(t, v@lock_axis);
"""

VEX_SPINE_FLIP = """// root_flip (the user's per-lock "root end"): the root is the piece's other end. The spine is
// reversed in place: the bands were measured from the end Detect took, and seen from the other end they
// are the same cross-sections in reverse order. Measured from the new root: curveu, twist; the tangent
// turns round, so the minor axis (tangent x axis) does too. Detect still matches on the measured root
// (SPINES_RAW), so a flipped lock keeps its id and its flip through re-Detect.
if (i@root_flip == 0) return;
int pts[] = primpoints(0, @primnum);
int n = len(pts);
if (n < 2) return;
vector P[], A[], TG[]; float W[], TK[], TW[], U[];
foreach (int p; pts) {
    vector v = point(0, "P", p); append(P, v);
    vector a = point(0, "lock_axis", p); append(A, a);
    vector tg = point(0, "tangentu", p); append(TG, tg);
    float w = point(0, "lock_width", p); append(W, w);
    float tk = point(0, "lock_thick", p); append(TK, tk);
    float tw = point(0, "lock_twist", p); append(TW, tw);
    float u = point(0, "curveu", p); append(U, u);
}
for (int i = 0; i < n; i++) {
    int j = n - 1 - i, p = pts[i];
    setpointattrib(0, "P", p, P[j]);
    setpointattrib(0, "lock_width", p, W[j]);
    setpointattrib(0, "lock_thick", p, TK[j]);
    setpointattrib(0, "lock_twist", p, TW[n - 1] - TW[j]);   // an angle around the reversed tangent
    setpointattrib(0, "curveu", p, 1 - U[j]);
    setpointattrib(0, "tangentu", p, -TG[j]);
    setpointattrib(0, "lock_axis", p, A[j]);
    setpointattrib(0, "lock_minor", p, normalize(cross(-TG[j], A[j])));
}
v@root = P[n - 1];
v@direction = normalize(P[0] - P[n - 1]);
"""

VEX_LOCK_SHOWN = """// what the display draws (shown) and what grows hair (grows): the lock's eye with its group's
// (visible, from groom_data), or exactly the isolated locks; every lock while publishing (cook_all).
// Excluded locks keep their guide and mesh but grow no hair. Hidden locks are not cooked at all.
int on = i@visible;
string iso = chs("../isolate_ids");
if (iso != "") on = find(split(iso), itoa(i@lock_id)) >= 0;
if (chi("../cook_all")) on = 1;
// the lock's display: its own (or its group's) Display, else the node's; lighter while playing like
// the node's (display_eff); full hair while publishing
int m = i@row_display >= 0 ? i@row_display : chi("../display_eff");
if (chi("../playing") && chi("../play_display") > 0) m = min(m, chi("../play_display"));
if (chi("../cook_all")) m = 3;
i@disp = m;
i@shown = on;
i@grows = on && i@excluded == 0 && m >= 2;   // only preview and hair grow strands
"""

VEX_GUIDE_ROOT = """// guide root on the scalp
if (vertexprimindex(0, pointvertex(0, @ptnum)) == 0 && nprimitives(1) > 0) {
    int sp; vector suv;
    xyzdist(1, @P, sp, suv);
    @P = primuv(1, "P", sp, suv);
}
"""

VEX_REGION_POINTS = """// provisional point lock_owner (nearest root) for scalps not split yet; the frozen split is per prim.
// Hidden locks keep their region (hiding never changes another lock's hair); excluded ones take none.
i@lock_owner = -1;
if (npoints(1) == 0) {
    float best = 1e30;
    for (int pr = 0; pr < nprimitives(2); pr++) {
        int id = prim(2, "lock_id", pr);
        int ex = prim(2, "excluded", pr);
        if (id < 0 || ex) continue;
        float d = distance2(@P, point(2, "P", primpoint(2, pr, 0)));
        if (d < best) { best = d; i@lock_owner = id; }
    }
}
"""

VEX_REGION_PRIMS = """// prim lock_owners: the frozen split (Update regions: one frozen point per scalp prim, its centroid,
// by prim number, or the nearest centroid when the scalp changed), else the majority of the
// provisional point owners. Stacked locks share a prim: share = number of owners, density = their
// mean (each owner grows its density / share there, so the prim's strand count stays the same).
int own[];
int nf = npoints(2);
if (nf > 0) {
    vector c = 0;
    int pp[] = primpoints(0, @primnum);
    foreach (int p; pp) c += point(0, "P", p);
    c /= max(len(pp), 1);
    int src = nearpoint(2, c);   // by position, never by prim number: a re-exported scalp may reorder
    own = point(2, "lock_owners", src);
} else {
    int pts[] = primpoints(0, @primnum);
    int ids[], cnt[];
    foreach (int p; pts) {
        int o = point(0, "lock_owner", p);
        int at = find(ids, o);
        if (at < 0) { append(ids, o); append(cnt, 1); } else cnt[at] += 1;
    }
    int best = -1, bc = 0;
    for (int i = 0; i < len(ids); i++)
        if (cnt[i] > bc || (cnt[i] == bc && ids[i] < best)) { best = ids[i]; bc = cnt[i]; }
    if (best >= 0) append(own, best);
}
i[]@lock_owners = own;
i@lock_owner = len(own) > 0 ? own[0] : -1;
i@share = len(own);
float u = chf("../unit_cm");
f@area_cm2 = primintrinsic(0, "measuredarea", @primnum) * u * u;
float dsum = 0;
foreach (int o; own) {
    int sp = findattribval(1, "prim", "lock_id", o);
    if (sp >= 0) dsum += prim(1, "density", sp);
}
f@density = len(own) > 0 ? dsum / len(own) : 0.0;
"""

VEX_PREVIEW = """// expected strands at full count and the hair_preview density factor
float total = 0;
for (int pr = 0; pr < nprimitives(0); pr++) total += prim(0, "density", pr) * prim(0, "area_cm2", pr);
f@expected = total;
float f = clamp(chf("../preview_fraction"), 0.0, 1.0);
int cap = chi("../preview_max");
// capped: snapped down to a step of %(step)s^k, since the factor is in every lock's cache key and an exact
// cap / total changed with any density edit (grooming_adapter.preview_factor, the same rule)
if (total * f > cap && total > 0) {
    f = cap / total;
    if (f > 0) f = pow(%(step)s, ceil(log(f) / log(%(step)s) - 1e-6));
}
f@factor = chi("../display_eff") == 2 ? f : 1.0;   // display_eff: the display mode, lighter while playing
f@preview_factor = f;   // the locks a slider is dragging (preview_ids) grow at this, whatever the display
// fingerprints of each lock's region for the hair cache (adapter.cook_lock_keys): per lock id 9 floats
// summing what the per-lock loop reads of its prims (count, area / share, share, centre, centre x a
// weight by prim number, so a moved or swapped prim changes it)
int mx = -1;
for (int pr = 0; pr < nprimitives(0); pr++) {
    int own[] = prim(0, "lock_owners", pr);
    foreach (int o; own) mx = max(mx, o);
}
float rk[]; resize(rk, (mx + 1) * 9);
for (int pr = 0; pr < nprimitives(0); pr++) {
    int own[] = prim(0, "lock_owners", pr);
    if (len(own) == 0) continue;
    float a = prim(0, "area_cm2", pr);
    int sh = prim(0, "share", pr);
    vector c = primuv(0, "P", pr, {0.5, 0.5, 0});
    float wq = 1 + (pr %% 13) * 0.37;
    foreach (int o; own) {
        int k = o * 9;
        rk[k] += 1; rk[k + 1] += a / max(sh, 1); rk[k + 2] += sh;
        rk[k + 3] += c.x; rk[k + 4] += c.y; rk[k + 5] += c.z;
        rk[k + 6] += c.x * wq; rk[k + 7] += c.y * wq; rk[k + 8] += c.z * wq;
    }
}
f[]@region_keys = rk;
""" % {"step": config.PREVIEW_FACTOR_STEP}

VEX_SURFACE_KEYS = """// fingerprints of each piece's lookup cloud for the hair cache: per piece 9 floats (count, cloud
// position, ds, dt, position x a weight by point number)
int np = npoints(0);
int mx = -1;
for (int i = 0; i < np; i++) mx = max(mx, point(0, "piece", i));
float sk[]; resize(sk, (mx + 1) * 9);
for (int i = 0; i < np; i++) {
    int k = point(0, "piece", i) * 9;
    vector p = point(0, "P", i);
    float ds = point(0, "ds", i), dt = point(0, "dt", i);
    float wq = 1 + (i % 11) * 0.29;
    sk[k] += 1; sk[k + 1] += p.x; sk[k + 2] += p.y; sk[k + 3] += p.z; sk[k + 4] += ds; sk[k + 5] += dt;
    sk[k + 6] += p.x * wq; sk[k + 7] += p.y * wq; sk[k + 8] += p.z * wq;
}
f[]@surface_keys = sk;
"""

VEX_REGION_CUT = """// only this lock's region (the prims it owns alone or shares)
int id = prim(1, "lock_id", 0);
if (find(i[]@lock_owners, id) < 0) removeprim(0, @primnum, 1);
"""

VEX_REGION_FRAME = """// region frame: centroid, principal axes on the scalp, half extents
int n = npoints(0);
if (n == 0) return;
vector c = 0;
for (int i = 0; i < n; i++) c += point(0, "P", i);
c /= n;
vector nn = 0;
for (int pr = 0; pr < nprimitives(0); pr++) nn += prim_normal(0, pr, 0.5, 0.5);
nn = length(nn) > 1e-12 ? normalize(nn) : {0, 1, 0};
vector e1 = normalize(cross(nn, abs(nn.y) < 0.9 ? {0, 1, 0} : {1, 0, 0}));
vector e2 = cross(nn, e1);
float sxx = 0, syy = 0, sxy = 0;
for (int i = 0; i < n; i++) {
    vector d = point(0, "P", i) - c;
    float x = dot(d, e1), y = dot(d, e2);
    sxx += x * x; syy += y * y; sxy += x * y;
}
float th = 0.5 * atan2(2 * sxy, sxx - syy);
vector ra = cos(th) * e1 + sin(th) * e2;
vector rb = cross(nn, ra);
float ea = 0, eb = 0;
for (int i = 0; i < n; i++) {
    vector d = point(0, "P", i) - c;
    ea = max(ea, abs(dot(d, ra))); eb = max(eb, abs(dot(d, rb)));
}
v@rc = c; v@ra = ra; v@rb = rb; f@rea = ea; f@reb = eb;
// strands: density x the lock's share of the scalp, but at least density x the lock's own cross-section
// (its widest band, thickness >= 30 % of the width): locks whose roots converge on a small patch
// (Helen's fringe) and long locks that widen far from the root (hair_back: the first quarter gave
// 800 strands to a 12 cm wide ribbon, see-through) get as many strands as their mesh shows.
float dens = prim(1, "density", 0);
float area = 0;
for (int pr = 0; pr < nprimitives(0); pr++) {
    float a = prim(0, "area_cm2", pr);   // typed: inside an int expression prim() would return int
    int sh = prim(0, "share", pr);
    area += a / max(sh, 1);
}
int sp[] = primpoints(1, 0);
float w = 0, t = 0;
for (int i = 0; i < len(sp); i++) {
    w = max(w, point(1, "lock_width", sp[i]));
    t = max(t, point(1, "lock_thick", sp[i]));
}
float u = chf("../unit_cm");
float section = M_PI / 4 * (w * u) * (max(t, 0.3 * w) * u);
f@region_cm2 = area;
f@section_cm2 = section;
f@lock_density = area > 0 ? dens * max(area, section) / area : 0.0;
"""

VEX_REGION_DENSITY = """// the lock's density (with the cross-section floor), divided where it shares the scalp
int prs[] = pointprims(0, @ptnum);
float s = 0;
foreach (int pr; prs) { int sh = prim(0, "share", pr); s += sh; }
s = len(prs) > 0 ? s / len(prs) : 1.0;
f@density = detail(0, "lock_density") / max(s, 1.0);
"""

VEX_SURFACE_PARAMS = """// every hair-mesh point: where it sits along its lock (pu, the spine's parameter) and its offset
// across the lock in the spine's measured frame (ds along the width axis, dt along the thickness axis)
f@pu = -1; f@ds = 0; f@dt = 0; f@ps = 0;
int sp = findattribval(1, "prim", "piece", i@piece);
if (sp < 0) return;
int hp; vector huv;
xyzdist(1, itoa(sp), v@P, hp, huv);
vector c = primuv(1, "P", sp, huv);
vector a = normalize(primuv(1, "lock_axis", sp, huv));
vector m = normalize(primuv(1, "lock_minor", sp, huv));
float w = max(primuv(1, "lock_width", sp, huv), 1e-6);
f@pu = huv.x;
f@ds = dot(v@P - c, a);
f@dt = dot(v@P - c, m);
f@ps = clamp(f@ds / (0.5 * w), -1.5, 1.5);
"""

VEX_SPINE_SMOOTH = """// blur along the spine: each inner point moves halfway to its neighbours' average, the ends stay
// (Attribute Blur pins every point of an open curve: all of them are on its border)
int pts[] = primpoints(0, @primnum);
int n = len(pts), it = chi("../spine_smooth");
if (n < 3 || it <= 0) return;
vector P[]; foreach (int p; pts) { vector v = point(0, "P", p); append(P, v); }
for (int k = 0; k < it; k++) {
    vector W[] = P;
    for (int i = 1; i < n - 1; i++) W[i] = lerp(P[i], (P[i - 1] + P[i + 1]) * 0.5, 0.5);
    P = W;
}
for (int i = 1; i < n - 1; i++) setpointattrib(0, "P", pts[i], P[i]);
for (int i = 0; i < n; i++)        // Resample's tangentu is from before the blur; later nodes project on it
    setpointattrib(0, "tangentu", pts[i], normalize(P[min(i + 1, n - 1)] - P[max(i - 1, 0)]));
string fl[] = {"lock_width", "lock_thick"};
foreach (string a; fl) {
    if (!haspointattrib(0, a)) continue;
    float V[]; foreach (int p; pts) { float v = point(0, a, p); append(V, v); }
    for (int k = 0; k < it; k++) {
        float W[] = V;
        for (int i = 1; i < n - 1; i++) W[i] = lerp(V[i], (V[i - 1] + V[i + 1]) * 0.5, 0.5);
        V = W;
    }
    for (int i = 1; i < n - 1; i++) setpointattrib(0, a, pts[i], V[i]);
}
// The frame (lock_axis across, lock_minor through the thickness). A band's principal axis has no sign
// and is near random where the band is round: Helen's crown caps turned 40-145 deg between
// neighbours, and every mesh offset measured in that frame put a corner in the strands. The axis
// becomes an angle around the spine from a frame carried along it (parallel transport), doubled so
// a sign flip is no turn, unwrapped, smoothed over a long stretch, and the frame is rebuilt.
if (!haspointattrib(0, "lock_axis")) return;
vector T[]; resize(T, n);
for (int i = 0; i < n; i++) T[i] = normalize(P[min(i + 1, n - 1)] - P[max(i - 1, 0)]);
vector R[]; resize(R, n);
vector a0 = point(0, "lock_axis", pts[0]);
R[0] = normalize(a0 - T[0] * dot(a0, T[0]));
for (int i = 1; i < n; i++) {
    vector r = R[i - 1] - T[i] * dot(R[i - 1], T[i]);      // carried: no twist added
    R[i] = normalize(r);
}
float th[]; resize(th, n);
for (int i = 0; i < n; i++) {
    vector ax = point(0, "lock_axis", pts[i]);
    vector side = cross(T[i], R[i]);
    th[i] = 2 * atan2(dot(ax, side), dot(ax, R[i]));       // doubled: axis and -axis are one line
}
for (int i = 1; i < n; i++) {
    while (th[i] - th[i - 1] > M_PI) th[i] -= 2 * M_PI;
    while (th[i] - th[i - 1] < -M_PI) th[i] += 2 * M_PI;
}
for (int k = 0; k < it * 4; k++) {
    float W[] = th;
    for (int i = 1; i < n - 1; i++) W[i] = (th[i - 1] + 2 * th[i] + th[i + 1]) * 0.25;
    W[0] = (2 * th[0] + th[1]) / 3.0; W[n - 1] = (2 * th[n - 1] + th[n - 2]) / 3.0;
    th = W;
}
for (int i = 0; i < n; i++) {
    float h = th[i] * 0.5;
    vector ax = normalize(R[i] * cos(h) + cross(T[i], R[i]) * sin(h));
    setpointattrib(0, "lock_axis", pts[i], ax);
    setpointattrib(0, "lock_minor", pts[i], normalize(cross(T[i], ax)));
}
"""

VEX_SURFACE_EXTENT = """// ps (across) comes from the measured width, narrower than the mesh where a lock widens: Helen's
// mesh points reached ps 1.5 and strands (s in -1..1) left both edges bare. Per piece and per tenth of
// its length, ps is stretched so the mesh's own edges are -1 and 1.
int NB = 10;
int np = npoints(0);
int pcs[]; float pus[], pss[];
resize(pcs, np); resize(pus, np); resize(pss, np);
int maxp = 0;
for (int i = 0; i < np; i++) {
    pcs[i] = point(0, "piece", i); pus[i] = point(0, "pu", i); pss[i] = point(0, "ps", i);
    maxp = max(maxp, pcs[i]);
}
float lo[], hi[];
resize(lo, (maxp + 1) * NB); resize(hi, (maxp + 1) * NB);
for (int k = 0; k < len(lo); k++) { lo[k] = 1e9; hi[k] = -1e9; }
for (int i = 0; i < np; i++) {
    int k = pcs[i] * NB + clamp(int(pus[i] * NB), 0, NB - 1);
    lo[k] = min(lo[k], pss[i]); hi[k] = max(hi[k], pss[i]);
}
// empty bands take their neighbour's extent, then a [1 2 1] blur along the lock, and every point reads
// the extent interpolated between band centres: steps from band to band shifted the lookup sideways
// and put a corner in every strand at a band edge (Helen hair_base_01: 82 deg at u 0.55)
for (int pc = 0; pc <= maxp; pc++) {
    for (int pass = 0; pass < 2; pass++)
        for (int j = 0; j < NB; j++) {
            int k = pc * NB + j;
            if (lo[k] > 1e8) {
                int kk = pc * NB + (pass == 0 ? max(j - 1, 0) : min(j + 1, NB - 1));
                lo[k] = lo[kk]; hi[k] = hi[kk];
            }
        }
    for (int it = 0; it < 2; it++) {
        float L[], H[]; resize(L, NB); resize(H, NB);
        for (int j = 0; j < NB; j++) {
            int a = pc * NB + max(j - 1, 0), b = pc * NB + j, c = pc * NB + min(j + 1, NB - 1);
            L[j] = (lo[a] + 2 * lo[b] + lo[c]) * 0.25; H[j] = (hi[a] + 2 * hi[b] + hi[c]) * 0.25;
        }
        for (int j = 0; j < NB; j++) { lo[pc * NB + j] = L[j]; hi[pc * NB + j] = H[j]; }
    }
}
for (int i = 0; i < np; i++) {
    float x = clamp(pus[i] * NB - 0.5, 0, NB - 1);
    int j0 = int(floor(x)), j1 = min(j0 + 1, NB - 1);
    float f = x - j0;
    int k0 = pcs[i] * NB + j0, k1 = pcs[i] * NB + j1;
    float a = min(lerp(lo[k0], lo[k1], f), -0.2), b = max(lerp(hi[k0], hi[k1], f), 0.2);  // one-sided keeps scale
    float v = pss[i] < 0 ? -pss[i] / a : pss[i] / b;
    setpointattrib(0, "ps", i, v);
}
"""

PIECE_GAP = 100.0   # far beyond (along x weight, across) = (3, 1): lookups never reach another piece
SHEET_GAP = 10.0    # a lock's underside (dt < 0) sits this far from its top side in the cloud

VEX_SURFACE_CLOUD = """// the mesh points as a cloud in (along, across) space, for fit_to_lock's lookup; z = the piece x
// PIECE_GAP keeps each lock's points apart, so a lookup needs no per-lock blast (73 ms a lock)
// and its underside (dt < 0) at + SHEET_GAP: top and underside share (along, across), and one lookup
// for both made strands jump between them every segment (zigzags of the lock's thickness)
@P = set(f@pu * chf("../surface_along_weight"), f@ps, i@piece * %(gap)s + (f@dt < 0 ? %(sheet)s : 0));
""" % {"gap": PIECE_GAP, "sheet": SHEET_GAP}

_FIT_PARAMS = """float wm = prim(1, "width_mult", 0), tm = prim(1, "thick_mult", 0);
if (wm <= 0) wm = 1;
if (tm <= 0) tm = 1;
float aw = chf("../surface_along_weight");
float pz = prim(1, "piece", 0) * %(gap)s;
float cm = 1.0 / max(chf("../unit_cm"), 1e-6);
int fl = prim(1, "root_flip", 0);
"""

_FIT_PLACE = """vector place(float uu; float ss; float tt; float aw; float pz; float wm; float tm; float cm; int fl) {
    // a flipped lock (root_flip) runs its spine the other way; the cloud keeps the mesh's own along
    // parameter and thickness side (from SPINES_RAW), so it is read at 1 - u, the other side, and the
    // thickness offset turns with the reversed minor axis
    float ul = fl ? 1 - uu : uu;
    float tl = fl ? -tt : tt;
    float sg = fl ? -1.0 : 1.0;
    vector uv = set(uu, 0, 0);
    vector c = primuv(1, "P", 0, uv);
    vector a = normalize(primuv(1, "lock_axis", 0, uv));
    vector m = normalize(primuv(1, "lock_minor", 0, uv));
    float w = primuv(1, "lock_width", 0, uv), th = primuv(1, "lock_thick", 0, uv);
    float vol = min(min(th, 0.15 * w), cm);           // volume around the surface, at most 1 cm
    // the cloud keeps the mesh's faces: the nearest spot on them, interpolated, is continuous along
    // the strand (the nearest POINT jumped from one mesh point to the next). Top side and underside
    // are looked up apart and blended by t, so a strand stays at one depth inside the lock.
    int ht, hb; vector uvt, uvb;
    xyzdist(3, set(ul * aw, ss, pz), ht, uvt, %(gap)s * 0.5);
    xyzdist(3, set(ul * aw, ss, pz + %(sheet)s), hb, uvb, %(gap)s * 0.5);
    if (ht < 0)                                         // no mesh for this piece: the ellipse
        return c + a * (ss * 0.5 * w) + m * (tt * 0.5 * th);
    float dst = primuv(3, "ds", ht, uvt), dtt = primuv(3, "dt", ht, uvt);
    float dsb = primuv(3, "ds", hb, uvb), dtb = primuv(3, "dt", hb, uvb);
    float k = clamp((tl + 1) * 0.5, 0, 1);
    float ds = lerp(dsb, dst, k), dt = lerp(dtb, dtt, k);
    float extra = max(vol - abs(dtt - dtb), 0);         // a one-sided ribbon still gets some volume
    return c + a * (ds * wm) + m * (sg * dt * tm + tt * 0.5 * extra);
}
"""

VEX_FIT_ROOT = ("""// place the strand on the lock's own mesh surface (not on a flat ellipse: wide caps like Helen's
// hair_base are curved), from its root on the scalp. (s, t) = where its root sits in the lock's
// region; the mesh offset at (u, s) comes from the surface cloud (input 3), then the lock's settings
// (width_mult, thick_mult, twist_add through the spine's axes) apply; t adds a little volume.
// fit_root runs once per strand (prim wrangle): (s, t), the root and its placement, the same for all
// its points; fit_to_lock then places each point (a point wrangle: writing points from a prim
// wrangle was 2.5x slower).
int pr = @primnum;
int nv = primvertexcount(0, pr);
vector root = point(0, "P", primpoint(0, pr, 0));
vector rc = detail(2, "rc"), ra = detail(2, "ra"), rb = detail(2, "rb");
float s = clamp(dot(root - rc, ra) / max(detail(2, "rea"), 1e-6), -1, 1);
float t = clamp(dot(root - rc, rb) / max(detail(2, "reb"), 1e-6), -1, 1);
int p0 = primpoint(1, 0, 0);
vector a0 = point(1, "lock_axis", p0), m0 = point(1, "lock_minor", p0);
if (dot(ra, a0) < 0) s = -s;
if (dot(rb, m0) < 0) t = -t;
// where a root fell in the region bunches strands in the middle of the lock (Helen: 22 %% of the mesh
// with no strand near it before clumping); cross_spread moves each strand toward an even spread over
// the whole cross-section. root_pull then brings its root under that spot.
float spread = clamp(chf("../cross_spread"), 0, 1);
if (spread > 0) {
    s = lerp(s, fit01(rand(set(pr, 0.37, 1.7)), -1, 1), spread);
    t = lerp(t, fit01(rand(set(pr, 2.91, 0.3)), -1, 1), spread);
}

""" + _FIT_PARAMS + _FIT_PLACE + """

vector c0 = place(0.0, s, t, aw, pz, wm, tm, cm, fl);
// roots are scattered over the lock's whole scalp region, often much wider than the lock's own root:
// pulled toward the mesh root at the same (s, t) and put back on the region, strands leave the scalp
// like the mesh does instead of fanning in from all over the region
float pull = clamp(chf("../root_pull"), 0, 1);
if (pull > 0 && nprimitives(2) > 0) {
    int rp; vector ruv;
    xyzdist(2, lerp(root, c0, pull), rp, ruv);
    root = primuv(2, "P", rp, ruv);
}
f@fit_s = s; f@fit_t = t; v@fit_c0 = c0; v@fit_root = root;
""") % {"gap": PIECE_GAP, "sheet": SHEET_GAP}

VEX_FIT = ("""// each strand point: the lock's mesh offset at (u, s, t), eased onto the root over root_blend
int pr = pointprims(0, @ptnum)[0];
int nv = primvertexcount(0, pr);
float u = nv > 1 ? float(vertexprimindex(0, pointvertex(0, @ptnum))) / (nv - 1) : 0.0;
float s = prim(0, "fit_s", pr), t = prim(0, "fit_t", pr);
vector c0 = prim(0, "fit_c0", pr), root = prim(0, "fit_root", pr);
""" + _FIT_PARAMS + _FIT_PLACE + """
@P = (u <= 0 ? c0 : place(u, s, t, aw, pz, wm, tm, cm, fl)) +(root - c0) * (1 - smooth(0, max(chf("../root_blend"), 1e-4), u));
""") % {"gap": PIECE_GAP, "sheet": SHEET_GAP}

VEX_STRAND_SMOOTH = """// a surface lookup can land on a fold of the flattened mesh and throw one point off (Helen: 2-11 %
// of points bent back over 90 deg). The strand's offset from its lock's spine (smooth already) gets a
// median of 3, which removes single spikes, then a light blur; the root stays.
int pts[] = primpoints(0, @primnum);
int n = len(pts), it = chi("../strand_smooth");
if (n < 4 || it <= 0) return;
vector O[], S[];
for (int i = 0; i < n; i++) {
    vector sp = primuv(1, "P", 0, set(float(i) / (n - 1), 0, 0));
    vector p = point(0, "P", pts[i]);
    append(S, sp); append(O, p - sp);
}
vector M[] = O;
for (int i = 1; i < n - 1; i++) {                  // median of 3, per component
    vector a = O[i - 1], b = O[i], c = O[i + 1], r;
    for (int k = 0; k < 3; k++) {
        float x = a[k], y = b[k], z = c[k];
        r[k] = max(min(x, y), min(max(x, y), z));
    }
    M[i] = r;
}
for (int k = 0; k < it; k++) {
    vector W[] = M;
    for (int i = 1; i < n - 1; i++) W[i] = lerp(M[i], (M[i - 1] + M[i + 1]) * 0.5, 0.5);
    W[n - 1] = lerp(M[n - 1], M[n - 2], 0.25);
    M = W;
}
vector P[]; resize(P, n);
for (int i = 0; i < n; i++) P[i] = i == 0 ? point(0, "P", pts[0]) : S[i] + M[i];
// the root sits on the scalp while the next points already follow the mesh: the first joint was the
// sharpest corner of most strands (Helen: 5 % of points in the first 5 % bent over 60 deg). The first
// fifth of the strand is relaxed in place, root held, fading out along it (a hard stop made its own
// corner where the relaxed part met the rest), so the strand leaves the scalp on a curve.
int nr = max(4, int(ceil(n * 0.2)));
for (int k = 0; k < it * 2; k++) {
    vector Q[] = P;
    for (int i = 1; i < min(nr, n - 1); i++) {
        float wgt = 0.5 * (1 - smooth(0, 1, float(i) / nr));
        Q[i] = lerp(P[i], (P[i - 1] + P[i + 1]) * 0.5, wgt);
    }
    P = Q;
}
for (int i = 1; i < n; i++) setpointattrib(0, "P", pts[i], P[i]);
"""

VEX_STRAND_TAGS = """// lock attributes on every strand (no display colour or visibility: those change without a recook,
// so they are not in the lock's cache key; hair_color looks the colour up after the cache)
i@lock_id = prim(1, "lock_id", 0);
s@name = prim(1, "name", 0);
s@group = prim(1, "group", 0);
i@clumpid = i@lock_id;
f@clumpblend = prim(1, "clump", 0);   // the lock's clump drives hairclump's blend
f@length_mult = prim(1, "length_mult", 0);
f@frizz = prim(1, "frizz", 0);
"""

VEX_LENGTH_FRIZZ = """// length_mult (cut or extend along the strand), then frizz (noise across the strand, growing to the tip)
int pts[] = primpoints(0, @primnum);
int n = len(pts);
if (n < 2) return;
vector P[];
foreach (int p; pts) { vector pp = point(0, "P", p); append(P, pp); }
float lm = f@length_mult;
if (abs(lm - 1) > 1e-4 && lm > 0) {
    float cl[]; resize(cl, n);
    for (int i = 1; i < n; i++) cl[i] = cl[i - 1] + distance(P[i], P[i - 1]);
    float total = cl[n - 1];
    vector Q[]; resize(Q, n);
    vector tipdir = normalize(P[n - 1] - P[n - 2]);
    int j = 0;
    for (int i = 0; i < n; i++) {
        float s = total * lm * i / (n - 1);
        if (s >= total) { Q[i] = P[n - 1] + tipdir * (s - total); continue; }
        while (j < n - 2 && cl[j + 1] < s) j++;
        float seg = cl[j + 1] - cl[j];
        Q[i] = lerp(P[j], P[j + 1], seg > 0 ? (s - cl[j]) / seg : 0.0);
    }
    P = Q;
}
float fr = f@frizz;
if (fr > 0) {
    float amp = chf("../frizz_amp") * fr, fq = chf("../frizz_freq");
    vector Q[] = P;
    for (int i = 1; i < n; i++) {
        float u = float(i) / (n - 1);
        vector tg = normalize(P[min(i + 1, n - 1)] - P[i - 1]);
        vector nz = noise(set(u * fq, @primnum * 1.37, i@lock_id * 0.71));
        nz -= {0.5, 0.5, 0.5};
        nz -= tg * dot(nz, tg);
        Q[i] = P[i] + nz * (2 * amp * u);
    }
    P = Q;
}
for (int i = 0; i < n; i++) setpointattrib(0, "P", pts[i], P[i]);
"""

VEX_HAIR_OUT = """// contract attributes on the strands. Clumped per lock, so hairclump's clump numbers restart in
// every lock: clump_id = lock_id x CLUMP_ID_STRIDE + its clump, unique in the groom
i@clump_id = i@lock_id * %d + i@clumpid;
""" % config.CLUMP_ID_STRIDE

VEX_COLOR_POINTS = """// display colour by lock or by group
int pr = pointprims(0, @ptnum)[0];
vector c = chi("../color_by") == 0 ? prim(0, "lock_cd", pr) : prim(0, "group_cd", pr);
v@Cd = c;
"""

VEX_HAIR_COLOR = """// strand display colour by lock or group, looked up on the spines: the cached strands carry no colour
// (a colour change recooks no lock). Per strand (prim Cd): 116 k prims, not 4 M points.
int sp = findattribval(1, "prim", "lock_id", i@lock_id);
vector c = {0.25, 0.25, 0.25};
if (sp >= 0) {
    vector lc = prim(1, "lock_cd", sp), gc = prim(1, "group_cd", sp);
    c = chi("../color_by") == 0 ? lc : gc;
}
v@Cd = c;
"""

VEX_FOCUS = """// the panel's selection (focus_ids): the other locks are drawn see-through (ghost_* wrangles)
string toks[] = split(chs("../focus_ids"));
int ids[];
foreach (string t; toks) append(ids, atoi(t));
i[]@focus = ids;
"""


def _vex_ghost(focus_input: int, lock_id: str, cls: str) -> str:
    """Out of focus: the colour towards a grey and see-through. Alpha is added only then, so with nothing
    in focus the geometry carries no Alpha (the viewport draws no transparency pass)."""
    tint = "{%s, %s, %s}" % config.GHOST_TINT
    return """
// focus: the panel's selection keeps its colour, the other locks are see-through grey
int fo[] = detail(%(i)d, "focus");
if (len(fo) > 0 && find(fo, %(lid)s) < 0) {
    v@Cd = lerp(v@Cd, %(tint)s, %(mix)s);
    add%(cls)sattrib(0, "Alpha", 1.0);
    set%(cls)sattrib(0, "Alpha", @%(num)s, chf("../xray_opacity"));
}
""" % {"i": focus_input, "lid": lock_id, "tint": tint, "mix": config.GHOST_MIX, "cls": cls,
       "num": "primnum" if cls == "prim" else "ptnum"}


VEX_DISPLAY_MODES = """// which displays the shown locks use (disp: 0 mesh, 1 guide, 2 preview, 3 hair)
int m[] = {0, 0, 0, 0};
for (int i = 0; i < nprimitives(0); i++) {
    int d = prim(0, "disp", i), on = prim(0, "shown", i);
    if (on && d >= 0 && d < 4) m[d] = 1;
}
i@any_mesh = m[0];
i@any_guide = m[1];
"""

VEX_MESH_COLOR = """// mesh display: lock of the piece from the spines, hidden (and isolated-out) locks removed
int k = point(0, "piece", primpoint(0, @primnum, 0));
int sp = findattribval(1, "prim", "piece", k);
int on = sp >= 0 ? prim(1, "shown", sp) : 1;
int m = sp >= 0 ? prim(1, "disp", sp) : chi("../display_eff");
if (on == 0 || m != 0) { removeprim(0, @primnum, 1); return; }   // only the locks shown as mesh
i@lock_id = sp >= 0 ? prim(1, "lock_id", sp) : -1;
vector c = {0.25, 0.25, 0.25};
if (sp >= 0) c = chi("../color_by") == 0 ? prim(1, "lock_cd", sp) : prim(1, "group_cd", sp);
v@Cd = c;
"""

VEX_REST_NAMES = """// prim names of the rest hair mesh (Geo_HairBang ...): which prims of a packed anim input are hair
string names[];
if (hasprimattrib(0, "name")) names = uniquevals(0, "prim", "name");
s[]@rest_names = names;
"""

VEX_ANIM_KIND = """// a packed USD anim input (USD Import left packed) is unpacked here, hair prims only
string t = nprimitives(0) > 0 ? primintrinsic(0, "typename", 0) : "";
i@packed = t == "PackedUSD";
"""

VEX_ANIM_KEEP = """// keep the gprims named like a rest hair mesh prim (by name, path, or the path's last part): matching
// "Hair" would also take Helen's HairProxy_grp/Geo_Eyebrows
string nm[] = detail(1, "rest_names");
string path = s@path, name = s@name;
string parts[] = split(path, "/");
string leaf = len(parts) > 0 ? parts[-1] : "";
if (find(nm, name) < 0 && find(nm, path) < 0 && find(nm, leaf) < 0) removeprim(0, @primnum, 1);
"""

VEX_ANIM_CHECK = """// deform only with the rest mesh's points: another count would move the wrong points
i@deform_ok = npoints(0) == npoints(1) && npoints(0) > 0;
if (!i@deform_ok && npoints(0) > 0)
    warning("Anim hair mesh: %d points, rest hair mesh %d: no deform", npoints(0), npoints(1));
"""

# ---------------------------------------------------------------------------
# network
# ---------------------------------------------------------------------------


def _wrangle(parent, name, code, cls, inputs=()):
    n = parent.createNode("attribwrangle", name)
    n.parm("class").set(cls)  # 0 detail, 1 primitive, 2 point
    n.parm("snippet").set(code)
    for i, src in enumerate(inputs):
        if src is not None:
            n.setInput(i, src)
    return n


def _node(parent, kind, name, inputs=(), **parms):
    n = parent.createNode(kind, name)
    for i, src in enumerate(inputs):
        if src is not None:
            n.setInput(i, src)
    for k, v in parms.items():
        n.parm(k).set(v)
    return n


DETAIL, PRIM, POINT = 0, 1, 2


def build_network(sub) -> None:
    """Create every node of the HDA inside `sub` (a SOP subnet with 3 indirect inputs)."""
    ins = sub.indirectInputs()
    # The scalp and the rest hair mesh are read at one fixed frame: a USD Import upstream is time
    # dependent even for a static file, which made the whole groom recook on every frame (2 s/frame on
    # Helen) when only the deform by input 2 should.
    rest_scalp = _node(sub, "timeshift", "rest_frame_scalp", [ins[0]])
    rest_hair = _node(sub, "timeshift", "rest_frame_hair", [ins[1]])
    for ts in (rest_scalp, rest_hair):
        ts.parm("frame").setExpression('ch("../rest_frame")')
    in_scalp = _node(sub, "null", "IN_SCALP", [rest_scalp])
    in_hair = _node(sub, "null", "IN_HAIR", [rest_hair])
    in_anim = _node(sub, "null", "IN_ANIM", [ins[2]])
    sections = []

    def section(title):
        seen = {n for _, ns in sections for n in ns}
        sections.append((title, [n for n in sub.children() if n not in seen]))

    section("Inputs (rest frame)")

    # ---- pieces, spine and measure ----
    pieces = _node(sub, "connectivity", "pieces", [in_hair], connecttype=0, attribname="piece")
    sdist = _wrangle(sub, "scalp_dist", VEX_SCALP_DIST, POINT, [pieces, in_scalp])
    # the two ends of each ribbon along its surface; the one nearer the scalp is the root
    s0 = _wrangle(sub, "root_seed0", VEX_SEED_NEAREST, DETAIL, [sdist])
    d0 = _node(sub, "distancealonggeometry", "dist_from_seed0", [s0], startpts="s0", outattrib="d0")
    end_a = _wrangle(sub, "end_a", VEX_END_A, DETAIL, [d0])
    da = _node(sub, "distancealonggeometry", "dist_from_end_a", [end_a], startpts="end_a", outattrib="dA")
    root_end = _wrangle(sub, "root_end", VEX_ROOT_END, DETAIL, [da])
    dr = _node(sub, "distancealonggeometry", "dist_from_root_end", [root_end], startpts="root_end",
               outattrib="dR")
    for n in (d0, da, dr):
        n.parm("distmetric").set(0)  # along edges: fast, close to the surface distance on a quad mesh
    seeds = _wrangle(sub, "root_seeds", VEX_ROOT_SEEDS, DETAIL, [dr])
    dist = _node(sub, "distancealonggeometry", "dist_from_root", [seeds],
                 startpts="root", outattrib="dist")
    dist.parm("distmetric").set(0)  # along edges: fast, and on a quad mesh close to the surface distance
    empty = _node(sub, "add", "empty")
    attrs = _wrangle(sub, "spine_attribs", VEX_SPINE_ATTRIBS, DETAIL, [empty])
    samples = _wrangle(sub, "measure_samples", VEX_MEASURE_SAMPLES, DETAIL, [dist])
    build = _wrangle(sub, "spine_build", VEX_SPINE_BUILD, DETAIL, [attrs, samples])
    resample = _node(sub, "resample", "spine_resample", [build], dolength=0, dosegs=1,
                     docurveuattr=1, dotangentattr=1)
    resample.parm("segs").setExpression('ch("../spine_points")')
    # band centroids and frames jump from band to band (Helen: median corner 34 deg every 2.8 cm), and
    # every strand inherits them as zigzags: blurred along the spine, root and tip held
    smooth = _wrangle(sub, "spine_smooth", VEX_SPINE_SMOOTH, PRIM, [resample])
    raw = _node(sub, "null", "SPINES_RAW", [smooth])
    # the hair mesh as a lookup cloud: strands follow its real surface, curved caps included
    sparams = _wrangle(sub, "surface_params", VEX_SURFACE_PARAMS, POINT, [pieces, raw])
    sextent = _wrangle(sub, "surface_extent", VEX_SURFACE_EXTENT, DETAIL, [sparams])
    scloud = _wrangle(sub, "surface_cloud", VEX_SURFACE_CLOUD, POINT, [sextent])
    surface = _node(sub, "null", "SURFACE_CLOUD", [scloud])
    section("Pieces, root ends, spines")

    # ---- lock ids, names, groups and resolved settings from the JSON ----
    assign = _node(sub, "python", "assign_locks", [raw])
    assign.parm("python").set("from apps.houdini import grooming_adapter\n"
                              "grooming_adapter.cook_assign(hou.pwd())\n")
    flip = _wrangle(sub, "spine_flip", VEX_SPINE_FLIP, PRIM, [assign])
    spines_locks = _node(sub, "null", "SPINES_LOCKS", [flip])
    settings = _wrangle(sub, "apply_settings", VEX_APPLY_SETTINGS, POINT, [spines_locks])
    spines = _node(sub, "null", "SPINES", [settings])
    # hidden locks (the panel's eye) are not cooked for display; publish (cook_all) cooks every lock
    guides_cut = _node(sub, "blast", "guides_keep", [spines], group="@lock_id<0", grouptype=4)
    shown = _wrangle(sub, "lock_shown", VEX_LOCK_SHOWN, PRIM, [guides_cut])
    roots = _wrangle(sub, "guide_roots", VEX_GUIDE_ROOT, POINT, [shown, in_scalp])
    guides = _wrangle(sub, "guide_length", 'f@lock_len = primintrinsic(0, "measuredperimeter", @primnum);\n',
                      PRIM, [roots])
    section("Locks and settings (groom_data)")

    # ---- frozen regions, on a finer scalp (bilinear: same shape and UVs) so footprints are not one prim ----
    fine = _node(sub, "subdivide", "scalp_subdivide", [in_scalp])
    fine.parm("algorithm").set("osdbilinear")
    fine.parm("iterations").setExpression('ch("../region_subdiv")')
    scalp_fine = _node(sub, "null", "SCALP_FINE", [fine])
    frozen = _node(sub, "python", "frozen_regions", [scalp_fine])
    frozen.parm("python").set("from apps.houdini import grooming_adapter\n"
                              "grooming_adapter.cook_frozen_regions(hou.pwd())\n")
    rpts = _wrangle(sub, "region_points", VEX_REGION_POINTS, POINT, [scalp_fine, frozen, spines])
    rprims = _wrangle(sub, "region_prims", VEX_REGION_PRIMS, PRIM, [rpts, spines, frozen])
    regions = _node(sub, "null", "SCALP_REGIONS", [rprims])
    preview = _wrangle(sub, "PREVIEW", VEX_PREVIEW, DETAIL, [regions])
    section("Frozen regions")

    # ---- hair cache: only locks that grow and are not cached go through the loop ----
    # Every lock's hair is cooked once per state of its inputs and kept (grooming_adapter.LockCache):
    # an edit of one lock recooks that lock, hiding cooks nothing, showing a cached lock merges it back.
    # Clump, length and frizz run per lock inside the loop, so no whole-groom node is left to recook.
    skeys = _wrangle(sub, "surface_keys", VEX_SURFACE_KEYS, DETAIL, [surface])
    keys = _node(sub, "python", "lock_keys", [guides, preview, skeys])
    keys.parm("python").set("from apps.houdini import grooming_adapter\n"
                            "grooming_adapter.cook_lock_keys(hou.pwd())\n")
    to_cook = _node(sub, "blast", "to_cook", [keys], group="@grows==0 @cached==1", grouptype=4)
    section("Hair cache keys")

    # ---- hairgen per lock ----
    begin = _node(sub, "block_begin", "foreach_begin", [to_cook], method=1, blockpath="../foreach_end")
    scalp_in = _node(sub, "block_begin", "foreach_scalp", [regions], method=3, blockpath="../foreach_end")
    cut = _wrangle(sub, "region_cut", VEX_REGION_CUT, PRIM, [scalp_in, begin])
    frame = _wrangle(sub, "region_frame", VEX_REGION_FRAME, DETAIL, [cut, begin])
    rdens = _wrangle(sub, "region_density", VEX_REGION_DENSITY, POINT, [frame])
    # hairgen scatters the roots and grows straight unguided strands; fit_to_lock gives them the
    # lock's shape (the spine as a hairgen guide would need skinprim/skinuv on the region).
    hairgen = _node(sub, "hairgen::2.0", "hairgen", [rdens], useguides=0, growunguided=1,
                    useinitdirattrib=0, unguidedlength=0.01)
    # segments by the lock's length (24 on a 90 cm lock made 4 cm straight runs across its curves)
    # a lock a slider is dragging: DRAG_SEGMENTS (its real strand count, coarser, while the drag lasts)
    hairgen.parm("unguidedsegments").setExpression(
        'if(prim("../foreach_begin", 0, "drag_seg", 0), %d, '
        'max(32, ceil(prim("../foreach_begin", 0, "lock_len", 0) * ch("../unit_cm") '
        '/ max(ch("../strand_segment_cm"), 0.1))))' % config.DRAG_SEGMENTS)
    hairgen.parm("densityoverride").set(1)  # skin attribute "density" (strands/cm2) x the parm
    hairgen.parm("density").setExpression(
        'pow(ch("../unit_cm"), 2) * prim("../foreach_begin", 0, "strand_factor", 0)')
    hairgen.parm("scatterseed").setExpression('prim("../foreach_begin", 0, "lock_id", 0)')
    hairgen.parm("thickness").setExpression('ch("../strand_width")')
    fit_root = _wrangle(sub, "fit_root", VEX_FIT_ROOT, PRIM, [hairgen, begin, frame, surface])
    fit = _wrangle(sub, "fit_to_lock", VEX_FIT, POINT, [fit_root, begin, frame, surface])
    sm_strand = _wrangle(sub, "strand_smooth", VEX_STRAND_SMOOTH, PRIM, [fit, begin])
    tags = _wrangle(sub, "strand_tags", VEX_STRAND_TAGS, PRIM, [sm_strand, begin])
    # clump on the lock's own region: hairgen's skinprim / skinprimuv index this region cut, so they
    # are valid on it as they are (one hairclump over the whole scalp needed them looked up again)
    clump_skin = _wrangle(sub, "clump_skin", "v@rest = @P;  // hairclump wants a rest skin\n", POINT,
                          [rdens])
    clump = _node(sub, "hairclump::2.0", "clump", [tags, clump_skin])
    clump.parm("clumpsize").setExpression('ch("../clump_size")')
    # the lock's clump setting is hairclump's blend (per strand `clumpblend`): its tightness alone does not
    # switch clumping off (tightness 0 still left 27 % of Helen's mesh bare, blend 0 left 10 %)
    clump.parm("tightness").set(0.5)
    clump.parm("blend").set(1.0)
    clump.parm("blendoverride").set("curveattrib")
    clump.parm("blendcurveattrib").set("clumpblend")
    lf = _wrangle(sub, "length_frizz", VEX_LENGTH_FRIZZ, PRIM, [clump])
    hair_out = _wrangle(sub, "hair_attribs", VEX_HAIR_OUT, PRIM, [lf])
    nothing = _node(sub, "add", "no_strands")
    has_region = _node(sub, "switch", "has_region", [nothing, hair_out])
    has_region.parm("input").setExpression('if(nprims("../region_cut") > 0, 1, 0)')
    # with the shot deform on, each lock is captured to the rest hair mesh here, once, and kept with its
    # strands: a capture of all 4 M points (and the merge it waits for) cost 3-9 s on every hide or show
    lock_capture = _node(sub, "pointdeform", "lock_capture", [has_region, in_hair], mode="capture")
    lock_capture.parm("radius").setExpression('ch("../deform_radius")')
    captured = _node(sub, "switch", "captured", [has_region, lock_capture])
    # per lock (lock_keys): always with Shot deform on; with it off, full-hair locks only, so turning it on
    # recooks nothing, while a preview lock or a drag tick skips the capture (~0.3 s a lock)
    captured.parm("input").setExpression('prim("../foreach_begin", 0, "do_capture", 0)')
    store = _node(sub, "python", "cache_store", [captured, begin])
    store.parm("python").set("from apps.houdini import grooming_adapter\n"
                             "grooming_adapter.cook_cache_store(hou.pwd())\n")
    end = _node(sub, "block_end", "foreach_end", [store], itermethod=1, method=1, useattrib=1,
                attrib="lock_id", blockpath="../foreach_begin", templatepath="../foreach_begin")
    end.parm("class").set(0)
    section("Hair per lock (for each lock_id): hairgen, fit, clump, length, frizz")

    # ---- every lock that grows, from the cache ----
    merged = _node(sub, "python", "hair_cache", [end, keys])
    merged.parm("python").set("from apps.houdini import grooming_adapter\n"
                              "grooming_adapter.cook_hair_cache(hou.pwd())\n")
    hair = _node(sub, "null", "HAIR", [merged])
    section("Hair from the cache")

    # ---- publish: the full hair, without display-only attributes ----
    # skinprim / skinprimuv refer to the per-lock region inside the loop, not the scalp: dropped
    pub_clean = _node(sub, "attribdelete", "publish_clean", [hair], primdel="lock_cd group_cd tightness clumpblend fit_s fit_t fit_c0 fit_root "
                      "length_mult frizz clumpid skinprim skinprimuv path visible Cd",
                      ptdel="Cd tightness skinprim skinprimuv pCaptPts pCaptWeights")
    pub = _node(sub, "usdexport", "PUBLISH_USD",[pub_clean])
    pub.parm("lopoutput").setExpression('chs("../publish_path")', language=hou.exprLanguage.Hscript)
    pub.parm("pathprefix").set("/groom")
    pub.parm("enable_pathattr").set(1)
    pub.parm("pathattr").set("name")          # one BasisCurves prim per lock: /groom/<lock name>
    pub.parm("authortimesamples").set("never")  # the asset groom is static
    pub.parm("enable_topologyhandling").set(1)
    pub.parm("topologyhandling").set("static")
    pub.parm("trange").set(0)
    section("Publish")

    # ---- display ----
    # which displays are in use at all: the mesh branch colours every mesh polygon (196 k on Helen) and
    # cooked on each edit once the parts were merged, though no lock was shown as mesh
    modes = _wrangle(sub, "display_modes", VEX_DISPLAY_MODES, DETAIL, [shown])
    nothing_shown = _node(sub, "add", "nothing_shown")
    focus = _wrangle(sub, "focus", VEX_FOCUS, DETAIL, [nothing_shown])
    mesh_col0 = _wrangle(sub, "mesh_color", VEX_MESH_COLOR + _vex_ghost(2, "i@lock_id", "prim"), PRIM,
                         [pieces, shown, focus])
    mesh_col = _node(sub, "switch", "mesh_in_use", [nothing_shown, mesh_col0])
    mesh_col.parm("input").setExpression('detail("../display_modes", "any_mesh", 0)')
    guides_vis = _node(sub, "blast", "guides_visible", [shown], group="@shown==0 @disp!=1", grouptype=4)
    guide_col0 = _wrangle(sub, "guide_color", VEX_COLOR_POINTS +
                          _vex_ghost(1, 'prim(0, "lock_id", pointprims(0, @ptnum)[0])', "point"), POINT,
                          [guides_vis, focus])
    guide_col = _node(sub, "switch", "guide_in_use", [nothing_shown, guide_col0])
    guide_col.parm("input").setExpression('detail("../display_modes", "any_guide", 0)')
    hair_col = _wrangle(sub, "hair_color", VEX_HAIR_COLOR + _vex_ghost(2, "i@lock_id", "prim"), PRIM,
                        [hair, spines, focus])
    # each lock in its own display (its row's Display, else the node's): mesh, guide and hair side by
    # side in one output, so the parts are merged, not switched on the node's mode
    disp = _node(sub, "merge", "display", [mesh_col, guide_col, hair_col])
    # What the viewport shows when there is no shot deform: the hair as one packed prim per lock
    # (cook_hair_packed), coloured per packed prim. An edit or a hide then changes one or no packed prim
    # and the viewport keeps the others; the merged strands above are for publish and the deform only.
    # The locks in `strand_ids` are drawn as strands after the packed prims (their width ramp shows).
    packed = _node(sub, "python", "hair_packed", [end, keys])
    packed.parm("python").set("from apps.houdini import grooming_adapter\n"
                              "grooming_adapter.cook_hair_packed(hou.pwd())\n")
    # packed prims carry their colour inside (cook_hair_packed, see-through ones too); this colours the
    # locks drawn as strands
    packed_col = _wrangle(sub, "hair_packed_color", VEX_HAIR_COLOR + _vex_ghost(2, "i@lock_id", "prim"),
                          PRIM, [packed, spines, focus])
    disp_fast = _node(sub, "merge", "display_fast", [mesh_col, guide_col, packed_col])
    section("Display")

    # ---- shot deform: the animated hair mesh, from a packed USD import too ----
    # A USD Import unpacked to polygons costs 0.1-0.3 s a frame for the whole character (627 k points on
    # Helen, the hair is 196 k); packed it is 0.001 s. A packed USD input is unpacked here to its gprims
    # as packed prims, only those named like the rest hair mesh's prims are kept, and only they become
    # polygons, points only (no primvars). An unpacked input goes through as it is.
    rest_names = _wrangle(sub, "rest_names", VEX_REST_NAMES, DETAIL, [in_hair])
    anim_kind = _wrangle(sub, "anim_kind", VEX_ANIM_KIND, DETAIL, [in_anim])
    gprims = _node(sub, "unpackusd", "anim_gprims", [anim_kind], output="packedprims",
                   unpacktraversal="std:boundables")
    keep = _wrangle(sub, "anim_keep_hair", VEX_ANIM_KEEP, PRIM, [gprims, rest_names])
    polys = _node(sub, "unpackusd", "anim_unpack", [keep], output="polygons", unpacktraversal="std:boundables",
                  importprimvars="", addpathattrib=0, addfilepathattrib=0, addnameattrib=0, detailattributes=0)
    pick = _node(sub, "switch", "anim_packed", [in_anim, polys])
    pick.parm("input").setExpression('detail("../anim_kind", "packed", 0)')
    anim_hair = _wrangle(sub, "ANIM_HAIR", VEX_ANIM_CHECK, DETAIL, [pick, in_hair])
    # Hair strands come captured from the cache (lock_capture); only the mesh and guide parts are captured
    # here (small, and only when some lock shows them). Then only the deform runs per frame and per edit.
    mesh_guide = _node(sub, "merge", "mesh_guide", [mesh_col, guide_col])
    capture = _node(sub, "pointdeform", "deform_capture", [mesh_guide, in_hair], mode="capture")
    capture.parm("radius").setExpression('ch("../deform_radius")')
    to_deform = _node(sub, "merge", "to_deform", [capture, hair_col])
    deform = _node(sub, "pointdeform", "deform", [to_deform, in_hair, anim_hair], mode="deform")
    deform.parm("radius").setExpression('ch("../deform_radius")')
    # two switches: an hscript if() evaluates both sides, so one expression read ANIM_HAIR (unpacking the
    # anim USD) on every frame even with Shot deform off
    deform_ok = _node(sub, "switch", "deform_ok", [disp_fast, deform])
    deform_ok.parm("input").setExpression('detail("../ANIM_HAIR", "deform_ok", 0)')
    use_deform = _node(sub, "switch", "use_deform", [disp_fast, deform_ok])
    use_deform.parm("input").setExpression('ch("../deform_active")')
    out = _node(sub, "null", "OUT", [use_deform])
    output = _node(sub, "output", "output0", [out])
    output.setDisplayFlag(True)
    output.setRenderFlag(True)
    section("Shot deform")
    _layout_sections(sub, sections)


def _layout_sections(sub, sections) -> None:
    """One column per section, left to right in build order, each in a titled network box: one
    layoutChildren over everything put the loop and the regions in a knot of crossing wires."""
    x = 0.0
    for title, nodes in sections:
        if not nodes:
            continue
        sub.layoutChildren(items=nodes)
        xs = [n.position()[0] for n in nodes]
        ys = [n.position()[1] for n in nodes]
        shift = hou.Vector2(x - min(xs), -max(ys))
        for n in nodes:
            n.move(shift)
        box = sub.createNetworkBox()
        box.setComment(title)
        for n in nodes:
            box.addItem(n)
        box.fitAroundContents()
        x += max(xs) - min(xs) + 5.0


def _parm_templates() -> hou.ParmTemplateGroup:
    ptg = hou.ParmTemplateGroup()
    cb = 'from apps.houdini import grooming_adapter; grooming_adapter.on_button(kwargs["node"], "{}")'
    ptg.append(hou.MenuParmTemplate(
        "display_mode", "Display", menu_items=config.DISPLAY_MODES,
        menu_labels=("Mesh", "Guide", "Hair preview", "Hair full"), default_value=2))
    ptg.append(hou.MenuParmTemplate(
        "play_display", "While playing", menu_items=config.PLAY_DISPLAY,
        menu_labels=("Same as Display", "Guide", "Hair preview"), default_value=2,
        help="Lighter display while the timeline plays (hair full deforms 4 M points, ~1 s a frame on "
             "Helen); back to Display on stop. Never heavier than Display"))
    # what the network draws: Display, or While playing during playback (`playing`, set by the
    # adapter's playbar callback with undo off)
    eff = hou.IntParmTemplate("display_eff", "Display in use", 1, default_expression=(
        'if(ch("playing") && ch("play_display") > 0, min(ch("display_mode"), ch("play_display")), '
        'ch("display_mode"))',), default_expression_language=(hou.scriptLanguage.Hscript,))
    eff.hide(True)
    ptg.append(eff)
    playing = hou.ToggleParmTemplate("playing", "Playing", default_value=False)
    playing.hide(True)
    ptg.append(playing)
    ptg.append(hou.MenuParmTemplate("color_by", "Colour by", menu_items=config.COLOR_BY,
                                    menu_labels=("Lock", "Group"), default_value=0))
    detect = hou.ButtonParmTemplate("detect", "Detect", script_callback=cb.format("detect"),
                                    script_callback_language=hou.scriptLanguage.Python)
    detect.setJoinWithNext(True)
    ptg.append(detect)
    ptg.append(hou.ButtonParmTemplate("split_regions", "Update regions", script_callback=cb.format("split_regions"),
                                      script_callback_language=hou.scriptLanguage.Python))
    pub_v = hou.StringParmTemplate("publish_version", "Publish version", 1,
                                   help="Empty: the scene's _vNNN, or the next free version")
    pub_v.setJoinWithNext(True)
    ptg.append(pub_v)
    ptg.append(hou.ButtonParmTemplate("publish", "Publish", script_callback=cb.format("publish"),
                                      script_callback_language=hou.scriptLanguage.Python))

    adv = hou.FolderParmTemplate("advanced", "Advanced", folder_type=hou.folderType.Collapsible)
    adv.addParmTemplate(hou.FloatParmTemplate("preview_fraction", "Preview fraction", 1,
                                              default_value=(config.PREVIEW_FRACTION,), min=0.0, max=1.0))
    adv.addParmTemplate(hou.IntParmTemplate("preview_max", "Preview max strands", 1,
                                            default_value=(config.PREVIEW_MAX_STRANDS,), min=0, max=100000))
    adv.addParmTemplate(hou.FloatParmTemplate("surface_along_weight", "Surface along weight", 1,
                                              default_value=(3.0,), min=0.1, max=20.0,
                                              help="How much a mesh point's position along the lock counts "
                                                   "against its position across, when a strand looks up the "
                                                   "mesh surface"))
    gone = hou.IntParmTemplate("surface_neighbours", "Surface neighbours (unused)", 1, default_value=(1,))
    gone.hide(True)   # kept so scenes saved before the face lookup load without a warning
    adv.addParmTemplate(gone)
    adv.addParmTemplate(hou.FloatParmTemplate("cross_spread", "Cross-section spread", 1, default_value=(1.0,),
                                              min=0.0, max=1.0,
                                              help="0: a strand's place across the lock follows where its root "
                                                   "fell in the region (bunches in the middle); 1: an even spread"))
    adv.addParmTemplate(hou.FloatParmTemplate("root_pull", "Root pull to mesh", 1, default_value=(0.85,),
                                              min=0.0, max=1.0,
                                              help="0: roots stay where hairgen scattered them over the lock's "
                                                   "region (fans in from a wide region); 1: under the mesh root"))
    adv.addParmTemplate(hou.FloatParmTemplate("strand_segment_cm", "Strand segment (cm)", 1, default_value=(2.0,),
                                              min=0.5, max=10.0,
                                              help="Longest segment of a strand: long locks get more points, "
                                                   "never fewer than 32"))
    adv.addParmTemplate(hou.IntParmTemplate("strand_smooth", "Strand smoothing", 1, default_value=(8,),
                                            min=0, max=30,
                                            help="Blur passes on each strand's offset from its lock's spine, after "
                                                 "a spike filter. 0 keeps the raw surface lookup"))
    adv.addParmTemplate(hou.IntParmTemplate("measure_samples", "Measure samples", 1, default_value=(4000,),
                                            min=0, max=20000,
                                            help="Points spread over each lock's mesh to measure its cross-sections; "
                                                 "low-res meshes otherwise give a few points a band and a wrong width"))
    adv.addParmTemplate(hou.IntParmTemplate("spine_smooth", "Spine smoothing", 1, default_value=(18,),
                                            min=0, max=50,
                                            help="Blur passes along each lock's spine and its width, thickness "
                                                 "and axes. 0 keeps the raw band measure, which zigzags"))
    adv.addParmTemplate(hou.FloatParmTemplate("rest_frame", "Rest frame", 1, default_value=(1.0,),
                                              min=-100.0, max=1000.0,
                                              help="Frame at which the scalp and the rest hair mesh (inputs "
                                                   "1-2) are read; only the animated hair mesh follows time"))
    adv.addParmTemplate(hou.IntParmTemplate("region_subdiv", "Region subdivisions", 1,
                                            default_value=(config.REGION_SUBDIV,), min=0, max=4,
                                            help="Bilinear subdivisions of the scalp before Update regions "
                                                 "(x4 polygons each), so a lock's footprint covers several"))
    adv.addParmTemplate(hou.IntParmTemplate("spine_points", "Spine segments", 1, default_value=(48,),
                                            min=3, max=100, min_is_strict=True))
    adv.addParmTemplate(hou.FloatParmTemplate("root_tolerance", "Root tolerance", 1, default_value=(0.03,),
                                              min=0.0, max=0.3,
                                              help="Share of a piece's distance-to-scalp range taken as its root"))
    adv.addParmTemplate(hou.FloatParmTemplate("round_section", "Round section", 1, default_value=(0.15,),
                                              min=0.0, max=1.0,
                                              help="Below this anisotropy a cross-section keeps the previous "
                                                   "band's axis, so a round lock does not show false twist"))
    adv.addParmTemplate(hou.FloatParmTemplate("root_blend", "Root blend", 1, default_value=(0.05,),
                                              min=0.0, max=1.0))
    adv.addParmTemplate(hou.FloatParmTemplate("unit_cm", "Centimetres per unit", 1, default_value=(100.0,),
                                              min=0.001, max=1000.0))
    adv.addParmTemplate(hou.FloatParmTemplate("strand_width", "Strand width", 1, default_value=(0.0001,),
                                              min=0.0, max=0.01))
    adv.addParmTemplate(hou.FloatParmTemplate("clump_size", "Clump size", 1, default_value=(0.006,),
                                              min=0.0, max=0.1))
    adv.addParmTemplate(hou.FloatParmTemplate("frizz_amp", "Frizz amplitude", 1, default_value=(0.004,),
                                              min=0.0, max=0.05))
    adv.addParmTemplate(hou.FloatParmTemplate("frizz_freq", "Frizz frequency", 1, default_value=(8.0,),
                                              min=0.0, max=50.0))
    adv.addParmTemplate(hou.ToggleParmTemplate(
        "shot_deform", "Shot deform", default_value=False,
        help="Off (the default, and how a scene opens): the hair stays at rest even with an animated hair mesh"
             " wired in, so an edit does not deform 4 M points and the panel's focus and strands work. On: it"
             " follows the animation"))
    wired = hou.IntParmTemplate("anim_wired", "Animated hair mesh wired in", 1, default_expression=(
        'strcmp(opinputpath(".", 2), "") != 0',), default_expression_language=(hou.scriptLanguage.Hscript,))
    wired.hide(True)
    adv.addParmTemplate(wired)
    active = hou.IntParmTemplate("deform_active", "Deform in use", 1, default_expression=(
        'ch("shot_deform") && ch("anim_wired")',), default_expression_language=(hou.scriptLanguage.Hscript,))
    active.hide(True)
    adv.addParmTemplate(active)
    adv.addParmTemplate(hou.FloatParmTemplate("deform_radius", "Deform radius", 1, default_value=(0.02,),
                                              min=0.0, max=1.0))
    ptg.append(adv)

    data = hou.StringParmTemplate(config.DATA_PARM, "Groom data", 1, tags={"editor": "1"})
    data.hide(True)
    ptg.append(data)
    regions = hou.DataParmTemplate("regions", "Regions", 1, data_parm_type=hou.dataParmType.Geometry)
    regions.hide(True)
    ptg.append(regions)
    path = hou.StringParmTemplate("publish_path", "Publish path", 1)
    path.hide(True)
    ptg.append(path)
    # display state the adapter sets with undo off (set_isolate) or while publishing: never a groom edit
    iso = hou.StringParmTemplate("isolate_ids", "Isolated locks", 1)
    iso.hide(True)
    ptg.append(iso)
    drag = hou.StringParmTemplate("preview_ids", "Locks shown light while a slider drags", 1)
    drag.hide(True)
    ptg.append(drag)
    strands = hou.StringParmTemplate("strand_ids", "Locks drawn as strands", 1)
    strands.hide(True)
    ptg.append(strands)
    focus = hou.StringParmTemplate("focus_ids", "Locks in focus (the others see-through)", 1)
    focus.hide(True)
    ptg.append(focus)
    xray = hou.FloatParmTemplate("xray_opacity", "X-ray opacity per strand of locks out of focus", 1,
                                 default_value=(config.GHOST_ALPHA,), min=0.0, max=1.0)
    xray.hide(True)
    ptg.append(xray)
    drag_f = hou.FloatParmTemplate("drag_factor", "Strand fraction of dragged locks", 1, default_value=(1.0,))
    drag_f.hide(True)
    ptg.append(drag_f)
    cook_all = hou.ToggleParmTemplate("cook_all", "Cook every lock", default_value=False)
    cook_all.hide(True)
    ptg.append(cook_all)
    return ptg


ON_LOADED = """from apps.houdini import grooming_adapter
grooming_adapter.on_loaded(kwargs["node"])
"""
ON_CREATED = """from apps.houdini import grooming_adapter
grooming_adapter.install_playbar_callback()
"""


def build(out_path: str = DEFAULT_OUT) -> str:
    out_path = os.path.abspath(out_path).replace("\\", "/")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    backup_dir = os.path.join(os.path.dirname(out_path), "backup")
    had_backups = set(glob.glob(os.path.join(backup_dir, "*")))
    if os.path.exists(out_path):
        hou.hda.uninstallFile(out_path)
        os.remove(out_path)

    geo = hou.node("/obj").createNode("geo", "mono_grooming_build")
    sub = geo.createNode("subnet", "mono_grooming")
    for i, label in enumerate(("Scalp (UV)", "Hair mesh (rest)", "Animated hair mesh")):
        sub.parm(f"label{i + 1}").set(label)
    build_network(sub)
    hda = sub.createDigitalAsset(
        name=config.HDA_TYPE, hda_file_name=out_path, description=config.HDA_LABEL,
        min_num_inputs=2, max_num_inputs=3, version="0.1", ignore_external_references=True,
        change_node_type=True, create_backup=False)
    definition = hda.type().definition()
    definition.setParmTemplateGroup(_parm_templates())
    definition.setIcon("SOP_hairgen")
    definition.setComment("MONO Grooming v0.1, built by tools/fx/grooming/build_hda.py")
    definition.addSection("OnLoaded", ON_LOADED)
    definition.setExtraFileOption("OnLoaded/IsPython", True)
    definition.addSection("OnCreated", ON_CREATED)
    definition.setExtraFileOption("OnCreated/IsPython", True)
    definition.save(out_path, hda, create_backup=False)
    geo.destroy()

    for f in set(glob.glob(os.path.join(backup_dir, "*"))) - had_backups:
        os.remove(f)
    if os.path.isdir(backup_dir) and not os.listdir(backup_dir):
        os.rmdir(backup_dir)
    return out_path


if __name__ == "__main__":
    path = build(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)
    print("built", path)
