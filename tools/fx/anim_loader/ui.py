"""Mono Anim Loader manager window (PySide6): every loader in the scene, what is behind, one-step updates.

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

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
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
    _font,
    _lucide_pixmap,
    _Thumbnails,
)
from tools.fx.auto_material.logic import STATUS_MISSING as AM_MISSING
from tools.fx.auto_material.logic import STATUS_OK as AM_OK
from tools.fx.auto_material.logic import STATUS_PINNED as AM_WARN
from tools.fx.auto_material.logic import STATUS_UPDATE as AM_UPDATE

WINDOW_NAME = "AnimLoaderManager"
PREFS = Path(os.environ.get("APPDATA", Path.home())) / "MonoFXSuite" / "anim_loader_prefs.json"
PART_LABEL = {"anim": "Anim", "lookdev": "Lookdev", "groom": "Groom", "cloth": "Cloth"}
ACCENT_ON_SELECTED = "#6f9aff"  # the accent as text on a selected row: #5b8cff there is 3.95:1, this 4.5:1
SELECTED = "#273352"  # the accent at 24 % over the window, opaque (Houdini paints transparent rows grey)
ROLE_ROW = Qt.ItemDataRole.UserRole + 10
ROLE_HEADER = Qt.ItemDataRole.UserRole + 11


def scale_css(css: str, scale: float) -> str:
    """Every size in a style sheet times the UI scale (Houdini's x the window's); 1 px lines stay 1 px."""
    import re

    def one(m):
        v = float(m.group(1))
        return m.group(0) if v <= 1 else f"{round(v * scale)}px"

    return css if scale == 1 else re.sub(r"(\d+(?:\.\d+)?)px", one, css)


def chip(state: str, newer: str | None, version: str) -> tuple[str, str]:
    """(text, colour) of a part's chip; colour never stands alone: the word says it too."""
    if state == logic.STATUS_OK:
        return version or "ok", STATUS_COLORS[AM_OK]
    if state == logic.STATUS_NEWER:
        return f"{version} → {newer}", STATUS_COLORS[AM_UPDATE]
    if state == logic.STATUS_MISSING:
        return (f"missing · {newer} out" if newer else "missing"), STATUS_COLORS[AM_MISSING]
    if state in (logic.STATUS_NONE, logic.STATUS_OFF):
        return "\u2013", TEXT_META
    if state == logic.STATUS_ASSET:
        return "asset?", STATUS_COLORS[AM_WARN]
    return "\u2013", TEXT_META


def row_summary(row: Row) -> tuple[str, str]:
    """The one-line status of a card (text, colour)."""
    if row.legacy:
        return "Anim Loader 2.1 · upgrade", STATUS_COLORS[AM_WARN]
    if row.needs_asset:
        return "asset? · right click", STATUS_COLORS[AM_WARN]
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
            icon = "target" if row.kind == "cam" else ("triangle-alert" if row.needs_asset or row.legacy else "user")
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
        f = _font(self.px(FS_SMALL), QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        p.setFont(f)
        p.setPen(QColor(TEXT_LABEL))
        p.drawText(rect.adjusted(self.px(16), 0, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                   text.upper())


NARROW_ROW_PX = 560  # under this width a list row puts its versions on a second line
COLUMNS = (("anim", "Anim", 72), ("lookdev", "Lookdev", 72), ("groom", "Groom", 72), ("cloth", "Cloth", 72),
           ("subd", "Subd", 92))


def subd_cell(row: Row) -> tuple[str, str]:
    """(text, colour) of a row's subdivision cell: meshes and viewport polygons, amber over the heavy line."""
    if not row.subd:
        return "\u2013", TEXT_META
    n, polys = row.subd
    return f"{n} \u00b7 ~{polys / 1e6:.1f} M", (STATUS_COLORS[AM_WARN] if polys > logic.HEAVY_SUBD_POLYGONS
                                                 else TEXT_LABEL)


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

    def columns(self, rect: QRect) -> tuple[dict[str, QRect], int]:
        """Each column's rect from the right edge, and where the name column ends."""
        pt = self.pt
        x = rect.right() - pt.px(16)
        out = {}
        for key, _, w in reversed(COLUMNS):
            w = pt.px(w)
            out[key] = QRect(x - w, rect.top(), w, rect.height())
            x -= w + pt.px(8)
        return out, x

    def cells(self, rect: QRect) -> list[tuple[QRect, str]]:
        """Narrow rows: the four versions' cells across the row."""
        pad = self.pt.px(16)
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
        if index.data(ROLE_HEADER):
            names_line = index.row() == 0 and not wide
            head_rect = QRect(rect.left(), rect.top(), rect.width(), pt.px(34)) if names_line else rect
            pt.header(p, head_rect.adjusted(0, 0, 0, -pt.px(6)), index.data(ROLE_HEADER))
            if index.row() == 0:  # the column names once, on the first header
                f = _font(pt.px(FS_SMALL), QFont.Weight.DemiBold)
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
                p.setFont(f)
                p.setPen(QColor(TEXT_LABEL))
                bottom = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
                if wide:
                    cols, _ = self.columns(rect.adjusted(0, 0, 0, -pt.px(6)))
                    for key, label, _ in COLUMNS:
                        p.drawText(cols[key], bottom, label.upper())
                else:
                    r = QRect(rect.left(), rect.top() + pt.px(34), rect.width(), pt.px(20))
                    for cell, part in self.cells(r):
                        p.drawText(QRect(cell.left(), r.top(), cell.width(), r.height()), bottom,
                                   PART_LABEL[part].upper())
            p.restore()
            return
        row: Row = index.data(ROLE_ROW)
        selected = bool(option.state & option.state.__class__.State_Selected)
        hover = bool(option.state & option.state.__class__.State_MouseOver)
        p.fillRect(rect, QColor(SELECTED if selected else (BG_HOVER if hover else BG_APP)))
        p.setPen(QColor(LINE))
        p.drawLine(rect.bottomLeft(), rect.bottomRight())
        pad, th = pt.px(16), pt.px(28)
        line1 = QRect(rect.left(), rect.top(), rect.width(), pt.px(40))
        pt.thumb(p, QRect(rect.left() + pad, line1.center().y() - th // 2, th, th), row)
        name_x = rect.left() + pad + th + pt.px(10)
        cols, name_end = self.columns(line1)
        if not wide:
            name_end = cols["subd"].left() - pt.px(8)
        p.setFont(_font(pt.px(FS_META), QFont.Weight.DemiBold))
        name_w = min(p.fontMetrics().horizontalAdvance(row.instance) + pt.px(4), name_end - name_x)
        self._text(p, QRect(name_x, line1.top(), name_w, line1.height()), row.instance, TEXT_PRIMARY, FS_META, True)
        tag = "camera" if row.kind == "cam" else ("Anim Loader 2.1" if row.legacy else "")
        if tag:
            self._text(p, QRect(name_x + name_w + pt.px(8), line1.top(), max(0, name_end - name_x - name_w - pt.px(8)),
                                line1.height()), tag, TEXT_LABEL, FS_SMALL)
        text, color = subd_cell(row)
        if row.kind != "cam" and not row.legacy:
            self._text(p, cols["subd"], text if wide or row.subd else "", color, FS_SMALL)
        if wide:
            cells = [(cols[part], part) for part in ALL_PARTS]
        else:  # the versions on a second line, under the column names of the first header
            cells = [(QRect(c.left(), rect.top() + pt.px(36), c.width(), pt.px(20)), part)
                     for c, part in self.cells(rect)]
        if row.legacy:
            first = cells[0][0]
            self._text(p, QRect(first.left(), first.top(), rect.right() - pad - first.left(), first.height()),
                       "Upgrade to 2.2 keeps its settings", STATUS_COLORS[AM_WARN], FS_SMALL)
        else:
            for r, part in cells:
                if row.kind == "cam" and part != "anim":
                    continue
                text, color = part_cell(row, part)
                if selected and color == ACCENT:
                    color = ACCENT_ON_SELECTED
                self._text(p, r, text, color, FS_SMALL)
        p.restore()

    def sizeHint(self, option, index) -> QSize:
        width = self.view.viewport().width() if self.view is not None else 1000
        wide = width >= self.pt.px(NARROW_ROW_PX)
        if index.data(ROLE_HEADER):
            return QSize(width, self.pt.px(34 if wide or index.row() else 58))
        return QSize(width, self.pt.px(40 if wide else 62))


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
                       subd_chip(row).split(" · ")[0])
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
        self.setWindowTitle("Anim loaders")
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
        self.setStyleSheet(self.css(STYLE_WINDOW.replace("AutoMaterialWindow", WINDOW_NAME) + STYLE_MENU))
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
        b.setStyleSheet(self.css(style))
        b.setFont(_font(self.px(FS_META if style is not STYLE_PRIMARY else FS_BODY),
                        QFont.Weight.DemiBold if style is STYLE_PRIMARY else QFont.Weight.Normal))
        b.setMinimumHeight(self.px(32))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
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

        top, t = self._bar()
        top.setObjectName("top")
        t.addWidget(self._label("Anim loaders", 17, QFont.Weight.DemiBold))
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
        self.view_buttons = QButtonGroup(self)
        for key, text in (("list", "List"), ("grid", "Grid")):
            b = self._button(text, STYLE_PILL)
            b.setCheckable(True)
            b.setObjectName(f"view_{key}")
            b.setToolTip(f"Show the loaders as a {text.lower()}")
            b.clicked.connect(lambda _=False, k=key: self.set_view(k))
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.view_buttons.addButton(b)
            t.addWidget(b)
        self.load_button = self._button("Load shot \u25be", STYLE_GHOST)
        self.load_button.setToolTip("A loader for every anim output of a version that has none yet")
        self.load_menu = self._menu_for(self.load_button)
        self.load_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        t.addWidget(self.load_button)
        root.addWidget(top)
        self.nav_row, self._nav_layout = self._bar()
        self.nav_row.setObjectName("nav_row")
        self._nav_layout.setContentsMargins(self.px(10), 0, self.px(16), self.px(6))
        self.nav_row.hide()
        root.addWidget(self.nav_row)
        root.addWidget(self._line())

        # Status line: what the primary does, how many loaders; the heavy-shot note on the right
        status, st = self._bar()
        status.setObjectName("status")
        st.setContentsMargins(self.px(16), self.px(8), self.px(16), self.px(8))
        self.headline = self._label("", FS_META, QFont.Weight.DemiBold)
        self.status_meta = self._label("", FS_META, color=TEXT_LABEL)
        self.status_meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.heavy_label = self._label("", FS_SMALL, color=STATUS_COLORS[AM_WARN])
        self.heavy_label.setToolTip("Estimated viewport polygons of the subdivided meshes (faces x 16)")
        for lab in (self.headline, self.heavy_label):  # wrapped until resizeEvent knows the width: a label
            lab.setWordWrap(True)                        # that does not wrap sets the window's minimum width
        self.hulls_link = QPushButton("Draw Hulls Only")
        self.hulls_link.setStyleSheet(self.css(STYLE_LINK))
        self.hulls_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hulls_link.setToolTip("The /stage viewports draw hulls: lighter to draw and less memory")
        self.hulls_link.clicked.connect(self._hulls)
        st.addWidget(self.headline)
        st.addWidget(self.status_meta, 1)
        st.addWidget(self.heavy_label)
        st.addWidget(self.hulls_link)
        root.addWidget(status)
        root.addWidget(self._line())

        self.stack = QStackedWidget()
        self.list_view = self._view(grid=False)
        self.grid_view = self._view(grid=True)
        self.stack.addWidget(self.list_view)
        self.stack.addWidget(self.grid_view)
        self.empty = self._label("No anim loaders in the scene yet. Pick a shot and press Load shot.", FS_BODY,
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
        self.split.addWidget(self.stack)
        self.subd_panel = InspectorPanel(self)
        self.subd_panel.setMinimumWidth(1)  # set by resizeEvent: 360 beside the list, free when stacked
        self.subd_panel.hide()  # only while a loader is selected
        self.split.addWidget(self.subd_panel)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)  # the inspector keeps its width; the list takes the rest
        root.addWidget(self.split, 1)

        root.addWidget(self._line())
        self.result = self._label("", FS_META, color=TEXT_LABEL)
        self.result.setWordWrap(True)
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
        self.undo_button = self._button("Undo", STYLE_GHOST)
        self.undo_button.setToolTip("Houdini's undo of the last change")
        self.undo_button.clicked.connect(self._undo)
        self.retarget_button = self._button("", STYLE_GHOST)
        self.retarget_button.setToolTip("Move loaders copied from another shot to the shot in the top bar: "
                                        "newest anim there, groom / cloth from there, lookdev and settings kept")
        self.retarget_button.clicked.connect(self._run(lambda: self.ctl.retarget()))
        self.retarget_button.hide()
        self.upgrade_button = self._button("", STYLE_GHOST)
        self.upgrade_button.setToolTip("Change Anim Loader 2.1 and Character Loader 3.2 nodes to 2.2, keeping "
                                       "their settings")
        self.upgrade_button.clicked.connect(self._run(self.ctl.upgrade_all))
        self.primary = self._button("", STYLE_PRIMARY)
        self.primary.setToolTip("The one thing worth doing now")
        self.primary.clicked.connect(self._run(self.ctl.primary))
        for w in (self.undo_button, self.retarget_button, self.upgrade_button, self.primary):
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
        menu.setStyleSheet(self.css(STYLE_MENU))
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
        v.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if grid:
            v.setViewMode(QListView.ViewMode.IconMode)
            v.setResizeMode(QListView.ResizeMode.Adjust)
            v.setMovement(QListView.Movement.Static)
            v.setWrapping(True)
            v.setSpacing(0)
            v.setContentsMargins(self.px(10), 0, self.px(10), 0)
            v.setItemDelegate(_GridDelegate(self._paint, v, v))
        else:
            v.setItemDelegate(_ListDelegate(self._paint, v, v))
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
        for view in (self.list_view, self.grid_view):
            keep = {i.data(ROLE_ROW).node_path for i in view.selectedItems() if i.data(ROLE_ROW)}
            view.blockSignals(True)
            view.clear()
            shot = None
            for row in rows:
                group = row.shot or ("assets" if row.asset_source else "old loaders")
                if group != shot:
                    shot = group
                    count = sum(1 for r in rows if (r.shot or ("assets" if r.asset_source else "old loaders")) == group)
                    h = QListWidgetItem()
                    h.setData(ROLE_HEADER, f"{group} · {count}")
                    h.setFlags(Qt.ItemFlag.NoItemFlags)
                    view.addItem(h)
                item = QListWidgetItem()
                item.setData(ROLE_ROW, row)
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
            lines.append(f"{PART_LABEL[part]}: {chip(st, newer, row.versions.get(part, ''))[0]}")
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
                                    f" font-weight: 600;")
        n = sum(1 for r in rows if not r.legacy)
        self.status_meta.setText(f"\u00b7 {n} loader{'s' if n != 1 else ''}" if rows else "")
        heavy = self.ctl.heavy_polygons()
        self.heavy_label.setText(f"Heavy shot \u00b7 ~{heavy / 1e6:.1f} M subdivision polygons" if heavy else "")
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
        self.upgrade_button.setText(self.ctl.upgrade_label())
        self.upgrade_button.setVisible(n_old > 0 and (action is None or action[0] != "upgrade"))
        self.retarget_button.setText(self.ctl.retarget_label())
        self.retarget_button.setVisible(bool(self.ctl.retarget_paths()) and (action is None or action[0] != "retarget"))
        self.result.setText(self.ctl.message)  # results only

    def _selection_changed(self, view: QListWidget) -> None:
        self.ctl.selection = [i.data(ROLE_ROW).node_path for i in view.selectedItems() if i.data(ROLE_ROW)]
        self._update_bar()
        self._show_subd()

    def _show_subd(self) -> None:
        sel = self.ctl.selection[-1] if self.ctl.selection else ""
        row = next((r for r in self.ctl.rows() if r.node_path == sel), None)
        self.subd_panel.setVisible(row is not None)  # the inspector is for a selection (Monos)
        self.subd_panel.show_row(row)

    def _repaint_views(self) -> None:
        for v in (self.list_view, self.grid_view):
            v.viewport().update()

    NARROW_PX = 640

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            for v in (getattr(self, "list_view", None), getattr(self, "grid_view", None)):
                if v is not None and obj is v.viewport():
                    QTimer.singleShot(0, v.doItemsLayout)
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        narrow = self.width() < self.px(self.NARROW_PX)
        if narrow and self.nav_box.parentWidget() is not self.nav_row:
            self._nav_layout.addWidget(self.nav_box, 1)
        elif not narrow and self.nav_box.parentWidget() is self.nav_row:
            self._top_layout.insertWidget(1, self.nav_box, 1)
        self.nav_row.setVisible(narrow)
        for lab in (self.headline, self.heavy_label):  # wrap when docked narrow, never widen the window
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
        self.split.setOrientation(Qt.Orientation.Vertical if narrow_split else Qt.Orientation.Horizontal)
        self.subd_panel.setMinimumWidth(1 if narrow_split else self.px(360))

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
        row: Row | None = item.data(ROLE_ROW) if item else None
        if row is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(self.css(STYLE_MENU))
        menu.addAction("Select node", lambda: self._select_node(item))
        if not row.legacy and row.behind:
            menu.addAction("Update this loader", self._run(lambda: self.ctl._update([row.node_path])))
        target = self.ctl.target_shot
        if not row.legacy and row.shot and target and row.shot != target:
            menu.addAction(f"Retarget to {target}", self._run(lambda: self.ctl.retarget([row.node_path])))
        if row.needs_asset or (not row.legacy and row.kind == "geo"):
            sub = menu.addMenu("Asset")
            root = next((i.state.project_root for i in self.ctl._infos if i.path == row.node_path and i.state), "")
            for asset in getattr(self.backend, "assets", lambda r: [])(root):
                sub.addAction(asset, self._run(lambda a=asset: self.ctl.set_asset(row.node_path, a)))
        menu.exec(view.viewport().mapToGlobal(pos))

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
        if not self.versions:
            self.load_menu.addAction(f"No anim publish in {shot}" if shot else "Pick a project first").setEnabled(False)
        for i, version in enumerate(self.versions):
            act = self.load_menu.addAction(f"{shot} {version}" + ("  \u00b7  newest" if i == 0 else ""))
            act.triggered.connect(lambda _=False, v=version: self.load_version(v))

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


def open_manager() -> AnimLoaderManager:
    """Opens (or brings back) the one manager window in Houdini."""
    global _WINDOW
    import hou  # noqa: F401

    from apps.houdini.anim_loader_adapter import HoudiniBackend

    if _WINDOW is not None:
        try:
            _WINDOW.refresh()
            _WINDOW.show()
            _WINDOW.raise_()
            _WINDOW.activateWindow()
            return _WINDOW
        except RuntimeError:  # deleted with Houdini's main window
            _WINDOW = None
    parent = hou.qt.mainWindow()
    _WINDOW = AnimLoaderManager(HoudiniBackend(), parent, scale=max(0.5, min(3.0, hou.ui.scaledSize(1000) / 1000.0)))
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


def subd_chip(row: Row) -> str:
    """The row's subdivision chip: "subd 26 · ~9.9 M" (meshes subdivided, estimated viewport polygons)."""
    if not row.subd:
        return ""
    n, polys = row.subd
    return f"subd {n} · ~{polys / 1e6:.1f} M"


def _faces_word(n: int) -> str:
    return f"{n / 1000:.1f}k" if n < 1_000_000 else f"{n / 1e6:.2f} M"


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
        lay.setContentsMargins(owner.px(14), owner.px(12), owner.px(14), owner.px(10))
        lay.setSpacing(owner.px(4))
        self.title = owner._label("", 17, QFont.Weight.DemiBold)
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.meta = owner._label("", FS_SMALL, color=TEXT_LABEL)
        self.meta.setWordWrap(True)
        lay.addWidget(self.meta)
        lay.addSpacing(owner.px(8))
        self.load = owner._label("", FS_SMALL, QFont.Weight.DemiBold, color=TEXT_LABEL)
        self.load.setWordWrap(True)
        lay.addWidget(self.load)
        self.tree = QTreeWidget()
        self.tree.setObjectName("subdTree")
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Mesh", "Faces", "From", "Scheme", "Dice"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setRootIsDecorated(True)
        self.tree.setStyleSheet(owner.css(
            f"QTreeWidget#subdTree {{ background: {BG_APP}; alternate-background-color: {BG_APP};"
            f" color: {TEXT_PRIMARY}; border: none; font-size: {FS_SMALL}px; outline: none; }}"
            f"QTreeWidget#subdTree::item {{ height: 26px; background: {BG_APP}; }}"
            f"QTreeWidget#subdTree::item:hover {{ background: {BG_HOVER}; }}"
            f"QTreeWidget#subdTree::item:selected {{ background: {SELECTED}; color: {TEXT_PRIMARY}; }}"
            f"QTreeWidget#subdTree QHeaderView::section {{ background: {BG_APP}; color: {TEXT_LABEL}; border: none;"
            f" border-bottom: 1px solid {LINE}; padding: 4px; font-size: {FS_SMALL}px; }}"))
        self.tree.viewport().setStyleSheet(f"background: {BG_APP};")
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        head = self.tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # the mesh name gets the room
        for col in range(1, 5):
            head.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.tree, 1)
        self.hint = owner._label("Right-click meshes to set their scheme or dicing.", FS_SMALL, color=TEXT_LABEL)
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

    def sizeHint(self) -> QSize:
        return QSize(self.owner.px(360), self.owner.px(400))

    def show_row(self, row) -> None:
        from PySide6.QtWidgets import QTreeWidgetItem

        from tools.fx.anim_loader.logic import HEAVY_SUBD_POLYGONS, mesh_groups, subd_polygons

        self.tree.clear()
        if row is None:
            self.path = ""
            return
        self.title.setText(row.instance)
        bits = [row.node_path]
        if not row.legacy:
            bits += [f"{PART_LABEL[p].lower()} {row.versions[p]}" for p in ALL_PARTS if row.versions.get(p)]
        self.meta.setText(" \u00b7 ".join(bits))
        self.asset = row.asset or ""
        detail = self.owner.ctl.subd_detail(row.node_path)
        self.path = row.node_path if detail and detail["plan"] else ""
        self.tree.setVisible(bool(self.path))
        self.hint.setVisible(bool(self.path))
        if not self.path:
            self.load.setText("Camera: nothing to subdivide." if row.kind == "cam" else "No meshes to subdivide.")
            self.load.setStyleSheet(f"color: {TEXT_LABEL}; font-size: {self.owner.px(FS_SMALL)}px; background: transparent;")
            return
        plan, faces = detail["plan"], detail["faces"]
        polys = subd_polygons(faces, plan)
        n = sum(1 for c in plan.values() if c.scheme != logic.SUBD_NONE)
        self.load.setText(f"SUBDIVISION \u00b7 {n} of {len(plan)} meshes \u00b7 ~{polys / 1e6:.1f} M viewport polygons")
        warn = polys > HEAVY_SUBD_POLYGONS
        self.load.setStyleSheet(f"color: {STATUS_COLORS[AM_WARN] if warn else TEXT_LABEL}; font-size: "
                                f"{self.owner.px(FS_SMALL)}px; font-weight: 600; background: transparent;")
        any_dicing = any(c.dicing for c in plan.values())
        for key, meshes in mesh_groups(list(plan)).items():
            g_from = self._common([plan[m].source for m in meshes])
            g = QTreeWidgetItem([key.rsplit("/", 1)[-1], _faces_word(sum(faces.get(m, 0) for m in meshes)), g_from,
                                 self._common([SCHEME_WORD.get(plan[m].scheme, plan[m].scheme) for m in meshes]),
                                 self._common([f"{plan[m].dicing:g}" if plan[m].dicing else "" for m in meshes])])
            g.setData(0, ROLE_PATTERN, key + "/**")
            g.setToolTip(0, key)
            self.tree.addTopLevelItem(g)
            for m in meshes:
                c = plan[m]
                item = QTreeWidgetItem([m.rsplit("/", 1)[-1], _faces_word(faces.get(m, 0)),
                                        "" if c.source == g_from else c.source, SCHEME_WORD.get(c.scheme, c.scheme),
                                        f"{c.dicing:g}" if c.dicing else ""])
                item.setData(0, ROLE_PATTERN, m.strip("/"))
                item.setToolTip(0, m)
                if c.source == "shot":
                    for col in (2, 3):
                        item.setForeground(col, QColor(ACCENT))
                g.addChild(item)
        self.tree.setColumnHidden(4, not any_dicing)
        self.tree.expandAll()

    @staticmethod
    def _common(values: list[str]) -> str:
        return values[0] if values and all(v == values[0] for v in values) else "mixed"

    def patterns_for(self, item) -> list[str]:
        """The right-clicked row, or the whole selection when the row is part of it."""
        selected = self.tree.selectedItems()
        rows = selected if item in selected else [item]
        return [i.data(0, ROLE_PATTERN) for i in rows]

    def menu_for(self, item) -> QMenu:
        from PySide6.QtWidgets import QLineEdit, QWidgetAction

        pats = self.patterns_for(item)
        menu = QMenu(self)
        menu.setStyleSheet(self.owner.css(STYLE_MENU))
        current = item.text(3)
        head = menu.addAction(f"{len(pats)} item{'s' if len(pats) != 1 else ''}" if len(pats) > 1 else item.text(0))
        head.setEnabled(False)
        for word, scheme in WORD_SCHEME.items():
            act = menu.addAction(word)
            act.setCheckable(True)
            act.setChecked(word == current)
            act.triggered.connect(lambda _=False, sc=scheme: self.set_scheme(pats, sc))
        menu.addSeparator()
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(self.owner.px(12), self.owner.px(4), self.owner.px(12), self.owner.px(4))
        row.addWidget(self.owner._label("Dicing", FS_SMALL, color=TEXT_LABEL))
        edit = QLineEdit(item.text(4))
        edit.setPlaceholderText("-")
        edit.setToolTip("Karma dicing quality (render only); empty clears it. Enter sets it.")
        edit.setFixedWidth(self.owner.px(64))
        edit.setStyleSheet(self.owner.css(f"QLineEdit {{ background: {BG_APP}; color: {TEXT_PRIMARY};"
                                          f" border: 1px solid #2c2c33; border-radius: 6px; padding: 3px 6px;"
                                          f" font-size: {FS_SMALL}px; }}"))
        edit.returnPressed.connect(lambda: (self.set_dicing(pats, edit.text()), menu.close()))
        row.addWidget(edit)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(box)
        menu.addAction(wa)
        menu.addSeparator()
        menu.addAction("Clear override").triggered.connect(lambda _=False: self.clear(pats))
        what = f"every {self.asset}" if self.asset else "every instance"
        menu.addAction(f"Apply overrides to {what}").triggered.connect(lambda _=False: self.to_asset())
        return menu

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is not None and self.path:
            self.menu_for(item).exec(self.tree.viewport().mapToGlobal(pos))

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
