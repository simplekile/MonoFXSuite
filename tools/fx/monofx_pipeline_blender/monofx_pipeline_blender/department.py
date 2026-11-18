"""
Which department's panel the MonoFX tab shows.

Auto (default) reads the department from where the .blend is saved (``01_modelling`` -> Model,
``02_rigging`` -> Rig, ``NN_anim`` -> Anim, ``publish_paths.department_from_scene``); the artist
can pick another one. The pick lives on the window manager: it is not saved in the file and goes
back to Auto in a new session. A file outside a project shows Model and Anim, as before.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import bpy
from bpy.props import EnumProperty
from bpy.types import Context

from . import publish_paths

_PROP = "monofx_department"
_LABELS = {"MODEL": "Model", "RIG": "Rig", "ANIM": "Anim"}

_ITEMS = [
    ("AUTO", "Auto", "Department from the folder the .blend is saved in"),
    ("MODEL", "Model", "Geo prep, material bake, asset USD publish"),
    ("RIG", "Rig", "Rig publish"),
    ("ANIM", "Anim", "Animation tools, rig linking, anim USD publish"),
]


def detected_department() -> Optional[str]:
    fp = bpy.data.filepath
    return publish_paths.department_from_scene(Path(fp)) if fp else None


def active_department(context: Context) -> Optional[str]:
    """``MODEL`` / ``RIG`` / ``ANIM``, or ``None`` when Auto finds no department."""
    wm = getattr(context, "window_manager", None)
    pick = str(getattr(wm, _PROP, "AUTO") or "AUTO")
    if pick != "AUTO":
        return pick
    return detected_department()


def shows(context: Context, dept: str) -> bool:
    active = active_department(context)
    if active is None:
        return dept in {"MODEL", "ANIM"}
    return active == dept


def draw_department_row(layout, context: Context) -> None:
    """One row: ``Auto (Rig) | Model | Rig | Anim``; Auto names what it found in the path."""
    wm = context.window_manager
    found = detected_department()
    row = layout.row(align=True)
    auto = f"Auto ({_LABELS[found]})" if found else "Auto"
    row.prop_enum(wm, _PROP, "AUTO", text=auto)
    for key in ("MODEL", "RIG", "ANIM"):
        row.prop_enum(wm, _PROP, key)


def register() -> None:
    setattr(
        bpy.types.WindowManager,
        _PROP,
        EnumProperty(
            name="Department",
            description="Which department's tools the MonoFX tab shows",
            items=_ITEMS,
            default="AUTO",
        ),
    )


def unregister() -> None:
    if hasattr(bpy.types.WindowManager, _PROP):
        delattr(bpy.types.WindowManager, _PROP)
