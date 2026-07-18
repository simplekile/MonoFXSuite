"""
Node Preset Library controller — UI + logic + Houdini adapter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
from PySide6.QtGui import QPixmap

from tools.fx.node_preset_library import config
from tools.fx.node_preset_library.logic import (
    add_category,
    add_preset,
    category_id_from_name,
    color_for_category_id,
    count_presets_by_category,
    delete_category,
    delete_preset,
    ensure_library_root,
    export_library_to_zip,
    get_category,
    get_preset,
    list_categories,
    list_presets,
    merge_library_from_folder,
    merge_library_from_zip,
    new_preset_id,
    preset_relative_paths,
    rename_category,
    set_category_color,
    update_preset,
)
from tools.fx.node_preset_library.ui import (
    CategoryDialog,
    NodePresetLibraryUI,
    SavePresetDialog,
    SettingsDialog,
)
from tools.fx.node_preset_library.prefs import (
    default_library_root,
    get_card_scale,
    get_window_geometry,
    is_favorite,
    list_favorite_ids,
    list_pinned_library_roots,
    list_recent_library_roots,
    list_recent_preset_ids,
    prune_recent_prefs,
    remember_library_root,
    remember_recent_preset,
    remove_recent_library_root,
    set_card_scale,
    set_window_geometry,
    toggle_favorite,
    toggle_pin_library_root,
)


def _find_open_library_windows() -> list[Any]:
    """Find live library windows by objectName (no QVariant/QWidget property — avoids shiboken errors)."""
    app = QApplication.instance()
    if app is None:
        return []
    found: list[Any] = []
    for w in app.topLevelWidgets():
        try:
            if w.objectName() == "NodePresetLibraryWindow":
                found.append(w)
        except RuntimeError:
            continue
    return found


def _close_open_library_windows() -> None:
    for w in _find_open_library_windows():
        try:
            if hasattr(w, "persist_window_geometry"):
                w.persist_window_geometry()
            w.close()
            w.deleteLater()
        except RuntimeError:
            continue


def run() -> None:
    import importlib
    import apps.houdini.adapter as h
    importlib.reload(h)

    if not h.is_available():
        h.ui_display_message("Houdini is not available.", "Node Preset Library")
        return

    # One window only — close prior instance (saves geometry) before opening fresh
    _close_open_library_windows()

    library_root = config.get_library_root()
    ensure_library_root(library_root)
    # Mutable holder so Settings can switch active root without rewriting closures
    ctx: dict = {"library_root": library_root}

    ui = NodePresetLibraryUI()
    suite_version = getattr(config, "get_suite_version", lambda: "0.0.0")()
    ui.setWindowTitle(f"{config.WINDOW_TITLE}  —  v{suite_version}")
    ui.set_version_text(f"v{suite_version}")
    ui.apply_card_scale(get_card_scale())
    ui.restore_window_geometry(get_window_geometry())
    ui.on_geometry_save(set_window_geometry)

    state = {
        "category_id": "__all__",
        "search": "",
        "network": "__all__",
        "auto_detect": True,
        "view_mode": "grid",
    }

    def root() -> Path:
        return ctx["library_root"]

    def refresh_categories(select_id: Optional[str] = None) -> None:
        cats = list_categories(root())
        if not cats and select_id is None:
            add_category("Uncategorized", root())
            cats = list_categories(root())
        counts = count_presets_by_category(root())
        total = sum(counts.values())
        fav_n = len([pid for pid in list_favorite_ids() if get_preset(pid, root())])
        recent_n = len([pid for pid in list_recent_preset_ids() if get_preset(pid, root())])
        enriched: list[dict] = [
            {"id": "__all__", "name": f"All ({total})", "color": color_for_category_id("__all__")},
            {
                "id": "__favorites__",
                "name": f"Favorites ({fav_n})",
                "color": color_for_category_id("__favorites__"),
            },
            {
                "id": "__recent__",
                "name": f"Recent ({recent_n})",
                "color": color_for_category_id("__recent__"),
            },
        ]
        for c in cats:
            cid = c.get("id", "")
            n = counts.get(cid, 0)
            name = c.get("name", cid or "Uncategorized")
            c = dict(c)
            c["name"] = f"{name} ({n})"
            enriched.append(c)
        ui.set_categories(enriched, select_id or state.get("category_id") or "__all__")

    def refresh_presets(category_id: Optional[str] = None) -> None:
        state["category_id"] = category_id or "__all__"
        cid = state["category_id"]
        if cid in (None, "", "__all__"):
            presets = list_presets(category_id=None, library_root=root())
        elif cid == "__favorites__":
            by_id = {p.get("id"): p for p in list_presets(library_root=root())}
            presets = [by_id[i] for i in list_favorite_ids() if i in by_id]
        elif cid == "__recent__":
            by_id = {p.get("id"): p for p in list_presets(library_root=root())}
            presets = [by_id[i] for i in list_recent_preset_ids() if i in by_id]
        else:
            presets = list_presets(category_id=cid, library_root=root())
        net = state["network"]
        if net not in ("__all__", "", None):
            presets = [p for p in presets if net in (p.get("networks") or [])]
        text = state["search"].strip().lower()
        if text:
            def matches(p: dict) -> bool:
                name = (p.get("name") or "").lower()
                desc = (p.get("description") or "").lower()
                return text in name or text in desc
            presets = [p for p in presets if matches(p)]
        ui.set_presets(presets, root())

    def switch_library_root(new_root: Path) -> None:
        path = remember_library_root(new_root)
        ensure_library_root(path)
        ctx["library_root"] = path
        ui.set_message(f"Library: {path}")
        refresh_categories("__all__")
        refresh_presets("__all__")

    def open_settings() -> None:
        prune_recent_prefs()
        dialog = SettingsDialog(ui)
        dialog.set_current_path(str(root()))
        dialog.set_card_scale(get_card_scale())

        def fill_recent() -> None:
            dialog.set_recent_paths(
                [str(p) for p in list_recent_library_roots(existing_only=True)],
                [str(p) for p in list_pinned_library_roots(existing_only=True)],
            )

        fill_recent()

        def do_reset() -> None:
            dialog.set_current_path(str(default_library_root()))

        def do_remove() -> None:
            selected = dialog.get_selected_recent_path()
            if not selected:
                ui.set_message("Select a recent path to remove.", error=True)
                return
            remove_recent_library_root(selected)
            fill_recent()
            ui.set_message(f"Removed from recent: {selected}")

        def do_pin() -> None:
            selected = dialog.get_selected_recent_path()
            if not selected:
                ui.set_message("Select a recent path to pin.", error=True)
                return
            now = toggle_pin_library_root(selected)
            fill_recent()
            dialog.select_recent_path(selected)
            ui.set_message(f"{'Pinned' if now else 'Unpinned'}: {selected}")

        dialog.on_reset_default(do_reset)
        dialog.on_remove_recent(do_remove)
        dialog.on_pin_recent(do_pin)

        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return

        scale = set_card_scale(dialog.get_card_scale())
        ui.apply_card_scale(scale)

        chosen = dialog.get_current_path()
        if not chosen:
            ui.set_message("Enter a library path.", error=True)
            return
        try:
            switch_library_root(Path(chosen))
        except OSError as e:
            ui.set_message(f"Cannot use library path: {e}", error=True)

    ui.on_settings_clicked(open_settings)

    def on_category_selected(cid: Optional[str]) -> None:
        refresh_presets(cid)

    ui.on_category_selected(on_category_selected)
    refresh_categories()
    ui.ensure_category_selected()
    refresh_presets(ui.get_selected_category_id() or "__all__")

    def _wire_thumbnail_buttons(dialog: SavePresetDialog, *, auto_capture: bool) -> None:
        def do_paste() -> None:
            clipboard = QApplication.clipboard()
            img = clipboard.image()
            if img.isNull():
                QMessageBox.information(dialog, "Paste thumbnail", "No image in clipboard.")
                return
            dialog.set_thumbnail_from_pixmap(QPixmap.fromImage(img))

        def do_capture() -> None:
            pix = None
            if hasattr(h, "capture_selection_thumbnail"):
                try:
                    pix = h.capture_selection_thumbnail()
                except Exception:
                    pix = None
            if pix is None or (hasattr(pix, "isNull") and pix.isNull()):
                QMessageBox.information(
                    dialog,
                    "Capture thumbnail",
                    "Could not capture selection. Select nodes in the network and try again, "
                    "or paste a screenshot.",
                )
                return
            dialog.set_thumbnail_from_pixmap(pix)

        dialog.on_paste_thumbnail(do_paste)
        dialog.on_capture_thumbnail(do_capture)
        if auto_capture:
            do_capture()

        def do_new_category() -> None:
            used = {
                str(c.get("color"))
                for c in list_categories(root())
                if c.get("color")
            }
            cat_dlg = CategoryDialog(dialog, used_colors=used)
            if cat_dlg.exec() != CategoryDialog.DialogCode.Accepted:
                return
            name = cat_dlg.get_name()
            if not name:
                return
            add_category(name, root(), color=cat_dlg.get_color())
            dialog.set_categories(list_categories(root()))
            dialog.set_category(category_id_from_name(name))

        dialog.on_new_category(do_new_category)

    def _save_thumbnail(pix: Optional[QPixmap], rel_thumb: str) -> Optional[str]:
        if not pix or pix.isNull():
            return None
        full_thumb = root() / rel_thumb
        full_thumb.parent.mkdir(parents=True, exist_ok=True)
        if pix.save(str(full_thumb)):
            return rel_thumb
        return None

    def open_save_dialog() -> None:
        parent, items = h.get_selected_network_items()
        if not parent or not items:
            ui.set_message("Select one or more nodes in the same network first.", error=True)
            return
        dialog = SavePresetDialog(ui)
        dialog.set_mode("save")
        cats = list_categories(root())
        if not cats:
            add_category("Uncategorized", root())
            cats = list_categories(root())
        dialog.set_categories(cats)
        _wire_thumbnail_buttons(dialog, auto_capture=True)

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
                networks = h.detect_network_tags_for_items(parent, items)
            except Exception:
                networks = []
        # Product rule: one network tag per preset
        networks = networks[:1]
        if state["auto_detect"] and networks:
            state["network"] = networks[0]
            ui.set_network_filter_value(state["network"])
        cat_name = dialog.get_category() or "Uncategorized"
        cat_id = dialog.get_category_id() or category_id_from_name(cat_name)
        add_category(cat_name, root())
        preset_id = new_preset_id()
        rel_cpio, rel_thumb = preset_relative_paths(cat_id, preset_id)
        full_cpio = root() / rel_cpio
        full_cpio.parent.mkdir(parents=True, exist_ok=True)
        if not h.save_items_to_file(
            parent,
            items,
            str(full_cpio),
            save_hda_fallbacks=dialog.get_embed_hda(),
        ):
            ui.set_message("Failed to save nodes to file.", error=True)
            return
        thumb_rel = _save_thumbnail(dialog.get_thumbnail_pixmap(), rel_thumb)
        add_preset(
            name=name,
            category_id=cat_id,
            relative_hipnc_path=rel_cpio,
            node_count=len(items),
            thumbnail_relative=thumb_rel,
            description=description,
            networks=networks,
            preset_id=preset_id,
            library_root=root(),
        )
        embed_note = " (HDA embedded)" if dialog.get_embed_hda() else ""
        ui.set_message(f"Saved preset: {name}{embed_note}")
        refresh_categories(cat_id)
        refresh_presets(cat_id)

    def open_edit_dialog() -> None:
        pid = ui.get_selected_preset_id()
        if not pid:
            ui.set_message("Select a preset first.", error=True)
            return
        preset = get_preset(pid, root())
        if not preset:
            ui.set_message("Preset not found.", error=True)
            return

        dialog = SavePresetDialog(ui)
        dialog.set_mode("edit")
        cats = list_categories(root())
        if not cats:
            add_category("Uncategorized", root())
            cats = list_categories(root())
        dialog.set_categories(cats)
        dialog.set_name(preset.get("name") or "")
        dialog.set_category(preset.get("category_id") or "uncategorized")
        dialog.set_description(preset.get("description") or "")
        thumb_rel_existing = preset.get("thumbnail")
        if thumb_rel_existing:
            thumb_path = root() / thumb_rel_existing
            if thumb_path.is_file():
                dialog.set_thumbnail_from_pixmap(QPixmap(str(thumb_path)))
        # Edit: do not auto-overwrite existing thumb; user can capture/paste
        _wire_thumbnail_buttons(dialog, auto_capture=False)

        if dialog.exec() != SavePresetDialog.DialogCode.Accepted:
            return
        name = dialog.get_name()
        if not name:
            ui.set_message("Enter a preset name.", error=True)
            return
        cat_name = dialog.get_category() or "Uncategorized"
        cat_id = dialog.get_category_id() or category_id_from_name(cat_name)
        add_category(cat_name, root())

        ok = update_preset(
            pid,
            name=name,
            category_id=cat_id,
            description=dialog.get_description(),
            library_root=root(),
        )
        if not ok:
            ui.set_message("Failed to update preset.", error=True)
            return

        pix = dialog.get_thumbnail_pixmap()
        if pix and not pix.isNull():
            _, rel_thumb = preset_relative_paths(cat_id, pid)
            saved = _save_thumbnail(pix, rel_thumb)
            if saved:
                update_preset(pid, thumbnail_relative=saved, library_root=root())

        ui.set_message(f"Updated preset: {name}")
        refresh_categories(cat_id)
        refresh_presets(cat_id)

    def update_preset_from_selection(preset_id: Optional[str] = None) -> None:
        pid = preset_id or ui.get_selected_preset_id()
        if not pid:
            ui.set_message("Select a preset first.", error=True)
            return
        preset = get_preset(pid, root())
        if not preset:
            ui.set_message("Preset not found.", error=True)
            return
        parent, items = h.get_selected_network_items()
        if not parent or not items:
            ui.set_message("Select one or more nodes in the same network first.", error=True)
            return

        name = preset.get("name", pid)
        n = len(items)
        answer = QMessageBox.question(
            ui,
            "Update preset",
            (
                f'Overwrite preset "{name}" with the current selection ({n} node'
                f'{"s" if n != 1 else ""})?\n\n'
                "Saved nodes will be replaced. Name, category, and description stay the same."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        rel_path = preset.get("file")
        if not rel_path:
            ui.set_message("Preset has no file.", error=True)
            return
        full_cpio = root() / rel_path
        full_cpio.parent.mkdir(parents=True, exist_ok=True)
        if not h.save_items_to_file(parent, items, str(full_cpio), save_hda_fallbacks=False):
            ui.set_message("Failed to update preset nodes.", error=True)
            return

        networks: list[str] = []
        if hasattr(h, "detect_network_tags_for_items"):
            try:
                networks = h.detect_network_tags_for_items(parent, items)
            except Exception:
                networks = []
        networks = networks[:1]

        update_kwargs: dict = {
            "node_count": n,
            "library_root": root(),
        }
        if networks:
            update_kwargs["networks"] = networks
        if not update_preset(pid, **update_kwargs):
            ui.set_message("Saved nodes but failed to update preset metadata.", error=True)
            return

        # Refresh thumbnail from current selection when possible
        pix = None
        if hasattr(h, "capture_selection_thumbnail"):
            try:
                pix = h.capture_selection_thumbnail()
            except Exception:
                pix = None
        if pix is not None and not (hasattr(pix, "isNull") and pix.isNull()):
            cat_id = preset.get("category_id") or "uncategorized"
            _, rel_thumb = preset_relative_paths(cat_id, pid)
            saved = _save_thumbnail(pix, rel_thumb)
            if saved:
                update_preset(pid, thumbnail_relative=saved, library_root=root())

        if state["auto_detect"] and networks:
            state["network"] = networks[0]
            ui.set_network_filter_value(state["network"])

        ui.set_message(f"Updated preset from selection: {name} ({n} nodes)")
        refresh_categories(state["category_id"])
        refresh_presets(state["category_id"])
        refreshed = get_preset(pid, root())
        ui.set_inspector_preset(refreshed, root(), favorited=is_favorite(pid))

    ui.on_save_clicked(open_save_dialog)

    def on_houdini_nodes_dropped(paths: list[str]) -> None:
        parent, items = (None, [])
        if hasattr(h, "select_network_items_by_paths"):
            try:
                parent, items = h.select_network_items_by_paths(paths)
            except Exception:
                parent, items = (None, [])
        if not parent or not items:
            # Fallback: current selection (some Houdini builds omit MIME outside Python Panel)
            parent, items = h.get_selected_network_items()
        if not parent or not items:
            ui.set_message(
                "Drop nodes from the Network Editor (same network), or select nodes then drop.",
                error=True,
            )
            return
        open_save_dialog()

    if hasattr(h, "parse_node_paths_from_mime"):
        ui.set_houdini_mime_extractor(h.parse_node_paths_from_mime)
    ui.on_houdini_nodes_dropped(on_houdini_nodes_dropped)

    def on_new_category_clicked() -> None:
        used = {
            str(c.get("color"))
            for c in list_categories(root())
            if c.get("color")
        }
        cat_dlg = CategoryDialog(ui, used_colors=used)
        if cat_dlg.exec() != CategoryDialog.DialogCode.Accepted:
            return
        name = cat_dlg.get_name()
        if not name:
            return
        add_category(name, root(), color=cat_dlg.get_color())
        cid = category_id_from_name(name)
        refresh_categories(cid)
        refresh_presets(cid)
        ui.set_message(f"Added category: {name}")

    ui.on_new_category_clicked(on_new_category_clicked)

    def on_category_context(cid: str, display_name: str, global_pos: QPoint) -> None:
        special = cid in ("__all__", "__favorites__", "__recent__", "__sidebar__")
        # Strip trailing " (N)" for rename default
        bare = display_name
        if bare and bare.rsplit(" (", 1)[-1].endswith(")") and bare.count("("):
            bare = bare.rsplit(" (", 1)[0]
        can_delete = (not special) and cid not in ("uncategorized",)

        def do_rename() -> None:
            new_name, ok = QInputDialog.getText(ui, "Rename category", "New name:", text=bare)
            if not ok or not new_name.strip():
                return
            if rename_category(cid, new_name.strip(), root()):
                ui.set_message(f"Renamed category to: {new_name.strip()}")
                refresh_categories(cid)
                refresh_presets(state["category_id"])
            else:
                ui.set_message("Failed to rename category.", error=True)

        def do_set_color() -> None:
            cat = get_category(cid, root()) or {}
            used = {
                str(c.get("color"))
                for c in list_categories(root())
                if c.get("color") and c.get("id") != cid
            }
            cat_dlg = CategoryDialog(
                ui,
                title="Set category color",
                name=bare or str(cat.get("name") or cid),
                color=str(cat.get("color") or color_for_category_id(cid)),
                used_colors=used,
            )
            if cat_dlg.exec() != CategoryDialog.DialogCode.Accepted:
                return
            # Keep name if unchanged; allow rename from this dialog too
            new_name = cat_dlg.get_name()
            if new_name and new_name != bare:
                rename_category(cid, new_name, root())
            if set_category_color(cid, cat_dlg.get_color(), root()):
                ui.set_message(f"Updated color for: {new_name or bare}")
                refresh_categories(cid)
                refresh_presets(state["category_id"])
            else:
                ui.set_message("Failed to set category color.", error=True)

        def do_delete() -> None:
            answer = QMessageBox.question(
                ui,
                "Delete category",
                f'Delete category "{bare}"?\nPresets move to Uncategorized.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            if delete_category(cid, root()):
                ui.set_message(f"Deleted category: {bare}")
                refresh_categories("__all__")
                refresh_presets("__all__")
            else:
                ui.set_message("Failed to delete category.", error=True)

        ui.show_category_context_menu(
            global_pos,
            can_rename=not special,
            can_delete=can_delete,
            show_edit_actions=not special,
            on_rename=do_rename,
            on_set_color=do_set_color,
            on_delete=do_delete,
            on_open_folder=on_open_folder,
        )

    # Define open-folder before wiring category menu (menu references it)
    def on_open_folder() -> None:
        import os
        import subprocess
        import sys

        path = root()
        ensure_library_root(path)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            ui.set_message(f"Opened: {path}")
        except Exception as e:
            ui.set_message(f"Could not open folder: {e}", error=True)

    ui.on_open_folder_clicked(on_open_folder)
    ui.on_category_context_menu(on_category_context)

    def on_import_clicked() -> None:
        path = ui.show_import_zip_or_folder_dialog()
        if not path:
            return
        src = Path(path)
        try:
            if src.suffix.lower() == ".zip":
                cats_added, presets_added = merge_library_from_zip(src, root())
            else:
                cats_added, presets_added = merge_library_from_folder(src, root())
            ui.set_message(f"Imported: {cats_added} categories, {presets_added} presets.")
            refresh_categories()
            refresh_presets(ui.get_selected_category_id())
        except Exception as e:
            ui.set_message(f"Import failed: {e}", error=True)

    ui.on_import_clicked(on_import_clicked)

    def on_export_clicked() -> None:
        dest = ui.show_export_zip_dialog()
        if not dest:
            return
        try:
            out = export_library_to_zip(dest, root())
            ui.set_message(f"Exported: {out}")
        except Exception as e:
            ui.set_message(f"Export failed: {e}", error=True)

    ui.on_export_clicked(on_export_clicked)

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
                    nets = h.detect_network_tags_for_parent(parent)
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

    ui.on_view_mode_changed(on_view_mode)

    def on_insert_clicked(
        preset_id: Optional[str] = None,
        *,
        place_at_cursor: bool = False,
    ) -> None:
        pid = preset_id or ui.get_selected_preset_id()
        if not pid:
            ui.set_message("Select a preset first.", error=True)
            return
        preset = get_preset(pid, root())
        if not preset:
            ui.set_message("Preset not found.", error=True)
            return
        rel_path = preset.get("file")
        if not rel_path:
            ui.set_message("Preset has no file.", error=True)
            return
        full_path = root() / rel_path
        if not full_path.is_file():
            ui.set_message(f"File not found: {rel_path}", error=True)
            return
        parent = h.get_current_network_parent()
        if not parent:
            ui.set_message("Open a network (e.g. double-click a node) and try again.", error=True)
            return
        if hasattr(h, "load_items_from_file_ex"):
            ok, err = h.load_items_from_file_ex(
                parent,
                str(full_path),
                place_at_cursor=place_at_cursor,
            )
        else:
            ok, err = h.load_items_from_file(parent, str(full_path)), ""
        if not ok:
            ui.set_message(f"Failed to load preset. {err}".strip(), error=True)
            return
        remember_recent_preset(pid)
        refresh_categories(state["category_id"])
        where = "at cursor" if place_at_cursor else "at center view"
        ui.set_message(f"Inserted {where}: {preset.get('name', pid)}")

    ui.on_insert_clicked(lambda: on_insert_clicked())
    ui.on_preset_double_clicked(lambda pid: on_insert_clicked(pid))

    def on_drag_finished(pid: str) -> None:
        # Drag-drop onto Network Editor → insert at cursor under mouse
        if hasattr(h, "is_network_editor_under_cursor") and h.is_network_editor_under_cursor():
            on_insert_clicked(pid, place_at_cursor=True)
        else:
            ui.set_message("Drop on the Network Editor to insert (or right-click → Insert).")

    ui.on_preset_drag_finished(on_drag_finished)

    def on_preset_selected(pid: Optional[str]) -> None:
        if not pid:
            ui.clear_inspector()
            return
        preset = get_preset(pid, root())
        ui.set_inspector_preset(preset, root(), favorited=is_favorite(pid))

    ui.on_preset_selected(on_preset_selected)

    def on_favorite_clicked() -> None:
        pid = ui.get_selected_preset_id()
        if not pid:
            return
        now = toggle_favorite(pid)
        ui.set_inspector_favorite(now)
        ui.set_message("Added to Favorites" if now else "Removed from Favorites")
        refresh_categories(state["category_id"])
        if state["category_id"] == "__favorites__":
            refresh_presets("__favorites__")

    ui.on_favorite_clicked(on_favorite_clicked)

    def on_delete_clicked() -> None:
        pid = ui.get_selected_preset_id()
        if not pid:
            ui.set_message("Select a preset first.", error=True)
            return
        preset = get_preset(pid, root())
        if not preset:
            ui.set_message("Preset not found.", error=True)
            return
        name = preset.get("name", pid)
        answer = QMessageBox.question(
            ui,
            "Delete preset",
            f'Delete preset "{name}"? This cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not delete_preset(pid, root()):
            ui.set_message("Failed to delete preset.", error=True)
            return
        ui.set_message(f"Deleted preset: {name}")
        refresh_categories(ui.get_selected_category_id())
        refresh_presets(state["category_id"])

    ui.on_edit_clicked(open_edit_dialog)
    ui.on_update_from_selection_clicked(update_preset_from_selection)
    ui.on_delete_clicked(on_delete_clicked)

    def on_preset_ctx(pid: str, global_pos: QPoint) -> None:
        ui.show_preset_context_menu(
            global_pos,
            favorited=is_favorite(pid),
            on_insert=lambda: on_insert_clicked(pid),
            on_edit=open_edit_dialog,
            on_update_from_selection=lambda: update_preset_from_selection(pid),
            on_delete=on_delete_clicked,
            on_favorite=on_favorite_clicked,
        )

    ui.on_preset_context_menu(on_preset_ctx)

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
    ui.raise_()
    ui.activateWindow()
