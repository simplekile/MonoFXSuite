"""
Scene Info logic — DCC-agnostic.
Builds summary text from scene data (path, selection count).
"""

from __future__ import annotations

from typing import Optional


def build_summary(
    hip_path: Optional[str],
    selection_count: int,
    empty_path_label: str = "(unsaved)",
    no_selection_label: str = "No nodes selected",
) -> str:
    """
    Build a short summary string from scene path and selection count.
    """
    path_line = hip_path if hip_path else empty_path_label
    if selection_count == 0:
        sel_line = no_selection_label
    else:
        sel_line = f"{selection_count} node(s) selected"
    return f"{path_line}\n\n{sel_line}"
