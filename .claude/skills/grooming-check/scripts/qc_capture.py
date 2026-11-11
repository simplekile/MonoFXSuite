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


def viewer():
    return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)


def grab(name):
    """The viewport only, full size."""
    mw = hou.qt.mainWindow()
    scr = mw.screen()
    pix = scr.grabWindow(0, mw.x() - scr.geometry().x(), mw.y() - scr.geometry().y(), mw.width(), mw.height())
    # crop the menus, shelf and timeline away: the viewport is the big middle of a maximized pane
    h, w = pix.height(), pix.width()
    pix = pix.copy(int(w * 0.012), int(h * 0.15), int(w * 0.965), int(h * 0.80))
    pix.save(os.path.join(OUT, name + ".png"))


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


def set_view(view, bbox):
    vp = viewer().curViewport()
    vp.changeType(hou.geometryViewportType.Perspective)
    rx, ry = VIEWS.get(view, (-15, 40))
    cam = vp.defaultCamera()
    cam.setRotation(hou.hmath.buildRotate(rx, ry, 0).extractRotationMatrix3())
    vp.frameBoundingBox(bbox)
    aim_looks()


def solo(names):
    ga, node = S["ga"], S["node"]
    data = ga.read_data(node)
    for lk in data.locks:
        lk.visible = (names is None) or lk.name in names
    ga.write_data(node, data, "qc solo")


STEPS = []


def s_open():
    mw = hou.qt.mainWindow()
    if SECOND is not None:
        mw.setGeometry(SECOND.availableGeometry())
    hou.hda.installFile(SUITE + "/otls/mono_grooming.hdalc")
    hou.hipFile.load(HIP, suppress_save_prompt=True, ignore_load_warnings=True)
    from apps.houdini import grooming_adapter as ga
    S["ga"], S["node"] = ga, ga.find_nodes()[0]
    node = S["node"]
    geo = node.parent()
    node.setInput(2, None)                 # rest pose: the hair mesh is the target
    ga.set_display(node, "hair", "lock")
    S["ours"] = look_network(geo, node, "ours")
    if REF:
        imp = geo.createNode("usdimport", "qc_ref_usd")
        imp.parm("filepath1").set(REF)
        for k, v in (("input_unpack", 1), ("unpack_geomtype", 1)):
            if imp.parm(k):
                imp.parm(k).set(v)
        S["ref"] = look_network(geo, imp, "ref")
    pieces = geo.createNode("object_merge", "qc_pieces")
    pieces.parm("objpath1").set(node.path() + "/pieces")
    tpl = geo.createNode("blast", "qc_lock_mesh")       # the solo lock's own mesh, as a wire template
    tpl.setInput(0, pieces)
    tpl.parm("grouptype").set(3)                         # points
    tpl.parm("group").set("@piece!=-1")
    S["tpl"] = tpl
    S["piece_of"] = {p.attribValue("name"): int(p.attribValue("piece"))
                     for p in node.node("SPINES").geometry().prims()}
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


add_views("", "ours")
if REF:
    add_views("ref_", "ref")

worst = [n for n in os.environ.get("QC_LOCKS", "").split(",") if n]
if not worst and REPORT and os.path.exists(REPORT):
    with open(REPORT, encoding="utf-8") as fh:
        worst = [r["name"] for r in json.load(fh).get("worst_locks", [])[:4]]
for name in worst:
    for i, view in enumerate(("threequarter", "left")):
        def _prep(name=name, view=view, first=(i == 0)):
            if first:
                solo({name})
                S["tpl"].parm("group").set(f"@piece!={S['piece_of'].get(name, -1)}")
                S["tpl"].setTemplateFlag(True)
            S["ours"].setDisplayFlag(True)
            S["ours"].cook(force=False)
            set_view(view, S["ours"].geometry().boundingBox())

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
        QtCore.QTimer.singleShot(3500, _next)


QtCore.QTimer.singleShot(5000, _next)
