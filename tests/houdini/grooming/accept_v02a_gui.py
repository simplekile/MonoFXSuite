"""Acceptance of MONO Grooming v0.2a, rung 7: the mask brush in the viewport (Houdini GUI).

    set ACCEPT_SUITE=<suite>  ACCEPT_SCENE=<scene.hiplc>  ACCEPT_OUT=<out_dir>   [ACCEPT_STEPS=s1,s4]
    houdini.exe -foreground accept_v02a_gui.py

Run it on the SECONDARY monitor only, one GUI Houdini at a time across sessions (the plan's gui.lock), and
kill only the process you started. Strokes are Qt mouse events sent to the viewport widget (the real cursor
stays the user's), pictures are viewport flipbooks (never a screen grab). It writes `accept_gui.json` (same
shape as accept.json), `shots/*.png` and `accept_v02a_gui_painted.hiplc` under the out folder, and ends its
log with DONE. The panel is not part of it (it does not exist yet): Paint is entered through the adapter.

Checks (round 3, one kind of layer "= D strands / cm2"): the brush paints a layer's mask white and black, undo
per stroke and a chain of five, Esc ends Paint with the mouse up and with it held (keeping the stroke), another
node selected ends Paint and a drag then paints nothing, the node selected again keeps Paint, and the plan's
"crown painted down to v006's density, thin skin painted up, in the GUI by scripted strokes" ("= 5104", "= 150").
The painted scene is saved; run grooming-check on it for the QC numbers after painting."""

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


def calibrate(done, tries=0):
    """Global pixel <- viewport screen position, fitted from where three test moves hit the scalp (so no
    guess about toolbars, pixel ratio or the viewport's place in the pane)."""
    st = state_mod().running()
    if st is None or st.session is None:
        # the brush is on its way back (Houdini drops a state entered by name when the node is selected)
        if tries > 40:
            raise RuntimeError("calibration: the brush is not the viewport's tool")
        return later(150, lambda: calibrate(done, tries + 1))
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

def mask_of(node, lid):
    """The layer's stored mask (copy), None when never painted."""
    return lib.mask_arrays(node, lid)[1]


def painted(node, lid) -> int:
    a = mask_of(node, lid)
    return 0 if a is None else int((a > 0).sum())


def same_mask(a, b) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and np.array_equal(a, b))


def clear_layers(node):
    for m in list(ga().read_data(node).masks):
        ga().mask_remove(node, m.id)
    node.cook()


def send_esc(target):
    for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
        app.sendEvent(target, QtGui.QKeyEvent(kind, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier, ""))


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
    S["K"] = lib.Skin(G)
    S["roots0"] = G.roots()
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
def s1_brush():
    """The brush on a "= D" layer: white, the views, one undo step a stroke, black back to the automatic roots."""
    node, G = S["node"], S["G"]
    lid = ga().mask_add(node, "= 120", value=120.0)
    S["lid"] = lid
    ga().set_brush(radius_cm=1.0, soft=0.5, erase=False, view="density", level=1.0)
    shots = [shot("s1_0_before")]
    entered = ga().paint_enter(node, lid)
    st = state_mod().running()
    C.add("gui_paint_enter", bool(entered and st is not None and st.session is not None and node.isSelected()),
          {"state": viewer().currentState(), "paint_layer": ga().paint_layer(node), "locked_hda": bool(node.isLockedHDA()),
           "node_selected": node.isSelected(), "enter_s": round(state_mod().STATS.get("enter_s", -1), 3),
           "errors": state_mod().STATS["errors"][-1:]},
          "the viewport's tool is the brush on the layer, the HDA still locked, the node the selection")
    snap = {}

    def after_white():
        snap["white"] = mask_of(node, lid)
        snap["stroke"] = stroke_stats()[0]
        snap["label"] = hou.undos.undoLabels()[0]
        snap["strands_white"] = G.strands()
        shots.append(shot("s1_1_white_density_view"))
        ga().set_brush(view="layer")
        st2 = state_mod().running()
        cd = np.frombuffer(st2.geo.pointFloatAttribValuesAsString("Cd"), np.float32).reshape(-1, 3)
        a = snap["white"]
        snap["layer_view_white_where_painted"] = bool(a is not None and cd[a >= 0.999].min() > 0.98
                                                      and cd[a <= 0].max() < 0.2)
        shots.append(shot("s1_2_white_layer_view"))
        ga().set_brush(view="density")
        t = time.perf_counter()
        hou.undos.performUndo()
        later(900, lambda: after_undo(time.perf_counter() - t))

    def after_undo(_s):
        snap["undone"] = mask_of(node, lid)
        snap["state_after_undo"] = viewer().currentState()
        hou.undos.performRedo()
        later(900, after_redo)

    def after_redo():
        snap["redone"] = mask_of(node, lid)
        a = snap["white"]
        ok = (a is not None and int((a > 0).sum()) > 20 and float(a.max()) <= 1.0 and snap["label"].endswith("Paint mask")
              and snap["stroke"].get("wrote") and snap["strands_white"] != S["base_strands"]
              and snap["layer_view_white_where_painted"])
        C.add("gui_brush_paints_the_layers_mask_white", ok,
              {"points_painted": 0 if a is None else int((a > 0).sum()), "mask_max": None if a is None else float(a.max()),
               "undo_label": snap["label"], "stroke": snap["stroke"], "strands": [S["base_strands"], snap["strands_white"]],
               "layer_view_white_where_painted": snap["layer_view_white_where_painted"], "shots": shots},
              "a drag in the viewport paints the layer's mask white (over 20 points), one undo step named Paint mask, "
              "the hair follows, the layer view shows the mask white on dark", evidence=shots[-1])
        C.add("gui_undo_redo_a_stroke", snap["undone"] is None and same_mask(snap["redone"], a)
              and snap["state_after_undo"] == state_mod().STATE,
              {"mask_after_undo": "none" if snap["undone"] is None else int((snap["undone"] > 0).sum()),
               "redo_gives_the_stroke_back": same_mask(snap["redone"], a), "state_after_undo": snap["state_after_undo"]},
              "undo removes exactly the stroke (the mask is as before it), redo puts it back byte for byte, Paint stays on")
        ga().set_brush(level=0.0, radius_cm=1.6, soft=0.3)          # black, wider than the white stroke
        drag(line(-170, 0, 170), after_black)

    def after_black():
        a = mask_of(node, lid)
        left = 0.0 if a is None else float(a.max())
        node.cook()
        r1, l1 = G.roots()
        r0, l0 = S["roots0"]
        same = bool(r1.shape == r0.shape and np.array_equal(l1, l0) and float(np.abs(r1 - r0).max()) == 0.0)
        shots.append(shot("s1_3_black_again"))
        C.add("gui_black_paint_returns_the_automatic_roots", left == 0.0 and same,
              {"mask_left_max": left, "roots_at_the_same_places": same, "strands": G.strands(), "automatic": S["base_strands"]},
              "a black stroke of the brush over the white one: the mask is 0 and every root is where the automatic "
              "groom has it", evidence=shots[-1])
        ga().set_brush(level=1.0, radius_cm=1.0, soft=0.5)
        S["next"]()

    def go():
        drag(line(-150, 0, 150), after_white)

    later(500, lambda: calibrate(go))


@step
def s2_undo_chain():
    """Five strokes, five undos, five redos in the viewport: each step is one stroke, Paint stays on."""
    node = S["node"]
    lid = S["lid"]
    if viewer().currentState() != state_mod().STATE:
        ga().paint_enter(node, lid)
    states = [mask_of(node, lid)]
    rows = [-80, -40, 0, 40, 80]
    out = {"undo_s": [], "undo_ok": [], "redo_ok": [], "state_on": []}

    def stroke(i):
        if i >= len(rows):
            return undo(0)
        drag(line(-140, rows[i], 140, n=24), lambda: (states.append(mask_of(node, lid)), stroke(i + 1)))

    def undo(i):
        if i >= len(rows):
            return redo(0)
        t = time.perf_counter()
        hou.undos.performUndo()
        node.cook()
        out["undo_s"].append(round(time.perf_counter() - t, 3))
        later(500, lambda: (out["undo_ok"].append(same_mask(mask_of(node, lid), states[len(rows) - 1 - i])),
                            out["state_on"].append(viewer().currentState() == state_mod().STATE), undo(i + 1)))

    def redo(i):
        if i >= len(rows):
            return finish()
        hou.undos.performRedo()
        later(500, lambda: (out["redo_ok"].append(same_mask(mask_of(node, lid), states[i + 1])), redo(i + 1)))

    def finish():
        out["points_painted_by_stroke"] = [0 if s is None else int((s > 0).sum()) for s in states]
        grew = all(b > a for a, b in zip(out["points_painted_by_stroke"], out["points_painted_by_stroke"][1:]))
        C.add("gui_undo_chain_of_5_strokes", all(out["undo_ok"]) and all(out["redo_ok"]) and all(out["state_on"]) and grew, out,
              "5 strokes, then 5 undos: after each the mask is the one before that stroke, byte for byte, and Paint is "
              "still on; 5 redos put each stroke back", note="seconds are the undo and the display cook in the GUI (not graded: hython grades them)")
        S["next"]()

    later(400, lambda: stroke(0))


@step
def s3_esc():
    """Esc ends Paint: with the mouse up, with the mouse held (keeping the stroke), and from another widget."""
    node = S["node"]
    lid = S["lid"]
    sm = state_mod()
    out = {}

    def up():
        ga().paint_enter(node, lid)
        later(500, up_send)

    def up_send():
        w = S.get("gl") or gl_widget()
        w.setFocus()
        send_esc(w)
        later(700, up_check)

    def up_check():
        out["mouse_up"] = {"state": viewer().currentState(), "paint_layer": ga().paint_layer(node)}
        ga().paint_enter(node, lid)
        later(500, other_widget)

    def other_widget():
        send_esc(hou.qt.mainWindow())                 # the keyboard is elsewhere in Houdini's window
        later(700, other_check)

    def other_check():
        out["sent_to_the_main_window"] = {"state": viewer().currentState(), "paint_layer": ga().paint_layer(node)}
        ok = all(v["state"] != sm.STATE and v["paint_layer"] is None for v in out.values())
        C.add("gui_esc_leaves_paint", ok, dict(out), "Esc sent to the viewport, and to Houdini's main window: Paint is off")
        clear_held()

    # ---- Esc with the left button held
    def clear_held():
        ga().mask_clear(node, lid)
        node.cook()
        ga().paint_enter(node, lid)
        later(600, held_press)

    pts = line(-140, 20, 140, n=30)

    def held_press():
        out["undo_before"] = len(hou.undos.undoLabels())
        _send(QtCore.QEvent.MouseMove, pts[0], QtCore.Qt.NoButton)
        later(100, lambda: (_send(QtCore.QEvent.MouseButtonPress, pts[0], QtCore.Qt.LeftButton), later(30, lambda: held_move(1))))

    def held_move(i):
        if i == 12:                                   # mid stroke: Esc, the button still down
            st = sm.running()
            out["down_at_esc"] = bool(st is not None and st.down)
            send_esc(S.get("gl") or gl_widget())
            return later(250, lambda: held_after_esc(i))
        _send(QtCore.QEvent.MouseMove, pts[i], QtCore.Qt.LeftButton)
        later(20, lambda: held_move(i + 1))

    def held_after_esc(i):
        out["right_after_esc"] = {"paint_layer": ga().paint_layer(node), "points_painted": painted(node, lid),
                                  "state": viewer().currentState()}
        out["mask_at_esc"] = mask_of(node, lid)
        held_more(i)

    def held_more(i):
        if i >= len(pts):
            _send(QtCore.QEvent.MouseButtonRelease, pts[-1], QtCore.Qt.NoButton)
            return later(900, held_check)
        _send(QtCore.QEvent.MouseMove, pts[i], QtCore.Qt.LeftButton)      # the artist keeps dragging
        later(20, lambda: held_more(i + 1))

    def held_check():
        a = mask_of(node, lid)
        row = {"button_down_when_esc_came": out.get("down_at_esc"), "right_after_esc": out["right_after_esc"],
               "kept_what_was_painted": bool(out["mask_at_esc"] is not None and int((out["mask_at_esc"] > 0).sum()) > 5),
               "the_drag_after_esc_painted_nothing": same_mask(a, out["mask_at_esc"]),
               "undo_steps_added": len(hou.undos.undoLabels()) - out["undo_before"],
               "undo_label": hou.undos.undoLabels()[0],
               "after_release": {"state": viewer().currentState(), "paint_layer": ga().paint_layer(node)},
               "esc_seen": sm.STATS.get("esc"), "errors": sm.STATS["errors"][-2:]}
        ok = (row["button_down_when_esc_came"] and row["right_after_esc"]["paint_layer"] is None
              and row["kept_what_was_painted"] and row["the_drag_after_esc_painted_nothing"]
              and row["undo_steps_added"] == 1 and row["undo_label"].endswith("Paint mask")
              and row["after_release"]["state"] != sm.STATE and row["after_release"]["paint_layer"] is None
              and not row["errors"])
        C.add("gui_esc_with_the_mouse_held_leaves_paint_and_keeps_the_stroke", ok, row,
              "Esc while the left button is down: Paint is off at once, what was painted so far is stored (one undo "
              "step), the rest of the drag paints nothing, and after the release the viewport's tool is not the brush")
        S["next"]()

    later(400, up)


@step
def s4_selection():
    """Paint belongs to the painted node: another node selected ends it; the node selected again keeps it."""
    node = S["node"]
    lid = S["lid"]
    sm = state_mod()
    out = {}
    ga().mask_clear(node, lid)
    node.cook()
    ga().paint_enter(node, lid)

    def reselect():
        node.setCurrent(True, clear_all_selected=True)         # the same node again: Houdini drops the state
        later(1200, reselect_stroke)

    def reselect_stroke():
        out["after_reselect"] = {"state": viewer().currentState(), "paint_layer": ga().paint_layer(node),
                                 "came_back": sm.STATS.get("came_back")}
        drag(line(-120, -30, 120, n=24), reselect_check)

    def reselect_check():
        n = painted(node, lid)
        C.add("gui_selecting_the_painted_node_again_keeps_paint", out["after_reselect"]["state"] == sm.STATE and n > 10,
              dict(out["after_reselect"], points_painted=n),
              "the grooming node selected again while painting: the brush is still the tool and the next drag paints")
        other()

    def other():
        null = node.parent().createNode("null", "accept_other_node")
        null.setInput(0, node)
        S["null"] = null
        out["mask_before"] = mask_of(node, lid)
        out["undo_before"] = list(hou.undos.undoLabels()[:1])
        null.setCurrent(True, clear_all_selected=True)         # the artist selects another node
        later(1500, other_drag)

    def other_drag():
        out["after_selecting_another"] = {"state": viewer().currentState(), "paint_layer": ga().paint_layer(node),
                                          "selected": [n.name() for n in hou.selectedNodes()],
                                          "ended_by_selection": sm.STATS.get("ended_by_selection")}
        pts = line(-120, 40, 120, n=24)
        _send(QtCore.QEvent.MouseMove, pts[0], QtCore.Qt.NoButton)

        def press():
            _send(QtCore.QEvent.MouseButtonPress, pts[0], QtCore.Qt.LeftButton)
            later(30, lambda: move(1))

        def move(i):
            if i >= len(pts):
                _send(QtCore.QEvent.MouseButtonRelease, pts[-1], QtCore.Qt.NoButton)
                return later(1200, other_check)
            _send(QtCore.QEvent.MouseMove, pts[i], QtCore.Qt.LeftButton)
            later(20, lambda: move(i + 1))
        later(150, press)

    def other_check():
        a = mask_of(node, lid)
        row = dict(out["after_selecting_another"])
        C.add("gui_selecting_another_node_ends_paint", row["state"] != sm.STATE and row["paint_layer"] is None, row,
              "another node of the network selected while painting: Paint is off and the brush does not come back")
        C.add("gui_a_drag_never_paints_while_another_node_is_selected", same_mask(a, out["mask_before"])
              and viewer().currentState() != sm.STATE,
              {"mask_unchanged": same_mask(a, out["mask_before"]), "state_after_the_drag": viewer().currentState(),
               "paint_layer": ga().paint_layer(node), "refused_strokes": sm.STATS.get("refused_strokes"),
               "errors": sm.STATS["errors"][-2:]},
              "a drag in the viewport with the other node selected: the grooming node's mask is the same, byte for byte")
        S["null"].destroy()
        node.setCurrent(True, clear_all_selected=True)
        later(800, S["next"])

    later(600, reselect)


def _paint_disc(name, centre, normal, half_cm, spacing_cm, value, radius_cm, done, frame_cm=4.0, points=14):
    """A layer "= value" painted white over a disc by rows of strokes in the viewport; done(layer id, shots)."""
    node = S["node"]
    set_view(normal, box_round(centre, frame_cm))
    lid = ga().mask_add(node, name, value=value)
    ga().set_brush(radius_cm=radius_cm, soft=0.3, erase=False, level=1.0, view="density")
    shots = []

    def go():
        shots.append(shot("%s_0_before" % name.split()[0].lower()))
        ga().paint_enter(node, lid)
        later(500, lambda: calibrate(paint))

    def paint():
        S["rows"] = rows_over(centre, normal, half_cm, spacing_cm, points=points)
        strokes(S["rows"], finish)

    def finish():
        node.cook()
        ga().set_brush(xray=True)
        shots.append(shot("%s_1_after_density_view" % name.split()[0].lower()))
        ga().set_brush(xray=False)
        ga().paint_exit(node)
        later(600, lambda: (shots.append(shot("%s_2_after_hair" % name.split()[0].lower())), done(lid, shots)))

    later(1200, go)


@step
def s5_crown():
    """Done-when: the crown painted down to the approved groom's density, by strokes in the viewport."""
    node, G = S["node"], S["G"]
    clear_layers(node)
    roots0 = S["roots0"]
    centre, _n, per = lib.densest_spot(roots0[0], 1.0)
    P = G.scalp()["P_cm"]
    brush = __import__("apps.houdini.grooming_masks", fromlist=["x"]).scalp_brush(node)
    normal = brush.N[((P - centre) ** 2).sum(1).argmin()]

    def done(lid, shots):
        r1 = G.roots()
        same_disc = lib.disc_density(r1[0], centre, 1.0)
        densest = lib.densest_spot(r1[0], 1.0)[2]
        st = stroke_stats(len(S["rows"]))
        C.add("gui_crown_painted_down_to_v006", abs(same_disc / V006_CROWN - 1) <= 0.15 and abs(densest / V006_CROWN - 1) <= 0.15,
              {"layer": "= 5104", "strokes": len(S["rows"]), "densest_1cm_before_per_cm2": round(per, 1),
               "same_disc_after_per_cm2": round(same_disc, 1), "densest_1cm_after_per_cm2": round(densest, 1),
               "v006_per_cm2": V006_CROWN, "strands": [len(roots0[0]), len(r1[0])],
               "stroke_cook_s": [s.get("cook_s") for s in st], "shots": shots},
              "\"= 5104\" painted over the whorl with the brush: the densest 1 cm disc within 15 % of v006's 5,104 / cm2",
              evidence=shots[-1])
        S["next"]()

    _paint_disc("Crown = 5104", centre, normal, 2.0, 0.6, V006_CROWN, 1.0, done)


@step
def s6_thin_skin():
    """Done-when: thin skin under floating mesh painted up, by strokes in the viewport."""
    node, G, K = S["node"], S["G"], S["K"]
    s = G.scalp()
    geo = node.node("SCALP_REGIONS").geometry()
    dist = geo.primFloatListAttribValues("owner_dist")
    hi = float(node.evalParm("root_far_cm")) * 1.5 / G.unit
    floating = np.array([len(o) == 1 and len(dd) == 1 and dd[0] > hi * 1.2 for o, dd in zip(s["owners"], dist)])
    cen = s["cen_cm"]
    tiny = cen[s["area"] < 0.001][::10]
    idx = np.nonzero(floating)[0]
    if len(tiny):
        idx = np.array([i for i in idx if ((tiny - cen[i]) ** 2).sum(1).min() > 2.0 ** 2], dtype=int)
    brush = __import__("apps.houdini.grooming_masks", fromlist=["x"]).scalp_brush(node)
    fine = node.node("SCALP_FINE").geometry()

    def seen_square_on(c_cm, n):
        o = hou.Vector3(*((c_cm + n * 15.0) / G.unit))
        pos, nrm, uvw = hou.Vector3(), hou.Vector3(), hou.Vector3()
        if fine.intersect(o, hou.Vector3(*(-n)), pos, nrm, uvw) < 0:
            return False
        return float(np.linalg.norm(np.array(pos) * G.unit - c_cm)) < 0.3

    ranked = sorted(((int((((cen[idx] - cen[i]) ** 2).sum(1) <= 1.44).sum()), int(i))
                     for i in idx[::max(1, len(idx) // 300)]), reverse=True)
    centre = normal = None
    for _k, i in ranked:
        lock = s["owners"][i][0]
        patch = np.array([p for p in idx[((cen[idx] - cen[i]) ** 2).sum(1) <= 1.44] if s["owners"][p] == (lock,)], dtype=int)
        c = cen[patch].mean(0)
        n = brush.N[((s["P_cm"] - c) ** 2).sum(1).argmin()].astype(float)
        if seen_square_on(c, n):
            centre, normal = c, n
            break
    if centre is None:
        raise RuntimeError("no floating skin the camera sees square on")
    roots0 = S["roots0"]

    def done(lid, shots):
        mask = ga().mask_values(node, lid)
        core = K.core(mask, 1.0, margin=0.3)
        area = float(K.area[core].sum())
        before = sum(K.roots_in(core, roots0)[0].values()) / max(area, 1e-9)
        after = sum(K.roots_in(core, G.roots())[0].values()) / max(area, 1e-9)
        lim = lib.density_limit(150.0, area)
        C.add("gui_thin_skin_painted_up", area > 0.5 and abs(after / 150.0 - 1) <= lim and before < 0.5 * 150.0,
              {"layer": "= 150", "lock": G.lock_names()[lock], "strokes": len(S["rows"]), "fully_painted_core_cm2": round(area, 2),
               "per_cm2_before": round(before, 1), "per_cm2_after": round(after, 1), "limit": round(lim, 3), "shots": shots},
              "\"= 150\" painted on skin under floating mesh with the brush: 150 / cm2 within max(0.15, 2 / sqrt(N)) "
              "where it was under half of that", evidence=shots[-1])
        S["next"]()

    _paint_disc("Thin = 150", centre, normal, 1.3, 0.5, 150.0, 0.8, done, points=10)


@step
def s9_done():
    node = S.get("node")
    if node is not None and not S.get("abort"):
        hip = OUT + "/accept_v02a_gui_painted.hiplc"
        hou.hipFile.save(hip)
        C.meta["painted_hip"] = hip
        C.meta["layers"] = [m.name for m in ga().read_data(node).masks]
        C.meta["state_errors"] = state_mod().STATS["errors"]
        C.meta["state_stats"] = {k: v for k, v in state_mod().STATS.items() if k not in ("strokes", "errors")}
        nodes = [n.path() for n in ga().find_nodes()]
        C.add("gui_paint_leaves_no_node_behind", nodes == [node.path()], nodes,
              "after every Paint on / off of this run the scene holds the one MONO Grooming node it had (leaving "
              "Paint by entering the node's state by name made a new node)")
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
