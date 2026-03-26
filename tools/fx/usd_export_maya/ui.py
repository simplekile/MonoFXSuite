"""
USD Publish — Maya tool UI (PySide6, MONOS tokens).
"""

from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tools.fx.usd_export_maya import config
from tools.fx.usd_export_maya.logic import ExportJob

BG_PANEL = "#18181b"
BG_CONTENT = "#121214"
BG_SURFACE = "#27272a"
TEXT_PRIMARY = "#fafafa"
TEXT_LABEL = "#a1a1aa"
TEXT_META = "#71717a"
BLUE_600 = "#2563eb"

STYLE_WINDOW = f"""
    QWidget#UsdExportMayaWindow {{
        background-color: {BG_PANEL};
        color: {TEXT_PRIMARY};
    }}
"""

STYLE_INPUT = f"""
    QLineEdit {{
        padding: 6px 8px;
        border: 1px solid rgba(39, 39, 42, 0.50);
        border-radius: 6px;
        background: {BG_SURFACE};
        color: {TEXT_PRIMARY};
        font-size: 13px;
    }}
    QLineEdit:focus {{ border: 1px solid {BLUE_600}; }}
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


# ---------------------------------------------------------------------------
# Loading overlay (matching auto_material)
# ---------------------------------------------------------------------------

class _LoadingOverlay(QWidget):
    """Semi-transparent overlay with centered status text.
    Modes: loading (Esc to cancel), done (click to dismiss)."""

    _MODE_LOADING = 0
    _MODE_DONE = 1

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._text = "Loading..."
        self._sub_text: Optional[str] = None
        self._mode = self._MODE_LOADING
        self._cancelled = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setVisible(False)

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
        if self._mode == self._MODE_DONE:
            painter.fillRect(self.rect(), QColor(16, 185, 129, 80))  # emerald-500 (soft)
        else:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 180))

        painter.setPen(QColor(TEXT_PRIMARY))
        main_font = QFont("Inter", 13, QFont.Weight.DemiBold)
        painter.setFont(main_font)
        painter.drawText(
            self.rect().adjusted(0, -20, 0, 0),
            Qt.AlignmentFlag.AlignCenter,
            self._text,
        )

        if self._sub_text:
            color = QColor("#ef4444") if self._mode == self._MODE_LOADING else QColor(TEXT_META)
            painter.setPen(color)
            sub_font = QFont("Inter", 10, QFont.Weight.Normal)
            painter.setFont(sub_font)
            painter.drawText(
                self.rect().adjusted(0, 40, 0, 0),
                Qt.AlignmentFlag.AlignCenter,
                self._sub_text,
            )

        painter.end()

    def cancel(self) -> None:
        if self._mode != self._MODE_LOADING or self._cancelled:
            return
        self._cancelled = True
        self._text = "Cancelling..."
        self._sub_text = None
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        # Only allow click to dismiss when done.
        if self._mode == self._MODE_DONE:
            self.reset()
            self.setVisible(False)
            event.accept()
            return
        event.ignore()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape and self._mode == self._MODE_LOADING:
            self.cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.raise_()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)


class UsdExportMayaSettingsDialog(QDialog):
    """Publish root, rules JSON, camera renderable filter."""

    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        auto_publish: str,
        publish_manual: str,
        publish_locked: bool,
        rules_path: str,
        camera_require_renderable: bool,
        skip_hidden_outliner: bool,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("USD Publish — Settings")
        self.setMinimumWidth(560)
        self.setStyleSheet(STYLE_WINDOW + STYLE_INPUT + STYLE_BTN + STYLE_BTN_PRIMARY)
        self._auto = auto_publish

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self._lock_pub = QCheckBox("Lock publish root (do not auto-update from scene path)")
        self._lock_pub.setChecked(publish_locked)
        self._lock_pub.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        self._lock_pub.toggled.connect(self._on_lock_toggled)
        layout.addWidget(self._lock_pub)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        pl = QLabel("Publish root")
        pl.setStyleSheet(f"color: {TEXT_LABEL};")
        self._pub = QLineEdit(publish_manual if publish_locked else auto_publish)
        self._pub.setStyleSheet(STYLE_INPUT)
        self._pub_browse = QPushButton("Browse…")
        self._pub_browse.setObjectName("DialogSecondaryButton")
        self._pub_browse.setStyleSheet(STYLE_BTN)
        self._pub_browse.clicked.connect(self._browse_publish)
        grid.addWidget(pl, 0, 0)
        grid.addWidget(self._pub, 0, 1)
        grid.addWidget(self._pub_browse, 0, 2)

        rl = QLabel("Rules file")
        rl.setStyleSheet(f"color: {TEXT_LABEL};")
        self._rules = QLineEdit(rules_path)
        self._rules.setStyleSheet(STYLE_INPUT)
        rules_browse = QPushButton("Browse…")
        rules_browse.setObjectName("DialogSecondaryButton")
        rules_browse.setStyleSheet(STYLE_BTN)
        rules_browse.clicked.connect(self._browse_rules)
        grid.addWidget(rl, 1, 0)
        grid.addWidget(self._rules, 1, 1)
        grid.addWidget(rules_browse, 1, 2)

        layout.addLayout(grid)

        self._renderable_check = QCheckBox(
            "Cameras: require renderable (shape.renderable must be on)"
        )
        self._renderable_check.setChecked(camera_require_renderable)
        self._renderable_check.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        layout.addWidget(self._renderable_check)

        self._skip_hidden = QCheckBox("Skip hidden objects (Outliner visibility)")
        self._skip_hidden.setChecked(skip_hidden_outliner)
        self._skip_hidden.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        layout.addWidget(self._skip_hidden)

        hint = QLabel(
            "When publish is not locked, the folder is taken from the current scene path "
            "(e.g. …/maya/work/ → …/<task>/publish) and updates on Open/New scene."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {TEXT_META}; font-size: 11px;")
        layout.addWidget(hint)

        self._on_lock_toggled(self._lock_pub.isChecked())

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = box.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setObjectName("DialogPrimaryButton")
        save_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        save_btn.setText("Save")
        cancel_btn = box.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setObjectName("DialogSecondaryButton")
        cancel_btn.setStyleSheet(STYLE_BTN)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _on_lock_toggled(self, locked: bool) -> None:
        self._pub.setEnabled(locked)
        self._pub_browse.setEnabled(locked)
        if not locked:
            self._pub.setText(self._auto)

    def _browse_publish(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Publish root", self._pub.text() or "")
        if d:
            self._pub.setText(d)

    def _browse_rules(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Rules JSON",
            self._rules.text() or "",
            "JSON (*.json);;All (*.*)",
        )
        if path:
            self._rules.setText(path)

    def result_publish_root(self) -> str:
        if not self._lock_pub.isChecked():
            return ""
        return self._pub.text().strip()

    def result_rules_path(self) -> str:
        return self._rules.text().strip()

    def result_camera_require_renderable(self) -> bool:
        return self._renderable_check.isChecked()

    def result_publish_locked(self) -> bool:
        return self._lock_pub.isChecked()

    def result_skip_hidden_outliner(self) -> bool:
        return self._skip_hidden.isChecked()


class UsdExportMayaUI(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("UsdExportMayaWindow")
        self.setWindowTitle(config.WINDOW_TITLE)
        self.setMinimumSize(720, 520)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._jobs: List[ExportJob] = []
        self._camera_require_renderable = False
        self._publish_root = ""
        self._rules_path = ""
        self._publish_locked = False
        self._skip_hidden_outliner = True
        self._get_auto_publish: Optional[Callable[[], str]] = None
        self._on_close: Optional[Callable[[], None]] = None
        self._loading = _LoadingOverlay(self)

        font = QFont("Inter", 13)
        font.setWeight(QFont.Weight.Medium)
        self.setFont(font)

        self.setStyleSheet(STYLE_WINDOW + STYLE_TABLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        scene_row = QHBoxLayout()
        scene_lbl = QLabel("Scene path")
        scene_lbl.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        scene_row.addWidget(scene_lbl)
        scene_row.addStretch()
        self._settings_btn = QPushButton("Settings…")
        self._settings_btn.setObjectName("DialogSecondaryButton")
        self._settings_btn.setStyleSheet(STYLE_BTN)
        self._settings_btn.setToolTip("Publish folder, rules JSON, camera options")
        scene_row.addWidget(self._settings_btn)
        root.addLayout(scene_row)

        self._scene_path = QLineEdit("")
        self._scene_path.setReadOnly(True)
        self._scene_path.setStyleSheet(STYLE_INPUT)
        mono = QFont("JetBrains Mono", 11)
        self._scene_path.setFont(mono)
        root.addWidget(self._scene_path)

        self._ver_label = QLabel("Next folder: —")
        self._ver_label.setStyleSheet(f"color: {TEXT_META}; font-size: 12px;")
        root.addWidget(self._ver_label)

        opts = QHBoxLayout()
        self._uv_check = QCheckBox("Export UVs")
        self._uv_check.setChecked(True)
        self._uv_check.setStyleSheet(f"color: {TEXT_PRIMARY};")
        self._anim_check = QCheckBox("Export animation")
        self._anim_check.setChecked(True)
        self._anim_check.setStyleSheet(f"color: {TEXT_PRIMARY};")
        opts.addWidget(self._uv_check)
        opts.addWidget(self._anim_check)
        opts.addWidget(QLabel("Scale"))
        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(0.0001, 1000.0)
        self._scale_spin.setValue(1.0)
        self._scale_spin.setSingleStep(0.1)
        self._scale_spin.setStyleSheet(STYLE_INPUT)
        opts.addWidget(self._scale_spin)
        opts.addStretch()
        root.addLayout(opts)

        row_btns = QHBoxLayout()
        self._rescan_btn = QPushButton("Rescan scene")
        self._rescan_btn.setObjectName("DialogSecondaryButton")
        self._rescan_btn.setStyleSheet(STYLE_BTN)
        row_btns.addWidget(self._rescan_btn)
        row_btns.addStretch()
        root.addLayout(row_btns)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Export", "Rule", "DAG", "USD name"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setColumnWidth(0, 56)
        self._table.setColumnWidth(1, 140)
        self._table.setColumnWidth(2, 260)
        self._table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._table, 1)

        bottom = QHBoxLayout()
        self._publish_run_btn = QPushButton("Publish")
        self._publish_run_btn.setObjectName("DialogPrimaryButton")
        self._publish_run_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        bottom.addStretch()
        bottom.addWidget(self._publish_run_btn)
        root.addLayout(bottom)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {TEXT_META}; font-size: 12px;")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._on_rescan: Optional[Callable[[], None]] = None
        self._on_publish: Optional[Callable[[], None]] = None
        self._on_version_hint: Optional[Callable[[], None]] = None

        self._rescan_btn.clicked.connect(self._emit_rescan)
        self._publish_run_btn.clicked.connect(self._emit_publish)
        self._settings_btn.clicked.connect(self._open_settings)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._loading.setGeometry(self.rect())

    def set_callbacks(
        self,
        on_rescan: Callable[[], None],
        on_publish: Callable[[], None],
        on_version_hint: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_rescan = on_rescan
        self._on_publish = on_publish
        self._on_version_hint = on_version_hint

    def _emit_rescan(self) -> None:
        if self._on_rescan:
            self._on_rescan()

    def _emit_publish(self) -> None:
        if self._on_publish:
            self._on_publish()

    def _emit_version_hint(self) -> None:
        if self._on_version_hint:
            self._on_version_hint()

    def set_auto_publish_supplier(self, fn: Callable[[], str]) -> None:
        self._get_auto_publish = fn

    def set_on_close(self, fn: Optional[Callable[[], None]]) -> None:
        self._on_close = fn

    def _open_settings(self) -> None:
        auto = self._get_auto_publish() if self._get_auto_publish else ""
        dlg = UsdExportMayaSettingsDialog(
            self,
            auto_publish=auto,
            publish_manual=self.get_publish_root(),
            publish_locked=self._publish_locked,
            rules_path=self.get_rules_path(),
            camera_require_renderable=self._camera_require_renderable,
            skip_hidden_outliner=self._skip_hidden_outliner,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._publish_locked = dlg.result_publish_locked()
        if self._publish_locked:
            self.set_publish_root(dlg.result_publish_root())
        elif self._get_auto_publish:
            self.set_publish_root(self._get_auto_publish())
        else:
            self.set_publish_root("")
        self.set_rules_path(dlg.result_rules_path())
        self._camera_require_renderable = dlg.result_camera_require_renderable()
        self._skip_hidden_outliner = dlg.result_skip_hidden_outliner()
        self._emit_version_hint()
        self._emit_rescan()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._on_close:
            try:
                self._on_close()
            except Exception:
                pass
        super().closeEvent(event)

    def show_loading(self, text: str = "Loading...") -> None:
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

    def set_scene_path_display(self, path: str) -> None:
        self._scene_path.setText(path or "(unsaved scene)")

    def set_publish_root(self, path: str) -> None:
        self._publish_root = (path or "").strip()

    def get_publish_root(self) -> str:
        return self._publish_root

    def set_rules_path(self, path: str) -> None:
        self._rules_path = (path or "").strip()

    def get_rules_path(self) -> str:
        return self._rules_path

    def set_publish_locked(self, locked: bool) -> None:
        self._publish_locked = bool(locked)

    def get_publish_locked(self) -> bool:
        return self._publish_locked

    def set_next_version_label(self, text: str) -> None:
        self._ver_label.setText(text)

    def get_export_uvs(self) -> bool:
        return self._uv_check.isChecked()

    def get_export_anim(self) -> bool:
        return self._anim_check.isChecked()

    def get_scale(self) -> float:
        return float(self._scale_spin.value())

    def get_camera_require_renderable(self) -> bool:
        return self._camera_require_renderable

    def set_camera_require_renderable(self, value: bool) -> None:
        self._camera_require_renderable = bool(value)

    def get_skip_hidden_outliner(self) -> bool:
        return bool(self._skip_hidden_outliner)

    def set_skip_hidden_outliner(self, value: bool) -> None:
        self._skip_hidden_outliner = bool(value)

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_jobs(self, jobs: List[ExportJob]) -> None:
        self._jobs = list(jobs)
        self._table.setRowCount(0)
        for job in jobs:
            r = self._table.rowCount()
            self._table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            chk.setCheckState(Qt.CheckState.Checked)
            self._table.setItem(r, 0, chk)
            self._table.setItem(r, 1, QTableWidgetItem(job.rule_id))
            dag_item = QTableWidgetItem(job.dag_path)
            fmono = QFont("JetBrains Mono", 10)
            dag_item.setFont(fmono)
            self._table.setItem(r, 2, dag_item)
            self._table.setItem(r, 3, QTableWidgetItem(job.output_basename))

    def checked_jobs(self) -> List[ExportJob]:
        out: List[ExportJob] = []
        for row in range(self._table.rowCount()):
            it = self._table.item(row, 0)
            if it and it.checkState() == Qt.CheckState.Checked and row < len(self._jobs):
                out.append(self._jobs[row])
        return out

    def show_error(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    def show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)
