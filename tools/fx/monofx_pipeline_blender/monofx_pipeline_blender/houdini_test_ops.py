"""Test in Houdini: the operators and the row the Model / Anim publish panels draw.

A NEW Houdini process every time (the user's pick, 2026-11-19), built by ``houdini_test_startup.py`` with the MonoFX
Loader. After a publish the row tests what was just written; its menu opens any version on disk. Logic without bpy:
``houdini_launch.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Context, Operator

from . import houdini_launch, preferences, publish_paths

_JUST = {"model": "monofx_houdini_test_model", "anim": "monofx_houdini_test_anim"}  # WindowManager: not in the file
_ITEMS_KEEP: list = []  # Blender needs the enum strings kept alive while the search popup shows


def _scene_path() -> Optional[Path]:
    return Path(bpy.data.filepath) if bpy.data.filepath else None


def publish_root(kind: str) -> Optional[Path]:
    scene = _scene_path()
    if scene is None:
        return None
    if kind == "model":
        return publish_paths.resolve_publish_root_from_scene(scene)
    return publish_paths.resolve_anim_publish_root_from_scene(scene)


def choices(kind: str) -> list[houdini_launch.PublishChoice]:
    root = publish_root(kind)
    return houdini_launch.model_publishes(root) if kind == "model" else houdini_launch.anim_publishes(root)


def remember(context: Context, kind: str, path: str) -> None:
    """Called by the publish operators: the row then offers to test what was just written."""
    try:
        setattr(context.window_manager, _JUST[kind], path or "")
    except Exception:  # never fail a publish over this
        pass


def _just_published(context: Context, kind: str) -> str:
    path = getattr(context.window_manager, _JUST[kind], "") or ""
    root = publish_root(kind)
    if not path or root is None or not Path(path).exists():
        return ""
    try:
        Path(path).resolve().relative_to(root.resolve())  # this scene's publish, not another file's
    except ValueError:
        return ""
    return path


def launch(kind: str, path: str) -> tuple[bool, str]:
    prefs = preferences.get_addon_prefs()
    exe = houdini_launch.find_houdini(getattr(prefs, "houdini_path", "") if prefs else "")
    if exe is None:
        return False, "No Houdini found: set Houdini in the MonoFX add-on preferences."
    script = houdini_launch.startup_script(Path(__file__).resolve().parent)
    argv, env = houdini_launch.launch_command(exe, script, kind, path)
    cwd = houdini_launch.work_dir()
    try:
        cwd.mkdir(parents=True, exist_ok=True)
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(argv, env=env, cwd=str(cwd), creationflags=flags, close_fds=True)
    except OSError as exc:
        return False, f"Houdini did not start: {exc}"
    return True, f"Opening {Path(path).name} in {exe.parent.parent.name}; the check is on Houdini's status bar."


class MONOFX_OT_test_in_houdini(Operator):
    bl_idname = "wm.mono_fx_test_in_houdini"
    bl_label = "Test in Houdini"
    bl_description = ("Open this publish in a new Houdini, loaded by the MonoFX Loader as lighting reads it, "
                      "with a check on Houdini's status bar")
    bl_options = {"REGISTER"}

    kind: StringProperty(default="model", options={"HIDDEN", "SKIP_SAVE"})
    path: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context: Context) -> set[str]:
        if not self.path or not Path(self.path).exists():
            self.report({"ERROR"}, f"Not on disk: {self.path or '(nothing)'}")
            return {"CANCELLED"}
        ok, msg = launch(self.kind, self.path)
        self.report({"INFO"} if ok else {"ERROR"}, msg)
        return {"FINISHED"} if ok else {"CANCELLED"}


def _publish_items(self, context):
    items = [(c.path, c.label, c.path) for c in choices(self.kind)]
    _ITEMS_KEEP[:] = items or [("", "No publish on disk", "")]
    return _ITEMS_KEEP


class MONOFX_OT_test_publish_in_houdini(Operator):
    bl_idname = "wm.mono_fx_test_publish_in_houdini"
    bl_label = "Test a Publish in Houdini"
    bl_description = "Pick a version on disk and open it in a new Houdini, loaded by the MonoFX Loader"
    bl_options = {"REGISTER"}
    bl_property = "publish"

    kind: StringProperty(default="model", options={"HIDDEN", "SKIP_SAVE"})
    publish: EnumProperty(name="Publish", items=_publish_items)

    def invoke(self, context: Context, event) -> set[str]:
        if not choices(self.kind):
            self.report({"WARNING"}, "No publish on disk for this scene yet.")
            return {"CANCELLED"}
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Context) -> set[str]:
        if not self.publish:
            return {"CANCELLED"}
        ok, msg = launch(self.kind, self.publish)
        self.report({"INFO"} if ok else {"ERROR"}, msg)
        return {"FINISHED"} if ok else {"CANCELLED"}


def draw_test_row(layout, context: Context, kind: str) -> None:
    """Test in Houdini for what was just published (when this scene published it), and a picker of every version."""
    row = layout.row(align=True)
    just = _just_published(context, kind)
    if just:
        op = row.operator(MONOFX_OT_test_in_houdini.bl_idname, text="Test in Houdini", icon="PLAY")
        op.kind, op.path = kind, just
        pick = row.operator(MONOFX_OT_test_publish_in_houdini.bl_idname, text="", icon="DOWNARROW_HLT")
    else:
        pick = row.operator(MONOFX_OT_test_publish_in_houdini.bl_idname, text="Test a Publish in Houdini",
                            icon="PLAY")
    pick.kind = kind
    row.enabled = publish_root(kind) is not None


CLASSES = (MONOFX_OT_test_in_houdini, MONOFX_OT_test_publish_in_houdini)


def register() -> None:
    for prop in _JUST.values():
        setattr(bpy.types.WindowManager, prop, StringProperty(default="", options={"SKIP_SAVE"}))


def unregister() -> None:
    for prop in _JUST.values():
        if hasattr(bpy.types.WindowManager, prop):
            delattr(bpy.types.WindowManager, prop)
