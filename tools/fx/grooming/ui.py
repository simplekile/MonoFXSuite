"""
MONO Grooming panel — one window, floating or docked in a Houdini pane.

Three zones, each on its own surface with a line between them:
  top bar      the node, its asset, the display it shows, UI size, Dock
  left         the layer tree (Defaults, group › lock, Orphans): swatch, name, status, eye; drag to reorder
               or to move locks into another group; Isolate (I, Esc leaves)
  right (main) the selection: title, measured shape (cm), then one compact row per setting:
               name, slider, value, where an inherited value comes from, Reset (only when set here)
  action bar   the result line; Detect, Split regions, display, colour by; version, Publish (the one
               accent button) with its warning when locks are hidden or isolated

Colour: one accent (Publish, the selection, a drop target); status colours only for status (unsure, new,
regions out of date, errors); everything else neutral. Size: every px goes through `Sz`, which is
Houdini's UI scale x the panel's own UI size (saved per user), so fonts and icons follow both.

The panel shows what the controller gives it and fires events back (`on(event, callback)`); it keeps no
data of its own. Palette and icons are Auto Material's (tools/fx/auto_material/ui.py).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStyledItemDelegate,
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
    "focus": '<circle cx="12" cy="12" r="3"/><path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>',
    "type": '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" x2="15" y1="20" y2="20"/><line x1="12" x2="12" y1="4" y2="20"/>',
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
WARN = STATUS_COLORS[STATUS_PINNED]
STATUS_TEXT = {"unsure": WARN, "new": STATUS_COLORS[STATUS_NEW]}
STATUS_HELP = {
    "edited": "● has its own settings",
    "unsure": "unsure: re-import matched it by position or shape only (right click › Confirm match)",
    "new": "new: Detect found it in the hair mesh for the first time",
}
SOURCE_LABELS = {"group": "group", "defaults": "defaults", "builtin": "built-in", "mixed": "mixed"}
SHORT_DISPLAY = {"mesh": "Mesh", "guide": "Guide", "hair_preview": "Preview", "hair": "Hair"}

# Group colours offered in the swatch menu (no colour dialog: it would be modal)
SWATCHES: tuple[tuple[float, float, float], ...] = (
    (0.91, 0.45, 0.42), (0.95, 0.66, 0.30), (0.93, 0.83, 0.38), (0.55, 0.80, 0.45), (0.33, 0.78, 0.70),
    (0.38, 0.62, 0.95), (0.62, 0.52, 0.95), (0.88, 0.50, 0.80), (0.70, 0.70, 0.72), (0.55, 0.45, 0.38),
)

COL_NAME, COL_STATUS, COL_EYE = range(3)
ROLE_ROW = Qt.ItemDataRole.UserRole + 1
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
    QWidget#TopBar, QWidget#TreePane, QWidget#ActionBar {{ background: {PANE}; }}
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
class _Slider(QSlider):
    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # no focus from the wheel either

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()  # goes up to the scroll area


class _Combo(QComboBox):
    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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
                parts.append((badge, STATUS_TEXT[badge]))
        if row.get("display"):
            parts.append((SHORT_DISPLAY.get(row["display"], row["display"]), TEXT_LABEL))
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

    def startDrag(self, actions) -> None:  # noqa: N802
        if self._dragged():
            super().startDrag(Qt.DropAction.MoveAction)

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
    on release, so it is one undo step; *on_reset(key)*."""

    def __init__(self, s: dict, z: Sz, on_set: Callable[[str, float], None], on_reset: Callable[[str], None]):
        super().__init__()
        self.setProperty("setting", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.key = s["key"]
        self._on_set = on_set
        self._lo, self._hi = s["range"]
        self._value = float(s["value"])
        self._mixed = bool(s.get("mixed"))
        own = bool(s["resettable"])
        lay = QHBoxLayout(self)
        lay.setContentsMargins(z.px(4), z.px(5), z.px(2), z.px(5))
        lay.setSpacing(z.px(10))

        unit = f'&nbsp;<span style="color:{TEXT_META}; font-size:{z.px(13)}px;">{s["unit"]}</span>' \
            if s["unit"] else ""
        name = _label(f'{s["label"]}{unit}', "body")
        name.setTextFormat(Qt.TextFormat.RichText)
        name.setFixedWidth(z.px(128))
        lay.addWidget(name)

        self.slider = _Slider()
        self.slider.setRange(0, SLIDER_STEPS)
        self.slider.setProperty("mixed", self._mixed)
        self.slider.setValue(self._to_steps(self._value))
        self.slider.setMinimumWidth(z.px(80))
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.sliderReleased.connect(self._commit_slider)
        lay.addWidget(self.slider, stretch=1)

        self.field = QLineEdit()
        self.field.setFixedWidth(z.px(70))
        self.field.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.field.setProperty("inherited", not own)
        self.field.setPlaceholderText("mixed")
        self.field.setText("" if self._mixed else _fmt(self._value))
        self.field.editingFinished.connect(self._on_field)
        lay.addWidget(self.field)

        source = s["source"]
        self.source = _label("" if own and source != "mixed" else SOURCE_LABELS.get(source, source), "small")
        self.source.setFixedWidth(z.px(62))
        self.source.setToolTip("Where this value comes from: lock › group › defaults › built-in. A value set"
                               " here shows bold, with Reset")
        lay.addWidget(self.source)

        self.reset = QToolButton()
        self.reset.setProperty("flat", True)
        self.reset.setIcon(_lucide_icon("rotate-ccw", z.px(15), TEXT_LABEL))
        self.reset.setIconSize(QSize(z.px(15), z.px(15)))
        self.reset.setToolTip("Reset: take the value from the level below again")
        self.reset.clicked.connect(lambda: on_reset(self.key))
        policy = self.reset.sizePolicy()
        policy.setRetainSizeWhenHidden(True)  # the columns stay lined up row to row
        self.reset.setSizePolicy(policy)
        self.reset.setVisible(own)
        lay.addWidget(self.reset)

    def _to_steps(self, value: float) -> int:
        t = (value - self._lo) / (self._hi - self._lo) if self._hi > self._lo else 0.0
        return int(round(min(max(t, 0.0), 1.0) * SLIDER_STEPS))

    def _from_steps(self, steps: int) -> float:
        return self._lo + (self._hi - self._lo) * steps / SLIDER_STEPS

    def _on_slider(self, steps: int) -> None:
        self.field.setText(_fmt(self._from_steps(steps)))
        if not self.slider.isSliderDown():  # a click on the groove or a key: one change
            self._commit(self._from_steps(steps))

    def _commit_slider(self) -> None:
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
        self._on_set(self.key, value)


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
        root.addWidget(self._build_top_bar())
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
        leave.activated.connect(lambda: self._fire("isolate_off"))
        self._apply_size(refresh=False)

    # =====================================================================
    # Size
    # =====================================================================

    def _apply_size(self, refresh: bool = True) -> None:
        z = self.z
        self.setStyleSheet(_sheet(z))
        self.setMinimumSize(z.px(560 if self._docked else 820), z.px(480))
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
        for col, width in ((COL_STATUS, 92), (COL_EYE, 36)):
            header.resizeSection(col, z.px(width))
        self._tree_pane.setMinimumWidth(z.px(300))
        self._body.setSizes([z.px(400), z.px(640)])
        self._version_edit.setFixedWidth(z.px(76))
        self._isolate_btn.setIconSize(QSize(z.px(17), z.px(17)))
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
        self._size_btn.setText(f"  {name}")

    def _icon(self, widget, name: str, color: str = TEXT_LABEL, size: int = 16):
        self._icons.append((widget, name, color, size))
        widget.setIcon(_lucide_icon(name, self.z.px(size), color))
        return widget

    # =====================================================================
    # Build
    # =====================================================================

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 12, 10)
        lay.setSpacing(10)
        self._hda_label = QLabel()
        lay.addWidget(self._hda_label)
        self._node_label = _label("No node", "name")
        lay.addWidget(self._node_label)
        self._asset_label = _label("", "meta")
        self._asset_label.setToolTip("Asset mode: the groom of the asset, published to 04_grooming")
        lay.addWidget(self._asset_label)
        lay.addStretch(1)
        self._mode_label = _label("", "meta")
        lay.addWidget(self._mode_label)
        lay.addSpacing(6)
        self._size_btn = QToolButton()
        self._size_btn.setText(f"  {self._ui_size}")
        self._size_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._size_btn.setToolTip("UI size of this panel, on top of Houdini's own scale (saved for you)")
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
        self._isolate_btn = QToolButton()
        self._isolate_btn.setProperty("flat", True)
        self._isolate_btn.setCheckable(True)
        self._isolate_btn.setToolTip("Isolate: show the selected lock or group alone (I). Esc or a second"
                                     " click shows everything again; hidden states stay as they are")
        self._icon(self._isolate_btn, "focus", TEXT_LABEL, 17)
        self._isolate_btn.clicked.connect(lambda: self._fire("isolate"))
        head.addWidget(self._isolate_btn)
        lay.addLayout(head)

        self._banner = QWidget()
        self._banner.setObjectName("Banner")
        self._banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        b = QHBoxLayout(self._banner)
        b.setContentsMargins(10, 4, 4, 4)
        self._banner_label = _label("", "meta", TEXT_PRIMARY)
        b.addWidget(self._banner_label, stretch=1)
        show_all = QToolButton()
        show_all.setText("Show all  Esc")
        show_all.setProperty("flat", True)
        show_all.clicked.connect(lambda: self._fire("isolate_off"))
        b.addWidget(show_all)
        self._banner.setVisible(False)
        lay.addWidget(self._banner)

        tree = _LayerTree(self)
        tree.setColumnCount(3)
        tree.setHeaderHidden(True)
        tree.setUniformRowHeights(True)
        # Lock names share their group's prefix (hair_back_01, hair_back_02 ...): cut them in the middle so
        # the number that tells them apart stays visible.
        tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree.setItemDelegateForColumn(COL_STATUS, _StatusDelegate(tree))
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._row_menu)
        tree.itemSelectionChanged.connect(self._on_tree_selection)
        tree.itemClicked.connect(self._on_item_clicked)
        tree.setExpandsOnDoubleClick(True)
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, header.ResizeMode.Stretch)
        for col in (COL_STATUS, COL_EYE):
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
        self._message_label = _label("", "meta")
        self._message_label.setWordWrap(True)
        self._message_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        outer.addWidget(self._message_label)

        lay = QHBoxLayout()
        lay.setSpacing(8)
        self._detect_btn = self._button("  Detect", "scan-search",
                                        "Find the locks in the hair mesh again; ids are kept by name and position")
        self._detect_btn.clicked.connect(lambda: self._fire("detect"))
        lay.addWidget(self._detect_btn)
        self._split_btn = self._button("  Split regions", "layout-grid",
                                       "Chia vùng: give each lock its growth region on the scalp again (frozen"
                                       " until the next split)")
        self._split_btn.clicked.connect(lambda: self._fire("split_regions"))
        lay.addWidget(self._split_btn)
        self._stale = _label("Regions out of date", "meta", WARN)
        self._stale.setToolTip("Locks changed since the last split: Split regions to grow them from their own area")
        self._stale.setVisible(False)
        lay.addWidget(self._stale)
        lay.addStretch(1)
        self._display_combo = _Combo()
        for mode in config.DISPLAY_MODES:
            self._display_combo.addItem(DISPLAY_LABELS[mode], mode)
        self._display_combo.setToolTip(
            f"Display of every lock without its own. Hair preview: {int(config.PREVIEW_FRACTION * 100)}% of the"
            f" strands, at most {config.PREVIEW_MAX_STRANDS:,}")
        self._display_combo.currentIndexChanged.connect(
            lambda _i: None if self._filling else self._fire("set_display", self._display_combo.currentData(), None))
        lay.addWidget(self._display_combo)
        self._color_combo = _Combo()
        for key, text in COLOR_BY_LABELS.items():
            self._color_combo.addItem(f"Colour by {text.lower()}", key)
        self._color_combo.currentIndexChanged.connect(
            lambda _i: None if self._filling else self._fire("set_display", None, self._color_combo.currentData()))
        lay.addWidget(self._color_combo)
        lay.addSpacing(10)
        lay.addWidget(_line(vertical=True))
        lay.addSpacing(10)
        self._version_edit = QLineEdit()
        self._version_edit.setPlaceholderText("vNNN")
        self._version_edit.setToolTip("Publish version")
        lay.addWidget(self._version_edit)
        self._publish_btn = QPushButton("  Publish")
        self._publish_btn.setObjectName("Publish")
        self._icon(self._publish_btn, "upload", "#ffffff")
        self._publish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._publish_btn.setToolTip("04_grooming/publish/vNNN/char_<name>_grooming_publish.usd: every lock,"
                                     " hidden or not; never overwrites")
        self._publish_btn.clicked.connect(lambda: self._fire("publish", self._version_edit.text()))
        lay.addWidget(self._publish_btn)
        outer.addLayout(lay)

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
        set_display(mode, color_by), publish(version), isolate(), isolate_off(),
        can_drop(dragged, target, where) -> plan | reason, drop(dragged, target, where),
        poll(), refresh(), dock()
        """
        self._callbacks[event] = callback

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
        self._node_label.setText(path or "No node")
        self._asset_label.setText(asset or "")
        self.setWindowTitle(f"{config.WINDOW_TITLE} · {path}" if path else config.WINDOW_TITLE)

    def show_tree(self, rows: list[dict]) -> None:
        self._filling = True
        self._tree_rows = rows
        expanded = {key for key, item in self._rows.items() if item.isExpanded()}
        first = not self._rows
        scroll = self._tree.verticalScrollBar().value()
        self._tree.clear()
        self._rows = {}
        locks = 0
        for row in rows:
            item = self._make_item(row)
            self._tree.addTopLevelItem(item)
            for child in row.get("children", []):
                item.addChild(self._make_item(child, parent=row))
                locks += child["kind"] == SEL_LOCKS
            key = (row["kind"], row["id"])
            item.setExpanded(first or key in expanded)
        groups = sum(r["kind"] == SEL_GROUP for r in rows)
        self._count_label.setText(f"{locks} locks · {groups} groups")
        self._tree.verticalScrollBar().setValue(scroll)
        self._filling = False

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
        item.setText(COL_NAME, name)
        flags = item.flags()
        if kind not in (SEL_GROUP, SEL_LOCKS):
            flags &= ~Qt.ItemFlag.ItemIsDragEnabled
        item.setFlags(flags & ~Qt.ItemFlag.ItemIsDropEnabled)
        if kind in (SEL_GROUP, SEL_DEFAULTS, ORPHANS_ROW):
            item.setFont(COL_NAME, z.font("name"))
        else:
            item.setFont(COL_NAME, z.font("body"))
        if "color" in row:
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
            visible = row.get("visible", True)
            if by_group:
                icon, color = ("eye" if visible else "eye-off"), "#4a4a53"
                tip = (f"Hidden by its group{' (its own eye: shown)' if visible else ' (its own eye: hidden too)'}."
                       " Click to change its own eye")
            else:
                icon, color = ("eye", TEXT_LABEL) if visible else ("eye-off", DIM)
                tip = "Hide" if visible else "Show"
            item.setIcon(COL_EYE, _fixed_icon(icon, z.px(16), color))
            item.setToolTip(COL_EYE, tip)
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
            hint = _label("Select a lock or a group to see its settings.\nShift / Ctrl select several locks;"
                          " the viewport selection shows here too.\nDrag rows to reorder or to move locks into"
                          " another group.", "meta")
            hint.setWordWrap(True)
            lay.addWidget(hint)
            lay.addStretch(1)
            return
        lay.addWidget(_label(props["title"], "title"))
        if props.get("subtitle"):
            lay.addSpacing(z.px(2))
            lay.addWidget(_label(props["subtitle"], "meta"))
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
            own = {"lock": "this lock", "group": "this group", "defaults": "defaults"}.get(props.get("own", ""), "")
            if own:
                head.addWidget(_label(f"bold = set on {own} · grey = inherited", "small"))
            holder = QWidget()
            holder.setLayout(head)
            head.setContentsMargins(z.px(4), 0, 0, z.px(4))
            lay.addWidget(holder)
            lay.addWidget(_line())
            for s in props["settings"]:
                lay.addWidget(_SettingRow(
                    s, z, lambda key, value: self._fire("set_value", key, value),
                    lambda key: self._fire("reset_value", key)))
        lay.addStretch(1)
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(scroll))

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
        cols = 3
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
        reassign = self._button("  Reassign", "git-merge", "Give its settings to this lock")
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
        self._message_label.setText(text)
        self._message_label.setStyleSheet(f"color: {TEXT_ERROR if error else TEXT_LABEL};")

    def message(self) -> str:
        return self._message_label.text()

    def set_regions_stale(self, stale: bool) -> None:
        self._stale.setVisible(stale)

    def set_display_state(self, mode: str, color_by: str) -> None:
        self._filling = True
        self._display_combo.setCurrentIndex(max(0, self._display_combo.findData(mode)))
        self._color_combo.setCurrentIndex(max(0, self._color_combo.findData(color_by)))
        self._filling = False
        self._mode_label.setText(f"{DISPLAY_LABELS.get(mode, mode)} · colour by {color_by}")

    def set_publish_version(self, version: str, note: str) -> None:
        self._version_edit.setText(version)
        self._version_edit.setToolTip(note)

    def set_isolate(self, text: str) -> None:
        """'' = every lock shown; else what the viewport shows alone."""
        self._banner_label.setText(text)
        self._banner.setVisible(bool(text))
        self._isolate_btn.setChecked(bool(text))

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
        if column == COL_EYE:
            kind, ids = self._targets(row)
            self._fire("set_visible", kind, ids, not row.get("visible", True))
        elif column == COL_STATUS and row.get("display"):
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
            self._display_menu(row, menu.addMenu(_lucide_icon("monitor", z.px(15)), "Display"))
        if row["kind"] == SEL_LOCKS:
            unsure = [r["id"] for r in self._selected_rows() if r["kind"] == SEL_LOCKS
                      and ({"unsure", "new"} & set(r["badges"]))] or \
                     ([row["id"]] if {"unsure", "new"} & set(row["badges"]) else [])
            act = menu.addAction(_lucide_icon("check", z.px(15)), "Confirm match")
            act.setEnabled(bool(unsure))
            act.triggered.connect(lambda: self._fire("confirm", unsure))
        if row["kind"] == SEL_GROUP:
            colors = menu.addMenu(_lucide_icon("palette", z.px(15)), "Colour")
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
                sub = menu.addMenu(_lucide_icon("git-merge", z.px(15)), f"Reassign {orphan['name']} to")
                for lock_id, name, badges in locks:
                    sub.addAction(name + ("  (new)" if "new" in badges else "")).triggered.connect(
                        lambda _c=False, o=orphan["id"], t=lock_id: self._fire("reassign_orphan", o, t))
                sub.setEnabled(bool(locks))
            if row["kind"] == SEL_ORPHAN:
                menu.addAction(_lucide_icon("trash", z.px(15)), "Delete orphan").triggered.connect(
                    lambda: self._fire("delete_orphan", row["id"]))
        if not menu.isEmpty():
            menu.exec(self._tree.viewport().mapToGlobal(pos))


__all__ = ["GroomingUI", "Sz", "UI_SIZES", "houdini_scale", "load_prefs", "save_prefs"]
