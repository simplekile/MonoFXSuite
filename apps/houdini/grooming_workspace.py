"""
MONO Grooming's workspace in Houdini (v0.2a last task; the entries and what they call:
`tools.fx.grooming.workspace`).

- `radial(entry)`: what the radial menu "MONO Grooming" runs. It finds the open panel's controller (the
  same function as the panel's button) or, without a panel, a controller on the scene's MONO Grooming node
  whose messages go to Houdini's status line; with no such node it says so on the status line, never raises.
- `radial_on()` / `radial_off()`: the panel shown puts the viewport's radial menu (key C) on "MONO Grooming"
  and remembers the user's; the last panel hidden (closed, or its desktop left) puts the user's back, unless
  the user picked another meanwhile. Houdini 22 has no public call for it: `hou.ui._setActiveRadialMenu` /
  `_getActiveRadialMenu` (spike t72). Without them both return False and the panel asks the user once to
  pick it by hand (the plan's fallback). A desktop's own `radial menu set` line is not used: switching back
  to the user's desktop did not put their radial menu back (spike t72).
- `open_workspace()` / `leave_workspace()`: the desktop "MONO_Grooming" (`desktop/MONO_Grooming.desk`), and
  back to the desktop the user had before. The user picks the desktop from Houdini's desktop list; these are
  for scripts and tests.
"""

from __future__ import annotations

import traceback

import hou

from tools.fx.grooming import workspace as ws

_KEPT = "_mono_grooming_workspace"      # on hou.session: survives a reload of this module


def _kept() -> dict:
    got = getattr(hou.session, _KEPT, None)
    if got is None:
        got = {"radial_before": None, "desk_before": None, "errors": []}
        setattr(hou.session, _KEPT, got)
    return got


def _status(text: str, error: bool = False) -> None:
    try:
        hou.ui.setStatusMessage(text, hou.severityType.Warning if error else hou.severityType.Message)
    except Exception:
        pass


class StatusView:
    """A controller's view without a panel: the message line is Houdini's status line, the rest does nothing."""

    def set_message(self, text: str, error: bool = False) -> None:
        if text:
            _status("MONO Grooming: " + text if not text.startswith("MONO Grooming") else text, error)

    def __getattr__(self, name):
        return lambda *a, **k: None


def _panels() -> list:
    from tools.fx.grooming import controller as ctl
    return ctl.live_panels()


def controller():
    """The open panel's controller (a visible one first), else one without a panel on the scene's MONO
    Grooming node, else None."""
    panels = _panels()
    shown = [c for ui, c in panels if _visible(ui)]
    if shown or panels:
        return (shown or [c for _ui, c in panels])[-1]
    from tools.fx.grooming import controller as ctl
    adapter = ctl._adapter()
    nodes = adapter.find_nodes()
    if not nodes:
        return None
    c = ctl.GroomController(adapter, StatusView())
    c.set_node(nodes[0])
    return c


def _visible(ui) -> bool:
    try:
        return bool(ui.isVisible())
    except RuntimeError:
        return False


def radial(entry: str) -> bool:
    """A radial menu entry. Never raises: a failure goes to the status line."""
    try:
        c = controller()
        if c is None:
            _status(ws.NO_NODE, error=True)
            return False
        return _said(c, lambda: ws.run(c, entry))
    except Exception as e:
        _kept()["errors"] = (_kept()["errors"] + [traceback.format_exc()])[-10:]
        label = next((e[1] for e in ws.ENTRIES if e[0] == entry), entry)
        _status(f"MONO Grooming: {label} failed: {e}", error=True)
        return False


def _said(c, call):
    """Run a radial entry with what the panel says also put on the status line: the artist is looking at the
    viewport, not at the panel (t73: Paint with a lock selected said nothing where it was used)."""
    view = c.view
    own = getattr(view, "set_message", None)
    if own is None or isinstance(view, StatusView):
        return call()

    def both(text, error=False, *a, **k):
        own(text, error, *a, **k)
        if text:
            _status("MONO Grooming: " + text if not text.startswith("MONO Grooming") else text, error)
    had_own = "set_message" in getattr(view, "__dict__", {})   # set on the instance before (a test's spy)
    view.set_message = both
    try:
        return call()
    finally:
        if had_own:
            view.set_message = own
        else:
            del view.set_message           # the class's own method again


def checked(entry: str) -> bool:
    """The radial menu's check mark of a toggle entry; never raises (Houdini evaluates it on opening)."""
    try:
        panels = _panels()
        c = (([c for ui, c in panels if _visible(ui)] or [c for _ui, c in panels]) or [None])[-1]
        return ws.checked(c, entry)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The radial menu (key C in the viewport)
# ---------------------------------------------------------------------------

def _radial_api():
    get = getattr(hou.ui, "_getActiveRadialMenu", None)
    put = getattr(hou.ui, "_setActiveRadialMenu", None)
    return (get, put) if get is not None and put is not None and hou.ui.radialMenu(ws.RADIAL_NAME) is not None \
        else (None, None)


def active_radial() -> str | None:
    get, _put = _radial_api()
    return get() if get is not None else None


def radial_on() -> bool:
    """The viewport's radial menu becomes MONO Grooming; the user's is remembered. False when Houdini does not
    allow it (no such call, or the menu file is not installed)."""
    if not hou.isUIAvailable():
        return False
    get, put = _radial_api()
    if put is None:
        return False
    now = get()
    if now != ws.RADIAL_NAME:
        _kept()["radial_before"] = now
        put(ws.RADIAL_NAME)
    return get() == ws.RADIAL_NAME


def radial_off(still_shown: bool | None = None) -> bool:
    """The user's radial menu back, once no panel is shown. True when it was put back."""
    if not hou.isUIAvailable():
        return False
    if still_shown is None:
        still_shown = any(_visible(ui) for ui, _c in _panels())
    if still_shown:
        return False
    get, put = _radial_api()
    before = _kept().get("radial_before")
    if put is None or not before or get() != ws.RADIAL_NAME:
        return False         # the user picked another radial menu meanwhile: theirs stays
    put(before)
    _kept()["radial_before"] = None
    return get() == before


# ---------------------------------------------------------------------------
# The desktop
# ---------------------------------------------------------------------------

def open_workspace() -> bool:
    """Switch to the desktop MONO_Grooming, remembering the user's."""
    desk = hou.ui.desktop(ws.DESK_NAME)
    if desk is None:
        _status(f"MONO Grooming: the desktop {ws.DESK_NAME} is not installed", error=True)
        return False
    cur = hou.ui.curDesktop().name()
    if cur != ws.DESK_NAME:
        _kept()["desk_before"] = cur
    desk.setAsCurrent()
    return hou.ui.curDesktop().name() == ws.DESK_NAME


def leave_workspace() -> bool:
    """Back to the desktop the user had before `open_workspace`."""
    before = _kept().get("desk_before")
    desk = hou.ui.desktop(before) if before else None
    if desk is None:
        return False
    desk.setAsCurrent()
    return hou.ui.curDesktop().name() == before


__all__ = ["radial", "checked", "controller", "radial_on", "radial_off", "active_radial", "open_workspace",
           "leave_workspace", "StatusView"]
