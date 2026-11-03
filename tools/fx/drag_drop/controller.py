"""
Drag & Drop settings controller — Houdini shelf entry point.
"""

from __future__ import annotations

from tools.fx.drag_drop import config, prefs
from tools.fx.drag_drop.ui import DragDropSettingsUI


def run() -> None:
    from apps.houdini import adapter as houdini_adapter

    if not houdini_adapter.is_available():
        return

    ui = DragDropSettingsUI()
    ui.setWindowTitle(config.WINDOW_TITLE)
    ui.set_prefs(prefs.load_prefs())

    def on_save() -> None:
        prefs.save_prefs(ui.get_prefs())
        ui.close()

    ui.on_save_clicked(on_save)
    ui.on_reset_clicked(lambda: ui.set_prefs(dict(prefs.DEFAULTS)))

    parent = houdini_adapter.get_main_qt_window()
    if parent:
        from PySide6.QtCore import Qt
        ui.setWindowFlags(ui.windowFlags() | Qt.WindowType.Window)
        ui.setParent(parent, ui.windowFlags())
    ui.show()
