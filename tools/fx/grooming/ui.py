"""
MONO Grooming panel — one window, floating or docked in a Houdini pane.

Zones, each on its own surface with a line between them:
  top bar      the node, its asset, UI size (Aa), Dock; under it the view bar: what the viewport draws
               (Display, Color by, Deform, Isolate). Viewing never sits next to an action that writes.
  left         the layer tree (All locks › group › lock, Missing locks): swatch, name, status, packed /
               strands, eye (the two icons show on hover, on the selection, or when not the default);
               a filter, Confirm all while locks are new or to check; drag to reorder or regroup
  right (main) the selection: title, what the viewport does with it, its actions (Strands, Isolate,
               Hide, Flip root, Exclude), measured shape (cm), then one compact row per setting; with
               nothing selected, the whole groom and the keys
  action bar   loading, the result line (fades); Detect locks, Update regions; version, Publish (the one
               accent button) with its warning when locks are hidden or isolated
Below NARROW_PX wide (a docked panel) the tree sits above the settings and the bars wrap.

Names follow Houdini: Hair Generate's Thickness (and `width`) is one strand's, so the lock's measured
cross-section is "Lock width" / "Lock thickness"; Color (US spelling, as Houdini writes it).

Colour: one accent (Publish, the selection, a drop target, a toggle that is on); status colours only for status (unsure, new,
regions out of date, errors); everything else neutral. Size: every px goes through `Sz`, which is
Houdini's UI scale x the panel's own UI size (saved per user), so fonts and icons follow both.

The panel shows what the controller gives it and fires events back (`on(event, callback)`); it keeps no
data of its own. Palette and icons are Auto Material's (tools/fx/auto_material/ui.py).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionSlider,
    QStyleOptionViewItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tools.fx.auto_material.logic import STATUS_NEW, STATUS_PINNED
from tools.fx.auto_material.ui import (
    ACCENT,
    ACCENT_FILL,
    BG_APP,
    BG_HOVER,
    BG_RAISED,
    LINE,
    LUCIDE,
    STATUS_COLORS,
    TEXT_ERROR,
    TEXT_LABEL,
    TEXT_META,
    TEXT_PRIMARY,
    _lucide_icon,
    _lucide_pixmap,
    _rgba,
)
from tools.fx.grooming import config
from tools.fx.grooming.controller import (
    COLOR_BY_LABELS,
    DISPLAY_LABELS,
    DROP_ABOVE,
    DROP_BELOW,
    DROP_ON,
    ORPHANS_ROW,
    ALL_LOCKS,
    SEL_DEFAULTS,
    SEL_GROUP,
    SEL_LOCKS,
    SEL_NONE,
    SEL_ORPHAN,
)

LUCIDE.update({
    "eye-off": '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>',
    "scan-search": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="3"/><path d="m16 16-1.9-1.9"/>',
    "layout-grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
    "panel-right": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18"/>',
    "rotate-ccw": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    "git-merge": '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/>',
    "monitor": '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>',
    "waves": '<path d="M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/>',
    "focus": '<circle cx="12" cy="12" r="3"/><path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>',
    "type": '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" x2="15" y1="20" y2="20"/><line x1="12" x2="12" y1="4" y2="20"/>',
    "badge-check": '<path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/><path d="m9 12 2 2 4-4"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "play": '<polygon points="6 3 20 12 6 21 6 3"/>',
    "move-3d": '<path d="M5 3v16h16"/><path d="m5 19 6-6"/><path d="m2 6 3-3 3 3"/><path d="m18 16 3 3-3 3"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "flip-vertical": '<path d="M21 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v3"/><path d="M21 16v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3"/>'
                     '<path d="M4 12H2"/><path d="M10 12H8"/><path d="M16 12h-2"/><path d="M22 12h-2"/>',
    "circle-slash": '<circle cx="12" cy="12" r="10"/><line x1="9" x2="15" y1="15" y2="9"/>',
    "package": '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0'
               ' 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><polyline points="3.29 7 12 12 20.71 7"/>'
               '<path d="m7.5 4.27 9 5.15"/>',
    "triangle-alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
})
LUCIDE.setdefault("chevron-right", '<path d="m9 18 6-6-6-6"/>')
LUCIDE.setdefault("chevron-down", '<path d="m6 9 6 6 6-6"/>')
LUCIDE.setdefault("check", '<path d="M20 6 9 17l-5-5"/>')

# Surfaces: the settings (main work) on the window colour, tree and bars one step up, a clear line between
PANE = "#17171b"
SEPARATOR = "#2e2e36"
ROW_LINE = "#1d1d22"
SELECTED = "#273352"      # the accent at 24 % over PANE, opaque: Houdini paints the tree's own background
DIM = "#62626c"           # names of hidden rows: still readable, clearly off
FAINT = "#4a4a53"         # an eye decided by something else (a hidden group, isolate), not by this row
WARN = STATUS_COLORS[STATUS_PINNED]
STATUS_TEXT = {"unsure": WARN, "new": STATUS_COLORS[STATUS_NEW]}
STATUS_HELP = {
    "edited": "● has its own settings",
    "unsure": "check match: Detect locks matched it by position or shape only (Confirm all, or right click ›"
              " Confirm match)",
    "new": "new: Detect locks found this piece of the hair mesh for the first time",
}
STATUS_WORD = {"unsure": "check match", "new": "new"}   # the data says "unsure"
SOURCE_LABELS = {"group": "group", "defaults": "All locks", "builtin": "tool default", "mixed": "mixed"}
SHORT_DISPLAY = {"mesh": "Mesh", "guide": "Guides", "hair_preview": "Preview", "hair": "Hair"}

# Group colours offered in the swatch menu (no colour dialog: it would be modal)
SWATCHES: tuple[tuple[float, float, float], ...] = (
    (0.91, 0.45, 0.42), (0.95, 0.66, 0.30), (0.93, 0.83, 0.38), (0.55, 0.80, 0.45), (0.33, 0.78, 0.70),
    (0.38, 0.62, 0.95), (0.62, 0.52, 0.95), (0.88, 0.50, 0.80), (0.70, 0.70, 0.72), (0.55, 0.45, 0.38),
)

COL_NAME, COL_STATUS, COL_STRANDS, COL_EYE = range(4)
ROLE_ROW = Qt.ItemDataRole.UserRole + 1
ROLE_ICON = Qt.ItemDataRole.UserRole + 2    # the packed / strands and eye icons, painted by _IconDelegate
ROLE_QUIET = Qt.ItemDataRole.UserRole + 3   # True: the default state, drawn only on hover or selection
NARROW_PX = 760      # below this width (at size 1) the tree sits above the settings
MESSAGE_MS = 6000    # the result line fades after this; errors stay twice as long
FILTER_WORDS = {      # words the tree's filter knows besides names
    "new": lambda r: "new" in r.get("badges", []),
    "check": lambda r: "unsure" in r.get("badges", []),
    "edited": lambda r: "edited" in r.get("badges", []),
    "hidden": lambda r: not r.get("visible", True) or bool(r.get("hidden_by_group")),
    "excluded": lambda r: bool(r.get("excluded")),
    "flipped": lambda r: bool(r.get("root_flip")),
    "strands": lambda r: bool(r.get("strands")),
}
SLIDER_STEPS = 1000

# ---------------------------------------------------------------------------
# Size: Houdini's UI scale x the panel's own size
# ---------------------------------------------------------------------------
UI_SIZES: dict[str, float] = {"Small": 0.9, "Normal": 1.0, "Large": 1.15, "Larger": 1.3, "Largest": 1.5}
DEFAULT_UI_SIZE = "Normal"
PREFS_PATH = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "MonoFXSuite",
                          "grooming_prefs.json")

# Type roles, px at size 1. Bigger than Auto Material's (an artist sits in this panel for hours):
#   title  22/600 primary   the selection's name
#   name   16/600 primary   group rows, values set here, the node
#   body   16/400 primary   lock rows, setting names, buttons
#   meta   15/400 label     subtitle, the result line
#   small  14/400 label     units, where an inherited value comes from, measured labels
#   caps   13/600 label     section headers (+1px spacing)
TYPE: dict[str, tuple[int, int, str]] = {
    "title": (22, 600, TEXT_PRIMARY),
    "name": (16, 600, TEXT_PRIMARY),
    "body": (16, 400, TEXT_PRIMARY),
    "meta": (15, 400, TEXT_LABEL),
    "small": (14, 400, TEXT_LABEL),
    "caps": (13, 600, TEXT_LABEL),
}


def load_prefs() -> dict:
    try:
        with open(PREFS_PATH, encoding="utf-8") as f:
            prefs = json.load(f)
        return prefs if isinstance(prefs, dict) else {}
    except (OSError, ValueError):
        return {}


def save_prefs(prefs: dict) -> None:
    try:
        os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=1)
    except OSError:
        pass  # a read-only profile: the size just is not remembered


def houdini_scale() -> float:
    """Houdini's UI scale (Edit › Preferences › General › Scale), 1 outside Houdini. Fonts are set in
    pixels (Houdini would scale point sizes itself and overflow painted text), so the panel scales them."""
    try:
        import hou
        return max(0.5, min(3.0, hou.ui.scaledSize(1000) / 1000.0))
    except Exception:
        return 1.0


class Sz:
    """Every size of the panel: px at size 1 times Houdini's scale and the panel's UI size."""

    def __init__(self, scale: float = 1.0) -> None:
        self.scale = scale

    def px(self, n: float) -> int:
        return max(1, int(round(n * self.scale)))

    def font(self, role: str) -> QFont:
        size, weight, _color = TYPE[role]
        font = QFont("Inter")
        font.setPixelSize(self.px(size))
        font.setWeight(QFont.Weight.DemiBold if weight >= 600 else QFont.Weight.Normal)
        return font

    def text(self, role: str, color: str | None = None) -> str:
        size, weight, default = TYPE[role]
        spacing = " letter-spacing: 1px;" if role == "caps" else ""
        return (f"color: {color or default}; font-size: {self.px(size)}px; font-weight: {weight};{spacing}"
                f" background: transparent;")


def _image(name: str, size: int, color: str) -> str:
    """A Lucide icon as a PNG file (Qt style sheets take images by path), written once per size and colour."""
    import tempfile

    folder = os.path.join(tempfile.gettempdir(), "monofx_grooming_ui")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}_{size}_{color.strip('#')}.png").replace("\\", "/")
    if not os.path.isfile(path):
        _lucide_pixmap(name, size, color, 2.0).save(path)
    return path


def _sheet(z: Sz) -> str:
    """The one style sheet of the window: changing the UI size sets it again."""
    p = z.px
    t = {role: z.text(role) for role in TYPE}
    chevron = _image("chevron-down", p(14), TEXT_LABEL)
    check = _image("check", p(14), TEXT_PRIMARY)
    return f"""
    QWidget#GroomingWindow {{ background: {BG_APP}; color: {TEXT_PRIMARY}; }}
    QWidget#GroomingWindow QWidget {{ font-size: {p(16)}px; }}
    QWidget#TopBar, QWidget#ViewBar, QWidget#TreePane, QWidget#ActionBar {{ background: {PANE}; }}
    QWidget#PropsPane {{ background: {BG_APP}; }}
    QFrame[line="true"] {{ background: {SEPARATOR}; border: none; }}
    QLabel {{ color: {TEXT_PRIMARY}; background: transparent; }}
    QWidget#GroomingWindow QLabel[role="title"] {{ {t["title"]} }}
    QWidget#GroomingWindow QLabel[role="name"] {{ {t["name"]} }}
    QWidget#GroomingWindow QLabel[role="body"] {{ {t["body"]} }}
    QWidget#GroomingWindow QLabel[role="meta"] {{ {t["meta"]} }}
    QWidget#GroomingWindow QLabel[role="small"] {{ {t["small"]} }}
    QWidget#GroomingWindow QLabel[role="caps"] {{ {t["caps"]} }}
    QToolTip {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {LINE}; padding: {p(6)}px;
                font-size: {p(14)}px; }}
    QSplitter::handle {{ background: {SEPARATOR}; }}

    QPushButton, QToolButton {{
        background: transparent; color: {TEXT_PRIMARY}; border: 1px solid #34343c; border-radius: {p(7)}px;
        padding: {p(6)}px {p(12)}px; font-size: {p(16)}px;
    }}
    QPushButton:hover, QToolButton:hover {{ background: {BG_HOVER}; border-color: #44444e; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {TEXT_META}; border-color: {LINE}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
    QToolButton[flat="true"] {{ border: none; padding: {p(4)}px; border-radius: {p(5)}px; }}
    QToolButton[flat="true"]:checked {{ background: {_rgba(ACCENT, 0.22)}; }}
    QPushButton#Publish {{
        background: {ACCENT_FILL}; color: #ffffff; border: none; font-weight: 600;
        padding: {p(8)}px {p(20)}px;
    }}
    QPushButton#Publish:hover {{ background: #4b78f5; }}
    QPushButton#Publish[armed="true"] {{ background: #8a5a12; }}
    QPushButton[warn="true"] {{ border-color: {WARN}; color: {WARN}; }}
    QToolButton[toggle="true"] {{ padding: {p(5)}px {p(10)}px; font-size: {p(15)}px; }}
    QToolButton[toggle="true"]:checked {{ background: {_rgba(ACCENT, 0.18)}; border-color: {_rgba(ACCENT, 0.6)};
                                          color: {TEXT_PRIMARY}; }}

    QLineEdit {{
        padding: {p(4)}px {p(7)}px; border: 1px solid #2e2e36; border-radius: {p(6)}px; background: {BG_RAISED};
        color: {TEXT_PRIMARY}; font-size: {p(16)}px; selection-background-color: {_rgba(ACCENT, 0.4)};
    }}
    QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
    QLineEdit[inherited="true"] {{ color: {TEXT_LABEL}; }}
    QLineEdit[inherited="false"] {{ font-weight: 600; }}

    QComboBox {{
        padding: {p(5)}px {p(28)}px {p(5)}px {p(10)}px; border: 1px solid #34343c; border-radius: {p(7)}px;
        background: transparent; color: {TEXT_PRIMARY}; font-size: {p(16)}px;
    }}
    QComboBox:hover {{ background: {BG_HOVER}; }}
    QComboBox::drop-down {{ border: none; width: {p(24)}px; subcontrol-position: center right; }}
    QComboBox::down-arrow {{ image: url("{chevron}"); width: {p(14)}px; height: {p(14)}px; }}
    QComboBox QAbstractItemView {{
        background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {LINE}; outline: none;
        selection-background-color: {_rgba(ACCENT, 0.22)}; padding: {p(4)}px; font-size: {p(16)}px;
    }}

    QMenu {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid #34343c; padding: {p(4)}px; }}
    QMenu::item {{ padding: {p(7)}px {p(18)}px {p(7)}px {p(30)}px; font-size: {p(16)}px; }}
    QMenu::item:selected {{ background: {_rgba(ACCENT, 0.22)}; }}
    QMenu::item:disabled {{ color: {TEXT_META}; }}
    QMenu::icon {{ padding-left: {p(8)}px; }}
    QMenu::indicator {{ width: {p(14)}px; height: {p(14)}px; left: {p(9)}px; }}
    QMenu::indicator:checked {{ image: url("{check}"); }}
    QMenu::indicator:unchecked {{ image: none; }}
    QMenu::separator {{ height: 1px; background: {LINE}; margin: {p(4)}px {p(8)}px; }}

    QSlider {{ min-height: {p(22)}px; }}
    QSlider::groove:horizontal {{ height: {p(4)}px; background: #2c2c34; border-radius: {p(2)}px; }}
    QSlider::sub-page:horizontal {{ background: #6e6e7a; border-radius: {p(2)}px; }}
    QSlider::handle:horizontal {{ background: {TEXT_PRIMARY}; width: {p(14)}px; height: {p(14)}px;
                                  margin: -{p(5)}px 0; border-radius: {p(6)}px; }}
    QSlider::handle:horizontal:hover {{ background: #ffffff; }}
    QSlider[mixed="true"]::handle:horizontal {{ background: {TEXT_META}; }}
    QSlider[mixed="true"]::sub-page:horizontal {{ background: #2c2c34; }}

    QWidget[setting="true"] {{ border-bottom: 1px solid {ROW_LINE}; }}
    QWidget[setting="true"]:hover {{ background: #15151a; }}
    QWidget#Measured {{ background: {PANE}; border: 1px solid {LINE}; border-radius: {p(8)}px; }}
    QWidget#Banner {{ background: {BG_RAISED}; border: 1px solid #34343c; border-radius: {p(7)}px; }}

    QWidget#GroomingWindow QTreeWidget {{ background: {PANE}; border: none; outline: none; color: {TEXT_PRIMARY};
                   font-size: {p(16)}px; }}
    QWidget#GroomingWindow QTreeWidget {{ alternate-background-color: {PANE}; }}
    QTreeWidget::item {{ height: {p(36)}px; border: none; padding-left: {p(2)}px; background: {PANE}; }}
    QTreeWidget::item:hover {{ background: {BG_HOVER}; }}
    QTreeWidget::item:selected {{ background: {SELECTED}; color: {TEXT_PRIMARY}; }}
    QTreeWidget::branch {{ background: {PANE}; }}
    QTreeWidget::branch:hover {{ background: {BG_HOVER}; }}
    QTreeWidget::branch:selected {{ background: {SELECTED}; }}
    QTreeWidget::branch:has-children:closed {{ image: url("{_image("chevron-right", p(14), TEXT_LABEL)}"); }}
    QTreeWidget::branch:has-children:open {{ image: url("{_image("chevron-down", p(14), TEXT_LABEL)}"); }}

    QScrollArea {{ background: {BG_APP}; border: none; }}
    QScrollBar:vertical, QScrollBar:horizontal {{ background: transparent; border: none; margin: 2px; }}
    QScrollBar:vertical {{ width: {p(10)}px; }}
    QScrollBar:horizontal {{ height: {p(10)}px; }}
    QScrollBar::handle {{ background: #2e2e36; border-radius: {p(3)}px; min-height: 30px; min-width: 30px; }}
    QScrollBar::handle:hover {{ background: #3c3c46; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


def _label(text: str, role: str, color: str | None = None) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", role)
    if color:
        label.setStyleSheet(f"color: {color};")
    return label


def _line(vertical: bool = False) -> QFrame:
    line = QFrame()
    line.setProperty("line", True)
    if vertical:
        line.setFixedWidth(1)
    else:
        line.setFixedHeight(1)
    return line


def _fixed_icon(name: str, size: int, color: str) -> QIcon:
    """A Lucide icon that keeps its colour on a selected row (Qt would tint the Selected mode)."""
    icon = QIcon()
    for scale in (1.0, 2.0):
        pm = _lucide_pixmap(name, size, color, scale)
        icon.addPixmap(pm, QIcon.Mode.Normal)
        icon.addPixmap(pm, QIcon.Mode.Selected)
    return icon


def _swatch(color: tuple[float, float, float] | None, size: int, alpha: float = 1.0) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    if color is not None:
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        c = QColor.fromRgbF(*color)
        c.setAlphaF(alpha)
        p.setBrush(c)
        p.drawRoundedRect(QRect(3, 3, size * 2 - 6, size * 2 - 6), size * 0.45, size * 0.45)
        p.end()
    pm.setDevicePixelRatio(2.0)
    icon = QIcon(pm)
    icon.addPixmap(pm, QIcon.Mode.Selected)
    return icon


_hda_icon_cache: dict[int, QPixmap] = {}


def _hda_icon(size: int) -> QPixmap:
    """The MONO Grooming node's own icon in Houdini (hair generate when the HDA has none); Lucide outside."""
    if size not in _hda_icon_cache:
        pm = None
        try:
            import hou
            node_type = hou.nodeType(hou.sopNodeTypeCategory(), config.HDA_TYPE)
            name = node_type.icon() if node_type is not None else "SOP_hairgen"
            pm = hou.qt.Icon(name, size * 2, size * 2).pixmap(size * 2, size * 2)
            pm.setDevicePixelRatio(2.0)
            if pm.isNull():
                pm = None
        except Exception:
            pm = None
        _hda_icon_cache[size] = pm or _lucide_pixmap("layers", size, TEXT_LABEL)
    return _hda_icon_cache[size]


def _fmt(value: float) -> str:
    return f"{value:.3g}" if abs(value) < 1000 else f"{value:,.0f}"


# ---------------------------------------------------------------------------
# Widgets that never take the wheel: it scrolls the panel instead
# ---------------------------------------------------------------------------
def _left_button_down() -> bool:
    """The left mouse button as the system sees it, not as Qt last heard it: any window that pops up
    takes Qt's mouse grab, and Qt then never tells the slider about the moves or the release."""
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            vk = 0x02 if user32.GetSystemMetrics(23) else 0x01  # SM_SWAPBUTTON: left-handed mouse
            return bool(user32.GetAsyncKeyState(vk) & 0x8000)
        except Exception:
            pass
    return bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)


class _Slider(QSlider):
    """A slider that follows the mouse itself while dragged (a timer reads the cursor and the button), so
    a window popping up mid-drag does not end the drag. A press on the groove jumps there and drags."""

    FOLLOW_MS = 15

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # no focus from the wheel either
        self._grab = 0
        self._follow = QTimer(self)
        self._follow.timeout.connect(self._poll)
        self.button_down = _left_button_down  # tests swap these two
        self.cursor_x = lambda: self.mapFromGlobal(QCursor.pos()).x()

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()  # goes up to the scroll area

    def _rects(self):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()
        groove = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self)
        return groove, handle

    def _move_to(self, x: int) -> None:
        groove, handle = self._rects()
        span = max(groove.width() - handle.width(), 1)
        pos = min(max(x - self._grab - groove.x(), 0), span)
        self.setValue(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), pos, span))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        x = int(event.position().x())
        handle = self._rects()[1]
        self._grab = x - handle.x() if handle.contains(event.position().toPoint()) else handle.width() // 2
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.setSliderDown(True)
        self._move_to(x)
        self._follow.start(self.FOLLOW_MS)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self.isSliderDown():
            self._move_to(int(event.position().x()))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self.isSliderDown():
            self._move_to(int(event.position().x()))
            self._finish()
        event.accept()

    def _poll(self) -> None:
        if not self.isSliderDown():
            self._follow.stop()
        elif not self.button_down():
            self._finish()
        else:
            self._move_to(self.cursor_x())

    def _finish(self) -> None:
        self._follow.stop()
        if self.isSliderDown():
            self.setSliderDown(False)  # sliderReleased: the row writes the value once


class _Combo(QComboBox):
    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # shrinks with a narrow panel instead of holding it at its longest item's width
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------
class _StatusDelegate(QStyledItemDelegate):
    """Status column: ● edited (neutral), "unsure" / "new" in their status colours, the row's own display
    mode in grey. Plain text, no chips: they looked like buttons."""

    def __init__(self, tree: "_LayerTree") -> None:
        super().__init__(tree)
        self._tree = tree

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        row = index.siblingAtColumn(COL_NAME).data(ROLE_ROW) or {}
        z = self._tree.z
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(z.font("small"))
        metrics = painter.fontMetrics()
        x = option.rect.right() - z.px(6)
        cy = option.rect.center().y()
        dim = row.get("dimmed")
        parts: list[tuple[str, str]] = []
        for badge in ("new", "unsure"):
            if badge in row.get("badges", []):
                parts.append((STATUS_WORD[badge], STATUS_TEXT[badge]))
        if row.get("display"):
            parts.append((SHORT_DISPLAY.get(row["display"], row["display"]), TEXT_LABEL))
        if row.get("root_flip"):                 # per-lock choices: neutral words, not status colours
            parts.append(("root flipped", TEXT_LABEL))
        if row.get("excluded"):
            parts.append(("excluded", TEXT_LABEL))
        for text, color in parts:
            w = metrics.horizontalAdvance(text)
            c = QColor(color)
            if dim:
                c.setAlphaF(0.5)
            painter.setPen(c)
            painter.drawText(QRect(x - w, option.rect.top(), w, option.rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)
            x -= w + z.px(8)
        if "edited" in row.get("badges", []):
            r = z.px(3)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(DIM if dim else TEXT_LABEL))
            painter.drawEllipse(QPoint(x - r, cy), r, r)
        painter.restore()


class _WrapRow(QWidget):
    """Buttons on as many lines as the width needs (the selection's actions): it never makes the settings
    column wider than the panel, whatever the UI size."""

    def __init__(self, buttons: list[QWidget], spacing: int) -> None:
        super().__init__()
        self._buttons = buttons
        self._spacing = spacing
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(spacing)
        self._grid.setVerticalSpacing(spacing)
        self._cols = 0
        self._place(len(buttons))

    def _fit(self, width: int) -> int:
        cols, used = 0, 0
        for b in self._buttons:
            used += b.sizeHint().width() + (self._spacing if cols else 0)
            if used > width and cols:
                break
            cols += 1
        return max(1, cols)

    def _place(self, cols: int) -> None:
        if cols == self._cols:
            return
        for b in self._buttons:
            self._grid.removeWidget(b)
        for c in range(len(self._buttons) + 1):
            self._grid.setColumnStretch(c, 0)
        for n, b in enumerate(self._buttons):
            self._grid.addWidget(b, n // cols, n % cols)
        self._grid.setColumnStretch(cols, 1)
        self._cols = cols
        self.updateGeometry()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._place(self._fit(event.size().width()))
        super().resizeEvent(event)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        widest = max((b.sizeHint().width() for b in self._buttons), default=0)
        return QSize(widest, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSizeHint()


class _IconDelegate(QStyledItemDelegate):
    """The packed / strands and eye columns: an icon in its default state (packed, shown) is drawn only on
    the row under the mouse or a selected row, so 60 identical icons do not fill the tree; a state that
    is not the default (strands, hidden, isolated) always shows."""

    def __init__(self, tree: "_LayerTree") -> None:
        super().__init__(tree)
        self._tree = tree

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        icon = index.data(ROLE_ICON)
        if icon is None:
            return
        if index.data(ROLE_QUIET) and not (self._tree.is_hovered(index) or self._tree.is_selected(index)):
            return
        size = self._tree.iconSize()
        r = option.rect
        target = QRect(r.center().x() - size.width() // 2, r.center().y() - size.height() // 2,
                       size.width(), size.height())
        icon.paint(painter, target)


class _LayerTree(QTreeWidget):
    """The layer tree with drag and drop like Cinema 4D / Substance Painter: drag one or several locks
    between locks (reorder) or onto a group (move into it), drag a group between groups. The controller
    decides (`can_drop`) on every move, so a refused place shows a stop cursor and why; Qt never moves
    items itself: the drop goes to the controller (one undo step) and the tree is shown again."""

    def __init__(self, ui: "GroomingUI") -> None:
        super().__init__()
        self._ui = ui
        self.z = ui.z
        self._drop_rect: QRect | None = None
        self._drop_line = False
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)  # painted here, in the accent
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setMouseTracking(True)
        self._hover: tuple | None = None   # (parent row, row) under the mouse

    @staticmethod
    def _key(index) -> tuple:
        return (index.parent().row(), index.row())

    def is_hovered(self, index) -> bool:
        return self._hover == self._key(index)

    def is_selected(self, index) -> bool:
        return self.selectionModel().isSelected(index.siblingAtColumn(COL_NAME))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        index = self.indexAt(event.position().toPoint())
        key = self._key(index) if index.isValid() else None
        if key != self._hover:
            self._hover = key
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = None
        self.viewport().update()
        super().leaveEvent(event)

    def _dragged(self) -> list[tuple]:
        return [(r["kind"], r["id"]) for r in (it.data(COL_NAME, ROLE_ROW) for it in self.selectedItems())
                if r["kind"] in (SEL_LOCKS, SEL_GROUP)]

    def _place(self, pos: QPoint) -> tuple[Any, str, QRect | None]:
        """(target (kind, id) | None, above / below / on, the target row's rect)."""
        item = self.itemAt(pos)
        if item is None:
            return None, DROP_BELOW, None
        row = item.data(COL_NAME, ROLE_ROW)
        rect = self.visualItemRect(item)
        rect = QRect(0, rect.top(), self.viewport().width(), rect.height())
        y = (pos.y() - rect.top()) / max(rect.height(), 1)
        if row["kind"] == SEL_GROUP:
            dragging_group = any(k == SEL_GROUP for k, _i in self._dragged())
            if dragging_group:
                where = DROP_ABOVE if y < 0.5 else DROP_BELOW
            else:
                where = DROP_ABOVE if y < 0.2 else (DROP_BELOW if y > 0.8 and item.isExpanded() else DROP_ON)
        else:
            where = DROP_ABOVE if y < 0.5 else DROP_BELOW
        return (row["kind"], row["id"]), where, rect

    def _plan(self, event) -> tuple[Any, Any, str]:
        target, where, rect = self._place(event.position().toPoint())
        plan = self._ui._ask("can_drop", self._dragged(), target, where)
        self._drop_rect, self._drop_line = (rect, where != DROP_ON) if isinstance(plan, dict) else (None, False)
        if isinstance(plan, dict) and rect is not None and where == DROP_BELOW:
            self._drop_rect = QRect(rect.left(), rect.bottom() + 1, rect.width(), 0)
        elif isinstance(plan, dict) and rect is not None and where == DROP_ABOVE:
            self._drop_rect = QRect(rect.left(), rect.top(), rect.width(), 0)
        self.viewport().update()
        return plan, target, where

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """An eye or packed / strands click acts on the selection it is part of: handled here, before
        Qt's press replaces a multi-selection with the clicked row alone."""
        pos = event.position().toPoint()
        item = self.itemAt(pos)
        column = self.columnAt(pos.x())
        if item is not None and event.button() == Qt.MouseButton.LeftButton and column in (COL_EYE, COL_STRANDS):
            row = item.data(COL_NAME, ROLE_ROW)
            if row and row["kind"] in (SEL_GROUP, SEL_LOCKS):
                kind, ids = self._ui._targets(row)
                if column == COL_EYE:
                    self._ui._fire("set_visible", kind, ids, not row.get("visible", True))
                else:
                    self._ui._fire("set_strands_of", kind, ids, not row.get("strands", False))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        """Double-click a lock or group: strands / packed (the first click selected it). On the eye or the
        packed / strands icon it is a second click: it toggles back."""
        pos = event.position().toPoint()
        item = self.itemAt(pos)
        if item is None or event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        if self.columnAt(pos.x()) in (COL_EYE, COL_STRANDS):
            self.mousePressEvent(event)
            return
        row = item.data(COL_NAME, ROLE_ROW)
        if row and row["kind"] in (SEL_GROUP, SEL_LOCKS):
            self._ui._fire("strands")
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
            self._ui._fire("strands")
            event.accept()
            return
        super().keyPressEvent(event)

    def startDrag(self, actions) -> None:  # noqa: N802
        """The dragged rows fade in the tree, and the image under the cursor is see-through."""
        if not self._dragged():
            return
        from PySide6.QtGui import QDrag
        items = self.selectedItems()
        rects = [self.visualItemRect(it) for it in items]
        rects = [r for r in rects if r.isValid() and self.viewport().rect().intersects(r)]
        drag = QDrag(self)
        drag.setMimeData(self.model().mimeData(self.selectedIndexes()))
        if rects:
            box = rects[0]
            for r in rects[1:]:
                box = box.united(r)
            box = QRect(0, box.top(), self.viewport().width(), min(box.height(), self.z.px(36) * 6))
            shot = self.viewport().grab(box)
            faded = QPixmap(shot.size())
            faded.fill(Qt.GlobalColor.transparent)
            p = QPainter(faded)
            p.setOpacity(0.55)
            p.drawPixmap(0, 0, shot)
            p.end()
            drag.setPixmap(faded)
            drag.setHotSpot(self.viewport().mapFromGlobal(QCursor.pos()) - box.topLeft())
        self._dragging = True
        self.viewport().update()
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._dragging = False
            self.viewport().update()

    def drawRow(self, painter, option, index) -> None:  # noqa: N802
        if getattr(self, "_dragging", False) and self.selectionModel().isSelected(index):
            painter.save()
            painter.setOpacity(0.4)
            super().drawRow(painter, option, index)
            painter.restore()
        else:
            super().drawRow(painter, option, index)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        plan, _t, _w = self._plan(event)
        if isinstance(plan, dict):
            event.acceptProposedAction()
            self._ui._drop_hint("")
        else:
            event.ignore()
            self._ui._drop_hint("" if plan in (None, "Already there") else plan)
        # keep the tree scrolling near its edges while dragging
        y = event.position().toPoint().y()
        bar = self.verticalScrollBar()
        edge = self.z.px(24)
        if y < edge:
            bar.setValue(bar.value() - bar.singleStep())
        elif y > self.viewport().height() - edge:
            bar.setValue(bar.value() + bar.singleStep())

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._drop_rect = None
        self._ui._drop_hint("")
        self.viewport().update()

    def dropEvent(self, event) -> None:  # noqa: N802
        plan, target, where = self._plan(event)
        dragged = self._dragged()
        self._drop_rect = None
        self._ui._drop_hint("")
        self.viewport().update()
        event.setDropAction(Qt.DropAction.IgnoreAction)  # Qt removes nothing; the controller moves
        event.accept()
        # After the drag returns: the drop rebuilds the tree, which must not happen inside Qt's drag
        QTimer.singleShot(0, lambda: self._ui._fire("drop", dragged, target, where))

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._drop_rect is None:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(ACCENT), self.z.px(2))
        p.setPen(pen)
        r = self._drop_rect
        if self._drop_line:
            left = r.left() + self.indentation()
            p.drawLine(left, r.top(), r.right() - self.z.px(4), r.top())
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(QPoint(left, r.top()), self.z.px(3), self.z.px(3))
        else:
            p.setBrush(QColor(_rgba(ACCENT, 0.0)))
            fill = QColor(ACCENT)
            fill.setAlphaF(0.14)
            p.setBrush(fill)
            p.drawRoundedRect(r.adjusted(2, 1, -2, -1), self.z.px(5), self.z.px(5))
        p.end()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class _SettingRow(QWidget):
    """One setting on one line: name, slider, value, where an inherited value comes from, Reset (shown
    only when the value is set at this level). Fires *on_set(key, value)* once per change: a drag writes
    on release, so it is one undo step; while dragging, *on_preview(key, value)* at most every
    PREVIEW_MS so the viewport follows the slider (no undo step); *on_reset(key)*."""

    PREVIEW_MS = 120

    def __init__(self, s: dict, z: Sz, on_set: Callable[[str, float], None], on_reset: Callable[[str], None],
                 on_preview: Callable[[str, float], None] | None = None, compact: bool = False):
        super().__init__()
        self._on_preview = on_preview
        self._pending: float | None = None
        self._tick = QTimer(self)
        self._tick.setSingleShot(True)
        self._tick.timeout.connect(self._send_preview)
        self.setProperty("setting", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.key = s["key"]
        self._on_set = on_set
        # shown = stored x scale (twist: stored in radians, shown in degrees); the callbacks get stored units
        self._scale = float(s.get("scale", 1.0)) or 1.0
        self._lo, self._hi = (v * self._scale for v in s["range"])
        self._value = float(s["value"]) * self._scale
        self._mixed = bool(s.get("mixed"))
        own = bool(s["resettable"])
        lay = QHBoxLayout(self)
        lay.setContentsMargins(z.px(4), z.px(5), z.px(2), z.px(5))
        lay.setSpacing(z.px(6 if compact else 10))

        unit = f'&nbsp;<span style="color:{TEXT_META}; font-size:{z.px(13)}px;">{s["unit"]}</span>' \
            if s["unit"] else ""
        name = _label(f'{s["label"]}{unit}', "body")
        name.setTextFormat(Qt.TextFormat.RichText)
        name.setFixedWidth(z.px(108 if compact else 150))   # compact: a narrow docked panel
        if s.get("tip"):
            name.setToolTip(s["tip"])
        lay.addWidget(name)

        self.slider = _Slider()
        self.slider.setRange(0, SLIDER_STEPS)
        self.slider.setProperty("mixed", self._mixed)
        self.slider.setValue(self._to_steps(self._value))
        self.slider.setMinimumWidth(z.px(40 if compact else 80))
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.sliderReleased.connect(self._commit_slider)
        lay.addWidget(self.slider, stretch=1)

        self.field = QLineEdit()
        self.field.setFixedWidth(z.px(58 if compact else 70))
        self.field.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.field.setProperty("inherited", not own)
        self.field.setPlaceholderText("mixed")
        self.field.setText("" if self._mixed else _fmt(self._value))
        self.field.editingFinished.connect(self._on_field)
        lay.addWidget(self.field)

        source = s["source"]
        name_of = s.get("source_name") or SOURCE_LABELS.get(source, source)
        width = z.px(64 if compact else 92)
        shown = "" if own and source != "mixed" else name_of
        self.source = _label(QFontMetrics(z.font("small")).elidedText(shown, Qt.TextElideMode.ElideRight, width),
                             "small")
        self.source.setFixedWidth(width)
        self.source.setToolTip(("Inherited from " + name_of + ". " if shown and source != "mixed" else "")
                               + "Each value comes from the lock, else its group, else All locks, else the"
                               " tool's own default. A value set here shows bold, with Reset")
        lay.addWidget(self.source)

        # All locks / a group: do the levels below follow this value, or set their own?
        below = s.get("below")
        self.below = None
        if below is not None:
            own_below = below["groups"] + below["locks"]
            if own_below:
                text = f"↓{len(own_below)}" if compact else f"{len(own_below)} set own"
                parts = ([f"groups: {', '.join(below['groups'])}"] if below["groups"] else []) + \
                        ([f"locks: {', '.join(below['locks'][:12])}" + (" …" if len(below["locks"]) > 12 else "")]
                         if below["locks"] else [])
                tip = (f"{len(own_below)} below set their own value, so a change here does not reach them"
                       f" ({'; '.join(parts)}). Select them and Reset to follow again")
                color = WARN
            else:
                text = "" if compact else "all follow"
                tip = f"Every one of the {below['total']} below takes this value (none sets its own)"
                color = TEXT_LABEL
            self.below = _label(text, "small", color)
            self.below.setFixedWidth(z.px(26 if compact else 74))
            self.below.setToolTip(tip)
            lay.addWidget(self.below)

        self.reset = QToolButton()
        self.reset.setProperty("flat", True)
        self.reset.setIcon(_lucide_icon("rotate-ccw", z.px(15), TEXT_LABEL))
        self.reset.setIconSize(QSize(z.px(15), z.px(15)))
        self.reset.setToolTip("Reset: take the value from the level below again")
        self.reset.clicked.connect(lambda: on_reset(self.key))
        policy = self.reset.sizePolicy()
        policy.setRetainSizeWhenHidden(True)  # the columns stay lined up row to row
        self.reset.setSizePolicy(policy)
        lay.addWidget(self.reset)
        self.reset.setVisible(own)  # only once it has a parent: shown alone it is a window that flashes
        # up on every rebuild and takes the mouse from a slider being dragged

    def _to_steps(self, value: float) -> int:
        t = (value - self._lo) / (self._hi - self._lo) if self._hi > self._lo else 0.0
        return int(round(min(max(t, 0.0), 1.0) * SLIDER_STEPS))

    def _from_steps(self, steps: int) -> float:
        return self._lo + (self._hi - self._lo) * steps / SLIDER_STEPS

    def _on_slider(self, steps: int) -> None:
        self.field.setText(_fmt(self._from_steps(steps)))
        if not self.slider.isSliderDown():  # a click on the groove or a key: one change
            self._commit(self._from_steps(steps))
        elif self._on_preview is not None:  # dragging: the viewport follows, throttled
            self._pending = self._from_steps(steps)
            if not self._tick.isActive():
                self._tick.start(self.PREVIEW_MS)

    def _send_preview(self) -> None:
        if self._pending is not None and self.slider.isSliderDown() and self._on_preview is not None:
            value, self._pending = self._pending, None
            self._on_preview(self.key, round(value, 4) / self._scale)

    def _commit_slider(self) -> None:
        self._tick.stop()
        self._pending = None
        self._commit(self._from_steps(self.slider.value()))

    def _on_field(self) -> None:
        text = self.field.text().strip().replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            self.field.setText("" if self._mixed else _fmt(self._value))
            return
        self._commit(value)

    def _commit(self, value: float) -> None:
        value = round(float(value), 4)
        if abs(value - self._value) < 1e-9 and not self._mixed:
            return
        self._value = value
        self._mixed = False
        self._on_set(self.key, value / self._scale)


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------
class GroomingUI(QWidget):

    def __init__(self, parent: QWidget | None = None, docked: bool = False):
        super().__init__(parent)
        self.setObjectName("GroomingWindow")
        self.setWindowTitle(config.WINDOW_TITLE)
        self._docked = docked
        self._callbacks: dict[str, Callable[..., Any]] = {}
        self._filling = False
        self._rows: dict[tuple, QTreeWidgetItem] = {}
        self._tree_rows: list[dict] = []
        self._collapsed: set = set()     # rows the user closed (All locks opens unless closed)
        self._props: dict = {}
        self._timer: QTimer | None = None
        self._icons: list[tuple[Any, str, str, int]] = []  # (button, icon, colour, px at size 1)
        self._ui_size = load_prefs().get("ui_size", DEFAULT_UI_SIZE)
        if self._ui_size not in UI_SIZES:
            self._ui_size = DEFAULT_UI_SIZE
        self.z = Sz(houdini_scale() * UI_SIZES[self._ui_size])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._narrow = False
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(lambda: self._message_label.setText(""))
        root.addWidget(self._build_top_bar())
        root.addWidget(_line())
        root.addWidget(self._build_view_bar())
        root.addWidget(_line())
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setHandleWidth(1)
        body.setChildrenCollapsible(False)
        body.addWidget(self._build_tree())
        body.addWidget(self._build_properties())
        body.setStretchFactor(1, 1)
        self._body = body
        root.addWidget(body, stretch=1)
        root.addWidget(_line())
        root.addWidget(self._build_action_bar())

        isolate = QShortcut(QKeySequence("I"), self)
        isolate.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        isolate.activated.connect(lambda: self._fire("isolate"))
        leave = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        leave.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        leave.activated.connect(lambda: self._fire("escape"))
        # with the panel focused Houdini's own Ctrl+Z never runs: the panel asks Houdini to undo
        # (a focused text field keeps its own undo)
        for seq, event in (("Ctrl+Z", "undo"), ("Ctrl+Shift+Z", "redo"), ("Ctrl+Y", "redo")):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda e=event: self._fire(e))
        self._apply_size(refresh=False)

    # =====================================================================
    # Size
    # =====================================================================

    def _apply_size(self, refresh: bool = True) -> None:
        z = self.z
        self.setStyleSheet(_sheet(z))
        self.setMinimumSize(z.px(400), z.px(480))
        if not self._docked and not self.isVisible():
            self.resize(z.px(1100), z.px(800))
        for widget, name, color, size in self._icons:
            widget.setIcon(_lucide_icon(name, z.px(size), color))
            widget.setIconSize(QSize(z.px(size), z.px(size)))
        self._hda_label.setPixmap(_hda_icon(z.px(20)))
        self._tree.z = z
        self._tree.setIndentation(z.px(18))
        self._tree.setIconSize(QSize(z.px(14), z.px(14)))
        # Houdini's own style sheet paints item views in its grey: the tree's surface is set on the widget
        self._tree.setStyleSheet(f"QTreeWidget {{ background-color: {PANE}; }}")
        for widget in (self._tree, self._tree.viewport()):
            palette = widget.palette()
            for role in (palette.ColorRole.Base, palette.ColorRole.AlternateBase, palette.ColorRole.Window):
                palette.setColor(role, QColor(PANE))
            widget.setPalette(palette)
            widget.setAutoFillBackground(True)
        self._tree.setAlternatingRowColors(False)
        self._tree.viewport().setStyleSheet(f"background-color: {PANE};")
        header = self._tree.header()
        for col, width in ((COL_STATUS, 92), (COL_STRANDS, 30), (COL_EYE, 36)):
            header.resizeSection(col, z.px(width))
        self._version_edit.setFixedWidth(z.px(84))
        self._filter.setMinimumWidth(z.px(120))
        self._narrow = None   # lay out again for this size
        self._apply_layout()
        if refresh:
            self._fire("refresh")

    def set_ui_size(self, name: str) -> None:
        """The panel's own UI size (on top of Houdini's scale), saved for this user."""
        if name not in UI_SIZES:
            return
        self._ui_size = name
        prefs = load_prefs()
        prefs["ui_size"] = name
        save_prefs(prefs)
        self.z = Sz(houdini_scale() * UI_SIZES[name])
        self._apply_size()
        self._size_btn.setToolTip(f"UI size: {name} (on top of Houdini's own scale, saved for you)")

    def _icon(self, widget, name: str, color: str = TEXT_LABEL, size: int = 16):
        self._icons.append((widget, name, color, size))
        widget.setIcon(_lucide_icon(name, self.z.px(size), color))
        return widget

    def _recolor_icon(self, widget, color: str) -> None:
        """A registered icon in another colour, kept when the UI size changes."""
        for i, (w, name, _c, size) in enumerate(self._icons):
            if w is widget:
                self._icons[i] = (w, name, color, size)
                widget.setIcon(_lucide_icon(name, self.z.px(size), color))

    # =====================================================================
    # Build
    # =====================================================================

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 12, 8)
        lay.setSpacing(10)
        self._hda_label = QLabel()
        lay.addWidget(self._hda_label)
        self._node_label = _label("No node", "name")
        self._node_label.setMinimumWidth(1)
        self._node_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self._node_label, stretch=1)
        self._asset_label = _label("", "meta")
        self._asset_label.setToolTip("Asset mode: the groom of the asset, published to 04_grooming")
        lay.addWidget(self._asset_label)
        self._size_btn = QToolButton()
        self._size_btn.setProperty("flat", True)
        self._size_btn.setToolTip(f"UI size: {self._ui_size} (on top of Houdini's own scale, saved for you)")
        self._size_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._icon(self._size_btn, "type")
        menu = QMenu(self._size_btn)
        for name in UI_SIZES:
            act = menu.addAction(name)
            act.setCheckable(True)
            act.triggered.connect(lambda _c=False, n=name: self.set_ui_size(n))
        menu.aboutToShow.connect(lambda: [a.setChecked(a.text() == self._ui_size) for a in menu.actions()])
        self._size_btn.setMenu(menu)
        lay.addWidget(self._size_btn)
        self._dock_btn = QPushButton("  Dock")
        self._icon(self._dock_btn, "panel-right")
        self._dock_btn.setToolTip("Put the panel in a Houdini pane tab (drag the tab out to float it again)")
        self._dock_btn.clicked.connect(lambda: self._fire("dock"))
        self._dock_btn.setVisible(not self._docked)
        lay.addWidget(self._dock_btn)
        self._node_path = ""
        return bar

    def _build_view_bar(self) -> QWidget:
        """What the viewport draws: changes nothing in the groom, so it sits apart from Detect / Publish."""
        bar = QWidget()
        bar.setObjectName("ViewBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._view_lay = QBoxLayout(QBoxLayout.Direction.LeftToRight, bar)
        self._view_lay.setContentsMargins(14, 6, 12, 6)
        self._view_lay.setSpacing(6)
        shown = QHBoxLayout()
        shown.setSpacing(8)
        self._display_combo = _Combo()
        for mode in config.DISPLAY_MODES:
            text = DISPLAY_LABELS[mode]
            if mode == "hair_preview":
                text = f"{text} ({int(config.PREVIEW_FRACTION * 100)}%)"
            self._display_combo.addItem(text, mode)
        self._display_combo.setToolTip(
            f"Display of every lock without its own (right click a row › Display). Hair preview:"
            f" {int(config.PREVIEW_FRACTION * 100)}% of the strands, at most {config.PREVIEW_MAX_STRANDS:,}")
        self._display_combo.currentIndexChanged.connect(
            lambda _i: None if self._filling else self._fire("set_display", self._display_combo.currentData(), None))
        shown.addWidget(self._display_combo)
        self._color_combo = _Combo()
        for key, text in COLOR_BY_LABELS.items():
            self._color_combo.addItem(f"Color by {text.lower()}", key)
        self._color_combo.setToolTip("Viewport color of each lock: its own, or its group's")
        self._color_combo.currentIndexChanged.connect(
            lambda _i: None if self._filling else self._fire("set_display", None, self._color_combo.currentData()))
        shown.addWidget(self._color_combo)
        toggles = QHBoxLayout()
        toggles.setSpacing(4)
        self._deform_btn = QToolButton()
        self._deform_btn.setProperty("flat", True)
        self._deform_btn.setCheckable(True)
        self._deform_btn.setText("  Deform")
        self._deform_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._icon(self._deform_btn, "move-3d", TEXT_LABEL, 16)
        self._deform_btn.setToolTip("Deform by the animated hair mesh wired into input 3 (Point Deform), as in"
                                    " the shot. Off while grooming: every edit would deform 4 M points (~1 s), every"
                                    " lock is drawn as strands and the others only dim")
        self._deform_btn.clicked.connect(lambda on: self._fire("set_shot_deform", on))
        self._deform_btn.setVisible(False)
        toggles.addWidget(self._deform_btn)
        self._isolate_btn = QToolButton()
        self._isolate_btn.setProperty("flat", True)
        self._isolate_btn.setCheckable(True)
        self._isolate_btn.setText("  Isolate")
        self._isolate_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._isolate_btn.setToolTip("Isolate: show the selected locks or group alone (I). I on other locks"
                                     " isolates them instead; Esc or I again shows everything. Eyes stay as they are")
        self._icon(self._isolate_btn, "focus", TEXT_LABEL, 16)
        self._isolate_btn.clicked.connect(lambda: self._fire("isolate"))
        toggles.addWidget(self._isolate_btn)
        toggles.addStretch(1)
        self._view_groups = (shown, toggles)
        self._view_lay.addLayout(shown)
        self._view_lay.addSpacing(10)
        self._view_lay.addLayout(toggles)
        self._view_lay.addStretch(1)
        return bar

    def _build_tree(self) -> QWidget:
        side = QWidget()
        side.setObjectName("TreePane")
        side.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._tree_pane = side
        lay = QVBoxLayout(side)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(6, 0, 0, 0)
        head.addWidget(_label("LAYERS", "caps"))
        self._count_label = _label("", "small")
        head.addWidget(self._count_label)
        head.addStretch(1)
        lay.addLayout(head)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter: name, or new, check, hidden, edited, excluded")
        self._filter.setClearButtonEnabled(True)
        self._filter.addAction(_lucide_icon("search", 16, TEXT_META), QLineEdit.ActionPosition.LeadingPosition)
        self._filter.setToolTip("Shows the locks whose name holds the text. Words: new, check (match to check),"
                                " hidden, edited, excluded, flipped, strands")
        self._filter.textChanged.connect(lambda _t: self._apply_filter())
        lay.addWidget(self._filter)

        # New / to-check locks: one line with Confirm all, instead of a word on every row
        self._review = QWidget()
        self._review.setObjectName("Banner")
        self._review.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        r = QHBoxLayout(self._review)
        r.setContentsMargins(10, 4, 4, 4)
        self._review_label = _label("", "meta", TEXT_PRIMARY)
        self._review_label.setWordWrap(True)
        r.addWidget(self._review_label, stretch=1)
        confirm = QToolButton()
        confirm.setText("  Confirm all")
        confirm.setProperty("flat", True)
        confirm.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        confirm.setIcon(_lucide_icon("badge-check", 16, TEXT_PRIMARY))
        confirm.setToolTip("Accept every new and to-check lock as Detect locks matched it (one undo step)")
        confirm.clicked.connect(lambda: self._fire("confirm_all"))
        r.addWidget(confirm)
        self._review_btn = confirm
        self._review.setVisible(False)
        lay.addWidget(self._review)

        self._banner = QWidget()
        self._banner.setObjectName("Banner")
        self._banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        b = QHBoxLayout(self._banner)
        b.setContentsMargins(10, 4, 4, 4)
        self._banner_label = _label("", "meta", TEXT_PRIMARY)
        self._banner_label.setWordWrap(True)
        b.addWidget(self._banner_label, stretch=1)
        show_all = QToolButton()
        show_all.setText("Show all  Esc")
        show_all.setProperty("flat", True)
        show_all.clicked.connect(lambda: self._fire("escape"))
        b.addWidget(show_all)
        self._banner_btn = show_all
        self._banner_texts = {"isolate": "", "strands": ""}
        self._banner.setVisible(False)
        lay.addWidget(self._banner)

        tree = _LayerTree(self)
        tree.setColumnCount(4)
        tree.setHeaderHidden(True)
        tree.setUniformRowHeights(True)
        # Lock names share their group's prefix (hair_back_01, hair_back_02 ...): cut them in the middle so
        # the number that tells them apart stays visible.
        tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree.setItemDelegateForColumn(COL_STATUS, _StatusDelegate(tree))
        icons = _IconDelegate(tree)
        tree.setItemDelegateForColumn(COL_STRANDS, icons)
        tree.setItemDelegateForColumn(COL_EYE, icons)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._row_menu)
        tree.itemSelectionChanged.connect(self._on_tree_selection)
        tree.itemClicked.connect(self._on_item_clicked)
        tree.setExpandsOnDoubleClick(False)   # a double-click draws the row as strands
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, header.ResizeMode.Stretch)
        for col in (COL_STATUS, COL_STRANDS, COL_EYE):
            header.setSectionResizeMode(col, header.ResizeMode.Fixed)
        self._tree = tree
        lay.addWidget(tree, stretch=1)
        self._drop_label = _label("", "small", WARN)
        self._drop_label.setVisible(False)
        lay.addWidget(self._drop_label)
        return side

    def _build_properties(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll = scroll
        self._props_widget = QWidget()
        self._props_widget.setObjectName("PropsPane")
        self._props_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._props_lay = QVBoxLayout(self._props_widget)
        self._props_lay.setContentsMargins(22, 16, 18, 16)
        self._props_lay.setSpacing(0)
        scroll.setWidget(self._props_widget)
        return scroll

    def _build_action_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("ActionBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(14, 8, 14, 10)
        outer.setSpacing(8)
        # Loading: what is being cooked and a moving bar, shown only when the cook outlasts BUSY_DELAY_MS
        # (Houdini handles Qt events mid-cook, so the timer fires and the bar moves during the cook)
        self._busy = QWidget()
        busy_lay = QHBoxLayout(self._busy)
        busy_lay.setContentsMargins(0, 0, 0, 0)
        busy_lay.setSpacing(10)
        self._busy_label = _label("", "meta", TEXT_PRIMARY)
        busy_lay.addWidget(self._busy_label)
        self._busy_bar = QProgressBar()
        self._busy_bar.setRange(0, 0)
        self._busy_bar.setTextVisible(False)
        self._busy_bar.setFixedHeight(4)
        self._busy_bar.setStyleSheet(f"QProgressBar {{ background: {BG_RAISED}; border: none; border-radius: 1px; }}"
                                     f" QProgressBar::chunk {{ background: {ACCENT}; border-radius: 1px; }}")
        busy_lay.addWidget(self._busy_bar, stretch=1)
        self._busy.setVisible(False)
        self._busy_text = ""
        self._busy_timer = QTimer(self)
        self._busy_timer.setSingleShot(True)
        self._busy_timer.timeout.connect(self._show_busy)
        outer.addWidget(self._busy)
        self._message_label = _label("", "meta")
        self._message_label.setWordWrap(True)
        self._message_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        outer.addWidget(self._message_label)

        # Two groups that sit on one line, or one above the other when the panel is narrow
        self._action_lay = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._action_lay.setSpacing(8)
        groom = QHBoxLayout()
        groom.setSpacing(8)
        self._detect_btn = self._button("  Detect locks", "scan-search",
                                        "Find the locks in the hair mesh again; each keeps its id and settings by"
                                        " name, then root position, then shape")
        self._detect_btn.clicked.connect(lambda: self._fire("detect"))
        groom.addWidget(self._detect_btn)
        self._split_btn = self._button("  Update regions", "layout-grid",
                                       "Chia vùng: give each lock its growth region on the skin again. Regions stay"
                                       " as they are until you update them, so an edit never moves another lock's hair")
        self._split_btn.clicked.connect(lambda: self._fire("split_regions"))
        groom.addWidget(self._split_btn)
        self._stale = QLabel()
        self._stale.setToolTip("Regions out of date: locks were added, moved, flipped or excluded since the last"
                               " update. Update regions to grow each from its own skin area")
        self._stale.setVisible(False)
        groom.addWidget(self._stale)
        groom.addStretch(1)
        publish = QHBoxLayout()
        publish.setSpacing(8)
        publish.addStretch(1)
        self._version_edit = QLineEdit()
        self._version_edit.setPlaceholderText("Version")
        self._version_edit.setToolTip("Publish version (vNNN)")
        publish.addWidget(self._version_edit)
        self._publish_btn = QPushButton("  Publish")
        self._publish_btn.setObjectName("Publish")
        self._icon(self._publish_btn, "upload", "#ffffff")
        self._publish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._publish_btn.setToolTip("04_grooming/publish/vNNN/char_<name>_grooming_publish.usd: every lock,"
                                     " hidden or not; never overwrites")
        self._publish_btn.clicked.connect(lambda: self._fire("publish", self._version_edit.text()))
        publish.addWidget(self._publish_btn)
        self._action_lay.addLayout(groom, stretch=1)
        self._action_lay.addLayout(publish)
        outer.addLayout(self._action_lay)

        self._warning = QWidget()
        w = QHBoxLayout(self._warning)
        w.setContentsMargins(0, 0, 0, 0)
        w.setSpacing(8)
        w.addStretch(1)
        self._warning_icon = QLabel()
        w.addWidget(self._warning_icon, alignment=Qt.AlignmentFlag.AlignTop)
        self._warning_label = _label("", "meta", WARN)
        self._warning_label.setWordWrap(True)
        self._warning_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        w.addWidget(self._warning_label, stretch=3)
        self._warning.setVisible(False)
        outer.addWidget(self._warning)
        return bar

    # =====================================================================
    # Narrow (docked) or wide
    # =====================================================================

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_layout()

    def _apply_layout(self) -> None:
        """Below NARROW_PX the tree sits above the settings, and the view and action bars wrap."""
        z = self.z
        narrow = self.width() < z.px(NARROW_PX)
        if narrow == self._narrow:
            return
        self._narrow = narrow
        self._body.setOrientation(Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal)
        self._tree_pane.setMinimumWidth(0 if narrow else z.px(300))
        w, h = max(self.width(), 1), max(self.height(), 1)    # the body's own size is not laid out yet
        self._body.setSizes([int(h * 0.45), int(h * 0.55)] if narrow else [int(w * 0.36), int(w * 0.64)])
        down = QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        self._view_lay.setDirection(down)
        self._action_lay.setDirection(down)
        self._props_lay.setContentsMargins(z.px(14 if narrow else 22), z.px(14), z.px(12 if narrow else 18), z.px(14))
        self._asset_label.setVisible(not narrow)
        self._show_node_label()
        if self._props:
            self.show_properties(self._props)   # stat cells and setting rows in their narrow / wide sizes

    def _button(self, text: str, icon: str, tip: str) -> QPushButton:
        btn = QPushButton(text)
        self._icon(btn, icon)
        btn.setToolTip(tip)
        return btn

    # =====================================================================
    # Callbacks (controller)
    # =====================================================================

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        """
        select(kind, ids), set_value(key, value), reset_value(key), set_visible(kind, ids, on),
        set_row_display(kind, ids, mode), set_group_color(gid, rgb), confirm(ids),
        reassign_orphan(orphan_id, lock_id), delete_orphan(orphan_id), detect(), split_regions(),
        set_display(mode, color_by), publish(version), isolate(), isolate_off(), escape(), strands(),
        set_strands_of(kind, ids, on), confirm_all(), set_root_flip(ids, on), set_excluded(ids, on), undo(), redo(),
        can_drop(dragged, target, where) -> plan | reason, drop(dragged, target, where),
        poll(), refresh(), dock()
        """
        self._callbacks[event] = callback

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._fire("shown")

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._fire("hidden")   # the viewport draws every lock in its colour again

    def _fire(self, event: str, *args) -> None:
        cb = self._callbacks.get(event)
        if cb is not None:
            cb(*args)

    def _ask(self, event: str, *args) -> Any:
        cb = self._callbacks.get(event)
        return cb(*args) if cb is not None else None

    def start_polling(self, ms: int) -> None:
        """Read the viewport selection and the node's data while the panel is up (no Houdini callback)."""
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(lambda: self._fire("poll") if self.isVisible() else None)
        self._timer.start(ms)

    # =====================================================================
    # What the controller shows
    # =====================================================================

    def show_node(self, path: str, asset: str) -> None:
        self._node_path = path
        self._show_node_label()
        self._node_label.setToolTip(path)
        self._asset_label.setText(asset or "")
        self.setWindowTitle(f"{config.WINDOW_TITLE} · {path}" if path else config.WINDOW_TITLE)

    def _show_node_label(self) -> None:
        """The node's path, or only its parent and name when narrow (the tooltip has the path)."""
        path = getattr(self, "_node_path", "")
        if not path:
            self._node_label.setText("No node")
            return
        self._node_label.setText("/".join(path.split("/")[-2:]) if self._narrow else path)

    def show_tree(self, rows: list[dict]) -> None:
        self._filling = True
        self._tree_rows = rows
        expanded = {key for key, item in self._rows.items() if item.isExpanded()}
        self._collapsed = {key for key, item in self._rows.items() if not item.isExpanded()}
        first = not self._rows
        scroll = self._tree.verticalScrollBar().value()
        self._tree.clear()
        self._rows = {}
        locks = 0
        root = None   # All locks: the defaults, and the level every group inherits from, so it holds them
        for row in rows:
            item = self._make_item(row)
            if row["kind"] == SEL_DEFAULTS:
                root = item
                self._tree.addTopLevelItem(item)
            elif row["kind"] == SEL_GROUP and root is not None:
                root.addChild(item)
            else:
                self._tree.addTopLevelItem(item)
            for child in row.get("children", []):
                item.addChild(self._make_item(child, parent=row))
                locks += child["kind"] == SEL_LOCKS
            key = (row["kind"], row["id"])
            item.setExpanded(first or key in expanded or row["kind"] == SEL_DEFAULTS and key not in self._collapsed)
        groups = sum(r["kind"] == SEL_GROUP for r in rows)
        self._count_label.setText(f"{locks} locks · {groups} groups")
        self._apply_filter()
        self._tree.verticalScrollBar().setValue(scroll)
        self._filling = False

    def _apply_filter(self) -> None:
        """Hide the rows the filter does not match: a lock by its name or a filter word; a group shows when
        its name or any of its locks matches."""
        text = self._filter.text().strip().lower()
        word = FILTER_WORDS.get(text)

        def match(row: dict) -> bool:
            return bool(word(row)) if word else text in row.get("name", "").lower()

        def walk(item) -> bool:
            """Show or hide the item's children; whether any shows."""
            row = item.data(COL_NAME, ROLE_ROW) or {}
            if row.get("kind") in (SEL_LOCKS, SEL_ORPHAN):
                return match(row)
            own = row.get("kind") == SEL_GROUP and not word and match(row)
            shown = False
            for k in range(item.childCount()):
                child = item.child(k)
                hit = True if not text else (own or walk(child))
                if not text:
                    walk(child)
                child.setHidden(not hit)
                shown = shown or hit
            if text and shown:
                item.setExpanded(True)
            return shown or own

        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            top.setHidden(bool(text) and not walk(top))
            if not text:
                walk(top)

    def set_review(self, new: int, to_check: int) -> None:
        """New and to-check locks: one line with Confirm all (none: hidden)."""
        parts = ([f"{new} new"] if new else []) + ([f"{to_check} to check"] if to_check else [])
        self._review_label.setText(" · ".join(parts))
        self._review_label.setToolTip("Filter the tree with new or check to see them")
        self._review.setVisible(bool(parts))

    def _make_item(self, row: dict, parent: dict | None = None) -> QTreeWidgetItem:
        z = self.z
        item = QTreeWidgetItem()
        kind = row["kind"]
        group_hidden = kind == SEL_GROUP and not row.get("visible", True)
        by_group = bool(row.get("hidden_by_group"))
        hidden = (kind in (SEL_GROUP, SEL_LOCKS) and not row.get("visible", True)) or by_group
        row = dict(row, dimmed=hidden or group_hidden or bool(row.get("isolated_out")))
        item.setData(COL_NAME, ROLE_ROW, row)
        name = row["name"]
        if kind in (SEL_DEFAULTS, ORPHANS_ROW, SEL_GROUP) and row.get("meta"):
            item.setToolTip(COL_NAME, row["meta"])
        if kind == SEL_LOCKS:                      # the per-lock choices: words in the status column
            notes = (["excluded from hair"] if row.get("excluded") else []) + (["root flipped"] if row.get("root_flip") else [])
            if notes:
                item.setToolTip(COL_NAME, ", ".join(notes).capitalize() + ". Right click to change")
            if row.get("excluded"):
                row["dimmed"] = True
                item.setData(COL_NAME, ROLE_ROW, row)
        item.setText(COL_NAME, name)
        flags = item.flags()
        if kind not in (SEL_GROUP, SEL_LOCKS):
            flags &= ~Qt.ItemFlag.ItemIsDragEnabled
        item.setFlags(flags & ~Qt.ItemFlag.ItemIsDropEnabled)
        if kind in (SEL_GROUP, SEL_DEFAULTS, ORPHANS_ROW):
            item.setFont(COL_NAME, z.font("name"))
        else:
            item.setFont(COL_NAME, z.font("body"))
        if kind == SEL_GROUP:     # a group reads as a folder, in its colour (dim when hidden)
            rgb = row.get("color", (0.6, 0.6, 0.6))
            hexc = DIM if row["dimmed"] else "#%02x%02x%02x" % tuple(int(max(0.0, min(1.0, c)) * 255) for c in rgb)
            item.setIcon(COL_NAME, _lucide_icon("folder", z.px(16), hexc))
        elif "color" in row:
            item.setIcon(COL_NAME, _swatch(row["color"], z.px(14), 0.35 if row["dimmed"] else 1.0))
        elif kind == SEL_DEFAULTS:
            item.setIcon(COL_NAME, QIcon(_hda_icon(z.px(14))))
        elif kind == ORPHANS_ROW:
            item.setIcon(COL_NAME, _lucide_icon("unlink", z.px(14), WARN))
        if kind == SEL_ORPHAN or row["dimmed"]:
            item.setForeground(COL_NAME, QColor(DIM if row["dimmed"] else TEXT_LABEL))
        help_lines = [STATUS_HELP[b] for b in row.get("badges", []) if b in STATUS_HELP]
        if row.get("display"):
            help_lines.append(f"Shows {DISPLAY_LABELS[row['display']]} (its own display; right click › Display)")
        item.setToolTip(COL_STATUS, "\n".join(help_lines))
        if kind in (SEL_GROUP, SEL_LOCKS):
            # The eye's shape says what the viewport draws (open = drawn, crossed = not drawn); its tone says
            # why: normal = this row's own eye, faint = its group or isolate decided, accent = drawn because
            # it is isolated. A click always changes the row's own eye; the tooltip says what that is.
            visible = row.get("visible", True)
            own = "its own eye: shown" if visible else "its own eye: hidden"
            if row.get("isolated_in"):
                icon, color = "eye", ACCENT
                tip = f"Drawn: isolated ({own}). Click to change its own eye"
            elif row.get("isolated_out"):
                icon, color = "eye-off", FAINT
                tip = f"Not drawn while isolating ({own}). Click to change its own eye"
            elif by_group:
                icon, color = "eye-off", FAINT
                tip = f"Hidden by its group ({own}). Click to change its own eye"
            else:
                icon, color = ("eye", TEXT_LABEL) if visible else ("eye-off", TEXT_LABEL)
                tip = "Shown: click to hide" if visible else "Hidden: click to show"
            item.setData(COL_EYE, ROLE_ICON, _fixed_icon(icon, z.px(16), color))
            item.setData(COL_EYE, ROLE_QUIET, icon == "eye" and color == TEXT_LABEL)   # shown, its own eye
            item.setToolTip(COL_EYE, tip)
            # Packed (a flat band, quiet) or drawn as its strands, each thinning to its tip (accent)
            if row.get("strands"):
                item.setData(COL_STRANDS, ROLE_ICON, _fixed_icon("waves", z.px(16), ACCENT))
                item.setData(COL_STRANDS, ROLE_QUIET, False)
                item.setToolTip(COL_STRANDS, "Strands: drawn strand by strand, each thinning to its tip. Click,"
                                             " double-click or Enter to pack it again")
            else:
                item.setData(COL_STRANDS, ROLE_ICON, _fixed_icon("package", z.px(15), TEXT_LABEL))
                item.setData(COL_STRANDS, ROLE_QUIET, True)
                item.setToolTip(COL_STRANDS, "Packed: drawn as a flat band (fast). Click, double-click or Enter to"
                                             " draw its strands")
            if by_group:
                item.setToolTip(COL_NAME, "Hidden by its group")
        self._rows[(kind, row["id"])] = item
        return item

    def set_selection(self, selection: tuple[str, tuple]) -> None:
        kind, ids = selection
        self._filling = True
        self._tree.clearSelection()
        first = None
        for i in ids:
            item = self._rows.get((kind, i))
            if item is not None:
                item.setSelected(True)
                first = first or item
        if kind == SEL_DEFAULTS and (SEL_DEFAULTS, "") in self._rows:
            first = self._rows[(SEL_DEFAULTS, "")]
            first.setSelected(True)
        if first is not None:
            self._tree.scrollToItem(first)
        self._filling = False

    def show_properties(self, props: dict) -> None:
        z = self.z
        self._props = props
        scroll = self._scroll.verticalScrollBar().value()
        while self._props_lay.count():
            entry = self._props_lay.takeAt(0)
            if entry.widget() is not None:  # hidden now: deleteLater waits for the event loop
                entry.widget().hide()
                entry.widget().deleteLater()
        kind = props.get("kind", SEL_NONE)
        lay = self._props_lay
        if kind == SEL_NONE:
            self._overview(props)
            return
        title = _label(props["title"], "title")
        title.setWordWrap(True)
        lay.addWidget(title)
        if props.get("subtitle"):
            lay.addSpacing(z.px(2))
            sub = _label(props["subtitle"], "meta")
            sub.setWordWrap(True)
            lay.addWidget(sub)
        lay.addSpacing(z.px(12))
        if props.get("state"):
            lay.addWidget(self._action_row(props["state"]))
            lay.addSpacing(z.px(14))
        if kind == SEL_ORPHAN:
            self._orphan_actions(props)
        if props.get("measured"):
            lay.addWidget(self._measured_box(props["measured"]))
            lay.addSpacing(z.px(18))
        if props.get("settings"):
            head = QHBoxLayout()
            head.addWidget(_label("SETTINGS", "caps"))
            head.addStretch(1)
            own = {"lock": "this lock", "group": "this group", "defaults": ALL_LOCKS}.get(props.get("own", ""), "")
            if own and not self._narrow:   # narrow: the source column's tooltip says it
                below = "" if props.get("own") == "lock" else " · last column: levels below"
                head.addWidget(_label(f"bold = set here · grey = inherited{below}", "small"))
            holder = QWidget()
            holder.setLayout(head)
            head.setContentsMargins(z.px(4), 0, 0, z.px(4))
            lay.addWidget(holder)
            lay.addWidget(_line())
            for s in props["settings"]:
                lay.addWidget(_SettingRow(
                    s, z, lambda key, value: self._fire("set_value", key, value),
                    lambda key: self._fire("reset_value", key),
                    lambda key, value: self._fire("preview_value", key, value), compact=bool(self._narrow)))
        lay.addStretch(1)
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(scroll))

    def _overview(self, props: dict) -> None:
        """Nothing selected: the whole groom, the keys, how to start."""
        z, lay = self.z, self._props_lay
        lay.addWidget(_label("Groom", "title"))
        lay.addSpacing(z.px(2))
        hint = _label("Select a lock or a group to edit it. Shift / Ctrl click selects several; a pick in the"
                      " viewport selects here too. Drag rows to reorder or to move locks into another group.", "meta")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addSpacing(z.px(14))
        if props.get("overview"):
            box = self._measured_box(props["overview"])
            box.setToolTip("")
            lay.addWidget(box)
            lay.addSpacing(z.px(18))
        if props.get("shortcuts"):
            lay.addWidget(_label("KEYS", "caps"))
            lay.addSpacing(z.px(6))
            grid = QGridLayout()
            grid.setHorizontalSpacing(z.px(16))
            grid.setVerticalSpacing(z.px(6))
            for n, (keys, what) in enumerate(props["shortcuts"]):
                grid.addWidget(_label(keys, "name"), n, 0)
                desc = _label(what, "meta")
                desc.setWordWrap(True)
                grid.addWidget(desc, n, 1)
            grid.setColumnStretch(1, 1)
            holder = QWidget()
            holder.setLayout(grid)
            lay.addWidget(holder)
        lay.addStretch(1)

    def _action_row(self, state: dict) -> QWidget:
        """What the viewport does with the selection, as toggles: on = the accent. Flip root and Exclude
        only for locks; a toggle whose locks differ shows off with "mixed" in its tooltip."""
        z = self.z
        kind, ids, lock_ids = state["kind"], state["ids"], state["lock_ids"]
        hidden = state.get("visible") is False
        buttons = [
            ("Strands", "waves", bool(state.get("strands")),
             "Draw strand by strand (Enter, double-click); off: packed, a flat band", lambda _on: self._fire("strands")),
            ("Isolate", "focus", bool(state.get("isolated")), "Show it alone (I)", lambda _on: self._fire("isolate")),
            ("Hidden", "eye-off", hidden, "Its eye is off: not drawn, not cooked for display (Publish still writes it)",
             lambda _on: self._fire("set_visible", kind, list(ids), hidden)),
        ]
        if kind == SEL_LOCKS:
            buttons += [
                ("Flip root", "flip-vertical", bool(state.get("root_flip")),
                 "The root is the piece's other end (Detect took the wrong one)",
                 lambda on: self._fire("set_root_flip", list(lock_ids), on)),
                ("Exclude", "circle-slash", bool(state.get("excluded")),
                 "No hair for this piece (an accessory, a floating strand); mesh and guide still show",
                 lambda on: self._fire("set_excluded", list(lock_ids), on)),
            ]
        made = []
        for text, icon, on, tip, act in buttons:
            b = QToolButton()
            b.setText(f"  {text}")
            b.setCheckable(True)
            b.setChecked(on)
            b.setProperty("toggle", True)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setIcon(_lucide_icon(icon, z.px(15), ACCENT if on else TEXT_LABEL))
            b.setIconSize(QSize(z.px(15), z.px(15)))
            mixed = {"Flip root": "root_flip", "Exclude": "excluded", "Hidden": "visible"}.get(text)
            b.setToolTip(tip + (" · the selected locks differ" if mixed and state.get(mixed) is None else ""))
            b.clicked.connect(act)
            made.append(b)
        return _WrapRow(made, z.px(6))

    def _measured_box(self, measured: list[tuple[str, str]]) -> QWidget:
        """Measured shape as small stat cells, three per row: value over its name."""
        z = self.z
        box = QWidget()
        box.setObjectName("Measured")
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        grid = QGridLayout(box)
        grid.setContentsMargins(z.px(14), z.px(10), z.px(14), z.px(10))
        grid.setHorizontalSpacing(z.px(18))
        grid.setVerticalSpacing(z.px(10))
        cols = 2 if self._narrow else 3
        for n, (name, value) in enumerate(measured):
            cell = QVBoxLayout()
            cell.setSpacing(z.px(1))
            cell.addWidget(_label(value, "name"))
            cell.addWidget(_label(name, "small"))
            grid.addLayout(cell, n // cols, n % cols)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        box.setToolTip("Measured from the hair mesh in the last cook (scene units shown in cm)")
        return box

    def _orphan_actions(self, props: dict) -> None:
        orphan_id = self._props_selection_id()
        row = QHBoxLayout()
        row.setSpacing(8)
        combo = _Combo()
        targets = sorted(props.get("targets", []), key=lambda t: (t[2] != "new", t[1]))
        for lock_id, name, match in targets:
            combo.addItem(f"{name}  ({match})" if match != "ok" else name, lock_id)
        reassign = self._button("  Give settings to", "git-merge", "Give its settings to this lock (usually a new"
                                " lock that is the same piece renamed or reshaped)")
        reassign.setEnabled(bool(targets))
        reassign.clicked.connect(lambda: self._fire("reassign_orphan", orphan_id, combo.currentData()))
        delete = self._button("  Delete", "trash", "Forget it and its settings (Ctrl+Z brings it back)")
        delete.clicked.connect(lambda: self._fire("delete_orphan", orphan_id))
        row.addWidget(combo, stretch=1)
        row.addWidget(reassign)
        row.addWidget(delete)
        holder = QWidget()
        holder.setLayout(row)
        self._props_lay.addWidget(holder)
        self._props_lay.addSpacing(self.z.px(14))

    def _props_selection_id(self) -> Any:
        items = self._tree.selectedItems()
        return items[0].data(COL_NAME, ROLE_ROW)["id"] if items else None

    def set_message(self, text: str, error: bool = False) -> None:
        """The result line; it fades after MESSAGE_MS (errors stay twice as long). A state that lasts
        (isolate, strands, hidden locks at Publish) is told by the banner or the warning, not here."""
        self._message_label.setText(text)
        self._message_label.setStyleSheet(f"color: {TEXT_ERROR if error else TEXT_LABEL};")
        if text:
            self._message_timer.start(MESSAGE_MS * (2 if error else 1))
        else:
            self._message_timer.stop()

    def message(self) -> str:
        return self._message_label.text()

    BUSY_DELAY_MS = 150

    def set_busy(self, what: str | None) -> None:
        """A change is being made and cooked (None: done). The line shows only past BUSY_DELAY_MS, so a
        quick change draws nothing."""
        if what:
            self._busy_text = f"Cooking: {what}…"
            self._busy_timer.start(self.BUSY_DELAY_MS)
        else:
            self._busy_timer.stop()
            self._busy.setVisible(False)

    def _show_busy(self) -> None:
        self._busy_label.setText(self._busy_text)
        self._busy.setVisible(True)
        self._busy.repaint()

    def is_busy(self) -> bool:
        return self._busy.isVisible()

    def set_regions_stale(self, stale: bool) -> None:
        """Out of date: a warning icon next to Update regions, and the button in the warning colour."""
        self._stale.setPixmap(_lucide_pixmap("triangle-alert", self.z.px(16), WARN))
        self._stale.setVisible(stale)
        self._split_btn.setProperty("warn", bool(stale))
        self._split_btn.style().unpolish(self._split_btn)
        self._split_btn.style().polish(self._split_btn)

    def set_display_state(self, mode: str, color_by: str) -> None:
        self._filling = True
        self._display_combo.setCurrentIndex(max(0, self._display_combo.findData(mode)))
        self._color_combo.setCurrentIndex(max(0, self._color_combo.findData(color_by)))
        self._filling = False

    def set_deform_state(self, wired: bool, on: bool) -> None:
        """The Deform toggle: shown only when an animated hair mesh is wired in."""
        self._deform_btn.setVisible(bool(wired))
        self._deform_btn.setChecked(bool(on))
        self._recolor_icon(self._deform_btn, ACCENT if on else TEXT_LABEL)

    def set_publish_version(self, version: str, note: str) -> None:
        """The proposed version; when there is none the field says to type one and why (tooltip)."""
        self._version_edit.setText(version)
        self._version_edit.setPlaceholderText("Version" if version else "vNNN?")
        self._version_edit.setToolTip(f"Publish version (vNNN). {note}" if note else "Publish version (vNNN)")

    def _show_banner(self) -> None:
        iso, strands = self._banner_texts["isolate"], self._banner_texts["strands"]
        text = "  ·  ".join(t for t in (iso, strands) if t)
        self._banner_label.setText(text)
        self._banner.setVisible(bool(text))
        self._banner_btn.setText("Show all  Esc" if iso else "Pack all  Esc")
        self._banner_btn.setToolTip("Show every lock again" + (" and draw every lock packed" if strands else "")
                                    if iso else "Draw every lock packed again (a flat band each)")

    def set_isolate(self, text: str) -> None:
        """'' = every lock shown; else what the viewport shows alone."""
        self._banner_texts["isolate"] = text
        self._show_banner()
        self._isolate_btn.setChecked(bool(text))
        # on: the icon takes the accent too, not only the background (the tint alone was easy to miss)
        self._recolor_icon(self._isolate_btn, ACCENT if text else TEXT_LABEL)

    def set_strands(self, text: str) -> None:
        """'' = every lock packed; else the locks drawn as strands (Enter / double-click)."""
        self._banner_texts["strands"] = text
        self._show_banner()

    def set_publish_warning(self, text: str) -> None:
        """Next to Publish: hidden or isolated locks. The button turns amber and says the next click goes on."""
        self._warning_label.setText(text)
        self._warning.setVisible(bool(text))
        if text:
            self._warning_icon.setPixmap(_lucide_pixmap("triangle-alert", self.z.px(16), WARN))
        self._publish_btn.setText("  Publish anyway" if text else "  Publish")
        self._publish_btn.setProperty("armed", bool(text))
        self._publish_btn.style().unpolish(self._publish_btn)
        self._publish_btn.style().polish(self._publish_btn)

    def publish_warning(self) -> str:
        return self._warning_label.text() if self._warning.isVisibleTo(self) else ""

    def _drop_hint(self, text: str) -> None:
        self._drop_label.setText(f"Not here: {text}" if text else "")
        self._drop_label.setVisible(bool(text))

    # =====================================================================
    # Tree events
    # =====================================================================

    def _selected_rows(self) -> list[dict]:
        return [item.data(COL_NAME, ROLE_ROW) for item in self._tree.selectedItems()]

    def _on_tree_selection(self) -> None:
        if self._filling:
            return
        rows = [r for r in self._selected_rows() if r["kind"] != ORPHANS_ROW]
        if not rows:
            self._fire("select", SEL_NONE, ())
            return
        locks = [r["id"] for r in rows if r["kind"] == SEL_LOCKS]
        if locks:  # locks win over a group picked with them
            self._fire("select", SEL_LOCKS, tuple(locks))
        else:
            self._fire("select", rows[0]["kind"], (rows[0]["id"],) if rows[0]["kind"] != SEL_DEFAULTS else ())

    def _targets(self, row: dict) -> tuple[str, list]:
        """The rows an eye / display click acts on: the selection when the clicked row is in it."""
        same = [r["id"] for r in self._selected_rows() if r["kind"] == row["kind"]]
        return row["kind"], same if row["id"] in same else [row["id"]]

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        row = item.data(COL_NAME, ROLE_ROW)
        if row["kind"] not in (SEL_GROUP, SEL_LOCKS):
            return
        if column == COL_STATUS and row.get("display"):   # the eye is the tree's own (mousePressEvent)
            menu = self._display_menu(row)
            menu.exec(self._tree.viewport().mapToGlobal(self._tree.visualItemRect(item).bottomRight()))

    def _menu(self, parent: QWidget | None = None) -> QMenu:
        return QMenu(parent or self)

    def _display_menu(self, row: dict, menu: QMenu | None = None) -> QMenu:
        menu = menu or self._menu()
        kind, ids = self._targets(row)
        for mode in (None,) + config.DISPLAY_MODES:
            action = menu.addAction(DISPLAY_LABELS[mode] if mode else "Node display (auto)")
            action.setCheckable(True)
            action.setChecked(row.get("display") == mode)
            action.triggered.connect(lambda _c=False, m=mode: self._fire("set_row_display", kind, ids, m))
        return menu

    def _row_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        z = self.z
        row = item.data(COL_NAME, ROLE_ROW)
        menu = self._menu()
        if row["kind"] in (SEL_GROUP, SEL_LOCKS):
            kind, ids = self._targets(row)
            visible = row.get("visible", True)
            menu.addAction(_lucide_icon("eye-off" if visible else "eye", z.px(15)), "Hide" if visible else "Show") \
                .triggered.connect(lambda: self._fire("set_visible", kind, ids, not visible))
            menu.addAction(_lucide_icon("focus", z.px(15)), "Isolate    I").triggered.connect(
                lambda: self._fire("isolate"))
            strands = bool(row.get("strands"))
            menu.addAction(_lucide_icon("package" if strands else "waves", z.px(15)),
                           ("Pack" if strands else "Strands") + "    Enter").triggered.connect(
                lambda: self._fire("set_strands_of", kind, ids, not strands))
            self._display_menu(row, menu.addMenu(_lucide_icon("monitor", z.px(15)), "Display"))
        if row["kind"] == SEL_LOCKS:
            unsure = [r["id"] for r in self._selected_rows() if r["kind"] == SEL_LOCKS
                      and ({"unsure", "new"} & set(r["badges"]))] or \
                     ([row["id"]] if {"unsure", "new"} & set(row["badges"]) else [])
            act = menu.addAction(_lucide_icon("badge-check", z.px(15)), "Confirm match")  # not "check": reads as ticked
            act.setEnabled(bool(unsure))
            act.triggered.connect(lambda: self._fire("confirm", unsure))
            menu.addSeparator()
            _kind, ids = self._targets(row)
            flip = menu.addAction("Flip root")
            flip.setCheckable(True)
            flip.setChecked(bool(row.get("root_flip")))
            flip.triggered.connect(lambda on: self._fire("set_root_flip", ids, on))
            excl = menu.addAction("Exclude from hair")
            excl.setCheckable(True)
            excl.setChecked(bool(row.get("excluded")))
            excl.triggered.connect(lambda on: self._fire("set_excluded", ids, on))
        if row["kind"] == SEL_GROUP:
            colors = menu.addMenu(_lucide_icon("palette", z.px(15)), "Color")
            for rgb in SWATCHES:
                colors.addAction(_swatch(rgb, z.px(14)), "").triggered.connect(
                    lambda _c=False, c=rgb: self._fire("set_group_color", row["id"], c))
        if row["kind"] in (SEL_ORPHAN, ORPHANS_ROW):
            orphans = [row] if row["kind"] == SEL_ORPHAN else \
                [item.child(i).data(COL_NAME, ROLE_ROW) for i in range(item.childCount())]
            locks = [(r["id"], r["name"], r["badges"]) for key, it in self._rows.items() if key[0] == SEL_LOCKS
                     for r in [it.data(COL_NAME, ROLE_ROW)]]
            locks.sort(key=lambda t: ("new" not in t[2], t[1]))
            for orphan in orphans:
                sub = menu.addMenu(_lucide_icon("git-merge", z.px(15)), f"Give settings of {orphan['name']} to")
                for lock_id, name, badges in locks:
                    sub.addAction(name + ("  (new)" if "new" in badges else "")).triggered.connect(
                        lambda _c=False, o=orphan["id"], t=lock_id: self._fire("reassign_orphan", o, t))
                sub.setEnabled(bool(locks))
            if row["kind"] == SEL_ORPHAN:
                menu.addAction(_lucide_icon("trash", z.px(15)), "Delete missing lock").triggered.connect(
                    lambda: self._fire("delete_orphan", row["id"]))
        if not menu.isEmpty():
            menu.exec(self._tree.viewport().mapToGlobal(pos))


__all__ = ["GroomingUI", "Sz", "UI_SIZES", "houdini_scale", "load_prefs", "save_prefs"]
