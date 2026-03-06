"""
Scene Info controller — Houdini entry point.
Gathers data via adapter, runs logic, shows UI.
"""

from __future__ import annotations

from tools.fx.scene_info import config
from tools.fx.scene_info.logic import build_summary
from tools.fx.scene_info.ui import SceneInfoUI


def run() -> None:
    """Run Scene Info tool (call from Houdini shelf or menu)."""
    from apps.houdini import adapter as houdini_adapter

    if not houdini_adapter.is_available():
        return

    hip_path = houdini_adapter.get_hip_path()
    selected = houdini_adapter.get_selected_nodes()
    selection_count = len(selected)

    summary = build_summary(
        hip_path=hip_path,
        selection_count=selection_count,
        empty_path_label=config.DEFAULT_EMPTY_PATH_LABEL,
        no_selection_label=config.DEFAULT_NO_SELECTION,
    )

    ui = SceneInfoUI()
    ui.set_summary(summary)
    ui.setWindowTitle(config.WINDOW_TITLE)

    parent = houdini_adapter.get_main_qt_window()
    if parent:
        from PySide6.QtCore import Qt
        ui.setWindowFlags(ui.windowFlags() | Qt.WindowType.Window)
        ui.setParent(parent, ui.windowFlags())
    ui.show()
