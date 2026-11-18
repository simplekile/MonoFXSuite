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
    wm = context.window_manager
    row = layout.row(align=True)
    row.prop(wm, _PROP, expand=True)
    if str(getattr(wm, _PROP, "AUTO")) == "AUTO":
        found = detected_department()
        hint = layout.row()
        hint.enabled = False
        if found:
            hint.label(text=f"{_LABELS[found]}, from the file's folder", icon="FILE_FOLDER")
        else:
            hint.label(text="No department in this file's path", icon="INFO")


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
