"""
Node Preset Library UI — Save dialog + Library panel. MONOS design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, QSize, QRect
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
    QCheckBox,
    QComboBox,
    QToolButton,
    QStyledItemDelegate,
)

# ---------------------------------------------------------------------------
# MONOS palette (aligned with auto_material, search_replace)
# ---------------------------------------------------------------------------
BG_PANEL = "#18181b"
BG_CONTENT = "#121214"
BG_SURFACE = "#27272a"
TEXT_PRIMARY = "#fafafa"
TEXT_LABEL = "#a1a1aa"
TEXT_META = "#71717a"
BLUE_600 = "#2563eb"

NETWORK_TAG_COLORS = {
    "SOP": "#22c55e",
    "VOP": "#a855f7",
    "LOP": "#f97316",
    "OBJ": "#38bdf8",
    "DOP": "#f97316",
    "CHOP": "#06b6d4",
    "COP2": "#ec4899",
    "TOP": "#eab308",
}

STYLE_WINDOW = f"""
    QWidget#NodePresetLibraryWindow {{
        background-color: {BG_PANEL};
        color: {TEXT_PRIMARY};
    }}
"""

STYLE_INPUT = f"""
    QLineEdit {{
        padding: 6px 8px;
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 6px;
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
    }}
    QLineEdit:focus {{
        border: 1px solid {BLUE_600};
    }}
"""

STYLE_BTN = """
    QPushButton {
        background: rgba(24, 24, 27, 0.35);
        color: #a1a1aa;
        padding: 6px 12px;
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 8px;
    }
    QPushButton:hover {
        background: rgba(255, 255, 255, 0.12);
        border: 1px solid rgba(63, 63, 70, 0.80);
        color: #e4e4e7;
    }
    QPushButton:disabled {
        color: rgba(161, 161, 170, 0.5);
        background: rgba(24, 24, 27, 0.25);
    }
"""

STYLE_BTN_PRIMARY = f"""
    QPushButton {{
        background: rgba(37, 99, 235, 0.22);
        border: 1px solid rgba(37, 99, 235, 0.70);
        color: {TEXT_PRIMARY};
        padding: 8px 16px;
        border-radius: 8px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: rgba(37, 99, 235, 0.35);
        border-color: rgba(59, 130, 246, 0.80);
    }}
"""

STYLE_COMBO = f"""
    QComboBox {{
        padding: 6px 8px;
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 6px;
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
    }}
    QComboBox:focus {{ border: 1px solid {BLUE_600}; }}
"""

STYLE_LIST = f"""
    QListWidget {{
        background: {BG_CONTENT};
        color: {TEXT_PRIMARY};
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 6px;
        padding: 4px;
    }}
    QListWidget::item {{
        padding: 6px 8px;
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background: rgba(37, 99, 235, 0.25);
        color: {TEXT_PRIMARY};
    }}
    QListWidget::item:hover {{
        background: rgba(255, 255, 255, 0.08);
    }}

    /* Tile style for main preset view (grid) */
    QListWidget#PresetList[view="grid"]::item {{
        margin: 3px;
        padding: 6px;
        background: #1f2933;
        border-radius: 10px;
        border: 1px solid rgba(63, 63, 70, 0.75);
    }}
    QListWidget#PresetList[view="grid"]::item:selected {{
        background: rgba(37, 99, 235, 0.35);
        border-color: rgba(59, 130, 246, 0.9);
    }}
    QListWidget#PresetList[view="grid"]::item:hover {{
        background: rgba(255, 255, 255, 0.10);
    }}

    /* Compact row style (list) */
    QListWidget#PresetList[view="list"]::item {{
        margin: 1px;
        padding: 4px 6px;
        background: #1f2933;
        border-radius: 10px;
        border: 1px solid rgba(63, 63, 70, 0.65);
    }}
    QListWidget#PresetList[view="list"]::item:selected {{
        background: rgba(37, 99, 235, 0.30);
        border-color: rgba(59, 130, 246, 0.85);
    }}
    QListWidget#PresetList[view="list"]::item:hover {{
        background: rgba(255, 255, 255, 0.08);
    }}
"""


class PresetItemDelegate(QStyledItemDelegate):
    """Custom delegate to draw network tags above the thumbnail."""

    def sizeHint(self, option, index):  # type: ignore[override]
        parent = self.parent()
        try:
            if isinstance(parent, QListWidget) and parent.viewMode() == QListWidget.ViewMode.ListMode:
                return QSize(max(200, option.rect.width()), 62)
            if isinstance(parent, QListWidget) and parent.viewMode() == QListWidget.ViewMode.IconMode:
                gs = parent.gridSize()
                if gs.isValid() and gs.width() > 0 and gs.height() > 0:
                    return gs
        except Exception:
            pass
        return super().sizeHint(option, index)

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        # Let base class draw icon + text first
        super().paint(painter, option, index)

        nets = index.data(Qt.ItemDataRole.UserRole + 1) or []
        if not nets:
            return

        if isinstance(nets, str):
            nets = [nets]

        rect: QRect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        x = rect.left() + 10
        y = rect.top() + 8
        padding_x = 6
        padding_y = 2
        spacing = 4

        for n in nets[:3]:  # limit to first 3 tags for space
            label = str(n)
            color_hex = NETWORK_TAG_COLORS.get(label, "#4b5563")
            fm = painter.fontMetrics()
            text_width = fm.horizontalAdvance(label)
            w = text_width + padding_x * 2
            h = fm.height() + padding_y * 2

            tag_rect = QRect(x, y, w, h)
            painter.setBrush(QColor(color_hex))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(tag_rect, 6, 6)

            painter.setPen(QColor("#0b1120"))
            painter.drawText(
                tag_rect.adjusted(padding_x, padding_y - 1, -padding_x, -padding_y),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

            x += w + spacing

        painter.restore()


# ---------------------------------------------------------------------------
# Save Preset Dialog
# ---------------------------------------------------------------------------


class SavePresetDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("SavePresetDialog")
        self.setWindowTitle("Save to Library")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Preset name")
        self._name_edit.setStyleSheet(STYLE_INPUT)
        layout.addWidget(QLabel("Name:"))
        layout.addWidget(self._name_edit)

        cat_layout = QHBoxLayout()
        cat_layout.addWidget(QLabel("Category:"))
        from PySide6.QtWidgets import QComboBox
        self._category_combo = QComboBox()
        self._category_combo.setStyleSheet(STYLE_COMBO)
        self._category_combo.setEditable(True)
        cat_layout.addWidget(self._category_combo, 1)
        self._new_cat_btn = QPushButton("New…")
        self._new_cat_btn.setStyleSheet(STYLE_BTN)
        cat_layout.addWidget(self._new_cat_btn)
        layout.addLayout(cat_layout)

        layout.addWidget(QLabel("Description (optional):"))
        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText("Short description of what this preset does...")
        self._desc_edit.setFixedHeight(60)
        self._desc_edit.setStyleSheet(
            f"QPlainTextEdit {{ background: {BG_SURFACE}; color: {TEXT_PRIMARY}; "
            "border-radius: 6px; border: 1px solid rgba(39,39,42,0.50); padding: 4px 6px; }}"
        )
        layout.addWidget(self._desc_edit)

        layout.addWidget(QLabel("Thumbnail:"))
        thumb_row = QHBoxLayout()
        self._paste_thumb_btn = QPushButton("Paste thumbnail")
        self._paste_thumb_btn.setStyleSheet(STYLE_BTN)
        thumb_row.addWidget(self._paste_thumb_btn)
        self._thumb_preview = QLabel()
        self._thumb_preview.setFixedSize(64, 64)
        self._thumb_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_preview.setStyleSheet(f"background: {BG_SURFACE}; border-radius: 6px; color: {TEXT_META};")
        self._thumb_preview.setText("(none)")
        thumb_row.addWidget(self._thumb_preview)
        thumb_row.addStretch()
        layout.addLayout(thumb_row)

        self._thumb_pixmap: Optional[QPixmap] = None  # keep for controller to save

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setStyleSheet(STYLE_BTN)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        layout.addWidget(buttons)

        self.setStyleSheet(f"background: {BG_PANEL}; color: {TEXT_PRIMARY};")

    def get_name(self) -> str:
        return self._name_edit.text().strip()

    def set_name(self, value: str) -> None:
        self._name_edit.setText(value)

    def get_category(self) -> str:
        return self._category_combo.currentText().strip()

    def set_categories(self, categories: list[dict[str, Any]]) -> None:
        self._category_combo.clear()
        for c in categories:
            self._category_combo.addItem(c.get("name", ""), c.get("id", ""))

    def set_category(self, category_id: str) -> None:
        for i in range(self._category_combo.count()):
            if self._category_combo.itemData(i) == category_id:
                self._category_combo.setCurrentIndex(i)
                return
        self._category_combo.setCurrentText(category_id)

    def get_category_id(self) -> str:
        idx = self._category_combo.currentIndex()
        if idx >= 0:
            cid = self._category_combo.itemData(idx)
            if cid:
                return str(cid)
        return self.get_category().lower().replace(" ", "_") or "uncategorized"

    def get_description(self) -> str:
        return self._desc_edit.toPlainText().strip()

    def set_description(self, text: str) -> None:
        self._desc_edit.setPlainText(text or "")

    def set_thumbnail_from_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        self._thumb_pixmap = pixmap
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._thumb_preview.setPixmap(scaled)
            self._thumb_preview.setText("")
        else:
            self._thumb_preview.clear()
            self._thumb_preview.setText("(none)")
            self._thumb_pixmap = None

    def get_thumbnail_pixmap(self) -> Optional[QPixmap]:
        return self._thumb_pixmap

    def on_new_category(self, callback: Callable[[], None]) -> None:
        self._new_cat_btn.clicked.connect(callback)

    def on_paste_thumbnail(self, callback: Callable[[], None]) -> None:
        self._paste_thumb_btn.clicked.connect(callback)


# ---------------------------------------------------------------------------
# Library main window
# ---------------------------------------------------------------------------


class NodePresetLibraryUI(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("NodePresetLibraryWindow")
        self.setMinimumSize(520, 400)
        self.setStyleSheet(STYLE_WINDOW)

        main = QVBoxLayout(self)
        main.setSpacing(8)
        main.setContentsMargins(8, 8, 8, 8)

        # Toolbar (top)
        toolbar = QHBoxLayout()
        self._save_btn = QPushButton("Save to Library")
        self._save_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        toolbar.addWidget(self._save_btn)
        toolbar.addStretch()
        main.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("MainSplitter")
        splitter.setContentsMargins(0, 0, 0, 0)
        splitter.setHandleWidth(1)
        # Make handle blend with main content background to avoid visible gap.
        splitter.setStyleSheet(
            f"QSplitter#MainSplitter::handle {{ background-color: {BG_CONTENT}; margin: 0px; padding: 0px; }}"
        )

        # Categories (left)
        cat_widget = QWidget()
        cat_widget.setStyleSheet(f"background-color: {BG_CONTENT};")
        # Let splitter control overall sidebar width, but keep it within a sensible range.
        cat_widget.setMinimumWidth(180)
        cat_widget.setMaximumWidth(260)
        cat_layout = QVBoxLayout(cat_widget)
        cat_layout.setContentsMargins(0, 0, 0, 0)
        cat_layout.addWidget(QLabel("Categories"))
        self._category_list = QListWidget()
        self._category_list.setStyleSheet(STYLE_LIST)
        # Do not lock internal list width; it should expand with the container.
        cat_layout.addWidget(self._category_list)

        # Sidebar actions at bottom
        self._new_cat_btn = QPushButton("New category")
        self._new_cat_btn.setStyleSheet(STYLE_BTN)
        self._import_btn = QPushButton("Import library…")
        self._import_btn.setStyleSheet(STYLE_BTN)
        cat_layout.addWidget(self._new_cat_btn)
        cat_layout.addWidget(self._import_btn)
        splitter.addWidget(cat_widget)

        # Presets (right)
        preset_widget = QWidget()
        preset_widget.setStyleSheet(f"background-color: {BG_CONTENT};")
        preset_layout = QVBoxLayout(preset_widget)
        preset_layout.setContentsMargins(0, 0, 0, 0)

        # Header: search + filters + view toggle
        header_row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search presets by name or description...")
        self._search_edit.setStyleSheet(STYLE_INPUT)
        header_row.addWidget(self._search_edit, 1)

        self._auto_detect_chk = QCheckBox("Auto detect network")
        self._auto_detect_chk.setChecked(True)
        self._auto_detect_chk.setStyleSheet(
            f"QCheckBox {{ color: {TEXT_META}; }} QCheckBox::indicator {{ width: 12px; height: 12px; }}"
        )
        header_row.addWidget(self._auto_detect_chk)

        self._network_combo = QComboBox()
        self._network_combo.setStyleSheet(STYLE_COMBO)
        self._network_combo.addItem("All networks", "__all__")
        for tag in ["SOP", "VOP", "LOP", "OBJ", "DOP", "CHOP", "COP2", "TOP"]:
            self._network_combo.addItem(tag, tag)
        self._network_combo.setEnabled(False)  # auto detect on by default
        header_row.addWidget(self._network_combo)

        self._view_grid_btn = QToolButton()
        self._view_grid_btn.setText("▦")  # placeholder icon
        self._view_grid_btn.setCheckable(True)
        self._view_list_btn = QToolButton()
        self._view_list_btn.setText("≣")  # placeholder icon
        self._view_list_btn.setCheckable(True)
        self._view_grid_btn.setChecked(True)
        header_row.addWidget(self._view_grid_btn)
        header_row.addWidget(self._view_list_btn)

        self._insert_btn = QPushButton("Insert")
        self._insert_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        header_row.addWidget(self._insert_btn)

        preset_layout.addLayout(header_row)

        self._preset_list = QListWidget()
        self._preset_list.setObjectName("PresetList")
        self._preset_list.setProperty("view", "grid")
        self._preset_list.setStyleSheet(STYLE_LIST)
        self._preset_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._preset_list.setIconSize(QSize(112, 84))
        self._preset_list.setSpacing(2)
        self._preset_list.setMovement(QListWidget.Movement.Static)
        self._preset_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._preset_list.setWordWrap(True)
        # Fixed tile size so all cards are equal, regardless of thumbnail/description
        self._preset_list.setUniformItemSizes(True)
        self._preset_list.setGridSize(QSize(176, 168))
        # Custom delegate to overlay network tags above thumbnail
        self._preset_list.setItemDelegate(PresetItemDelegate(self._preset_list))
        preset_layout.addWidget(self._preset_list)

        splitter.addWidget(preset_widget)
        splitter.setSizes([200, 600])
        # Give splitter all remaining vertical space; footer stays compact at bottom.
        main.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self._message = QLabel()
        self._message.setStyleSheet(f"color: {TEXT_META}; font-size: 12px;")
        footer.addWidget(self._message, 1)
        self._version_label = QLabel()
        self._version_label.setStyleSheet(f"color: {TEXT_META}; font-size: 11px;")
        footer.addWidget(self._version_label, 0, Qt.AlignmentFlag.AlignRight)
        main.addLayout(footer, 0)

        self._presets_data: list[dict[str, Any]] = []
        self._library_root: Optional[Path] = None

    def set_categories(self, categories: list[dict[str, Any]], select_id: Optional[str] = None) -> None:
        self._category_list.clear()
        for c in categories:
            name = c.get("name", c.get("id", ""))
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, c.get("id", ""))
            self._category_list.addItem(item)
        if select_id:
            for i in range(self._category_list.count()):
                if self._category_list.item(i).data(Qt.ItemDataRole.UserRole) == select_id:
                    self._category_list.setCurrentRow(i)
                    break

    def get_selected_category_id(self) -> Optional[str]:
        item = self._category_list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def set_presets(self, presets: list[dict[str, Any]], library_root: Optional[Path] = None) -> None:
        self._preset_list.clear()
        self._presets_data = presets
        self._library_root = library_root
        placeholder_icon: Optional[QIcon] = None
        for p in presets:
            name = p.get("name", "?")
            pid = p.get("id", "")
            desc = p.get("description", "") or ""
            networks = p.get("networks", []) or []
            nets_str = " ".join(f"[{n}]" for n in networks)

            # Line 1: preset name
            # Line 2: description (if any)
            # Line 3: network tags (if any)
            lines = [name]
            if desc:
                lines.append(desc)
            if nets_str:
                lines.append(nets_str)

            text = "\n".join(lines)
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, pid)
            # Store networks for delegate to draw tags
            item.setData(Qt.ItemDataRole.UserRole + 1, networks)
            thumb_path = p.get("thumbnail")
            icon: Optional[QIcon] = None
            if thumb_path and library_root:
                fp = library_root / thumb_path
                if fp.is_file():
                    icon = QIcon(str(fp))
            if icon is None:
                if placeholder_icon is None:
                    # Placeholder thumbnail: neutral tile matching card background.
                    size = self._preset_list.iconSize()
                    pm = QPixmap(size)
                    pm.fill(QColor("#111827"))
                    placeholder_icon = QIcon(pm)
                icon = placeholder_icon
            item.setIcon(icon)
            self._preset_list.addItem(item)

    def get_selected_preset_id(self) -> Optional[str]:
        item = self._preset_list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def set_message(self, text: str, error: bool = False) -> None:
        self._message.setText(text)
        self._message.setStyleSheet(
            f"color: {'#fca5a5' if error else TEXT_META}; font-size: 12px;"
        )

    def set_version_text(self, version: str) -> None:
        self._version_label.setText(version)

    def on_save_clicked(self, callback: Callable[[], None]) -> None:
        self._save_btn.clicked.connect(callback)

    def on_new_category_clicked(self, callback: Callable[[], None]) -> None:
        self._new_cat_btn.clicked.connect(callback)

    def on_import_clicked(self, callback: Callable[[], None]) -> None:
        self._import_btn.clicked.connect(callback)

    def on_insert_clicked(self, callback: Callable[[], None]) -> None:
        self._insert_btn.clicked.connect(callback)

    def on_search_changed(self, callback: Callable[[str], None]) -> None:
        self._search_edit.textChanged.connect(callback)

    def on_auto_detect_toggled(self, callback: Callable[[bool], None]) -> None:
        self._auto_detect_chk.toggled.connect(callback)

    def on_network_filter_changed(self, callback: Callable[[str], None]) -> None:
        def _on_changed(index: int) -> None:
            value = self._network_combo.itemData(index)
            callback(str(value) if value is not None else "__all__")

        self._network_combo.currentIndexChanged.connect(_on_changed)

    def on_view_mode_changed(self, callback: Callable[[str], None]) -> None:
        def set_mode(mode: str) -> None:
            if mode == "grid":
                self._view_grid_btn.setChecked(True)
                self._view_list_btn.setChecked(False)
                self._preset_list.setViewMode(QListWidget.ViewMode.IconMode)
                self._preset_list.setIconSize(QSize(112, 84))
                self._preset_list.setSpacing(2)
                self._preset_list.setWordWrap(True)
                self._preset_list.setGridSize(QSize(176, 168))
                self._preset_list.setProperty("view", "grid")
            else:
                self._view_grid_btn.setChecked(False)
                self._view_list_btn.setChecked(True)
                self._preset_list.setViewMode(QListWidget.ViewMode.ListMode)
                self._preset_list.setIconSize(QSize(32, 32))
                self._preset_list.setSpacing(0)
                self._preset_list.setWordWrap(False)
                # Let delegate sizeHint control row height in list mode.
                self._preset_list.setProperty("view", "list")
            # Re-apply stylesheet to pick up property-based selectors
            self._preset_list.style().unpolish(self._preset_list)
            self._preset_list.style().polish(self._preset_list)
            self._preset_list.viewport().update()
            callback(mode)

        self._view_grid_btn.clicked.connect(lambda: set_mode("grid"))
        self._view_list_btn.clicked.connect(lambda: set_mode("list"))

    def set_auto_detect_enabled(self, enabled: bool) -> None:
        self._auto_detect_chk.setChecked(enabled)
        self._network_combo.setEnabled(not enabled)

    def set_network_filter_value(self, value: str) -> None:
        for i in range(self._network_combo.count()):
            if self._network_combo.itemData(i) == value:
                self._network_combo.setCurrentIndex(i)
                return

    def on_category_selected(self, callback: Callable[[Optional[str]], None]) -> None:
        def _on_change(cur: Optional[QListWidgetItem], _: Optional[QListWidgetItem]) -> None:
            cid = cur.data(Qt.ItemDataRole.UserRole) if cur else None
            callback(cid)

        self._category_list.currentItemChanged.connect(_on_change)

    def on_preset_double_clicked(self, callback: Callable[[str], None]) -> None:
        def on_item_double_clicked(item: QListWidgetItem) -> None:
            pid = item.data(Qt.ItemDataRole.UserRole) if item else None
            if pid:
                callback(pid)
        self._preset_list.itemDoubleClicked.connect(on_item_double_clicked)

    def show_import_folder_dialog(self) -> Optional[str]:
        path = QFileDialog.getExistingDirectory(self, "Import library — select folder")
        return path if path else None
