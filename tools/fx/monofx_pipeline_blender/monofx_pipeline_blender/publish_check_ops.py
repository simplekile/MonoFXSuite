"""Test in Houdini / Test in Blender: the operators and the row the Model / Anim publish panels draw.

A NEW process every time (the user's picks, 2026-11-19): Houdini built by ``houdini_test_startup.py`` with the MonoFX
Loader, or a new Blender file by ``blender_test_startup.py`` with Blender's USD importer (the open file is never
touched). After a publish the row tests what was just written; otherwise it picks a version on disk, and its menu
picks another one. Logic without bpy: ``publish_check_launch.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Context, Menu, Operator

from . import publish_check_launch, preferences, publish_paths

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


def choices(kind: str) -> list[publish_check_launch.PublishChoice]:
    root = publish_root(kind)
    return publish_check_launch.model_publishes(root) if kind == "model" else publish_check_launch.anim_publishes(root)


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


_APP_NAME = {"houdini": "Houdini", "blender": "Blender"}
_ICON = {"houdini": "PLAY", "blender": "BLENDER"}


def launch(kind: str, path: str, app: str = "houdini") -> tuple[bool, str]:
    """A new Houdini or Blender process on this publish; (started, message for the report)."""
    if app == "blender":
        exe = Path(bpy.app.binary_path)  # this Blender's version, in a process of its own
        where = f"a new Blender {bpy.app.version_string}"
    else:
        prefs = preferences.get_addon_prefs()
        exe = publish_check_launch.find_houdini(getattr(prefs, "houdini_path", "") if prefs else "")
        if exe is None:
            return False, "No Houdini found: set Houdini in the MonoFX add-on preferences."
        where = exe.parent.parent.name
    script = publish_check_launch.startup_script(Path(__file__).resolve().parent, app)
    argv, env = publish_check_launch.launch_command(exe, script, kind, path, app=app)
    cwd = publish_check_launch.work_dir(app=app)
    try:
        cwd.mkdir(parents=True, exist_ok=True)
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(argv, env=env, cwd=str(cwd), creationflags=flags, close_fds=True)
    except OSError as exc:
        return False, f"{_APP_NAME[app]} did not start: {exc}"
    return True, f"Opening {Path(path).name} in {where}; the check is on its status bar."


_APP_ITEMS = [("houdini", "Houdini", "A new Houdini, loaded by the MonoFX Loader as lighting reads it"),
              ("blender", "Blender", "A new Blender file, imported with Blender's USD importer")]


class MONOFX_OT_test_in_houdini(Operator):
    bl_idname = "wm.mono_fx_test_in_houdini"
    bl_label = "Test Publish"
    bl_description = "Open this publish in a new Houdini or a new Blender file, with a check on its status bar"
    bl_options = {"REGISTER"}

    kind: StringProperty(default="model", options={"HIDDEN", "SKIP_SAVE"})
    path: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    app: EnumProperty(items=_APP_ITEMS, default="houdini", options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        if props.app == "blender":
            return ("Open this publish in a new Blender file (your open file stays as it is), imported with "
                    "Blender's USD importer, with a check on the status bar")
        return ("Open this publish in a new Houdini, loaded by the MonoFX Loader as lighting reads it, "
                "with a check on Houdini's status bar")

    def execute(self, context: Context) -> set[str]:
        if not self.path or not Path(self.path).exists():
            self.report({"ERROR"}, f"Not on disk: {self.path or '(nothing)'}")
            return {"CANCELLED"}
        ok, msg = launch(self.kind, self.path, self.app)
        self.report({"INFO"} if ok else {"ERROR"}, msg)
        return {"FINISHED"} if ok else {"CANCELLED"}


def _publish_items(self, context):
    items = [(c.path, c.label, c.path) for c in choices(self.kind)]
    _ITEMS_KEEP[:] = items or [("", "No publish on disk", "")]
    return _ITEMS_KEEP


class MONOFX_OT_test_publish_in_houdini(Operator):
    bl_idname = "wm.mono_fx_test_publish_in_houdini"
    bl_label = "Test a Publish"
    bl_description = "Pick a version on disk and open it in a new Houdini or a new Blender file"
    bl_options = {"REGISTER"}
    bl_property = "publish"

    kind: StringProperty(default="model", options={"HIDDEN", "SKIP_SAVE"})
    app: EnumProperty(items=_APP_ITEMS, default="houdini", options={"HIDDEN", "SKIP_SAVE"})
    publish: EnumProperty(name="Publish", items=_publish_items)

    @classmethod
    def description(cls, context, props):
        where = "a new Blender file" if props.app == "blender" else "a new Houdini"
        return f"Pick a version on disk and open it in {where}"

    def invoke(self, context: Context, event) -> set[str]:
        if not choices(self.kind):
            self.report({"WARNING"}, "No publish on disk for this scene yet.")
            return {"CANCELLED"}
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Context) -> set[str]:
        if not self.publish:
            return {"CANCELLED"}
        ok, msg = launch(self.kind, self.publish, self.app)
        self.report({"INFO"} if ok else {"ERROR"}, msg)
        return {"FINISHED"} if ok else {"CANCELLED"}


class MONOFX_MT_test_publish_pick(Menu):
    bl_idname = "MONOFX_MT_test_publish_pick"
    bl_label = "Test Another Version"

    def draw(self, context: Context) -> None:
        kind = getattr(context, "monofx_test_kind", "model")
        for app, name in _APP_NAME.items():
            op = self.layout.operator(MONOFX_OT_test_publish_in_houdini.bl_idname,
                                      text=f"Pick a Version for {name}...", icon=_ICON[app])
            op.kind, op.app = kind, app


def draw_test_row(layout, context: Context, kind: str) -> None:
    """Test in Houdini / Test in Blender: what this scene just published, else a picker of the versions on disk;
    the menu beside them picks another version for either."""
    row = layout.row(align=True)
    row.enabled = publish_root(kind) is not None
    just = _just_published(context, kind)
    for app, name in _APP_NAME.items():
        if just:
            op = row.operator(MONOFX_OT_test_in_houdini.bl_idname, text=f"Test in {name}", icon=_ICON[app])
            op.kind, op.path, op.app = kind, just, app
        else:
            op = row.operator(MONOFX_OT_test_publish_in_houdini.bl_idname, text=f"Test in {name}...",
                              icon=_ICON[app])
            op.kind, op.app = kind, app
    if just:
        sub = row.row(align=True)
        sub.context_string_set("monofx_test_kind", kind)
        sub.menu(MONOFX_MT_test_publish_pick.bl_idname, text="", icon="DOWNARROW_HLT")


CLASSES = (MONOFX_OT_test_in_houdini, MONOFX_OT_test_publish_in_houdini, MONOFX_MT_test_publish_pick)


def register() -> None:
    for prop in _JUST.values():
        setattr(bpy.types.WindowManager, prop, StringProperty(default="", options={"SKIP_SAVE"}))


def unregister() -> None:
    for prop in _JUST.values():
        if hasattr(bpy.types.WindowManager, prop):
            delattr(bpy.types.WindowManager, prop)
