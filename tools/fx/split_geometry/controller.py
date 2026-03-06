"""
Split Geometry controller — luôn mở UI; không có node thì thông báo trên giao diện.
"""

from __future__ import annotations

from tools.fx.split_geometry import config
from tools.fx.split_geometry.ui import SplitGeometryUI


def run() -> None:
    import importlib
    import apps.houdini.adapter as h
    importlib.reload(h)  # ensure latest adapter (e.g. after suite update) without restarting Houdini

    if not h.is_available():
        return

    sop = None
    for n in h.get_selected_nodes():
        if h.is_sop_node(n):
            sop = n
            break

    ui = SplitGeometryUI(title=config.WINDOW_TITLE)
    ui.setWindowTitle(config.WINDOW_TITLE)

    def refresh_list_for_attr(attr_name: str) -> None:
        nonlocal sop
        if sop is None:
            return
        c = h.get_value_counts_by_string_attribute(sop, attr_name)
        vals = sorted(c.keys(), key=lambda v: (-c[v], v)) if c else []
        ui.set_values(vals, counts=c)
        ui.set_blast_button_enabled(bool(c))

    if sop is None:
        ui.set_message("Chọn một SOP node rồi bấm nút bên cạnh để tải.")
        ui.set_source_node_name("—")
        ui.set_attr_combo([], None)
        ui.set_values([], None)
        ui.set_blast_button_enabled(False)
    else:
        ui.set_message("")
        ui.set_source_node_name(h.get_node_name(sop))
        attr_names = h.get_string_attribute_names_from_geometry(sop)
        if not attr_names:
            ui.set_message("Node không có string attribute nào (path, shop_materialpath, ...).")
            ui.set_attr_combo([], None)
            ui.set_blast_button_enabled(False)
        else:
            current_attr = "path" if "path" in attr_names else attr_names[0]
            counts = h.get_value_counts_by_string_attribute(sop, current_attr)
            ui.set_attr_combo(attr_names, current_attr=current_attr)
            vals = sorted(counts.keys(), key=lambda v: (-counts[v], v)) if counts else []
            ui.set_values(vals, counts=counts)
            ui.set_blast_button_enabled(bool(counts))

    ui.on_attr_changed(refresh_list_for_attr)

    def on_select_source() -> None:
        nonlocal sop
        new_sop = None
        for n in h.get_selected_nodes():
            if h.is_sop_node(n):
                new_sop = n
                break
        if new_sop is None:
            ui.set_message("Chọn ít nhất một SOP node trong network rồi bấm lại.")
            return
        sop = new_sop
        ui.set_message("")
        ui.set_source_node_name(h.get_node_name(sop))
        attrs = h.get_string_attribute_names_from_geometry(sop)
        if not attrs:
            ui.set_message("Node không có string attribute nào.")
            ui.set_attr_combo([], None)
            ui.set_blast_button_enabled(False)
            return
        cur = ui.get_selected_attribute() if ui.get_selected_attribute() in attrs else attrs[0]
        ui.set_attr_combo(attrs, current_attr=cur)
        refresh_list_for_attr(cur)

    ui.on_select_source_clicked(on_select_source)

    def create_blast():
        if sop is None:
            return
        attr = ui.get_selected_attribute()
        selected = ui.get_selected_values()
        if not selected:
            h.ui_display_message(
                "Chọn ít nhất một value trong list rồi bấm Create Blast SOP.",
                title=config.WINDOW_TITLE,
            )
            return
        parent = sop.parent()
        pos = sop.position()
        created = []
        for i, path_value in enumerate(selected):
            group_expr = f"@{attr}={path_value}" if path_value else f"@{attr}="
            safe_name = (path_value or "empty").replace("/", "_").strip("_") or "empty"
            new_node = h.create_node(parent, "blast", name=f"blast_{safe_name}")
            if new_node is None:
                continue
            h.set_node_input(new_node, 0, sop)
            h.set_parm(new_node, "group", group_expr)
            if not h.set_parm(new_node, "negate", 1):
                h.set_parm(new_node, "deletenonselected", 1)
            # Xếp ngang (một hàng) thay vì dọc
            new_node.setPosition((pos[0] + i * 2.0, pos[1] - 1.5))
            created.append(group_expr)
        if created:
            ui.show_info(
                config.WINDOW_TITLE,
                f"Đã tạo {len(created)} Blast SOP (mỗi value một node), Delete Non Selected = on.",
            )

    ui.on_create_blast_clicked(create_blast)

    parent_win = h.get_main_qt_window()
    if parent_win:
        from PySide6.QtCore import Qt
        ui.setWindowFlags(ui.windowFlags() | Qt.WindowType.Window)
        ui.setParent(parent_win, ui.windowFlags())
    ui.show()
