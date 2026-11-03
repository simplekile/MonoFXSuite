"""
Auto Material Builder controller — connects UI + logic + Solaris adapter.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from tools.fx.auto_material import config
from tools.fx.auto_material.logic import scan_and_group, substance_assign_entries, substance_source
from tools.fx.auto_material.ui import AutoMaterialUI


def run() -> None:
    import importlib
    import apps.houdini.solaris_adapter as sa
    importlib.reload(sa)

    if not sa.is_available():
        return

    ui = AutoMaterialUI()
    ui.setWindowTitle(config.WINDOW_TITLE)

    # The Painter export loaded last; Scan clears it, so Create builds from the folder again.
    state: dict = {"substance": None}

    # --- Scan ---
    def on_scan() -> None:
        folder = ui.get_folder()
        if not folder:
            ui.set_message("Select a texture folder first.", error=True)
            return
        state["substance"] = None
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

    # --- Substance Painter USD export ---
    def on_substance() -> None:
        usd_path = ui.ask_substance_usd()
        if not usd_path:
            return
        ui.set_message("")
        ui.show_loading("Reading Substance USD...")
        try:
            sublayers, materials, bindings = sa.read_substance_usd(usd_path)
            groups, source = substance_source(usd_path, sublayers, materials, bindings)
        except Exception as e:
            ui.set_message(f"Cannot read Substance USD: {e}", error=True)
            return
        finally:
            ui.hide_loading()
        if not groups:
            ui.set_message("No Painter material with textures in this USD.", error=True)
            return
        state["substance"] = source
        ui.set_materials(groups, [])
        ui.set_message(
            f"Substance USD: {len(groups)} material(s), geometry {', '.join(source.geo_layers)}. "
            "Create makes the Sublayer, the materials and the Assign Material.",
            error=False,
        )

    ui.on_substance_clicked(on_substance)

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

        # Painter export: Sublayer (its geometry) -> Material Library -> Assign Material, named
        # after the export without its version so a newer export updates the same nodes.
        source = state["substance"]
        mat_lib_name = "materiallibrary1"
        if source is not None:
            selected = sa.get_or_create_substance_sublayer(
                stage, source.node_base + config.SUBSTANCE_GEO_NODE_SUFFIX, source.geo_layers,
            )
            if selected is None:
                ui.set_message("Cannot create the Sublayer for the Substance geometry.", error=True)
                return
            mat_lib_name = source.node_base + config.SUBSTANCE_MATLIB_NODE_SUFFIX

        ui.show_loading("Creating materials...")
        cancelled = False
        created: list[str] = []
        updated: list[str] = []
        notes: list[str] = []
        material_paths: dict[str, str] = {}
        try:
            with sa.manual_update():
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
                    result = sa.build_material(
                        stage=stage,
                        material_name=prefix,
                        slots=group.slots,
                        mat_lib_name=mat_lib_name,
                        selected_node=selected,
                    )
                    if result is None:
                        continue
                    (updated if result.updated else created).append(result.node_name)
                    notes += [f"{result.node_name}: {n}" for n in result.notes]
                    material_paths[prefix] = result.path
                    if mat_lib_node is None:
                        mat_lib_node = stage.node(mat_lib_name)

                # Place only the new builders; the ones already there keep their position.
                if mat_lib_node and created:
                    sa.layout_material_library(mat_lib_node, new_names=created)

                if source is not None and mat_lib_node is not None:
                    assign, added = sa.assign_substance_materials(
                        stage,
                        mat_lib_node,
                        source.node_base + config.SUBSTANCE_ASSIGN_NODE_SUFFIX,
                        substance_assign_entries(source, material_paths),
                    )
                    if assign is not None:
                        notes.append(f"{assign.name()}: {added} binding(s) added from the Substance USD.")
        finally:
            done = ", ".join(
                s for s in (
                    f"created {len(created)}" if created else "",
                    f"updated {len(updated)}" if updated else "",
                ) if s
            )
            if cancelled:
                msg = f"Cancelled: {done} before cancel" if done else "Cancelled"
                ui.show_done(msg, "Click to continue")
                ui.set_message(msg, error=True)
            elif done:
                msg = f"Materials {done}."
                ui.show_done(msg, "Click to continue")
                ui.set_message(msg, error=False)
            else:
                ui.hide_loading()
                ui.set_message("Failed to create materials.", error=True)
        if notes:
            QMessageBox.information(ui, config.WINDOW_TITLE, "\n".join(notes))

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
                ui.show_done(msg, "Click to continue")
                ui.set_message(msg, error=False)
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
                            if n > 0:
                                done_msg = f"Đã tạo {n} Assign Material LOP (prim pattern: /world/geo/*). Gán tay sau."
                                ui.show_done(done_msg, "Click to continue")
                                ui.set_message(done_msg, error=False)
                            else:
                                ui.hide_loading()
                                ui.set_message(msg, error=True)
                        except Exception:
                            ui.hide_loading()
                            raise
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
