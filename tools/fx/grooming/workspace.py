"""
The tool's own workspace (v0.2a last task): the desktop "MONO_Grooming" (`desktop/MONO_Grooming.desk` at the
suite root, which is the package `hpath`) and the radial menu "MONO Grooming"
(`radialmenu/mono_grooming.radialmenu`, key C in the viewport). Pure: the entries and what each one calls on
the panel's controller, so they are tested without Houdini; `apps/houdini/grooming_workspace.py` finds the
controller and switches the radial menu.

Every radial entry calls the SAME controller function as the panel's button (no second code path):
Paint -> toggle_paint (the layer's Paint), Erase -> set_brush(erase) (Eraser), Guides / Hair preview / Hair ->
set_display (the view bar's Display), Isolate -> toggle_isolate (I), Scalp X-ray -> set_brush(xray) (the paint
strip's X-ray), Update regions -> split_regions, Detect locks -> detect.
"""

from __future__ import annotations

import json
from typing import Any

RADIAL_NAME = "mono_grooming"
RADIAL_LABEL = "MONO Grooming"
DESK_NAME = "MONO_Grooming"
NO_NODE = "MONO Grooming: no MONO Grooming node in the scene (the Grooming shelf tool makes one)"
RADIAL_BY_HAND = ("Radial menu: Houdini did not let the panel switch it; pick MONO Grooming in the viewport's"
                  " radial menu list once (C opens it)")

# (id, label, icon, where on the menu; "display/<where>" sits in the Display submenu)
ENTRIES: tuple[tuple[str, str, str, str], ...] = (
    ("paint", "Paint", "SOP_paint", "top"),
    ("erase", "Erase", "SOP_paint", "top_right"),
    ("scalp_xray", "Scalp X-ray", "VIEW_display_xray", "right"),
    ("update_regions", "Update regions", "SOP_hairgen", "bottom_right"),
    ("detect", "Detect locks", "SOP_hairgen", "bottom"),
    ("isolate", "Isolate selected locks", "VIEW_visualization_isolate", "bottom_left"),
    ("guide", "Guides", "SOP_guidegroom", "display/top_left"),
    ("hair_preview", "Hair preview", "SOP_hairgen", "display/left"),
    ("hair", "Hair", "SOP_hairgen", "display/bottom_left"),
)
DISPLAY_AT = "left"
DISPLAYS = ("guide", "hair_preview", "hair")
TOGGLES = ("paint", "erase", "scalp_xray", "guide", "hair_preview", "hair")   # shown with a check mark


def entry_ids() -> list[str]:
    return [e[0] for e in ENTRIES]


def run(controller: Any, entry: str) -> bool:
    """What the radial entry `entry` does, on the panel's controller. False when it did nothing (no node:
    the controller's message line, or the status line for a controller without a panel, says why)."""
    if entry not in entry_ids():
        raise KeyError(entry)
    if controller is None or getattr(controller, "node", None) is None:
        view = getattr(controller, "view", None)
        if view is not None:
            view.set_message(NO_NODE, error=True)
        return False
    if entry == "paint":
        return bool(controller.toggle_paint())
    if entry == "erase":
        # the panel's Eraser sits on a paint layer's Properties: the radial one asks for the same (t73)
        needs = getattr(controller, "paint_needs", None)
        problem = needs() if needs is not None and getattr(controller, "paint_layer_id", None) is None else ""
        if problem:
            controller.view.set_message(problem, error=True)
            return False
        controller.set_brush(erase=not bool(controller.brush_state().get("erase")))
        return True
    if entry == "scalp_xray":
        controller.set_brush(xray=not bool(controller.brush_state().get("xray")))
        return True
    if entry in DISPLAYS:
        return bool(controller.set_display(entry))
    if entry == "isolate":
        return bool(controller.toggle_isolate())
    if entry == "update_regions":
        return bool(controller.split_regions())
    return controller.detect() is not None


def checked(controller: Any, entry: str) -> bool:
    """Whether a toggle entry shows its check mark (Paint on, Eraser on, Scalp X-ray on, the Display now)."""
    if controller is None or getattr(controller, "node", None) is None:
        return False
    if entry == "paint":
        return getattr(controller, "paint_layer_id", None) is not None
    if entry in ("erase", "scalp_xray"):
        return bool(controller.brush_state().get("erase" if entry == "erase" else "xray"))
    if entry in DISPLAYS:
        return getattr(controller, "display_mode", None) == entry
    return False


def _script(call: str, entry: str) -> str:
    """An item's script; a check script returns its value (as Houdini's own radial menus write it)."""
    body = f"grooming_workspace.{call}({entry!r})"
    return "from apps.houdini import grooming_workspace\n" + ("return " + body if call == "checked" else body)


def radial_menu() -> list:
    """The `.radialmenu` file's content (Houdini's JSON-like list form), made from ENTRIES."""
    def item(entry_id, label, icon):
        out = ["script", "label", label, "icon", icon, "script", _script("radial", entry_id)]
        if entry_id in TOGGLES:
            out[5:5] = ["check", _script("checked", entry_id)]
        return out

    root: list = ["submenu", "label", RADIAL_LABEL]
    display: list = ["submenu", "label", "Display"]
    for entry_id, label, icon, where in ENTRIES:
        if where.startswith("display/"):
            display += [where.split("/", 1)[1], item(entry_id, label, icon)]
        else:
            root += [where, item(entry_id, label, icon)]
    root += [DISPLAY_AT, display]
    return ["fileversion", "22.0.466", "name", RADIAL_NAME, "label", RADIAL_LABEL, "categories", "MonoFX",
            "submenu", root]


def radial_menu_text() -> str:
    return json.dumps(radial_menu(), indent="\t") + "\n"


__all__ = ["RADIAL_NAME", "RADIAL_LABEL", "DESK_NAME", "ENTRIES", "NO_NODE", "RADIAL_BY_HAND", "entry_ids", "run",
           "checked", "radial_menu", "radial_menu_text"]
