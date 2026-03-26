"""
Node Preset Library — save/load node presets with categories and thumbnails.
"""

from __future__ import annotations


def run() -> None:
    # Houdini shelf tools often keep modules cached; reload to pick up changes
    # without requiring a Houdini restart.
    import importlib

    from tools.fx.node_preset_library import controller as _controller

    importlib.reload(_controller)
    _controller.run()

__all__ = ["run"]
