"""
Auto Material Builder UI — MONOS design system.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QSize, QTimer, QRect, QPoint
from PySide6.QtGui import QIcon, QColor, QPainter, QFont, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# MONOS palette
# ---------------------------------------------------------------------------
BG_PANEL = "#18181b"
BG_CONTENT = "#121214"
BG_SURFACE = "#27272a"
TEXT_PRIMARY = "#fafafa"
TEXT_LABEL = "#a1a1aa"
TEXT_META = "#71717a"
TEXT_ERROR = "#fca5a5"
BLUE_600 = "#2563eb"
BLUE_400 = "#60a5fa"
EMERALD = "#10b981"
AMBER = "#f59e0b"

STYLE_WINDOW = f"""
    QWidget#AutoMaterialWindow {{
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
    QPushButton:disabled {{
        border: 1px solid rgba(39, 39, 42, 0.50);
        background: rgba(24, 24, 27, 0.35);
        color: rgba(250, 250, 250, 0.45);
    }}
"""

# Same as primary but emerald/green (for Auto assign)
STYLE_BTN_PRIMARY_EMERALD = f"""
    QPushButton {{
        background: rgba(16, 185, 129, 0.22);
        border: 1px solid rgba(16, 185, 129, 0.70);
        color: {TEXT_PRIMARY};
        padding: 8px 16px;
        border-radius: 8px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: rgba(16, 185, 129, 0.35);
        border-color: rgba(52, 211, 153, 0.80);
    }}
    QPushButton:disabled {{
        border: 1px solid rgba(39, 39, 42, 0.50);
        background: rgba(24, 24, 27, 0.35);
        color: rgba(250, 250, 250, 0.45);
    }}
"""

STYLE_MATERIAL_LIST = """
    QListWidget#MaterialList {
        background-color: #0d0d0f;
        border: none;
        outline: none;
        padding: 5px;
    }
"""

ROLE_DISABLED = Qt.ItemDataRole.UserRole + 1

ZINC_400 = "#a1a1aa"
ZINC_500 = "#71717a"
RED_400 = "#f87171"
RED_500 = "#ef4444"
RED_900_A = "rgba(127, 29, 29, 0.25)"
RED_900_A_SEL = "rgba(153, 27, 27, 0.40)"

_X_SIZE = 16
_X_MARGIN_RIGHT = 8


class _MaterialItemDelegate(QStyledItemDelegate):
    """Custom delegate that draws material items with an [x] toggle."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect: QRect = option.rect
        disabled = bool(index.data(ROLE_DISABLED))
        selected = bool(option.state & option.state.__class__.State_Selected)
        hovered = bool(option.state & option.state.__class__.State_MouseOver)

        if disabled:
            bg = QColor(RED_900_A_SEL) if selected else QColor(RED_900_A)
        elif selected:
            bg = QColor(37, 99, 235, 26)
        elif hovered:
            bg = QColor(255, 255, 255, 8)
        else:
            bg = QColor(0, 0, 0, 0)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect.adjusted(2, 1, -2, -1), 6, 6)

        if disabled:
            text_color = QColor(RED_400) if selected else QColor(RED_500)
        elif selected:
            text_color = QColor(BLUE_600)
        else:
            text_color = QColor(ZINC_400) if not hovered else QColor(ZINC_400)

        font = QFont("Inter", 7)
        font.setWeight(QFont.Weight.Bold if selected else QFont.Weight.Medium)
        if disabled:
            font.setStrikeOut(True)
        painter.setFont(font)
        painter.setPen(text_color)

        text_rect = rect.adjusted(12, 0, -(_X_SIZE + _X_MARGIN_RIGHT + 8), 0)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

        x_rect = self._x_rect(rect)
        x_color = QColor(RED_400) if disabled else QColor(ZINC_500)
        painter.setPen(x_color)
        x_font = QFont("Inter", 10, QFont.Weight.Bold)
        painter.setFont(x_font)
        painter.drawText(x_rect, Qt.AlignmentFlag.AlignCenter, "✕")

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 34)

    @staticmethod
    def _x_rect(item_rect: QRect) -> QRect:
        x = item_rect.right() - _X_SIZE - _X_MARGIN_RIGHT
        y = item_rect.center().y() - _X_SIZE // 2
        return QRect(x, y, _X_SIZE, _X_SIZE)

STYLE_TABLE = f"""
    QTableWidget {{
        background-color: {BG_CONTENT};
        border: 1px solid #2a2a2c;
        gridline-color: #2a2a2c;
        color: #eeeeee;
        font-size: 14px;
        selection-background-color: rgba(37, 99, 235, 0.15);
        selection-color: {BLUE_600};
        outline: none;
    }}
    QHeaderView::section {{
        background-color: #0d0d0f;
        color: #4a4a4c;
        padding: 8px 12px;
        border: none;
        border-bottom: 2px solid #2a2a2c;
        font-weight: 800;
        font-size: 14px;
    }}
    QTableWidget::item {{
        padding: 6px 12px;
        border-bottom: 1px solid #1e1e20;
        font-size: 14px;
    }}
"""

STYLE_CHECKBOX = f"""
    QCheckBox {{
        color: {TEXT_LABEL};
        spacing: 6px;
    }}
"""

STYLE_SECTION_LABEL = f"color: {TEXT_META}; font-size: 12px; font-weight: 800;"

STYLE_COMBO = f"""
    QComboBox {{
        padding: 6px 8px;
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 6px;
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
    }}
    QComboBox:focus {{
        border: 1px solid {BLUE_600};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {TEXT_META};
        margin-right: 6px;
    }}
    QComboBox QAbstractItemView {{
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid rgba(39, 39, 42, 0.70);
        selection-background-color: rgba(37, 99, 235, 0.20);
        selection-color: {TEXT_PRIMARY};
        padding: 4px;
        outline: none;
    }}
"""

_HISTORY_DIR = Path(os.environ.get("APPDATA", Path.home())) / "MonoFXSuite"
_HISTORY_FILE = _HISTORY_DIR / "auto_material_paths.json"
_MAX_HISTORY = 15


def _load_path_history() -> list[str]:
    try:
        data = json.loads(_HISTORY_FILE.read_text("utf-8"))
        if isinstance(data, list):
            return [str(p) for p in data[:_MAX_HISTORY]]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _save_path_history(paths: list[str]) -> None:
    try:
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        _HISTORY_FILE.write_text(json.dumps(paths[:_MAX_HISTORY], ensure_ascii=False), "utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Loading overlay
# ---------------------------------------------------------------------------

class _LoadingOverlay(QWidget):
    """Semi-transparent overlay with centered status text.
    Modes: loading (cancelable), done (click to dismiss)."""

    _MODE_LOADING = 0
    _MODE_DONE = 1

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._text = "Loading..."
        self._sub_text: str | None = None
        self._mode = self._MODE_LOADING
        self._cancelled = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setVisible(False)

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def reset(self) -> None:
        self._cancelled = False
        self._mode = self._MODE_LOADING

    def set_text(self, text: str, sub_text: str | None = None) -> None:
        self._text = text
        self._sub_text = sub_text or "Click to cancel"
        self._mode = self._MODE_LOADING
        self.update()

    def set_done(self, text: str, sub_text: str | None = None) -> None:
        self._text = text
        self._sub_text = sub_text or "Click to continue"
        self._mode = self._MODE_DONE
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))

        painter.setPen(QColor(TEXT_PRIMARY))
        main_font = QFont("Inter", 13, QFont.Weight.DemiBold)
        painter.setFont(main_font)
        painter.drawText(
            self.rect().adjusted(0, -20, 0, 0),
            Qt.AlignmentFlag.AlignCenter,
            self._text,
        )

        if self._sub_text:
            color = QColor(TEXT_ERROR) if self._mode == self._MODE_LOADING else QColor(TEXT_META)
            painter.setPen(color)
            sub_font = QFont("Inter", 10, QFont.Weight.Normal)
            painter.setFont(sub_font)
            painter.drawText(
                self.rect().adjusted(0, 40, 0, 0),
                Qt.AlignmentFlag.AlignCenter,
                self._sub_text,
            )

        painter.end()

    def mousePressEvent(self, event) -> None:
        if self._mode == self._MODE_DONE:
            self.reset()
            self.setVisible(False)
        elif self._mode == self._MODE_LOADING:
            self._cancelled = True
            self._text = "Cancelling..."
            self._sub_text = None
            self.update()
        event.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class AutoMaterialUI(QWidget):

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("AutoMaterialWindow")
        self.setWindowTitle("Auto Material Builder")
        self.setMinimumWidth(700)
        self.setMinimumHeight(560)
        self.resize(1000, 900)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # --- Title ---
        title = QLabel("AUTO MATERIAL BUILDER")
        title.setStyleSheet(f"color: {TEXT_META}; font-size: 32px; font-weight: 700;")
        root.addWidget(title)

        # --- Folder row ---
        folder_section = QLabel("TEXTURE FOLDER")
        folder_section.setStyleSheet(STYLE_SECTION_LABEL)
        root.addWidget(folder_section)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)
        self._folder_combo = QComboBox()
        self._folder_combo.setEditable(True)
        self._folder_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._folder_combo.lineEdit().setPlaceholderText("Select texture folder...")
        self._folder_combo.setStyleSheet(STYLE_COMBO)
        self._folder_combo.setSizePolicy(
            self._folder_combo.sizePolicy().horizontalPolicy(),
            self._folder_combo.sizePolicy().verticalPolicy(),
        )
        self._path_history = _load_path_history()
        for p in self._path_history:
            self._folder_combo.addItem(p)
        self._folder_combo.setCurrentText("")
        folder_row.addWidget(self._folder_combo, stretch=1)

        self._browse_btn = QPushButton("Browse")
        self._browse_btn.setStyleSheet(STYLE_BTN)
        self._browse_btn.clicked.connect(self._on_browse)
        folder_row.addWidget(self._browse_btn)

        self._publish_btn = QPushButton("Publish")
        self._publish_btn.setToolTip("Auto-fill $HIP/../../../03_surfacing/02_texturing/publish")
        self._publish_btn.setStyleSheet(STYLE_BTN)
        folder_row.addWidget(self._publish_btn)

        self._scan_btn = QPushButton("Scan")
        self._scan_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        folder_row.addWidget(self._scan_btn)

        root.addLayout(folder_row)

        # --- Options row ---
        opts_row = QHBoxLayout()
        self._recursive_cb = QCheckBox("Recursive scan subfolders")
        self._recursive_cb.setChecked(True)
        self._recursive_cb.setStyleSheet(STYLE_CHECKBOX)
        opts_row.addWidget(self._recursive_cb)
        opts_row.addStretch()
        root.addLayout(opts_row)

        # --- Splitter: material list + slot table ---
        materials_label = QLabel("MATERIALS")
        materials_label.setStyleSheet(STYLE_SECTION_LABEL)
        root.addWidget(materials_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: rgba(39, 39, 42, 0.50); width: 1px; }")

        # Left: material list
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(4)

        self._material_list = QListWidget()
        self._material_list.setObjectName("MaterialList")
        self._material_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._material_list.setStyleSheet(STYLE_MATERIAL_LIST)
        self._material_list.setMouseTracking(True)
        self._material_delegate = _MaterialItemDelegate(self._material_list)
        self._material_list.setItemDelegate(self._material_delegate)
        self._material_list.currentRowChanged.connect(self._on_material_selected)
        self._material_list.clicked.connect(self._on_material_clicked)
        left_lay.addWidget(self._material_list)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {TEXT_META}; font-size: 11px;")
        left_lay.addWidget(self._status_label)

        splitter.addWidget(left)

        # Right: slot table
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(4)

        slots_label = QLabel("SLOTS")
        slots_label.setStyleSheet(STYLE_SECTION_LABEL)
        right_lay.addWidget(slots_label)

        self._slot_table = QTableWidget(0, 3)
        self._slot_table.setHorizontalHeaderLabels(["Slot", "Path", "Color Space"])
        self._slot_table.setStyleSheet(STYLE_TABLE)
        self._slot_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._slot_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._slot_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._slot_table.verticalHeader().setVisible(False)
        self._slot_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        right_lay.addWidget(self._slot_table)

        splitter.addWidget(right)
        splitter.setSizes([240, 460])
        root.addWidget(splitter, stretch=1)

        # --- Message ---
        self._message_label = QLabel("")
        self._message_label.setStyleSheet(f"color: {TEXT_ERROR};")
        self._message_label.setWordWrap(True)
        self._message_label.setVisible(False)
        root.addWidget(self._message_label)

        # --- Unmatched (clickable to show log) ---
        self._unmatched_btn = QPushButton("")
        self._unmatched_btn.setStyleSheet(f"""
            QPushButton {{
                color: {AMBER};
                font-size: 15px;
                font-weight: 600;
                text-align: left;
                background: transparent;
                border: none;
                padding: 4px 0;
            }}
            QPushButton:hover {{
                color: #fbbf24;
            }}
        """)
        self._unmatched_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._unmatched_btn.setVisible(False)
        self._unmatched_btn.clicked.connect(self._on_unmatched_clicked)
        root.addWidget(self._unmatched_btn)

        # --- Bottom row ---
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        self._auto_assign_btn = QPushButton("Auto assign")
        self._auto_assign_btn.setStyleSheet(STYLE_BTN_PRIMARY_EMERALD)
        self._auto_assign_btn.setToolTip(
            "Match prims named *_grp / *_Grp with M_char_* under /materials and create Assign Material LOPs. Select a LOP node first."
        )
        bottom_row.addWidget(self._auto_assign_btn)

        bottom_row.addStretch()

        self._create_btn = QPushButton("Create Materials in Solaris")
        self._create_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self._create_btn.setEnabled(False)
        bottom_row.addWidget(self._create_btn)

        root.addLayout(bottom_row)

        self.setStyleSheet(STYLE_WINDOW)

        self._groups_data: dict = {}
        self._unmatched_data: list[str] = []

        self._loading = _LoadingOverlay(self)

    # --- Public API ---

    def get_folder(self) -> str:
        return self._folder_combo.currentText().strip()

    def set_folder(self, path: str) -> None:
        self._folder_combo.setCurrentText(path)

    def save_folder_to_history(self, path: str) -> None:
        path = path.strip()
        if not path:
            return
        if path in self._path_history:
            self._path_history.remove(path)
        self._path_history.insert(0, path)
        self._path_history = self._path_history[:_MAX_HISTORY]
        _save_path_history(self._path_history)
        self._folder_combo.clear()
        for p in self._path_history:
            self._folder_combo.addItem(p)
        self._folder_combo.setCurrentText(path)

    def is_recursive(self) -> bool:
        return self._recursive_cb.isChecked()

    def set_materials(self, groups: dict, unmatched: list[str]) -> None:
        self._groups_data = groups
        self._unmatched_data = unmatched
        self._material_list.clear()
        self._slot_table.setRowCount(0)

        for prefix, group in groups.items():
            n_slots = len(group.slots)
            has_udim = any(s.udim for s in group.slots.values())
            badge = f"[{group.parse_mode}]"
            udim_tag = " UDIM" if has_udim else ""
            label = f"{prefix}  —  {n_slots} slots  {badge}{udim_tag}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, prefix)
            self._material_list.addItem(item)

        n_mat = len(groups)
        n_un = len(unmatched)
        self._status_label.setText(f"{n_mat} material(s) found")
        self._create_btn.setEnabled(n_mat > 0)

        if n_un > 0:
            self._unmatched_btn.setText(f"⚠ {n_un} unmatched file(s) — click to show list")
            self._unmatched_btn.setVisible(True)
        else:
            self._unmatched_btn.setVisible(False)

        if n_mat > 0:
            self._material_list.setCurrentRow(0)

    def set_message(self, text: str, error: bool = False) -> None:
        self._message_label.setText(text)
        self._message_label.setStyleSheet(f"color: {TEXT_ERROR if error else TEXT_META};")
        self._message_label.setVisible(bool(text))

    def get_selected_material_prefix(self) -> str | None:
        item = self._material_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def get_all_material_prefixes(self) -> list[str]:
        out = []
        for i in range(self._material_list.count()):
            item = self._material_list.item(i)
            if item and not item.data(ROLE_DISABLED):
                val = item.data(Qt.ItemDataRole.UserRole)
                if val:
                    out.append(str(val))
        return out

    def show_loading(self, text: str = "Loading...") -> None:
        self._loading.set_text(text)
        self._loading.setGeometry(self.rect())
        self._loading.setVisible(True)
        self._loading.raise_()
        QApplication.processEvents()

    def show_done(self, text: str, sub_text: str | None = None) -> None:
        """Show completion message on the overlay. Click to dismiss."""
        self._loading.set_done(text, sub_text)
        self._loading.setGeometry(self.rect())
        self._loading.setVisible(True)
        self._loading.raise_()
        QApplication.processEvents()

    def hide_loading(self) -> None:
        self._loading.setVisible(False)
        self._loading.reset()
        QApplication.processEvents()

    def is_cancelled(self) -> bool:
        QApplication.processEvents()
        return self._loading.cancelled

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._loading.setGeometry(self.rect())

    # --- Callbacks ---

    def on_scan_clicked(self, callback: Callable[[], None]) -> None:
        self._scan_btn.clicked.connect(callback)

    def on_publish_clicked(self, callback: Callable[[], None]) -> None:
        self._publish_btn.clicked.connect(callback)

    def on_create_clicked(self, callback: Callable[[], None]) -> None:
        self._create_btn.clicked.connect(callback)

    def on_auto_assign_clicked(self, callback: Callable[[], None]) -> None:
        self._auto_assign_btn.clicked.connect(callback)

    # --- Internal ---

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Texture Folder", self.get_folder())
        if folder:
            self._folder_combo.setCurrentText(folder)

    def _on_unmatched_clicked(self) -> None:
        if not self._unmatched_data:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Unmatched files")
        dlg.setMinimumSize(480, 320)
        dlg.resize(560, 400)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        label = QLabel(f"{len(self._unmatched_data)} file(s) were not assigned to any material.")
        label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        layout.addWidget(label)
        log = QPlainTextEdit()
        log.setReadOnly(True)
        log.setPlainText("\n".join(self._unmatched_data))
        log.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {BG_CONTENT};
                color: {TEXT_LABEL};
                border: 1px solid #2a2a2c;
                border-radius: 6px;
                padding: 8px;
                font-size: 12px;
            }}
        """)
        layout.addWidget(log, stretch=1)
        ok_btn = QPushButton("OK")
        ok_btn.setMinimumWidth(80)
        ok_btn.clicked.connect(dlg.accept)
        layout.addWidget(ok_btn, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.setStyleSheet(f"QDialog {{ background: {BG_PANEL}; }}")
        dlg.exec()

    def _on_material_clicked(self, index) -> None:
        item_rect = self._material_list.visualRect(index)
        x_rect = _MaterialItemDelegate._x_rect(item_rect)
        cursor_pos = self._material_list.viewport().mapFromGlobal(
            self._material_list.cursor().pos()
        )
        if x_rect.contains(cursor_pos):
            item = self._material_list.item(index.row())
            if item:
                current = bool(item.data(ROLE_DISABLED))
                item.setData(ROLE_DISABLED, not current)
                self._material_list.viewport().update()
                self._update_status_count()

    def _update_status_count(self) -> None:
        total = self._material_list.count()
        enabled = sum(
            1 for i in range(total)
            if not (self._material_list.item(i) and self._material_list.item(i).data(ROLE_DISABLED))
        )
        if enabled < total:
            self._status_label.setText(f"{enabled}/{total} material(s) enabled")
        else:
            self._status_label.setText(f"{total} material(s) found")

    def _on_material_selected(self, row: int) -> None:
        self._slot_table.setRowCount(0)
        item = self._material_list.item(row)
        if item is None:
            return
        prefix = item.data(Qt.ItemDataRole.UserRole)
        group = self._groups_data.get(prefix)
        if group is None:
            return

        self._slot_table.setRowCount(len(group.slots))
        for i, (slot_name, slot_info) in enumerate(sorted(group.slots.items())):
            slot_item = QTableWidgetItem(slot_name)
            slot_item.setFlags(slot_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._slot_table.setItem(i, 0, slot_item)

            path_display = slot_info.filepath.replace("%(UDIM)d", "<UDIM>")
            if len(path_display) > 60:
                path_display = "..." + path_display[-57:]
            path_item = QTableWidgetItem(path_display)
            path_item.setToolTip(slot_info.filepath)
            self._slot_table.setItem(i, 1, path_item)

            cs = slot_info.colorspace or "—"
            cs_item = QTableWidgetItem(cs)
            cs_item.setFlags(cs_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._slot_table.setItem(i, 2, cs_item)
