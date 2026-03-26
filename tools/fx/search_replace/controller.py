"""
Search & Replace controller — tìm và thay thế trong node name, string parms.
Scope: selected nodes hoặc cả network. Hỗ trợ regex.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from tools.fx.search_replace import config
from tools.fx.search_replace.logic import build_preview_line, replace_in_string


def run() -> None:
    import importlib
    import apps.houdini.adapter as h
    importlib.reload(h)  # ensure latest adapter without restarting Houdini
    # Reload UI so installed/build copy is used (avoid stale .pyc)
    import tools.fx.search_replace.ui as _sr_ui
    importlib.reload(_sr_ui)
    SearchReplaceUI = _sr_ui.SearchReplaceUI

    if not h.is_available():
        return

    ui = SearchReplaceUI()
    ui.setWindowTitle(config.WINDOW_TITLE)
    ui.set_scope_options(config.SCOPE_OPTIONS)
    ui.set_target_options(config.TARGET_OPTIONS)

    # Pending changes: (node, "name" or parm_name, new_value)
    pending: List[Tuple[Any, str, str]] = []

    def get_nodes():
        if ui.get_scope() == config.SCOPE_NETWORK:
            return h.get_nodes_in_current_network()
        return h.get_selected_nodes()

    def do_preview():
        pending.clear()
        find_str = ui.get_find()
        if not find_str:
            ui.set_preview("Enter a Find string.")
            ui.set_apply_enabled(False)
            return
        replace_str = ui.get_replace()
        use_regex = ui.get_use_regex()
        target = ui.get_target()
        nodes = get_nodes()
        if not nodes:
            ui.set_preview("No nodes in scope (select nodes or choose 'All nodes in current network').")
            ui.set_apply_enabled(False)
            return
        lines = []
        for node in nodes:
            try:
                path = node.path()
            except Exception:
                continue
            if target in (config.TARGET_NAMES, config.TARGET_BOTH):
                name = h.get_node_name(node)
                new_name, n = replace_in_string(name, find_str, replace_str, use_regex)
                if n > 0 and new_name != name:
                    pending.append((node, "name", new_name))
                    lines.append(build_preview_line(path, "name", name, new_name))
            if target in (config.TARGET_PARMS, config.TARGET_BOTH):
                for parm_name, old_val in h.get_string_parms_for_node(node):
                    new_val, n = replace_in_string(old_val, find_str, replace_str, use_regex)
                    if n > 0 and new_val != old_val:
                        pending.append((node, parm_name, new_val))
                        lines.append(build_preview_line(path, parm_name, old_val, new_val))
        ui.set_preview("\n\n".join(lines) if lines else "No matches.")
        ui.set_apply_enabled(len(pending) > 0)

    def do_apply():
        applied = 0
        for node, key, new_value in pending:
            try:
                if key == "name":
                    if h.set_node_name(node, new_value):
                        applied += 1
                else:
                    if h.set_parm_value(node, key, new_value):
                        applied += 1
            except Exception:
                pass
        pending.clear()
        ui.set_preview("")
        ui.set_apply_enabled(False)
        ui.show_info(config.WINDOW_TITLE, f"Applied {applied} replacement(s).")

    ui.on_preview_clicked(do_preview)
    ui.on_apply_clicked(do_apply)

    parent_win = h.get_main_qt_window()
    if parent_win:
        from PySide6.QtCore import Qt
        flags = ui.windowFlags() | Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        ui.setWindowFlags(flags)
        ui.setParent(parent_win, flags)
    else:
        from PySide6.QtCore import Qt
        ui.setWindowFlags(ui.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    ui.show()
