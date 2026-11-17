"""MonoFX Loaders manager window (PySide6): every loader in the scene, what is behind, one-step updates.
Layout A, picked by the user (2026-11-17, mockups https://claude.ai/artifact/1uy5omTXrVU2LX4ePHZ2bb): one list and an
Add drawer. "+ Add" holds Load shot (versions) and Assets... (a drawer beside the list: type chips, search, thumbnails,
pick several, Add N: Source Asset loaders wired into ``assets_merge``). A view bar under the top bar: Solo selected,
Lookdev / Groom in the viewport, Filter. The status line adds what the shot has that the scene lacks (Add it) and the
textures the lookdevs pull. The inspector adds Source Shot / Asset, what is new in a newer version, and Folder, Monos,
Frame. The action bar adds Hand off... (a self-contained package for people without MonoFX).
Before that:

Layout R-A, picked by the user (2026-11-17, mockups https://claude.ai/artifact/GEiaL6PUnMXhXukHH2isM1, after the
Monos UI rules: browse first, act second; the inspector is information and shows only for a selection; actions in
context; no combo box for a one-shot pick). Top bar: title, project crumb (menu: the scene's, the loaders', recent
projects, Browse...), shot crumb (menu: the project's shots), List / Grid, Load shot (menu: the shot's versions).
A status line: what the primary button will do, the loader count, and a heavy-shot note with Draw Hulls Only.
**List**: a table, one 40 px row per instance (thumbnail, name, Anim / Lookdev / Groom / Cloth versions, subdivision),
"-" where nothing is published, colour only for behind / missing / asset?; two lines when docked narrow. **Grid**:
a card per instance. Inspector beside (under, when narrow) the list, only while a loader is selected: its versions
and subdivision per mesh; scheme and dicing on the meshes' right-click menu. Action bar: result line, Undo,
Retarget / Upgrade when not the primary, the one primary button. The view is the viewer's
(``%APPDATA%/MonoFXSuite/anim_loader_prefs.json``), never the scene's. Scene reads on the main thread, disk scans on
a worker thread; no modal dialogs (Browse is Qt's folder picker).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEasingCurve, QEvent, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from tools.fx.anim_loader import logic
from tools.fx.anim_loader.controller import ALL_PARTS, Controller, Row
from tools.fx.auto_material.ui import (
    ACCENT,
    ACCENT_LINE,
    BG_APP,
    BG_HOVER,
    BG_RAISED,
    FS_BODY,
    FS_DISPLAY,
    FS_META,
    FS_SMALL,
    LINE,
    STATUS_COLORS,
    STYLE_COMBO,
    STYLE_GHOST,
    STYLE_LINK,
    STYLE_MENU,
    STYLE_PILL,
    STYLE_PRIMARY,
    STYLE_WINDOW,
    TEXT_LABEL,
    TEXT_META,
    TEXT_PRIMARY,
    LUCIDE,
    _font,
    _lucide_icon,
    _lucide_pixmap,
    _Thumbnails,
)
from tools.fx.auto_material.logic import STATUS_MISSING as AM_MISSING
from tools.fx.auto_material.logic import STATUS_OK as AM_OK
from tools.fx.auto_material.logic import STATUS_PINNED as AM_WARN
from tools.fx.auto_material.logic import STATUS_UPDATE as AM_UPDATE

# Icons the manager adds to the suite's Lucide set (lucide.dev, ISC licence): fewer words, an icon per button
# (the user's ask, 2026-11-17); every icon-only button keeps a tooltip and an accessible name.
LUCIDE.update({
    "list": '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/><path d="M8 12h13"/>'
            '<path d="M8 18h13"/><path d="M8 6h13"/>',
    "layout-grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/>'
                   '<rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    # what a prim shows (the inspector's menu): hide, render only, viewport only
    "eye-off": '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444'
               ' 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1'
               '-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>',
    "camera": '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>'
              '<circle cx="12" cy="13" r="3"/>',
    "monitor": '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/>'
               '<line x1="12" x2="12" y1="17" y2="21"/>',
    "monitor-off": '<path d="M17 17H4a2 2 0 0 1-2-2V5c0-1.5 1-2 1-2"/><path d="M22 15V5a2 2 0 0 0-2-2H9"/>'
                   '<path d="M8 21h8"/><path d="M12 17v4"/><path d="m2 2 20 20"/>',
    "camera-off": '<line x1="2" x2="22" y1="2" y2="22"/><path d="M7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16"/>'
                  '<path d="M9.5 4h5L17 7h3a2 2 0 0 1 2 2v7.5"/><path d="M14.121 15.121A3 3 0 1 1 9.88 10.88"/>',
    "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
            '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>',
})

def _crisp_icon(name: str, size: int, color: str) -> "QIcon":
    """A Lucide icon drawn at ``size`` logical px for every device-pixel ratio Houdini may use: scaling one small
    pixmap up broke the strokes (the search icon, the user's report 2026-11-17)."""
    from PySide6.QtGui import QIcon

    icon = QIcon()
    for ratio in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0):
        icon.addPixmap(_lucide_pixmap(name, size, color, ratio))
    return icon


# A toggle that is on draws filled (the user's ask): the shape solid, its inner part (the pupil, the lens) cut out
# so the row shows through; off stays the outline with its slash. Shapes from Lucide (ISC), in its 24-unit box.
_FILLED = {
    "eye": ('<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1'
            '-19.876 0"/>', (12.0, 12.0, 3.4)),
    "monitor": ('<rect width="20" height="14" x="2" y="3" rx="2"/><path d="M8 21h8M12 17v4" fill="none"/>', None),
    "camera": ('<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>',
               (12.0, 13.0, 3.4)),
}
_filled_cache: dict = {}


def _filled_pixmap(name: str, size: int, color: str, ratio: float = 2.0) -> "QPixmap":
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPixmap
    from PySide6.QtSvg import QSvgRenderer

    key = (name, size, color, ratio)
    if key not in _filled_cache:
        body, hole = _FILLED[name]
        phys = int(size * ratio)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{phys}" height="{phys}" viewBox="0 0 24 24" '
               f'fill="{color}" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
               f"{body}</svg>")
        pm = QPixmap(phys, phys)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        QSvgRenderer(svg.encode("utf-8")).render(p)
        if hole is not None:  # the pupil / the lens: cut out, not painted, so it reads on any row colour
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0))
            k = phys / 24.0
            p.drawEllipse(QPointF(hole[0] * k, hole[1] * k), hole[2] * k, hole[2] * k)
        p.end()
        pm.setDevicePixelRatio(ratio)
        _filled_cache[key] = pm
    return _filled_cache[key]


_prim_icon_cache: dict = {}
_PRIM_LUCIDE = {"xform": "layers", "mesh": "box", "basiscurves": "droplet"}  # outside Houdini


def _prim_icon(kind: str, size: int) -> "QPixmap":
    """The scene graph's own icon of a prim type (Houdini's ``SCENEGRAPH_primtype_<kind>``: xform, mesh), as the
    Scene Graph Tree shows it (the user's ask, 2026-11-17); a Lucide icon outside Houdini."""
    key = (kind, size)
    if key not in _prim_icon_cache:
        pm = None
        try:
            import hou

            pm = hou.qt.Icon(f"SCENEGRAPH_primtype_{kind}", size * 2, size * 2).pixmap(size * 2, size * 2)
            pm.setDevicePixelRatio(2.0)
            if pm.isNull():
                pm = None
        except Exception:  # no hou, or no such icon
            pm = None
        _prim_icon_cache[key] = pm or _crisp_icon(_PRIM_LUCIDE.get(kind, "box"), size, TEXT_LABEL).pixmap(size)
    return _prim_icon_cache[key]


# Menus with square corners (the user's ask, 2026-11-17): the suite's menu style without its radii
STYLE_MENU_SQ = STYLE_MENU.replace("border-radius: 10px", "border-radius: 0px").replace(
    "border-radius: 6px", "border-radius: 0px")

WINDOW_NAME = "AnimLoaderManager"
PREFS = Path(os.environ.get("APPDATA", Path.home())) / "MonoFXSuite" / "anim_loader_prefs.json"
# "Geo": the geometry a row reads, a shot's anim or an asset's model (the user asked why mushroom had "anim v003")
PART_LABEL = {"anim": "Geo", "lookdev": "Lookdev", "groom": "Groom", "cloth": "Cloth"}


def part_word(row, part: str) -> str:
    """The part's name in a sentence: the Geo column is anim for a shot, model for an asset."""
    if part == "anim":
        return "model" if getattr(row, "asset_source", False) or getattr(row, "kind", "") == "layer" else "anim"
    return part
ACCENT_ON_SELECTED = "#6f9aff"  # the accent as text on a selected row: #5b8cff there is 3.95:1, this 4.5:1
SELECTED = "#273352"  # the accent at 24 % over the window, opaque (Houdini paints transparent rows grey)
ROLE_ROW = Qt.ItemDataRole.UserRole + 10
ROLE_HEADER = Qt.ItemDataRole.UserRole + 11


def _border_px(scale: float) -> int:
    """Width of a control's border: 2 px at least (1 px breaks on rounded corners), more under a large UI scale."""
    return max(2, round(1.5 * scale))


def scale_css(css: str, scale: float) -> str:
    """Every size in a style sheet times the UI scale (Houdini's x the window's); 1 px lines stay 1 px."""
    import re

    def one(m):
        v = float(m.group(1))
        return m.group(0) if v <= 1 else f"{round(v * scale)}px"

    css = css if scale == 1 else re.sub(r"(\d+(?:\.\d+)?)px", one, css)
    # a control's whole border (rounded): at least 2 px, after the scale (no double scaling); dividers
    # (border-bottom, border-left...) stay hairlines
    return re.sub(r"border:\s*1px", f"border: {_border_px(scale)}px", css)


def chip(state: str, newer: str | None, version: str) -> tuple[str, str]:
    """(text, colour) of a part's chip; colour never stands alone: the word says it too."""
    if state == logic.STATUS_OK:
        return version or "ok", STATUS_COLORS[AM_OK]
    if state == logic.STATUS_NEWER:
        return (f"{version} → {newer}" if version else f"+{newer}"), STATUS_COLORS[AM_UPDATE]
    if state == logic.STATUS_MISSING:
        return (f"missing ({newer} out)" if newer else "missing"), STATUS_COLORS[AM_MISSING]
    if state in (logic.STATUS_NONE, logic.STATUS_OFF):
        return "\u2013", TEXT_META
    if state == logic.STATUS_ASSET:
        return "asset?", STATUS_COLORS[AM_WARN]
    return "\u2013", TEXT_META


def row_summary(row: Row) -> tuple[str, str]:
    """The one-line status of a card (text, colour)."""
    if row.legacy:
        return "old loader, upgrade", STATUS_COLORS[AM_WARN]
    if row.needs_asset:
        return "asset? right-click", STATUS_COLORS[AM_WARN]
    behind = [p for p, (s, _) in row.parts.items() if s == logic.STATUS_NEWER]
    if behind:
        return f"{len(behind)} behind", STATUS_COLORS[AM_UPDATE]
    if row.missing:
        return "something missing", STATUS_COLORS[AM_MISSING]
    return "up to date", STATUS_COLORS[AM_OK]


BROWSE = "__browse__"  # the Project box's last item


def _path_key(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").lower()


def _load_prefs() -> dict:
    try:
        data = json.loads(PREFS.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_prefs(data: dict) -> None:
    try:
        PREFS.parent.mkdir(parents=True, exist_ok=True)
        PREFS.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


class _Painter:
    """Shared painting for both views: thumbnail, chips, header."""

    def __init__(self, thumbs: _Thumbnails, scale: float) -> None:
        self.thumbs = thumbs
        self.s = scale

    def px(self, v: float) -> int:
        return int(round(v * self.s))

    def thumb(self, p: QPainter, rect: QRect, row: Row) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), self.px(6), self.px(6))
        p.save()
        p.setClipPath(path)
        pm = self.thumbs.get(row.thumb) if row.thumb else None
        if pm is not None and not pm.isNull():
            scaled = pm.scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
            src = QRect((scaled.width() - rect.width()) // 2, (scaled.height() - rect.height()) // 2,
                        rect.width(), rect.height())
            p.drawPixmap(rect, scaled, src)
        else:
            p.fillRect(rect, QColor("#1f1f26"))
            icon = ("target" if row.kind == "cam" else "layers" if row.kind == "layer"
                    else ("triangle-alert" if row.needs_asset or row.legacy else "user"))
            size = min(self.px(22), rect.height() // 2)
            p.drawPixmap(QRect(rect.center().x() - size // 2, rect.center().y() - size // 2, size, size),
                         _lucide_pixmap(icon, size, "#4a4a55"))
        p.restore()

    def chip(self, p: QPainter, x: int, y: int, text: str, color: str, max_w: int) -> int:
        p.setFont(_font(self.px(FS_SMALL), QFont.Weight.DemiBold))
        fm = p.fontMetrics()
        text = fm.elidedText(text, Qt.TextElideMode.ElideRight, max_w - self.px(16))
        w = min(max_w, fm.horizontalAdvance(text) + self.px(16))
        h = self.px(22)
        r = QRect(x, y, w, h)
        c = QColor(color)
        bg = QColor(c)
        bg.setAlphaF(0.12)
        border = QColor(c)
        border.setAlphaF(0.38)
        shape = QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(BG_APP))  # an opaque base: the tint over a selected row fell to 3.3:1
        p.drawRoundedRect(shape, self.px(6), self.px(6))
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(shape, self.px(6), self.px(6))
        p.setPen(c)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        return w

    def header(self, p: QPainter, rect: QRect, text: str) -> None:
        f = _font(self.px(FS_SMALL), QFont.Weight.Normal)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        p.setFont(f)
        p.setPen(QColor(TEXT_LABEL))
        p.drawText(rect.adjusted(self.px(LIST_PAD), 0, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                   text.upper())

    def band(self, p: QPainter, rect: QRect, text: str) -> None:
        """A group band across the list: filled, a line above and below, the group name in caps."""
        p.fillRect(rect, QColor(BAND))
        p.setPen(QColor(LINE))
        p.drawLine(rect.topLeft(), rect.topRight())
        p.drawLine(rect.bottomLeft(), rect.bottomRight())
        f = _font(self.px(FS_SMALL), QFont.Weight.Normal)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        p.setFont(f)
        p.setPen(QColor(TEXT_LABEL))
        p.drawText(rect.adjusted(self.px(LIST_PAD), 0, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   text.upper())


NARROW_ROW_PX = 560  # under this width a list row puts its versions on a second line
LIST_PAD = 6  # the list's side margins: tight to the edges (the user's ask, 2026-11-17)
ZEBRA = "#151519"       # every other row, a step over the window (TEXT_LABEL on it 7.2:1)
MESH_BAND = "#1a1e27"   # the inspector's meshes table header
BAND = BG_RAISED        # group bands and the column header
ROLE_ZEBRA = Qt.ItemDataRole.UserRole + 12
# Monos states (docs/ui_states_rules.md): pressed a step past hover, selected + hover brighter than selected
STATES_PILL = (f"QPushButton:pressed {{ background: #26262d; }}"
               f"QPushButton:checked:hover {{ background: #22305a; border-color: {ACCENT}; }}"
               f"QPushButton:checked:pressed {{ background: #1c2850; }}")
STATES_GHOST = ("QPushButton:pressed { background: #26262d; color: #ededf0; }"
                "QPushButton::menu-indicator { image: none; width: 0; }")  # the label carries the arrow
STATES_PRIMARY = "QPushButton:pressed { background: #2f5bd8; }"
# The top bar's icon buttons (the user's ask): compact, no border; a solid fill only on hover, press and the view
# that is on (List / Grid), never an outline
STYLE_ICON_FLAT = (f"QPushButton {{ background: transparent; border: none; border-radius: 6px; padding: 0px;"
                   f" font-size: {FS_META}px; }}"
                   f"QPushButton:hover {{ background: {BG_HOVER}; }}"
                   f"QPushButton:pressed {{ background: #2c2c34; }}"
                   f"QPushButton:checked {{ background: #2a2a32; }}"
                   f"QPushButton:checked:hover {{ background: #31313a; }}"
                   "QPushButton::menu-indicator { image: none; width: 0; }")
COLUMNS = (("anim", "Geo", 76), ("lookdev", "Lookdev", 76), ("groom", "Groom", 76), ("cloth", "Cloth", 76),
           ("subd", "Subd", 92), ("tex", "Textures", 76))


def subd_cell(row: Row) -> tuple[str, str]:
    """(text, colour) of a row's subdivision cell: meshes and viewport polygons, amber over the heavy line."""
    if not row.subd:
        return "\u2013", TEXT_META
    n, polys = row.subd
    return f"~{polys / 1e6:.1f} M", (STATUS_COLORS[AM_WARN] if polys > logic.HEAVY_SUBD_POLYGONS
                                                 else TEXT_LABEL)


def _num(v: float) -> str:
    """A camera value for people: 35, 20.25, 0.0001, 1,000,000 (not 1e+06 or 34.99999)."""
    return f"{v:,.0f}" if abs(v) >= 1e4 else f"{v:.4g}"


def tex_cell(row: Row) -> tuple[str, str]:
    """(text, colour) of the textures a row's lookdev pulls."""
    if row.weight < 1e6:
        return "\u2013", TEXT_META
    return logic.size_word(row.weight), TEXT_LABEL


def part_cell(row: Row, part: str) -> tuple[str, str]:
    """(text, colour) of a part's cell: the version plain, colour only when something is to be done."""
    st, newer = row.parts.get(part, (logic.STATUS_OFF, None))
    text, color = chip(st, newer, row.versions.get(part, ""))
    return text.replace(" \u2192 ", "\u2192"), (TEXT_PRIMARY if st == logic.STATUS_OK else color)  # fits a column


class _ListDelegate(QStyledItemDelegate):
    """List view: a table row per instance (thumbnail, name, four versions, subdivision); the shot header carries
    the column names. Narrow: the versions go on a second line."""

    def __init__(self, painter: _Painter, view: QListView | None = None, parent=None) -> None:
        super().__init__(parent)
        self.pt = painter
        self.view = view

    def visible_columns(self, width: int) -> tuple:
        """Every column: the list scrolls sideways when they do not fit (the user's ask, 2026-11-17)."""
        return COLUMNS

    def table_width(self) -> int:
        """The narrowest the table gets: a 160 px name column and every column beside it."""
        pt = self.pt
        return pt.px(LIST_PAD + 28 + 10 + 160) + sum(pt.px(w) + pt.px(8) for _, _, w in COLUMNS) + pt.px(LIST_PAD)

    def columns(self, rect: QRect) -> tuple[dict[str, QRect], int]:
        """Each visible column's rect from the right edge, and where the name column ends."""
        pt = self.pt
        x = rect.right() - pt.px(LIST_PAD)
        out = {}
        for key, _, w in reversed(self.visible_columns(rect.width())):
            w = pt.px(w)
            out[key] = QRect(x - w, rect.top(), w, rect.height())
            x -= w + pt.px(8)
        return out, x

    def cells(self, rect: QRect) -> list[tuple[QRect, str]]:
        """Narrow rows: the four versions' cells across the row."""
        pad = self.pt.px(LIST_PAD)
        w = (rect.width() - 2 * pad) // 4
        return [(QRect(rect.left() + pad + i * w, rect.top(), w - self.pt.px(6), rect.height()), part)
                for i, part in enumerate(ALL_PARTS)]

    def _text(self, p: QPainter, rect: QRect, text: str, color: str, size: int, bold: bool = False,
              align=Qt.AlignmentFlag.AlignLeft) -> None:
        p.setFont(_font(self.pt.px(size), QFont.Weight.DemiBold if bold else QFont.Weight.Normal))
        p.setPen(QColor(color))
        p.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, rect.width()))

    def paint(self, p: QPainter, option, index) -> None:
        pt = self.pt
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect
        wide = rect.width() >= pt.px(NARROW_ROW_PX)
        if index.data(ROLE_HEADER):  # a group band (the column names are in the sticky header above)
            pt.band(p, rect, index.data(ROLE_HEADER))
            p.restore()
            return
        row: Row = index.data(ROLE_ROW)
        selected = bool(option.state & option.state.__class__.State_Selected)
        hover = bool(option.state & option.state.__class__.State_MouseOver)
        base = ZEBRA if index.data(ROLE_ZEBRA) else BG_APP
        # Monos states: hover a step lighter, selected its own blue, selected + hover brighter than selected
        fill = ("#2e3c5f" if hover else SELECTED) if selected else (BG_HOVER if hover else base)
        p.fillRect(rect, QColor(fill))
        p.setPen(QColor(LINE))
        p.drawLine(rect.bottomLeft(), rect.bottomRight())
        if wide and not (row.legacy and not row.versions):  # separators (an old loader's line spans them)
            cols_sep, name_sep = self.columns(rect)
            for x in [name_sep + pt.px(4)] + [cols_sep[k].left() - pt.px(4)
                                              for k, _, _ in self.visible_columns(rect.width())[1:]]:
                p.drawLine(x, rect.top(), x, rect.bottom())
        pad, th = pt.px(LIST_PAD), pt.px(28)
        line1 = QRect(rect.left(), rect.top(), rect.width(), pt.px(40))
        pt.thumb(p, QRect(rect.left() + pad, line1.center().y() - th // 2, th, th), row)
        name_x = rect.left() + pad + th + pt.px(10)
        cols, name_end = self.columns(line1)
        if not wide and "subd" in cols:
            name_end = cols["subd"].left() - pt.px(8)  # narrow: subd sits at the right of the name line
        p.setFont(_font(pt.px(FS_META), QFont.Weight.Normal))
        name_w = min(p.fontMetrics().horizontalAdvance(row.instance) + pt.px(4), name_end - name_x)
        self._text(p, QRect(name_x, line1.top(), name_w, line1.height()), row.instance, TEXT_PRIMARY, FS_META)
        unread = row.legacy and not row.versions  # 2.1 / Character Loader 3.2: no state to show
        tag = ("baked" if getattr(row, "baked", False) else "camera" if row.kind == "cam" else ""
               if row.kind == "layer"  # the group says sublayers
               else ("2.2" if row.legacy and not unread else ("old" if unread else "")))
        if tag:
            self._text(p, QRect(name_x + name_w + pt.px(8), line1.top(), max(0, name_end - name_x - name_w - pt.px(8)),
                                line1.height()), tag, TEXT_LABEL, FS_SMALL)
        text, color = subd_cell(row)
        if row.kind != "cam" and not (row.legacy and not row.versions):
            if "subd" in cols:
                self._text(p, cols["subd"], text if wide or row.subd else "", color, FS_SMALL,
                           align=Qt.AlignmentFlag.AlignHCenter)  # every column but the name is centred
            if wide and "tex" in cols:
                t_text, t_color = tex_cell(row)
                self._text(p, cols["tex"], t_text, t_color, FS_SMALL, align=Qt.AlignmentFlag.AlignHCenter)
        if wide:
            cells = [(cols[part], part) for part in ALL_PARTS]
        else:  # the versions on a second line, under the column names of the first header
            cells = [(QRect(c.left(), rect.top() + pt.px(36), c.width(), pt.px(20)), part)
                     for c, part in self.cells(rect)]
        if unread:
            first = cells[0][0]
            self._text(p, QRect(first.left(), first.top(), rect.right() - pad - first.left(), first.height()),
                       "Upgrade to MonoFX Loader keeps its settings", STATUS_COLORS[AM_WARN], FS_SMALL)
        else:
            for r, part in cells:
                if row.kind == "cam" and part != "anim":
                    continue
                text, color = part_cell(row, part)
                if selected and color == ACCENT:  # 4.5:1 on the selected fill, and on selected + hover
                    color = "#86abff" if hover else ACCENT_ON_SELECTED
                self._text(p, r, text, color, FS_SMALL, align=Qt.AlignmentFlag.AlignHCenter)
        p.restore()

    def sizeHint(self, option, index) -> QSize:
        width = self.view.viewport().width() if self.view is not None else 1000
        wide = width >= self.pt.px(NARROW_ROW_PX)
        if wide:  # the table keeps its columns; the view scrolls sideways
            width = max(width, self.table_width())
        if index.data(ROLE_HEADER):
            return QSize(width, self.pt.px(28))
        return QSize(width, self.pt.px(40 if wide else 62))


class _SlideClip(QWidget):
    """Holds a panel at ``full`` width while it slides: the clip widens from the window's right edge and shows
    the panel's left part first, so the panel moves in rather than stretching. At rest the panel fills it."""

    def __init__(self, panel: QWidget) -> None:
        super().__init__()
        self.panel = panel
        panel.setParent(self)
        self.full = 0  # > 0 while sliding: the panel's width then

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.panel.setGeometry(0, 0, max(self.width(), self.full), self.height())

    def sizeHint(self) -> QSize:
        return self.panel.sizeHint()

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.panel.minimumSizeHint().height())


class _ColumnHeader(QWidget):
    """The list's column names, fixed above the rows (a table header): filled band, separators at the rows'
    column lines; narrow, the four part names where the rows put their versions."""

    def __init__(self, view: QListWidget, delegate: _ListDelegate, painter: _Painter) -> None:
        super().__init__(view)
        self.view, self.delegate, self.pt = view, delegate, painter
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def place(self) -> None:
        vp = self.view.viewport()
        self.setGeometry(vp.x(), vp.y() - self.pt.px(30), vp.width(), self.pt.px(30))
        self.update()

    def paintEvent(self, _event) -> None:
        pt = self.pt
        p = QPainter(self)
        p.fillRect(QRect(0, 0, self.width(), self.height()), QColor(BAND))
        rect = QRect(0, 0, self.width(), self.height())
        if self.width() >= pt.px(NARROW_ROW_PX):  # the table's width, moved with the list's sideways scroll
            rect = QRect(0, 0, max(self.width(), self.delegate.table_width()), self.height())
            p.translate(-self.view.horizontalScrollBar().value(), 0)
        p.setPen(QColor(LINE))
        p.drawLine(rect.bottomLeft(), rect.bottomRight())
        f = _font(pt.px(FS_SMALL), QFont.Weight.Normal)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        p.setFont(f)
        p.setPen(QColor(TEXT_LABEL))
        mid = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        centre = Qt.AlignmentFlag.AlignCenter  # every column but the name, like the cells under it
        if rect.width() >= pt.px(NARROW_ROW_PX):
            cols, name_end = self.delegate.columns(rect)
            p.drawText(QRect(pt.px(LIST_PAD), 0, name_end - pt.px(LIST_PAD), rect.height()), mid, "NAME")
            shown = self.delegate.visible_columns(rect.width())
            for key, label, _ in shown:
                p.drawText(cols[key], centre, label.upper())
            p.setPen(QColor(LINE))
            for x in [name_end + pt.px(4)] + [cols[k].left() - pt.px(4) for k, _, _ in shown[1:]]:
                p.drawLine(x, 0, x, rect.bottom())
        else:
            for cell, part in self.delegate.cells(rect):
                p.drawText(cell, centre, PART_LABEL[part].upper())
        p.end()


class _GridDelegate(QStyledItemDelegate):
    """Grid view: a card per instance, thumbnail on top, status edge, name, status line, four part lines."""

    def __init__(self, painter: _Painter, view: QListView, parent=None) -> None:
        super().__init__(parent)
        self.pt = painter
        self.view = view

    CARD_MIN_PX = 200

    def card(self, row: Row | None = None) -> QSize:
        """Cards share the row's width (as many as fit at 200 px); a camera card has one part line, not four."""
        # Qt's icon layout keeps room for the vertical scroll bar before it wraps
        bar = self.view.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        avail = max(self.pt.px(self.CARD_MIN_PX), self.view.viewport().width() - bar - 2)
        n = max(1, avail // self.pt.px(self.CARD_MIN_PX))
        short = row is not None and (row.kind == "cam" or row.legacy)
        return QSize(avail // n, self.pt.px(188 if short else 248))

    def paint(self, p: QPainter, option, index) -> None:
        pt = self.pt
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if index.data(ROLE_HEADER):
            pt.header(p, option.rect.adjusted(-pt.px(10), 0, 0, -pt.px(6)), index.data(ROLE_HEADER))
            p.restore()
            return
        row: Row = index.data(ROLE_ROW)
        rect = option.rect.adjusted(pt.px(6), pt.px(6), -pt.px(6), -pt.px(6))
        selected = bool(option.state & option.state.__class__.State_Selected)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), pt.px(10), pt.px(10))
        p.fillPath(path, QColor(BG_RAISED))
        thumb = QRect(rect.left(), rect.top(), rect.width(), pt.px(96))
        p.setClipPath(path)
        pt.thumb(p, thumb, row)
        text, color = row_summary(row)
        p.fillRect(QRect(rect.left(), thumb.bottom() + 1, rect.width(), pt.px(3)), QColor(color))
        p.setClipping(False)
        x, w = rect.left() + pt.px(12), rect.width() - pt.px(24)
        y = thumb.bottom() + pt.px(10)
        p.setFont(_font(pt.px(FS_META), QFont.Weight.DemiBold))
        p.setPen(QColor(TEXT_PRIMARY))
        p.drawText(QRect(x, y, w, pt.px(20)), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(row.instance, Qt.TextElideMode.ElideMiddle, w))
        y += pt.px(20)
        p.setFont(_font(pt.px(FS_SMALL), QFont.Weight.DemiBold))
        p.setPen(QColor(color))
        p.drawText(QRect(x, y, w, pt.px(18)), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        if row.subd:
            p.setPen(QColor(STATUS_COLORS[AM_WARN] if row.subd[1] > logic.HEAVY_SUBD_POLYGONS else TEXT_LABEL))
            p.drawText(QRect(x, y, w, pt.px(18)), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       subd_chip(row).split(", ")[0])
        y += pt.px(24)
        if not row.legacy:
            parts = ALL_PARTS[:1] if row.kind == "cam" else ALL_PARTS
            for part in parts:
                st, newer = row.parts.get(part, (logic.STATUS_OFF, None))
                label, c = chip(st, newer, row.versions.get(part, ""))
                p.setFont(_font(pt.px(FS_SMALL)))
                p.setPen(QColor(TEXT_LABEL))
                p.drawText(QRect(x, y, w, pt.px(18)), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           PART_LABEL[part])
                p.setFont(_font(pt.px(FS_SMALL), QFont.Weight.DemiBold))
                p.setPen(QColor(c))
                p.drawText(QRect(x, y, w, pt.px(18)), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideLeft, w - pt.px(64)))
                y += pt.px(20)
        p.setPen(QPen(QColor(ACCENT if selected else LINE), 2 if selected else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), pt.px(10), pt.px(10))
        p.restore()

    def sizeHint(self, option, index) -> QSize:
        if index.data(ROLE_HEADER):
            return QSize(max(self.pt.px(200), self.view.viewport().width() - self.pt.px(24)), self.pt.px(34))
        return self.card(index.data(ROLE_ROW))


class AnimLoaderManager(QWidget):
    """The window. ``backend`` is ``apps.houdini.anim_loader_adapter.HoudiniBackend`` in Houdini."""

    def __init__(self, backend: Any, parent: QWidget | None = None, scale: float = 1.0) -> None:
        super().__init__(parent)
        from concurrent.futures import ThreadPoolExecutor

        self.setObjectName(WINDOW_NAME)
        self.setWindowTitle("MonoFX Loaders")
        self.s = scale
        self.backend = backend
        self.ctl = Controller(backend)
        self.prefs = _load_prefs()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="monofx_anim_loader_scan")
        self._pending: tuple[int, Any] | None = None
        self._poll = QTimer(self)
        self._poll.setInterval(50)
        self._poll.timeout.connect(self._collect)
        self._thumbs = _Thumbnails(self._repaint_views)
        self._paint = _Painter(self._thumbs, scale)
        self.setStyleSheet(self.css(STYLE_WINDOW.replace("AutoMaterialWindow", WINDOW_NAME) + STYLE_MENU_SQ))
        self._build()
        self.set_view(self.prefs.get("view", "list"))
        self.refresh()

    # --- layout --------------------------------------------------------------------------------
    def px(self, v: float) -> int:
        return int(round(v * self.s))

    def css(self, style: str) -> str:
        return scale_css(style, self.s)

    def _label(self, text: str, px: int, weight=QFont.Weight.Normal, color: str = TEXT_PRIMARY) -> QLabel:
        lab = QLabel(text)
        lab.setFont(_font(self.px(px), weight))
        # a style sheet size, not only setFont: the window's sheet sets every QWidget's font-size
        bold = 600 if weight == QFont.Weight.DemiBold else 400
        lab.setStyleSheet(f"color: {color}; background: transparent; font-size: {self.px(px)}px; font-weight: {bold};")
        return lab

    def _button(self, text: str, style: str) -> QPushButton:
        b = QPushButton(text)
        states = {id(STYLE_PILL): STATES_PILL, id(STYLE_GHOST): STATES_GHOST, id(STYLE_PRIMARY): STATES_PRIMARY}
        b.setStyleSheet(self.css(style + states.get(id(style), "")))
        b.setFont(_font(self.px(FS_META if style is not STYLE_PRIMARY else FS_BODY),
                        QFont.Weight.DemiBold if style is STYLE_PRIMARY else QFont.Weight.Normal))
        b.setMinimumHeight(self.px(32))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _icon_button(self, icon: str, tip: str, style: str = STYLE_GHOST, text: str = "") -> QPushButton:
        """A button that says it with an icon (text only when a number helps); the tooltip names it."""
        b = self._button(text, style)
        b.setIcon(_crisp_icon(icon, self.px(16), TEXT_PRIMARY))
        b.setIconSize(QSize(self.px(16), self.px(16)))
        b.setToolTip(tip)
        b.setAccessibleName(tip.split(":")[0])
        b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if not text:
            side = 28 if style is STYLE_ICON_FLAT else 34
            b.setFixedSize(self.px(side), self.px(side))
            b.setStyleSheet(b.styleSheet() + self.css("QPushButton { padding: 0px; text-align: center; }"))
        return b

    def _bar(self) -> tuple[QWidget, QHBoxLayout]:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(self.px(16), self.px(10), self.px(16), self.px(10))
        lay.setSpacing(self.px(8))
        return w, lay

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.left = QWidget()  # top bar, status line and list; the inspector is the full-height column beside it
        left_lay = QVBoxLayout(self.left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)
        self.left.installEventFilter(self)  # the crumbs follow the left column's width

        top, t = self._bar()
        top.setObjectName("top")
        # no title label: the window's title bar says MonoFX Loaders, the crumbs get the room
        # Where: project and shot as crumbs with menus (Monos: a one-shot pick is a menu, not a combo box). In the
        # top bar, or in a row of their own when docked narrow (resizeEvent).
        self._project = ""
        self._picked_shot = ""  # a shot the artist chose; any other is picked again on each fill
        self.project_button = self._crumb("Pick a project", "Project: the scene's, recent ones, or Browse")
        self.project_menu = self._menu_for(self.project_button)
        self.shot_button = self._crumb("", "Shot: Load shot and Retarget use it", strong=True)
        self.shot_menu = self._menu_for(self.shot_button)
        self.nav_box = QWidget()
        nb = QHBoxLayout(self.nav_box)
        nb.setContentsMargins(0, 0, 0, 0)
        nb.setSpacing(self.px(2))
        nb.addWidget(self.project_button)
        nb.addWidget(self.shot_button)
        nb.addStretch(1)
        self.nav_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._top_layout = t
        t.addWidget(self.nav_box, 1)
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("filter")
        self.filter_edit.setPlaceholderText("Filter")
        self.filter_edit.setToolTip("Only loaders whose name or asset holds this text")
        self.filter_edit.addAction(_crisp_icon("search", 16, TEXT_LABEL),  # the field's own 16 px icon slot
                                   QLineEdit.ActionPosition.LeadingPosition)
        self.filter_edit.setFixedWidth(self.px(150))
        self.filter_edit.setMinimumHeight(self.px(32))
        self.filter_edit.setStyleSheet(self.css(
            f"QLineEdit#filter {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {LINE};"
            f" border-radius: 8px; padding: 3px 6px; font-size: {FS_SMALL}px; }}"
            f"QLineEdit#filter:focus {{ border: 1px solid {ACCENT}; }}"))
        self.filter_edit.textChanged.connect(lambda _t: self._show_rows())
        t.addWidget(self.filter_edit)
        self.viewport_button = self._icon_button("eye", "Viewport: solo, lookdev and groom in the viewport, "
                                                        "draw hulls only", STYLE_ICON_FLAT)
        self.viewport_menu = self._menu_for(self.viewport_button)
        self.viewport_menu.aboutToShow.connect(self._fill_viewport_menu)
        t.addWidget(self.viewport_button)
        self.view_buttons = QButtonGroup(self)
        for key, icon, text in (("list", "list", "List"), ("grid", "layout-grid", "Grid")):
            b = self._icon_button(icon, f"{text}: show the loaders as a {text.lower()}", STYLE_ICON_FLAT)
            b.setCheckable(True)
            b.setObjectName(f"view_{key}")
            b.clicked.connect(lambda _=False, k=key: self.set_view(k))
            self.view_buttons.addButton(b)
            t.addWidget(b)
        self.load_button = self._icon_button("plus", "Add: load a shot, or add assets", STYLE_ICON_FLAT)
        self.load_menu = self._menu_for(self.load_button)
        t.addWidget(self.load_button)
        left_lay.addWidget(top)
        self.nav_row, self._nav_layout = self._bar()
        self.nav_row.setObjectName("nav_row")
        self._nav_layout.setContentsMargins(self.px(10), 0, self.px(16), self.px(6))
        self.nav_row.hide()
        left_lay.addWidget(self.nav_row)
        left_lay.addWidget(self._line())


        # Status line: what the primary does, how many loaders; the heavy-shot note on the right
        status, st = self._bar()
        status.setObjectName("status")
        st.setContentsMargins(self.px(16), self.px(8), self.px(16), self.px(8))
        self.headline = self._label("", FS_META)
        self.status_meta = self._label("", FS_META, color=TEXT_LABEL)
        self.status_meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.heavy_label = self._label("", FS_SMALL, color=STATUS_COLORS[AM_WARN])
        self.heavy_label.setToolTip("Estimated viewport polygons of the subdivided meshes (faces x 16)")
        for lab in (self.headline, self.heavy_label):  # wrapped until resizeEvent knows the width: a label
            lab.setWordWrap(True)                        # that does not wrap sets the window's minimum width
        self.hulls_link = QPushButton("Hulls only")
        self.hulls_link.setStyleSheet(self.css(STYLE_LINK))
        self.hulls_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hulls_link.setToolTip("The /stage viewports draw hulls: lighter to draw and less memory")
        self.hulls_link.clicked.connect(self._hulls)
        self.gap_label = self._label("", FS_META, color=TEXT_LABEL)
        self.gap_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.gap_link = QPushButton("Add")
        self.gap_link.setStyleSheet(self.css(STYLE_LINK))
        self.gap_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gap_link.setToolTip("A loader for each output of the shot's newest anim version that the scene lacks")
        self.gap_link.clicked.connect(self._run(self.ctl.add_missing))
        self.gap_link.setMinimumHeight(self.px(24))  # a 24 px target (WCAG 2.5.8)
        self.weight_label = self._label("", FS_SMALL, color=TEXT_LABEL)
        self.weight_label.setToolTip("Textures: the files the lookdevs pull (UDIM tiles too), read from the publishes")
        self.weight_icon = QLabel()
        self.weight_icon.setPixmap(_lucide_pixmap("image", self.px(14), TEXT_LABEL))
        self.weight_icon.setToolTip(self.weight_label.toolTip())
        # what the viewport shows now, in words (Monos: state is read, not a toggle that hides what it wrote)
        self.view_state = self._label("", FS_SMALL, color=TEXT_LABEL)
        self.solo_off = QPushButton("Show all")
        self.solo_off.setStyleSheet(self.css(STYLE_LINK))
        self.solo_off.setCursor(Qt.CursorShape.PointingHandCursor)
        self.solo_off.setMinimumHeight(self.px(24))
        self.solo_off.setToolTip("End the solo: every loader in the viewport again")
        self.solo_off.clicked.connect(self._run(self.ctl.toggle_solo))
        st.addWidget(self.headline)
        st.addWidget(self.status_meta)
        st.addWidget(self.gap_label, 1)
        st.addWidget(self.gap_link)
        st.addWidget(self.view_state)
        st.addWidget(self.solo_off)
        st.addWidget(self.weight_icon)
        st.addWidget(self.weight_label)
        st.addWidget(self.heavy_label)
        st.addWidget(self.hulls_link)
        left_lay.addWidget(status)
        left_lay.addWidget(self._line())

        self.stack = QStackedWidget()
        self.list_view = self._view(grid=False)
        self.grid_view = self._view(grid=True)
        self.stack.addWidget(self.list_view)
        self.stack.addWidget(self.grid_view)
        self.empty = self._label("No loaders in the scene yet. Pick a shot and press Load shot, or put down a "
                                 "MonoFX Loader (Tab > MonoFX).", FS_BODY,
                                 color=TEXT_LABEL)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack.addWidget(self.empty)
        from PySide6.QtWidgets import QSplitter

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(self.px(4))
        self.split.setStyleSheet(f"QSplitter::handle {{ background: {LINE}; }}"
                                 f"QSplitter::handle:hover {{ background: {TEXT_META}; }}")
        left_lay.addWidget(self.stack, 1)
        self.split.addWidget(self.left)
        self.subd_panel = InspectorPanel(self)
        self.subd_clip = _SlideClip(self.subd_panel)  # the inspector slides in this from the right edge
        self.subd_clip.setMinimumWidth(1)  # set by resizeEvent: 360 beside the list, free when stacked
        self.subd_clip.hide()  # only while a loader is selected
        self.subd_panel.hide()
        self.split.addWidget(self.subd_clip)
        self.drawer = AddDrawer(self)
        self.drawer.hide()
        self.split.addWidget(self.drawer)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)  # the inspector keeps its width; the list takes the rest
        root.addWidget(self.split, 1)

        root.addWidget(self._line())
        self.result = self._label("", FS_META, color=TEXT_LABEL)
        self.result.setWordWrap(True)
        self.result.setMaximumHeight(self.px(44))  # two lines at most: a long result never pushes the bar up
        self.result.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.result_row, self._result_layout = self._bar()
        self._result_layout.setContentsMargins(self.px(16), self.px(8), self.px(16), 0)
        self.result_row.hide()
        root.addWidget(self.result_row)
        bar, b = self._bar()
        bar.setObjectName("actions")
        self._actions_layout = b
        b.addWidget(self.result, 1)  # the result line beside the buttons (above them when narrow)
        b.addStretch(0)  # keeps the buttons right when the result line moves above them
        self.handoff_button = self._icon_button("package", "Hand off: a self-contained package of the selected "
                                                "loaders (else every one) for people without MonoFX: one USD each, "
                                                "textures copied, paths relative")
        self.handoff_menu = self._menu_for(self.handoff_button)
        self.handoff_menu.aboutToShow.connect(self._fill_handoff_menu)
        self.handoff_button.setStyleSheet(self.handoff_button.styleSheet()
                                          + "QPushButton::menu-indicator { image: none; width: 0px; }")
        self.handoff_button.setToolTip("Hand off: a USD package for any app, or the loaders baked to plain Houdini "
                                       "nodes (no MonoFX needed)")
        self.undo_button = self._icon_button("undo", "Undo: Houdini's undo of the last change")
        self.undo_button.clicked.connect(self._undo)
        self.retarget_button = self._button("", STYLE_GHOST)
        self.retarget_button.setToolTip("Move loaders copied from another shot to the shot in the top bar: "
                                        "newest anim there, groom / cloth from there, lookdev and settings kept")
        self.retarget_button.clicked.connect(self._run(lambda: self.ctl.retarget()))
        self.retarget_button.hide()
        self.upgrade_button = self._icon_button("circle-up", "Upgrade", text=" ")
        self.upgrade_button.setToolTip("Change Anim Loader 2.1 and Character Loader 3.2 nodes to 2.2, keeping "
                                       "their settings")
        self.upgrade_button.clicked.connect(self._run(self.ctl.upgrade_all))
        self.primary = self._button("", STYLE_PRIMARY)
        self.primary.setToolTip("The one thing worth doing now")
        self.primary.clicked.connect(self._run(self.ctl.primary))
        for w in (self.handoff_button, self.undo_button, self.retarget_button, self.upgrade_button, self.primary):
            b.addWidget(w)
        root.addWidget(bar)

    def _crumb(self, text: str, tip: str, strong: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(self.css(
            f"QPushButton {{ background: transparent; border: none; border-radius: 6px; padding: 5px 7px;"
            f" color: {TEXT_PRIMARY if strong else TEXT_LABEL}; font-size: {FS_META}px;"
            f" font-weight: {600 if strong else 400}; }}"
            f"QPushButton:hover {{ background: {BG_HOVER}; color: {TEXT_PRIMARY}; }}"
            f"QPushButton:pressed {{ background: {SELECTED}; }}"
            f"QPushButton::menu-indicator {{ image: none; width: 0px; }}"))
        b.setMinimumHeight(self.px(28))
        return b

    def _menu_for(self, button: QPushButton) -> QMenu:
        menu = QMenu(button)
        menu.setStyleSheet(self.css(STYLE_MENU_SQ))
        button.setMenu(menu)
        if button is self.__dict__.get("load_button"):
            button.setStyleSheet(button.styleSheet() + "QPushButton::menu-indicator { image: none; width: 0px; }")
        return menu

    def _line(self) -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {LINE};")
        return line

    def _view(self, grid: bool) -> QListWidget:
        v = QListWidget()
        v.setObjectName("grid" if grid else "list")
        v.setStyleSheet(f"QListWidget {{ background: {BG_APP}; border: none; outline: none; }}")
        v.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        v.setMouseTracking(True)
        v.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        v.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if grid
                                       else Qt.ScrollBarPolicy.ScrollBarAsNeeded)  # the table scrolls sideways
        v.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        if grid:
            v.setViewMode(QListView.ViewMode.IconMode)
            v.setResizeMode(QListView.ResizeMode.Adjust)
            v.setMovement(QListView.Movement.Static)
            v.setWrapping(True)
            v.setSpacing(0)
            v.setContentsMargins(self.px(10), 0, self.px(10), 0)
            v.setItemDelegate(_GridDelegate(self._paint, v, v))
        else:
            delegate = _ListDelegate(self._paint, v, v)
            v.setItemDelegate(delegate)
            v.setViewportMargins(0, self.px(30), 0, 0)  # room for the sticky column header
            self.column_header = _ColumnHeader(v, delegate, self._paint)
            v.horizontalScrollBar().valueChanged.connect(lambda _v: self.column_header.update())
        v.viewport().installEventFilter(self)  # rows / cards follow the view's own width (the splitter moves it)
        v.itemSelectionChanged.connect(lambda view=v: self._selection_changed(view))
        v.itemDoubleClicked.connect(self._select_node)
        v.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        v.customContextMenuRequested.connect(lambda pos, view=v: self._menu(view, pos))
        return v

    # --- state ---------------------------------------------------------------------------------
    def set_view(self, key: str) -> None:
        key = key if key in ("list", "grid") else "list"
        for b in self.view_buttons.buttons():
            b.setChecked(b.objectName() == f"view_{key}")
        self._view_key = key
        self.prefs["view"] = key
        _save_prefs(self.prefs)
        self._show_rows()

    def current_view(self) -> QListWidget:
        return self.grid_view if self._view_key == "grid" else self.list_view

    def refresh(self) -> None:
        """Reads the loaders now (main thread) and scans the disk on the worker thread."""
        token, infos = self.ctl.begin_scan()
        self._pending = (token, self._pool.submit(self.ctl.scan_job, infos))
        self._poll.start()

    def wait(self, timeout: float = 10.0) -> None:
        """Blocks until the pending scan is in (tests and grabs)."""
        if self._pending is not None:
            self._pending[1].result(timeout)
        self._collect()

    def _collect(self) -> None:
        if self._pending is None or not self._pending[1].done():
            return
        token, fut = self._pending
        self._pending = None
        self._poll.stop()
        if fut.exception() is None and self.ctl.finish_scan(token, *fut.result()):
            self._show_rows()

    def _show_rows(self) -> None:
        rows = self.ctl.rows()
        needle = self.filter_edit.text().strip().lower() if hasattr(self, "filter_edit") else ""
        if needle:
            rows = [r for r in rows if needle in r.instance.lower() or needle in (r.asset or "").lower()]
        for view in (self.list_view, self.grid_view):
            keep = {i.data(ROLE_ROW).node_path for i in view.selectedItems() if i.data(ROLE_ROW)}
            view.blockSignals(True)
            view.clear()
            shot = None
            n_in_group = 0
            for row in rows:
                group = row.shot or ("assets" if row.asset_source else "sublayers" if row.kind == "layer"
                                     else "old loaders")
                if group != shot:
                    shot = group
                    n_in_group = 0
                    count = sum(1 for r in rows if (r.shot or ("assets" if r.asset_source else "sublayers"
                                                              if r.kind == "layer" else "old loaders")) == group)
                    h = QListWidgetItem()
                    h.setData(ROLE_HEADER, f"{group}   {count}")
                    h.setFlags(Qt.ItemFlag.NoItemFlags)
                    view.addItem(h)
                item = QListWidgetItem()
                item.setData(ROLE_ROW, row)
                item.setData(ROLE_ZEBRA, n_in_group % 2 == 1)
                n_in_group += 1
                item.setToolTip(self._tooltip(row))
                view.addItem(item)
                item.setSelected(row.node_path in keep)
            view.blockSignals(False)
        self.stack.setCurrentWidget(self.current_view() if rows else self.empty)
        if hasattr(self, "subd_panel"):
            self.ctl.selection = [p for p in self.ctl.selection if any(r.node_path == p for r in rows)]
            self._show_subd()
        self._fill_nav()
        self._update_bar()

    def _tooltip(self, row: Row) -> str:
        if row.legacy:
            return f"{row.node_path}\nAnim Loader 2.1: Upgrade keeps its settings"
        lines = [row.node_path, f"prim /{row.instance}" if row.kind == "geo" else "camera"]
        for part in ALL_PARTS:
            st, newer = row.parts.get(part, (logic.STATUS_OFF, None))
            lines.append(f"{part_word(row, part).title()}: {chip(st, newer, row.versions.get(part, ''))[0]}")
        return "\n".join(lines)

    def _update_bar(self) -> None:
        # One primary, the most important thing to do (retarget > update > upgrade 2.1); the status line says the
        # same. Nothing to do: no primary button at all. The heavy-shot note sits on the status line's right.
        rows = self.ctl.rows()
        action = self.ctl.primary_action()
        self.headline.setText(self.ctl.headline())
        color = (TEXT_LABEL if not rows else STATUS_COLORS[AM_UPDATE] if self.ctl.behind_paths()
                 else STATUS_COLORS[AM_WARN] if action or any(r.needs_asset for r in rows)
                 else STATUS_COLORS[AM_OK])
        self.headline.setStyleSheet(f"color: {color}; background: transparent; font-size: {self.px(FS_META)}px;"
                                    f" font-weight: 400;")
        n = sum(1 for r in rows if not r.legacy)
        self.status_meta.setText(f"   {n} loader{'s' if n != 1 else ''}" if rows else "")
        heavy = self.ctl.heavy_polygons()
        self.heavy_label.setText(f"~{heavy / 1e6:.1f} M polygons, heavy" if heavy else "")
        self.heavy_label.setVisible(bool(heavy))
        self.hulls_link.setVisible(bool(heavy) and hasattr(self.backend, "set_hulls_only"))
        self.primary.setVisible(action is not None)
        if action is not None:
            self.primary.setText(action[1])
            self.primary.setToolTip({
                "retarget": "Move loaders copied from another shot to this shot: newest anim there, groom / cloth "
                            "from there, lookdev and settings kept (one undo step)",
                "update": "Move what is behind to the newest version (one undo step)",
                "upgrade": "Change Anim Loader 2.1 and Character Loader 3.2 nodes to 2.2, keeping their settings "
                           "(one undo step)",
                "hulls": "Draw Hulls Only in the /stage viewports: lighter to draw and less memory",
            }[action[0]])
        n_old = len(self.ctl.legacy_paths())
        self.upgrade_button.setText(str(len(self.ctl.legacy_paths())))  # the icon says upgrade, the tip says it all
        self.upgrade_button.setToolTip(f"{self.ctl.upgrade_label()}: old loaders and publish sublayers become "
                                       "MonoFX Loaders in place, keeping their settings")
        self.upgrade_button.setVisible(n_old > 0 and (action is None or action[0] != "upgrade"))
        self.retarget_button.setText(self.ctl.retarget_label())
        self.retarget_button.setVisible(bool(self.ctl.retarget_paths()) and (action is None or action[0] != "retarget"))
        gap = self.ctl.gap_line()
        self.gap_label.setText(gap)
        self.gap_link.setVisible(bool(gap))
        total = self.ctl.weight_total()
        self.weight_label.setText(logic.size_word(total) if total >= 1e8 else "")
        self.weight_icon.setVisible(bool(self.weight_label.text()) and self.weight_label.isVisibleTo(self))
        bits = []
        if self.ctl.soloed:
            bits.append(f"Solo: {len(self.ctl.soloed)} loader{'s' if len(self.ctl.soloed) != 1 else ''}")
        hidden = [p.title() for p in ("lookdev", "groom") if rows and not self.ctl.viewport_part_on(p)]
        if hidden:
            bits.append(" and ".join(hidden) + " render only")
        self.view_state.setText(", ".join(bits))
        self.solo_off.setVisible(bool(self.ctl.soloed))
        if getattr(self, "_drawer_open", False):  # one primary: the drawer's Add while it is open
            self.primary.setVisible(False)
        msg = self.ctl.message
        self.result.setText(msg if len(msg) <= 140 else msg[:137].rstrip() + "\u2026")  # results only, short
        self.result.setToolTip(getattr(self.ctl, "details", "") or (msg if len(msg) > 140 else ""))
        self.ctl.details = ""

    def _selection_changed(self, view: QListWidget) -> None:
        self.ctl.selection = [i.data(ROLE_ROW).node_path for i in view.selectedItems() if i.data(ROLE_ROW)]
        self._update_bar()
        self._show_subd()

    DIALOG_IN_MS, DIALOG_OUT_MS = 160, 120  # Monos motion tokens: enter faster than exit

    def _show_subd(self) -> None:
        sel = self.ctl.selection[-1] if self.ctl.selection else ""
        row = next((r for r in self.ctl.rows() if r.node_path == sel), None)
        want = row is not None and not getattr(self, "_drawer_open", False)  # for a selection
        if row is not None:
            self.subd_panel.show_row(row)
        self._slide(self.subd_clip, want)
        if row is None:
            self.subd_panel.show_row(None)

    def _slide(self, clip: "_SlideClip", show: bool) -> None:
        """The inspector slides in from the window's right edge (in 160 ms OutCubic) and back out (120 ms InCubic):
        its clip widens or narrows while the panel keeps its full width, so it moves rather than stretches.
        Stacked under the list (narrow) or offscreen, it just shows."""
        panel = clip.panel
        if show == (not clip.isHidden()) and not getattr(clip, "_sliding_out", False):
            panel.setVisible(show)
            return
        anim = getattr(clip, "_slide_anim", None)
        if anim is not None:
            anim.stop()
        horizontal = self.split.orientation() == Qt.Orientation.Horizontal and self.isVisible()
        full = max(self.px(360), clip.width() if not clip.isHidden() else 0)
        if not horizontal:
            clip._sliding_out = False
            clip.full = 0
            clip.setMaximumWidth(16777215)
            clip.setVisible(show)
            panel.setVisible(show)
            return
        # The splitter's sizes are driven frame by frame: a QSplitter does not grow a pane when its maximum width
        # grows, so animating maximumWidth showed nothing and then jumped (the user's report, 2026-11-17)
        anim = QVariantAnimation(self)
        clip._slide_anim = anim
        clip.setMinimumWidth(0)  # the 360 px floor would stop the slide; set again when it ends
        clip.full = full
        panel.setGeometry(0, 0, full, clip.height())
        index = self.split.indexOf(clip)

        def step(value):
            sizes = self.split.sizes()
            w = int(value)
            sizes[0] = max(0, sizes[0] + sizes[index] - w)  # the list gives what the inspector takes
            sizes[index] = w
            self.split.setSizes(sizes)
        anim.valueChanged.connect(step)

        def rest():
            clip.full = 0
            clip.setMaximumWidth(16777215)
            clip.setMinimumWidth(self.px(360))
        if show:
            clip._sliding_out = False
            clip.setMaximumWidth(16777215)
            clip.setVisible(True)
            panel.setVisible(True)
            step(0)
            anim.setDuration(self.DIALOG_IN_MS)
            anim.setStartValue(0)
            anim.setEndValue(full)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(rest)
        else:
            clip._sliding_out = True
            anim.setDuration(self.DIALOG_OUT_MS)
            anim.setStartValue(clip.width())
            anim.setEndValue(0)
            anim.setEasingCurve(QEasingCurve.Type.InCubic)

            def done():
                clip._sliding_out = False
                clip.setVisible(False)
                panel.setVisible(False)
                rest()
            anim.finished.connect(done)
        anim.start()

    def _repaint_views(self) -> None:
        for v in (self.list_view, self.grid_view):
            v.viewport().update()

    NARROW_PX = 640

    def _place_nav(self) -> None:
        """Project and shot crumbs in the top bar, or on a row of their own when the left column (not the window:
        the inspector takes a share of it) leaves them under 560 px."""
        narrow = self.left.width() < self.px(560) if self.left.width() > 1 else self.width() < self.px(self.NARROW_PX)
        if narrow and self.nav_box.parentWidget() is not self.nav_row:
            self._nav_layout.addWidget(self.nav_box, 1)
        elif not narrow and self.nav_box.parentWidget() is self.nav_row:
            self._top_layout.insertWidget(0, self.nav_box, 1)  # first: the title label is gone
        self.nav_row.setVisible(narrow)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize and obj is getattr(self, "left", None):
            self._place_nav()
        if event.type() == QEvent.Type.Resize:
            for v in (getattr(self, "list_view", None), getattr(self, "grid_view", None)):
                if v is not None and obj is v.viewport():
                    QTimer.singleShot(0, v.doItemsLayout)
                    if v is getattr(self, "list_view", None) and hasattr(self, "column_header"):
                        self.column_header.place()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        narrow = self.width() < self.px(self.NARROW_PX)
        self._place_nav()
        self.weight_label.setVisible(not narrow and bool(self.weight_label.text()))  # the tooltip-level detail
        self.weight_icon.setVisible(self.weight_label.isVisible())
        for lab in (self.headline, self.heavy_label, self.gap_label):  # wrap when docked narrow, never widen
            lab.setWordWrap(narrow)
        if narrow and self.result.parentWidget() is not self.result_row:
            self._result_layout.addWidget(self.result, 1)
            self.result.setWordWrap(True)
        elif not narrow and self.result.parentWidget() is self.result_row:
            self._actions_layout.insertWidget(0, self.result, 1)
            self.result.setWordWrap(False)
        self.result_row.setVisible(narrow)
        self.grid_view.doItemsLayout()  # grid headers span the row
        self.list_view.doItemsLayout()  # list rows change height when narrow
        # the inspector sits beside the list, or under it when docked narrow
        narrow_split = self.width() < self.px(760)
        was_vertical = self.split.orientation() == Qt.Orientation.Vertical
        self.split.setOrientation(Qt.Orientation.Vertical if narrow_split else Qt.Orientation.Horizontal)
        if narrow_split and not was_vertical:  # stacked: the list keeps the larger half
            h = max(self.split.height(), self.px(400))
            self.split.setSizes([int(h * 0.55), int(h * 0.45), int(h * 0.45)])
        self.subd_clip.setMinimumWidth(1 if narrow_split else self.px(360))

    # --- commands --------------------------------------------------------------------------------
    def _run(self, fn):
        def go(*_):
            try:
                fn()
            except Exception as exc:  # the result line, never a dialog
                self.ctl.message = f"Failed: {exc}"
            self._show_rows()
            self.refresh()
        return go

    def _run_detail(self, fn, path: str):
        """A write that moves no version (a show toggle): that loader's inspector is worked out again, the list and the
        project are not scanned again (a full refresh made each click ~1 s and held the window)."""
        def go(*_):
            try:
                fn()
                self.ctl.refresh_detail(path)
            except Exception as exc:  # the result line, never a dialog
                self.ctl.message = f"Failed: {exc}"
            self._update_bar()
            self._show_subd()
        return go

    def _fill_viewport_menu(self) -> None:
        """Explicit actions, each saying what it does (Monos menu rules: actions, never hidden state)."""
        m = self.viewport_menu
        m.clear()
        if self.ctl.soloed:
            m.addAction("Show all loaders", self._run(self.ctl.toggle_solo))
        else:
            act = m.addAction("Solo the selected loaders", self._run(self.ctl.toggle_solo))
            act.setEnabled(bool(self.ctl.selection))
        m.addSeparator()
        for part in ("lookdev", "groom"):
            on = self.ctl.viewport_part_on(part)
            m.addAction(f"{'Hide' if on else 'Show'} {part} in the viewport (every loader)",
                        self._run(lambda p=part: self.ctl.toggle_viewport_part(p)))
        if hasattr(self.backend, "set_hulls_only"):
            m.addSeparator()
            m.addAction("Draw hulls only", self._hulls)

    def _link(self, path: str, key: str) -> None:
        {"folder": self.ctl.open_folder, "monos": self.ctl.open_monos, "frame": self.ctl.frame}[key](path)
        self.result.setText(self.ctl.message)

    def open_drawer(self) -> None:
        self.ctl.target_root = self._project
        self.drawer.open(self._project)
        self.subd_clip.hide()
        self.subd_panel.hide()
        self.drawer.show()
        self._drawer_open = True
        self._update_bar()

    def close_drawer(self) -> None:
        self.drawer.hide()
        self._drawer_open = False
        self._show_subd()
        self._update_bar()

    def add_picked(self, names: list[str]) -> None:
        self.ctl.target_root = self._project
        self._run(lambda: self.ctl.add_assets(names))()
        self.close_drawer()

    def _fill_handoff_menu(self) -> None:
        m = self.handoff_menu
        m.clear()
        sel = [r for r in self.ctl.rows() if r.node_path in self.ctl.selection and not r.legacy
               and r.kind in ("geo", "cam")]
        n = f" ({len(sel)})" if sel else " (every loader)"
        m.addAction(f"Hand off as USD{n}\u2026", self._handoff).setToolTip(
            "One USD per loader, textures copied, relative paths: any app opens it")
        m.addSeparator()
        bake = m.addAction(f"Bake to plain nodes{(' (' + str(len(sel)) + ')') if sel else ''}",
                           self._run(lambda: self.ctl.bake([r.node_path for r in sel])))
        bake.setEnabled(bool(sel))
        bake.setToolTip("Each selected loader becomes a plain subnet anyone with Houdini opens; Upgrade restores it")

    def _handoff(self) -> None:
        out = QFileDialog.getExistingDirectory(self, "Hand off to folder", str(Path.home()))
        if out:
            self._run(lambda: self.ctl.handoff(out))()

    def _hulls(self) -> None:
        self.ctl.draw_hulls()
        self._update_bar()
        self._show_subd()

    def _undo(self) -> None:
        undo = getattr(self.backend, "undo", None)
        if undo:
            undo()
        self.ctl.message = "Undone."
        self.refresh()
        self._update_bar()

    def _select_node(self, item: QListWidgetItem) -> None:
        row = item.data(ROLE_ROW)
        if row and getattr(self.backend, "select", None):
            self.backend.select(row.node_path)

    def _menu(self, view: QListWidget, pos) -> None:
        item = view.itemAt(pos)
        menu = self.row_menu(item) if item is not None else None
        if menu is not None:
            menu.exec(view.viewport().mapToGlobal(pos))

    def row_menu(self, item) -> QMenu | None:
        """The right-click menu of a row: its actions (the inspector only shows information)."""
        row: Row | None = item.data(ROLE_ROW) if item else None
        if row is None:
            return None
        menu = QMenu(self)
        menu.setStyleSheet(self.css(STYLE_MENU_SQ))
        menu.addAction("Select node", lambda: self._select_node(item))
        menu.addSeparator()
        if row.kind == "layer":
            sel = self.ctl.layer_paths(self.ctl.selection) if row.node_path in self.ctl.selection else []
            paths = sel or [row.node_path]
            st, newer = row.parts.get(next(iter(row.parts), ""), (logic.STATUS_OFF, None))
            if newer and st == logic.STATUS_NEWER:
                menu.addAction(f"Update to {newer}", self._run(lambda: self.ctl._update([row.node_path])))
            n = f" ({len(paths)})" if len(paths) > 1 else ""
            menu.addAction(f"Upgrade to MonoFX Loader{n}", self._run(lambda: self.ctl.upgrade_paths(list(paths))))
            menu.addSeparator()
            menu.addAction("Open folder", lambda: self._link(row.node_path, "folder"))
            return menu
        if not row.legacy and row.behind:
            news = self.ctl.news(row.node_path)
            label = f"Update to {news[0].part} {news[0].new}" if len(news) == 1 else "Update this loader"
            menu.addAction(label, self._run(lambda: self.ctl._update([row.node_path])))
        if not row.legacy and row.kind == "geo":
            paths = self.ctl.selection if row.node_path in self.ctl.selection else [row.node_path]
            other = "shot" if row.asset_source else "asset"
            n = f" ({len(paths)})" if len(paths) > 1 else ""
            menu.addAction(f"Switch to Source {other.title()}{n}",
                           self._run(lambda: self.ctl.set_source(other, list(paths))))
        if not row.legacy:
            menu.addSeparator()
            menu.addAction("Open folder", lambda: self._link(row.node_path, "folder"))
            if row.kind != "cam":
                menu.addAction("Open in Monos", lambda: self._link(row.node_path, "monos"))
            menu.addAction("Frame in the viewport", lambda: self._link(row.node_path, "frame"))
        if row.legacy:  # an old loader or a baked one: its one action
            menu.addAction("Upgrade to MonoFX Loader", self._run(lambda: self.ctl.upgrade_paths([row.node_path])))
        elif row.kind in ("geo", "cam"):
            paths = self.ctl.selection if row.node_path in self.ctl.selection else [row.node_path]
            n = f" ({len(paths)})" if len(paths) > 1 else ""
            menu.addAction(f"Bake to plain nodes{n}", self._run(lambda: self.ctl.bake(list(paths))))
        target = self.ctl.target_shot
        retarget = not row.legacy and row.shot and target and row.shot != target
        if retarget or row.needs_asset or (not row.legacy and row.kind == "geo"):
            menu.addSeparator()
        if retarget:
            menu.addAction(f"Retarget to {target}", self._run(lambda: self.ctl.retarget([row.node_path])))
        if row.needs_asset or (not row.legacy and row.kind == "geo"):
            sub = menu.addMenu("Asset")
            root = next((i.state.project_root for i in self.ctl._infos if i.path == row.node_path and i.state), "")
            for asset in getattr(self.backend, "assets", lambda r: [])(root):
                sub.addAction(asset, self._run(lambda a=asset: self.ctl.set_asset(row.node_path, a)))
        return menu

    def _projects(self) -> list[str]:
        """The picked project, the scene's, the loaders', then recent ones (prefs), each once."""
        hip_root = getattr(self.backend, "project_and_shot", lambda: ("", ""))()[0]
        loader_roots = [i.state.project_root for i in self.ctl._infos if i.state and i.state.project_root]
        recent = _load_prefs().get("recent_projects", [])
        paths: list[str] = []
        for path in [self._project, hip_root, *loader_roots, *(recent if isinstance(recent, list) else [])]:
            if path and _path_key(path) not in {_path_key(x) for x in paths}:
                paths.append(path)
        return paths

    def _fill_nav(self) -> None:
        """Project and shot crumbs, their menus and the Load shot menu."""
        projects = self._projects()
        self._project = self._project or (projects[0] if projects else "")
        self.project_menu.clear()
        for path in projects:
            act = self.project_menu.addAction(Path(path).name or path)
            act.setCheckable(True)
            act.setChecked(_path_key(path) == _path_key(self._project))
            act.setToolTip(path)
            act.triggered.connect(lambda _=False, x=path: self.pick_project(x))
        if projects:
            self.project_menu.addSeparator()
        self.project_menu.addAction("Browse...").triggered.connect(lambda _=False: self.pick_project(BROWSE))
        self.project_button.setText(f"{Path(self._project).name} \u203a" if self._project else "Pick a project \u203a")
        self.project_button.setToolTip(self._project or "Pick the project to load shots from")

        root = self._project
        guess = getattr(self.backend, "project_and_shot", lambda: ("", ""))()
        shots = set(logic.list_shots(Path(root))) if root else set()
        shots |= {r.shot for r in self.ctl.rows() if r.shot and any(
            i.path == r.node_path and i.state and _path_key(i.state.project_root) == _path_key(root)
            for i in self.ctl._infos)}
        if guess[1] and _path_key(guess[0]) == _path_key(root):
            shots.add(guess[1])
        self.shots = sorted(shots, key=str.lower)
        loaded = [x for x in self.ctl.shots() if x in shots]  # an unsaved scene: the shot its loaders are from
        shot = ((self._picked_shot if self._picked_shot in shots else "") or (guess[1] if guess[1] in shots else "")
                or (loaded[0] if loaded else "") or (self.shots[0] if self.shots else ""))
        self.ctl.scene_shot = guess[1]
        self.ctl.target_shot = shot
        self.ctl.target_root = root
        self.shot_menu.clear()
        for name in self.shots:
            act = self.shot_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(name == shot)
            act.triggered.connect(lambda _=False, x=name: self.pick_shot(x))
        self.shot_button.setText(f"{shot} \u25be" if shot else "No shot")
        self.shot_button.setVisible(bool(root))
        self._fill_load_menu()

    def _fill_load_menu(self) -> None:
        root, shot = self._project, self.ctl.target_shot
        self.versions = list(reversed(logic.list_versions(logic.anim_publish_dir(Path(root), shot)))) \
            if root and shot else []
        self.load_menu.clear()
        self.load_menu.addSection(f"Load shot {shot}" if shot else "Load shot")
        if not self.versions:
            self.load_menu.addAction(f"No anim publish in {shot}" if shot else "Pick a project first").setEnabled(False)
        for i, version in enumerate(self.versions):
            act = self.load_menu.addAction(f"Load {shot} {version}" + (" (newest)" if i == 0 else ""))
            act.triggered.connect(lambda _=False, v=version: self.load_version(v))
        self.load_menu.addSeparator()
        assets = self.load_menu.addAction("Add assets\u2026")
        assets.setToolTip("Pick assets to load on Source Asset (newest model, groom, lookdev)")
        assets.setEnabled(bool(root))
        assets.triggered.connect(self.open_drawer)

    def pick_project(self, path: str) -> None:
        """A project from the menu, or BROWSE: Qt's folder picker; a folder anywhere inside a project finds its
        root, and one inside a shot picks that shot too."""
        shot = ""
        if path == BROWSE:
            folder = QFileDialog.getExistingDirectory(self, "Project folder", self._project)
            found = logic.find_project_root(Path(folder)) if folder else None
            if folder and found is None:
                self.ctl.message = f"{folder} is in no project (a folder with 01_assets and 02_shots)."
                self._update_bar()
                return
            if found is None:
                return
            path = found.as_posix()
            shot = logic.detect_shot(Path(folder).relative_to(found)) or ""
            self._remember_project(path)
        self._project = path
        self._picked_shot = shot
        self._fill_nav()
        self._update_bar()

    def pick_shot(self, shot: str) -> None:
        self._picked_shot = shot
        self._fill_nav()
        self._update_bar()

    @staticmethod
    def _remember_project(root: str) -> None:
        prefs = _load_prefs()
        recent = prefs.get("recent_projects", [])
        prefs["recent_projects"] = logic.remember_project(recent if isinstance(recent, list) else [], root)
        _save_prefs(prefs)

    def load_version(self, version: str) -> None:
        root, shot = self._project, self.ctl.target_shot
        if not (root and shot and version):
            self.ctl.message = "Pick a project and a shot first."
            self._update_bar()
            return
        self._remember_project(root)
        self._run(lambda: self.ctl.load_shot(root, shot, version))()


_WINDOW: AnimLoaderManager | None = None


def open_manager(parent_path: str = "/stage") -> AnimLoaderManager:
    """Opens (or brings back) the one manager window in Houdini. ``parent_path``: the LOP network Load shot
    builds in (the node's own network when opened from a node)."""
    global _WINDOW
    import hou  # noqa: F401

    from apps.houdini.anim_loader_adapter import HoudiniBackend

    if _WINDOW is not None:
        try:
            _WINDOW.ctl.backend.parent_path = parent_path
            _WINDOW.refresh()
            _WINDOW.show()
            _WINDOW.raise_()
            _WINDOW.activateWindow()
            return _WINDOW
        except RuntimeError:  # deleted with Houdini's main window
            _WINDOW = None
    parent = hou.qt.mainWindow()
    _WINDOW = AnimLoaderManager(HoudiniBackend(parent_path), parent, scale=max(0.5, min(3.0, hou.ui.scaledSize(1000) / 1000.0)))
    _WINDOW.setWindowFlag(Qt.WindowType.Window, True)
    _WINDOW.resize(int(1000 * _WINDOW.s), int(640 * _WINDOW.s))
    _WINDOW.show()
    return _WINDOW


# --- heavy-shot prompt (the user's decision, 2026-11-17) ----------------------------------------------
# Non-modal: a modal box would hold Houdini and the MCP bridge (and a farm job) until someone clicks.
# Draw Hulls Only lowers memory too (measured on /stage, Helen catmullClark: RAM 12.8 -> 7.2 GB once settled,
# VRAM +6.7 -> +4.9 GB); scheme none lowers it most (2.5 GB). An earlier "does not lower memory" came from
# measurements where hulls had not reached the /stage viewports.

def prompt_allowed() -> bool:
    return _load_prefs().get("hulls_prompt", True) is not False


class HeavyShotPrompt(QWidget):
    """A small floating panel: the heavy-shot line, Draw Hulls Only, Later, Don't ask again; hides itself."""

    def __init__(self, text: str, on_hulls, parent: QWidget | None = None, hide_after_ms: int = 20000,
                 scale: float = 1.0) -> None:
        from PySide6.QtWidgets import QCheckBox

        css = lambda c: scale_css(c, scale)  # noqa: E731
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("AnimLoaderPrompt")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setStyleSheet(css(f"QWidget#AnimLoaderPrompt {{ background: {BG_RAISED}; border: 1px solid {LINE};"
                               f" border-radius: 10px; }}" + STYLE_MENU))
        self._on_hulls = on_hulls
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        title = QLabel(text)
        title.setWordWrap(True)
        title.setStyleSheet(css(f"color: {TEXT_PRIMARY}; font-size: {FS_META}px; font-weight: 600; background: transparent;"))
        lay.addWidget(title)
        hint = QLabel("The viewport may be slow and use a lot of memory. Draw Hulls Only draws the unsubdivided "
                      "cages: lighter and less memory (Helen 12.8 GB -> 7.2 GB).")
        hint.setWordWrap(True)
        hint.setStyleSheet(css(f"color: {TEXT_LABEL}; font-size: {FS_SMALL}px; background: transparent;"))
        lay.addWidget(hint)
        row = QHBoxLayout()
        self.dont_ask = QCheckBox("Don't ask again")
        self.dont_ask.setStyleSheet(css(f"color: {TEXT_LABEL}; font-size: {FS_SMALL}px; background: transparent;"))
        row.addWidget(self.dont_ask)
        row.addStretch(1)
        self.later_button = QPushButton("Later")
        self.later_button.setStyleSheet(css(STYLE_GHOST))
        self.hulls_button = QPushButton("Draw Hulls Only")
        self.hulls_button.setStyleSheet(css(STYLE_PRIMARY))
        for b in (self.later_button, self.hulls_button):
            row.addWidget(b)
        lay.addLayout(row)
        self.later_button.clicked.connect(self._close)
        self.hulls_button.clicked.connect(self._hulls)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(hide_after_ms)
        self._timer.timeout.connect(self._close)
        self.setMinimumWidth(round(380 * scale))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def _remember(self) -> None:
        if self.dont_ask.isChecked():
            prefs = _load_prefs()
            prefs["hulls_prompt"] = False
            _save_prefs(prefs)

    def _close(self) -> None:
        self._remember()
        self.hide()

    def _hulls(self) -> None:
        self._remember()
        try:
            self._on_hulls()
        finally:
            self.hide()


_PROMPT: HeavyShotPrompt | None = None


def show_heavy_shot_prompt(text: str, on_hulls) -> None:
    """Shows the prompt at the bottom right of Houdini's main window (Houdini only, with a UI)."""
    global _PROMPT
    import hou

    if not hou.isUIAvailable() or not prompt_allowed():
        return
    main = hou.qt.mainWindow()
    if _PROMPT is not None:
        try:
            _PROMPT.close()
        except RuntimeError:
            pass
    _PROMPT = HeavyShotPrompt(text, on_hulls, main, scale=max(0.5, min(3.0, hou.ui.scaledSize(1000) / 1000.0)))
    _PROMPT.adjustSize()
    geo = main.geometry()
    _PROMPT.move(geo.right() - _PROMPT.width() - 24, geo.bottom() - _PROMPT.height() - 48)
    _PROMPT.show()


# --- subdivision column (the user's pick, 2026-11-17: option A, a detail column beside List / Grid) ----------

SCHEME_WORD = {"publish": "Publish", "none": "Off", "catmullClark": "Catmull-Clark"}
WORD_SCHEME = {v: k for k, v in SCHEME_WORD.items()}
ROLE_PATTERN = Qt.ItemDataRole.UserRole + 20
ROLE_PRIM = Qt.ItemDataRole.UserRole + 21  # the prim type of a meshes-table row: "xform" (a group) or "mesh"


def subd_chip(row: Row) -> str:
    """The row's subdivision chip: "subd 26 · ~9.9 M" (meshes subdivided, estimated viewport polygons)."""
    if not row.subd:
        return ""
    n, polys = row.subd
    return f"subd {n}, ~{polys / 1e6:.1f} M"


def _faces_word(n: int) -> str:
    return f"{n / 1000:.1f}k" if n < 1_000_000 else f"{n / 1e6:.2f} M"


class _Props(QWidget):
    """Rows of label and value, the label column in TEXT_LABEL, the value in TEXT_PRIMARY (or a status colour);
    the user's ask, 2026-11-17: details as a list, never joined by dots."""

    def __init__(self, owner) -> None:
        from PySide6.QtWidgets import QGridLayout

        super().__init__()
        self.owner = owner
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(owner.px(12))
        self.grid.setVerticalSpacing(owner.px(4))
        self.grid.setColumnStretch(1, 1)

    def set_rows(self, rows: list[tuple[str, str, str]]) -> None:
        """(label, value, colour) rows; "" colour = TEXT_PRIMARY."""
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:  # off at once: taken out of the grid it stayed painted over the new rows until deleted
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for i, (label, value, color) in enumerate(rows):
            k = self.owner._label(label, FS_SMALL, color=TEXT_LABEL)
            k.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            v = self.owner._label(value, FS_SMALL, color=color or TEXT_PRIMARY)
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grid.addWidget(k, i, 0)
            self.grid.addWidget(v, i, 1)
        self.setVisible(bool(rows))

    def rows(self) -> dict[str, str]:
        """{label: value} as shown (tests)."""
        out = {}
        for i in range(self.grid.rowCount()):
            k, v = self.grid.itemAtPosition(i, 0), self.grid.itemAtPosition(i, 1)
            if k and v and k.widget() and v.widget():
                out[k.widget().text()] = v.widget().text()
        return out


class _Section(QPushButton):
    """A section title that folds the widget under it: chevron + caps label, flat. Folded or open is view state,
    kept per viewer in the prefs (``inspector_<key>``), never in the scene."""

    def __init__(self, owner, title: str, key: str, body: QWidget) -> None:
        super().__init__(title.upper())
        self.owner, self.key, self.body = owner, key, body
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setChecked(_load_prefs().get(f"inspector_{key}", True) is not False)
        self.setStyleSheet(owner.css(
            f"QPushButton {{ background: transparent; border: none; color: {TEXT_LABEL}; text-align: left;"
            f" padding: 2px 0px; font-size: {FS_SMALL}px; letter-spacing: 1px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRIMARY}; }}"))
        self.setMinimumHeight(owner.px(24))
        self.setIconSize(QSize(owner.px(14), owner.px(14)))
        self.toggled.connect(self._toggled)
        self._paint_icon()

    def _paint_icon(self) -> None:
        self.setIcon(_crisp_icon("chevron-down" if self.isChecked() else "chevron-right", self.owner.px(14),
                                 TEXT_LABEL))
        self.setToolTip("Fold this section" if self.isChecked() else "Show this section")

    def _toggled(self, on: bool) -> None:
        prefs = _load_prefs()
        prefs[f"inspector_{self.key}"] = on
        _save_prefs(prefs)
        self._paint_icon()
        self.apply()

    def apply(self, has_rows: bool | None = None) -> None:
        """Shows the body when open and it has something; the title shows whenever the body has rows."""
        if has_rows is not None:
            self._has = has_rows
        has = getattr(self, "_has", True)
        self.setVisible(has)
        self.body.setVisible(has and self.isChecked())


def _mesh_tree_class():
    """A tree that paints its own rows: Houdini 22's style paints a tree's rows grey (#303030 / #3a3a3a) whatever
    its palette or alternate-background-color says, a style sheet ``::item`` background beats an item's own, and an
    all but transparent one wiped what was under it (measured in the live window; offscreen shows none of it). So, as
    the main list does, a delegate paints every cell (row colour, hover, lines, elided text), the branch area gets the
    row's colour and a chevron, and no ``::item`` rule is left for Houdini's style to act on."""
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QStyle, QTreeWidget

    class _MeshDelegate(QStyledItemDelegate):
        def __init__(self, tree, px):
            super().__init__(tree)
            self.tree, self.px = tree, px

        def paint(self, painter, option, index):  # noqa: D102
            painter.save()
            color = QColor(self.tree._row_color(index))
            if option.state & QStyle.StateFlag.State_MouseOver:
                color = color.lighter(125) if color.name() != BG_APP else QColor(BG_HOVER)
            r = option.rect
            painter.fillRect(r, color)
            painter.setPen(QPen(QColor(LINE), 1))
            if index.column() not in TOGGLE_COLS:  # the toggles sit together, no lines between them
                painter.drawLine(r.right(), r.top(), r.right(), r.bottom())
            painter.drawLine(r.left(), r.bottom(), r.right(), r.bottom())
            fg = index.data(Qt.ItemDataRole.ForegroundRole)
            painter.setPen(fg.color() if fg is not None else QColor(TEXT_PRIMARY))
            painter.setFont(option.font)
            align = index.data(Qt.ItemDataRole.TextAlignmentRole)
            align = Qt.AlignmentFlag(align) if align else Qt.AlignmentFlag.AlignLeft
            toggle = index.data(ROLE_TOGGLE) if index.column() in TOGGLE_COLS else None
            if toggle:  # the eye, viewport and render toggles (Blender's outliner)
                name, col, own, dim = toggle
                size = self.px(13)  # smaller than the prim icon (the user's ask)
                cx, cy = r.center().x(), r.center().y() - self.px(2)
                if dim:  # under a hidden parent: it keeps its own setting for when the parent shows again
                    painter.setOpacity(0.4)
                ratio = painter.device().devicePixelRatioF() if painter.device() else 1.0
                pm = (_filled_pixmap(name, size, col, max(2.0, ratio)) if name in _FILLED
                      else _crisp_icon(name, size, col).pixmap(size))
                painter.drawPixmap(cx - size // 2 + 1, cy - size // 2 + 1, pm)
                if own:  # this shot overrides it: a dot under the icon (what Remove the shot's overrides takes off)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(col))
                    d = self.px(4)
                    painter.drawEllipse(cx - d // 2 + 1, cy + size // 2 + self.px(2), d, d)
                painter.restore()
                return
            text_rect = r.adjusted(self.px(6), 0, -self.px(6), 0)
            kind = index.data(ROLE_PRIM) if index.column() == 0 else None
            if kind:  # the prim's icon before its name, as in Houdini's Scene Graph Tree
                size = self.px(16)
                painter.drawPixmap(text_rect.left(), r.center().y() - size // 2 + 1, _prim_icon(kind, size))
                text_rect.setLeft(text_rect.left() + size + self.px(6))
            text = option.fontMetrics.elidedText(str(index.data() or ""), Qt.TextElideMode.ElideRight,
                                                 text_rect.width())
            painter.drawText(text_rect, align | Qt.AlignmentFlag.AlignVCenter, text)
            painter.restore()

        def sizeHint(self, option, index):  # noqa: N802 (Qt)
            w = option.fontMetrics.horizontalAdvance(str(index.data() or "")) + self.px(14)
            if index.column() == 0 and index.data(ROLE_PRIM):
                w += self.px(22)
            return QSize(w, self.px(28))

    from PySide6.QtWidgets import QHeaderView

    class _MeshHeader(QHeaderView):
        def paintSection(self, painter, rect, logical):  # noqa: N802 (Qt)
            if logical in TOGGLE_COLS:  # the toggles' header: the band and the line under it, nothing between them
                painter.save()
                painter.fillRect(rect, QColor(MESH_BAND))
                painter.setPen(QPen(QColor(LINE), 1))
                painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
                painter.restore()
                return
            super().paintSection(painter, rect, logical)

    class _MeshTree(QTreeWidget):
        on_toggle = None  # (item, column): set by the panel

        def __init__(self):
            super().__init__()
            self.setHeader(_MeshHeader(Qt.Orientation.Horizontal, self))

        def set_px(self, px) -> None:
            self.setItemDelegate(_MeshDelegate(self, px))
            self.setMouseTracking(True)

        def mousePressEvent(self, event):  # noqa: N802 (Qt)
            index = self.indexAt(event.position().toPoint())
            if (event.button() == Qt.MouseButton.LeftButton and index.isValid() and index.column() in TOGGLE_COLS
                    and index.data(ROLE_TOGGLE) and self.on_toggle is not None):
                self.on_toggle(self.itemFromIndex(index), index.column())
                event.accept()
                return
            super().mousePressEvent(event)

        def mouseDoubleClickEvent(self, event):  # noqa: N802 (Qt): a quick second click toggles again, no expand
            index = self.indexAt(event.position().toPoint())
            if index.isValid() and index.column() in TOGGLE_COLS:
                self.mousePressEvent(event)
                return
            super().mouseDoubleClickEvent(event)

        def _row_color(self, index) -> str:
            # one background (the user's ask, "too many colours"): no zebra, no band per group level; a group reads
            # as one by its quieter text and chevron, a selected row by the selection colour
            return SELECTED if self.selectionModel().isSelected(index) else BG_APP

        def drawRow(self, painter, option, index):  # noqa: N802 (Qt)
            painter.fillRect(option.rect, QColor(self._row_color(index)))
            super().drawRow(painter, option, index)

        def drawBranches(self, painter, rect, index):  # noqa: N802 (Qt)
            painter.fillRect(rect, QColor(self._row_color(index)))
            if not self.model().hasChildren(index):
                return
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(TEXT_LABEL), max(1.2, self.indentation() / 10)))
            c = rect.center()
            cx = rect.right() - self.indentation() / 2 + 1
            s = self.indentation() / 5
            path = QPainterPath()
            if self.isExpanded(index):  # v
                path.moveTo(cx - s, c.y() - s / 2)
                path.lineTo(cx, c.y() + s / 2)
                path.lineTo(cx + s, c.y() - s / 2)
            else:  # >
                path.moveTo(cx - s / 2, c.y() - s)
                path.lineTo(cx + s / 2, c.y())
                path.lineTo(cx - s / 2, c.y() + s)
            painter.drawPath(path)
            painter.restore()

    return _MeshTree


COLS = 8  # the inspector's prim table: PRIM, FACES, FROM, SCHEME, DICE, then the eye, viewport, render toggles
TOGGLE_COLS = {5: "eye", 6: "viewport", 7: "render"}


def TOGGLE_W(owner) -> int:  # noqa: N802: a toggle column's width, the icon and a little air
    return owner.px(21)


ROLE_TOGGLE = Qt.ItemDataRole.UserRole + 22  # (icon, colour) of a toggle cell
ROLE_SHOW = Qt.ItemDataRole.UserRole + 23    # the row's logic.PrimShow


class _CamEdit(QWidget):
    """The camera's settings the loader holds (layout B, the user's pick 2026-11-17): parm rows, label left, fields
    right; Enter or leaving a field sets the node's parm, one undo step each."""

    ROWS = (("Clipping", ("clippingRange1", "clippingRange2"), "to", "m"),
            ("Aperture", ("horizontalAperture",), "", "mm"),
            ("Ratio", ("aspectratiox", "aspectratioy"), ":", ""),
            ("Guide scale", ("xn__houdiniguidescale_s3a",), "", ""))

    def __init__(self, owner) -> None:
        from PySide6.QtWidgets import QGridLayout, QLineEdit

        super().__init__()
        self.owner, self.path, self.fields = owner, "", {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, owner.px(2), 0, owner.px(4))
        grid.setHorizontalSpacing(owner.px(12))
        grid.setVerticalSpacing(owner.px(6))
        grid.setColumnStretch(1, 1)
        style = owner.css(f"QLineEdit {{ background: {BG_APP}; color: {TEXT_PRIMARY}; border: 2px solid #2c2c33;"
                          f" border-radius: 6px; padding: 2px 6px; font-size: {FS_SMALL}px; }}"
                          f"QLineEdit:focus {{ border-color: {ACCENT}; }}")
        for i, (label, names, joint, unit) in enumerate(self.ROWS):
            grid.addWidget(owner._label(label, FS_SMALL, color=TEXT_LABEL), i, 0)
            row = QHBoxLayout()
            row.setSpacing(owner.px(6))
            for j, name in enumerate(names):
                if j:
                    row.addWidget(owner._label(joint, FS_SMALL, color=TEXT_LABEL))
                edit = QLineEdit()
                edit.setObjectName(name)
                edit.setStyleSheet(style)
                edit.setFixedWidth(owner.px(84))
                edit.setAlignment(Qt.AlignmentFlag.AlignRight)
                edit.setAccessibleName(f"{label} {j + 1}" if len(names) > 1 else label)
                edit.editingFinished.connect(lambda n=name, lab=label, e=edit: self._set(n, lab, e))
                self.fields[name] = edit
                row.addWidget(edit)
            if unit:
                row.addWidget(owner._label(unit, FS_SMALL, color=TEXT_LABEL))
            row.addStretch(1)
            grid.addLayout(row, i, 1)

    def load(self, path: str, values: dict) -> None:
        self.path = path
        for name, edit in self.fields.items():
            edit.blockSignals(True)
            edit.setText(_num(values[name]).replace(",", "") if name in values else "")
            edit.setEnabled(name in values)
            edit.blockSignals(False)
        self._values = dict(values)

    def _set(self, name: str, label: str, edit) -> None:
        try:
            value = float(edit.text().replace(",", ""))
        except ValueError:
            edit.setText(_num(self._values.get(name, 0)).replace(",", ""))
            return
        if self.path and abs(value - self._values.get(name, value + 1)) > 1e-12:
            self._values[name] = value
            path = self.path
            self.owner._run(lambda: self.owner.ctl.set_camera_parm(path, name, label.lower(), value))()


class InspectorPanel(QWidget):
    """The selected loader (shown only while one is selected): name, node and versions, then its meshes by group
    with faces, where the scheme comes from (only where it differs from the group), scheme and dicing (that column
    only when some mesh has dicing). Read-only; the meshes' right-click menu sets the scheme (on a selected row: the
    whole selection), dicing, clears overrides, applies them to every instance. Each change is one undo step."""

    def __init__(self, owner, parent=None) -> None:
        from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTreeWidget

        super().__init__(parent)
        self.owner = owner
        self.path = ""
        self.asset = ""
        lay = QVBoxLayout(self)
        # the meshes table runs edge to edge (the user's ask: no strips beside it); the rest keeps its side margins
        side = owner.px(14)
        lay.setContentsMargins(0, owner.px(12), 0, 0)  # the table runs down to the action bar
        lay.setSpacing(owner.px(4))
        head = QWidget()
        top = QVBoxLayout(head)
        top.setContentsMargins(side, 0, side, 0)
        top.setSpacing(owner.px(4))
        lay.addWidget(head)
        self.title = owner._label("", 15, QFont.Weight.DemiBold)  # the one bold line of the inspector
        self.title.setWordWrap(True)
        top.addWidget(self.title)
        top.addSpacing(owner.px(6))
        self.details = _Props(owner)  # node, kind, shot / asset, versions, textures, subdivision
        self.details_head = _Section(owner, "Details", "details", self.details)
        top.addWidget(self.details_head)
        top.addWidget(self.details)
        top.addSpacing(owner.px(6))
        self.news = _Props(owner)  # which part, version, published, by, what changed
        self.news_head = _Section(owner, "Newer version", "news", self.news)
        top.addWidget(self.news_head)
        top.addWidget(self.news)
        top.addSpacing(owner.px(6))
        self.cam_edit = _CamEdit(owner)  # clipping, aperture, ratio, guide scale: the loader's own camera settings
        self.cam_head = _Section(owner, "On the loader", "camera", self.cam_edit)
        top.addWidget(self.cam_head)
        top.addWidget(self.cam_edit)
        self.cam_head.apply(False)
        lay.addSpacing(owner.px(6))
        self.tree = _mesh_tree_class()()
        self.tree.setObjectName("subdTree")
        self.tree.setColumnCount(COLS)
        self.tree.setHeaderLabels(["PRIM", "FACES", "FROM", "SCHEME", "DICE", "", "", ""])
        self.tree.headerItem().setTextAlignment(0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col in range(1, COLS):
            self.tree.headerItem().setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
        for col, (name, tip) in {5: ("eye", "Show or hide (visibility): hiding a prim hides what is under it"),
                                 6: ("monitor", "Drawn in the viewport (purpose)"),
                                 7: ("camera", "Rendered by Karma (purpose)")}.items():
            self.tree.headerItem().setToolTip(col, tip)  # no icon in the header (the user's ask): the rows show them
        self.tree.on_toggle = self._toggle
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.set_px(owner.px)
        self.tree.setIndentation(owner.px(14))  # the names need the room more than the tree lines
        self.tree.setAlternatingRowColors(False)  # zebra: set on the mesh items (Houdini ignores the palette)
        self.tree.setStyleSheet(owner.css(
            f"QTreeWidget#subdTree {{ background: {BG_APP};"
            f" color: {TEXT_PRIMARY}; border: none; font-size: {FS_SMALL}px; outline: none; }}"
            # the scroll bars sit inside the table, thin, on its own colour, and show only when needed
            f"QTreeWidget#subdTree QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; border: none; }}"
            f"QTreeWidget#subdTree QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px;"
            f" border: none; }}"
            f"QTreeWidget#subdTree QScrollBar::handle {{ background: {LINE}; border-radius: 2px; min-height: 24px;"
            f" min-width: 24px; }}"
            f"QTreeWidget#subdTree QScrollBar::handle:hover {{ background: {TEXT_META}; }}"
            f"QTreeWidget#subdTree QScrollBar::add-line, QTreeWidget#subdTree QScrollBar::sub-line"
            f" {{ width: 0; height: 0; border: none; background: none; }}"
            f"QTreeWidget#subdTree QScrollBar::add-page, QTreeWidget#subdTree QScrollBar::sub-page"
            f" {{ background: none; }}"
            f"QTreeWidget#subdTree QAbstractScrollArea::corner {{ background: {BG_APP}; }}"
            f"QTreeWidget#subdTree QHeaderView::section {{ background: {MESH_BAND}; color: {TEXT_LABEL};"
            f" border: none; border-right: 1px solid {LINE}; border-bottom: 1px solid {LINE}; padding: 6px 4px;"
            f" font-size: {FS_SMALL}px; letter-spacing: 1px; }}"))
        self.tree.viewport().setStyleSheet(f"background: {BG_APP};")
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        head = self.tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # drag its edge: the name column's width
        for col in range(1, COLS):
            head.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed if col in TOGGLE_COLS
                                      else QHeaderView.ResizeMode.ResizeToContents)
        for col in TOGGLE_COLS:
            self.tree.setColumnWidth(col, TOGGLE_W(owner))
        for i, col in enumerate(sorted(TOGGLE_COLS)):  # first, before the name (the user's ask): never scrolled away
            head.moveSection(head.visualIndex(col), i)
        self.tree.setTreePosition(0)  # the branches and indentation stay in the name column
        head.setMinimumSectionSize(owner.px(20))  # the toggles are narrow; the name keeps its own minimum
        head.setToolTip("Drag the edge of MESH to widen the name column")
        self._name_width = 0  # the width the artist dragged the name column to (kept across loaders)
        head.sectionResized.connect(lambda i, _old, new: setattr(self, "_name_width", new) if i == 0
                                    and QApplication.mouseButtons() != Qt.MouseButton.NoButton
                                    and not getattr(self, "_filling", False) else None)
        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        lay.addWidget(self.tree, 1)  # the meshes take all the room; without them the stretch below does
        self.hint = owner._label("Right-click meshes to set their scheme or dicing.", FS_SMALL, color=TEXT_LABEL)
        self.hint.setWordWrap(True)
        self.hint.setContentsMargins(side, 0, side, 0)
        lay.addWidget(self.hint)
        lay.addStretch(0)

    def sizeHint(self) -> QSize:
        return QSize(self.owner.px(360), self.owner.px(400))

    def show_row(self, row) -> None:
        from PySide6.QtWidgets import QTreeWidgetItem

        from tools.fx.anim_loader.logic import HEAVY_SUBD_POLYGONS, mesh_groups, subd_polygons

        keep = self._tree_state() if row is not None and row.node_path == self.path else None
        self.tree.clear()
        if row is None:
            self.path = ""
            return
        self.title.setText(row.instance)
        self.asset = row.asset or ""
        self.row_path = row.node_path
        warn, upd, miss = STATUS_COLORS[AM_WARN], STATUS_COLORS[AM_UPDATE], STATUS_COLORS[AM_MISSING]
        rows: list[tuple[str, str, str]] = [("Node", row.node_path.partition("#")[0], "")]
        if row.kind == "layer":
            rows += [("Kind", "Sublayer", ""), ("Reads", row.layer, ""),
                     ("Upgrade", "a MonoFX Loader in its place, the xforms after it follow", TEXT_LABEL)]
        elif getattr(row, "baked", False):
            rows += [("Kind", "Baked loader (plain nodes)", ""),
                     ("Upgrade", "the MonoFX Loader again, from the settings it kept", TEXT_LABEL)]
        elif row.legacy:
            rows += [("Kind", "Old loader", warn),
                     ("Upgrade", "a MonoFX Loader in its place, keeping its settings", TEXT_LABEL)]
        elif row.kind == "cam":
            rows += [("Kind", "Camera", ""), ("Shot", row.shot, "")]
        elif row.asset_source:
            rows += [("Kind", "Asset loader", ""), ("Asset", row.asset or "", "")]
        else:
            rows += [("Kind", "Shot loader", ""), ("Shot", row.shot, ""), ("Asset", row.asset or "asset?",
                                                                            "" if row.asset else warn)]
        for p in (("anim",) if row.kind == "cam" else ALL_PARTS):
            if p not in row.versions and p not in row.parts:
                continue
            st, newer = row.parts.get(p, (logic.STATUS_OFF, None))
            if st == logic.STATUS_OFF and not row.versions.get(p):
                continue
            text, color = chip(st, newer, row.versions.get(p, ""))
            rows.append((part_word(row, p).title(), text.replace("\u2013", "none"),
                         "" if st == logic.STATUS_OK else color))
        tl = self.owner.ctl.timeline(row.node_path) if not row.legacy and row.kind in ("geo", "cam") else None
        if tl is not None:  # a shot's anim: its frame range and fps (the user's ask)
            rows += [("Frames", f"{tl[1]}-{tl[2]}", ""), ("Fps", f"{tl[0]:g}", "")]
        if row.kind == "cam" and not row.legacy:
            cam = self.owner.ctl.camera(row.node_path)
            if cam:
                rows.append(("Camera", cam["prim"].rsplit("/", 1)[-1], ""))
                if cam["focal"] is not None:
                    rows.append(("Focal length", _num(cam["focal"]) + " mm"
                                 + (", animated" if cam["focal_animated"] else ""), ""))
                h, v = cam["h_aperture"], cam["v_aperture"]
                if h and v:
                    rows.append(("Aperture", f"{_num(h)} x {_num(v)} mm, {h / v:.3g}:1", ""))
                if cam["clip"]:
                    rows.append(("Clipping", f"{_num(cam['clip'][0])} to {_num(cam['clip'][1])} m", ""))
                if cam["fstop"]:  # f-stop 0: USD's "no depth of field"
                    rows.append(("F-stop", _num(cam["fstop"]), ""))
                    rows.append(("Focus distance", "none" if cam["focus"] is None else _num(cam["focus"]) + " m", ""))
                else:
                    rows.append(("Depth of field", "off", ""))
        if row.weight >= 1e6:
            rows.append(("Textures", logic.size_word(row.weight), ""))
        detail = self.owner.ctl.subd_detail(row.node_path)
        self.path = row.node_path if detail and detail["plan"] and row.kind not in ("layer", "cam") else ""
        if self.path:
            plan, faces = detail["plan"], detail["faces"]
            polys = subd_polygons(faces, plan)
            n = sum(1 for c in plan.values() if c.scheme != logic.SUBD_NONE)
            rows.append(("Subdivision", f"{n} of {len(plan)} meshes", ""))
            rows.append(("Viewport polygons", f"~{polys / 1e6:.1f} M" + (", heavy" if polys > HEAVY_SUBD_POLYGONS
                                                                        else ""),
                         warn if polys > HEAVY_SUBD_POLYGONS else ""))
        self.details.set_rows(rows)
        self.details_head.apply(bool(rows))
        news = self.owner.ctl.news(row.node_path) if not row.legacy else []
        news_rows: list[tuple[str, str, str]] = []
        for w in news:
            news_rows.append((w.part.title(), f"{w.old} \u2192 {w.new}" if w.old else f"{w.new}, first version", upd))
            if w.date:
                news_rows.append(("Published", w.date, ""))
            if w.author:
                news_rows.append(("Work file by", w.author, ""))
            news_rows += [(k, v, "") for k, v in w.lines]
        self.news.set_rows(news_rows)
        self.news_head.apply(bool(news_rows))
        cam_parms = self.owner.ctl.camera_parms(row.node_path) if row.kind == "cam" and not row.legacy else {}
        self.cam_edit.load(row.node_path, cam_parms)
        self.cam_head.apply(bool(cam_parms))
        self.tree.setVisible(bool(self.path))
        self.hint.setVisible(False)
        self.tree.setToolTip("Right-click a row: subdivision, dicing, hide, render only, viewport only")
        if not self.path:
            return
        plan, faces = detail["plan"], detail["faces"]
        curves = detail.get("curves", {})
        shown = detail.get("shown", {})
        any_dicing = any(c.dicing for c in plan.values())
        # every level of the hierarchy, as the scene graph shows it (the user's ask: Geo > Base_grp > Body_grp >
        # Geo_Body); a group sums its meshes' faces and shows their source / scheme / dicing when they agree.
        # The groom's curves sit under /Groom (the user's ask: "no groom in here")
        tree: dict = {}
        for m in list(plan) + list(curves):
            node = tree
            for part in m.strip("/").split("/"):
                node = node.setdefault(part, {})

        def under(prefix: str) -> list[str]:
            return [m for m in plan if m.strip("/").startswith(prefix + "/")]

        where = {"shot": "set for this shot", "loader": "set on the loader (Hide Prims, Show in Viewport)",
                 "publish": "as published", "": ""}

        def shown_cell(item, prefix: str, parent_word: str = "") -> str:
            """The eye, viewport and render toggles of a row (logic.PrimShow): a shot setting in the accent, a toggle
            under a hidden parent dimmed (it keeps its own setting for when the parent shows again)."""
            ps = shown.get(prefix)
            if ps is None:
                return ""
            item.setData(0, ROLE_SHOW, ps)
            # one look per state (the user's report: blue and white for one state); a dot marks the shot's override,
            # what Remove the shot's overrides takes off (a dot for the publish's or the loader's own value stayed
            # after it, the user's report); dimmed: under a hidden parent; who set a value is in the tooltip
            def color(source):
                return TEXT_LABEL

            pruned = not ps.visible and ps.own_visible
            item.setData(5, ROLE_TOGGLE, ("eye" if ps.own_visible else "eye-off", color(ps.vis_source),
                                          ps.vis_source == "shot", pruned))
            item.setToolTip(5, ("Hidden with its parent; shows again with it" if pruned
                                else "Shown" if ps.own_visible else "Hidden")
                            + (f", its own: {where[ps.vis_source]}" if ps.vis_source else ", as its parent")
                            + ". Click to toggle.")
            item.setData(6, ROLE_TOGGLE, ("monitor" if ps.viewport else "monitor-off", color(ps.purpose_source),
                                          ps.purpose_source == "shot", not ps.visible))
            item.setData(7, ROLE_TOGGLE, ("camera" if ps.render else "camera-off", color(ps.purpose_source),
                                          ps.purpose_source == "shot", not ps.visible))
            tip = f"Purpose {ps.purpose}, " + (f"its own: {where[ps.purpose_source]}" if ps.purpose_source
                                               else "inherited from its parent")
            item.setToolTip(6, ("Drawn in the viewport. " if ps.viewport else "Not drawn in the viewport. ") + tip)
            item.setToolTip(7, ("Rendered. " if ps.render else "Not rendered. ") + tip)
            return ""

        def add(parent, name: str, prefix: str, kids: dict, parent_from: str, parent_word: str = "") -> None:
            if not kids and "/" + prefix in curves:  # groom curves: no subdivision
                item = QTreeWidgetItem([name, f"{_faces_word(curves['/' + prefix])} cv", "", "\u2013", "", "", "", ""])
                item.setData(0, ROLE_PATTERN, prefix)
                item.setData(0, ROLE_PRIM, "basiscurves")
                item.setToolTip(0, "/" + prefix)
                for col in range(1, COLS):
                    item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
                shown_cell(item, prefix, parent_word)
            elif not kids and ("/" + prefix in plan or prefix in plan):  # a mesh
                m = "/" + prefix if "/" + prefix in plan else prefix
                c = plan[m]
                item = QTreeWidgetItem([name, _faces_word(faces.get(m, 0)),
                                        "" if c.source == parent_from else c.source,
                                        SCHEME_WORD.get(c.scheme, c.scheme), f"{c.dicing:g}" if c.dicing else ""])
                item.setData(0, ROLE_PATTERN, prefix)
                item.setData(0, ROLE_PRIM, "mesh")
                item.setToolTip(0, m)
                for col in range(1, COLS):
                    item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
                if c.source == "shot":
                    for col in (2, 3):
                        item.setForeground(col, QColor(ACCENT))
                shown_cell(item, prefix, parent_word)
            else:  # a group
                meshes = under(prefix)
                if meshes:
                    g_from = self._common([plan[m].source for m in meshes])
                    cells = [_faces_word(sum(faces.get(m, 0) for m in meshes)), g_from,
                             self._common([SCHEME_WORD.get(plan[m].scheme, plan[m].scheme) for m in meshes]),
                             self._common([f"{plan[m].dicing:g}" if plan[m].dicing else "" for m in meshes])]
                else:  # curves only (Groom)
                    g_from = ""
                    cvs = sum(n for c, n in curves.items() if c.strip("/").startswith(prefix + "/"))
                    cells = [f"{_faces_word(cvs)} cv", "", "\u2013", ""]
                item = QTreeWidgetItem([name, *cells, "", "", ""])
                item.setData(0, ROLE_PATTERN, prefix + "/**")
                item.setData(0, ROLE_PRIM, "xform")
                item.setToolTip(0, "/" + prefix)
                for col in range(COLS):
                    item.setForeground(col, QColor(TEXT_LABEL))
                    if col:
                        item.setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
                word = shown_cell(item, prefix, parent_word)
                for k, sub in kids.items():
                    add(item, k, prefix + "/" + k, sub, g_from, word)
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)

        for k, sub in tree.items():
            add(None, k, k, sub, "")
        self.tree.setColumnHidden(4, not any_dicing)
        if keep is None:
            self.tree.expandAll()
        else:
            for it in self._all_items():
                it.setExpanded(it.data(0, ROLE_PATTERN) not in keep["folded"])
            self._restore_tree_state(keep)
        self._fit_name()
        QTimer.singleShot(0, self._fit_name)  # again once the tree has its width

    def _fit_name(self) -> None:
        """The name column fills what the other columns leave (never a strip of nothing on the right, never a name
        column squeezed to nothing); dragging its edge wider keeps that width, with a sideways scroll."""
        self._filling = True
        for col in range(1, COLS):
            if col in TOGGLE_COLS:
                self.tree.setColumnWidth(col, TOGGLE_W(self.owner))
            else:
                self.tree.resizeColumnToContents(col)
        rest = sum(self.tree.columnWidth(c) for c in range(1, COLS) if not self.tree.isColumnHidden(c))
        free = self.tree.viewport().width() - rest  # exactly the width: no strip, no sideways scroll
        # names before numbers: the name keeps room for the deepest rows; FACES / FROM / SCHEME scroll sideways
        self.tree.setColumnWidth(0, max(self.owner.px(170), free, self._name_width))
        self._filling = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.tree.topLevelItemCount():
            self._fit_name()

    def _all_items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            yield it
            stack += [it.child(i) for i in range(it.childCount())]

    def _tree_state(self) -> dict:
        """What the artist did to the table: folded groups, selected rows, the current row, the scroll."""
        items = list(self._all_items())
        current = self.tree.currentItem()
        return {"folded": {i.data(0, ROLE_PATTERN) for i in items if i.childCount() and not i.isExpanded()},
                "selected": {i.data(0, ROLE_PATTERN) for i in self.tree.selectedItems()},
                "current": current.data(0, ROLE_PATTERN) if current is not None else None,
                "scroll": (self.tree.verticalScrollBar().value(), self.tree.horizontalScrollBar().value())}

    def _restore_tree_state(self, keep: dict) -> None:
        from PySide6.QtCore import QItemSelectionModel

        self.tree.blockSignals(True)
        for it in self._all_items():
            pattern = it.data(0, ROLE_PATTERN)
            if pattern in keep["folded"]:
                it.setExpanded(False)
            if pattern == keep["current"]:
                self.tree.setCurrentItem(it, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
            if pattern in keep["selected"]:
                it.setSelected(True)
        self.tree.blockSignals(False)
        v, h = keep["scroll"]

        def scroll():
            self.tree.verticalScrollBar().setValue(v)
            self.tree.horizontalScrollBar().setValue(h)

        scroll()
        QTimer.singleShot(0, scroll)  # again once the rows are laid out

    def _items_text(self, col: int):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it.text(col):
                yield it.text(col)
            stack += [it.child(i) for i in range(it.childCount())]

    @staticmethod
    def _common(values: list[str]) -> str:
        return values[0] if values and all(v == values[0] for v in values) else "mixed"

    def patterns_for(self, item) -> list[str]:
        """The right-clicked row, or the whole selection when the row is part of it."""
        selected = self.tree.selectedItems()
        rows = selected if item in selected else [item]
        return [i.data(0, ROLE_PATTERN) for i in rows]

    # the meshes' right-click menu: verbs that say what happens, an icon on every row (the user's ask, 2026-11-17:
    # "Publish / Off / Catmull-Clark" and a Dicing field were cryptic and did not line up)
    MENU_PUBLISH = "Use the publish's subdivision"
    MENU_OFF = "Turn subdivision off"
    MENU_CATMULL = "Subdivide (Catmull-Clark)"
    MENU_DICING = "Dicing quality (Karma)"
    MENU_DICING_PUBLISH = "Use the publish's dicing"
    MENU_CLEAR = "Remove the shot's overrides"
    MENU_DISPLAY = "Display"
    DICING_STEPS = ("0.25", "0.5", "1", "2", "4")

    @staticmethod
    def _source_of(item) -> str:
        """Where the row's scheme comes from; a mesh left blank shares its group's."""
        while item is not None and not item.text(2):
            item = item.parent()
        return item.text(2) if item is not None else ""

    def menu_for(self, item) -> QMenu:
        from PySide6.QtGui import QIcon

        pats = self.patterns_for(item)
        menu = QMenu(self)
        menu.setStyleSheet(self.owner.css(STYLE_MENU_SQ))
        size = self.owner.px(16)

        def icon(name, color=TEXT_LABEL):
            return _crisp_icon(name, size, color)

        # what the menu acts on: a band of its own, not a greyed-out item (the user's ask)
        if len(pats) > 1:
            pix, name, note = icon("layers").pixmap(size), f"{len(pats)} rows selected", ""
        else:
            n = sum(1 for _ in self._leaves(item))
            kind = item.data(0, ROLE_PRIM) or "mesh"
            pix, name = _prim_icon(kind, size), item.text(0)
            note = f"{n} mesh{'es' if n != 1 else ''}" if kind != "mesh" else ""
        menu.addAction(self._menu_head(menu, pix, name, note))
        has_mesh = item.data(0, ROLE_PRIM) == "mesh" or any(
            leaf.data(0, ROLE_PRIM) == "mesh" for leaf in self._leaves(item))
        overridden = self._source_of(item) == "shot"
        current = item.text(3) if overridden else ""
        for label, scheme, name, on in () if not has_mesh else ((self.MENU_PUBLISH, "publish", "file-box",
                                                                 not overridden),
                                        (self.MENU_OFF, "none", "x", current == SCHEME_WORD["none"]),
                                        (self.MENU_CATMULL, "catmullClark", "sparkles",
                                         current == SCHEME_WORD["catmullClark"])):
            act = menu.addAction(icon("check", ACCENT) if on else icon(name), label)
            act.setData("current" if on else "")
            act.triggered.connect(lambda _=False, sc=scheme: self.set_scheme(pats, sc))
        dicing = QMenu(self.MENU_DICING, menu)  # parented: addMenu's own submenu was deleted with its wrapper
        dicing.menuAction().setVisible(has_mesh)
        dicing.setIcon(icon("sliders"))
        menu.addMenu(dicing)
        menu._keep = dicing  # noqa: SLF001 (the Python wrapper lives as long as the menu)
        dicing.setStyleSheet(self.owner.css(STYLE_MENU_SQ))
        dicing.setToolTipsVisible(True)
        now = item.text(4)
        for value in ("",) + self.DICING_STEPS:
            on = (now == value) if value else not now
            act = dicing.addAction(icon("check", ACCENT) if on else QIcon(),
                                   value or self.MENU_DICING_PUBLISH)
            act.setToolTip("How finely Karma dices the subdivided surface at render time (1 is Karma's default)")
            act.triggered.connect(lambda _=False, v=value: self.set_dicing(pats, v))
        # Display (the user's ask): the row's three toggles as verbs that say what a click does
        ps = item.data(0, ROLE_SHOW)
        if ps is not None:
            display = QMenu(self.MENU_DISPLAY, menu)  # parented, as the dicing submenu
            display.setIcon(icon("eye"))
            display.setStyleSheet(self.owner.css(STYLE_MENU_SQ))
            menu.addMenu(display)
            menu._keep_display = display  # noqa: SLF001
            for col, on, off_label, on_label, on_icon, off_icon in (
                    (5, ps.own_visible, "Hide", "Show", "eye", "eye-off"),
                    (6, ps.viewport, "Stop drawing in the viewport", "Draw in the viewport", "monitor", "monitor-off"),
                    (7, ps.render, "Stop rendering", "Render", "camera", "camera-off")):
                act = display.addAction(icon(off_icon if on else on_icon), off_label if on else on_label)
                act.triggered.connect(lambda _=False, c=col: self._toggle(item, c))
        menu.addSeparator()
        menu.addAction(icon("undo"), self.MENU_CLEAR).triggered.connect(lambda _=False: self.clear(pats))
        # this loader's whole subdivision setup onto the asset's other loaders (its instances in the scene); only when
        # there are some (the user asked what "Copy these overrides" did)
        others = self.other_instances()
        if others:
            act = menu.addAction(icon("link"), f"Same overrides on the other {len(others)} {self.asset} "
                                               f"loader{'s' if len(others) != 1 else ''}")
            act.setToolTip("This loader's subdivision, dicing and what it shows, set on " + ", ".join(others))
            act.triggered.connect(lambda _=False: self.to_asset())
        menu.setToolTipsVisible(True)
        return menu

    def other_instances(self) -> list[str]:
        """The other MonoFX Loaders of this loader's asset in the scene (what the subdivision can be copied to)."""
        if not self.asset:
            return []
        return [r.instance for r in self.owner.ctl.rows() if r.asset == self.asset and r.node_path != self.path
                and r.kind == "geo" and not r.legacy and not getattr(r, "baked", False)]

    def _menu_head(self, menu, pix, name: str, note: str):
        """The menu's first row: the prim's icon and name on a lighter band, a firm line under it."""
        from PySide6.QtWidgets import QWidgetAction

        px = self.owner.px
        box = QWidget()
        box.setObjectName("menuHead")
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box.setStyleSheet(self.owner.css(f"QWidget#menuHead {{ background: #26262e;"
                                         f" border-bottom: 2px solid {LINE}; }}"))
        row = QHBoxLayout(box)
        row.setContentsMargins(px(6), px(9), px(16), px(9))  # icon and name over the items' own
        row.setSpacing(px(14))
        ic = QLabel()
        ic.setPixmap(pix)
        ic.setStyleSheet("background: transparent;")
        row.addWidget(ic)
        title = self.owner._label(name, FS_META, color=TEXT_LABEL)  # the items' size, regular, quieter, italic
        title.setStyleSheet(title.styleSheet() + " font-style: italic;")
        row.addWidget(title)
        row.addStretch(1)
        if note:
            row.addWidget(self.owner._label(note, FS_SMALL, color=TEXT_LABEL))
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(box)
        wa.setEnabled(False)
        menu._head = box  # noqa: SLF001 (keep the wrapper alive with the menu)
        return wa

    @staticmethod
    def _leaves(item):
        if not item.childCount():
            yield item
        for i in range(item.childCount()):
            yield from InspectorPanel._leaves(item.child(i))

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is not None and self.path:
            self.menu_for(item).exec(self.tree.viewport().mapToGlobal(pos))

    def _toggle(self, item, col: int) -> None:
        """A click on a row's eye, viewport or render toggle: that row, or the whole selection when the row is part
        of it, takes the clicked row's new value (Blender's outliner); one undo step."""
        which = TOGGLE_COLS[col]
        selected = self.tree.selectedItems()
        items = [item] + [i for i in selected if i is not item] if item in selected else [item]
        rows = []
        for it in items:
            ps = it.data(0, ROLE_SHOW)
            if ps is None:
                continue
            parent = it.parent().data(0, ROLE_SHOW) if it.parent() is not None else None
            rows.append((it.data(0, ROLE_PATTERN), ps, parent))
        edits = logic.toggle_edits(rows, which)
        if not edits or not self.path:
            return
        first = rows[0][1]
        what = {"eye": "hidden" if first.own_visible else "shown",
                "viewport": "not drawn in the viewport" if first.viewport else "drawn in the viewport",
                "render": "not rendered" if first.render else "rendered"}[which]
        path = self.path
        self.owner._run_detail(lambda: self.owner.ctl.set_show(path, edits, what), path)()

    def set_scheme(self, pats: list[str], scheme: str) -> None:
        path = self.path
        if path:
            self.owner._run(lambda: self.owner.ctl.set_subd(path, pats, scheme))()

    def set_dicing(self, pats: list[str], text: str) -> None:
        text = text.strip()
        try:
            dicing = float(text) if text else None
        except ValueError:
            self.owner.ctl.message = f"Dicing must be a number, not {text!r}."
            self.owner._update_bar()
            return
        path = self.path
        if path:
            self.owner._run(lambda: self.owner.ctl.set_subd(path, pats, None, dicing))()

    def clear(self, pats: list[str] | None) -> None:
        path = self.path
        if path:
            self.owner._run(lambda: self.owner.ctl.clear_subd(path, pats))()

    def to_asset(self) -> None:
        path = self.path
        if path:
            self.owner._run(lambda: self.owner.ctl.subd_to_asset(path))()


# --- Add drawer (layout A, the user's pick, 2026-11-17) ------------------------------------------------------

class AddDrawer(QWidget):
    """Assets of the project beside the list: type chips with counts, search, "with a model only", thumbnails;
    pick several (click toggles), Add N makes a MonoFX Loader on Source Asset for each, wired into assets_merge in
    the manager's network. Its Add is the window's one primary while it is open."""

    THUMB = (118, 80)

    def __init__(self, owner) -> None:
        super().__init__()
        self.owner = owner
        self.root = ""
        self.group = ""
        self.setObjectName("addDrawer")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(owner.px(14), owner.px(12), owner.px(14), owner.px(10))
        lay.setSpacing(owner.px(8))
        head = QHBoxLayout()
        head.addWidget(owner._label("Add assets", 15, QFont.Weight.DemiBold))
        head.addStretch(1)
        close = QPushButton("Close")
        close.setStyleSheet(owner.css(STYLE_LINK))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("Back to the selected loader (Esc)")
        close.clicked.connect(owner.close_drawer)
        close.setMinimumHeight(owner.px(24))
        head.addWidget(close)
        lay.addLayout(head)
        self.search = QLineEdit()
        self.search.setObjectName("assetSearch")
        self.search.setPlaceholderText("Search assets")
        self.search.setStyleSheet(owner.css(
            f"QLineEdit#assetSearch {{ background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {LINE};"
            f" border-radius: 8px; padding: 5px 9px; font-size: {FS_META}px; }}"
            f"QLineEdit#assetSearch:focus {{ border: 1px solid {ACCENT}; }}"))
        self.search.textChanged.connect(lambda _t: self.fill())
        lay.addWidget(self.search)
        self.chips_box = QWidget()
        self.chips = QHBoxLayout(self.chips_box)
        self.chips.setContentsMargins(0, 0, 0, 0)
        self.chips.setSpacing(owner.px(6))
        lay.addWidget(self.chips_box)
        self.model_only = QCheckBox("Published only")
        self.model_only.setChecked(True)
        self.model_only.setStyleSheet(f"color: {TEXT_LABEL}; font-size: {owner.px(FS_SMALL)}px;")
        self.model_only.setToolTip("Only assets with a UV or lookdev publish (a prop's lookdev is the whole asset)")
        self.model_only.toggled.connect(lambda _on: (self.fill_groups(), self.fill()))
        self.model_only.setMinimumHeight(owner.px(24))
        lay.addWidget(self.model_only)
        self.list = QListWidget()
        self.list.setObjectName("assetGrid")
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.list.setIconSize(QSize(owner.px(self.THUMB[0]), owner.px(self.THUMB[1])))
        self.list.setGridSize(QSize(owner.px(self.THUMB[0] + 24), owner.px(self.THUMB[1] + 58)))
        self.list.setWordWrap(True)
        self.list.setSpacing(owner.px(4))
        self.list.setStyleSheet(owner.css(
            f"QListWidget#assetGrid {{ background: {BG_APP}; border: none; outline: none; color: {TEXT_PRIMARY};"
            f" font-size: {FS_SMALL}px; }}"
            f"QListWidget#assetGrid::item {{ border: 1px solid {LINE}; border-radius: 8px; padding: 4px; }}"
            f"QListWidget#assetGrid::item:hover {{ background: {BG_HOVER}; }}"
            f"QListWidget#assetGrid::item:selected {{ background: {SELECTED}; border: 1px solid {ACCENT_LINE};"
            f" color: {TEXT_PRIMARY}; }}"
            f"QListWidget#assetGrid::item:selected:hover {{ background: #2e3c5f; border: 1px solid {ACCENT}; }}"))
        self.list.itemSelectionChanged.connect(self._picked_changed)
        lay.addWidget(self.list, 1)
        foot = QHBoxLayout()
        self.count = owner._label("", FS_META, color=TEXT_LABEL)
        foot.addWidget(self.count, 1)
        self.add_button = owner._button("Add", STYLE_PRIMARY)
        self.add_button.setToolTip("A MonoFX Loader on Source Asset for each picked asset (newest model, groom, "
                                   "lookdev), wired into assets_merge. One undo step.")
        self.add_button.clicked.connect(lambda: owner.add_picked(self.picked()))
        fm = self.add_button.fontMetrics()  # no layout jump: as wide as its widest label
        self.add_button.setMinimumWidth(fm.horizontalAdvance("Add 99") + owner.px(48))
        foot.addWidget(self.add_button)
        lay.addLayout(foot)

    def sizeHint(self) -> QSize:
        return QSize(self.owner.px(560), self.owner.px(500))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:  # Esc leaves the narrowest state
            self.owner.close_drawer()
            return
        super().keyPressEvent(event)

    def open(self, root: str) -> None:
        self.root = root
        self.fill_groups()
        self.fill()
        self.search.setFocus()

    def fill_groups(self) -> None:
        while self.chips.count():
            w = self.chips.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        items = logic.asset_catalog(self.root, "", "", self.model_only.isChecked())
        counts: dict[str, int] = {}
        for it in items:
            counts[it.group] = counts.get(it.group, 0) + 1
        for group, label in [("", "All")] + [(g, logic.group_label(g)) for g in logic.asset_groups(Path(self.root))
                                              if g in counts]:
            n = len(items) if not group else counts.get(group, 0)
            b = self.owner._button(f"{label} {n}", STYLE_PILL)
            b.setCheckable(True)
            b.setChecked(group == self.group)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            b.clicked.connect(lambda _=False, g=group: self._pick_group(g))
            self.chips.addWidget(b)
        self.chips.addStretch(1)

    def _pick_group(self, group: str) -> None:
        self.group = group
        self.fill_groups()
        self.fill()

    def fill(self) -> None:
        from PySide6.QtGui import QIcon, QPixmap

        keep = set(self.picked())
        self.list.clear()
        in_scene = {r.asset for r in self.owner.ctl.rows() if r.asset_source}
        w, h = self.owner.px(self.THUMB[0]), self.owner.px(self.THUMB[1])
        for it in logic.asset_catalog(self.root, self.group, self.search.text(), self.model_only.isChecked()):
            sub = "in the scene, adds another" if it.name in in_scene else (
                f"UV {it.model or '\u2013'}, LD {it.lookdev or '\u2013'}")
            item = QListWidgetItem(f"{it.name}\n{sub}")
            pix = QPixmap(it.thumb) if it.thumb else QPixmap()
            if pix.isNull():
                pix = QPixmap(w, h)
                pix.fill(QColor(BG_HOVER))
            item.setIcon(QIcon(pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)))
            item.setData(ROLE_ROW, it.name)
            item.setToolTip(f"{it.name} ({logic.group_label(it.group)})")
            self.list.addItem(item)
            if it.name in keep:
                item.setSelected(True)
        if self.list.count() == 0:
            self.count.setText("No assets match." if self.root else "Pick a project first.")
        self._picked_changed()

    def picked(self) -> list[str]:
        return [i.data(ROLE_ROW) for i in self.list.selectedItems()]

    def _picked_changed(self) -> None:
        n = len(self.picked())
        self.add_button.setText(f"Add {n}" if n else "Add")
        self.add_button.setEnabled(n > 0)
        if self.list.count():
            self.count.setText(f"{n} picked, Source Asset, newest versions" if n
                               else f"{self.list.count()} assets, click to pick")
