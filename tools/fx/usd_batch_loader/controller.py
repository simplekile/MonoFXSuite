"""USD Batch Load controller — MONOS UI + Solaris adapter."""

from __future__ import annotations

from tools.fx.usd_batch_loader import config
from tools.fx.usd_batch_loader.logic import collect_usd_files, node_name_from_label


def _network_path(h) -> str:
    parent = h.get_current_network_parent()
    if parent is None:
        return "— (open a LOP network in Network Editor)"
    try:
        return parent.path()
    except Exception:
        return "—"


def run() -> None:
    import importlib

    import apps.houdini.adapter as h

    importlib.reload(h)
    import tools.fx.usd_batch_loader.ui as _ui_mod

    importlib.reload(_ui_mod)
    UsdBatchLoadUI = _ui_mod.UsdBatchLoadUI

    if not h.is_available():
        return

    ui = UsdBatchLoadUI()
    ui.setWindowTitle(config.WINDOW_TITLE)
    ui.set_network_path(_network_path(h))

    def refresh_file_list() -> None:
        folder = ui.get_folder()
        if not folder:
            ui.set_files([])
            return
        strip = ui.get_strip_name()
        rows = [
            (path, name, node_name_from_label(name, strip))
            for path, name in collect_usd_files(folder, recursive=ui.get_recursive())
        ]
        ui.set_files(rows)
        if not rows:
            ui.set_message(f"No USD files in:\n{folder}", error=True)
        else:
            ui.set_message("", error=False)

    def on_browse() -> None:
        picked = ui.pick_folder(ui.get_folder())
        if picked:
            ui.set_folder(picked)
            refresh_file_list()

    def on_load() -> None:
        folder = ui.get_folder()
        if not folder:
            ui.set_message("Chọn folder chứa file USD.", error=True)
            return
        if not collect_usd_files(folder, recursive=ui.get_recursive()):
            ui.set_message("Folder không có file USD.", error=True)
            return

        ui.set_load_enabled(False)
        try:
            import importlib

            import apps.houdini.lop_usd_helpers as _lop_helpers
            import apps.houdini.usd_batch_loader as _loader

            importlib.reload(_lop_helpers)
            importlib.reload(_loader)

            count, msg = _loader.load_usd_folder(
                folder,
                mode=ui.get_mode(),  # type: ignore[arg-type]
                recursive=ui.get_recursive(),
                parent_prim_prefix=ui.get_prim_prefix(),
                strip_name=ui.get_strip_name(),
            )
        except Exception as exc:
            ui.set_load_enabled(True)
            ui.set_message(str(exc), error=True)
            return

        ui.set_load_enabled(True)
        ui.set_network_path(_network_path(h))
        if count == 0:
            ui.set_message(msg, error=True)
            ui.show_warning(config.WINDOW_TITLE, msg)
        else:
            ui.set_message(msg, error=False)
            ui.show_info(config.WINDOW_TITLE, msg)

    ui.on_browse_clicked(on_browse)
    ui.on_folder_changed(lambda _text: refresh_file_list())
    ui.on_strip_name_changed(lambda _text: refresh_file_list())
    ui.on_recursive_changed(lambda _checked: refresh_file_list())
    ui.on_load_clicked(on_load)
    ui._sync_reference_fields()

    parent_win = h.get_main_qt_window()
    if parent_win:
        from PySide6.QtCore import Qt

        ui.setWindowFlags(ui.windowFlags() | Qt.WindowType.Window)
        ui.setParent(parent_win, ui.windowFlags())
    ui.show()
