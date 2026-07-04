"""
Entry: reload modules, show dockable Reference Manager (singleton).
"""

from __future__ import annotations

import importlib
import traceback
from typing import Any, Optional

from tools.fx.maya_reference_manager import config

_active_ui: Optional[Any] = None


def run() -> None:
    global _active_ui

    try:
        import apps.maya.adapter as maya_adapter
    except ImportError as e:
        print(f"[{config.WINDOW_TITLE}] Import error: {e}")
        traceback.print_exc()
        return

    importlib.reload(maya_adapter)

    if not maya_adapter.is_available():
        print(
            f"[{config.WINDOW_TITLE}] Run inside Maya Script Editor — maya.cmds not available."
        )
        return

    try:
        import maya.utils as mu  # type: ignore
    except ImportError:
        mu = None  # type: ignore[assignment]

    def _show() -> None:
        global _active_ui

        import apps.common.project_layout as project_layout_mod

        importlib.reload(project_layout_mod)
        import tools.fx.maya_reference_manager.logic as logic_mod

        importlib.reload(logic_mod)
        import tools.fx.maya_reference_manager.ui as ui_mod

        importlib.reload(ui_mod)

        if _active_ui is not None:
            try:
                _active_ui.show_dockable()
                _active_ui.raise_()
                _active_ui.activateWindow()
                return
            except Exception:
                _active_ui = None

        parent = maya_adapter.get_main_qt_window()
        win = ui_mod.ReferenceManagerWindow(parent)
        win.set_maya_adapter(maya_adapter)
        _active_ui = win
        win.refresh_all()
        win.show_dockable()

    if mu is not None:
        mu.executeDeferred(_show)
    else:
        _show()


def run_immediate() -> None:
    """For tests or when not using executeDeferred."""
    global _active_ui
    try:
        import apps.maya.adapter as maya_adapter
    except ImportError:
        return
    if not maya_adapter.is_available():
        return
    import apps.common.project_layout as project_layout_mod

    importlib.reload(project_layout_mod)
    import tools.fx.maya_reference_manager.logic as logic_mod

    importlib.reload(logic_mod)
    import tools.fx.maya_reference_manager.ui as ui_mod

    importlib.reload(ui_mod)
    parent = maya_adapter.get_main_qt_window()
    win = ui_mod.ReferenceManagerWindow(parent)
    win.set_maya_adapter(maya_adapter)
    _active_ui = win
    win.refresh_all()
    win.show_dockable()
