"""
Drag & Drop settings UI — PySide6, dark theme (same palette as Auto Material).
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tools.fx.drag_drop import config

BG_PANEL = "#18181b"
BG_SURFACE = "#27272a"
TEXT_PRIMARY = "#fafafa"
TEXT_LABEL = "#a1a1aa"
TEXT_META = "#71717a"
BLUE_600 = "#2563eb"

STYLE = f"""
    QWidget#DragDropSettings {{ background-color: {BG_PANEL}; color: {TEXT_PRIMARY}; }}
    QLabel {{ color: {TEXT_LABEL}; }}
    QLabel#Hint {{ color: {TEXT_META}; font-size: 11px; }}
    QCheckBox {{ color: {TEXT_PRIMARY}; spacing: 8px; }}
    QComboBox {{
        padding: 5px 8px; border: 1px solid rgba(39, 39, 42, 0.50); border-radius: 6px;
        background: {BG_SURFACE}; color: {TEXT_PRIMARY};
    }}
    QComboBox:focus {{ border: 1px solid {BLUE_600}; }}
    QPushButton {{
        background: rgba(24, 24, 27, 0.35); color: #a1a1aa; padding: 6px 14px;
        border: 1px solid rgba(39, 39, 42, 0.50); border-radius: 8px;
    }}
    QPushButton:hover {{ background: rgba(255, 255, 255, 0.12); color: #e4e4e7; }}
    QPushButton#Primary {{
        background: rgba(37, 99, 235, 0.22); border: 1px solid rgba(37, 99, 235, 0.70);
        color: {TEXT_PRIMARY}; font-weight: 600;
    }}
    QPushButton#Primary:hover {{ background: rgba(37, 99, 235, 0.35); }}
"""


class DragDropSettingsUI(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DragDropSettings")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(380)

        self._enabled = QCheckBox("Handle files dropped from the file browser")
        self._layer_mode = QComboBox()
        for value, label in config.LAYER_MODE_LABELS:
            self._layer_mode.addItem(label, value)
        self._textures = QCheckBox("Textures / texture folder in LOP build Auto Material")
        self._other_images = QCheckBox("Other images make a material each (image as base colour)")
        self._sequences = QCheckBox("Collapse frame sequences to $F")

        hint = QLabel("Off: Houdini handles every drop itself. Changes apply to the next drop.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        self._save = QPushButton("Save")
        self._save.setObjectName("Primary")
        self._reset = QPushButton("Defaults")
        self._cancel = QPushButton("Cancel")
        self._cancel.clicked.connect(self.close)

        layer_row = QVBoxLayout()
        layer_row.setSpacing(4)
        layer_row.addWidget(QLabel("Geo / Alembic / USD dropped in LOP"))
        layer_row.addWidget(self._layer_mode)

        buttons = QHBoxLayout()
        buttons.addWidget(self._reset)
        buttons.addStretch(1)
        buttons.addWidget(self._cancel)
        buttons.addWidget(self._save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._enabled)
        layout.addWidget(hint)
        layout.addLayout(layer_row)
        layout.addWidget(self._textures)
        layout.addWidget(self._other_images)
        layout.addWidget(self._sequences)
        layout.addStretch(1)
        layout.addLayout(buttons)

        self._enabled.toggled.connect(self._update_enabled)
        self._textures.toggled.connect(self._update_enabled)

    def set_prefs(self, data: dict[str, Any]) -> None:
        self._enabled.setChecked(bool(data["enabled"]))
        self._layer_mode.setCurrentIndex(max(0, self._layer_mode.findData(data["lop_layer_mode"])))
        self._textures.setChecked(bool(data["lop_textures_material"]))
        self._other_images.setChecked(bool(data["other_images_base_color"]))
        self._sequences.setChecked(bool(data["collapse_sequences"]))
        self._update_enabled()

    def get_prefs(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled.isChecked(),
            "lop_layer_mode": self._layer_mode.currentData(),
            "lop_textures_material": self._textures.isChecked(),
            "other_images_base_color": self._other_images.isChecked(),
            "collapse_sequences": self._sequences.isChecked(),
        }

    def on_save_clicked(self, callback: Callable[[], None]) -> None:
        self._save.clicked.connect(callback)

    def on_reset_clicked(self, callback: Callable[[], None]) -> None:
        self._reset.clicked.connect(callback)

    def _update_enabled(self) -> None:
        on = self._enabled.isChecked()
        for w in (self._layer_mode, self._textures, self._sequences):
            w.setEnabled(on)
        self._other_images.setEnabled(on and self._textures.isChecked())
