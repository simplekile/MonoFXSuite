"""MONO Grooming hair check, the look: shaded viewport shots of the whole groom and of the worst locks.
Houdini GUI startup script (needs a display), puts the window on the SECONDARY monitor, never saves,
quits at the end. Settings come from env vars, because houdini.exe passes no arguments to a script:

    set QC_SUITE=<suite>  QC_HIP=<scene>  QC_OUT=<out dir>  [QC_REPORT=<qc_report.json>]  [QC_REF=<groom.usd>]
    houdini.exe -foreground qc_capture.py

The hair is shaded like XGen's preview, not coloured by lock (VEX_XGEN): thin strands, Kajiya-Kay
highlights for each view's camera, darker roots, per-strand value variation, no shadows. Strands that
leave the lock, zigzag or cross catch the highlight differently from their neighbours, so they stand out.

Shots (PNG in QC_OUT): front, back, left, right, top, three-quarter, crown close-up; for the 4 worst
locks of QC_REPORT (or QC_LOCKS=name,name) a close-up alone with the lock's mesh as a wire template
(`lock_<name>_a/b`); with QC_REF the same 7 views of the reference
(`ref_*`). A log in QC_OUT/capture_log.txt.

Shot mode (QC_FRAMES=0,60,120): the animated hair mesh stays wired, Shot deform is turned on, and for
each frame and view (QC_VIEWS, default threequarter) `shot_<view>_f<frame>` (ours deformed) and
`shot_mesh_<view>_f<frame>` (the animated hair mesh, same camera); nothing else is shot.

Shot close-up of a lock (QC_FRAMES and QC_LOCKS=name,name): for each lock, frame and view, that lock ALONE of
output 1 (blasted by lock_id, deformed),
`shot_lock_<name>_<view>_f<frame>`, and its animated mesh piece shaded alone with the same camera, `shot_lock_mesh_<name>_<view>_f<frame>`. The
camera frames the animated piece's box grown by QC_LOCK_MARGIN_CM (default 3 cm) on every side, grown again only
if the hair leaves it, then framed shrunk to QC_LOCK_ZOOM (0.55) about its centre, so scenes with the same lock unedited, moved 2 cm and moved 5 cm get the same camera at each
frame (the log says when the hair left the box). The two pictures overlay pixel for pixel (one picture over the
other shows hair against piece); the piece drawn in the same picture does not show: it lies under its hair, and
Alpha is drawn only inside packed geometry, a template's wire vanished on the white background. A drawn lock (no mesh) is framed on its own hair, margin the same.
The whole-groom shot pictures are skipped then.

v0.2b: the mesh shown beside a lock (mesh_*, compare, the close-ups' template) is the node's MESH_CARRIED (an edited
lock's piece on its edited spine); compare adds the modelled piece as a column for an edited lock, and frames a drawn
lock on its hair alone (it has no mesh). The `lock_<name>` close-ups show output 1's lock alone (blasted by lock_id):
output 1 ignores the eye that solo() set, so they used to show the whole groom.
"""

import json
import os
import sys
import traceback

SUITE = os.environ["QC_SUITE"]
HIP = os.environ["QC_HIP"]
OUT = os.environ["QC_OUT"]
REPORT = os.environ.get("QC_REPORT")
REF = os.environ.get("QC_REF")
# QC_COMPARE=hair_bang_01,hair_bang_02 or group:hair_bang or all: one image per lock, its mesh, our hair
# and the reference's strands of that lock side by side (front and side rows); whole-groom shots skipped
COMPARE = os.environ.get("QC_COMPARE", "")
FRAMES = [int(f) for f in os.environ.get("QC_FRAMES", "").split(",") if f.strip()]
SHOT_LOCKS = [n for n in os.environ.get("QC_LOCKS", "").split(",") if n] if FRAMES else []
LOCK_MARGIN_CM = float(os.environ.get("QC_LOCK_MARGIN_CM", "3"))
LOCK_ZOOM = float(os.environ.get("QC_LOCK_ZOOM", "0.55"))   # camera distance after framing, shot close-ups
os.makedirs(OUT, exist_ok=True)
_log = open(os.path.join(OUT, "capture_log.txt"), "w", encoding="utf-8")


def log(*a):
    _log.write(" ".join(str(x) for x in a) + "\n")
    _log.flush()


for m in [k for k in list(sys.modules) if k in ("tools", "apps") or k.startswith(("tools.", "apps."))]:
    del sys.modules[m]
sys.path.insert(0, SUITE)

import hou  # noqa: E402
from PySide6 import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance()
SECOND = next((s for s in app.screens() if s is not app.primaryScreen()), None)
S = {}
HAIR_COLOR = (0.16, 0.10, 0.06)
VIEWS = {  # name: (rx, ry) camera rotation in degrees; "crown" frames the top of the head only
    "front": (0, 0), "back": (0, 180), "left": (0, -90), "right": (0, 90), "top": (-80, 0),
    "threequarter": (-15, 40), "crown": (-35, 20),
}
_only = [v for v in os.environ.get("QC_VIEWS", "").split(",") if v in VIEWS]
if _only:                                    # QC_VIEWS=front,crown: just these
    VIEWS = {k: VIEWS[k] for k in _only}
elif FRAMES:                                 # shot mode: one view a frame unless asked
    VIEWS = {"threequarter": VIEWS["threequarter"]}


def viewer():
    return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)


def grab(name):
    """The viewport, rendered by a flipbook (never a screen grab: a grab takes whatever window covers the
    screen, and once saved a video the user had open instead of the hair)."""
    sv = viewer()
    st = sv.flipbookSettings().stash()
    f = int(hou.frame())
    st.frameRange((f, f))
    st.output(os.path.join(OUT, f"{name}.$F4.png").replace("\\", "/"))
    st.outputToMPlay(False)
    st.useResolution(True)
    st.resolution((1600, 1200))
    sv.flipbook(sv.curViewport(), st)
    out = os.path.join(OUT, f"{name}.{f:04d}.png")
    final = os.path.join(OUT, name + ".png")
    if os.path.isfile(out):
        os.replace(out, final)


# XGen-style preview, computed per point for the current camera (the viewport shows it unlit): Kajiya-Kay
# hair lighting from a light above and beside the camera, a primary highlight and a tinted secondary
# one, darker roots, a little value variation per strand. A strand that leaves its lock or runs the wrong
# way catches the highlight differently from its neighbours, so it shows; nothing sits in a black shadow.
VEX_XGEN = r"""
int pr = pointprims(0, @ptnum)[0];
int pts[] = primpoints(0, pr);
int n = len(pts), i = vertexprimindex(0, pointvertex(0, @ptnum));
vector a = point(0, "P", pts[max(i - 1, 0)]), b = point(0, "P", pts[min(i + 1, n - 1)]);
vector T = normalize(b - a);
vector eye = chv("eye"), up = chv("up"), side = chv("side");
vector V = normalize(eye - @P);
vector L = normalize(V + up * 0.6 + side * 0.5);
float tl = dot(T, L);
float diff = sqrt(max(1 - tl * tl, 0));
vector H = normalize(L + V);
float th = dot(T, H);
float spec = pow(sqrt(max(1 - th * th, 0)), 90);
float th2 = dot(T, normalize(H + up * 0.25));                 // secondary lobe, shifted toward the root
float spec2 = pow(sqrt(max(1 - th2 * th2, 0)), 30);
float u = n > 1 ? float(i) / (n - 1) : 0;
float jit = fit01(rand(pr * 7.31), 0.75, 1.2);
vector base = chv("base") * jit * fit01(smooth(0, 0.35, u), 0.45, 1.0);
v@Cd = base * (0.18 + 0.82 * diff) + spec * 0.55 * {1, 0.97, 0.92} + spec2 * 0.35 * chv("base") * 2.2;
"""


# The hair mesh, lit the same way (diffuse + a soft highlight) so its shape compares with the hair.
VEX_MESH = r"""
vector V = normalize(chv("eye") - @P);
vector L = normalize(V + chv("up") * 0.6 + chv("side") * 0.5);
vector N = normalize(@N);
if (dot(N, V) < 0) N = -N;
float diff = max(dot(N, L), 0);
float spec = pow(max(dot(N, normalize(L + V)), 0), 40);
v@Cd = chv("base") * (0.25 + 0.75 * diff) + spec * 0.3;
"""


def look_mesh(geo, src, name):
    nrm = geo.createNode("normal", f"qc_{name}_n")
    nrm.setInput(0, src)
    nrm.parm("type").set(0)                 # point normals
    look = geo.createNode("attribwrangle", f"qc_{name}_shade")
    look.setInput(0, nrm)
    look.parm("class").set(2)
    look.parm("snippet").set(VEX_MESH)
    ptg = look.parmTemplateGroup()
    for nm, val in (("eye", (0, 0, 5)), ("up", (0, 1, 0)), ("side", (1, 0, 0)), ("base", (0.5, 0.33, 0.22))):
        ptg.append(hou.FloatParmTemplate(nm, nm, 3, default_value=val))
    look.setParmTemplateGroup(ptg)
    S.setdefault("looks", []).append(look)
    return look


def look_network(geo, src, name):
    """src -> drop the display colour -> XGen-style colour for the current camera; returns the last node."""
    clean = geo.createNode("attribdelete", f"qc_{name}_nocd")
    clean.setInput(0, src)
    clean.parm("ptdel").set("Cd")
    clean.parm("primdel").set("Cd")
    look = geo.createNode("attribwrangle", f"qc_{name}_xgen")
    look.setInput(0, clean)
    look.parm("class").set(2)
    look.parm("snippet").set(VEX_XGEN)
    ptg = look.parmTemplateGroup()
    for nm, val in (("eye", (0, 0, 5)), ("up", (0, 1, 0)), ("side", (1, 0, 0)), ("base", HAIR_COLOR)):
        ptg.append(hou.FloatParmTemplate(nm, nm, 3, default_value=val))
    look.setParmTemplateGroup(ptg)
    S.setdefault("looks", []).append(look)
    return look


def aim_looks():
    """The current viewport camera into every look's eye/up/side, then cook them."""
    m = viewer().curViewport().viewTransform()
    eye = m.extractTranslates()
    rot = m.extractRotationMatrix3()
    up = hou.Vector3(0, 1, 0) * rot
    side = hou.Vector3(1, 0, 0) * rot
    for lk in S.get("looks", []):
        lk.parmTuple("eye").set(eye)
        lk.parmTuple("up").set(up)
        lk.parmTuple("side").set(side)


def set_view(view, bbox, zoom=1.0):
    """`zoom` < 1 frames the box shrunk to that share about its centre (frameBoundingBox leaves a wide border: a
    24 cm box filled a fifth of the picture). Moving the camera by its translation emptied the picture."""
    vp = viewer().curViewport()
    vp.changeType(hou.geometryViewportType.Perspective)
    rx, ry = VIEWS.get(view, (-15, 40))
    cam = vp.defaultCamera()
    cam.setRotation(hou.hmath.buildRotate(rx, ry, 0).extractRotationMatrix3())
    if zoom != 1.0:
        c, h = bbox.center(), bbox.sizevec() * (0.5 * zoom)
        bbox = hou.BoundingBox(c[0] - h[0], c[1] - h[1], c[2] - h[2], c[0] + h[0], c[1] + h[1], c[2] + h[2])
    vp.frameBoundingBox(bbox)
    aim_looks()


def solo(names):
    ga, node = S["ga"], S["node"]
    data = ga.read_data(node)
    for lk in data.locks:
        lk.visible = (names is None) or lk.name in names
    ga.write_data(node, data, "qc solo")


# A reference strand belongs to the lock whose mesh is nearest to most of 5 points along it (the
# reference has no lock ids).
VEX_REF_PIECE = r"""
int pts[] = primpoints(0, @primnum);
int n = len(pts);
int votes[];
for (int k = 0; k < 5; k++) {
    int hp; vector uv;
    xyzdist(1, point(0, "P", pts[int(rint((n - 1) * k / 4.0))]), hp, uv);
    int pc = point(1, "piece", primpoint(1, hp, 0));
    if (pc >= len(votes)) resize(votes, pc + 1);
    votes[pc]++;
}
int best = -1, most = 0;
for (int i = 0; i < len(votes); i++) if (votes[i] > most) { most = votes[i]; best = i; }
i@qc_piece = best;
"""

STEPS = []


def s_open():
    mw = hou.qt.mainWindow()
    if SECOND is not None:
        mw.setGeometry(SECOND.availableGeometry())
    hou.hda.installFile(SUITE + "/otls/mono_grooming.hdalc")
    hou.hipFile.load(HIP, suppress_save_prompt=True, ignore_load_warnings=True)
    hou.hda.installFile(SUITE + "/otls/mono_grooming.hdalc", force_use_assets=True)  # not another checkout's
    from apps.houdini import grooming_adapter as ga
    S["ga"], S["node"] = ga, ga.find_nodes()[0]
    node = S["node"]
    geo = node.parent()
    if FRAMES and len(node.inputs()) > 2 and node.inputs()[2] is not None:
        ga.set_shot_deform(node, True)     # OnLoaded opened it at rest; the shot is the target
        S["anim_mesh"] = look_mesh(geo, node.inputs()[2], "anim_mesh")
        if SHOT_LOCKS:
            # one lock's animated mesh piece: the node's unpacked animated hair mesh (ANIM_HAIR, the rest mesh's
            # points) with the rest pieces' `piece` on the same point numbers
            am = geo.createNode("object_merge", "qc_anim_hair")
            am.parm("objpath1").set(node.path() + "/ANIM_HAIR")
            rp = geo.createNode("object_merge", "qc_rest_pieces")
            rp.parm("objpath1").set(node.path() + "/pieces")
            ap = geo.createNode("attribwrangle", "qc_anim_piece")
            ap.setInput(0, am)
            ap.setInput(1, rp)
            ap.parm("class").set(2)
            ap.parm("snippet").set('i@piece = point(1, "piece", @ptnum);')
            one = geo.createNode("blast", "qc_anim_one")
            one.setInput(0, ap)
            one.parm("grouptype").set(3)
            one.parm("group").set("@piece!=-1")
            S["anim_one_blast"], S["anim_one"] = one, look_mesh(geo, one, "anim_one")
    else:
        node.setInput(2, None)             # rest pose: the hair mesh is the target
    ga.set_display(node, "hair", "lock")
    # the strands themselves (output 1 "Groom", GROOM; HAIR on a node built before it), not the display:
    # it packs each lock with its colour inside, which the look's attribdelete / wrangle never reach
    hair = geo.createNode("object_merge", "qc_ours_hair")
    hair.parm("objpath1").set(node.path() + ("/GROOM" if node.node("GROOM") is not None else "/HAIR"))
    S["ours"] = look_network(geo, hair, "ours")
    if REF:
        imp = geo.createNode("usdimport", "qc_ref_usd")
        imp.parm("filepath1").set(REF)
        for k, v in (("input_unpack", 1), ("unpack_geomtype", 1)):
            if imp.parm(k):
                imp.parm(k).set(v)
        S["ref"] = look_network(geo, imp, "ref")
        S["ref_raw"] = imp
    modelled = geo.createNode("object_merge", "qc_pieces_modelled")      # the hair mesh as modelled
    modelled.parm("objpath1").set(node.path() + "/pieces")
    # v0.2b: an edited lock's mesh is its piece carried onto the edited spine (MESH_CARRIED; the mesh itself when
    # nothing is edited)
    pieces = geo.createNode("object_merge", "qc_pieces")
    pieces.parm("objpath1").set(node.path() + ("/MESH_CARRIED" if node.node("MESH_CARRIED") is not None else "/pieces"))
    tpl = geo.createNode("blast", "qc_lock_mesh")       # the solo lock's own mesh, as a wire template
    tpl.setInput(0, pieces)
    tpl.parm("grouptype").set(3)                         # points
    tpl.parm("group").set("@piece!=-1")
    S["tpl"] = tpl
    S["mesh"] = look_mesh(geo, pieces, "mesh")
    lock_ours = geo.createNode("blast", "qc_lock_ours")    # one lock of output 1 (the eye does not reach it)
    lock_ours.setInput(0, S["ours"])
    lock_ours.parm("grouptype").set(4)
    lock_ours.parm("group").set("@lock_id!=-1")
    S["lock_ours"] = lock_ours
    if COMPARE:
        one_mesh = geo.createNode("blast", "qc_cmp_mesh")      # one lock's mesh
        one_mesh.setInput(0, pieces)
        one_mesh.parm("grouptype").set(3)
        one_mesh.parm("group").set("@piece!=-1")
        S["cmp_mesh_blast"], S["cmp_mesh"] = one_mesh, look_mesh(geo, one_mesh, "cmp_mesh")
        one_ours = geo.createNode("blast", "qc_cmp_ours")     # one lock of the finished hair: no recook
        one_ours.setInput(0, S["ours"])
        one_ours.parm("grouptype").set(4)
        one_ours.parm("group").set("@lock_id!=-1")
        S["cmp_ours_blast"] = S["cmp_ours"] = one_ours
        one_mod = geo.createNode("blast", "qc_cmp_modelled")    # an edited lock's piece as modelled
        one_mod.setInput(0, modelled)
        one_mod.parm("grouptype").set(3)
        one_mod.parm("group").set("@piece!=-1")
        S["cmp_mod_blast"], S["cmp_mod"] = one_mod, look_mesh(geo, one_mod, "cmp_mod")
        if REF:
            own = geo.createNode("attribwrangle", "qc_ref_piece")  # each reference strand -> a lock
            own.setInput(0, S["ref_raw"])
            own.setInput(1, modelled)     # the approved groom was made on the modelled mesh
            own.parm("class").set(1)
            own.parm("snippet").set(VEX_REF_PIECE)
            one_ref = geo.createNode("blast", "qc_cmp_ref")
            one_ref.setInput(0, own)
            one_ref.parm("grouptype").set(4)
            one_ref.parm("group").set("@qc_piece!=-1")
            S["cmp_ref_blast"], S["cmp_ref"] = one_ref, look_network(geo, one_ref, "cmp_ref")
    S["piece_of"] = {p.attribValue("name"): int(p.attribValue("piece"))
                     for p in node.node("SPINES").geometry().prims()}
    S["lock_of"] = {p.attribValue("name"): int(p.attribValue("lock_id"))
                    for p in node.node("SPINES").geometry().prims()}
    sg = node.node("SPINES").geometry()
    S["edited"] = {p.attribValue("name") for p in sg.prims()
                   if sg.findPrimAttrib("edited") is not None and p.attribValue("edited")}
    S["drawn"] = {p.attribValue("name") for p in sg.prims()
                  if sg.findPrimAttrib("drawn") is not None and p.attribValue("drawn")}
    S["unit_cm"] = float(node.evalParm("unit_cm")) if node.parm("unit_cm") else 100.0
    S["ours"].setDisplayFlag(True)
    S["ours"].cook(force=True)
    scalp = geo.node("OUT_SCALP")
    S["bbox_all"] = S["ours"].geometry().boundingBox()
    if scalp is not None:
        b = scalp.geometry().boundingBox()
        c, s = b.center(), b.sizevec()
        S["bbox_crown"] = hou.BoundingBox(c[0] - s[0] * 0.8, c[1] - s[1] * 0.1, c[2] - s[2] * 0.8,
                                          c[0] + s[0] * 0.8, c[1] + s[1] * 0.9, c[2] + s[2] * 0.8)
    else:
        S["bbox_crown"] = S["bbox_all"]
    pane = viewer()
    pane.pane().setIsMaximized(True)
    pane.setPwd(geo)
    st = pane.curViewport().settings()
    st.setLighting(hou.viewportLighting.Off)   # the colour is the shading (VEX_XGEN): shown as is
    try:
        st.showsBadges(False)
    except Exception:  # noqa: BLE001
        pass
    hou.setFrame(1)
    log("open", node.path(), "prims", len(S["ours"].geometry().prims()))


STEPS.append(s_open)


def add_views(prefix, which):
    for view in VIEWS:
        def _prep(view=view, which=which):
            S[which].setDisplayFlag(True)
            S[which].cook(force=False)
            set_view(view, S["bbox_crown"] if view == "crown" else S["bbox_all"])

        def _shot(view=view, prefix=prefix):
            grab(f"{prefix}{view}")

        STEPS.extend([_prep, _shot])


def add_shot_frames():
    for f in FRAMES:
        for view in VIEWS:
            def _prep(f=f, view=view):
                hou.setFrame(f)
                S["ours"].setDisplayFlag(True)
                S["ours"].cook(force=False)
                set_view(view, S["ours"].geometry().boundingBox())

            def _shot(f=f, view=view):
                grab(f"shot_{view}_f{f:04d}")

            def _mesh(f=f):
                if "anim_mesh" in S:
                    S["anim_mesh"].setDisplayFlag(True)
                    aim_looks()
                    S["anim_mesh"].cook(force=True)

            def _mshot(f=f, view=view):
                if "anim_mesh" in S:
                    grab(f"shot_mesh_{view}_f{f:04d}")

            STEPS.extend([_prep, _shot, _mesh, _mshot])


def grown(box, cm):
    """A box grown by `cm` on every side (scene units from the node's unit_cm)."""
    e = cm / S.get("unit_cm", 100.0)
    lo, hi = box.minvec(), box.maxvec()
    return hou.BoundingBox(lo[0] - e, lo[1] - e, lo[2] - e, hi[0] + e, hi[1] + e, hi[2] + e)


def add_shot_locks():
    """One lock alone at each frame: its deformed hair (output 1 blasted by lock_id) with its animated piece as a
    wire template, then the piece shaded alone, the same camera for both (and for the same lock in another scene)."""
    for name in SHOT_LOCKS:
        for f in FRAMES:
            for view in VIEWS:
                def _prep(name=name, f=f, view=view):
                    hou.setFrame(f)
                    S["lock_ours"].parm("group").set(f"@lock_id!={S['lock_of'][name]}")
                    S["lock_ours"].setDisplayFlag(True)
                    S["lock_ours"].cook(force=True)
                    hb = S["lock_ours"].geometry().boundingBox()
                    box = None
                    if "anim_one" in S and name not in S["drawn"]:
                        S["anim_one_blast"].parm("group").set(f"@piece!={S['piece_of'].get(name, -1)}")
                        S["anim_one"].cook(force=True)
                        if S["anim_one"].geometry().points():
                            box = grown(S["anim_one"].geometry().boundingBox(), LOCK_MARGIN_CM)
                            if S["lock_ours"].geometry().points() and not (
                                    box.contains(hb.minvec()) and box.contains(hb.maxvec())):
                                log("hair leaves the framing box", name, f)
                                box.enlargeToContain(hb)
                    if box is None:
                        box = grown(hb, LOCK_MARGIN_CM)
                    S["shot_box"] = box
                    S["lock_ours"].setDisplayFlag(True)
                    set_view(view, box, LOCK_ZOOM)
                    log("lock", name, "frame", f, "strands", len(S["lock_ours"].geometry().prims()))

                def _shot(name=name, f=f, view=view):
                    grab(f"shot_lock_{name}_{view}_f{f:04d}")

                def _mesh(name=name, view=view):
                    if "anim_one" in S and name not in S["drawn"]:
                        S["anim_one"].setDisplayFlag(True)
                        set_view(view, S["shot_box"], LOCK_ZOOM)
                        S["anim_one"].cook(force=True)

                def _mshot(name=name, f=f, view=view):
                    if "anim_one" in S and name not in S["drawn"]:
                        grab(f"shot_lock_mesh_{name}_{view}_f{f:04d}")

                STEPS.extend([_prep, _shot, _mesh, _mshot])


if FRAMES and SHOT_LOCKS:
    STEPS.append(lambda: add_shot_locks_now())
elif FRAMES:
    add_shot_frames()
elif not COMPARE:
    add_views("", "ours")
    add_views("mesh_", "mesh")
    if REF:
        add_views("ref_", "ref")


def compare_names():
    names = sorted(S["piece_of"])
    if COMPARE == "all":
        return names
    if COMPARE.startswith("group:"):
        return [n for n in names if n.startswith(COMPARE[6:])]
    return [n for n in COMPARE.split(",") if n in S["piece_of"]]


CMP_VIEWS = ("threequarter", "left")
CMP_COLS = ("mesh", "ours", "ref")
CMP_NODE = {"mesh": "cmp_mesh", "modelled": "cmp_mod", "ours": "cmp_ours", "ref": "cmp_ref"}


def cmp_cols(name):
    """The columns of a lock's sheet: an edited lock adds its piece as modelled; a drawn lock has no mesh and no
    reference strands of its own (they are given to the nearest mesh piece), so only our hair."""
    if name in S.get("drawn", ()):
        return ("ours",)
    if name in S.get("edited", ()):
        return ("mesh", "modelled", "ours", "ref")
    return CMP_COLS


def s_compare():
    """Queue the per-lock steps once the scene is open (the lock list comes from the scene)."""
    steps = []
    for name in compare_names():
        def _lock(name=name):
            pc = S["piece_of"][name]
            S["cmp_ours_blast"].parm("group").set(f"@lock_id!={S['lock_of'][name]}")
            S["cmp_mesh_blast"].parm("group").set(f"@piece!={pc}")
            S["cmp_mod_blast"].parm("group").set(f"@piece!={pc}")
            if "cmp_ref_blast" in S:
                S["cmp_ref_blast"].parm("group").set(f"@qc_piece!={pc}")
            box = None
            for col in cmp_cols(name):        # only what has points: an empty mesh box framed a drawn lock wide
                key = CMP_NODE[col]
                if key in S:
                    S[key].cook(force=True)
                    if not S[key].geometry().points():
                        continue
                    b = S[key].geometry().boundingBox()
                    if box is None:
                        box = b
                    else:
                        box.enlargeToContain(b)
            S["cmp_box"] = box if box is not None else S["bbox_all"]
        steps.append(_lock)
        for view in CMP_VIEWS:
            for col in cmp_cols(name):
                node_key = CMP_NODE[col]

                def _prep(view=view, node_key=node_key):
                    if node_key in S:
                        S[node_key].setDisplayFlag(True)
                        set_view(view, S["cmp_box"])

                def _shot(name=name, view=view, col=col, node_key=node_key):
                    if node_key in S:
                        grab(f"_part_{name}_{view}_{col}")

                steps.extend([_prep, _shot])

        def _stitch(name=name):
            stitch(name)
        steps.append(_stitch)
    STEPS[_i[0]:_i[0]] = steps
    log("compare", len(compare_names()), "locks")


def stitch(name):
    """3 columns (mesh, ours, reference) x 2 rows (views) from the parts, centre-cropped, labelled."""
    from PySide6 import QtGui
    parts = {}
    cols = cmp_cols(name)
    for view in CMP_VIEWS:
        for col in cols:
            f = os.path.join(OUT, f"_part_{name}_{view}_{col}.png")
            if os.path.exists(f):
                img = QtGui.QImage(f)
                w, h = img.width(), img.height()
                parts[(view, col)] = img.copy(int(w * 0.5 - h * 0.45), 0, int(h * 0.9), h).scaledToHeight(700)
    if not parts:
        return
    cw = max(p.width() for p in parts.values())
    sheet = QtGui.QImage(cw * len(cols), 700 * len(CMP_VIEWS) + 40, QtGui.QImage.Format_RGB32)
    sheet.fill(QtGui.QColor(40, 40, 40))
    pt = QtGui.QPainter(sheet)
    pt.setPen(QtGui.QColor(230, 230, 230))
    f = pt.font(); f.setPixelSize(24); pt.setFont(f)
    labels = {"mesh": "carried mesh" if name in S.get("edited", ()) else "mesh", "modelled": "mesh as modelled",
              "ours": "MONO Grooming (drawn lock, no mesh)" if name in S.get("drawn", ()) else "MONO Grooming",
              "ref": "reference"}
    for c, col in enumerate(cols):
        pt.drawText(c * cw + 12, 30, f"{name}  {labels[col]}" if c == 0 else labels[col])
        for r, view in enumerate(CMP_VIEWS):
            if (view, col) in parts:
                pt.drawImage(c * cw, 40 + r * 700, parts[(view, col)])
    pt.end()
    sheet.save(os.path.join(OUT, f"cmp_{name}.png"))
    for view in CMP_VIEWS:
        for col in cols:
            try:
                os.remove(os.path.join(OUT, f"_part_{name}_{view}_{col}.png"))
            except OSError:
                pass


def add_shot_locks_now():
    """Queue the shot close-ups once the scene is open (lock names and pieces come from it)."""
    global STEPS
    queued = STEPS
    STEPS = []
    add_shot_locks()
    new, STEPS = STEPS, queued
    STEPS[_i[0]:_i[0]] = new
    log("shot locks", SHOT_LOCKS, len(new), "steps")


if COMPARE:
    STEPS.append(s_compare)

worst = [n for n in os.environ.get("QC_LOCKS", "").split(",") if n]
if FRAMES:
    worst = []
elif not worst and REPORT and os.path.exists(REPORT):
    with open(REPORT, encoding="utf-8") as fh:
        worst = [r["name"] for r in json.load(fh).get("worst_locks", [])[:4]]
for name in worst:
    for i, view in enumerate(("threequarter", "left")):
        def _prep(name=name, view=view, first=(i == 0)):
            if first:
                # output 1 ignores the eye solo() sets: the lock is blasted out of it by its id
                S["lock_ours"].parm("group").set(f"@lock_id!={S['lock_of'].get(name, -1)}")
                S["tpl"].parm("group").set(f"@piece!={S['piece_of'].get(name, -1)}")
                S["tpl"].setTemplateFlag(name not in S.get("drawn", ()))
            S["lock_ours"].setDisplayFlag(True)
            S["lock_ours"].cook(force=True)
            set_view(view, S["lock_ours"].geometry().boundingBox())

        def _shot(name=name, i=i):
            grab(f"lock_{name}_{'ab'[i]}")

        STEPS.extend([_prep, _shot])


def s_quit():
    log("done")
    _log.close()
    hou.exit(suppress_save_prompt=True)


STEPS.append(s_quit)
_i = [0]


def _next():
    fn = STEPS[_i[0]]
    _i[0] += 1
    try:
        fn()
    except Exception:  # noqa: BLE001
        log("ERROR", getattr(fn, "__name__", "?"), traceback.format_exc())
    if _i[0] < len(STEPS):
        QtCore.QTimer.singleShot(2500, _next)


QtCore.QTimer.singleShot(5000, _next)
