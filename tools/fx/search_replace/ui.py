"""
Search & Replace UI — Find/Replace, scope, target, preview, Apply.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)
from PySide6.QtCore import Qt

BACKGROUND = "#1b1b1b"
TEXT_COLOR = "#e0e0e0"
INPUT_STYLE = "background-color: #2d2d2d; color: #e0e0e0; padding: 4px; border-radius: 2px;"
BUTTON_STYLE = """
    QPushButton { background-color: #2d2d2d; color: #e0e0e0; padding: 6px 12px; border-radius: 4px; }
    QPushButton:hover { background-color: #3d3d3d; }
    QPushButton:disabled { color: #666; }
"""


class SearchReplaceUI(QWidget):
    """UI: find, replace, scope, target, preview, Apply."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText("Find (text or regex)...")
        self._find_edit.setStyleSheet(INPUT_STYLE)
        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText("Replace with...")
        self._replace_edit.setStyleSheet(INPUT_STYLE)
        self._regex_check = QCheckBox("Use regex")
        self._scope_combo = QComboBox()
        self._target_combo = QComboBox()
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMinimumHeight(120)
        self._preview_btn = QPushButton("Preview")
        self._apply_btn = QPushButton("Apply")
        self._preview_btn.setStyleSheet(BUTTON_STYLE)
        self._apply_btn.setStyleSheet(BUTTON_STYLE)

        layout = QVBoxLayout(self)
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

        self.setStyleSheet(f"background-color: {BACKGROUND}; color: {TEXT_COLOR};")
        self.setMinimumWidth(480)
        self.setMinimumHeight(420)

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
