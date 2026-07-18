"""
Node Preset Library UI — Save dialog + Library panel.
Visual system: Quiet Studio (graphite + soft teal), independent of MONOS zinc/blue.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, QSize, QRect, QRectF, QPoint, QMimeData
from PySide6.QtGui import (
    QIcon,
    QPixmap,
    QColor,
    QPainter,
    QPainterPath,
    QFont,
    QPen,
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QCloseEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
    QCheckBox,
    QComboBox,
    QToolButton,
    QStyledItemDelegate,
    QButtonGroup,
    QSizePolicy,
    QMenu,
    QAbstractItemView,
    QApplication,
    QTabWidget,
    QSlider,
    QColorDialog,
)

from tools.fx.node_preset_library import config
from tools.fx.node_preset_library.logic import (
    category_id_from_name,
    color_for_category_id,
    normalize_category_color,
    random_category_color,
)
from tools.fx.node_preset_library.prefs import (
    DEFAULT_CARD_SCALE,
    DEFAULT_WINDOW_H,
    DEFAULT_WINDOW_W,
    MAX_CARD_SCALE,
    MIN_CARD_SCALE,
    PRESET_MIME,
    clamp_card_scale,
    get_window_geometry,
    set_window_geometry,
)


def _lucide_icon(inner_svg: str, *, size: int = 18, color: str = "#eef1f6") -> QIcon:
    """Render Lucide SVG into a HiDPI-aware QIcon (crisp on scaled displays)."""
    dpr = 1.0
    try:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            dpr = max(1.0, float(screen.devicePixelRatio()))
    except Exception:
        pass

    icon = QIcon()
    # Provide 1x + screen DPR (+2x) so Qt never upscales a soft 1x pixmap
    scales = sorted({1.0, float(dpr), 2.0})
    for scale in scales:
        phys = max(1, int(round(size * scale)))
        # Slightly heavier stroke at tiny logical sizes reads cleaner
        stroke = 2.0 if size >= 18 else 2.25
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{phys}" height="{phys}" '
            f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{stroke}" '
            f'stroke-linecap="round" stroke-linejoin="round">{inner_svg}</svg>'
        )
        pm = QPixmap(phys, phys)
        pm.fill(Qt.GlobalColor.transparent)
        try:
            from PySide6.QtSvg import QSvgRenderer

            renderer = QSvgRenderer(svg.encode("utf-8"))
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            renderer.render(painter)
            painter.end()
        except Exception:
            loaded = QPixmap()
            if loaded.loadFromData(svg.encode("utf-8"), "SVG") and not loaded.isNull():
                pm = loaded.scaled(
                    phys,
                    phys,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            else:
                continue
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def icon_settings() -> QIcon:
    # Lucide "settings"
    return _lucide_icon(
        '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>'
        '<circle cx="12" cy="12" r="3"/>',
        color="#9aa3b5",
    )


def icon_plus() -> QIcon:
    # Lucide "arrow-left" (save selection into library)
    return _lucide_icon(
        '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
        color="#eef1f6",
    )


def icon_plus_add() -> QIcon:
    # Lucide "plus"
    return _lucide_icon(
        '<path d="M5 12h14"/><path d="M12 5v14"/>',
        color="#9aa3b5",
    )


def icon_import() -> QIcon:
    # Lucide "download"
    return _lucide_icon(
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10 12 15 17 10"/>'
        '<line x1="12" x2="12" y1="15" y2="3"/>',
        color="#9aa3b5",
    )


def icon_export() -> QIcon:
    # Lucide "upload"
    return _lucide_icon(
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="17 8 12 3 7 8"/>'
        '<line x1="12" x2="12" y1="3" y2="15"/>',
        color="#9aa3b5",
    )


def icon_folder() -> QIcon:
    # Lucide "folder"
    return _lucide_icon(
        '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9l-.81-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
        color="#9aa3b5",
    )


def icon_pin() -> QIcon:
    # Lucide "pin"
    return _lucide_icon(
        '<path d="M12 17v5"/>'
        '<path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
        size=16,
        color="#9aa3b5",
    )


def icon_pin_on() -> QIcon:
    return _lucide_icon(
        '<path d="M12 17v5"/>'
        '<path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
        size=16,
        color="#5ec4b6",
    )


def icon_layout_grid() -> QIcon:
    # Lucide "layout-grid"
    return _lucide_icon(
        '<rect width="7" height="7" x="3" y="3" rx="1"/>'
        '<rect width="7" height="7" x="14" y="3" rx="1"/>'
        '<rect width="7" height="7" x="14" y="14" rx="1"/>'
        '<rect width="7" height="7" x="3" y="14" rx="1"/>',
        color="#9aa3b5",
    )


def icon_list() -> QIcon:
    # Lucide "list"
    return _lucide_icon(
        '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/>'
        '<path d="M8 12h13"/><path d="M8 18h13"/><path d="M8 6h13"/>',
        color="#9aa3b5",
    )


def icon_search() -> QIcon:
    # Lucide "search"
    return _lucide_icon(
        '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
        size=16,
        color="#9aa3b5",
    )


def icon_layers() -> QIcon:
    # Lucide "layers" — All
    return _lucide_icon(
        '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/>'
        '<path d="M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12"/>'
        '<path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17"/>',
        size=16,
        color="#9aa3b5",
    )


def icon_star() -> QIcon:
    # Lucide "star" — Favorites
    return _lucide_icon(
        '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"/>',
        size=16,
        color="#fbbf24",
    )


def icon_clock() -> QIcon:
    # Lucide "clock" — Recent
    return _lucide_icon(
        '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
        size=16,
        color="#6ea8fe",
    )


def icon_color_tag(hex_color: str, *, size: int = 16) -> QIcon:
    """Filled rounded tag chip for category color."""
    color = normalize_category_color(hex_color, fallback="#5ec4b6")
    dpr = 1.0
    try:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            dpr = max(1.0, float(screen.devicePixelRatio()))
    except Exception:
        pass

    icon = QIcon()
    for scale in sorted({1.0, float(dpr), 2.0}):
        phys = max(1, int(round(size * scale)))
        pm = QPixmap(phys, phys)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        margin = max(1.0, phys * 0.18)
        rect = QRectF(margin, margin, phys - 2 * margin, phys - 2 * margin)
        radius = max(2.0, phys * 0.22)
        painter.setPen(QPen(QColor(0, 0, 0, 60), max(1.0, phys * 0.06)))
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(rect, radius, radius)
        painter.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def category_list_icon(category: dict[str, Any]) -> QIcon:
    """Icon for a sidebar / combo category row."""
    cid = str(category.get("id") or "")
    if cid == "__all__":
        return icon_layers()
    if cid == "__favorites__":
        return icon_star()
    if cid == "__recent__":
        return icon_clock()
    color = category.get("color") or color_for_category_id(cid)
    return icon_color_tag(str(color))


# ---------------------------------------------------------------------------
# Category dialog (name + color tag)
# ---------------------------------------------------------------------------


class CategoryDialog(QDialog):
    """Create / edit category name and color tag."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = "New category",
        name: str = "",
        color: Optional[str] = None,
        used_colors: Optional[set[str]] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CategoryDialog")
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        _apply_dialog_style(self)
        self._used = {normalize_category_color(c) for c in (used_colors or set())}
        self._color = normalize_category_color(
            color,
            fallback=random_category_color(avoid=self._used),
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 18, 20, 16)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700; padding-bottom: 2px;"
        )
        layout.addWidget(title_lbl)

        layout.addWidget(_field_label("Name"))
        self._name_edit = QLineEdit(name)
        self._name_edit.setPlaceholderText("Category name")
        self._name_edit.setStyleSheet(STYLE_INPUT)
        layout.addWidget(self._name_edit)

        layout.addWidget(_field_label("Color tag"))
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        self._swatch_btn = QToolButton()
        self._swatch_btn.setFixedSize(36, 36)
        self._swatch_btn.setToolTip("Pick color")
        self._swatch_btn.setAutoRaise(False)
        self._swatch_btn.clicked.connect(self._pick_color)
        color_row.addWidget(self._swatch_btn)

        self._hex_label = QLabel()
        self._hex_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        color_row.addWidget(self._hex_label, 1)

        pick_btn = QPushButton("Pick…")
        pick_btn.setStyleSheet(STYLE_BTN)
        pick_btn.clicked.connect(self._pick_color)
        color_row.addWidget(pick_btn)

        rand_btn = QPushButton("Random")
        rand_btn.setStyleSheet(STYLE_BTN)
        rand_btn.clicked.connect(self._random_color)
        color_row.addWidget(rand_btn)
        layout.addLayout(color_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setStyleSheet(STYLE_BTN)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok:
            ok.setStyleSheet(STYLE_BTN_PRIMARY)
            ok.setText("Create" if not name.strip() else "Save")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._apply_swatch()
        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _apply_swatch(self) -> None:
        self._hex_label.setText(self._color.upper())
        self._swatch_btn.setIcon(icon_color_tag(self._color, size=20))
        self._swatch_btn.setIconSize(QSize(20, 20))
        self._swatch_btn.setStyleSheet(
            f"""
            QToolButton {{
                background: {BG_SURFACE};
                border: 1px solid {BORDER_STRONG};
                border-radius: 10px;
            }}
            QToolButton:hover {{
                border-color: {ACCENT};
            }}
            """
        )

    def _pick_color(self) -> None:
        initial = QColor(self._color)
        chosen = QColorDialog.getColor(initial, self, "Category color")
        if chosen.isValid():
            self._color = normalize_category_color(chosen.name())
            self._apply_swatch()

    def _random_color(self) -> None:
        avoid = set(self._used)
        avoid.add(self._color)
        self._color = random_category_color(avoid=avoid)
        self._apply_swatch()

    def get_name(self) -> str:
        return self._name_edit.text().strip()

    def get_color(self) -> str:
        return self._color

    def accept(self) -> None:  # type: ignore[override]
        if not self.get_name():
            QMessageBox.information(self, "New category", "Enter a category name.")
            return
        super().accept()


class PresetListWidget(QListWidget):
    """List/grid with left-drag insert + drop from Houdini to save + RBM menu."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        # DefaultContextMenu → contextMenuEvent(); CustomContextMenu skips it.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self._drag_finished_cb: Optional[Callable[[str], None]] = None
        self._context_menu_cb: Optional[Callable[[str, QPoint], None]] = None
        self._houdini_drop_cb: Optional[Callable[[list[str]], None]] = None
        self._mime_paths_fn: Optional[Callable[[QMimeData], list[str]]] = None
        self._press_pos: Optional[QPoint] = None
        self._press_item: Optional[QListWidgetItem] = None

    def on_drag_finished(self, callback: Callable[[str], None]) -> None:
        self._drag_finished_cb = callback

    def on_context_menu(self, callback: Callable[[str, QPoint], None]) -> None:
        self._context_menu_cb = callback

    def on_houdini_nodes_dropped(self, callback: Callable[[list[str]], None]) -> None:
        self._houdini_drop_cb = callback

    def set_mime_paths_extractor(self, fn: Callable[[QMimeData], list[str]]) -> None:
        self._mime_paths_fn = fn

    def _drop_paths(self, mime: QMimeData) -> list[str]:
        if self._mime_paths_fn is not None:
            try:
                return list(self._mime_paths_fn(mime) or [])
            except Exception:
                return []
        # Fallback without Houdini: ignore library preset MIME
        if mime.hasFormat(PRESET_MIME):
            return []
        if mime.hasText():
            text = mime.text() or ""
            out = []
            for part in text.replace("\t", "\n").replace(",", "\n").split("\n"):
                p = part.strip()
                if p.startswith("/"):
                    out.append(p)
            return out
        return []

    def _can_accept_houdini_drop(self, mime: QMimeData) -> bool:
        return bool(self._drop_paths(mime))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        mime = event.mimeData()
        if mime and self._can_accept_houdini_drop(mime):
            event.acceptProposedAction()
            return
        # Allow internal preset drag to pass through without accepting as "save"
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # type: ignore[override]
        mime = event.mimeData()
        if mime and self._can_accept_houdini_drop(mime):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        mime = event.mimeData()
        paths = self._drop_paths(mime) if mime else []
        if paths and self._houdini_drop_cb:
            self._houdini_drop_cb(paths)
            event.acceptProposedAction()
            return
        event.ignore()

    def _item_at(self, pos: QPoint) -> Optional[QListWidgetItem]:
        item = self.itemAt(pos)
        if item is not None:
            return item
        # Fallback: IconMode gaps / delegate padding
        idx = self.indexAt(pos)
        if idx.isValid():
            return self.item(idx.row())
        return None

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.RightButton:
            item = self._item_at(event.position().toPoint() if hasattr(event, "position") else event.pos())
            if item is not None:
                self.setCurrentItem(item)
            # Do not start drag on right-click
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self._press_item = self._item_at(self._press_pos)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        # Only allow drag with left button past startDragDistance
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._press_pos is None:
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if (pos - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        if self._press_item is not None:
            self.setCurrentItem(self._press_item)
            self.startDrag(Qt.DropAction.CopyAction)
            self._press_pos = None
            self._press_item = None
            return
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event) -> None:  # type: ignore[override]
        item = self._item_at(event.pos())
        if item is None or self._context_menu_cb is None:
            event.ignore()
            return
        self.setCurrentItem(item)
        pid = item.data(Qt.ItemDataRole.UserRole)
        if not pid:
            event.ignore()
            return
        self._context_menu_cb(str(pid), event.globalPos())
        event.accept()

    def startDrag(self, supportedActions) -> None:  # type: ignore[override]
        item = self.currentItem() or self._press_item
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        if not pid:
            return
        mime = QMimeData()
        mime.setData(PRESET_MIME, str(pid).encode("utf-8"))
        mime.setText(str(pid))
        drag = QDrag(self)
        drag.setMimeData(mime)
        icon = item.icon()
        if not icon.isNull():
            drag.setPixmap(icon.pixmap(48, 36))
        drag.exec(Qt.DropAction.CopyAction)
        if self._drag_finished_cb:
            self._drag_finished_cb(str(pid))

# ---------------------------------------------------------------------------
# Quiet Studio palette — cool graphite, soft teal accent, low eye strain
# ---------------------------------------------------------------------------
BG_APP = "#0b0d11"
BG_SIDEBAR = "#0f1218"
BG_CONTENT = "#12161e"
BG_SURFACE = "#1a1f2a"
BG_ELEVATED = "#222836"
BG_HOVER = "#2a3142"
BORDER = "rgba(255, 255, 255, 0.07)"
BORDER_STRONG = "rgba(255, 255, 255, 0.12)"
TEXT_PRIMARY = "#eef1f6"
TEXT_SECONDARY = "#9aa3b5"
TEXT_MUTED = "#6b7385"
ACCENT = "#5ec4b6"
ACCENT_DIM = "rgba(94, 196, 182, 0.18)"
ACCENT_BORDER = "rgba(94, 196, 182, 0.55)"
ACCENT_HOVER = "rgba(94, 196, 182, 0.28)"
DANGER = "#e07a7a"
DANGER_DIM = "rgba(224, 122, 122, 0.14)"
DANGER_BORDER = "rgba(224, 122, 122, 0.45)"
FOCUS = ACCENT

# Soft, desaturated network chips (readable on dark cards)
NETWORK_TAG_COLORS = {
    "SOP": "#3d9b6e",
    "VOP": "#8b6bc9",
    "LOP": "#c4844a",
    "OBJ": "#4a9ec9",
    "DOP": "#c47a55",
    "CHOP": "#3aa8b0",
    "COP2": "#c45f8a",
    "TOP": "#b09a3d",
}

STYLE_SCROLLBAR = f"""
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px 1px 4px 0;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255, 255, 255, 0.14);
        border-radius: 5px;
        min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(94, 196, 182, 0.45);
    }}
    QScrollBar::handle:vertical:pressed {{
        background: rgba(94, 196, 182, 0.6);
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
        width: 0;
        border: none;
        background: none;
    }}
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 0 4px 1px 4px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background: rgba(255, 255, 255, 0.14);
        border-radius: 5px;
        min-width: 28px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: rgba(94, 196, 182, 0.45);
    }}
    QScrollBar::handle:horizontal:pressed {{
        background: rgba(94, 196, 182, 0.6);
    }}
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        height: 0;
        width: 0;
        border: none;
        background: none;
    }}
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
"""

STYLE_WINDOW = f"""
    QWidget#NodePresetLibraryWindow {{
        background-color: {BG_APP};
        color: {TEXT_PRIMARY};
        font-size: 13px;
    }}
    QLabel#SectionLabel {{
        color: {TEXT_MUTED};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        padding: 2px 2px 6px 2px;
    }}
    QLabel#FieldLabel {{
        color: {TEXT_SECONDARY};
        font-size: 12px;
        font-weight: 600;
        padding-bottom: 2px;
    }}
""" + STYLE_SCROLLBAR

STYLE_INPUT = f"""
    QLineEdit {{
        padding: 8px 12px;
        border: 1px solid {BORDER};
        border-radius: 10px;
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        selection-background-color: {ACCENT_DIM};
    }}
    QLineEdit:hover {{
        border: 1px solid {BORDER_STRONG};
        background: {BG_ELEVATED};
    }}
    QLineEdit:focus {{
        border: 1px solid {FOCUS};
        background: {BG_ELEVATED};
    }}
    QLineEdit:disabled {{
        color: {TEXT_MUTED};
        background: {BG_CONTENT};
    }}
"""

STYLE_TEXTAREA = f"""
    QPlainTextEdit {{
        padding: 8px 10px;
        border: 1px solid {BORDER};
        border-radius: 10px;
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        selection-background-color: {ACCENT_DIM};
    }}
    QPlainTextEdit:hover {{
        border: 1px solid {BORDER_STRONG};
        background: {BG_ELEVATED};
    }}
    QPlainTextEdit:focus {{
        border: 1px solid {FOCUS};
        background: {BG_ELEVATED};
    }}
""" + STYLE_SCROLLBAR

STYLE_BTN = f"""
    QPushButton {{
        background: {BG_SURFACE};
        color: {TEXT_SECONDARY};
        padding: 7px 14px;
        border: 1px solid {BORDER};
        border-radius: 10px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background: {BG_HOVER};
        border: 1px solid {BORDER_STRONG};
        color: {TEXT_PRIMARY};
    }}
    QPushButton:pressed {{
        background: {BG_ELEVATED};
    }}
    QPushButton:disabled {{
        color: {TEXT_MUTED};
        background: {BG_CONTENT};
        border-color: {BORDER};
    }}
"""

STYLE_BTN_PRIMARY = f"""
    QPushButton {{
        background: {ACCENT_DIM};
        border: 1px solid {ACCENT_BORDER};
        color: {TEXT_PRIMARY};
        padding: 8px 16px;
        border-radius: 10px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: {ACCENT_HOVER};
        border-color: {ACCENT};
        color: #ffffff;
    }}
    QPushButton:pressed {{
        background: rgba(94, 196, 182, 0.35);
    }}
    QPushButton:disabled {{
        color: {TEXT_MUTED};
        background: {BG_SURFACE};
        border-color: {BORDER};
    }}
"""

STYLE_BTN_DANGER = f"""
    QPushButton {{
        background: {DANGER_DIM};
        border: 1px solid {DANGER_BORDER};
        color: {DANGER};
        padding: 7px 14px;
        border-radius: 10px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: rgba(224, 122, 122, 0.24);
        border-color: {DANGER};
        color: #ffb4b4;
    }}
"""

STYLE_COMBO = f"""
    QComboBox {{
        padding: 7px 12px;
        border: 1px solid {BORDER};
        border-radius: 10px;
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        min-width: 110px;
    }}
    QComboBox:hover {{
        border: 1px solid {BORDER_STRONG};
        background: {BG_ELEVATED};
    }}
    QComboBox:focus {{
        border: 1px solid {FOCUS};
    }}
    QComboBox:disabled {{
        color: {TEXT_MUTED};
        background: {BG_CONTENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background: {BG_ELEVATED};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_STRONG};
        selection-background-color: {ACCENT_DIM};
        outline: none;
        padding: 4px;
    }}
""" + STYLE_SCROLLBAR

STYLE_CHECKBOX = f"""
    QCheckBox {{
        color: {TEXT_SECONDARY};
        spacing: 8px;
        font-size: 12px;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 4px;
        border: 1px solid {BORDER_STRONG};
        background: {BG_SURFACE};
    }}
    QCheckBox::indicator:hover {{
        border-color: {ACCENT};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
"""

STYLE_TOOL_BTN = f"""
    QToolButton {{
        background: {BG_SURFACE};
        color: {TEXT_SECONDARY};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 6px 10px;
        font-size: 13px;
        min-width: 28px;
    }}
    QToolButton:hover {{
        background: {BG_HOVER};
        color: {TEXT_PRIMARY};
        border-color: {BORDER_STRONG};
    }}
    QToolButton:checked {{
        background: {ACCENT_DIM};
        color: {ACCENT};
        border-color: {ACCENT_BORDER};
        font-weight: 700;
    }}
"""

STYLE_ICON_BTN = f"""
    QToolButton {{
        background: {BG_SURFACE};
        border: 2px solid #323848;
        border-radius: 10px;
        padding: 0px;
        margin: 0px;
        qproperty-iconSize: 18px;
    }}
    QToolButton:hover {{
        background: {BG_HOVER};
        border-color: #4a5568;
    }}
    QToolButton:pressed {{
        background: {BG_ELEVATED};
    }}
    QToolButton:checked {{
        background: {ACCENT_DIM};
        border: 2px solid {ACCENT};
    }}
"""

STYLE_ICON_BTN_PRIMARY = f"""
    QToolButton {{
        background: {ACCENT_DIM};
        border: 2px solid {ACCENT};
        border-radius: 10px;
        padding: 0px;
        margin: 0px;
        qproperty-iconSize: 18px;
    }}
    QToolButton:hover {{
        background: {ACCENT_HOVER};
        border-color: {ACCENT};
    }}
    QToolButton:pressed {{
        background: rgba(94, 196, 182, 0.35);
    }}
"""

# Grid/List segmented control — no per-button borders
STYLE_VIEW_TOGGLE = f"""
    QToolButton {{
        background: transparent;
        border: none;
        border-radius: 8px;
        padding: 0px;
        margin: 0px;
        qproperty-iconSize: 18px;
    }}
    QToolButton:hover {{
        background: {BG_HOVER};
    }}
    QToolButton:checked {{
        background: {ACCENT_DIM};
    }}
"""

STYLE_SIDEBAR_LIST = f"""
    QListWidget {{
        background: transparent;
        color: {TEXT_PRIMARY};
        border: none;
        outline: none;
        padding: 4px 2px;
    }}
    QListWidget::item {{
        padding: 9px 12px;
        border-radius: 9px;
        margin: 1px 4px;
        color: {TEXT_SECONDARY};
    }}
    QListWidget::item:hover {{
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
    }}
    QListWidget::item:selected {{
        background: {ACCENT_DIM};
        color: {TEXT_PRIMARY};
        border: 1px solid {ACCENT_BORDER};
    }}
""" + STYLE_SCROLLBAR

# Dense list row — fixed columns: thumb | name | tag | description
LIST_ROW_H = 36
LIST_THUMB = QSize(40, 28)
LIST_PAD_X = 10
LIST_GAP = 12
LIST_COL_NAME = 200
LIST_COL_TAG = 52

# Design base at 100% — default prefs use ~70%. Thumb area is 16:9.
BASE_CARD_W = 196
BASE_TEXT_BLOCK_H = 52
BASE_THUMB_GAP = 6
BASE_TEXT_BOTTOM_PAD = 10
BASE_THUMB_H = int(round(BASE_CARD_W * 9 / 16))  # 16:9
BASE_GRID_SIZE = QSize(
    BASE_CARD_W,
    BASE_THUMB_H + BASE_THUMB_GAP + BASE_TEXT_BLOCK_H + BASE_TEXT_BOTTOM_PAD,
)
BASE_ICON_SIZE = QSize(BASE_CARD_W, BASE_THUMB_H)
BASE_GRID_SPACING = 8
# Inset inside each grid cell so cards never touch (Qt spacing alone is unreliable)
BASE_CARD_INSET = 12


def grid_metrics_for_scale(scale_pct: int) -> tuple[QSize, QSize, int, int]:
    """Return (grid_size, icon_size, spacing, inset) for a card scale percent (16:9 thumbs)."""
    s = clamp_card_scale(scale_pct) / 100.0
    # Keep a solid gap even at small card scales
    inset = max(10, int(round(BASE_CARD_INSET * max(s, 0.85))))
    card_w = max(100, int(round(BASE_CARD_W * s)))
    thumb_h = max(56, int(round(card_w * 9 / 16)))
    text_h = max(36, int(round(BASE_TEXT_BLOCK_H * s)))
    gap = max(4, int(round(BASE_THUMB_GAP * s)))
    bottom_pad = max(8, int(round(BASE_TEXT_BOTTOM_PAD * max(s, 0.85))))
    content_h = thumb_h + gap + text_h + bottom_pad
    grid = QSize(card_w + inset * 2, content_h + inset * 2)
    icon = QSize(card_w, thumb_h)
    spacing = max(6, int(round(BASE_GRID_SPACING * max(s, 0.85))))
    return grid, icon, spacing, inset


STYLE_PRESET_LIST = f"""
    QListWidget#PresetList {{
        background: {BG_CONTENT};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        border-radius: 14px;
        padding: 8px;
        outline: none;
    }}
    QListWidget#PresetList::item {{
        color: {TEXT_PRIMARY};
    }}

    QListWidget#PresetList[view="grid"]::item {{
        margin: 0px;
        padding: 0;
        background: transparent;
        border: none;
    }}
    QListWidget#PresetList[view="grid"]::item:selected {{
        background: transparent;
        border: none;
    }}
    QListWidget#PresetList[view="grid"]::item:hover {{
        background: transparent;
        border: none;
    }}

    /* Flat dense rows — background/selection drawn by PresetItemDelegate */
    QListWidget#PresetList[view="list"]::item {{
        margin: 0;
        padding: 0;
        border: none;
        background: transparent;
    }}
    QListWidget#PresetList[view="list"]::item:selected {{
        background: transparent;
    }}
    QListWidget#PresetList[view="list"]::item:hover {{
        background: transparent;
    }}
""" + STYLE_SCROLLBAR

STYLE_DIALOG = f"""
    QDialog {{
        background-color: {BG_APP};
        background: {BG_APP};
        color: {TEXT_PRIMARY};
        font-size: 13px;
    }}
    QDialog QLabel {{
        background: transparent;
        color: {TEXT_PRIMARY};
    }}
    QDialog QDialogButtonBox {{
        background: transparent;
    }}
    QDialog QWidget {{
        color: {TEXT_PRIMARY};
    }}
""" + STYLE_SCROLLBAR


def _apply_dialog_style(dialog: QDialog) -> None:
    """Force Quiet Studio chrome on QDialog (stylesheet alone often skips dialog bg)."""
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dialog.setAutoFillBackground(True)
    pal = dialog.palette()
    bg = QColor(BG_APP)
    pal.setColor(dialog.backgroundRole(), bg)
    pal.setColor(dialog.foregroundRole(), QColor(TEXT_PRIMARY))
    dialog.setPalette(pal)
    dialog.setStyleSheet(STYLE_DIALOG + STYLE_WINDOW)


def _field_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("FieldLabel")
    return lab


def _section_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("SectionLabel")
    return lab


# UserRole+1 networks, +2 name, +3 desc, +4 full-res thumbnail QPixmap
ROLE_THUMB_PIXMAP = int(Qt.ItemDataRole.UserRole) + 4
CARD_RADIUS = 12.0


def _rounded_cover_pixmap(
    src: QPixmap,
    target: QSize,
    radius: float = 12.0,
    *,
    border_color: Optional[str] = None,
    border_width: float = 2.0,
) -> QPixmap:
    """
    Cover-fit pixmap into target, clip to rounded rect, optionally stroke a border
    fully inside the pixmap (avoids QLabel CSS border being cropped by the pixmap).
    """
    if src.isNull() or not target.isValid() or target.width() < 1 or target.height() < 1:
        return QPixmap()
    tw, th = target.width(), target.height()
    r = min(radius, tw / 2.0, th / 2.0)
    scaled = src.scaled(
        target,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - tw) // 2)
    y = max(0, (scaled.height() - th) // 2)
    cropped = scaled.copy(x, y, tw, th)

    out = QPixmap(target)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    # Inset image slightly when stroking so AA border isn't clipped at pixmap edge
    bw = float(border_width) if border_color else 0.0
    pad = bw  # keep full border stroke inside
    inner = QRectF(pad, pad, tw - pad * 2, th - pad * 2)
    inner_r = max(0.0, r - pad)

    clip = QPainterPath()
    if inner.width() > 0 and inner.height() > 0:
        clip.addRoundedRect(inner, inner_r, inner_r)
    else:
        clip.addRoundedRect(QRectF(0, 0, tw, th), r, r)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, cropped)
    painter.setClipping(False)

    if border_color and bw > 0:
        pen = QPen(QColor(border_color), bw)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        half = bw / 2.0
        # Stroke centered on inset rect so entire stroke stays inside pixmap
        stroke = QRectF(half, half, tw - bw, th - bw)
        stroke_r = max(0.0, r - half)
        painter.drawRoundedRect(stroke, stroke_r, stroke_r)

    painter.end()
    return out


def _device_pixel_ratio(painter: QPainter) -> float:
    dev = painter.device()
    if dev is None:
        return 1.0
    try:
        return max(1.0, float(dev.devicePixelRatioF()))
    except Exception:
        return 1.0


def _pixmap_from_icon(icon: QIcon, logical: QSize, dpr: float) -> QPixmap:
    """Pick the sharpest available icon pixmap (prefer native sizes ≥ target×dpr)."""
    if icon.isNull() or not logical.isValid():
        return QPixmap()
    phys = QSize(
        max(1, int(round(logical.width() * dpr))),
        max(1, int(round(logical.height() * dpr))),
    )
    sizes = icon.availableSizes()
    if sizes:
        best = max(sizes, key=lambda s: s.width() * s.height())
        if best.width() >= phys.width() and best.height() >= phys.height():
            return icon.pixmap(best)
    return icon.pixmap(phys)


def _draw_cover_pixmap(painter: QPainter, pix: QPixmap, target: QRect) -> None:
    """Draw pixmap cover-fit into target at device pixel ratio (crisp on HiDPI)."""
    if pix.isNull() or not target.isValid():
        return
    dpr = _device_pixel_ratio(painter)
    phys_w = max(1, int(round(target.width() * dpr)))
    phys_h = max(1, int(round(target.height() * dpr)))
    scaled = pix.scaled(
        phys_w,
        phys_h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - phys_w) // 2)
    y = max(0, (scaled.height() - phys_h) // 2)
    cropped = scaled.copy(x, y, phys_w, phys_h)
    cropped.setDevicePixelRatio(dpr)
    painter.drawPixmap(target.topLeft(), cropped)


class PresetItemDelegate(QStyledItemDelegate):
    """Grid + list cards fully custom-painted."""

    def sizeHint(self, option, index):  # type: ignore[override]
        parent = self.parent()
        try:
            if isinstance(parent, QListWidget) and parent.viewMode() == QListWidget.ViewMode.ListMode:
                return QSize(max(200, option.rect.width()), LIST_ROW_H)
            if isinstance(parent, QListWidget) and parent.viewMode() == QListWidget.ViewMode.IconMode:
                gs = parent.gridSize()
                if gs.isValid() and gs.width() > 0 and gs.height() > 0:
                    return gs
        except Exception:
            pass
        return super().sizeHint(option, index)

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        parent = self.parent()
        is_list = (
            isinstance(parent, QListWidget)
            and parent.viewMode() == QListWidget.ViewMode.ListMode
        )
        if is_list:
            self._paint_list_row(painter, option, index)
            return
        self._paint_grid_card(painter, option, index)

    def _resolve_thumb_pixmap(self, painter: QPainter, index, logical: QSize) -> QPixmap:
        stored = index.data(ROLE_THUMB_PIXMAP)
        if isinstance(stored, QPixmap) and not stored.isNull():
            return stored
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            return _pixmap_from_icon(icon, logical, _device_pixel_ratio(painter))
        return QPixmap()

    def _paint_grid_card(self, painter: QPainter, option, index) -> None:
        """Thumb flush under rounded card clip; bold name; single-line description."""
        from PySide6.QtWidgets import QStyle

        rect: QRect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # Leave empty gutter around the painted card (reliable gap between neighbors)
        inset = BASE_CARD_INSET
        parent = self.parent()
        if isinstance(parent, QListWidget):
            prop = parent.property("cardInset")
            if prop is not None:
                try:
                    inset = max(6, int(prop))
                except (TypeError, ValueError):
                    pass
        if inset > 0 and rect.width() > inset * 2 + 40 and rect.height() > inset * 2 + 40:
            rect = rect.adjusted(inset, inset, -inset, -inset)

        name = index.data(Qt.ItemDataRole.UserRole + 2) or ""
        if not name:
            display = index.data(Qt.ItemDataRole.DisplayRole) or ""
            name = str(display).split("\n", 1)[0]
        desc = index.data(Qt.ItemDataRole.UserRole + 3) or ""
        nets = index.data(Qt.ItemDataRole.UserRole + 1) or []
        if isinstance(nets, str):
            nets = [nets]
        tag = str(nets[0]) if nets else ""

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Card chrome — selection wins over hover so accent border never drops
        border_w = 2.5 if selected else 1.25
        if selected:
            bg = QColor(BG_ELEVATED)
            border = QColor(ACCENT)
        elif hovered:
            bg = QColor(BG_HOVER)
            border = QColor("#5a6578")
        else:
            bg = QColor(BG_SURFACE)
            border = QColor("#3a4254")

        card = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
        half = border_w / 2.0
        fill_r = card.adjusted(half, half, -half, -half)
        radius = CARD_RADIUS

        card_path = QPainterPath()
        card_path.addRoundedRect(fill_r, radius, radius)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawPath(card_path)

        # Clip ALL card content to rounded fill — prevents thumb square corners leaking
        painter.setClipPath(card_path)

        # Thumbnail — fixed 16:9 from card width
        scale_ref = fill_r.width() / max(1.0, float(BASE_CARD_W))
        bottom_pad = max(8, int(round(BASE_TEXT_BOTTOM_PAD * max(scale_ref, 0.85))))
        text_block_h = max(36, min(56, int(round(BASE_TEXT_BLOCK_H * scale_ref))))
        thumb_w = fill_r.width()
        thumb_h = thumb_w * 9.0 / 16.0
        max_thumb_h = max(36.0, fill_r.height() - text_block_h - bottom_pad - 4.0)
        if thumb_h > max_thumb_h:
            # Card shorter than ideal: keep 16:9 by letterboxing width
            thumb_h = max_thumb_h
            thumb_w = thumb_h * 16.0 / 9.0
        thumb_x = fill_r.left() + (fill_r.width() - thumb_w) / 2.0
        thumb_f = QRectF(thumb_x, fill_r.top(), thumb_w, thumb_h)
        thumb_rect = thumb_f.toAlignedRect()

        painter.fillRect(thumb_rect, QColor(BG_ELEVATED))

        thumb_path = QPainterPath()
        thumb_path.addRect(QRectF(thumb_rect))
        painter.setClipPath(card_path.intersected(thumb_path))

        pix = self._resolve_thumb_pixmap(painter, index, thumb_rect.size())
        if not pix.isNull():
            _draw_cover_pixmap(painter, pix, thumb_rect)
        else:
            painter.setClipping(False)
            painter.setClipPath(card_path)
            painter.setPen(QColor(TEXT_MUTED))
            font = QFont(painter.font())
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(thumb_rect, int(Qt.AlignmentFlag.AlignCenter), "No preview")

        painter.setClipping(False)
        painter.setClipPath(card_path)

        # Tag on thumb
        if tag:
            chip_font = QFont(painter.font())
            chip_font.setPointSize(max(8, chip_font.pointSize() - 1))
            chip_font.setBold(True)
            painter.setFont(chip_font)
            fm = painter.fontMetrics()
            pad_x, pad_y = 6, 2
            cw = fm.horizontalAdvance(tag) + pad_x * 2
            ch = fm.height() + pad_y * 2
            chip = QRect(thumb_rect.left() + 6, thumb_rect.top() + 6, cw, ch)
            fill = QColor(NETWORK_TAG_COLORS.get(tag, "#4a5568"))
            fill.setAlpha(220)
            painter.setBrush(fill)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(chip, 5, 5)
            painter.setPen(QColor("#f4f7fb"))
            painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), tag)

        # Text block under thumb
        text_top = thumb_rect.bottom() + max(4, int(round(BASE_THUMB_GAP * scale_ref)))
        text_left = int(fill_r.left()) + 8
        text_w = int(fill_r.width()) - 16

        name_font = QFont(painter.font())
        name_font.setBold(True)
        name_font.setPointSize(max(9, name_font.pointSize()))
        painter.setFont(name_font)
        fm_name = painter.fontMetrics()
        name_h = fm_name.height()
        painter.setPen(QColor(TEXT_PRIMARY))
        painter.drawText(
            QRect(text_left, text_top, text_w, name_h),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            fm_name.elidedText(str(name), Qt.TextElideMode.ElideRight, text_w),
        )

        if desc:
            desc_font = QFont(painter.font())
            desc_font.setBold(False)
            desc_font.setPointSize(max(8, desc_font.pointSize() - 1))
            painter.setFont(desc_font)
            fm_desc = painter.fontMetrics()
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                QRect(text_left, text_top + name_h + 2, text_w, fm_desc.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                fm_desc.elidedText(str(desc), Qt.TextElideMode.ElideRight, text_w),
            )

        painter.setClipping(False)

        # Border last so content never erases it
        pen = QPen(border, border_w)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawRoundedRect(card.adjusted(half, half, -half, -half), radius, radius)

        painter.restore()

    def _paint_list_row(self, painter: QPainter, option, index) -> None:
        """Fixed columns: thumb | name | tag (1) | description."""
        from PySide6.QtWidgets import QStyle

        rect: QRect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if selected:
            painter.fillRect(rect, QColor(ACCENT_DIM))
            painter.setPen(QPen(QColor(ACCENT), 1))
            painter.drawLine(rect.left(), rect.top(), rect.left(), rect.bottom())
        elif hovered:
            painter.fillRect(rect, QColor(BG_SURFACE))

        painter.setPen(QPen(QColor("#1c2230"), 1))
        painter.drawLine(rect.left() + 8, rect.bottom(), rect.right() - 8, rect.bottom())

        name = index.data(Qt.ItemDataRole.UserRole + 2) or ""
        if not name:
            display = index.data(Qt.ItemDataRole.DisplayRole) or ""
            name = str(display).split("\n", 1)[0]
        desc = index.data(Qt.ItemDataRole.UserRole + 3) or ""
        nets = index.data(Qt.ItemDataRole.UserRole + 1) or []
        if isinstance(nets, str):
            nets = [nets]
        tag = str(nets[0]) if nets else ""

        mid_y = rect.center().y()
        left = rect.left() + LIST_PAD_X

        # --- Col: thumbnail ---
        thumb_w, thumb_h = LIST_THUMB.width(), LIST_THUMB.height()
        thumb_rect = QRect(left, mid_y - thumb_h // 2, thumb_w, thumb_h)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        thumb_path = QPainterPath()
        thumb_path.addRoundedRect(QRectF(thumb_rect), 4, 4)
        painter.setClipPath(thumb_path)
        painter.fillRect(thumb_rect, QColor(BG_ELEVATED))
        pix = self._resolve_thumb_pixmap(painter, index, thumb_rect.size())
        if not pix.isNull():
            _draw_cover_pixmap(painter, pix, thumb_rect)
        painter.setClipping(False)

        # --- Col: name ---
        name_x = thumb_rect.right() + LIST_GAP
        name_rect = QRect(name_x, rect.top(), LIST_COL_NAME, rect.height())
        name_font = QFont(painter.font())
        name_font.setBold(True)
        name_font.setPointSize(max(9, name_font.pointSize()))
        painter.setFont(name_font)
        fm_name = painter.fontMetrics()
        painter.setPen(QColor(TEXT_PRIMARY))
        painter.drawText(
            name_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            fm_name.elidedText(str(name), Qt.TextElideMode.ElideRight, LIST_COL_NAME),
        )

        # --- Col: single network tag ---
        tag_x = name_rect.right() + LIST_GAP
        tag_rect = QRect(tag_x, rect.top(), LIST_COL_TAG, rect.height())
        if tag:
            chip_font = QFont(painter.font())
            chip_font.setPointSize(max(8, chip_font.pointSize() - 1))
            chip_font.setBold(True)
            painter.setFont(chip_font)
            fm_chip = painter.fontMetrics()
            tw = fm_chip.horizontalAdvance(tag)
            cw, ch = tw + 10, fm_chip.height() + 2
            chip = QRect(
                tag_rect.left(),
                mid_y - ch // 2,
                min(cw, LIST_COL_TAG),
                ch,
            )
            fill = QColor(NETWORK_TAG_COLORS.get(tag, "#4a5568"))
            fill.setAlpha(210)
            painter.setBrush(fill)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(chip, 5, 5)
            painter.setPen(QColor("#f4f7fb"))
            painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), tag)

        # --- Col: description (remaining width) ---
        desc_x = tag_rect.right() + LIST_GAP
        desc_w = max(0, rect.right() - LIST_PAD_X - desc_x)
        if desc and desc_w > 24:
            desc_font = QFont(painter.font())
            desc_font.setBold(False)
            desc_font.setPointSize(max(8, desc_font.pointSize() - 1))
            painter.setFont(desc_font)
            fm_desc = painter.fontMetrics()
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                QRect(desc_x, rect.top(), desc_w, rect.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                fm_desc.elidedText(str(desc), Qt.TextElideMode.ElideRight, desc_w),
            )

        painter.restore()


# ---------------------------------------------------------------------------
# Save Preset Dialog
# ---------------------------------------------------------------------------


class SavePresetDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("SavePresetDialog")
        self.setWindowTitle("Save to Library")
        self.setMinimumWidth(480)
        _apply_dialog_style(self)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 18)

        self._title_label = QLabel("Save preset")
        self._title_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 16px; font-weight: 700; padding-bottom: 4px;"
        )
        layout.addWidget(self._title_label)

        layout.addWidget(_field_label("Name"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Preset name")
        self._name_edit.setStyleSheet(STYLE_INPUT)
        layout.addWidget(self._name_edit)

        layout.addWidget(_field_label("Category"))
        cat_layout = QHBoxLayout()
        cat_layout.setSpacing(8)
        self._category_combo = QComboBox()
        self._category_combo.setStyleSheet(STYLE_COMBO)
        self._category_combo.setEditable(False)
        self._category_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        cat_layout.addWidget(self._category_combo, 1)
        self._new_cat_btn = QPushButton("New…")
        self._new_cat_btn.setStyleSheet(STYLE_BTN)
        self._new_cat_btn.setToolTip("Create a new category")
        cat_layout.addWidget(self._new_cat_btn)
        layout.addLayout(cat_layout)

        layout.addWidget(_field_label("Description"))
        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText("Short description of what this preset does…")
        self._desc_edit.setFixedHeight(72)
        self._desc_edit.setStyleSheet(STYLE_TEXTAREA)
        layout.addWidget(self._desc_edit)

        layout.addWidget(_field_label("Thumbnail"))
        thumb_row = QHBoxLayout()
        thumb_row.setSpacing(12)
        # 2× previous 88×66 preview
        self._thumb_preview_size = QSize(176, 132)
        self._thumb_preview = QLabel()
        self._thumb_preview.setFixedSize(self._thumb_preview_size)
        self._thumb_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_preview.setStyleSheet(
            f"background: {BG_SURFACE}; border: 2px dashed {BORDER_STRONG}; "
            f"border-radius: 12px; color: {TEXT_MUTED}; font-size: 11px;"
        )
        self._thumb_preview.setText("No image")
        thumb_row.addWidget(self._thumb_preview)
        thumb_col = QVBoxLayout()
        thumb_col.setSpacing(6)
        self._capture_thumb_btn = QPushButton("Capture from network")
        self._capture_thumb_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        thumb_col.addWidget(self._capture_thumb_btn)
        self._paste_thumb_btn = QPushButton("Paste from clipboard")
        self._paste_thumb_btn.setStyleSheet(STYLE_BTN)
        thumb_col.addWidget(self._paste_thumb_btn)
        tip = QLabel("Auto-capture uses selection layout; paste overrides.")
        tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        tip.setWordWrap(True)
        thumb_col.addWidget(tip)
        thumb_col.addStretch()
        thumb_row.addLayout(thumb_col, 1)
        layout.addLayout(thumb_row)

        self._embed_hda_chk = QCheckBox("Embed HDA definitions (portable, larger file)")
        self._embed_hda_chk.setStyleSheet(STYLE_CHECKBOX)
        self._embed_hda_chk.setToolTip(
            "Include HDA definitions in the preset so machines without those HDAs can still load it."
        )
        layout.addWidget(self._embed_hda_chk)

        self._thumb_pixmap: Optional[QPixmap] = None

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn:
            cancel_btn.setStyleSheet(STYLE_BTN)
        self._save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if self._save_btn:
            self._save_btn.setStyleSheet(STYLE_BTN_PRIMARY)
            self._save_btn.setText("Save preset")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addSpacing(6)
        layout.addWidget(buttons)

    def set_mode(self, mode: str) -> None:
        """mode: 'save' | 'edit'."""
        if mode == "edit":
            self.setWindowTitle("Edit preset")
            self._title_label.setText("Edit preset")
            if self._save_btn:
                self._save_btn.setText("Save changes")
            self._embed_hda_chk.setVisible(False)
        else:
            self.setWindowTitle("Save to Library")
            self._title_label.setText("Save preset")
            if self._save_btn:
                self._save_btn.setText("Save preset")
            self._embed_hda_chk.setVisible(True)

    def get_embed_hda(self) -> bool:
        return bool(self._embed_hda_chk.isChecked())

    def set_embed_hda(self, value: bool) -> None:
        self._embed_hda_chk.setChecked(value)

    def get_name(self) -> str:
        return self._name_edit.text().strip()

    def set_name(self, value: str) -> None:
        self._name_edit.setText(value)

    def get_category(self) -> str:
        return self._category_combo.currentText().strip()

    def set_categories(self, categories: list[dict[str, Any]]) -> None:
        current = self._category_combo.currentData()
        self._category_combo.clear()
        for c in categories:
            self._category_combo.addItem(
                category_list_icon(c),
                str(c.get("name", "")),
                c.get("id", ""),
            )
        if self._category_combo.count() == 0:
            self._category_combo.addItem(
                icon_color_tag(color_for_category_id("uncategorized")),
                "Uncategorized",
                "uncategorized",
            )
        # Restore previous selection when possible
        if current is not None:
            self.set_category(str(current))
        elif self._category_combo.count() > 0:
            self._category_combo.setCurrentIndex(0)

    def set_category(self, category_id: str) -> None:
        for i in range(self._category_combo.count()):
            if self._category_combo.itemData(i) == category_id:
                self._category_combo.setCurrentIndex(i)
                return
        # Fallback: match by display name
        for i in range(self._category_combo.count()):
            if self._category_combo.itemText(i).strip().lower() == str(category_id).strip().lower():
                self._category_combo.setCurrentIndex(i)
                return
        if self._category_combo.count() > 0:
            self._category_combo.setCurrentIndex(0)

    def get_category_id(self) -> str:
        idx = self._category_combo.currentIndex()
        if idx >= 0:
            cid = self._category_combo.itemData(idx)
            if cid:
                return str(cid)
        text = self.get_category()
        return category_id_from_name(text) if text else "uncategorized"

    def get_description(self) -> str:
        return self._desc_edit.toPlainText().strip()

    def set_description(self, text: str) -> None:
        self._desc_edit.setPlainText(text or "")

    def set_thumbnail_from_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        self._thumb_pixmap = pixmap
        if pixmap and not pixmap.isNull():
            size = getattr(self, "_thumb_preview_size", QSize(176, 132))
            rounded = _rounded_cover_pixmap(
                pixmap,
                size,
                radius=12.0,
                border_color=ACCENT,
                border_width=2.0,
            )
            self._thumb_preview.setPixmap(rounded)
            self._thumb_preview.setText("")
            self._thumb_preview.setStyleSheet(
                "background: transparent; border: none; padding: 0px;"
            )
        else:
            self._thumb_preview.clear()
            self._thumb_preview.setText("No image")
            self._thumb_preview.setStyleSheet(
                f"background: {BG_SURFACE}; border: 2px dashed {BORDER_STRONG}; "
                f"border-radius: 12px; color: {TEXT_MUTED}; font-size: 11px;"
            )
            self._thumb_pixmap = None

    def get_thumbnail_pixmap(self) -> Optional[QPixmap]:
        return self._thumb_pixmap

    def on_new_category(self, callback: Callable[[], None]) -> None:
        self._new_cat_btn.clicked.connect(callback)

    def on_paste_thumbnail(self, callback: Callable[[], None]) -> None:
        self._paste_thumb_btn.clicked.connect(callback)

    def on_capture_thumbnail(self, callback: Callable[[], None]) -> None:
        self._capture_thumb_btn.clicked.connect(callback)


# ---------------------------------------------------------------------------
# Settings dialog — library location + recent roots
# ---------------------------------------------------------------------------


class SettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsDialog")
        self.setWindowTitle("Library Settings")
        self.setMinimumWidth(540)
        self.setMinimumHeight(420)
        _apply_dialog_style(self)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 14)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"""
            QTabWidget::pane {{
                border: 1px solid {BORDER};
                border-radius: 12px;
                background: {BG_CONTENT};
                top: -1px;
            }}
            QTabBar::tab {{
                background: {BG_SURFACE};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER};
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 8px 16px;
                margin-right: 4px;
            }}
            QTabBar::tab:selected {{
                background: {BG_CONTENT};
                color: {TEXT_PRIMARY};
                border-color: {ACCENT_BORDER};
            }}
            QTabBar::tab:hover {{
                color: {TEXT_PRIMARY};
            }}
            """
        )

        # --- Library tab ---
        lib_page = QWidget()
        lib_layout = QVBoxLayout(lib_page)
        lib_layout.setSpacing(12)
        lib_layout.setContentsMargins(14, 14, 14, 12)

        title = QLabel("Library location")
        title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700; padding-bottom: 2px;"
        )
        lib_layout.addWidget(title)

        tip = QLabel("Choose the folder that holds index.json and categories/.")
        tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        tip.setWordWrap(True)
        lib_layout.addWidget(tip)

        lib_layout.addWidget(_field_label("Current path"))
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self._path_edit = QLineEdit()
        self._path_edit.setStyleSheet(STYLE_INPUT)
        self._path_edit.setPlaceholderText("Library folder…")
        path_row.addWidget(self._path_edit, 1)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setStyleSheet(STYLE_BTN)
        path_row.addWidget(self._browse_btn)
        lib_layout.addLayout(path_row)

        self._reset_btn = QPushButton("Use default location")
        self._reset_btn.setStyleSheet(STYLE_BTN)
        lib_layout.addWidget(self._reset_btn)

        lib_layout.addWidget(_section_label("Recent locations"))
        self._recent_list = QListWidget()
        self._recent_list.setStyleSheet(STYLE_SIDEBAR_LIST)
        self._recent_list.setMinimumHeight(120)
        self._recent_list.setMaximumHeight(160)
        lib_layout.addWidget(self._recent_list)

        recent_btns = QHBoxLayout()
        recent_btns.setSpacing(8)
        self._use_recent_btn = QPushButton("Use selected")
        self._use_recent_btn.setStyleSheet(STYLE_BTN)
        self._pin_recent_btn = QPushButton("Pin")
        self._pin_recent_btn.setStyleSheet(STYLE_BTN)
        self._pin_recent_btn.setToolTip("Pin so this path is kept when new locations are added")
        self._remove_recent_btn = QPushButton("Remove from list")
        self._remove_recent_btn.setStyleSheet(STYLE_BTN_DANGER)
        recent_btns.addWidget(self._use_recent_btn)
        recent_btns.addWidget(self._pin_recent_btn)
        recent_btns.addWidget(self._remove_recent_btn)
        recent_btns.addStretch()
        lib_layout.addLayout(recent_btns)

        self._recent_hint = QLabel(
            "Up to 5 folders. Pin keeps a path when new ones arrive. Missing paths are dropped."
        )
        self._recent_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._recent_hint.setWordWrap(True)
        lib_layout.addWidget(self._recent_hint)
        lib_layout.addStretch(1)
        tabs.addTab(lib_page, "Library")

        # --- UI tab ---
        ui_page = QWidget()
        ui_layout = QVBoxLayout(ui_page)
        ui_layout.setSpacing(12)
        ui_layout.setContentsMargins(14, 14, 14, 12)

        ui_title = QLabel("Appearance")
        ui_title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 700; padding-bottom: 2px;"
        )
        ui_layout.addWidget(ui_title)

        ui_tip = QLabel("Adjust how large preset cards appear in grid view.")
        ui_tip.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        ui_tip.setWordWrap(True)
        ui_layout.addWidget(ui_tip)

        ui_layout.addWidget(_field_label("Card size"))
        scale_row = QHBoxLayout()
        scale_row.setSpacing(10)
        self._card_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._card_scale_slider.setRange(MIN_CARD_SCALE, MAX_CARD_SCALE)
        self._card_scale_slider.setSingleStep(5)
        self._card_scale_slider.setPageStep(10)
        self._card_scale_slider.setTickInterval(10)
        self._card_scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._card_scale_slider.setValue(DEFAULT_CARD_SCALE)
        self._card_scale_slider.setStyleSheet(
            f"""
            QSlider::groove:horizontal {{
                height: 6px;
                background: {BG_ELEVATED};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                margin: -5px 0;
                background: {ACCENT};
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT_DIM};
                border-radius: 3px;
            }}
            """
        )
        self._card_scale_value = QLabel(f"{DEFAULT_CARD_SCALE}%")
        self._card_scale_value.setMinimumWidth(44)
        self._card_scale_value.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
        )
        scale_row.addWidget(self._card_scale_slider, 1)
        scale_row.addWidget(self._card_scale_value)
        ui_layout.addLayout(scale_row)

        scale_hint = QLabel(f"{MIN_CARD_SCALE}% compact  ·  {MAX_CARD_SCALE}% large  ·  default {DEFAULT_CARD_SCALE}%")
        scale_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        ui_layout.addWidget(scale_hint)
        ui_layout.addStretch(1)
        tabs.addTab(ui_page, "UI")

        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn:
            cancel_btn.setStyleSheet(STYLE_BTN)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setStyleSheet(STYLE_BTN_PRIMARY)
            ok_btn.setText("Apply")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._browse_btn.clicked.connect(self._on_browse)
        self._use_recent_btn.clicked.connect(self._on_use_recent)
        self._recent_list.itemDoubleClicked.connect(lambda _i: self._on_use_recent())
        self._recent_list.currentItemChanged.connect(self._sync_pin_button)
        self._card_scale_slider.valueChanged.connect(self._on_card_scale_changed)

    def _on_card_scale_changed(self, value: int) -> None:
        self._card_scale_value.setText(f"{int(value)}%")

    def _on_browse(self) -> None:
        start = self._path_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Select library folder", start)
        if path:
            self._path_edit.setText(path)

    def _on_use_recent(self) -> None:
        item = self._recent_list.currentItem()
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole) or item.text()
        self._path_edit.setText(str(path))

    def set_current_path(self, path: str) -> None:
        self._path_edit.setText(path)

    def get_current_path(self) -> str:
        return self._path_edit.text().strip()

    def set_recent_paths(
        self,
        paths: list[str],
        pinned_paths: Optional[list[str]] = None,
    ) -> None:
        pinned = {str(Path(p)).lower() for p in (pinned_paths or [])}
        # Also accept already-normalized keys
        pinned |= {p.lower() for p in (pinned_paths or [])}
        self._recent_list.clear()
        for p in paths:
            pinned_here = False
            try:
                pinned_here = str(Path(p).expanduser().resolve()).lower() in pinned or p.lower() in pinned
            except OSError:
                pinned_here = p.lower() in pinned
            label = p
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setData(Qt.ItemDataRole.UserRole + 1, pinned_here)
            item.setToolTip(("Pinned — " if pinned_here else "") + p)
            if pinned_here:
                item.setIcon(icon_pin_on())
            self._recent_list.addItem(item)
        self._sync_pin_button()

    def get_selected_recent_path(self) -> Optional[str]:
        item = self._recent_list.currentItem()
        if not item:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole) or item.text())

    def select_recent_path(self, path: str) -> None:
        target = str(path)
        for i in range(self._recent_list.count()):
            item = self._recent_list.item(i)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == target:
                self._recent_list.setCurrentItem(item)
                return
        self._sync_pin_button()

    def _sync_pin_button(self, *_args) -> None:
        item = self._recent_list.currentItem()
        if not item:
            self._pin_recent_btn.setText("Pin")
            self._pin_recent_btn.setEnabled(False)
            return
        self._pin_recent_btn.setEnabled(True)
        pinned = bool(item.data(Qt.ItemDataRole.UserRole + 1))
        self._pin_recent_btn.setText("Unpin" if pinned else "Pin")

    def set_card_scale(self, scale: int) -> None:
        self._card_scale_slider.setValue(clamp_card_scale(scale))

    def get_card_scale(self) -> int:
        return clamp_card_scale(self._card_scale_slider.value())

    def on_reset_default(self, callback: Callable[[], None]) -> None:
        self._reset_btn.clicked.connect(callback)

    def on_remove_recent(self, callback: Callable[[], None]) -> None:
        self._remove_recent_btn.clicked.connect(callback)

    def on_pin_recent(self, callback: Callable[[], None]) -> None:
        self._pin_recent_btn.clicked.connect(callback)


# ---------------------------------------------------------------------------
# Library main window
# ---------------------------------------------------------------------------


class NodePresetLibraryUI(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("NodePresetLibraryWindow")
        self.setMinimumSize(900, 520)
        self.setStyleSheet(STYLE_WINDOW)
        self._card_scale = DEFAULT_CARD_SCALE
        self._view_mode = "grid"
        self._open_folder_cb: Optional[Callable[[], None]] = None
        self._houdini_drop_cb: Optional[Callable[[list[str]], None]] = None
        self._mime_paths_fn: Optional[Callable[[QMimeData], list[str]]] = None
        self.setAcceptDrops(True)

        main = QVBoxLayout(self)
        main.setSpacing(12)
        main.setContentsMargins(14, 14, 14, 12)

        # Top bar: [Auto|Network] … [Search] … [view|settings|save]
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        left_bar = QHBoxLayout()
        left_bar.setSpacing(8)
        left_bar.setContentsMargins(0, 0, 0, 0)
        self._auto_detect_chk = QCheckBox("Auto")
        self._auto_detect_chk.setChecked(True)
        self._auto_detect_chk.setToolTip("Auto detect network")
        self._auto_detect_chk.setStyleSheet(STYLE_CHECKBOX)
        left_bar.addWidget(self._auto_detect_chk)

        self._network_combo = QComboBox()
        self._network_combo.setStyleSheet(STYLE_COMBO)
        self._network_combo.setMinimumWidth(96)
        self._network_combo.setMaximumWidth(120)
        self._network_combo.addItem("All", "__all__")
        for tag in ["SOP", "VOP", "LOP", "OBJ", "DOP", "CHOP", "COP2", "TOP"]:
            self._network_combo.addItem(tag, tag)
        self._network_combo.setEnabled(False)
        left_bar.addWidget(self._network_combo)
        left_bar.addStretch(1)
        left_wrap = QWidget()
        left_wrap.setLayout(left_bar)
        left_wrap.setMinimumWidth(180)
        toolbar.addWidget(left_wrap, 1)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search presets…")
        self._search_edit.setStyleSheet(STYLE_INPUT)
        self._search_edit.setMinimumHeight(34)
        self._search_edit.setMinimumWidth(320)
        self._search_edit.setMaximumWidth(520)
        self._search_edit.setClearButtonEnabled(True)
        search_icon_action = self._search_edit.addAction(
            icon_search(),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        search_icon_action.setToolTip("Search")
        # Center the search field within the middle stretch zone
        center_wrap = QWidget()
        center_row = QHBoxLayout(center_wrap)
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.addStretch(1)
        center_row.addWidget(self._search_edit, 0)
        center_row.addStretch(1)
        toolbar.addWidget(center_wrap, 2)

        right_bar = QHBoxLayout()
        right_bar.setSpacing(6)
        right_bar.setContentsMargins(0, 0, 0, 0)
        right_bar.addStretch(1)

        view_wrap = QWidget()
        view_wrap.setStyleSheet(
            f"background: {BG_SURFACE}; border: 2px solid #323848; border-radius: 10px;"
        )
        view_row = QHBoxLayout(view_wrap)
        view_row.setContentsMargins(2, 2, 2, 2)
        view_row.setSpacing(2)
        self._view_grid_btn = QToolButton()
        self._view_grid_btn.setIcon(icon_layout_grid())
        self._view_grid_btn.setIconSize(QSize(18, 18))
        self._view_grid_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._view_grid_btn.setToolTip("Grid view")
        self._view_grid_btn.setCheckable(True)
        self._view_grid_btn.setFixedSize(32, 32)
        self._view_grid_btn.setStyleSheet(STYLE_VIEW_TOGGLE)
        self._view_list_btn = QToolButton()
        self._view_list_btn.setIcon(icon_list())
        self._view_list_btn.setIconSize(QSize(18, 18))
        self._view_list_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._view_list_btn.setToolTip("List view")
        self._view_list_btn.setCheckable(True)
        self._view_list_btn.setFixedSize(32, 32)
        self._view_list_btn.setStyleSheet(STYLE_VIEW_TOGGLE)
        self._view_grid_btn.setChecked(True)
        view_group = QButtonGroup(self)
        view_group.setExclusive(True)
        view_group.addButton(self._view_grid_btn)
        view_group.addButton(self._view_list_btn)
        view_row.addWidget(self._view_grid_btn)
        view_row.addWidget(self._view_list_btn)
        right_bar.addWidget(view_wrap)

        self._settings_btn = QToolButton()
        self._settings_btn.setIcon(icon_settings())
        self._settings_btn.setIconSize(QSize(18, 18))
        self._settings_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._settings_btn.setToolTip("Settings — library location")
        self._settings_btn.setStyleSheet(STYLE_ICON_BTN)
        self._settings_btn.setFixedSize(36, 36)
        self._settings_btn.setAutoRaise(False)
        right_bar.addWidget(self._settings_btn)

        self._save_btn = QToolButton()
        self._save_btn.setIcon(icon_plus())
        self._save_btn.setIconSize(QSize(18, 18))
        self._save_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._save_btn.setToolTip("Save selection to Library")
        self._save_btn.setStyleSheet(STYLE_ICON_BTN_PRIMARY)
        self._save_btn.setFixedSize(36, 36)
        self._save_btn.setAutoRaise(False)
        right_bar.addWidget(self._save_btn)

        right_wrap = QWidget()
        right_wrap.setLayout(right_bar)
        right_wrap.setMinimumWidth(180)
        toolbar.addWidget(right_wrap, 1)
        main.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("MainSplitter")
        splitter.setContentsMargins(0, 0, 0, 0)
        splitter.setHandleWidth(8)
        splitter.setStyleSheet(
            f"""
            QSplitter#MainSplitter::handle {{
                background: transparent;
            }}
            QSplitter#MainSplitter::handle:hover {{
                background: {ACCENT_DIM};
            }}
            """
        )

        # Categories (left)
        cat_widget = QWidget()
        cat_widget.setObjectName("SidebarPanel")
        cat_widget.setStyleSheet(
            f"""
            QWidget#SidebarPanel {{
                background-color: {BG_SIDEBAR};
                border: 1px solid {BORDER};
                border-radius: 14px;
            }}
            """
        )
        cat_widget.setMinimumWidth(190)
        cat_widget.setMaximumWidth(280)
        cat_layout = QVBoxLayout(cat_widget)
        cat_layout.setContentsMargins(10, 12, 10, 10)
        cat_layout.setSpacing(8)

        cat_header = QHBoxLayout()
        cat_header.setContentsMargins(0, 0, 0, 0)
        cat_header.setSpacing(6)
        cat_header.addWidget(_section_label("Categories"), 1)
        self._new_cat_btn = QToolButton()
        self._new_cat_btn.setIcon(icon_plus_add())
        self._new_cat_btn.setIconSize(QSize(16, 16))
        self._new_cat_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._new_cat_btn.setToolTip("New category")
        self._new_cat_btn.setFixedSize(28, 28)
        self._new_cat_btn.setStyleSheet(STYLE_ICON_BTN)
        self._new_cat_btn.setAutoRaise(False)
        cat_header.addWidget(self._new_cat_btn)
        cat_layout.addLayout(cat_header)

        self._category_list = QListWidget()
        self._category_list.setStyleSheet(STYLE_SIDEBAR_LIST)
        self._category_list.setSpacing(1)
        self._category_list.setIconSize(QSize(16, 16))
        self._category_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._category_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._category_list.setWordWrap(False)
        self._category_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        cat_layout.addWidget(self._category_list, 1)

        io_row = QHBoxLayout()
        io_row.setContentsMargins(0, 0, 0, 0)
        io_row.setSpacing(6)
        self._import_btn = QToolButton()
        self._import_btn.setIcon(icon_import())
        self._import_btn.setIconSize(QSize(16, 16))
        self._import_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._import_btn.setToolTip("Import zip or folder…")
        self._import_btn.setFixedSize(32, 32)
        self._import_btn.setStyleSheet(STYLE_ICON_BTN)
        self._import_btn.setAutoRaise(False)
        self._export_btn = QToolButton()
        self._export_btn.setIcon(icon_export())
        self._export_btn.setIconSize(QSize(16, 16))
        self._export_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._export_btn.setToolTip("Export library zip…")
        self._export_btn.setFixedSize(32, 32)
        self._export_btn.setStyleSheet(STYLE_ICON_BTN)
        self._export_btn.setAutoRaise(False)
        io_row.addWidget(self._import_btn)
        io_row.addWidget(self._export_btn)
        io_row.addStretch(1)
        cat_layout.addLayout(io_row)
        splitter.addWidget(cat_widget)

        # Presets (right)
        preset_widget = QWidget()
        preset_widget.setStyleSheet("background: transparent;")
        preset_layout = QVBoxLayout(preset_widget)
        preset_layout.setContentsMargins(4, 0, 0, 0)
        preset_layout.setSpacing(10)

        # Preset list + inspector side by side
        content_split = QSplitter(Qt.Orientation.Horizontal)
        content_split.setObjectName("ContentSplitter")
        content_split.setHandleWidth(8)
        content_split.setStyleSheet(
            f"QSplitter#ContentSplitter::handle {{ background: transparent; }}"
            f"QSplitter#ContentSplitter::handle:hover {{ background: {ACCENT_DIM}; }}"
        )

        self._preset_list = PresetListWidget()
        self._preset_list.setObjectName("PresetList")
        self._preset_list.setProperty("view", "grid")
        self._preset_list.setStyleSheet(STYLE_PRESET_LIST)
        self._preset_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._preset_list.setMovement(QListWidget.Movement.Static)
        self._preset_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._preset_list.setWordWrap(False)
        self._preset_list.setUniformItemSizes(True)
        self._preset_list.setFlow(QListWidget.Flow.LeftToRight)
        self._preset_list.setWrapping(True)
        self._preset_list.setItemDelegate(PresetItemDelegate(self._preset_list))
        self._preset_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.apply_card_scale(DEFAULT_CARD_SCALE)
        list_host = QWidget()
        list_wrap = QVBoxLayout(list_host)
        list_wrap.setContentsMargins(0, 0, 0, 0)
        list_wrap.setSpacing(4)
        list_wrap.addWidget(self._preset_list, 1)
        drag_hint = QLabel(
            "Right-click preset for Insert / Edit / Update / Delete. "
            "Drag preset → Network Editor to insert. "
            "Drag nodes from Network Editor → here to save."
        )
        drag_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; padding: 0 4px;")
        drag_hint.setWordWrap(True)
        list_wrap.addWidget(drag_hint)
        content_split.addWidget(list_host)

        # Inspector
        insp = QWidget()
        insp.setObjectName("InspectorPanel")
        insp.setStyleSheet(
            f"""
            QWidget#InspectorPanel {{
                background-color: {BG_SIDEBAR};
                border: 1px solid {BORDER};
                border-radius: 14px;
            }}
            """
        )
        insp.setMinimumWidth(200)
        insp.setMaximumWidth(300)
        insp_layout = QVBoxLayout(insp)
        insp_layout.setContentsMargins(14, 14, 14, 14)
        insp_layout.setSpacing(8)
        insp_layout.addWidget(_section_label("Inspector"))

        self._insp_thumb = QLabel()
        self._insp_thumb.setFixedHeight(140)
        self._insp_thumb.setMinimumWidth(0)
        self._insp_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._insp_thumb.setScaledContents(False)
        self._insp_thumb.setStyleSheet(
            f"background: {BG_SURFACE}; border: 2px solid #323848; border-radius: 12px; "
            f"color: {TEXT_MUTED}; font-size: 12px;"
        )
        self._insp_thumb.setText("Select a preset")
        insp_layout.addWidget(self._insp_thumb)

        self._insp_name = QLabel("—")
        self._insp_name.setWordWrap(True)
        self._insp_name.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;"
        )
        insp_layout.addWidget(self._insp_name)

        self._insp_tag = QLabel("")
        self._insp_tag.setStyleSheet(f"color: {ACCENT}; font-size: 11px; font-weight: 700;")
        insp_layout.addWidget(self._insp_tag)

        desc_box = QWidget()
        desc_box.setObjectName("InspectorDescBox")
        desc_box.setStyleSheet(
            f"""
            QWidget#InspectorDescBox {{
                background: rgba(255, 255, 255, 0.045);
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            """
        )
        desc_layout = QVBoxLayout(desc_box)
        desc_layout.setContentsMargins(12, 10, 12, 10)
        desc_layout.setSpacing(6)

        self._insp_desc = QLabel("")
        self._insp_desc.setWordWrap(True)
        self._insp_desc.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent; border: none;"
        )
        desc_layout.addWidget(self._insp_desc)

        self._insp_meta = QLabel("")
        self._insp_meta.setWordWrap(True)
        self._insp_meta.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; background: transparent; border: none;"
        )
        desc_layout.addWidget(self._insp_meta)
        insp_layout.addWidget(desc_box)

        insp_layout.addStretch(1)

        self._insp_fav_btn = QPushButton("☆  Favorite")
        self._insp_fav_btn.setStyleSheet(STYLE_BTN)
        self._insp_fav_btn.setEnabled(False)
        self._insp_fav_btn.setCheckable(True)
        insp_layout.addWidget(self._insp_fav_btn)

        self._insp_insert_btn = QPushButton("Insert at center view")
        self._insp_insert_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self._insp_insert_btn.setEnabled(False)
        insp_layout.addWidget(self._insp_insert_btn)

        self._insp_edit_btn = QPushButton("Edit")
        self._insp_edit_btn.setStyleSheet(STYLE_BTN)
        self._insp_edit_btn.setEnabled(False)
        insp_layout.addWidget(self._insp_edit_btn)

        self._insp_update_btn = QPushButton("Update from selection")
        self._insp_update_btn.setStyleSheet(STYLE_BTN)
        self._insp_update_btn.setEnabled(False)
        self._insp_update_btn.setToolTip(
            "Overwrite this preset's nodes with the current Network Editor selection"
        )
        insp_layout.addWidget(self._insp_update_btn)

        content_split.addWidget(insp)
        content_split.setSizes([480, 240])
        content_split.setStretchFactor(0, 3)
        content_split.setStretchFactor(1, 1)
        preset_layout.addWidget(content_split, 1)

        splitter.addWidget(preset_widget)
        splitter.setSizes([200, 720])
        main.addWidget(splitter, 1)
        self._main_splitter = splitter
        self._content_splitter = content_split

        footer = QHBoxLayout()
        footer.setContentsMargins(2, 0, 2, 0)
        self._message = QLabel()
        self._message.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        footer.addWidget(self._message, 1)
        self._version_label = QLabel()
        self._version_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        footer.addWidget(self._version_label, 0, Qt.AlignmentFlag.AlignRight)
        main.addLayout(footer, 0)

        self._presets_data: list[dict[str, Any]] = []
        self._library_root: Optional[Path] = None
        self._geometry_save_cb: Optional[Callable[[dict[str, Any]], None]] = None
        self.clear_inspector()

    def on_geometry_save(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._geometry_save_cb = callback

    def capture_window_geometry(self) -> dict[str, Any]:
        geo = self.geometry()
        out: dict[str, Any] = {
            "w": max(geo.width(), self.minimumWidth()),
            "h": max(geo.height(), self.minimumHeight()),
            "x": geo.x(),
            "y": geo.y(),
        }
        main = getattr(self, "_main_splitter", None)
        content = getattr(self, "_content_splitter", None)
        if main is not None:
            sizes = main.sizes()
            if len(sizes) >= 2:
                out["main_splitter"] = [int(sizes[0]), int(sizes[1])]
        if content is not None:
            sizes = content.sizes()
            if len(sizes) >= 2:
                out["content_splitter"] = [int(sizes[0]), int(sizes[1])]
        return out

    def restore_window_geometry(self, geometry: Optional[dict[str, Any]] = None) -> None:
        data = geometry if isinstance(geometry, dict) else get_window_geometry()
        w = int(data.get("w") or DEFAULT_WINDOW_W)
        h = int(data.get("h") or DEFAULT_WINDOW_H)
        self.resize(w, h)
        if "x" in data and "y" in data:
            try:
                self.move(int(data["x"]), int(data["y"]))
            except (TypeError, ValueError):
                pass
        main = getattr(self, "_main_splitter", None)
        content = getattr(self, "_content_splitter", None)
        ms = data.get("main_splitter")
        if main is not None and isinstance(ms, list) and len(ms) >= 2:
            main.setSizes([int(ms[0]), int(ms[1])])
        cs = data.get("content_splitter")
        if content is not None and isinstance(cs, list) and len(cs) >= 2:
            content.setSizes([int(cs[0]), int(cs[1])])

    def persist_window_geometry(self) -> None:
        geom = self.capture_window_geometry()
        if self._geometry_save_cb is not None:
            try:
                self._geometry_save_cb(geom)
                return
            except Exception:
                pass
        set_window_geometry(geom)

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        try:
            self.persist_window_geometry()
        except Exception:
            pass
        try:
            app = QApplication.instance()
            if app is not None:
                cur = app.property(config.UI_INSTANCE_PROPERTY)
                if cur is self:
                    app.setProperty(config.UI_INSTANCE_PROPERTY, None)
        except Exception:
            pass
        super().closeEvent(event)

    def set_categories(self, categories: list[dict[str, Any]], select_id: Optional[str] = None) -> None:
        self._category_list.clear()
        for c in categories:
            name = c.get("name", c.get("id", ""))
            item = QListWidgetItem(category_list_icon(c), name)
            item.setData(Qt.ItemDataRole.UserRole, c.get("id", ""))
            color = c.get("color")
            if color:
                item.setData(Qt.ItemDataRole.UserRole + 1, str(color))
            self._category_list.addItem(item)
        if select_id:
            for i in range(self._category_list.count()):
                if self._category_list.item(i).data(Qt.ItemDataRole.UserRole) == select_id:
                    self._category_list.setCurrentRow(i)
                    break

    def get_selected_category_id(self) -> Optional[str]:
        item = self._category_list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def ensure_category_selected(self) -> None:
        if self.get_selected_category_id() is None and self._category_list.count() > 0:
            self._category_list.setCurrentRow(0)

    def set_presets(self, presets: list[dict[str, Any]], library_root: Optional[Path] = None) -> None:
        self._preset_list.clear()
        self._presets_data = presets
        self._library_root = library_root
        placeholder_icon: Optional[QIcon] = None
        for p in presets:
            name = p.get("name", "?")
            pid = p.get("id", "")
            desc = p.get("description", "") or ""
            networks = p.get("networks", []) or []

            # Name/desc stored separately; DisplayRole unused (custom grid/list paint)
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, pid)
            item.setData(Qt.ItemDataRole.UserRole + 1, networks)
            item.setData(Qt.ItemDataRole.UserRole + 2, name)
            item.setData(Qt.ItemDataRole.UserRole + 3, desc)
            item.setToolTip(f"{name}\n{desc}".strip() if desc else name)
            thumb_path = p.get("thumbnail")
            icon: Optional[QIcon] = None
            thumb_pix: Optional[QPixmap] = None
            if thumb_path and library_root:
                fp = library_root / thumb_path
                if fp.is_file():
                    loaded = QPixmap(str(fp))
                    if not loaded.isNull():
                        thumb_pix = loaded
                        icon = QIcon(loaded)
            if icon is None:
                if placeholder_icon is None:
                    placeholder_icon = QIcon(self._make_placeholder_pixmap())
                icon = placeholder_icon
            item.setIcon(icon)
            if thumb_pix is not None:
                item.setData(ROLE_THUMB_PIXMAP, thumb_pix)
            self._preset_list.addItem(item)
        self.clear_inspector()

    def clear_inspector(self) -> None:
        self._insp_thumb.clear()
        self._insp_thumb.setText("Select a preset")
        self._insp_thumb.setStyleSheet(
            f"background: {BG_SURFACE}; border: 2px solid #323848; border-radius: 12px; "
            f"color: {TEXT_MUTED}; font-size: 12px;"
        )
        self._insp_name.setText("—")
        self._insp_tag.setText("")
        self._insp_desc.setText("")
        self._insp_meta.setText("")
        self._insp_insert_btn.setEnabled(False)
        self._insp_edit_btn.setEnabled(False)
        self._insp_update_btn.setEnabled(False)
        self._insp_fav_btn.setEnabled(False)
        self._insp_fav_btn.setChecked(False)
        self._insp_fav_btn.setText("☆  Favorite")

    def set_inspector_preset(
        self,
        preset: Optional[dict[str, Any]],
        library_root: Optional[Path] = None,
        *,
        favorited: bool = False,
    ) -> None:
        if not preset:
            self.clear_inspector()
            return
        name = preset.get("name") or "—"
        desc = (preset.get("description") or "").strip()
        nets = preset.get("networks") or []
        tag = str(nets[0]) if nets else ""
        node_count = preset.get("node_count")
        created = preset.get("created") or ""
        if created and "T" in created:
            created = created.split("T", 1)[0]

        self._insp_name.setText(name)
        self._insp_tag.setText(tag if tag else "")
        self._insp_desc.setText(desc if desc else "No description")
        meta_parts = []
        if node_count is not None:
            meta_parts.append(f"{node_count} node{'s' if node_count != 1 else ''}")
        if created:
            meta_parts.append(created)
        cat = preset.get("category_id") or ""
        if cat:
            meta_parts.append(cat)
        self._insp_meta.setText(" · ".join(meta_parts))

        thumb_rel = preset.get("thumbnail")
        root = library_root or self._library_root
        pix = None
        if thumb_rel and root:
            fp = root / thumb_rel
            if fp.is_file():
                pix = QPixmap(str(fp))
        if pix and not pix.isNull():
            # Bake rounded image + border into pixmap — CSS border on QLabel gets cropped by pixmap
            tw = max(160, self._insp_thumb.width() or 240)
            th = max(100, self._insp_thumb.height() or 140)
            rounded = _rounded_cover_pixmap(
                pix,
                QSize(tw, th),
                radius=12.0,
                border_color=ACCENT,
                border_width=2.0,
            )
            self._insp_thumb.setPixmap(rounded)
            self._insp_thumb.setText("")
            self._insp_thumb.setStyleSheet(
                "background: transparent; border: none; padding: 0px;"
            )
        else:
            self._insp_thumb.clear()
            self._insp_thumb.setText("No preview")
            self._insp_thumb.setStyleSheet(
                f"background: {BG_SURFACE}; border: 2px dashed {BORDER_STRONG}; border-radius: 12px; "
                f"color: {TEXT_MUTED}; font-size: 12px;"
            )

        self._insp_insert_btn.setEnabled(True)
        self._insp_edit_btn.setEnabled(True)
        self._insp_update_btn.setEnabled(True)
        self._insp_fav_btn.setEnabled(True)
        self.set_inspector_favorite(favorited)

    def set_inspector_favorite(self, favorited: bool) -> None:
        self._insp_fav_btn.setChecked(favorited)
        self._insp_fav_btn.setText("★  Favorited" if favorited else "☆  Favorite")

    def _make_placeholder_pixmap(self) -> QPixmap:
        size = self._preset_list.iconSize()
        pm = QPixmap(size)
        pm.fill(QColor(BG_ELEVATED))
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(TEXT_MUTED), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = 8
        painter.drawRoundedRect(
            inset,
            inset,
            size.width() - inset * 2,
            size.height() - inset * 2,
            8,
            8,
        )
        painter.setPen(QColor(TEXT_MUTED))
        font = QFont(painter.font())
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "No preview")
        painter.end()
        return pm

    def get_selected_preset_id(self) -> Optional[str]:
        item = self._preset_list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def set_message(self, text: str, error: bool = False) -> None:
        self._message.setText(text)
        self._message.setStyleSheet(
            f"color: {DANGER if error else TEXT_MUTED}; font-size: 12px;"
        )

    def set_version_text(self, version: str) -> None:
        self._version_label.setText(version)

    def on_save_clicked(self, callback: Callable[[], None]) -> None:
        self._save_btn.clicked.connect(callback)

    def on_settings_clicked(self, callback: Callable[[], None]) -> None:
        self._settings_btn.clicked.connect(callback)

    def on_new_category_clicked(self, callback: Callable[[], None]) -> None:
        self._new_cat_btn.clicked.connect(callback)

    def on_import_clicked(self, callback: Callable[[], None]) -> None:
        self._import_btn.clicked.connect(callback)

    def on_export_clicked(self, callback: Callable[[], None]) -> None:
        self._export_btn.clicked.connect(callback)

    def on_open_folder_clicked(self, callback: Callable[[], None]) -> None:
        self._open_folder_cb = callback

    def on_favorite_clicked(self, callback: Callable[[], None]) -> None:
        self._insp_fav_btn.clicked.connect(callback)

    def on_preset_drag_finished(self, callback: Callable[[str], None]) -> None:
        self._preset_list.on_drag_finished(callback)

    def on_houdini_nodes_dropped(self, callback: Callable[[list[str]], None]) -> None:
        self._houdini_drop_cb = callback
        self._preset_list.on_houdini_nodes_dropped(callback)

    def set_houdini_mime_extractor(self, fn: Callable[[QMimeData], list[str]]) -> None:
        self._mime_paths_fn = fn
        self._preset_list.set_mime_paths_extractor(fn)

    def _window_drop_paths(self, mime: QMimeData) -> list[str]:
        if self._mime_paths_fn is not None:
            try:
                return list(self._mime_paths_fn(mime) or [])
            except Exception:
                return []
        return self._preset_list._drop_paths(mime)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        mime = event.mimeData()
        if mime and self._window_drop_paths(mime):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # type: ignore[override]
        mime = event.mimeData()
        if mime and self._window_drop_paths(mime):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        mime = event.mimeData()
        paths = self._window_drop_paths(mime) if mime else []
        if paths and self._houdini_drop_cb:
            self._houdini_drop_cb(paths)
            event.acceptProposedAction()
            return
        event.ignore()

    def on_insert_clicked(self, callback: Callable[[], None]) -> None:
        self._insp_insert_btn.clicked.connect(callback)
        self._insert_callback = callback

    def on_edit_clicked(self, callback: Callable[[], None]) -> None:
        self._insp_edit_btn.clicked.connect(callback)
        self._edit_callback = callback

    def on_update_from_selection_clicked(self, callback: Callable[[], None]) -> None:
        self._insp_update_btn.clicked.connect(callback)

    def on_delete_clicked(self, callback: Callable[[], None]) -> None:
        self._delete_callback = callback

    def on_preset_context_menu(self, callback: Callable[[str, QPoint], None]) -> None:
        """callback(preset_id, global_pos). Wired via contextMenuEvent (reliable with drag)."""
        self._preset_list.on_context_menu(callback)

    def show_preset_context_menu(
        self,
        global_pos: QPoint,
        *,
        favorited: bool = False,
        on_insert: Optional[Callable[[], None]] = None,
        on_edit: Optional[Callable[[], None]] = None,
        on_update_from_selection: Optional[Callable[[], None]] = None,
        on_delete: Optional[Callable[[], None]] = None,
        on_favorite: Optional[Callable[[], None]] = None,
    ) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            f"""
            QMenu {{
                background: {BG_ELEVATED};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_STRONG};
                border-radius: 8px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 18px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: {ACCENT_DIM};
            }}
            """
        )
        act_insert = menu.addAction("Insert at center view")
        act_edit = menu.addAction("Edit…")
        act_update = menu.addAction("Update from selection…")
        act_fav = menu.addAction("Remove from Favorites" if favorited else "Add to Favorites")
        menu.addSeparator()
        act_delete = menu.addAction("Delete…")
        chosen = menu.exec(global_pos)
        if chosen == act_insert and on_insert:
            on_insert()
        elif chosen == act_edit and on_edit:
            on_edit()
        elif chosen == act_update and on_update_from_selection:
            on_update_from_selection()
        elif chosen == act_fav and on_favorite:
            on_favorite()
        elif chosen == act_delete and on_delete:
            on_delete()

    def on_preset_selected(self, callback: Callable[[Optional[str]], None]) -> None:
        def _on_change(cur: Optional[QListWidgetItem], _: Optional[QListWidgetItem]) -> None:
            pid = cur.data(Qt.ItemDataRole.UserRole) if cur else None
            callback(str(pid) if pid else None)

        self._preset_list.currentItemChanged.connect(_on_change)

    def on_search_changed(self, callback: Callable[[str], None]) -> None:
        self._search_edit.textChanged.connect(callback)

    def on_auto_detect_toggled(self, callback: Callable[[bool], None]) -> None:
        self._auto_detect_chk.toggled.connect(callback)

    def on_network_filter_changed(self, callback: Callable[[str], None]) -> None:
        def _on_changed(index: int) -> None:
            value = self._network_combo.itemData(index)
            callback(str(value) if value is not None else "__all__")

        self._network_combo.currentIndexChanged.connect(_on_changed)

    def on_view_mode_changed(self, callback: Callable[[str], None]) -> None:
        def set_mode(mode: str) -> None:
            self._view_mode = mode
            if mode == "grid":
                self._view_grid_btn.setChecked(True)
                self._view_list_btn.setChecked(False)
                self._preset_list.setViewMode(QListWidget.ViewMode.IconMode)
                self._preset_list.setFlow(QListWidget.Flow.LeftToRight)
                self._preset_list.setWrapping(True)
                self._preset_list.setWordWrap(False)
                self._preset_list.setUniformItemSizes(True)
                self._preset_list.setProperty("view", "grid")
                self.apply_card_scale(self._card_scale)
            else:
                self._view_grid_btn.setChecked(False)
                self._view_list_btn.setChecked(True)
                self._preset_list.setViewMode(QListWidget.ViewMode.ListMode)
                # Critical: clear IconMode gridSize or rows stay tall
                self._preset_list.setGridSize(QSize())
                self._preset_list.setIconSize(LIST_THUMB)
                self._preset_list.setSpacing(0)
                self._preset_list.setWordWrap(False)
                self._preset_list.setUniformItemSizes(True)
                self._preset_list.setFlow(QListWidget.Flow.TopToBottom)
                self._preset_list.setWrapping(False)
                self._preset_list.setProperty("view", "list")
                self._preset_list.style().unpolish(self._preset_list)
                self._preset_list.style().polish(self._preset_list)
                self._preset_list.doItemsLayout()
                self._preset_list.viewport().update()
            callback(mode)

        self._view_grid_btn.clicked.connect(lambda: set_mode("grid"))
        self._view_list_btn.clicked.connect(lambda: set_mode("list"))

    def apply_card_scale(self, scale_pct: int) -> None:
        """Apply grid card size (percent of design base). No-op effect in list mode until grid."""
        self._card_scale = clamp_card_scale(scale_pct)
        if getattr(self, "_view_mode", "grid") != "grid":
            return
        if self._preset_list.viewMode() != QListWidget.ViewMode.IconMode:
            return
        grid, icon, spacing, inset = grid_metrics_for_scale(self._card_scale)
        self._preset_list.setProperty("cardInset", inset)
        self._preset_list.setIconSize(icon)
        self._preset_list.setSpacing(spacing)
        self._preset_list.setGridSize(grid)
        self._preset_list.style().unpolish(self._preset_list)
        self._preset_list.style().polish(self._preset_list)
        self._preset_list.doItemsLayout()
        self._preset_list.viewport().update()

    def get_card_scale(self) -> int:
        return int(self._card_scale)

    def set_auto_detect_enabled(self, enabled: bool) -> None:
        self._auto_detect_chk.setChecked(enabled)
        self._network_combo.setEnabled(not enabled)

    def set_network_filter_value(self, value: str) -> None:
        for i in range(self._network_combo.count()):
            if self._network_combo.itemData(i) == value:
                self._network_combo.setCurrentIndex(i)
                return

    def on_category_selected(self, callback: Callable[[Optional[str]], None]) -> None:
        def _on_change(cur: Optional[QListWidgetItem], _: Optional[QListWidgetItem]) -> None:
            cid = cur.data(Qt.ItemDataRole.UserRole) if cur else None
            callback(cid)

        self._category_list.currentItemChanged.connect(_on_change)

    def on_category_context_menu(
        self,
        callback: Callable[[str, str, QPoint], None],
    ) -> None:
        """callback(category_id, display_name, global_pos)."""

        def _on_menu(pos: QPoint) -> None:
            item = self._category_list.itemAt(pos)
            global_pos = self._category_list.mapToGlobal(pos)
            if not item:
                callback("__sidebar__", "", global_pos)
                return
            cid = item.data(Qt.ItemDataRole.UserRole)
            callback(str(cid or "__sidebar__"), item.text(), global_pos)

        self._category_list.customContextMenuRequested.connect(_on_menu)

    def show_category_context_menu(
        self,
        global_pos: QPoint,
        *,
        can_rename: bool = True,
        can_delete: bool = True,
        show_edit_actions: bool = True,
        on_rename: Optional[Callable[[], None]] = None,
        on_set_color: Optional[Callable[[], None]] = None,
        on_delete: Optional[Callable[[], None]] = None,
        on_open_folder: Optional[Callable[[], None]] = None,
    ) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            f"""
            QMenu {{
                background: {BG_ELEVATED};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_STRONG};
                border-radius: 8px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 18px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: {ACCENT_DIM};
            }}
            QMenu::item:disabled {{
                color: {TEXT_MUTED};
            }}
            """
        )
        act_rename = act_color = act_delete = act_open = None
        if show_edit_actions:
            act_rename = menu.addAction("Rename…")
            act_rename.setEnabled(can_rename)
            act_color = menu.addAction("Set color…")
            act_color.setEnabled(can_rename)
            act_delete = menu.addAction("Delete…")
            act_delete.setEnabled(can_delete)
        open_cb = on_open_folder or getattr(self, "_open_folder_cb", None)
        if open_cb:
            if show_edit_actions:
                menu.addSeparator()
            act_open = menu.addAction(icon_folder(), "Open folder")
        if menu.isEmpty():
            return
        chosen = menu.exec(global_pos)
        if act_rename is not None and chosen == act_rename and on_rename:
            on_rename()
        elif act_color is not None and chosen == act_color and on_set_color:
            on_set_color()
        elif act_delete is not None and chosen == act_delete and on_delete:
            on_delete()
        elif act_open is not None and chosen == act_open and open_cb:
            open_cb()

    def on_preset_double_clicked(self, callback: Callable[[str], None]) -> None:
        def on_item_double_clicked(item: QListWidgetItem) -> None:
            pid = item.data(Qt.ItemDataRole.UserRole) if item else None
            if pid:
                callback(pid)

        self._preset_list.itemDoubleClicked.connect(on_item_double_clicked)

    def show_import_folder_dialog(self) -> Optional[str]:
        path = QFileDialog.getExistingDirectory(self, "Import library — select folder")
        return path if path else None

    def show_import_zip_dialog(self) -> Optional[str]:
        path, _filt = QFileDialog.getOpenFileName(
            self,
            "Import library — select zip",
            "",
            "Library zip (*.zip);;All files (*.*)",
        )
        return path if path else None

    def show_import_zip_or_folder_dialog(self) -> Optional[str]:
        """Ask zip vs folder once, then open a single picker."""
        box = QMessageBox(self)
        box.setWindowTitle("Import library")
        box.setText("Import from a zip file or a library folder?")
        box.setIcon(QMessageBox.Icon.Question)
        zip_btn = box.addButton("Zip…", QMessageBox.ButtonRole.AcceptRole)
        folder_btn = box.addButton("Folder…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(zip_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked == zip_btn:
            return self.show_import_zip_dialog()
        if clicked == folder_btn:
            return self.show_import_folder_dialog()
        return None

    def show_export_zip_dialog(self, suggested_name: str = "node_preset_library.zip") -> Optional[str]:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export library zip",
            suggested_name,
            "Zip archive (*.zip)",
        )
        return path if path else None
