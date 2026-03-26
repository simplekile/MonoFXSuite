"""
Search & Replace UI — MONOS design system.
Find/Replace, scope, target, preview, Apply.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# MONOS palette (aligned with auto_material)
# ---------------------------------------------------------------------------
BG_PANEL = "#18181b"
BG_CONTENT = "#121214"
BG_SURFACE = "#27272a"
TEXT_PRIMARY = "#fafafa"
TEXT_LABEL = "#a1a1aa"
TEXT_META = "#71717a"
BLUE_600 = "#2563eb"

STYLE_WINDOW = f"""
    QWidget#SearchReplaceWindow {{
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
    QPushButton:disabled {{
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

STYLE_PREVIEW = f"""
    QPlainTextEdit {{
        background: {BG_CONTENT};
        color: {TEXT_LABEL};
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 6px;
        padding: 8px;
        font-size: 12px;
    }}
"""

STYLE_LABEL = f"color: {TEXT_LABEL}; font-size: 12px;"


class SearchReplaceUI(QWidget):
    """UI: find, replace, scope, target, preview, Apply — MONOS style."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchReplaceWindow")
        self.setStyleSheet(STYLE_WINDOW)
        self.setMinimumWidth(480)
        self.setMinimumHeight(420)

        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText("Find (text or regex)...")
        self._find_edit.setStyleSheet(STYLE_INPUT)
        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText("Replace with...")
        self._replace_edit.setStyleSheet(STYLE_INPUT)

        self._regex_check = QCheckBox("Use regex")
        self._regex_check.setStyleSheet(f"color: {TEXT_LABEL};")

        self._scope_combo = QComboBox()
        self._scope_combo.setStyleSheet(STYLE_COMBO)
        self._target_combo = QComboBox()
        self._target_combo.setStyleSheet(STYLE_COMBO)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMinimumHeight(120)
        self._preview.setStyleSheet(STYLE_PREVIEW)

        self._preview_btn = QPushButton("Preview")
        self._preview_btn.setStyleSheet(STYLE_BTN)
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setStyleSheet(STYLE_BTN_PRIMARY)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Find:"))
        layout.addWidget(self._find_edit)
        layout.addWidget(QLabel("Replace with:"))
        layout.addWidget(self._replace_edit)
        layout.addWidget(self._regex_check)
        layout.addWidget(QLabel("Scope:"))
        layout.addWidget(self._scope_combo)
        layout.addWidget(QLabel("Target:"))
        layout.addWidget(self._target_combo)
        layout.addWidget(self._preview_btn)
        layout.addWidget(QLabel("Preview:"))
        layout.addWidget(self._preview)
        layout.addWidget(self._apply_btn)

        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if isinstance(w, QLabel):
                w.setStyleSheet(STYLE_LABEL)

    def get_find(self) -> str:
        return self._find_edit.text().strip()

    def get_replace(self) -> str:
        return self._replace_edit.text().strip()

    def get_use_regex(self) -> bool:
        return self._regex_check.isChecked()

    def set_scope_options(self, options: list) -> None:
        self._scope_combo.clear()
        for label, value in options:
            self._scope_combo.addItem(label, value)

    def get_scope(self) -> str:
        return self._scope_combo.currentData() or "selected"

    def set_target_options(self, options: list) -> None:
        self._target_combo.clear()
        for label, value in options:
            self._target_combo.addItem(label, value)

    def get_target(self) -> str:
        return self._target_combo.currentData() or "both"

    def set_preview(self, text: str) -> None:
        self._preview.setPlainText(text)

    def on_preview_clicked(self, callback):
        self._preview_btn.clicked.connect(callback)

    def on_apply_clicked(self, callback):
        self._apply_btn.clicked.connect(callback)

    def set_apply_enabled(self, enabled: bool) -> None:
        self._apply_btn.setEnabled(enabled)

    def show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)
