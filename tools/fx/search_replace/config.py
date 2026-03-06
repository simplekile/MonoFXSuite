"""
Config for Search & Replace tool — tìm và thay thế trong path, name, parm, attribute.
"""

from __future__ import annotations

WINDOW_TITLE = "Search & Replace"
SCOPE_SELECTED = "selected"
SCOPE_NETWORK = "network"
SCOPE_OPTIONS = [
    ("Selected nodes only", SCOPE_SELECTED),
    ("All nodes in current network", SCOPE_NETWORK),
]
TARGET_NAMES = "names"
TARGET_PARMS = "parms"
TARGET_BOTH = "both"
TARGET_OPTIONS = [
    ("Node names", TARGET_NAMES),
    ("String parms (path, file, ...)", TARGET_PARMS),
    ("Both", TARGET_BOTH),
]
