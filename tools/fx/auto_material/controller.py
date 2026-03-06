"""
Auto Material Builder controller — connects UI + logic + Solaris adapter.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from tools.fx.auto_material import config
from tools.fx.auto_material.logic import scan_and_group
from tools.fx.auto_material.ui import AutoMaterialUI


def run() -> None:
    import importlib
    import apps.houdini.solaris_adapter as sa
    importlib.reload(sa)

    if not sa.is_available():
        return

    ui = AutoMaterialUI()
    ui.setWindowTitle(config.WINDOW_TITLE)

    # --- Scan ---
    def on_scan() -> None:
        folder = ui.get_folder()
        if not folder:
            ui.set_message("Select a texture folder first.", error=True)
            return
        ui.set_message("")
        ui.show_loading("Scanning textures...")
        try:
            groups, unmatched = scan_and_group(folder, recursive=ui.is_recursive())
            if not groups and not unmatched:
                ui.set_message("No image files found in folder.", error=True)
                return
            ui.set_materials(groups, unmatched)
            ui.save_folder_to_history(folder)
        finally:
            ui.hide_loading()

    ui.on_scan_clicked(on_scan)

    # --- Publish button ---
    def on_publish() -> None:
        publish_path = sa.resolve_publish_texture_folder()
        if publish_path:
            ui.set_folder(publish_path)
            ui.set_message("")
        else:
            hip = sa.get_hip_dir()
            if hip is None:
                ui.set_message("Save .hip file first — $HIP is not set.", error=True)
            else:
                ui.set_message(
                    f"Publish folder not found: $HIP/../../../03_surfacing/02_texturing/publish",
                    error=True,
                )

    ui.on_publish_clicked(on_publish)

    # --- Create ---
    def on_create() -> None:
        if not sa.is_lop_context_available():
            ui.set_message("Open a Solaris / LOP network first.", error=True)
            return

        stage = sa.get_stage_context()
        if stage is None:
            ui.set_message("Cannot find /stage node.", error=True)
            return

        selected = sa.get_selected_lop_node()

        prefixes = ui.get_all_material_prefixes()
        if not prefixes:
            ui.set_message("No materials to create.", error=True)
            return

        ui.show_loading("Creating materials...")
        cancelled = False
        try:
            created: list[str] = []
            mat_lib_node = None
            total = len(prefixes)
            for idx, prefix in enumerate(prefixes, 1):
                if ui.is_cancelled():
                    cancelled = True
                    break
                ui.show_loading(f"Creating material {idx}/{total}:  {prefix}")
                group = ui._groups_data.get(prefix)
                if group is None:
                    continue
                mat_path = sa.build_material(
                    stage=stage,
                    material_name=prefix,
                    slots=group.slots,
                    selected_node=selected,
                )
                if mat_path:
                    created.append(mat_path)
                    if mat_lib_node is None:
                        mat_lib_node = stage.node("materiallibrary1")

            if mat_lib_node and created:
                sa.layout_material_library(mat_lib_node)
        finally:
            if cancelled:
                n = len(created)
                msg = f"Cancelled — {n} material(s) created before cancel" if n else "Cancelled"
                ui.show_done(msg, "Click to continue")
                ui.set_message(msg, error=True)
            elif created:
                ui.show_done(
                    f"Created {len(created)} material(s)",
                    "Click to continue",
                )
                ui.set_message(f"{len(created)} material(s) created.", error=False)
            else:
                ui.hide_loading()
                ui.set_message("Failed to create materials.", error=True)

    ui.on_create_clicked(on_create)

    # --- Auto assign ---
    def on_auto_assign() -> None:
        if not sa.is_lop_context_available():
            ui.set_message("Open a Solaris / LOP network first.", error=True)
            return
        stage = sa.get_stage_context()
        if stage is None:
            ui.set_message("Cannot find /stage node.", error=True)
            return
        selected = sa.get_selected_lop_node()
        if selected is None:
            ui.set_message("Select a LOP node (e.g. merge output) that has the scene graph and /materials.", error=True)
            return
        ui.set_message("")
        ui.show_loading("Auto assigning materials...")
        try:
            created, msg = sa.run_auto_assign(stage, selected)
            ui.hide_loading()
            if created > 0:
                ui.set_message(msg, error=False)
                sa.layout_nodes(stage)
            else:
                stage_usd = sa.get_stage_from_lop_node(selected)
                materials = sa.get_material_names_under_scope(stage_usd) if stage_usd else {}
                if materials:
                    reply = QMessageBox.question(
                        ui,
                        config.WINDOW_TITLE,
                        "Không tìm thấy prim *_grp khớp với material. Bạn có muốn vẫn tạo sẵn Assign Material LOP cho từng material (để gán tay sau)?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        ui.show_loading("Đang tạo Assign Material LOP...")
                        try:
                            n = sa.create_assign_for_all_materials(stage, selected, "/world/geo/*")
                            ui.set_message(
                                f"Đã tạo {n} Assign Material LOP (prim pattern: /world/geo/*). Gán tay sau." if n else msg,
                                error=(n == 0),
                            )
                            if n > 0:
                                sa.layout_nodes(stage)
                        finally:
                            ui.hide_loading()
                    else:
                        ui.set_message(msg, error=True)
                else:
                    ui.set_message(msg, error=True)
        except Exception as e:
            ui.hide_loading()
            ui.set_message(f"Auto assign failed: {e}", error=True)

    ui.on_auto_assign_clicked(on_auto_assign)

    # --- Show ---
    parent_win = sa.get_main_qt_window()
    if parent_win:
        from PySide6.QtCore import Qt
        flags = ui.windowFlags() | Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        ui.setWindowFlags(flags)
        ui.setParent(parent_win, flags)
    else:
        from PySide6.QtCore import Qt
        ui.setWindowFlags(ui.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    ui.show()
