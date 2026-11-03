"""
Labels for the Drag & Drop settings window.
"""

from __future__ import annotations

from tools.fx.drag_drop.prefs import LAYER_ASK, LAYER_REFERENCE, LAYER_SUBLAYER

WINDOW_TITLE = "Drag & Drop Settings"

LAYER_MODE_LABELS = (
    (LAYER_ASK, "Ask each time (menu at cursor)"),
    (LAYER_REFERENCE, "Reference LOP per file"),
    (LAYER_SUBLAYER, "One Sublayer LOP"),
)
