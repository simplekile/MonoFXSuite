"""
Sidebar UI helpers: section headers, icons, alert styling.

Blender does not support arbitrary RGB on panel widgets; use ``layout.alert = True``
for warning/error emphasis (theme-driven red tint).

Sidebar operator tooltips in Blender 5 use the class ``__doc__`` and ``description()``;
``bl_description`` alone is not always enough.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Tuple, TypeVar

import bpy

from . import preferences as _prefs_mod


# Icons must match Blender 5.1 UILayout icon enum (no legacy aliases like "SYNTAX").

# Workflow tabs
ICON_TAB_PREPARING = "TOOL_SETTINGS"
ICON_TAB_ASSET_PUBLISH = "FILE_BLEND"
ICON_TAB_ANIM_PUBLISH = "ANIM"
ICON_TAB_RIG_LINK = "LINKED"

# Preparing Asset
ICON_HIERARCHY = "OUTLINER_COLLECTION"
ICON_NAMING = "SYNTAX_ON"
ICON_TRANSFORMS = "OBJECT_ORIGIN"
ICON_MATERIALS = "MATERIAL"
ICON_PRESET = "PRESET"

# Asset Publish
ICON_PUBLISH = "PACKAGE"
ICON_OUTPUT_OK = "CHECKMARK"
ICON_OUTPUT_WARN = "ERROR"
ICON_FOLDER = "FILE_FOLDER"
ICON_PREPARE = "ORIENTATION_GIMBAL"
ICON_EXPORT = "FILE_BLEND"
ICON_RESTORE = "LOOP_BACK"
ICON_USD = "WORLD"


_OperatorCls = TypeVar("_OperatorCls", bound=type)


def operator_tooltip(text: str) -> Callable[[_OperatorCls], _OperatorCls]:
    """Decorator so sidebar buttons show a tooltip in Blender 5."""

    doc = text.strip()

    def decorator(cls: _OperatorCls) -> _OperatorCls:
        cls.__doc__ = doc
        cls.bl_description = doc

        @classmethod
        def description(cls, context, properties) -> str:
            return doc

        cls.description = description  # type: ignore[method-assign]
        return cls

    return decorator


def panel_header(layout: bpy.types.UILayout, title: str = "MonoFX Pipeline") -> None:
    row = layout.row(align=True)
    row.label(text=title, icon="BLENDER")


def draw_panel_tabs(
    layout: bpy.types.UILayout,
    data,
    prop_name: str,
) -> None:
    """Horizontal tab row backed by an EnumProperty with ``expand=True``."""
    shell = layout.box()
    row = shell.row(align=True)
    row.prop(data, prop_name, expand=True)


def draw_vertical_tabs(
    layout: bpy.types.UILayout,
    data,
    prop_name: str,
    *,
    factor: float = 0.24,
) -> Tuple[bpy.types.UILayout, bpy.types.UILayout]:
    """
    Vertical tab column (left) + content column (right).

    EnumProperty items should include icons (4th tuple element) for compact tabs.
    The tab column is wrapped in a box so it uses the theme's lighter panel background.
    """
    split = layout.split(factor=factor, align=True)
    tab_shell = split.box()
    tabs = tab_shell.column(align=True)
    tabs.scale_x = 0.85
    tabs.prop(data, prop_name, expand=True)
    body = split.column(align=True)
    return tabs, body


def framed_section(
    layout: bpy.types.UILayout,
    title: str,
    *,
    icon: str = "NONE",
) -> bpy.types.UILayout:
    """
    Non-collapsible framed section.

    Blender doesn't allow arbitrary section background colors; nested boxes
    still give a clear visual hierarchy (main vs subsection).
    """
    box = layout.box()
    if title:
        box.label(text=title, icon=icon)
    return box.column(align=True)

def _prefs_foldout_section(
    layout: bpy.types.UILayout,
    prefs: Any,
    prop_name: str,
    title: str,
    *,
    icon: str = "NONE",
) -> Tuple[Optional[bpy.types.UILayout], bool]:
    box = layout.box()
    row = box.row(align=True)
    kwargs: dict = {"text": title, "emboss": False, "toggle": True}
    if icon != "NONE":
        kwargs["icon"] = icon
    row.prop(prefs, prop_name, **kwargs)
    if not getattr(prefs, prop_name):
        return None, False
    return box, True


def collapsible_section(
    layout: bpy.types.UILayout,
    panel_id: str,
    title: str,
    *,
    icon: str = "NONE",
    default_closed: bool = True,
    prefs: Any = None,
) -> Tuple[Optional[bpy.types.UILayout], bool]:
    """
    Foldout section. Uses add-on preferences when available so open/closed
    state survives Blender restarts. Returns (body_layout, is_open).
    """
    if prefs is None:
        prefs = _prefs_mod.get_addon_prefs()
    prop_name = _prefs_mod.section_prop_for_panel_id(panel_id)
    if prefs is not None and prop_name:
        body, is_open = _prefs_foldout_section(layout, prefs, prop_name, title, icon=icon)
        if is_open and body is not None:
            col = body.column(align=True)
            return col, True
        return None, False

    panel_fn = getattr(layout, "panel", None)
    if panel_fn is None:
        box = layout.box()
        box.label(text=title, icon=icon)
        return box, True

    header, body = panel_fn(panel_id, default_closed=default_closed)
    row = header.row(align=True)
    row.label(text=title, icon=icon)
    return body, body is not None


def section(
    layout: bpy.types.UILayout,
    title: str,
    *,
    icon: str = "NONE",
    panel_id: str = "",
    default_closed: bool = True,
    prefs: Any = None,
) -> Optional[bpy.types.UILayout]:
    """Collapsible section; alias for collapsible_section body only."""
    pid = panel_id or f"monofx_sec_{title.replace(' ', '_').lower()}"
    body, _open = collapsible_section(
        layout,
        pid,
        title,
        icon=icon,
        default_closed=default_closed,
        prefs=prefs,
    )
    return body


def status_label(
    parent: bpy.types.UILayout,
    text: str,
    *,
    ok: Optional[bool] = None,
    icon: Optional[str] = None,
) -> None:
    row = parent.row(align=True)
    if ok is True:
        row.label(text=text, icon=icon or ICON_OUTPUT_OK)
    elif ok is False:
        col = row.column(align=True)
        col.alert = True
        col.label(text=text, icon=icon or ICON_OUTPUT_WARN)
    else:
        row.label(text=text, icon=icon or "INFO")


def prop_checkbox(
    layout: bpy.types.UILayout,
    data,
    prop_name: str,
    *,
    text: Optional[str] = None,
) -> None:
    """Draw a BoolProperty as a classic checkbox (not an icon toggle)."""
    kwargs: dict = {"toggle": False}
    if text is not None:
        kwargs["text"] = text
    layout.prop(data, prop_name, **kwargs)


def prop_object_channel(
    layout: bpy.types.UILayout,
    obj: Optional[bpy.types.Object],
    prop_path: str,
    index: int = 0,
    *,
    text: Optional[str] = None,
    fallback_data=None,
    fallback_prop: Optional[str] = None,
) -> None:
    """
    Draw a rig object channel with Blender keyframe decorators.

    Uses the object RNA path so keys inserted in the Properties editor show here too.
    Falls back to *fallback_data*.*fallback_prop* when *obj* is unavailable.
    """
    if obj is not None:
        kwargs: dict = {}
        if text is not None:
            kwargs["text"] = text
        layout.prop(obj, prop_path, index=index, **kwargs)
        return
    if fallback_data is not None and fallback_prop:
        layout.prop(fallback_data, fallback_prop, text=text or "")


def operator_row(
    parent: bpy.types.UILayout,
    op_idname: str,
    *,
    text: Optional[str] = None,
    icon: str = "NONE",
    depress: bool = False,
    scale_y: float = 1.0,
    emboss: bool = True,
) -> bpy.types.Operator:
    row = parent.row(align=True)
    row.scale_y = scale_y
    kwargs: dict = {"icon": icon}
    if text is not None:
        kwargs["text"] = text
    if depress:
        kwargs["depress"] = True
    if not emboss:
        kwargs["emboss"] = False
    return row.operator(op_idname, **kwargs)


def label_row_right(
    parent: bpy.types.UILayout,
    left_text: str,
    right_text: str,
    *,
    left_icon: str = "NONE",
    right_icon: str = "NONE",
    factor: float = 0.52,
) -> None:
    """Two-column row: label left, counter / meta text right-aligned."""
    if not right_text:
        row = parent.row(align=True)
        if left_icon != "NONE":
            row.label(text=left_text, icon=left_icon)
        else:
            row.label(text=left_text)
        return
    split = parent.split(factor=factor, align=True)
    left = split.row(align=True)
    if left_icon != "NONE":
        left.label(text=left_text, icon=left_icon)
    else:
        left.label(text=left_text)
    right = split.row(align=True)
    right.alignment = "RIGHT"
    if right_icon != "NONE":
        right.label(text=right_text, icon=right_icon)
    else:
        right.label(text=right_text)
