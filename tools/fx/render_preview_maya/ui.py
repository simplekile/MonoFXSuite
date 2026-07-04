"""
Render Preview — Maya UI (PySide6).

Kept intentionally similar to tools/fx/usd_export_maya/ui.py styling.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QByteArray, QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPixmap, QIcon
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from tools.fx.render_preview_maya import config
from tools.fx.render_preview_maya.logic import Ext, frame_file_path, is_image_ext, normalize_ext, validate_frame_range


BG_PANEL = "#18181b"
BG_CONTENT = "#121214"
BG_SURFACE = "#27272a"
TEXT_PRIMARY = "#fafafa"
TEXT_LABEL = "#a1a1aa"
TEXT_META = "#71717a"
BLUE_600 = "#2563eb"

STYLE_WINDOW = f"""
    QWidget#RenderPreviewMayaWindow {{
        background-color: {BG_PANEL};
        color: {TEXT_PRIMARY};
    }}
"""

STYLE_INPUT = f"""
    QLineEdit, QSpinBox, QComboBox {{
        padding: 6px 8px;
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 6px;
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        font-size: 13px;
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {BLUE_600}; }}
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
"""

STYLE_BTN_PRIMARY = f"""
    QPushButton {{
        background: rgba(37, 99, 235, 0.22);
        border: 1px solid rgba(37, 99, 235, 0.70);
        color: {TEXT_PRIMARY};
        padding: 8px 16px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background: rgba(37, 99, 235, 0.35);
    }}
"""

STYLE_ICON_BTN = """
    QPushButton#RenderPreviewIconButton {
        background: rgba(12, 12, 14, 0.82);
        color: #fafafa;
        padding: 0px;
        border: 1px solid rgba(255, 255, 255, 0.18);
        border-radius: 12px;
        min-width: 46px;
        min-height: 46px;
    }
    QPushButton#RenderPreviewIconButton:hover {
        background: rgba(37, 99, 235, 0.82);
        color: #ffffff;
    }
    QPushButton#RenderPreviewIconButton:disabled {
        opacity: 0.7;
    }
"""


def _load_svg_icon(svg_filename: str, *, size: int = 18) -> QIcon:
    assets_dir = Path(__file__).resolve().parent / "assets"
    p = assets_dir / svg_filename
    if not p.exists():
        return QIcon()
    try:
        svg_bytes = p.read_bytes()
        renderer = QSvgRenderer(QByteArray(svg_bytes))
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        renderer.render(painter)
        painter.end()
        return QIcon(pm)
    except Exception:
        return QIcon()


class _LoadingOverlay(QWidget):
    _MODE_LOADING = 0
    _MODE_DONE = 1

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._text = "Loading..."
        self._sub_text: Optional[str] = None
        self._mode = self._MODE_LOADING
        self._cancelled = False
        self.setVisible(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def reset(self) -> None:
        self._cancelled = False
        self._mode = self._MODE_LOADING

    def set_text(self, text: str, sub_text: Optional[str] = None) -> None:
        self._text = text
        self._sub_text = sub_text or "Press Esc to cancel"
        self._mode = self._MODE_LOADING
        self.update()

    def set_done(self, text: str, sub_text: Optional[str] = None) -> None:
        self._text = text
        self._sub_text = sub_text or "Click to continue"
        self._mode = self._MODE_DONE
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))
        painter.setPen(QColor(TEXT_PRIMARY))
        painter.setFont(QFont("Inter", 13, QFont.Weight.DemiBold))
        painter.drawText(self.rect().adjusted(0, -20, 0, 0), Qt.AlignmentFlag.AlignCenter, self._text)
        if self._sub_text:
            painter.setPen(QColor(TEXT_META))
            painter.setFont(QFont("Inter", 10, QFont.Weight.Normal))
            painter.drawText(self.rect().adjusted(0, 40, 0, 0), Qt.AlignmentFlag.AlignCenter, self._sub_text)
        painter.end()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self._mode == self._MODE_DONE:
            self.reset()
            self.setVisible(False)
            event.accept()
            return
        event.ignore()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape and self._mode == self._MODE_LOADING:
            self._cancelled = True
            self._text = "Cancelling..."
            self._sub_text = None
            self.update()
            event.accept()
            return
        super().keyPressEvent(event)


@dataclass
class RenderPreviewState:
    scene_path: str = ""
    output_root: str = ""
    basename: str = "untitled"
    start_frame: int = 1
    end_frame: int = 1
    fps: float = 24.0
    width: int = 1920
    height: int = 1080
    ext: Ext = "jpg"
    activate_shot_camera: bool = True
    rename_to_camera: bool = False
    loop_playback: bool = False
    force_shot_overscan_1: bool = True
    viewport_hud_enabled: bool = True
    viewport_hud_font_size: str = "large"
    viewport_hud_show_shot: bool = True
    viewport_hud_show_frame: bool = True
    viewport_hud_show_camera: bool = True
    viewport_hud_show_focal_length: bool = True
    viewport_hud_show_fps: bool = True


class RenderPreviewMayaSettingsDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], state: RenderPreviewState) -> None:
        super().__init__(parent)
        self.setWindowTitle("Render Preview — Settings")
        self.setMinimumWidth(560)
        self.setStyleSheet(STYLE_WINDOW + STYLE_INPUT + STYLE_BTN + STYLE_BTN_PRIMARY)

        self._out_root = QLineEdit(state.output_root)
        self._basename = QLineEdit(state.basename)
        self._start = QSpinBox()
        self._start.setRange(-999999, 999999)
        self._start.setValue(int(state.start_frame))
        self._end = QSpinBox()
        self._end.setRange(-999999, 999999)
        self._end.setValue(int(state.end_frame))
        self._w = QSpinBox()
        self._w.setRange(1, 16384)
        self._w.setValue(int(state.width))
        self._h = QSpinBox()
        self._h.setRange(1, 16384)
        self._h.setValue(int(state.height))
        self._ext = QComboBox()
        self._ext.addItems(["jpg", "png", "avi", "mov"])
        self._ext.setCurrentText(state.ext)

        self._activate = QCheckBox("Use shot camera panel for playblast (no viewport focus change)")
        self._activate.setChecked(bool(state.activate_shot_camera))
        self._activate.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")

        self._rename = QCheckBox("Rename output folder to active panel camera")
        self._rename.setChecked(bool(state.rename_to_camera))
        self._rename.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")

        self._force_over = QCheckBox("Force shot camera overscan to 1.0 during playblast (restore after)")
        self._force_over.setChecked(bool(state.force_shot_overscan_1))
        self._force_over.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")

        self._loop = QCheckBox("Loop playback (preview)")
        self._loop.setChecked(bool(state.loop_playback))
        self._loop.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")

        self._hud_enabled = QCheckBox("Viewport HUD during playblast")
        self._hud_enabled.setChecked(bool(state.viewport_hud_enabled))
        self._hud_enabled.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")

        self._hud_shot = QCheckBox("Show shot token")
        self._hud_shot.setChecked(bool(state.viewport_hud_show_shot))
        self._hud_frame = QCheckBox("Show current frame")
        self._hud_frame.setChecked(bool(state.viewport_hud_show_frame))
        self._hud_cam = QCheckBox("Show camera name")
        self._hud_cam.setChecked(bool(state.viewport_hud_show_camera))
        self._hud_focal = QCheckBox("Show focal length")
        self._hud_focal.setChecked(bool(state.viewport_hud_show_focal_length))
        self._hud_fps = QCheckBox("Show scene FPS")
        self._hud_fps.setChecked(bool(state.viewport_hud_show_fps))
        for cb in (
            self._hud_shot,
            self._hud_frame,
            self._hud_cam,
            self._hud_focal,
            self._hud_fps,
        ):
            cb.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 13px; margin-left: 20px;")

        hud_row = QHBoxLayout()
        hud_row.addWidget(QLabel("HUD font size"))
        self._hud_font = QComboBox()
        self._hud_font.addItems(["large", "small"])
        cur = str(state.viewport_hud_font_size or "large").lower().strip()
        self._hud_font.setCurrentText("small" if cur == "small" else "large")
        self._hud_font.setStyleSheet(STYLE_INPUT)
        hud_row.addWidget(self._hud_font)
        hud_row.addStretch()
        hud_wrap = QWidget()
        hud_wrap.setLayout(hud_row)

        def _sync_hud_children() -> None:
            on = self._hud_enabled.isChecked()
            self._hud_shot.setEnabled(on)
            self._hud_frame.setEnabled(on)
            self._hud_cam.setEnabled(on)
            self._hud_focal.setEnabled(on)
            self._hud_fps.setEnabled(on)
            self._hud_font.setEnabled(on)

        self._hud_enabled.toggled.connect(lambda _v: _sync_hud_children())
        _sync_hud_children()

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("Output root"), 0, 0)
        grid.addWidget(self._out_root, 0, 1)
        grid.addWidget(QLabel("Basename"), 1, 0)
        grid.addWidget(self._basename, 1, 1)
        grid.addWidget(QLabel("Start frame"), 2, 0)
        grid.addWidget(self._start, 2, 1)
        grid.addWidget(QLabel("End frame"), 3, 0)
        grid.addWidget(self._end, 3, 1)
        grid.addWidget(QLabel("Resolution"), 4, 0)
        res_row = QHBoxLayout()
        res_row.addWidget(self._w)
        res_row.addWidget(QLabel("x"))
        res_row.addWidget(self._h)
        res_wrap = QWidget()
        res_wrap.setLayout(res_row)
        grid.addWidget(res_wrap, 4, 1)
        grid.addWidget(QLabel("Extension"), 5, 0)
        grid.addWidget(self._ext, 5, 1)
        layout.addLayout(grid)
        layout.addWidget(self._activate)
        layout.addWidget(self._rename)
        layout.addWidget(self._force_over)
        layout.addWidget(self._loop)
        layout.addWidget(self._hud_enabled)
        layout.addWidget(self._hud_shot)
        layout.addWidget(self._hud_frame)
        layout.addWidget(self._hud_cam)
        layout.addWidget(self._hud_focal)
        layout.addWidget(self._hud_fps)
        layout.addWidget(hud_wrap)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Save).setStyleSheet(STYLE_BTN_PRIMARY)
        box.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(STYLE_BTN)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def result_state(self) -> RenderPreviewState:
        a, b = validate_frame_range(self._start.value(), self._end.value())
        ext = normalize_ext(self._ext.currentText(), "jpg")
        return RenderPreviewState(
            output_root=self._out_root.text().strip(),
            basename=self._basename.text().strip() or "untitled",
            start_frame=a,
            end_frame=b,
            width=int(self._w.value()),
            height=int(self._h.value()),
            ext=ext,
            activate_shot_camera=self._activate.isChecked(),
            rename_to_camera=self._rename.isChecked(),
            loop_playback=self._loop.isChecked(),
            force_shot_overscan_1=self._force_over.isChecked(),
            viewport_hud_enabled=self._hud_enabled.isChecked(),
            viewport_hud_font_size=str(self._hud_font.currentText() or "large").lower().strip(),
            viewport_hud_show_shot=self._hud_shot.isChecked(),
            viewport_hud_show_frame=self._hud_frame.isChecked(),
            viewport_hud_show_camera=self._hud_cam.isChecked(),
            viewport_hud_show_focal_length=self._hud_focal.isChecked(),
            viewport_hud_show_fps=self._hud_fps.isChecked(),
        )


class RenderPreviewMayaUI(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("RenderPreviewMayaWindow")
        self.setWindowTitle(config.WINDOW_TITLE)
        self.setMinimumSize(720, 560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._state = RenderPreviewState()
        self._on_playblast: Optional[Callable[[], None]] = None
        self._on_open_folder: Optional[Callable[[], None]] = None
        self._on_refresh_from_scene: Optional[Callable[[], None]] = None
        self._on_close: Optional[Callable[[], None]] = None
        self._on_persist_settings: Optional[Callable[[], None]] = None

        self._loading = _LoadingOverlay(self)

        font = QFont("Inter", 13)
        font.setWeight(QFont.Weight.Medium)
        self.setFont(font)
        self.setStyleSheet(STYLE_WINDOW + STYLE_INPUT + STYLE_BTN + STYLE_BTN_PRIMARY + STYLE_ICON_BTN)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        lbl = QLabel("Scene path")
        lbl.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        top.addWidget(lbl)
        top.addStretch()
        self._settings_btn = QPushButton("Settings…")
        self._settings_btn.setStyleSheet(STYLE_BTN)
        top.addWidget(self._settings_btn)
        root.addLayout(top)

        self._scene = QLineEdit("")
        self._scene.setReadOnly(True)
        self._scene.setStyleSheet(STYLE_INPUT)
        self._scene.setFont(QFont("JetBrains Mono", 11))
        root.addWidget(self._scene)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(f"color: {TEXT_META}; font-size: 12px;")
        root.addWidget(self._summary)

        btns = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh from scene")
        self._refresh_btn.setStyleSheet(STYLE_BTN)
        self._open_btn = QPushButton("Open Preview Folder")
        self._open_btn.setStyleSheet(STYLE_BTN)
        self._playblast_btn = QPushButton("Playblast")
        self._playblast_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        btns.addWidget(self._refresh_btn)
        btns.addStretch()
        btns.addWidget(self._open_btn)
        btns.addWidget(self._playblast_btn)
        root.addLayout(btns)

        preview_container = QWidget()
        preview_container.setStyleSheet(f"background: {BG_CONTENT}; border: 1px solid #2a2a2c; border-radius: 8px;")
        preview_container.setMinimumHeight(240)
        preview_container_layout = QGridLayout(preview_container)
        preview_container_layout.setContentsMargins(0, 0, 0, 0)
        preview_container.setMouseTracking(True)
        self._preview_container = preview_container

        self._preview = QLabel("No image preview")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet("background: transparent; border: none;")
        self._preview.setMouseTracking(True)
        preview_container_layout.addWidget(self._preview, 0, 0)

        # Middle controls overlay
        middle_controls = QWidget()
        self._middle_controls = middle_controls
        middle_controls.setAutoFillBackground(False)
        middle_controls.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        middle_controls.setStyleSheet("background: rgba(0, 0, 0, 0.18); border: none;")
        middle_controls_layout = QHBoxLayout(middle_controls)
        middle_controls_layout.setContentsMargins(0, 0, 0, 0)
        middle_controls_layout.setSpacing(12)
        middle_controls_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        middle_controls.setMouseTracking(True)

        self._play_btn = QPushButton()
        self._play_btn.setObjectName("RenderPreviewIconButton")
        self._play_btn.setToolTip("Play sequence")
        self._play_btn.setIconSize(QPixmap(22, 22).size())
        self._play_btn.clicked.connect(self._toggle_play)

        self._restart_btn = QPushButton()
        self._restart_btn.setObjectName("RenderPreviewIconButton")
        self._restart_btn.setToolTip("Restart sequence")
        self._restart_btn.setIcon(_load_svg_icon("rotate-ccw.svg", size=22))
        self._restart_btn.setIconSize(QPixmap(22, 22).size())
        self._restart_btn.clicked.connect(self._restart_playback)

        middle_controls_layout.addWidget(self._play_btn)
        middle_controls_layout.addWidget(self._restart_btn)

        preview_container_layout.addWidget(middle_controls, 0, 0, 1, 1)
        middle_controls.setVisible(False)
        root.addWidget(preview_container, 1)

        self._frame_lbl = QLabel("Frame: —")
        self._frame_lbl.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        root.addWidget(self._frame_lbl)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 8px; background: #2a2a2c; border-radius: 4px; }"
            f"QSlider::sub-page:horizontal {{ background: rgba(37,99,235,0.55); border-radius: 4px; }}"
            "QSlider::handle:horizontal { background: #e4e4e7; border: 1px solid #3f3f46; width: 16px; margin: -6px 0; border-radius: 8px; }"
        )
        self._slider.valueChanged.connect(self._on_slider_changed)
        root.addWidget(self._slider)

        # icon-only play/restart lives in the preview overlay

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {TEXT_META}; font-size: 12px;")
        root.addWidget(self._status)

        self._settings_btn.clicked.connect(self._open_settings)
        self._playblast_btn.clicked.connect(lambda: self._on_playblast() if self._on_playblast else None)
        self._open_btn.clicked.connect(lambda: self._on_open_folder() if self._on_open_folder else None)
        self._refresh_btn.clicked.connect(lambda: self._on_refresh_from_scene() if self._on_refresh_from_scene else None)

        # simple non-blocking preview playback (image sequences only)
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // 24)
        self._timer.timeout.connect(self._tick_preview)
        self._playing = False
        self._cur_frame = 0
        self._sync_play_button()

        # Hover-to-show overlay controls
        self._preview_container.installEventFilter(self)
        self._preview.installEventFilter(self)
        self._middle_controls.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj in (getattr(self, "_preview_container", None), getattr(self, "_preview", None), getattr(self, "_middle_controls", None)):
            if event.type() == QEvent.Type.Enter:
                try:
                    self._middle_controls.setVisible(True)
                except Exception:
                    pass
            elif event.type() == QEvent.Type.Leave:
                # Defer: allow moving between children without flicker.
                QTimer.singleShot(0, self._sync_overlay_visibility)
        return super().eventFilter(obj, event)

    def _sync_overlay_visibility(self) -> None:
        try:
            if not hasattr(self, "_preview_container") or not hasattr(self, "_middle_controls"):
                return
            # Hide only when cursor is outside the preview container.
            gp = QCursor.pos()
            lp = self._preview_container.mapFromGlobal(gp)
            inside = self._preview_container.rect().contains(lp)
            self._middle_controls.setVisible(bool(inside))
        except Exception:
            pass

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._loading.setGeometry(self.rect())
        self._rescale_preview()

    def show_loading(self, text: str) -> None:
        self._loading.set_text(text)
        self._loading.setGeometry(self.rect())
        self._loading.setVisible(True)
        self._loading.raise_()
        self._loading.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def show_done(self, text: str, sub_text: str = "Click to continue") -> None:
        self._loading.set_done(text, sub_text)
        self._loading.setGeometry(self.rect())
        self._loading.setVisible(True)
        self._loading.raise_()
        self._loading.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def hide_loading(self) -> None:
        self._loading.setVisible(False)
        self._loading.reset()

    def is_cancelled(self) -> bool:
        return self._loading.cancelled

    def set_callbacks(
        self,
        *,
        on_playblast: Callable[[], None],
        on_open_folder: Callable[[], None],
        on_refresh_from_scene: Callable[[], None],
    ) -> None:
        self._on_playblast = on_playblast
        self._on_open_folder = on_open_folder
        self._on_refresh_from_scene = on_refresh_from_scene

    def set_on_close(self, fn: Optional[Callable[[], None]]) -> None:
        self._on_close = fn

    def set_persist_settings(self, fn: Optional[Callable[[], None]]) -> None:
        """Write current UI state to QSettings (e.g. on Settings Save and window close)."""
        self._on_persist_settings = fn

    def _persist_settings_safe(self) -> None:
        if not self._on_persist_settings:
            return
        try:
            self._on_persist_settings()
        except Exception:
            pass

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._persist_settings_safe()
        if self._on_close:
            try:
                self._on_close()
            except Exception:
                pass
        super().closeEvent(event)

    def set_state(self, state: RenderPreviewState) -> None:
        self._state = state
        self._sync_summary()
        self._sync_slider_range()
        self._set_current_frame(self._state.start_frame, load=True)

    def state(self) -> RenderPreviewState:
        return self._state

    def set_scene_path_display(self, path: str) -> None:
        self._scene.setText(path or "(unsaved scene)")
        self._state.scene_path = path or ""
        self._sync_summary()

    def set_status(self, text: str) -> None:
        self._status.setText(text or "")

    def show_error(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    def show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)

    def _sync_summary(self) -> None:
        s = self._state
        self._summary.setText(
            f"{s.output_root}/{s.basename}/{s.basename}.####.{s.ext}   "
            f"FR {s.start_frame}-{s.end_frame}  Res {s.width}x{s.height}  FPS {s.fps:g}"
        )

    def _sync_slider_range(self) -> None:
        s = self._state
        a, b = validate_frame_range(s.start_frame, s.end_frame)
        self._slider.setMinimum(int(a))
        self._slider.setMaximum(int(b))
        self._slider.setValue(int(a))

    def _open_settings(self) -> None:
        dlg = RenderPreviewMayaSettingsDialog(self, self._state)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # Keep fps/scene_path from current state.
        st = dlg.result_state()
        st.scene_path = self._state.scene_path
        st.fps = float(self._state.fps or 24.0)
        self.set_state(st)
        self._persist_settings_safe()

    def _set_current_frame(self, frame: int, *, load: bool) -> None:
        s = self._state
        self._cur_frame = int(frame)
        self._frame_lbl.setText(f"Frame: {self._cur_frame}")
        if self._slider.value() != self._cur_frame:
            self._slider.blockSignals(True)
            try:
                self._slider.setValue(self._cur_frame)
            finally:
                self._slider.blockSignals(False)

        if not load:
            return

        self._preview.setPixmap(QPixmap())
        self._preview.setProperty("_pixmap_path", "")
        if not is_image_ext(s.ext):
            self._preview.setText("No image preview for movie formats")
            return
        p = frame_file_path(s.output_root, s.basename, self._cur_frame, s.ext)
        pm = QPixmap(p)
        if not pm.isNull():
            self._preview.setProperty("_pixmap_path", p)
            self._rescale_preview()
            self._preview.setText("")
        else:
            self._preview.setText("Image not found")

    def _rescale_preview(self) -> None:
        p = self._preview.property("_pixmap_path")
        if not p:
            return
        pm = QPixmap(str(p))
        if pm.isNull():
            return
        self._preview.setPixmap(
            pm.scaled(
                self._preview.width(),
                self._preview.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _on_slider_changed(self, value: int) -> None:
        self._set_current_frame(int(value), load=True)

    def _toggle_play(self) -> None:
        if self._playing:
            self._stop_playback()
            return
        self._start_playback()

    def _sync_play_button(self) -> None:
        icon_name = "pause.svg" if self._playing else "play.svg"
        tooltip = "Pause sequence" if self._playing else "Play sequence"
        self._play_btn.setIcon(_load_svg_icon(icon_name, size=22))
        self._play_btn.setToolTip(tooltip)

    def _stop_playback(self) -> None:
        self._playing = False
        self._timer.stop()
        self._sync_play_button()

    def _restart_playback(self) -> None:
        self._stop_playback()
        self._set_current_frame(int(self._state.start_frame), load=True)

    def _tick_preview(self) -> None:
        if not self._playing:
            return
        a, b = validate_frame_range(self._state.start_frame, self._state.end_frame)
        nxt = self._cur_frame + 1
        if nxt > b:
            if self._state.loop_playback:
                nxt = a
            else:
                self._stop_playback()
                return
        self._set_current_frame(int(nxt), load=True)

    def _start_playback(self) -> None:
        if self._playing:
            return
        if not is_image_ext(self._state.ext):
            return
        fps = float(self._state.fps or 24.0)
        if fps <= 0:
            fps = 24.0
        self._timer.setInterval(max(1, int(1000.0 / fps)))
        self._playing = True
        self._sync_play_button()
        self._timer.start()

