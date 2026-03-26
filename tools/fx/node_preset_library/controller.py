"""
Node Preset Library controller — UI + logic + Houdini adapter.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QInputDialog, QMessageBox
from PySide6.QtGui import QPixmap

from tools.fx.node_preset_library import config
from tools.fx.node_preset_library.logic import (
    add_category,
    add_preset,
    category_id_from_name,
    ensure_library_root,
    list_categories,
    list_presets,
    get_preset,
    merge_library_from_folder,
    preset_relative_paths,
    count_presets_by_category,
)
from tools.fx.node_preset_library.ui import NodePresetLibraryUI, SavePresetDialog


def run() -> None:
    import importlib
    import apps.houdini.adapter as h
    importlib.reload(h)

    if not h.is_available():
        h.ui_display_message("Houdini is not available.", "Node Preset Library")
        return

    library_root = config.get_library_root()
    ensure_library_root(library_root)

    ui = NodePresetLibraryUI()
    suite_version = getattr(config, "get_suite_version", lambda: "0.0.0")()
    ui.setWindowTitle(f"{config.WINDOW_TITLE}  —  v{suite_version}")
    ui.set_version_text(f"v{suite_version}")

    # UI state
    state = {
        "category_id": "__all__",
        "search": "",
        "network": "__all__",
        "auto_detect": True,
        "view_mode": "grid",
    }

    def refresh_categories(select_id: Optional[str] = None) -> None:
        cats = list_categories(library_root)
        if not cats and select_id is None:
            add_category("Uncategorized", library_root)
            cats = list_categories(library_root)
        counts = count_presets_by_category(library_root)
        total = sum(counts.values())
        all_entry = {"id": "__all__", "name": f"All ({total})"}
        enriched: list[dict] = [all_entry]
        for c in cats:
            cid = c.get("id", "")
            n = counts.get(cid, 0)
            name = c.get("name", cid or "Uncategorized")
            c = dict(c)
            c["name"] = f"{name} ({n})"
            enriched.append(c)
        ui.set_categories(enriched, select_id or "__all__")

    def refresh_presets(category_id: Optional[str] = None) -> None:
        state["category_id"] = category_id or "__all__"
        # Base set by category
        if state["category_id"] in (None, "", "__all__"):
            presets = list_presets(category_id=None, library_root=library_root)
        else:
            presets = list_presets(category_id=state["category_id"], library_root=library_root)
        # Network filter
        net = state["network"]
        if net not in ("__all__", "", None):
            presets = [p for p in presets if net in (p.get("networks") or [])]
        # Search filter
        text = state["search"].strip().lower()
        if text:
            def matches(p: dict) -> bool:
                name = (p.get("name") or "").lower()
                desc = (p.get("description") or "").lower()
                return text in name or text in desc
            presets = [p for p in presets if matches(p)]
        ui.set_presets(presets, library_root)

    def on_category_selected(cid: Optional[str]) -> None:
        refresh_presets(cid)

    ui.on_category_selected(on_category_selected)
    refresh_categories()
    cid = ui.get_selected_category_id() or "__all__"
    if cid is None and ui._category_list.count() > 0:
        ui._category_list.setCurrentRow(0)
        cid = ui.get_selected_category_id() or "__all__"
    refresh_presets(cid)

    def open_save_dialog() -> None:
        parent, items = h.get_selected_network_items()
        if not parent or not items:
            ui.set_message("Select one or more nodes in the same network first.", error=True)
            return
        dialog = SavePresetDialog(ui)
        cats = list_categories(library_root)
        if not cats:
            add_category("Uncategorized", library_root)
            cats = list_categories(library_root)
        dialog.set_categories(cats)

        def do_paste_thumbnail() -> None:
            from PySide6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            img = clipboard.image()
            if img.isNull():
                QMessageBox.information(dialog, "Paste thumbnail", "No image in clipboard.")
                return
            dialog.set_thumbnail_from_pixmap(QPixmap.fromImage(img))

        dialog.on_paste_thumbnail(do_paste_thumbnail)

        def do_new_category() -> None:
            name, ok = QInputDialog.getText(dialog, "New category", "Category name:")
            if ok and name.strip():
                add_category(name.strip(), library_root)
                dialog.set_categories(list_categories(library_root))
                dialog.set_category(category_id_from_name(name))

        dialog.on_new_category(do_new_category)

        if dialog.exec() != SavePresetDialog.DialogCode.Accepted:
            return
        name = dialog.get_name()
        if not name:
            ui.set_message("Enter a preset name.", error=True)
            return
        description = dialog.get_description()
        networks: list[str] = []
        if hasattr(h, "detect_network_tags_for_items"):
            try:
                networks = h.detect_network_tags_for_items(parent, items)  # type: ignore[attr-defined]
            except Exception:
                networks = []
        if state["auto_detect"] and networks:
            state["network"] = networks[0]
            if hasattr(ui, "set_network_filter_value"):
                ui.set_network_filter_value(state["network"])
        cat_id = dialog.get_category_id()
        if not cat_id:
            cat_id = "uncategorized"
        add_category(dialog.get_category() or "Uncategorized", library_root)
        preset_id = uuid.uuid4().hex[:12]
        rel_cpio, rel_thumb = preset_relative_paths(cat_id, preset_id)
        full_cpio = library_root / rel_cpio
        full_cpio.parent.mkdir(parents=True, exist_ok=True)
        if not h.save_items_to_file(parent, items, str(full_cpio)):
            ui.set_message("Failed to save nodes to file.", error=True)
            return
        thumb_rel: Optional[str] = None
        pix = dialog.get_thumbnail_pixmap()
        if pix and not pix.isNull():
            full_thumb = library_root / rel_thumb
            full_thumb.parent.mkdir(parents=True, exist_ok=True)
            if pix.save(str(full_thumb)):
                thumb_rel = rel_thumb
        add_preset(
            name=name,
            category_id=cat_id,
            relative_hipnc_path=rel_cpio,
            node_count=len(items),
            thumbnail_relative=thumb_rel,
            description=description,
            networks=networks,
            preset_id=preset_id,
            library_root=library_root,
        )
        ui.set_message(f"Saved preset: {name}")
        refresh_categories(cat_id)
        refresh_presets(cat_id)

    ui.on_save_clicked(open_save_dialog)

    def on_new_category_clicked() -> None:
        name, ok = QInputDialog.getText(ui, "New category", "Category name:")
        if ok and name.strip():
            add_category(name.strip(), library_root)
            cid = category_id_from_name(name.strip())
            refresh_categories(cid)
            refresh_presets(cid)
            ui.set_message(f"Added category: {name}")

    ui.on_new_category_clicked(on_new_category_clicked)

    def on_import_clicked() -> None:
        folder = ui.show_import_folder_dialog()
        if not folder:
            return
        src = Path(folder)
        try:
            cats_added, presets_added = merge_library_from_folder(src, library_root)
            ui.set_message(f"Imported: {cats_added} categories, {presets_added} presets.")
            refresh_categories()
            refresh_presets(ui.get_selected_category_id())
        except Exception as e:
            ui.set_message(f"Import failed: {e}", error=True)

    ui.on_import_clicked(on_import_clicked)

    def on_search(text: str) -> None:
        state["search"] = text
        refresh_presets(state["category_id"])

    ui.on_search_changed(on_search)

    def on_auto_detect(toggled: bool) -> None:
        state["auto_detect"] = toggled
        ui.set_auto_detect_enabled(toggled)
        if toggled:
            parent = h.get_current_network_parent()
            if parent and hasattr(h, "detect_network_tags_for_parent"):
                try:
                    nets = h.detect_network_tags_for_parent(parent)  # type: ignore[attr-defined]
                except Exception:
                    nets = []
                if nets:
                    state["network"] = nets[0]
                    ui.set_network_filter_value(state["network"])
        refresh_presets(state["category_id"])

    ui.on_auto_detect_toggled(on_auto_detect)

    def on_network_filter(value: str) -> None:
        state["network"] = value
        refresh_presets(state["category_id"])

    ui.on_network_filter_changed(on_network_filter)

    def on_view_mode(mode: str) -> None:
        state["view_mode"] = mode
        # UI already switches modes internally

    ui.on_view_mode_changed(on_view_mode)

    def on_insert_clicked(preset_id: Optional[str] = None) -> None:
        pid = preset_id or ui.get_selected_preset_id()
        if not pid:
            ui.set_message("Select a preset first.", error=True)
            return
        preset = get_preset(pid, library_root)
        if not preset:
            ui.set_message("Preset not found.", error=True)
            return
        rel_path = preset.get("file")
        if not rel_path:
            ui.set_message("Preset has no file.", error=True)
            return
        full_path = library_root / rel_path
        if not full_path.is_file():
            ui.set_message(f"File not found: {rel_path}", error=True)
            return
        parent = h.get_current_network_parent()
        if not parent:
            ui.set_message("Open a network (e.g. double-click a node) and try again.", error=True)
            return
        ok, err = getattr(h, "load_items_from_file_ex", None)(parent, str(full_path)) if hasattr(h, "load_items_from_file_ex") else (h.load_items_from_file(parent, str(full_path)), "")
        if not ok:
            ui.set_message(f"Failed to load preset. {err}".strip(), error=True)
            return
        ui.set_message(f"Inserted: {preset.get('name', pid)}")

    ui.on_insert_clicked(lambda: on_insert_clicked())
    ui.on_preset_double_clicked(lambda pid: on_insert_clicked(pid))

    parent_win = h.get_main_qt_window()
    if parent_win:
        from PySide6.QtCore import Qt as QtCore
        flags = ui.windowFlags() | QtCore.WindowType.Window | QtCore.WindowType.WindowStaysOnTopHint
        ui.setWindowFlags(flags)
        ui.setParent(parent_win, flags)
    else:
        from PySide6.QtCore import Qt as QtCore
        ui.setWindowFlags(ui.windowFlags() | QtCore.WindowType.WindowStaysOnTopHint)
    ui.show()
