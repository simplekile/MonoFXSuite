"""Acceptance of MONO Grooming v0.2b B3: the Edit points / Draw lock viewer state in GUI Houdini, by scripted events.

    set ACCEPT_SUITE=<suite>  ACCEPT_SCENE=<Helen scene.hiplc>  ACCEPT_OUT=<out_dir>   [ACCEPT_STEPS=k2a,g1b]
    houdini.exe -foreground accept_v02b_gui.py

Run it on the SECONDARY monitor only, one GUI Houdini at a time across sessions (gui.lock), on its own
HOUDINI_USER_PREF_DIR, and kill only the process you started. Mouse events are Qt events sent to the viewport widget
(the real cursor stays the user's), keys are POSTED to it (a sent key skips Houdini's shortcuts), pictures are
viewport flipbooks. Every tool is entered through `grooming_points_state` (the panel's interface) and, after each
entry, one click on empty viewport comes first (the first press after entering a state goes to the pane: t76).
It writes `accept_gui.json` (as accept.json: {item, pass, value, limit, evidence}), `shots/*.png`, and ends its log
with DONE.

The "Done when" lines it owns (docs/plans/grooming_v0_2.md v0.2b; `not_here` in accept_v02b.py): g1b (a dragged root
on the skin at every event of the drag), k1 (Control points and Paint: entering one ends the other; Esc, another node
selected, the node deleted and File > New leave the tool with no traceback), k2 (a fringe lock moved, one rotated
about its root, one redrawn, one drawn on bare skin, flipbooks before and after each); and the gestures the spike
left open: several locks in one drag, a control-point edit on a drawn lock, the handle keys, a click on hair. For
each gesture: one undo step with its name, undo back to the data before in under 0.1 s with no lock regrown, redo,
the handles the node got equal to what the viewport showed at release, the recook within 0.2 s a lock + 0.1 s.
Definitions: "a root on the skin" = its distance to IN_SCALP's surface (nearestPrim), cm."""

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

# limits: the plan's "Done when" lines, never tuned to a result
ROOT_SKIN_CM = 0.001
UNDO_S = 0.1
LOCK_S, PLUS_S = 0.2, 0.1
REDRAW_CM = 0.25
SAME_CM = 0.01          # the handles the node got against the ones the viewport showed at release
FRINGE, BACK, BASE = "hair_bang_11", "hair_back_20", "hair_base_20"
FIVE = ("hair_bang_01", "hair_bang_02", "hair_bang_03", "hair_bang_04", "hair_bang_05")
SPOT = (0.02807, 1.51098, 0.00315)      # bare skin 4.8 cm from the nearest root (spike t76 q5)
SPOT_N = (0.973, 0.21, -0.099)

app = QtWidgets.QApplication.instance()
SECOND = next((s for s in app.screens() if s is not app.primaryScreen()), None)
C = lib.Checks(OUT, "accept_gui.json", {"suite": SUITE, "scene": SCENE, "part": "v0.2b B3",
                                        "houdini": hou.applicationVersionString(),
                                        "pref_dir": os.environ.get("HOUDINI_USER_PREF_DIR"),
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


def pump(n=6):
    for _ in range(n):
        app.processEvents()


def viewer():
    return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)


def gl_widget():
    c = viewer().qtScreenGeometry().center()
    mw = hou.qt.mainWindow()
    w = app.widgetAt(c)
    return w if w is not None and w.window() is mw else mw.childAt(mw.mapFromGlobal(c))


def send_mouse(kind, gp, button, buttons, mods=QtCore.Qt.NoModifier):
    w = S["gl"]
    gp = QtCore.QPoint(int(round(gp[0])), int(round(gp[1])))
    app.sendEvent(w, QtGui.QMouseEvent(kind, QtCore.QPointF(w.mapFromGlobal(gp)), QtCore.QPointF(gp), button, buttons,
                                       mods))


def post_key(key, text, release=False):
    kind = QtCore.QEvent.KeyRelease if release else QtCore.QEvent.KeyPress
    app.postEvent(S["gl"], QtGui.QKeyEvent(kind, key, QtCore.Qt.NoModifier, text))


def shot(name):
    sv = viewer()
    s = sv.flipbookSettings().stash()
    f = int(hou.frame())
    s.frameRange((f, f))
    s.output(f"{SHOTS}/{name}.$F4.png")
    s.outputToMPlay(False)
    s.useResolution(True)
    s.resolution((1280, 960))
    sv.flipbook(sv.curViewport(), s)
    src = f"{SHOTS}/{name}.{f:04d}.png"
    if os.path.isfile(src):
        os.replace(src, f"{SHOTS}/{name}.png")
    return f"shots/{name}.png"


def set_view(normal, bbox):
    n = hou.Vector3(*(float(x) for x in normal)).normalized()
    ry = float(np.degrees(np.arctan2(n[0], n[2])))
    rx = -float(np.degrees(np.arcsin(max(-1.0, min(1.0, n[1])))))
    vp = viewer().curViewport()
    vp.changeType(hou.geometryViewportType.Perspective)
    vp.defaultCamera().setRotation(hou.hmath.buildRotate(rx, ry, 0).extractRotationMatrix3())
    vp.frameBoundingBox(bbox)


def spines(name="SPINES"):
    return S["ga"]._spine_rows(S["ga"]._cooked(S["node"], name))


def look_at(lids):
    sp = spines()
    P = np.concatenate([sp[i]["P"] for i in lids])
    box = hou.BoundingBox(*(P.min(0) - 0.02), *(P.max(0) + 0.02))
    g = S["node"].node("IN_SCALP").geometry()
    pr = g.nearestPrim(hou.Vector3(*sp[lids[0]]["P"][0]))[0]
    n = np.array(pr.normal())
    m = np.cross(sp[lids[0]]["tangent"][len(sp[lids[0]]["P"]) // 2], sp[lids[0]]["axis"][len(sp[lids[0]]["P"]) // 2])
    m = m / max(np.linalg.norm(m), 1e-12)
    if np.dot(m, n) < 0:
        m = -m
    set_view(m * 0.8 + n * 0.2, box)


def frame_on(lids):
    S["ga"].set_isolate(S["node"], lids)
    S["node"].cook()
    look_at(lids)


def drag(points, step_ms, done, mods=QtCore.Qt.NoModifier, settle_ms=1500):
    pts = list(points)
    info = {}

    def press():
        info["t_press"] = time.perf_counter()
        send_mouse(QtCore.QEvent.MouseButtonPress, pts[0], QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, mods)
        later(step_ms, lambda: move(1))

    def move(i):
        if i >= len(pts):
            return later(80, release)
        send_mouse(QtCore.QEvent.MouseMove, pts[i], QtCore.Qt.NoButton, QtCore.Qt.LeftButton, mods)
        later(step_ms, lambda: move(i + 1))

    def release():
        info["t_release"] = time.perf_counter()
        send_mouse(QtCore.QEvent.MouseButtonRelease, pts[-1], QtCore.Qt.LeftButton, QtCore.Qt.NoButton, mods)
        later(settle_ms, lambda: done(info))

    send_mouse(QtCore.QEvent.MouseMove, pts[0], QtCore.Qt.NoButton, QtCore.Qt.NoButton, mods)
    later(200, press)


def click(gp, done, mods=QtCore.Qt.NoModifier, settle_ms=800):
    drag([gp, gp], 40, done, mods, settle_ms)


def path(a, dx, dy, n=20):
    return [(a[0] + dx * i / n, a[1] + dy * i / n) for i in range(n + 1)]


def calibrate(done):
    """Global pixels -> the viewport's own pixel coordinates (what a state's device reports): three moves."""
    # the viewport widget is found once, before any state: with the state's HUD up, the widget under the
    # viewport's centre is the HUD's, and events sent there reached the state in another frame (t81 r5)
    if S.get("gl") is None:
        S["gl"] = gl_widget()
    c = viewer().qtScreenGeometry().center()
    g = [(c.x(), c.y()), (c.x() + 120, c.y()), (c.x(), c.y() + 120)]
    got = []

    def go(i):
        if i:
            got.append(S["gps"].LIVE.get("last_mouse"))
        if i >= 3:
            if None in got:
                raise RuntimeError(f"calibration got no mouse event in the state: {got}")
            S["cal"] = {"g0": g[0], "m0": got[0], "sx": (got[1][0] - got[0][0]) / 120.0,
                        "sy": (got[2][1] - got[0][1]) / 120.0}
            C.log("calibrate", S["cal"])
            return done()
        send_mouse(QtCore.QEvent.MouseMove, g[i], QtCore.Qt.NoButton, QtCore.Qt.NoButton)
        later(150, lambda: go(i + 1))
    go(0)


def to_global(world):
    """Where a point (the node's space) is on screen, global px: the viewport's pixels have y up from the GL
    widget's bottom (t81 r1: a state's mouse x = the widget's x, y = its height - y). Read live, so a state bar
    or HUD that changes the viewport is followed; moves read back from the state lagged after a flipbook (r5)."""
    vp = viewer().curViewport()
    s = vp.mapToScreen(hou.Vector3(*map(float, world)) * S["node"].parent().worldTransform())
    w = S["gl"]
    dpr = w.devicePixelRatioF()
    g = w.mapToGlobal(QtCore.QPoint(int(round(s[0] / dpr)), int(round(w.height() - s[1] / dpr))))
    return (float(g.x()), float(g.y()))


def first_click(done):
    """Once after entering a tool: a click on empty viewport (its first press goes to the pane)."""
    def go():
        c = viewer().qtScreenGeometry()
        p = (c.left() + 40, c.top() + 90)
        click(p, lambda _i: done())
    calibrate(go)


def to_skin_cm(p):
    g = S["node"].node("IN_SCALP").geometry()
    pr, u, v, _ = g.nearestPrim(hou.Vector3(*map(float, p)))
    return (hou.Vector3(*map(float, p)) - pr.positionAtInterior(u, v)).length() * S["unit"]


def data_now():
    return S["node"].evalParm("groom_data")


def handles(lid):
    return S["ga"].lock_handles(S["node"], [lid])[lid]


def recooked():
    geo = S["node"].node("to_cook").geometry()
    return sorted(geo.primIntAttribValues("lock_id")) if geo.findPrimAttrib("lock_id") else []


def restore():
    """Back to the fresh groom, undo off (each gesture starts from it)."""
    with hou.undos.disabler():
        S["node"].parm("groom_data").set(S["D0"])
        S["node"].parm("regions").set(S["REG0"])
    S["node"].cook()


def undo_redo(before, after):
    """One undo: the data before, how long with the display's cook, the locks regrown; one redo: the data after."""
    node = S["node"]
    t = time.perf_counter()
    hou.undos.performUndo()
    node.cook()
    u = {"s": round(time.perf_counter() - t, 4), "data_is_before": data_now() == before, "regrown": recooked()}
    t = time.perf_counter()
    hou.undos.performRedo()
    node.cook()
    r = {"s": round(time.perf_counter() - t, 4), "data_is_after": data_now() == after, "regrown": recooked()}
    ok = u["data_is_before"] and u["s"] < UNDO_S and not u["regrown"] and r["data_is_after"]
    return ok, {"undo": u, "redo": r}


def last_drag():
    return dict(S["gps"].STATS["drags"][-1]) if S["gps"].STATS["drags"] else None


def gesture(tag, lid_names, start_of, offsets, then, mods=QtCore.Qt.NoModifier, keys=(), enter=True,
            tool="points", check=None, step_ms=30, arm="", hold=False):
    """Enter the tool on these locks, picture before, drag from `start_of()` (a global px) along `offsets`
    (px from the start), picture after, then the shared checks and `check(rec)` for the gesture's own."""
    gps, ga, node = S["gps"], S["ga"], S["node"]
    lids = [S["ID"][n] for n in lid_names]
    rec = {"locks": list(lid_names)}

    def entered():
        S["before_data"] = data_now()
        S["before_handles"] = {i: np.array(handles(i)["points"]) for i in lids}
        S["before_spine"] = {i: spines()[i]["P"].copy() for i in lids} if lids else {}
        rec["shot_before"] = shot(tag + "_before")
        S["labels0"] = len(hou.undos.undoLabels())
        S["drags0"] = len(gps.STATS["drags"]) + len(gps.STATS["draws"])
        # a flipbook leaves the viewport drawn at its resolution until the next redraw (t81 r4 / r7: presses
        # 30 px off the handle): redraw, then read where things are
        viewer().curViewport().draw()
        pump()
        later(600, press)

    def press():
        for k, t in keys:              # R / E arm the next drag: held through it, or tapped before it
            post_key(k, t)
            if not hold:
                post_key(k, t, release=True)
        pump()
        S["state_after_keys"] = viewer().currentState()
        pop = app.activePopupWidget()
        S["popup_after_keys"] = (type(pop).__name__ + " " + pop.objectName()) if pop is not None else None
        grab = QtWidgets.QWidget.mouseGrabber()
        S["grabber_after_keys"] = type(grab).__name__ if grab is not None else None
        S["menu_actions"] = list(gps.STATS.get("menu", []))[-4:]
        if arm:
            S["pk"].update(held=arm)
        S["held_after_keys"] = S["pk"].STATE.held
        viewer().curViewport().draw()
        pump()
        a = start_of()
        S["press_global"] = a
        S["events_at_press"] = gps.STATS["events"]
        S["press_viewport"] = tuple(viewer().curViewport().size())
        pts = [(a[0] + dx, a[1] + dy) for dx, dy in offsets]
        later(150, lambda: drag(pts, step_ms, done, mods))

    def done(_info):
        rec["held_after_drag"] = S["pk"].STATE.held
        rec["key_held_through_drag"] = bool(hold and keys)
        if hold:
            for k, t in keys:
                post_key(k, t, release=True)
            pump()
        labels = hou.undos.undoLabels()
        rec["undo_steps"] = len(labels) - S["labels0"]
        rec["undo_label"] = labels[0] if labels else ""
        got = (gps.STATS["draws"] if tool == "draw" else gps.STATS["drags"])
        if len(gps.STATS["drags"]) + len(gps.STATS["draws"]) == S["drags0"]:
            C.add(tag, False, {"failed": "no gesture reached the state", "last_mouse": gps.LIVE.get("last_mouse"),
                               "state_after_keys": S.get("state_after_keys"), "held": S.get("held_after_keys"),
                               "popup": S.get("popup_after_keys"), "grabber": S.get("grabber_after_keys"),
                               "menu_actions": S.get("menu_actions"), "events": gps.STATS["events"],
                               "events_at_press": S.get("events_at_press"), "press_global": S.get("press_global"),
                               "gl_visible": S["gl"].isVisible(), "pick": gps.STATS.get("pick"),
                               "state_now": viewer().currentState(), "ended": gps.STATS["ended"][-3:],
                               "tool": gps.current_tool(), "mouse_log": gps.STATS.get("mouse_log", [])[-30:],
                               "errors": gps.STATS["errors"][-2:], "keys": gps.STATS["keys"][-6:]})
            return then()
        d = dict(got[-1])
        rec["gesture"] = {k: d.get(k) for k in ("kind", "mode", "events", "moved", "handler_ms_median",
                                                 "handler_ms_max", "write_s", "cook_s", "recooked", "held", "angle",
                                                 "factor", "length_cm")}
        rec["result"] = d.get("result")
        rec["state_load"] = gps.STATS.get("load")
        rec["state_pick"] = gps.STATS.get("pick")
        rec["press_global"] = S.get("press_global")
        rec["press_viewport"] = S.get("press_viewport")
        rec["shot_after"] = shot(tag + "_after")
        after = data_now()
        if d.get("write_s") is not None:
            n = len(d.get("recooked") or [])
            rec["recook_s"] = round(d["write_s"] + d["cook_s"], 3)
            rec["recook_limit_s"] = round(LOCK_S * max(n, 1) + PLUS_S, 2)
        ok = True
        if check is not None:
            ok = bool(check(rec, d, lids))
        ok_undo, rec["undo_redo"] = undo_redo(S["before_data"], after)
        rec["errors"] = gps.STATS["errors"][-2:]
        ok = ok and ok_undo and rec["undo_steps"] == 1 and not rec["errors"]
        if "recook_s" in rec:
            ok = ok and rec["recook_s"] <= rec["recook_limit_s"]
        C.add(tag, ok, rec, {"undo_s": UNDO_S, "undo_steps": 1, "recook": "0.2 s a lock + 0.1 s"})
        then()

    def go():
        if enter:
            if tool == "draw":
                gps.enter_draw(node)
            else:
                gps.enter_points(node, lids)
            later(1000, lambda: first_click(entered))
        else:
            later(300, entered)
    go()


def handles_match(rec, lid, want):
    got = np.array(handles(lid)["points"])
    if got.shape != np.asarray(want).shape:
        rec.setdefault("handles_cm", {})[S["NAMES"][lid]] = "count differs"
        return False
    worst = float(np.linalg.norm(got - want, axis=1).max()) * S["unit"]
    rec.setdefault("handles_cm", {})[S["NAMES"][lid]] = round(worst, 5)
    return worst <= SAME_CM


# ------------------------------------------------------------------------------------------------- steps
@step
def s0_open():
    mw = hou.qt.mainWindow()
    if SECOND is None:
        C.add("secondary_monitor", False, [s.name() for s in app.screens()])
        S["abort"] = True
        return S["next"]()
    mw.setGeometry(SECOND.availableGeometry())
    pump()
    C.meta["window_screen"] = mw.screen().name()
    ga, node = lib.open_scene(SUITE, SCENE)
    lib.fresh(ga, node)
    from apps.houdini import grooming_points_state as gps
    from apps.houdini import grooming_paint_state as ps
    from tools.fx.grooming import logic, points_keys as pk
    S.update(ga=ga, node=node, gps=gps, ps=ps, pk=pk, logic=logic, unit=float(node.evalParm("unit_cm")))
    for o in hou.node("/obj").children():
        o.setDisplayFlag(o == node.parent())
    viewer().setPwd(node.parent())
    pump()
    S["gl"] = gl_widget()
    C.meta["gl_widget"] = type(S["gl"]).__name__
    t = time.perf_counter()
    node.cook(force=True)
    C.meta["cold_cook_s"] = round(time.perf_counter() - t, 2)
    S["NAMES"] = {lk.id: lk.name for lk in ga.read_data(node).locks}
    S["ID"] = {v: k for k, v in S["NAMES"].items()}
    S["D0"] = data_now()
    S["REG0"] = hou.Geometry(node.parm("regions").evalAsGeometry())
    S["G"] = lib.Groom(ga, node)
    C.meta.update(library=node.type().definition().libraryFilePath(), locks=len(S["NAMES"]))
    later(1500, S["next"])


@step
def k2a_move_fringe():
    lid = S["ID"][FRINGE]
    S["ga"].set_isolate(S["node"], [lid])
    S["node"].cook()
    look_at([lid])

    def start():
        return to_global(S["gps"].running().locks[lid]["world"][-1])

    def check(rec, d, lids):
        rec["shot_handles"] = shot("k2a_handles_on")
        k = len(S["before_handles"][lid]) - 1
        moved = float(np.linalg.norm(np.array(handles(lid)["points"])[k] - S["before_handles"][lid][k])) * S["unit"]
        rec["tip_handle_moved_cm"] = round(moved, 3)
        rec["recooked_only_it"] = d.get("recooked") == [lid]
        return moved > 0.5 and rec["recooked_only_it"] and rec["undo_label"] == "MONO Grooming: Move control points"
    gesture("k2a_move_fringe_tip", [FRINGE], start, [(90 * i / 20, 0) for i in range(21)], S["next"], check=check)


@step
def g1b_root_drag():
    restore()
    lid = S["ID"][FRINGE]
    frame_on([lid])          # each step frames its own lock: run alone, the view was the default (t81 r15)

    def start():
        return to_global(S["gps"].running().locks[lid]["world"][0])

    def check(rec, d, lids):
        roots = d.get("roots") or []
        dist = [to_skin_cm(r[lid]) for r in roots if lid in r]
        sp = spines()[lid]["P"]
        rec["events_with_root"] = len(dist)
        rec["root_to_skin_cm_max_during"] = float("%.3g" % max(dist)) if dist else None
        rec["root_moved_cm"] = round(float(np.linalg.norm(sp[0] - S["before_spine"][lid][0])) * S["unit"], 3)
        rec["root_to_skin_cm_after_cook"] = float("%.3g" % to_skin_cm(sp[0]))
        rec["missed_skin_events"] = d.get("missed_skin", 0)
        data = S["ga"].read_data(S["node"])
        rec["regions_out_of_date"] = [bool(data.regions_stale), list(data.stale_why)]
        return (len(dist) >= 10 and max(dist) <= ROOT_SKIN_CM and rec["root_to_skin_cm_after_cook"] <= ROOT_SKIN_CM
                and rec["root_moved_cm"] > 0.3 and data.regions_stale)
    gesture("g1b_root_on_skin_at_every_event_of_the_drag", [FRINGE], start,
            [(45 * i / 20, 25 * i / 20) for i in range(21)], S["next"], check=check)


@step
def k2b_rotate():
    restore()
    lid = S["ID"][FRINGE]
    frame_on([lid])          # each step frames its own lock: run alone, the view was the default (t81 r15)

    def start():
        return to_global(S["gps"].running().locks[lid]["world"][-1])

    def check(rec, d, lids):
        ang, axis = d.get("angle"), d.get("axis")
        want = S["logic"].rotate_about_root(S["before_handles"][lid], axis, ang)
        rec["angle_deg"] = round(float(ang), 2)
        ok = handles_match(rec, lid, want)
        rec["root_moved_cm"] = round(float(np.linalg.norm(np.array(handles(lid)["points"])[0]
                                                          - S["before_handles"][lid][0])) * S["unit"], 5)
        return (ok and abs(ang) > 5 and rec["root_moved_cm"] < 1e-3 and rec["undo_label"] == "MONO Grooming: Rotate lock"
                and rec.get("held_after_drag") == "")
    gesture("k2b_rotate_about_root", [FRINGE], start, [(-160 * i / 20, 70 * i / 20) for i in range(21)],
            S["next"], keys=[(QtCore.Qt.Key_R, "r")], check=check, hold=True)


@step
def k2c_scale():
    restore()
    lid = S["ID"][FRINGE]
    frame_on([lid])          # each step frames its own lock: run alone, the view was the default (t81 r15)

    def start():
        return to_global(S["gps"].running().locks[lid]["world"][-1])

    def check(rec, d, lids):
        f = d.get("factor")
        want = S["logic"].scale_about_root(S["before_handles"][lid], f)
        rec["factor"] = round(float(f), 4)
        ok = handles_match(rec, lid, want)
        L0 = float(S["logic"].arc_lengths(S["before_spine"][lid])[-1])
        L1 = float(S["logic"].arc_lengths(spines()[lid]["P"])[-1])
        rec["spine_length_ratio"] = round(L1 / L0, 4)
        return (ok and f > 1.1 and abs(L1 / L0 - f) / f < 0.05 and rec["undo_label"] == "MONO Grooming: Scale lock"
                and rec.get("held_after_drag") == "")
    by_key = os.environ.get("ACCEPT_SCALE_ARM", "key") == "key"
    gesture("k2c_scale_about_root", [FRINGE], start, [(100 * i / 20, 0) for i in range(21)], S["next"],
            keys=[(QtCore.Qt.Key_E, "e")] if by_key else (), arm="" if by_key else "scale", check=check)


def _poly_dist(points, line):
    """Each point's distance to a polyline (arrays, scene units)."""
    a, b = line[:-1], line[1:]
    ab = b - a
    out = []
    for p in points:
        t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-18), 0, 1)
        out.append(float(np.min(np.linalg.norm(a + ab * t[:, None] - p, axis=1))))
    return np.array(out)


@step
def k2d_redraw():
    restore()
    lid = S["ID"][FRINGE]
    frame_on([lid])          # each step frames its own lock: run alone, the view was the default (t81 r15)

    def start():
        return to_global(S["gps"].running().locks[lid]["world"][0])

    # from the root handle (the root stays), a bow out to the side and down
    offs = [(40 * np.sin(np.pi * i / 24) + 20 * i / 24, 160 * i / 24) for i in range(25)]

    def check(rec, d, lids):
        stroke = np.array(d.get("stroke") or [])
        sp = spines()[lid]["P"]
        res = d.get("result") or {}
        rec["stroke_points"] = len(stroke)
        rec["handles"] = res.get("count")
        rec["gap_cm_adapter"] = res.get("gap_cm")
        if len(stroke) < 2:
            return False
        s_to_sp = _poly_dist(stroke, sp) * S["unit"]
        sp_to_s = _poly_dist(sp, stroke) * S["unit"]
        rec["stroke_to_spine_cm_max"] = round(float(s_to_sp.max()), 4)
        rec["spine_to_stroke_cm_max"] = round(float(sp_to_s.max()), 4)
        rec["root_moved_cm"] = round(float(np.linalg.norm(sp[0] - S["before_spine"][lid][0])) * S["unit"], 5)
        return (max(rec["stroke_to_spine_cm_max"], rec["spine_to_stroke_cm_max"]) <= REDRAW_CM
                and rec["undo_label"] == "MONO Grooming: Redraw lock")
    gesture("k2d_redraw_from_a_stroke", [FRINGE], start, offs, S["next"], mods=QtCore.Qt.ShiftModifier, check=check)


@step
def k2e_five_locks():
    restore()
    lids = [S["ID"][n] for n in FIVE]
    S["ga"].set_isolate(S["node"], lids)
    S["node"].cook()
    look_at(lids)

    def start():
        return to_global(S["gps"].running().locks[lids[0]]["world"][-1])

    def check(rec, d, _lids):
        rec["shot_handles"] = shot("k2e_five_handles")
        moves = []
        for i in lids:
            got = np.array(handles(i)["points"])
            moves.append(got[-1] - S["before_handles"][i][-1])
        moves = np.array(moves)
        spread = float(np.linalg.norm(moves - moves[0], axis=1).max()) * S["unit"]
        rec["tip_moves_cm"] = [round(float(np.linalg.norm(m)) * S["unit"], 3) for m in moves]
        rec["tip_move_spread_cm"] = round(spread, 5)
        rec["locks_written"] = sorted((d.get("result") or {}).get("locks", []))
        return (spread <= SAME_CM and min(rec["tip_moves_cm"]) > 0.5 and rec["locks_written"] == sorted(lids)
                and sorted(d.get("recooked") or []) == sorted(lids))
    gesture("k2e_several_locks_one_drag", list(FIVE), start, [(70 * i / 20, 0) for i in range(21)], S["next"],
            check=check)


@step
def k2f_heavy():
    """The lock with the most strands and the longest lock: one mid-handle drag each, timed."""
    todo = [BASE, BACK]

    def go(i):
        if i >= len(todo):
            return S["next"]()
        restore()
        lid = S["ID"][todo[i]]
        S["ga"].set_isolate(S["node"], [lid])
        S["node"].cook()
        look_at([lid])

        def start():
            w = S["gps"].running().locks[lid]["world"]
            return to_global(w[len(w) // 2])

        def check(rec, d, lids):
            rec["recooked_only_it"] = d.get("recooked") == [lid]
            return rec["recooked_only_it"]
        gesture(f"k2f_drag_{todo[i]}", [todo[i]], start, [(60 * j / 20, 0) for j in range(21)], lambda: go(i + 1),
                check=check)
    go(0)


@step
def k2g_handle_keys():
    restore()
    lid = S["ID"][FRINGE]
    gps, node = S["gps"], S["node"]
    S["ga"].set_isolate(node, [lid])
    node.cook()
    look_at([lid])
    gps.enter_points(node, [lid])
    rec = {}

    def go():
        rec["count_before"] = handles(lid)["count"]
        before = data_now()
        n0 = len(hou.undos.undoLabels())
        post_key(QtCore.Qt.Key_Plus, "+")
        post_key(QtCore.Qt.Key_Plus, "+", release=True)
        later(1500, lambda: more(before, n0))

    def more(before, n0):
        rec["count_after_plus"] = handles(lid)["count"]
        labels = hou.undos.undoLabels()
        rec["undo_steps_plus"] = len(labels) - n0
        rec["undo_label"] = labels[0] if labels else ""
        rec["keys_seen"] = gps.STATS["keys"][-4:]
        rec["key_step"] = gps.STATS.get("key_step")
        rec["handles_step"] = gps.STATS.get("handles_step")
        rec["message"] = S["pk"].STATE.message
        rec["last_drag"] = {k: v for k, v in (last_drag() or {}).items() if k in ("kind", "result", "to", "step")}
        rec["shot"] = shot("k2g_plus_one_handle")
        ok_u, rec["undo_redo"] = undo_redo(before, data_now())
        rec["undo_ok"] = ok_u
        n1 = len(hou.undos.undoLabels())
        post_key(QtCore.Qt.Key_Minus, "-")
        post_key(QtCore.Qt.Key_Minus, "-", release=True)
        later(1500, lambda: less(n1))

    def less(n1):
        rec["count_after_minus"] = handles(lid)["count"]
        rec["undo_steps_minus"] = len(hou.undos.undoLabels()) - n1
        rec["errors"] = gps.STATS["errors"][-2:]
        ok = (rec["count_after_plus"] == rec["count_before"] + 1 and rec["count_after_minus"] == rec["count_before"]
              and rec["undo_steps_plus"] == 1 and rec["undo_steps_minus"] == 1 and rec["undo_ok"]
              and rec["undo_label"] == "MONO Grooming: Set handle count" and not rec["errors"])
        C.add("k2g_handle_count_minus_plus", ok, rec, "+1 then -1, one undo step each")
        S["next"]()
    later(1000, lambda: first_click(go))


@step
def k2h_click_selects():
    restore()
    gps, node, ga = S["gps"], S["node"], S["ga"]
    a, b = S["ID"]["hair_bang_11"], S["ID"]["hair_bang_14"]
    ga.set_isolate(node, None)
    node.cook()
    look_at([a, b])
    gps.enter_points(node, [a])
    rec = {}

    def go():
        sp = spines()[b]["P"]
        click(to_global(sp[len(sp) // 3]), after_plain)

    def after_plain(_i):
        rec["after_click"] = [S["NAMES"].get(i) for i in S["pk"].STATE.lock_ids]
        rec["handles_follow"] = sorted(gps.running().order) == sorted(S["pk"].STATE.lock_ids) if gps.running() else False
        sp = spines()[a]["P"]
        click(to_global(sp[len(sp) // 3]), after_shift, mods=QtCore.Qt.ShiftModifier)

    def after_shift(_i):
        rec["after_shift_click"] = [S["NAMES"].get(i) for i in S["pk"].STATE.lock_ids]
        c = viewer().qtScreenGeometry()
        click((c.left() + 40, c.top() + 90), after_empty)

    def after_empty(_i):
        rec["after_empty_click"] = [S["NAMES"].get(i) for i in S["pk"].STATE.lock_ids]
        rec["clicks"] = gps.STATS["clicks"][-4:]
        rec["mouse_log"] = gps.STATS.get("mouse_log", [])[-40:]
        rec["ids"] = {n: S["ID"][n] for n in ("hair_bang_11", "hair_bang_14")}
        rec["shot"] = shot("k2h_two_selected")
        rec["errors"] = gps.STATS["errors"][-2:]
        ok = (rec["after_click"] == ["hair_bang_14"] and rec["after_shift_click"] == ["hair_bang_14", "hair_bang_11"]
              and rec["after_empty_click"] == ["hair_bang_14", "hair_bang_11"] and rec["handles_follow"]
              and not rec["errors"])
        C.add("k2h_click_on_hair_selects_the_lock", ok, rec, "click, Shift click, empty click")
        S["next"]()
    later(1000, lambda: first_click(go))


@step
def k2i_no_lock():
    restore()
    gps, node = S["gps"], S["node"]
    ok = gps.enter_points(node, [])

    def see():
        st = gps.running()
        rec = {"entered": ok, "state": viewer().currentState(), "tool": gps.current_tool(),
               "hud_locks": (gps.STATS.get("hud") or {}).get("locks"), "message": S["pk"].STATE.message}
        C.add("k2i_edit_points_with_no_lock_says_select_a_lock",
              st is not None and rec["tool"] == "points" and rec["hud_locks"] == "Select a lock", rec)
        S["next"]()
    later(800, see)


@step
def k2j_draw_lock():
    restore()
    gps, node, ga = S["gps"], S["node"], S["ga"]
    ga.set_isolate(node, None)
    node.cook()
    spot, nrm = np.array(SPOT), np.array(SPOT_N)
    box = hou.BoundingBox(*(spot - 0.12), *(spot + 0.06))
    side = np.cross(nrm, [0.0, 1.0, 0.0])
    set_view(side / np.linalg.norm(side) * 0.8 + nrm * 0.5, box)
    S["drawn_before"] = set(ga.drawn_ids(node))

    def start():
        return to_global(spot)

    def check(rec, d, lids):
        res = d.get("result") or {}
        new = sorted(set(ga.drawn_ids(node)) - S["drawn_before"])
        rec["new_locks"] = new
        rec["message"] = res.get("message")
        rec["gave"] = res.get("gave")
        rec["tool_after"] = gps.current_tool()
        rec["selection_after"] = list(S["pk"].STATE.lock_ids)
        if len(new) != 1:
            return False
        S["drawn_id"] = new[0]
        sp = spines()[new[0]]["P"]
        rec["root_to_skin_cm"] = float("%.3g" % to_skin_cm(sp[0]))
        rec["strands"] = S["G"].strands_by_lock().get(new[0], 0)
        rec["length_cm"] = round(float(S["logic"].arc_lengths(sp)[-1]) * S["unit"], 2)
        rec["shot_alone"] = shot("k2j_drawn_lock")
        return (rec["strands"] > 0 and bool(rec["gave"]) and rec["tool_after"] == "draw"
                and rec["selection_after"] == new and rec["root_to_skin_cm"] <= 0.0025
                and rec["undo_label"] == "MONO Grooming: Draw lock")
    gesture("k2j_draw_a_lock_on_bare_skin", [], start, [(8 * i / 24, 170 * i / 24) for i in range(25)],
            S["next"], tool="draw", check=check)


@step
def k2k_edit_drawn():
    gps, node = S["gps"], S["node"]
    lid = S.get("drawn_id")
    if lid is None:
        C.add("k2k_control_point_edit_on_a_drawn_lock", False, "no drawn lock from k2j")
        return S["next"]()
    S["NAMES"][lid] = S["ga"].read_data(node).lock(lid).name
    S["ID"][S["NAMES"][lid]] = lid

    def start():
        return to_global(gps.running().locks[lid]["world"][-1])

    def check(rec, d, lids):
        lk = S["ga"].read_data(node).lock(lid)
        rec["edited"] = bool(lk.edited)
        rec["tip_moved_cm"] = round(float(np.linalg.norm(np.array(handles(lid)["points"])[-1]
                                                         - S["before_handles"][lid][-1])) * S["unit"], 3)
        return rec["edited"] and rec["tip_moved_cm"] > 0.5 and rec["undo_label"] == "MONO Grooming: Move control points"
    gesture("k2k_control_point_edit_on_a_drawn_lock", [S["NAMES"][lid]], start, [(-60 * i / 20, 0) for i in range(21)],
            S["next"], check=check)


@step
def k1a_paint_ends_points():
    restore()
    gps, ps, node, ga = S["gps"], S["ps"], S["node"], S["ga"]
    from apps.houdini import grooming_masks as gm
    lid = S["ID"][FRINGE]
    gps.enter_points(node, [lid])
    dl = ga.mask_add(node, name="t81", density=75.0)
    pl = ga.mask_add(node, name="t81 paint", parent=dl)
    S["layers"] = (dl, pl)
    rec = {}

    def paint():
        rec["before"] = viewer().currentState()
        rec["paint_enter"] = bool(ga.paint_enter(node, pl))
        later(2500, seen)

    def seen():
        rec["state_2_5s_after_paint"] = viewer().currentState()
        rec["tool"] = gps.current_tool()
        rec["points_running"] = gps.running() is not None
        ok = (rec["before"] == gps.STATE and rec["state_2_5s_after_paint"] == ps.STATE and rec["tool"] == "paint"
              and not rec["points_running"])
        C.add("k1a_paint_entered_ends_edit_points", ok, rec)
        later(300, points_again)

    def points_again():
        r = {"paint_on_before": gm.PAINT["node"] is not None}
        r["entered"] = gps.enter_points(node, [lid])

        def see():
            r["state_2_5s_after"] = viewer().currentState()
            r["paint_on_after"] = gm.PAINT["node"] is not None
            r["tool"] = gps.current_tool()
            r["errors"] = gps.STATS["errors"][-2:] + ps.STATS["errors"][-2:]
            C.add("k1b_edit_points_entered_ends_paint", r["paint_on_before"] and not r["paint_on_after"]
                  and r["state_2_5s_after"] == gps.STATE and r["tool"] == "points" and not r["errors"], r)
            S["next"]()
        later(2500, see)
    later(800, paint)


@step
def k1c_esc():
    gps, node = S["gps"], S["node"]
    lid = S["ID"][FRINGE]
    gps.enter_points(node, [lid])

    def esc():
        post_key(QtCore.Qt.Key_Escape, "")
        later(1200, see)

    def see():
        r = {"state": viewer().currentState(), "tool": gps.current_tool(), "esc_seen": gps.STATS["esc"],
             "errors": gps.STATS["errors"][-2:]}
        C.add("k1c_esc_ends_the_tool", r["state"] != gps.STATE and r["tool"] == "select" and not r["errors"], r)
        S["next"]()
    later(1000, lambda: first_click(esc))


@step
def k1d_other_node():
    gps, node = S["gps"], S["node"]
    lid = S["ID"][FRINGE]
    gps.enter_points(node, [lid])
    other = node.parent().node("accept_roots")

    def pick_other():
        other.setSelected(True, clear_all_selected=True)
        later(1200, after)

    def after():
        r = {"state_after_select": viewer().currentState(), "tool_after_select": gps.current_tool()}
        if gps.running() is not None:      # the state still has the viewport: the next press ends it
            c = viewer().qtScreenGeometry()
            click((c.left() + 40, c.top() + 90), lambda _i: see(r))
        else:
            see(r)

    def see(r):
        r.update(state=viewer().currentState(), tool=gps.current_tool(), ended=gps.STATS["ended"][-2:],
                 errors=gps.STATS["errors"][-2:])
        C.add("k1d_another_node_selected_ends_the_tool", r["tool"] == "select" and r["state"] != gps.STATE
              and not r["errors"], r)
        node.setSelected(True, clear_all_selected=True)
        S["next"]()
    later(1000, lambda: first_click(pick_other))


@step
def k1e_node_deleted():
    gps, node = S["gps"], S["node"]
    lid = S["ID"][FRINGE]
    gps.enter_points(node, [lid])

    def delete():
        S["node_path"] = node.path()
        node.destroy()
        later(1500, see)

    def see():
        r = {"state": viewer().currentState(), "tool": gps.current_tool(), "ended": gps.STATS["ended"][-2:],
             "errors": gps.STATS["errors"][-2:]}
        C.add("k1e_node_deleted_ends_the_tool", r["tool"] == "select" and r["state"] != gps.STATE and not r["errors"], r)
        later(300, reopen)

    def reopen():
        ga, node2 = lib.open_scene(SUITE, SCENE)
        S["node"] = node2
        viewer().setPwd(node2.parent())
        node2.setSelected(True, clear_all_selected=True)
        node2.cook()
        later(1000, S["next"])
    later(1000, lambda: first_click(delete))


@step
def k1f_file_new():
    gps, node = S["gps"], S["node"]
    lid = next(lk.id for lk in S["ga"].read_data(node).locks if lk.name == FRINGE)
    ok = gps.enter_points(node, [lid])

    def new():
        hou.hipFile.clear(suppress_save_prompt=True)
        later(1500, see)

    def see():
        r = {"entered": ok, "state": viewer().currentState(), "tool": gps.current_tool(),
             "ended": gps.STATS["ended"][-2:], "errors": gps.STATS["errors"][-2:]}
        C.add("k1f_file_new_ends_the_tool", ok and r["tool"] == "select" and r["state"] != gps.STATE
              and not r["errors"], r)
        S["next"]()
    later(1200, new)


@step
def z_errors():
    gps, ps = S["gps"], S["ps"]
    C.add("z_no_traceback_in_either_state", not gps.STATS["errors"] and not ps.STATS["errors"],
          {"points_state": gps.STATS["errors"][-3:], "paint_state": ps.STATS["errors"][-3:],
           "enters": gps.STATS["enters"], "exits": gps.STATS["exits"], "came_back": gps.STATS["came_back"]})
    S["next"]()


def run_steps(i=0):
    todo = [f for f in STEPS if not ONLY or f.__name__.split("_")[0] in ONLY or f.__name__ in ("s0_open", "z_errors")]

    def nxt():
        run_steps(i + 1)
    if i >= len(todo) or S.get("abort"):
        C.write(done=True)
        C.log("DONE")
        return
    S["next"] = nxt
    S["step"] = todo[i].__name__
    C.log("step", S["step"])
    later(300, todo[i])


def wait_main(n=0):
    if hou.qt.mainWindow() is not None and viewer() is not None:
        return later(3000, run_steps)
    QtCore.QTimer.singleShot(1000, lambda: wait_main(n + 1))


wait_main()
