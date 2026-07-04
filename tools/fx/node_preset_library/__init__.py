"""
Node Preset Library — save/load node presets with categories and thumbnails.
"""

from __future__ import annotations


def reload_and_run() -> None:
    """Reload all modules then run. Use during development to pick up code changes without restarting Houdini."""
    import importlib

    import apps.houdini.adapter as _adapter
    import tools.fx.node_preset_library.config as _cfg
    import tools.fx.node_preset_library.logic as _logic
    import tools.fx.node_preset_library.ui as _ui
    import tools.fx.node_preset_library.controller as _ctrl

    importlib.reload(_cfg)
    importlib.reload(_logic)
    importlib.reload(_adapter)
    importlib.reload(_ui)
    importlib.reload(_ctrl)
    _ctrl.run()


def run() -> None:
    """Shelf entry: reload modules then run."""
    reload_and_run()


__all__ = ["run", "reload_and_run"]
