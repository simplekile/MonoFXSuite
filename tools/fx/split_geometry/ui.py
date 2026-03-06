"""
Split Geometry UI — title, node nguồn, combo attribute, SelectableListMulti (rule), Blast SOP.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)
from PySide6.QtWidgets import QAbstractItemView
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QStyle

BACKGROUND = "#18181b"
TEXT_PRIMARY = "#fafafa"
TEXT_LABEL = "#a1a1aa"
TEXT_META = "#71717a"
TEXT_ERROR = "#fca5a5"

BUTTON_STYLE = """
    QPushButton, QToolButton {
        background: rgba(24, 24, 27, 0.35);
        color: #a1a1aa;
        padding: 6px 12px;
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 8px;
    }
    QPushButton:hover, QToolButton:hover {
        background: rgba(255, 255, 255, 0.12);
        border: 1px solid rgba(63, 63, 70, 0.80);
        color: #e4e4e7;
    }
    QPushButton:disabled, QToolButton:disabled {
        color: rgba(161, 161, 170, 0.5);
        background: rgba(24, 24, 27, 0.25);
    }
"""

BUTTON_PRIMARY_STYLE = """
    QPushButton {
        background: rgba(37, 99, 235, 0.22);
        border: 1px solid rgba(37, 99, 235, 0.70);
        color: #fafafa;
        padding: 8px 12px;
        border-radius: 8px;
    }
    QPushButton:hover {
        background: rgba(37, 99, 235, 0.35);
        border-color: rgba(59, 130, 246, 0.80);
    }
    QPushButton:disabled {
        border: 1px solid rgba(39, 39, 42, 0.50);
        background: rgba(24, 24, 27, 0.35);
        color: rgba(250, 250, 250, 0.45);
    }
"""

STYLE_SELECTABLE_LIST_MULTI = """
    QListWidget#SelectableListMulti {
        background-color: #0d0d0f;
        border: none;
        outline: none;
        padding: 5px;
    }
    QListWidget#SelectableListMulti::item {
        background-color: transparent;
        color: #888888;
        padding: 8px 12px;
        margin-bottom: 2px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 500;
    }
    QListWidget#SelectableListMulti::item:hover {
        background-color: rgba(255, 255, 255, 0.03);
        color: #eeeeee;
    }
    QListWidget#SelectableListMulti::item:selected {
        background-color: rgba(37, 99, 235, 0.10);
        color: #2563eb;
        font-weight: 700;
    }
"""


# --- Selectable List Pattern: giống hệt dialog picker (MonoStudio _FilterPickDialog) ---
# MultiSelection = click toggle từng item, không custom mouse/drag.

def _item_id(it: QListWidgetItem) -> str | None:
    """Lấy id từ item (UserRole)."""
    val = it.data(Qt.ItemDataRole.UserRole)
    return str(val) if val is not None else None


class SelectableListMulti(QListWidget):
    """
    List multi-select y hệt dialog picker: objectName SelectableListMulti, UserRole = id.
    MultiSelection → click = toggle 1 item (Qt mặc định), không xử lý chuột tùy chỉnh.
    Build: (id, label, icon?) → setData(UserRole, id). Read: selected_items() → list[str] giữ thứ tự.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SelectableListMulti")
        self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setIconSize(QSize(16, 16))
        self.setStyleSheet(STYLE_SELECTABLE_LIST_MULTI)
        self.setMinimumHeight(200)

    def build_list(
        self,
        items: Sequence[tuple[str, str] | tuple[str, str, str]],
        selected: set[str] | None = None,
    ) -> None:
        """
        Rule §4: Build flat list. items = [(id, label)] hoặc [(id, label, icon_name)].
        selected = set id pre-select (nếu None thì không chọn sẵn).
        """
        self.clear()
        selected = selected or set()
        for row in items:
            item_id = row[0]
            label = row[1] or "(empty)"
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, item_id)
            if len(row) >= 3 and row[2]:
                pass  # optional: it.setIcon(...)
            self.addItem(it)
            if item_id in selected:
                it.setSelected(True)

    def selected_items(self) -> list[str]:
        """Rule §5: Duyệt toàn bộ item, selected thì lấy id (UserRole), giữ thứ tự → list[str]."""
        out: list[str] = []
        for i in range(self.count()):
            it = self.item(i)
            if it and it.isSelected():
                id_val = _item_id(it)
                if id_val is not None:
                    out.append(id_val)
        return out


# --- Split Geometry UI ---

class SplitGeometryUI(QWidget):
    """UI: title, node nguồn + nút icon, combo attribute, SelectableListMulti, Select all / Deselect all, Blast SOP."""

    def __init__(self, parent: QWidget | None = None, title: str = "Split Geometry"):
        super().__init__(parent)
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        self._message_label = QLabel()
        self._message_label.setStyleSheet(f"color: {TEXT_ERROR};")
        self._message_label.setWordWrap(True)

        self._source_label = QLabel("Node: —")
        self._source_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold;")
        self._select_source_btn = QToolButton()
        self._select_source_btn.setToolTip("Chọn node nguồn")
        self._select_source_btn.setStyleSheet(BUTTON_STYLE)
        _icon_path = Path(__file__).parent / "icons" / "icon_select.svg"
        if _icon_path.is_file():
            self._select_source_btn.setIcon(QIcon(str(_icon_path)))
        else:
            self._select_source_btn.setIcon(self._select_source_btn.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self._select_source_btn.setIconSize(QSize(22, 22))

        source_row = QHBoxLayout()
        source_row.addWidget(self._source_label)
        source_row.addWidget(self._select_source_btn)
        source_row.addStretch()

        self._attr_combo = QComboBox()
        self._attr_combo.setMinimumWidth(180)

        self._list = SelectableListMulti(self)
        self._hint_label = QLabel("Selected: 0")
        self._hint_label.setStyleSheet(f"color: {TEXT_META}; font-size: 11px;")
        self._list.selectionModel().selectionChanged.connect(self._sync_selection_hint)

        self._select_all_btn = QPushButton("Select all")
        self._select_all_btn.setStyleSheet(BUTTON_STYLE)
        self._deselect_all_btn = QPushButton("Deselect all")
        self._deselect_all_btn.setStyleSheet(BUTTON_STYLE)
        list_btn_row = QHBoxLayout()
        list_btn_row.addWidget(QLabel("Values to keep (chọn nhiều: click / Ctrl+Shift):"))
        list_btn_row.addStretch()
        list_btn_row.addWidget(self._hint_label)
        list_btn_row.addWidget(self._select_all_btn)
        list_btn_row.addWidget(self._deselect_all_btn)

        self._create_blast_btn = QPushButton("Create Blast SOP")
        self._create_blast_btn.setStyleSheet(BUTTON_PRIMARY_STYLE)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addWidget(self._message_label)
        layout.addLayout(source_row)
        layout.addWidget(QLabel("Attribute:"))
        layout.addWidget(self._attr_combo)
        layout.addLayout(list_btn_row)
        layout.addWidget(self._list)
        layout.addWidget(self._create_blast_btn)

        self._select_all_btn.clicked.connect(self._list.selectAll)
        self._deselect_all_btn.clicked.connect(self._list.clearSelection)

        self.setStyleSheet(f"background-color: {BACKGROUND}; color: {TEXT_PRIMARY};")
        self.setMinimumWidth(440)
        self.setMinimumHeight(420)

    def _sync_selection_hint(self) -> None:
        n = len(self._list.selected_items())
        self._hint_label.setText(f"Selected: {n}")

    def set_title(self, text: str) -> None:
        self._title_label.setText(text or "Split Geometry")

    def set_message(self, text: str) -> None:
        self._message_label.setText(text or "")
        self._message_label.setVisible(bool(text))

    def set_source_node_name(self, name: str) -> None:
        self._source_label.setText(f"Node: {name or '—'}")

    def set_attr_combo(self, attr_names: list[str], current_attr: str | None = None) -> None:
        self._attr_combo.clear()
        self._attr_combo.addItems(attr_names or [])
        if attr_names:
            cur = current_attr if current_attr in attr_names else attr_names[0]
            idx = self._attr_combo.findText(cur)
            if idx >= 0:
                self._attr_combo.setCurrentIndex(idx)
        self._attr_combo.setEnabled(bool(attr_names))

    def on_attr_changed(self, callback):
        self._attr_combo.currentTextChanged.connect(callback)

    def get_selected_attribute(self) -> str:
        return self._attr_combo.currentText().strip()

    def on_select_source_clicked(self, callback):
        self._select_source_btn.clicked.connect(callback)

    def set_values(self, values: list, counts: dict | None = None) -> None:
        """Rule §4: items = [(id, label)]; label có thể kèm (count)."""
        items: list[tuple[str, str]] = []
        for item_id in values or []:
            label = item_id if item_id else "(empty)"
            if counts is not None and item_id in counts:
                label = f"{label}  ({counts[item_id]})"
            items.append((item_id, label))
        self._list.build_list(items)
        self._sync_selection_hint()

    def get_selected_values(self) -> list[str]:
        """Rule §5: selected_items() → list[str] giữ thứ tự."""
        return self._list.selected_items()

    def on_create_blast_clicked(self, callback):
        self._create_blast_btn.clicked.connect(callback)

    def set_blast_button_enabled(self, enabled: bool) -> None:
        self._create_blast_btn.setEnabled(enabled)

    def show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)
