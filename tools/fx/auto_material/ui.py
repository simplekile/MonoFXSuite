"""
Auto Material Builder UI — MONOS design system.

Two pages: Start (where the textures come from, and the assets already in the scene) and the
Version manager (materials of one source, each with its version chip, and the maps of the one selected).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tools.fx.auto_material.logic import (
    STATUS_MISSING,
    STATUS_NEW,
    STATUS_OK,
    STATUS_PINNED,
    STATUS_UPDATE,
    MaterialPlan,
    material_status,
    plan_summary,
    to_latest,
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
ZINC_400 = "#a1a1aa"
ZINC_500 = "#71717a"

def _font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Font in pixels: Houdini scales point sizes with its UI scale, which overflows painted chips."""
    font = QFont("Inter")
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


STYLE_WINDOW = f"""
    QWidget#AutoMaterialWindow {{
        background-color: {BG_PANEL};
        color: {TEXT_PRIMARY};
    }}
    QLabel {{ color: {TEXT_PRIMARY}; }}
    QWidget#AutoMaterialWindow QWidget {{ font-size: 13px; }}
    QPushButton, QToolButton, QComboBox, QCheckBox, QLineEdit {{ font-size: 13px; }}
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

STYLE_BTN_LINK = f"""
    QPushButton {{ background: transparent; border: none; color: {TEXT_LABEL}; padding: 2px 4px; }}
    QPushButton:hover {{ color: {BLUE_400}; }}
"""

STYLE_BTN_PRIMARY = f"""
    QPushButton {{
        background: rgba(37, 99, 235, 0.22);
        border: 1px solid rgba(37, 99, 235, 0.70);
        color: {TEXT_PRIMARY};
        padding: 8px 16px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 14px;
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
"""

STYLE_LIST = f"""
    QListWidget {{
        background-color: #0d0d0f;
        border: none;
        outline: none;
        padding: 5px;
        border-radius: 8px;
        color: {TEXT_PRIMARY};
    }}
"""

STYLE_TABLE = f"""
    QTableWidget {{
        background-color: {BG_CONTENT};
        border: 1px solid #2a2a2c;
        gridline-color: #2a2a2c;
        color: #eeeeee;
        font-size: 14px;
        selection-background-color: rgba(37, 99, 235, 0.15);
        selection-color: {BLUE_400};
        outline: none;
        border-radius: 8px;
    }}
    QHeaderView::section {{
        background-color: #0d0d0f;
        color: #4a4a4c;
        padding: 8px 12px;
        border: none;
        border-bottom: 2px solid #2a2a2c;
        font-weight: 800;
        font-size: 13px;
    }}
    QTableWidget::item {{
        padding: 0px 10px;
        border-bottom: 1px solid #1e1e20;
        background-color: {BG_CONTENT};
    }}
    QTableWidget::item:selected {{ background: rgba(37, 99, 235, 0.15); color: {BLUE_400}; }}
"""

STYLE_CHECKBOX = f"""
    QCheckBox {{ color: {TEXT_LABEL}; spacing: 6px; }}
    QCheckBox::indicator {{
        width: 14px; height: 14px; border-radius: 3px;
        border: 1px solid {ZINC_500}; background: transparent;
    }}
    QCheckBox::indicator:checked {{ background: rgba(37, 99, 235, 0.80); border-color: {BLUE_400}; }}
"""

STYLE_SECTION_LABEL = f"color: {TEXT_META}; font-size: 12px; font-weight: 800; letter-spacing: 1px;"

STYLE_COMBO = f"""
    QComboBox {{
        padding: 6px 8px;
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 6px;
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
    }}
    QComboBox:focus {{ border: 1px solid {BLUE_600}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
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

STYLE_MENU = f"""
    QMenu {{
        background: {BG_PANEL};
        color: {TEXT_PRIMARY};
        border: 1px solid #3f3f46;
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{ padding: 6px 14px; border-radius: 6px; }}
    QMenu::item:selected {{ background: rgba(37, 99, 235, 0.20); }}
    QMenu::item:disabled {{ color: {TEXT_META}; }}
    QMenu::separator {{ height: 1px; background: #27272a; margin: 4px 6px; }}
"""

STYLE_CARD = """
    QFrame#SourceCard {
        background: rgba(24, 24, 27, 0.35);
        border: 1px solid rgba(63, 63, 70, 0.60);
        border-radius: 12px;
    }
    QFrame#SourceCard:hover { background: rgba(255, 255, 255, 0.06); border-color: rgba(96, 165, 250, 0.60); }
    QFrame#SourceCard[primary="true"] { border: 2px solid rgba(37, 99, 235, 0.80); }
    QFrame#SourceCard[enabled_card="false"] { border-color: rgba(39, 39, 42, 0.60); }
"""

STYLE_BANNER = """
    QFrame#Banner {
        background: rgba(37, 99, 235, 0.16);
        border: 1px solid rgba(37, 99, 235, 0.50);
        border-radius: 8px;
    }
"""

STYLE_SOURCE_BAR = """
    QFrame#SourceBar {
        background: rgba(24, 24, 27, 0.35);
        border: 1px solid rgba(63, 63, 70, 0.60);
        border-radius: 8px;
    }
"""

# Version chips: (text colour, rgb of the tint) — MONOS emerald / blue / violet / amber / red.
CHIP_TONES: dict[str, tuple[str, str]] = {
    STATUS_OK:      ("#34d399", "16, 185, 129"),
    STATUS_UPDATE:  (BLUE_400,  "37, 99, 235"),
    STATUS_NEW:     ("#a78bfa", "139, 92, 246"),
    STATUS_PINNED:  ("#fbbf24", "245, 158, 11"),
    STATUS_MISSING: ("#f87171", "239, 68, 68"),
    "zinc":         (TEXT_LABEL, "63, 63, 70"),
}

CHIP_HELP = {
    STATUS_OK: "Up to date",
    STATUS_UPDATE: "Create switches it to this version",
    STATUS_NEW: "Not in the scene yet",
    STATUS_PINNED: "Pinned: All to latest and later updates keep it here",
    STATUS_MISSING: "Not in the export the geometry comes from: the geometry may not match",
}


def _chip_style(tone: str) -> str:
    fg, rgb = CHIP_TONES.get(tone, CHIP_TONES["zinc"])
    return (
        f"color: {fg}; background: rgba({rgb}, 0.16); border: 1px solid rgba({rgb}, 0.45);"
        "border-radius: 9px; padding: 1px 8px; font-size: 12px; font-weight: 600;"
    )


# ---------------------------------------------------------------------------
# Lucide icons
# ---------------------------------------------------------------------------
LUCIDE = {
    "rotate-cw": '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    "folder-open": '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "package": '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><path d="m3.3 7 7.703 4.734a2 2 0 0 0 1.994 0L20.7 7"/><path d="m7.5 4.27 9 5.15"/>',
    "file-box": '<path d="M14.5 22H18a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v4"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M3 13.1a2 2 0 0 0-1 1.76v3.24a2 2 0 0 0 .97 1.78L6 21.7a2 2 0 0 0 2.03.01L11 19.9a2 2 0 0 0 1-1.76V14.9a2 2 0 0 0-.97-1.78L8 11.3a2 2 0 0 0-2.03-.01Z"/><path d="M7 17v5"/><path d="M11.7 14.2 7 17l-4.7-2.8"/>',
    "arrow-left-right": '<path d="M8 3 4 7l4 4"/><path d="M4 7h16"/><path d="m16 21 4-4-4-4"/><path d="M20 17H4"/>',
    "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "box": '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    "building": '<rect width="16" height="20" x="4" y="2" rx="2" ry="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M12 6h.01"/><path d="M12 10h.01"/><path d="M12 14h.01"/><path d="M16 10h.01"/><path d="M16 14h.01"/><path d="M8 10h.01"/><path d="M8 14h.01"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "pin": '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "triangle-alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "sparkles": '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
}

ASSET_ICONS = {"character": "user", "prop": "box", "environment": "building"}


def _lucide_pixmap(name: str, size: int = 16, color: str = TEXT_LABEL, scale: float = 2.0) -> QPixmap:
    from PySide6.QtSvg import QSvgRenderer

    phys = int(size * scale)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{phys}" height="{phys}" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f"{LUCIDE[name]}</svg>"
    )
    pm = QPixmap(phys, phys)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    QSvgRenderer(svg.encode("utf-8")).render(painter)
    painter.end()
    pm.setDevicePixelRatio(scale)
    return pm


def _lucide_icon(name: str, size: int = 16, color: str = TEXT_LABEL) -> QIcon:
    icon = QIcon()
    for scale in (1.0, 2.0):
        icon.addPixmap(_lucide_pixmap(name, size, color, scale))
    return icon


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(STYLE_SECTION_LABEL)
    return label


def _slot_label(slot: str) -> str:
    return slot.replace("_", " ")


def _file_label(filepath: str) -> str:
    return Path(filepath.replace("%(UDIM)d", "<UDIM>")).name


def _icon_button(icon: str, tooltip: str) -> QToolButton:
    btn = QToolButton()
    btn.setIcon(_lucide_icon(icon))
    btn.setIconSize(QSize(16, 16))
    btn.setToolTip(tooltip)
    btn.setStyleSheet(STYLE_BTN)
    return btn


def open_in_explorer(path: str, select: bool = False) -> None:
    """Open a folder, or (select=True) the folder of a file with the file selected."""
    path = path.replace("%(UDIM)d", "1001").replace("<UDIM>", "1001")
    if select and sys.platform == "win32" and os.path.exists(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        return
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


# ---------------------------------------------------------------------------
# Path history (Recent)
# ---------------------------------------------------------------------------
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
        painter.setFont(_font(16, QFont.Weight.DemiBold))
        painter.drawText(self.rect().adjusted(0, -20, 0, 0), Qt.AlignmentFlag.AlignCenter, self._text)
        if self._sub_text:
            color = QColor(TEXT_ERROR) if self._mode == self._MODE_LOADING else QColor(TEXT_META)
            painter.setPen(color)
            painter.setFont(_font(13))
            painter.drawText(self.rect().adjusted(0, 40, 0, 0), Qt.AlignmentFlag.AlignCenter, self._sub_text)
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


# ---------------------------------------------------------------------------
# Material list: checkbox, name, version chip
# ---------------------------------------------------------------------------

ROLE_NAME = Qt.ItemDataRole.UserRole
ROLE_ENABLED = Qt.ItemDataRole.UserRole + 1
ROLE_CHIP = Qt.ItemDataRole.UserRole + 2     # (text, status) or None
ROLE_META = Qt.ItemDataRole.UserRole + 3     # e.g. "8 maps · UDIM" (folder source, no chip)

_BOX = 14


class _MaterialDelegate(QStyledItemDelegate):
    """Row: [checkbox] name ............ [chip]. The chip is the version and its status."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._icons: dict[tuple[str, str], QPixmap] = {}

    def _icon(self, name: str, color: str) -> QPixmap:
        key = (name, color)
        if key not in self._icons:
            self._icons[key] = _lucide_pixmap(name, 11, color)
        return self._icons[key]

    @staticmethod
    def box_rect(rect: QRect) -> QRect:
        return QRect(rect.left() + 10, rect.center().y() - _BOX // 2, _BOX, _BOX)

    def chip_rect(self, rect: QRect, index) -> QRect:
        chip = index.data(ROLE_CHIP)
        if not chip:
            return QRect()
        w = QFontMetrics(_font(12, QFont.Weight.DemiBold)).horizontalAdvance(chip[0]) + 18
        if chip[1] in (STATUS_OK, STATUS_PINNED, STATUS_MISSING):
            w += 14
        return QRect(rect.right() - w - 10, rect.center().y() - 10, w, 20)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect: QRect = option.rect
        enabled = bool(index.data(ROLE_ENABLED))
        selected = bool(option.state & option.state.__class__.State_Selected)
        hovered = bool(option.state & option.state.__class__.State_MouseOver)

        bg = QColor(37, 99, 235, 30) if selected else QColor(255, 255, 255, 8) if hovered else QColor(0, 0, 0, 0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect.adjusted(2, 1, -2, -1), 6, 6)

        # Checkbox
        box = self.box_rect(rect)
        if enabled:
            painter.setBrush(QColor(37, 99, 235, 200))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(box, 3, 3)
            painter.drawPixmap(box.adjusted(2, 2, -1, -1), self._icon("check", TEXT_PRIMARY))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(ZINC_500))
            painter.drawRoundedRect(box, 3, 3)

        # Chip / meta on the right
        right = rect.right() - 10
        chip = index.data(ROLE_CHIP)
        if chip and enabled:
            text, status = chip
            fg, rgb = CHIP_TONES.get(status, CHIP_TONES["zinc"])
            cr = self.chip_rect(rect, index)
            r, g, b = (int(x) for x in rgb.split(","))
            painter.setBrush(QColor(r, g, b, 45))
            painter.setPen(QColor(r, g, b, 120))
            painter.drawRoundedRect(cr, 10, 10)
            x = cr.left() + 9
            icon = {STATUS_OK: "check", STATUS_PINNED: "pin", STATUS_MISSING: "triangle-alert"}.get(status)
            if icon:
                painter.drawPixmap(QRect(x, cr.center().y() - 5, 11, 11), self._icon(icon, fg))
                x += 14
            painter.setPen(QColor(fg))
            painter.setFont(_font(12, QFont.Weight.DemiBold))
            painter.drawText(QRect(x, cr.top(), cr.right() - x - 6, cr.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            right = cr.left() - 8
        elif index.data(ROLE_META):
            meta = index.data(ROLE_META)
            painter.setFont(_font(12))
            painter.setPen(QColor(ZINC_500))
            w = painter.fontMetrics().horizontalAdvance(meta)
            painter.drawText(QRect(right - w, rect.top(), w, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, meta)
            right -= w + 8

        # Name
        font = _font(14, QFont.Weight.DemiBold if selected else QFont.Weight.Medium)
        font.setStrikeOut(not enabled)
        painter.setFont(font)
        painter.setPen(QColor(ZINC_500) if not enabled else QColor(BLUE_400) if selected else QColor("#e4e4e7"))
        name_rect = QRect(box.right() + 10, rect.top(), max(0, right - box.right() - 10), rect.height())
        text = painter.fontMetrics().elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "",
                                                Qt.TextElideMode.ElideRight, name_rect.width())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 36)


# ---------------------------------------------------------------------------
# Start page pieces
# ---------------------------------------------------------------------------

class _SourceCard(QFrame):
    """Big clickable card: icon, title, one line under it."""

    def __init__(self, icon: str, title: str, sub: str, on_click: Callable[[], None]) -> None:
        super().__init__()
        self.setObjectName("SourceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(STYLE_CARD)
        self.setMinimumHeight(104)
        self._on_click = on_click
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        self._icon = QLabel()
        self._icon.setPixmap(_lucide_pixmap(icon, 22, TEXT_LABEL))
        lay.addWidget(self._icon)
        lay.addSpacing(6)
        self._title = QLabel(title)
        self._title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 600;")
        lay.addWidget(self._title)
        self._sub = QLabel(sub)
        self._sub.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 13px;")
        self._sub.setWordWrap(True)
        lay.addWidget(self._sub)
        lay.addStretch()
        self._icon_name = icon
        self._usable = True

    def set_state(self, sub: str, usable: bool = True, primary: bool = False) -> None:
        self._sub.setText(sub)
        self._usable = usable
        self.setProperty("primary", "true" if primary and usable else "false")
        self.setProperty("enabled_card", "true" if usable else "false")
        self._icon.setPixmap(_lucide_pixmap(self._icon_name, 22, BLUE_400 if primary and usable else TEXT_LABEL))
        self.setCursor(Qt.CursorShape.PointingHandCursor if usable else Qt.CursorShape.ArrowCursor)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:
        if self._usable and event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(event)


class _AssetRow(QWidget):
    """Asset in the scene: [tick if it has a newer export] icon name · meta ....... chip  >"""

    def __init__(self, asset: dict, on_open: Callable[[str], None], on_tick: Callable[[], None]) -> None:
        super().__init__()
        self.key = asset["key"]
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)
        # Only assets with something to build get a tick; the others keep its room so icons line up.
        self.can_update = asset["status"] in (STATUS_UPDATE, STATUS_NEW)
        self.tick = QCheckBox()
        self.tick.setStyleSheet(STYLE_CHECKBOX)
        self.tick.setChecked(asset["status"] == STATUS_UPDATE)
        self.tick.setToolTip("Update with the others")
        self.tick.toggled.connect(lambda _on: on_tick())
        policy = self.tick.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.tick.setSizePolicy(policy)
        self.tick.setVisible(self.can_update)
        lay.addWidget(self.tick)
        icon = QLabel()
        icon.setPixmap(_lucide_pixmap(ASSET_ICONS.get(asset.get("kind", ""), "box"), 18, TEXT_LABEL))
        lay.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel(asset["name"] + (f"   <span style='color:{BLUE_400}; font-size:12px'>selected branch</span>"
                                       if asset.get("branch") else ""))
        name.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 600;")
        text.addWidget(name)
        meta = QLabel(asset.get("meta", ""))
        meta.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        text.addWidget(meta)
        lay.addLayout(text, stretch=1)
        chip = QLabel(asset["chip"])
        chip.setStyleSheet(_chip_style(asset["status"]))
        chip.setToolTip(CHIP_HELP.get(asset["status"], ""))
        chip.setFixedHeight(22)
        lay.addWidget(chip, alignment=Qt.AlignmentFlag.AlignVCenter)
        arrow = QLabel()
        arrow.setPixmap(_lucide_pixmap("chevron-right", 14, TEXT_META))
        lay.addWidget(arrow)
        self._on_open = on_open

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_open(self.key)
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------

class AutoMaterialUI(QWidget):

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("AutoMaterialWindow")
        self.setWindowTitle("Auto Material Builder")
        self.setMinimumWidth(760)
        self.setMinimumHeight(600)
        self.resize(1040, 860)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE_WINDOW)

        self._callbacks: dict[str, Callable[..., Any]] = {}
        self._mode = "folder"                  # "folder" | "usd"
        self._plans: list[MaterialPlan] = []
        self._groups_by_version: dict[str, dict] = {}   # usd: version -> {name: MaterialGroup}
        self._geometry_materials: frozenset[str] = frozenset()
        self._unmatched_data: list[str] = []
        self._source_path = ""
        self._asset_rows: list[_AssetRow] = []
        self._path_history = _load_path_history()
        self._load_pending = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_start_page())
        self._pages.addWidget(self._build_manager_page())
        root.addWidget(self._pages, stretch=1)

        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)
        self._message_label.setVisible(False)
        root.addWidget(self._message_label)

        self._loading = _LoadingOverlay(self)

    # =====================================================================
    # Build
    # =====================================================================

    def _build_start_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        title = QLabel("Auto Material Builder")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 20px; font-weight: 700;")
        lay.addWidget(title)
        sub = QLabel("Karma materials from a texture folder or a Substance Painter USD export.")
        sub.setStyleSheet(f"color: {TEXT_META}; font-size: 13px;")
        lay.addWidget(sub)
        lay.addSpacing(10)

        question = QLabel("Where are the textures?")
        question.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 600;")
        lay.addWidget(question)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self._card_publish = _SourceCard("package", "Latest publish", "Looking for the publish…",
                                         lambda: self._fire("latest_publish"))
        self._card_folder = _SourceCard("folder", "Texture folder", "Pick a folder of textures",
                                        self._pick_folder)
        self._card_usd = _SourceCard("file-box", "Painter USD", "Pick a Substance Painter .usd export",
                                     self._pick_usd)
        for card in (self._card_publish, self._card_folder, self._card_usd):
            cards.addWidget(card, stretch=1)
        lay.addLayout(cards)

        recent_row = QHBoxLayout()
        recent_row.setSpacing(8)
        recent_label = QLabel("Recent")
        recent_label.setStyleSheet(f"color: {TEXT_META}; font-size: 13px;")
        recent_row.addWidget(recent_label)
        self._recent_combo = QComboBox()
        self._recent_combo.setEditable(True)
        self._recent_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._recent_combo.lineEdit().setPlaceholderText("Paste a folder or .usd path and press Enter")
        self._recent_combo.setStyleSheet(STYLE_COMBO)
        self._recent_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._refill_recent()
        # Enter can fire returnPressed and activated (activated only for a history entry): one load.
        self._recent_combo.lineEdit().returnPressed.connect(self._request_open_recent)
        self._recent_combo.activated.connect(lambda _i: self._request_open_recent())
        recent_row.addWidget(self._recent_combo, stretch=1)
        lay.addLayout(recent_row)
        drop = QLabel("Or drop a folder or a .usd file anywhere on this window.")
        drop.setStyleSheet(f"color: {TEXT_META}; font-size: 12px;")
        lay.addWidget(drop)

        lay.addSpacing(14)
        self._assets_header = QHBoxLayout()
        self._assets_label = _section_label("IN THIS SCENE")
        self._assets_header.addWidget(self._assets_label)
        self._assets_header.addStretch()
        self._assets_hint = QLabel("")
        self._assets_hint.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        self._assets_header.addWidget(self._assets_hint)
        lay.addLayout(self._assets_header)

        self._asset_list = QListWidget()
        self._asset_list.setStyleSheet(STYLE_LIST)
        self._asset_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._asset_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        lay.addWidget(self._asset_list, stretch=1)
        self._assets_empty = QLabel("No asset from a Painter export in this scene yet.")
        self._assets_empty.setStyleSheet(f"color: {TEXT_META}; font-size: 13px; padding: 8px 2px;")
        lay.addWidget(self._assets_empty)

        foot = QHBoxLayout()
        foot.addStretch()
        self._update_assets_btn = QPushButton("Update")
        self._update_assets_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self._update_assets_btn.clicked.connect(lambda: self._fire("update_assets", self.ticked_assets()))
        foot.addWidget(self._update_assets_btn)
        lay.addLayout(foot)
        return page

    def _build_manager_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # New export banner
        self._banner = QFrame()
        self._banner.setObjectName("Banner")
        self._banner.setStyleSheet(STYLE_BANNER)
        b_lay = QHBoxLayout(self._banner)
        b_lay.setContentsMargins(12, 6, 8, 6)
        spark = QLabel()
        spark.setPixmap(_lucide_pixmap("sparkles", 16, BLUE_400))
        b_lay.addWidget(spark)
        self._banner_label = QLabel("")
        self._banner_label.setStyleSheet(f"color: {BLUE_400}; font-size: 14px;")
        b_lay.addWidget(self._banner_label, stretch=1)
        self._banner_btn = QPushButton("Open version manager")
        self._banner_btn.setStyleSheet(STYLE_BTN)
        self._banner_btn.clicked.connect(lambda: self._fire("banner"))
        b_lay.addWidget(self._banner_btn)
        self._banner.setVisible(False)
        lay.addWidget(self._banner)

        # Source bar
        bar = QFrame()
        bar.setObjectName("SourceBar")
        bar.setStyleSheet(STYLE_SOURCE_BAR)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(12, 6, 6, 6)
        bar_lay.setSpacing(10)
        self._source_icon = QLabel()
        bar_lay.addWidget(self._source_icon)
        self._source_name = QLabel("")
        self._source_name.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700;")
        bar_lay.addWidget(self._source_name)
        self._source_meta = QLabel("")
        self._source_meta.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 13px;")
        self._source_meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bar_lay.addWidget(self._source_meta, stretch=1)
        self._unmatched_btn = QPushButton("")
        self._unmatched_btn.setStyleSheet(
            f"QPushButton {{ {_chip_style(STATUS_PINNED)} }} QPushButton:hover {{ background: rgba(245,158,11,0.28); }}")
        self._unmatched_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._unmatched_btn.clicked.connect(self._on_unmatched_clicked)
        self._unmatched_btn.setVisible(False)
        bar_lay.addWidget(self._unmatched_btn)
        self._recursive_cb = QCheckBox("Include subfolders")
        self._recursive_cb.setChecked(True)
        self._recursive_cb.setStyleSheet(STYLE_CHECKBOX)
        self._recursive_cb.toggled.connect(lambda _on: self._fire("reload"))
        bar_lay.addWidget(self._recursive_cb)
        self._folder_btn = _icon_button("folder-open", "Open the source folder in Explorer")
        self._folder_btn.clicked.connect(self._open_source_folder)
        bar_lay.addWidget(self._folder_btn)
        self._reload_btn = _icon_button("rotate-cw", "Reload from disk")
        self._reload_btn.clicked.connect(lambda: self._fire("reload"))
        bar_lay.addWidget(self._reload_btn)
        self._change_btn = QPushButton("Change")
        self._change_btn.setIcon(_lucide_icon("arrow-left-right", 14, BLUE_400))
        self._change_btn.setStyleSheet(STYLE_BTN_LINK + f"QPushButton {{ color: {BLUE_400}; }}")
        self._change_btn.setToolTip("Pick another source")
        self._change_btn.clicked.connect(lambda: self._fire("change"))
        bar_lay.addWidget(self._change_btn)
        lay.addWidget(bar)

        # Body: materials | maps
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(14)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; }")

        left = QWidget()
        l_lay = QVBoxLayout(left)
        l_lay.setContentsMargins(0, 0, 0, 0)
        l_lay.setSpacing(6)
        l_head = QHBoxLayout()
        self._materials_label = _section_label("MATERIALS")
        l_head.addWidget(self._materials_label)
        l_head.addStretch()
        self._latest_btn = QPushButton("All to latest")
        self._latest_btn.setStyleSheet(STYLE_BTN_LINK)
        self._latest_btn.setToolTip("Every material that is not pinned to its newest version")
        self._latest_btn.clicked.connect(self._all_to_latest)
        l_head.addWidget(self._latest_btn)
        l_lay.addLayout(l_head)

        self._material_list = QListWidget()
        self._material_list.setStyleSheet(STYLE_LIST)
        self._material_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._material_list.setMouseTracking(True)
        self._material_delegate = _MaterialDelegate(self._material_list)
        self._material_list.setItemDelegate(self._material_delegate)
        self._material_list.currentRowChanged.connect(self._show_maps)
        self._material_list.viewport().installEventFilter(self)
        self._material_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._material_list.customContextMenuRequested.connect(self._material_menu)
        l_lay.addWidget(self._material_list)

        self._legend = QLabel("")
        self._legend.setTextFormat(Qt.TextFormat.RichText)
        self._legend.setWordWrap(True)
        l_lay.addWidget(self._legend)
        splitter.addWidget(left)

        right = QWidget()
        r_lay = QVBoxLayout(right)
        r_lay.setContentsMargins(0, 0, 0, 0)
        r_lay.setSpacing(6)
        self._maps_label = _section_label("MAPS")
        r_lay.addWidget(self._maps_label)
        self._slot_table = QTableWidget(0, 3)
        self._slot_table.setHorizontalHeaderLabels(["Map", "File", "Color space"])
        self._slot_table.setStyleSheet(STYLE_TABLE)
        header = self._slot_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._slot_table.verticalHeader().setVisible(False)
        self._slot_table.verticalHeader().setDefaultSectionSize(32)
        self._slot_table.setShowGrid(False)
        self._slot_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._slot_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._slot_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._slot_table.customContextMenuRequested.connect(self._map_menu)
        r_lay.addWidget(self._slot_table)
        self._maps_note = QLabel("")
        self._maps_note.setStyleSheet(f"color: {CHIP_TONES[STATUS_MISSING][0]}; font-size: 13px;")
        self._maps_note.setWordWrap(True)
        r_lay.addWidget(self._maps_note)
        splitter.addWidget(right)
        splitter.setSizes([360, 660])
        lay.addWidget(splitter, stretch=1)

        # Footer
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(39, 39, 42, 0.80);")
        lay.addWidget(divider)
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self._auto_assign_btn = QPushButton("Auto assign")
        self._auto_assign_btn.setStyleSheet(STYLE_BTN_PRIMARY_EMERALD)
        self._auto_assign_btn.setToolTip(
            "Match prims named *_grp / *_Grp with M_char_* under /materials and create Assign Material LOPs. "
            "Select a LOP node first.")
        self._auto_assign_btn.clicked.connect(lambda: self._fire("auto_assign"))
        foot.addWidget(self._auto_assign_btn)
        foot.addStretch(1)
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 13px;")
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._summary_label.setWordWrap(True)
        foot.addWidget(self._summary_label, stretch=2)
        self._create_btn = QPushButton("Create")
        self._create_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self._create_btn.setMinimumWidth(230)
        self._create_btn.clicked.connect(lambda: self._fire("create"))
        foot.addWidget(self._create_btn)
        lay.addLayout(foot)
        return page

    # =====================================================================
    # Callbacks (controller)
    # =====================================================================

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        """
        latest_publish(), open_path(path), open_asset(key), update_assets(keys), change(), reload(),
        create(), auto_assign(), banner(), activated()
        """
        self._callbacks[event] = callback

    def _fire(self, event: str, *args) -> None:
        cb = self._callbacks.get(event)
        if cb is not None:
            cb(*args)

    # =====================================================================
    # Start page
    # =====================================================================

    def show_start(self, latest: str | None, assets: list[dict]) -> None:
        """
        latest: label of the publish found from $HIP (e.g. "char_Helen · v008 · USD") or None.
        assets: dicts with key, name, kind, meta, chip, status, branch.
        """
        self._card_publish.set_state(latest or "No publish next to this .hip", usable=bool(latest), primary=True)
        self._asset_list.clear()
        self._asset_rows = []
        for asset in assets:
            row = _AssetRow(asset, lambda key: self._fire("open_asset", key), self._refresh_update_button)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 58))
            self._asset_list.addItem(item)
            self._asset_list.setItemWidget(item, row)
            self._asset_rows.append(row)
        has_assets = bool(assets)
        self._asset_list.setVisible(has_assets)
        self._assets_empty.setVisible(not has_assets)
        n_upd = sum(1 for a in assets if a["status"] == STATUS_UPDATE)
        n_new = sum(1 for a in assets if a["status"] == STATUS_NEW)
        hint = [f"{n_upd} with a newer export"] if n_upd else []
        hint += [f"{n_new} not in the scene yet"] if n_new else []
        self._assets_hint.setText(" · ".join(hint) or ("All up to date" if has_assets else ""))
        self._refresh_update_button()
        self._pages.setCurrentIndex(0)

    def ticked_assets(self) -> list[str]:
        return [row.key for row in self._asset_rows if row.can_update and row.tick.isChecked()]

    def _refresh_update_button(self) -> None:
        n = len(self.ticked_assets())
        self._update_assets_btn.setVisible(any(row.can_update for row in self._asset_rows))
        self._update_assets_btn.setEnabled(n > 0)
        self._update_assets_btn.setText(f"Update {n} asset" + ("s" if n != 1 else "") if n else "Tick assets to update")

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Texture Folder", self._last_dir())
        if folder:
            self._fire("open_path", folder)

    def _pick_usd(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Substance Painter USD export", self._last_dir(), "USD (*.usd *.usda *.usdc)")
        if path:
            self._fire("open_path", path)

    def _last_dir(self) -> str:
        last = self._source_path or (self._path_history[0] if self._path_history else "")
        return last if os.path.isdir(last) else os.path.dirname(last)

    def _request_open_recent(self) -> None:
        if self._load_pending:
            return
        self._load_pending = True

        def run() -> None:
            self._load_pending = False
            path = self._recent_combo.currentText().strip()
            if path:
                self._fire("open_path", path)

        QTimer.singleShot(0, run)

    def _refill_recent(self) -> None:
        self._recent_combo.clear()
        for p in self._path_history:
            self._recent_combo.addItem(p)
        self._recent_combo.setCurrentText("")

    def save_to_history(self, path: str) -> None:
        path = path.strip()
        if not path:
            return
        if path in self._path_history:
            self._path_history.remove(path)
        self._path_history.insert(0, path)
        self._path_history = self._path_history[:_MAX_HISTORY]
        _save_path_history(self._path_history)
        self._refill_recent()

    # Drag and drop: a folder or a .usd anywhere on the window
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self._fire("open_path", url.toLocalFile())
                break

    # Window comes back to the front: the controller checks for a newer export
    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._fire("activated")

    # =====================================================================
    # Version manager page
    # =====================================================================

    def show_folder(self, path: str, groups: dict, unmatched: list[str]) -> None:
        """Texture folder: no versions, no chips; maps from the scan."""
        self._mode = "folder"
        self._source_path = path
        self._groups_by_version = {"": groups}
        self._geometry_materials = frozenset(groups)
        self._plans = [MaterialPlan(name=n, versions=[""], chosen="") for n in groups]
        self._unmatched_data = unmatched
        self._source_icon.setPixmap(_lucide_pixmap("folder", 18, TEXT_LABEL))
        self._source_name.setText(Path(path).name or path)
        self._source_meta.setText(f"Texture folder · {path}")
        self._source_meta.setToolTip(path)
        self._unmatched_btn.setText(f"{len(unmatched)} unmatched file(s)")
        self._unmatched_btn.setVisible(bool(unmatched))
        self._recursive_cb.setVisible(True)
        self._auto_assign_btn.setVisible(True)
        self._latest_btn.setVisible(False)
        self._banner.setVisible(False)
        self._fill_materials()
        self._pages.setCurrentIndex(1)

    def show_usd(
        self,
        asset: str,
        meta: str,
        kind: str,
        usd_path: str,
        plans: list[MaterialPlan],
        groups_by_version: dict[str, dict],
        geometry_materials: set[str],
    ) -> None:
        """Painter exports of one asset: a chip per material, maps of the chosen version."""
        self._mode = "usd"
        self._source_path = usd_path
        self._plans = plans
        self._groups_by_version = groups_by_version
        self._geometry_materials = frozenset(geometry_materials)
        self._unmatched_data = []
        self._source_icon.setPixmap(_lucide_pixmap(ASSET_ICONS.get(kind, "box"), 18, TEXT_LABEL))
        self._source_name.setText(asset)
        self._source_meta.setText(meta)
        self._source_meta.setToolTip(usd_path)
        self._unmatched_btn.setVisible(False)
        self._recursive_cb.setVisible(False)
        self._auto_assign_btn.setVisible(False)
        self._latest_btn.setVisible(True)
        self._banner.setVisible(False)
        self._fill_materials()
        self._pages.setCurrentIndex(1)

    def show_banner(self, text: str) -> None:
        self._banner_label.setText(text)
        self._banner.setVisible(True)

    def hide_banner(self) -> None:
        self._banner.setVisible(False)

    def is_recursive(self) -> bool:
        return self._recursive_cb.isChecked()

    def mode(self) -> str:
        return self._mode

    def source_path(self) -> str:
        return self._source_path

    def plans(self) -> list[MaterialPlan]:
        return self._plans

    def get_all_material_prefixes(self) -> list[str]:
        """Names of the materials left on, in list order."""
        return [p.name for p in self._plans if p.enabled]

    def group_for(self, plan: MaterialPlan):
        return self._groups_by_version.get(plan.chosen, {}).get(plan.name)

    # --- list ---

    def _chip_for(self, plan: MaterialPlan) -> tuple[str, str] | None:
        if self._mode != "usd":
            return None
        status = material_status(plan, self._geometry_materials)
        if status == STATUS_UPDATE:
            return f"{plan.scene}→{plan.chosen}", status
        if status == STATUS_NEW:
            return f"+{plan.chosen}", status
        return plan.chosen, status

    def _fill_materials(self) -> None:
        current = self._material_list.currentRow()
        self._material_list.blockSignals(True)
        self._material_list.clear()
        for plan in self._plans:
            item = QListWidgetItem(plan.name)
            item.setData(ROLE_NAME, plan.name)
            self._apply_item(item, plan)
            self._material_list.addItem(item)
        self._material_list.blockSignals(False)
        if self._plans:
            self._material_list.setCurrentRow(min(max(current, 0), len(self._plans) - 1))
            self._show_maps(self._material_list.currentRow())
        else:
            self._show_maps(-1)
        self._refresh_summary()

    def _apply_item(self, item: QListWidgetItem, plan: MaterialPlan) -> None:
        item.setData(ROLE_ENABLED, plan.enabled)
        chip = self._chip_for(plan)
        item.setData(ROLE_CHIP, chip)
        group = self.group_for(plan)
        if chip is None and group is not None:
            n = len(group.slots)
            udim = any(s.udim for s in group.slots.values())
            item.setData(ROLE_META, f"{n} map{'s' if n != 1 else ''}" + (" · UDIM" if udim else ""))
        item.setToolTip(CHIP_HELP.get(chip[1], "") if chip else "")

    def _refresh_rows(self) -> None:
        for i, plan in enumerate(self._plans):
            item = self._material_list.item(i)
            if item is not None:
                self._apply_item(item, plan)
        self._material_list.viewport().update()
        self._show_maps(self._material_list.currentRow())
        self._refresh_summary()

    def eventFilter(self, obj, event) -> bool:
        # Checkbox and chip are painted by the delegate: route their clicks here.
        if obj is self._material_list.viewport() and event.type() == QEvent.Type.MouseButtonRelease \
                and event.button() == Qt.MouseButton.LeftButton:
            index = self._material_list.indexAt(event.position().toPoint())
            if index.isValid():
                rect = self._material_list.visualRect(index)
                pos = event.position().toPoint()
                plan = self._plans[index.row()]
                if _MaterialDelegate.box_rect(rect).adjusted(-6, -6, 6, 6).contains(pos):
                    plan.enabled = not plan.enabled
                    self._refresh_rows()
                    return True
                chip = self._material_delegate.chip_rect(rect, index)
                if plan.enabled and chip.isValid() and chip.contains(pos):
                    self._version_menu(plan).exec(self._material_list.viewport().mapToGlobal(chip.bottomLeft()))
                    return True
        return super().eventFilter(obj, event)

    def _version_menu(self, plan: MaterialPlan) -> QMenu:
        menu = QMenu(self)
        menu.setStyleSheet(STYLE_MENU)
        for version in reversed(plan.versions):
            label = version + ("   · in scene" if version == plan.scene else "")
            if version == plan.versions[-1]:
                label += "   · latest"
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(version == plan.chosen)
            action.triggered.connect(lambda _c=False, v=version: self._choose(plan, v))
        menu.addSeparator()
        pin = menu.addAction(_lucide_icon("pin", 14, CHIP_TONES[STATUS_PINNED][0]),
                             "Unpin" if plan.pinned else f"Pin to {plan.chosen}")
        pin.triggered.connect(lambda: self._toggle_pin(plan))
        return menu

    def _material_menu(self, pos: QPoint) -> None:
        index = self._material_list.indexAt(pos)
        if not index.isValid():
            return
        plan = self._plans[index.row()]
        menu = QMenu(self)
        menu.setStyleSheet(STYLE_MENU)
        group = self.group_for(plan)
        folder = os.path.dirname(next(iter(group.slots.values())).filepath) if group and group.slots else ""
        open_action = menu.addAction(_lucide_icon("folder-open", 14), "Open textures folder")
        open_action.setEnabled(bool(folder))
        open_action.triggered.connect(lambda: open_in_explorer(folder))
        if self._mode == "usd":
            pin = menu.addAction(_lucide_icon("pin", 14, CHIP_TONES[STATUS_PINNED][0]),
                                 "Unpin" if plan.pinned else f"Pin to {plan.chosen}")
            pin.triggered.connect(lambda: self._toggle_pin(plan))
            versions = menu.addMenu("Pick version")
            versions.setStyleSheet(STYLE_MENU)
            for v in reversed(plan.versions):
                a = versions.addAction(v + ("   · in scene" if v == plan.scene else ""))
                a.setCheckable(True)
                a.setChecked(v == plan.chosen)
                a.triggered.connect(lambda _c=False, vv=v: self._choose(plan, vv))
        menu.addSeparator()
        toggle = menu.addAction("Leave out" if plan.enabled else "Bring back")
        toggle.triggered.connect(lambda: self._toggle_enabled(plan))
        menu.exec(self._material_list.viewport().mapToGlobal(pos))

    def _choose(self, plan: MaterialPlan, version: str) -> None:
        plan.chosen = version  # a pinned material keeps its pin, now on this version
        self._refresh_rows()

    def _toggle_pin(self, plan: MaterialPlan) -> None:
        plan.pinned = not plan.pinned
        self._refresh_rows()

    def _toggle_enabled(self, plan: MaterialPlan) -> None:
        plan.enabled = not plan.enabled
        self._refresh_rows()

    def _all_to_latest(self) -> None:
        to_latest(self._plans)
        self._refresh_rows()

    # --- maps ---

    def _show_maps(self, row: int) -> None:
        self._slot_table.setRowCount(0)
        self._maps_label.setText("MAPS")
        self._maps_note.setText("")
        if row < 0 or row >= len(self._plans):
            return
        plan = self._plans[row]
        group = self.group_for(plan)
        version = f"  ·  {plan.chosen}" if self._mode == "usd" else ""
        self._maps_label.setText(f"MAPS  ·  {plan.name}{version}")
        if self._mode == "usd" and plan.name not in self._geometry_materials:
            self._maps_note.setText(f"Not in the export the geometry comes from: the geometry may not match {plan.chosen}.")
        if group is None:
            return
        slots = sorted(group.slots.items())
        self._slot_table.setRowCount(len(slots))
        for i, (slot_name, slot_info) in enumerate(slots):
            self._slot_table.setItem(i, 0, QTableWidgetItem(_slot_label(slot_name)))
            path_item = QTableWidgetItem(_file_label(slot_info.filepath))
            path_item.setToolTip(slot_info.filepath.replace("%(UDIM)d", "<UDIM>"))
            path_item.setData(Qt.ItemDataRole.UserRole, slot_info.filepath)
            self._slot_table.setItem(i, 1, path_item)
            cs_item = QTableWidgetItem(slot_info.colorspace or "default")
            if not slot_info.colorspace:
                cs_item.setForeground(QColor(TEXT_META))
                cs_item.setToolTip("No colour space in the name: the map type's default is used")
            self._slot_table.setItem(i, 2, cs_item)

    def _map_menu(self, pos: QPoint) -> None:
        item = self._slot_table.item(self._slot_table.rowAt(pos.y()), 1)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole) or ""
        menu = QMenu(self)
        menu.setStyleSheet(STYLE_MENU)
        menu.addAction(_lucide_icon("folder-open", 14), "Show in folder").triggered.connect(
            lambda: open_in_explorer(path, select=True))
        menu.exec(self._slot_table.viewport().mapToGlobal(pos))

    def _open_source_folder(self) -> None:
        if self._source_path:
            open_in_explorer(self._source_path, select=os.path.isfile(self._source_path))

    # --- footer ---

    def _refresh_summary(self) -> None:
        if self._mode == "usd":
            s = plan_summary(self._plans)
            parts = [f"{s['new']} new"] if s["new"] else []
            parts += [f"{s['update']} update"] if s["update"] else []
            parts += [f"{s['unchanged']} unchanged"] if s["unchanged"] else []
            parts += [f"{s['left_out']} left out"] if s["left_out"] else []
            pinned = sum(1 for p in self._plans if p.enabled and p.pinned)
            parts += [f"{pinned} pinned"] if pinned else []
            self._summary_label.setText(" · ".join(parts))
            if s["new"] and s["update"]:
                text = f"Create {s['new']} and update {s['update']}"
            elif s["new"]:
                built = any(p.scene for p in self._plans)
                text = f"Create {s['new']} material{'s' if s['new'] != 1 else ''}" + ("" if built else " + geometry")
            elif s["update"]:
                text = f"Update {s['update']} material{'s' if s['update'] != 1 else ''}"
            elif s["save"]:
                text = "Save choices"
            else:
                text = "Nothing to change"
            self._create_btn.setText(text)
            self._create_btn.setEnabled(bool(s["new"] or s["update"] or s["save"]))
            self._legend.setText(self._legend_html())
            self._legend.setVisible(True)
        else:
            n = len(self.get_all_material_prefixes())
            total = len(self._plans)
            self._summary_label.setText(
                f"{total - n} left out · into a Material Library after the selected LOP node" if n < total
                else "Into a Material Library after the selected LOP node")
            self._create_btn.setText(f"Create {n} material{'s' if n != 1 else ''}")
            self._create_btn.setEnabled(n > 0)
            self._legend.setVisible(False)

    @staticmethod
    def _legend_html() -> str:
        parts = []
        for status, label in ((STATUS_OK, "up to date"), (STATUS_UPDATE, "will update"), (STATUS_NEW, "new"),
                              (STATUS_PINNED, "pinned"), (STATUS_MISSING, "not in geometry")):
            fg = CHIP_TONES[status][0]
            parts.append(f"<span style='color:{fg}'>●</span> <span style='color:{TEXT_META}'>{label}</span>")
        return "<span style='font-size:12px'>" + "&nbsp;&nbsp;&nbsp;".join(parts) + "</span>"

    # =====================================================================
    # Messages and loading
    # =====================================================================

    def set_message(self, text: str, error: bool = False, tooltip: str = "") -> None:
        self._message_label.setText(text)
        self._message_label.setToolTip(tooltip)
        self._message_label.setStyleSheet(f"color: {TEXT_ERROR if error else TEXT_LABEL}; font-size: 14px;")
        self._message_label.setVisible(bool(text))

    def message(self) -> str:
        return self._message_label.text()

    def show_loading(self, text: str = "Loading...") -> None:
        self._loading.set_text(text)
        self._loading.setGeometry(self.rect())
        self._loading.setVisible(True)
        self._loading.raise_()
        QApplication.processEvents()

    def show_done(self, text: str, sub_text: str | None = None) -> None:
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
        label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px;")
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
                font-size: 13px;
            }}
        """)
        layout.addWidget(log, stretch=1)
        ok_btn = QPushButton("OK")
        ok_btn.setMinimumWidth(80)
        ok_btn.clicked.connect(dlg.accept)
        layout.addWidget(ok_btn, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.setStyleSheet(f"QDialog {{ background: {BG_PANEL}; }}")
        dlg.exec()
