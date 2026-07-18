"""
Standalone UI preview — no Houdini, no install.

  python -m tools.fx.node_preset_library.preview

Opens the Library window + Save dialog with sample categories/presets
so you can check colors, layout, and interaction visually.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Repo root on sys.path when run as module or script
_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _seed_sample_library(root: Path) -> None:
    from tools.fx.node_preset_library.logic import (
        add_category,
        add_preset,
        ensure_library_root,
        preset_relative_paths,
    )

    ensure_library_root(root)
    add_category("SOP Utils", root)
    add_category("LOP Layout", root)
    add_category("VOP Noise", root)

    samples = [
        ("Box + Transform", "sop_utils", "Quick start SOP chain", ["SOP"], 3),
        ("Scatter scatter", "sop_utils", "Point scatter utility", ["SOP"], 5),
        ("Camera pack", "lop_layout", "Camera + lights layout", ["LOP"], 4),
        ("Layer stack", "lop_layout", "", ["LOP"], 2),
        ("FBM noise", "vop_noise", "Fractal noise network", ["VOP"], 6),
        ("Empty look", "sop_utils", "No thumbnail yet", ["SOP"], 1),
    ]
    for i, (name, cat, desc, nets, count) in enumerate(samples):
        pid = f"preview{i:02d}"
        rel_cpio, rel_thumb = preset_relative_paths(cat, pid)
        (root / rel_cpio).parent.mkdir(parents=True, exist_ok=True)
        (root / rel_cpio).write_bytes(b"preview")
        thumb_rel = None
        # Leave last item without thumbnail to show placeholder
        if i < len(samples) - 1:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QPixmap, QColor, QPainter, QFont

            # Hi-res 16:9 sample so grid cards stay sharp on HiDPI
            pm = QPixmap(320, 180)
            pm.fill(QColor("#2a3142"))
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            font = QFont()
            font.setPointSize(18)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#5ec4b6"))
            painter.drawText(pm.rect(), int(Qt.AlignmentFlag.AlignCenter), name[:16])
            painter.end()
            full_thumb = root / rel_thumb
            pm.save(str(full_thumb))
            thumb_rel = rel_thumb
        add_preset(
            name=name,
            category_id=cat,
            relative_hipnc_path=rel_cpio,
            node_count=count,
            thumbnail_relative=thumb_rel,
            description=desc,
            networks=nets,
            preset_id=pid,
            library_root=root,
        )


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 is required. pip install PySide6")
        return 1

    from tools.fx.node_preset_library import config
    from tools.fx.node_preset_library.logic import (
        count_presets_by_category,
        list_categories,
        list_presets,
    )
    from tools.fx.node_preset_library.ui import NodePresetLibraryUI, SavePresetDialog

    app = QApplication(sys.argv)
    app.setApplicationName("Node Preset Library Preview")

    tmp = Path(tempfile.mkdtemp(prefix="npl_preview_"))
    _seed_sample_library(tmp)

    ui = NodePresetLibraryUI()
    suite_version = getattr(config, "get_suite_version", lambda: "preview")()
    ui.setWindowTitle(f"{config.WINDOW_TITLE}  —  preview (no Houdini)")
    ui.set_version_text(f"v{suite_version} · preview")
    from tools.fx.node_preset_library.prefs import DEFAULT_CARD_SCALE

    ui.apply_card_scale(DEFAULT_CARD_SCALE)

    cats = list_categories(tmp)
    counts = count_presets_by_category(tmp)
    total = sum(counts.values())
    enriched = [{"id": "__all__", "name": f"All ({total})"}]
    for c in cats:
        cid = c.get("id", "")
        n = counts.get(cid, 0)
        entry = dict(c)
        entry["name"] = f"{c.get('name', cid)} ({n})"
        enriched.append(entry)
    ui.set_categories(enriched, "__all__")
    ui.set_presets(list_presets(library_root=tmp), tmp)
    ui.set_message(f"Preview mode · sample library: {tmp}")

    # Wire light interactions (no Houdini)
    def on_cat(cid):
        if cid in (None, "", "__all__"):
            ui.set_presets(list_presets(library_root=tmp), tmp)
        else:
            ui.set_presets(list_presets(category_id=cid, library_root=tmp), tmp)

    ui.on_category_selected(on_cat)

    def on_preset_sel(pid):
        if not pid:
            ui.clear_inspector()
            return
        from tools.fx.node_preset_library.logic import get_preset

        ui.set_inspector_preset(get_preset(pid, tmp), tmp)

    ui.on_preset_selected(on_preset_sel)

    def on_search(text: str):
        q = text.strip().lower()
        presets = list_presets(library_root=tmp)
        if q:
            presets = [
                p
                for p in presets
                if q in (p.get("name") or "").lower() or q in (p.get("description") or "").lower()
            ]
        ui.set_presets(presets, tmp)

    ui.on_search_changed(on_search)
    ui.on_view_mode_changed(lambda _mode: None)
    ui.on_auto_detect_toggled(lambda enabled: ui.set_auto_detect_enabled(enabled))
    ui.on_network_filter_changed(
        lambda value: ui.set_presets(
            [
                p
                for p in list_presets(library_root=tmp)
                if value in ("__all__", "", None) or value in (p.get("networks") or [])
            ],
            tmp,
        )
    )
    ui.on_insert_clicked(lambda: ui.set_message("Insert skipped in preview (no Houdini)."))
    ui.on_delete_clicked(lambda: ui.set_message("Delete skipped in preview.", error=True))
    ui.on_new_category_clicked(lambda: ui.set_message("New category skipped in preview."))
    ui.on_import_clicked(lambda: ui.set_message("Import skipped in preview."))
    ui.on_export_clicked(lambda: ui.set_message("Export skipped in preview."))
    ui.on_open_folder_clicked(lambda: ui.set_message(f"Would open: {tmp}"))
    ui.on_favorite_clicked(lambda: ui.set_message("Favorite toggled in preview."))
    ui.on_preset_drag_finished(lambda pid: ui.set_message(f"Drag finished: {pid}"))
    ui.on_preset_double_clicked(lambda _pid: ui.set_message("Double-click insert skipped in preview."))

    def on_preset_ctx(pid: str, global_pos) -> None:
        from tools.fx.node_preset_library.prefs import is_favorite, toggle_favorite

        def do_fav() -> None:
            now = toggle_favorite(pid)
            ui.set_inspector_favorite(now)
            ui.set_message("Favorited" if now else "Unfavorited")

        ui.show_preset_context_menu(
            global_pos,
            favorited=is_favorite(pid),
            on_insert=lambda: ui.set_message(f"Insert (preview): {pid}"),
            on_edit=lambda: open_dialog("edit"),
            on_delete=lambda: ui.set_message(f"Delete (preview): {pid}", error=True),
            on_favorite=do_fav,
        )

    ui.on_preset_context_menu(on_preset_ctx)

    def open_dialog(mode: str = "save") -> None:
        from tools.fx.node_preset_library.logic import get_preset, update_preset, rename_category

        dlg = SavePresetDialog(ui)
        dlg.set_mode(mode)
        dlg.set_categories(list_categories(tmp))

        def do_paste() -> None:
            from PySide6.QtGui import QPixmap, QColor

            pm = QPixmap(120, 90)
            pm.fill(QColor("#5ec4b6"))
            dlg.set_thumbnail_from_pixmap(pm)

        def do_capture() -> None:
            from PySide6.QtGui import QPixmap, QColor, QPainter
            from PySide6.QtCore import Qt as QtCore

            pm = QPixmap(160, 120)
            pm.fill(QColor("#141820"))
            painter = QPainter(pm)
            painter.setPen(QColor("#5ec4b6"))
            painter.drawRoundedRect(40, 40, 44, 22, 5, 5)
            painter.drawRoundedRect(90, 55, 44, 22, 5, 5)
            painter.setPen(QColor("#eef1f6"))
            painter.drawText(pm.rect(), int(QtCore.AlignmentFlag.AlignBottom | QtCore.AlignmentFlag.AlignLeft), "  2 nodes")
            painter.end()
            dlg.set_thumbnail_from_pixmap(pm)

        dlg.on_paste_thumbnail(do_paste)
        dlg.on_capture_thumbnail(do_capture)
        dlg.on_new_category(lambda: None)

        if mode == "edit":
            pid = ui.get_selected_preset_id()
            if not pid:
                ui.set_message("Select a preset first.", error=True)
                return
            preset = get_preset(pid, tmp)
            if not preset:
                return
            dlg.set_name(preset.get("name") or "")
            dlg.set_category(preset.get("category_id") or "uncategorized")
            dlg.set_description(preset.get("description") or "")
            if dlg.exec() == SavePresetDialog.DialogCode.Accepted:
                update_preset(
                    pid,
                    name=dlg.get_name(),
                    category_id=dlg.get_category_id(),
                    description=dlg.get_description(),
                    library_root=tmp,
                )
                ui.set_message(f"Updated (preview): {dlg.get_name()}")
                on_cat(ui.get_selected_category_id())
            return

        do_capture()  # auto-capture on save
        dlg.exec()

    ui.on_save_clicked(lambda: open_dialog("save"))
    ui.on_edit_clicked(lambda: open_dialog("edit"))

    def on_cat_menu(cid: str, display_name: str, global_pos) -> None:
        from tools.fx.node_preset_library.logic import rename_category, delete_category

        special = cid in ("__all__", "__favorites__", "__recent__", "__sidebar__")
        bare = display_name.rsplit(" (", 1)[0] if " (" in display_name else display_name

        def do_rename() -> None:
            from PySide6.QtWidgets import QInputDialog

            new_name, ok = QInputDialog.getText(ui, "Rename category", "New name:", text=bare)
            if ok and new_name.strip():
                rename_category(cid, new_name.strip(), tmp)
                # refresh categories
                from tools.fx.node_preset_library.logic import count_presets_by_category

                cats = list_categories(tmp)
                counts = count_presets_by_category(tmp)
                total = sum(counts.values())
                enriched = [{"id": "__all__", "name": f"All ({total})"}]
                for c in cats:
                    n = counts.get(c.get("id", ""), 0)
                    entry = dict(c)
                    entry["name"] = f"{c.get('name', '')} ({n})"
                    enriched.append(entry)
                ui.set_categories(enriched, cid)
                ui.set_message(f"Renamed: {new_name.strip()}")

        def do_delete() -> None:
            delete_category(cid, tmp)
            ui.set_message(f"Deleted category: {bare}")
            cats = list_categories(tmp)
            from tools.fx.node_preset_library.logic import count_presets_by_category

            counts = count_presets_by_category(tmp)
            total = sum(counts.values())
            enriched = [{"id": "__all__", "name": f"All ({total})"}]
            for c in cats:
                n = counts.get(c.get("id", ""), 0)
                entry = dict(c)
                entry["name"] = f"{c.get('name', '')} ({n})"
                enriched.append(entry)
            ui.set_categories(enriched, "__all__")
            on_cat("__all__")

        ui.show_category_context_menu(
            global_pos,
            can_rename=not special,
            can_delete=(not special) and cid != "uncategorized",
            show_edit_actions=not special,
            on_rename=do_rename,
            on_delete=do_delete,
            on_open_folder=lambda: ui.set_message(f"Would open: {tmp}"),
        )

    ui.on_category_context_menu(on_cat_menu)

    def open_settings() -> None:
        import os
        import tempfile
        from tools.fx.node_preset_library.prefs import (
            default_library_root,
            get_card_scale,
            list_pinned_library_roots,
            list_recent_library_roots,
            prune_recent_prefs,
            remember_library_root,
            remove_recent_library_root,
            set_card_scale,
            toggle_pin_library_root,
        )
        from tools.fx.node_preset_library.ui import SettingsDialog

        # Isolate prefs in preview so we don't touch real user prefs
        prefs_file = Path(tempfile.gettempdir()) / "monofx_npl_preview_prefs.json"
        os.environ["MONOFX_NODE_PRESET_PREFS"] = str(prefs_file)
        prune_recent_prefs()
        # Seed current tmp lib into recent for demo
        remember_library_root(tmp)

        dialog = SettingsDialog(ui)
        dialog.set_current_path(str(tmp))
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
            sel = dialog.get_selected_recent_path()
            if not sel:
                return
            remove_recent_library_root(sel)
            fill_recent()

        def do_pin() -> None:
            sel = dialog.get_selected_recent_path()
            if not sel:
                return
            now = toggle_pin_library_root(sel)
            fill_recent()
            dialog.select_recent_path(sel)
            ui.set_message(f"{'Pinned' if now else 'Unpinned'}: {sel}")

        dialog.on_reset_default(do_reset)
        dialog.on_remove_recent(do_remove)
        dialog.on_pin_recent(do_pin)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            scale = set_card_scale(dialog.get_card_scale())
            ui.apply_card_scale(scale)
            chosen = dialog.get_current_path()
            if chosen:
                remember_library_root(chosen)
                ui.set_message(f"Preview Apply path: {chosen} · cards {scale}%")
                fill_recent()

    ui.on_settings_clicked(open_settings)

    ui.resize(900, 580)
    ui.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
