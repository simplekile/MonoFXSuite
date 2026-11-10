"""
MONO Grooming panel — one window, floating or docked in a Houdini pane.

Top line: the node and what it shows. Left: the layer tree (Defaults, group › lock, Orphans) with an eye,
a colour swatch, a display override and badges per row. Right: the selection's settings, a slider each
with where the value comes from and Reset, then the measured values. Action bar: the result line,
Detect, Split regions (with "regions out of date"), display mode, colour by, publish version, Publish.

The panel shows what the controller gives it and fires events back (`on(event, callback)`); it keeps no
data of its own. Palette, text roles and icons are Auto Material's (tools/fx/auto_material/ui.py).
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tools.fx.auto_material.logic import STATUS_NEW, STATUS_OK, STATUS_PINNED, STATUS_UPDATE
from tools.fx.auto_material.ui import (
    ACCENT,
    BG_APP,
    BG_HOVER,
    BG_RAISED,
    FS_META,
    LINE,
    LUCIDE,
    STATUS_COLORS,
    STYLE_COMBO,
    STYLE_GHOST,
    STYLE_MENU,
    STYLE_PILL,
    STYLE_PRIMARY,
    STYLE_WINDOW,
    TEXT_LABEL,
    TEXT_META,
    TEXT_PRIMARY,
    _divider,
    _font,
    _label,
    _lucide_icon,
    _lucide_pixmap,
    _rgba,
    _text,
)
from tools.fx.grooming import config
from tools.fx.grooming.controller import (
    COLOR_BY_LABELS,
    DISPLAY_LABELS,
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
})

# Badges take the status colours: edited = changed here, unsure = needs a confirm, new = just detected
BADGE_COLORS = {
    "edited": STATUS_COLORS[STATUS_UPDATE],
    "unsure": STATUS_COLORS[STATUS_PINNED],
    "new": STATUS_COLORS[STATUS_NEW],
}
BADGE_HELP = {
    "edited": "Has its own settings",
    "unsure": "Re-import matched it by position or shape only: right click › Confirm match",
    "new": "Detect found it in the hair mesh for the first time",
}
# Where a setting comes from: its own level in the accent, inherited ones quieter
SOURCE_COLORS = {
    "lock": ACCENT,
    "group": STATUS_COLORS[STATUS_NEW],
    "defaults": STATUS_COLORS[STATUS_OK],
    "builtin": TEXT_LABEL,
    "mixed": STATUS_COLORS[STATUS_PINNED],
}
SOURCE_LABELS = {"lock": "lock", "group": "group", "defaults": "defaults", "builtin": "built-in", "mixed": "mixed"}
WARN = STATUS_COLORS[STATUS_PINNED]

# Group colours offered in the swatch menu (no colour dialog: it would be modal)
SWATCHES: tuple[tuple[float, float, float], ...] = (
    (0.91, 0.45, 0.42), (0.95, 0.66, 0.30), (0.93, 0.83, 0.38), (0.55, 0.80, 0.45), (0.33, 0.78, 0.70),
    (0.38, 0.62, 0.95), (0.62, 0.52, 0.95), (0.88, 0.50, 0.80), (0.70, 0.70, 0.72), (0.55, 0.45, 0.38),
)

COL_NAME, COL_BADGES, COL_DISPLAY, COL_EYE = range(4)
ROLE_ROW = Qt.ItemDataRole.UserRole + 1
SLIDER_STEPS = 1000

STYLE_TREE = f"""
    QTreeWidget {{ background: transparent; border: none; outline: none; color: {TEXT_PRIMARY};
                   font-size: {FS_META}px; }}
    QTreeWidget::item {{ height: 30px; border: none; }}
    QTreeWidget::item:hover {{ background: {BG_HOVER}; }}
    QTreeWidget::item:selected {{ background: {_rgba(ACCENT, 0.18)}; color: {TEXT_PRIMARY}; }}
    QTreeWidget::branch {{ background: transparent; }}
    QTreeWidget::branch:selected {{ background: {_rgba(ACCENT, 0.18)}; }}
    QHeaderView::section {{ background: transparent; color: {TEXT_LABEL}; border: none; padding: 4px; }}
"""
STYLE_SLIDER = f"""
    QSlider::groove:horizontal {{ height: 4px; background: {LINE}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {TEXT_PRIMARY}; width: 12px; height: 12px; margin: -4px 0;
                                  border-radius: 5px; }}
    QSlider::handle:horizontal:disabled {{ background: {TEXT_META}; }}
"""
STYLE_FIELD = f"""
    QLineEdit, QDoubleSpinBox {{
        padding: 5px 8px; border: 1px solid #2c2c33; border-radius: 8px; background: {BG_RAISED};
        color: {TEXT_PRIMARY}; font-size: {FS_META}px;
    }}
    QLineEdit:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
"""


def _swatch(color: tuple[float, float, float] | None, size: int = 12) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    if color is not None:
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor.fromRgbF(*color))
        p.drawRoundedRect(QRect(2, 2, size * 2 - 4, size * 2 - 4), 5, 5)
        p.end()
    pm.setDevicePixelRatio(2.0)
    return QIcon(pm)


_hda_icon_cache: dict[int, QPixmap] = {}


def _hda_icon(size: int = 18) -> QPixmap:
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
        _hda_icon_cache[size] = pm or _lucide_pixmap("layers", size, ACCENT)
    return _hda_icon_cache[size]


def _fmt(value: float) -> str:
    return f"{value:.3g}" if abs(value) < 1000 else f"{value:,.0f}"


class _BadgeDelegate(QStyledItemDelegate):
    """Badges column: one small chip per badge, in the status colours."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        badges = index.data(ROLE_ROW + 1) or []
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = _font(11, QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        x = option.rect.left() + 4
        for badge in badges:
            color = QColor(BADGE_COLORS.get(badge, TEXT_LABEL))
            w = metrics.horizontalAdvance(badge) + 12
            rect = QRect(x, option.rect.center().y() - 9, w, 18)
            fill = QColor(color)
            fill.setAlphaF(0.16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 8, 8)  # radius under half the height, or Qt squares it
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, badge)
            x += w + 4
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(60 * len(index.data(ROLE_ROW + 1) or []) + 8, 30)


class _SettingRow(QWidget):
    """One setting: name, source chip, slider, field, Reset. Fires *on_set(key, value)* once per change
    (on release while dragging) and *on_reset(key)*."""

    def __init__(self, s: dict, on_set: Callable[[str, float], None], on_reset: Callable[[str], None]):
        super().__init__()
        self.key = s["key"]
        self._on_set = on_set
        self._lo, self._hi = s["range"]
        self._value = float(s["value"])
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setHorizontalSpacing(10)
        lay.setVerticalSpacing(4)
        name = _label(s["label"] + (f"  {s['unit']}" if s["unit"] else ""), "name")
        lay.addWidget(name, 0, 0)
        color = SOURCE_COLORS.get(s["source"], TEXT_LABEL)
        self.source = QLabel(SOURCE_LABELS.get(s["source"], s["source"]))
        self.source.setStyleSheet(
            f"color: {color}; background: {_rgba(color, 0.14)}; border: 1px solid {_rgba(color, 0.40)};"
            f" border-radius: 8px; padding: 1px 8px; font-size: 13px; font-weight: 600;")
        self.source.setToolTip("Where this value comes from: lock › group › defaults › built-in")
        lay.addWidget(self.source, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        self.reset = QPushButton()
        self.reset.setIcon(_lucide_icon("rotate-ccw", 14, TEXT_LABEL))
        self.reset.setStyleSheet(STYLE_GHOST + f" QPushButton {{ padding: 4px 6px; }}"
                                 f" QPushButton:disabled {{ border-color: {LINE}; }}")
        self.reset.setToolTip("Reset: take the value from the level below again")
        self.reset.setEnabled(bool(s["resettable"]))
        self.reset.clicked.connect(lambda: on_reset(self.key))
        lay.addWidget(self.reset, 0, 3, alignment=Qt.AlignmentFlag.AlignRight)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, SLIDER_STEPS)
        self.slider.setStyleSheet(STYLE_SLIDER)
        self.slider.setValue(self._to_steps(self._value))
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.sliderReleased.connect(self._commit_slider)
        lay.addWidget(self.slider, 1, 0, 1, 3)
        self.field = QDoubleSpinBox()
        self.field.setRange(-1e6, 1e6)
        self.field.setDecimals(3)
        self.field.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.field.setStyleSheet(STYLE_FIELD)
        self.field.setFixedWidth(84)
        self.field.setValue(self._value)
        self.field.editingFinished.connect(lambda: self._commit(self.field.value()))
        lay.addWidget(self.field, 1, 3)
        lay.setColumnStretch(2, 1)

    def _to_steps(self, value: float) -> int:
        t = (value - self._lo) / (self._hi - self._lo) if self._hi > self._lo else 0.0
        return int(round(min(max(t, 0.0), 1.0) * SLIDER_STEPS))

    def _from_steps(self, steps: int) -> float:
        return self._lo + (self._hi - self._lo) * steps / SLIDER_STEPS

    def _on_slider(self, steps: int) -> None:
        self.field.blockSignals(True)
        self.field.setValue(self._from_steps(steps))
        self.field.blockSignals(False)
        if not self.slider.isSliderDown():  # a click on the groove or a key: one change
            self._commit(self._from_steps(steps))

    def _commit_slider(self) -> None:
        self._commit(self._from_steps(self.slider.value()))

    def _commit(self, value: float) -> None:
        value = round(float(value), 4)
        if abs(value - self._value) < 1e-9:
            return
        self._value = value
        self._on_set(self.key, value)


class GroomingUI(QWidget):

    def __init__(self, parent: QWidget | None = None, docked: bool = False):
        super().__init__(parent)
        self.setObjectName("GroomingWindow")
        self.setWindowTitle(config.WINDOW_TITLE)
        self.setMinimumSize(560 if docked else 820, 480)
        if not docked:
            self.resize(1040, 760)
        self.setStyleSheet(STYLE_WINDOW.replace("AutoMaterialWindow", "GroomingWindow"))
        self._docked = docked
        self._callbacks: dict[str, Callable[..., Any]] = {}
        self._filling = False
        self._rows: dict[tuple, QTreeWidgetItem] = {}
        self._props: dict = {}
        self._timer: QTimer | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_top_line())
        root.addWidget(_divider())
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setHandleWidth(1)
        body.setStyleSheet(f"QSplitter::handle {{ background: {LINE}; }}")
        body.addWidget(self._build_tree())
        body.addWidget(self._build_properties())
        body.setStretchFactor(1, 1)
        body.setSizes([420, 520])
        self._body = body
        root.addWidget(body, stretch=1)
        root.addWidget(_divider())
        root.addWidget(self._build_action_bar())

    # =====================================================================
    # Build
    # =====================================================================

    def _build_top_line(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(_hda_icon(18))
        lay.addWidget(icon)
        self._node_label = _label("No node", "name")
        self._node_label.setStyleSheet(_text("body") + " font-weight: 600;")
        lay.addWidget(self._node_label)
        self._asset_pill = QLabel("")
        self._asset_pill.setStyleSheet(STYLE_PILL.replace("QPushButton, QToolButton", "QLabel"))
        self._asset_pill.setToolTip("Asset mode: the groom of the asset, published to 04_grooming")
        lay.addWidget(self._asset_pill)
        lay.addStretch(1)
        self._mode_label = _label("", "meta")
        lay.addWidget(self._mode_label)
        self._dock_btn = QPushButton("  Dock")
        self._dock_btn.setIcon(_lucide_icon("panel-right", 14, TEXT_LABEL))
        self._dock_btn.setStyleSheet(STYLE_GHOST)
        self._dock_btn.setToolTip("Put the panel in a Houdini pane tab (drag the tab out to float it again)")
        self._dock_btn.clicked.connect(lambda: self._fire("dock"))
        self._dock_btn.setVisible(not self._docked)
        lay.addWidget(self._dock_btn)
        return bar

    def _build_tree(self) -> QWidget:
        side = QWidget()
        side.setMinimumWidth(300)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(10, 12, 10, 10)
        lay.setSpacing(6)
        lay.addWidget(_label("LAYERS", "caps"))
        tree = QTreeWidget()
        tree.setColumnCount(4)
        tree.setHeaderHidden(True)
        tree.setStyleSheet(STYLE_TREE)
        tree.setIndentation(16)
        tree.setIconSize(QSize(12, 12))
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree.setItemDelegateForColumn(COL_BADGES, _BadgeDelegate(tree))
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._row_menu)
        tree.itemSelectionChanged.connect(self._on_tree_selection)
        tree.itemClicked.connect(self._on_item_clicked)
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, header.ResizeMode.Stretch)
        for col, width in ((COL_BADGES, 120), (COL_DISPLAY, 92), (COL_EYE, 30)):
            header.setSectionResizeMode(col, header.ResizeMode.Fixed)
            header.resizeSection(col, width)
        self._tree = tree
        lay.addWidget(tree, stretch=1)
        return side

    def _build_properties(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: {BG_APP}; border: none; }}")
        self._props_widget = QWidget()
        self._props_widget.setStyleSheet(f"background: {BG_APP};")
        self._props_lay = QVBoxLayout(self._props_widget)
        self._props_lay.setContentsMargins(18, 14, 18, 14)
        self._props_lay.setSpacing(6)
        scroll.setWidget(self._props_widget)
        self.show_properties({"kind": SEL_NONE})
        return scroll

    def _build_action_bar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background: #141418;")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(8)
        self._message_label = _label("", "meta")
        self._message_label.setWordWrap(True)
        self._message_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        outer.addWidget(self._message_label)

        lay = QHBoxLayout()
        lay.setSpacing(8)
        self._detect_btn = self._ghost("  Detect", "scan-search",
                                       "Find the locks in the hair mesh again; ids are kept by name and position")
        self._detect_btn.clicked.connect(lambda: self._fire("detect"))
        lay.addWidget(self._detect_btn)
        self._split_btn = self._ghost("  Split regions", "layout-grid",
                                      "Chia vùng: give each lock its growth region on the scalp again (frozen until"
                                      " the next split)")
        self._split_btn.clicked.connect(lambda: self._fire("split_regions"))
        lay.addWidget(self._split_btn)
        self._stale = QLabel()
        self._stale.setText("Regions out of date")
        self._stale.setStyleSheet(_text("small", WARN) + " font-weight: 600;")
        self._stale.setToolTip("Locks changed since the last split: Split regions to grow them from their own area")
        self._stale.setVisible(False)
        lay.addWidget(self._stale)
        lay.addStretch(1)

        self._display_combo = QComboBox()
        self._display_combo.setStyleSheet(STYLE_COMBO)
        for mode in config.DISPLAY_MODES:
            self._display_combo.addItem(DISPLAY_LABELS[mode], mode)
        self._display_combo.setToolTip(
            f"Hair preview: {int(config.PREVIEW_FRACTION * 100)}% of the strands, at most"
            f" {config.PREVIEW_MAX_STRANDS:,}")
        self._display_combo.currentIndexChanged.connect(
            lambda _i: None if self._filling else self._fire("set_display", self._display_combo.currentData(), None))
        lay.addWidget(self._display_combo)
        self._color_combo = QComboBox()
        self._color_combo.setStyleSheet(STYLE_COMBO)
        for key, text in COLOR_BY_LABELS.items():
            self._color_combo.addItem(f"Colour by {text.lower()}", key)
        self._color_combo.currentIndexChanged.connect(
            lambda _i: None if self._filling else self._fire("set_display", None, self._color_combo.currentData()))
        lay.addWidget(self._color_combo)

        lay.addSpacing(8)
        self._version_edit = QLineEdit()
        self._version_edit.setPlaceholderText("vNNN")
        self._version_edit.setFixedWidth(70)
        self._version_edit.setStyleSheet(STYLE_FIELD)
        lay.addWidget(self._version_edit)
        self._publish_btn = QPushButton("  Publish")
        self._publish_btn.setIcon(_lucide_icon("upload", 14, "#ffffff"))
        self._publish_btn.setStyleSheet(STYLE_PRIMARY)
        self._publish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._publish_btn.setToolTip("04_grooming/publish/vNNN/char_<name>_grooming_publish.usd; never overwrites")
        self._publish_btn.clicked.connect(lambda: self._fire("publish", self._version_edit.text()))
        lay.addWidget(self._publish_btn)
        outer.addLayout(lay)
        return bar

    @staticmethod
    def _ghost(text: str, icon: str, tip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setIcon(_lucide_icon(icon, 14, TEXT_LABEL))
        btn.setStyleSheet(STYLE_GHOST)
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
        set_display(mode, color_by), publish(version), poll(), refresh(), dock()
        """
        self._callbacks[event] = callback

    def _fire(self, event: str, *args) -> None:
        cb = self._callbacks.get(event)
        if cb is not None:
            cb(*args)

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
        self._asset_pill.setText(f"Asset · {asset}" if asset else "Asset")
        self.setWindowTitle(f"{config.WINDOW_TITLE} · {path}" if path else config.WINDOW_TITLE)

    def show_tree(self, rows: list[dict]) -> None:
        self._filling = True
        expanded = {key for key, item in self._rows.items() if item.isExpanded()}
        first = not self._rows
        self._tree.clear()
        self._rows = {}
        for row in rows:
            item = self._make_item(row)
            self._tree.addTopLevelItem(item)
            for child in row.get("children", []):
                item.addChild(self._make_item(child))
            key = (row["kind"], row["id"])
            item.setExpanded(first or key in expanded)
        self._filling = False

    def _make_item(self, row: dict) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setData(COL_NAME, ROLE_ROW, row)
        item.setText(COL_NAME, row["name"] + (f"   {row['meta']}" if row.get("meta") and row["kind"]
                                              in (SEL_DEFAULTS, ORPHANS_ROW) else ""))
        if row["kind"] == SEL_GROUP and row.get("meta"):
            item.setToolTip(COL_NAME, row["meta"])
        if row["kind"] in (SEL_GROUP, SEL_DEFAULTS, ORPHANS_ROW):
            item.setFont(COL_NAME, _font(FS_META, QFont.Weight.DemiBold))
        if "color" in row:
            item.setIcon(COL_NAME, _swatch(row["color"]))
        elif row["kind"] == SEL_DEFAULTS:
            item.setIcon(COL_NAME, QIcon(_hda_icon(12)))
        elif row["kind"] == ORPHANS_ROW:
            item.setIcon(COL_NAME, _lucide_icon("unlink", 12, WARN))
        if row["kind"] == SEL_ORPHAN:
            item.setForeground(COL_NAME, QColor(TEXT_LABEL))
        item.setData(COL_BADGES, ROLE_ROW + 1, row.get("badges", []))
        item.setToolTip(COL_BADGES, "\n".join(BADGE_HELP[b] for b in row.get("badges", []) if b in BADGE_HELP))
        if row["kind"] in (SEL_GROUP, SEL_LOCKS):
            display = row.get("display")
            item.setText(COL_DISPLAY, DISPLAY_LABELS[display] if display else "auto")
            item.setForeground(COL_DISPLAY, QColor(TEXT_PRIMARY if display else TEXT_META))
            item.setToolTip(COL_DISPLAY, "Display of this row; auto follows the node's display mode")
            visible = row.get("visible", True)
            item.setIcon(COL_EYE, _lucide_icon("eye" if visible else "eye-off", 14,
                                               TEXT_LABEL if visible else TEXT_META))
            item.setToolTip(COL_EYE, "Hide" if visible else "Show")
            if not visible:
                item.setForeground(COL_NAME, QColor(TEXT_META))
        self._rows[(row["kind"], row["id"])] = item
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
        if first is not None:
            self._tree.scrollToItem(first)
        self._filling = False

    def show_properties(self, props: dict) -> None:
        self._props = props
        while self._props_lay.count():
            entry = self._props_lay.takeAt(0)
            if entry.widget() is not None:  # hidden now: deleteLater waits for the event loop
                entry.widget().hide()
                entry.widget().deleteLater()
        kind = props.get("kind", SEL_NONE)
        if kind == SEL_NONE:
            hint = _label("Select a lock or a group to see its settings.\nShift / Ctrl select several locks;"
                          " the viewport selection shows here too.", "meta")
            hint.setWordWrap(True)
            self._props_lay.addWidget(hint)
            self._props_lay.addStretch(1)
            return
        self._props_lay.addWidget(_label(props["title"], "title"))
        if props.get("subtitle"):
            self._props_lay.addWidget(_label(props["subtitle"], "meta"))
        self._props_lay.addSpacing(8)
        if kind == SEL_ORPHAN:
            self._orphan_actions(props)
        if props.get("settings"):
            self._props_lay.addWidget(_label("SETTINGS", "caps"))
            for s in props["settings"]:
                self._props_lay.addWidget(_SettingRow(
                    s, lambda key, value: self._fire("set_value", key, value),
                    lambda key: self._fire("reset_value", key)))
        if props.get("measured"):
            self._props_lay.addSpacing(10)
            self._props_lay.addWidget(_label("MEASURED", "caps"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(4)
            for r, (name, value) in enumerate(props["measured"]):
                grid.addWidget(_label(name, "meta"), r, 0)
                grid.addWidget(_label(value, "name"), r, 1)
            grid.setColumnStretch(1, 1)
            holder = QWidget()
            holder.setLayout(grid)
            self._props_lay.addWidget(holder)
        self._props_lay.addStretch(1)

    def _orphan_actions(self, props: dict) -> None:
        orphan_id = self._props_selection_id()
        row = QHBoxLayout()
        row.setSpacing(8)
        combo = QComboBox()
        combo.setStyleSheet(STYLE_COMBO)
        targets = sorted(props.get("targets", []), key=lambda t: (t[2] != "new", t[1]))
        for lock_id, name, match in targets:
            combo.addItem(f"{name}  ({match})" if match != "ok" else name, lock_id)
        reassign = self._ghost("  Reassign", "git-merge", "Give its settings and name to this lock")
        reassign.setEnabled(bool(targets))
        reassign.clicked.connect(lambda: self._fire("reassign_orphan", orphan_id, combo.currentData()))
        delete = self._ghost("  Delete", "trash", "Forget it and its settings (Ctrl+Z brings it back)")
        delete.clicked.connect(lambda: self._fire("delete_orphan", orphan_id))
        row.addWidget(combo, stretch=1)
        row.addWidget(reassign)
        row.addWidget(delete)
        holder = QWidget()
        holder.setLayout(row)
        self._props_lay.addWidget(holder)
        self._props_lay.addSpacing(8)

    def _props_selection_id(self) -> Any:
        items = self._tree.selectedItems()
        return items[0].data(COL_NAME, ROLE_ROW)["id"] if items else None

    def set_message(self, text: str, error: bool = False) -> None:
        self._message_label.setText(text)
        self._message_label.setStyleSheet(_text("body", "#fca5a5" if error else TEXT_LABEL))

    def message(self) -> str:
        return self._message_label.text()

    def set_regions_stale(self, stale: bool) -> None:
        self._stale.setVisible(stale)
        self._split_btn.setIcon(_lucide_icon("layout-grid", 14, WARN if stale else TEXT_LABEL))

    def set_display_state(self, mode: str, color_by: str) -> None:
        self._filling = True
        self._display_combo.setCurrentIndex(max(0, self._display_combo.findData(mode)))
        self._color_combo.setCurrentIndex(max(0, self._color_combo.findData(color_by)))
        self._filling = False
        self._mode_label.setText(f"{DISPLAY_LABELS.get(mode, mode)} · colour by {color_by}")

    def set_publish_version(self, version: str, note: str) -> None:
        self._version_edit.setText(version)
        self._version_edit.setToolTip(note)

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
        elif column == COL_DISPLAY:
            menu = self._display_menu(row)
            menu.exec(self._tree.viewport().mapToGlobal(self._tree.visualItemRect(item).bottomRight()))

    def _display_menu(self, row: dict, menu: QMenu | None = None) -> QMenu:
        menu = menu or QMenu(self)
        menu.setStyleSheet(STYLE_MENU)
        kind, ids = self._targets(row)
        for mode in (None,) + config.DISPLAY_MODES:
            action = menu.addAction(DISPLAY_LABELS[mode] if mode else "Auto (node display)")
            action.setCheckable(True)
            action.setChecked(row.get("display") == mode)
            action.triggered.connect(lambda _c=False, m=mode: self._fire("set_row_display", kind, ids, m))
        return menu

    def _row_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        row = item.data(COL_NAME, ROLE_ROW)
        menu = QMenu(self)
        menu.setStyleSheet(STYLE_MENU)
        if row["kind"] in (SEL_GROUP, SEL_LOCKS):
            kind, ids = self._targets(row)
            visible = row.get("visible", True)
            menu.addAction(_lucide_icon("eye-off" if visible else "eye", 14), "Hide" if visible else "Show") \
                .triggered.connect(lambda: self._fire("set_visible", kind, ids, not visible))
            self._display_menu(row, menu.addMenu(_lucide_icon("monitor", 14), "Display"))
        if row["kind"] == SEL_LOCKS:
            unsure = [r["id"] for r in self._selected_rows() if r["kind"] == SEL_LOCKS
                      and ({"unsure", "new"} & set(r["badges"]))] or \
                     ([row["id"]] if {"unsure", "new"} & set(row["badges"]) else [])
            act = menu.addAction(_lucide_icon("check", 14), "Confirm match")
            act.setEnabled(bool(unsure))
            act.triggered.connect(lambda: self._fire("confirm", unsure))
        if row["kind"] == SEL_GROUP:
            colors = menu.addMenu(_lucide_icon("palette", 14), "Colour")
            colors.setStyleSheet(STYLE_MENU)
            for rgb in SWATCHES:
                colors.addAction(_swatch(rgb, 14), "").triggered.connect(
                    lambda _c=False, c=rgb: self._fire("set_group_color", row["id"], c))
        if row["kind"] in (SEL_ORPHAN, ORPHANS_ROW):
            orphans = [row] if row["kind"] == SEL_ORPHAN else \
                [item.child(i).data(COL_NAME, ROLE_ROW) for i in range(item.childCount())]
            locks = [(r["id"], r["name"], r["badges"]) for key, it in self._rows.items() if key[0] == SEL_LOCKS
                     for r in [it.data(COL_NAME, ROLE_ROW)]]
            locks.sort(key=lambda t: ("new" not in t[2], t[1]))
            for orphan in orphans:
                sub = menu.addMenu(_lucide_icon("git-merge", 14), f"Reassign {orphan['name']} to")
                sub.setStyleSheet(STYLE_MENU)
                for lock_id, name, badges in locks:
                    sub.addAction(name + ("  (new)" if "new" in badges else "")).triggered.connect(
                        lambda _c=False, o=orphan["id"], t=lock_id: self._fire("reassign_orphan", o, t))
                sub.setEnabled(bool(locks))
            if row["kind"] == SEL_ORPHAN:
                menu.addAction(_lucide_icon("trash", 14), "Delete orphan").triggered.connect(
                    lambda: self._fire("delete_orphan", row["id"]))
        if not menu.isEmpty():
            menu.exec(self._tree.viewport().mapToGlobal(pos))


__all__ = ["GroomingUI"]
