"""Mono Anim Loader manager window (PySide6): every loader in the scene, what is behind, one-step updates.

Layout picked by the user (2026-11-17, mockups https://claude.ai/artifact/GEiaL6PUnMXhXukHH2isM1): two views
switched in the top bar, **List** (one row per instance: thumbnail, name, Anim / Lookdev / Groom / Cloth chips,
grouped by shot) and **Grid** (one card per instance). Thumbnails are the asset's Monos picture
(``logic.asset_thumbnail``). Top bar: title, List / Grid, Load shot (shot, version, Load). Headline: what
the primary button will do. Action bar: result line, Undo, Upgrade N old, the one primary button
("Update N behind" / "Update N selected"). Right click a row: select the node, choose the asset of an
"asset?" row. The view is the viewer's (``%APPDATA%/MonoFXSuite/anim_loader_prefs.json``), never the scene's.
Scene reads on the main thread, disk scans on a worker thread; no modal dialogs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
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


# Combo boxes keep Houdini's own arrow: the suite's border-triangle trick drew a square in Houdini 22.
COMBO_CSS = f"""
    QComboBox {{
        padding: 6px 10px; border: 1px solid #2c2c33; border-radius: 8px; background: {BG_RAISED};
        color: {TEXT_PRIMARY}; font-size: {FS_META}px;
    }}
    QComboBox:focus {{ border: 1px solid {ACCENT}; }}
    QComboBox QAbstractItemView {{
        background: {BG_RAISED}; color: {TEXT_PRIMARY}; border: 1px solid {LINE};
        selection-background-color: #273352; padding: 4px; outline: none;
    }}
"""


def chip(state: str, newer: str | None, version: str) -> tuple[str, str]:
    """(text, colour) of a part's chip; colour never stands alone: the word says it too."""
    if state == logic.STATUS_OK:
        return version or "ok", STATUS_COLORS[AM_OK]
    if state == logic.STATUS_NEWER:
        return f"{version} → {newer}", STATUS_COLORS[AM_UPDATE]
    if state == logic.STATUS_MISSING:
        return (f"missing · {newer} out" if newer else "missing"), STATUS_COLORS[AM_MISSING]
    if state == logic.STATUS_NONE:
        return "none", TEXT_META
    if state == logic.STATUS_ASSET:
        return "asset?", STATUS_COLORS[AM_WARN]
    return "off", TEXT_META


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


NARROW_ROW_PX = 620  # under this width a list row puts its chips under the name


class _ListDelegate(QStyledItemDelegate):
    """List view: a row per instance, thumbnail, name and prim, then four part chips in columns (under the
    name when docked narrow)."""

    def __init__(self, painter: _Painter, view: QListView | None = None, parent=None) -> None:
        super().__init__(parent)
        self.pt = painter
        self.view = view

    def paint(self, p: QPainter, option, index) -> None:
        pt = self.pt
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect
        if index.data(ROLE_HEADER):
            pt.header(p, rect.adjusted(0, 0, 0, -pt.px(6)), index.data(ROLE_HEADER))
            p.restore()
            return
        row: Row = index.data(ROLE_ROW)
        selected = bool(option.state & option.state.__class__.State_Selected)
        hover = bool(option.state & option.state.__class__.State_MouseOver)
        p.fillRect(rect, QColor(SELECTED if selected else (BG_HOVER if hover else BG_APP)))
        p.setPen(QColor(LINE))
        p.drawLine(rect.bottomLeft(), rect.bottomRight())
        pad = pt.px(16)
        narrow = rect.width() < pt.px(NARROW_ROW_PX)
        th = (pt.px(64) if narrow else rect.height()) - pt.px(12)
        tw = int(th * 1.4)
        pt.thumb(p, QRect(rect.left() + pad, rect.top() + pt.px(6), tw, th), row)
        name_x = rect.left() + pad + tw + pt.px(12)
        cols_x = name_x if narrow else rect.left() + int(rect.width() * 0.36)
        name_w = (rect.right() - pad - name_x) if narrow else cols_x - name_x - pt.px(8)
        mid = rect.top() + (pt.px(32) if narrow else rect.height() // 2)
        p.setFont(_font(pt.px(FS_META), QFont.Weight.DemiBold))
        p.setPen(QColor(TEXT_PRIMARY))
        fm = p.fontMetrics()
        p.drawText(QRect(name_x, mid - pt.px(20), name_w, pt.px(20)), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                   fm.elidedText(row.instance, Qt.TextElideMode.ElideMiddle, name_w))
        p.setFont(_font(pt.px(FS_META)))
        p.setPen(QColor(TEXT_LABEL))
        sub = "camera" if row.kind == "cam" else ("Anim Loader 2.1" if row.legacy else f"/{row.instance}")
        sub_rect = QRect(name_x, mid + pt.px(1), name_w, pt.px(20))
        top_left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        if row.subd:
            fm = p.fontMetrics()
            tail = f"  ·  {subd_chip(row)}"
            head_w = min(fm.horizontalAdvance(sub), max(0, name_w - fm.horizontalAdvance(tail)))
            p.drawText(QRect(name_x, sub_rect.top(), head_w, sub_rect.height()), top_left,
                       fm.elidedText(sub, Qt.TextElideMode.ElideMiddle, head_w))
            if row.subd[1] > logic.HEAVY_SUBD_POLYGONS:
                p.setPen(QColor(STATUS_COLORS[AM_WARN]))
            p.drawText(QRect(name_x + head_w, sub_rect.top(), name_w - head_w, sub_rect.height()), top_left,
                       fm.elidedText(tail, Qt.TextElideMode.ElideRight, name_w - head_w))
        else:
            p.drawText(sub_rect, top_left, p.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideMiddle, name_w))
        if narrow:  # chips under the name, two by two, across the whole row
            cols_x = rect.left() + pad
            y = rect.top() + pt.px(68)
            col_w = (rect.right() - pad - cols_x) // 2
        else:
            y = mid - pt.px(11)
            col_w = (rect.right() - pad - cols_x) // 4
        if row.legacy:
            text, color = row_summary(row)
            pt.chip(p, cols_x, y, text, color, col_w * 3)
        else:
            parts = ALL_PARTS[:1] if (narrow and row.kind == "cam") else ALL_PARTS
            for i, part in enumerate(parts):
                st, newer = row.parts.get(part, (logic.STATUS_OFF, None))
                text, color = chip(st, newer, row.versions.get(part, ""))
                if narrow:
                    pt.chip(p, cols_x + (i % 2) * col_w, y + (i // 2) * pt.px(26), f"{PART_LABEL[part]} {text}",
                            color, col_w - pt.px(6))
                else:
                    pt.chip(p, cols_x + i * col_w, y, text, color, col_w - pt.px(6))
        p.restore()

    def sizeHint(self, option, index) -> QSize:
        width = self.view.viewport().width() if self.view is not None else 1000
        if index.data(ROLE_HEADER):
            return QSize(width, self.pt.px(34))
        return QSize(width, self.pt.px(128 if width < self.pt.px(NARROW_ROW_PX) else 56))


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
        t.addWidget(self._label("Anim loaders", 19, QFont.Weight.DemiBold))
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
        self.shot_box = QComboBox()
        self.shot_box.setEditable(True)
        self.shot_box.setToolTip("Shot to load")
        self.version_box = QComboBox()
        self.version_box.setToolTip("Anim version to load")
        for box in (self.shot_box, self.version_box):
            box.setStyleSheet(self.css(COMBO_CSS))
            box.setMinimumHeight(self.px(32))
            box.setMinimumWidth(self.px(84))
        self.shot_box.currentTextChanged.connect(self._fill_versions)
        self.shot_box.currentTextChanged.connect(self._shot_changed)
        self.load_button = self._button("Load shot", STYLE_GHOST)
        self.load_button.setToolTip("A loader for every anim output of this version that has none yet")
        self.load_button.clicked.connect(self._load_shot)
        # Load shot sits in the top bar, or in a row of its own when docked narrow (resizeEvent); its box is
        # ignored for the window's minimum width so the window can be docked at 400 px
        self.load_box = QWidget()
        lb = QHBoxLayout(self.load_box)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.setSpacing(self.px(8))
        lb.addStretch(1)
        for w in (self.shot_box, self.version_box, self.load_button):
            lb.addWidget(w)
        self.load_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._top_layout = t
        t.addWidget(self.load_box, 1)
        root.addWidget(top)
        self.load_row, self._load_layout = self._bar()
        self.load_row.setObjectName("load_row")
        self.load_row.hide()
        root.addWidget(self.load_row)
        root.addWidget(self._line())

        self.headline = self._label("", FS_DISPLAY, QFont.Weight.DemiBold)
        self.headline.setWordWrap(True)
        self.headline.setContentsMargins(self.px(16), self.px(14), self.px(16), self.px(8))
        root.addWidget(self.headline)

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
        self.subd_panel = SubdPanel(self)
        self.subd_panel.setMinimumWidth(1)  # set by resizeEvent: 360 beside the list, free when stacked
        self.split.addWidget(self.subd_panel)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        root.addWidget(self.split, 1)

        root.addWidget(self._line())
        self.result = self._label("", FS_META, color=TEXT_LABEL)
        self.result.setWordWrap(True)
        self.result.setContentsMargins(self.px(16), self.px(8), self.px(16), 0)
        self.result.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self.result)
        bar, b = self._bar()
        bar.setObjectName("actions")
        b.addStretch(1)
        self.undo_button = self._button("Undo", STYLE_GHOST)
        self.undo_button.setToolTip("Houdini's undo of the last change")
        self.undo_button.clicked.connect(self._undo)
        self.retarget_button = self._button("", STYLE_GHOST)
        self.retarget_button.setToolTip("Move loaders copied from another shot to the shot in the Load shot box: "
                                        "newest anim there, groom / cloth from there, lookdev and settings kept")
        self.retarget_button.clicked.connect(self._run(lambda: self.ctl.retarget()))
        self.retarget_button.hide()
        self.upgrade_button = self._button("", STYLE_GHOST)
        self.upgrade_button.setToolTip("Change Anim Loader 2.1 nodes to 2.2, keeping their settings")
        self.upgrade_button.clicked.connect(self._run(self.ctl.upgrade_all))
        self.primary = self._button("", STYLE_PRIMARY)
        self.primary.setToolTip("The one thing worth doing now")
        self.primary.clicked.connect(self._run(self.ctl.primary))
        for w in (self.undo_button, self.retarget_button, self.upgrade_button, self.primary):
            b.addWidget(w)
        root.addWidget(bar)

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
                group = row.shot or "old loaders"
                if group != shot:
                    shot = group
                    count = sum(1 for r in rows if (r.shot or "old loaders") == group)
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
        self._fill_shots()
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
        # One primary, the most important thing to do (retarget > update > upgrade 2.1 > Draw Hulls Only); the headline says
        # the same. Nothing to do: no primary button at all.
        self.headline.setText(self.ctl.headline())
        action = self.ctl.primary_action()
        self.primary.setVisible(action is not None)
        if action is not None:
            self.primary.setText(action[1])
            self.primary.setToolTip({
                "retarget": "Move loaders copied from another shot to this shot: newest anim there, groom / cloth "
                            "from there, lookdev and settings kept (one undo step)",
                "update": "Move what is behind to the newest version (one undo step)",
                "upgrade": "Change Anim Loader 2.1 nodes to 2.2, keeping their settings (one undo step)",
                "hulls": "Draw Hulls Only in every viewport: lighter to work in; memory stays the same",
            }[action[0]])
        n_old = len(self.ctl.legacy_paths())
        self.upgrade_button.setText(self.ctl.upgrade_label())
        self.upgrade_button.setVisible(n_old > 0 and (action is None or action[0] != "upgrade"))
        self.retarget_button.setText(self.ctl.retarget_label())
        self.retarget_button.setVisible(bool(self.ctl.retarget_paths()) and (action is None or action[0] != "retarget"))
        self.result.setText(self.ctl.message)  # results only; the heavy-shot line lives in the Subdivision column

    def _selection_changed(self, view: QListWidget) -> None:
        self.ctl.selection = [i.data(ROLE_ROW).node_path for i in view.selectedItems() if i.data(ROLE_ROW)]
        self._update_bar()
        self._show_subd()

    def _show_subd(self) -> None:
        sel = self.ctl.selection[-1] if self.ctl.selection else ""
        self.subd_panel.show_row(next((r for r in self.ctl.rows() if r.node_path == sel), None))

    def _repaint_views(self) -> None:
        for v in (self.list_view, self.grid_view):
            v.viewport().update()

    NARROW_PX = 640

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        narrow = self.width() < self.px(self.NARROW_PX)
        if narrow and self.load_box.parentWidget() is not self.load_row:
            self._load_layout.addWidget(self.load_box, 1)
            self.load_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        elif not narrow and self.load_box.parentWidget() is self.load_row:
            self._top_layout.addWidget(self.load_box, 1)
            self.load_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.load_row.setVisible(narrow)
        self.grid_view.doItemsLayout()  # grid headers span the row
        self.list_view.doItemsLayout()  # list rows change height when narrow
        # the subdivision column sits beside the list, or under it when docked narrow
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
        n = self.backend.set_hulls_only()
        self.ctl.message = (f"Draw Hulls Only on in {n} viewport{'s' if n != 1 else ''}: lighter to work in; "
                            "memory stays the same.")
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

    def _fill_shots(self) -> None:
        current = self.shot_box.currentText()
        shots = self.ctl.shots()
        guess = getattr(self.backend, "project_and_shot", lambda: ("", ""))()
        if guess[1] and guess[1] not in shots:
            shots.append(guess[1])
        self.shot_box.blockSignals(True)
        self.shot_box.clear()
        self.shot_box.addItems(sorted(shots))
        self.shot_box.setCurrentText(current or guess[1] or (shots[0] if shots else ""))
        self.shot_box.blockSignals(False)
        self.ctl.scene_shot = guess[1]
        self.ctl.target_shot = self.shot_box.currentText()
        self._fill_versions(self.shot_box.currentText())

    def _shot_changed(self, shot: str) -> None:
        self.ctl.target_shot = shot
        self._update_bar()

    def _project_root(self) -> str:
        roots = [i.state.project_root for i in self.ctl._infos if i.state and i.state.project_root]
        if roots:
            return roots[0]
        return getattr(self.backend, "project_and_shot", lambda: ("", ""))()[0]

    def _fill_versions(self, shot: str) -> None:
        root = self._project_root()
        versions = logic.list_versions(logic.anim_publish_dir(Path(root), shot)) if root and shot else []
        self.version_box.clear()
        self.version_box.addItems(list(reversed(versions)))
        self.load_button.setEnabled(bool(versions))

    def _load_shot(self) -> None:
        root, shot, version = self._project_root(), self.shot_box.currentText(), self.version_box.currentText()
        if not (root and shot and version):
            self.ctl.message = "Pick a shot and a version first."
            self._update_bar()
            return
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
# Draw Hulls Only makes the viewport light to work in; it does NOT lower memory (measured: Helen catmullClark
# 12.8 GB -> 19.5 GB when turned on, 13 GB when on from the start).

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
        hint = QLabel("The viewport may be slow. Draw Hulls Only makes it lighter to work in; it does not lower memory.")
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


class SubdPanel(QWidget):
    """The selected loader's meshes by group: faces, where the scheme comes from (only where it differs from the
    group), the scheme as a menu on each row (on a selected row it sets the whole selection), dicing (only when
    some mesh has it). Each change is one undo step; Clear overrides and Apply to all instances share a row."""

    def __init__(self, owner, parent=None) -> None:
        from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLineEdit, QTreeWidget

        super().__init__(parent)
        self.owner = owner
        self.path = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(owner.px(12), owner.px(10), owner.px(12), owner.px(10))
        lay.setSpacing(owner.px(8))
        self.title = owner._label("Pick a character to see its subdivision.", 19, QFont.Weight.DemiBold)
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.load = owner._label("", FS_SMALL, color=TEXT_LABEL)
        self.load.setWordWrap(True)
        self.hulls_link = QPushButton("Draw Hulls Only")
        self.hulls_link.setStyleSheet(owner.css(STYLE_LINK))
        self.hulls_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hulls_link.setToolTip("Every viewport draws hulls: lighter to work in; memory stays the same")
        self.hulls_link.clicked.connect(owner._hulls)
        self.hulls_link.hide()
        warn_row = QHBoxLayout()
        warn_row.addWidget(self.load, 1)
        warn_row.addWidget(self.hulls_link, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(warn_row)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Mesh", "Faces", "From", "Scheme", "Dice"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setRootIsDecorated(True)
        self.tree.setStyleSheet(owner.css(
            f"QTreeWidget {{ background: {BG_APP}; color: {TEXT_PRIMARY}; border: 1px solid {LINE};"
            f" border-radius: 8px; font-size: {FS_SMALL}px; outline: none; }}"
            f"QTreeWidget::item {{ height: 26px; }}"
            f"QTreeWidget::item:selected {{ background: {SELECTED}; color: {TEXT_PRIMARY}; }}"
            f"QHeaderView::section {{ background: {BG_APP}; color: {TEXT_LABEL}; border: none;"
            f" border-bottom: 1px solid {LINE}; padding: 4px; font-size: {FS_SMALL}px; }}"))
        self.tree.itemSelectionChanged.connect(self._sel_changed)
        head = self.tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # the mesh name gets the room
        for col in range(1, 5):
            head.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.sel_label = owner._label("Nothing selected", FS_SMALL, color=TEXT_LABEL)
        row.addWidget(self.sel_label, 1)
        row.addWidget(owner._label("Dicing", FS_SMALL, color=TEXT_LABEL))
        self.dicing = QLineEdit()
        self.dicing.setPlaceholderText("-")
        self.dicing.setToolTip("Karma dicing quality of the selection (render only); empty clears it")
        self.dicing.setFixedWidth(owner.px(56))
        self.dicing.setStyleSheet(owner.css(f"QLineEdit {{ background: {BG_RAISED}; color: {TEXT_PRIMARY};"
                                            f" border: 1px solid #2c2c33; border-radius: 8px; padding: 4px 6px;"
                                            f" font-size: {FS_META}px; }}"))
        self.dicing.returnPressed.connect(self._set_dicing)
        row.addWidget(self.dicing)
        self.set_button = owner._button("Set", STYLE_GHOST)
        self.set_button.setToolTip("Set the dicing of the selected rows; their scheme stays")
        self.set_button.clicked.connect(self._set_dicing)
        row.addWidget(self.set_button)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.clear_button = owner._button("Clear overrides", STYLE_GHOST)
        self.clear_button.setToolTip("Drop the shot overrides of the selection (or of the whole character if none)")
        self.clear_button.clicked.connect(self._clear)
        self.asset_button = owner._button("Apply to all instances", STYLE_GHOST)
        self.asset_button.clicked.connect(self._to_asset)
        row2.addWidget(self.clear_button)
        row2.addWidget(self.asset_button)
        row2.addStretch(1)
        lay.addLayout(row2)
        self._sel_changed()

    def show_row(self, row) -> None:
        from PySide6.QtWidgets import QTreeWidgetItem

        from tools.fx.anim_loader.logic import HEAVY_SUBD_POLYGONS, mesh_groups, subd_polygons

        self.tree.clear()
        self.hulls_link.hide()
        detail = self.owner.ctl.subd_detail(row.node_path) if row else None
        self.path = row.node_path if row and detail and detail["plan"] else ""
        for w in (self.dicing, self.clear_button, self.asset_button):
            w.setEnabled(bool(self.path))
        self._sel_changed()
        if row is None:
            self.title.setText("Pick a character to see its subdivision.")
            self.load.setText("")
            return
        if not self.path:
            self.title.setText(f"{row.instance}: No meshes to subdivide.")
            self.load.setText("")
            return
        self.title.setText(f"{row.instance} · Subdivision")
        plan, faces = detail["plan"], detail["faces"]
        polys = subd_polygons(faces, plan)
        warn = polys > HEAVY_SUBD_POLYGONS
        self.load.setText(f"~{polys / 1e6:.1f} M viewport polygons"
                          + (" · over 5 M: the viewport may be slow" if warn else ""))
        self.load.setStyleSheet(f"color: {STATUS_COLORS[AM_WARN] if warn else TEXT_LABEL}; font-size: "
                                f"{self.owner.px(FS_SMALL)}px; background: transparent;")
        self.hulls_link.setVisible(warn and self.owner.ctl.heavy_polygons() > 0
                                   and hasattr(self.owner.backend, "set_hulls_only"))
        self.asset_button.setToolTip(f"Copy these overrides to every {row.asset} loader in the scene" if row.asset
                                     else "Copy these overrides to every loader of this asset")
        any_dicing = any(c.dicing for c in plan.values())
        for key, meshes in mesh_groups(list(plan)).items():
            g_from = self._common([plan[m].source for m in meshes])
            g = QTreeWidgetItem([key.rsplit("/", 1)[-1], _faces_word(sum(faces.get(m, 0) for m in meshes)), g_from, "",
                                 self._common([f"{plan[m].dicing:g}" if plan[m].dicing else "" for m in meshes])])
            g.setData(0, ROLE_PATTERN, key + "/**")
            g.setToolTip(0, key)
            self.tree.addTopLevelItem(g)
            self._scheme_menu(g, self._common([SCHEME_WORD.get(plan[m].scheme, plan[m].scheme) for m in meshes]))
            for m in meshes:
                c = plan[m]
                item = QTreeWidgetItem([m.rsplit("/", 1)[-1], _faces_word(faces.get(m, 0)),
                                        "" if c.source == g_from else c.source, "",
                                        f"{c.dicing:g}" if c.dicing else ""])
                item.setData(0, ROLE_PATTERN, m.strip("/"))
                item.setToolTip(0, m)
                if c.source == "shot":
                    item.setForeground(2, QColor(ACCENT))
                g.addChild(item)
                self._scheme_menu(item, SCHEME_WORD.get(c.scheme, c.scheme))
        self.tree.setColumnHidden(4, not any_dicing)
        self.tree.expandAll()

    def _scheme_menu(self, item, current: str) -> None:
        box = QComboBox()
        if current == "mixed":
            box.addItem("Mixed")
        box.addItems(list(SCHEME_WORD.values()))
        box.setCurrentText("Mixed" if current == "mixed" else current)
        box.setStyleSheet(self.owner.css(COMBO_CSS.replace("padding: 6px 10px", "padding: 1px 6px")))
        box.setFixedHeight(self.owner.px(24))
        box.setToolTip("Publish: lookdev, else the anim publish, else none. On a selected row: the whole selection.")
        box.currentTextChanged.connect(lambda text, it=item: self._scheme_changed(it, text))
        self.tree.setItemWidget(item, 3, box)

    def _scheme_changed(self, item, text: str) -> None:
        if text not in WORD_SCHEME or not self.path:
            return
        selected = self.tree.selectedItems()
        pats = self._patterns() if item in selected and len(selected) > 1 else [item.data(0, ROLE_PATTERN)]
        path = self.path
        self.owner._run(lambda: self.owner.ctl.set_subd(path, pats, WORD_SCHEME[text]))()

    @staticmethod
    def _common(values: list[str]) -> str:
        return values[0] if values and all(v == values[0] for v in values) else "mixed"

    def _patterns(self) -> list[str]:
        return [i.data(0, ROLE_PATTERN) for i in self.tree.selectedItems()]

    def _sel_changed(self) -> None:
        n = len(self.tree.selectedItems())
        self.sel_label.setText(f"{n} selected" if n else "Nothing selected")
        self.set_button.setEnabled(bool(n and self.path))

    def _set_dicing(self) -> None:
        pats = self._patterns()
        if not pats or not self.path:
            return
        text = self.dicing.text().strip()
        try:
            dicing = float(text) if text else None
        except ValueError:
            self.owner.ctl.message = f"Dicing must be a number, not {text!r}."
            self.owner._update_bar()
            return
        path = self.path
        self.owner._run(lambda: self.owner.ctl.set_subd(path, pats, None, dicing))()

    def _clear(self) -> None:
        if self.path:
            pats = self._patterns() or None
            path = self.path
            self.owner._run(lambda: self.owner.ctl.clear_subd(path, pats))()

    def _to_asset(self) -> None:
        if self.path:
            path = self.path
            self.owner._run(lambda: self.owner.ctl.subd_to_asset(path))()
