"""
Config for Node Preset Library.
"""

from __future__ import annotations

import os
from pathlib import Path

WINDOW_TITLE = "Node Preset Library"

INDEX_VERSION = 1
INDEX_FILENAME = "index.json"
CATEGORIES_DIR = "categories"
PRESET_FILE_EXT = ".cpio"
THUMB_EXT = ".png"

# Library root: env MONOFX_NODE_PRESET_LIBRARY, else <suite_root>/library/node_preset_library
def _suite_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def get_library_root() -> Path:
    env = os.environ.get("MONOFX_NODE_PRESET_LIBRARY", "").strip()
    if env:
        return Path(env)
    return _suite_root() / "library" / "node_preset_library"


def get_suite_version() -> str:
    """
    Read global VERSION file at repo root so UI version always matches installer/version.
    Fallback to '0.0.0' if missing.
    """
    try:
        path = _suite_root() / "VERSION"
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return "0.0.0"
