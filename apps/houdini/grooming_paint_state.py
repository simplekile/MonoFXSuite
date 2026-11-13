"""
The mask brush of MONO Grooming (v0.2a): a Python viewer state, entered by `grooming_adapter.paint_enter`.

It touches no node inside the locked HDA. It reads the fine scalp (`SCALP_FINE`), keeps the layer in numpy
while the button is down (`grooming_masks.PaintSession`) and writes the node's `mask_layers` parm once on
release: one undo step a stroke, and nothing cooks while the brush moves, so it follows the mouse whatever
the hair costs. The scalp is drawn coloured by the factor (grey 1, blue towards 0, red towards 2+), the
brush as a ring on the skin. Ctrl paints the other way round (erase while painting, paint while erasing),
Esc leaves Paint.

Houdini drops a state entered by name when the node is selected again (it enters the node's own state on
its next event loop): while Paint is on, the state comes back by itself (`_came_back`), so no stroke is lost.
"""

from __future__ import annotations

import time
import traceback

import hou

from apps.houdini import grooming_masks as gm
from tools.fx.grooming import config, logic

STATE = config.PAINT_STATE
LABEL = "MONO Grooming: Paint mask"
LIVE: dict = {}      # "state": the running state object, "prev": the viewer's state before Paint
# what tests read: one dict a stroke, counters, errors (a state's exception only reaches Houdini's console)
STATS: dict = {"strokes": [], "events": 0, "enters": 0, "exits": 0, "came_back": 0, "errors": []}
REENTER_MAX = 6      # times the state comes back within REENTER_WINDOW_S before Paint is given up
REENTER_WINDOW_S = 2.0
# states the artist picks by hand: going to one of them ends Paint. Anything else (the node's own state,
# which Houdini enters when the node is selected) is not a choice of tool, and the brush comes back
USER_STATES = ("select", "view", "scriptselect", "xform", "edit", "scenegraphselect")


def _np():
    import numpy as np
    return np


def colours(factor):
    """Final factor per point -> the scalp's colour (logic.mask_color, on arrays)."""
    np = _np()
    m = np.asarray(factor, np.float32)
    lo = np.clip(1.0 - m, 0.0, 1.0)[:, None]
    hi = np.clip(m - 1.0, 0.0, 1.0)[:, None]
    one = np.array(logic.MASK_COLOR_ONE, np.float32)
    zero = np.array(logic.MASK_COLOR_ZERO, np.float32)
    more = np.array(logic.MASK_COLOR_MORE, np.float32)
    return (one + (zero - one) * lo + (more - one) * hi).astype(np.float32)


def _viewer():
    return hou.ui.paneTabOfType(hou.paneTabType.SceneViewer) if hou.isUIAvailable() else None


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
        self.dots = None
        self.root_count = 0

    # ---- entering and leaving ----
    def onEnter(self, kwargs):
        self._setup()

    def onGenerate(self, kwargs):      # entered by name (setCurrentState): no node in kwargs
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
        node.addEventCallback((hou.nodeEventType.ParmTupleChanged,), self._parm_changed)
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

    def reroot(self, cook: bool | None = None) -> None:
        """Count the groom's roots again for the "density" and "roots" views (after a stroke's cook, an
        undo, entering, a change of view) and show the dots in the "roots" view. `cook` None: grow what is
        missing only when the whole groom was counted before (then a stroke's locks are all that miss)."""
        dots = getattr(self, "dots", None)
        if dots is None or self.node is None or self.session is None:
            return
        view = gm.BRUSH["view"]
        if view in ("density", "roots"):
            self.session.measure(self.session.whole if cook is None else cook)
        roots = self.session.roots if view == "roots" else ()
        self.root_count = int(len(roots))
        geo = hou.Geometry()
        if len(roots):
            geo.createPoints(((0.0, 0.0, 0.0),) * len(roots))
            geo.setPointFloatAttribValuesFromString("P", roots.tobytes())
        self.root_geo = geo
        dots.setGeometry(geo)
        dots.show(bool(len(roots)))

    def brush_changed(self) -> None:
        if self.draw is not None:
            self.draw.setXray(bool(gm.BRUSH["xray"]))
            if self.session is not None and not self.down:
                # the view may have changed; one chosen by hand may grow the hair it needs to count
                self.reroot(cook=True if gm.BRUSH.pop("count_roots", False) else None)
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
            gm.paint_exit()
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
        t0 = time.perf_counter()
        STATS["events"] += 1
        dev = ui_event.device()
        origin, direction = ui_event.ray()
        origin = origin * self.inverse
        direction = direction.multiplyAsDir(self.inverse)
        pos, nrm, uvw = hou.Vector3(), hou.Vector3(), hou.Vector3()
        hit = self.isect.intersect(origin, direction, pos, nrm, uvw) >= 0
        radius = gm.BRUSH["radius_cm"] / self.session.unit_cm
        self.last_hit = tuple(pos) if hit else None
        if hit:
            z = nrm.normalized()
            x = z.cross(hou.Vector3(0, 1, 0) if abs(z[1]) < 0.9 else hou.Vector3(1, 0, 0)).normalized()
            y = z.cross(x)
            lift = z * (0.02 * radius)     # just off the skin, so the ring is not half inside it
            self.ring.setTransform(hou.Matrix4((
                (x[0] * radius, x[1] * radius, x[2] * radius, 0), (y[0] * radius, y[1] * radius, y[2] * radius, 0),
                (z[0], z[1], z[2], 0), (pos[0] + lift[0], pos[1] + lift[1], pos[2] + lift[2], 1))) * self.xform)
        self.ring.show(hit)
        left = dev.isLeftButton()
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

    def _end_stroke(self) -> None:
        self.down = False
        c, self.cur = self.cur, None
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
        return
    LIVE["leaving"] = True
    try:
        prev = LIVE.get("prev") or "select"
        with hou.undos.disabler():
            try:
                viewer.setCurrentState(prev)
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
        if node is None or current in USER_STATES or len(recent) >= REENTER_MAX:
            gm.PAINT["node"], gm.PAINT["layer"] = None, None
            hook = gm.HOOKS.get("exit")
            if hook is not None:
                hook()
            return
        LIVE["reenters"] = recent + [now]
        STATS["came_back"] += 1
        STATS["came_back_from"] = current
        with hou.undos.disabler():
            viewer.setCurrentState(STATE, request_new_on_generate=False)
    except Exception:
        _note(traceback.format_exc())
