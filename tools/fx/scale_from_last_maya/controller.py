"""Maya entry point for scaling object positions from the last-selected object."""

from __future__ import annotations

import importlib
import traceback
from typing import Any, Dict, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel, QFrame, QVBoxLayout, QWidget

from tools.fx.scale_from_last_maya import config
from tools.fx.scale_from_last_maya.logic import (
    as_vec3,
    scale_positions_from_pivot,
)

_active_session: Optional["_InteractiveScaleSession"] = None


class _EnterEscEventFilter(QObject):
    def __init__(self, session: "_InteractiveScaleSession") -> None:
        super().__init__()
        self._session = session

    def eventFilter(self, _obj: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() != QEvent.Type.KeyPress:
            return False
        key = getattr(event, "key", lambda: None)()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._session.apply()
            return True
        if key == Qt.Key.Key_Escape:
            self._session.cancel()
            return True
        return False


class _HintWindow(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(config.WINDOW_TITLE)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet(
            "QFrame {"
            " background: rgba(18, 18, 20, 240);"
            " color: #fafafa;"
            " border: 1px solid rgba(37, 99, 235, 180);"
            " border-radius: 10px;"
            "}"
            "QLabel#title { font-size: 13px; font-weight: 700; }"
            "QLabel#body { font-size: 12px; color: #d4d4d8; }"
        )
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        title = QLabel("Scale locator de doi vi tri object")
        title.setObjectName("title")
        body = QLabel(
            "Scale locator trong viewport.\n"
            "Objects chi doi vi tri, khong doi scale.\n"
            "Nhan Enter de Apply, Esc de Cancel."
        )
        body.setObjectName("body")
        body.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(body)

    def place_near_top_right(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        self.adjustSize()
        self.move(QPoint(rect.right() - self.width() - 24, rect.top() + 40))


class _InteractiveScaleSession(QObject):
    def __init__(
        self,
        maya_adapter: Any,
        *,
        ordered_selection: list[str],
        pivot_node: str,
        target_nodes: list[str],
    ) -> None:
        super().__init__()
        self._maya = maya_adapter
        self._ordered_selection = list(ordered_selection)
        self._pivot_node = pivot_node
        self._target_nodes = list(target_nodes)
        self._pivot_position = as_vec3(self._maya.get_world_rotate_pivot(pivot_node), (0.0, 0.0, 0.0))
        self._initial_positions: Dict[str, tuple[float, float, float]] = {
            node: as_vec3(self._maya.get_world_translation(node), (0.0, 0.0, 0.0))
            for node in self._target_nodes
        }
        self._control = ""
        self._last_scale = (1.0, 1.0, 1.0)
        self._timer = QTimer(self)
        self._timer.setInterval(config.POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll_scale)
        self._hint = _HintWindow(self._maya.get_main_qt_window())
        self._event_filter = _EnterEscEventFilter(self)
        self._closed = False

    def start(self) -> None:
        self._control = self._maya.create_locator(
            config.LOCATOR_NAME,
            world_position=self._pivot_position,
        )
        self._maya.set_locator_display_scale(self._control, 2.0)
        self._maya.select_nodes([self._control])
        self._hint.place_near_top_right()
        self._hint.show()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._event_filter)
        self._timer.start()
        self._maya.show_in_view_message(
            "Scale locator roi nhan <hl>Enter</hl> de apply, <hl>Esc</hl> de huy.",
            position="topCenter",
            fade=True,
        )

    def _poll_scale(self) -> None:
        if self._closed or not self._maya.node_exists(self._control):
            return
        scale_xyz = as_vec3(self._maya.get_local_scale(self._control), (1.0, 1.0, 1.0))
        if scale_xyz == self._last_scale:
            return
        self._last_scale = scale_xyz
        updated = scale_positions_from_pivot(
            self._initial_positions,
            self._pivot_position,
            scale_xyz,
        )
        for node, pos in updated.items():
            if self._maya.node_exists(node):
                self._maya.set_world_translation(node, pos)

    def apply(self) -> None:
        if self._closed:
            return
        self._poll_scale()
        self._cleanup(restore_initial=False)
        self._maya.show_in_view_message(
            "Da apply scale positions tu tam cua object cuoi.",
            position="topCenter",
            fade=True,
        )

    def cancel(self) -> None:
        if self._closed:
            return
        for node, pos in self._initial_positions.items():
            if self._maya.node_exists(node):
                self._maya.set_world_translation(node, pos)
        self._cleanup(restore_initial=True)
        self._maya.show_in_view_message(
            "Da huy scale positions.",
            position="topCenter",
            fade=True,
        )

    def _cleanup(self, *, restore_initial: bool) -> None:
        self._closed = True
        self._timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self._event_filter)
        self._hint.close()
        self._maya.delete_node(self._control)
        if restore_initial:
            self._maya.select_nodes(self._ordered_selection)
        else:
            self._maya.select_nodes(self._target_nodes + [self._pivot_node])


def _show_selection_error(maya_adapter: Any, message: str) -> None:
    maya_adapter.show_in_view_message(message, position="topCenter", fade=True)
    print(f"[{config.WINDOW_TITLE}] {message}")


def run() -> None:
    global _active_session

    try:
        import apps.maya.adapter as maya_adapter
    except ImportError as e:
        print(f"[{config.WINDOW_TITLE}] Import error: {e}")
        traceback.print_exc()
        return

    importlib.reload(maya_adapter)

    if not maya_adapter.is_available():
        print(f"[{config.WINDOW_TITLE}] Run inside Maya Script Editor.")
        return

    ordered = maya_adapter.get_ordered_selection_long(type_name="transform")
    if len(ordered) < 2:
        _show_selection_error(
            maya_adapter,
            "Chon it nhat 2 transform. Object chon cuoi se la tam scale.",
        )
        return

    pivot_node = ordered[-1]
    target_nodes = ordered[:-1]

    if _active_session is not None:
        try:
            _active_session.cancel()
        except Exception:
            pass
        _active_session = None

    try:
        session = _InteractiveScaleSession(
            maya_adapter,
            ordered_selection=ordered,
            pivot_node=pivot_node,
            target_nodes=target_nodes,
        )
        session.start()
        _active_session = session
        print(
            f"[{config.WINDOW_TITLE}] Started. "
            f"Pivot = {pivot_node}, targets = {len(target_nodes)}"
        )
    except Exception:
        traceback.print_exc()
        _show_selection_error(maya_adapter, "Khong khoi tao duoc tool.")
