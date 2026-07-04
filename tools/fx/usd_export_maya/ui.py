"""
USD Publish — Maya tool UI (PySide6, MONOS tokens).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, List, Optional, Set, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QStandardItem, QStandardItemModel
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
    QMenu,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QComboBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tools.fx.usd_export_maya import config
from tools.fx.usd_export_maya.logic import (
    ExportJob,
    list_existing_version_folders,
    next_version_folder_name,
    sanitize_filename_component,
)

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

# Overwrite dropdown: older = amber, newest = green + "(latest)". Real folder in UserRole.
_VERSION_OW_OLD = QColor("#ca8a04")
_VERSION_OW_NEW = QColor("#4ade80")
_VERSION_OW_FOLDER_ROLE = Qt.ItemDataRole.UserRole
_LATEST_LABEL = " (latest)"


def _sync_version_overwrite_combo_chrome(combo: QComboBox) -> None:
    """Closed combo face + popup chrome; list row colors come from the model ForegroundRole."""
    n = combo.count()
    idx = combo.currentIndex()
    if n <= 0 or idx < 0:
        fg = TEXT_PRIMARY
    elif idx == n - 1:
        fg = _VERSION_OW_NEW.name()
    else:
        fg = _VERSION_OW_OLD.name()
    combo.setStyleSheet(
        f"""
        QComboBox {{
            padding: 6px 8px;
            border: 1px solid rgba(39, 39, 42, 0.50);
            border-radius: 6px;
            background: {BG_SURFACE};
            color: {fg};
            font-size: 13px;
        }}
        QComboBox:hover {{ border: 1px solid rgba(63, 63, 70, 0.85); }}
        QComboBox:focus {{ border: 1px solid {BLUE_600}; }}
        QComboBox:disabled {{ color: {TEXT_META}; }}
        QComboBox::drop-down {{ border: none; width: 22px; }}
        QComboBox QAbstractItemView {{
            background: {BG_SURFACE};
            outline: none;
            border: 1px solid #2a2a2c;
            padding: 2px;
        }}
        QComboBox QAbstractItemView::item {{
            padding: 6px 8px;
            min-height: 22px;
        }}
        QComboBox QAbstractItemView::item:selected {{
            background: rgba(37, 99, 235, 0.28);
        }}
        """
    )


def _populate_version_overwrite_combo(combo: QComboBox, folders: List[str]) -> None:
    model = QStandardItemModel(combo)
    n = len(folders)
    for i, raw in enumerate(folders):
        disp = f"{raw}{_LATEST_LABEL}" if n and i == n - 1 else raw
        item = QStandardItem(disp)
        item.setData(raw, _VERSION_OW_FOLDER_ROLE)
        item.setForeground(_VERSION_OW_NEW if (n and i == n - 1) else _VERSION_OW_OLD)
        model.appendRow(item)
    combo.setModel(model)
    _sync_version_overwrite_combo_chrome(combo)


def _version_overwrite_combo_select_folder(combo: QComboBox, folder: str) -> None:
    want = (folder or "").strip()
    if not want:
        return
    for i in range(combo.count()):
        d = combo.itemData(i, _VERSION_OW_FOLDER_ROLE)
        if d is not None and str(d).strip() == want:
            combo.setCurrentIndex(i)
            _sync_version_overwrite_combo_chrome(combo)
            return


def _version_overwrite_combo_folder_value(combo: QComboBox) -> str:
    i = combo.currentIndex()
    if i < 0:
        return ""
    d = combo.itemData(i, _VERSION_OW_FOLDER_ROLE)
    if d is not None:
        s = str(d).strip()
        if s:
            return s
    return (combo.currentText() or "").replace(_LATEST_LABEL, "").strip()


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
    """Settings grouped into tabs: Path / USD Config / Rules+Keywords."""

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
        export_subdivide: bool,
        export_normals: bool,
        export_uvs: bool,
        export_anim: bool,
        export_scale: float,
        usd_options_raw: str,
        rules_override_json: str,
        geometry_include_non_reference: bool = True,
        existing_version_folders: Optional[List[str]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("USD Publish — Settings")
        self.setMinimumWidth(560)
        self.setStyleSheet(STYLE_WINDOW + STYLE_INPUT + STYLE_BTN + STYLE_BTN_PRIMARY)
        self._auto = auto_publish

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # --- Tab 1: Path ---
        tab_path = QWidget()
        path_layout = QVBoxLayout(tab_path)
        path_layout.setSpacing(10)

        self._lock_pub = QCheckBox("Lock publish root (do not auto-update from scene path)")
        self._lock_pub.setChecked(publish_locked)
        self._lock_pub.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        self._lock_pub.toggled.connect(self._on_lock_toggled)
        path_layout.addWidget(self._lock_pub)

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

        path_layout.addLayout(grid)

        ver_row = QHBoxLayout()
        ver_lbl = QLabel("Publish version")
        ver_lbl.setStyleSheet(f"color: {TEXT_LABEL};")
        self._ver_mode = QComboBox()
        self._ver_mode.addItems(["Auto (next)", "Manual", "Overwrite (existing)"])
        self._ver_mode.setStyleSheet(STYLE_INPUT)
        self._ver_num = QDoubleSpinBox()
        self._ver_num.setDecimals(0)
        self._ver_num.setRange(1, 999)
        self._ver_num.setValue(1)
        self._ver_num.setSingleStep(1)
        self._ver_num.setStyleSheet(STYLE_INPUT)
        self._ver_num.setToolTip("Publish into v### (manual)")
        self._ver_overwrite = QComboBox()
        self._ver_overwrite.setMinimumWidth(140)
        self._ver_overwrite.setToolTip("Existing v### folder under publish root")
        _populate_version_overwrite_combo(self._ver_overwrite, list(existing_version_folders or []))
        ver_row.addWidget(ver_lbl)
        ver_row.addWidget(self._ver_mode, 1)
        self._ver_v_lbl = QLabel("v")
        ver_row.addWidget(self._ver_v_lbl)
        ver_row.addWidget(self._ver_num)
        ver_row.addWidget(self._ver_overwrite)
        ver_row.addStretch()
        path_layout.addLayout(ver_row)
        self._ver_mode.currentIndexChanged.connect(self._on_settings_ver_mode_changed)
        self._ver_overwrite.currentIndexChanged.connect(
            lambda _i: _sync_version_overwrite_combo_chrome(self._ver_overwrite)
        )
        self._on_settings_ver_mode_changed(self._ver_mode.currentIndex())

        hint = QLabel(
            "When publish is not locked, the publish root comes from the main window "
            "(output path preset + scene path). Lock here to use a fixed folder."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {TEXT_META}; font-size: 11px;")
        path_layout.addWidget(hint)

        tabs.addTab(tab_path, "Path")

        # --- Tab 2: USD Config ---
        tab_usd = QWidget()
        usd_layout = QVBoxLayout(tab_usd)
        usd_layout.setSpacing(10)

        self._export_uvs = QCheckBox("Export UVs")
        self._export_uvs.setChecked(export_uvs)
        self._export_uvs.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        usd_layout.addWidget(self._export_uvs)

        self._export_anim = QCheckBox("Export animation (use playback range)")
        self._export_anim.setChecked(export_anim)
        self._export_anim.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        usd_layout.addWidget(self._export_anim)

        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("Scale"))
        self._scale = QDoubleSpinBox()
        self._scale.setRange(0.0001, 1000.0)
        self._scale.setValue(float(export_scale))
        self._scale.setSingleStep(0.1)
        self._scale.setStyleSheet(STYLE_INPUT)
        scale_row.addWidget(self._scale)
        scale_row.addStretch()
        usd_layout.addLayout(scale_row)

        self._renderable_check = QCheckBox("Cameras: require renderable (shape.renderable must be on)")
        self._renderable_check.setChecked(camera_require_renderable)
        self._renderable_check.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        usd_layout.addWidget(self._renderable_check)

        self._skip_hidden = QCheckBox("Skip hidden objects (Outliner visibility)")
        self._skip_hidden.setChecked(skip_hidden_outliner)
        self._skip_hidden.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        usd_layout.addWidget(self._skip_hidden)

        self._geo_include_native = QCheckBox(
            "Geometry rule: include native scene roots (Geometry / GEO / … not from reference)"
        )
        self._geo_include_native.setChecked(geometry_include_non_reference)
        self._geo_include_native.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        self._geo_include_native.setToolTip(
            "When on (default), ref_geometry also finds transforms in the open scene that are not "
            "from a file reference. When off, only referenced rigs (namespace:Geometry, …)."
        )
        usd_layout.addWidget(self._geo_include_native)

        self._subdivide = QCheckBox("Export Subdivide (defaultMeshScheme=catmullClark)")
        self._subdivide.setChecked(export_subdivide)
        self._subdivide.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        usd_layout.addWidget(self._subdivide)

        self._normals = QCheckBox("Export Normals")
        self._normals.setChecked(export_normals)
        self._normals.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        usd_layout.addWidget(self._normals)

        raw_lbl = QLabel("Raw USD Export options (optional; paste from Maya UI). If set, it will be used as-is.")
        raw_lbl.setWordWrap(True)
        raw_lbl.setStyleSheet(f"color: {TEXT_META}; font-size: 11px;")
        usd_layout.addWidget(raw_lbl)

        self._raw = QPlainTextEdit()
        self._raw.setPlainText(usd_options_raw or "")
        self._raw.setStyleSheet(f"background: {BG_CONTENT}; color: {TEXT_PRIMARY}; border: 1px solid #2a2a2c;")
        self._raw.setMinimumHeight(140)
        usd_layout.addWidget(self._raw)

        tabs.addTab(tab_usd, "USD Config")

        # --- Tab 3: Rules / Keywords ---
        tab_rules = QWidget()
        rules_layout = QVBoxLayout(tab_rules)
        rules_layout.setSpacing(10)

        kw_hint = QLabel(
            "Rule list (defaults shown). You can add/edit/remove rules here, "
            "and Reset Default to restore shipped rules."
        )
        kw_hint.setWordWrap(True)
        kw_hint.setStyleSheet(f"color: {TEXT_META}; font-size: 11px;")
        rules_layout.addWidget(kw_hint)

        self._rules_override_json = (rules_override_json or "").strip()
        self._rules_list = QListWidget()
        self._rules_list.setObjectName("SelectableList")
        self._rules_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._rules_list.setStyleSheet(
            "QListWidget#SelectableList { background-color: #0d0d0f; border: none; outline: none; padding: 5px; }"
            "QListWidget#SelectableList::item { background: transparent; color: #888888; padding: 8px 12px; margin-bottom: 2px; border-radius: 6px; font-size: 13px; font-weight: 500; border-left: 3px solid transparent; }"
            "QListWidget#SelectableList::item:hover { background-color: rgba(255,255,255,0.03); color: #eeeeee; }"
            "QListWidget#SelectableList::item:selected { background-color: rgba(37,99,235,0.10); color: #2563eb; border-left: 3px solid #2563eb; font-weight: 700; }"
        )
        rules_layout.addWidget(self._rules_list, 1)

        btn_row = QHBoxLayout()
        self._rule_add = QPushButton("Add")
        self._rule_add.setObjectName("DialogSecondaryButton")
        self._rule_add.setStyleSheet(STYLE_BTN)
        self._rule_edit = QPushButton("Edit")
        self._rule_edit.setObjectName("DialogSecondaryButton")
        self._rule_edit.setStyleSheet(STYLE_BTN)
        self._rule_remove = QPushButton("Remove")
        self._rule_remove.setObjectName("DialogSecondaryButton")
        self._rule_remove.setStyleSheet(STYLE_BTN)
        self._rule_reset = QPushButton("Reset Default")
        self._rule_reset.setObjectName("DialogSecondaryButton")
        self._rule_reset.setStyleSheet(STYLE_BTN)
        btn_row.addWidget(self._rule_add)
        btn_row.addWidget(self._rule_edit)
        btn_row.addWidget(self._rule_remove)
        btn_row.addStretch()
        btn_row.addWidget(self._rule_reset)
        rules_layout.addLayout(btn_row)

        self._rule_add.clicked.connect(self._on_rule_add)
        self._rule_edit.clicked.connect(self._on_rule_edit)
        self._rule_remove.clicked.connect(self._on_rule_remove)
        self._rule_reset.clicked.connect(self._on_rule_reset)

        self._load_rules_into_list()
        tabs.addTab(tab_rules, "Rules/Keywords")

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

    def set_publish_version(self, mode: str, number: int, overwrite_folder: str = "") -> None:
        m = (mode or "auto").strip().lower()
        self._ver_mode.blockSignals(True)
        if m == "manual":
            self._ver_mode.setCurrentIndex(1)
        elif m == "overwrite":
            self._ver_mode.setCurrentIndex(2)
        else:
            self._ver_mode.setCurrentIndex(0)
        self._ver_mode.blockSignals(False)
        try:
            n = int(number)
        except Exception:
            n = 1
        n = max(1, min(999, n))
        self._ver_num.setValue(float(n))
        ow = (overwrite_folder or "").strip()
        if ow:
            _version_overwrite_combo_select_folder(self._ver_overwrite, ow)
        elif self._ver_overwrite.count() > 0:
            self._ver_overwrite.setCurrentIndex(self._ver_overwrite.count() - 1)
        _sync_version_overwrite_combo_chrome(self._ver_overwrite)
        self._on_settings_ver_mode_changed(self._ver_mode.currentIndex())

    def _on_settings_ver_mode_changed(self, _idx: int) -> None:
        i = int(self._ver_mode.currentIndex())
        manual = i == 1
        ow = i == 2
        self._ver_num.setEnabled(manual)
        self._ver_v_lbl.setVisible(not ow)
        self._ver_num.setVisible(not ow)
        self._ver_overwrite.setVisible(ow)
        self._ver_overwrite.setEnabled(ow)

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

    def result_geometry_include_non_reference(self) -> bool:
        return self._geo_include_native.isChecked()

    def result_export_subdivide(self) -> bool:
        return self._subdivide.isChecked()

    def result_export_normals(self) -> bool:
        return self._normals.isChecked()

    def result_export_uvs(self) -> bool:
        return self._export_uvs.isChecked()

    def result_export_anim(self) -> bool:
        return self._export_anim.isChecked()

    def result_export_scale(self) -> float:
        return float(self._scale.value())

    def result_usd_options_raw(self) -> str:
        return self._raw.toPlainText().strip()

    def result_rules_override_json(self) -> str:
        return self._rules_override_json

    def result_publish_version_mode(self) -> str:
        i = int(self._ver_mode.currentIndex())
        if i == 1:
            return "manual"
        if i == 2:
            return "overwrite"
        return "auto"

    def result_publish_version_number(self) -> int:
        try:
            return int(self._ver_num.value())
        except Exception:
            return 1

    def result_publish_version_folder(self) -> str:
        return _version_overwrite_combo_folder_value(self._ver_overwrite)

    # --- Rule list helpers ---
    def _shipped_default_rules_json(self) -> str:
        try:
            from pathlib import Path
            p = Path(config.default_rules_path())
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except Exception:
            pass
        return ""

    def _effective_rules_json(self) -> str:
        return self._rules_override_json or self._shipped_default_rules_json()

    def _load_rules_into_list(self) -> None:
        import json as _json
        self._rules_list.clear()
        raw = self._effective_rules_json()
        try:
            data = _json.loads(raw) if raw else {"rules": []}
            rules = data.get("rules") or []
        except Exception:
            rules = []
        for idx, r in enumerate(rules):
            rid = str(r.get("id") or f"rule_{idx}")
            m = r.get("match") or {}
            mtype = str(m.get("type") or "")
            enabled = bool(r.get("enabled", True))
            fn = r.get("filename") or {}
            prefix = str(fn.get("prefix") or "")
            label = f"{'✓' if enabled else '·'} {rid}  ({mtype})  prefix={prefix}"
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, idx)
            self._rules_list.addItem(it)

    def _selected_rule_index(self) -> Optional[int]:
        it = self._rules_list.currentItem()
        if not it:
            return None
        v = it.data(Qt.ItemDataRole.UserRole)
        try:
            return int(v)
        except Exception:
            return None

    def _edit_rule_dialog(self, rule: dict) -> Optional[dict]:
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Rule")
        dlg.setStyleSheet(STYLE_WINDOW + STYLE_INPUT + STYLE_BTN + STYLE_BTN_PRIMARY)
        lay = QVBoxLayout(dlg)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        enabled_cb = QCheckBox("Enabled")
        enabled_cb.setChecked(bool(rule.get("enabled", True)))
        enabled_cb.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        grid.addWidget(enabled_cb, 0, 0, 1, 2)

        grid.addWidget(QLabel("ID"), 1, 0)
        rid = QLineEdit(str(rule.get("id") or ""))
        rid.setStyleSheet(STYLE_INPUT)
        grid.addWidget(rid, 1, 1)

        grid.addWidget(QLabel("Match type"), 2, 0)
        mt = QComboBox()
        mt.addItems(["camera", "ref_geometry", "transform_regex"])
        m = rule.get("match") or {}
        cur = str(m.get("type") or "camera")
        i = mt.findText(cur)
        if i >= 0:
            mt.setCurrentIndex(i)
        mt.setStyleSheet(STYLE_INPUT)
        grid.addWidget(mt, 2, 1)

        grid.addWidget(QLabel("leaf_regex"), 3, 0)
        leaf = QLineEdit(str((rule.get("match") or {}).get("leaf_regex") or ""))
        leaf.setStyleSheet(STYLE_INPUT)
        grid.addWidget(leaf, 3, 1)

        grid.addWidget(QLabel("path_regex"), 4, 0)
        path = QLineEdit(str((rule.get("match") or {}).get("path_regex") or ""))
        path.setStyleSheet(STYLE_INPUT)
        grid.addWidget(path, 4, 1)

        grid.addWidget(QLabel("filename prefix"), 5, 0)
        pref = QLineEdit(str((rule.get("filename") or {}).get("prefix") or ""))
        pref.setStyleSheet(STYLE_INPUT)
        grid.addWidget(pref, 5, 1)

        grid.addWidget(QLabel("name_from"), 6, 0)
        nf = QComboBox()
        nf.addItems(["leaf", "namespace"])
        cur_nf = str((rule.get("filename") or {}).get("name_from") or "leaf")
        j = nf.findText(cur_nf)
        if j >= 0:
            nf.setCurrentIndex(j)
        nf.setStyleSheet(STYLE_INPUT)
        grid.addWidget(nf, 6, 1)

        # Preview
        preview_lbl = QLabel("USD name preview")
        preview_lbl.setStyleSheet(f"color: {TEXT_LABEL};")
        preview_val = QLineEdit()
        preview_val.setReadOnly(True)
        preview_val.setStyleSheet(STYLE_INPUT)
        preview_val.setFont(QFont("JetBrains Mono", 10))
        grid.addWidget(preview_lbl, 7, 0)
        grid.addWidget(preview_val, 7, 1)

        def _sync_preview() -> None:
            p = pref.text().strip()
            src = nf.currentText().strip()
            # keep the preview explicit about the source for clarity
            body = "<leafName>" if src == "leaf" else "<namespace>"
            preview_val.setText(f"{p}{body}.usd")

        pref.textChanged.connect(_sync_preview)
        nf.currentTextChanged.connect(lambda _t: _sync_preview())
        _sync_preview()

        lay.addLayout(grid)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Save).setStyleSheet(STYLE_BTN_PRIMARY)
        box.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(STYLE_BTN)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None

        out = {
            "id": rid.text().strip(),
            "enabled": enabled_cb.isChecked(),
            "match": {"type": mt.currentText().strip()},
            "filename": {"prefix": pref.text().strip(), "name_from": nf.currentText().strip()},
        }
        if leaf.text().strip():
            out["match"]["leaf_regex"] = leaf.text().strip()
        if path.text().strip():
            out["match"]["path_regex"] = path.text().strip()
        return out

    def _get_rules_list_data(self) -> list[dict]:
        import json as _json
        raw = self._effective_rules_json()
        try:
            data = _json.loads(raw) if raw else {"rules": []}
            rules = data.get("rules") or []
            return list(rules)
        except Exception:
            return []

    def _set_rules_override_from_list(self, rules: list[dict]) -> None:
        import json as _json
        self._rules_override_json = _json.dumps({"version": 1, "rules": rules}, indent=2, ensure_ascii=False)
        self._load_rules_into_list()

    def _on_rule_add(self) -> None:
        rules = self._get_rules_list_data()
        edited = self._edit_rule_dialog({"id": "", "enabled": True, "match": {"type": "camera"}, "filename": {"prefix": "cam_", "name_from": "leaf"}})
        if edited is None:
            return
        rules.append(edited)
        self._set_rules_override_from_list(rules)

    def _on_rule_edit(self) -> None:
        idx = self._selected_rule_index()
        if idx is None:
            return
        rules = self._get_rules_list_data()
        if idx < 0 or idx >= len(rules):
            return
        edited = self._edit_rule_dialog(dict(rules[idx]))
        if edited is None:
            return
        rules[idx] = edited
        self._set_rules_override_from_list(rules)

    def _on_rule_remove(self) -> None:
        idx = self._selected_rule_index()
        if idx is None:
            return
        rules = self._get_rules_list_data()
        if idx < 0 or idx >= len(rules):
            return
        rules.pop(idx)
        self._set_rules_override_from_list(rules)

    def _on_rule_reset(self) -> None:
        self._rules_override_json = ""
        self._load_rules_into_list()


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
        self._geometry_include_non_reference = True
        self._export_subdivide = False
        self._export_normals = False
        self._export_uvs = True
        self._export_anim = True
        self._export_scale = 1.0
        self._usd_options_raw = ""
        self._rules_override_json = ""
        self._publish_version_mode = "auto"
        self._publish_version_number = 1
        self._restore_overwrite_folder: str = ""
        self._output_path_preset = "anim"  # anim | uv | custom
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

        path_bar = QHBoxLayout()
        _opl = QLabel("Output path")
        _opl.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        path_bar.addWidget(_opl)
        self._path_preset_main = QComboBox()
        self._path_preset_main.addItems(["Anim publish", "UV publish", "Custom"])
        self._path_preset_main.setStyleSheet(STYLE_INPUT)
        self._path_preset_main.setToolTip("Where publish root is resolved from the current scene path")
        path_bar.addWidget(self._path_preset_main, 1)
        path_bar.addStretch()
        self._settings_btn = QPushButton("Settings…")
        self._settings_btn.setObjectName("DialogSecondaryButton")
        self._settings_btn.setStyleSheet(STYLE_BTN)
        self._settings_btn.setToolTip("Rules, USD options, lock publish folder")
        path_bar.addWidget(self._settings_btn)
        root.addLayout(path_bar)

        prev_lbl = QLabel("Publish path preview")
        prev_lbl.setStyleSheet(f"color: {TEXT_LABEL}; font-size: 12px;")
        root.addWidget(prev_lbl)
        self._publish_preview = QLineEdit("")
        self._publish_preview.setReadOnly(True)
        self._publish_preview.setStyleSheet(STYLE_INPUT)
        mono = QFont("JetBrains Mono", 11)
        self._publish_preview.setFont(mono)
        root.addWidget(self._publish_preview)
        self._publish_preview.editingFinished.connect(self._on_publish_preview_edited)

        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("Version"))
        self._ver_mode_main = QComboBox()
        self._ver_mode_main.addItems(["Auto (next)", "Manual", "Overwrite"])
        self._ver_mode_main.setStyleSheet(STYLE_INPUT)
        self._ver_v_label_main = QLabel("v")
        self._ver_num_main = QSpinBox()
        self._ver_num_main.setRange(1, 999)
        self._ver_num_main.setValue(1)
        self._ver_num_main.setStyleSheet(STYLE_INPUT)
        self._ver_num_main.setEnabled(False)
        self._ver_overwrite_main = QComboBox()
        self._ver_overwrite_main.setMinimumWidth(140)
        self._ver_overwrite_main.setToolTip("Existing v### folder under publish root (scan)")
        ver_row.addWidget(self._ver_mode_main)
        ver_row.addWidget(self._ver_v_label_main)
        ver_row.addWidget(self._ver_num_main)
        ver_row.addWidget(self._ver_overwrite_main)
        ver_row.addStretch()
        root.addLayout(ver_row)

        self._auto_name_scene = QCheckBox("Auto-name USD files from scene filename")
        self._auto_name_scene.setChecked(False)
        self._auto_name_scene.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        self._auto_name_scene.setToolTip(
            "Single target: basename = scene file stem (no extension). "
            "Multiple targets: {sceneStem}_{ruleBasename}."
        )
        self._auto_name_scene.stateChanged.connect(lambda _s: self._emit_rescan())
        root.addWidget(self._auto_name_scene)

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
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)
        self._table.itemChanged.connect(self._on_table_item_changed)
        self._table.setColumnWidth(0, 56)
        self._table.setColumnWidth(1, 140)
        self._table.setColumnWidth(2, 260)
        self._table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._table, 1)

        bottom = QHBoxLayout()
        self._open_publish_btn = QPushButton("Open Publish Folder")
        self._open_publish_btn.setObjectName("DialogSecondaryButton")
        self._open_publish_btn.setStyleSheet(STYLE_BTN)
        self._publish_run_btn = QPushButton("Publish")
        self._publish_run_btn.setObjectName("DialogPrimaryButton")
        self._publish_run_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        bottom.addStretch()
        bottom.addWidget(self._open_publish_btn)
        bottom.addWidget(self._publish_run_btn)
        root.addLayout(bottom)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {TEXT_META}; font-size: 12px;")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._on_rescan: Optional[Callable[[], None]] = None
        self._on_publish: Optional[Callable[[], None]] = None
        self._on_open_publish_folder: Optional[Callable[[], None]] = None
        self._on_version_hint: Optional[Callable[[], None]] = None
        self._on_output_preset_changed: Optional[Callable[[], None]] = None

        self._rescan_btn.clicked.connect(self._emit_rescan)
        self._publish_run_btn.clicked.connect(self._emit_publish)
        self._open_publish_btn.clicked.connect(self._emit_open_publish_folder)
        self._settings_btn.clicked.connect(self._open_settings)
        self._path_preset_main.currentIndexChanged.connect(self._on_main_path_preset_changed)
        self._ver_mode_main.currentIndexChanged.connect(self._on_main_version_mode_changed)
        self._ver_num_main.valueChanged.connect(lambda _v: self._emit_version_hint())
        self._ver_overwrite_main.currentIndexChanged.connect(self._on_overwrite_main_index_changed)
        _sync_version_overwrite_combo_chrome(self._ver_overwrite_main)
        self._apply_main_version_widgets()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._loading.setGeometry(self.rect())

    def set_callbacks(
        self,
        on_rescan: Callable[[], None],
        on_publish: Callable[[], None],
        on_open_publish_folder: Optional[Callable[[], None]] = None,
        on_version_hint: Optional[Callable[[], None]] = None,
        on_output_preset_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_rescan = on_rescan
        self._on_publish = on_publish
        self._on_open_publish_folder = on_open_publish_folder
        self._on_version_hint = on_version_hint
        self._on_output_preset_changed = on_output_preset_changed

    def _emit_rescan(self) -> None:
        if self._on_rescan:
            self._on_rescan()

    def _emit_publish(self) -> None:
        if self._on_publish:
            self._on_publish()

    def _emit_open_publish_folder(self) -> None:
        if self._on_open_publish_folder:
            self._on_open_publish_folder()

    def _emit_version_hint(self) -> None:
        if self._on_version_hint:
            self._on_version_hint()

    def _on_overwrite_main_index_changed(self, _idx: int) -> None:
        _sync_version_overwrite_combo_chrome(self._ver_overwrite_main)
        self._emit_version_hint()

    def _suggest_current_version_number(self) -> int:
        root = self.get_publish_root().strip()
        if not root:
            return 1
        try:
            vname = next_version_folder_name(root)  # e.g. v003
            return max(1, int(vname.lstrip("vV")))
        except Exception:
            return 1

    def _on_main_path_preset_changed(self, _idx: int) -> None:
        i = int(self._path_preset_main.currentIndex())
        self._output_path_preset = "uv" if i == 1 else "custom" if i == 2 else "anim"
        self._publish_preview.setReadOnly(self._output_path_preset != "custom")
        if self._on_output_preset_changed:
            self._on_output_preset_changed()

    def _on_main_version_mode_changed(self, _idx: int) -> None:
        i = int(self._ver_mode_main.currentIndex())
        manual = i == 1
        ow = i == 2
        self._ver_v_label_main.setVisible(not ow)
        self._ver_num_main.setVisible(not ow)
        self._ver_overwrite_main.setVisible(ow)
        self._ver_num_main.setEnabled(manual)
        self._ver_overwrite_main.setEnabled(ow)
        if manual:
            self._ver_num_main.setValue(self._suggest_current_version_number())
        elif not ow:
            self._ver_num_main.blockSignals(True)
            self._ver_num_main.setValue(self._suggest_current_version_number())
            self._ver_num_main.blockSignals(False)
        self._emit_version_hint()

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
            export_subdivide=self._export_subdivide,
            export_normals=self._export_normals,
            export_uvs=self._export_uvs,
            export_anim=self._export_anim,
            export_scale=self._export_scale,
            usd_options_raw=self._usd_options_raw,
            rules_override_json=self._rules_override_json,
            geometry_include_non_reference=self._geometry_include_non_reference,
            existing_version_folders=list_existing_version_folders(self.get_publish_root()),
        )
        dlg.set_publish_version(
            self.get_publish_version_mode(),
            self.get_publish_version_number(),
            self.get_publish_version_overwrite_folder(),
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
        self._geometry_include_non_reference = dlg.result_geometry_include_non_reference()
        self._export_subdivide = dlg.result_export_subdivide()
        self._export_normals = dlg.result_export_normals()
        self._export_uvs = dlg.result_export_uvs()
        self._export_anim = dlg.result_export_anim()
        self._export_scale = dlg.result_export_scale()
        self._usd_options_raw = dlg.result_usd_options_raw()
        self._rules_override_json = dlg.result_rules_override_json()
        self.set_publish_version(
            dlg.result_publish_version_mode(),
            dlg.result_publish_version_number(),
            dlg.result_publish_version_folder(),
        )
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

    def set_publish_path_preview(self, path: str) -> None:
        self._publish_preview.setText(path or "—")
        self._publish_preview.setReadOnly(self.get_output_path_preset() != "custom")

    def _on_publish_preview_edited(self) -> None:
        # Only allow editing in custom mode.
        if self.get_output_path_preset() != "custom":
            self._publish_preview.setReadOnly(True)
            return
        import os as _os
        import re as _re

        raw = (self._publish_preview.text() or "").strip()
        if not raw or raw == "—":
            return
        norm = _os.path.normpath(raw)
        base = _os.path.basename(norm).strip()
        m = _re.match(r"^v(\d{3})$", base, _re.I)
        if m:
            # User typed a full .../publish/v### path.
            self.set_publish_root(_os.path.dirname(norm))
            self.set_publish_version("manual", int(m.group(1)))
        else:
            # Treat it as publish root (no version).
            self.set_publish_root(norm)
        self._emit_version_hint()

    def set_output_path_preset(self, preset: str) -> None:
        p = (preset or "anim").strip().lower()
        if p not in ("anim", "uv", "custom"):
            p = "anim"
        self._output_path_preset = p
        self._path_preset_main.blockSignals(True)
        self._path_preset_main.setCurrentIndex(0 if p == "anim" else 1 if p == "uv" else 2)
        self._path_preset_main.blockSignals(False)
        self._publish_preview.setReadOnly(p != "custom")

    def get_output_path_preset(self) -> str:
        return str(self._output_path_preset or "anim").strip().lower()

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

    # Back-compat: controller used to drive a label; now it drives the preview field.
    def set_next_version_label(self, text: str) -> None:
        self.set_publish_path_preview(text)

    def set_publish_version(self, mode: str, number: int, overwrite_folder: str = "") -> None:
        self._publish_version_mode = (mode or "auto").strip().lower()
        try:
            self._publish_version_number = int(number)
        except Exception:
            self._publish_version_number = 1
        self._publish_version_number = max(1, min(999, self._publish_version_number))
        ow_name = (overwrite_folder or "").strip()
        self._restore_overwrite_folder = ow_name
        m = self._publish_version_mode
        self._ver_mode_main.blockSignals(True)
        if m == "manual":
            self._ver_mode_main.setCurrentIndex(1)
        elif m == "overwrite":
            self._ver_mode_main.setCurrentIndex(2)
        else:
            self._ver_mode_main.setCurrentIndex(0)
        self._ver_mode_main.blockSignals(False)
        self._ver_num_main.blockSignals(True)
        if m == "manual":
            self._ver_num_main.setValue(self._publish_version_number)
        else:
            self._ver_num_main.setValue(self._suggest_current_version_number())
        self._ver_num_main.blockSignals(False)
        self._apply_main_version_widgets()

    def set_version_overwrite_options(self, folders: List[str]) -> None:
        prev = (self._restore_overwrite_folder or self.get_publish_version_overwrite_folder()).strip()
        self._ver_overwrite_main.blockSignals(True)
        _populate_version_overwrite_combo(self._ver_overwrite_main, folders)
        if prev:
            _version_overwrite_combo_select_folder(self._ver_overwrite_main, prev)
        elif self._ver_overwrite_main.count() > 0:
            self._ver_overwrite_main.setCurrentIndex(self._ver_overwrite_main.count() - 1)
        self._ver_overwrite_main.blockSignals(False)
        _sync_version_overwrite_combo_chrome(self._ver_overwrite_main)
        if self._ver_overwrite_main.count() > 0:
            self._restore_overwrite_folder = ""

    def _apply_main_version_widgets(self) -> None:
        i = int(self._ver_mode_main.currentIndex())
        manual = i == 1
        ow = i == 2
        self._ver_v_label_main.setVisible(not ow)
        self._ver_num_main.setVisible(not ow)
        self._ver_overwrite_main.setVisible(ow)
        self._ver_num_main.setEnabled(manual)
        self._ver_overwrite_main.setEnabled(ow)

    def update_auto_version_spin(self, version_num: int) -> None:
        """When mode is Auto, show the computed next v### number in the spinbox (read-only)."""
        if self.get_publish_version_mode() != "auto":
            return
        try:
            n = int(version_num)
        except Exception:
            n = 1
        n = max(1, min(999, n))
        self._ver_num_main.blockSignals(True)
        self._ver_num_main.setValue(n)
        self._ver_num_main.blockSignals(False)

    def get_publish_version_mode(self) -> str:
        i = int(self._ver_mode_main.currentIndex())
        if i == 1:
            return "manual"
        if i == 2:
            return "overwrite"
        return "auto"

    def get_publish_version_number(self) -> int:
        return int(self._ver_num_main.value())

    def get_publish_version_overwrite_folder(self) -> str:
        return _version_overwrite_combo_folder_value(self._ver_overwrite_main)

    def get_export_uvs(self) -> bool:
        return bool(self._export_uvs)

    def set_export_uvs(self, value: bool) -> None:
        self._export_uvs = bool(value)

    def get_export_anim(self) -> bool:
        return bool(self._export_anim)

    def set_export_anim(self, value: bool) -> None:
        self._export_anim = bool(value)

    def get_scale(self) -> float:
        return float(self._export_scale)

    def set_scale(self, value: float) -> None:
        self._export_scale = float(value)

    def get_camera_require_renderable(self) -> bool:
        return self._camera_require_renderable

    def set_camera_require_renderable(self, value: bool) -> None:
        self._camera_require_renderable = bool(value)

    def get_skip_hidden_outliner(self) -> bool:
        return bool(self._skip_hidden_outliner)

    def set_skip_hidden_outliner(self, value: bool) -> None:
        self._skip_hidden_outliner = bool(value)

    def get_geometry_include_non_reference(self) -> bool:
        return bool(self._geometry_include_non_reference)

    def set_geometry_include_non_reference(self, value: bool) -> None:
        self._geometry_include_non_reference = bool(value)

    def get_auto_name_from_scene(self) -> bool:
        return self._auto_name_scene.isChecked()

    def set_auto_name_from_scene(self, value: bool) -> None:
        self._auto_name_scene.blockSignals(True)
        self._auto_name_scene.setChecked(bool(value))
        self._auto_name_scene.blockSignals(False)

    def get_export_subdivide(self) -> bool:
        return bool(self._export_subdivide)

    def set_export_subdivide(self, value: bool) -> None:
        self._export_subdivide = bool(value)

    def get_export_normals(self) -> bool:
        return bool(self._export_normals)

    def set_export_normals(self, value: bool) -> None:
        self._export_normals = bool(value)

    def get_usd_options_raw(self) -> str:
        return str(self._usd_options_raw or "").strip()

    def set_usd_options_raw(self, value: str) -> None:
        self._usd_options_raw = str(value or "")

    def get_rules_override_json(self) -> str:
        return str(self._rules_override_json or "").strip()

    def set_rules_override_json(self, value: str) -> None:
        self._rules_override_json = str(value or "")

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    @staticmethod
    def _job_row_key(job: ExportJob) -> Tuple[str, str]:
        return (job.dag_path, job.rule_id)

    def _checked_job_keys(self) -> Set[Tuple[str, str]]:
        s: Set[Tuple[str, str]] = set()
        for row in range(self._table.rowCount()):
            it = self._table.item(row, 0)
            if it and it.checkState() == Qt.CheckState.Checked and row < len(self._jobs):
                s.add(self._job_row_key(self._jobs[row]))
        return s

    def _selected_job_keys(self) -> Set[Tuple[str, str]]:
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        s: Set[Tuple[str, str]] = set()
        for row in rows:
            if 0 <= row < len(self._jobs):
                s.add(self._job_row_key(self._jobs[row]))
        return s

    def _selected_table_rows(self) -> List[int]:
        return sorted({idx.row() for idx in self._table.selectedIndexes()})

    def _restore_row_selection_for_keys(self, keys: Set[Tuple[str, str]]) -> None:
        if not keys:
            return
        self._table.clearSelection()
        for row in range(self._table.rowCount()):
            if row >= len(self._jobs):
                continue
            if self._job_row_key(self._jobs[row]) in keys:
                self._table.selectRow(row)

    def _on_table_context_menu(self, pos) -> None:
        menu = QMenu(self)
        act_only = QAction("Check selected only", self)
        act_only.triggered.connect(self._ctx_check_selected_only)
        menu.addAction(act_only)
        menu.addSeparator()
        act_all = QAction("Check all", self)
        act_all.triggered.connect(self._ctx_check_all)
        menu.addAction(act_all)
        act_usel = QAction("Uncheck selected", self)
        act_usel.triggered.connect(self._ctx_uncheck_selected)
        menu.addAction(act_usel)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _ctx_check_selected_only(self) -> None:
        rows = set(self._selected_table_rows())
        if not rows:
            return
        self._table.blockSignals(True)
        for r in range(self._table.rowCount()):
            it = self._table.item(r, 0)
            if it:
                it.setCheckState(
                    Qt.CheckState.Checked if r in rows else Qt.CheckState.Unchecked
                )
        self._table.blockSignals(False)

    def _ctx_check_all(self) -> None:
        self._table.blockSignals(True)
        for r in range(self._table.rowCount()):
            it = self._table.item(r, 0)
            if it:
                it.setCheckState(Qt.CheckState.Checked)
        self._table.blockSignals(False)

    def _ctx_uncheck_selected(self) -> None:
        rows = set(self._selected_table_rows())
        if not rows:
            return
        self._table.blockSignals(True)
        for r in rows:
            it = self._table.item(r, 0)
            if it:
                it.setCheckState(Qt.CheckState.Unchecked)
        self._table.blockSignals(False)

    def _basename_from_table_cell(self, text: str) -> str:
        s = (text or "").strip()
        if s.lower().endswith(".usd"):
            s = s[:-4].strip()
        return sanitize_filename_component(s)

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 3:
            return
        row = item.row()
        if row < 0 or row >= len(self._jobs):
            return
        cleaned = self._basename_from_table_cell(item.text())
        if cleaned != item.text():
            self._table.blockSignals(True)
            item.setText(cleaned)
            self._table.blockSignals(False)
        self._jobs[row] = replace(self._jobs[row], output_basename=cleaned)

    def set_jobs(self, jobs: List[ExportJob]) -> None:
        prior_checked: Optional[Set[Tuple[str, str]]] = None
        prior_selected: Optional[Set[Tuple[str, str]]] = None
        if self._table.rowCount() > 0 and self._jobs:
            prior_checked = self._checked_job_keys()
            prior_selected = self._selected_job_keys()

        self._jobs = list(jobs)
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        for job in jobs:
            r = self._table.rowCount()
            self._table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            key = self._job_row_key(job)
            if prior_checked is None:
                check_on = True
            else:
                check_on = key in prior_checked
            chk.setCheckState(
                Qt.CheckState.Checked if check_on else Qt.CheckState.Unchecked
            )
            self._table.setItem(r, 0, chk)
            rule_it = QTableWidgetItem(job.rule_id)
            rule_it.setFlags(ro)
            self._table.setItem(r, 1, rule_it)
            dag_item = QTableWidgetItem(job.dag_path)
            dag_item.setFlags(ro)
            fmono = QFont("JetBrains Mono", 10)
            dag_item.setFont(fmono)
            self._table.setItem(r, 2, dag_item)
            name_it = QTableWidgetItem(job.output_basename)
            name_it.setFlags(
                ro
                | Qt.ItemFlag.ItemIsEditable
            )
            name_it.setFont(fmono)
            self._table.setItem(r, 3, name_it)
        self._table.blockSignals(False)
        if prior_selected is not None:
            self._restore_row_selection_for_keys(prior_selected)

    def checked_jobs(self) -> List[ExportJob]:
        out: List[ExportJob] = []
        for row in range(self._table.rowCount()):
            it = self._table.item(row, 0)
            if it and it.checkState() == Qt.CheckState.Checked and row < len(self._jobs):
                j = self._jobs[row]
                name_it = self._table.item(row, 3)
                base = (
                    self._basename_from_table_cell(name_it.text())
                    if name_it
                    else j.output_basename
                )
                out.append(replace(j, output_basename=base))
        return out

    def show_error(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    def show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)
