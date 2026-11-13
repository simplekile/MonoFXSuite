"""Acceptance of MONO Grooming v0.2a, rung 7: the mask brush in the viewport (Houdini GUI).

    set ACCEPT_SUITE=<suite>  ACCEPT_SCENE=<scene.hiplc>  ACCEPT_OUT=<out_dir>   [ACCEPT_STEPS=s1,s4]
    houdini.exe -foreground accept_v02a_gui.py

Run it on the SECONDARY monitor only, one GUI Houdini at a time across sessions (the plan's gui.lock), and
kill only the process you started. Strokes are Qt mouse events sent to the viewport widget (the real cursor
stays the user's), pictures are viewport flipbooks (never a screen grab). It writes `accept_gui.json` (same
shape as accept.json), `shots/*.png` and `accept_v02a_gui_painted.hiplc` under the out folder, and ends its
log with DONE. The panel is not part of it (it does not exist yet): Paint is entered through the adapter.

Checks: gui_* the brush itself, dw2_* the plan's "crown painted down, thin skin painted up, in the GUI by
scripted strokes"."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

SUITE = os.environ["ACCEPT_SUITE"].replace("\\", "/")
SCENE = os.environ["ACCEPT_SCENE"].replace("\\", "/")
OUT = os.environ["ACCEPT_OUT"].replace("\\", "/")
ONLY = [s for s in os.environ.get("ACCEPT_STEPS", "").split(",") if s]
SHOTS = OUT + "/shots"
os.makedirs(SHOTS, exist_ok=True)
for _m in [k for k in list(sys.modules) if k in ("tools", "apps") or k.startswith(("tools.", "apps."))]:
    del sys.modules[_m]
sys.path.insert(0, SUITE)
sys.path.insert(0, SUITE + "/tests/houdini/grooming")

import hou  # noqa: E402
import numpy as np  # noqa: E402
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

import accept_lib as lib  # noqa: E402

V006_CROWN = 5104.0
app = QtWidgets.QApplication.instance()
SECOND = next((s for s in app.screens() if s is not app.primaryScreen()), None)
C = lib.Checks(OUT, "accept_gui.json", {"suite": SUITE, "scene": SCENE, "part": "v0.2a", "rung": 7,
                                        "houdini": hou.applicationVersionString(),
                                        "screens": [s.name() for s in app.screens()],
                                        "secondary": SECOND.name() if SECOND is not None else None})
S: dict = {}
STEPS = []


def step(fn):
    STEPS.append(fn)
    return fn


def later(ms, fn):
    def run():
        try:
            fn()
        except Exception:
            C.add("step_" + S.get("step", "?"), False, traceback.format_exc()[-1500:], note="the step raised")
            S["next"]()
    QtCore.QTimer.singleShot(ms, run)


def viewer():
    return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)


def shot(name, res=(1280, 960)):
    sv = viewer()
    s = sv.flipbookSettings().stash()
    f = int(hou.frame())
    s.frameRange((f, f))
    s.output(f"{SHOTS}/{name}.$F4.png")
    s.outputToMPlay(False)
    s.useResolution(True)
    s.resolution(res)
    sv.flipbook(sv.curViewport(), s)
    src = f"{SHOTS}/{name}.{f:04d}.png"
    if os.path.isfile(src):
        os.replace(src, f"{SHOTS}/{name}.png")
    return f"shots/{name}.png"


def ga():
    from apps.houdini import grooming_adapter
    return grooming_adapter


def state_mod():
    from apps.houdini import grooming_paint_state
    return grooming_paint_state


def centre_px() -> QtCore.QPoint:
    return viewer().qtScreenGeometry().center()


def gl_widget():
    """The viewport's widget. Looked up inside Houdini's own window, so another window lying over it (the
    user's own Houdini on the same screen) does not hide it from the test."""
    c = centre_px()
    mw = hou.qt.mainWindow()
    return app.widgetAt(c) if app.widgetAt(c) is not None and app.widgetAt(c).window() is mw         else mw.childAt(mw.mapFromGlobal(c))


def _send(kind, pt, buttons, modifiers=QtCore.Qt.NoModifier):
    """A Qt mouse event to the viewport widget at global point `pt` (the user's own cursor is not touched)."""
    gp = QtCore.QPoint(int(round(pt[0])), int(round(pt[1])))
    w = S.get("gl") or gl_widget()
    S["gl"] = w
    lp = QtCore.QPointF(w.mapFromGlobal(gp))
    button = QtCore.Qt.LeftButton if kind != QtCore.QEvent.MouseMove else QtCore.Qt.NoButton
    app.sendEvent(w, QtGui.QMouseEvent(kind, lp, QtCore.QPointF(gp), button, buttons, modifiers))


def drag(points, done, step_ms=16, settle_ms=400):
    """One stroke through global points, one move a timer tick (Houdini merges moves sent in one tick)."""
    pts = [(float(x), float(y)) for x, y in points]

    def press():
        _send(QtCore.QEvent.MouseButtonPress, pts[0], QtCore.Qt.LeftButton)
        later(step_ms, lambda: move(1))

    def move(i):
        if i >= len(pts):
            return later(60, release)
        _send(QtCore.QEvent.MouseMove, pts[i], QtCore.Qt.LeftButton)
        later(step_ms, lambda: move(i + 1))

    count = len(state_mod().STATS["strokes"])

    def release():
        _send(QtCore.QEvent.MouseButtonRelease, pts[-1], QtCore.Qt.NoButton)
        later(100, lambda: wait(0))

    def wait(n):
        # the release stores the stroke and cooks the node; Houdini may handle it after this tick
        if len(state_mod().STATS["strokes"]) > count or n > 200:
            return later(settle_ms, done)
        later(100, lambda: wait(n + 1))

    _send(QtCore.QEvent.MouseMove, pts[0], QtCore.Qt.NoButton)
    later(120, press)


def line(dx0, dy, dx1, n=40):
    c = centre_px()
    return [(c.x() + dx0 + (dx1 - dx0) * i / (n - 1), c.y() + dy) for i in range(n)]


def set_view(normal, bbox):
    """Look at the skin square on (against its normal), framed on `bbox`."""
    n = hou.Vector3(*(float(x) for x in normal)).normalized()
    ry = float(np.degrees(np.arctan2(n[0], n[2])))
    rx = -float(np.degrees(np.arcsin(max(-1.0, min(1.0, n[1])))))
    vp = viewer().curViewport()
    vp.changeType(hou.geometryViewportType.Perspective)
    vp.defaultCamera().setRotation(hou.hmath.buildRotate(rx, ry, 0).extractRotationMatrix3())
    vp.frameBoundingBox(bbox)


def box_round(centre_cm, half_cm):
    c = np.asarray(centre_cm) / S["G"].unit
    h = half_cm / S["G"].unit
    return hou.BoundingBox(c[0] - h, c[1] - h, c[2] - h, c[0] + h, c[1] + h, c[2] + h)


def calibrate(done):
    """Global pixel <- viewport screen position, fitted from where three test moves hit the scalp (so no
    guess about toolbars, pixel ratio or the viewport's place in the pane)."""
    st = state_mod().running()
    c = centre_px()
    # a dozen probes near and far: on skin at the scalp's edge the far ones fall off it
    probes = [(c.x() + dx, c.y() + dy) for dx, dy in ((0, 0), (90, 10), (-20, 80), (-70, -60), (30, 0), (0, 30),
                                                     (-30, -10), (15, -35), (60, 50), (-55, 40), (45, -45), (0, -70))]
    got = []

    def go(i):
        if i > 0 and st.last_hit is not None:
            world = hou.Vector3(st.last_hit) * st.xform
            got.append((probes[i - 1], tuple(viewer().curViewport().mapToScreen(world))))
        if i >= len(probes):
            if len(got) < 3:
                raise RuntimeError("calibration: the test moves missed the scalp (%d hits)" % len(got))
            a = np.array([[sx, sy, 1.0] for _g, (sx, sy) in got])
            b = np.array([g for g, _s in got], dtype=float)
            S["px"] = np.linalg.lstsq(a, b, rcond=None)[0]
            return done()
        _send(QtCore.QEvent.MouseMove, probes[i], QtCore.Qt.NoButton)
        later(110, lambda: go(i + 1))
    go(0)


def to_px(points_cm):
    """Global pixels of points on the skin (cm, object space), by the fitted map."""
    st = state_mod().running()
    vp = viewer().curViewport()
    out = []
    for p in points_cm:
        sx, sy = vp.mapToScreen(hou.Vector3(*(np.asarray(p) / S["G"].unit)) * st.xform)
        out.append(tuple(np.array([sx, sy, 1.0]) @ S["px"]))
    return out


def rows_over(centre_cm, normal, half_cm, spacing_cm, points=14):
    """Stroke paths (cm, on the skin) that cover the disc of `half_cm` round `centre_cm`: straight rows
    `spacing_cm` apart, each point moved onto the nearest scalp point."""
    n = np.asarray(normal, float)
    n /= np.linalg.norm(n)
    e1 = np.cross(n, [0.0, 1.0, 0.0] if abs(n[1]) < 0.9 else [1.0, 0.0, 0.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    rows = []
    for k, off in enumerate(np.arange(-half_cm, half_cm + 1e-6, spacing_cm)):
        w = np.sqrt(max(half_cm ** 2 - off ** 2, 0.0))
        if w < 0.2:
            continue
        ts = np.linspace(-w, w, points)[::(-1 if k % 2 else 1)]
        # on the tangent plane: the cursor's ray finds the skin (snapped to the nearest scalp POINT, rows
        # collapsed onto a band of tiny polygons nearby)
        rows.append([np.asarray(centre_cm) + e2 * off + e1 * t for t in ts])
    return rows


def strokes(paths_cm, done):
    """Drag each path in turn (one stroke, one undo step, one cook each)."""
    def go(i):
        if i >= len(paths_cm):
            return done()
        drag(to_px(paths_cm[i]), lambda: go(i + 1), step_ms=16, settle_ms=250)
    go(0)


def stroke_stats(n=1):
    return [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}
            for s in state_mod().STATS["strokes"][-n:]]


# ------------------------------------------------------------------ steps (each calls S["next"]() when done)

@step
def s0_open():
    mw = hou.qt.mainWindow()
    if SECOND is None:
        C.add("gui_on_the_secondary_monitor", False, [s.name() for s in app.screens()],
              "a second screen: the GUI check never runs on the main one")
        S["abort"] = True
        return S["next"]()
    mw.setGeometry(SECOND.availableGeometry())
    gai, node = lib.open_scene(SUITE, SCENE)
    lib.fresh(gai, node)
    S["node"] = node
    for o in hou.node("/obj").children():
        o.setDisplayFlag(o == node.parent())
    viewer().setPwd(node.parent())
    node.setCurrent(True, clear_all_selected=True)
    node.cook(force=True)
    G = lib.Groom(gai, node)
    S["G"] = G
    S["base_strands"] = G.strands()
    L = G.lock_id("hair_back_06")
    geo = node.node("SCALP_REGIONS").geometry()
    prims = G.region_prims(L)
    nrm = sum((geo.prim(int(p)).normal() for p in prims[::20]), hou.Vector3()).normalized()
    S["zone"] = {"L": L, "centre_cm": G.scalp()["cen_cm"][prims].mean(0), "normal": tuple(nrm)}
    set_view(S["zone"]["normal"], box_round(S["zone"]["centre_cm"], 3.5))
    on_second = mw.screen() is SECOND
    C.add("gui_on_the_secondary_monitor", on_second, {"window_on": mw.screen().name(), "secondary": SECOND.name(),
                                                      "locked_hda": bool(node.isLockedHDA()),
                                                      "errors": lib.node_errors(node)[:3],
                                                      "strands": S["base_strands"]}, "Houdini's window on the second screen")
    later(2500, S["next"])


@step
def s1_strokes():
    """Paint, undo per stroke, soft edge, erase, the ring and the coloured scalp."""
    node = S["node"]
    lid = ga().mask_add(node, "paint", kind="paint")      # a paint layer: the brush carries the value
    S["lid"] = lid
    ga().set_brush(radius_cm=1.0, value=0.0, soft=0.5, erase=False, view="factor", level=1.0)
    shots = [shot("s1_0_before")]
    S["undo_before_paint"] = list(hou.undos.undoLabels()[:3])
    entered = ga().paint_enter(node, lid)
    st = state_mod().running()
    C.add("gui_paint_enter", bool(entered and st is not None and st.session is not None),
          {"state": viewer().currentState(), "paint_layer": ga().paint_layer(node), "locked_hda": bool(node.isLockedHDA()),
           "enter_s": round(state_mod().STATS.get("enter_s", -1), 3), "errors": state_mod().STATS["errors"][-1:]},
          "the viewport's tool is the mask brush on the layer, the HDA still locked")
    snaps = {}

    def after_a():
        snaps["a"] = lib.mask_arrays(node, lid)
        S["stroke_a"] = stroke_stats()[0]
        ga().set_brush(value=2.0)
        drag(line(-150, 40, 150), after_b)

    def after_b():
        snaps["b"] = lib.mask_arrays(node, lid)
        S["stroke_b"] = stroke_stats()[0]
        shots.append(shot("s1_1_two_strokes"))
        v, a = snaps["a"]
        soft = int(((a > 0.02) & (a < 0.98)).sum())
        st = state_mod().running()
        cd = np.frombuffer(st.geo.pointFloatAttribValuesAsString("Cd"), np.float32).reshape(-1, 3)
        blue = int((cd[:, 2] > cd[:, 0] + 0.2).sum())
        red = int((cd[:, 0] > cd[:, 2] + 0.2).sum())
        locks = S["G"].cook_display()
        C.add("gui_stroke_paints_with_a_soft_edge",
              a is not None and int((a > 0).sum()) > 50 and soft > 10 and float(v[a > 0.98].max()) == 0.0,
              {"stroke": S["stroke_a"], "points_painted": int((a > 0).sum()), "points_on_the_soft_edge": soft,
               "undo_label": hou.undos.undoLabels()[0]}, "one drag paints skin; coverage between 0 and 1 on its edge",
              evidence=shots[-1])
        C.add("gui_scalp_coloured_and_ring_on_the_skin",
              blue > 50 and red > 50 and st.ring is not None and st.last_hit is not None,
              {"scalp_points_blue": blue, "scalp_points_red": red, "ring_on_skin_at": [round(float(x), 4) for x in st.last_hit],
               "draws_through": "hou.SimpleDrawable (scalp) + hou.GeometryDrawable (ring)"},
              "the scalp drawable shows 0 as blue and 2 as red; the ring follows the cursor's hit", evidence=shots[-1])
        # ---- undo per stroke
        t = time.perf_counter()
        hou.undos.performUndo()
        node.cook()
        undo_s = time.perf_counter() - t
        u1 = lib.mask_arrays(node, lid)
        undo_locks = len(node.node("to_cook").geometry().iterPrims())
        later(400, lambda: after_undo(u1, undo_s, undo_locks))

    def after_undo(u1, undo_s, undo_locks):
        st = state_mod().running()
        seen = np.array_equal(st.session.md.a[lid], u1[1])          # the brush took the undone state
        shots.append(shot("s1_2_after_undo"))
        hou.undos.performUndo()
        u0 = lib.mask_arrays(node, lid)
        hou.undos.performRedo()
        hou.undos.performRedo()
        r2 = lib.mask_arrays(node, lid)
        node.cook()
        C.add("gui_undo_removes_one_stroke",
              lib.same_arrays(u1, snaps["a"]) and (u0[1] is None or not (u0[1] > 0).any()) and lib.same_arrays(r2, snaps["b"])
              and seen and undo_locks == 0,
              {"undo_1_equals_after_stroke_1": lib.same_arrays(u1, snaps["a"]), "undo_2_is_unpainted": bool(u0[1] is None or not (u0[1] > 0).any()),
               "redo_2_equals_after_stroke_2": lib.same_arrays(r2, snaps["b"]), "brush_shows_the_undone_state": bool(seen),
               "undo_and_cook_s": round(undo_s, 3), "locks_regrown_by_the_undo": undo_locks},
              "each undo takes off exactly one stroke (bit for bit), redo puts it back, no lock regrown",
              evidence=shots[-1])
        later(400, erase)

    def erase():
        ga().set_brush(erase=True, radius_cm=0.6)
        drag(line(-60, -60, 60, n=20), after_erase)

    def after_erase():
        e = lib.mask_arrays(node, lid)
        b = snaps["b"]
        less = int((e[1] < b[1] - 1e-6).sum())
        more = int((e[1] > b[1] + 1e-6).sum())
        shots.append(shot("s1_3_after_erase"))
        ga().set_brush(erase=False, radius_cm=1.0, value=0.0)
        C.add("gui_erase_takes_paint_off", less > 20 and more == 0 and hou.undos.undoLabels()[0].endswith("Erase mask"),
              {"points_with_less_coverage": less, "points_with_more": more, "undo_label": hou.undos.undoLabels()[0],
               "stroke": stroke_stats()[0]}, "an erase stroke only lowers coverage, one undo step", evidence=shots[-1])
        rows = [S["stroke_a"], S["stroke_b"]]
        C.add("gui_brush_keeps_up", all(r["handler_ms_median"] < 8.0 and r["dabs"] > 10 for r in rows),
              {"strokes": rows}, "our code under 8 ms a mouse move (median), nothing cooks while the button is down",
              note="GUI cook seconds are recorded, not judged here: rung 5 times the cook in hython")
        S["next"]()

    def go():
        ga().set_brush(value=0.0)
        drag(line(-150, -60, 150), after_a)

    later(500, lambda: calibrate(go))


def image_diff(a, b) -> float:
    """Mean absolute difference of two shots (0..255), on a 160 px wide copy."""
    ia = QtGui.QImage(OUT + "/" + a).convertToFormat(QtGui.QImage.Format_RGB888).scaledToWidth(160)
    ib = QtGui.QImage(OUT + "/" + b).convertToFormat(QtGui.QImage.Format_RGB888).scaledToWidth(160)
    n = ia.width() * ia.height() * 3
    pa = np.frombuffer(bytes(ia.constBits())[:ia.sizeInBytes()], np.uint8).reshape(ia.height(), ia.bytesPerLine())[:, :ia.width() * 3]
    pb = np.frombuffer(bytes(ib.constBits())[:ib.sizeInBytes()], np.uint8).reshape(ib.height(), ib.bytesPerLine())[:, :ib.width() * 3]
    return float(np.abs(pa.astype(int) - pb.astype(int)).sum() / n)


@step
def s1b_undo_look():
    """What the artist sees over a Ctrl+Z: the coloured scalp stays (Guides display, so the skin is in view)."""
    node = S["node"]
    lid = S["lid"]
    ga().set_display(node, "guide", "lock")
    node.cook()
    set_view(S["zone"]["normal"], node.inputs()[0].geometry().boundingBox())
    ga().set_brush(value=0.0, radius_cm=2.0, erase=False)
    shots = {}

    def before():
        shots["before"] = shot("s1b_0_before_stroke")
        drag(line(-60, 0, 60, n=20), after_stroke)

    def after_stroke():
        shots["stroke"] = shot("s1b_1_after_stroke")
        hou.undos.performUndo()
        later(700, after_undo)

    def after_undo():
        shots["undo"] = shot("s1b_2_after_undo")
        st = state_mod().running()
        on = st is not None and ga().paint_layer(node) == lid
        ga().paint_exit(node)
        later(500, lambda: off(on))

    def off(on):
        shots["off"] = shot("s1b_3_paint_off")
        d = {"stroke_vs_before": image_diff(shots["stroke"], shots["before"]),
             "undo_vs_before": image_diff(shots["undo"], shots["before"]),
             "undo_vs_paint_off": image_diff(shots["undo"], shots["off"])}
        C.add("gui_scalp_stays_drawn_after_undo",
              on and d["undo_vs_before"] < 0.5 * d["stroke_vs_before"] and d["undo_vs_paint_off"] > 4 * max(d["undo_vs_before"], 0.05),
              {"paint_still_on_after_undo": on, "image_mean_abs_diff": {k: round(v, 3) for k, v in d.items()}, "shots": shots},
              "after the undo the picture is the one before the stroke (scalp drawn, paint gone), not the one "
              "with Paint off (no scalp)", evidence=shots["undo"])
        ga().set_display(node, "hair", "lock")
        node.cook()
        set_view(S["zone"]["normal"], box_round(S["zone"]["centre_cm"], 3.5))
        ga().set_brush(value=0.0, radius_cm=1.0)
        ga().paint_enter(node, lid)
        later(600, lambda: calibrate(S["next"]))

    later(1200, before)


@step
def s1c_views():
    """What the scalp shows: the density as it is, the final factor, the painted layer alone, the roots."""
    from tools.fx.grooming import logic
    node = S["node"]
    lid = S["lid"]
    st = state_mod().running()
    ga().set_display(node, "guide", "lock")
    node.cook()
    set_view(S["zone"]["normal"], node.inputs()[0].geometry().boundingBox())
    v, a = lib.mask_arrays(node, lid)
    cds, shots, took = {}, {}, {}
    views = ("factor", "layer", "density", "roots")

    def go(i):
        if i > 0:
            cds[views[i - 1]] = np.frombuffer(st.geo.pointFloatAttribValuesAsString("Cd"), np.float32).reshape(-1, 3).copy()
            shots[views[i - 1]] = shot("s1c_view_" + views[i - 1])
        if i >= len(views):
            return finish()
        t = time.perf_counter()
        ga().set_brush(view=views[i])        # density and roots count the groom's roots (Guides: grows the hair)
        took[views[i]] = round(time.perf_counter() - t, 2)
        later(500, lambda: go(i + 1))

    def finish():
        unpainted = a <= 0
        ok_layer = bool(np.allclose(cds["layer"][unpainted], logic.LAYER_UNPAINTED, atol=1e-5)) and int(unpainted.sum()) > 1000
        ses = st.session
        base, reference, point_area = ses.base_density()
        dens = ses.density()
        pick = np.linspace(0, len(dens) - 1, 300).astype(int)
        mask = ses.md.mask(ses.layer())
        want = np.array([logic.mask_tint(logic.density_color(float(dens[i]), reference), float(mask[i])) for i in pick])
        err = float(np.abs(cds["density"][pick] - want).max())
        strands = S["G"].strands()
        counted = float((ses.actual * point_area).sum()) if ses.actual is not None else 0.0
        dots = st.root_count
        plain = bool(np.allclose(cds["roots"], cds["roots"][0]))
        ga().set_brush(view="density")
        S["views_done"] = True
        C.add("gui_views_density_factor_layer_roots",
              ok_layer and ses.whole and err < 1e-4 and abs(counted / strands - 1) < 0.15 and dots == strands > 1000 and plain,
              {"layer_view_unpainted_skin_is_dark": ok_layer, "groom_counted_whole": bool(ses.whole),
               "density_view_max_error_against_the_ramp": err, "density_reference_per_cm2": reference,
               "roots_the_density_adds_up_to": round(counted), "strands_of_the_groom": strands,
               "densest_point_per_cm2": round(float(ses.actual.max())) if ses.actual is not None else None,
               "root_dots": dots, "roots_view_scalp_is_plain": plain, "seconds_to_switch_view": took, "shots": shots},
              "layer view: skin the layer does not cover is dark; density view: roots / cm2 counted from the groom "
              "(it adds up to the strand count within 15 %), coloured by the ramp; roots view: one dot a strand on "
              "a plain scalp",
              evidence=shots["density"],
              note="Guides display, so the scalp is in view: choosing density or roots grows the groom once to count it")
        later(300, guides_stroke)

    def guides_stroke():
        # a stroke in Guides display must not grow hair to recount: the view goes on by prediction
        ses = state_mod().running().session
        before = ses.density().copy()
        cooks0 = node.node("groom_cache").cookCount()
        ga().set_brush(value=0.0, radius_cm=2.0, erase=False)
        drag(line(-40, 70, 40, n=12), lambda: after_guides(before, cooks0))

    def after_guides(before, cooks0):
        ses = state_mod().running().session
        st1 = stroke_stats()[0]
        v1, a1 = lib.mask_arrays(node, lid)
        core = (a1 >= 0.99) & (v1 == 0.0) & (before > 1.0)
        now = ses.density()
        fell = float(now[core].sum() / max(before[core].sum(), 1e-9)) if core.any() else 1.0
        grew = node.node("groom_cache").cookCount() - cooks0
        cost = (st1.get("cook_s") or 0) + (st1.get("count_s") or 0)
        C.add("gui_stroke_in_guides_grows_no_hair", grew == 0 and cost < 0.3 and fell < 0.05 and int(core.sum()) > 20,
              {"output1_cooks_by_the_stroke": grew, "cook_s": st1.get("cook_s"), "count_s": st1.get("count_s"),
               "density_view_on_the_stroke_after_over_before": round(fell, 4), "points": int(core.sum()),
               "counted_before": bool(ses.counted)},
              "Guides display: a stroke cooks no hair (output 1 untouched), costs under 0.3 s, and the density "
              "view still drops where 0 was painted (predicted from the last count)")
        hou.undos.performUndo()
        ga().set_brush(value=0.0, radius_cm=1.0)
        ga().set_display(node, "hair", "lock")
        node.cook()
        set_view(S["zone"]["normal"], box_round(S["zone"]["centre_cm"], 3.5))
        later(600, lambda: calibrate(S["next"]))

    later(800, lambda: go(0))


@step
def s1d_fill_layer():
    """Substance Painter's way: the layer holds one number, the brush paints its mask white or black."""
    from tools.fx.grooming import logic
    node = S["node"]
    paint_layer = S["lid"]
    ga().mask_set(node, paint_layer, on=False)
    node.cook()
    lid = ga().mask_add(node, "half", mode="multiply", value=0.5)
    ga().set_brush(radius_cm=1.0, soft=0.5, erase=False, level=1.0, view="density")
    ga().paint_enter(node, lid)
    st = state_mod().running()
    st.reroot(cook=True)
    before = st.session.density().copy()
    snaps, shots = {}, {}

    def white():
        drag(line(-120, -20, 120, n=30), after_white)

    def after_white():
        snaps["white"] = lib.mask_arrays(node, lid)
        v, a = snaps["white"]
        st = state_mod().running()
        after = st.session.density()
        core = a >= 0.99
        fell = float(after[core].sum() / max(before[core].sum(), 1e-9))
        snaps["fell"] = fell
        shots["density"] = shot("s1d_0_fill_white_density_view")
        ga().set_brush(view="layer")
        later(400, mask_view)

    def mask_view():
        st = state_mod().running()
        v, a = snaps["white"]
        cd = np.frombuffer(st.geo.pointFloatAttribValuesAsString("Cd"), np.float32).reshape(-1, 3)
        snaps["white_shown"] = bool(np.allclose(cd[a >= 1.0], 1.0, atol=1e-5)) and int((a >= 1.0).sum()) > 50 and bool(
            np.allclose(cd[a <= 0], logic.LAYER_UNPAINTED, atol=1e-5))
        shots["mask"] = shot("s1d_1_fill_mask_view")
        ga().set_brush(level=0.0, radius_cm=0.6)
        drag(line(-40, -20, 40, n=14), after_black)

    def after_black():
        v, a = lib.mask_arrays(node, lid)
        w = snaps["white"][1]
        less = int((a < w - 1e-6).sum())
        more = int((a > w + 1e-6).sum())
        shots["black"] = shot("s1d_2_fill_black_stroke")
        hou.undos.performUndo()
        undone = lib.same_arrays(lib.mask_arrays(node, lid), snaps["white"])
        ga().set_brush(level=1.0, radius_cm=1.0, view="density")
        C.add("gui_fill_layer_brush_paints_its_mask",
              snaps["white"][0] is None and int((w > 0).sum()) > 50 and 0.35 < snaps["fell"] < 0.7 and snaps["white_shown"]
              and less > 20 and more == 0 and undone,
              {"layer": "multiply 0.5", "stored": "mask only" if snaps["white"][0] is None else "value and mask",
               "points_painted_white": int((w > 0).sum()), "density_on_the_white_skin_after_over_before": round(snaps["fell"], 3),
               "mask_view_white_on_dark": snaps["white_shown"], "black_stroke_points_lowered": less,
               "black_stroke_points_raised": more, "undo_takes_the_black_stroke_off": undone, "shots": shots},
              "a white stroke paints only the mask and the density view shows the skin under it at about half "
              "(0.35 - 0.7: relocated roots included); the mask view is white on dark; a black stroke only "
              "lowers the mask; undo takes it off", evidence=shots["mask"])
        ga().mask_remove(node, lid)
        ga().mask_set(node, paint_layer, on=True)
        ga().paint_enter(node, paint_layer)
        later(600, lambda: calibrate(S["next"]))

    later(600, lambda: calibrate(white))


@step
def s2_reselect():
    """Selecting the node again must not lose the brush (Houdini enters the node's own state then)."""
    node = S["node"]
    lid = S["lid"]
    before = lib.mask_arrays(node, lid)
    sm = state_mod()
    back0 = sm.STATS["came_back"]
    stack = list(hou.undos.undoLabels())
    since = stack[:next((i for i, x in enumerate(stack) if "Add mask layer" in x), len(stack))]
    S["undo_s1"], S["undo_s1_clean"] = since[:10], bool(since) and all(x.startswith("MONO Grooming: ") for x in since)
    S["undo_s2"], S["undo_s2_count"] = stack[:12], len(stack)
    node.setSelected(False, clear_all_selected=True)
    node.setCurrent(True, clear_all_selected=True)
    right_after = viewer().currentState()

    def check():
        mid = viewer().currentState()
        S["gl"] = None

        def painted():
            after = lib.mask_arrays(node, lid)
            grew = int((after[1] > before[1] + 1e-6).sum())
            labels = list(hou.undos.undoLabels()[:12])
            new = labels[:len(labels) - len([x for x in labels if x in S["undo_s2"]])] if False else labels
            added = len(hou.undos.undoLabels()) - S["undo_s2_count"]
            C.add("gui_paint_adds_no_undo_step_of_its_own",
                  S["undo_s1_clean"] and added <= 3 and labels[0].endswith("Paint mask"),
                  {"steps_since_the_layer_was_added": S["undo_s1"], "all_ours": S["undo_s1_clean"],
                   "steps_added_by_select_again_and_one_stroke": added, "undo_stack_top": labels[:4]},
                  "entering Paint records nothing (every step since the layer's Add is a stroke); selecting the "
                  "node again adds only Houdini's own two selection steps, the brush coming back none",
                  note="a tool change recorded as 'Change selection' between strokes made Ctrl+Z drop the brush")
            C.add("gui_no_stroke_lost_after_selecting_the_node_again",
                  viewer().currentState() == sm.STATE and sm.running() is not None and grew > 20
                  and ga().paint_layer(node) == lid,
                  {"state_right_after_select": right_after, "state_one_second_later": mid,
                   "brush_came_back": sm.STATS["came_back"] - back0, "houdini_went_to": sm.STATS.get("came_back_from"),
                   "points_painted_by_the_next_stroke": grew, "errors": sm.STATS["errors"][-1:]},
                  "the brush is still (or again) the tool and the next stroke paints")
            S["next"]()
        ga().set_brush(value=2.0, radius_cm=0.8)
        drag(line(-120, 100, 120, n=30), painted)

    later(1000, check)


@step
def s3_leave():
    """Leaving Paint: Esc, the adapter's paint_exit, and the artist picking another tool."""
    node = S["node"]
    lid = S["lid"]
    sm = state_mod()
    w = S.get("gl") or gl_widget()
    tried = []

    def esc_to(name, target):
        if target is None or viewer().currentState() != sm.STATE:
            return
        for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            app.sendEvent(target, QtGui.QKeyEvent(kind, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier, ""))
        tried.append(name)

    def try_esc(i):
        # a key sent by script has to find the widget Houdini reads keys from: the viewport, then whatever
        # holds the focus, then the main window
        if i == 0:
            w.setFocus()
            esc_to("viewport widget", w)
        elif i == 1:
            esc_to("focus widget", app.focusWidget())
        elif i == 2:
            esc_to("main window", hou.qt.mainWindow())
        else:
            return after_esc()
        later(500, lambda: try_esc(i + 1))

    def after_esc():
        esc = {"state": viewer().currentState(), "paint_layer": ga().paint_layer(node), "esc_sent_to": tried}
        C.add("gui_esc_leaves_paint", esc["state"] != sm.STATE and esc["paint_layer"] is None, esc,
              "Esc in the viewport ends Paint")
        ga().paint_enter(node, lid)
        later(300, exit_by_api)

    def exit_by_api():
        on = viewer().currentState() == sm.STATE
        st = sm.running()
        ga().paint_exit(node)
        hidden = st is not None and not st.down
        C.add("gui_paint_exit", on and viewer().currentState() != sm.STATE and ga().paint_layer(node) is None and hidden,
              {"was_on": on, "state_after": viewer().currentState(), "paint_layer": ga().paint_layer(node)},
              "paint_exit gives the viewport its tool back")
        ga().paint_enter(node, lid)
        later(300, pick_tool)

    def pick_tool():
        viewer().setCurrentState("select")          # the artist picks the Select tool
        later(900, after_tool)

    def after_tool():
        C.add("gui_another_tool_ends_paint", viewer().currentState() == "select" and ga().paint_layer(node) is None,
              {"state": viewer().currentState(), "paint_layer": ga().paint_layer(node)},
              "a tool picked by hand ends Paint (the brush does not come back over it)")
        S["next"]()

    later(500, lambda: try_esc(0))


def real_px(pt):
    """Physical screen pixel of a Qt global point (Windows input takes physical pixels)."""
    q = QtCore.QPoint(int(round(pt[0])), int(round(pt[1])))
    scr = app.screenAt(q) or SECOND
    g, ratio = scr.geometry(), scr.devicePixelRatio()
    return int(round(g.x() + (q.x() - g.x()) * ratio)), int(round(g.y() + (q.y() - g.y()) * ratio))


def real_drag(points, done, step_ms=20, settle_ms=500):
    """One stroke by the real mouse: Windows moves the cursor and presses the left button (the user's own
    cursor is taken for the time of the stroke)."""
    import ctypes
    u = ctypes.windll.user32
    pts = [real_px(p) for p in points]
    count = len(state_mod().STATS["strokes"])

    def press():
        u.mouse_event(0x0002, 0, 0, 0, 0)
        later(step_ms, lambda: move(1))

    def move(i):
        if i >= len(pts):
            return later(80, release)
        u.SetCursorPos(*pts[i])
        later(step_ms, lambda: move(i + 1))

    def release():
        u.mouse_event(0x0004, 0, 0, 0, 0)
        later(150, lambda: wait(0))

    def wait(n):
        if len(state_mod().STATS["strokes"]) > count or n > 100:
            return later(settle_ms, done)
        later(100, lambda: wait(n + 1))

    u.SetCursorPos(*pts[0])
    later(250, press)


@step
def s3b_real_mouse():
    """With the real mouse and keyboard (ACCEPT_INPUT=real): paint, Esc, Paint again, paint."""
    if os.environ.get("ACCEPT_INPUT") != "real":
        return S["next"]()
    import ctypes
    u = ctypes.windll.user32
    node = S["node"]
    sm = state_mod()
    for m in list(ga().read_data(node).masks):
        ga().mask_remove(node, m.id)
    lid = ga().mask_add(node, "real mouse", mode="multiply", value=0.5)
    ga().set_brush(radius_cm=1.0, soft=0.5, erase=False, level=1.0, view="factor")
    set_view(S["zone"]["normal"], box_round(S["zone"]["centre_cm"], 3.5))
    mw = hou.qt.mainWindow()
    hwnd = int(mw.winId())
    start = (ctypes.c_long * 2)()
    u.GetCursorPos(start)
    # in front of every other window (the user's own Houdini may lie over this one), then a real click on
    # its title bar: Windows gives the keyboard only to a window the user clicked
    u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0003)
    mw.raise_()
    mw.activateWindow()
    top = mw.frameGeometry()
    u.SetCursorPos(*real_px((top.center().x(), top.top() + 12)))
    u.mouse_event(0x0002, 0, 0, 0, 0)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    ga().paint_enter(node, lid)
    out = {"foreground_is_this_houdini": None}

    def painted():
        v, a = lib.mask_arrays(node, lid)
        return 0 if a is None else int((a > 0).sum())

    def first():
        out["foreground_is_this_houdini"] = bool(u.GetForegroundWindow() == hwnd)
        real_drag(line(-110, -30, 110, n=30), after_first)

    def after_first():
        out["stroke_1"] = {"points_painted": painted(), "stroke": stroke_stats()[0] if sm.STATS["strokes"] else None,
                           "undo_label": hou.undos.undoLabels()[0] if hou.undos.undoLabels() else ""}
        out["shot_1"] = shot("s3b_0_real_stroke")
        u.keybd_event(0x1B, 0, 0, 0)              # Esc down, up
        u.keybd_event(0x1B, 0, 2, 0)
        later(900, after_esc)

    def after_esc():
        out["after_esc"] = {"state": viewer().currentState(), "paint_layer": ga().paint_layer(node)}
        out["entered_again"] = bool(ga().paint_enter(node, lid))       # what the panel's Paint button does
        later(500, second)

    def second():
        out["before_2"] = painted()
        real_drag(line(-110, 50, 110, n=30), after_second)

    def after_second():
        n2 = painted()
        out["stroke_2"] = {"points_painted": n2, "added": n2 - out["before_2"],
                           "stroke": stroke_stats()[0] if sm.STATS["strokes"] else None}
        out["shot_2"] = shot("s3b_1_real_stroke_after_esc")
        out["state_errors"] = sm.STATS["errors"][-2:]
        u.SetCursorPos(start[0], start[1])
        u.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0003)        # no longer over every window
        ok = (out["foreground_is_this_houdini"] and out["stroke_1"]["points_painted"] > 50 and out["after_esc"]["state"] != sm.STATE
              and out["after_esc"]["paint_layer"] is None and out["entered_again"] and out["stroke_2"]["added"] > 50
              and not out["state_errors"])
        C.add("real_mouse_paint_esc_paint_again", ok, out,
              "a real left-button drag paints the mask; the real Esc key ends Paint; Paint on again and a second "
              "real drag paints more", evidence=out["shot_2"],
              note="Windows input (SetCursorPos, mouse_event, keybd_event) on the Houdini window brought to the front")
        ga().paint_exit(node)
        S["next"]()

    later(1200, first)


@step
def s4_crown():
    """dw2: the crown painted down to the approved groom's density, by strokes in the viewport."""
    node = S["node"]
    G = S["G"]
    for m in list(ga().read_data(node).masks):
        ga().mask_remove(node, m.id)
    node.cook()
    roots0 = G.roots()
    centre, n, per = lib.densest_spot(roots0[0], 1.0)
    P = G.scalp()["P_cm"]
    brush = __import__("apps.houdini.grooming_masks", fromlist=["x"]).scalp_brush(node)
    normal = brush.N[((P - centre) ** 2).sum(1).argmin()]
    set_view(normal, box_round(centre, 4.0))
    value = round(V006_CROWN / per, 3)
    lid = ga().mask_add(node, "crown", mode="multiply", value=value)       # a fill layer: x value where white
    ga().set_brush(radius_cm=1.0, soft=0.5, erase=False, level=1.0, view="density")
    shots = []

    def painted():
        node.cook()
        r1 = G.roots()
        c1, n1, per1 = lib.densest_spot(r1[0], 1.0)
        ga().set_brush(xray=True)
        shots.append(shot("s4_2_crown_after_scalp_xray"))
        ga().set_brush(xray=False)
        ga().paint_exit(node)
        later(600, lambda: finish(r1, per1))

    def finish(r1, per1):
        shots.append(shot("s4_3_crown_after"))
        st = stroke_stats(len(S["crown_rows"]))
        C.add("dw2_crown_painted_down_to_v006_gui", abs(per1 / V006_CROWN - 1) <= 0.12,
              {"painted": value, "strokes": len(S["crown_rows"]), "densest_1cm_before_per_cm2": round(per, 1),
               "densest_1cm_after_per_cm2": round(per1, 1), "v006_per_cm2": V006_CROWN,
               "same_disc_after_per_cm2": round(lib.disc_density(r1[0], centre, 1.0), 1),
               "strands_before": len(roots0[0]), "strands_after": len(r1[0]),
               "stroke_cook_s": [s.get("cook_s") for s in st], "shots": shots},
              "densest 1 cm disc within 12 % of v006's 5,104 / cm2", evidence=shots[-1])
        S["next"]()

    def go():
        shots.append(shot("s4_0_crown_before"))
        ga().paint_enter(node, lid)
        later(400, lambda: calibrate(paint))

    def paint():
        shots.append(shot("s4_1_crown_before_scalp"))
        S["crown_rows"] = rows_over(centre, normal, 2.0, 0.6)
        strokes(S["crown_rows"], painted)

    later(1500, go)


@step
def s5_thin_skin():
    """dw2: thin skin under floating mesh painted up, by strokes in the viewport."""
    from tools.fx.grooming import config
    node = S["node"]
    G = S["G"]
    s = G.scalp()
    geo = node.node("SCALP_REGIONS").geometry()
    dist = geo.primFloatListAttribValues("owner_dist")
    dens = np.frombuffer(geo.primFloatAttribValuesAsString("density"), np.float32)
    hi = float(node.evalParm("root_far_cm")) * (1 + config.ROOT_FAR_SOFT) / G.unit
    floating = np.array([len(o) == 1 and len(dd) == 1 and dd[0] > hi * 1.2 for o, dd in zip(s["owners"], dist)])
    cen = s["cen_cm"]
    # away from slivers: Helen's scalp has a band of tiny polygons by the ears (half its prims on 1.7 cm2),
    # where a 1 cm brush holds thousands of points and no patch of floating skin is whole
    tiny = cen[s["area"] < 0.001][::10]
    idx = np.nonzero(floating)[0]
    if len(tiny):
        idx = np.array([i for i in idx if ((tiny - cen[i]) ** 2).sum(1).min() > 2.0 ** 2], dtype=int)
    brush = __import__("apps.houdini.grooming_masks", fromlist=["x"]).scalp_brush(node)
    fine = node.node("SCALP_FINE").geometry()

    def seen_square_on(c_cm, n):
        """The camera looking at this skin against its normal sees it first (no other skin in between)."""
        o = hou.Vector3(*((c_cm + n * 15.0) / G.unit))
        pos, nrm, uvw = hou.Vector3(), hou.Vector3(), hou.Vector3()
        if fine.intersect(o, hou.Vector3(*(-n)), pos, nrm, uvw) < 0:
            return False
        return float(np.linalg.norm(np.array(pos) * G.unit - c_cm)) < 0.3

    # the floating skin with the most floating skin within 1.2 cm that the camera can see square on
    ranked = sorted(((int((((cen[idx] - cen[i]) ** 2).sum(1) <= 1.44).sum()), int(i))
                     for i in idx[::max(1, len(idx) // 300)]), reverse=True)
    best = None
    for _k, i in ranked:
        lock = s["owners"][i][0]
        patch = np.array([p for p in idx[((cen[idx] - cen[i]) ** 2).sum(1) <= 1.44] if s["owners"][p] == (lock,)], dtype=int)
        centre = cen[patch].mean(0)
        normal = brush.N[((s["P_cm"] - centre) ** 2).sum(1).argmin()].astype(float)
        if seen_square_on(centre, normal):
            best = i
            break
    if best is None:
        raise RuntimeError("no floating skin the camera sees square on")
    roots0 = G.roots()
    set_view(normal, box_round(centre, 4.0))
    lid = ga().mask_add(node, "thin skin", mode="multiply", value=2.0)     # a fill layer: x 2 where white
    ga().set_brush(radius_cm=0.8, soft=0.3, erase=False, level=1.0, view="density")
    shots = []

    def painted():
        node.cook()
        ga().set_brush(xray=True)
        shots.append(shot("s5_2_thin_after_scalp_xray"))
        ga().set_brush(xray=False)
        lo, hi2 = G.prim_factor(ga().mask_factor(node).astype(float))
        inner = np.array([p for p in G.inner_prims((lo == 2.0) & (hi2 == 2.0), 0.3) if p in set(patch.tolist())], dtype=int)
        asked = float((dens[inner] * s["area"][inner]).sum())
        b, _ = G.roots_on(inner, roots0)
        a, _ = G.roots_on(inner)
        ga().paint_exit(node)
        later(600, lambda: finish(asked, b, a, len(inner)))

    def finish(asked, b, a, n_inner):
        shots.append(shot("s5_3_thin_after"))
        fill = a / max(asked, 1e-9)
        va, aa = lib.mask_arrays(node, lid)
        C.add("dw2_thin_skin_painted_up_gui", 0.8 <= fill <= 1.25 and b / max(asked, 1e-9) < 0.25 and n_inner >= 20,
              {"lock": G.lock_names()[lock], "painted": 2.0, "strokes": len(S["thin_rows"]),
               "points_painted": int((aa > 0).sum()) if aa is not None else 0, "patch_prims": len(patch),
               "skin_fully_painted_prims": n_inner, "roots_asked_by_the_set_density": round(asked, 1),
               "roots_before": b, "roots_after": a, "density_before_over_set": round(b / max(asked, 1e-9), 3),
               "density_after_over_set": round(fill, 3), "shots": shots},
              "floating skin painted 2 fills to the set density (0.8 - 1.25 of it); under 0.25 before",
              evidence=shots[-1])
        S["next"]()

    def go():
        shots.append(shot("s5_0_thin_before"))
        ga().paint_enter(node, lid)
        later(400, lambda: calibrate(paint))

    def paint():
        shots.append(shot("s5_1_thin_before_scalp"))
        S["thin_rows"] = rows_over(centre, normal, 1.1, 0.5, points=10)
        strokes(S["thin_rows"], painted)

    later(1500, go)


@step
def s9_done():
    node = S.get("node")
    if node is not None and not S.get("abort"):
        hip = OUT + "/accept_v02a_gui_painted.hiplc"
        hou.hipFile.save(hip)
        C.meta["painted_hip"] = hip
        C.meta["layers"] = [m.name for m in ga().read_data(node).masks]
        C.meta["state_errors"] = state_mod().STATS["errors"]
    C.write(done=True)
    C.log("DONE")


def run_steps(i=0):
    todo = [s for s in STEPS if not ONLY or s.__name__.split("_")[0] in ONLY or s.__name__ in ("s0_open", "s9_done")]
    if S.get("abort"):
        todo = [s for s in todo if s.__name__ == "s9_done"]
        i = 0 if i < len(STEPS) else i
        if S.get("aborted"):
            return
        S["aborted"] = True

    def nxt():
        run_steps(i + 1)
    if i >= len(todo):
        return
    S["next"] = nxt
    S["step"] = todo[i].__name__
    C.log("STEP", todo[i].__name__)
    try:
        todo[i]()
    except Exception:
        C.add("step_" + todo[i].__name__, False, traceback.format_exc()[-1500:], note="the step raised")
        later(300, nxt)


def wait_main(n=0):
    if hou.qt.mainWindow() is None or not hou.qt.mainWindow().isVisible():
        if n < 120:
            QtCore.QTimer.singleShot(1000, lambda: wait_main(n + 1))
        return
    QtCore.QTimer.singleShot(4000, run_steps)


QtCore.QTimer.singleShot(2000, wait_main)
