"""
Scene Info UI — PySide6, dark theme.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Qt


BACKGROUND = "#1b1b1b"
TEXT_COLOR = "#e0e0e0"


class SceneInfoUI(QWidget):
    """Simple widget showing scene summary text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(f"color: {TEXT_COLOR}; font-size: 12px; padding: 8px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self.setStyleSheet(f"background-color: {BACKGROUND};")
        self.setMinimumWidth(320)
        self.setMinimumHeight(120)

    def set_summary(self, text: str) -> None:
        self._label.setText(text)
