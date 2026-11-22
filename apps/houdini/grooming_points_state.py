"""
Edit points and Draw lock of MONO Grooming (v0.2b B3): one Python viewer state (`config.POINTS_STATE`), entered by
name on the node, as Paint is (`grooming_paint_state.py`; spike t76, the plan's "v0.2b", design gate t78 mockup B).

It touches no node inside the locked HDA and never writes the node's data itself: it reads the handles
(`grooming_adapter.lock_handles`), keeps a drag in numpy while the button is down (nothing cooks; the handles and
the spine they give are drawn at once, X-ray, `hou.SimpleDrawable`), and on release calls ONE adapter function
(`set_points`, `rotate_points`, `scale_points`, `redraw_lock`, `set_handle_count`, `draw_lock`): one undo step a
gesture, then the node cooks (or the panel's `points_keys.HOOKS["write"]` does it inside its loading line).

Edit points (`enter_points(node, lock_ids)`): drag a handle on the view plane through it; the root handle (red)
follows the mouse ray onto the skin, and every other lock's root onto the skin under it, at every event. R / E held at
the press rotate / scale the locks about their roots for that drag (anywhere in the view), Shift + drag redraws the
lock nearest the press from the stroke, minus / plus change the handle count of each lock; the strip's sticky mode
(`set_mode`) does the same without a key. With several locks one drag moves the same handle of each
(`points_keys.map_handle`). A click (no drag) on hair selects that lock, Shift / Ctrl adds / toggles; empty space
keeps the selection; with no lock the tool stays on and says "Select a lock".

Draw lock (`enter_draw(node)`): a drag from the skin draws a lock (`draw_lock`, its footprint in the same undo step),
the wheel sets the next lock's width; the tool stays on and the new lock becomes `STATE.lock_ids`.

One tool at a time: entering this ends Paint, and Paint entering ends this (`yield_to_paint`, called from
`grooming_paint_state.enter`). Esc (from anywhere in Houdini's window, the mouse held too: an application event
filter, as Paint's), another node selected, the node deleted and File > New end the tool. Houdini drops a state
entered by name when the node is selected again: the tool comes back by itself (`_came_back`).

The record of the tool in hand (`points_keys.STATE`) is the one source for the panel, the state bar and the HUD;
`points_keys.HOOKS["tool"]` hears of every change.
"""

from __future__ import annotations

import time
import traceback

import hou

from tools.fx.grooming import config
from tools.fx.grooming import points_keys as pk

STATE = config.POINTS_STATE
LABEL = "MONO Grooming: Edit points"
HOTKEY_CONTEXT = "h.pane.gview.state.sop." + STATE
LIVE: dict = {}      # "state": the running state object, "prev": the viewer's state before the tool
STATS: dict = {"drags": [], "draws": [], "clicks": [], "keys": [], "events": 0, "enters": 0, "exits": 0,
               "came_back": 0, "errors": [], "ended": [], "esc": 0}
REENTER_MAX = 6
REENTER_WINDOW_S = 2.0
USER_STATES = ("select", "view", "scriptselect", "xform", "edit", "scenegraphselect")
HANDLE_CM = 0.4      # a handle's half size
ROOT_RGB, HANDLE_RGB, LINE_RGB, STROKE_RGB = (0.95, 0.2, 0.2), (0.45, 0.95, 1.0), (0.25, 0.55, 1.0), (1.0, 1.0, 1.0)


def _np():
    import numpy as np
    return np


def _ga():
    from apps.houdini import grooming_adapter as ga
    return ga


def _viewer():
    return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer) if hou.isUIAvailable() else None


def _note(text: str) -> None:
    STATS["errors"].append(text)
    del STATS["errors"][:-20]


def _say(text: str, important: bool = False) -> None:
    pk.update(message=text)
    try:
        hou.ui.setStatusMessage(text, hou.severityType.ImportantMessage if important else hou.severityType.Message)
    except hou.Error:
        pass


def _node():
    return hou.node(pk.STATE.node) if pk.STATE.node else None


def _on() -> bool:
    return pk.STATE.tool in (pk.TOOL_POINTS, pk.TOOL_DRAW) and _node() is not None


def _not_ours(node) -> str:
    from apps.houdini import grooming_paint_state as ps
    return ps._not_ours(node)


# ---------------------------------------------------------------------------
# keys seen by the application (a state gets no key while a mouse button is down)
# ---------------------------------------------------------------------------

def _qt():
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets
    return QtCore, QtWidgets


def _key_filter():
    got = LIVE.get("key_filter")
    if got is not None:
        return got
    QtCore, QtWidgets = _qt()
    held_keys = {QtCore.Qt.Key_R: pk.HELD_KEYS[pk.KEY_ROTATE], QtCore.Qt.Key_E: pk.HELD_KEYS[pk.KEY_SCALE]}

    class _KeyFilter(QtCore.QObject):
        """Esc ends the tool from anywhere (the gesture in progress is dropped: nothing was written yet). R / E
        ARM the next drag (`STATE.held`): a press arms it, a second press disarms it, the drag uses it once and
        the release is ignored, so held through the drag or tapped before it, both work (t81: both checked)."""

        def eventFilter(self, obj, event):
            try:
                kind = event.type()
                if kind not in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease, QtCore.QEvent.ShortcutOverride):
                    return False
                if not _on():
                    return False
                focus = QtWidgets.QApplication.focusWidget()
                if isinstance(focus, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
                    return False
                key = event.key()
                if key == QtCore.Qt.Key_Escape and kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride):
                    if kind == QtCore.QEvent.ShortcutOverride:
                        event.accept()
                    STATS["esc"] += 1
                    import hdefereval
                    hdefereval.executeDeferred(lambda: exit_tool("Esc"))
                    return True
                if key in held_keys and kind == QtCore.QEvent.KeyPress and not event.isAutoRepeat():
                    mode = held_keys[key]
                    pk.update(held="" if pk.STATE.held == mode else mode)
                    LIVE["armed_at"] = time.perf_counter()
                    state = running()
                    if state is not None:
                        state.queue_show()
                return False
            except Exception:
                _note(traceback.format_exc())
                return False

    LIVE["key_filter"] = _KeyFilter()
    return LIVE["key_filter"]


def _watch_keys(on: bool) -> None:
    try:
        _QtCore, QtWidgets = _qt()
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        if on and not LIVE.get("keys_on"):
            app.installEventFilter(_key_filter())
            LIVE["keys_on"] = True
        elif not on and LIVE.get("keys_on"):
            app.removeEventFilter(_key_filter())
            LIVE["keys_on"] = False
    except Exception:
        _note(traceback.format_exc())


def _scene_cleared(event_type) -> None:
    """File > New / Open: the tool ends before the node goes."""
    try:
        if event_type in (hou.hipFileEventType.BeforeClear, hou.hipFileEventType.BeforeLoad) and \
                pk.STATE.tool in (pk.TOOL_POINTS, pk.TOOL_DRAW):
            _end("the scene was cleared", leave_viewer=False)
    except Exception:
        _note(traceback.format_exc())


def _watch_scene() -> None:
    if not LIVE.get("scene_cb"):
        hou.hipFile.addEventCallback(_scene_cleared)
        LIVE["scene_cb"] = True


# ---------------------------------------------------------------------------
# the state
# ---------------------------------------------------------------------------

class PointsTool(object):
    def __init__(self, state_name, scene_viewer):
        self.state_name = state_name
        self.scene_viewer = scene_viewer
        self.node = None
        self.locks: dict = {}       # id -> {"world", "frame", "count", "count_set", "edited", "drawn", "name", ...}
        self.order: list = []       # ids with handles, in the selection's order
        self.spines: dict = {}      # id -> cooked SPINES points (for picking hair)
        self.cur = None             # the gesture while the button is down
        self.writing = False
        self.stale = False
        self.parms = None
        self.show_queued = False
        self.handles_draw = None
        self.ring = None
        self.callbacks = False
        self.unit = 1.0

    # ---- entering and leaving ----
    def onEnter(self, kwargs):
        self.parms = kwargs.get("state_parms")
        self._setup()

    def onGenerate(self, kwargs):
        self.parms = kwargs.get("state_parms")
        self._setup()

    def _setup(self) -> None:
        try:
            self._open()
        except Exception:
            _note(traceback.format_exc())
            raise

    def _open(self) -> None:
        t0 = time.perf_counter()
        LIVE["state"] = self
        STATS["enters"] += 1
        node = _node()
        if node is None or pk.STATE.tool not in (pk.TOOL_POINTS, pk.TOOL_DRAW):
            return
        self.node = node
        self.unit = max(float(node.evalParm("unit_cm")), 1e-9)
        parent = node.parent()
        self.xform = parent.worldTransform() if hasattr(parent, "worldTransform") else hou.hmath.identityTransform()
        self.inverse = self.xform.inverted()
        self.scalp = node.node("IN_SCALP").geometry().freeze()
        self.handles_draw = hou.SimpleDrawable(self.scene_viewer, hou.Geometry(), STATE + "_handles")
        self.handles_draw.setDisplayMode(hou.drawableDisplayMode.CurrentViewportMode)
        self.handles_draw.setTransform(self.xform)
        self.handles_draw.setXray(True)          # the lock's own hair hid them without X-ray (spike t76)
        self.handles_draw.enable(True)
        self.handles_draw.show(True)
        np = _np()
        ring = hou.Geometry()
        pts = ring.createPoints([(float(np.cos(a)), float(np.sin(a)), 0.0) for a in np.linspace(0, 2 * np.pi, 49)[:-1]])
        poly = ring.createPolygon(is_closed=True)
        for p in pts:
            poly.addVertex(p)
        self.ring = hou.GeometryDrawable(self.scene_viewer, hou.drawableGeometryType.Line, STATE + "_ring",
                                         params={"color1": hou.Vector4(1, 1, 1, 1), "line_width": 2.0})
        self.ring.setGeometry(ring)
        self.ring.show(False)
        node.addEventCallback((hou.nodeEventType.ParmTupleChanged,), self._parm_changed)
        node.addEventCallback((hou.nodeEventType.BeingDeleted,), self._deleted)
        self.callbacks = True
        _watch_keys(True)
        _watch_scene()
        self.load()
        try:
            self.scene_viewer.hudInfo(template=pk.hud_template(pk.STATE.tool))
        except Exception:
            _note(traceback.format_exc())
        self.show()
        STATS["enter_s"] = time.perf_counter() - t0

    def onExit(self, kwargs):
        STATS["exits"] += 1
        self._close()
        if LIVE.get("state") is self:
            LIVE.pop("state", None)
        if _on() and not LIVE.get("leaving"):
            import hdefereval
            hdefereval.executeDeferred(_came_back)

    def _close(self) -> None:
        self.cur = None
        if self.node is not None and self.callbacks:
            for kind, fn in (((hou.nodeEventType.ParmTupleChanged,), self._parm_changed),
                             ((hou.nodeEventType.BeingDeleted,), self._deleted)):
                try:
                    self.node.removeEventCallback(kind, fn)
                except Exception:
                    pass
            self.callbacks = False
        if self.ring is not None:
            self.ring.show(False)
        if self.handles_draw is not None:
            self.handles_draw.show(False)
            self.handles_draw.enable(False)
        if not _on():
            _watch_keys(False)

    def onInterrupt(self, kwargs):
        if self.ring is not None:
            self.ring.show(False)

    def _deleted(self, node=None, event_type=None, **kwargs):
        self.callbacks = False      # the node's callbacks go with it
        self.node = None
        import hdefereval
        hdefereval.executeDeferred(lambda: _end("the node was deleted"))

    # ---- the data: the adapter's handles of the locks being edited ----
    def _parm_changed(self, node=None, event_type=None, parm_tuple=None, **kwargs):
        if self.writing or parm_tuple is None:
            return
        if parm_tuple.name() in (config.DATA_PARM, "regions", "isolate"):
            self.stale = True
            import hdefereval
            hdefereval.executeDeferred(self.refresh)

    def refresh(self) -> None:
        """What the node holds now (an undo, a redo, the panel), not during a gesture."""
        if self.node is None or self.cur is not None or not self.stale:
            return
        try:
            self.stale = False
            if self.node.isDisplayFlagSet():
                self.node.cook()
            self.load()
            self.show()
        except Exception:
            _note(traceback.format_exc())

    def pickable(self) -> set:
        """Locks the viewport shows (isolated ones, else every shown lock): only they get handles or a click."""
        ga = _ga()
        iso = set(ga.isolate_ids(self.node))
        data = ga.read_data(self.node)
        if iso:
            return {lk.id for lk in data.locks if lk.id in iso}
        return {lk.id for lk in data.locks if lk.shown(data.group(lk.group))}

    def load(self) -> None:
        np = _np()
        ga = _ga()
        t0 = time.perf_counter()
        self.locks, self.order = {}, []
        shown = self.pickable()
        self.spines = {i: r["P"] for i, r in ga._spine_rows(ga._cooked(self.node, ga.NODE_SPINES)).items() if i in shown}
        why = ""
        if pk.STATE.tool == pk.TOOL_POINTS and pk.STATE.lock_ids:
            want = [i for i in pk.STATE.lock_ids if i in shown]
            hidden = [i for i in pk.STATE.lock_ids if i not in shown]
            for lid, h in ga.lock_handles(self.node, want).items():
                self.locks[lid] = {"world": np.asarray(h["points"], dtype=float),
                                   "frame": np.asarray(h["frame"], dtype=float),
                                   "origin": np.asarray(h["origin"], dtype=float),
                                   "axes": np.asarray(h["axes"], dtype=float),
                                   "measured": np.asarray(h["measured"], dtype=float), "count": h["count"],
                                   "count_set": h["count_set"], "edited": h["edited"], "drawn": h["drawn"],
                                   "root_moved": h["root_moved"], "length_cm": h["length_cm"]}
            self.order = [i for i in want if i in self.locks]
            data = ga.read_data(self.node)
            for lid in self.order:
                lk = data.lock(lid)
                self.locks[lid]["name"] = lk.name if lk is not None else str(lid)
            if hidden:
                names = [(data.lock(i).name if data.lock(i) else str(i)) for i in hidden]
                why = "no handles for " + ", ".join(names) + " (hidden or not isolated)"
        STATS["load_s"] = time.perf_counter() - t0
        STATS["load"] = {"tool": pk.STATE.tool, "lock_ids": list(pk.STATE.lock_ids), "shown": len(shown),
                         "order": list(self.order), "spines": len(self.spines), "why": why}
        if why:
            _say("MONO Grooming: " + why)
        self.redraw()

    # ---- drawing ----
    def _preview(self, lk, world):
        """The spine these handles give (the network's rule: each handle's move along the measured spine,
        Catmull-Rom; a drawn lock: the curve through its handles)."""
        from tools.fx.grooming import logic
        np = _np()
        if lk["drawn"]:
            return logic.drawn_spine(world, 49)
        M = lk["measured"]
        S = logic.arc_lengths(M)
        K = len(world)
        if K < 2 or S[-1] <= 0:
            return M
        at = logic.at_lengths(M, np.linspace(0.0, S[-1], K))
        return M + logic.catmull_rom(world - at, S / S[-1] * (K - 1))

    def redraw(self, worlds: dict | None = None, stroke=None) -> None:
        np = _np()
        if self.handles_draw is None:
            return
        g = hou.Geometry()
        g.addAttrib(hou.attribType.Point, "Cd", (1.0, 1.0, 1.0))
        r = HANDLE_CM / self.unit
        offs = np.array([[r, 0, 0], [-r, 0, 0], [0, r, 0], [0, -r, 0], [0, 0, r], [0, 0, -r]])
        tris = ((0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4), (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5))
        for lid in self.order:
            lk = self.locks[lid]
            world = worlds[lid] if worlds and lid in worlds else lk["world"]
            line = g.createPolygon(is_closed=False)
            for p in g.createPoints([hou.Vector3(*map(float, x)) for x in self._preview(lk, world)]):
                p.setAttribValue("Cd", LINE_RGB)
                line.addVertex(p)
            for k, w in enumerate(world):
                pts = g.createPoints([hou.Vector3(*map(float, w + o)) for o in offs])
                for p in pts:
                    p.setAttribValue("Cd", ROOT_RGB if k == 0 else HANDLE_RGB)
                for t in tris:
                    poly = g.createPolygon()
                    for q in t:
                        poly.addVertex(pts[q])
        if stroke is not None and len(stroke) > 1:
            line = g.createPolygon(is_closed=False)
            for p in g.createPoints([hou.Vector3(*map(float, x)) for x in stroke]):
                p.setAttribValue("Cd", STROKE_RGB)
                line.addVertex(p)
        self.handles_draw.setGeometry(g)
        self.handles_draw.show(True)
        STATS["drawn_handles"] = sum(len(self.locks[i]["world"]) for i in self.order)
        try:
            self.scene_viewer.curViewport().draw()
        except hou.Error:
            pass

    def onDraw(self, kwargs):
        if self.ring is not None:
            self.ring.draw(kwargs["draw_handle"])

    def _place_ring(self, pos, nrm) -> None:
        radius = 0.5 * pk.STATE.width_cm / self.unit
        z = nrm.normalized()
        x = z.cross(hou.Vector3(0, 1, 0) if abs(z[1]) < 0.9 else hou.Vector3(1, 0, 0)).normalized()
        y = z.cross(x)
        lift = z * (0.02 * radius)
        self.ring.setTransform(hou.Matrix4((
            (x[0] * radius, x[1] * radius, x[2] * radius, 0), (y[0] * radius, y[1] * radius, y[2] * radius, 0),
            (z[0], z[1], z[2], 0), (pos[0] + lift[0], pos[1] + lift[1], pos[2] + lift[2], 1))) * self.xform)

    # ---- the HUD and the bar (one source: points_keys.STATE) ----
    def show(self) -> None:
        self.show_queued = False
        if self.node is None or LIVE.get("state") is not self:
            return
        rec = pk.STATE
        info = {i: self.locks[i] for i in self.order}
        values = pk.hud_values(rec, info)
        try:
            self.scene_viewer.hudInfo(values=values)
        except Exception:
            _note(traceback.format_exc())
        STATS["hud"] = values
        bar = pk.bar_values(rec, info)
        visible = pk.bar_visible(rec.tool)
        STATS["bar"] = bar
        put = getattr(self.scene_viewer, "_setCurrentStateParm", None)
        for name, value in bar.items():
            if self.parms is not None:
                try:
                    if self.parms[name]["value"] != value:
                        self.parms[name]["value"] = value
                    if self.parms[name].get("visible") != visible[name]:
                        self.parms[name]["visible"] = visible[name]
                except (KeyError, TypeError, AttributeError):
                    pass
            if put is not None and self.scene_viewer.currentState() == STATE:
                try:
                    put(name, repr(float(value)) if isinstance(value, float) else str(int(value)))
                except hou.Error:
                    pass
        text = pk.status_text(rec, len(self.order))
        if text:
            try:
                hou.ui.setStatusMessage(text, hou.severityType.Message)
            except hou.Error:
                pass

    def queue_show(self) -> None:
        if self.show_queued:
            return
        self.show_queued = True
        import hdefereval
        hdefereval.executeDeferred(self._show_deferred)

    def _show_deferred(self) -> None:
        try:
            self.show()
        except Exception:
            _note(traceback.format_exc())

    def onParmChangeEvent(self, kwargs):
        try:
            asked = pk.field_change(kwargs["parm_name"], kwargs["parm_value"], pk.STATE)
            if "handles" in asked:
                ids = list(self.order)
                if ids and any(self.locks[i]["count_set"] != asked["handles"] for i in ids):
                    self._write("handles", lambda: _ga().set_handle_count(self.node, ids, asked["handles"]))
            elif asked:
                pk.update(**asked)
                self.queue_show()
        except Exception:
            _note(traceback.format_exc())

    def onMenuAction(self, kwargs):
        try:
            item = kwargs["menu_item"]
            STATS["menu"] = (STATS.get("menu", []) + [item])[-20:]
            self._drop_stale()
            asked = pk.menu_fields(item)
            if "held" in asked and time.perf_counter() - LIVE.get("armed_at", 0.0) < 0.5:
                asked = {}            # the R / E hotkey of a key the filter has just taken
            if "handles" in asked:
                if pk.STATE.tool == pk.TOOL_POINTS and self.cur is None:
                    self.step_handles(asked["handles"])
            elif asked:
                pk.update(**asked)
                self.queue_show()
        except Exception:
            _note(traceback.format_exc())

    def _drop_stale(self) -> None:
        """A gesture whose button is no longer down (its release went to the pane, t81 r10) is closed: a drag that
        moved is written as on release, a press that did not is dropped."""
        if self.cur is None:
            return
        try:
            QtCore, QtWidgets = _qt()
            down = bool(QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton)
        except Exception:
            down = True
        if down:
            return
        STATS["stale_gestures"] = STATS.get("stale_gestures", 0) + 1
        c = self.cur
        if c.get("moved") and c.get("kind") != "draw":
            mx, my = LIVE.get("last_mouse") or c["press_px"]
            self._release(None, mx, my)
        else:
            self.cur = None
            self.redraw()

    # ---- keys ----
    def onKeyEvent(self, kwargs):
        try:
            key = kwargs["ui_event"].device().keyString()
            STATS["keys"] = (STATS["keys"] + [key])[-30:]
            self._drop_stale()
            name = pk.key_name(key)
            if name in ("esc", "escape"):
                exit_tool("Esc")
                return True
            if name in (pk.KEY_ROTATE, pk.KEY_SCALE):
                # armed by the application filter (it sees the press first); consumed so Houdini's own R / E do
                # not run
                return True
            step = pk.handle_step(key)
            STATS["key_step"] = {"key": key, "step": step, "tool": pk.STATE.tool, "busy": self.cur is not None}
            if step and pk.STATE.tool == pk.TOOL_POINTS and self.cur is None:
                self.step_handles(step)
                return True
        except Exception:
            _note(traceback.format_exc())
        return False

    def step_handles(self, step: int) -> None:
        """Minus / plus: one handle fewer / more on EACH lock (a lock at its limit stays); one undo step."""
        ids = list(self.order)
        STATS["handles_step"] = {"step": step, "ids": ids, "counts": [self.locks[i]["count"] for i in ids]}
        if not ids:
            _say("MONO Grooming: Select a lock")
            return
        by: dict = {}
        for lid in ids:
            to = pk.next_count(self.locks[lid]["count"], step)
            if to != self.locks[lid]["count"]:
                by.setdefault(to, []).append(lid)
        if not by:
            _say(f"MONO Grooming: Handles at {'least' if step < 0 else 'most'} already "
                 f"({config.HANDLES_MIN if step < 0 else config.HANDLES_MAX})")
            return

        def go():
            out = {"locks": [], "message": "", "gap_cm": {}}
            msgs = []
            with hou.undos.group(config.UNDO_SPINE["handles"]):
                for to, lids in sorted(by.items()):
                    res = _ga().set_handle_count(self.node, lids, to)
                    out["locks"] += res["locks"]
                    out["gap_cm"].update(res.get("gap_cm", {}))
                    msgs.append(res["message"])
            out["message"] = "; ".join(msgs)
            return out
        c = {"kind": "handles", "step": step, "to": {str(k): v for k, v in by.items()}}
        c["result"] = self._write("handles", go, c)
        STATS["drags"].append(c)

    def onMouseWheelEvent(self, kwargs):
        if pk.STATE.tool != pk.TOOL_DRAW or self.node is None:
            return False
        try:
            notches = kwargs["ui_event"].device().mouseWheel()
            pk.update(width_cm=pk.wheel_width(pk.STATE.width_cm, notches))
            STATS["wheel"] = STATS.get("wheel", 0) + 1
            if self.ring is not None and LIVE.get("ring_at") is not None:
                self._place_ring(*LIVE["ring_at"])
            self.queue_show()
        except Exception:
            _note(traceback.format_exc())
        return True

    # ---- the mouse ----
    def onMouseEvent(self, kwargs):
        t0 = time.perf_counter()
        try:
            used = self._mouse(kwargs["ui_event"])
        except Exception:
            _note(traceback.format_exc())
            raise
        STATS["events"] += 1
        STATS["last_mouse"] = LIVE.get("last_mouse")
        if self.cur is not None:
            self.cur.setdefault("handler_ms", []).append((time.perf_counter() - t0) * 1000.0)
        return used

    def _ray(self, ui_event):
        np = _np()
        origin, direction = ui_event.ray()
        o = origin * self.inverse
        d = direction.multiplyAsDir(self.inverse)
        return np.array(tuple(o), dtype=float), np.array(tuple(d.normalized()), dtype=float)

    def _skin_hit(self, o, d):
        pos, nrm, uvw = hou.Vector3(), hou.Vector3(), hou.Vector3()
        if self.scalp.intersect(hou.Vector3(*map(float, o)), hou.Vector3(*map(float, d)), pos, nrm, uvw) >= 0:
            return _np().array(tuple(pos)), nrm
        return None, None

    def on_skin(self, p):
        np = _np()
        pr, u, v, _dist = self.scalp.nearestPrim(hou.Vector3(*map(float, p)))
        return np.array(tuple(pr.positionAtInterior(u, v))) if pr is not None else np.asarray(p, dtype=float)

    @staticmethod
    def _on_plane(o, d, point, normal):
        np = _np()
        den = float(np.dot(d, normal))
        if abs(den) < 1e-9:
            return None
        return o + d * (float(np.dot(point - o, normal)) / den)

    def _screen(self, p):
        s = self.scene_viewer.curViewport().mapToScreen(hou.Vector3(*map(float, p)) * self.xform)
        return float(s[0]), float(s[1])

    def pick_handle(self, mx, my):
        best = {}
        for lid in self.order:
            for k, w in enumerate(self.locks[lid]["world"]):
                sx, sy = self._screen(w)
                best[(lid, k)] = ((sx - mx) ** 2 + (sy - my) ** 2) ** 0.5
        STATS["pick"] = {"at": (mx, my), "nearest_px": round(min(best.values()), 1) if best else None,
                         "viewport": tuple(self.scene_viewer.curViewport().size()),
                         "handles_px": [tuple(round(c, 1) for c in self._screen(w)) for lid in self.order
                                        for w in self.locks[lid]["world"]]}
        return pk.nearest(best, pk.PICK_PX)

    def pick_hair(self, mx, my):
        """The lock whose spine passes nearest the click on screen, within HAIR_PICK_PX."""
        np = _np()
        vp = self.scene_viewer.curViewport()
        _x, _y, w, h = vp.size()
        direction, origin = vp.mapToWorld(w * 0.5, h * 0.5)
        eye = np.array(tuple(origin * self.inverse))
        ahead = np.array(tuple(direction.multiplyAsDir(self.inverse)))
        dist = {}
        for lid, P in self.spines.items():
            Q = P[::2]
            # only what is in front of the camera and inside the view: a point behind it maps mirrored, one far
            # outside lands anywhere, and a click on empty space must keep the selection
            Q = Q[(Q - eye) @ ahead > 0]
            S = np.array([tuple(vp.mapToScreen(hou.Vector3(*map(float, p)) * self.xform)) for p in Q])
            if len(S) < 2:
                continue
            keep = (S[:, 0] >= 0) & (S[:, 0] <= w) & (S[:, 1] >= 0) & (S[:, 1] <= h)
            S = S[keep]
            if len(S) < 2:
                continue
            a, b = S[:-1], S[1:]
            ab = b - a
            t = np.clip(((np.array([mx, my]) - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-9), 0, 1)
            q = a + ab * t[:, None]
            dist[lid] = float(np.min(np.hypot(q[:, 0] - mx, q[:, 1] - my)))
        return pk.nearest(dist, pk.HAIR_PICK_PX)

    def _mouse(self, ui_event) -> bool:
        if self.node is None:
            return False
        dev = ui_event.device()
        mx, my = float(dev.mouseX()), float(dev.mouseY())
        LIVE["last_mouse"] = (mx, my)
        log = STATS.setdefault("mouse_log", [])
        log.append((round(mx), round(my), bool(dev.isLeftButton()), bool(dev.isShiftKey()),
                    self.cur["kind"] if self.cur else None))
        del log[:-80]
        if not _on():
            import hdefereval
            hdefereval.executeDeferred(_leave_viewer)
            return False
        left = dev.isLeftButton()
        o, d = self._ray(ui_event)
        # a press and release with no motion comes as ONE event, reason Picked, the button still down and no
        # release after it (t81 r11): it is a whole click
        picked = ui_event.reason() == hou.uiEventReason.Picked
        log[-1] = log[-1] + (("picked",) if picked else ())
        if picked and left and self.cur is None:
            why = _not_ours(self.node)
            if why:
                _end(why)
                return False
            if pk.STATE.tool == pk.TOOL_DRAW:
                _say("MONO Grooming: drag from the skin to draw a lock")
                return True
            if self.stale:
                self.refresh()
            self._press(dev, mx, my, o, d)
            self._release(dev, mx, my)
            return True
        if pk.STATE.tool == pk.TOOL_DRAW:
            return self._mouse_draw(dev, left, mx, my, o, d)
        if self.cur is None:
            if not left:
                return False
            why = _not_ours(self.node)
            if why:
                _end(why)
                return False
            if self.stale:
                self.refresh()
            self._press(dev, mx, my, o, d)
            return True
        c = self.cur
        c["events"] += 1
        c["moved"] = c["moved"] or pk.is_drag(c["press_px"], (mx, my))
        if c["kind"] == "move":
            self._drag_move(o, d)
        elif c["kind"] in ("rotate", "scale"):
            self._drag_turn(mx, o, d)
        elif c["kind"] == "redraw":
            self._drag_stroke(mx, my, o, d)
        if not left or picked:
            self._release(dev, mx, my)
        return True

    def _press(self, dev, mx, my, o, d) -> None:
        mode = pk.drag_mode(pk.STATE.mode, pk.STATE.held, bool(dev.isShiftKey()))
        hit = self.pick_handle(mx, my)
        start = {i: self.locks[i]["world"].copy() for i in self.order}
        c = {"t0": time.perf_counter(), "events": 0, "moved": False, "press_px": (mx, my), "mode": mode,
             "shift": bool(dev.isShiftKey()), "ctrl": bool(dev.isCtrlKey()), "start": start, "normal": d.copy(),
             "hit": hit, "roots": [], "worlds": None, "held": pk.STATE.held, "locks": list(self.order)}
        if not self.order:
            c["kind"] = "click"
        elif mode == "redraw":
            lid = hit[0] if hit is not None else self._nearest_lock(mx, my)
            c.update(kind="redraw", lock=lid)
            root = start[lid][0]
            if hit is not None and hit[1] == 0:
                first = root.copy()                       # from the root handle: the root stays
            else:
                first, _n = self._skin_hit(o, d)          # from the skin: the root moves there
                if first is None:
                    first = self._on_plane(o, d, root, d)
            c["stroke"] = [first] if first is not None else []
            c["last_px"] = (mx, my)
            c["plane"] = root
        elif hit is not None and mode == "move":
            c.update(kind="move", lock=hit[0], k=hit[1])
        elif mode in ("rotate", "scale"):
            lid = hit[0] if hit is not None else self.order[0]
            pivot = start[lid][0]
            c.update(kind=mode, lock=lid, pivot=pivot, a=self._on_plane(o, d, pivot, d), angle=0.0, factor=1.0)
        else:
            c["kind"] = "click"
        self.cur = c

    def _nearest_lock(self, mx, my):
        dist = {}
        for lid in self.order:
            for w in self.locks[lid]["world"]:
                sx, sy = self._screen(w)
                dist[lid] = min(dist.get(lid, 1e18), ((sx - mx) ** 2 + (sy - my) ** 2) ** 0.5)
        return pk.nearest(dist, 1e18)

    def _drag_move(self, o, d) -> None:
        c = self.cur
        lid, k = c["lock"], c["k"]
        K0 = len(c["start"][lid])
        startp = c["start"][lid][k]
        if k == 0:
            new, _n = self._skin_hit(o, d)        # a ray that misses the skin leaves the root where it was
            if new is None:
                c["missed_skin"] = c.get("missed_skin", 0) + 1
        else:
            new = self._on_plane(o, d, startp, c["normal"])
        if new is None:
            return
        delta = new - startp
        worlds = {}
        roots = {}
        for j in self.order:
            w = c["start"][j].copy()
            kk = pk.map_handle(k, K0, len(w))
            w[kk] = w[kk] + delta
            if kk == 0:
                w[0] = new if j == lid else self.on_skin(w[0])
                roots[j] = tuple(map(float, w[0]))
            worlds[j] = w
        c["worlds"] = worlds
        if roots:
            c["roots"].append(roots)
        self.redraw(worlds)

    def _drag_turn(self, mx, o, d) -> None:
        from tools.fx.grooming import logic
        c = self.cur
        if c["kind"] == "rotate":
            b = self._on_plane(o, d, c["pivot"], c["normal"])
            if b is None or c["a"] is None:
                return
            c["angle"] = pk.signed_angle(c["a"] - c["pivot"], b - c["pivot"], c["normal"])
            worlds = {j: logic.rotate_about_root(c["start"][j], c["normal"], c["angle"]) for j in self.order}
        else:
            c["factor"] = pk.scale_factor(mx - c["press_px"][0])
            worlds = {j: logic.scale_about_root(c["start"][j], c["factor"]) for j in self.order}
        c["worlds"] = worlds
        self.redraw(worlds)

    def _drag_stroke(self, mx, my, o, d) -> None:
        c = self.cur
        if not c["stroke"]:
            return
        lx, ly = c["last_px"]
        if ((mx - lx) ** 2 + (my - ly) ** 2) ** 0.5 < pk.STROKE_STEP_PX:
            return
        p = self._on_plane(o, d, c["plane"], c["normal"])
        if p is None:
            return
        c["stroke"].append(p)
        c["last_px"] = (mx, my)
        self.redraw(stroke=c["stroke"])

    def _release(self, dev, mx, my) -> None:
        c, self.cur = self.cur, None
        np = _np()
        c["drag_s"] = time.perf_counter() - c["t0"]
        hm = c.pop("handler_ms", [])
        c["handler_ms_median"] = float(sorted(hm)[len(hm) // 2]) if hm else 0.0
        c["handler_ms_max"] = float(max(hm)) if hm else 0.0
        c["handler_events"] = len(hm)
        res = None
        if c["kind"] == "click" or not c["moved"]:
            c["kind"] = "click"
            self._click(mx, my, c)
        else:
            ids = list(self.order)
            if c["kind"] == "move" and c["worlds"] is not None:
                worlds = c["worlds"]
                res = self._write("move", lambda: self._set_points(worlds), c)
            elif c["kind"] == "rotate" and abs(c["angle"]) > 1e-3:
                axis, deg = c["normal"].tolist(), float(c["angle"])
                res = self._write("rotate", lambda: _ga().rotate_points(self.node, ids, axis, deg), c)
            elif c["kind"] == "scale" and abs(c["factor"] - 1.0) > 1e-4:
                f = float(c["factor"])
                res = self._write("scale", lambda: _ga().scale_points(self.node, ids, f), c)
            elif c["kind"] == "redraw" and len(c["stroke"]) >= 2:
                stroke = np.array(c["stroke"]).tolist()
                lid = c["lock"]
                res = self._write("redraw", lambda: _ga().redraw_lock(self.node, lid, stroke), c)
            else:
                self.redraw()
        c["result"] = res
        if c["kind"] != "click" and c.get("held"):
            pk.update(held="")            # R / E armed that one drag
            self.queue_show()
        c["axis"] = c["normal"].tolist() if c.get("normal") is not None else None
        for key in ("start", "worlds", "normal", "a", "pivot", "plane"):
            c.pop(key, None)
        if "stroke" in c:
            c["stroke"] = [list(map(float, p)) for p in c["stroke"]]
        STATS["drags"].append(c)
        del STATS["drags"][:-100]

    def _set_points(self, worlds: dict) -> dict:
        """The handles after a move, ONE undo step: a lock of the mesh by its root frame with the handles that did
        not move kept exactly (a moved root on the skin off the stored one must not read as moved again), a drawn
        lock in the node's space."""
        from tools.fx.grooming import logic
        np = _np()
        ga = _ga()
        frame, points = {}, {}
        for lid, w in worlds.items():
            lk = self.locks[lid]
            if lk["drawn"]:
                points[lid] = w.tolist()
                continue
            H = lk["frame"].copy()
            moved = np.linalg.norm(w - lk["world"], axis=1) > 0.0
            if moved.any():
                H[moved] = logic.world_to_frame(w[moved], lk["origin"], lk["axes"])
            frame[lid] = H.tolist()
        if frame and points:
            with hou.undos.group(config.UNDO_SPINE["move"]):
                a = ga.set_points(self.node, frame, space="frame", step="move")
                b = ga.set_points(self.node, points, space="points", step="move")
            return {"locks": a["locks"] + b["locks"], "roots_moved": a["roots_moved"] + b["roots_moved"],
                    "message": a["message"] + "; " + b["message"]}
        if frame:
            return ga.set_points(self.node, frame, space="frame", step="move")
        return ga.set_points(self.node, points, space="points", step="move")

    def _click(self, mx, my, c) -> None:
        """A click without a drag: the lock under it becomes the selection (Shift adds, Ctrl toggles)."""
        t = time.perf_counter()
        if c.get("hit") is not None:
            # a press on a handle wins over the hair under it (review_b, decided): no selection change
            STATS["clicks"].append({"hit": None, "on_handle": list(c["hit"]), "at": (mx, my)})
            self.redraw()
            return
        hit = self.pick_hair(mx, my)
        new = pk.click_selection(pk.STATE.lock_ids, hit, c.get("shift", False), c.get("ctrl", False))
        c.update(picked=hit, selection=new, pick_s=time.perf_counter() - t)
        STATS["clicks"].append({"hit": hit, "selection": new, "pick_s": c["pick_s"], "at": (mx, my),
                                "shift": c.get("shift"), "ctrl": c.get("ctrl"), "before": list(pk.STATE.lock_ids)})
        del STATS["clicks"][:-50]
        if new != pk.STATE.lock_ids:
            pk.update(lock_ids=new)
            self.load()
            self.show()
        else:
            self.redraw()

    def _write(self, step: str, fn, c: dict | None = None):
        """Run one adapter write (one undo step), then cook (or the panel's hook), then read the handles again."""
        t = time.perf_counter()
        self.writing = True
        try:
            res = fn()
        except Exception as exc:
            _note(traceback.format_exc())
            _say(f"MONO Grooming: {step} refused: {exc}", important=True)
            self.redraw()
            return None
        finally:
            self.writing = False
        write_s = time.perf_counter() - t
        t = time.perf_counter()
        self._cook(res)
        cook_s = time.perf_counter() - t
        try:
            geo = self.node.node("to_cook").geometry()
            recooked = sorted(geo.primIntAttribValues("lock_id")) if geo.findPrimAttrib("lock_id") else []
        except Exception:
            recooked = None
        self.load()
        if res and res.get("message"):
            _say("MONO Grooming: " + res["message"])
        self.show()
        if c is not None:
            c.update(write_s=write_s, cook_s=cook_s, recooked=recooked)
        return res

    def _cook(self, res) -> None:
        hook = pk.HOOKS.get("write")
        try:
            if hook is not None:
                hook(self.node, res)
            elif self.node.isDisplayFlagSet():
                self.node.cook()
        except hou.Error:
            pass                       # a cook error stays on the node

    # ---- Draw lock ----
    def _mouse_draw(self, dev, left, mx, my, o, d) -> bool:
        np = _np()
        hit, nrm = self._skin_hit(o, d)
        if self.cur is None:
            if hit is not None:
                LIVE["ring_at"] = (hou.Vector3(*map(float, hit)), hou.Vector3(nrm))
                self._place_ring(*LIVE["ring_at"])
            self.ring.show(hit is not None)
            if not left:
                return False
            why = _not_ours(self.node)
            if why:
                _end(why)
                return False
            if hit is None:
                _say("MONO Grooming: start the lock on the skin")
                return True
            self.cur = {"kind": "draw", "t0": time.perf_counter(), "events": 0, "stroke": [hit], "plane": hit,
                        "normal": d.copy(), "last_px": (mx, my), "press_px": (mx, my), "moved": False}
            return True
        c = self.cur
        c["events"] += 1
        c["moved"] = c["moved"] or pk.is_drag(c["press_px"], (mx, my))
        lx, ly = c["last_px"]
        if ((mx - lx) ** 2 + (my - ly) ** 2) ** 0.5 >= pk.STROKE_STEP_PX:
            p = self._on_plane(o, d, c["plane"], c["normal"])
            if p is not None:
                c["stroke"].append(p)
                c["last_px"] = (mx, my)
                self.redraw(stroke=c["stroke"])
        if not left:
            self.cur = None
            self.ring.show(False)
            c["drag_s"] = time.perf_counter() - c["t0"]
            hm = c.pop("handler_ms", [])
            c["handler_ms_median"] = float(sorted(hm)[len(hm) // 2]) if hm else 0.0
            c["handler_ms_max"] = float(max(hm)) if hm else 0.0
            stroke = np.array(c["stroke"])
            length_cm = float(np.linalg.norm(np.diff(stroke, axis=0), axis=1).sum()) * self.unit \
                if len(stroke) > 1 else 0.0
            c["length_cm"] = length_cm
            if not c["moved"] or length_cm < 2 * HANDLE_CM:
                _say("MONO Grooming: drag from the skin to draw a lock")
                self.redraw()
            else:
                rec = pk.STATE
                args = (stroke.tolist(), rec.width_cm, rec.thick_cm, rec.taper)
                res = self._write("draw", lambda: _ga().draw_lock(self.node, *args), c)
                c["result"] = res
                if res:
                    # the new lock is the selection while Draw lock stays on (review_b finding 4)
                    pk.update(lock_ids=[res["id"]])
                    self.redraw()
            c["stroke"] = [list(map(float, p)) for p in c["stroke"]]
            for key in ("plane", "normal"):
                c.pop(key, None)
            STATS["draws"].append(c)
            del STATS["draws"][:-50]
        return True


# ---------------------------------------------------------------------------
# registered once a session, driven by the functions below (the panel's interface)
# ---------------------------------------------------------------------------

def register(force: bool = False) -> None:
    if hou.ui.isRegisteredViewerState(STATE):
        if not force:
            return
        hou.ui.unregisterViewerState(STATE)
    template = hou.ViewerStateTemplate(STATE, LABEL, hou.sopNodeTypeCategory())
    template.bindFactory(PointsTool)
    template.bindIcon("SOP_edit")
    defaults = pk.bar_values(pk.STATE)
    template.bindParameter(hou.parmTemplateType.Menu, name="drag_mode", label="Drag",
                           menu_items=[(m, pk.MODE_LABELS[m]) for m in pk.MODES], default_value=pk.STATE.mode,
                           help="The sticky drag mode; R / E / Shift held at the press act for that drag only")
    template.bindParameter(hou.parmTemplateType.Int, name="handles", label="Handles", min_limit=0,
                           max_limit=config.HANDLES_MAX, default_value=0,
                           help="0 = auto (one every 8 cm); - / + in the viewport")
    template.bindParameter(hou.parmTemplateType.Float, name="width", label="Width", min_limit=pk.WIDTH_MIN_CM,
                           max_limit=10.0, default_value=defaults["width"], help="The next lock's width, cm (wheel)")
    template.bindParameter(hou.parmTemplateType.Float, name="thickness", label="Thickness",
                           min_limit=pk.THICK_MIN_CM, max_limit=5.0, default_value=defaults["thickness"],
                           help="The next lock's thickness, cm")
    template.bindParameter(hou.parmTemplateType.Float, name="taper", label="Tip taper", min_limit=0.0,
                           max_limit=1.0, default_value=defaults["taper"], help="0 = blunt, 1 = pointed")
    # R / E as the state's own hotkeys: else Houdini's R / E run and take the viewport to their tools (t81 r10:
    # a posted R left the viewer in "edit"); the press arrives as a menu action, the release through the filter
    keys = hou.PluginHotkeyDefinitions()
    keys.addContext(HOTKEY_CONTEXT, LABEL, "Edit points / Draw lock of MONO Grooming")
    keys.addCommandCategory(HOTKEY_CONTEXT, LABEL, "Edit points / Draw lock of MONO Grooming")
    menu = hou.ViewerStateMenu(STATE + "_menu", LABEL)
    for item, text, key in pk.menu_items():
        hotkey = ""
        if key:
            hotkey = HOTKEY_CONTEXT + "." + item
            keys.addCommand(hotkey, text, text)
            keys.addDefaultBinding(HOTKEY_CONTEXT, hotkey, [key])
        menu.addActionItem(item, text, hotkey=hotkey)
    template.bindHotkeyDefinitions(keys)
    template.bindMenu(menu)
    hou.ui.registerViewerState(template)


def running():
    viewer = _viewer()
    state = LIVE.get("state")
    return state if state is not None and viewer is not None and viewer.currentState() == STATE else None


def _end_paint_first() -> None:
    from apps.houdini import grooming_masks as gm
    if gm.PAINT["node"] is not None:
        gm.paint_exit()


def _enter(node, tool: str, lock_ids) -> bool:
    _end_paint_first()
    pk.update(tool=tool, node=node.path(), lock_ids=list(lock_ids or ()), held="", message="")
    viewer = _viewer()
    if viewer is None:
        return False
    register()
    with hou.undos.disabler():
        if viewer.pwd() != node.parent():
            viewer.setPwd(node.parent())
        if _not_ours(node):
            node.setSelected(True, clear_all_selected=True)
        current = viewer.currentState()
        if current != STATE:
            LIVE["prev"] = current
        state = running()
        if state is not None:                   # already on: the other tool, or another node
            state._close()
            state.__init__(state.state_name, state.scene_viewer)
            state._setup()
        else:
            viewer.setCurrentState(STATE, request_new_on_generate=False)
    ok = running() is not None and running().node is not None
    if ok and tool == pk.TOOL_POINTS and not pk.STATE.lock_ids:
        _say("MONO Grooming: Edit points. Select a lock")
    return ok


def enter_points(node, lock_ids) -> bool:
    """Edit points on these locks (none: the tool is on and says "Select a lock"). True when it runs."""
    return _enter(node, pk.TOOL_POINTS, lock_ids)


def enter_draw(node) -> bool:
    """Draw lock on this node. True when it runs."""
    return _enter(node, pk.TOOL_DRAW, [])


def current_tool() -> str:
    return pk.STATE.tool


def set_mode(mode: str) -> None:
    """The sticky drag mode (the strip's Move / Rotate / Scale / Redraw)."""
    pk.update(mode=mode)
    state = running()
    if state is not None:
        state.queue_show()


def set_locks(lock_ids) -> None:
    """The locks being edited (the panel's selection): the handles follow while the tool is on."""
    changed = pk.update(lock_ids=list(lock_ids or ()))
    state = running()
    if changed and state is not None and state.cur is None:
        state.load()
        state.show()


def set_new_lock(width_cm: float | None = None, thick_cm: float | None = None, taper: float | None = None) -> None:
    """The next drawn lock's width, thickness (cm) and tip taper (shared with the state bar)."""
    fields = {k: v for k, v in (("width_cm", width_cm), ("thick_cm", thick_cm), ("taper", taper)) if v is not None}
    pk.update(**fields)
    state = running()
    if state is not None:
        state.queue_show()


def _leave_viewer() -> None:
    viewer = _viewer()
    if viewer is None or viewer.currentState() != STATE:
        return
    LIVE["leaving"] = True
    try:
        prev = LIVE.get("prev") or "select"
        with hou.undos.disabler():
            try:
                if prev in USER_STATES or prev == "sopview":
                    viewer.setCurrentState(prev)
                else:
                    viewer.enterCurrentNodeState()      # by name a node state would make a second node
            except hou.Error:
                viewer.setCurrentState("select")
    finally:
        LIVE["leaving"] = False


def _end(why: str, leave_viewer: bool = True) -> None:
    """The tool off without the artist asking (another node, the node deleted, the scene cleared)."""
    if pk.STATE.tool not in (pk.TOOL_POINTS, pk.TOOL_DRAW):
        return
    STATS["ended"] = (STATS["ended"] + [why])[-20:]
    pk.reset()
    if leave_viewer:
        _leave_viewer()
    _watch_keys(False)
    _say(f"MONO Grooming: Edit points / Draw lock ended, {why}")


def exit_tool(why: str = "") -> None:
    """Edit points / Draw lock off: back to the tool the viewport had (Select in the record)."""
    if pk.STATE.tool in (pk.TOOL_POINTS, pk.TOOL_DRAW):
        STATS["ended"] = (STATS["ended"] + [why or "exit_tool"])[-20:]
        pk.reset()
        _leave_viewer()
        _watch_keys(False)


def yield_to_paint() -> None:
    """Paint is entering (`grooming_paint_state.enter`): this tool ends first, and the record says Paint."""
    if pk.STATE.tool in (pk.TOOL_POINTS, pk.TOOL_DRAW):
        STATS["ended"] = (STATS["ended"] + ["paint"])[-20:]
        _leave_viewer()
        _watch_keys(False)
    pk.update(tool=pk.TOOL_PAINT, held="")


def paint_ended() -> None:
    """Paint is over (`grooming_paint_state.leave` / its own end): the record goes back to Select."""
    if pk.STATE.tool == pk.TOOL_PAINT:
        pk.update(tool=pk.TOOL_SELECT)


def _came_back() -> None:
    """Houdini took the state away while the tool is on (the node selected again: its own state): it comes back.
    The artist picked a tool by hand, another node is selected, or it keeps being taken: the tool ends."""
    try:
        viewer = _viewer()
        if viewer is None or not _on():
            if pk.STATE.tool in (pk.TOOL_POINTS, pk.TOOL_DRAW) and _node() is None:
                _end("the node is gone", leave_viewer=False)
            return
        current = viewer.currentState()
        if current == STATE:
            return
        node = _node()
        now = time.perf_counter()
        recent = [t for t in LIVE.get("reenters", []) if now - t < REENTER_WINDOW_S]
        other = _not_ours(node)
        if current in USER_STATES or len(recent) >= REENTER_MAX or other:
            _end(other or f"the {current} tool was picked", leave_viewer=False)
            return
        LIVE["reenters"] = recent + [now]
        STATS["came_back"] += 1
        try:
            with hou.undos.disabler():
                if viewer.pwd() != node.parent():
                    viewer.setPwd(node.parent())
                viewer.setCurrentState(STATE, request_new_on_generate=False)
        except hou.Error:
            _end("the viewport left the node's network", leave_viewer=False)
    except Exception:
        _note(traceback.format_exc())


__all__ = ["enter_points", "enter_draw", "exit_tool", "set_mode", "set_locks", "set_new_lock", "current_tool",
           "running", "register", "yield_to_paint", "paint_ended", "STATS", "STATE", "LABEL"]
