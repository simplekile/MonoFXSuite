"""
The mask brush of MONO Grooming (v0.2a): a Python viewer state, entered by `grooming_adapter.paint_enter`.

It touches no node inside the locked HDA. It reads the fine scalp (`SCALP_FINE`), keeps the layer in numpy
while the button is down (`grooming_masks.PaintSession`) and writes the node's `mask_layers` parm once on
release: one undo step a stroke, and nothing cooks while the brush moves, so it follows the mouse whatever
the hair costs. The scalp is drawn coloured by the view (the density, or the layer's mask alone), the
brush as a ring on the skin. Ctrl paints the other way round (erase while painting, paint while erasing),
Esc leaves Paint.

Houdini drops a state entered by name when the node is selected again (it enters the node's own state on
its next event loop): while Paint is on, the state comes back by itself (`_came_back`), so no stroke is lost.

Paint belongs to the node being painted and to nothing else (round 3, after the second check): it is on only
while that node is the selection. Another node selected, in its network or any other, or no node selected
ends it (`_not_ours`: `_came_back` does not bring the brush back, and a stroke never starts), and Esc ends
it from anywhere in Houdini's window, with the mouse held too: an application event filter (`_EscFilter`)
sees the key, since a state gets no key event while a button is down; the stroke in progress is stored first.

Like Houdini's Attribute Paint (v0.2a last task, decided 2026-11-19; what it shows and how the keys move the
brush is `tools.fx.grooming.brush_keys`): a hint overlay (HUD) with the keys and the live brush values
(Shift+F1 hides it), a parameter bar above the viewport (Radius, Softness, Grey, Eraser), the mouse wheel and
Ctrl+Shift+LMB drag for the radius, F (a hotkey of the state's menu) swaps paint / erase, and a right-click
menu with the same and radius / grey picks. All of it goes through `grooming_masks.set_brush(source="state")`:
one source for the bar, the HUD and the panel's Properties. A brush change is view state: no undo step, no
cook. The bar is written from the brush only outside the read-only callbacks (`onMouseEvent`: Houdini does not
show a parm written there), deferred and coalesced (`_queue_show`); writing a state parm from code calls no
`onParmChangeEvent` (spike t72), and `brush_keys.field_change` ignores a value the brush already has.
"""

from __future__ import annotations

import time
import traceback

import hou

from apps.houdini import grooming_masks as gm
from tools.fx.grooming import brush_keys as bk
from tools.fx.grooming import config

STATE = config.PAINT_STATE
LABEL = "MONO Grooming: Paint mask"
HOTKEY_CONTEXT = "h.pane.gview.state.sop." + STATE
LIVE: dict = {}      # "state": the running state object, "prev": the viewer's state before Paint
# what tests read: one dict a stroke, counters, errors (a state's exception only reaches Houdini's console)
STATS: dict = {"strokes": [], "events": 0, "enters": 0, "exits": 0, "came_back": 0, "errors": [], "esc": 0,
               "ended_by_selection": 0, "refused_strokes": 0}
ESC_PAIR_S = 0.5     # a KeyPress of Esc this soon after the ShortcutOverride that ended Paint is the same key
REENTER_MAX = 6      # times the state comes back within REENTER_WINDOW_S before Paint is given up
REENTER_WINDOW_S = 2.0
# states the artist picks by hand: going to one of them ends Paint. Anything else (the node's own state,
# which Houdini enters when the node is selected) is not a choice of tool, and the brush comes back
USER_STATES = ("select", "view", "scriptselect", "xform", "edit", "scenegraphselect")


def _np():
    import numpy as np
    return np


def _viewer():
    return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer) if hou.isUIAvailable() else None


def _others_selected(node) -> list:
    """Selected nodes that are not the painted node, in ANY network: Paint is not theirs. (The networks the
    node sits in are left out: the object holding it may stay selected in /obj.) A node of another network
    (an object in /obj) used to be missed: Paint stayed on, the drag painted nothing, and coming back raised
    "Failed setting state" (t64 B8)."""
    path = node.path()
    return [n for n in hou.selectedNodes() if n != node and not path.startswith(n.path() + "/")]


def _not_ours(node) -> str:
    """Why Paint cannot go on on `node` ("" when it can): it is the painted node's only while that node is
    the selection."""
    if _others_selected(node):
        return "another node is selected"
    if not node.isSelected():
        return "the node is no longer selected"
    return ""


def _say_ended(why: str) -> None:
    try:
        hou.ui.setStatusMessage("MONO Grooming: Paint ended, " + why, hou.severityType.Message)
    except hou.Error:
        pass


def _end_paint(why: str, said: str = "another node is selected") -> None:
    """Paint off without the artist asking (another node was selected, or none is): said on the status bar."""
    STATS[why] = STATS.get(why, 0) + 1
    gm.paint_exit()
    _say_ended(said)


def esc() -> None:
    """Esc: leave Paint and keep what was painted, the stroke the mouse still holds too. Paint is off FIRST:
    storing the stroke cooks the node, and a cook runs Qt's event loop (Houdini's interrupt check), so with
    Paint still on during it the brush stayed on for as long as the cook took (a stroke over 4,000 points:
    Paint still on 0.3 s after Esc, t66 B8(b)); the cook then ran with Paint already over."""
    t0 = time.perf_counter()
    state = LIVE.get("state")
    pending = state is not None and state.down
    gm.PAINT["node"], gm.PAINT["layer"] = None, None      # off now: no dab from here on (_mouse), paint_layer None
    STATS["esc_off_s"] = time.perf_counter() - t0
    if pending:
        try:
            state._end_stroke()
        except Exception:
            _note(traceback.format_exc())
    gm.paint_exit()


def _qt():
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets
    return QtCore, QtWidgets


def _esc_filter():
    """The application event filter that turns Esc into `esc()` while Paint is on (made once a session). A
    viewer state gets no key event while a mouse button is down, and none when another pane has the
    keyboard: Esc with the mouse held left the brush on (checks t60, t61). Esc typed in a text field is
    left to the field."""
    got = LIVE.get("esc_filter")
    if got is not None:
        return got
    QtCore, QtWidgets = _qt()

    class _EscFilter(QtCore.QObject):
        def eventFilter(self, obj, event):
            try:
                kind = event.type()
                # a key press arrives as ShortcutOverride first, and where Houdini has Esc as a shortcut
                # (the network editor, a pane with the keyboard) the KeyPress never follows: Houdini then
                # ended the drag itself and Paint stayed on until the button was up (t64 B8). Both count;
                # the KeyPress that may follow a ShortcutOverride we took is swallowed
                if kind not in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) or \
                        event.key() != QtCore.Qt.Key_Escape:
                    return False
                STATS["esc_seen"] = STATS.get("esc_seen", []) + [(
                    "override" if kind == QtCore.QEvent.ShortcutOverride else "press", type(obj).__name__,
                    type(QtWidgets.QApplication.focusWidget()).__name__, gm.PAINT["node"] is not None,
                    LIVE.get("state") is not None, bool(getattr(LIVE.get("state"), "down", False)))][-12:]
                if gm.PAINT["node"] is None or LIVE.get("state") is None:
                    took = LIVE.get("esc_took", 0.0)
                    if kind == QtCore.QEvent.KeyPress and time.perf_counter() - took < ESC_PAIR_S:
                        LIVE["esc_took"] = 0.0
                        return True
                    return False
                focus = QtWidgets.QApplication.focusWidget()
                if isinstance(focus, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
                    return False
                STATS["esc"] += 1
                if kind == QtCore.QEvent.ShortcutOverride:
                    LIVE["esc_took"] = time.perf_counter()
                    event.accept()
                esc()
                return True
            except Exception:
                _note(traceback.format_exc())
                return False

    LIVE["esc_filter"] = _EscFilter()
    return LIVE["esc_filter"]


def _watch_esc(on: bool) -> None:
    try:
        QtCore, QtWidgets = _qt()
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        if on and not LIVE.get("esc_on"):
            app.installEventFilter(_esc_filter())
            LIVE["esc_on"] = True
        elif not on and LIVE.get("esc_on"):
            app.removeEventFilter(_esc_filter())
            LIVE["esc_on"] = False
    except Exception:
        _note(traceback.format_exc())


def _note(exc_text: str) -> None:
    STATS["errors"].append(exc_text)
    del STATS["errors"][:-20]


class MaskPaint(object):
    def __init__(self, state_name, scene_viewer):
        self.state_name = state_name
        self.scene_viewer = scene_viewer
        self.session = None
        self.node = None
        self.down = False
        self.stale = False
        self.writing = False
        self.cur = None
        self.draw = None
        self.ring = None
        self.last_hit = None      # where the cursor's ray last met the skin (object space), None off it
        self.last_frame = None    # (pos, normal) of that hit, for the ring
        self.dots = None
        self.root_count = 0
        self.parms = None         # the bar's state_parms (Houdini's dict, kept from onEnter / onGenerate)
        self.drag = None          # Ctrl+Shift+LMB: {"x": px at the press, "radius": cm then, "at": (pos, nrm)}
        self.show_queued = False

    # ---- entering and leaving ----
    def onEnter(self, kwargs):
        self.parms = kwargs.get("state_parms")
        self._setup()

    def onGenerate(self, kwargs):      # entered by name (setCurrentState): no node in kwargs
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
        node = hou.node(gm.PAINT["node"]) if gm.PAINT["node"] else None
        if node is None or gm.PAINT["layer"] is None:
            return                     # entered by hand from the tool list: nothing to paint on
        self.node = node
        self.session = gm.PaintSession(node, gm.PAINT["layer"])
        scalp = self.session.scalp
        self.isect = scalp.freeze()
        self.xform = node.parent().worldTransform() if hasattr(node.parent(), "worldTransform") \
            else hou.hmath.identityTransform()
        self.inverse = self.xform.inverted()
        self.geo = hou.Geometry()
        self.geo.merge(scalp)
        self.geo.addAttrib(hou.attribType.Point, "Cd", (1.0, 1.0, 1.0))
        self.draw = hou.SimpleDrawable(self.scene_viewer, self.geo, STATE + "_scalp")
        self.draw.setDisplayMode(hou.drawableDisplayMode.CurrentViewportMode)
        self.draw.setTransform(self.xform)
        self.draw.setXray(bool(gm.BRUSH["xray"]))
        self.draw.enable(True)
        self.draw.show(True)
        np = _np()
        ring = hou.Geometry()
        pts = ring.createPoints([(float(np.cos(a)), float(np.sin(a)), 0.0)
                                 for a in np.linspace(0, 2 * np.pi, 49)[:-1]])
        poly = ring.createPolygon(is_closed=True)
        for p in pts:
            poly.addVertex(p)
        self.ring = hou.GeometryDrawable(self.scene_viewer, hou.drawableGeometryType.Line, STATE + "_ring",
                                         params={"color1": hou.Vector4(1, 1, 1, 1), "line_width": 2.0})
        self.ring.setGeometry(ring)
        self.ring.show(False)
        # the roots the display grew, as dots on the skin (set_brush(roots=True))
        self.dots = hou.GeometryDrawable(self.scene_viewer, hou.drawableGeometryType.Point, STATE + "_roots",
                                         params={"color1": hou.Vector4(1.0, 1.0, 1.0, 1.0), "radius": 2.0,
                                                 "style": hou.drawableGeometryPointStyle.LinearCircle})
        self.dots.setTransform(self.xform)
        self.reroot(cook=False)       # entering never cooks: what the cache holds, or the density asked
        self.recolour()
        self.view_shown = gm.BRUSH["view"]
        gm.BRUSH.pop("count_roots", None)
        node.addEventCallback((hou.nodeEventType.ParmTupleChanged,), self._parm_changed)
        _watch_esc(True)
        try:
            self.scene_viewer.hudInfo(template=bk.hud_template())
            self.show_brush()
        except Exception:
            _note(traceback.format_exc())
        STATS["enter_s"] = time.perf_counter() - t0

    def onExit(self, kwargs):
        STATS["exits"] += 1
        self._close()
        if LIVE.get("state") is self:
            LIVE.pop("state", None)
        if gm.PAINT["node"] is not None and not LIVE.get("leaving"):
            # not our own leave: the node was selected again, or the artist picked another tool
            import hdefereval
            hdefereval.executeDeferred(_came_back)

    def _close(self) -> None:
        if self.down:                  # the tool was taken away mid-stroke: keep what was painted
            self._end_stroke()
        if gm.PAINT["node"] is None:   # Paint is over (not the brush about to come back): no more Esc watch
            _watch_esc(False)
        if self.node is not None:
            try:
                self.node.removeEventCallback((hou.nodeEventType.ParmTupleChanged,), self._parm_changed)
            except (hou.Error, ValueError):
                pass
        for d in (self.draw, self.ring, getattr(self, "dots", None)):
            if d is not None:
                d.show(False)
        if self.draw is not None:
            self.draw.enable(False)

    def onInterrupt(self, kwargs):
        if self.ring is not None:
            self.ring.show(False)

    # ---- what the node holds changed under us (undo, redo, the panel's layer row) ----
    def _parm_changed(self, node=None, event_type=None, parm_tuple=None, **kwargs):
        if self.writing or parm_tuple is None:
            return
        if parm_tuple.name() in (config.MASK_PARM, config.DATA_PARM):
            self.stale = True
            import hdefereval
            hdefereval.executeDeferred(self.refresh)

    def refresh(self) -> None:
        """Take what the node holds now (not during a stroke: the stroke wins and is written on release)."""
        if self.session is None or self.down or not self.stale:
            return
        try:
            self.stale = False
            self.session.reload()
            if self.session.layer() is None:      # the layer is gone (its Add was undone, or it was deleted)
                gm.paint_exit()
                # said out loud: the scalp's colours vanish with the brush, which reads as a fault
                hou.ui.setStatusMessage("MONO Grooming: Paint ended, the layer being painted is gone "
                                        "(undone or deleted); redo brings it back", hou.severityType.ImportantMessage)
                return
            if self.node.isDisplayFlagSet():
                self.node.cook()               # an undo from outside: the display's hair, then its roots
            self.reroot()
            self.recolour()
        except Exception:
            _note(traceback.format_exc())

    def recolour(self) -> None:
        self.geo.setPointFloatAttribValuesFromString("Cd", self.session.colours(gm.BRUSH["view"]).tobytes())
        # a fresh copy: handed the same hou.Geometry again the drawable keeps the old colours
        self.draw.setGeometry(hou.Geometry(self.geo))

    def reroot(self, cook: bool = False) -> None:
        """Count the groom's roots again for the "density" and "roots" views and show the dots in the
        "roots" view. Without `cook` (after a stroke, an undo, entering) nothing is grown for it: when the
        display holds the hair (Hair) the count is new, else (Guides, Hair preview) the last count stays
        and the density view goes on from it by the factor's change, so a stroke in Guides costs no hair.
        `cook` (the view chosen by hand, `recount`) grows what is missing and counts."""
        dots = getattr(self, "dots", None)
        if dots is None or self.node is None or self.session is None:
            return
        view = gm.BRUSH["view"]
        if view in ("density", "roots"):
            self.session.measure(cook)
        roots = self.session.roots if view == "roots" else ()
        self.root_count = int(len(roots))
        geo = hou.Geometry()
        if len(roots):
            geo.createPoints(((0.0, 0.0, 0.0),) * len(roots))
            geo.setPointFloatAttribValuesFromString("P", roots.tobytes())
        self.root_geo = geo
        dots.setGeometry(geo)
        dots.show(bool(len(roots)))

    # ---- the brush shown: HUD and bar (one source: grooming_masks.BRUSH) ----
    def layer_name(self) -> str:
        try:
            layer = self.session.layer() if self.session is not None else None
            return layer.name if layer is not None else ""
        except Exception:
            return ""

    def show_brush(self) -> None:
        """The HUD's values and the bar's parms from the brush now (no undo, no cook)."""
        self.show_queued = False
        if self.session is None or LIVE.get("state") is not self:
            return
        brush = dict(gm.BRUSH)
        self.scene_viewer.hudInfo(values=bk.hud_values(brush, self.layer_name()))
        if self.parms is not None:
            for name, value in bk.bar_values(brush).items():
                try:
                    now = self.parms[name]["value"]
                except (KeyError, TypeError):
                    continue
                if now != value:
                    self.parms[name]["value"] = value
        STATS["shown"] = STATS.get("shown", 0) + 1

    def _queue_show(self) -> None:
        """Show the brush from Houdini's event loop, once for any number of changes before it runs."""
        if self.show_queued:
            return
        self.show_queued = True
        import hdefereval
        hdefereval.executeDeferred(self._show_deferred)

    def _show_deferred(self) -> None:
        try:
            self.show_brush()
        except Exception:
            _note(traceback.format_exc())

    def set_brush(self, **fields) -> None:
        """A brush change made in the viewport (bar, wheel, drag, F, menu): the panel hears of it by its hook."""
        if fields:
            gm.set_brush(source="state", **fields)

    def onParmChangeEvent(self, kwargs):
        try:
            self.set_brush(**bk.field_change(kwargs["parm_name"], kwargs["parm_value"], gm.BRUSH))
        except Exception:
            _note(traceback.format_exc())

    def onMenuAction(self, kwargs):
        try:
            STATS["menu"] = (STATS.get("menu", []) + [kwargs["menu_item"]])[-20:]
            self.set_brush(**bk.menu_fields(kwargs["menu_item"], gm.BRUSH))
        except Exception:
            _note(traceback.format_exc())

    def onMouseWheelEvent(self, kwargs):
        """The wheel sizes the brush. Consumed: the camera does not dolly while painting (MMB / Alt move it)."""
        if self.session is None or gm.PAINT["node"] is None:
            return False
        try:
            notches = kwargs["ui_event"].device().mouseWheel()
            STATS["wheel"] = STATS.get("wheel", 0) + 1
            self.set_brush(radius_cm=bk.wheel_radius(gm.BRUSH["radius_cm"], notches))
            self._ring_again()
        except Exception:
            _note(traceback.format_exc())
        return True

    def _ring_again(self) -> None:
        at = self.drag["at"] if self.drag is not None else self.last_frame
        if at is not None and self.ring is not None:
            self._place_ring(*at)
            self.scene_viewer.curViewport().draw()

    def brush_changed(self) -> None:
        if self.session is not None:
            self._queue_show()
        if self.draw is not None:
            self.draw.setXray(bool(gm.BRUSH["xray"]))
            view = gm.BRUSH["view"]
            if self.session is not None and not self.down and (view != getattr(self, "view_shown", None)
                                                               or "count_roots" in gm.BRUSH):
                # the view changed; one chosen by hand may grow the hair it needs to count. A radius, grey,
                # softness or mode change (the wheel, a drag) costs no recount and no recolour
                self.view_shown = view
                self.reroot(cook=bool(gm.BRUSH.pop("count_roots", False)))
                self.recolour()
            self.scene_viewer.curViewport().draw()

    # ---- drawing and input ----
    def onDraw(self, kwargs):
        if getattr(self, "dots", None) is not None:
            self.dots.draw(kwargs["draw_handle"])
        if self.ring is not None:
            self.ring.draw(kwargs["draw_handle"])

    def onKeyEvent(self, kwargs):
        if kwargs["ui_event"].device().keyString() == "Esc":
            esc()
            return True
        return False

    def onMouseEvent(self, kwargs):
        try:
            return self._mouse(kwargs["ui_event"])
        except Exception:
            _note(traceback.format_exc())
            raise

    def _mouse(self, ui_event) -> bool:
        if self.session is None:
            return False
        if gm.PAINT["node"] is None:
            # Paint is over (Esc with the mouse held: Houdini keeps the state until the button is up): no
            # dab, and the tool goes back as soon as it can
            if self.ring is not None:
                self.ring.show(False)
            import hdefereval
            hdefereval.executeDeferred(leave)
            return False
        t0 = time.perf_counter()
        STATS["events"] += 1
        dev = ui_event.device()
        origin, direction = ui_event.ray()
        origin = origin * self.inverse
        direction = direction.multiplyAsDir(self.inverse)
        pos, nrm, uvw = hou.Vector3(), hou.Vector3(), hou.Vector3()
        hit = self.isect.intersect(origin, direction, pos, nrm, uvw) >= 0
        self.last_hit = tuple(pos) if hit else None
        left = dev.isLeftButton()
        if self.drag is not None:
            # Ctrl+Shift+LMB drag: the radius follows the mouse right (larger) / left, the ring stays put
            if left:
                self.set_brush(radius_cm=bk.drag_radius(self.drag["radius"], dev.mouseX() - self.drag["x"]))
                self._place_ring(*self.drag["at"])
            else:
                STATS["drags"] = STATS.get("drags", 0) + 1
                self.drag = None
            return True
        if hit:
            self.last_frame = (hou.Vector3(pos), hou.Vector3(nrm))
            self._place_ring(pos, nrm)
        self.ring.show(hit)
        why = _not_ours(self.node) if left and not self.down else ""
        if why:
            # another node is selected, or none: this click is not for the painted node
            STATS["refused_strokes"] += 1
            _end_paint("ended_by_selection", why)
            return False
        if left and not self.down and dev.isCtrlKey() and dev.isShiftKey():
            if hit:      # sizing, not painting: no stroke starts
                self.drag = {"x": dev.mouseX(), "radius": gm.BRUSH["radius_cm"], "at": self.last_frame}
            return True
        if left and not self.down:
            self.refresh()
            self.down = True
            self.session.begin()
            self.cur = {"t0": t0, "events": 0, "dabs": 0, "points": 0, "handler_ms": []}
        if self.down and left:
            self.cur["events"] += 1
            if hit:
                erase = bool(gm.BRUSH["erase"]) != bool(dev.isCtrlKey())
                reached = self.session.stroke_to(tuple(pos), tuple(nrm), gm.BRUSH["radius_cm"],
                                                 value=gm.BRUSH["value"], soft=gm.BRUSH["soft"], erase=erase)
                if reached:
                    self.cur["dabs"] += 1
                    self.cur["points"] += reached
                    self.cur["erase"] = erase
                    self.recolour()
            self.cur["handler_ms"].append((time.perf_counter() - t0) * 1000.0)
        if self.down and not left:
            self._end_stroke()
        return bool(left or self.down)

    def _place_ring(self, pos, nrm) -> None:
        radius = gm.BRUSH["radius_cm"] / self.session.unit_cm
        z = nrm.normalized()
        x = z.cross(hou.Vector3(0, 1, 0) if abs(z[1]) < 0.9 else hou.Vector3(1, 0, 0)).normalized()
        y = z.cross(x)
        lift = z * (0.02 * radius)     # just off the skin, so the ring is not half inside it
        self.ring.setTransform(hou.Matrix4((
            (x[0] * radius, x[1] * radius, x[2] * radius, 0), (y[0] * radius, y[1] * radius, y[2] * radius, 0),
            (z[0], z[1], z[2], 0), (pos[0] + lift[0], pos[1] + lift[1], pos[2] + lift[2], 1))) * self.xform)

    def _end_stroke(self) -> None:
        self.down = False
        c, self.cur = self.cur, None
        if c is None:
            return
        t = time.perf_counter()
        self.writing = True
        try:
            wrote = self.session.commit("Erase mask" if c.get("erase") else "Paint mask")   # one undo step
        finally:
            self.writing = False
        c["wrote"] = wrote
        c["write_s"] = time.perf_counter() - t
        if wrote:
            t = time.perf_counter()
            hook = gm.HOOKS.get("stroke")
            try:
                if hook is not None:
                    hook(self.node)            # the panel cooks inside its loading line
                elif self.node.isDisplayFlagSet():
                    self.node.cook()
            except hou.Error:
                pass                           # a cook error stays on the node
            c["cook_s"] = time.perf_counter() - t
            t = time.perf_counter()
            self.reroot()
            self.recolour()
            c["count_s"] = time.perf_counter() - t
        hm = c.pop("handler_ms")
        c["drag_s"] = t - c.pop("t0")
        c["handler_ms_median"] = float(sorted(hm)[len(hm) // 2]) if hm else 0.0
        c["handler_ms_max"] = float(max(hm)) if hm else 0.0
        STATS["strokes"].append(c)
        del STATS["strokes"][:-200]


# ---------------------------------------------------------------------------
# registered and driven by grooming_masks.paint_enter / paint_exit
# ---------------------------------------------------------------------------

def register(force: bool = False) -> None:
    """Register the state once a session (again with `force`, after this module was reloaded)."""
    if hou.ui.isRegisteredViewerState(STATE):
        if not force:
            return
        hou.ui.unregisterViewerState(STATE)
    template = hou.ViewerStateTemplate(STATE, LABEL, hou.sopNodeTypeCategory())
    template.bindFactory(MaskPaint)
    template.bindIcon("SOP_paint")
    # the bar above the viewport: the panel's Radius, Softness, Grey, Eraser (one source, gm.BRUSH)
    limits = {"radius": (bk.RADIUS_MIN_CM, bk.RADIUS_BAR_MAX_CM), "soft": (0.0, 1.0), "grey": (0.0, 1.0)}
    defaults = bk.bar_values(gm.BRUSH)
    for field, name, label in bk.BAR:
        if field == "erase":
            template.bindParameter(hou.parmTemplateType.Toggle, name=name, label=label,
                                   default_value=defaults[name], help="Take the layer's paint away (F swaps)")
        else:
            lo, hi = limits[name]
            template.bindParameter(hou.parmTemplateType.Float, name=name, label=label, min_limit=lo,
                                   max_limit=hi, default_value=defaults[name])
    # F swaps paint / erase: a hotkey of the state's menu (Houdini's own F, frame, is not run then)
    keys = hou.PluginHotkeyDefinitions()
    keys.addContext(HOTKEY_CONTEXT, LABEL, "The mask brush of MONO Grooming")
    keys.addCommandCategory(HOTKEY_CONTEXT, LABEL, "The mask brush of MONO Grooming")
    keys.addCommand(HOTKEY_CONTEXT + "." + bk.SWAP, "Paint / Erase", "Swap painting and erasing")
    keys.addDefaultBinding(HOTKEY_CONTEXT, HOTKEY_CONTEXT + "." + bk.SWAP, [bk.SWAP_KEY])
    template.bindHotkeyDefinitions(keys)
    menu = hou.ViewerStateMenu(STATE + "_menu", LABEL)
    subs: dict = {}
    for sub, item, text in bk.menu_items():
        if not sub:
            menu.addActionItem(item, text, hotkey=HOTKEY_CONTEXT + "." + item if item == bk.SWAP else "")
            continue
        if sub not in subs:
            subs[sub] = hou.ViewerStateMenu(STATE + "_" + sub.lower(), sub)
        subs[sub].addActionItem(item, text)
    for sub in subs.values():
        menu.addMenu(sub)
    template.bindMenu(menu)
    hou.ui.registerViewerState(template)


def running():
    """The state object while the brush is the viewport's tool, else None."""
    viewer = _viewer()
    state = LIVE.get("state")
    return state if state is not None and viewer is not None and viewer.currentState() == STATE else None


def enter(node) -> bool:
    """Make the brush the viewport's tool on `gm.PAINT`'s node and layer. True when it is running."""
    viewer = _viewer()
    if viewer is None:
        return False
    register()
    # no undo step for changing tool: Houdini records "Change selection" for these, and such a step between
    # two strokes made Ctrl+Z undo a tool change (dropping the brush) and, recorded after an undo, emptied redo
    with hou.undos.disabler():
        if viewer.pwd() != node.parent():
            viewer.setPwd(node.parent())           # a SOP state needs the viewer inside the node's network
        if _not_ours(node):
            # Paint is this node's: it becomes the selection (Houdini then enters the node's own state on
            # its next event loop, and the brush comes back: _came_back)
            node.setSelected(True, clear_all_selected=True)
        current = viewer.currentState()
        if current != STATE:
            LIVE["prev"] = current
        state = running()
        if state is not None:                      # already painting: another layer, or another node
            state._close()
            state.__init__(state.state_name, state.scene_viewer)
            state._setup()
        else:
            viewer.setCurrentState(STATE, request_new_on_generate=False)
    return running() is not None and running().session is not None


def leave() -> None:
    """Back to the tool the viewport had before Paint (grooming_masks.paint_exit cleared PAINT)."""
    viewer = _viewer()
    if viewer is None or viewer.currentState() != STATE:
        if gm.PAINT["node"] is None:
            _watch_esc(False)
        return
    LIVE["leaving"] = True
    try:
        prev = LIVE.get("prev") or "select"
        with hou.undos.disabler():
            try:
                if prev in USER_STATES or prev == "sopview":
                    viewer.setCurrentState(prev)
                else:
                    # the tool before Paint was a node's own state (the grooming node selected). Entered by
                    # NAME, a node state generates: Houdini made a second MONO Grooming node on every such
                    # exit. The viewer goes to the current node's state instead, which makes nothing
                    viewer.enterCurrentNodeState()
            except hou.Error:
                viewer.setCurrentState("select")
    finally:
        LIVE["leaving"] = False
    hook = gm.HOOKS.get("exit")
    if hook is not None:
        hook()


def brush_changed() -> None:
    state = running()
    if state is not None:
        state.brush_changed()


def _came_back() -> None:
    """After Houdini took the state away while Paint is on. The node selected again (the viewer goes to the
    node's own state): the brush comes back. The artist picked a tool (USER_STATES): Paint is off."""
    try:
        viewer = _viewer()
        if viewer is None or gm.PAINT["node"] is None:
            return
        current = viewer.currentState()
        if current == STATE:
            return
        node = hou.node(gm.PAINT["node"])
        now = time.perf_counter()
        recent = [t for t in LIVE.get("reenters", []) if now - t < REENTER_WINDOW_S]
        # another node selected (in any network), or none: Houdini went to that node's state, and the brush
        # must not come back over it
        other = _not_ours(node) if node is not None else ""
        if other:
            STATS["ended_by_selection"] += 1
        if node is None or current in USER_STATES or len(recent) >= REENTER_MAX or other:
            _paint_over(other)
            return
        LIVE["reenters"] = recent + [now]
        STATS["came_back"] += 1
        STATS["came_back_from"] = current
        try:
            with hou.undos.disabler():
                if viewer.pwd() != node.parent():
                    viewer.setPwd(node.parent())
                viewer.setCurrentState(STATE, request_new_on_generate=False)
        except hou.Error:
            # the viewer cannot take the brush (it looks at another network): Paint is off, not half on
            # (`paint_layer` said 1 with no brush, and every later event raised again)
            STATS["came_back_failed"] = STATS.get("came_back_failed", 0) + 1
            _paint_over("the viewport left the node's network")
    except Exception:
        _note(traceback.format_exc())


def _paint_over(why: str = "") -> None:
    """Paint is off although nobody called paint_exit (the brush cannot or must not come back)."""
    gm.PAINT["node"], gm.PAINT["layer"] = None, None
    _watch_esc(False)
    if why:
        _say_ended(why)
    hook = gm.HOOKS.get("exit")
    if hook is not None:
        hook()
