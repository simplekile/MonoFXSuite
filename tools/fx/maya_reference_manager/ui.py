"""
PySide6 UI — Library + Scene tabs (MONOS tokens aligned with USD Publish).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import uuid
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from PySide6.QtCore import QByteArray, QPoint, QSettings, QSize, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCloseEvent,
    QDrag,
    QDragMoveEvent,
    QDropEvent,
    QIcon,
    QCursor,
    QFont,
    QGuiApplication,
    QHideEvent,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

def _settings_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes")
    if value is None:
        return default
    return bool(value)


def _as_qbytearray(value: object) -> Optional[QByteArray]:
    if value is None:
        return None
    if isinstance(value, QByteArray):
        return None if value.isEmpty() else value
    if isinstance(value, (bytes, bytearray)) and value:
        return QByteArray(bytes(value))
    return None


def _lucide_icon(path_d: str, *, size: int = 16, color: str = "#d4d4d8") -> QIcon:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{path_d}</svg>"""
    pm = QPixmap()
    pm.loadFromData(svg.encode("utf-8"), "SVG")
    return QIcon(pm)


# Context-menu icon colors
ICON_BLUE = "#60a5fa"
ICON_GREEN = "#34d399"
ICON_AMBER = "#fbbf24"
ICON_RED = "#f87171"
ICON_VIOLET = "#a78bfa"
ICON_CYAN = "#22d3ee"


ICON_REFRESH = _lucide_icon(
    '<path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15.55-6.36L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15.55 6.36L3 16"/>',
    color=ICON_BLUE,
)
ICON_OPEN = _lucide_icon(
    '<path d="M6 14a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v1"/><path d="M22 19a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    color=ICON_AMBER,
)
ICON_FOLDER = _lucide_icon(
    '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    color=ICON_AMBER,
)
ICON_COPY = _lucide_icon(
    '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    color=ICON_VIOLET,
)
ICON_REMOVE = _lucide_icon(
    '<path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>',
    color=ICON_RED,
)
ICON_EDIT = _lucide_icon(
    '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    color=ICON_CYAN,
)
ICON_RELOAD = _lucide_icon(
    '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>',
    color=ICON_BLUE,
)
ICON_LOAD = _lucide_icon(
    '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
    color=ICON_GREEN,
)
ICON_UNLOAD = _lucide_icon(
    '<path d="M12 21V9"/><path d="m17 14-5-5-5 5"/><path d="M5 3h14"/>',
    color=ICON_AMBER,
)
ICON_SPARKLES = _lucide_icon(
    '<path d="m12 3-1.9 4.6L5.5 9.5l4.6 1.9L12 16l1.9-4.6 4.6-1.9-4.6-1.9z"/><path d="M5 3v4"/><path d="M3 5h4"/><path d="M19 17v4"/><path d="M17 19h4"/>',
    color=ICON_VIOLET,
)


# Match tools/fx/usd_export_maya/ui.py tokens
BG_PANEL = "#18181b"
BG_CONTENT = "#121214"
BG_SURFACE = "#27272a"
TEXT_PRIMARY = "#fafafa"
TEXT_LABEL = "#a1a1aa"
TEXT_META = "#71717a"
BLUE_600 = "#2563eb"
# Scene "Version" column: current (behind) vs newest on disk
VERSION_CELL_OLD = "#71717a"
VERSION_CELL_NEWEST = "#34c759"

STYLE_WINDOW = f"""
    QMainWindow#MonoFXReferenceManagerWindow {{
        background-color: {BG_PANEL};
        color: {TEXT_PRIMARY};
    }}
"""

STYLE_INPUT = f"""
    QLineEdit, QComboBox {{
        padding: 6px 8px;
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 6px;
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        font-size: 13px;
    }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid {BLUE_600}; }}
"""

STYLE_TABLE = f"""
    QTableWidget {{
        background: {BG_CONTENT};
        border: 1px solid #2a2a2c;
        gridline-color: #2a2a2c;
        color: #eeeeee;
        font-size: 12px;
        border-radius: 6px;
    }}
    QTableWidget::item:selected {{
        background: rgba(37, 99, 235, 0.15);
        color: {BLUE_600};
    }}
    QHeaderView::section {{
        background: #0d0d0f;
        color: #4a4a4c;
        border: none;
        border-bottom: 2px solid #2a2a2c;
        padding: 6px;
        font-size: 12px;
    }}
"""

# Match Path column text inset for widget cells (Version sits right after Path)
STYLE_SCENE_REF_TABLE = """
    QTableWidget#MonoFXSceneRefTable::item {
        padding-left: 10px;
        padding-right: 10px;
    }
"""

STYLE_SCENE_REF_TREE = f"""
    QTreeWidget#MonoFXSceneRefTree {{
        background: {BG_CONTENT};
        border: 1px solid #2a2a2c;
        color: #eeeeee;
        font-size: 12px;
        border-radius: 6px;
    }}
    QTreeWidget#MonoFXSceneRefTree::item {{
        padding-left: 6px;
        padding-right: 10px;
    }}
    QTreeWidget#MonoFXSceneRefTree::item:selected {{
        background: rgba(37, 99, 235, 0.15);
        color: {BLUE_600};
    }}
    QTreeWidget#MonoFXSceneRefTree QHeaderView::section {{
        background: #0d0d0f;
        color: #4a4a4c;
        border: none;
        border-bottom: 2px solid #2a2a2c;
        padding: 6px;
        font-size: 12px;
    }}
"""

STYLE_LIBRARY_TABLE = """
    QTableWidget#MonoFXLibraryTable::item {
        padding-left: 10px;
        padding-right: 10px;
    }
"""

STYLE_BTN = """
    QPushButton {
        background: rgba(24, 24, 27, 0.35);
        color: #a1a1aa;
        padding: 6px 12px;
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 8px;
        font-size: 13px;
    }
    QPushButton:hover {
        background: rgba(255, 255, 255, 0.12);
        color: #e4e4e7;
    }
    QPushButton:disabled {
        color: #52525b;
        border-color: rgba(39, 39, 42, 0.35);
    }
"""

STYLE_BTN_PRIMARY = f"""
    QPushButton {{
        background: rgba(37, 99, 235, 0.22);
        border: 1px solid rgba(37, 99, 235, 0.70);
        color: {TEXT_PRIMARY};
        padding: 8px 14px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background: rgba(37, 99, 235, 0.35);
    }}
    QPushButton:disabled {{
        background: rgba(24, 24, 27, 0.35);
        border: 1px solid rgba(39, 39, 42, 0.50);
        color: #52525b;
    }}
"""

# Scene ref load pill (~70% of original 46×26)
SCENE_REF_LOAD_PILL_W = 32
SCENE_REF_LOAD_PILL_H = 18

# Column 0: Qt draws tree in this column; thumb/version widgets use same column index where set.
SCENE_TREE_COL_THUMB = 0
SCENE_TREE_COL_NS = 1
SCENE_TREE_COL_PATH = 2
SCENE_TREE_COL_VER = 3
SCENE_TREE_COL_STATUS = 4
SCENE_TREE_COL_INPROJ = 5
SCENE_TREE_COL_PAYLOAD = SCENE_TREE_COL_NS  # UserRole+1 on namespace column


def _scene_tree_item_is_group(item: QTreeWidgetItem) -> bool:
    d = item.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
    return isinstance(d, dict) and d.get("kind") == "group"


def _scene_tree_item_is_ref(item: QTreeWidgetItem) -> bool:
    d = item.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
    return (
        isinstance(d, dict)
        and str(d.get("ref_node_short") or "").strip()
        and d.get("kind") != "group"
    )


def _random_group_folder_qcolor() -> QColor:
    """Saturated but dark-friendly tint for a new folder row."""
    h = random.randint(0, 359)
    s = random.randint(72, 108)
    v = random.randint(44, 58)
    return QColor.fromHsv(h, s, v)


def _stable_group_qcolor_from_id(gid: str) -> QColor:
    """Deterministic color when loading layout rows that have no stored rgb."""
    digest = hashlib.md5(str(gid).encode()).hexdigest()
    h = int(digest[:6], 16) % 360
    s = 72 + (int(digest[6:8], 16) % 34)
    v = 42 + (int(digest[8:10], 16) % 20)
    return QColor.fromHsv(h, s, v)


def _qcolor_to_rgb_list(c: QColor) -> List[int]:
    return [c.red(), c.green(), c.blue()]


# iOS-style load pill (Scene references) — indicator fills the control; no text label
STYLE_IOS_REF_SWITCH = f"""
    QCheckBox#SceneRefLoadSwitch {{
        spacing: 0;
        margin: 0;
        padding: 0;
    }}
    QCheckBox#SceneRefLoadSwitch::indicator {{
        width: {SCENE_REF_LOAD_PILL_W}px;
        height: {SCENE_REF_LOAD_PILL_H}px;
        border-radius: 9px;
        border: none;
        background: #3a3a3c;
    }}
    QCheckBox#SceneRefLoadSwitch::indicator:hover:!disabled {{
        background: #48484a;
    }}
    QCheckBox#SceneRefLoadSwitch::indicator:checked {{
        background: #34c759;
    }}
    QCheckBox#SceneRefLoadSwitch::indicator:checked:hover:!disabled {{
        background: #30b350;
    }}
    QCheckBox#SceneRefLoadSwitch::indicator:disabled {{
        background: #2c2c2e;
    }}
"""

STYLE_IOS_FOCUS_SWITCH = f"""
    QCheckBox#SceneFocusSwitch {{
        color: {TEXT_LABEL};
        spacing: 8px;
        font-size: 13px;
        font-weight: 500;
    }}
    QCheckBox#SceneFocusSwitch::indicator {{
        width: 42px;
        height: 24px;
        border-radius: 12px;
        border: none;
        background: #3a3a3c;
    }}
    QCheckBox#SceneFocusSwitch::indicator:hover:!disabled {{
        background: #48484a;
    }}
    QCheckBox#SceneFocusSwitch::indicator:checked {{
        background: {BLUE_600};
    }}
    QCheckBox#SceneFocusSwitch::indicator:checked:hover:!disabled {{
        background: #3b82f6;
    }}
"""

STYLE_EXTRAS = f"""
    QTabWidget::pane {{
        border: 1px solid #2a2a2c;
        background: {BG_CONTENT};
        border-radius: 6px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: {BG_SURFACE};
        color: {TEXT_LABEL};
        padding: 8px 16px;
        margin-right: 2px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        font-size: 13px;
    }}
    QTabBar::tab:selected {{
        background: {BG_CONTENT};
        color: {TEXT_PRIMARY};
    }}
    QCheckBox {{ color: {TEXT_LABEL}; spacing: 8px; font-size: 13px; }}
    QMenu {{
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        border: 1px solid #2a2a2c;
        padding: 4px;
    }}
    QMenu::item {{ padding: 8px 24px; border-radius: 4px; }}
    QMenu::item:selected {{ background: rgba(37, 99, 235, 0.25); }}
"""

from apps.common.project_layout import list_asset_groups
from tools.fx.maya_reference_manager import config
from tools.fx.maya_reference_manager.logic import (
    Mode,
    RigOffer,
    RigVersionEntry,
    SceneRefVersionDisplay,
    matching_rig_versions_for_scene_path,
    newer_rig_version_for_scene_path,
    resolve_project_root_from_scene_path,
    rig_paths_equivalent,
    rig_version_index_for_scene_path,
    scene_ref_version_display,
    scan_rigs,
    suggest_namespace_from_asset,
    thumb_path_for_asset,
    version_display_token_from_path,
)

try:
    from tools.fx.maya_reference_manager.logic import thumb_path_for_reference_file
except ImportError:

    def thumb_path_for_reference_file(  # type: ignore[no-redef]
        reference_path: str,
        project_root: Optional[Path],
    ) -> Optional[Path]:
        """Stale ``logic`` in ``sys.modules`` — no scene thumbs until reload."""
        return None

try:
    from maya.app.general.mayaMixin import MayaQWidgetDockableMixin
except Exception:  # noqa: BLE001
    MayaQWidgetDockableMixin = None

_WINDOW_BASES: tuple = (
    (MayaQWidgetDockableMixin, QMainWindow)
    if MayaQWidgetDockableMixin is not None
    else (QMainWindow,)
)


def _move_widget_to_cursor(widget: QWidget, *, offset_x: int = 8, offset_y: int = 8) -> None:
    """Place window top-left near the cursor, clamped to the active screen."""
    pos = QCursor.pos()
    screen = QGuiApplication.screenAt(pos)
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    widget.adjustSize()
    w, h = widget.width(), widget.height()
    if w < 4 or h < 4:
        sh = widget.sizeHint()
        w = max(w, sh.width())
        h = max(h, sh.height())
    x = pos.x() + offset_x
    y = pos.y() + offset_y
    if screen is not None:
        ag = screen.availableGeometry()
        m = 6
        x = min(max(ag.left() + m, x), max(ag.left() + m, ag.right() - w - m + 1))
        y = min(max(ag.top() + m, y), max(ag.top() + m, ag.bottom() - h - m + 1))
    widget.move(x, y)


class _DialogAtCursor(QDialog):
    """QDialog that opens near the mouse cursor."""

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        _move_widget_to_cursor(self)


class _MessageBoxAtCursor(QMessageBox):
    """QMessageBox that repositions to the mouse after the platform shows the window."""

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        _move_widget_to_cursor(self)


def _message_box_at_cursor(
    parent: Optional[QWidget],
    icon: QMessageBox.Icon,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.NoButton,
) -> QMessageBox.StandardButton:
    msg = _MessageBoxAtCursor(parent)
    msg.setIcon(icon)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStandardButtons(buttons)
    if default_button != QMessageBox.StandardButton.NoButton:
        msg.setDefaultButton(default_button)
    return QMessageBox.StandardButton(msg.exec())


class _SceneRefTreeWidget(QTreeWidget):
    """Scene tree: reorder/reparent via middle-mouse drag only (left = selection)."""

    structureModified = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(False)
        self._middle_drag_origin: Optional[QPoint] = None
        self._middle_drag_armed: bool = False

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle_drag_origin = QPoint(event.pos())
            it = self.itemAt(event.pos())
            self._middle_drag_armed = it is not None
            if it is not None and not it.isSelected():
                self.clearSelection()
                it.setSelected(True)
                self.setCurrentItem(it)
        else:
            self._middle_drag_origin = None
            self._middle_drag_armed = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle_drag_origin = None
            self._middle_drag_armed = False
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if (
            self._middle_drag_armed
            and self._middle_drag_origin is not None
            and event.buttons() & Qt.MouseButton.MiddleButton
        ):
            dist = (event.pos() - self._middle_drag_origin).manhattanLength()
            if dist >= QApplication.startDragDistance():
                self._middle_drag_origin = None
                self._middle_drag_armed = False
                self._start_middle_button_row_drag()
                return
        super().mouseMoveEvent(event)

    def _start_middle_button_row_drag(self) -> None:
        idxs = self.selectedIndexes()
        if not idxs:
            return
        mime = self.model().mimeData(idxs)
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def startDrag(self, supportedActions) -> None:  # type: ignore[override]
        """Block QAbstractItemView default (left-button) row drag; middle-mouse uses QDrag only."""
        return

    def _scene_tree_row_under_drag_pos(self, event: QDropEvent | QDragMoveEvent) -> Optional[QTreeWidgetItem]:
        pos = self.viewport().mapFrom(self, event.position().toPoint())
        idx = self.indexAt(pos)
        if not idx.isValid():
            return None
        return self.itemFromIndex(idx)

    def _scene_ref_parenting_drop_allowed(self, event: QDropEvent | QDragMoveEvent) -> bool:
        """Refs cannot be parents: OnItem drops may only nest under group rows."""
        if self.dropIndicatorPosition() != QAbstractItemView.DropIndicatorPosition.OnItem:
            return True
        target = self._scene_tree_row_under_drag_pos(event)
        if target is None:
            return True
        if _scene_tree_item_is_ref(target):
            return False
        return True

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # type: ignore[override]
        super().dragMoveEvent(event)
        if event.isAccepted() and not self._scene_ref_parenting_drop_allowed(event):
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        if not self._scene_ref_parenting_drop_allowed(event):
            event.ignore()
            return
        super().dropEvent(event)
        self.structureModified.emit()


class ReferenceManagerWindow(*_WINDOW_BASES):  # type: ignore[misc]
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(config.WINDOW_TITLE)
        self.setObjectName("MonoFXReferenceManagerWindow")
        self.resize(960, 520)

        self._maya_adapter: Any = None
        self._project_root: Optional[Path] = None
        self._library_offers: List[RigOffer] = []
        self._settings = QSettings(config.SETTINGS_ORG, config.SETTINGS_APP)
        self._loading_ui_settings = False
        self._header_states_restored = False
        self._geometry_restored = False
        self._scene_changed_callback_ids: tuple[Optional[int], Optional[int]] = (None, None)
        self._scene_refresh_timer = QTimer(self)
        self._scene_refresh_timer.setSingleShot(True)
        self._scene_refresh_timer.setInterval(250)
        self._scene_refresh_timer.timeout.connect(self._refresh_all_safely)
        self._scene_tree_populating = False
        self._scene_layout_save_timer = QTimer(self)
        self._scene_layout_save_timer.setSingleShot(True)
        self._scene_layout_save_timer.setInterval(400)
        self._scene_layout_save_timer.timeout.connect(self._flush_scene_tree_layout_to_settings)

        font = QFont("Inter", 13)
        font.setWeight(QFont.Weight.Medium)
        self.setFont(font)
        self.setStyleSheet(
            STYLE_WINDOW
            + STYLE_INPUT
            + STYLE_TABLE
            + STYLE_SCENE_REF_TABLE
            + STYLE_SCENE_REF_TREE
            + STYLE_LIBRARY_TABLE
            + STYLE_BTN
            + STYLE_BTN_PRIMARY
            + STYLE_IOS_REF_SWITCH
            + STYLE_IOS_FOCUS_SWITCH
            + STYLE_EXTRAS
        )

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {TEXT_META}; font-size: 12px;")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)

        self._lib_tab = QWidget()
        self._scene_tab = QWidget()
        self._tabs.addTab(self._lib_tab, "Library")
        self._tabs.addTab(self._scene_tab, "Scene")

        self._build_library_tab(self._lib_tab)
        self._build_scene_tab(self._scene_tab)
        self._apply_saved_ui_preferences()
        self._tabs.currentChanged.connect(lambda _i: self._persist_ui_settings())

    def set_maya_adapter(self, adapter: Any) -> None:
        # If adapter is swapped, remove old callbacks first.
        try:
            if self._maya_adapter and hasattr(
                self._maya_adapter, "remove_scene_changed_callbacks"
            ):
                self._maya_adapter.remove_scene_changed_callbacks(
                    self._scene_changed_callback_ids
                )
        except Exception:
            pass

        self._maya_adapter = adapter

        # Auto refresh when scene changes (File > Open, New Scene, etc.)
        try:
            if self._maya_adapter and hasattr(self._maya_adapter, "add_scene_changed_callbacks"):
                self._scene_changed_callback_ids = self._maya_adapter.add_scene_changed_callbacks(
                    self._on_scene_changed_callback
                )
        except Exception:
            self._scene_changed_callback_ids = (None, None)

    def _on_scene_changed_callback(self) -> None:
        """Scene opened/changed callback from Maya — schedule UI refresh."""
        # Defer to avoid hammering refresh during scene load.
        self._scene_refresh_timer.start()

    def _refresh_all_safely(self) -> None:
        """Call refresh_all only when adapter is ready."""
        if not self._maya_adapter:
            return
        # If user is typing in search, let debounce finish.
        self.refresh_all()

    def _build_library_tab(self, w: QWidget) -> None:
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(10)
        top = QHBoxLayout()
        lay.addLayout(top)
        gl = QLabel("Group")
        gl.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        top.addWidget(gl)
        self._group_combo = QComboBox()
        self._group_combo.setStyleSheet(STYLE_INPUT)
        self._group_combo.currentIndexChanged.connect(lambda _i: self.refresh_library())
        top.addWidget(self._group_combo, 1)

        self._publish_chk = QCheckBox("Published (vs Work)")
        self._publish_chk.setChecked(True)
        self._publish_chk.toggled.connect(lambda _c: self._on_publish_mode_toggled())
        top.addWidget(self._publish_chk)

        sl = QLabel("Search")
        sl.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        top.addWidget(sl)
        self._lib_search = QLineEdit()
        self._lib_search.setPlaceholderText("Filter by name…")
        self._lib_search.setStyleSheet(STYLE_INPUT)
        self._lib_search.textChanged.connect(lambda _t: self._filter_library_rows())
        top.addWidget(self._lib_search, 1)

        lib_refresh_btn = QPushButton("Refresh")
        lib_refresh_btn.setStyleSheet(STYLE_BTN)
        lib_refresh_btn.clicked.connect(self.refresh_library)
        top.addWidget(lib_refresh_btn, 0)

        lib_hint = QLabel(
            "Ctrl/Shift-click to multi-select. Right-click: Open rig, Reference into scene, or refresh."
        )
        lib_hint.setStyleSheet(f"color: {TEXT_META}; font-size: 12px;")
        lay.addWidget(lib_hint)

        self._lib_table = QTableWidget()
        self._lib_table.setObjectName("MonoFXLibraryTable")
        self._lib_table.setColumnCount(5)
        self._lib_table.setHorizontalHeaderLabels(
            ["NAME", "STATUS", "VERSION", "LAST UPDATED", "ASSIGNEE"]
        )
        self._lib_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._lib_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._lib_table.verticalHeader().setVisible(False)
        self._lib_table.setAlternatingRowColors(False)
        self._lib_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._lib_table.customContextMenuRequested.connect(self._on_lib_table_context_menu)
        lay.addWidget(self._lib_table, 1)
        self._group_combo.currentIndexChanged.connect(lambda _i: self._persist_ui_settings())
        self._lib_search_save_timer = QTimer(self)
        self._lib_search_save_timer.setSingleShot(True)
        self._lib_search_save_timer.setInterval(450)
        self._lib_search_save_timer.timeout.connect(self._persist_ui_settings)
        self._lib_search.textChanged.connect(lambda _t: self._lib_search_save_timer.start())

    def _on_publish_mode_toggled(self) -> None:
        self.refresh_library()
        self.refresh_scene()
        self._persist_ui_settings()

    def _on_scene_focus_toggled(self, checked: bool) -> None:
        self._scene_focus_mode.setEnabled(checked)
        self._scene_focus_custom.setEnabled(checked and self._scene_focus_mode.currentData() == "custom")
        self._scene_focus_custom_exclude.setEnabled(
            checked and self._scene_focus_mode.currentData() == "custom"
        )
        self._persist_ui_settings()
        if checked:
            self._on_scene_tree_selection_changed()

    def _on_scene_focus_mode_changed(self, _index: int) -> None:
        custom_on = self._scene_focus_chk.isChecked() and self._scene_focus_mode.currentData() == "custom"
        self._scene_focus_custom.setEnabled(custom_on)
        self._scene_focus_custom_exclude.setEnabled(custom_on)
        self._persist_ui_settings()
        if self._scene_focus_chk.isChecked():
            self._on_scene_tree_selection_changed()

    def _on_scene_focus_custom_changed(self) -> None:
        self._persist_ui_settings()
        if self._scene_focus_chk.isChecked() and self._scene_focus_mode.currentData() == "custom":
            self._on_scene_tree_selection_changed()

    def _build_scene_tab(self, w: QWidget) -> None:
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(10)
        hint = QLabel(
            "Ctrl/Shift-click to multi-select. Middle-mouse drag to reorder or nest under a group (Outliner-style). "
            "Right-click: New group, Group selection, Ungroup. Version column: switch rig file. "
            "(Published vs Work on Library picks which files are listed)."
        )
        hint.setStyleSheet(f"color: {TEXT_META}; font-size: 12px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        scene_top = QHBoxLayout()
        scene_top.setSpacing(10)
        scene_top.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._scene_focus_chk = QCheckBox("Focus")
        self._scene_focus_chk.setObjectName("SceneFocusSwitch")
        self._scene_focus_chk.setToolTip(
            "When enabled, selecting a row also selects the corresponding reference in Maya."
        )
        scene_top.addWidget(self._scene_focus_chk, 0, Qt.AlignmentFlag.AlignVCenter)

        self._scene_focus_mode = QComboBox()
        self._scene_focus_mode.setStyleSheet(STYLE_INPUT)
        self._scene_focus_mode.addItem("Root", "root")
        self._scene_focus_mode.addItem("Geometry", "geometry")
        self._scene_focus_mode.addItem("Main", "main")
        self._scene_focus_mode.addItem("Top Main", "top_main")
        self._scene_focus_mode.addItem("Custom", "custom")
        self._scene_focus_mode.setToolTip("Choose which node in the reference gets focused in Maya.")
        self._scene_focus_mode.setEnabled(False)
        scene_top.addWidget(self._scene_focus_mode, 0, Qt.AlignmentFlag.AlignVCenter)

        self._scene_focus_custom = QLineEdit()
        self._scene_focus_custom.setPlaceholderText("Custom token…")
        self._scene_focus_custom.setStyleSheet(STYLE_INPUT)
        self._scene_focus_custom.setFixedWidth(140)
        self._scene_focus_custom.setEnabled(False)
        self._scene_focus_custom.setToolTip("Leaf-name token to focus when mode = Custom.")
        scene_top.addWidget(self._scene_focus_custom, 0, Qt.AlignmentFlag.AlignVCenter)

        self._scene_focus_custom_exclude = QLineEdit()
        self._scene_focus_custom_exclude.setPlaceholderText("Exclude keyword…")
        self._scene_focus_custom_exclude.setStyleSheet(STYLE_INPUT)
        self._scene_focus_custom_exclude.setFixedWidth(140)
        self._scene_focus_custom_exclude.setEnabled(False)
        self._scene_focus_custom_exclude.setToolTip(
            "Leaf-name token to exclude when mode = Custom."
        )
        scene_top.addWidget(self._scene_focus_custom_exclude, 0, Qt.AlignmentFlag.AlignVCenter)

        scene_refresh_btn = QPushButton("Refresh scene")
        scene_refresh_btn.setStyleSheet(STYLE_BTN)
        scene_refresh_btn.clicked.connect(self.refresh_scene)
        scene_top.addWidget(scene_refresh_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._scene_update_all_btn = QPushButton("Update all")
        self._scene_update_all_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self._scene_update_all_btn.setEnabled(False)
        self._scene_update_all_btn.setToolTip(
            "Update every reference that is behind the newest version (Version column)."
        )
        self._scene_update_all_btn.clicked.connect(self._scene_update_all_versions)
        scene_top.addWidget(self._scene_update_all_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(scene_top)

        self._scene_tree = _SceneRefTreeWidget()
        self._scene_tree.setObjectName("MonoFXSceneRefTree")
        self._scene_tree.setColumnCount(6)
        self._scene_tree.setHeaderLabels(
            ["", "Namespace", "Path", "Version", "Status", "In project"]
        )
        self._scene_tree.setRootIsDecorated(True)
        self._scene_tree.setUniformRowHeights(False)
        self._scene_tree.setAnimated(True)
        self._scene_tree.setIndentation(18)
        th = self._scene_tree.header()
        th.setSectionResizeMode(SCENE_TREE_COL_THUMB, QHeaderView.ResizeMode.Interactive)
        self._scene_tree.setColumnWidth(SCENE_TREE_COL_THUMB, 240)
        th.setSectionResizeMode(SCENE_TREE_COL_NS, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(SCENE_TREE_COL_PATH, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(SCENE_TREE_COL_VER, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(SCENE_TREE_COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(SCENE_TREE_COL_INPROJ, QHeaderView.ResizeMode.ResizeToContents)
        self._scene_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._scene_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._scene_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._scene_tree.setAlternatingRowColors(False)
        self._scene_tree.setAcceptDrops(True)
        self._scene_tree.setDropIndicatorShown(True)
        self._scene_tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._scene_tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._scene_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._scene_tree.customContextMenuRequested.connect(self._on_scene_tree_context_menu)
        self._scene_tree.itemSelectionChanged.connect(self._on_scene_tree_selection_changed)
        self._scene_tree.structureModified.connect(self._on_scene_tree_structure_modified)
        lay.addWidget(self._scene_tree, 1)
        self._scene_focus_chk.toggled.connect(self._on_scene_focus_toggled)
        self._scene_focus_mode.currentIndexChanged.connect(self._on_scene_focus_mode_changed)
        self._scene_focus_custom.editingFinished.connect(self._on_scene_focus_custom_changed)
        self._scene_focus_custom_exclude.editingFinished.connect(self._on_scene_focus_custom_changed)

    def _adjust_context_selection(self, table: QTableWidget, pos, row_ok) -> None:
        """If right-click is on a row that is not part of the current selection, select that row only."""
        idx = table.indexAt(pos)
        row = idx.row()
        if row < 0 or not row_ok(row):
            return
        sm = table.selectionModel()
        if sm is None:
            table.selectRow(row)
            return
        if not sm.isSelected(table.model().index(row, 0)):
            table.clearSelection()
            table.selectRow(row)

    def _on_lib_table_context_menu(self, pos) -> None:
        def row_ok(r: int) -> bool:
            return (
                r >= 0
                and r < self._lib_table.rowCount()
                and not self._lib_table.isRowHidden(r)
            )

        row = self._lib_table.rowAt(pos.y())
        self._adjust_context_selection(self._lib_table, pos, row_ok)
        menu = QMenu(self)
        a_refresh_lib = QAction(ICON_REFRESH, "Refresh library", self)
        a_refresh_lib.triggered.connect(self.refresh_library)
        menu.addAction(a_refresh_lib)
        a_refresh_all = QAction(ICON_REFRESH, "Refresh all (project + library + scene)", self)
        a_refresh_all.triggered.connect(self.refresh_all)
        menu.addAction(a_refresh_all)
        if row >= 0 and row_ok(row):
            n = len(self._selected_library_rows())
            menu.addSeparator()
            open_label = "Open rig file…" if n <= 1 else f"Open rig file… ({n} selected — one at a time)"
            a_open = QAction(ICON_OPEN, open_label, self)
            a_open.triggered.connect(self._library_open)
            a_open_loc = QAction(
                ICON_OPEN,
                "Open file location…" if n <= 1 else f"Open {n} file locations…",
                self,
            )
            a_open_loc.triggered.connect(self._library_open_file_location)
            ref_label = "Reference into scene" if n <= 1 else f"Reference {n} rigs into scene"
            a_ref = QAction(ICON_COPY, ref_label, self)
            a_ref.triggered.connect(self._library_reference)
            menu.addAction(a_open)
            menu.addAction(a_open_loc)
            menu.addAction(a_ref)
        menu.exec(self._lib_table.viewport().mapToGlobal(pos))

    def _adjust_scene_tree_context_selection(self, pos) -> None:
        idx = self._scene_tree.indexAt(pos)
        if not idx.isValid():
            return
        item = self._scene_tree.itemFromIndex(idx)
        if item is None:
            return
        sm = self._scene_tree.selectionModel()
        if sm is None:
            self._scene_tree.setCurrentItem(item)
            item.setSelected(True)
            return
        if not sm.isSelected(idx):
            self._scene_tree.clearSelection()
            item.setSelected(True)
            self._scene_tree.setCurrentItem(item)

    def _on_scene_tree_context_menu(self, pos) -> None:
        hit = self._scene_tree.itemAt(pos)
        self._adjust_scene_tree_context_selection(pos)
        menu = QMenu(self)
        menu.addAction(self._action("New group", self._scene_new_group, icon=ICON_COPY))
        n_ref_pick = len(self._selected_scene_refs())
        n_grp_pick = len(self._selected_scene_group_items())
        if n_ref_pick >= 1:
            menu.addAction(
                self._action(
                    "Group selection" if n_ref_pick == 1 else f"Group {n_ref_pick} references",
                    self._scene_group_selection,
                    icon=ICON_COPY,
                )
            )
        if n_grp_pick >= 1:
            menu.addAction(
                self._action(
                    "Ungroup" if n_grp_pick == 1 else f"Ungroup {n_grp_pick} folders",
                    self._scene_ungroup_selection,
                    icon=ICON_EDIT,
                )
            )
        if n_grp_pick == 1:
            menu.addAction(
                self._action("Rename group…", self._scene_rename_selected_group, icon=ICON_EDIT)
            )
        menu.addSeparator()
        menu.addAction(self._action("Refresh scene references", self.refresh_scene, icon=ICON_REFRESH))
        menu.addAction(
            self._action("Refresh all (project + library + scene)", self.refresh_all, icon=ICON_REFRESH)
        )
        if hit is not None:
            n = len(self._selected_scene_refs())
            menu.addSeparator()
            menu.addAction(
                self._action(
                    "Load reference" if n <= 1 else f"Load {n} references",
                    self._scene_load,
                    icon=ICON_LOAD,
                )
            )
            menu.addAction(
                self._action(
                    "Unload reference" if n <= 1 else f"Unload {n} references",
                    self._scene_unload,
                    icon=ICON_UNLOAD,
                )
            )
            menu.addAction(
                self._action(
                    "Reload reference" if n <= 1 else f"Reload {n} references",
                    self._scene_reload,
                    icon=ICON_RELOAD,
                )
            )
            menu.addSeparator()
            a_rename_ns = self._action("Rename namespace…", self._scene_rename_namespace, icon=ICON_EDIT)
            a_rename_ns.setEnabled(n == 1)
            menu.addAction(a_rename_ns)
            menu.addAction(
                self._action(
                    "Update to latest version"
                    if n <= 1
                    else f"Update {n} to latest version",
                    self._scene_update_version,
                    icon=ICON_REFRESH,
                )
            )
            a_choose_ver = self._action("Choose version…", self._scene_choose_version, icon=ICON_EDIT)
            a_choose_ver.setEnabled(n == 1)
            menu.addAction(a_choose_ver)
            menu.addSeparator()
            menu.addAction(
                self._action(
                    "Duplicate reference" if n <= 1 else f"Duplicate {n} references",
                    self._scene_duplicate,
                    icon=ICON_COPY,
                )
            )
            menu.addAction(
                self._action(
                    "Duplicate smart" if n <= 1 else f"Duplicate {n} smart",
                    self._scene_duplicate_smart,
                    icon=ICON_SPARKLES,
                )
            )
            menu.addSeparator()
            menu.addAction(
                self._action(
                    "Replace from Library selection…"
                    if n <= 1
                    else f"Replace {n} from Library selection…",
                    self._scene_replace_from_library,
                    icon=ICON_EDIT,
                )
            )
            menu.addAction(
                self._action(
                    "Replace from file…" if n <= 1 else f"Replace {n} from file…",
                    self._scene_replace_browse,
                    icon=ICON_OPEN,
                )
            )
            menu.addAction(
                self._action(
                    "Open file location…" if n <= 1 else f"Open {n} file locations…",
                    self._scene_open_file_location,
                    icon=ICON_OPEN,
                )
            )
            menu.addSeparator()
            menu.addAction(
                self._action(
                    "Remove reference…" if n <= 1 else f"Remove {n} references…",
                    self._scene_remove,
                    icon=ICON_REMOVE,
                )
            )
        menu.exec(self._scene_tree.viewport().mapToGlobal(pos))

    def _action(self, title: str, slot: Callable[[], None], *, icon: Optional[QIcon] = None) -> QAction:
        a = QAction(icon or QIcon(), title, self)
        a.triggered.connect(slot)
        return a

    def refresh_all(self) -> None:
        self._refresh_project()
        self.refresh_library()
        self.refresh_scene()
        self._restore_header_states_once()

    def _apply_saved_ui_preferences(self) -> None:
        self._loading_ui_settings = True
        try:
            s = self._settings
            self._publish_chk.blockSignals(True)
            self._publish_chk.setChecked(
                _settings_bool(s.value(config.SETTINGS_KEY_PUBLISH_MODE, True), True)
            )
            self._publish_chk.blockSignals(False)
            self._scene_focus_chk.blockSignals(True)
            self._scene_focus_chk.setChecked(
                _settings_bool(s.value(config.SETTINGS_KEY_SCENE_FOCUS_SELECTION, False), False)
            )
            self._scene_focus_chk.blockSignals(False)
            focus_mode = str(s.value(config.SETTINGS_KEY_SCENE_FOCUS_MODE, "root") or "root")
            idx = max(0, self._scene_focus_mode.findData(focus_mode))
            self._scene_focus_mode.blockSignals(True)
            self._scene_focus_mode.setCurrentIndex(idx)
            self._scene_focus_mode.blockSignals(False)
            self._scene_focus_mode.setEnabled(self._scene_focus_chk.isChecked())
            self._scene_focus_custom.setText(
                str(s.value(config.SETTINGS_KEY_SCENE_FOCUS_CUSTOM, "") or "")
            )
            self._scene_focus_custom_exclude.setText(
                str(s.value(config.SETTINGS_KEY_SCENE_FOCUS_CUSTOM_EXCLUDE, "") or "")
            )
            custom_on = self._scene_focus_chk.isChecked() and self._scene_focus_mode.currentData() == "custom"
            self._scene_focus_custom.setEnabled(custom_on)
            self._scene_focus_custom_exclude.setEnabled(custom_on)
            self._lib_search.setText(str(s.value(config.SETTINGS_KEY_LIB_SEARCH, "") or ""))
            ti = int(s.value(config.SETTINGS_KEY_MAIN_TAB, 0) or 0)
            self._tabs.blockSignals(True)
            self._tabs.setCurrentIndex(ti if ti in (0, 1) else 0)
            self._tabs.blockSignals(False)
        finally:
            self._loading_ui_settings = False

    def _persist_ui_settings(self) -> None:
        if self._loading_ui_settings:
            return
        s = self._settings
        try:
            s.setValue(config.SETTINGS_KEY_PUBLISH_MODE, self._publish_chk.isChecked())
            s.setValue(config.SETTINGS_KEY_ASSETS_GROUP, self._group_combo.currentText())
            s.setValue(config.SETTINGS_KEY_LIB_SEARCH, self._lib_search.text())
            s.setValue(
                config.SETTINGS_KEY_SCENE_FOCUS_SELECTION,
                self._scene_focus_chk.isChecked(),
            )
            s.setValue(
                config.SETTINGS_KEY_SCENE_FOCUS_MODE,
                self._scene_focus_mode.currentData(),
            )
            s.setValue(
                config.SETTINGS_KEY_SCENE_FOCUS_CUSTOM,
                self._scene_focus_custom.text(),
            )
            s.setValue(
                config.SETTINGS_KEY_SCENE_FOCUS_CUSTOM_EXCLUDE,
                self._scene_focus_custom_exclude.text(),
            )
            s.setValue(config.SETTINGS_KEY_MAIN_TAB, self._tabs.currentIndex())
            s.setValue(config.SETTINGS_KEY_WINDOW_GEOMETRY, self.saveGeometry())
            s.setValue(
                config.SETTINGS_KEY_LIB_HEADER_STATE,
                self._lib_table.horizontalHeader().saveState(),
            )
            s.setValue(
                config.SETTINGS_KEY_SCENE_HEADER_STATE,
                self._scene_tree.header().saveState(),
            )
        finally:
            s.sync()

    def _restore_header_states_once(self) -> None:
        if self._header_states_restored:
            return
        self._header_states_restored = True
        s = self._settings
        lib_ba = _as_qbytearray(s.value(config.SETTINGS_KEY_LIB_HEADER_STATE))
        if lib_ba is not None:
            self._lib_table.horizontalHeader().restoreState(lib_ba)
        sc_ba = _as_qbytearray(s.value(config.SETTINGS_KEY_SCENE_HEADER_STATE))
        if sc_ba is not None:
            try:
                self._scene_tree.header().restoreState(sc_ba)
            except Exception:
                pass

    def showEvent(self, event: QShowEvent) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._geometry_restored:
            self._geometry_restored = True
            ba = _as_qbytearray(self._settings.value(config.SETTINGS_KEY_WINDOW_GEOMETRY))
            if ba is not None:
                self.restoreGeometry(ba)

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        try:
            if self._maya_adapter and hasattr(
                self._maya_adapter, "remove_scene_changed_callbacks"
            ):
                self._maya_adapter.remove_scene_changed_callbacks(
                    self._scene_changed_callback_ids
                )
        except Exception:
            pass
        self._persist_ui_settings()
        super().closeEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:  # type: ignore[override]
        self._persist_ui_settings()
        super().hideEvent(event)

    def _refresh_project(self) -> None:
        ad = self._maya_adapter
        if not ad:
            self._project_root = None
            self._status.setText("Maya adapter not set.")
            return
        sp = ad.get_scene_path()
        self._project_root = resolve_project_root_from_scene_path(sp)
        if self._project_root is None:
            self._status.setText("Scene not saved or outside project (need 01_assets + 02_shots).")
        else:
            self._status.setText(f"Project: {self._project_root}")

    def refresh_library(self) -> None:
        self._refresh_project()
        prev_group = self._group_combo.currentText()
        saved_gr = str(self._settings.value(config.SETTINGS_KEY_ASSETS_GROUP, "") or "").strip()
        if not prev_group and saved_gr:
            prev_group = saved_gr
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        if self._project_root is None:
            self._group_combo.blockSignals(False)
            self._lib_table.setRowCount(0)
            return
        groups = list_asset_groups(self._project_root)
        for g in groups:
            self._group_combo.addItem(g)
        if groups:
            if prev_group in groups:
                self._group_combo.setCurrentIndex(groups.index(prev_group))
            else:
                default_idx = 0
                if "_characters" in groups:
                    default_idx = groups.index("_characters")
                self._group_combo.setCurrentIndex(default_idx)
        self._group_combo.blockSignals(False)
        mode = "publish" if self._publish_chk.isChecked() else "work"
        group = self._group_combo.currentText()
        if not group:
            self._lib_table.setRowCount(0)
            return
        self._library_offers = scan_rigs(self._project_root, group, mode)  # type: ignore[arg-type]
        self._populate_library_table()
        self._filter_library_rows()

    def _populate_library_table(self) -> None:
        offers = self._library_offers
        mode: Mode = "publish" if self._publish_chk.isChecked() else "work"
        self._lib_table.setRowCount(len(offers))
        for row, offer in enumerate(offers):
            self._lib_table.setRowHeight(row, 56)
            name_w = QWidget()
            h = QHBoxLayout(name_w)
            h.setContentsMargins(4, 2, 4, 2)
            thumb_lbl = QLabel()
            thumb_lbl.setFixedSize(48, 48)
            tp = thumb_path_for_asset(offer.asset_root)
            if tp.is_file():
                pix = QPixmap(str(tp))
                if not pix.isNull():
                    thumb_lbl.setPixmap(pix.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            h.addWidget(thumb_lbl)
            nl = QLabel(f"<b style='color:{TEXT_PRIMARY}'>{offer.display_name}</b>")
            nl.setStyleSheet("background: transparent;")
            h.addWidget(nl, 1)
            self._lib_table.setCellWidget(row, 0, name_w)

            status = "READY" if offer.versions else "—"
            self._lib_table.setItem(row, 1, QTableWidgetItem(status))

            combo = QComboBox()
            combo.setMinimumWidth(96)
            n_ver = len(offer.versions)
            last_i = n_ver - 1
            for j, v in enumerate(offer.versions):
                tok = version_display_token_from_path(v.path, mode) or "—"
                combo.addItem(f"{tok} newest" if j == last_i else tok, v.path)
                combo.setItemData(j, v.path, Qt.ItemDataRole.ToolTipRole)
            combo.setProperty("version_entry_count", n_ver)
            if offer.versions:
                combo.blockSignals(True)
                combo.setCurrentIndex(min(offer.default_index, n_ver - 1))
                combo.blockSignals(False)
            combo.currentIndexChanged.connect(lambda _i, r=row: self._on_lib_version_changed(r))
            combo.currentIndexChanged.connect(self._on_version_entry_combo_index_changed)
            self._style_version_entry_combo(combo, n_ver)
            self._lib_table.setCellWidget(row, 2, combo)

            self._lib_table.setItem(row, 3, QTableWidgetItem(self._fmt_mtime(self._lib_selected_entry(row))))
            self._lib_table.setItem(row, 4, QTableWidgetItem("—"))

            for col in (1, 3, 4):
                it = self._lib_table.item(row, col)
                if it:
                    it.setData(Qt.ItemDataRole.UserRole, row)

    def _on_lib_version_changed(self, row: int) -> None:
        it = self._lib_table.item(row, 3)
        if it:
            it.setText(self._fmt_mtime(self._lib_selected_entry(row)))

    def _lib_selected_entry(self, row: int) -> Optional[RigVersionEntry]:
        if row < 0 or row >= len(self._library_offers):
            return None
        w = self._lib_table.cellWidget(row, 2)
        if not isinstance(w, QComboBox):
            return None
        offer = self._library_offers[row]
        idx = w.currentIndex()
        if idx < 0 or idx >= len(offer.versions):
            return None
        return offer.versions[idx]

    def _fmt_mtime(self, entry: Optional[RigVersionEntry]) -> str:
        if entry is None:
            return "—"
        try:
            return datetime.fromtimestamp(entry.mtime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "—"

    def _filter_library_rows(self) -> None:
        q = self._lib_search.text().strip().lower()
        for row in range(self._lib_table.rowCount()):
            if row >= len(self._library_offers):
                continue
            name = self._library_offers[row].display_name.lower()
            self._lib_table.setRowHidden(row, bool(q) and q not in name)

    def _selected_library_rows(self) -> List[int]:
        sm = self._lib_table.selectionModel()
        if sm is None:
            r = self._lib_table.currentRow()
            if r >= 0 and not self._lib_table.isRowHidden(r) and r < len(self._library_offers):
                return [r]
            return []
        rows = sorted({idx.row() for idx in sm.selectedRows()})
        return [
            r
            for r in rows
            if not self._lib_table.isRowHidden(r) and 0 <= r < len(self._library_offers)
        ]

    def _report_batch_errors(self, errors: List[str]) -> None:
        if not errors:
            return
        body = "\n".join(errors[:15])
        if len(errors) > 15:
            body += f"\n… and {len(errors) - 15} more."
        _message_box_at_cursor(self, QMessageBox.Icon.Warning, config.WINDOW_TITLE, body)

    def _open_paths_in_file_browser(self, paths: List[str]) -> None:
        uniq: List[str] = []
        seen: set[str] = set()
        for p in paths:
            raw = str(p or "").strip()
            if not raw:
                continue
            try:
                norm = os.path.normcase(os.path.normpath(raw))
            except Exception:
                norm = raw
            if norm in seen:
                continue
            seen.add(norm)
            uniq.append(raw)
        if not uniq:
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Information,
                config.WINDOW_TITLE,
                "No file location available for the current selection.",
            )
            return
        errors: List[str] = []
        for p in uniq:
            try:
                target = os.path.normpath(p)
                if os.path.isfile(target):
                    try:
                        subprocess.Popen(["explorer", "/select,", target])
                    except Exception:
                        os.startfile(os.path.dirname(target))  # type: ignore[attr-defined]
                elif os.path.isdir(target):
                    os.startfile(target)  # type: ignore[attr-defined]
                else:
                    parent = os.path.dirname(target)
                    if parent and os.path.isdir(parent):
                        os.startfile(parent)  # type: ignore[attr-defined]
                    else:
                        errors.append(target)
            except Exception:
                errors.append(p)
        if errors:
            self._report_batch_errors([f"Could not open file location: {p}" for p in errors])

    def _style_version_entry_combo(self, combo: QComboBox, entry_count: int) -> None:
        """Green bold text when the selected row is the newest version (last in list)."""
        last_i = entry_count - 1
        newest = entry_count > 0 and combo.currentIndex() == last_i
        color = VERSION_CELL_NEWEST if newest else TEXT_PRIMARY
        weight = "600" if newest else "400"
        combo.setStyleSheet(
            f"""
            QComboBox {{
                padding: 6px 8px;
                border: 1px solid rgba(39, 39, 42, 0.50);
                border-radius: 6px;
                background: {BG_SURFACE};
                color: {color};
                font-size: 13px;
                font-weight: {weight};
            }}
            QComboBox:focus {{ border: 1px solid {BLUE_600}; }}
            """
        )

    def _on_version_entry_combo_index_changed(self, _index: int) -> None:
        cb = self.sender()
        if not isinstance(cb, QComboBox):
            return
        prop = cb.property("version_entry_count")
        try:
            n = int(prop) if prop is not None else 0
        except (TypeError, ValueError):
            n = 0
        self._style_version_entry_combo(cb, n)

    def _build_scene_version_cell(
        self,
        disp: Optional[SceneRefVersionDisplay],
        path: str,
        mode: Mode,
        entries: List[RigVersionEntry],
        ref_node_short: str,
        *,
        in_project: bool,
        has_path: bool,
    ) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 0, 10, 0)
        use_combo = (
            bool(entries)
            and has_path
            and in_project
            and disp is not None
            and disp.has_scan_match
        )
        if use_combo:
            combo = QComboBox()
            combo.setMinimumWidth(88)
            combo.setToolTip("Choose rig version on disk for this reference")
            combo.setProperty("ref_node_short", ref_node_short)
            combo.setProperty("scene_path_ref", path)
            combo.setProperty("version_paths_joined", "\n".join(e.path for e in entries))
            last_i = len(entries) - 1
            for j, e in enumerate(entries):
                tok = version_display_token_from_path(e.path, mode) or "—"
                combo.addItem(f"{tok} newest" if j == last_i else tok, e.path)
                combo.setItemData(j, e.path, Qt.ItemDataRole.ToolTipRole)
            idx = rig_version_index_for_scene_path(path, entries)
            combo.setProperty("version_entry_count", len(entries))
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
            self._style_version_entry_combo(combo, len(entries))
            combo.currentIndexChanged.connect(self._on_version_entry_combo_index_changed)
            combo.activated.connect(
                lambda i, cb=combo: self._on_scene_version_combo_activated(cb, int(i))
            )
            lay.addWidget(combo, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            lay.addStretch(1)
            return w

        lab = QLabel()
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setStyleSheet("background: transparent; font-size: 12px;")
        if not has_path:
            lab.setText("—")
            lab.setStyleSheet(f"color: {TEXT_META}; background: transparent; font-size: 12px;")
            lab.setToolTip("")
        elif not in_project:
            tok = version_display_token_from_path(path, mode) or "—"
            lab.setText(
                f"<span style='color:{VERSION_CELL_OLD}'>{escape(tok)}</span>"
            )
            lab.setToolTip(path)
        elif disp is None:
            lab.setText("—")
            lab.setStyleSheet(f"color: {TEXT_META}; background: transparent; font-size: 12px;")
            lab.setToolTip(path)
        elif not disp.has_scan_match:
            t = escape(disp.current_token)
            lab.setText(f"<span style='color:{VERSION_CELL_OLD}'>{t}</span>")
            lab.setToolTip(disp.scene_path)
        elif disp.is_on_newest:
            t = escape(disp.newest_token)
            lab.setText(
                f"<span style='color:{VERSION_CELL_NEWEST}; font-weight:600'>{t} newest</span>"
            )
            lab.setToolTip(f"Newest on disk:\n{disp.scene_path}")
        else:
            c = escape(disp.current_token)
            n = escape(disp.newest_token)
            lab.setText(
                f"<span style='color:{VERSION_CELL_OLD}'>{c}</span> "
                f"<span style='color:{VERSION_CELL_NEWEST}; font-weight:600'>{n} newest</span>"
            )
            lab.setToolTip(f"Scene:\n{disp.scene_path}\n\nNewest:\n{disp.newest_path}")
        lay.addWidget(lab, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        return w

    def _on_scene_version_combo_activated(self, combo: QComboBox, index: int) -> None:
        ad = self._maya_adapter
        if not ad:
            return
        rn_prop = combo.property("ref_node_short")
        ref_node = rn_prop if isinstance(rn_prop, str) else ""
        if not ref_node:
            return
        sp_prop = combo.property("scene_path_ref")
        scene_path = sp_prop if isinstance(sp_prop, str) else ""
        new_path = combo.itemData(index)
        if not isinstance(new_path, str) or not new_path.strip():
            return
        if scene_path and rig_paths_equivalent(new_path.strip(), scene_path):
            return
        joined = combo.property("version_paths_joined")
        paths = (
            [p for p in str(joined).split("\n") if p.strip()]
            if isinstance(joined, str)
            else []
        )
        fake_entries = [
            RigVersionEntry(label="", path=p, sort_key=(0,), mtime=0.0) for p in paths
        ]
        try:
            ad.replace_reference_path(ref_node, os.path.normpath(new_path.strip()))
        except Exception as e:  # noqa: BLE001
            _message_box_at_cursor(self, QMessageBox.Icon.Critical, config.WINDOW_TITLE, str(e))
            combo.blockSignals(True)
            combo.setCurrentIndex(rig_version_index_for_scene_path(scene_path, fake_entries))
            combo.blockSignals(False)
            self._style_version_entry_combo(combo, len(paths))
            return
        self.refresh_scene()

    def _library_open(self) -> None:
        ad = self._maya_adapter
        if not ad:
            return
        rows = self._selected_library_rows()
        if not rows:
            _message_box_at_cursor(
                self, QMessageBox.Icon.Warning, config.WINDOW_TITLE, "Select a row with a rig file."
            )
            return
        if len(rows) > 1:
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Information,
                config.WINDOW_TITLE,
                "Only one scene can be open in Maya. Opening the first selected rig.",
            )
            rows = rows[:1]
        row = rows[0]
        ent = self._lib_selected_entry(row)
        if not ent:
            _message_box_at_cursor(
                self, QMessageBox.Icon.Warning, config.WINDOW_TITLE, "Select a row with a rig file."
            )
            return
        if ad.scene_is_modified():
            r = _message_box_at_cursor(
                self,
                QMessageBox.Icon.Question,
                config.WINDOW_TITLE,
                "Scene modified. Open anyway? Unsaved changes will be lost.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        try:
            ad.open_scene_path(ent.path, force=True)
        except Exception as e:  # noqa: BLE001
            _message_box_at_cursor(self, QMessageBox.Icon.Critical, config.WINDOW_TITLE, str(e))

    def _library_reference(self) -> None:
        ad = self._maya_adapter
        if not ad:
            return
        rows = self._selected_library_rows()
        if not rows:
            _message_box_at_cursor(
                self, QMessageBox.Icon.Warning, config.WINDOW_TITLE, "Select one or more asset rows."
            )
            return
        errors: List[str] = []
        for row in rows:
            if row >= len(self._library_offers):
                continue
            offer = self._library_offers[row]
            ent = self._lib_selected_entry(row)
            if not ent:
                errors.append(f"{offer.display_name}: no rig file for this asset.")
                continue
            ns = suggest_namespace_from_asset(offer.asset_folder_name)
            try:
                ad.create_file_reference(ent.path, ns)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{offer.display_name}: {e}")
        self._report_batch_errors(errors)
        self.refresh_scene()

    def _library_open_file_location(self) -> None:
        rows = self._selected_library_rows()
        paths: List[str] = []
        for row in rows:
            ent = self._lib_selected_entry(row)
            if ent and ent.path:
                paths.append(ent.path)
        self._open_paths_in_file_browser(paths)

    @staticmethod
    def _parse_scene_layouts_blob(raw: object) -> Dict[str, Any]:
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return {}
            try:
                o = json.loads(s)
                return dict(o) if isinstance(o, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def _scene_layout_storage_key(self) -> Optional[str]:
        ad = self._maya_adapter
        if not ad or not hasattr(ad, "get_scene_path"):
            return None
        sp = ad.get_scene_path()
        if not sp or not str(sp).strip():
            return None
        norm = os.path.normpath(str(sp)).replace("\\", "/").encode("utf-8", errors="replace")
        return hashlib.sha256(norm).hexdigest()[:40]

    def _load_scene_tree_layout_for_current_scene(self) -> Optional[List[Any]]:
        k = self._scene_layout_storage_key()
        if not k:
            return None
        store = self._parse_scene_layouts_blob(
            self._settings.value(config.SETTINGS_KEY_SCENE_TREE_LAYOUTS)
        )
        arr = store.get(k)
        if arr is None:
            return None
        return arr if isinstance(arr, list) else None

    def _on_scene_tree_structure_modified(self) -> None:
        if self._scene_tree_populating:
            return
        self._repair_scene_ref_tree_widgets()
        self._fit_scene_tree_branch_column()
        self._refresh_all_scene_tree_group_backgrounds()
        self._scene_layout_save_timer.start()

    def _flush_scene_tree_layout_to_settings(self) -> None:
        if self._scene_tree_populating:
            return
        k = self._scene_layout_storage_key()
        if not k:
            return
        layout = self._serialize_scene_tree()
        store = self._parse_scene_layouts_blob(
            self._settings.value(config.SETTINGS_KEY_SCENE_TREE_LAYOUTS)
        )
        store[k] = layout
        self._settings.setValue(config.SETTINGS_KEY_SCENE_TREE_LAYOUTS, json.dumps(store))

    def _serialize_scene_subtree(self, item: QTreeWidgetItem) -> Optional[dict]:
        d = item.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
        if isinstance(d, dict) and d.get("kind") == "group":
            gid = str(d.get("group_id") or "")
            label = str(d.get("label") or item.text(SCENE_TREE_COL_NS) or "Group")
            kids: List[dict] = []
            for i in range(item.childCount()):
                sub = self._serialize_scene_subtree(item.child(i))
                if sub is not None:
                    kids.append(sub)
            node: Dict[str, Any] = {"t": "g", "id": gid, "n": label, "c": kids}
            gc = d.get("group_color")
            if isinstance(gc, list) and len(gc) >= 3:
                node["rgb"] = [int(gc[0]), int(gc[1]), int(gc[2])]
            return node
        if isinstance(d, dict) and str(d.get("ref_node_short") or "").strip():
            return {"t": "r", "ref": str(d["ref_node_short"]).strip()}
        return None

    def _serialize_scene_tree(self) -> List[dict]:
        out: List[dict] = []
        tree = self._scene_tree
        for i in range(tree.topLevelItemCount()):
            node = self._serialize_scene_subtree(tree.topLevelItem(i))
            if node is not None:
                out.append(node)
        return out

    def _is_scene_group_item(self, item: QTreeWidgetItem) -> bool:
        d = item.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
        return isinstance(d, dict) and d.get("kind") == "group"

    def _is_scene_ref_item(self, item: QTreeWidgetItem) -> bool:
        d = item.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
        return (
            isinstance(d, dict)
            and str(d.get("ref_node_short") or "").strip()
            and d.get("kind") != "group"
        )

    def _iter_scene_tree_items(self) -> Iterator[QTreeWidgetItem]:
        def walk(it: QTreeWidgetItem) -> Iterator[QTreeWidgetItem]:
            yield it
            for i in range(it.childCount()):
                yield from walk(it.child(i))

        tree = self._scene_tree
        for i in range(tree.topLevelItemCount()):
            yield from walk(tree.topLevelItem(i))

    def _scene_sibling_index(self, item: QTreeWidgetItem) -> int:
        tree = self._scene_tree
        p = item.parent()
        if p is None:
            return tree.indexOfTopLevelItem(item)
        return p.indexOfChild(item)

    def _scene_item_depth(self, item: QTreeWidgetItem) -> int:
        d = 0
        p = item.parent()
        while p is not None:
            d += 1
            p = p.parent()
        return d

    def _fit_scene_tree_branch_column(self) -> None:
        """Widen column 0 so tree indent + pill/thumbnail cell are not clipped at max depth."""
        tree = self._scene_tree
        max_d = 0
        for it in self._iter_scene_tree_items():
            max_d = max(max_d, self._scene_item_depth(it))
        margin = 28
        thumb_block = 118
        need = margin + max_d * max(1, tree.indentation()) + thumb_block
        cur = tree.columnWidth(SCENE_TREE_COL_THUMB)
        tree.setColumnWidth(SCENE_TREE_COL_THUMB, max(cur, need))

    def _detach_scene_item(self, item: QTreeWidgetItem) -> None:
        tree = self._scene_tree
        p = item.parent()
        if p is None:
            i = tree.indexOfTopLevelItem(item)
            if i >= 0:
                tree.takeTopLevelItem(i)
        else:
            idx = p.indexOfChild(item)
            if idx >= 0:
                p.takeChild(idx)

    def _add_scene_tree_child(self, parent: Optional[QTreeWidgetItem], child: QTreeWidgetItem) -> None:
        if parent is None:
            self._scene_tree.addTopLevelItem(child)
        else:
            parent.addChild(child)

    def _place_group_row_widgets(self, item: QTreeWidgetItem) -> None:
        w_thumb = QWidget()
        w_thumb.setFixedHeight(56)
        self._scene_tree.setItemWidget(item, SCENE_TREE_COL_THUMB, w_thumb)
        w_ver = QWidget()
        w_ver.setFixedHeight(56)
        self._scene_tree.setItemWidget(item, SCENE_TREE_COL_VER, w_ver)

    def _apply_row_background_uniform(self, item: QTreeWidgetItem, brush: QBrush) -> None:
        n = self._scene_tree.columnCount()
        for col in range(n):
            item.setBackground(col, brush)

    def _refresh_all_scene_tree_group_backgrounds(self) -> None:
        """Folder rows use their stored tint; direct children refs share the same tint."""
        tree = self._scene_tree
        n = tree.columnCount()
        clear = QBrush()
        for it in self._iter_scene_tree_items():
            if self._is_scene_group_item(it):
                d = it.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
                if not isinstance(d, dict):
                    continue
                gc = d.get("group_color")
                if not isinstance(gc, list) or len(gc) < 3:
                    c = _stable_group_qcolor_from_id(str(d.get("group_id") or ""))
                    gc = _qcolor_to_rgb_list(c)
                    d["group_color"] = gc
                    it.setData(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1, d)
                c = QColor(int(gc[0]), int(gc[1]), int(gc[2]))
                self._apply_row_background_uniform(it, QBrush(c))
            elif self._is_scene_ref_item(it):
                p = it.parent()
                if p is not None and self._is_scene_group_item(p):
                    pd = p.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
                    gc = pd.get("group_color") if isinstance(pd, dict) else None
                    if isinstance(gc, list) and len(gc) >= 3:
                        c = QColor(int(gc[0]), int(gc[1]), int(gc[2]))
                        self._apply_row_background_uniform(it, QBrush(c))
                        for col in (SCENE_TREE_COL_THUMB, SCENE_TREE_COL_VER):
                            w = tree.itemWidget(it, col)
                            if w is not None:
                                w.setStyleSheet("background-color: transparent;")
                    else:
                        for col in range(n):
                            it.setBackground(col, clear)
                        for col in (SCENE_TREE_COL_THUMB, SCENE_TREE_COL_VER):
                            w = tree.itemWidget(it, col)
                            if w is not None:
                                w.setStyleSheet("")
                else:
                    for col in range(n):
                        it.setBackground(col, clear)
                    for col in (SCENE_TREE_COL_THUMB, SCENE_TREE_COL_VER):
                        w = tree.itemWidget(it, col)
                        if w is not None:
                            w.setStyleSheet("")

    def _create_group_tree_item(
        self,
        name: str,
        gid: str,
        rgb: Optional[List[int]] = None,
        *,
        prefer_random_color: bool = True,
    ) -> QTreeWidgetItem:
        it = QTreeWidgetItem()
        it.setSizeHint(SCENE_TREE_COL_THUMB, QSize(0, 56))
        it.setIcon(SCENE_TREE_COL_NS, ICON_FOLDER)
        it.setText(SCENE_TREE_COL_NS, name)
        it.setText(SCENE_TREE_COL_PATH, "")
        it.setText(SCENE_TREE_COL_STATUS, "")
        it.setText(SCENE_TREE_COL_INPROJ, "")
        if isinstance(rgb, list) and len(rgb) >= 3:
            c = QColor(
                max(0, min(255, int(rgb[0]))),
                max(0, min(255, int(rgb[1]))),
                max(0, min(255, int(rgb[2]))),
            )
        elif prefer_random_color:
            c = _random_group_folder_qcolor()
        else:
            c = _stable_group_qcolor_from_id(gid)
        payload = {
            "kind": "group",
            "group_id": gid,
            "label": name,
            "group_color": _qcolor_to_rgb_list(c),
        }
        it.setData(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1, payload)
        it.setExpanded(True)
        self._apply_row_background_uniform(it, QBrush(c))
        return it

    def _attach_ref_row_widgets(
        self, item: QTreeWidgetItem, thumb_cell: QWidget, ver_cell: QWidget
    ) -> None:
        self._scene_tree.setItemWidget(item, SCENE_TREE_COL_THUMB, thumb_cell)
        self._scene_tree.setItemWidget(item, SCENE_TREE_COL_VER, ver_cell)

    def _repair_scene_ref_tree_widgets(self) -> None:
        """Qt drops can detach column widgets from moved items — rebuild thumb + version cells."""
        mode = "publish" if self._publish_chk.isChecked() else "work"
        tree = self._scene_tree
        for item in self._iter_scene_tree_items():
            if not self._is_scene_ref_item(item):
                continue
            w0, w3 = tree.itemWidget(item, SCENE_TREE_COL_THUMB), tree.itemWidget(
                item, SCENE_TREE_COL_VER
            )
            if w0 is not None and w3 is not None:
                continue
            d = item.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
            if not isinstance(d, dict):
                continue
            if w0 is not None:
                tree.removeItemWidget(item, SCENE_TREE_COL_THUMB)
                w0.deleteLater()
            if w3 is not None:
                tree.removeItemWidget(item, SCENE_TREE_COL_VER)
                w3.deleteLater()
            thumb_cell, ver_cell = self._make_ref_row_cells(d, mode)
            self._attach_ref_row_widgets(item, thumb_cell, ver_cell)

    def _make_ref_row_cells(self, row_data: dict, mode: str) -> tuple[QWidget, QWidget]:
        path = row_data.get("resolved_path") or row_data.get("unresolved_path") or ""
        r = row_data
        loaded = r.get("is_loaded", True)
        exists = r.get("exists_on_disk", False)

        thumb_cell = QWidget()
        th_lay = QHBoxLayout(thumb_cell)
        th_lay.setContentsMargins(6, 2, 4, 2)
        th_lay.setSpacing(8)
        load_sw = QCheckBox()
        load_sw.setObjectName("SceneRefLoadSwitch")
        load_sw.setFixedSize(SCENE_REF_LOAD_PILL_W, SCENE_REF_LOAD_PILL_H)
        load_sw.setCursor(Qt.CursorShape.PointingHandCursor)
        load_sw.setToolTip("Load or unload this reference")
        load_sw.setProperty("ref_node_short", r.get("ref_node_short", ""))
        load_sw.blockSignals(True)
        load_sw.setChecked(bool(loaded))
        load_sw.blockSignals(False)
        if not exists and not loaded:
            load_sw.setEnabled(False)
            load_sw.setToolTip("File missing on disk — cannot load.")
        elif not exists and loaded:
            load_sw.setToolTip("File missing — turn off to unload from scene")
        load_sw.toggled.connect(self._on_scene_ref_load_switch_toggled)
        th_lay.addWidget(load_sw, 0, Qt.AlignmentFlag.AlignVCenter)
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(48, 48)
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_lbl.setStyleSheet(
            f"background-color: {BG_SURFACE}; border-radius: 4px; border: 1px solid #2a2a2c;"
        )
        tpath: Optional[Path] = None
        if self._project_root is not None and path.strip():
            tpath = thumb_path_for_reference_file(path, self._project_root)
        if tpath is not None and tpath.is_file():
            pix = QPixmap(str(tpath))
            if not pix.isNull():
                thumb_lbl.setPixmap(
                    pix.scaled(
                        48,
                        48,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        th_lay.addWidget(thumb_lbl)

        ip = r.get("in_project")
        has_path = bool(path.strip())
        ver_entries: List[RigVersionEntry] = []
        ver_disp: Optional[SceneRefVersionDisplay] = None
        if self._project_root is not None and has_path and ip is True:
            ver_entries = matching_rig_versions_for_scene_path(path, self._project_root, mode)
            ver_disp = scene_ref_version_display(
                path, self._project_root, mode, matching_entries=ver_entries
            )
        ver_cell = self._build_scene_version_cell(
            ver_disp,
            path,
            mode,
            ver_entries,
            str(r.get("ref_node_short", "")),
            in_project=(ip is True),
            has_path=has_path,
        )
        return thumb_cell, ver_cell

    def _build_ref_tree_item(self, r: dict, mode: str) -> tuple[QTreeWidgetItem, QWidget, QWidget, int]:
        item = QTreeWidgetItem()
        item.setSizeHint(SCENE_TREE_COL_THUMB, QSize(0, 56))
        path = r.get("resolved_path") or r.get("unresolved_path") or ""
        row_data = dict(r)
        pending_updates = 0
        if self._project_root is not None and path.strip() and r.get("in_project"):
            up_ent = newer_rig_version_for_scene_path(path, self._project_root, mode)
            if up_ent is not None:
                pending_updates = 1
                row_data["_update_path"] = up_ent.path
                row_data["_update_label"] = up_ent.label
            else:
                row_data["_update_path"] = None
                row_data["_update_label"] = None
        else:
            row_data["_update_path"] = None
            row_data["_update_label"] = None

        thumb_cell, ver_cell = self._make_ref_row_cells(row_data, mode)

        ip = r.get("in_project")
        loaded = r.get("is_loaded", True)
        exists = r.get("exists_on_disk", False)
        align_lp = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        item.setText(SCENE_TREE_COL_NS, str(r.get("namespace", "") or ""))
        item.setTextAlignment(SCENE_TREE_COL_NS, int(align_lp))
        short = os.path.basename(path) if path else ""
        item.setText(SCENE_TREE_COL_PATH, short)
        item.setTextAlignment(SCENE_TREE_COL_PATH, int(align_lp))
        item.setToolTip(SCENE_TREE_COL_PATH, path)
        if not exists:
            st = "Missing"
        elif not loaded:
            st = "Unloaded"
        else:
            st = "OK"
        item.setText(SCENE_TREE_COL_STATUS, st)
        item.setTextAlignment(SCENE_TREE_COL_STATUS, int(align_lp))
        item.setText(SCENE_TREE_COL_INPROJ, "Yes" if ip else ("No" if ip is False else "—"))
        item.setTextAlignment(SCENE_TREE_COL_INPROJ, int(align_lp))
        item.setData(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1, row_data)
        return item, thumb_cell, ver_cell, pending_updates

    def _apply_scene_layout_node_list(
        self,
        parent: Optional[QTreeWidgetItem],
        nodes: List[Any],
        rows_by_short: Dict[str, dict],
        mode: str,
    ) -> int:
        pending_updates = 0
        for node in nodes:
            if not isinstance(node, dict):
                continue
            t = node.get("t")
            if t == "g":
                gid = str(node.get("id") or uuid.uuid4().hex)
                name = str(node.get("n") or "Group")
                raw_rgb = node.get("rgb")
                rgb_list = raw_rgb if isinstance(raw_rgb, list) and len(raw_rgb) >= 3 else None
                g_item = self._create_group_tree_item(
                    name, gid, rgb_list, prefer_random_color=False
                )
                self._add_scene_tree_child(parent, g_item)
                self._place_group_row_widgets(g_item)
                children = node.get("c")
                if isinstance(children, list):
                    pending_updates += self._apply_scene_layout_node_list(
                        g_item, children, rows_by_short, mode
                    )
            elif t == "r":
                ref_key = str(node.get("ref") or "").strip()
                r = rows_by_short.pop(ref_key, None)
                if r is not None:
                    item, thumb_cell, ver_cell, p = self._build_ref_tree_item(r, mode)
                    self._add_scene_tree_child(parent, item)
                    self._attach_ref_row_widgets(item, thumb_cell, ver_cell)
                    pending_updates += p
        return pending_updates

    def _selected_scene_group_items(self) -> List[QTreeWidgetItem]:
        return [it for it in self._scene_tree.selectedItems() if self._is_scene_group_item(it)]

    def _scene_new_group(self) -> None:
        tree = self._scene_tree
        gid = uuid.uuid4().hex
        name, ok = QInputDialog.getText(self, config.WINDOW_TITLE, "Folder name:", text="Group")
        label = name.strip() if ok and name.strip() else "Group"
        item = self._create_group_tree_item(label, gid)
        cur = tree.currentItem()
        if cur is None:
            tree.addTopLevelItem(item)
        else:
            parent = cur.parent()
            if parent is None:
                idx = tree.indexOfTopLevelItem(cur) + 1
                tree.insertTopLevelItem(idx, item)
            else:
                idx = parent.indexOfChild(cur) + 1
                parent.insertChild(idx, item)
                parent.setExpanded(True)
        self._place_group_row_widgets(item)
        tree.clearSelection()
        item.setSelected(True)
        tree.setCurrentItem(item)
        self._on_scene_tree_structure_modified()

    def _scene_group_selection(self) -> None:
        tree = self._scene_tree
        refs = [it for it in tree.selectedItems() if self._is_scene_ref_item(it)]
        if not refs:
            return
        parents = {it.parent() for it in refs}
        if len(parents) != 1:
            self._scene_group_mixed_parents(refs)
            return
        parent = refs[0].parent()
        insert_at = min(self._scene_sibling_index(it) for it in refs)
        gid = uuid.uuid4().hex
        group = self._create_group_tree_item("Group", gid)
        for it in sorted(refs, key=self._scene_sibling_index, reverse=True):
            self._detach_scene_item(it)
        if parent is None:
            tree.insertTopLevelItem(insert_at, group)
        else:
            parent.insertChild(insert_at, group)
            parent.setExpanded(True)
        self._place_group_row_widgets(group)
        for it in refs:
            group.addChild(it)
        group.setExpanded(True)
        tree.clearSelection()
        group.setSelected(True)
        tree.setCurrentItem(group)
        self._on_scene_tree_structure_modified()

    def _scene_group_mixed_parents(self, refs: List[QTreeWidgetItem]) -> None:
        tree = self._scene_tree
        for it in refs:
            self._detach_scene_item(it)
        group = self._create_group_tree_item("Group", uuid.uuid4().hex)
        tree.addTopLevelItem(group)
        self._place_group_row_widgets(group)
        for it in refs:
            group.addChild(it)
        group.setExpanded(True)
        tree.clearSelection()
        group.setSelected(True)
        tree.setCurrentItem(group)
        self._on_scene_tree_structure_modified()

    def _scene_ungroup_selection(self) -> None:
        tree = self._scene_tree
        groups = self._selected_scene_group_items()
        if not groups:
            return
        for g in sorted(groups, key=self._scene_item_depth, reverse=True):
            parent = g.parent()
            if parent is None:
                g_idx = tree.indexOfTopLevelItem(g)
            else:
                g_idx = parent.indexOfChild(g)
            chs: List[QTreeWidgetItem] = []
            while g.childCount():
                chs.append(g.takeChild(0))
            self._detach_scene_item(g)
            for i, ch in enumerate(chs):
                if parent is None:
                    tree.insertTopLevelItem(g_idx + i, ch)
                else:
                    parent.insertChild(g_idx + i, ch)
        self._on_scene_tree_structure_modified()

    def _scene_rename_selected_group(self) -> None:
        grps = self._selected_scene_group_items()
        if len(grps) == 1:
            self._scene_rename_group(grps[0])

    def _scene_rename_group(self, item: QTreeWidgetItem) -> None:
        if not self._is_scene_group_item(item):
            return
        d = item.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
        if not isinstance(d, dict):
            return
        old = str(d.get("label") or item.text(SCENE_TREE_COL_NS) or "")
        new, ok = QInputDialog.getText(self, config.WINDOW_TITLE, "Folder name:", text=old)
        if not ok or not str(new).strip():
            return
        label = str(new).strip()
        d["label"] = label
        item.setText(SCENE_TREE_COL_NS, label)
        item.setData(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1, d)
        self._on_scene_tree_structure_modified()

    def refresh_scene(self) -> None:
        ad = self._maya_adapter
        if not ad:
            return
        pr = str(self._project_root) if self._project_root else None
        rows = ad.collect_file_references(pr)
        mode = "publish" if self._publish_chk.isChecked() else "work"
        rows_by_short: Dict[str, dict] = {}
        for r in rows:
            key = str(r.get("ref_node_short") or "").strip()
            if key:
                rows_by_short[key] = dict(r)

        self._scene_tree_populating = True
        try:
            self._scene_tree.clear()
            layout = self._load_scene_tree_layout_for_current_scene()
            pending_updates = 0
            if layout is not None:
                pending_updates += self._apply_scene_layout_node_list(
                    None, layout, rows_by_short, mode
                )
            for key in sorted(rows_by_short.keys()):
                r = rows_by_short[key]
                item, thumb_cell, ver_cell, p = self._build_ref_tree_item(r, mode)
                self._scene_tree.addTopLevelItem(item)
                self._attach_ref_row_widgets(item, thumb_cell, ver_cell)
                pending_updates += p
        finally:
            self._scene_tree_populating = False

        self._fit_scene_tree_branch_column()
        self._refresh_all_scene_tree_group_backgrounds()
        self._scene_update_all_btn.setEnabled(pending_updates > 0)
        self._scene_update_all_btn.setText(
            f"Update all ({pending_updates})" if pending_updates else "Update all"
        )

    def _all_scene_refs(self) -> List[dict]:
        out: List[dict] = []
        for it in self._iter_scene_tree_items():
            if not self._is_scene_ref_item(it):
                continue
            d = it.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
            if isinstance(d, dict):
                out.append(d)
        return out

    def _pairs_for_reference_updates(self, refs: List[dict]) -> tuple[List[tuple[dict, str]], int]:
        pairs: List[tuple[dict, str]] = []
        skipped = 0
        for r in refs:
            p = r.get("_update_path")
            if isinstance(p, str) and p.strip():
                pairs.append((r, p.strip()))
            else:
                skipped += 1
        return pairs, skipped

    def _apply_reference_updates(self, pairs: List[tuple[dict, str]], skipped: int) -> None:
        ad = self._maya_adapter
        if not ad:
            return
        errors: List[str] = []
        for r, p in pairs:
            try:
                ad.replace_reference_path(r["ref_node_short"], p)
            except Exception as e:  # noqa: BLE001
                label = r.get("namespace") or r.get("ref_node_short") or "?"
                errors.append(f"{label}: {e}")
        self._report_batch_errors(errors)
        if skipped and not errors:
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Information,
                config.WINDOW_TITLE,
                f"Updated {len(pairs)} reference(s). "
                f"{skipped} skipped (already latest or not applicable).",
            )
        self.refresh_scene()

    def _selected_scene_refs(self) -> List[dict]:
        out: List[dict] = []
        for it in self._scene_tree.selectedItems():
            if not self._is_scene_ref_item(it):
                continue
            d = it.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
            if isinstance(d, dict):
                out.append(d)
        return out

    def _selected_scene_refs_for_focus(self) -> List[dict]:
        """
        Preserve the current row as the active/last-picked item for Maya selection.

        Qt's multi-select order is not tied to click order; we keep the bulk selection,
        but move the current item's reference to the end so Maya's active object matches
        the user's latest click.
        """
        refs = self._selected_scene_refs()
        cur = self._scene_tree.currentItem()
        if cur is None or len(refs) <= 1:
            return refs
        if not self._is_scene_ref_item(cur):
            return refs
        cur_data = cur.data(SCENE_TREE_COL_PAYLOAD, Qt.ItemDataRole.UserRole + 1)
        if not isinstance(cur_data, dict):
            return refs
        cur_ref = str(cur_data.get("ref_node_short", "") or "").strip()
        if not cur_ref:
            return refs
        rest = [r for r in refs if str(r.get("ref_node_short", "") or "").strip() != cur_ref]
        rest.append(cur_data)
        return rest

    def _on_scene_tree_selection_changed(self) -> None:
        if not self._scene_focus_chk.isChecked():
            return
        ad = self._maya_adapter
        if not ad:
            return
        refs = self._selected_scene_refs_for_focus()
        if not refs:
            return
        ref_nodes = [
            str(r.get("ref_node_short", "") or "").strip()
            for r in refs
            if str(r.get("ref_node_short", "") or "").strip()
        ]
        if not ref_nodes:
            return
        try:
            focus_mode = str(self._scene_focus_mode.currentData() or "root")
            custom_token = self._scene_focus_custom.text().strip()
            custom_exclude_token = self._scene_focus_custom_exclude.text().strip()
            if hasattr(ad, "focus_references_in_outliner"):
                ad.focus_references_in_outliner(
                    ref_nodes,
                    mode=focus_mode,
                    custom_token=custom_token,
                    custom_exclude_token=custom_exclude_token,
                )
            elif hasattr(ad, "focus_reference_in_outliner"):
                ad.focus_reference_in_outliner(ref_nodes[0])
            if hasattr(ad, "focus_model_panel_for_hotkeys"):
                ad.focus_model_panel_for_hotkeys(prefer_shot_camera=False)
        except Exception:
            pass

    def _on_scene_ref_load_switch_toggled(self, checked: bool) -> None:
        ad = self._maya_adapter
        if not ad:
            return
        w = self.sender()
        if not isinstance(w, QCheckBox):
            return
        prop = w.property("ref_node_short")
        ref_node = prop if isinstance(prop, str) else ""
        if not ref_node:
            return
        try:
            if checked:
                ad.load_reference_node(ref_node)
            else:
                ad.unload_reference_node(ref_node)
        except Exception as e:  # noqa: BLE001
            _message_box_at_cursor(self, QMessageBox.Icon.Critical, config.WINDOW_TITLE, str(e))
            w.blockSignals(True)
            w.setChecked(not checked)
            w.blockSignals(False)
            return
        self.refresh_scene()

    def _scene_load(self) -> None:
        ad = self._maya_adapter
        refs = self._selected_scene_refs()
        if not ad or not refs:
            return
        errors: List[str] = []
        for r in refs:
            try:
                ad.load_reference_node(r["ref_node_short"])
            except Exception as e:  # noqa: BLE001
                label = r.get("namespace") or r.get("ref_node_short") or "?"
                errors.append(f"{label}: {e}")
        self._report_batch_errors(errors)
        self.refresh_scene()

    def _scene_unload(self) -> None:
        ad = self._maya_adapter
        refs = self._selected_scene_refs()
        if not ad or not refs:
            return
        errors: List[str] = []
        for r in refs:
            try:
                ad.unload_reference_node(r["ref_node_short"])
            except Exception as e:  # noqa: BLE001
                label = r.get("namespace") or r.get("ref_node_short") or "?"
                errors.append(f"{label}: {e}")
        self._report_batch_errors(errors)
        self.refresh_scene()

    def _scene_reload(self) -> None:
        ad = self._maya_adapter
        refs = self._selected_scene_refs()
        if not ad or not refs:
            return
        errors: List[str] = []
        for r in refs:
            try:
                ad.reload_reference_node(r["ref_node_short"])
            except Exception as e:  # noqa: BLE001
                label = r.get("namespace") or r.get("ref_node_short") or "?"
                errors.append(f"{label}: {e}")
        self._report_batch_errors(errors)
        self.refresh_scene()

    def _scene_rename_namespace(self) -> None:
        ad = self._maya_adapter
        refs = self._selected_scene_refs()
        if not ad or len(refs) != 1:
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Information,
                config.WINDOW_TITLE,
                "Select exactly one scene reference to rename its namespace.",
            )
            return
        r = refs[0]
        current_ns = str(r.get("namespace", "") or "").strip()
        new_ns, ok = QInputDialog.getText(
            self,
            config.WINDOW_TITLE,
            "Rename reference namespace:",
            text=current_ns,
        )
        if not ok:
            return
        new_ns = str(new_ns or "").strip()
        if not new_ns or new_ns == current_ns:
            return
        try:
            ad.rename_reference_namespace(r["ref_node_short"], new_ns)
        except Exception as e:  # noqa: BLE001
            _message_box_at_cursor(self, QMessageBox.Icon.Critical, config.WINDOW_TITLE, str(e))
            return
        self.refresh_scene()

    def _scene_open_file_location(self) -> None:
        refs = self._selected_scene_refs()
        paths: List[str] = []
        for r in refs:
            p = str(r.get("resolved_path") or r.get("unresolved_path") or "").strip()
            if p:
                paths.append(p)
        self._open_paths_in_file_browser(paths)

    def _scene_duplicate(self) -> None:
        ad = self._maya_adapter
        refs = self._selected_scene_refs()
        if not ad or not refs:
            return
        errors: List[str] = []
        for r in refs:
            try:
                ad.duplicate_reference_node(r["ref_node_short"])
            except Exception as e:  # noqa: BLE001
                label = r.get("namespace") or r.get("ref_node_short") or "?"
                errors.append(f"{label}: {e}")
        self._report_batch_errors(errors)
        self.refresh_scene()

    def _scene_duplicate_smart(self) -> None:
        ad = self._maya_adapter
        refs = self._selected_scene_refs()
        if not ad or not refs:
            return
        errors: List[str] = []
        for r in refs:
            try:
                ad.duplicate_reference_smart(r["ref_node_short"])
            except Exception as e:  # noqa: BLE001
                label = r.get("namespace") or r.get("ref_node_short") or "?"
                errors.append(f"{label}: {e}")
        self._report_batch_errors(errors)
        self.refresh_scene()

    def _scene_choose_version(self) -> None:
        ad = self._maya_adapter
        if not ad or self._project_root is None:
            return
        refs = self._selected_scene_refs()
        if len(refs) != 1:
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Information,
                config.WINDOW_TITLE,
                "Select exactly one reference to choose a version from disk.",
            )
            return
        r = refs[0]
        path = (r.get("resolved_path") or r.get("unresolved_path") or "").strip()
        if not path:
            _message_box_at_cursor(
                self, QMessageBox.Icon.Warning, config.WINDOW_TITLE, "Reference has no file path."
            )
            return
        mode = "publish" if self._publish_chk.isChecked() else "work"
        entries = matching_rig_versions_for_scene_path(path, self._project_root, mode)
        if not entries:
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Information,
                config.WINDOW_TITLE,
                "No matching rig versions found for this reference. "
                "Check Published vs Work on the Library tab and project layout.",
            )
            return
        dlg = _DialogAtCursor(self)
        dlg.setWindowTitle(f"{config.WINDOW_TITLE} — version")
        dlg.setMinimumWidth(440)
        vlay = QVBoxLayout(dlg)
        vlay.setSpacing(12)
        head = QLabel(f"<span style='color:{TEXT_META};'>Current:</span> {escape(path)}")
        head.setWordWrap(True)
        head.setTextFormat(Qt.TextFormat.RichText)
        vlay.addWidget(head)
        lab = QLabel("Available versions on disk:")
        lab.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        vlay.addWidget(lab)
        combo = QComboBox()
        combo.setStyleSheet(STYLE_INPUT)
        for e in entries:
            combo.addItem(e.label, e.path)
        combo.setCurrentIndex(rig_version_index_for_scene_path(path, entries))
        vlay.addWidget(combo)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        vlay.addWidget(box)
        dlg.setStyleSheet(
            STYLE_WINDOW
            + STYLE_INPUT
            + STYLE_BTN
            + STYLE_BTN_PRIMARY
            + STYLE_IOS_REF_SWITCH
            + STYLE_EXTRAS
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_path = combo.currentData()
        if not isinstance(new_path, str) or not new_path.strip():
            return
        if rig_paths_equivalent(new_path, path):
            return
        try:
            ad.replace_reference_path(r["ref_node_short"], new_path)
        except Exception as e:  # noqa: BLE001
            _message_box_at_cursor(self, QMessageBox.Icon.Critical, config.WINDOW_TITLE, str(e))
            return
        self.refresh_scene()

    def _scene_update_version(self) -> None:
        if not self._maya_adapter:
            return
        refs = self._selected_scene_refs()
        if not refs:
            return
        pairs, skipped = self._pairs_for_reference_updates(refs)
        if not pairs:
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Information,
                config.WINDOW_TITLE,
                "No newer version found for the selection. "
                "Uses the same Published vs Work mode as the Library tab; "
                "refresh the scene if you changed rig files on disk.",
            )
            return
        self._apply_reference_updates(pairs, skipped)

    def _scene_update_all_versions(self) -> None:
        if not self._maya_adapter:
            return
        refs = self._all_scene_refs()
        pairs, skipped = self._pairs_for_reference_updates(refs)
        if not pairs:
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Information,
                config.WINDOW_TITLE,
                "No references have a newer version on disk. "
                "Check Published vs Work on the Library tab and refresh the scene list.",
            )
            return
        n = len(pairs)
        if (
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Question,
                config.WINDOW_TITLE,
                f"Update {n} reference(s) to the latest matching rig file on disk?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._apply_reference_updates(pairs, skipped)

    def _scene_remove(self) -> None:
        ad = self._maya_adapter
        refs = self._selected_scene_refs()
        if not ad or not refs:
            return
        n = len(refs)
        msg = "Remove this reference?" if n == 1 else f"Remove {n} references?"
        if (
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Question,
                config.WINDOW_TITLE,
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        errors: List[str] = []
        for r in refs:
            try:
                ad.remove_file_reference(
                    r["ref_node_short"],
                    exists_on_disk=bool(r.get("exists_on_disk")),
                    is_loaded=bool(r.get("is_loaded")),
                )
            except Exception as e:  # noqa: BLE001
                label = r.get("namespace") or r.get("ref_node_short") or "?"
                errors.append(f"{label}: {e}")
        self._report_batch_errors(errors)
        self.refresh_scene()

    def _scene_replace_from_library(self) -> None:
        ad = self._maya_adapter
        if not ad:
            return
        refs = self._selected_scene_refs()
        lib_rows = self._selected_library_rows()
        if not refs:
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Warning,
                config.WINDOW_TITLE,
                "Select one or more scene reference rows.",
            )
            return
        if len(lib_rows) != 1:
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Warning,
                config.WINDOW_TITLE,
                "Select exactly one library row (with a version) to use as the new file path.",
            )
            return
        lr = lib_rows[0]
        ent = self._lib_selected_entry(lr)
        if not ent:
            _message_box_at_cursor(
                self,
                QMessageBox.Icon.Warning,
                config.WINDOW_TITLE,
                "The selected library row has no rig file version.",
            )
            return
        errors: List[str] = []
        for sr in refs:
            try:
                ad.replace_reference_path(sr["ref_node_short"], ent.path)
            except Exception as e:  # noqa: BLE001
                label = sr.get("namespace") or sr.get("ref_node_short") or "?"
                errors.append(f"{label}: {e}")
        self._report_batch_errors(errors)
        self.refresh_scene()

    def _scene_replace_browse(self) -> None:
        ad = self._maya_adapter
        refs = self._selected_scene_refs()
        if not ad or not refs:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Replace reference" if len(refs) == 1 else f"Replace {len(refs)} references",
            "",
            "Maya files (*.ma *.mb);;All (*.*)",
        )
        if not path:
            return
        errors: List[str] = []
        for sr in refs:
            try:
                ad.replace_reference_path(sr["ref_node_short"], path)
            except Exception as e:  # noqa: BLE001
                label = sr.get("namespace") or sr.get("ref_node_short") or "?"
                errors.append(f"{label}: {e}")
        self._report_batch_errors(errors)
        self.refresh_scene()

    def show_dockable(self) -> None:
        parent = None
        if self._maya_adapter:
            parent = self._maya_adapter.get_main_qt_window()
        if MayaQWidgetDockableMixin is not None and isinstance(self, MayaQWidgetDockableMixin):
            try:
                self.show(
                    dockable=True,
                    area="right",
                    floating=False,
                    allowedArea=["right", "left", "top", "bottom"],
                )
                return
            except Exception:
                pass
        if parent:
            self.setParent(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        self.show()
        self.raise_()
        self.activateWindow()
