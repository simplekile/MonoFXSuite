"""
Auto Material Builder UI — one window, scene first.

Top bar: the asset and its latest publish, Follows selection, Open (texture folder, Painter USD, recent).
Sidebar: the Material Libraries in the scene, a ring each (how many materials are behind).
Main: what the opened source would do (headline), its versions on a timeline, its materials as tiles
with a texture thumbnail, and the maps of the selected tile. Action bar: result line, Undo, the button.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tools.fx.auto_material.logic import (
    DEFAULT_LIBRARY,
    STATUS_MISSING,
    STATUS_NEW,
    STATUS_OK,
    STATUS_PINNED,
    STATUS_UPDATE,
    MaterialPlan,
    folder_status,
    group_version,
    material_status,
    plan_summary,
    to_latest,
    version_number,
)

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
BG_APP = "#111113"        # window
BG_RAISED = "#18181d"     # tiles, pills, inputs
BG_HOVER = "#1f1f25"
BG_CURRENT = "#1c2333"    # the opened library in the sidebar
LINE = "#26262d"          # every border and divider
TEXT_PRIMARY = "#ededf0"
TEXT_LABEL = "#a3a3ae"    # every supporting text
TEXT_META = "#8e8e98"     # icons, placeholders, disabled only
TEXT_ERROR = "#fca5a5"
ACCENT = "#5b8cff"        # links, selection, the timeline
ACCENT_FILL = "#3d6cf0"   # the one primary button
ACCENT_LINE = "#2f4a80"

# Status colours: the same in chips, tile edges, rings and the legend
STATUS_COLORS: dict[str, str] = {
    STATUS_OK: "#3ecf8e",
    STATUS_UPDATE: ACCENT,
    STATUS_NEW: "#a78bfa",
    STATUS_PINNED: "#f5b14c",
    STATUS_MISSING: "#f87171",
}

# Type rules: every text takes one role, never a size picked by hand.
#   display  26px 600 TEXT_PRIMARY   the headline (what Create / Update will do)
#   title    19px 600 TEXT_PRIMARY   empty state
#   body     15px 400 TEXT_PRIMARY   buttons, the result line
#   name     14px 600 TEXT_PRIMARY   library, material and map names
#   meta     14px 400 TEXT_LABEL     second lines, hints, links, file names
#   small    13px 400/600            tile status, timeline labels, caps (600 + 1px spacing)
# Two weights (400, 600). Supporting text is TEXT_LABEL, never TEXT_META.
FS_DISPLAY, FS_TITLE, FS_BODY, FS_META, FS_SMALL = 26, 19, 15, 14, 13


def _text(role: str, color: str | None = None) -> str:
    """Style sheet for a label of *role* (display, title, body, name, meta, caps, small)."""
    size, weight, default = {
        "display": (FS_DISPLAY, 600, TEXT_PRIMARY),
        "title": (FS_TITLE, 600, TEXT_PRIMARY),
        "body": (FS_BODY, 400, TEXT_PRIMARY),
        "name": (FS_META, 600, TEXT_PRIMARY),  # 14px: names share meta's size, bold
        "meta": (FS_META, 400, TEXT_LABEL),
        "caps": (FS_SMALL, 600, TEXT_LABEL),
        "small": (FS_SMALL, 400, TEXT_LABEL),
    }[role]
    spacing = " letter-spacing: 1px;" if role == "caps" else ""
    return f"color: {color or default}; font-size: {size}px; font-weight: {weight};{spacing} background: transparent;"


def _font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Font in pixels: Houdini scales point sizes with its UI scale, which overflows painted text."""
    font = QFont("Inter")
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


def _rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


STYLE_WINDOW = f"""
    QWidget#AutoMaterialWindow {{ background-color: {BG_APP}; color: {TEXT_PRIMARY}; }}
    QLabel {{ color: {TEXT_PRIMARY}; background: transparent; }}
    QWidget#AutoMaterialWindow QWidget {{ font-size: {FS_META}px; }}
    QPushButton, QToolButton, QComboBox, QCheckBox, QLineEdit {{ font-size: {FS_META}px; }}
    QToolTip {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {LINE}; padding: 6px; }}
    QSplitter::handle {{ background: transparent; }}
    QScrollBar:vertical, QScrollBar:horizontal {{ background: transparent; border: none; margin: 2px; }}
    QScrollBar:vertical {{ width: 10px; }}
    QScrollBar:horizontal {{ height: 10px; }}
    QScrollBar::handle {{ background: #2c2c33; border-radius: 3px; min-height: 30px; min-width: 30px; }}
    QScrollBar::handle:hover {{ background: #3a3a44; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    QScrollBar::up-arrow, QScrollBar::down-arrow, QScrollBar::left-arrow, QScrollBar::right-arrow {{ image: none; }}
"""

STYLE_PRIMARY = f"""
    QPushButton {{
        background: {ACCENT_FILL}; color: #ffffff; border: none; border-radius: 10px;
        padding: 10px 20px; font-size: {FS_BODY}px; font-weight: 600;
    }}
    QPushButton:hover {{ background: #4b78f5; }}
    QPushButton:disabled {{ background: {BG_RAISED}; color: {TEXT_META}; }}
"""

STYLE_GHOST = f"""
    QPushButton, QToolButton {{
        background: transparent; color: {TEXT_LABEL}; border: 1px solid #33333b; border-radius: 10px;
        padding: 9px 14px; font-size: {FS_META}px;
    }}
    QPushButton:hover, QToolButton:hover {{ background: {BG_HOVER}; color: {TEXT_PRIMARY}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
"""

STYLE_PILL = f"""
    QPushButton, QToolButton {{
        background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid #2c2c33; border-radius: 13px;
        padding: 5px 12px; font-size: {FS_META}px; text-align: left;
    }}
    QPushButton:hover, QToolButton:hover {{ border-color: #3a3a44; background: {BG_HOVER}; }}
    QPushButton:checked {{ background: {_rgba(ACCENT, 0.16)}; border-color: {ACCENT_LINE}; color: {ACCENT}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
"""

STYLE_LINK = f"""
    QPushButton {{ background: transparent; border: none; color: {ACCENT}; padding: 0; font-size: {FS_META}px; }}
    QPushButton:hover {{ color: #8fb0ff; }}
"""

STYLE_LIST = f"""
    QListWidget {{ background: transparent; border: none; outline: none; color: {TEXT_PRIMARY}; }}
"""

STYLE_CHECKBOX = f"""
    QCheckBox {{ color: {TEXT_LABEL}; spacing: 8px; font-size: {FS_META}px; background: transparent; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 1px solid #4a4a55; background: transparent; }}
    QCheckBox::indicator:checked {{ background: {ACCENT_FILL}; border-color: {ACCENT}; }}
"""

STYLE_COMBO = f"""
    QComboBox {{
        padding: 6px 10px; border: 1px solid #2c2c33; border-radius: 8px; background: {BG_RAISED};
        color: {TEXT_PRIMARY}; font-size: {FS_META}px;
    }}
    QComboBox:focus {{ border: 1px solid {ACCENT}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox::down-arrow {{
        image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
        border-top: 5px solid {TEXT_LABEL}; margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {LINE};
        selection-background-color: {_rgba(ACCENT, 0.20)}; padding: 4px; outline: none;
    }}
"""

STYLE_MENU = f"""
    QMenu {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid #33333b; border-radius: 10px; padding: 4px; }}
    QMenu::item {{ padding: 7px 16px; border-radius: 6px; font-size: {FS_META}px; }}
    QMenu::item:selected {{ background: {_rgba(ACCENT, 0.20)}; }}
    QMenu::item:disabled {{ color: {TEXT_META}; }}
    QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}
"""


def _chip_style(status: str) -> str:
    color = STATUS_COLORS.get(status, TEXT_LABEL)
    return (f"color: {color}; background: {_rgba(color, 0.14)}; border: 1px solid {_rgba(color, 0.40)};"
            f" border-radius: 10px; padding: 2px 9px; font-size: {FS_SMALL}px; font-weight: 600;")


CHIP_HELP = {
    STATUS_OK: "Up to date",
    STATUS_UPDATE: "Create switches it to this version",
    STATUS_NEW: "Not in the scene yet",
    STATUS_PINNED: "Pinned: All to latest and later updates keep it here",
    STATUS_MISSING: "Not in the export the geometry comes from: the geometry may not match",
}

# ---------------------------------------------------------------------------
# Lucide icons
# ---------------------------------------------------------------------------
LUCIDE = {
    "rotate-cw": '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    "folder-open": '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "package": '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><path d="m3.3 7 7.703 4.734a2 2 0 0 0 1.994 0L20.7 7"/><path d="m7.5 4.27 9 5.15"/>',
    "file-box": '<path d="M14.5 22H18a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v4"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M3 13.1a2 2 0 0 0-1 1.76v3.24a2 2 0 0 0 .97 1.78L6 21.7a2 2 0 0 0 2.03.01L11 19.9a2 2 0 0 0 1-1.76V14.9a2 2 0 0 0-.97-1.78L8 11.3a2 2 0 0 0-2.03-.01Z"/><path d="M7 17v5"/><path d="M11.7 14.2 7 17l-4.7-2.8"/>',
    "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "box": '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    "building": '<rect width="16" height="20" x="4" y="2" rx="2" ry="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M12 6h.01"/><path d="M12 10h.01"/><path d="M12 14h.01"/><path d="M16 10h.01"/><path d="M16 14h.01"/><path d="M8 10h.01"/><path d="M8 14h.01"/>',
    "pin": '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "sparkles": '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "unlink": '<path d="m18.84 12.25 1.72-1.71h-.02a5.004 5.004 0 0 0-.12-7.07 5.006 5.006 0 0 0-6.95 0l-1.72 1.71"/><path d="m5.17 11.75-1.71 1.71a5.004 5.004 0 0 0 .12 7.07 5.006 5.006 0 0 0 6.95 0l1.71-1.71"/><path d="M8 2v3"/><path d="M2 8h3"/><path d="M16 22v-3"/><path d="M22 16h-3"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11"/>',
    "image": '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "triangle-alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
}

LUCIDE.update({
    "palette": '<circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>',
    "sliders": '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
    "mountain": '<path d="m8 3 4 8 5-5 5 15H2L8 3z"/>',
    "eye": '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    "droplet": '<path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z"/>',
    "layers": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "gem": '<path d="M6 3h12l4 6-10 13L2 9Z"/><path d="M11 3 8 9l4 13 4-13-3-6"/><path d="M2 9h20"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "circle-check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "circle-up": '<circle cx="12" cy="12" r="10"/><path d="m16 12-4-4-4 4"/><path d="M12 16V8"/>',
    "circle-plus": '<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/><path d="M12 8v8"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "library": '<path d="m16 6 4 14"/><path d="M12 6v14"/><path d="M8 8v12"/><path d="M4 4v16"/>',
    "save": '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/><path d="M7 3v4a1 1 0 0 0 1 1h7"/>',
})

ASSET_ICONS = {"character": "user", "prop": "box", "environment": "building"}

# Map icons, by what the slot does: colour, a value, the surface shape, see-through, light, skin, layers
_SLOT_ICON_WORDS = (
    (("emission",), "sun"),
    (("subsurface",), "droplet"),
    (("coat", "sheen"), "layers"),
    (("normal", "bump", "height", "displacement"), "mountain"),
    (("opacity", "transmission", "alpha"), "eye"),
    (("metal",), "gem"),
    (("color", "diffuse", "albedo"), "palette"),
)


def _slot_icon(slot: str) -> str:
    for words, icon in _SLOT_ICON_WORDS:
        if any(w in slot for w in words):
            return icon
    return "sliders"


# Houdini's own node icons, so a row looks like the node it stands for; Lucide outside Houdini
_NODE_ICONS = {  # kind -> (category, node type, fallback)
    "library": ("lop", "materiallibrary", "library"),
    "material": ("vop", "mtlxstandard_surface", "layers"),
    "image": ("vop", "mtlximage", "image"),
}
_node_icon_cache: dict[tuple[str, int], QPixmap] = {}


def _node_icon(kind: str, size: int = 16) -> QPixmap:
    key = (kind, size)
    if key not in _node_icon_cache:
        category, type_name, fallback = _NODE_ICONS[kind]
        pm = None
        try:
            import hou
            cat = hou.lopNodeTypeCategory() if category == "lop" else hou.vopNodeTypeCategory()
            node_type = hou.nodeType(cat, type_name)
            if node_type is not None:
                icon = hou.qt.Icon(node_type.icon(), size * 2, size * 2)
                pm = icon.pixmap(size * 2, size * 2)
                pm.setDevicePixelRatio(2.0)
                if pm.isNull():
                    pm = None
        except Exception:
            pm = None
        _node_icon_cache[key] = pm or _lucide_pixmap(fallback, size, TEXT_LABEL)
    return _node_icon_cache[key]


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


def _label(text: str, role: str, color: str | None = None) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(_text(role, color))
    return label


def _slot_label(slot: str) -> str:
    return slot.replace("_", " ")


def _file_label(filepath: str) -> str:
    return Path(filepath.replace("%(UDIM)d", "<UDIM>")).name


def _divider(vertical: bool = False) -> QFrame:
    line = QFrame()
    if vertical:
        line.setFixedWidth(1)
    else:
        line.setFixedHeight(1)
    line.setStyleSheet(f"background: {LINE};")
    return line


def open_in_explorer(path: str, select: bool = False) -> None:
    """Open a folder, or (select=True) the folder of a file with the file selected."""
    path = path.replace("%(UDIM)d", "1001").replace("<UDIM>", "1001")
    if select and sys.platform == "win32" and os.path.exists(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        return
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


# ---------------------------------------------------------------------------
# Path history (Recent) and preferences
# ---------------------------------------------------------------------------
_HISTORY_DIR = Path(os.environ.get("APPDATA", Path.home())) / "MonoFXSuite"
_HISTORY_FILE = _HISTORY_DIR / "auto_material_paths.json"
_PREFS_FILE = _HISTORY_DIR / "auto_material_prefs.json"
_MAX_HISTORY = 15


def _load_json(path: Path, kind: type) -> Any:
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, kind) else kind()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return kind()


def _save_json(path: Path, data: Any) -> None:
    try:
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    except OSError:
        pass


def _load_path_history() -> list[str]:
    return [str(p) for p in _load_json(_HISTORY_FILE, list)[:_MAX_HISTORY]]


def _load_prefs() -> dict:
    return _load_json(_PREFS_FILE, dict)


# ---------------------------------------------------------------------------
# Texture thumbnails (base colour map), loaded one at a time so the window never stalls
# ---------------------------------------------------------------------------
_QT_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".bmp", ".webp"}
_THUMB_W, _THUMB_H = 168, 84


def _first_tile(path: str) -> str | None:
    """An existing file for a texture path: the path itself, or the first UDIM tile of <UDIM> / %(UDIM)d."""
    path = path.replace("%(UDIM)d", "<UDIM>")
    if "<UDIM>" not in path:
        return path if os.path.isfile(path) else None
    tiles = sorted(glob.glob(glob.escape(path).replace(glob.escape("<UDIM>"), "[0-9][0-9][0-9][0-9]")))
    return tiles[0] if tiles else None


def _read_thumbnail(path: str) -> QPixmap | None:
    """A small picture of a texture; None when it cannot be read quickly (EXR without OpenImageIO)."""
    file = _first_tile(path)
    if file is None:
        return None
    ext = os.path.splitext(file)[1].lower()
    if ext in _QT_IMAGE_EXT:
        reader = QImageReader(file)
        size = reader.size()
        if size.isValid() and size.width() > 0:
            scale = max(_THUMB_W * 2 / size.width(), _THUMB_H * 2 / size.height())
            reader.setScaledSize(QSize(max(1, int(size.width() * scale)), max(1, int(size.height() * scale))))
        image = reader.read()
        return QPixmap.fromImage(image) if not image.isNull() else None
    if ext == ".exr":
        try:  # Houdini ships OpenImageIO in some builds; without it an EXR tile shows no picture
            import OpenImageIO as oiio
            from PySide6.QtGui import QImage

            buf = oiio.ImageBuf(file)
            spec = buf.spec()
            step = max(1, max(spec.width // (_THUMB_W * 2), spec.height // (_THUMB_H * 2)))
            small = oiio.ImageBufAlgo.resample(buf, roi=oiio.ROI(0, spec.width // step, 0, spec.height // step))
            pixels = small.get_pixels(oiio.FLOAT)
            h, w = pixels.shape[0], pixels.shape[1]
            image = QImage(w, h, QImage.Format.Format_RGB32)
            for y in range(h):
                for x in range(w):
                    r, g, b = (min(1.0, max(0.0, float(pixels[y, x, i]))) ** (1 / 2.2) for i in range(3))
                    image.setPixel(x, y, QColor(int(r * 255), int(g * 255), int(b * 255)).rgb())
            return QPixmap.fromImage(image)
        except Exception:
            return None
    return None


class _Thumbnails:
    """Cache of texture thumbnails; *request* queues a path, *on_ready* repaints when one is in."""

    def __init__(self, on_ready: Callable[[], None]) -> None:
        self._cache: dict[str, QPixmap | None] = {}
        self._queue: list[str] = []
        self._on_ready = on_ready
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._next)

    def get(self, path: str) -> QPixmap | None:
        if not path:
            return None
        if path not in self._cache:
            if path not in self._queue:
                self._queue.append(path)
                self._timer.start(0)
            return None
        return self._cache[path]

    def _next(self) -> None:
        if not self._queue:
            return
        path = self._queue.pop(0)
        try:
            self._cache[path] = _read_thumbnail(path)
        except Exception:
            self._cache[path] = None
        self._on_ready()
        if self._queue:
            self._timer.start(0)


# ---------------------------------------------------------------------------
# Sidebar: one row per Material Library in the scene, with its ring
# ---------------------------------------------------------------------------
ROLE_DATA = Qt.ItemDataRole.UserRole


def _paint_ring(painter: QPainter, rect: QRect, behind: int, total: int) -> None:
    """A ring: the share of materials up to date, green when all are, blue with the count behind."""
    pen_w = 3
    r = QRectF(rect).adjusted(pen_w, pen_w, -pen_w, -pen_w)
    painter.setPen(QPen(QColor("#2c2c33"), pen_w))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(r)
    share = 1.0 if total <= 0 else (total - behind) / total
    color = QColor(STATUS_COLORS[STATUS_UPDATE] if behind else STATUS_COLORS[STATUS_OK])
    pen = QPen(color, pen_w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    if share > 0:
        painter.drawArc(r, 90 * 16, -int(360 * 16 * share))
    painter.setPen(QColor(TEXT_PRIMARY))
    if behind:
        painter.setFont(_font(12, QFont.Weight.DemiBold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(behind))
    else:
        painter.drawPixmap(QRect(rect.center().x() - 6, rect.center().y() - 6, 12, 12),
                           _lucide_pixmap("check", 12, STATUS_COLORS[STATUS_OK]))


class _LibraryDelegate(QStyledItemDelegate):
    """[ring] name / "2 behind v010" ; current row tinted, scene-selected rows marked."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        data = index.data(ROLE_DATA) or {}
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(2, 2, -2, -2)
        hovered = bool(option.state & option.state.__class__.State_MouseOver)
        if data.get("current"):
            painter.setBrush(QColor(BG_CURRENT))
            painter.setPen(QColor(ACCENT_LINE))
        elif hovered:
            painter.setBrush(QColor(BG_HOVER))
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(rect), 10, 10)

        ring = QRect(rect.left() + 10, rect.center().y() - 16, 32, 32)
        _paint_ring(painter, ring, data.get("behind", 0), data.get("total", 0))

        x = ring.right() + 12
        painter.drawPixmap(QRect(x, rect.top() + 12, 16, 16), _node_icon("library", 16))
        x += 22
        width = rect.right() - x - 10
        painter.setFont(_font(FS_META, QFont.Weight.DemiBold))
        painter.setPen(QColor(TEXT_PRIMARY))
        name = painter.fontMetrics().elidedText(data.get("name", ""), Qt.TextElideMode.ElideMiddle, width)
        painter.drawText(QRect(x, rect.top() + 10, width, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        painter.setFont(_font(FS_SMALL))
        sub = data.get("sub", "")
        if data.get("selected"):
            painter.setPen(QColor(ACCENT))
            sub = "Selected in scene · " + sub
        else:
            painter.setPen(QColor(TEXT_LABEL))
        sub = painter.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, width + 22)
        painter.drawText(QRect(x - 22, rect.top() + 33, width + 22, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 64)


# ---------------------------------------------------------------------------
# Version timeline
# ---------------------------------------------------------------------------

class _Timeline(QWidget):
    """
    v006 · v007 · v008 · v010 on a line: the scene's version (white ring), the target (blue, glowing),
    the line filled up to the target. A click on a version picks it, when *pickable* allows.
    """

    def __init__(self, on_pick: Callable[[str], None]) -> None:
        super().__init__()
        self._versions: list[str] = []
        self._scene = ""
        self._target = ""
        self._latest = ""
        self._pickable: set[str] = set()
        self._on_pick = on_pick
        self.setFixedHeight(62)
        self.setMouseTracking(True)

    def set_state(self, versions: list[str], scene: str, target: str, pickable: set[str]) -> None:
        self._versions = sorted(set(versions), key=version_number)
        self._latest = self._versions[-1] if self._versions else ""
        self._scene, self._target, self._pickable = scene, target, pickable
        self.update()

    def _points(self) -> list[tuple[str, int]]:
        n = len(self._versions)
        if n == 0:
            return []
        left, right = 40, self.width() - 40
        if n == 1:
            return [(self._versions[0], left)]
        return [(v, int(left + (right - left) * i / (n - 1))) for i, v in enumerate(self._versions)]

    def paintEvent(self, event) -> None:
        points = self._points()
        if not points:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        y = 16
        painter.setPen(QPen(QColor("#2c2c33"), 2))
        painter.drawLine(points[0][1], y, points[-1][1], y)
        target_x = next((x for v, x in points if v == self._target), None)
        if target_x is not None:
            painter.setPen(QPen(QColor(ACCENT), 2))
            painter.drawLine(points[0][1], y, target_x, y)
        for v, x in points:
            done = target_x is not None and x <= target_x
            if v == self._target:
                painter.setPen(Qt.PenStyle.NoPen)
                glow = QColor(ACCENT)
                glow.setAlphaF(0.25)
                painter.setBrush(glow)
                painter.drawEllipse(QPoint(x, y), 11, 11)
            painter.setPen(QPen(QColor(TEXT_PRIMARY if v == self._scene else (ACCENT if done else "#3a3a44")), 2))
            painter.setBrush(QColor(ACCENT if done and v != self._scene else BG_APP))
            painter.drawEllipse(QPoint(x, y), 6, 6)
            label = v + ("  · scene" if v == self._scene else "") + ("  · latest" if v == self._latest and v != self._scene else "")
            painter.setFont(_font(FS_SMALL, QFont.Weight.DemiBold if v == self._target else QFont.Weight.Normal))
            painter.setPen(QColor(TEXT_PRIMARY if v == self._target else TEXT_LABEL))
            w = painter.fontMetrics().horizontalAdvance(label)
            lx = min(max(x - w // 2, 0), self.width() - w)
            painter.drawText(QRect(lx, y + 14, w, 18), Qt.AlignmentFlag.AlignCenter, label)
        painter.end()

    def _version_at(self, x: int) -> str | None:
        best = min(self._points(), key=lambda p: abs(p[1] - x), default=None)
        return best[0] if best is not None and abs(best[1] - x) < 30 else None

    def mouseMoveEvent(self, event) -> None:
        v = self._version_at(int(event.position().x()))
        self.setCursor(Qt.CursorShape.PointingHandCursor if v in self._pickable else Qt.CursorShape.ArrowCursor)
        if v and v not in self._pickable:
            self.setToolTip(f"{v} is what the scene has; a texture folder builds only its own version")
        elif v:
            self.setToolTip(f"Move the materials to {v}")
        else:
            self.setToolTip("")

    def mouseReleaseEvent(self, event) -> None:
        v = self._version_at(int(event.position().x()))
        if v and v in self._pickable:
            self._on_pick(v)


# ---------------------------------------------------------------------------
# Material tiles
# ---------------------------------------------------------------------------
ROLE_TILE = Qt.ItemDataRole.UserRole + 1
_TILE = QSize(196, 156)


class _TileDelegate(QStyledItemDelegate):
    """A tile: texture thumbnail, status edge, name, status line; a check to leave it out."""

    def __init__(self, thumbs: _Thumbnails, parent=None) -> None:
        super().__init__(parent)
        self._thumbs = thumbs

    @staticmethod
    def check_rect(rect: QRect) -> QRect:
        return QRect(rect.left() + 12, rect.top() + 12, 18, 18)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        t = index.data(ROLE_TILE) or {}
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(option.state & option.state.__class__.State_Selected)
        enabled = t.get("enabled", True)
        color = QColor(STATUS_COLORS.get(t.get("status"), TEXT_LABEL))

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 10, 10)
        painter.fillPath(path, QColor(BG_RAISED))
        painter.setClipPath(path)

        thumb_rect = QRect(rect.left(), rect.top(), rect.width(), 92)
        pm = self._thumbs.get(t.get("thumb", ""))
        if pm is not None and not pm.isNull():
            scaled = pm.scaled(thumb_rect.size() * 2, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
            src = QRect((scaled.width() - thumb_rect.width() * 2) // 2, (scaled.height() - thumb_rect.height() * 2) // 2,
                        thumb_rect.width() * 2, thumb_rect.height() * 2)
            painter.drawPixmap(thumb_rect, scaled, src)
        else:
            painter.fillRect(thumb_rect, QColor("#1f1f26"))
            painter.drawPixmap(QRect(thumb_rect.center().x() - 10, thumb_rect.center().y() - 10, 20, 20),
                               _lucide_pixmap("image", 20, "#3a3a44"))
        painter.fillRect(QRect(rect.left(), rect.top(), 3, rect.height()), color)
        painter.setClipping(False)

        # Leave-out check
        box = self.check_rect(rect)
        if enabled:
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
        painter.setBrush(QColor(ACCENT_FILL) if enabled else QColor(0, 0, 0, 120))
        painter.drawRoundedRect(QRectF(box), 5, 5)
        if enabled:
            painter.drawPixmap(box.adjusted(3, 3, -3, -3), _lucide_pixmap("check", 12, "#ffffff"))
        if t.get("pinned"):
            pin = QRect(rect.right() - 26, rect.top() + 10, 18, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 140))
            painter.drawEllipse(pin)
            painter.drawPixmap(pin.adjusted(3, 3, -3, -3), _lucide_pixmap("pin", 12, STATUS_COLORS[STATUS_PINNED]))

        text_left = rect.left() + 12
        text_w = rect.width() - 22
        painter.setFont(_font(FS_META, QFont.Weight.DemiBold))
        painter.setPen(QColor(TEXT_PRIMARY if enabled else TEXT_META))
        name = painter.fontMetrics().elidedText(t.get("name", ""), Qt.TextElideMode.ElideMiddle, text_w)
        painter.drawText(QRect(text_left, rect.top() + 99, text_w, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        painter.setFont(_font(FS_SMALL, QFont.Weight.DemiBold))
        painter.setPen(color if enabled else QColor(TEXT_META))
        painter.drawText(QRect(text_left, rect.top() + 121, text_w, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         t.get("label", "") if enabled else "Left out")

        border = QColor(ACCENT) if selected else QColor(LINE)
        painter.setPen(QPen(border, 1.5 if selected else 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        if not enabled:
            painter.fillPath(path, QColor(17, 17, 19, 120))
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        hint = index.data(Qt.ItemDataRole.SizeHintRole)
        return hint if isinstance(hint, QSize) and hint.isValid() else _TILE


ROLE_MAP = Qt.ItemDataRole.UserRole + 2


class _MapDelegate(QStyledItemDelegate):
    """A map row on two lines: map name and colour space, then the file name."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        m = index.data(ROLE_MAP) or {}
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(0, 2, 0, -2)
        selected = bool(option.state & option.state.__class__.State_Selected)
        hovered = bool(option.state & option.state.__class__.State_MouseOver)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG_CURRENT if selected else BG_HOVER))
            painter.drawRoundedRect(QRectF(rect), 8, 8)
        painter.drawPixmap(QRect(rect.left() + 12, rect.top() + 10, 18, 18),
                           _lucide_pixmap(_slot_icon(m.get("slot_key", "")), 18, ACCENT))
        inner = rect.adjusted(40, 0, -12, 0)
        painter.setFont(_font(FS_SMALL, QFont.Weight.DemiBold))
        cs = m.get("colorspace", "")
        cs_w = painter.fontMetrics().horizontalAdvance(cs) + 16
        cs_rect = QRect(inner.right() - cs_w, inner.top() + 8, cs_w, 20)
        painter.setPen(QColor(LINE))
        painter.setBrush(QColor(BG_RAISED))
        painter.drawRoundedRect(QRectF(cs_rect), 9, 9)
        painter.setPen(QColor(TEXT_LABEL if m.get("default_cs") else TEXT_PRIMARY))
        painter.drawText(cs_rect, Qt.AlignmentFlag.AlignCenter, cs)
        painter.setFont(_font(FS_META, QFont.Weight.DemiBold))
        painter.setPen(QColor(TEXT_PRIMARY))
        painter.drawText(QRect(inner.left(), inner.top() + 6, inner.width() - cs_w - 8, 24),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, m.get("slot", ""))
        painter.setFont(_font(FS_SMALL))
        painter.setPen(QColor(TEXT_LABEL))
        file = painter.fontMetrics().elidedText(m.get("file", ""), Qt.TextElideMode.ElideMiddle, inner.width())
        painter.drawText(QRect(inner.left(), inner.top() + 30, inner.width(), 20),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, file)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 58)


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------

class AutoMaterialUI(QWidget):

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("AutoMaterialWindow")
        self.setWindowTitle("Auto Material")
        self.setMinimumSize(900, 620)
        self.resize(1180, 800)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE_WINDOW)

        self._callbacks: dict[str, Callable[..., Any]] = {}
        self._mode = "empty"                   # "empty" | "folder" | "usd"
        self._plans: list[MaterialPlan] = []
        self._groups_by_version: dict[str, dict] = {}   # usd: version -> {name: MaterialGroup}
        self._geometry_materials: frozenset[str] = frozenset()
        self._unmatched_data: list[str] = []
        self._source_path = ""
        self._libraries: dict[str, dict[str, str]] = {}  # folder: library -> {material: version}
        self._library_why = "new"
        self._folder_versions: dict[str, str] = {}
        self._following = False
        self._extra_ticks: dict[str, QCheckBox] = {}
        self._assets: list[dict] = []
        self._current_key = ""
        self._scene_selection: list[str] = []
        self._path_history = _load_path_history()
        self._prefs = _load_prefs()
        self._recursive = bool(self._prefs.get("recursive", True))
        self._usd_meta = ""
        self._thumbs = _Thumbnails(lambda: self._tiles.viewport().update())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._top = self._build_top_bar()
        root.addWidget(self._top)
        root.addWidget(_divider())
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setHandleWidth(1)
        body.setStyleSheet(f"QSplitter::handle {{ background: {LINE}; }}")
        self._body = body
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_main())
        body.setStretchFactor(1, 1)
        body.setSizes([330, 850])
        root.addWidget(body, stretch=1)
        root.addWidget(_divider())
        root.addWidget(self._build_action_bar())

        self._refresh_main()

    # =====================================================================
    # Build
    # =====================================================================

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)
        self._asset_icon = QLabel()
        self._asset_icon.setPixmap(_lucide_pixmap("package", 18, ACCENT))
        lay.addWidget(self._asset_icon)
        self._asset_name = _label("Auto Material", "name")
        self._asset_name.setStyleSheet(_text("body") + " font-weight: 600;")
        lay.addWidget(self._asset_name)

        self._publish_pill = QPushButton("")
        self._publish_pill.setStyleSheet(STYLE_PILL)
        self._publish_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self._publish_pill.clicked.connect(self._on_publish_pill)
        lay.addWidget(self._publish_pill)
        self._banner_text = ""
        lay.addStretch(1)

        self._link_pill = QPushButton("")
        self._link_pill.setCheckable(True)
        self._link_pill.setStyleSheet(STYLE_PILL)
        self._link_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self._link_pill.setToolTip("While on, selecting Material Library nodes in /stage picks them here")
        self._link_pill.setChecked(self.linked())
        self._link_pill.toggled.connect(self._set_linked)
        lay.addWidget(self._link_pill)
        self._restyle_link()

        self._open_btn = QToolButton()
        self._open_btn.setText("  Open")
        self._open_btn.setIcon(_lucide_icon("plus", 14, TEXT_PRIMARY))
        self._open_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._open_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._open_btn.setStyleSheet(STYLE_PILL)
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_menu = QMenu(self)
        self._open_menu.setStyleSheet(STYLE_MENU)
        self._open_menu.aboutToShow.connect(self._fill_open_menu)
        self._open_btn.setMenu(self._open_menu)
        lay.addWidget(self._open_btn)
        return bar

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setMinimumWidth(260)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(10, 14, 10, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(6, 0, 4, 0)
        head.setSpacing(8)
        lib_icon = QLabel()
        lib_icon.setPixmap(_node_icon("library", 16))
        head.addWidget(lib_icon)
        head.addWidget(_label("IN THIS SCENE", "caps"))
        head.addStretch(1)
        self._update_assets_btn = QPushButton("")
        self._update_assets_btn.setStyleSheet(STYLE_LINK)
        self._update_assets_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_assets_btn.clicked.connect(lambda: self._fire("update_assets", self.ticked_assets()))
        head.addWidget(self._update_assets_btn)
        lay.addLayout(head)

        self._library_list = QListWidget()
        self._library_list.setStyleSheet(STYLE_LIST)
        self._library_list.setItemDelegate(_LibraryDelegate(self._library_list))
        self._library_list.setMouseTracking(True)
        self._library_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._library_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._library_list.itemClicked.connect(lambda item: self._fire("open_asset", item.data(ROLE_DATA)["key"]))
        lay.addWidget(self._library_list, stretch=1)
        self._library_empty = _label("Nothing built from a publish here yet.", "meta")
        self._library_empty.setWordWrap(True)
        self._library_empty.setContentsMargins(6, 0, 6, 0)
        lay.addWidget(self._library_empty)
        lay.addStretch(0)
        return side

    def _build_main(self) -> QWidget:
        self._main_stack = QStackedWidget()

        # Empty: nothing opened
        empty = QWidget()
        e_lay = QVBoxLayout(empty)
        e_lay.addStretch(1)
        icon = QLabel()
        icon.setPixmap(_lucide_pixmap("package", 40, "#3a3a44"))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e_lay.addWidget(icon)
        self._empty_title = _label("Drop a texture folder or a Painter .usd here", "title")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e_lay.addWidget(self._empty_title)
        self._empty_sub = _label("Or pick a library on the left, or Open › Texture folder / Painter USD.", "meta")
        self._empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e_lay.addWidget(self._empty_sub)
        e_lay.addStretch(2)
        self._main_stack.addWidget(empty)

        # Content
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(22, 18, 22, 8)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        # Page title: the library being looked at (the node it is, its name)
        lib_row = QHBoxLayout()
        lib_row.setSpacing(8)
        lib_icon = QLabel()
        lib_icon.setPixmap(_node_icon("library", 18))
        lib_row.addWidget(lib_icon)
        self._page_title = _label("", "title")
        self._page_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lib_row.addWidget(self._page_title, stretch=1)
        titles.addLayout(lib_row)
        titles.addSpacing(4)
        head_row = QHBoxLayout()
        head_row.setSpacing(10)
        self._head_icon = QLabel()
        head_row.addWidget(self._head_icon)
        self._headline = _label("", "display")
        head_row.addWidget(self._headline, stretch=1)
        titles.addLayout(head_row)
        self._subline = _label("", "meta")
        self._subline.setTextFormat(Qt.TextFormat.RichText)
        self._subline.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._subline.linkActivated.connect(self._on_subline_link)
        titles.addWidget(self._subline)
        head.addLayout(titles, stretch=1)
        self._unmatched_btn = QPushButton("")
        self._unmatched_btn.setStyleSheet(f"QPushButton {{ {_chip_style(STATUS_PINNED)} }}")
        self._unmatched_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._unmatched_btn.clicked.connect(self._on_unmatched_clicked)
        head.addWidget(self._unmatched_btn, alignment=Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)

        # Texture folder target: which library, changeable; other libraries holding the same materials
        self._target = QWidget()
        t_lay = QVBoxLayout(self._target)
        t_lay.setContentsMargins(0, 0, 0, 0)
        t_lay.setSpacing(6)
        t_row = QHBoxLayout()
        t_row.setSpacing(8)
        self._library_label = _label("Into", "meta")
        t_row.addWidget(self._library_label)
        self._library_combo = QComboBox()
        self._library_combo.setEditable(True)
        self._library_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._library_combo.setStyleSheet(STYLE_COMBO)
        self._library_combo.setMinimumWidth(300)
        self._library_combo.setToolTip("Material Library in /stage to create or update the materials in. "
                                       "Type a new name to make a new library.")
        self._library_combo.currentTextChanged.connect(lambda _t: self._on_library_changed())
        t_row.addWidget(self._library_combo)
        self._from_selection = QLabel("from selection")
        self._from_selection.setStyleSheet(_chip_style(STATUS_UPDATE))
        t_row.addWidget(self._from_selection)
        t_row.addStretch(1)
        t_lay.addLayout(t_row)
        self._dup_line = _label("", "meta")
        self._dup_line.setTextFormat(Qt.TextFormat.RichText)
        self._dup_line.linkActivated.connect(lambda _l: self._extra_box.setVisible(not self._extra_box.isVisible()))
        t_lay.addWidget(self._dup_line)
        self._extra_box = QWidget()
        self._extra_lay = QVBoxLayout(self._extra_box)
        self._extra_lay.setContentsMargins(0, 0, 0, 0)
        self._extra_lay.setSpacing(4)
        self._extra_box.setVisible(False)
        t_lay.addWidget(self._extra_box)
        self._target.setVisible(False)
        lay.addWidget(self._target)

        self._timeline = _Timeline(self._pick_version)
        lay.addWidget(self._timeline)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(16)
        split.setStyleSheet("QSplitter::handle { background: transparent; }")
        self._tiles = QListWidget()
        self._tiles.setViewMode(QListView.ViewMode.IconMode)
        self._tiles.setResizeMode(QListView.ResizeMode.Adjust)
        self._tiles.setMovement(QListView.Movement.Static)
        self._tiles.setUniformItemSizes(True)
        self._tiles.setGridSize(_TILE)
        self._tiles.setSpacing(0)
        self._tiles.setStyleSheet(STYLE_LIST)
        self._tiles.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tiles.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._tile_delegate = _TileDelegate(self._thumbs, self._tiles)
        self._tiles.setItemDelegate(self._tile_delegate)
        self._tiles.currentRowChanged.connect(self._show_maps)
        self._tiles.viewport().installEventFilter(self)
        self._tiles.installEventFilter(self)  # its own resize, not the viewport's (see _fit_tiles)
        self._tiles.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tiles.customContextMenuRequested.connect(self._material_menu)
        split.addWidget(self._tiles)

        # Maps of the selected tile: a full-height column, a row of two lines per map
        maps = QFrame()
        maps.setObjectName("MapsPanel")
        maps.setStyleSheet(f"QFrame#MapsPanel {{ background: {BG_RAISED}; border: 1px solid {LINE}; border-radius: 12px; }}")
        maps.setMinimumWidth(300)
        m_lay = QVBoxLayout(maps)
        m_lay.setContentsMargins(8, 12, 8, 10)
        m_lay.setSpacing(6)
        m_head = QHBoxLayout()
        m_head.setContentsMargins(12, 0, 12, 0)
        m_head.setSpacing(8)
        image_icon = QLabel()
        image_icon.setPixmap(_node_icon("image", 16))
        m_head.addWidget(image_icon)
        self._maps_label = _label("MAPS", "caps")
        m_head.addWidget(self._maps_label)
        m_head.addStretch(1)
        m_lay.addLayout(m_head)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(12, 0, 12, 4)
        title_row.setSpacing(8)
        material_icon = QLabel()
        material_icon.setPixmap(_node_icon("material", 16))
        title_row.addWidget(material_icon)
        self._maps_title = _label("", "name")
        title_row.addWidget(self._maps_title, stretch=1)
        m_lay.addLayout(title_row)
        self._map_list = QListWidget()
        self._map_list.setStyleSheet(STYLE_LIST)
        self._map_list.setItemDelegate(_MapDelegate(self._map_list))
        self._map_list.setMouseTracking(True)
        self._map_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._map_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._map_list.customContextMenuRequested.connect(self._map_menu)
        self._map_list.itemDoubleClicked.connect(
            lambda item: open_in_explorer(item.data(ROLE_MAP)["path"], select=True))
        m_lay.addWidget(self._map_list, stretch=1)
        self._maps_note = _label("", "meta", STATUS_COLORS[STATUS_MISSING])
        self._maps_note.setWordWrap(True)
        self._maps_note.setContentsMargins(12, 0, 12, 0)
        m_lay.addWidget(self._maps_note)
        self._legend = _label("", "small")
        self._legend.setTextFormat(Qt.TextFormat.RichText)
        self._legend.setWordWrap(True)
        self._legend.setContentsMargins(12, 4, 12, 0)
        m_lay.addWidget(self._legend)
        split.addWidget(maps)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([640, 340])
        lay.addWidget(split, stretch=1)

        self._main_stack.addWidget(content)
        return self._main_stack

    def _build_action_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background: #141418;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 12, 16, 12)
        lay.setSpacing(10)
        self._message_label = _label("", "meta")
        self._message_label.setWordWrap(True)
        self._message_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self._message_label, stretch=1)

        # Work in progress: a thin bar and what is being done, with Cancel; the window stays visible
        self._busy = QWidget()
        b_lay = QHBoxLayout(self._busy)
        b_lay.setContentsMargins(0, 0, 0, 0)
        b_lay.setSpacing(12)
        self._busy_bar = QProgressBar()
        self._busy_bar.setRange(0, 0)
        self._busy_bar.setTextVisible(False)
        self._busy_bar.setFixedSize(140, 4)
        self._busy_bar.setStyleSheet(f"QProgressBar {{ background: {LINE}; border: none; border-radius: 2px; }}"
                                     f" QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}")
        b_lay.addWidget(self._busy_bar)
        self._busy_text = _label("", "body")
        self._busy_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        b_lay.addWidget(self._busy_text, stretch=1)
        self._cancel_btn = QPushButton("  Cancel")
        self._cancel_btn.setIcon(_lucide_icon("x", 14, TEXT_LABEL))
        self._cancel_btn.setStyleSheet(STYLE_GHOST)
        self._cancel_btn.clicked.connect(self._on_cancel)
        b_lay.addWidget(self._cancel_btn)
        self._busy.setVisible(False)
        lay.addWidget(self._busy, stretch=1)
        self._cancelled = False
        self._is_busy = False
        self._undo_btn = QPushButton("  Undo")
        self._undo_btn.setIcon(_lucide_icon("undo", 14, TEXT_LABEL))
        self._undo_btn.setStyleSheet(STYLE_GHOST)
        self._undo_btn.setToolTip("Takes back the last Create / Update (one step, like Ctrl+Z)")
        self._undo_btn.clicked.connect(lambda: self._fire("undo"))
        self._undo_btn.setVisible(False)
        lay.addWidget(self._undo_btn)
        self._auto_assign_btn = QPushButton("  Auto assign")
        self._auto_assign_btn.setIcon(_lucide_icon("target", 14, TEXT_LABEL))
        self._auto_assign_btn.setStyleSheet(STYLE_GHOST)
        self._auto_assign_btn.setToolTip(
            "Match prims named *_grp / *_Grp with M_char_* under /materials and create Assign Material LOPs. "
            "Select a LOP node first.")
        self._auto_assign_btn.clicked.connect(lambda: self._fire("auto_assign"))
        lay.addWidget(self._auto_assign_btn)
        self._create_btn = QPushButton("Create")
        self._create_btn.setStyleSheet(STYLE_PRIMARY)
        self._create_btn.setMinimumWidth(200)
        self._create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_btn.clicked.connect(lambda: self._fire("create"))
        lay.addWidget(self._create_btn)
        return bar

    # =====================================================================
    # Callbacks (controller)
    # =====================================================================

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        """
        latest_publish(), open_path(path), open_asset(key), update_assets(keys), reload(),
        create(), auto_assign(), banner(), activated(), undo()
        """
        self._callbacks[event] = callback

    def _fire(self, event: str, *args) -> None:
        cb = self._callbacks.get(event)
        if cb is not None:
            cb(*args)

    # =====================================================================
    # Top bar
    # =====================================================================

    def _on_publish_pill(self) -> None:
        self._fire("banner" if self._banner_text else "latest_publish")

    def _restyle_publish_pill(self, latest: str | None, action: str) -> None:
        if self._banner_text:
            self._publish_pill.setText(f"  {self._banner_text}  ·  Open")
            self._publish_pill.setIcon(_lucide_icon("sparkles", 14, ACCENT))
            self._publish_pill.setToolTip("A newer export was published: open it to see what changes")
        elif latest:
            self._publish_pill.setText(f"  Latest publish  ·  {latest}")
            self._publish_pill.setIcon(_lucide_icon("package", 14, ACCENT))
            self._publish_pill.setToolTip(f"{action}\nOpens a review of it: nothing changes until you press the button.")
        else:
            self._publish_pill.setText("  No publish next to this .hip")
            self._publish_pill.setIcon(_lucide_icon("package", 14, TEXT_META))
            self._publish_pill.setToolTip("The publish is found from $HIP/../../../03_surfacing/02_texturing/publish")
        self._publish_pill.setEnabled(bool(latest or self._banner_text))

    def _fill_open_menu(self) -> None:
        menu = self._open_menu
        menu.clear()
        menu.addAction(_lucide_icon("folder", 14), "Texture folder…").triggered.connect(self._pick_folder)
        menu.addAction(_lucide_icon("file-box", 14), "Painter USD…").triggered.connect(self._pick_usd)
        if self._path_history:
            recent = menu.addMenu("Recent")
            recent.setStyleSheet(STYLE_MENU)
            for p in self._path_history:
                recent.addAction(p).triggered.connect(lambda _c=False, path=p: self._fire("open_path", path))
        menu.addSeparator()
        sub = menu.addAction("Include subfolders")
        sub.setCheckable(True)
        sub.setChecked(self._recursive)
        sub.toggled.connect(self._set_recursive)
        reload_action = menu.addAction(_lucide_icon("rotate-cw", 14), "Reload from disk")
        reload_action.setEnabled(self._mode != "empty")
        reload_action.triggered.connect(lambda: self._fire("reload"))
        show = menu.addAction(_lucide_icon("folder-open", 14), "Show source in Explorer")
        show.setEnabled(bool(self._source_path))
        show.triggered.connect(self._open_source_folder)

    def _set_recursive(self, on: bool) -> None:
        self._recursive = on
        self._prefs["recursive"] = on
        _save_json(_PREFS_FILE, self._prefs)
        if self._mode == "folder":
            self._fire("reload")

    def show_banner(self, text: str) -> None:
        self._banner_text = text
        self._restyle_publish_pill(self._latest_label, self._latest_action)

    def hide_banner(self) -> None:
        self._banner_text = ""
        self._restyle_publish_pill(self._latest_label, self._latest_action)

    # --- Follows selection ---

    def linked(self) -> bool:
        return bool(self._prefs.get("link_selection", True))

    def _restyle_link(self) -> None:
        on = self._link_pill.isChecked()
        self._link_pill.setText("  Follows selection" if on else "  Not linked")
        self._link_pill.setIcon(_lucide_icon("link" if on else "unlink", 14, ACCENT if on else TEXT_LABEL))

    def _set_linked(self, on: bool) -> None:
        self._prefs["link_selection"] = on
        _save_json(_PREFS_FILE, self._prefs)
        self._restyle_link()
        self._refresh_sidebar()
        if on and self._mode == "folder":
            self._follow_selection()

    def set_scene_selection(self, paths: list[str]) -> None:
        """Material Library node paths selected in /stage (the controller polls the selection)."""
        if paths == self._scene_selection:
            return
        self._scene_selection = list(paths)
        self._refresh_sidebar()
        if self._mode == "folder":
            self._follow_selection()

    # =====================================================================
    # Sidebar
    # =====================================================================

    def show_start(self, latest: str | None, assets: list[dict], action: str = "") -> None:
        """
        The scene's libraries in the sidebar, and the publish found from $HIP in the top bar.
        latest: "char_Helen · Painter USD v010 · from $HIP" or None; action: what building from it does.
        assets: dicts with key (library path), name, kind, meta, chip, status, tooltip, behind, total.
        """
        self._latest_label, self._latest_action = latest, action
        asset = (latest or "").split(" · ", 1)[0]
        if asset:
            self._asset_name.setText(asset)
        kinds = {a.get("kind") for a in assets}
        self._asset_icon.setPixmap(_lucide_pixmap(ASSET_ICONS.get(next(iter(kinds)) if len(kinds) == 1 else "", "package"), 18, ACCENT))
        self._restyle_publish_pill(latest, action)
        self._assets = assets
        self._refresh_sidebar()

    _latest_label: str | None = None
    _latest_action = ""

    def set_current(self, key: str) -> None:
        """The library opened in the main area (highlighted in the sidebar)."""
        self._current_key = key
        self._refresh_sidebar()

    def _selected_assets(self) -> list[dict]:
        return [a for a in self._assets if a["key"] in self._scene_selection] if self.linked() else []

    def ticked_assets(self) -> list[str]:
        """Libraries the sidebar's Update acts on: the ones selected in the scene, else every one behind."""
        chosen = self._selected_assets() or self._assets
        return [a["key"] for a in chosen if a.get("status") == STATUS_UPDATE]

    def _refresh_sidebar(self) -> None:
        self._library_list.clear()
        selected = {a["key"] for a in self._selected_assets()}
        for a in self._assets:
            item = QListWidgetItem()
            sub = a.get("chip", "")
            behind = a.get("behind", 1 if a.get("status") == STATUS_UPDATE else 0)
            if a.get("status") == STATUS_UPDATE:
                sub = f"{behind} behind · {sub}"
            else:
                sub = f"Up to date · {sub}"
            item.setData(ROLE_DATA, {
                "key": a["key"], "name": a.get("name", ""), "sub": sub, "behind": behind,
                "total": a.get("total", max(behind, 1)), "current": a["key"] == self._current_key,
                "selected": a["key"] in selected,
            })
            item.setToolTip(f"{a.get('meta', '')}\n{a.get('tooltip', '')}".strip())
            item.setSizeHint(QSize(0, 64))
            self._library_list.addItem(item)
        has = bool(self._assets)
        self._library_list.setVisible(has)
        self._library_empty.setVisible(not has)
        n = len(self.ticked_assets())
        if selected:
            text = f"Update {n} selected" if n else ""
        else:
            text = f"Update all ({n})" if n else ""
        self._update_assets_btn.setText(text)
        self._update_assets_btn.setVisible(bool(text))

    # =====================================================================
    # Main: a texture folder or a Painter export
    # =====================================================================

    def show_folder(
        self, path: str, groups: dict, unmatched: list[str], libraries: dict[str, dict[str, str]],
        library: str, why: str,
    ) -> None:
        """
        Texture folder: a tile per material against the chosen library (version there -> this folder's).
        *why*: how *library* was picked: "selection", "holds", "new" (logic.pick_library) or "fixed"
        (opened from its library in the sidebar).
        """
        self._mode = "folder"
        self._source_path = path
        self._groups_by_version = {"": groups}
        self._geometry_materials = frozenset(groups)
        self._plans = [MaterialPlan(name=n, versions=[""], chosen="") for n in groups]
        self._folder_versions = {n: group_version(g) for n, g in groups.items()}
        self._library_why = why
        self._fill_libraries(libraries, library)
        self._set_library_box(why == "selection")
        self._unmatched_data = unmatched
        self._extra_box.setVisible(False)
        self._fill_tiles()
        self._refresh_main()

    def show_usd(
        self,
        asset: str,
        meta: str,
        kind: str,
        usd_path: str,
        plans: list[MaterialPlan],
        groups_by_version: dict[str, dict],
        geometry_materials: set[str],
        library: str = "",
    ) -> None:
        """Painter exports of one asset: a tile per material, the versions on the timeline.
        *library*: the Material Library they go into (the page title)."""
        self._mode = "usd"
        self._usd_library = library
        self._source_path = usd_path
        self._plans = plans
        self._groups_by_version = groups_by_version
        self._geometry_materials = frozenset(geometry_materials)
        self._unmatched_data = []
        self._usd_meta = meta
        self._target.setVisible(False)
        self._asset_name.setText(asset)
        self._asset_icon.setPixmap(_lucide_pixmap(ASSET_ICONS.get(kind, "box"), 18, ACCENT))
        self._banner_text = ""
        self._restyle_publish_pill(self._latest_label, self._latest_action)
        self._fill_tiles()
        self._refresh_main()

    def is_recursive(self) -> bool:
        return self._recursive

    def mode(self) -> str:
        return self._mode

    def source_path(self) -> str:
        return self._source_path

    def plans(self) -> list[MaterialPlan]:
        return self._plans

    def get_all_material_prefixes(self) -> list[str]:
        """Names of the materials left on, in order."""
        return [p.name for p in self._plans if p.enabled]

    def group_for(self, plan: MaterialPlan):
        return self._groups_by_version.get(plan.chosen, {}).get(plan.name)

    # --- texture folder target ---

    def set_libraries(self, libraries: dict[str, dict[str, str]], library: str | None = None) -> None:
        """The scene's Material Libraries again (after a Create, or coming back), *library* chosen."""
        self._fill_libraries(libraries, library or self.library())
        self._refresh_tiles()

    def _fill_libraries(self, libraries: dict[str, dict[str, str]], library: str) -> None:
        self._libraries = libraries
        names = list(self._folder_versions)
        self._library_combo.blockSignals(True)
        self._library_combo.clear()
        for name, materials in libraries.items():
            n = sum(1 for m in names if m in materials)
            self._library_combo.addItem(f"{name}  ·  {n} here" if n else name, name)
        self._set_combo_library(library)
        self._library_combo.blockSignals(False)

    def _set_combo_library(self, library: str) -> None:
        idx = self._library_combo.findData(library)
        if idx >= 0:
            self._library_combo.setCurrentIndex(idx)
        else:
            self._library_combo.setEditText(library)

    def library(self) -> str:
        """Material Library chosen for a texture folder's Create (typed names too)."""
        idx = self._library_combo.currentIndex()
        text = self._library_combo.currentText().strip()
        if idx >= 0 and text == self._library_combo.itemText(idx).strip():
            return self._library_combo.itemData(idx) or text
        return text.split("  ·  ")[0].strip() or DEFAULT_LIBRARY

    def _set_library_box(self, box: bool) -> None:
        self._library_box = box
        self._target.setVisible(self._mode == "folder" and box)

    _library_box = False
    _usd_library = ""

    def _on_subline_link(self, link: str) -> None:
        if link == "change":
            self._library_why = "chosen"
            self._set_library_box(True)
            self._library_combo.setFocus()
            self._refresh_main()

    def _on_library_changed(self) -> None:
        if self._library_why == "selection" and not self._following:
            self._library_why = "chosen"
        self._refresh_tiles()

    def _follow_selection(self) -> None:
        """Linked, one Material Library selected in /stage: it becomes the target, with a flash."""
        if not self.linked():
            return
        names = [p.rsplit("/", 1)[-1] for p in self._scene_selection]
        if len(names) != 1 or names[0] not in self._libraries \
                or (names[0] == self.library() and self._library_why == "selection"):
            return
        self._following = True
        self._library_why = "selection"
        self._set_library_box(True)
        self._set_combo_library(names[0])
        self._following = False
        self._refresh_tiles()
        self._library_combo.setStyleSheet(STYLE_COMBO + f"QComboBox {{ border: 1px solid {STATUS_COLORS[STATUS_PINNED]}; }}")
        QTimer.singleShot(900, lambda: self._library_combo.setStyleSheet(STYLE_COMBO))

    def extra_libraries(self) -> list[str]:
        """Other libraries ticked to update too (their existing materials only)."""
        return [name for name, box in self._extra_ticks.items() if box.isChecked()]

    def folder_status_of(self, plan: MaterialPlan) -> str:
        """new / update / ok for a texture folder material against the chosen library."""
        scene = self._libraries.get(self.library(), {}).get(plan.name)
        return folder_status(scene, self._folder_versions.get(plan.name, ""))

    def _refresh_extra(self) -> None:
        lib = self.library()
        others = [name for name, mats in self._libraries.items()
                  if name != lib and any(m in mats for m in self._folder_versions)]
        old = {name: box.isChecked() for name, box in self._extra_ticks.items()}
        while self._extra_lay.count():
            w = self._extra_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self._extra_ticks = {}
        for name in others:
            mats = self._libraries[name]
            n = sum(1 for m in self._folder_versions
                    if m in mats and folder_status(mats[m], self._folder_versions[m]) == STATUS_UPDATE)
            box = QCheckBox(f"Update there too: {name}  ·  {n} to update" if n else f"{name}  ·  up to date")
            box.setStyleSheet(STYLE_CHECKBOX)
            box.setEnabled(n > 0)
            box.setChecked(old.get(name, False) and n > 0)
            box.toggled.connect(lambda _on: self._refresh_main())
            self._extra_lay.addWidget(box)
            self._extra_ticks[name] = box
        self._dup_line.setVisible(bool(others))
        self._dup_line.setText(
            f"<a href='dup' style='color:{ACCENT}; text-decoration:none'>Also used in {len(others)} other "
            f"librar{'ies' if len(others) != 1 else 'y'}</a>  · not changed unless ticked")
        self._target.setVisible(self._mode == "folder" and (self._library_box or bool(others)))
        for w in (self._library_label, self._library_combo):
            w.setVisible(self._library_box)
        self._from_selection.setVisible(self._library_box and self._library_why == "selection")

    # --- tiles ---

    def _status_of(self, plan: MaterialPlan) -> tuple[str, str]:
        """(status, label) of a tile."""
        if self._mode == "folder":
            version = self._folder_versions.get(plan.name, "")
            scene = self._libraries.get(self.library(), {}).get(plan.name)
            status = folder_status(scene, version)
            if status == STATUS_NEW:
                return status, f"+ {version} new" if version else "New"
            if status == STATUS_OK:
                return status, version or "Up to date"
            return status, f"{scene} → {version}" if scene and version else "Update"
        status = material_status(plan, self._geometry_materials)
        label = {
            STATUS_UPDATE: f"{plan.scene} → {plan.chosen}",
            STATUS_NEW: f"+ {plan.chosen} new",
            STATUS_PINNED: f"Pinned {plan.chosen}",
            STATUS_MISSING: f"{plan.chosen} · not in geometry",
        }.get(status, plan.chosen)
        return status, label

    def _tile_data(self, plan: MaterialPlan) -> dict:
        status, label = self._status_of(plan)
        group = self.group_for(plan)
        thumb = ""
        if group is not None:
            slot = group.slots.get("base_color") or next(iter(group.slots.values()), None)
            thumb = slot.filepath if slot is not None else ""
        return {"name": plan.name, "status": status, "label": label, "enabled": plan.enabled,
                "pinned": plan.pinned, "thumb": thumb}

    def _fill_tiles(self) -> None:
        current = self._tiles.currentRow()
        self._tiles.blockSignals(True)
        self._tiles.clear()
        for plan in self._plans:
            item = QListWidgetItem()
            item.setSizeHint(self._tiles.gridSize() if self._tiles.gridSize().isValid() else _TILE)
            item.setData(ROLE_TILE, self._tile_data(plan))
            self._tiles.addItem(item)
        self._tiles.blockSignals(False)
        if self._plans:
            self._tiles.setCurrentRow(min(max(current, 0), len(self._plans) - 1))
        self._show_maps(self._tiles.currentRow())

    def _refresh_tiles(self) -> None:
        for i, plan in enumerate(self._plans):
            item = self._tiles.item(i)
            if item is not None:
                item.setData(ROLE_TILE, self._tile_data(plan))
                item.setToolTip(self._tile_tip(plan))
        self._tiles.viewport().update()
        self._show_maps(self._tiles.currentRow())
        self._refresh_main()

    def _tile_tip(self, plan: MaterialPlan) -> str:
        status, _label = self._status_of(plan)
        if self._mode == "folder":
            lib = self.library()
            return {STATUS_UPDATE: f"Updates {plan.name} in {lib}",
                    STATUS_OK: f"Already at this version in {lib}: left as it is"}.get(
                status, f"Not in {lib} yet: Create makes it there")
        return CHIP_HELP.get(status, "")

    def _fit_tiles(self) -> None:
        """
        Tiles share the row's width: as many columns of at least _TILE as fit, none left empty.
        The width is the list's, less a scroll bar's whether one shows or not: from the viewport's,
        a scroll bar appearing would shrink the tiles, hide itself, grow them again, and so on.
        """
        bar = self._tiles.verticalScrollBar().sizeHint().width()
        width = self._tiles.width() - 2 * self._tiles.frameWidth() - bar - 4
        cols = max(1, width // _TILE.width())
        cell = QSize(width // cols, _TILE.height())
        if self._tiles.gridSize() == cell:
            return
        self._tiles.setGridSize(cell)
        for i in range(self._tiles.count()):
            self._tiles.item(i).setSizeHint(cell)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._tiles and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._fit_tiles)
        # The leave-out check is painted on the tile: route its clicks here; a double click toggles too.
        if obj is self._tiles.viewport() and event.type() in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick) \
                and event.button() == Qt.MouseButton.LeftButton:
            index = self._tiles.indexAt(event.position().toPoint())
            if index.isValid():
                rect = self._tiles.visualRect(index).adjusted(4, 4, -4, -4)
                inside = _TileDelegate.check_rect(rect).adjusted(-6, -6, 6, 6).contains(event.position().toPoint())
                if inside or event.type() == QEvent.Type.MouseButtonDblClick:
                    plan = self._plans[index.row()]
                    plan.enabled = not plan.enabled
                    self._refresh_tiles()
                    return True
        return super().eventFilter(obj, event)

    def _version_menu(self, plan: MaterialPlan, menu: QMenu) -> None:
        for version in reversed(plan.versions):
            label = version + ("   · in scene" if version == plan.scene else "")
            if version == plan.versions[-1]:
                label += "   · latest"
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(version == plan.chosen)
            action.triggered.connect(lambda _c=False, v=version: self._choose(plan, v))

    def _material_menu(self, pos: QPoint) -> None:
        index = self._tiles.indexAt(pos)
        if not index.isValid():
            return
        plan = self._plans[index.row()]
        menu = QMenu(self)
        menu.setStyleSheet(STYLE_MENU)
        if self._mode == "usd":
            versions = menu.addMenu("Version")
            versions.setStyleSheet(STYLE_MENU)
            self._version_menu(plan, versions)
            pin = menu.addAction(_lucide_icon("pin", 14, STATUS_COLORS[STATUS_PINNED]),
                                 "Unpin" if plan.pinned else f"Pin to {plan.chosen}")
            pin.triggered.connect(lambda: self._toggle_pin(plan))
            menu.addSeparator()
        toggle = menu.addAction("Leave out" if plan.enabled else "Bring back")
        toggle.triggered.connect(lambda: self._toggle_enabled(plan))
        group = self.group_for(plan)
        folder = os.path.dirname(next(iter(group.slots.values())).filepath) if group and group.slots else ""
        open_action = menu.addAction(_lucide_icon("folder-open", 14), "Open textures folder")
        open_action.setEnabled(bool(folder))
        open_action.triggered.connect(lambda: open_in_explorer(folder))
        menu.exec(self._tiles.viewport().mapToGlobal(pos))

    def _choose(self, plan: MaterialPlan, version: str) -> None:
        plan.chosen = version  # a pinned material keeps its pin, now on this version
        self._refresh_tiles()

    def _toggle_pin(self, plan: MaterialPlan) -> None:
        plan.pinned = not plan.pinned
        self._refresh_tiles()

    def _toggle_enabled(self, plan: MaterialPlan) -> None:
        plan.enabled = not plan.enabled
        self._refresh_tiles()

    # --- timeline ---

    def _timeline_state(self) -> tuple[list[str], str, str, set[str]]:
        """(versions, scene's oldest, target, pickable) of the opened source."""
        if self._mode == "usd":
            versions = sorted({v for p in self._plans for v in p.versions}, key=version_number)
            scene = min((p.scene for p in self._plans if p.scene), key=version_number, default="")
            chosen = [p.chosen for p in self._plans if p.enabled and not p.pinned]
            target = max(chosen, key=version_number) if chosen else (versions[-1] if versions else "")
            return versions + ([scene] if scene and scene not in versions else []), scene, target, set(versions)
        here = self._libraries.get(self.library(), {})
        scene_versions = {here[m] for m in self._folder_versions if here.get(m)}
        target = max((v for v in self._folder_versions.values() if v), key=version_number, default="")
        scene = min(scene_versions, key=version_number, default="")
        return sorted(scene_versions | ({target} if target else set()), key=version_number), scene, target, {target}

    def _pick_version(self, version: str) -> None:
        """The timeline: every material that is on and not pinned goes to *version* (or the nearest below)."""
        if self._mode != "usd":
            return
        if version == max((v for p in self._plans for v in p.versions), key=version_number, default=""):
            to_latest(self._plans)
        else:
            for p in self._plans:
                if not p.enabled or p.pinned:
                    continue
                below = [v for v in p.versions if version_number(v) <= version_number(version)]
                if below:
                    p.chosen = max(below, key=version_number)
        self._refresh_tiles()

    # --- headline, subline, button ---

    def _refresh_main(self) -> None:
        if self._mode == "empty":
            self.setWindowTitle("Auto Material")
            self._main_stack.setCurrentIndex(0)
            self._create_btn.setText("Create")
            self._create_btn.setEnabled(False)
            self._auto_assign_btn.setVisible(False)
            return
        self._main_stack.setCurrentIndex(1)
        if self._mode == "usd":
            lib = self._usd_library or "Material Library"
            title = lib
        else:
            lib = self.library()
            title = lib + ("" if lib in self._libraries else "   (new library)")
        self._page_title.setText(title)
        self.setWindowTitle(f"{lib} — Auto Material")
        versions, scene, target, pickable = self._timeline_state()
        self._timeline.set_state(versions, scene, target, pickable)
        self._timeline.setVisible(len(versions) > 1 or (len(versions) == 1 and self._mode == "usd"))
        self._auto_assign_btn.setVisible(self._mode == "folder")
        self._unmatched_btn.setText(f"{len(self._unmatched_data)} unmatched file(s)")
        self._unmatched_btn.setVisible(bool(self._unmatched_data))

        if self._mode == "usd":
            s = plan_summary(self._plans)
            new, update = s["new"], s["update"]
            if update and new:
                head = f"{update} to update · {new} new"
            elif update:
                head = f"{update} material{'s' if update != 1 else ''} behind {target}"
            elif new:
                head = f"{new} new material{'s' if new != 1 else ''} from {target}"
            else:
                head = f"Everything at {target}"
            self._subline.setText(self._usd_meta)
            if new and update:
                button = f"Create {new} and update {update}"
            elif new:
                built = any(p.scene for p in self._plans)
                button = f"Create {new} material{'s' if new != 1 else ''}" + ("" if built else " + geometry")
            elif update:
                button = f"Update {update} to {target}"
            elif s["save"]:
                button = "Save choices"
            else:
                button = ""
            self._legend.setText(self._legend_html())
        else:
            self._refresh_extra()
            on = [p for p in self._plans if p.enabled]
            statuses = [self.folder_status_of(p) for p in on]
            new, update, ok = (statuses.count(x) for x in (STATUS_NEW, STATUS_UPDATE, STATUS_OK))
            lib = self.library()
            if update and new:
                head = f"{update} to update · {new} new"
            elif update:
                head = f"{update} material{'s' if update != 1 else ''} behind {target or 'this folder'}"
            elif new:
                head = f"{new} new material{'s' if new != 1 else ''}"
            else:
                head = f"Everything at {target}" if target else "Nothing to change"
            exists = lib in self._libraries
            verb = "Updating in" if update or ok else ("Creating in" if exists else "Creating")
            new_lib = "" if exists else "  (new library)"
            change = "" if self._library_box else \
                f"  ·  <a href='change' style='color:{ACCENT}; text-decoration:none'>Change</a>"
            self._subline.setText(
                f"{verb} <b style='color:{TEXT_PRIMARY}'>{lib}</b>{new_lib}{change}"
                f"  ·  texture folder <span style='color:{TEXT_META}'>{self._source_path}</span>")
            if new and update:
                button = f"Create {new} and update {update}"
            elif update:
                button = f"Update {update} to {target}" if target else f"Update {update}"
            elif new:
                button = f"Create {new} material{'s' if new != 1 else ''}"
            else:
                button = ""
            extra = len(self.extra_libraries())
            if extra:
                more = f"{extra} more librar{'ies' if extra != 1 else 'y'}"
                button = f"{button} + {more}" if button else f"Update {more}"
            self._legend.setText(self._legend_html(folder=True))
        left_out = sum(1 for p in self._plans if not p.enabled)
        self._headline.setText(head + (f"  ·  {left_out} left out" if left_out else ""))
        if update:
            icon, tone = "circle-up", STATUS_COLORS[STATUS_UPDATE]
        elif new:
            icon, tone = "circle-plus", STATUS_COLORS[STATUS_NEW]
        else:
            icon, tone = "circle-check", STATUS_COLORS[STATUS_OK]
        self._head_icon.setPixmap(_lucide_pixmap(icon, 26, tone))
        self._create_btn.setText(("  " + button) if button else "Nothing to change")
        self._create_btn.setIcon(_lucide_icon(
            "refresh" if button.startswith("Update") else "save" if button.startswith("Save") else "plus", 16,
            "#ffffff") if button else QIcon())
        self._create_btn.setEnabled(bool(button))

    @staticmethod
    def _legend_html(folder: bool = False) -> str:
        tones = ((STATUS_OK, "up to date"), (STATUS_UPDATE, "will update"), (STATUS_NEW, "new"),
                 (STATUS_PINNED, "pinned"), (STATUS_MISSING, "not in geometry"))
        parts = [f"<span style='color:{STATUS_COLORS[s]}'>●</span> {label}" for s, label in (tones[:3] if folder else tones)]
        return "&nbsp;&nbsp; ".join(parts)

    # --- maps ---

    def _show_maps(self, row: int) -> None:
        self._map_list.clear()
        self._maps_title.setText("")
        self._maps_note.setText("")
        if row < 0 or row >= len(self._plans):
            return
        plan = self._plans[row]
        group = self.group_for(plan)
        version = plan.chosen if self._mode == "usd" else self._folder_versions.get(plan.name, "")
        self._maps_title.setText(plan.name + (f"  ·  {version}" if version else ""))
        if self._mode == "usd" and plan.name not in self._geometry_materials:
            self._maps_note.setText(f"Not in the export the geometry comes from: the geometry may not match {plan.chosen}.")
        if group is None:
            return
        for slot_name, slot_info in sorted(group.slots.items()):
            item = QListWidgetItem()
            item.setData(ROLE_MAP, {
                "slot": _slot_label(slot_name), "slot_key": slot_name, "file": _file_label(slot_info.filepath),
                "path": slot_info.filepath, "colorspace": slot_info.colorspace or "default",
                "default_cs": not slot_info.colorspace,
            })
            item.setToolTip(slot_info.filepath.replace("%(UDIM)d", "<UDIM>")
                            + ("" if slot_info.colorspace else "\nNo colour space in the name: the map type's default is used")
                            + "\nDouble click: show in Explorer")
            item.setSizeHint(QSize(0, 58))
            self._map_list.addItem(item)

    def _map_menu(self, pos: QPoint) -> None:
        item = self._map_list.itemAt(pos)
        if item is None:
            return
        path = item.data(ROLE_MAP)["path"]
        menu = QMenu(self)
        menu.setStyleSheet(STYLE_MENU)
        menu.addAction(_lucide_icon("folder-open", 14), "Show in folder").triggered.connect(
            lambda: open_in_explorer(path, select=True))
        menu.exec(self._map_list.viewport().mapToGlobal(pos))

    def _open_source_folder(self) -> None:
        if self._source_path:
            open_in_explorer(self._source_path, select=os.path.isfile(self._source_path))

    # =====================================================================
    # Opening sources
    # =====================================================================

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

    def save_to_history(self, path: str) -> None:
        path = path.strip()
        if not path:
            return
        if path in self._path_history:
            self._path_history.remove(path)
        self._path_history.insert(0, path)
        self._path_history = self._path_history[:_MAX_HISTORY]
        _save_json(_HISTORY_FILE, self._path_history)

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
    # Messages and loading
    # =====================================================================

    def set_message(self, text: str, error: bool = False, tooltip: str = "") -> None:
        self._message_label.setText(text)
        self._message_label.setToolTip(tooltip)
        self._message_label.setStyleSheet(_text("body", TEXT_ERROR if error else TEXT_LABEL))

    def message(self) -> str:
        return self._message_label.text()

    def show_undo(self, on: bool) -> None:
        self._undo_btn.setVisible(on)

    def show_loading(self, text: str = "Loading...") -> None:
        """Work in progress on the action bar; the rest of the window is greyed until it ends.
        A flag, not isVisible(): the first source is read before the window shows, when nothing is
        visible yet, and hide_loading would then never clear it."""
        if not self._is_busy:
            self._is_busy = True
            self._cancelled = False
            self._busy_bar.setRange(0, 0)
            self._cancel_btn.setEnabled(True)
            self._busy.setVisible(True)
            self._message_label.setVisible(False)
            for w in (self._top, self._body, self._undo_btn, self._auto_assign_btn, self._create_btn):
                w.setEnabled(False)
        self._busy_text.setText(text)
        QApplication.processEvents()

    def show_done(self, text: str, sub_text: str | None = None) -> None:
        """The run is over: the result is on the action bar (set_message)."""
        self.hide_loading()

    def hide_loading(self) -> None:
        if self._is_busy:
            self._is_busy = False
            self._busy.setVisible(False)
            self._message_label.setVisible(True)
            for w in (self._top, self._body, self._undo_btn, self._auto_assign_btn, self._create_btn):
                w.setEnabled(True)
            self._refresh_main()
        self._cancelled = False
        QApplication.processEvents()

    def _on_cancel(self) -> None:
        self._cancelled = True
        self._busy_text.setText("Cancelling… (what is done stays, one undo step)")
        self._cancel_btn.setEnabled(False)

    def is_cancelled(self) -> bool:
        QApplication.processEvents()
        return self._cancelled

    def _on_unmatched_clicked(self) -> None:
        """The files no material took, in a window that does not block Houdini."""
        if not self._unmatched_data:
            return
        log = QPlainTextEdit()
        log.setWindowTitle(f"{len(self._unmatched_data)} unmatched file(s)")
        log.setReadOnly(True)
        log.setPlainText("\n".join(self._unmatched_data))
        log.setStyleSheet(f"QPlainTextEdit {{ background: {BG_APP}; color: {TEXT_LABEL}; padding: 10px;"
                          f" font-size: {FS_META}px; border: none; }}")
        log.resize(620, 420)
        log.setParent(self, Qt.WindowType.Window)
        log.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        log.show()
