"""
Build the MONO Grooming SOP HDA (`mono::grooming::0.1`) from code into `otls/mono_grooming.hdalc`.

    hython tools/fx/grooming/build_hda.py [output.hdalc]

The network follows the fixed processing order of docs/plans/grooming_v0_1.md:

  hair mesh -> pieces -> spine + measure -> lock ids from the JSON -> settings -> frozen regions
  -> For-Each lock_id { region, hairgen, fit to the lock } -> clump -> length, frizz -> display
  -> point deform by input 3 (optional) -> output

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

VEX_GUIDE_ROOT = """// guide root on the scalp
if (vertexprimindex(0, pointvertex(0, @ptnum)) == 0 && nprimitives(1) > 0) {
    int sp; vector suv;
    xyzdist(1, @P, sp, suv);
    @P = primuv(1, "P", sp, suv);
}
"""

VEX_REGION_POINTS = """// provisional point lock_owner (nearest root) for scalps not split yet; the frozen split is per prim
i@lock_owner = -1;
if (npoints(1) == 0) {
    float best = 1e30;
    for (int pr = 0; pr < nprimitives(2); pr++) {
        int id = prim(2, "lock_id", pr);
        if (id < 0 || prim(2, "visible", pr) == 0) continue;
        float d = distance2(@P, point(2, "P", primpoint(2, pr, 0)));
        if (d < best) { best = d; i@lock_owner = id; }
    }
}
"""

VEX_REGION_PRIMS = """// prim lock_owners: the frozen split ("Chia vùng": one frozen point per scalp prim, its centroid,
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
if (total * f > cap && total > 0) f = cap / total;
f@factor = chi("../display_mode") == 2 ? f : 1.0;
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
// (widest band of the first quarter, thickness >= 30 % of the width): locks whose roots converge on a
// small patch (Helen's fringe) still get as many strands as their mesh shows.
float dens = prim(1, "density", 0);
float area = 0;
for (int pr = 0; pr < nprimitives(0); pr++) {
    float a = prim(0, "area_cm2", pr);   // typed: inside an int expression prim() would return int
    int sh = prim(0, "share", pr);
    area += a / max(sh, 1);
}
int sp[] = primpoints(1, 0);
float w = 0, t = 0;
for (int i = 0; i < max(1, len(sp) / 4); i++) {
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

PIECE_GAP = 100.0   # far beyond (along x weight, across) = (3, 1): lookups never reach another piece

VEX_SURFACE_CLOUD = """// the mesh points as a cloud in (along, across) space, for fit_to_lock's lookup; z = the piece x
// PIECE_GAP keeps each lock's points apart, so a lookup needs no per-lock blast (73 ms a lock)
@P = set(f@pu * chf("../surface_along_weight"), f@ps, i@piece * %(gap)s);
""" % {"gap": PIECE_GAP}

VEX_FIT = """// place the strand on the lock's own mesh surface (not on a flat ellipse: wide caps like Helen's
// hair_base are curved), from its root on the scalp. (s, t) = where its root sits in the lock's
// region; the mesh offset at (u, s) comes from the surface cloud (input 3), then the lock's settings
// (width_mult, thick_mult, twist_add through the spine's axes) apply; t adds a little volume.
int pr = pointprims(0, @ptnum)[0];
int nv = primvertexcount(0, pr);
int iv = vertexprimindex(0, pointvertex(0, @ptnum));
float u = nv > 1 ? float(iv) / (nv - 1) : 0.0;
vector root = point(0, "P", primpoint(0, pr, 0));
vector rc = detail(2, "rc"), ra = detail(2, "ra"), rb = detail(2, "rb");
float s = clamp(dot(root - rc, ra) / max(detail(2, "rea"), 1e-6), -1, 1);
float t = clamp(dot(root - rc, rb) / max(detail(2, "reb"), 1e-6), -1, 1);
int p0 = primpoint(1, 0, 0);
vector a0 = point(1, "lock_axis", p0), m0 = point(1, "lock_minor", p0);
if (dot(ra, a0) < 0) s = -s;
if (dot(rb, m0) < 0) t = -t;
float wm = prim(1, "width_mult", 0), tm = prim(1, "thick_mult", 0);
if (wm <= 0) wm = 1;
if (tm <= 0) tm = 1;
float aw = chf("../surface_along_weight");
float pz = prim(1, "piece", 0) * %(gap)s;
float cm = 1.0 / max(chf("../unit_cm"), 1e-6);

vector place(float uu; float ss; float tt; float aw; float pz; float wm; float tm; float cm) {
    vector uv = set(uu, 0, 0);
    vector c = primuv(1, "P", 0, uv);
    vector a = normalize(primuv(1, "lock_axis", 0, uv));
    vector m = normalize(primuv(1, "lock_minor", 0, uv));
    float w = primuv(1, "lock_width", 0, uv), th = primuv(1, "lock_thick", 0, uv);
    float vol = min(min(th, 0.15 * w), cm);           // volume around the surface, at most 1 cm
    vector q = set(uu * aw, ss, pz);
    int near[] = pcfind(3, "P", q, 0.25, chi("../surface_neighbours"));
    if (len(near) == 0) near = pcfind(3, "P", q, %(gap)s * 0.5, 1);
    if (len(near) == 0)                                 // no mesh points for this piece: the ellipse
        return c + a * (ss * 0.5 * w) + m * (tt * 0.5 * th);
    float wsum = 0, ds = 0, dt = 0;
    foreach (int n; near) {
        float k = 1.0 / max(distance(point(3, "P", n), q), 1e-4);
        ds += k * point(3, "ds", n);
        dt += k * point(3, "dt", n);
        wsum += k;
    }
    ds /= wsum; dt /= wsum;
    return c + a * (ds * wm) + m * (dt * tm + tt * 0.5 * vol);
}

vector shaped = place(u, s, t, aw, pz, wm, tm, cm);
vector c0 = place(0.0, s, t, aw, pz, wm, tm, cm);
@P = shaped + (root - c0) * (1 - smooth(0, max(chf("../root_blend"), 1e-4), u));
""" % {"gap": PIECE_GAP}

VEX_STRAND_TAGS = """// lock attributes on every strand
i@lock_id = prim(1, "lock_id", 0);
s@name = prim(1, "name", 0);
s@group = prim(1, "group", 0);
i@clumpid = i@lock_id;
f@tightness = prim(1, "clump", 0);
f@length_mult = prim(1, "length_mult", 0);
f@frizz = prim(1, "frizz", 0);
i@visible = prim(1, "visible", 0);
v@lock_cd = prim(1, "lock_cd", 0);
v@group_cd = prim(1, "group_cd", 0);
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

VEX_HAIR_OUT = """// contract attributes on the strands
i@clump_id = i@clumpid;
"""

VEX_COLOR_POINTS = """// display colour by lock or by group
int pr = pointprims(0, @ptnum)[0];
vector c = chi("../color_by") == 0 ? prim(0, "lock_cd", pr) : prim(0, "group_cd", pr);
v@Cd = c;
"""

VEX_MESH_COLOR = """// mesh display: lock of the piece from the spines, hidden locks removed
int k = point(0, "piece", primpoint(0, @primnum, 0));
int sp = findattribval(1, "prim", "piece", k);
if (sp >= 0 && prim(1, "visible", sp) == 0) { removeprim(0, @primnum, 1); return; }
i@lock_id = sp >= 0 ? prim(1, "lock_id", sp) : -1;
vector c = {0.25, 0.25, 0.25};
if (sp >= 0) c = chi("../color_by") == 0 ? prim(1, "lock_cd", sp) : prim(1, "group_cd", sp);
v@Cd = c;
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
    build = _wrangle(sub, "spine_build", VEX_SPINE_BUILD, DETAIL, [attrs, dist])
    resample = _node(sub, "resample", "spine_resample", [build], dolength=0, dosegs=1,
                     docurveuattr=1, dotangentattr=1)
    resample.parm("segs").setExpression('ch("../spine_points")')
    raw = _node(sub, "null", "SPINES_RAW", [resample])
    # the hair mesh as a lookup cloud: strands follow its real surface, curved caps included
    sparams = _wrangle(sub, "surface_params", VEX_SURFACE_PARAMS, POINT, [pieces, raw])
    scloud = _wrangle(sub, "surface_cloud", VEX_SURFACE_CLOUD, POINT, [sparams])
    surface = _node(sub, "null", "SURFACE_CLOUD", [scloud])
    section("Pieces, root ends, spines")

    # ---- lock ids, names, groups and resolved settings from the JSON ----
    assign = _node(sub, "python", "assign_locks", [raw])
    assign.parm("python").set("from apps.houdini import grooming_adapter\n"
                              "grooming_adapter.cook_assign(hou.pwd())\n")
    spines_locks = _node(sub, "null", "SPINES_LOCKS", [assign])
    settings = _wrangle(sub, "apply_settings", VEX_APPLY_SETTINGS, POINT, [spines_locks])
    spines = _node(sub, "null", "SPINES", [settings])
    # hidden locks (the panel's eye) still grow hair and are published: visibility is display only
    guides_cut = _node(sub, "blast", "guides_keep", [spines], group="@lock_id<0", grouptype=4)
    guides = _wrangle(sub, "guide_roots", VEX_GUIDE_ROOT, POINT, [guides_cut, in_scalp])
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

    # ---- hairgen per lock ----
    begin = _node(sub, "block_begin", "foreach_begin", [guides], method=1, blockpath="../foreach_end")
    scalp_in = _node(sub, "block_begin", "foreach_scalp", [regions], method=3, blockpath="../foreach_end")
    cut = _wrangle(sub, "region_cut", VEX_REGION_CUT, PRIM, [scalp_in, begin])
    frame = _wrangle(sub, "region_frame", VEX_REGION_FRAME, DETAIL, [cut, begin])
    rdens = _wrangle(sub, "region_density", VEX_REGION_DENSITY, POINT, [frame])
    # hairgen scatters the roots and grows straight unguided strands; fit_to_lock gives them the
    # lock's shape (the spine as a hairgen guide would need skinprim/skinuv on the region).
    hairgen = _node(sub, "hairgen::2.0", "hairgen", [rdens], useguides=0, growunguided=1,
                    useinitdirattrib=0, unguidedlength=0.01)
    hairgen.parm("unguidedsegments").setExpression('ch("../spine_points")')
    hairgen.parm("densityoverride").set(1)  # skin attribute "density" (strands/cm2) x the parm
    hairgen.parm("density").setExpression(
        'pow(ch("../unit_cm"), 2) * detail("../PREVIEW", "factor", 0)')
    hairgen.parm("scatterseed").setExpression('prim("../foreach_begin", 0, "lock_id", 0)')
    hairgen.parm("thickness").setExpression('ch("../strand_width")')
    fit = _wrangle(sub, "fit_to_lock", VEX_FIT, POINT, [hairgen, begin, frame, surface])
    tags = _wrangle(sub, "strand_tags", VEX_STRAND_TAGS, PRIM, [fit, begin])
    nothing = _node(sub, "add", "no_strands")
    has_region = _node(sub, "switch", "has_region", [nothing, tags])
    has_region.parm("input").setExpression('if(nprims("../region_cut") > 0, 1, 0)')
    end = _node(sub, "block_end", "foreach_end", [has_region], itermethod=1, method=1, useattrib=1,
                attrib="lock_id", blockpath="../foreach_begin", templatepath="../foreach_begin")
    end.parm("class").set(0)
    section("Hair per lock (for each lock_id)")

    # ---- clump, length, frizz ----
    clump_skin = _wrangle(sub, "clump_skin", "v@rest = @P;  // hairclump wants a rest skin\n", POINT,
                          [in_scalp])
    # hairgen's skinprim / skinprimuv index the per-lock region cut inside the loop, not this skin:
    # looked up again on the clump skin from each strand's root (hairclump needs them valid).
    skinref = _node(sub, "guideskinattriblookup", "strands_skinref", [end, clump_skin])
    clump = _node(sub, "hairclump::2.0", "clump", [skinref, clump_skin])
    clump.parm("clumpsize").setExpression('ch("../clump_size")')
    clump.parm("tightness").set(1.0)  # x the strand's `tightness` = the lock's clump setting
    clump.parm("tightnessoverride").set("curveattrib")
    clump.parm("tightnesscurveattrib").set("tightness")
    lf = _wrangle(sub, "length_frizz", VEX_LENGTH_FRIZZ, PRIM, [clump])
    hair_out = _wrangle(sub, "hair_attribs", VEX_HAIR_OUT, PRIM, [lf])
    hair = _node(sub, "null", "HAIR", [hair_out])
    section("Clump, length, frizz")

    # ---- publish: the full hair, without display-only attributes ----
    # skinprim / skinprimuv refer to the per-lock region inside the loop, not the scalp: dropped
    pub_clean = _node(sub, "attribdelete", "publish_clean", [hair], primdel="lock_cd group_cd tightness "
                      "length_mult frizz clumpid skinprim skinprimuv path visible",
                      ptdel="Cd tightness skinprim skinprimuv")
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
    mesh_col = _wrangle(sub, "mesh_color", VEX_MESH_COLOR, PRIM, [pieces, spines])
    guides_vis = _node(sub, "blast", "guides_visible", [guides_cut], group="@visible==0", grouptype=4)
    hair_vis = _node(sub, "blast", "hair_visible", [hair], group="@visible==0", grouptype=4)
    guide_col = _wrangle(sub, "guide_color", VEX_COLOR_POINTS, POINT, [guides_vis])
    hair_col = _wrangle(sub, "hair_color", VEX_COLOR_POINTS, POINT, [hair_vis])
    disp = _node(sub, "switch", "display", [mesh_col, guide_col, hair_col])
    disp.parm("input").setExpression('min(ch("../display_mode"), 2)')
    deform = _node(sub, "pointdeform", "deform", [disp, in_hair, in_anim])
    deform.parm("radius").setExpression('ch("../deform_radius")')
    use_deform = _node(sub, "switch", "use_deform", [disp, deform])
    use_deform.parm("input").setExpression('if(strcmp(opinputpath("..", 2), "") == 0, 0, 1)')
    out = _node(sub, "null", "OUT", [use_deform])
    output = _node(sub, "output", "output0", [out])
    output.setDisplayFlag(True)
    output.setRenderFlag(True)
    section("Display and shot deform")
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
    ptg.append(hou.MenuParmTemplate("color_by", "Colour by", menu_items=config.COLOR_BY,
                                    menu_labels=("Lock", "Group"), default_value=0))
    detect = hou.ButtonParmTemplate("detect", "Detect", script_callback=cb.format("detect"),
                                    script_callback_language=hou.scriptLanguage.Python)
    detect.setJoinWithNext(True)
    ptg.append(detect)
    ptg.append(hou.ButtonParmTemplate("split_regions", "Chia vùng", script_callback=cb.format("split_regions"),
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
    adv.addParmTemplate(hou.IntParmTemplate("surface_neighbours", "Surface neighbours", 1, default_value=(1,),
                                            min=1, max=12,
                                            help="Mesh points averaged per strand point. 1 keeps strands on the "
                                                 "surface of curved caps; more smooths flat ribbons"))
    adv.addParmTemplate(hou.FloatParmTemplate("rest_frame", "Rest frame", 1, default_value=(1.0,),
                                              min=-100.0, max=1000.0,
                                              help="Frame at which the scalp and the rest hair mesh (inputs "
                                                   "1-2) are read; only the animated hair mesh follows time"))
    adv.addParmTemplate(hou.IntParmTemplate("region_subdiv", "Region subdivisions", 1,
                                            default_value=(config.REGION_SUBDIV,), min=0, max=4,
                                            help="Bilinear subdivisions of the scalp before Chia vùng "
                                                 "(x4 polygons each), so a lock's footprint covers several"))
    adv.addParmTemplate(hou.IntParmTemplate("spine_points", "Spine segments", 1, default_value=(24,),
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
    return ptg


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
