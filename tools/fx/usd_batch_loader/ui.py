"""
USD Batch Load UI — MONOS design system (Solaris / LOP).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tools.fx.usd_batch_loader import config

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

STYLE_WINDOW = f"""
    QWidget#UsdBatchLoadWindow {{
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
        font-family: "JetBrains Mono", "Consolas", monospace;
        font-size: 12px;
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
    QPushButton#DialogPrimaryButton {{
        background: rgba(37, 99, 235, 0.22);
        border: 1px solid rgba(37, 99, 235, 0.70);
        color: {TEXT_PRIMARY};
        padding: 8px 16px;
        border-radius: 8px;
        font-weight: 600;
    }}
    QPushButton#DialogPrimaryButton:hover {{
        background: rgba(37, 99, 235, 0.35);
        border-color: rgba(59, 130, 246, 0.80);
    }}
    QPushButton#DialogPrimaryButton:disabled {{
        border: 1px solid rgba(39, 39, 42, 0.50);
        background: rgba(24, 24, 27, 0.35);
        color: rgba(250, 250, 250, 0.45);
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
    QComboBox:focus {{
        border: 1px solid {BLUE_600};
    }}
    QComboBox QAbstractItemView {{
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid rgba(39, 39, 42, 0.70);
        selection-background-color: rgba(37, 99, 235, 0.20);
        outline: none;
    }}
"""

STYLE_LIST = f"""
    QListWidget {{
        background: {BG_CONTENT};
        color: {TEXT_PRIMARY};
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 6px;
        padding: 4px;
        font-family: "JetBrains Mono", "Consolas", monospace;
        font-size: 12px;
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
"""


class UsdBatchLoadUI(QWidget):
    """Batch load USD files into Solaris — folder, mode, preview list, Load."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("UsdBatchLoadWindow")
        self.setStyleSheet(STYLE_WINDOW + STYLE_INPUT + STYLE_BTN + STYLE_BTN_PRIMARY + STYLE_COMBO + STYLE_LIST)
        self.setMinimumWidth(520)
        self.setMinimumHeight(480)

        title = QLabel(config.WINDOW_TITLE)
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")

        self._message_label = QLabel()
        self._message_label.setStyleSheet(f"color: {TEXT_ERROR}; font-size: 12px;")
        self._message_label.setWordWrap(True)
        self._message_label.hide()

        self._network_label = QLabel("Network: —")
        self._network_label.setStyleSheet(f"color: {TEXT_META}; font-size: 11px;")
        self._network_label.setWordWrap(True)

        folder_lbl = QLabel("USD folder")
        folder_lbl.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("Select folder containing .usd / .usda / .usdc …")
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setObjectName("DialogSecondaryButton")

        folder_row = QHBoxLayout()
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(self._browse_btn)

        mode_lbl = QLabel("Load mode")
        mode_lbl.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        self._mode_combo = QComboBox()
        for label, _value in config.MODE_OPTIONS:
            self._mode_combo.addItem(label)

        prim_lbl = QLabel("Reference prim prefix")
        prim_lbl.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        self._prim_prefix_edit = QLineEdit("/")
        self._prim_prefix_edit.setPlaceholderText("/world/geo")
        self._prim_prefix_row_lbl = prim_lbl

        strip_lbl = QLabel("Strip name")
        strip_lbl.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        self._strip_name_edit = QLineEdit()
        self._strip_name_edit.setPlaceholderText("prop_,publish  (comma-separated, removed from node name)")

        self._recursive_cb = QCheckBox("Include subfolders")
        self._recursive_cb.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")

        list_header = QHBoxLayout()
        self._file_count_label = QLabel("Files: 0")
        self._file_count_label.setStyleSheet(f"color: {TEXT_META}; font-size: 11px;")
        list_header.addWidget(QLabel("Preview"))
        list_header.addStretch()
        list_header.addWidget(self._file_count_label)

        self._file_list = QListWidget()
        self._file_list.setMinimumHeight(180)

        self._load_btn = QPushButton("Load USD into Solaris")
        self._load_btn.setObjectName("DialogPrimaryButton")
        self._load_btn.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self._message_label)
        layout.addWidget(self._network_label)
        layout.addWidget(folder_lbl)
        layout.addLayout(folder_row)
        layout.addWidget(mode_lbl)
        layout.addWidget(self._mode_combo)
        layout.addWidget(self._prim_prefix_row_lbl)
        layout.addWidget(self._prim_prefix_edit)
        layout.addWidget(strip_lbl)
        layout.addWidget(self._strip_name_edit)
        layout.addWidget(self._recursive_cb)
        layout.addLayout(list_header)
        layout.addWidget(self._file_list, 1)
        layout.addWidget(self._load_btn)

        self._mode_combo.currentIndexChanged.connect(self._sync_reference_fields)

    def _sync_reference_fields(self) -> None:
        is_ref = self.get_mode() == config.MODE_REFERENCE
        self._prim_prefix_row_lbl.setVisible(is_ref)
        self._prim_prefix_edit.setVisible(is_ref)

    def set_message(self, text: str, *, error: bool = True) -> None:
        self._message_label.setText(text or "")
        color = TEXT_ERROR if error else TEXT_META
        self._message_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._message_label.setVisible(bool(text))

    def set_network_path(self, path: str) -> None:
        self._network_label.setText(f"Network: {path or '—'}")

    def get_folder(self) -> str:
        return self._folder_edit.text().strip()

    def set_folder(self, path: str) -> None:
        self._folder_edit.setText(path or "")

    def get_mode(self) -> str:
        idx = self._mode_combo.currentIndex()
        if 0 <= idx < len(config.MODE_OPTIONS):
            return config.MODE_OPTIONS[idx][1]
        return config.MODE_SUBLAYER

    def get_prim_prefix(self) -> str:
        return self._prim_prefix_edit.text().strip() or "/"

    def get_strip_name(self) -> str:
        return self._strip_name_edit.text().strip()

    def get_recursive(self) -> bool:
        return self._recursive_cb.isChecked()

    def set_files(self, files: list[tuple[str, str, str]]) -> None:
        """``(abs_path, filename, node_name_preview)`` per row."""
        self._file_list.clear()
        for abs_path, name, node_name in files:
            it = QListWidgetItem(node_name)
            it.setToolTip(f"{name}\n{abs_path}")
            it.setData(Qt.ItemDataRole.UserRole, abs_path)
            self._file_list.addItem(it)
        n = len(files)
        self._file_count_label.setText(f"Files: {n}")
        self._load_btn.setEnabled(n > 0)

    def set_load_enabled(self, enabled: bool) -> None:
        self._load_btn.setEnabled(enabled)

    def on_browse_clicked(self, callback) -> None:
        self._browse_btn.clicked.connect(callback)

    def on_folder_changed(self, callback) -> None:
        self._folder_edit.textChanged.connect(callback)

    def on_strip_name_changed(self, callback) -> None:
        self._strip_name_edit.textChanged.connect(callback)

    def on_recursive_changed(self, callback) -> None:
        self._recursive_cb.toggled.connect(callback)

    def on_load_clicked(self, callback) -> None:
        self._load_btn.clicked.connect(callback)

    def pick_folder(self, start_dir: str = "") -> str | None:
        path = QFileDialog.getExistingDirectory(self, "Select USD folder", start_dir or "")
        return path or None

    def show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)

    def show_warning(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)
