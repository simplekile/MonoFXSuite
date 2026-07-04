"""
Addon keymap entries so MonoFX operators appear in Preferences > Keymap
and support right-click Assign Shortcut on panel buttons.
"""

from __future__ import annotations

from typing import Iterable, List, Tuple, Type

import bpy

_addon_keymaps: List[Tuple[bpy.types.KeyMap, bpy.types.KeyMapItem]] = []
_legacy_classes: List[type] = []


def _iter_registerable_operators(classes: Iterable[type]) -> Iterable[type]:
    for cls in classes:
        if not issubclass(cls, bpy.types.Operator):
            continue
        options = getattr(cls, "bl_options", set()) or set()
        if "REGISTER" not in options:
            continue
        bl_idname = getattr(cls, "bl_idname", "") or ""
        if bl_idname.startswith("wm.mono_fx_"):
            yield cls


def _legacy_idname(wm_idname: str) -> str:
    return "mono_fx." + wm_idname.removeprefix("wm.mono_fx_")


def _make_legacy_alias(new_idname: str) -> type:
    old_idname = _legacy_idname(new_idname)
    category, op_name = new_idname.split(".", 1)

    class MONOFX_OT_legacy_alias(bpy.types.Operator):
        bl_idname = old_idname
        bl_label = old_idname
        bl_options = {"INTERNAL"}

        _target_category = category
        _target_op = op_name

        def execute(self, _context):
            return getattr(getattr(bpy.ops, self._target_category), self._target_op)()

    MONOFX_OT_legacy_alias.__name__ = f"MONOFX_OT_legacy_{op_name}"
    return MONOFX_OT_legacy_alias


def register_keymaps(classes: Iterable[type]) -> None:
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return

    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
    for cls in _iter_registerable_operators(classes):
        kmi = km.keymap_items.new(cls.bl_idname, "NONE", "PRESS")
        _addon_keymaps.append((km, kmi))


def register_legacy_aliases(classes: Iterable[type]) -> None:
    for cls in _iter_registerable_operators(classes):
        legacy_cls = _make_legacy_alias(cls.bl_idname)
        bpy.utils.register_class(legacy_cls)
        _legacy_classes.append(legacy_cls)


def unregister_keymaps() -> None:
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()


def unregister_legacy_aliases() -> None:
    for cls in reversed(_legacy_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    _legacy_classes.clear()
