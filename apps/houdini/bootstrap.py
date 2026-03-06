"""
Houdini bootstrap: add MonoFX Suite to Python path and prepare environment.

Run this from Houdini's Python shell or 123.py / houdini.env so that
'from core...' and 'from tools...' work. DCC-specific code stays here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def find_suite_root(start: Optional[Path] = None) -> Optional[Path]:
    """
    Find MonoFXSuite repo root (directory containing 'core' and 'apps').
    Walks upward from start path.
    """
    current = Path(start or Path(__file__).resolve()).resolve()
    if not current.is_dir():
        current = current.parent
    while current != current.parent:
        if (current / "core").is_dir() and (current / "apps").is_dir():
            return current
        current = current.parent
    if (current / "core").is_dir() and (current / "apps").is_dir():
        return current
    return None


def ensure_pipeline_path(root: Optional[Path] = None) -> bool:
    """
    Add MonoFX Suite root to sys.path so core and tools can be imported.
    Returns True if path was added, False if already present or not found.
    """
    suite_root = root or find_suite_root()
    if not suite_root:
        return False
    root_str = str(suite_root)
    if root_str in sys.path:
        return False
    sys.path.insert(0, root_str)
    return True


def run_bootstrap(root: Optional[Path] = None) -> Path | None:
    """
    Ensure pipeline is on path. Optionally register menu/shelf (future).
    Returns suite root Path if successful, None otherwise.
    """
    ensure_pipeline_path(root)
    return find_suite_root(root)
