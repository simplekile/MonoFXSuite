"""
Save incremental .blend work-file versions (``*_v001.blend``, ``*_v002_note.blend``, …).
"""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty, IntProperty
from bpy.types import Context, Operator, Panel

from . import publish_paths
from . import ui_style
from monofx_pipeline_common.version_description_presets import DEPARTMENT_ENUM_ITEMS
from monofx_pipeline_common import version_description_presets as _desc_presets

_PREVIEW_TIMER_INTERVAL = 3.0
_preview_timer_registered = False
_syncing_save_version_presets = False


def _pipeline_props(context: Context):
    return context.scene.monofx_pipeline_blender_props


def _save_version_department_value(owner) -> str:
    raw = getattr(owner, "save_version_department", None)
    if isinstance(raw, str):
        dept = raw.strip()
        if dept in _desc_presets.department_ids():
            return dept
    if isinstance(raw, int):
        try:
            return DEPARTMENT_ENUM_ITEMS[int(raw)][0]
        except (IndexError, TypeError, ValueError):
            pass
    return _desc_presets._DEFAULT_DEPARTMENT


def save_version_description_preset_items(self, _context: Context):
    dept = _save_version_department_value(self)
    items = [("NONE", "(none)", "No preset, type a custom description")]
    for preset_id, label, tip, _value in _desc_presets.presets_for_department(dept):
        items.append((preset_id, label, tip))
    return items


def on_save_version_department(self, _context: Context) -> None:
    global _syncing_save_version_presets
    if _syncing_save_version_presets:
        return
    _syncing_save_version_presets = True
    try:
        self.save_version_description_preset = 0
    finally:
        _syncing_save_version_presets = False


def on_save_version_description_preset(self, _context: Context) -> None:
    global _syncing_save_version_presets
    if _syncing_save_version_presets:
        return
    value = _desc_presets.description_for_preset(
        _save_version_department_value(self),
        str(getattr(self, "save_version_description_preset", "NONE") or "NONE"),
    )
    if value is None:
        return
    _syncing_save_version_presets = True
    try:
        self.save_version_description = value
    finally:
        _syncing_save_version_presets = False


def init_save_version_dialog_props(context: Context, scene_path: Path) -> None:
    """Set department / preset dropdowns from the open work-file path."""
    global _syncing_save_version_presets
    props = _pipeline_props(context)
    dept = _desc_presets.detect_department_from_scene(scene_path)
    desc = publish_paths.description_from_blend_stem(scene_path.stem)
    preset = _desc_presets.match_preset_for_description(dept, desc)
    _syncing_save_version_presets = True
    try:
        props.save_version_department = dept
        props.save_version_description = desc
        props.save_version_description_preset = preset
    finally:
        _syncing_save_version_presets = False


def refresh_save_version_preview(*, context: Context | None = None) -> None:
    if context is not None and getattr(context, "scene", None) is not None:
        scenes = [context.scene]
    else:
        # During add-on enable/install the extension system may run with restricted
        # bpy.data (e.g. _RestrictData) which can lack `.scenes`.
        try:
            scenes = list(bpy.data.scenes)
        except (AttributeError, TypeError, RuntimeError):
            scenes = []
    fp = str(getattr(bpy.data, "filepath", "") or "").strip()
    for scene in scenes:
        try:
            props = scene.monofx_pipeline_blender_props
        except (AttributeError, TypeError, RuntimeError):
            continue
        if not fp:
            props.save_version_preview_num = 0
            continue
        ok, num, _err = publish_paths.preview_next_blend_version(Path(fp))
        props.save_version_preview_num = int(num) if ok else 0


def _preview_timer(_dummy=None):
    refresh_save_version_preview()
    return _PREVIEW_TIMER_INTERVAL


def _ensure_preview_timer() -> None:
    global _preview_timer_registered
    if _preview_timer_registered:
        return
    try:
        bpy.app.timers.register(_preview_timer, first_interval=0.1)
        _preview_timer_registered = True
    except Exception:
        pass


def _drop_preview_timer() -> None:
    global _preview_timer_registered
    if not _preview_timer_registered:
        return
    try:
        bpy.app.timers.unregister(_preview_timer)
    except Exception:
        pass
    _preview_timer_registered = False


@persistent
def _on_scene_file_handlers(_dummy=None) -> None:
    refresh_save_version_preview()


def _save_version_button_text(props) -> str:
    ver = int(getattr(props, "save_version_preview_num", 0) or 0)
    if ver > 0:
        return f"Save next version (v{ver:03d})"
    return "Save Version"


def _remove_blend_paths(paths: list[Path], *, keep: Path) -> list[str]:
    removed: list[str] = []
    keep_norm = ""
    try:
        keep_norm = str(keep.resolve()).casefold()
    except OSError:
        keep_norm = str(keep).casefold()
    for path in paths:
        try:
            if str(path.resolve()).casefold() == keep_norm:
                continue
        except OSError:
            if str(path).casefold() == keep_norm:
                continue
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            pass
    return removed


def _draw_version_description_fields(layout, props) -> None:
    layout.prop(props, "save_version_department", text="Department")
    layout.prop(props, "save_version_description_preset", text="Preset")
    layout.prop(props, "save_version_description", text="Description")


def _draw_save_version_confirm(layout, context: Context) -> None:
    scene_path = Path(bpy.data.filepath)
    props = _pipeline_props(context)
    description = str(getattr(props, "save_version_description", "") or "")

    ok, version, err = publish_paths.preview_next_blend_version(scene_path)
    if not ok:
        layout.label(text=err or "Cannot save version.", icon="ERROR")
        return

    ok_path, new_path, err_path = publish_paths.build_blend_save_path_for_version(
        scene_path,
        version,
        description,
    )
    if not ok_path:
        layout.label(text=err_path or "Cannot build save path.", icon="ERROR")
        return

    col = layout.column(align=True)
    col.label(text="Save scene as the next work-file version?", icon="QUESTION")
    col.separator()
    _draw_version_description_fields(col, props)
    col.separator()
    col.label(text=f"Version: v{version:03d}")
    col.label(text=Path(new_path).name, icon="FILE_BLEND")


def _paths_same(a: Path, b: Path) -> bool:
    try:
        return str(a.resolve()).casefold() == str(b.resolve()).casefold()
    except OSError:
        return str(a).casefold() == str(b).casefold()


def _draw_edit_version_description(layout, context: Context) -> None:
    scene_path = Path(bpy.data.filepath)
    props = _pipeline_props(context)
    version = publish_paths.version_number_from_blend_stem(scene_path.stem)
    if version is None:
        layout.label(text="Current file has no version suffix (_v001).", icon="ERROR")
        return

    description = str(getattr(props, "save_version_description", "") or "")
    ok, new_path, err = publish_paths.blend_path_with_version_description(
        scene_path,
        description,
    )
    col = layout.column(align=True)
    col.label(text=f"Version description for {scene_path.name}", icon="FILE_BLEND")
    col.separator()
    _draw_version_description_fields(col, props)
    if not ok:
        col.label(text=err or "Cannot build filename.", icon="ERROR")
        return
    col.separator()
    col.label(text=f"v{version:03d} → {Path(new_path).name}", icon="FILE_BLEND")


@ui_style.operator_tooltip(
    "Rename the open .blend file to change its version description suffix "
    "(same _v### number, e.g. layoutPass)."
)
class MONOFX_OT_edit_save_version_description(Operator):
    bl_idname = "wm.mono_fx_edit_save_version_description"
    bl_label = "Edit Description"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Context) -> bool:
        fp = str(getattr(bpy.data, "filepath", "") or "").strip()
        if not fp:
            return False
        return publish_paths.version_number_from_blend_stem(Path(fp).stem) is not None

    def invoke(self, context: Context, event) -> set[str]:
        init_save_version_dialog_props(context, Path(bpy.data.filepath))
        return context.window_manager.invoke_props_dialog(self, width=400, confirm_text="Rename")

    def draw(self, context: Context) -> None:
        _draw_edit_version_description(self.layout, context)

    def execute(self, context: Context) -> set[str]:
        scene_path = Path(bpy.data.filepath)
        props = _pipeline_props(context)
        description = str(getattr(props, "save_version_description", "") or "")
        ok, new_path, err = publish_paths.blend_path_with_version_description(
            scene_path,
            description,
        )
        if not ok:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}

        target = Path(new_path)
        if _paths_same(scene_path, target):
            self.report({"INFO"}, "Description unchanged.")
            return {"FINISHED"}

        if target.exists() and not _paths_same(scene_path, target):
            self.report({"ERROR"}, f"File already exists: {target.name}")
            return {"CANCELLED"}

        old_path = scene_path
        try:
            bpy.ops.wm.save_as_mainfile(filepath=new_path, copy=False)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        if not _paths_same(old_path, target) and old_path.exists():
            try:
                old_path.unlink()
            except OSError as exc:
                self.report(
                    {"WARNING"},
                    f"Saved as {target.name} but could not remove {old_path.name}: {exc}",
                )

        props.save_version_description = description
        refresh_save_version_preview(context=context)
        msg = f"Renamed to {target.name}"
        props.save_version_report = msg
        self.report({"INFO"}, msg)
        return {"FINISHED"}


@ui_style.operator_tooltip(
    "Save the scene as the next work-file version in the current folder. "
    "Asks for confirmation before writing; re-checks on disk and prompts if that version already exists."
)
class MONOFX_OT_save_version(Operator):
    bl_idname = "wm.mono_fx_save_version"
    bl_label = "Save Version"
    bl_options = {"REGISTER"}

    target_version: IntProperty(name="Version", default=0, min=0, max=999, options={"HIDDEN"})
    resolution: EnumProperty(
        name="Action",
        items=[
            ("OVERWRITE", "Overwrite", "Replace existing file(s) with this version number"),
            ("NEXT", "Next Version", "Use the next available version number instead"),
        ],
        default="NEXT",
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context: Context) -> bool:
        return bool(str(getattr(bpy.data, "filepath", "") or "").strip())

    def invoke(self, context: Context, event) -> set[str]:
        self.target_version = 0
        self.resolution = "NEXT"
        scene_path = Path(bpy.data.filepath)
        init_save_version_dialog_props(context, scene_path)
        ok, version, err = publish_paths.preview_next_blend_version(scene_path)
        if not ok:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        parent, _base, ctx_err = publish_paths.scene_work_save_context(scene_path)
        if parent is None:
            self.report({"ERROR"}, ctx_err)
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(
            self,
            width=400,
            confirm_text=f"Save next version (v{version:03d})",
        )

    def draw(self, context: Context) -> None:
        if int(self.target_version) > 0:
            layout = self.layout
            scene_path = Path(bpy.data.filepath)
            parent, base, _err = publish_paths.scene_work_save_context(scene_path)
            if parent is None:
                layout.label(text="Invalid scene path", icon="ERROR")
                return
            ver = int(self.target_version)
            layout.label(text=f"Version v{ver:03d} already exists on disk:", icon="ERROR")
            existing = publish_paths.find_blend_files_for_version(parent, base, ver)
            for path in existing[:4]:
                layout.label(text=path.name, icon="FILE_BLEND")
            if len(existing) > 4:
                layout.label(text=f"+ {len(existing) - 4} more")
            layout.separator()
            layout.prop(self, "resolution", expand=True)
            return
        _draw_save_version_confirm(self.layout, context)

    def execute(self, context: Context) -> set[str]:
        scene_path = Path(bpy.data.filepath)
        props = _pipeline_props(context)
        description = str(getattr(props, "save_version_description", "") or "")

        version = int(self.target_version)
        if version <= 0:
            ok, version, err = publish_paths.preview_next_blend_version(scene_path)
            if not ok:
                self.report({"ERROR"}, err)
                return {"CANCELLED"}

        parent, base, err = publish_paths.scene_work_save_context(scene_path)
        if parent is None:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}

        chosen_resolution = str(self.resolution or "")

        while version <= 999:
            if not publish_paths.version_number_taken(parent, base, version):
                break
            if chosen_resolution == "OVERWRITE":
                break
            if chosen_resolution == "NEXT":
                version += 1
                chosen_resolution = ""
                continue
            self.target_version = version
            return context.window_manager.invoke_props_dialog(self, width=380)

        if version > 999:
            self.report({"ERROR"}, "Version limit reached (v999).")
            return {"CANCELLED"}

        ok, new_path, err = publish_paths.build_blend_save_path_for_version(
            scene_path,
            version,
            description,
        )
        if not ok:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}

        target = Path(new_path)
        try:
            bpy.ops.wm.save_as_mainfile(filepath=new_path, copy=False)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        removed_names: list[str] = []
        if chosen_resolution == "OVERWRITE":
            removed_names = _remove_blend_paths(
                publish_paths.find_blend_files_for_version(parent, base, version),
                keep=target,
            )

        refresh_save_version_preview(context=context)
        name = target.name
        msg = f"Saved {name}"
        if removed_names:
            msg = f"{msg} (replaced {', '.join(removed_names)})"
        props.save_version_report = msg
        self.report({"INFO"}, msg)
        self.target_version = 0
        self.resolution = "NEXT"
        return {"FINISHED"}


class MONOFX_PT_scene(Panel):
    bl_label = "Scene"
    bl_idname = "MONOFX_PT_scene"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MonoFX"
    bl_order = -10
    bl_description = "Scene file versioning"

    def draw(self, context: Context) -> None:
        layout = self.layout
        props = _pipeline_props(context)
        box = layout.box()

        if not bpy.data.filepath:
            row = box.row()
            row.alert = True
            row.label(text="Save .blend first", icon="ERROR")
            row = box.row(align=True)
            row.operator(
                "wm.mono_fx_edit_save_version_description",
                text="Edit Description",
                icon="GREASEPENCIL",
            )
            row.operator("wm.mono_fx_save_version", text="Save Version", icon="FILE_NEW")
            return

        if props.save_version_report:
            ui_style.status_label(box, props.save_version_report, ok=True)

        row = box.row(align=True)
        row.operator(
            "wm.mono_fx_edit_save_version_description",
            text="Edit Description",
            icon="GREASEPENCIL",
        )
        row.operator(
            "wm.mono_fx_save_version",
            text=_save_version_button_text(props),
            icon="FILE_NEW",
        )


def register_scene_version_handlers() -> None:
    _ensure_preview_timer()
    for handler, bucket in (
        (_on_scene_file_handlers, bpy.app.handlers.load_post),
        (_on_scene_file_handlers, bpy.app.handlers.save_post),
    ):
        if handler not in bucket:
            bucket.append(handler)
    refresh_save_version_preview()


def unregister_scene_version_handlers() -> None:
    _drop_preview_timer()
    for handler, bucket in (
        (_on_scene_file_handlers, bpy.app.handlers.load_post),
        (_on_scene_file_handlers, bpy.app.handlers.save_post),
    ):
        try:
            bucket.remove(handler)
        except ValueError:
            pass


SCENE_VERSION_CLASSES = (
    MONOFX_OT_edit_save_version_description,
    MONOFX_OT_save_version,
    MONOFX_PT_scene,
)
